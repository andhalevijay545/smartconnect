"""Consistent JSON responses.

Success: {"ok": true,  "data": {...}}
Failure: {"ok": false, "error": {"code": "...", "message": "...", "details": {...}}}
"""
from flask import jsonify, request


def api_ok(data=None, status=200):
    return jsonify({"ok": True, "data": {} if data is None else data}), status


def api_error(code, message, status=400, details=None):
    body = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def json_body():
    """Return the JSON object sent by the client, or {} if missing/invalid."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
