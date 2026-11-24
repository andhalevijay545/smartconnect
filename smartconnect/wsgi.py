"""
wsgi.py - entry point for PRODUCTION servers (gunicorn).

    gunicorn --worker-class gthread --workers 1 --threads 100 wsgi:app

Flask-SocketIO wraps the Flask app, so this single `app` object serves both
normal HTTP requests and WebSocket connections.
"""
import os

from app import create_app

app = create_app(os.getenv("APP_ENV", "production"))
