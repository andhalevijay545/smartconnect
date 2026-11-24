"""Small pure helper functions (no database, no Flask request needed)."""
import ipaddress
import socket
from datetime import date, datetime, timedelta, timezone

try:  # zoneinfo needs the `tzdata` package on Windows
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def utcnow() -> datetime:
    """Current UTC time as a *naive* datetime. All DB timestamps are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    """Naive-UTC datetime -> ISO-8601 string ending in 'Z' (or None)."""
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


def get_tz(name: str):
    """Return a tzinfo for `name`, falling back to UTC if it cannot be found."""
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def parse_iso_dt(value, default_tz=None):
    """Parse an ISO-8601 string into naive UTC. Returns None if invalid.

    A string without a timezone is interpreted in `default_tz` (UTC if omitted).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in "zZ":
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz or timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def local_day_bounds(day: date, tz):
    """[start, end) of a local calendar day, returned as naive UTC datetimes."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(start), to_utc(end)


def period_bounds(period: str, anchor: date, tz):
    """Return (label, start_utc, end_utc, first_day, last_day) for daily/weekly/monthly."""
    if period == "daily":
        first, last = anchor, anchor
    elif period == "weekly":
        first = anchor - timedelta(days=anchor.weekday())  # Monday
        last = first + timedelta(days=6)
    elif period == "monthly":
        first = anchor.replace(day=1)
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = nxt - timedelta(days=1)
    else:
        raise ValueError("period must be daily, weekly or monthly")
    start, _ = local_day_bounds(first, tz)
    _, end = local_day_bounds(last, tz)
    return f"{first.isoformat()} to {last.isoformat()}", start, end, first, last


def to_local(dt: datetime, tz) -> datetime:
    """Naive-UTC -> aware local datetime."""
    return dt.replace(tzinfo=timezone.utc).astimezone(tz)


def get_lan_ips():
    """Private IPv4 addresses of this computer (what a phone on Wi-Fi must type)."""
    found = set()
    try:  # UDP "connect" sends no packet; it just asks the OS which NIC would be used.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def classify_ip(ip: str) -> str:
    """'LAN' for private/loopback/link-local/CGNAT addresses, 'WAN' for public ones."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "UNKNOWN"
    return "WAN" if addr.is_global else "LAN"


def csv_safe(value):
    """Prevent CSV/Excel formula injection by neutralising leading = + - @."""
    if isinstance(value, str) and value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


def mask_mobile(mobile: str) -> str:
    """Show only the last 4 digits (used for security-staff views)."""
    if not mobile:
        return ""
    return "*" * max(len(mobile) - 4, 0) + mobile[-4:]
