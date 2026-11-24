"""
Module 6 + WebSocket events - real-time dashboard and who is allowed to receive what.

`socketio.test_client` opens a real Socket.IO connection to the app inside the test process
(no browser needed).  Passing `flask_test_client=user.client` gives that connection the same
login cookie the user's browser would have, so the server authorises it exactly as in real use.
"""
from helpers import approve, approved_visitor, iso_in, register


def connect(app, user=None, **auth):
    from app.extensions import socketio
    kwargs = {}
    if user is not None:
        kwargs["flask_test_client"] = user.client
    if auth:
        kwargs["auth"] = auth
    return socketio.test_client(app, **kwargs)


def received(sio):
    """Return {event_name: [payloads]} for everything received since the last call."""
    out = {}
    for message in sio.get_received():
        out.setdefault(message["name"], []).append(message["args"][0])
    return out


class TestConnectionAuthorisation:
    def test_anonymous_connection_is_refused(self, app):
        assert connect(app).is_connected() is False

    def test_staff_connect_with_their_session(self, app, admin, guard1, host1):
        for user in (admin, guard1, host1):
            sio = connect(app, user)
            assert sio.is_connected()
            sio.disconnect()

    def test_visitor_needs_the_correct_access_key(self, app, anon):
        data = register(app, anon)
        pid, key = data["visitor"]["public_id"], data["access_key"]
        good = connect(app, public_id=pid, key=key)
        assert good.is_connected()
        assert connect(app, public_id=pid, key="wrong-key").is_connected() is False
        assert connect(app, public_id="0" * 32, key=key).is_connected() is False
        good.disconnect()

    def test_a_deactivated_staff_account_cannot_connect(self, app, admin, guard1):
        admin.patch(f"/api/admin/users/security/{guard1.user['id']}", {"is_active": False})
        assert connect(app, guard1).is_connected() is False


class TestEventDelivery:
    def test_visitor_registered_reaches_admin_security_and_only_the_chosen_host(self, app, anon, admin, guard1, host1, host2):
        clients = {name: connect(app, user) for name, user in
                   {"admin": admin, "guard": guard1, "host1": host1, "host2": host2}.items()}
        for c in clients.values():
            c.get_received()                                       # ignore connection chatter
        register(app, anon)                                        # chosen host is host1
        got = {name: received(c) for name, c in clients.items()}
        assert "visitor_registered" in got["admin"]
        assert "visitor_registered" in got["guard"]
        assert "visitor_registered" in got["host1"]
        assert "visitor_registered" not in got["host2"]            # a different host must not see it
        payload = got["host1"]["visitor_registered"][0]
        assert payload["full_name"] == "Asha Patil" and payload["status"] == "PENDING"
        assert "mobile" not in payload and "email" not in payload and "address" not in payload

    def test_approval_updated_reaches_the_visitor_and_the_host_but_not_other_visitors(self, app, anon, host1, host2):
        mine = register(app, anon)
        other = register(app, anon, full_name="Ravi Kumar", mobile="9123456780", email="ravi@example.com")
        me = connect(app, public_id=mine["visitor"]["public_id"], key=mine["access_key"])
        them = connect(app, public_id=other["visitor"]["public_id"], key=other["access_key"])
        host = connect(app, host1)
        for c in (me, them, host):
            c.get_received()
        approve(host1, mine["visitor"]["public_id"])
        assert received(me)["approval_updated"][0]["approval_status"] == "APPROVED"
        assert "approval_updated" in received(host)
        assert "approval_updated" not in received(them)

    def test_check_in_and_check_out_events(self, app, anon, host1, host2, admin, guard1, tokens):
        pid, text = approved_visitor(app, anon, host1, tokens)
        adm, h1, h2, g = connect(app, admin), connect(app, host1), connect(app, host2), connect(app, guard1)
        for c in (adm, h1, h2, g):
            c.get_received()
        guard1.post("/api/visitors/check-in", {"token": text})
        guard1.post("/api/visitors/check-out", {"token": text})
        for c in (adm, h1, g):
            ev = received(c)
            assert ev["visitor_checked_in"][0]["gate"] == "Main Gate"
            assert ev["visitor_checked_out"][0]["public_id"] == pid
        assert received(h2) == {}                                  # unrelated host sees nothing

    def test_sync_completed_goes_to_admin_and_the_syncing_guard_only(self, app, anon, host1, admin, guard1, guard2, tokens):
        _, text = approved_visitor(app, anon, host1, tokens)
        adm, g1, g2 = connect(app, admin), connect(app, guard1), connect(app, guard2)
        for c in (adm, g1, g2):
            c.get_received()
        guard1.post("/api/sync", {"device_id": "phone-test-0001", "operations": [
            {"operation_id": "op-rt000001", "type": "check-in", "token": text, "scanned_at": iso_in(-0.1)}]})
        a, b, c = received(adm), received(g1), received(g2)
        assert a["sync_completed"][0]["success"] == 1 and a["sync_completed"][0]["device_id"] == "phone-test-0001"
        assert "sync_completed" in b
        assert "sync_completed" not in c

    def test_network_status_changed_is_for_admins_only(self, app, admin, guard1):
        adm, g = connect(app, admin), connect(app, guard1)
        adm.get_received()
        g.get_received()
        extra = connect(app, guard1)
        assert received(adm)["network_status_changed"][-1]["ws_clients"] == 3
        assert "network_status_changed" not in received(g)
        extra.disconnect()
        assert received(adm)["network_status_changed"][-1]["ws_clients"] == 2

    def test_monitor_counts_real_websocket_clients(self, app, admin, guard1):
        assert admin.get("/api/network/status").get_json()["data"]["websocket"]["connected"] == 0
        a, g = connect(app, admin), connect(app, guard1)
        ws = admin.get("/api/network/status").get_json()["data"]["websocket"]
        assert ws["connected"] == 2 and {c["role"] for c in ws["clients"]} == {"admin", "security"}
        g.disconnect()
        assert admin.get("/api/network/status").get_json()["data"]["websocket"]["connected"] == 1
        a.disconnect()
        assert admin.get("/api/network/status").get_json()["data"]["websocket"]["connected"] == 0


class TestLiveDashboard:
    def test_dashboard_numbers_follow_the_visit_lifecycle(self, app, anon, host1, admin, guard1, tokens):
        def stats():
            return admin.get("/api/dashboard/stats").get_json()["data"]

        s0 = stats()
        assert (s0["inside_now"], s0["today_check_ins"], s0["today_check_outs"], s0["pending_approvals"]) == (0, 0, 0, 0)

        data = register(app, anon)
        pid, text = data["visitor"]["public_id"], tokens.latest
        s1 = stats()
        assert s1["pending_approvals"] == 1 and s1["registered_today"] == 1

        approve(host1, pid)
        assert stats()["pending_approvals"] == 0

        sio = connect(app, admin)
        sio.get_received()
        guard1.post("/api/visitors/check-in", {"token": text})
        assert "visitor_checked_in" in received(sio)               # pushed instantly, no polling
        s2 = stats()
        assert s2["inside_now"] == 1 and s2["live_visitor_count"] == 1 and s2["today_check_ins"] == 1
        assert s2["status_counts"]["INSIDE"] == 1
        assert sum(s2["hourly_check_ins"]) == 1
        assert "check_in" in {e["type"] for e in s2["recent"]}

        guard1.post("/api/visitors/check-out", {"token": text})
        assert "visitor_checked_out" in received(sio)
        s3 = stats()
        assert s3["inside_now"] == 0 and s3["today_check_outs"] == 1 and s3["status_counts"]["COMPLETED"] == 1

    def test_a_host_dashboard_only_counts_their_own_visitors(self, app, anon, host1, host2):
        register(app, anon)                                        # for host1
        mine = host1.get("/api/dashboard/stats").get_json()["data"]
        theirs = host2.get("/api/dashboard/stats").get_json()["data"]
        assert mine["pending_approvals"] == 1 and theirs["pending_approvals"] == 0
        assert all(e["name"] != "Asha Patil" for e in theirs["recent"])

    def test_security_dashboard_shows_the_assigned_gate(self, guard1, guard2):
        assert guard1.get("/api/dashboard/stats").get_json()["data"]["my_gate"]["name"] == "Main Gate"
        assert guard2.get("/api/dashboard/stats").get_json()["data"]["my_gate"]["name"] == "Gate 2"
