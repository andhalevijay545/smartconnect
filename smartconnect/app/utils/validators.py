"""Input validation (pure Python - easy to unit test).

Every function returns (clean_value, error_message). `error_message` is None when valid.
"""
import re
from datetime import timedelta

from .helpers import parse_iso_dt

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_MOBILE_RE = re.compile(r"^\+?\d{10,15}$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,40}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _text(value, label, min_len, max_len):
    if not isinstance(value, str):
        return None, f"{label} is required."
    value = " ".join(value.split())  # trim + collapse whitespace
    if _CONTROL_RE.search(value):
        return None, f"{label} contains invalid characters."
    if len(value) < min_len:
        return None, f"{label} must be at least {min_len} characters."
    if len(value) > max_len:
        return None, f"{label} must be at most {max_len} characters."
    return value, None


def validate_full_name(value):
    value, err = _text(value, "Full name", 2, 100)
    if err:
        return None, err
    if not value[0].isalpha() or not all(c.isalpha() or c in " .'-" for c in value):
        return None, "Full name may contain only letters, spaces, dots, apostrophes and hyphens."
    return value, None


def validate_mobile(value):
    if not isinstance(value, str):
        return None, "Mobile number is required."
    cleaned = re.sub(r"[\s\-()]", "", value)
    if not _MOBILE_RE.match(cleaned):
        return None, "Enter a valid mobile number (10-15 digits, optional leading +)."
    return cleaned, None


def validate_email(value):
    if not isinstance(value, str):
        return None, "Email is required."
    value = value.strip().lower()
    if len(value) > 120 or not _EMAIL_RE.match(value):
        return None, "Enter a valid email address."
    return value, None


def validate_username(value):
    if not isinstance(value, str) or not _USERNAME_RE.match(value.strip()):
        return None, "Username must be 3-40 characters: letters, digits, dot, dash, underscore."
    return value.strip().lower(), None


def validate_password(value):
    if not isinstance(value, str):
        return None, "Password is required."
    if len(value) < 8 or len(value) > 128:
        return None, "Password must be 8-128 characters."
    if not (re.search(r"[a-z]", value) and re.search(r"[A-Z]", value) and re.search(r"\d", value)):
        return None, "Password needs an uppercase letter, a lowercase letter and a digit."
    return value, None


def validate_int_id(value, label):
    if isinstance(value, bool):
        return None, f"{label} is invalid."
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None, f"{label} is required."
    if number <= 0:
        return None, f"{label} is invalid."
    return number, None


def validate_visitor_payload(data, now, default_tz=None):
    """Validate the visitor registration form. Returns (clean_dict, errors_dict)."""
    clean, errors = {}, {}
    if not isinstance(data, dict):
        return {}, {"_": "JSON object expected."}

    checks = {
        "full_name": validate_full_name(data.get("full_name")),
        "mobile": validate_mobile(data.get("mobile")),
        "email": validate_email(data.get("email")),
        "address": _text(data.get("address"), "Address", 5, 255),
        "purpose": _text(data.get("purpose"), "Purpose of visit", 3, 255),
        "department_id": validate_int_id(data.get("department_id"), "Department"),
        "host_id": validate_int_id(data.get("host_id"), "Host employee"),
    }
    for field, (value, err) in checks.items():
        if err:
            errors[field] = err
        else:
            clean[field] = value

    expected = parse_iso_dt(data.get("expected_at"), default_tz)
    if expected is None:
        errors["expected_at"] = "Expected visit date and time is required (ISO format)."
    elif expected < now - timedelta(hours=2):
        errors["expected_at"] = "Expected visit time cannot be in the past."
    elif expected > now + timedelta(days=90):
        errors["expected_at"] = "Expected visit time must be within the next 90 days."
    else:
        clean["expected_at"] = expected
    return clean, errors
