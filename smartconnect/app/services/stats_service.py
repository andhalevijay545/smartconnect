"""Live dashboard numbers (Module 6) and gate statistics (Module 11)."""
from datetime import datetime

from flask import current_app

from ..extensions import db
from ..models import Approval, Gate, VisitLog, Visitor
from ..utils.helpers import get_tz, iso, local_day_bounds, to_local


def _tz():
    return get_tz(current_app.config["APP_TIMEZONE"])


def _visits(host_id=None):
    q = db.session.query(VisitLog)
    if host_id:
        q = q.join(Visitor, Visitor.id == VisitLog.visitor_id).filter(Visitor.host_id == host_id)
    return q


def dashboard_stats(host_id=None):
    tz = _tz()
    today = datetime.now(tz).date()
    start, end = local_day_bounds(today, tz)

    inside = _visits(host_id).filter(VisitLog.check_out_at.is_(None)).count()
    in_rows = _visits(host_id).filter(VisitLog.check_in_at >= start, VisitLog.check_in_at < end).all()
    out_count = _visits(host_id).filter(VisitLog.check_out_at >= start, VisitLog.check_out_at < end).count()

    hourly = [0] * 24
    for v in in_rows:
        hourly[to_local(v.check_in_at, tz).hour] += 1

    pending = db.session.query(Approval).filter(Approval.status == "PENDING")
    registered = db.session.query(Visitor).filter(Visitor.created_at >= start, Visitor.created_at < end)
    expected = db.session.query(Visitor).filter(
        Visitor.expected_at >= start, Visitor.expected_at < end,
        Visitor.status.in_(("PENDING", "APPROVED")))
    status_q = db.session.query(Visitor.status, db.func.count(Visitor.id))
    if host_id:
        pending = pending.filter(Approval.host_id == host_id)
        registered = registered.filter(Visitor.host_id == host_id)
        expected = expected.filter(Visitor.host_id == host_id)
        status_q = status_q.filter(Visitor.host_id == host_id)
    status_counts = {s: 0 for s in ("PENDING", "APPROVED", "REJECTED", "INSIDE", "COMPLETED")}
    status_counts.update({s: n for s, n in status_q.group_by(Visitor.status).all()})

    return {
        "date": today.isoformat(),
        "inside_now": inside,
        "live_visitor_count": inside,
        "today_check_ins": len(in_rows),
        "today_check_outs": out_count,
        "pending_approvals": pending.count(),
        "registered_today": registered.count(),
        "expected_today": expected.count(),
        "hourly_check_ins": hourly,
        "status_counts": status_counts,
        "gates": gate_stats(host_id),
        "recent": recent_activity(host_id),
    }


def gate_stats(host_id=None):
    tz = _tz()
    start, end = local_day_bounds(datetime.now(tz).date(), tz)
    rows = []
    for gate in Gate.query.order_by(Gate.name).all():
        base = _visits(host_id)
        rows.append({
            "gate_id": gate.id,
            "name": gate.name,
            "is_active": gate.is_active,
            "inside_now": base.filter(VisitLog.check_in_gate_id == gate.id,
                                      VisitLog.check_out_at.is_(None)).count(),
            "check_ins_today": _visits(host_id).filter(
                VisitLog.check_in_gate_id == gate.id,
                VisitLog.check_in_at >= start, VisitLog.check_in_at < end).count(),
            "check_outs_today": _visits(host_id).filter(
                VisitLog.check_out_gate_id == gate.id,
                VisitLog.check_out_at >= start, VisitLog.check_out_at < end).count(),
            "check_ins_total": _visits(host_id).filter(VisitLog.check_in_gate_id == gate.id).count(),
        })
    return rows


def recent_activity(host_id=None, limit=15):
    events = []

    vq = Visitor.query.order_by(Visitor.created_at.desc())
    if host_id:
        vq = vq.filter(Visitor.host_id == host_id)
    for v in vq.limit(10):
        events.append({"type": "registered", "at": v.created_at, "name": v.full_name,
                       "detail": f"to meet {v.host.full_name}" if v.host else ""})

    for log in _visits(host_id).order_by(VisitLog.check_in_at.desc()).limit(10):
        events.append({"type": "check_in", "at": log.check_in_at, "name": log.visitor.full_name,
                       "detail": log.check_in_gate.name if log.check_in_gate else ""})
    for log in (_visits(host_id).filter(VisitLog.check_out_at.isnot(None))
                .order_by(VisitLog.check_out_at.desc()).limit(10)):
        events.append({"type": "check_out", "at": log.check_out_at, "name": log.visitor.full_name,
                       "detail": log.check_out_gate.name if log.check_out_gate else ""})

    aq = Approval.query.filter(Approval.decided_at.isnot(None)).order_by(Approval.decided_at.desc())
    if host_id:
        aq = aq.filter(Approval.host_id == host_id)
    for a in aq.limit(10):
        events.append({"type": a.status.lower(), "at": a.decided_at, "name": a.visitor.full_name,
                       "detail": a.remarks or ""})

    events.sort(key=lambda e: e["at"], reverse=True)
    return [dict(e, at=iso(e["at"])) for e in events[:limit]]
