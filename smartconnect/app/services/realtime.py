"""Real-time (WebSocket) event emitters.

Rooms decide WHO receives an event - this is how we make sure only authorised
users see it:

    role:admin        every admin
    role:security     every security officer
    host:<id>         one host employee (only their own visitors)
    visitor:<pid>     one visitor (only their own pass)
    user:<role>:<id>  one specific staff member

Event payloads never contain contact details (phone, e-mail, address).
"""
from ..extensions import socketio
from ..utils.helpers import iso, utcnow
from ..utils.serializers import visitor_brief


def _to_rooms(event, payload, rooms):
    for room in rooms:
        socketio.emit(event, payload, to=room)


def emit_visitor_registered(visitor):
    payload = visitor_brief(visitor)
    _to_rooms("visitor_registered", payload,
              ["role:admin", "role:security", f"host:{visitor.host_id}"])


def emit_approval_updated(visitor, approval):
    payload = visitor_brief(visitor)
    payload.update({"approval_id": approval.id, "approval_status": approval.status,
                    "remarks": approval.remarks})
    _to_rooms("approval_updated", payload,
              ["role:admin", "role:security", f"host:{visitor.host_id}",
               f"visitor:{visitor.public_id}"])


def emit_checked_in(visitor, visit):
    payload = visitor_brief(visitor)
    payload.update({"visit_id": visit.id, "at": iso(visit.check_in_at),
                    "gate": visit.check_in_gate.name if visit.check_in_gate else None,
                    "source": visit.source})
    _to_rooms("visitor_checked_in", payload,
              ["role:admin", "role:security", f"host:{visitor.host_id}",
               f"visitor:{visitor.public_id}"])


def emit_checked_out(visitor, visit):
    payload = visitor_brief(visitor)
    payload.update({"visit_id": visit.id, "at": iso(visit.check_out_at),
                    "gate": visit.check_out_gate.name if visit.check_out_gate else None,
                    "source": visit.source})
    _to_rooms("visitor_checked_out", payload,
              ["role:admin", "role:security", f"host:{visitor.host_id}",
               f"visitor:{visitor.public_id}"])


def emit_network_status_changed(reason, ws_clients):
    socketio.emit("network_status_changed",
                  {"reason": reason, "ws_clients": ws_clients, "at": iso(utcnow())},
                  to="role:admin")


def emit_sync_completed(staff, device_id, summary):
    payload = dict(summary, device_id=device_id, at=iso(utcnow()))
    _to_rooms("sync_completed", payload, ["role:admin", f"user:security:{staff.id}"])
