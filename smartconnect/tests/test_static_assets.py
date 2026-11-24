"""
Static checks of the front-end files (HTML templates, JavaScript, service worker, manifest).

These need no database or server, so they run on any machine with Flask installed.  They make
sure the pieces that cannot be tested through the API (offline queue, scanner, service worker)
still contain the behaviour the project requires.
"""
import json
import re
from pathlib import Path

import jinja2
import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TEMPLATES = APP / "templates"
JS = APP / "static" / "js"


def read(path):
    return Path(path).read_text(encoding="utf-8")


# ------------------------------------------------------------------ templates
@pytest.mark.parametrize("path", sorted(TEMPLATES.rglob("*.html")), ids=lambda p: p.name)
def test_template_syntax(path):
    jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES)).parse(read(path))


def test_every_static_file_used_by_a_template_exists():
    pattern = re.compile(r"url_for\(\s*'static'\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]")
    missing = []
    for tpl in TEMPLATES.rglob("*.html"):
        for name in pattern.findall(read(tpl)):
            if "{" in name:       # dynamic name, e.g. vendor files chosen at runtime
                continue
            if not (APP / "static" / name).exists():
                missing.append(f"{tpl.name}: {name}")
    assert not missing, missing


def test_pages_that_post_data_carry_the_csrf_meta_tag():
    assert 'name="csrf-token"' in read(TEMPLATES / "base.html")


# ------------------------------------------------------------------ javascript
def test_all_js_files_are_present():
    expected = {"common.js", "app-shell.js", "offline.js", "scanner.js", "dashboard.js", "charts.js",
                "admin_network.js", "admin_reports.js", "admin_users.js", "admin_gates.js",
                "admin_audit.js", "host.js", "login.js", "register.js", "pass.js",
                "visitors_list.js", "queue_panel.js"}
    assert expected <= {p.name for p in JS.glob("*.js")}


def test_offline_queue_uses_indexeddb_and_idempotent_sync():
    code = read(JS / "offline.js")
    assert "indexedDB.open" in code                       # IndexedDB storage
    assert '"/api/sync"' in code                           # upload endpoint
    assert "operation_id" in code                          # unique id per operation
    for state in ("PENDING", "SYNCING", "SUCCESS", "FAILED"):
        assert state in code                               # the four synchronisation states
    assert 'SC.on("online"' in code                        # automatic retry when connectivity returns
    assert 'r.token = ""' in code                          # secret removed after the server processed it


def test_scanner_never_marks_an_offline_scan_as_authorised():
    code = read(JS / "scanner.js")
    assert "NOT verified" in code
    assert "SCOffline.add" in code                         # saved to the queue on NetworkError
    assert "SC.NetworkError" in code
    assert "Html5Qrcode.getCameras" in code                # front / rear camera selection
    assert "scanFile" in code                              # image-upload fallback
    # The only place an "authorised" result is drawn is after a server reply.
    assert code.count('show("ok"') >= 1


def test_common_js_measures_latency_and_detects_outage():
    code = read(JS / "common.js")
    assert "performance.now()" in code                     # round-trip time
    assert "/api/network/ping" in code                     # heartbeat
    assert "X-Response-Time-ms" in code                    # server processing time
    assert "X-CSRF-Token" in code
    assert "X-Device-Id" in code


def test_javascript_does_not_persist_secrets_in_local_storage():
    """Only two things may live in localStorage:
    * `sc_device_id`  - a random id used to tell devices apart in the communication log;
    * `sc_visit`      - the VISITOR's own pass + access key, kept on the visitor's own phone
                        (visitors have no password).  Staff pages never store anything secret.
    """
    allowed = {"sc_device_id": {"common.js"}, "sc_visit": {"register.js", "pass.js"}}
    for path in JS.glob("*.js"):
        for line in read(path).splitlines():
            if "localStorage.setItem" in line:
                key = next((k for k in allowed if k in line), None)
                assert key and path.name in allowed[key], f"{path.name}: {line.strip()}"
            assert "console.log" not in line or "token" not in line.lower(), f"{path.name}: {line}"


# -------------------------------------------------------------- service worker
def test_service_worker_never_caches_live_data():
    code = read(APP / "static" / "sw.js")
    assert '"/api/"' in code and '"/socket.io/"' in code
    assert 'req.method !== "GET"' in code                  # POSTs always reach the network
    assert '"/offline"' in code


def test_service_worker_precache_files_exist():
    code = read(APP / "static" / "sw.js")
    block = code.split("const PRECACHE = [")[1].split("];")[0]
    local = [u for u in re.findall(r'"(/[^"]+)"', block)
             if u != "/offline" and not u.startswith("/static/vendor/")]
    missing = [u for u in local if not (APP / u.lstrip("/")).exists()]
    assert not missing, missing


def test_manifest_is_valid():
    manifest = json.loads(read(APP / "static" / "manifest.webmanifest"))
    assert manifest["name"] and manifest["start_url"] and manifest["icons"]


# --------------------------------------------------------------- project files
def test_requirements_list_the_required_stack():
    text = read(ROOT / "requirements.txt").lower()
    for package in ("flask", "flask-sqlalchemy", "sqlalchemy", "flask-socketio", "qrcode", "flask-migrate"):
        assert package in text


def test_env_example_contains_no_real_secrets():
    for line in read(ROOT / ".env.example").splitlines():
        if line.startswith(("SECRET_KEY=", "SEED_ADMIN_PASSWORD=", "QR_HASH_PEPPER=", "DATABASE_URL=")):
            assert line.split("=", 1)[1].strip() == "", line


def test_demo_passwords_live_only_in_seed_file():
    offenders = []
    for path in APP.rglob("*.py"):
        if path.name == "seed.py":
            continue
        if "Admin@123" in read(path) or "Security@123" in read(path):
            offenders.append(path.name)
    assert not offenders, offenders


def test_production_start_command_does_not_use_flask_dev_server():
    for name in ("Procfile", "render.yaml"):
        text = read(ROOT / name)
        assert "gunicorn" in text, name
        assert "flask run" not in text and "python run.py" not in text, name
