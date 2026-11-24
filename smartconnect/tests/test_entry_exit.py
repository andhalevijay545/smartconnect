"""Modules 5 and 11 - check-in, check-out, duplicate protection, gates, visitor history."""
from helpers import approved_visitor, register
from test_visitors_and_qr import expire_all_passes


class TestCheckIn:
    def test_successful_check_in_records_time_and_gate(self, app, anon, host1, guard1, tokens):
        pid, text = approved_visitor(app, anon, host1, tokens)
        r = guard1.post("/api/visitors/check-in", {"token": text})
        assert r.status_code == 200, r.get_json()
        data = r.get_json()["data"]
        assert data["ok"] and data["code"] == "checked_in"
        assert data["visit"]["check_in_gate"] == "Main Gate"         # guard1 is assigned to Main Gate
        assert data["visit"]["check_in_at"].endswith("Z")
        assert data["visitor"]["status"] == "INSIDE"

    def test_each_guard_records_their_own_gate(self, app, anon, host1, guard2, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        data = guard2.post("/api/visitors/check-in", {"token": text}).get_json()["data"]
        assert data["visit"]["check_in_gate"] == "Gate 2"

    def test_duplicate_check_in_is_refused(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        assert guard1.post("/api/visitors/check-in", {"token": text}).status_code == 200
        again = guard1.post("/api/visitors/check-in", {"token": text})
        assert again.status_code == 409
        assert again.get_json()["error"]["code"] == "already_used"
        from app.models import VisitLog
        with app.app_context():
            assert VisitLog.query.count() == 1                     # no second visit was created

    def test_a_reused_qr_cannot_enter_through_another_gate_either(self, app, anon, host1, guard1, guard2, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        assert guard1.post("/api/visitors/check-in", {"token": text}).status_code == 200
        assert guard2.post("/api/visitors/check-in", {"token": text}).status_code == 409

    def test_invalid_qr_is_not_found(self, guard1):
        r = guard1.post("/api/visitors/check-in", {"token": "SMARTCONNECT:v1:" + "B" * 43})
        assert r.status_code == 404 and r.get_json()["error"]["code"] == "invalid"

    def test_unapproved_and_rejected_visitors_cannot_enter(self, app, anon, host1, guard1, tokens):
        from helpers import approve
        data = register(app, anon)
        text = tokens.latest
        r = guard1.post("/api/visitors/check-in", {"token": text})
        assert r.status_code == 409 and r.get_json()["error"]["code"] == "pending_approval"
        approve(host1, data["visitor"]["public_id"], "reject")
        r = guard1.post("/api/visitors/check-in", {"token": text})
        assert r.status_code == 403 and r.get_json()["error"]["code"] == "rejected"

    def test_token_is_required(self, guard1):
        assert guard1.post("/api/visitors/check-in", {}).status_code == 400
        assert guard1.post("/api/visitors/check-in", {"token": ""}).status_code == 400

    def test_guard_without_a_gate_must_name_one(self, app, anon, host1, admin, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        from helpers import ids
        admin.patch(f"/api/admin/users/security/{guard1.user['id']}", {"gate_id": None})
        r = guard1.post("/api/visitors/check-in", {"token": text})
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "no_gate"
        r = guard1.post("/api/visitors/check-in", {"token": text, "gate_id": ids(app)["gate2"]})
        assert r.status_code == 200
        assert r.get_json()["data"]["visit"]["check_in_gate"] == "Gate 2"


class TestCheckOut:
    def test_successful_check_out(self, app, anon, host1, guard1, guard2, tokens):
        pid, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        r = guard2.post("/api/visitors/check-out", {"token": text})        # leaves through another gate
        assert r.status_code == 200, r.get_json()
        data = r.get_json()["data"]
        assert data["code"] == "checked_out"
        assert data["visit"]["check_in_gate"] == "Main Gate" and data["visit"]["check_out_gate"] == "Gate 2"
        assert data["visit"]["check_out_at"] >= data["visit"]["check_in_at"]
        assert data["visitor"]["status"] == "COMPLETED"

    def test_cannot_check_out_before_checking_in(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        r = guard1.post("/api/visitors/check-out", {"token": text})
        assert r.status_code == 409 and r.get_json()["error"]["code"] == "not_checked_in"

    def test_cannot_check_out_twice(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        assert guard1.post("/api/visitors/check-out", {"token": text}).status_code == 200
        again = guard1.post("/api/visitors/check-out", {"token": text})
        assert again.status_code == 409 and again.get_json()["error"]["code"] == "already_used"

    def test_a_visitor_who_is_inside_can_leave_even_after_the_pass_expired(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        expire_all_passes(app)
        assert guard1.post("/api/visitors/check-out", {"token": text}).status_code == 200

    def test_visit_history_is_kept(self, app, anon, host1, guard1, tokens):
        pid, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        guard1.post("/api/visitors/check-out", {"token": text})
        detail = host1.get(f"/api/visitors/{pid}").get_json()["data"]["visitor"]
        assert len(detail["visits"]) == 1
        assert detail["visits"][0]["check_out_at"] is not None
        assert detail["pass"]["state"] == "used"


class TestIdempotentScan:
    def test_same_operation_id_is_applied_only_once(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        body = {"token": text, "operation_id": "op-test-0001"}
        first = guard1.post("/api/visitors/check-in", body)
        again = guard1.post("/api/visitors/check-in", body)                # e.g. the response was lost
        assert first.status_code == again.status_code == 200
        assert first.get_json()["data"]["replayed"] is False
        assert again.get_json()["data"]["replayed"] is True
        from app.models import VisitLog
        with app.app_context():
            assert VisitLog.query.count() == 1

    def test_bad_operation_id(self, guard1):
        r = guard1.post("/api/visitors/check-in", {"token": "x" * 43, "operation_id": "!"})
        assert r.status_code == 400


class TestGates:
    def test_admin_manages_gates_and_staff_assignment(self, app, admin, guard1):
        created = admin.post("/api/gates", {"name": "Loading Bay", "location": "Rear"})
        assert created.status_code == 201
        gate_id = created.get_json()["data"]["gate"]["id"]
        assert admin.post("/api/gates", {"name": "Loading Bay"}).status_code == 409   # unique names
        assert admin.patch(f"/api/gates/{gate_id}", {"location": "Back road"}).status_code == 200
        r = admin.patch(f"/api/admin/users/security/{guard1.user['id']}", {"gate_id": gate_id})
        assert r.status_code == 200 and r.get_json()["data"]["user"]["gate_name"] == "Loading Bay"
        assert any(g["name"] == "Loading Bay" for g in guard1.get("/api/gates").get_json()["data"]["items"])

    def test_disabled_gate_cannot_be_used(self, app, anon, host1, admin, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        main = next(g for g in admin.get("/api/gates").get_json()["data"]["items"] if g["name"] == "Main Gate")
        admin.patch(f"/api/gates/{main['id']}", {"is_active": False})
        r = guard1.post("/api/visitors/check-in", {"token": text})
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_gate"

    def test_gate_wise_statistics(self, app, anon, host1, admin, guard1, guard2, tokens):
        _, t1 = approved_visitor(app, anon, host1, tokens)
        _, t2 = approved_visitor(app, anon, host1, tokens, full_name="Ravi Kumar",
                                 mobile="9123456780", email="ravi@example.com")
        guard1.post("/api/visitors/check-in", {"token": t1})
        guard2.post("/api/visitors/check-in", {"token": t2})
        guard2.post("/api/visitors/check-out", {"token": t2})
        rows = {r["name"]: r for r in admin.get("/api/gates/stats").get_json()["data"]["items"]}
        assert rows["Main Gate"]["check_ins_today"] == 1 and rows["Main Gate"]["inside_now"] == 1
        assert rows["Gate 2"]["check_ins_today"] == 1 and rows["Gate 2"]["check_outs_today"] == 1
        assert rows["Reception Desk"]["check_ins_today"] == 0
