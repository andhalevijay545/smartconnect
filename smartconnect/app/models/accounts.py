"""Staff accounts: Admin, SecurityStaff, Host.

Visitors do not have passwords - they get a one-time "access key" when they
register (see models/visitor.py).  Passwords are never stored in plain text:
Werkzeug hashes them with salted PBKDF2-SHA256.
"""
from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..utils.helpers import utcnow

# A throw-away hash (made lazily with the SAME cost as real hashes) used to keep login
# timing similar when a username does not exist - otherwise attackers could guess usernames.
_dummy_hash = None


class AccountBase(db.Model):
    """Abstract base: columns shared by all three staff tables."""

    __abstract__ = True
    role = ""  # set by subclasses

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, password: str):
        method = current_app.config.get("PASSWORD_HASH_METHOD", "pbkdf2:sha256")
        self.password_hash = generate_password_hash(password, method=method)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def burn_time():
        """Spend roughly the same time as a real check (prevents user enumeration)."""
        global _dummy_hash
        if _dummy_hash is None:
            method = current_app.config.get("PASSWORD_HASH_METHOD", "pbkdf2:sha256")
            _dummy_hash = generate_password_hash("not-a-real-password", method=method)
        check_password_hash(_dummy_hash, "x")


class Admin(AccountBase):
    __tablename__ = "admins"
    role = "admin"


class SecurityStaff(AccountBase):
    __tablename__ = "security_staff"
    role = "security"

    gate_id = db.Column(db.Integer, db.ForeignKey("gates.id"), index=True)
    gate = db.relationship("Gate", back_populates="staff")


class Host(AccountBase):
    __tablename__ = "hosts"
    role = "host"

    phone = db.Column(db.String(20))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    department = db.relationship("Department", back_populates="hosts")


ROLE_MODELS = {"admin": Admin, "security": SecurityStaff, "host": Host}
