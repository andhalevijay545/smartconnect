"""Reports and analytics (daily / weekly / monthly) and CSV export."""
import csv
import io
from datetime import timedelta

from flask import current_app

from ..models import Approval, Department, Gate, VisitLog, Visitor
from ..utils.helpers import csv_safe, get_tz, iso, period_bounds, to_local

CSV_COLUMNS = ["Visitor", "Mobile", "Department", "Host", "Purpose", "Status",
               "Expected (UTC)", "Check-in (UTC)", "Check-out (UTC)",
               "Entry gate", "Exit gate", "Duration (min)"]


def build_report(period, anchor):
    tz = get_tz(current_app.config["APP_TIMEZONE"])
    label, start, end, first, last = period_bounds(period, anchor, tz)

    registered = Visitor.query.filter(Visitor.created_at >= start, Visitor.created_at < end).all()
    visits = VisitLog.query.filter(VisitLog.check_in_at >= start, VisitLog.check_in_at < end) \
        .order_by(VisitLog.check_in_at).all()
    outs = VisitLog.query.filter(VisitLog.check_out_at >= start, VisitLog.check_out_at < end).count()
    decided = Approval.query.filter(Approval.decided_at >= start, Approval.decided_at < end).all()

    # --- department-wise -------------------------------------------------
    dept = {d.id: {"department": d.name, "registered": 0, "check_ins": 0}
            for d in Department.query.order_by(Department.name)}
    for v in registered:
        dept[v.department_id]["registered"] += 1
    for log in visits:
        dept[log.visitor.department_id]["check_ins"] += 1

    # --- gate-wise ---------------------------------------------------------
    gates = {g.id: {"gate": g.name, "check_ins": 0, "check_outs": 0}
             for g in Gate.query.order_by(Gate.name)}
    for log in visits:
        gates[log.check_in_gate_id]["check_ins"] += 1
    for log in VisitLog.query.filter(VisitLog.check_out_at >= start, VisitLog.check_out_at < end):
        if log.check_out_gate_id in gates:
            gates[log.check_out_gate_id]["check_outs"] += 1

    # --- per-day series ------------------------------------------------------
    days, d = [], first
    while d <= last:
        days.append(d)
        d += timedelta(days=1)
    series = {x.isoformat(): {"date": x.isoformat(), "registered": 0, "check_ins": 0} for x in days}
    for v in registered:
        series[to_local(v.created_at, tz).date().isoformat()]["registered"] += 1
    for log in visits:
        series[to_local(log.check_in_at, tz).date().isoformat()]["check_ins"] += 1

    durations = [(l.check_out_at - l.check_in_at).total_seconds() / 60
                 for l in visits if l.check_out_at]
    return {
        "period": period,
        "label": label,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "summary": {
            "registered": len(registered),
            "approved": sum(1 for a in decided if a.status == "APPROVED"),
            "rejected": sum(1 for a in decided if a.status == "REJECTED"),
            "check_ins": len(visits),
            "check_outs": outs,
            "avg_visit_minutes": round(sum(durations) / len(durations), 1) if durations else 0,
        },
        "by_department": list(dept.values()),
        "by_gate": list(gates.values()),
        "by_day": list(series.values()),
        "history": [_row(l) for l in visits[:1000]],
    }


def _row(log):
    v = log.visitor
    minutes = None
    if log.check_out_at:
        minutes = round((log.check_out_at - log.check_in_at).total_seconds() / 60, 1)
    return {
        "visitor": v.full_name, "mobile": v.mobile,
        "department": v.department.name if v.department else "",
        "host": v.host.full_name if v.host else "",
        "purpose": v.purpose, "status": v.status,
        "expected_at": iso(v.expected_at),
        "check_in_at": iso(log.check_in_at), "check_out_at": iso(log.check_out_at),
        "entry_gate": log.check_in_gate.name if log.check_in_gate else "",
        "exit_gate": log.check_out_gate.name if log.check_out_gate else "",
        "duration_min": minutes,
    }


def report_to_csv(report) -> str:
    """Return the report as CSV text (formula-injection safe)."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["SmartConnect report", report["period"], report["label"]])
    for key, value in report["summary"].items():
        w.writerow([key.replace("_", " ").title(), value])
    w.writerow([])
    w.writerow(CSV_COLUMNS)
    for r in report["history"]:
        w.writerow([csv_safe(x) if x is not None else "" for x in (
            r["visitor"], r["mobile"], r["department"], r["host"], r["purpose"], r["status"],
            r["expected_at"], r["check_in_at"], r["check_out_at"], r["entry_gate"],
            r["exit_gate"], r["duration_min"])])
    w.writerow([])
    w.writerow(["Department", "Registered", "Check-ins"])
    for r in report["by_department"]:
        w.writerow([csv_safe(r["department"]), r["registered"], r["check_ins"]])
    w.writerow([])
    w.writerow(["Gate", "Check-ins", "Check-outs"])
    for r in report["by_gate"]:
        w.writerow([csv_safe(r["gate"]), r["check_ins"], r["check_outs"]])
    return out.getvalue()
