"""Organisation structure: departments and security gates."""
from ..extensions import db
from ..utils.helpers import utcnow


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    hosts = db.relationship("Host", back_populates="department")


class Gate(db.Model):
    __tablename__ = "gates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    location = db.Column(db.String(160))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    staff = db.relationship("SecurityStaff", back_populates="gate")
