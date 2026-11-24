"""Module 12 (reports + CSV export) and Module 1/11 admin features (users, departments, audit log)."""
from datetime import datetime

from helpers import approved_visitor, ids


def make_visits(app, anon, host1, host2, guard1, guard2, tokens):
    """Two visitors: one for Engineering (in via Main Gate, out via Main Gate),
    one for HR (in via Gate 2, still inside)."""
    i = ids(app)
    _, t1 = approved_visitor(app, anon, host1, tokens)
    _, t2 = approved_visitor(app, anon, host2, tokens, full_name="Ravi Kumar", mobile="9123456780",
                             email="ravi@example.com", department_id=i["dept_hr"], host_id=i["host2"])
    guard1.post("/api/visitors/check-in", {"token": t1})
    guard1.post("/api/visitors/check-out", {"token": t1})
    guard2.post("/api/visitors/check-in", {"token": t2})


class TestReports:
    def test_daily_report_totals_department_and_gate_counts(self, app, anon, host1, host2, admin, guard1, guard2, tokens):
        make_visits(app, anon, host1, host2, guard1, guard2, tokens)
        data = admin.get("/api/reports/daily").get_json()["data"]
        s = data["summary"]
        assert (s["registered"], s["approved"], s["rejected"], s["check_ins"], s["check_outs"]) == (2, 2, 0, 2, 1)
        dept = {d["department"]: d for d in data["by_department"]}
        assert dept["Engineering"]["check_ins"] == 1 and dept["Human Resources"]["check_ins"] == 1
        assert dept["Finance"]["check_ins"] == 0
        gate = {g["gate"]: g for g in data["by_gate"]}
        assert gate["Main Gate"]["check_ins"] == 1 and gate["Main Gate"]["check_outs"] == 1
        assert gate["Gate 2"]["check_ins"] == 1 and gate["Gate 2"]["check_outs"] == 0
        assert len(data["by_day"]) == 1 and data["by_day"][0]["check_ins"] == 2
        assert len(data["history"]) == 2                           # visitor history rows

    def test_weekly_and_monthly_reports_cover_the_whole_period(self, app, anon, host1, host2, admin, guard1, guard2, tokens):
        make_visits(app, anon, host1, host2, guard1, guard2, tokens)
        week = admin.get("/api/reports/weekly").get_json()["data"]
        month = admin.get("/api/reports/monthly").get_json()["data"]
        assert len(week["by_day"]) == 7 and week["summary"]["check_ins"] == 2
        assert 28 <= len(month["by_day"]) <= 31 and month["summary"]["check_ins"] == 2
        assert datetime.strptime(week["from"], "%Y-%m-%d").weekday() == 0     # weeks start on Monday

    def test_other_dates_are_empty(self, admin, app, anon, host1, host2, guard1, guard2, tokens):
        make_visits(app, anon, host1, host2, guard1, guard2, tokens)
        old = admin.get("/api/reports/daily?date=2020-01-15").get_json()["data"]
        assert old["summary"]["check_ins"] == 0 and old["history"] == []

    def test_bad_input_and_permissions(self, admin, guard1, host1):
        assert admin.get("/api/reports/daily?date=15-01-2020").status_code == 400
        assert admin.get("/api/reports/yearly").status_code == 404
        assert guard1.get("/api/reports/daily").status_code == 403
        assert host1.get("/api/reports/daily/export").status_code == 403

    def test_csv_export(self, app, anon, host1, host2, admin, guard1, guard2, tokens):
        make_visits(app, anon, host1, host2, guard1, guard2, tokens)
        r = admin.get("/api/reports/daily/export")
        assert r.status_code == 200 and r.mimetype == "text/csv"
        assert "attachment; filename=\"smartconnect_daily_" in r.headers["Content-Disposition"]
        body = r.get_data(as_text=True)
        for expected in ("SmartConnect report", "Visitor,Mobile,Department", "Asha Patil", "Ravi Kumar",
                         "Department,Registered,Check-ins", "Gate,Check-ins,Check-outs", "Main Gate"):
            assert expected in body, expected

    def test_csv_export_blocks_spreadsheet_formula_injection(self, app, anon, host1, admin, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens, purpose="=cmd|' /C calc'!A0")
        guard1.post("/api/visitors/check-in", {"token": text})
        body = admin.get("/api/reports/daily/export").get_data(as_text=True)
        assert "'=cmd" in body and ",=cmd" not in body

    def test_reports_never_contain_qr_tokens(self, app, anon, host1, host2, admin, guard1, guard2, tokens):
        make_visits(app, anon, host1, host2, guard1, guard2, tokens)
        blob = str(admin.get("/api/reports/daily").get_json()) + admin.get("/api/reports/daily/export").get_data(as_text=True)
        assert not any(t in blob for t in tokens.all)


class TestUserManagement:
    NEW_HOST = {"role": "host", "username": "newhost", "full_name": "Neha Kapoor",
                "email": "neha@example.com", "password": "Str0ngPass1", "phone": "9000000000"}

    def test_admin_creates_a_host_who_can_log_in(self, app, admin):
        body = dict(self.NEW_HOST, department_id=ids(app)["dept_eng"])
        r = admin.post("/api/admin/users", body)
        assert r.status_code == 201, r.get_json()
        user = r.get_json()["data"]["user"]
        assert user["role"] == "host" and user["department_name"] == "Engineering"
        assert "password" not in str(user).lower()
        login = app.test_client().post("/api/auth/login", json={"role": "host", "username": "newhost",
                                                                "password": "Str0ngPass1"})
        assert login.status_code == 200

    def test_admin_creates_security_staff_with_a_gate(self, app, admin):
        body = {"role": "security", "username": "guard9", "full_name": "Guard Nine",
                "email": "g9@example.com", "password": "Str0ngPass1", "gate_id": ids(app)["gate2"]}
        r = admin.post("/api/admin/users", body)
        assert r.status_code == 201 and r.get_json()["data"]["user"]["gate_name"] == "Gate 2"

    def test_validation_and_duplicates(self, app, admin):
        dept = ids(app)["dept_eng"]
        weak = admin.post("/api/admin/users", dict(self.NEW_HOST, password="weak", department_id=dept))
        assert weak.status_code == 422 and "password" in weak.get_json()["error"]["details"]
        assert admin.post("/api/admin/users", dict(self.NEW_HOST, role="wizard")).status_code == 422
        assert admin.post("/api/admin/users", dict(self.NEW_HOST)).status_code == 422        # host needs a department
        assert admin.post("/api/admin/users", dict(self.NEW_HOST, department_id=dept)).status_code == 201
        assert admin.post("/api/admin/users", dict(self.NEW_HOST, department_id=dept)).status_code == 409

    def test_listing_by_role(self, admin):
        names = {u["username"] for u in admin.get("/api/admin/users?role=security").get_json()["data"]["items"]}
        assert names == {"security1", "security2"}
        assert len(admin.get("/api/admin/users?role=host").get_json()["data"]["items"]) == 3
        assert admin.get("/api/admin/users?role=king").status_code == 400

    def test_deactivate_and_reset_password(self, app, admin, guard2):
        uid = guard2.user["id"]
        assert admin.patch(f"/api/admin/users/security/{uid}", {"password": "N3wPassword9"}).status_code == 200
        ok = app.test_client().post("/api/auth/login", json={"role": "security", "username": "security2",
                                                             "password": "N3wPassword9"})
        assert ok.status_code == 200
        assert admin.patch(f"/api/admin/users/security/{uid}", {"is_active": False}).status_code == 200
        assert guard2.get("/api/auth/me").status_code == 401                # existing session stops working
        again = app.test_client().post("/api/auth/login", json={"role": "security", "username": "security2",
                                                                "password": "N3wPassword9"})
        assert again.status_code == 401

    def test_admin_cannot_deactivate_themselves(self, admin):
        r = admin.patch(f"/api/admin/users/admin/{admin.user['id']}", {"is_active": False})
        assert r.status_code == 422 and admin.get("/api/auth/me").status_code == 200

    def test_update_unknown_user(self, admin):
        assert admin.patch("/api/admin/users/host/9999", {"full_name": "Nobody Here"}).status_code == 404
        assert admin.patch("/api/admin/users/wizard/1", {"full_name": "Nobody Here"}).status_code == 404


class TestDepartments:
    def test_create_rename_disable(self, app, anon, admin):
        r = admin.post("/api/departments", {"name": "Legal"})
        assert r.status_code == 201
        dep_id = r.get_json()["data"]["department"]["id"]
        assert admin.post("/api/departments", {"name": "Legal"}).status_code == 409
        assert admin.patch(f"/api/departments/{dep_id}", {"name": "Legal Affairs"}).status_code == 200
        names = [d["name"] for d in anon.get("/api/lookups").get_json()["data"]["departments"]]
        assert "Legal Affairs" in names
        admin.patch(f"/api/departments/{dep_id}", {"is_active": False})
        names = [d["name"] for d in anon.get("/api/lookups").get_json()["data"]["departments"]]
        assert "Legal Affairs" not in names

    def test_short_names_are_rejected(self, admin):
        assert admin.post("/api/departments", {"name": "x"}).status_code == 422


class TestAuditLog:
    def test_important_actions_are_recorded(self, app, anon, host1, admin, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        admin.post("/api/gates", {"name": "Service Gate"})
        items = admin.get("/api/admin/audit?per_page=100").get_json()["data"]["items"]
        actions = {a["action"] for a in items}
        assert {"auth.login", "visitor.register", "approval.approve", "visit.check_in", "gate.create"} <= actions

    def test_filter_and_pagination(self, admin, guard1):
        data = admin.get("/api/admin/audit?action=auth.&per_page=1").get_json()["data"]
        assert data["total"] >= 2 and data["pages"] >= 2 and len(data["items"]) == 1
        assert all(a["action"].startswith("auth.") for a in data["items"])

    def test_audit_log_never_stores_secrets(self, app, anon, host1, admin, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        anon.post("/api/auth/login", json={"role": "admin", "username": "admin", "password": "Wrong-Pass-1"})
        blob = str(admin.get("/api/admin/audit?per_page=100").get_json())
        for secret in (tokens.all[-1], "Wrong-Pass-1", "Admin@123", "Security@123"):
            assert secret not in blob

    def test_only_admin_can_read_it(self, guard1, host1, anon):
        assert guard1.get("/api/admin/audit").status_code == 403
        assert host1.get("/api/admin/audit").status_code == 403
        assert anon.get("/api/admin/audit").status_code == 401
