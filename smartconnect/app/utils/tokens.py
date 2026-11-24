"""
QR token helpers (pure functions - no database).

Security design
---------------
* The token is 32 random bytes (256 bits) from `secrets` -> impossible to guess.
* The QR code contains ONLY "SMARTCONNECT:v1:<token>". No name, phone or e-mail.
* The database stores only HMAC-SHA256(pepper, token).  If the database leaks,
  an attacker still cannot rebuild a usable QR code.
"""
import hashlib
import hmac
import re
import secrets

QR_PREFIX = "SMARTCONNECT:v1:"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{32,64}$")
_OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 43 URL-safe characters


def hash_token(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def qr_payload(token: str) -> str:
    """The exact text that is encoded inside the QR image."""
    return QR_PREFIX + token


def extract_token(scanned):
    """Return the bare token from scanned text, or None if it is not a valid format."""
    if not isinstance(scanned, str):
        return None
    text = scanned.strip()
    if text.startswith(QR_PREFIX):
        text = text[len(QR_PREFIX):]
    return text if _TOKEN_RE.match(text) else None


def valid_operation_id(value) -> bool:
    return isinstance(value, str) and bool(_OPERATION_ID_RE.match(value))


def clean_device_id(value, fallback: str) -> str:
    """Accept a client-supplied device id only if it has a safe shape."""
    if isinstance(value, str) and _DEVICE_ID_RE.match(value):
        return value
    return fallback


def new_access_key() -> str:
    """Secret that lets a visitor look at their own pass (shown once, stored hashed)."""
    return secrets.token_urlsafe(24)
