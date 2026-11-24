"""Module 8 (server side) - offline synchronisation, idempotency, "never trust an unverified scan"."""
from helpers import approved_visitor, iso_in

DEVICE = "phone-test-0001"


def op(op_id, kind, token, hours_ago=0.2):
    return {"operation_id": op_id, "type": kind, "token": token, "scanned_at": iso_in(-hours_ago)}


def sync(guard, operations, **extra):
    return guard.post("/api/sync", dict({"device_id": DEVICE, "operations": operations}, **extra))


class TestOfflineSync:
    def test_queued_check_in_and_check_out_are_verified_and_applied(self, app, anon, host1, guard1, tokens):
        pid, text = approved_visitor(app, anon, host1, tokens)
        r = sync(guard1, [op("op-aaaa0001", "check-in", text, 0.3), op("op-aaaa0002", "check-out", text, 0.1)])
        assert r.status_code == 200, r.get_json()
        data = r.get_json()["data"]
        assert [x["status"] for x in data["results"]] == ["success", "success"]
        assert data["summary"] == {"total": 2, "success": 2, "failed": 0, "replayed": 0}
        from app.models import VisitLog
        with app.app_context():
            visit = VisitLog.query.one()
            assert visit.source == "offline_sync"                       # recorded as coming from the queue
            assert visit.check_out_at >= visit.check_in_at

    def test_the_visit_keeps_the_time_of_the_scan_not_the_time_of_the_upload(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        sync(guard1, [op("op-aaaa0003", "check-in", text, hours_ago=3)])
        from datetime import timedelta
        from app.models import VisitLog
        from app.utils.helpers import utcnow
        with app.app_context():
            age = utcnow() - VisitLog.query.one().check_in_at
            assert timedelta(hours=2.9) < age < timedelta(hours=3.1)

    def test_duplicate_sync_request_creates_no_duplicate_visit(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        batch = [op("op-bbbb0001", "check-in", text)]
        first = sync(guard1, batch).get_json()["data"]
        second = sync(guard1, batch).get_json()["data"]                 # the phone retried after a timeout
        assert first["results"][0]["status"] == "success" and first["results"][0]["replayed"] is False
        assert second["results"][0]["status"] == "success" and second["results"][0]["replayed"] is True
        assert second["summary"]["replayed"] == 1
        from app.models import SyncOperation, VisitLog
        with app.app_context():
            assert VisitLog.query.count() == 1
            assert SyncOperation.query.count() == 1

    def test_invalid_qr_is_reported_as_failed_never_as_an_entry(self, app, guard1):
        r = sync(guard1, [op("op-cccc0001", "check-in", "SMARTCONNECT:v1:" + "C" * 43)])
        result = r.get_json()["data"]["results"][0]
        assert result["status"] == "failed" and result["result"]["code"] == "invalid"
        from app.models import VisitLog
        with app.app_context():
            assert VisitLog.query.count() == 0

    def test_unapproved_visitor_scanned_offline_stays_refused(self, app, anon, guard1, tokens):
        from helpers import register
        register(app, anon)
        r = sync(guard1, [op("op-cccc0002", "check-in", tokens.latest)])
        result = r.get_json()["data"]["results"][0]
        assert result["status"] == "failed" and result["result"]["code"] == "pending_approval"

    def test_expired_pass_scanned_offline_is_rejected_on_sync(self, app, anon, host1, guard1, tokens):
        from test_visitors_and_qr import expire_all_passes
        _, text = approved_visitor(app, anon, host1, tokens)
        expire_all_passes(app)
        # The scan happened "now" (after the pass expired), so the server refuses it.
        result = sync(guard1, [op("op-cccc0003", "check-in", text, 0)]).get_json()["data"]["results"][0]
        assert result["status"] == "failed" and result["result"]["code"] == "expired"

    def test_very_old_offline_scans_are_not_trusted(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        result = sync(guard1, [op("op-cccc0004", "check-in", text, hours_ago=72)]).get_json()["data"]["results"][0]
        assert result["status"] == "failed" and result["result"]["code"] == "stale"

    def test_a_scan_from_the_future_is_clamped_to_now(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        future = {"operation_id": "op-cccc0005", "type": "check-in", "token": text, "scanned_at": iso_in(5)}
        assert sync(guard1, [future]).get_json()["data"]["results"][0]["status"] == "success"
        from app.models import VisitLog
        from app.utils.helpers import utcnow
        with app.app_context():
            assert VisitLog.query.one().check_in_at <= utcnow()

    def test_a_bad_operation_does_not_stop_the_rest_of_the_batch(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        batch = [{"operation_id": "x", "type": "check-in", "token": text},
                 {"operation_id": "op-dddd0002", "type": "explode", "token": text},
                 op("op-dddd0003", "check-in", text)]
        data = sync(guard1, batch).get_json()["data"]
        statuses = sorted(r["status"] for r in data["results"])
        assert statuses == ["error", "error", "success"]
        codes = {r["result"]["code"] for r in data["results"] if r["status"] == "error"}
        assert codes == {"bad_operation_id", "bad_type"}

    def test_operations_run_in_the_order_they_happened(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        # Sent in the wrong order on purpose: check-out first in the list, but it happened later.
        batch = [op("op-eeee0002", "check-out", text, 0.1), op("op-eeee0001", "check-in", text, 0.3)]
        data = sync(guard1, batch).get_json()["data"]
        assert data["summary"]["success"] == 2

    def test_another_guard_cannot_claim_an_existing_operation_id(self, app, anon, host1, guard1, guard2, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        sync(guard1, [op("op-ffff0001", "check-in", text)])
        result = sync(guard2, [op("op-ffff0001", "check-in", text)]).get_json()["data"]["results"][0]
        assert result["status"] == "error" and result["result"]["code"] == "operation_conflict"

    def test_request_validation(self, guard1, anon):
        assert guard1.post("/api/sync", {"operations": []}).status_code == 400
        assert guard1.post("/api/sync", {"operations": "nope"}).status_code == 400
        assert guard1.post("/api/sync", {"operations": ["x"]}).status_code == 400
        too_many = [{"operation_id": f"op-{i:08d}", "type": "check-in", "token": "x"} for i in range(101)]
        assert guard1.post("/api/sync", {"operations": too_many}).status_code == 413
        assert anon.post("/api/sync", json={"operations": [{}]}).status_code == 401

    def test_server_stores_only_token_hashes(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        sync(guard1, [op("op-gggg0001", "check-in", text)])
        from app.models import SyncOperation
        with app.app_context():
            row = SyncOperation.query.one()
            dump = " ".join(str(getattr(row, c.name)) for c in SyncOperation.__table__.columns)
            assert tokens.all[-1] not in dump
            assert len(row.token_hash) == 64 and row.status == "SUCCESS" and row.channel == "sync"

    def test_sync_states_are_visible_to_admin(self, app, anon, host1, admin, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        sync(guard1, [op("op-hhhh0001", "check-in", text),
                      op("op-hhhh0002", "check-in", "SMARTCONNECT:v1:" + "D" * 43)])
        status = admin.get("/api/network/status").get_json()["data"]["sync"]
        assert status["success"] == 1 and status["failed"] == 1 and status["pending"] == 0
        assert status["last_sync_at"]
        ops = admin.get("/api/sync/operations").get_json()["data"]["items"]
        assert {o["operation_id"] for o in ops} == {"op-hhhh0001", "op-hhhh0002"}
        assert "token" not in str(ops).lower().replace("token_hash", "")


class TestServerDisconnection:
    """What the SERVER can prove about outages; the browser half is checked in test_static_assets.py."""

    def test_health_endpoint_reports_a_broken_database(self, anon, monkeypatch):
        from app.extensions import db

        def boom(*_a, **_k):
            raise RuntimeError("database down")

        assert anon.get("/health").get_json()["status"] == "ok"
        monkeypatch.setattr(db.session, "execute", boom)
        r = anon.get("/health")
        assert r.status_code == 503 and r.get_json()["status"] == "degraded"

    def test_unexpected_errors_become_clean_json_not_stack_traces(self, anon, monkeypatch):
        from app.routes import dashboard

        monkeypatch.setattr(dashboard.stats_service, "dashboard_stats",
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret internal detail")))
        # unauthenticated -> 401 first; log in as admin to reach the broken code path
        from helpers import Staff
        admin = Staff(anon.application, "admin", "admin", "Admin@123")
        r = admin.get("/api/dashboard/stats")
        assert r.status_code == 500
        body = r.get_json()
        assert body["ok"] is False and body["error"]["code"] == "server_error"
        assert "secret internal detail" not in r.get_data(as_text=True)

    def test_unknown_api_route_returns_json_404(self, anon):
        r = anon.get("/api/does-not-exist")
        assert r.status_code == 404 and r.get_json()["ok"] is False
