"""Small helper functions shared by the test files."""
from datetime import datetime, timedelta, timezone


def iso_in(hours=1.0):
    """ISO time (UTC, ends with Z) some hours from now."""
    when = datetime.now(timezone.utc) + timedelta(hours=hours)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class Staff:
    """A logged-in test browser. Remembers the CSRF token the server issued at login."""

    def __init__(self, app, role, username, password):
        self.app = app
        self.client = app.test_client()
        r = self.client.post("/api/auth/login",
                             json={"role": role, "username": username, "password": password})
        assert r.status_code == 200, r.get_json()
        self.csrf = r.get_json()["data"]["csrf_token"]
        self.user = r.get_json()["data"]["user"]

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def _unsafe(self, method, url, json=None, csrf=True, **kw):
        headers = dict(kw.pop("headers", {}))
        if csrf:
            headers["X-CSRF-Token"] = self.csrf
        return getattr(self.client, method)(url, json=json, headers=headers, **kw)

    def post(self, url, json=None, **kw):
        return self._unsafe("post", url, json, **kw)

    def patch(self, url, json=None, **kw):
        return self._unsafe("patch", url, json, **kw)


def ids(app):
    """Primary keys the tests need (departments, hosts, gates)."""
    from app.models import Department, Gate, Host
    with app.app_context():
        return {
            "dept_eng": Department.query.filter_by(name="Engineering").one().id,
            "dept_hr": Department.query.filter_by(name="Human Resources").one().id,
            "host1": Host.query.filter_by(username="host1").one().id,
            "host2": Host.query.filter_by(username="host2").one().id,
            "main_gate": Gate.query.filter_by(name="Main Gate").one().id,
            "gate2": Gate.query.filter_by(name="Gate 2").one().id,
        }


def visitor_payload(app, **overrides):
    i = ids(app)
    data = {
        "full_name": "Asha Patil", "mobile": "9876543210", "email": "asha@example.com",
        "address": "12 MG Road, Pune", "purpose": "Project meeting",
        "department_id": i["dept_eng"], "host_id": i["host1"], "expected_at": iso_in(1),
    }
    data.update(overrides)
    return data


def register(app, client, **overrides):
    """Register a visitor through the public API. Returns the parsed `data` object."""
    r = client.post("/api/visitors/register", json=visitor_payload(app, **overrides))
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"]


def approve(host, public_id, decision="approve"):
    """Host approves (or rejects) the visitor's pending request."""
    items = host.get("/api/approvals?status=PENDING").get_json()["data"]["items"]
    approval = next(a for a in items if a["visitor"]["public_id"] == public_id)
    r = host.post(f"/api/approvals/{approval['id']}/decision", {"decision": decision, "remarks": "ok"})
    assert r.status_code == 200, r.get_json()
    return approval["id"]


def approved_visitor(app, anon, host, tokens, **overrides):
    """Register + approve. Returns (public_id, scanned_text)."""
    data = register(app, anon, **overrides)
    pid = data["visitor"]["public_id"]
    approve(host, pid)
    return pid, tokens.latest
