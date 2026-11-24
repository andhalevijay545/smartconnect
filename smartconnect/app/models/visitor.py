"""Visitor-related tables: Visitor, QRPass, Approval, VisitLog."""
import uuid

from sqlalchemy import text

from ..extensions import db
from ..utils.helpers import utcnow

# Visitor lifecycle:  PENDING -> APPROVED -> INSIDE -> COMPLETED   (or PENDING -> REJECTED)
VISITOR_STATUSES = ("PENDING", "APPROVED", "REJECTED", "INSIDE", "COMPLETED")
APPROVAL_STATUSES = ("PENDING", "APPROVED", "REJECTED")


def _new_public_id() -> str:
    return uuid.uuid4().hex


class Visitor(db.Model):
    __tablename__ = "visitors"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','INSIDE','COMPLETED')",
            name="ck_visitor_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Random public identifier used in URLs/APIs so ids cannot be guessed in order.
    public_id = db.Column(db.String(32), unique=True, nullable=False, default=_new_public_id)
    full_name = db.Column(db.String(100), nullable=False)
    mobile = db.Column(db.String(20), nullable=False, index=True)
    email = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(255), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    host_id = db.Column(db.Integer, db.ForeignKey("hosts.id"), nullable=False, index=True)
    expected_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(12), nullable=False, default="PENDING", index=True)
    access_key_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    department = db.relationship("Department")
    host = db.relationship("Host")
    approval = db.relationship("Approval", back_populates="visitor", uselist=False)
    passes = db.relationship("QRPass", back_populates="visitor", order_by="QRPass.id")
    visits = db.relationship("VisitLog", back_populates="visitor", order_by="VisitLog.id")


class QRPass(db.Model):
    """One QR pass. Only the HASH of the secret token is stored.

    A pass is one-time *per phase*: it can be consumed once for entry and once
    for exit.  After both, it is "used up".
    """

    __tablename__ = "qr_passes"

    id = db.Column(db.Integer, primary_key=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey("visitors.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    issued_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)
    checkin_consumed_at = db.Column(db.DateTime)
    checkout_consumed_at = db.Column(db.DateTime)
    issued_by = db.Column(db.String(40), nullable=False, default="visitor")

    visitor = db.relationship("Visitor", back_populates="passes")


class Approval(db.Model):
    __tablename__ = "approvals"
    __table_args__ = (
        db.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED')", name="ck_approval_status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey("visitors.id"), unique=True, nullable=False)
    host_id = db.Column(db.Integer, db.ForeignKey("hosts.id"), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default="PENDING", index=True)
    remarks = db.Column(db.String(255))
    requested_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    decided_at = db.Column(db.DateTime)
    decided_by = db.Column(db.String(40))  # e.g. "host:3" or "admin:1"

    visitor = db.relationship("Visitor", back_populates="approval")
    host = db.relationship("Host")


class VisitLog(db.Model):
    """One physical visit: a check-in and (later) a check-out."""

    __tablename__ = "visit_logs"
    __table_args__ = (
        db.CheckConstraint(
            "check_out_at IS NULL OR check_out_at >= check_in_at", name="ck_visit_times"
        ),
        # Database-level guard: a visitor can have only ONE open (not checked-out) visit.
        db.Index(
            "uq_visit_one_open",
            "visitor_id",
            unique=True,
            sqlite_where=text("check_out_at IS NULL"),
            postgresql_where=text("check_out_at IS NULL"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    visitor_id = db.Column(db.Integer, db.ForeignKey("visitors.id"), nullable=False, index=True)
    qr_pass_id = db.Column(db.Integer, db.ForeignKey("qr_passes.id"))
    check_in_at = db.Column(db.DateTime, nullable=False, index=True)
    check_out_at = db.Column(db.DateTime, index=True)
    check_in_gate_id = db.Column(db.Integer, db.ForeignKey("gates.id"), nullable=False, index=True)
    check_out_gate_id = db.Column(db.Integer, db.ForeignKey("gates.id"))
    check_in_staff_id = db.Column(db.Integer, db.ForeignKey("security_staff.id"), nullable=False)
    check_out_staff_id = db.Column(db.Integer, db.ForeignKey("security_staff.id"))
    source = db.Column(db.String(12), nullable=False, default="online")  # online | offline_sync

    visitor = db.relationship("Visitor", back_populates="visits")
    check_in_gate = db.relationship("Gate", foreign_keys=[check_in_gate_id])
    check_out_gate = db.relationship("Gate", foreign_keys=[check_out_gate_id])
    check_in_staff = db.relationship("SecurityStaff", foreign_keys=[check_in_staff_id])
    check_out_staff = db.relationship("SecurityStaff", foreign_keys=[check_out_staff_id])
