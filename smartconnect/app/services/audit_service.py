"""Audit trail: who did what, when. Never store passwords, tokens or access keys here."""
from flask import has_request_context, request

from ..extensions import db
from ..models import AuditLog


def log(action, actor=None, actor_type=None, actor_id=None, entity_type=None,
        entity_id=None, details=None, commit=False):
    """Add an audit row to the current session (commit=True to save immediately)."""
    if actor is not None:
        actor_type, actor_id = actor.role, actor.id
    ip = request.remote_addr if has_request_context() else None
    entry = AuditLog(
        actor_type=actor_type or "system",
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=(details or "")[:500] or None,
        ip_address=ip,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry
