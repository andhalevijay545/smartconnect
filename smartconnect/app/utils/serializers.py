"""Turn database objects into JSON-friendly dictionaries (with privacy rules)."""
from .helpers import iso, mask_mobile


def user_dict(user):
    data = {
        "id": user.id,
        "role": user.role,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "is_active": user.is_active,
        "created_at": iso(user.created_at),
        "last_login_at": iso(user.last_login_at),
    }
    if user.role == "security":
        data["gate_id"] = user.gate_id
        data["gate_name"] = user.gate.name if user.gate else None
    if user.role == "host":
        data["department_id"] = user.department_id
        data["department_name"] = user.department.name if user.department else None
        data["phone"] = user.phone
    return data


def gate_dict(gate):
    return {"id": gate.id, "name": gate.name, "location": gate.location, "is_active": gate.is_active}


def department_dict(dep):
    return {"id": dep.id, "name": dep.name, "is_active": dep.is_active}


def visit_dict(v):
    return {
        "id": v.id,
        "check_in_at": iso(v.check_in_at),
        "check_out_at": iso(v.check_out_at),
        "check_in_gate": v.check_in_gate.name if v.check_in_gate else None,
        "check_out_gate": v.check_out_gate.name if v.check_out_gate else None,
        "source": v.source,
    }


def pass_state(qr_pass, now):
    """Human readable state of a QR pass (never includes the token)."""
    if qr_pass is None:
        return None
    if qr_pass.revoked:
        state = "revoked"
    elif qr_pass.checkout_consumed_at:
        state = "used"
    elif qr_pass.checkin_consumed_at:
        state = "in_use"  # checked in, only exit remains
    elif qr_pass.expires_at < now:
        state = "expired"
    else:
        state = "active"
    return {
        "state": state,
        "issued_at": iso(qr_pass.issued_at),
        "expires_at": iso(qr_pass.expires_at),
        "checkin_used": qr_pass.checkin_consumed_at is not None,
        "checkout_used": qr_pass.checkout_consumed_at is not None,
    }


def visitor_dict(v, role, now=None, detail=False):
    """Serialise a visitor for a given viewer role.

    Privacy: security staff see a masked mobile number and no e-mail/address.
    Admin, host and the visitor themselves (role 'visitor') see everything.
    """
    full_contact = role in ("admin", "host", "visitor")
    data = {
        "public_id": v.public_id,
        "full_name": v.full_name,
        "mobile": v.mobile if full_contact else mask_mobile(v.mobile),
        "purpose": v.purpose,
        "department": v.department.name if v.department else None,
        "host": v.host.full_name if v.host else None,
        "host_id": v.host_id,
        "department_id": v.department_id,
        "expected_at": iso(v.expected_at),
        "status": v.status,
        "created_at": iso(v.created_at),
    }
    if full_contact:
        data["email"] = v.email
        data["address"] = v.address
    last = v.visits[-1] if v.visits else None
    data["last_check_in_at"] = iso(last.check_in_at) if last else None
    data["last_check_out_at"] = iso(last.check_out_at) if last else None
    data["last_gate"] = last.check_in_gate.name if last and last.check_in_gate else None
    if detail:
        a = v.approval
        data["approval"] = (
            {"id": a.id, "status": a.status, "remarks": a.remarks, "decided_at": iso(a.decided_at)}
            if a else None
        )
        active = v.passes[-1] if v.passes else None
        data["pass"] = pass_state(active, now) if now else None
        data["visits"] = [visit_dict(x) for x in v.visits]
    return data


def visitor_brief(v):
    """Minimal payload for real-time events (no contact details)."""
    return {
        "public_id": v.public_id,
        "full_name": v.full_name,
        "department": v.department.name if v.department else None,
        "host": v.host.full_name if v.host else None,
        "host_id": v.host_id,
        "status": v.status,
        "expected_at": iso(v.expected_at),
    }
