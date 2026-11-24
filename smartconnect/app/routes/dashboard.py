"""GET /api/dashboard/stats - live numbers for every role's dashboard."""
from flask import Blueprint, g

from ..services import stats_service
from ..utils.auth import login_required
from ..utils.responses import api_ok

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.get("/stats")
@login_required("admin", "security", "host")
def stats():
    host_id = g.user.id if g.user.role == "host" else None  # hosts only see their own
    data = stats_service.dashboard_stats(host_id)
    if g.user.role == "security":
        data["my_gate"] = {"id": g.user.gate_id, "name": g.user.gate.name if g.user.gate else None}
    return api_ok(data)
