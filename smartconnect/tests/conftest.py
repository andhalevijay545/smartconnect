"""
Shared test setup (pytest fixtures).

* Every test gets a brand-new SQLite file in a temporary folder - your real data in
  instance/smartconnect.db is never touched.
* The demo accounts from app/utils/seed.py exist in every test:
      admin / Admin@123      security1 / Security@123 (Main Gate)   security2 / Security@123 (Gate 2)
      host1 / Host@12345 (Engineering)   host2 (Human Resources)   host3 (Finance)
* Extension imports happen INSIDE fixtures so the pure-logic tests (test_utils.py,
  test_static_assets.py) also run on a machine where only Flask is installed.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Rate limiters and the live WebSocket list are module-level objects: start clean."""
    from app.utils.ratelimit import login_tracker, register_limiter
    login_tracker.clear()
    register_limiter.clear()
    try:
        from app.services.network_monitor import monitor
        with monitor._lock:
            monitor._ws.clear()
    except ImportError:  # extensions not installed (pure tests)
        pass
    yield


def _require_stack():
    """Skip (instead of crash) when the web stack is not installed yet."""
    for module in ("flask_sqlalchemy", "flask_socketio", "flask_migrate", "qrcode"):
        pytest.importorskip(module, reason=f"{module} not installed - run: pip install -r requirements.txt")


@pytest.fixture()
def app(tmp_path):
    _require_stack()
    from app import create_app
    from app.extensions import db
    from app.utils.seed import seed_database

    application = create_app("testing", overrides={
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + (tmp_path / "test.db").as_posix(),
    })
    with application.app_context():
        db.create_all()
        seed_database(demo=True, out=lambda *a, **k: None)
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def anon(app):
    """A browser that is not logged in."""
    return app.test_client()


@pytest.fixture()
def tokens(app, monkeypatch):
    """Capture the raw QR token of every pass that is issued.

    The raw token only exists inside the QR image (the database keeps just a hash), so the
    tests intercept the moment the image is drawn.  `tokens.latest` is the text a scanner
    would read from the QR code.
    """
    from app.services import qr_service
    from app.utils.tokens import qr_payload

    class Box:
        all = []

        @property
        def latest(self):
            return qr_payload(self.all[-1])

    box = Box()
    box.all = []
    real = qr_service.render_qr_data_uri

    def spy(token):
        box.all.append(token)
        return real(token)

    monkeypatch.setattr(qr_service, "render_qr_data_uri", spy)
    return box


def _staff(app, role, username, password):
    from helpers import Staff
    return Staff(app, role, username, password)


@pytest.fixture()
def admin(app):
    return _staff(app, "admin", "admin", "Admin@123")


@pytest.fixture()
def guard1(app):
    return _staff(app, "security", "security1", "Security@123")


@pytest.fixture()
def guard2(app):
    return _staff(app, "security", "security2", "Security@123")


@pytest.fixture()
def host1(app):
    return _staff(app, "host", "host1", "Host@12345")


@pytest.fixture()
def host2(app):
    return _staff(app, "host", "host2", "Host@12345")
