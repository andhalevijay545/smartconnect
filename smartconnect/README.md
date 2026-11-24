# SmartConnect – QR Code-Based Intelligent Visitor Management System
### with Dual Network Communication (LAN + WAN)

B.Tech Data Communication project. Flask + Flask-SocketIO + SQLAlchemy + Bootstrap 5.

> **Honest status:** the code was syntax-checked, linted and cross-checked, and the 99 pure-logic tests pass.
> The 148 integration tests (database, QR, WebSocket) need the packages in `requirements.txt`, which could not be
> installed in the environment where this project was written. **Run `pytest` on your PC first** (step 6 below) and
> fix anything it reports before your demo.

## 1. What you get
| Area | Where |
|---|---|
| Flask app, config, DB models | `app/`, `config.py`, `app/models/` |
| REST API (50 routes) + WebSocket | `app/routes/`, `app/sockets/` — see `docs/API.md` |
| QR tokens (hash only stored, expiring, one-time) | `app/services/qr_service.py`, `app/utils/tokens.py` |
| Offline queue (IndexedDB + Service Worker) | `app/static/js/offline.js`, `app/static/sw.js` |
| Network monitoring (real measured data) | `app/services/network_monitor.py`, `/admin/network` |
| Tests | `tests/` |
| Report, diagrams, viva notes | `docs/` |
| Render deployment | `render.yaml`, `Procfile`, `requirements-prod.txt` |

## 2. Install on Windows (VS Code)
1. Install **Python 3.11 or 3.12** from python.org (tick **Add python.exe to PATH**) and **VS Code** with the *Python* extension.
2. Unzip the project, open the `smartconnect` folder in VS Code (File → Open Folder), then open a terminal (Ctrl+`).
3. Create a virtual environment (an isolated box for this project's packages):
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
   If PowerShell blocks it: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry.
4. Install the packages (reads `requirements.txt`):
   ```
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
5. Optional, makes charts/scanner work without internet: `python scripts/download_vendor.py`
6. Run the tests: `pytest` — expect all green (about 247 tests).
7. Start the server: `python run.py`. First run creates `instance/smartconnect.db` and demo accounts and prints the URLs.

Open `http://localhost:5000`.

**Demo logins (local testing only):**
| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `Admin@123` |
| Security | `security1` / `security2` | `Security@123` |
| Host | `host1`, `host2`, `host3` | `Host@12345` |

Visitors need no account: they register at `/register` and receive a pass + private access key. Never use these passwords in production (set `SEED_ADMIN_PASSWORD`).

## 3. LAN mode (phone on the same Wi-Fi)
1. PC and phone on the same Wi-Fi. `python run.py` prints `On your phone: http://192.168.x.x:5000`.
2. Allow the port in Windows Firewall (Admin terminal): `netsh advfirewall firewall add rule name="SmartConnect" dir=in action=allow protocol=TCP localport=5000`
3. **Camera needs HTTPS** (browser rule). For the phone scanner:
   ```
   python scripts/make_cert.py
   ```
   then in `.env` (copy from `.env.example`) set `LAN_HTTPS=true` and `SESSION_COOKIE_SECURE=true`, run `python run.py`, open `https://192.168.x.x:5000` on the phone and accept the self-signed warning. Without HTTPS you can still use the **image-upload fallback** on the scanner page.
4. Log in as `security1` on the phone → Scanner.

## 4. WAN mode (Internet, Render)
1. Push the project to GitHub. In Render: **New → Blueprint**, pick the repo (`render.yaml` creates the web service and a PostgreSQL database).
2. In the Render dashboard set `SEED_ADMIN_PASSWORD` (a strong password). `SECRET_KEY` and `QR_HASH_PEPPER` are generated automatically.
3. Open the `https://<name>.onrender.com` URL. TLS is provided by Render; the app trusts the proxy headers (`BEHIND_PROXY=true`) so it sees real client IPs and marks the traffic **WAN**.
4. Free plans sleep when idle (first request is slow) — check Render's current free-tier limits before a demo.

Production start command is **gunicorn** (never the Flask dev server). Settings table: `.env.example`.

## 5. PostgreSQL locally (optional)
Create a database, then in `.env`: `DATABASE_URL=postgresql://user:password@localhost:5432/smartconnect`, run `pip install psycopg2-binary`, then `flask --app run init-db`.
Schema changes later: `flask --app run db init` (once) → `db migrate -m "msg"` → `db upgrade`.

## 6. Tests
```
pytest            # everything
pytest -k lan     # only LAN/WAN tests
```
Covers: registration, invalid data, QR generation, expired/invalid/reused QR, check-in/out, duplicates, unauthorized access, LAN & WAN, server failure, offline sync, duplicate sync, real-time WebSocket updates, reports, audit.

## 7. Demo script (5 minutes)
1. Phone A (mobile data or Wi-Fi) → `/register` → get QR. 2. Host PC → approve. 3. Guard phone → Scanner → scan → Check-in. 4. Admin PC → dashboard updates **live**. 5. Admin → **Network** page: latency, status codes, LAN vs WAN, WebSocket clients. 6. Turn Wi-Fi off on guard phone → scan → shows *saved, NOT verified* → turn on → auto-sync → verified. More in `docs/DEMO_AND_VIVA.md`.

## 8. Security design
Passwords hashed (PBKDF2). QR holds only a random token; DB stores an HMAC hash; passes expire, are one-time, and are revoked when reissued. CSRF header on all writes, login lockout, rate-limited registration, security headers/CSP, role checks on every API and WebSocket room. Logs never contain passwords, cookies or QR tokens.

## 9. Troubleshooting
| Problem | Fix |
|---|---|
| Phone cannot open the page | Same Wi-Fi? Firewall rule? Router "AP isolation" off? |
| Camera won't start | Use HTTPS (step 3) or the upload fallback |
| `ModuleNotFoundError` | Activate venv, rerun `pip install -r requirements.txt` |
| Port busy | Set `PORT=5001` in `.env` |
