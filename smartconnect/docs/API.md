# SmartConnect API

All responses are JSON: `{"ok": true, "data": {...}}` or `{"ok": false, "error": {"code", "message", "details?"}}`.
Staff authenticate with a session cookie from `/api/auth/login` and send `X-CSRF-Token` on POST/PATCH. Visitors send `X-Visitor-Key`. Optional `X-Device-Id` identifies the device in the communication log.

| Method & path | Who | Purpose |
|---|---|---|
| POST `/api/auth/login` | public | `{role, username, password}` → session + csrf_token |
| POST `/api/auth/logout`, GET `/api/auth/me` | staff | end / inspect session |
| POST `/api/visitors/register` | public | register, returns QR image + access key |
| GET `/api/visitors` | staff | list, filters `q, status, date_from, date_to, page, per_page` |
| GET `/api/visitors/<public_id>` | staff / visitor key | detail |
| POST `/api/qr/generate` | visitor key / host / admin | new pass (old one revoked) |
| POST `/api/qr/verify` | security | check a token without using it |
| POST `/api/visitors/check-in`, `/check-out` | security | `{token, operation_id?, gate_id?}` |
| GET `/api/approvals`, POST `/api/approvals/<id>/decision` | host, admin | approve / reject |
| GET `/api/dashboard/stats` | staff | live counters |
| GET/POST `/api/departments`, PATCH `/api/departments/<id>` | admin | manage |
| GET/POST `/api/gates`, PATCH `/api/gates/<id>`, GET `/api/gates/stats` | admin / security | gates |
| GET/POST `/api/admin/users`, PATCH `/api/admin/users/<role>/<id>` | admin | users |
| GET `/api/admin/audit` | admin | audit log |
| POST `/api/sync`, GET `/api/sync/operations` | security / admin | offline batch upload (idempotent by `operation_id`) |
| GET `/api/network/ping` | public | heartbeat |
| GET `/api/network/status`, `/metrics`, `/dns` | admin (status also security) | measured network data |
| GET `/api/reports/<daily\|weekly\|monthly>` and `/export` | admin | report / CSV |
| GET `/api/lookups` | public | departments + hosts for the form |

**Scan result codes:** `valid, checked_in, checked_out, invalid, expired, already_used, revoked, pending_approval, rejected, not_checked_in, stale`.

## WebSocket events (Socket.IO)
`visitor_registered`, `visitor_checked_in`, `visitor_checked_out`, `approval_updated`, `network_status_changed`, `sync_completed`.
Connections are authorised by the login session (staff) or `{public_id, key}` (visitor). Rooms: `role:admin`, `role:security`, `host:<id>`, `visitor:<public_id>`, `user:security:<id>`. Payloads never contain mobile, email or address.
