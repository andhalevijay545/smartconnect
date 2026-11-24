"""
SmartConnect application factory.

`create_app()` builds and configures the Flask application. Keeping this in a
function (the "factory pattern") lets the tests create a fresh app each time.
"""
import logging
import time
from pathlib import Path


def create_app(config_name=None, overrides=None):
    # Imports are inside the function so that simple helper modules
    # (app.utils.*) can be imported and unit-tested without Flask extensions.
    from flask import Flask, g, redirect, request
    from werkzeug.middleware.proxy_fix import ProxyFix

    from config import BASE_DIR, get_config

    from .extensions import db, migrate, socketio

    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    config_class = get_config(config_name)
    app.config.from_object(config_class)
    if overrides:
        app.config.update(overrides)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is not set. Add it to your environment or .env file.")
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Behind Render/Nginx the real client IP and https scheme arrive in
    # X-Forwarded-* headers; ProxyFix makes Flask trust exactly one proxy hop.
    if app.config["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    origins = [o.strip() for o in app.config["CORS_ORIGINS"].split(",") if o.strip()]
    socketio.init_app(app, async_mode=app.config["SOCKETIO_ASYNC_MODE"],
                      cors_allowed_origins=origins or None, logger=False, engineio_logger=False)

    from . import models  # noqa: F401  (registers all tables)
    from .routes import register_blueprints
    from .sockets import handlers  # noqa: F401  (registers Socket.IO event handlers)
    from .cli import register_cli
    from .services.network_monitor import monitor

    register_blueprints(app)
    register_cli(app)
    _register_error_handlers(app)

    # ------------------------------------------------------------ request hooks
    @app.before_request
    def _start_timer():
        g.request_started = time.perf_counter()
        if app.config["FORCE_HTTPS"] and not request.is_secure \
                and request.host.split(":")[0] not in ("localhost", "127.0.0.1"):
            return redirect(request.url.replace("http://", "https://", 1), code=301)

    @app.after_request
    def _finish(response):
        # Security headers: restrict what the browser may load/do.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; "
            "connect-src 'self' ws: wss: https://cdn.jsdelivr.net https://unpkg.com; "
            "worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"))
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"

        started = g.get("request_started")
        if started is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000
            # The browser subtracts this from its own round-trip time to get pure network time.
            response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.2f}"
            if monitor.should_log(request.path):
                monitor.log_request(elapsed_ms, response)
        return response

    @app.context_processor
    def _template_globals():
        import secrets as _secrets
        from flask import session
        from .utils.auth import load_session_user

        user = load_session_user()
        if user and not session.get("csrf"):
            session["csrf"] = _secrets.token_urlsafe(32)
        return {
            "current_user": user,
            "csrf_token": session.get("csrf", "") if user else "",
            "network_mode": app.config["NETWORK_MODE"],
            "vendor": _vendor_url,
        }

    return app


# ------------------------------------------------------------------ front-end libs
_VENDOR = {
    # name: (local file under static/vendor, CDN fallback)
    "bootstrap.css": ("bootstrap.min.css", "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"),
    "bootstrap.js": ("bootstrap.bundle.min.js", "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"),
    "chart.js": ("chart.umd.min.js", "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"),
    "socket.io.js": ("socket.io.min.js", "https://cdn.jsdelivr.net/npm/socket.io-client@4.7.5/dist/socket.io.min.js"),
    "html5-qrcode.js": ("html5-qrcode.min.js", "https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"),
}


def _vendor_url(name):
    """Use a local copy (static/vendor/) when present, otherwise the CDN.

    Local copies make LAN demos work with NO internet. Download them once with
    `python scripts/download_vendor.py`.
    """
    from flask import url_for

    filename, cdn = _VENDOR[name]
    local = Path(__file__).parent / "static" / "vendor" / filename
    if local.exists():
        return url_for("static", filename=f"vendor/{filename}")
    return cdn


def _register_error_handlers(app):
    from flask import render_template, request
    from werkzeug.exceptions import HTTPException

    from .extensions import db
    from .utils.responses import api_error

    def wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if wants_json():
            code = (err.name or "error").lower().replace(" ", "_")
            return api_error(code, err.description, err.code)
        return render_template("error.html", code=err.code, message=err.description), err.code

    @app.errorhandler(Exception)
    def _unexpected(err):
        app.logger.exception("Unhandled error")
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        if wants_json():
            return api_error("server_error", "Something went wrong on the server.", 500)
        return render_template("error.html", code=500, message="Something went wrong."), 500
