"""Host approval requests."""
from flask import Blueprint, g, request

from ..extensions import db
from ..models import Approval, Visitor
from ..services import approval_service
from ..utils.auth import login_required
from ..utils.helpers import iso, utcnow
from ..utils.responses import api_error, api_ok, json_body
from ..utils.serializers import visitor_dict

bp = Blueprint("approvals", __name__, url_prefix="/api/approvals")


def _approval_dict(a, role):
    return {
        "id": a.id, "status": a.status, "remarks": a.remarks,
        "requested_at": iso(a.requested_at), "decided_at": iso(a.decided_at),
        "visitor": visitor_dict(a.visitor, role, utcnow()),
    }


@bp.get("")
@login_required("host", "admin")
def list_approvals():
    status = request.args.get("status", "PENDING").upper()
    q = Approval.query.join(Visitor, Visitor.id == Approval.visitor_id)
    if g.user.role == "host":
        q = q.filter(Approval.host_id == g.user.id)
    if status in ("PENDING", "APPROVED", "REJECTED"):
        q = q.filter(Approval.status == status)
    items = q.order_by(Visitor.expected_at.asc()).limit(200).all()
    return api_ok({"items": [_approval_dict(a, g.user.role) for a in items]})


@bp.post("/<int:approval_id>/decision")
@login_required("host", "admin")
def decide(approval_id):
    approval = db.session.get(Approval, approval_id)
    if approval is None or (g.user.role == "host" and approval.host_id != g.user.id):
        return api_error("not_found", "Approval request not found.", 404)
    data = json_body()
    try:
        approval_service.decide(approval, data.get("decision"), data.get("remarks"), g.user)
    except approval_service.ApprovalError as err:
        return api_error("not_allowed", str(err), 409)
    return api_ok({"approval": _approval_dict(approval, g.user.role)})
