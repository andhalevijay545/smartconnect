"""QR pass management: issue, look up, validate and draw QR codes."""
import base64
import io
from datetime import timedelta

import qrcode
from flask import current_app

from ..extensions import db
from ..models import QRPass
from ..utils.auth import pepper
from ..utils.helpers import utcnow
from ..utils.tokens import extract_token, hash_token, new_token, qr_payload

# Result codes and the message shown to the guard.
MESSAGES = {
    "valid": "Valid pass.",
    "invalid": "Invalid QR code - not recognised by this system.",
    "revoked": "This pass was replaced by a newer one and can no longer be used.",
    "expired": "This pass has expired.",
    "already_used": "This pass has already been used.",
    "pending_approval": "Host approval is still pending.",
    "rejected": "The host rejected this visit.",
    "not_checked_in": "Visitor is not checked in, so cannot check out.",
}


def verdict(code):
    return {"valid": code == "valid", "code": code, "message": MESSAGES[code]}


def issue_pass(visitor, issued_by):
    """Create a new pass (revoking older ones). Returns (QRPass, raw_token).

    The raw token is returned ONCE so it can be drawn as a QR image; only its
    hash is saved in the database.
    """
    now = utcnow()
    ttl = timedelta(minutes=current_app.config["QR_TTL_MINUTES"])
    expires = max(now, visitor.expected_at) + ttl

    carried_checkin = None
    for old in visitor.passes:
        if not old.revoked:
            if visitor.status == "INSIDE":
                carried_checkin = old.checkin_consumed_at  # only exit remains
            old.revoked = True

    token = new_token()
    qp = QRPass(
        visitor=visitor,
        token_hash=hash_token(token, pepper()),
        issued_at=now,
        expires_at=expires,
        issued_by=issued_by,
        checkin_consumed_at=carried_checkin,
    )
    db.session.add(qp)
    return qp, token


def render_qr_data_uri(token: str) -> str:
    """Draw the QR image and return it as a data: URI (PNG, base64)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=3)
    qr.add_data(qr_payload(token))
    qr.make(fit=True)
    image = qr.make_image(fill_color="#0a2a66", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def find_pass(scanned_text):
    """Look up a pass by the scanned text. Returns (QRPass|None, token|None)."""
    token = extract_token(scanned_text)
    if token is None:
        return None, None
    qp = QRPass.query.filter_by(token_hash=hash_token(token, pepper())).first()
    return qp, token


def evaluate(qp, action, at=None):
    """Decide whether a pass may be used for `action` ('check-in' or 'check-out').

    Read-only: nothing is consumed here. Consumption happens atomically inside
    visit_service so two guards scanning at once cannot both succeed.
    """
    at = at or utcnow()
    if qp is None:
        return verdict("invalid")
    visitor = qp.visitor
    if qp.revoked:
        return verdict("revoked")

    if action == "check-in":
        if qp.checkin_consumed_at is not None or visitor.status in ("INSIDE", "COMPLETED"):
            return verdict("already_used")
        if visitor.status == "REJECTED":
            return verdict("rejected")
        if visitor.status == "PENDING":
            return verdict("pending_approval")
        if at > qp.expires_at:
            return verdict("expired")
        return verdict("valid")

    # check-out: an expired pass must still let a person who is inside leave.
    if qp.checkout_consumed_at is not None:
        return verdict("already_used")
    if qp.checkin_consumed_at is None or visitor.status != "INSIDE":
        return verdict("not_checked_in")
    return verdict("valid")
