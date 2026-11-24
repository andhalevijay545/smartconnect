"""
Seed (fill) the database with starting data.

* DEMO mode (development/testing only): creates sample staff with the passwords
  printed below so you can log in immediately.  These are for LOCAL TESTING
  ONLY - the command refuses to create them when APP_ENV=production.
* PRODUCTION mode: creates departments, gates and ONE admin whose password comes
  from SEED_ADMIN_PASSWORD (or is generated randomly and printed once).
"""
import os
import secrets

from ..extensions import db
from ..models import Admin, Department, Gate, Host, SecurityStaff

DEPARTMENTS = ["Administration", "Engineering", "Finance", "Human Resources", "Sales"]
GATES = [("Main Gate", "Front entrance"), ("Gate 2", "Parking entrance"),
         ("Reception Desk", "Visitor lobby")]

# ---- LOCAL TESTING CREDENTIALS (demo mode only) --------------------------------
DEMO_ADMIN = ("admin", "Admin@123")
DEMO_SECURITY = [("security1", "Security@123", "Main Gate"), ("security2", "Security@123", "Gate 2")]
DEMO_HOSTS = [("host1", "Host@12345", "Engineering", "Priya Sharma"),
              ("host2", "Host@12345", "Human Resources", "Rahul Verma"),
              ("host3", "Host@12345", "Finance", "Anita Desai")]


def _get_or_create(model, **lookup):
    obj = model.query.filter_by(**lookup).first()
    if obj is None:
        obj = model(**lookup)
        db.session.add(obj)
        db.session.flush()
    return obj


def seed_database(demo: bool, out=print):
    departments = {name: _get_or_create(Department, name=name) for name in DEPARTMENTS}
    gates = {}
    for name, location in GATES:
        gate = _get_or_create(Gate, name=name)
        gate.location = location
        gates[name] = gate

    created = []

    def add_user(model, username, password, **fields):
        if model.query.filter_by(username=username).first():
            return
        user = model(username=username, **fields)
        user.set_password(password)
        db.session.add(user)
        created.append((model.role, username, password))

    if demo:
        add_user(Admin, DEMO_ADMIN[0], DEMO_ADMIN[1], full_name="System Admin", email="admin@example.com")
        for username, password, gate in DEMO_SECURITY:
            add_user(SecurityStaff, username, password, full_name=f"Guard {username[-1]}",
                     email=f"{username}@example.com", gate_id=gates[gate].id)
        for username, password, dept, name in DEMO_HOSTS:
            add_user(Host, username, password, full_name=name, email=f"{username}@example.com",
                     department_id=departments[dept].id)
    else:
        username = os.getenv("SEED_ADMIN_USERNAME", "admin")
        password = os.getenv("SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(12) + "aA1"
        add_user(Admin, username, password, full_name="System Admin", email="admin@example.com")

    db.session.commit()
    if created:
        out("\nAccounts created (save these now):")
        for role, username, password in created:
            out(f"  {role:<9} username={username:<11} password={password}")
        if not demo:
            out("  -> Change this password after the first login.")
    else:
        out("No new accounts were needed (they already exist).")
