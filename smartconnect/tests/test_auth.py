"""Module 1 - authentication, role-based authorisation, sessions, CSRF, lockout."""
from helpers import register


def login(client, role, username, password):
    return client.post("/api/auth/login", json={"role": role, "username": username, "password": password})


class TestLogin:
    def test_each_role_can_log_in_and_is_sent_to_its_own_dashboard(self, app):
        cases = [("admin", "admin", "Admin@123", "/admin/dashboard"),
                 ("security", "security1", "Security@123", "/security/dashboard"),
                 ("host", "host1", "Host@12345", "/host/dashboard")]
        for role, username, password, home in cases:
            r = login(app.test_client(), role, username, password)
            assert r.status_code == 200, r.get_json()
            body = r.get_json()["data"]
            assert body["redirect"] == home
            assert body["user"]["role"] == role
            assert body["csrf_token"]
            assert "password" not in str(body).lower()

    def test_wrong_password_and_unknown_user_look_identical(self, anon):
        a = login(anon, "admin", "admin", "wrong-Password1")
        b = login(anon, "admin", "nobody", "wrong-Password1")
        assert a.status_code == b.status_code == 401
        assert a.get_json()["error"]["message"] == b.get_json()["error"]["message"]

    def test_role_must_match_the_account(self, anon):
        assert login(anon, "security", "admin", "Admin@123").status_code == 401

    def test_missing_fields(self, anon):
        assert anon.post("/api/auth/login", json={"username": "admin"}).status_code == 400
        assert anon.post("/api/auth/login", data="not json").status_code == 400

    def test_account_is_locked_after_repeated_failures(self, anon):
        for _ in range(5):
            assert login(anon, "admin", "admin", "bad-Password1").status_code == 401
        locked = login(anon, "admin", "admin", "Admin@123")   # even the right password is refused now
        assert locked.status_code == 429
        assert "Try again" in locked.get_json()["error"]["message"]

    def test_passwords_are_stored_hashed(self, app):
        from app.models import Admin
        with app.app_context():
            admin = Admin.query.filter_by(username="admin").one()
            assert admin.password_hash != "Admin@123"
            assert admin.password_hash.startswith("pbkdf2:")
            assert "Admin@123" not in admin.password_hash

    def test_deactivated_account_cannot_log_in(self, app, admin):
        from app.extensions import db
        from app.models import Host
        with app.app_context():
            host = Host.query.filter_by(username="host3").one()
            host.is_active = False
            db.session.commit()
        assert login(app.test_client(), "host", "host3", "Host@12345").status_code == 401


class TestSession:
    def test_me_requires_login(self, anon):
        r = anon.get("/api/auth/me")
        assert r.status_code == 401
        assert r.get_json()["error"]["code"] == "unauthorized"

    def test_logout_ends_the_session(self, admin):
        assert admin.get("/api/auth/me").status_code == 200
        assert admin.post("/api/auth/logout").status_code == 200
        assert admin.get("/api/auth/me").status_code == 401

    def test_login_and_logout_are_audited_without_passwords(self, admin):
        admin.post("/api/auth/logout")
        from app.models import AuditLog
        with admin.app.app_context():
            rows = AuditLog.query.all()
            actions = {r.action for r in rows}
            assert {"auth.login", "auth.logout"} <= actions
            assert "Admin@123" not in " ".join(str(r.details) for r in rows)


class TestAuthorisation:
    def test_anonymous_users_are_rejected_everywhere(self, anon):
        for method, url in [("get", "/api/visitors"), ("get", "/api/dashboard/stats"),
                            ("get", "/api/network/status"), ("get", "/api/network/metrics"),
                            ("get", "/api/reports/daily"), ("get", "/api/admin/users"),
                            ("get", "/api/approvals"), ("post", "/api/visitors/check-in"),
                            ("post", "/api/visitors/check-out"), ("post", "/api/qr/verify"),
                            ("post", "/api/sync")]:
            r = getattr(anon, method)(url)
            assert r.status_code == 401, (method, url, r.status_code)

    def test_security_cannot_use_admin_or_host_features(self, guard1):
        for url in ("/api/admin/users", "/api/admin/audit", "/api/reports/daily",
                    "/api/network/metrics", "/api/approvals", "/api/departments"):
            assert guard1.get(url).status_code == 403, url

    def test_host_cannot_scan_or_administer(self, host1):
        assert host1.post("/api/visitors/check-in", {"token": "x" * 43}).status_code == 403
        assert host1.post("/api/sync", {"operations": []}).status_code == 403
        assert host1.get("/api/admin/users").status_code == 403
        assert host1.get("/api/network/status").status_code == 403

    def test_admin_cannot_perform_security_scans(self, admin):
        assert admin.post("/api/visitors/check-in", {"token": "x" * 43}).status_code == 403

    def test_state_changing_requests_need_the_csrf_header(self, admin):
        r = admin.post("/api/departments", {"name": "Legal"}, csrf=False)
        assert r.status_code == 403
        assert r.get_json()["error"]["code"] == "csrf_failed"
        r = admin.post("/api/departments", {"name": "Legal"}, headers={"X-CSRF-Token": "forged"}, csrf=False)
        assert r.status_code == 403
        assert admin.post("/api/departments", {"name": "Legal"}).status_code == 201

    def test_pages_redirect_to_login_or_own_home(self, anon, guard1):
        r = anon.get("/admin/dashboard")
        assert r.status_code == 302 and "/login" in r.headers["Location"]
        r = guard1.get("/admin/dashboard")
        assert r.status_code == 302 and r.headers["Location"].endswith("/security/dashboard")

    def test_public_pages_render(self, anon):
        for url in ("/", "/login", "/register", "/visitor/pass", "/offline"):
            assert anon.get(url).status_code == 200, url

    def test_every_dashboard_page_renders_for_its_role(self, admin, guard1, host1):
        pages = {admin: ["/admin/dashboard", "/admin/visitors", "/admin/users", "/admin/gates",
                         "/admin/reports", "/admin/audit", "/admin/network"],
                 guard1: ["/security/dashboard", "/security/scanner", "/security/visitors"],
                 host1: ["/host/dashboard", "/host/visitors"]}
        for user, urls in pages.items():
            for url in urls:
                r = user.get(url)
                assert r.status_code == 200, url
                assert b"csrf-token" in r.data


class TestVisitorAccessKey:
    def test_visitor_authenticates_with_their_key_only(self, app, anon):
        data = register(app, anon)
        pid, key = data["visitor"]["public_id"], data["access_key"]
        ok = anon.get(f"/api/visitors/{pid}", headers={"X-Visitor-Key": key})
        assert ok.status_code == 200
        assert ok.get_json()["data"]["visitor"]["full_name"] == "Asha Patil"
        assert anon.get(f"/api/visitors/{pid}", headers={"X-Visitor-Key": "wrong"}).status_code == 401
        assert anon.get(f"/api/visitors/{pid}").status_code == 401

    def test_one_visitor_cannot_read_another_visitors_pass(self, app, anon):
        a = register(app, anon)
        b = register(app, anon, full_name="Ravi Kumar", mobile="9123456780", email="ravi@example.com")
        r = anon.get(f"/api/visitors/{b['visitor']['public_id']}", headers={"X-Visitor-Key": a["access_key"]})
        assert r.status_code == 401
