"""GET /api/reports/<daily|weekly|monthly> and the CSV export."""
from datetime import datetime

from flask import Blueprint, Response, current_app, request

from ..services import report_service
from ..utils.auth import login_required
from ..utils.helpers import get_tz
from ..utils.responses import api_error, api_ok

bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def _build(period):
    tz = get_tz(current_app.config["APP_TIMEZONE"])
    raw = request.args.get("date")
    try:
        anchor = datetime.strptime(raw, "%Y-%m-%d").date() if raw else datetime.now(tz).date()
    except ValueError:
        return None
    return report_service.build_report(period, anchor)


@bp.get("/<any(daily,weekly,monthly):period>")
@login_required("admin")
def report(period):
    data = _build(period)
    if data is None:
        return api_error("bad_request", "date must be YYYY-MM-DD.", 400)
    return api_ok(data)


@bp.get("/<any(daily,weekly,monthly):period>/export")
@login_required("admin")
def export_csv(period):
    data = _build(period)
    if data is None:
        return api_error("bad_request", "date must be YYYY-MM-DD.", 400)
    body = report_service.report_to_csv(data)
    filename = f"smartconnect_{period}_{data['from']}.csv"
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
