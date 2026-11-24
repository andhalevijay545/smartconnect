"""
Download the JavaScript/CSS libraries into app/static/vendor/ (run once, needs internet).

After this the website works on a LAN with NO internet connection, and the
service worker can cache every file for offline use.

Run:   python scripts/download_vendor.py
"""
import sys
import urllib.request
from pathlib import Path

FILES = {
    "bootstrap.min.css": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
    "bootstrap.bundle.min.js": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
    "chart.umd.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js",
    "socket.io.min.js": "https://cdn.jsdelivr.net/npm/socket.io-client@4.7.5/dist/socket.io.min.js",
    "html5-qrcode.min.js": "https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js",
}

target = Path(__file__).resolve().parent.parent / "app" / "static" / "vendor"
target.mkdir(parents=True, exist_ok=True)

ok = True
for name, url in FILES.items():
    try:
        print(f"Downloading {name} ...", end=" ")
        with urllib.request.urlopen(url, timeout=30) as resp:
            (target / name).write_bytes(resp.read())
        print("ok")
    except Exception as err:  # noqa: BLE001
        ok = False
        print(f"FAILED ({err})")

print("\nDone. Restart the server." if ok else "\nSome downloads failed; the CDN will be used for those.")
sys.exit(0 if ok else 1)
