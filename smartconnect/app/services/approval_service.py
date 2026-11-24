"""Host approval workflow."""
from ..extensions import db
from ..models import Approval
from ..utils.helpers import utcnow
from . import audit_service, realtime


class ApprovalError(Exception):
    pass


def create_for_visitor(visitor):
    approval = Approval(visitor=visitor, host_id=visitor.host_id, status="PENDING")
    db.session.add(approval)
    return approval


def decide(approval, decision, remarks, actor):
    """Approve or reject. `decision` is 'approve' or 'reject'."""
    if decision not in ("approve", "reject"):
        raise ApprovalError("decision must be 'approve' or 'reject'.")
    visitor = approval.visitor
    if approval.status != "PENDING" or visitor.status != "PENDING":
        raise ApprovalError("This request has already been decided.")

    approval.status = "APPROVED" if decision == "approve" else "REJECTED"
    approval.remarks = (remarks or "").strip()[:255] or None
    approval.decided_at = utcnow()
    approval.decided_by = f"{actor.role}:{actor.id}"
    visitor.status = approval.status
    audit_service.log(f"approval.{decision}", actor=actor, entity_type="visitor",
                      entity_id=visitor.public_id)
    db.session.commit()
    realtime.emit_approval_updated(visitor, approval)
    return approval
