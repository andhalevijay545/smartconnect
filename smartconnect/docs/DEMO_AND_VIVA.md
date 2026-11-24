# Demo & Viva Notes

## Demo order
1. `python run.py` – show the printed LAN IP. 2. Phone: `/register` → QR. 3. Host: approve. 4. Guard phone: scan → check-in. 5. Admin: live dashboard + `/admin/network`. 6. Disconnect guard Wi-Fi → scan → "saved, NOT verified" → reconnect → auto sync. 7. Show `/admin/reports` CSV and `/admin/audit`.

## Likely questions
- **Why is camera blocked on http://192.168…?** Browsers allow getUserMedia only on secure origins; use `make_cert.py`.
- **Why store a hash of the token?** A database leak must not reveal usable passes.
- **How are duplicates prevented offline?** Each queued scan has a unique `operation_id`; the server stores it with a UNIQUE constraint and returns the saved result on retry.
- **LAN vs WAN?** Private IP ranges (RFC 1918) vs public addresses; the server classifies each request.
- **WebSocket vs REST?** REST = request/response; WebSocket = persistent two-way TCP connection for push updates.
- **What does TLS give?** Encryption, integrity, server authentication.
- **Where does latency come from?** DNS + TCP + TLS handshakes, transmission, server processing (`X-Response-Time-ms`), database.
