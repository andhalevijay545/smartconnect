"""POST /api/sync - upload operations that were queued while offline."""
from flask import Blueprint, current_app, g, request

from ..models import SyncOperation
from ..services import sync_service
from ..utils.auth import login_required
from ..utils.helpers import iso
from ..utils.responses import api_error, api_ok, json_body
from ..utils.tokens import clean_device_id

bp = Blueprint("sync", __name__, url_prefix="/api/sync")


@bp.post("")
@login_required("security")
def sync():
    data = json_body()
    operations = data.get("operations")
    limit = current_app.config["SYNC_MAX_BATCH"]
    if not isinstance(operations, list) or not operations:
        return api_error("bad_request", "operations must be a non-empty list.", 400)
    if len(operations) > limit:
        return api_error("too_large", f"At most {limit} operations per request.", 413)
    if not all(isinstance(op, dict) for op in operations):
        return api_error("bad_request", "Every operation must be an object.", 400)

    fallback = clean_device_id(request.headers.get("X-Device-Id"), "unknown-device")
    device = clean_device_id(data.get("device_id"), fallback)
    gate_id = data.get("gate_id") if isinstance(data.get("gate_id"), int) else None
    results, summary = sync_service.process_batch(operations, g.user, device, gate_id)
    return api_ok({"results": results, "summary": summary})


@bp.get("/operations")
@login_required("admin", "security")
def list_operations():
    """Server-side record of operations (admin: all, security: own). No QR tokens."""
    q = SyncOperation.query.order_by(SyncOperation.id.desc())
    if g.user.role == "security":
        q = q.filter(SyncOperation.staff_id == g.user.id)
    return api_ok({"items": [{
        "operation_id": o.operation_id, "device_id": o.device_id, "type": o.op_type,
        "channel": o.channel, "status": o.status, "code": o.result_code,
        "received_at": iso(o.received_at), "processed_at": iso(o.processed_at),
    } for o in q.limit(100)]})
