"""Visitor entry and exit (check-in / check-out).

Race-condition safety
---------------------
Two guards may scan the same QR at the same moment.  We therefore "consume"
the pass with ONE conditional UPDATE:

    UPDATE qr_passes SET checkin_consumed_at = :now
    WHERE id = :id AND checkin_consumed_at IS NULL

The database guarantees only one request can change the row from NULL, so only
one scan wins.  A unique partial index on visit_logs is a second safety net.
"""
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Gate, QRPass, VisitLog
from ..utils.helpers import utcnow
from ..utils.serializers import visit_dict, visitor_brief
from . import audit_service, qr_service, realtime

EXTRA_MESSAGES = {
    "no_gate": "No gate is assigned to your account. Ask an admin to assign one.",
    "bad_gate": "The selected gate does not exist or is disabled.",
    "stale": "This offline scan is too old to be accepted. Verify the visitor manually.",
}


def result(ok, code, message=None, visitor=None, visit=None):
    return {
        "ok": ok,
        "code": code,
        "message": message or qr_service.MESSAGES.get(code) or EXTRA_MESSAGES.get(code, ""),
        "visitor": visitor_brief(visitor) if visitor is not None else None,
        "visit": visit_dict(visit) if visit is not None else None,
    }


def resolve_gate(staff, gate_id=None):
    """Guards use their assigned gate; unassigned staff must name an active gate."""
    gate = staff.gate if staff.gate_id else None
    if gate is None and gate_id:
        gate = db.session.get(Gate, gate_id)
    if gate is None:
        return None, "no_gate" if not gate_id else "bad_gate"
    if not gate.is_active:
        return None, "bad_gate"
    return gate, None


def verify(raw_token, action):
    """Read-only check used by the scanner screen. Returns (verdict, qr_pass|None)."""
    qp, _ = qr_service.find_pass(raw_token)
    return qr_service.evaluate(qp, action), qp


def process_scan(action, raw_token, staff, gate_id=None, at=None, source="online"):
    """Perform a check-in or check-out. Always returns a result dict (never raises)."""
    qp, _ = qr_service.find_pass(raw_token)
    at = at or utcnow()
    check = qr_service.evaluate(qp, action, at)
    visitor = qp.visitor if qp is not None else None
    if not check["valid"]:
        return result(False, check["code"], visitor=visitor)

    gate, gate_err = resolve_gate(staff, gate_id)
    if gate is None:
        return result(False, gate_err)

    if action == "check-in":
        return _check_in(qp, visitor, staff, gate, at, source)
    return _check_out(qp, visitor, staff, gate, at, source)


def _check_in(qp, visitor, staff, gate, at, source):
    claimed = db.session.execute(
        update(QRPass)
        .where(QRPass.id == qp.id, QRPass.checkin_consumed_at.is_(None), QRPass.revoked.is_(False))
        .values(checkin_consumed_at=at)
    )
    if claimed.rowcount != 1:  # somebody else consumed it first
        db.session.rollback()
        return result(False, "already_used", visitor=visitor)

    visit = VisitLog(visitor_id=visitor.id, qr_pass_id=qp.id, check_in_at=at,
                     check_in_gate_id=gate.id, check_in_staff_id=staff.id, source=source)
    visitor.status = "INSIDE"
    db.session.add(visit)
    audit_service.log("visit.check_in", actor=staff, entity_type="visitor",
                      entity_id=visitor.public_id, details=f"gate={gate.name} source={source}")
    try:
        db.session.commit()
    except IntegrityError:  # unique "one open visit" index fired
        db.session.rollback()
        return result(False, "already_used", visitor=visitor)

    realtime.emit_checked_in(visitor, visit)
    return result(True, "checked_in", "Check-in recorded.", visitor, visit)


def _check_out(qp, visitor, staff, gate, at, source):
    claimed = db.session.execute(
        update(QRPass)
        .where(QRPass.id == qp.id, QRPass.checkout_consumed_at.is_(None),
               QRPass.checkin_consumed_at.isnot(None))
        .values(checkout_consumed_at=at)
    )
    visit = (VisitLog.query.filter_by(visitor_id=visitor.id, check_out_at=None)
             .order_by(VisitLog.id.desc()).first())
    if claimed.rowcount != 1 or visit is None:
        db.session.rollback()
        code = "already_used" if claimed.rowcount != 1 and qp.checkout_consumed_at else "not_checked_in"
        return result(False, code, visitor=visitor)

    visit.check_out_at = max(at, visit.check_in_at)  # never earlier than check-in
    visit.check_out_gate_id = gate.id
    visit.check_out_staff_id = staff.id
    visitor.status = "COMPLETED"
    audit_service.log("visit.check_out", actor=staff, entity_type="visitor",
                      entity_id=visitor.public_id, details=f"gate={gate.name} source={source}")
    db.session.commit()

    realtime.emit_checked_out(visitor, visit)
    return result(True, "checked_out", "Check-out recorded.", visitor, visit)
