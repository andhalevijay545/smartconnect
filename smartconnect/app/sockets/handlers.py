"""
Socket.IO (WebSocket) connection handling.

A WebSocket is a long-lived two-way TCP connection. After the first HTTP
"upgrade" handshake, the server can PUSH data to the browser at any time, so
dashboards update instantly without polling.

Authorisation: a connection is accepted only if it carries
  * a valid staff session cookie, or
  * a visitor's public id + access key (so a visitor sees only their own pass).
Each accepted connection joins "rooms"; events are sent to rooms, never broadcast.
"""
import hmac

from flask import request
from flask_socketio import ConnectionRefusedError, join_room

from ..extensions import socketio
from ..models import Visitor
from ..services import realtime
from ..services.network_monitor import monitor
from ..utils.auth import load_session_user, pepper
from ..utils.helpers import classify_ip
from ..utils.tokens import clean_device_id, hash_token


@socketio.on("connect")
def on_connect(auth=None):
    auth = auth if isinstance(auth, dict) else {}
    ip = request.remote_addr or ""
    device = clean_device_id(auth.get("device_id"), "ws-" + request.sid[:12])
    info = {"device_id": device, "ip": ip, "network_type": classify_ip(ip)}

    user = load_session_user()
    if user is not None:
        join_room(f"role:{user.role}")
        join_room(f"user:{user.role}:{user.id}")
        if user.role == "host":
            join_room(f"host:{user.id}")
        if user.role == "security" and user.gate_id:
            join_room(f"gate:{user.gate_id}")
        info.update(role=user.role, user_id=user.id)
    else:
        visitor = _visitor_from_auth(auth)
        if visitor is None:
            raise ConnectionRefusedError("unauthorized")  # rejects the handshake
        join_room(f"visitor:{visitor.public_id}")
        info.update(role="visitor", user_id=None)

    count = monitor.register_ws(request.sid, info)
    realtime.emit_network_status_changed("client_connected", count)


@socketio.on("disconnect")
def on_disconnect(*_args):
    count = monitor.unregister_ws(request.sid)
    realtime.emit_network_status_changed("client_disconnected", count)


def _visitor_from_auth(auth):
    public_id, key = auth.get("public_id"), auth.get("key")
    if not isinstance(public_id, str) or not isinstance(key, str):
        return None
    visitor = Visitor.query.filter_by(public_id=public_id).first()
    if visitor is None:
        return None
    if hmac.compare_digest(hash_token(key, pepper()), visitor.access_key_hash):
        return visitor
    return None
