"""HTML pages (the screens users see). Data is loaded by JavaScript from the REST API."""
from flask import (Blueprint, current_app, g, jsonify, redirect, render_template,
                   send_from_directory, url_for)
from sqlalchemy import text

from ..extensions import db
from ..utils.auth import HOME_FOR_ROLE, load_session_user, page_required

bp = Blueprint("pages", __name__)

# Sidebar navigation for each role: (label, endpoint, key)
NAV = {
    "admin": [
        ("Dashboard", "pages.admin_dashboard", "dashboard"),
        ("Visitors", "pages.admin_visitors", "visitors"),
        ("Users & Staff", "pages.admin_users", "users"),
        ("Gates & Departments", "pages.admin_gates", "gates"),
        ("Reports", "pages.admin_reports", "reports"),
        ("Audit Log", "pages.admin_audit", "audit"),
        ("Network Monitor", "pages.admin_network", "network"),
    ],
    "security": [
        ("Dashboard", "pages.security_dashboard", "dashboard"),
        ("QR Scanner", "pages.security_scanner", "scanner"),
        ("Visitors", "pages.security_visitors", "visitors"),
    ],
    "host": [
        ("Approvals", "pages.host_dashboard", "dashboard"),
        ("My Visitors", "pages.host_visitors", "visitors"),
    ],
}


def _page(template, title, active, **extra):
    role = g.user.role
    nav = [(label, url_for(endpoint), key) for label, endpoint, key in NAV[role]]
    return render_template(template, title=title, active=active, nav=nav, role=role, **extra)


# ---------------------------------------------------------------- public pages
@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/login")
def login():
    user = load_session_user()
    if user:
        return redirect(url_for(HOME_FOR_ROLE[user.role]))
    return render_template("login.html")


@bp.get("/register")
def register():
    return render_template("visitor/register.html")


@bp.get("/visitor/pass")
def visitor_pass():
    return render_template("visitor/pass.html")


@bp.get("/offline")
def offline():
    return render_template("offline.html")


@bp.get("/health")
def health():
    """Used by hosting platforms (Render) to check the app and database are alive."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", database="ok")
    except Exception:  # noqa: BLE001
        return jsonify(status="degraded", database="down"), 503


@bp.get("/sw.js")
def service_worker():
    """The service worker must be served from the site root so it controls every page."""
    resp = send_from_directory(current_app.static_folder, "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/manifest.webmanifest")
def manifest():
    resp = send_from_directory(current_app.static_folder, "manifest.webmanifest",
                               mimetype="application/manifest+json")
    return resp


# ----------------------------------------------------------------------- admin
@bp.get("/admin/dashboard")
@page_required("admin")
def admin_dashboard():
    return _page("admin/dashboard.html", "Admin Dashboard", "dashboard")


@bp.get("/admin/visitors")
@page_required("admin")
def admin_visitors():
    return _page("visitors_list.html", "All Visitors", "visitors")


@bp.get("/admin/users")
@page_required("admin")
def admin_users():
    return _page("admin/users.html", "Users & Security Staff", "users")


@bp.get("/admin/gates")
@page_required("admin")
def admin_gates():
    return _page("admin/gates.html", "Gates & Departments", "gates")


@bp.get("/admin/reports")
@page_required("admin")
def admin_reports():
    return _page("admin/reports.html", "Reports & Analytics", "reports")


@bp.get("/admin/audit")
@page_required("admin")
def admin_audit():
    return _page("admin/audit.html", "Audit Log", "audit")


@bp.get("/admin/network")
@page_required("admin")
def admin_network():
    return _page("admin/network.html", "Network Monitoring", "network")


# -------------------------------------------------------------------- security
@bp.get("/security/dashboard")
@page_required("security")
def security_dashboard():
    return _page("security/dashboard.html", "Security Dashboard", "dashboard")


@bp.get("/security/scanner")
@page_required("security")
def security_scanner():
    return _page("security/scanner.html", "QR Scanner", "scanner")


@bp.get("/security/visitors")
@page_required("security")
def security_visitors():
    return _page("visitors_list.html", "Visitors", "visitors")


# ------------------------------------------------------------------------ host
@bp.get("/host/dashboard")
@page_required("host")
def host_dashboard():
    return _page("host/dashboard.html", "Approval Requests", "dashboard")


@bp.get("/host/visitors")
@page_required("host")
def host_visitors():
    return _page("visitors_list.html", "My Visitors", "visitors")
