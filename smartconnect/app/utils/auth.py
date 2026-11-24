"""Authentication helpers: session users, role checks, CSRF, visitor access keys."""
import hmac
from functools import wraps

from flask import current_app, g, redirect, request, session, url_for

from ..extensions import db
from ..models import ROLE_MODELS, Visitor
from .responses import api_error
from .tokens import hash_token

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
HOME_FOR_ROLE = {
    "admin": "pages.admin_dashboard",
    "security": "pages.security_dashboard",
    "host": "pages.host_dashboard",
}


def pepper() -> str:
    cfg = current_app.config
    return cfg.get("QR_HASH_PEPPER") or cfg["SECRET_KEY"]


def load_session_user():
    """Return the logged-in staff user from the session cookie, or None."""
    role, uid = session.get("role"), session.get("uid")
    model = ROLE_MODELS.get(role)
    if not model or not uid:
        return None
    user = db.session.get(model, uid)
    if user is None or not user.is_active:
        return None
    return user


def csrf_ok() -> bool:
    """Compare the X-CSRF-Token header with the token stored in the session.

    CSRF = a malicious site making the browser send a request with your cookie.
    A custom header cannot be set by another site, so requiring it blocks that attack.
    """
    sent = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    return bool(expected) and hmac.compare_digest(sent, expected)


def login_required(*roles):
    """Decorator for API endpoints: 401 if not logged in, 403 if wrong role/CSRF."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = load_session_user()
            if user is None:
                return api_error("unauthorized", "Please log in to continue.", 401)
            if roles and user.role not in roles:
                return api_error("forbidden", "You do not have permission for this action.", 403)
            if request.method in UNSAFE_METHODS and not csrf_ok():
                return api_error("csrf_failed", "Missing or invalid CSRF token.", 403)
            g.user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def page_required(*roles):
    """Decorator for HTML pages: redirect to /login when not allowed."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = load_session_user()
            if user is None:
                return redirect(url_for("pages.login", next=request.path))
            if roles and user.role not in roles:
                return redirect(url_for(HOME_FOR_ROLE[user.role]))
            g.user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def visitor_from_key(public_id: str):
    """Authenticate a visitor by their secret access key (header X-Visitor-Key)."""
    key = request.headers.get("X-Visitor-Key", "")
    if not key or not public_id:
        return None
    visitor = Visitor.query.filter_by(public_id=public_id).first()
    if visitor is None:
        return None
    supplied = hash_token(key, pepper())
    return visitor if hmac.compare_digest(supplied, visitor.access_key_hash) else None
