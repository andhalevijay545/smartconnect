"""Network endpoints: /ping (anyone), /status and /metrics (staff)."""
from flask import Blueprint, request

from ..services.network_monitor import dns_lookup, monitor
from ..utils.auth import login_required
from ..utils.helpers import iso, utcnow
from ..utils.responses import api_error, api_ok

bp = Blueprint("network", __name__, url_prefix="/api/network")


@bp.get("/ping")
def ping():
    """Tiny public endpoint. The browser times a round trip to it to measure latency
    and to detect that the server is unreachable (offline mode)."""
    return api_ok({"pong": True, "server_time": iso(utcnow())})


@bp.get("/status")
@login_required("admin", "security")
def status():
    return api_ok(monitor.status())


@bp.get("/metrics")
@login_required("admin")
def metrics():
    minutes = request.args.get("minutes", 60, type=int)
    return api_ok(monitor.metrics(minutes))


@bp.get("/dns")
@login_required("admin")
def dns():
    """DNS demo: resolve a host name (default: the name this page was opened with)."""
    host = request.args.get("host") or request.host.split(":")[0]
    result, err = dns_lookup(host)
    if err:
        return api_error("dns_error", err, 400)
    return api_ok(result)
