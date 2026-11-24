"""Offline synchronisation and idempotent scan operations.

How idempotency works (the key idea for "no duplicate operations")
------------------------------------------------------------------
1. The phone creates a random `operation_id` the moment a scan happens.
2. The server first tries to INSERT a row with that id (it is UNIQUE).
3. If the insert works -> this is the first time we see the operation -> run it
   and store the result.
4. If the insert fails (or the row already exists) -> we already handled it, so
   we simply return the stored result.  Retrying is therefore always safe, even
   when a network failure hid the first response.

The raw QR token is used in memory only; only its hash is saved.
"""
import json
from datetime import timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import SyncOperation
from ..utils.auth import pepper
from ..utils.helpers import parse_iso_dt, utcnow
from ..utils.tokens import extract_token, hash_token, valid_operation_id
from . import realtime, visit_service

VALID_TYPES = ("check-in", "check-out")


def _bad(op_id, code, message):
    return {"operation_id": op_id, "status": "error", "replayed": False,
            "result": {"ok": False, "code": code, "message": message}}


def _stored_result(rec, replayed):
    try:
        payload = json.loads(rec.result_json) if rec.result_json else {}
    except ValueError:
        payload = {}
    if rec.status == "PENDING":  # first request still running
        payload = {"ok": False, "code": "in_progress", "message": "Operation is still being processed."}
    return {"operation_id": rec.operation_id, "status": rec.status.lower(),
            "replayed": replayed, "result": payload}


def apply_operation(op, staff, device_id, channel="sync", gate_id=None):
    """Run ONE operation exactly once. `op` = {operation_id, type, token, scanned_at?}."""
    cfg = current_app.config
    op_id = op.get("operation_id")
    if not valid_operation_id(op_id):
        return _bad(str(op_id)[:64], "bad_operation_id", "operation_id must be 8-64 letters, digits, - or _.")
    op_type = op.get("type")
    if op_type not in VALID_TYPES:
        return _bad(op_id, "bad_type", "type must be 'check-in' or 'check-out'.")

    # ---- Replay protection: have we seen this operation before? ----------
    existing = SyncOperation.query.filter_by(operation_id=op_id).first()
    if existing is not None:
        if existing.staff_id != staff.id:
            return _bad(op_id, "operation_conflict", "This operation id belongs to another user.")
        return _stored_result(existing, replayed=True)

    token = extract_token(op.get("token"))
    token_hash = hash_token(token, pepper()) if token else hash_token(str(op.get("token"))[:200], pepper())

    now = utcnow()
    scanned_at = parse_iso_dt(op.get("scanned_at")) if op.get("scanned_at") else None
    if scanned_at is not None and scanned_at > now:
        scanned_at = now  # a phone clock running fast cannot put events in the future
    effective = scanned_at or now

    rec = SyncOperation(operation_id=op_id, device_id=device_id, staff_id=staff.id, op_type=op_type,
                        token_hash=token_hash, channel=channel, status="PENDING",
                        client_created_at=scanned_at, received_at=now)
    db.session.add(rec)
    try:
        db.session.commit()  # the UNIQUE constraint makes this the "claim" step
    except IntegrityError:
        db.session.rollback()
        existing = SyncOperation.query.filter_by(operation_id=op_id).first()
        return _stored_result(existing, replayed=True) if existing else _bad(op_id, "conflict", "Try again.")

    # ---- Execute -----------------------------------------------------------
    max_age = timedelta(hours=cfg["SYNC_MAX_AGE_HOURS"])
    if channel == "sync" and scanned_at is not None and now - scanned_at > max_age:
        res = visit_service.result(False, "stale")
    else:
        res = visit_service.process_scan(
            op_type, op.get("token"), staff, gate_id=gate_id, at=effective,
            source="offline_sync" if channel == "sync" else "online")

    rec = db.session.get(SyncOperation, rec.id)
    rec.status = "SUCCESS" if res["ok"] else "FAILED"
    rec.result_code = res["code"]
    rec.processed_at = utcnow()
    rec.result_json = json.dumps({
        "ok": res["ok"], "code": res["code"], "message": res["message"],
        "visitor_id": res["visitor"]["public_id"] if res.get("visitor") else None,
    })
    db.session.commit()

    out = {"operation_id": op_id, "status": rec.status.lower(), "replayed": False, "result": res}
    return out


def process_batch(operations, staff, device_id, gate_id=None):
    """Apply a list of offline operations in the order they happened."""
    ordered = sorted(operations, key=lambda o: str(o.get("scanned_at") or ""))
    results = [apply_operation(op, staff, device_id, "sync", gate_id) for op in ordered]
    summary = {
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] in ("failed", "error")),
        "replayed": sum(1 for r in results if r["replayed"]),
    }
    realtime.emit_sync_completed(staff, device_id, summary)
    return results, summary


def sync_status_counts():
    """Real counts from the database for the monitoring dashboard."""
    rows = db.session.query(SyncOperation.status, db.func.count(SyncOperation.id)).group_by(
        SyncOperation.status).all()
    counts = {"PENDING": 0, "SUCCESS": 0, "FAILED": 0}
    counts.update({status: n for status, n in rows})
    last = db.session.query(db.func.max(SyncOperation.processed_at)).filter(
        SyncOperation.channel == "sync").scalar()
    return counts, last
