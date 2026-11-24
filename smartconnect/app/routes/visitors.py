"""Visitor registration, listing, details, check-in and check-out."""
from datetime import datetime

from flask import Blueprint, current_app, g, request
from sqlalchemy import or_

from ..extensions import db
from ..models import Department, Host, Visitor
from ..services import approval_service, audit_service, qr_service, realtime, sync_service, visit_service
from ..utils.auth import load_session_user, login_required, pepper, visitor_from_key
from ..utils.helpers import get_tz, iso, local_day_bounds, utcnow
from ..utils.ratelimit import register_limiter
from ..utils.responses import api_error, api_ok, json_body
from ..utils.serializers import visitor_dict
from ..utils.tokens import clean_device_id, hash_token, new_access_key
from ..utils.validators import validate_visitor_payload

bp = Blueprint("visitors", __name__, url_prefix="/api/visitors")

# HTTP status used when a scan is refused.
HTTP_FOR_CODE = {
    "invalid": 404, "expired": 410, "stale": 410, "already_used": 409, "revoked": 409,
    "pending_approval": 409, "rejected": 403, "not_checked_in": 409,
    "no_gate": 400, "bad_gate": 400, "in_progress": 409,
}
VALID_STATUSES = ("PENDING", "APPROVED", "REJECTED", "INSIDE", "COMPLETED")


@bp.post("/register")
def register():
    """Public endpoint: a visitor registers and immediately receives a QR pass."""
    cfg = current_app.config
    if not register_limiter.allow(f"reg|{request.remote_addr}", cfg["REGISTER_RATE_LIMIT"],
                                  cfg["REGISTER_RATE_WINDOW"]):
        return api_error("rate_limited", "Too many registrations from this device. Try later.", 429)

    clean, errors = validate_visitor_payload(json_body(), utcnow(), get_tz(cfg["APP_TIMEZONE"]))
    if not errors:
        dept = db.session.get(Department, clean["department_id"])
        host = db.session.get(Host, clean["host_id"])
        if dept is None or not dept.is_active:
            errors["department_id"] = "Selected department does not exist."
        if host is None or not host.is_active:
            errors["host_id"] = "Selected host does not exist."
        elif dept is not None and host.department_id != dept.id:
            errors["host_id"] = "Selected host does not belong to this department."
    if errors:
        return api_error("validation_error", "Please correct the highlighted fields.", 422, errors)

    access_key = new_access_key()
    visitor = Visitor(access_key_hash=hash_token(access_key, pepper()), status="PENDING", **clean)
    db.session.add(visitor)
    db.session.flush()  # assigns visitor.id / public_id
    approval_service.create_for_visitor(visitor)
    qp, token = qr_service.issue_pass(visitor, "visitor")
    audit_service.log("visitor.register", actor_type="visitor", entity_type="visitor",
                      entity_id=visitor.public_id)
    db.session.commit()

    realtime.emit_visitor_registered(visitor)
    return api_ok({
        "visitor": visitor_dict(visitor, "visitor", utcnow(), detail=True),
        "access_key": access_key,  # shown once; only its hash is stored
        "qr": {"image": qr_service.render_qr_data_uri(token), "expires_at": iso(qp.expires_at)},
    }, 201)


@bp.get("")
@login_required("admin", "security", "host")
def list_visitors():
    q = Visitor.query
    if g.user.role == "host":
        q = q.filter(Visitor.host_id == g.user.id)  # hosts only ever see their own visitors

    search = request.args.get("q", "").strip()[:60]
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Visitor.full_name.ilike(like), Visitor.mobile.like(like),
                         Visitor.purpose.ilike(like), Visitor.public_id == search))
    status = request.args.get("status", "").upper()
    if status in VALID_STATUSES:
        q = q.filter(Visitor.status == status)
    for arg, column in (("department_id", Visitor.department_id), ("host_id", Visitor.host_id)):
        value = request.args.get(arg, type=int)
        if value and not (arg == "host_id" and g.user.role == "host"):
            q = q.filter(column == value)

    tz = get_tz(current_app.config["APP_TIMEZONE"])
    for arg, is_start in (("date_from", True), ("date_to", False)):
        raw = request.args.get(arg)
        if raw:
            try:
                day = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                return api_error("bad_request", f"{arg} must be YYYY-MM-DD.", 400)
            start, end = local_day_bounds(day, tz)
            q = q.filter(Visitor.expected_at >= start) if is_start else q.filter(Visitor.expected_at < end)

    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", 15, type=int), 1), 100)
    result = q.order_by(Visitor.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    now = utcnow()
    return api_ok({
        "items": [visitor_dict(v, g.user.role, now) for v in result.items],
        "page": result.page, "pages": result.pages, "total": result.total,
    })


@bp.get("/<public_id>")
def detail(public_id):
    """Staff (session) or the visitor themselves (X-Visitor-Key header)."""
    user = load_session_user()
    if user is not None:
        visitor = Visitor.query.filter_by(public_id=public_id).first()
        if visitor is None or (user.role == "host" and visitor.host_id != user.id):
            return api_error("not_found", "Visitor not found.", 404)
        viewer = user.role
    else:
        visitor = visitor_from_key(public_id)
        if visitor is None:
            return api_error("unauthorized", "Valid login or visitor access key required.", 401)
        viewer = "visitor"
    return api_ok({"visitor": visitor_dict(visitor, viewer, utcnow(), detail=True)})


# ------------------------------------------------------------------ entry / exit
def _scan(action):
    data = json_body()
    token = data.get("token")
    if not isinstance(token, str) or not token or len(token) > 300:
        return api_error("bad_request", "token is required.", 400)
    gate_id = data.get("gate_id") if isinstance(data.get("gate_id"), int) else None
    op_id = data.get("operation_id")
    device = clean_device_id(request.headers.get("X-Device-Id"), "unknown-device")

    replayed = False
    if op_id is not None:
        # Idempotent path: the same operation_id can be retried safely.
        out = sync_service.apply_operation(
            {"operation_id": op_id, "type": action, "token": token}, g.user, device, "online", gate_id)
        if out["status"] == "error":
            return api_error(out["result"]["code"], out["result"]["message"], 400)
        res, replayed = out["result"], out["replayed"]
    else:
        res = visit_service.process_scan(action, token, g.user, gate_id)

    if res["ok"]:
        return api_ok(dict(res, replayed=replayed))
    return api_error(res["code"], res["message"], HTTP_FOR_CODE.get(res["code"], 409),
                     {"visitor": res.get("visitor"), "replayed": replayed})


@bp.post("/check-in")
@login_required("security")
def check_in():
    return _scan("check-in")


@bp.post("/check-out")
@login_required("security")
def check_out():
    return _scan("check-out")
