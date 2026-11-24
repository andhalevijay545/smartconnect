"""POST /api/qr/generate and POST /api/qr/verify"""
from flask import Blueprint, g

from ..extensions import db
from ..models import Visitor
from ..services import audit_service, qr_service, visit_service
from ..utils.auth import csrf_ok, load_session_user, login_required, visitor_from_key
from ..utils.helpers import iso, utcnow
from ..utils.responses import api_error, api_ok, json_body
from ..utils.serializers import visitor_dict

bp = Blueprint("qr", __name__, url_prefix="/api/qr")


@bp.post("/generate")
def generate():
    """(Re)issue a QR pass. Allowed for: the visitor (access key), their host, or an admin.

    Issuing a new pass revokes the previous one, so a lost/shared QR stops working.
    """
    data = json_body()
    public_id = data.get("visitor_id")
    if not isinstance(public_id, str):
        return api_error("bad_request", "visitor_id is required.", 400)

    user = load_session_user()
    if user is not None:
        if user.role == "security":
            return api_error("forbidden", "Security staff cannot issue passes.", 403)
        if not csrf_ok():
            return api_error("csrf_failed", "Missing or invalid CSRF token.", 403)
        visitor = Visitor.query.filter_by(public_id=public_id).first()
        if visitor is None or (user.role == "host" and visitor.host_id != user.id):
            return api_error("not_found", "Visitor not found.", 404)
        issued_by = f"{user.role}:{user.id}"
    else:
        visitor = visitor_from_key(public_id)
        if visitor is None:
            return api_error("unauthorized", "Valid login or visitor access key required.", 401)
        issued_by = "visitor"

    if visitor.status in ("REJECTED", "COMPLETED"):
        return api_error("not_allowed", f"No new pass can be issued for a {visitor.status.lower()} visit.", 409)

    qp, token = qr_service.issue_pass(visitor, issued_by)
    audit_service.log("qr.generate", actor=user, actor_type="visitor" if user is None else None,
                      entity_type="visitor", entity_id=visitor.public_id)
    db.session.commit()
    return api_ok({
        "visitor_id": visitor.public_id,
        "qr": {"image": qr_service.render_qr_data_uri(token), "expires_at": iso(qp.expires_at)},
    }, 201)


@bp.post("/verify")
@login_required("security", "admin")
def verify():
    """Check a scanned QR WITHOUT using it up. Returns valid / expired / invalid / already_used ..."""
    data = json_body()
    token = data.get("token")
    action = data.get("action", "check-in")
    if not isinstance(token, str) or not token or len(token) > 300:
        return api_error("bad_request", "token is required.", 400)
    if action not in ("check-in", "check-out"):
        return api_error("bad_request", "action must be 'check-in' or 'check-out'.", 400)

    check, qp = visit_service.verify(token, action)
    audit_service.log("qr.verify", actor=g.user, entity_type="qr",
                      details=f"action={action} result={check['code']}", commit=True)
    body = dict(check, action=action,
                visitor=visitor_dict(qp.visitor, g.user.role, utcnow(), detail=True) if qp else None)
    return api_ok(body)
