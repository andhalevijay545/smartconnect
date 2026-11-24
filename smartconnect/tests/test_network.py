"""
Modules 7, 9 and 13 - LAN / WAN communication, network monitoring, communication logs.

LAN vs WAN is decided from the client's IP address:  private ranges (192.168.x.x, 10.x.x.x,
172.16-31.x.x, 127.x.x.x) = LAN,  public addresses = WAN.  The tests simulate both kinds of
clients by setting the REMOTE_ADDR of the request, exactly as the real network stack would.
"""
import pytest
from helpers import approve, approved_visitor, register, visitor_payload

PHONE_LAN = {"REMOTE_ADDR": "192.168.1.42"}      # a phone on the office Wi-Fi
PHONE_WAN = {"REMOTE_ADDR": "8.8.8.8"}           # a phone on mobile data (public address)


def last_log(app):
    from app.models import CommunicationLog
    with app.app_context():
        return CommunicationLog.query.order_by(CommunicationLog.id.desc()).first()


def make_app(tmp_path, **overrides):
    """A second, differently configured application (used for the WAN / proxy tests)."""
    for module in ("flask_sqlalchemy", "flask_socketio", "flask_migrate", "qrcode"):
        pytest.importorskip(module, reason=f"{module} not installed - run: pip install -r requirements.txt")
    from app import create_app
    from app.extensions import db
    from app.utils.seed import seed_database

    overrides.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///" + (tmp_path / "wan.db").as_posix())
    application = create_app("testing", overrides=overrides)
    with application.app_context():
        db.create_all()
        seed_database(demo=True, out=lambda *a, **k: None)
    return application


# ------------------------------------------------------------ communication logs
class TestCommunicationLog:
    def test_every_api_call_is_logged_with_all_required_fields(self, app, anon):
        anon.get("/api/lookups", headers={"X-Device-Id": "phone-test-0001"})
        row = last_log(app)
        assert row.endpoint == "/api/lookups"
        assert row.method == "GET"
        assert row.status_code == 200 and row.success is True
        assert row.device_id == "phone-test-0001"
        assert row.duration_ms >= 0
        assert row.timestamp is not None
        assert row.network_type == "LAN"                          # the test client is 127.0.0.1

    def test_failures_are_logged_as_failures(self, app, anon):
        anon.get("/api/visitors")                                  # not logged in -> 401
        row = last_log(app)
        assert row.status_code == 401 and row.success is False

    def test_logs_hold_the_route_pattern_not_the_real_ids(self, app, anon, admin):
        pid = register(app, anon)["visitor"]["public_id"]
        admin.get(f"/api/visitors/{pid}?q=secret-search")
        row = last_log(app)
        assert row.endpoint == "/api/visitors/<public_id>"
        assert pid not in row.endpoint and "secret-search" not in row.endpoint

    def test_passwords_cookies_and_qr_tokens_are_never_logged(self, app, anon, host1, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        anon.post("/api/auth/login", json={"role": "admin", "username": "admin", "password": "TopSecret-Pw1"})
        from app.models import CommunicationLog
        with app.app_context():
            dump = " ".join(str(getattr(r, c.name)) for r in CommunicationLog.query.all()
                            for c in CommunicationLog.__table__.columns)
        assert tokens.all[-1] not in dump
        assert "TopSecret-Pw1" not in dump
        assert "session" not in dump.lower()

    def test_devices_without_an_id_get_a_stable_anonymous_one(self, app, anon):
        anon.get("/api/lookups")
        first = last_log(app).device_id
        anon.get("/api/lookups")
        assert first.startswith("anon-") and last_log(app).device_id == first

    def test_a_forged_device_id_is_replaced(self, app, anon):
        anon.get("/api/lookups", headers={"X-Device-Id": "<script>alert(1)</script>"})
        assert last_log(app).device_id.startswith("anon-")

    def test_static_files_and_monitoring_calls_are_not_logged(self, app, anon, admin):
        from app.models import CommunicationLog
        with app.app_context():
            before = CommunicationLog.query.count()
        anon.get("/api/network/ping")
        admin.get("/api/network/status")
        admin.get("/api/network/metrics")
        anon.get("/static/css/style.css")
        anon.get("/")
        with app.app_context():
            assert CommunicationLog.query.count() == before


# -------------------------------------------------------------------- LAN / WAN
class TestLanAndWan:
    def test_lan_client_is_recognised(self, app, anon):
        r = anon.get("/api/lookups", environ_base=PHONE_LAN)
        assert r.status_code == 200
        row = last_log(app)
        assert row.client_ip == "192.168.1.42" and row.network_type == "LAN"

    def test_wan_client_is_recognised(self, app, anon):
        r = anon.get("/api/lookups", environ_base=PHONE_WAN)
        assert r.status_code == 200
        row = last_log(app)
        assert row.client_ip == "8.8.8.8" and row.network_type == "WAN"

    def test_same_backend_and_database_serve_both_networks(self, app, anon, host1, guard1, tokens):
        """A visitor registers from the internet (WAN); the guard scans on the office Wi-Fi (LAN)."""
        data = anon.post("/api/visitors/register", environ_base=PHONE_WAN,
                         json=visitor_payload(app)).get_json()["data"]
        approve(host1, data["visitor"]["public_id"])
        r = guard1.client.post("/api/visitors/check-in", json={"token": tokens.latest},
                               headers={"X-CSRF-Token": guard1.csrf}, environ_base=PHONE_LAN)
        assert r.status_code == 200 and r.get_json()["data"]["code"] == "checked_in"

    def test_status_endpoint_describes_the_connection(self, app, admin):
        data = admin.get("/api/network/status", environ_base=PHONE_WAN).get_json()["data"]
        assert data["connection"]["client_ip"] == "8.8.8.8"
        assert data["connection"]["network_type"] == "WAN"
        assert data["connection"]["scheme"] == "http" and data["connection"]["tls"] is False
        assert data["server"]["mode"] == "LAN"
        assert data["available"] is True and data["database"]["ok"] is True
        assert data["database"]["latency_ms"] >= 0
        assert isinstance(data["server"]["lan_ips"], list)

    def test_wan_mode_label_comes_from_configuration(self, tmp_path):
        application = make_app(tmp_path, NETWORK_MODE="WAN")
        from helpers import Staff
        admin = Staff(application, "admin", "admin", "Admin@123")
        assert admin.get("/api/network/status").get_json()["data"]["server"]["mode"] == "WAN"

    def test_behind_a_proxy_the_real_client_ip_and_https_are_read_from_headers(self, tmp_path):
        """On Render the load balancer terminates TLS and tells us the real client in X-Forwarded-*."""
        application = make_app(tmp_path, BEHIND_PROXY=True)
        client = application.test_client()
        r = client.get("/api/lookups", headers={"X-Forwarded-For": "8.8.8.8", "X-Forwarded-Proto": "https"})
        assert r.status_code == 200
        row = last_log(application)
        assert row.client_ip == "8.8.8.8" and row.network_type == "WAN" and row.is_secure is True
        assert "Strict-Transport-Security" in r.headers          # HSTS only appears on secure requests

    def test_https_is_enforced_for_public_hosts_when_enabled(self, tmp_path):
        application = make_app(tmp_path, FORCE_HTTPS=True)
        client = application.test_client()
        r = client.get("/api/network/ping", base_url="http://smartconnect.example.com")
        assert r.status_code == 301 and r.headers["Location"].startswith("https://smartconnect.example.com")
        # localhost stays reachable over plain http so development still works
        assert client.get("/api/network/ping", base_url="http://localhost").status_code == 200

    def test_plain_http_is_allowed_on_a_lan_when_force_https_is_off(self, app, anon):
        r = anon.get("/api/network/ping", base_url="http://192.168.1.10:5000")
        assert r.status_code == 200


# ------------------------------------------------------------ monitoring numbers
class TestMonitoring:
    def test_ping_is_public_and_returns_server_time(self, anon):
        r = anon.get("/api/network/ping")
        assert r.status_code == 200 and r.get_json()["data"]["pong"] is True
        assert float(r.headers["X-Response-Time-ms"]) >= 0       # server processing time header

    def test_metrics_count_the_real_requests(self, app, anon, admin):
        def totals():
            return admin.get("/api/network/metrics?minutes=10").get_json()["data"]["totals"]

        before = totals()
        for _ in range(3):
            anon.get("/api/lookups")
        anon.get("/api/visitors")                                  # 401 -> counted as failed
        after = totals()
        assert after["requests"] - before["requests"] == 4
        assert after["successful"] - before["successful"] == 3
        assert after["failed"] - before["failed"] == 1

    def test_metrics_contain_response_times_status_codes_and_history(self, app, anon, admin):
        for _ in range(5):
            anon.get("/api/lookups")
        anon.get("/api/visitors")
        data = admin.get("/api/network/metrics?minutes=10").get_json()["data"]
        rt = data["response_time_ms"]
        assert rt["min"] <= rt["avg"] <= rt["max"] and rt["p50"] <= rt["p95"] <= rt["max"] + 0.01
        assert data["status_codes"]["200"] >= 5 and data["status_codes"]["401"] >= 1
        assert data["status_classes"]["2xx"] >= 5 and data["status_classes"]["4xx"] >= 1
        assert data["network_types"]["LAN"] >= 6
        assert len(data["timeline"]) >= 1 and data["timeline"][0]["count"] >= 1
        assert data["history"] and {"t", "method", "endpoint", "status", "ms", "device_id"} <= set(data["history"][0])
        assert data["top_endpoints"][0]["count"] >= 5

    def test_an_empty_window_gives_zeroes_not_invented_numbers(self, app, admin):
        from app.extensions import db
        from app.models import CommunicationLog
        with app.app_context():
            CommunicationLog.query.delete()
            db.session.commit()
        data = admin.get("/api/network/metrics?minutes=1").get_json()["data"]
        assert data["totals"]["requests"] == 0 and data["totals"]["success_rate"] is None
        assert data["response_time_ms"]["avg"] == 0 and data["history"] == []

    def test_metrics_never_contain_qr_tokens(self, app, anon, host1, admin, guard1, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        guard1.post("/api/visitors/check-in", {"token": text})
        blob = str(admin.get("/api/network/metrics").get_json())
        assert tokens.all[-1] not in blob

    def test_window_is_clamped(self, admin):
        assert admin.get("/api/network/metrics?minutes=999999").get_json()["data"]["window_minutes"] == 1440
        assert admin.get("/api/network/metrics?minutes=0").get_json()["data"]["window_minutes"] == 1

    def test_metrics_are_admin_only_but_status_is_for_all_staff(self, guard1, host1):
        assert guard1.get("/api/network/metrics").status_code == 403
        assert guard1.get("/api/network/status").status_code == 200
        assert host1.get("/api/network/status").status_code == 403


class TestDns:
    def test_dns_lookup_resolves_and_times_a_name(self, admin):
        r = admin.get("/api/network/dns?host=localhost")
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert set(data["addresses"]) & {"127.0.0.1", "::1"}
        assert data["lookup_ms"] >= 0 and data["scope"][0]["network"] == "LAN"

    @pytest.mark.parametrize("bad", ["bad host!", "a..b", "-start.com", "x" * 300])
    def test_dns_input_is_validated(self, admin, bad):
        assert admin.get("/api/network/dns", query_string={"host": bad}).status_code == 400

    def test_unknown_name_gives_a_clean_error(self, admin):
        r = admin.get("/api/network/dns?host=this-name-does-not-exist.invalid")
        assert r.status_code == 400 and r.get_json()["error"]["code"] == "dns_error"


# --------------------------------------------------------------- security headers
class TestSecurityHeaders:
    def test_headers_on_every_response(self, anon):
        r = anon.get("/login")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]
        assert "camera=(self)" in r.headers["Permissions-Policy"]
        assert "Strict-Transport-Security" not in r.headers      # not sent over plain http

    def test_api_responses_are_never_cached(self, anon):
        assert anon.get("/api/lookups").headers["Cache-Control"] == "no-store"

    def test_service_worker_is_served_from_the_site_root(self, anon):
        r = anon.get("/sw.js")
        assert r.status_code == 200 and r.headers["Service-Worker-Allowed"] == "/"
        assert "javascript" in r.headers["Content-Type"]
        assert anon.get("/manifest.webmanifest").status_code == 200
