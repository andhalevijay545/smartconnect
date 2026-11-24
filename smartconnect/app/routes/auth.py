"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me"""
import secrets

from flask import Blueprint, current_app, g, request, session, url_for

from ..extensions import db
from ..models import ROLE_MODELS
from ..models.accounts import AccountBase
from ..services import audit_service
from ..utils.auth import HOME_FOR_ROLE, load_session_user, login_required
from ..utils.helpers import utcnow
from ..utils.ratelimit import login_tracker
from ..utils.responses import api_error, api_ok, json_body
from ..utils.serializers import user_dict

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    data = json_body()
    role = data.get("role")
    username = str(data.get("username", "")).strip().lower()
    password = data.get("password")
    if role not in ROLE_MODELS or not username or not isinstance(password, str) or not password:
        return api_error("bad_request", "role, username and password are required.", 400)

    cfg = current_app.config
    throttle_key = f"{request.remote_addr}|{role}|{username}"
    wait = login_tracker.locked_for(throttle_key)
    if wait:
        return api_error("too_many_attempts",
                         f"Too many failed attempts. Try again in {wait} seconds.", 429)

    user = ROLE_MODELS[role].query.filter_by(username=username).first()
    if user is None:
        AccountBase.burn_time()  # same time cost whether or not the user exists
    valid = bool(user and user.is_active and user.check_password(password))

    if not valid:
        login_tracker.failure(throttle_key, cfg["LOGIN_MAX_ATTEMPTS"], cfg["LOGIN_LOCK_SECONDS"])
        if user is not None:  # never log what was typed for unknown users
            audit_service.log("auth.login_failed", actor=user, entity_type=role,
                              entity_id=user.id, commit=True)
        return api_error("invalid_credentials", "Invalid username or password.", 401)

    login_tracker.success(throttle_key)
    session.clear()  # prevents session fixation
    session["role"] = role
    session["uid"] = user.id
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = True
    user.last_login_at = utcnow()
    audit_service.log("auth.login", actor=user, entity_type=role, entity_id=user.id)
    db.session.commit()

    return api_ok({
        "user": user_dict(user),
        "csrf_token": session["csrf"],
        "redirect": url_for(HOME_FOR_ROLE[role]),
    })


@bp.post("/logout")
def logout():
    user = load_session_user()
    if user is not None:
        audit_service.log("auth.logout", actor=user, entity_type=user.role,
                          entity_id=user.id, commit=True)
    session.clear()
    return api_ok({"redirect": url_for("pages.login")})


@bp.get("/me")
@login_required()
def me():
    return api_ok({"user": user_dict(g.user), "csrf_token": session.get("csrf")})
