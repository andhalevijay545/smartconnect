"""Departments, gates and the public lookup list used by the registration form."""
from flask import Blueprint, g
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Department, Gate, Host
from ..services import audit_service, stats_service
from ..utils.auth import login_required
from ..utils.responses import api_error, api_ok, json_body
from ..utils.serializers import department_dict, gate_dict

bp = Blueprint("org", __name__, url_prefix="/api")


@bp.get("/lookups")
def lookups():
    """Public: departments and host names (no e-mail/phone) for the registration form."""
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    hosts = Host.query.filter_by(is_active=True).order_by(Host.full_name).all()
    return api_ok({
        "departments": [department_dict(d) for d in departments],
        "hosts": [{"id": h.id, "full_name": h.full_name, "department_id": h.department_id}
                  for h in hosts],
    })


def _clean_name(value, label, max_len=80):
    if not isinstance(value, str) or not (2 <= len(value.strip()) <= max_len):
        return None, f"{label} must be 2-{max_len} characters."
    return " ".join(value.split()), None


# ---------------------------------------------------------------- departments
@bp.get("/departments")
@login_required("admin")
def list_departments():
    items = Department.query.order_by(Department.name).all()
    return api_ok({"items": [department_dict(d) for d in items]})


@bp.post("/departments")
@login_required("admin")
def create_department():
    name, err = _clean_name(json_body().get("name"), "Department name")
    if err:
        return api_error("validation_error", err, 422)
    dep = Department(name=name)
    db.session.add(dep)
    try:
        audit_service.log("department.create", actor=g.user, entity_type="department", details=name)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate", "A department with this name already exists.", 409)
    return api_ok({"department": department_dict(dep)}, 201)


@bp.patch("/departments/<int:dep_id>")
@login_required("admin")
def update_department(dep_id):
    dep = db.session.get(Department, dep_id)
    if dep is None:
        return api_error("not_found", "Department not found.", 404)
    data = json_body()
    if "name" in data:
        name, err = _clean_name(data["name"], "Department name")
        if err:
            return api_error("validation_error", err, 422)
        dep.name = name
    if isinstance(data.get("is_active"), bool):
        dep.is_active = data["is_active"]
    try:
        audit_service.log("department.update", actor=g.user, entity_type="department", entity_id=dep.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate", "A department with this name already exists.", 409)
    return api_ok({"department": department_dict(dep)})


# ---------------------------------------------------------------------- gates
@bp.get("/gates")
@login_required("admin", "security")
def list_gates():
    items = Gate.query.order_by(Gate.name).all()
    return api_ok({"items": [gate_dict(g_) for g_ in items]})


@bp.get("/gates/stats")
@login_required("admin", "security")
def gate_statistics():
    """Gate-wise visitor statistics (Module 11)."""
    return api_ok({"items": stats_service.gate_stats()})


@bp.post("/gates")
@login_required("admin")
def create_gate():
    data = json_body()
    name, err = _clean_name(data.get("name"), "Gate name")
    if err:
        return api_error("validation_error", err, 422)
    location = (data.get("location") or "").strip()[:160] or None
    gate = Gate(name=name, location=location)
    db.session.add(gate)
    try:
        audit_service.log("gate.create", actor=g.user, entity_type="gate", details=name)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate", "A gate with this name already exists.", 409)
    return api_ok({"gate": gate_dict(gate)}, 201)


@bp.patch("/gates/<int:gate_id>")
@login_required("admin")
def update_gate(gate_id):
    gate = db.session.get(Gate, gate_id)
    if gate is None:
        return api_error("not_found", "Gate not found.", 404)
    data = json_body()
    if "name" in data:
        name, err = _clean_name(data["name"], "Gate name")
        if err:
            return api_error("validation_error", err, 422)
        gate.name = name
    if "location" in data:
        gate.location = (data.get("location") or "").strip()[:160] or None
    if isinstance(data.get("is_active"), bool):
        gate.is_active = data["is_active"]
    try:
        audit_service.log("gate.update", actor=g.user, entity_type="gate", entity_id=gate.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate", "A gate with this name already exists.", 409)
    return api_ok({"gate": gate_dict(gate)})
