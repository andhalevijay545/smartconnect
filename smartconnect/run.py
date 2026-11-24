"""
Entry point.

Development / LAN demo :  python run.py
Production (Linux)     :  gunicorn run:app -w 1 --threads 100 -b 0.0.0.0:$PORT

`-w 1` (one worker process) is required: Socket.IO connections and the live
network counters live in the memory of a single process. Threads give concurrency.
"""
import sys
from pathlib import Path

from app import create_app
from app.extensions import db, socketio

app = create_app()


def _ensure_database():
    """First run convenience: create tables (and demo data in development)."""
    with app.app_context():
        db.create_all()
        from app.models import Admin

        if app.config["ENV_NAME"] != "production" and Admin.query.count() == 0:
            from app.utils.seed import seed_database

            print("First run: creating demo data ...")
            seed_database(demo=True)


def _banner(scheme, port):
    from app.utils.helpers import get_lan_ips

    print("\n" + "=" * 62)
    print(" SmartConnect is running")
    print(f"   On this computer : {scheme}://localhost:{port}")
    for ip in get_lan_ips():
        print(f"   On your phone    : {scheme}://{ip}:{port}   (same Wi-Fi)")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    _ensure_database()
    host, port = app.config["HOST"], app.config["PORT"]
    ssl_context, scheme = None, "http"

    if app.config["LAN_HTTPS"]:
        cert, key = Path("instance/cert.pem"), Path("instance/key.pem")
        if not (cert.exists() and key.exists()):
            sys.exit("LAN_HTTPS=true but no certificate found.\n"
                     "Run:  python scripts/make_cert.py   and start again.")
        ssl_context, scheme = (str(cert), str(key)), "https"

    _banner(scheme, port)
    # allow_unsafe_werkzeug: this development server is fine for a LAN demo.
    # For the internet, use gunicorn (see README) - never this server.
    socketio.run(app, host=host, port=port, debug=app.config["DEBUG"],
                 allow_unsafe_werkzeug=True, ssl_context=ssl_context)
