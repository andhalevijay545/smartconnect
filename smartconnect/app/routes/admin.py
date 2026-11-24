"""Admin-only: manage staff accounts and read the audit log."""
from flask import Blueprint, g, request
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import ROLE_MODELS, AuditLog, Department, Gate
from ..services import audit_service
from ..utils.auth import login_required
from ..utils.helpers import iso
from ..utils.responses import api_error, api_ok, json_body
from ..utils.serializers import user_dict
from ..utils.validators import (validate_email, validate_full_name, validate_int_id,
                                validate_password, validate_username)

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/users")
@login_required("admin")
def list_users():
    role = request.args.get("role", "security")
    model = ROLE_MODELS.get(role)
    if model is None:
        return api_error("bad_request", "role must be admin, security or host.", 400)
    users = model.query.order_by(model.full_name).all()
    return api_ok({"items": [user_dict(u) for u in users]})


@bp.post("/users")
@login_required("admin")
def create_user():
    data = json_body()
    role = data.get("role")
    model = ROLE_MODELS.get(role)
    if model is None:
        return api_error("validation_error", "role must be admin, security or host.", 422)

    errors, values = {}, {}
    for field, fn in (("username", validate_username), ("full_name", validate_full_name),
                      ("email", validate_email), ("password", validate_password)):
        value, err = fn(data.get(field))
        if err:
            errors[field] = err
        else:
            values[field] = value

    extra = {}
    if role == "host":
        dep_id, err = validate_int_id(data.get("department_id"), "Department")
        if err or db.session.get(Department, dep_id) is None:
            errors["department_id"] = err or "Department does not exist."
        else:
            extra["department_id"] = dep_id
        phone = (data.get("phone") or "").strip()[:20]
        extra["phone"] = phone or None
    if role == "security" and data.get("gate_id") not in (None, ""):
        gate_id, err = validate_int_id(data.get("gate_id"), "Gate")
        if err or db.session.get(Gate, gate_id) is None:
            errors["gate_id"] = err or "Gate does not exist."
        else:
            extra["gate_id"] = gate_id
    if errors:
        return api_error("validation_error", "Please correct the highlighted fields.", 422, errors)

    password = values.pop("password")
    user = model(**values, **extra)
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.flush()
        audit_service.log("user.create", actor=g.user, entity_type=role, entity_id=user.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate", "That username is already taken.", 409)
    return api_ok({"user": user_dict(user)}, 201)


@bp.patch("/users/<role>/<int:user_id>")
@login_required("admin")
def update_user(role, user_id):
    model = ROLE_MODELS.get(role)
    user = db.session.get(model, user_id) if model else None
    if user is None:
        return api_error("not_found", "User not found.", 404)
    data = json_body()
    errors = {}

    if "full_name" in data:
        value, err = validate_full_name(data["full_name"])
        user.full_name = value if not err else user.full_name
        if err:
            errors["full_name"] = err
    if "email" in data:
        value, err = validate_email(data["email"])
        user.email = value if not err else user.email
        if err:
            errors["email"] = err
    if "password" in data and data["password"]:
        value, err = validate_password(data["password"])
        if err:
            errors["password"] = err
        else:
            user.set_password(value)
    if "is_active" in data and isinstance(data["is_active"], bool):
        if not data["is_active"] and role == "admin" and user.id == g.user.id:
            errors["is_active"] = "You cannot deactivate your own account."
        else:
            user.is_active = data["is_active"]
    if role == "security" and "gate_id" in data:
        if data["gate_id"] in (None, ""):
            user.gate_id = None
        elif db.session.get(Gate, data["gate_id"]) is None:
            errors["gate_id"] = "Gate does not exist."
        else:
            user.gate_id = data["gate_id"]
    if role == "host" and "department_id" in data:
        if db.session.get(Department, data["department_id"]) is None:
            errors["department_id"] = "Department does not exist."
        else:
            user.department_id = data["department_id"]

    if errors:
        db.session.rollback()
        return api_error("validation_error", "Please correct the highlighted fields.", 422, errors)
    audit_service.log("user.update", actor=g.user, entity_type=role, entity_id=user.id,
                      details="fields=" + ",".join(k for k in data if k != "password"))
    db.session.commit()
    return api_ok({"user": user_dict(user)})


@bp.get("/audit")
@login_required("admin")
def audit_log():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", 25, type=int), 1), 100)
    q = AuditLog.query.order_by(AuditLog.id.desc())
    action = request.args.get("action", "").strip()
    if action:
        q = q.filter(AuditLog.action.like(f"{action[:40]}%"))
    result = q.paginate(page=page, per_page=per_page, error_out=False)
    return api_ok({
        "items": [{"id": a.id, "timestamp": iso(a.timestamp), "actor_type": a.actor_type,
                   "actor_id": a.actor_id, "action": a.action, "entity_type": a.entity_type,
                   "entity_id": a.entity_id, "details": a.details, "ip": a.ip_address}
                  for a in result.items],
        "page": result.page, "pages": result.pages, "total": result.total,
    })
