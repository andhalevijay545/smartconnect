"""Modules 2, 3, 4, 10 - registration, dynamic QR codes, verification, host approval."""
from helpers import approve, approved_visitor, iso_in, register, visitor_payload, ids


def expire_all_passes(app):
    """Move every pass's expiry into the past (simulates time passing)."""
    from datetime import timedelta

    from app.extensions import db
    from app.models import QRPass
    from app.utils.helpers import utcnow
    with app.app_context():
        for qp in QRPass.query.all():
            qp.expires_at = utcnow() - timedelta(hours=1)
        db.session.commit()


class TestRegistration:
    def test_successful_registration(self, app, anon):
        data = register(app, anon)
        v = data["visitor"]
        assert v["status"] == "PENDING"
        assert v["full_name"] == "Asha Patil"
        assert len(v["public_id"]) == 32                       # random, not a guessable 1,2,3
        assert data["access_key"]
        assert data["qr"]["image"].startswith("data:image/png;base64,")
        assert data["qr"]["expires_at"].endswith("Z")

    def test_registration_creates_a_pending_approval_for_the_chosen_host(self, app, anon, host1, host2):
        register(app, anon)
        assert len(host1.get("/api/approvals?status=PENDING").get_json()["data"]["items"]) == 1
        assert host2.get("/api/approvals?status=PENDING").get_json()["data"]["items"] == []

    def test_invalid_information_is_rejected_field_by_field(self, app, anon):
        bad = visitor_payload(app, full_name="R2D2", mobile="123", email="not-an-email",
                              address="x", purpose="", expected_at="yesterday-ish")
        r = anon.post("/api/visitors/register", json=bad)
        assert r.status_code == 422
        details = r.get_json()["error"]["details"]
        assert {"full_name", "mobile", "email", "address", "purpose", "expected_at"} <= set(details)

    def test_past_visit_time_is_rejected(self, app, anon):
        r = anon.post("/api/visitors/register", json=visitor_payload(app, expected_at=iso_in(-24)))
        assert r.status_code == 422 and "expected_at" in r.get_json()["error"]["details"]

    def test_host_must_belong_to_the_department(self, app, anon):
        i = ids(app)
        r = anon.post("/api/visitors/register",
                      json=visitor_payload(app, department_id=i["dept_hr"], host_id=i["host1"]))
        assert r.status_code == 422 and "host_id" in r.get_json()["error"]["details"]

    def test_unknown_department_and_host(self, app, anon):
        r = anon.post("/api/visitors/register", json=visitor_payload(app, department_id=9999, host_id=9999))
        assert r.status_code == 422

    def test_empty_and_malformed_bodies(self, anon):
        assert anon.post("/api/visitors/register", json={}).status_code == 422
        assert anon.post("/api/visitors/register", data="garbage").status_code == 422

    def test_public_lookup_list_hides_staff_contact_details(self, anon):
        data = anon.get("/api/lookups").get_json()["data"]
        assert len(data["departments"]) >= 5 and len(data["hosts"]) >= 3
        blob = str(data)
        assert "@example.com" not in blob and "password" not in blob.lower()

    def test_registration_is_rate_limited(self, app, anon):
        from app.utils.ratelimit import register_limiter
        app.config["REGISTER_RATE_LIMIT"] = 2
        register_limiter.clear()
        assert anon.post("/api/visitors/register", json=visitor_payload(app)).status_code == 201
        assert anon.post("/api/visitors/register", json=visitor_payload(app)).status_code == 201
        assert anon.post("/api/visitors/register", json=visitor_payload(app)).status_code == 429


class TestQrGeneration:
    def test_qr_contains_only_a_random_token_never_personal_data(self, app, anon, tokens):
        register(app, anon, full_name="Asha Patil", mobile="9876543210", email="asha@example.com")
        text = tokens.latest
        assert text.startswith("SMARTCONNECT:v1:")
        for private in ("Asha", "Patil", "9876543210", "asha@example.com", "Pune"):
            assert private not in text

    def test_only_a_hash_of_the_token_is_stored(self, app, anon, tokens):
        data = register(app, anon)
        raw = tokens.all[-1]
        from app.models import QRPass, Visitor
        with app.app_context():
            qp = QRPass.query.one()
            assert qp.token_hash != raw and raw not in qp.token_hash and len(qp.token_hash) == 64
            visitor = Visitor.query.one()
            assert visitor.access_key_hash != data["access_key"]

    def test_each_visitor_gets_a_different_token(self, app, anon, tokens):
        register(app, anon)
        register(app, anon, full_name="Ravi Kumar", mobile="9123456780", email="ravi@example.com")
        assert len(set(tokens.all)) == 2

    def test_visitor_can_generate_a_new_pass_and_the_old_one_stops_working(self, app, anon, host1, guard1, tokens):
        data = register(app, anon)
        pid, key = data["visitor"]["public_id"], data["access_key"]
        approve(host1, pid)
        old_text = tokens.latest
        r = anon.post("/api/qr/generate", json={"visitor_id": pid}, headers={"X-Visitor-Key": key})
        assert r.status_code == 201
        assert r.get_json()["data"]["qr"]["image"].startswith("data:image/png")
        new_text = tokens.latest
        assert old_text != new_text
        old = guard1.post("/api/qr/verify", {"token": old_text, "action": "check-in"}).get_json()["data"]
        new = guard1.post("/api/qr/verify", {"token": new_text, "action": "check-in"}).get_json()["data"]
        assert old["code"] == "revoked" and old["valid"] is False
        assert new["code"] == "valid" and new["valid"] is True

    def test_generate_requires_credentials(self, app, anon, guard1):
        pid = register(app, anon)["visitor"]["public_id"]
        assert anon.post("/api/qr/generate", json={"visitor_id": pid}).status_code == 401
        assert anon.post("/api/qr/generate", json={"visitor_id": pid},
                         headers={"X-Visitor-Key": "nope"}).status_code == 401
        assert guard1.post("/api/qr/generate", {"visitor_id": pid}).status_code == 403
        assert anon.post("/api/qr/generate", json={}).status_code == 400

    def test_host_can_only_issue_passes_for_their_own_visitors(self, app, anon, host1, host2):
        pid = register(app, anon)["visitor"]["public_id"]
        assert host2.post("/api/qr/generate", {"visitor_id": pid}).status_code == 404
        assert host1.post("/api/qr/generate", {"visitor_id": pid}).status_code == 201

    def test_no_new_pass_for_a_rejected_visit(self, app, anon, host1):
        data = register(app, anon)
        approve(host1, data["visitor"]["public_id"], "reject")
        r = anon.post("/api/qr/generate", json={"visitor_id": data["visitor"]["public_id"]},
                      headers={"X-Visitor-Key": data["access_key"]})
        assert r.status_code == 409


class TestQrVerification:
    def test_valid_expired_invalid_and_used_are_told_apart(self, app, anon, host1, guard1, tokens):
        pid, text = approved_visitor(app, anon, host1, tokens)

        def verify(t, action="check-in"):
            r = guard1.post("/api/qr/verify", {"token": t, "action": action})
            assert r.status_code == 200
            return r.get_json()["data"]

        ok = verify(text)
        assert ok["valid"] is True and ok["code"] == "valid"
        assert ok["visitor"]["full_name"] == "Asha Patil"
        assert ok["visitor"]["mobile"].startswith("*")           # guards see a masked number
        assert "email" not in ok["visitor"]

        assert verify(text)["valid"] is True                      # verifying does NOT use the pass up

        bad = verify("SMARTCONNECT:v1:" + "A" * 43)
        assert bad["valid"] is False and bad["code"] == "invalid" and bad["visitor"] is None
        assert verify("hello world")["code"] == "invalid"

        guard1.post("/api/visitors/check-in", {"token": text})
        assert verify(text)["code"] == "already_used"

    def test_expired_pass(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        expire_all_passes(app)
        verdict = guard1.post("/api/qr/verify", {"token": text, "action": "check-in"}).get_json()["data"]
        assert verdict["code"] == "expired" and verdict["valid"] is False
        r = guard1.post("/api/visitors/check-in", {"token": text})
        assert r.status_code == 410 and r.get_json()["error"]["code"] == "expired"

    def test_pass_is_not_valid_until_the_host_approves(self, app, anon, guard1, host1, tokens):
        data = register(app, anon)
        text = tokens.latest
        v = guard1.post("/api/qr/verify", {"token": text, "action": "check-in"}).get_json()["data"]
        assert v["code"] == "pending_approval" and v["valid"] is False
        approve(host1, data["visitor"]["public_id"], "reject")
        v = guard1.post("/api/qr/verify", {"token": text, "action": "check-in"}).get_json()["data"]
        assert v["code"] == "rejected" and v["valid"] is False

    def test_verify_input_validation(self, guard1):
        assert guard1.post("/api/qr/verify", {}).status_code == 400
        assert guard1.post("/api/qr/verify", {"token": "x" * 500}).status_code == 400
        assert guard1.post("/api/qr/verify", {"token": "x" * 43, "action": "explode"}).status_code == 400

    def test_raw_tokens_never_reach_the_audit_log(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/qr/verify", {"token": text, "action": "check-in"})
        guard1.post("/api/visitors/check-in", {"token": text})
        from app.models import AuditLog
        with app.app_context():
            blob = " ".join(f"{a.action} {a.details} {a.entity_id}" for a in AuditLog.query.all())
        assert tokens.all[-1] not in blob


class TestHostApproval:
    def test_host_approves_and_visitor_status_changes(self, app, anon, host1):
        data = register(app, anon)
        pid, key = data["visitor"]["public_id"], data["access_key"]
        approve(host1, pid)
        status = anon.get(f"/api/visitors/{pid}", headers={"X-Visitor-Key": key}).get_json()["data"]["visitor"]
        assert status["status"] == "APPROVED"
        assert status["approval"]["status"] == "APPROVED" and status["approval"]["remarks"] == "ok"

    def test_host_rejects(self, app, anon, host1):
        pid = register(app, anon)["visitor"]["public_id"]
        approve(host1, pid, "reject")
        assert host1.get(f"/api/visitors/{pid}").get_json()["data"]["visitor"]["status"] == "REJECTED"

    def test_a_request_can_only_be_decided_once(self, app, anon, host1):
        pid = register(app, anon)["visitor"]["public_id"]
        approval_id = approve(host1, pid)
        r = host1.post(f"/api/approvals/{approval_id}/decision", {"decision": "reject"})
        assert r.status_code == 409

    def test_another_host_cannot_decide(self, app, anon, host1, host2):
        pid = register(app, anon)["visitor"]["public_id"]
        approval = host1.get("/api/approvals").get_json()["data"]["items"][0]
        assert approval["visitor"]["public_id"] == pid
        assert host2.post(f"/api/approvals/{approval['id']}/decision", {"decision": "approve"}).status_code == 404

    def test_invalid_decision(self, app, anon, host1):
        register(app, anon)
        approval = host1.get("/api/approvals").get_json()["data"]["items"][0]
        assert host1.post(f"/api/approvals/{approval['id']}/decision", {"decision": "maybe"}).status_code == 409

    def test_hosts_only_see_their_own_visitors(self, app, anon, host1, host2):
        pid = register(app, anon)["visitor"]["public_id"]
        assert host2.get(f"/api/visitors/{pid}").status_code == 404
        assert host2.get("/api/visitors").get_json()["data"]["total"] == 0
        assert host1.get("/api/visitors").get_json()["data"]["total"] == 1


class TestVisitorList:
    def test_search_filter_and_pagination(self, app, anon, admin):
        register(app, anon)
        register(app, anon, full_name="Ravi Kumar", mobile="9123456780", email="ravi@example.com")
        assert admin.get("/api/visitors").get_json()["data"]["total"] == 2
        found = admin.get("/api/visitors?q=Ravi").get_json()["data"]
        assert found["total"] == 1 and found["items"][0]["full_name"] == "Ravi Kumar"
        assert admin.get("/api/visitors?status=APPROVED").get_json()["data"]["total"] == 0
        assert admin.get("/api/visitors?per_page=1").get_json()["data"]["pages"] == 2
        assert admin.get("/api/visitors?date_from=bad").status_code == 400

    def test_security_sees_masked_contact_details(self, app, anon, guard1):
        register(app, anon)
        item = guard1.get("/api/visitors").get_json()["data"]["items"][0]
        assert item["mobile"] == "******3210" and "email" not in item and "address" not in item
