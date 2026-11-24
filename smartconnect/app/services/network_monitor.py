"""
Network monitoring (Module 9 + 13).

EVERY number here is measured from real traffic - nothing is invented:

* Each /api request is timed with a monotonic clock (time.perf_counter) and
  written to the `communication_logs` table (Module 13).
* The dashboard calculates totals, averages and percentiles from those rows.
* WebSocket clients are counted from real Socket.IO connect/disconnect events.
* Sync figures come from the `sync_operations` table.
* Database latency is the measured time of a real `SELECT 1`.

Note: the measured duration is *server processing time* (request received ->
response ready). Network latency is measured separately by the browser, which
times a round trip to /api/network/ping (see static/js/network.js).
"""
import hashlib
import re
import socket
import threading
import time
from collections import Counter
from datetime import timedelta
from math import ceil

from flask import current_app, request
from sqlalchemy import delete, insert, text

from ..extensions import db
from ..models import CommunicationLog
from ..utils.helpers import classify_ip, get_lan_ips, iso, utcnow
from ..utils.tokens import clean_device_id
from . import sync_service

_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$")


def dns_lookup(hostname: str):
    """Resolve a host name to IP addresses and time it (DNS demonstration).

    DNS (Domain Name System) is the Internet's phone book: it turns a name such as
    "smartconnect.onrender.com" into the IP address that TCP must connect to.
    Returns (result_dict, error_message).
    """
    hostname = (hostname or "").strip().lower().rstrip(".")
    if not _HOSTNAME_RE.match(hostname):
        return None, "Enter a valid host name (letters, digits, dots, hyphens)."
    t0 = time.perf_counter()
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as err:
        return None, f"DNS lookup failed: {err.strerror or err}"
    ms = round((time.perf_counter() - t0) * 1000, 2)
    addresses = sorted({i[4][0] for i in infos})
    return {"hostname": hostname, "addresses": addresses, "lookup_ms": ms,
            "scope": [{"ip": a, "network": classify_ip(a)} for a in addresses]}, None


# Paths that are not logged, so the monitor does not measure itself.
UNLOGGED_PREFIXES = ("/api/network/",)


class NetworkMonitor:
    def __init__(self):
        self.started_at = time.time()
        self._ws = {}
        self._lock = threading.Lock()
        self._inserts = 0

    # ---------------------------------------------------------------- logging
    def should_log(self, path: str) -> bool:
        return path.startswith("/api/") and not path.startswith(UNLOGGED_PREFIXES)

    def log_request(self, duration_ms, response):
        """Called from after_request. Never raises - monitoring must not break the app."""
        try:
            if not current_app.config.get("COMM_LOG_ENABLED", True):
                return
            ip = request.remote_addr or ""
            seed = (ip + request.headers.get("User-Agent", "")).encode("utf-8", "ignore")
            fallback = "anon-" + hashlib.sha1(seed).hexdigest()[:12]
            rule = request.url_rule.rule if request.url_rule else "(unmatched)"
            status = response.status_code
            entry = {
                "timestamp": utcnow(),
                "device_id": clean_device_id(request.headers.get("X-Device-Id"), fallback),
                "client_ip": ip[:45],
                "network_type": classify_ip(ip),
                "endpoint": rule[:160],
                "method": request.method,
                "status_code": status,
                "duration_ms": round(duration_ms, 3),
                "success": status < 400,
                "request_bytes": request.content_length or 0,
                "response_bytes": response.calculate_content_length() or 0,
                "is_secure": request.is_secure,
            }
            with db.engine.begin() as conn:  # separate short transaction
                conn.execute(insert(CommunicationLog).values(**entry))
            self._inserts += 1
            if self._inserts % 500 == 0:
                self._prune()
        except Exception:  # noqa: BLE001
            current_app.logger.exception("communication log failed")

    def _prune(self):
        days = current_app.config["COMM_LOG_RETENTION_DAYS"]
        cutoff = utcnow() - timedelta(days=days)
        with db.engine.begin() as conn:
            conn.execute(delete(CommunicationLog).where(CommunicationLog.timestamp < cutoff))

    # -------------------------------------------------------- websocket clients
    def register_ws(self, sid, info):
        with self._lock:
            self._ws[sid] = dict(info, connected_at=iso(utcnow()))
            return len(self._ws)

    def unregister_ws(self, sid):
        with self._lock:
            self._ws.pop(sid, None)
            return len(self._ws)

    def ws_clients(self):
        with self._lock:
            return list(self._ws.values())

    # ------------------------------------------------------------------ status
    def status(self):
        t0 = time.perf_counter()
        try:
            db.session.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # noqa: BLE001
            db.session.rollback()
            db_ok = False
        db_ms = round((time.perf_counter() - t0) * 1000, 3)

        counts, last_sync = sync_service.sync_status_counts() if db_ok else ({}, None)
        ip = request.remote_addr or ""
        clients = self.ws_clients()
        return {
            "server_time": iso(utcnow()),
            "available": True,  # this very response proves the server is reachable
            "uptime_seconds": int(time.time() - self.started_at),
            "server": {
                "hostname": socket.gethostname(),
                "lan_ips": get_lan_ips(),
                "port": request.environ.get("SERVER_PORT"),
                "mode": current_app.config["NETWORK_MODE"],
                "async_mode": current_app.config["SOCKETIO_ASYNC_MODE"],
            },
            "database": {"ok": db_ok, "latency_ms": db_ms,
                         "engine": db.engine.dialect.name if db_ok else None},
            "connection": {
                "client_ip": ip,
                "client_port": request.environ.get("REMOTE_PORT"),
                "network_type": classify_ip(ip),
                "scheme": request.scheme,
                "tls": request.is_secure,
                "http_version": request.environ.get("SERVER_PROTOCOL"),
                "host_header": request.host,
            },
            "websocket": {"connected": len(clients), "clients": clients},
            "sync": {
                "pending": counts.get("PENDING", 0),
                "success": counts.get("SUCCESS", 0),
                "failed": counts.get("FAILED", 0),
                "last_sync_at": iso(last_sync),
            },
        }

    # ----------------------------------------------------------------- metrics
    def metrics(self, minutes=60):
        minutes = max(1, min(int(minutes), 24 * 60))
        cutoff = utcnow() - timedelta(minutes=minutes)
        c = CommunicationLog
        rows = (db.session.query(c.timestamp, c.status_code, c.duration_ms, c.success, c.endpoint,
                                 c.method, c.device_id, c.client_ip, c.network_type,
                                 c.request_bytes, c.response_bytes, c.is_secure)
                .filter(c.timestamp >= cutoff).order_by(c.timestamp.desc()).limit(20000).all())

        total = len(rows)
        ok = sum(1 for r in rows if r.success)
        durations = sorted(r.duration_ms for r in rows)

        def pct(p):
            return round(durations[max(0, ceil(p * len(durations)) - 1)], 2) if durations else 0

        codes = Counter(str(r.status_code) for r in rows)
        classes = Counter(f"{r.status_code // 100}xx" for r in rows)
        networks = Counter(r.network_type or "UNKNOWN" for r in rows)

        bucket = max(1, minutes // 60)  # minutes per chart point
        series = {}
        for r in rows:
            m = r.timestamp.replace(second=0, microsecond=0)
            m -= timedelta(minutes=m.minute % bucket)
            s = series.setdefault(m, {"count": 0, "total_ms": 0.0, "errors": 0})
            s["count"] += 1
            s["total_ms"] += r.duration_ms
            s["errors"] += 0 if r.success else 1
        timeline = [{"t": iso(t), "count": s["count"], "avg_ms": round(s["total_ms"] / s["count"], 2),
                     "errors": s["errors"]} for t, s in sorted(series.items())]

        per_endpoint = {}
        for r in rows:
            e = per_endpoint.setdefault((r.method, r.endpoint), {"count": 0, "ms": 0.0, "errors": 0})
            e["count"] += 1
            e["ms"] += r.duration_ms
            e["errors"] += 0 if r.success else 1
        top = sorted(({"method": k[0], "endpoint": k[1], "count": v["count"],
                       "avg_ms": round(v["ms"] / v["count"], 2), "errors": v["errors"]}
                      for k, v in per_endpoint.items()), key=lambda x: -x["count"])[:10]

        return {
            "window_minutes": minutes,
            "totals": {
                "requests": total, "successful": ok, "failed": total - ok,
                "success_rate": round(100 * ok / total, 1) if total else None,
                "bytes_in": sum(r.request_bytes or 0 for r in rows),
                "bytes_out": sum(r.response_bytes or 0 for r in rows),
                "tls_requests": sum(1 for r in rows if r.is_secure),
            },
            "response_time_ms": {
                "avg": round(sum(durations) / total, 2) if total else 0,
                "min": round(durations[0], 2) if total else 0,
                "max": round(durations[-1], 2) if total else 0,
                "p50": pct(0.50), "p95": pct(0.95),
            },
            "status_codes": dict(sorted(codes.items())),
            "status_classes": dict(classes),
            "network_types": dict(networks),
            "timeline": timeline,
            "top_endpoints": top,
            "history": [{
                "t": iso(r.timestamp), "device_id": r.device_id, "client_ip": r.client_ip,
                "network": r.network_type, "method": r.method, "endpoint": r.endpoint,
                "status": r.status_code, "ms": round(r.duration_ms, 2), "success": r.success,
                "bytes_out": r.response_bytes, "tls": r.is_secure,
            } for r in rows[:60]],
        }


monitor = NetworkMonitor()
