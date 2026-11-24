"""Command-line helpers:  flask --app run <command>"""
import click
from flask import current_app

from .extensions import db


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables (safe to run again)."""
        db.create_all()
        click.echo("Database tables created.")

    @app.cli.command("reset-db")
    @click.confirmation_option(prompt="This DELETES all data. Continue?")
    def reset_db():
        """Drop and re-create every table (development only)."""
        if current_app.config["ENV_NAME"] == "production":
            raise click.ClickException("Refusing to reset a production database.")
        db.drop_all()
        db.create_all()
        click.echo("Database reset.")

    @app.cli.command("seed")
    @click.option("--demo/--no-demo", default=None, help="Create sample staff accounts.")
    def seed(demo):
        """Insert departments, gates and starter accounts."""
        from .utils.seed import seed_database

        is_prod = current_app.config["ENV_NAME"] == "production"
        if demo is None:
            demo = not is_prod
        if demo and is_prod:
            raise click.ClickException("Demo accounts are not allowed in production.")
        db.create_all()
        seed_database(demo=demo, out=click.echo)

    @app.cli.command("show-urls")
    def show_urls():
        """Print the addresses a phone on the same Wi-Fi should open."""
        from .utils.helpers import get_lan_ips

        port = current_app.config["PORT"]
        scheme = "https" if current_app.config["LAN_HTTPS"] else "http"
        click.echo(f"This computer : {scheme}://localhost:{port}")
        for ip in get_lan_ips():
            click.echo(f"Phone (Wi-Fi) : {scheme}://{ip}:{port}")
