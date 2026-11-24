/*
 * scanner.js - mobile QR scanner for security staff (Modules 4, 5 and 8).
 *
 * Flow for every scanned code
 *   1. POST /api/qr/verify   (read-only: valid / expired / invalid / already used ...)
 *   2. guard presses Confirm (or auto-confirm) -> POST /api/visitors/check-in | check-out
 *   3. If the server cannot be reached at ANY point, the scan is saved in the offline queue
 *      as PENDING. It is shown as "NOT verified" - never as an authorised entry - until
 *      POST /api/sync returns the server's verdict.
 */
(function () {
  "use strict";
  const SC = window.SC;
  const $ = SC.$;
  const resultBox = $("result");
  let scanner = null, cameras = [], camIndex = 0, running = false;
  let lastText = "", lastAt = 0, busy = false;

  const mode = () => (document.querySelector('input[name="mode"]:checked') || {}).value || "check-in";
  const label = (m) => (m === "check-in" ? "Check-in" : "Check-out");

  // --------------------------------------------------------------- result card
  function show(kind, title, lines, extraHtml) {
    resultBox.className = "scan-result " + kind;
    resultBox.innerHTML = `<div class="big">${SC.esc(title)}</div>` +
      (lines || []).map((l) => `<div>${SC.esc(l)}</div>`).join("") + (extraHtml || "");
    if (navigator.vibrate) navigator.vibrate(kind === "ok" ? 80 : [60, 40, 60]);
  }

  function visitorLines(v) {
    if (!v) return [];
    const lines = [`${v.full_name}`, `Host: ${v.host || "—"} · ${v.department || "—"}`];
    if (v.mobile) lines.push(`Mobile: ${v.mobile}`);
    if (v.purpose) lines.push(`Purpose: ${v.purpose}`);
    return lines;
  }

  function showQueued(type, rec) {
    show("pending", "Saved - NOT verified yet",
      [`${label(type)} will be checked by the server when the connection returns.`,
        "Do NOT treat this person as authorised until it shows Verified."]);
    SC.toast("Saved offline as PENDING.", "warning");
    return rec;
  }

  // ------------------------------------------------------------ main scan flow
  async function handleText(text) {
    text = String(text || "").trim();
    if (!text || busy) return;
    const now = Date.now();
    if (text === lastText && now - lastAt < 4000) return;   // the camera sees the same code many times
    lastText = text; lastAt = now; busy = true;
    const action = mode();
    try {
      const r = await SC.api("/api/qr/verify", { method: "POST", body: { token: text, action } });
      if (r.status === 502 || r.status === 503 || r.status === 504) throw new SC.NetworkError("proxy");
      if (!r.ok) return show("bad", "Could not verify", [SC.errText(r)]);
      const d = r.data;
      if (!d.valid) {
        const v = d.visitor;
        return show("bad", `${String(d.code).replace(/_/g, " ").toUpperCase()}`, [d.message].concat(visitorLines(v)));
      }
      const opId = "op-" + SC.uuid();
      if ($("autoConfirm").checked) return await confirm(text, action, opId);
      show("ok", `VALID - ${label(action)}`, visitorLines(d.visitor),
        `<button class="btn btn-success btn-lg w-100 mt-3" id="confirmBtn">Confirm ${label(action)}</button>`);
      $("confirmBtn").addEventListener("click", () => confirm(text, action, opId));
    } catch (e) {
      if (!(e instanceof SC.NetworkError)) { show("bad", "Error", [String(e.message || e)]); return; }
      try { showQueued(action, await SCOffline.add(action, text)); }
      catch (ex) { show("bad", "Offline and cannot save", ["This browser blocks local storage. Scan again when online."]); }
    } finally {
      busy = false;
      renderQueue();
    }
  }

  async function confirm(text, action, opId) {
    busy = true;
    try {
      const r = await SC.api("/api/visitors/" + action, { method: "POST", body: { token: text, operation_id: opId } });
      if (r.status === 502 || r.status === 503 || r.status === 504) throw new SC.NetworkError("proxy");
      if (r.ok) {
        const d = r.data;
        const gate = d.visit && (action === "check-in" ? d.visit.check_in_gate : d.visit.check_out_gate);
        show("ok", `${label(action)} recorded`, visitorLines(d.visitor).concat(gate ? [`Gate: ${gate}`] : []));
      } else {
        const v = r.error && r.error.details && r.error.details.visitor;
        show("bad", String((r.error && r.error.code) || "error").replace(/_/g, " ").toUpperCase(),
          [SC.errText(r)].concat(visitorLines(v)));
      }
    } catch (e) {
      // The request may or may not have reached the server. We keep the SAME operation id:
      // if it did arrive, the server returns the stored result instead of repeating it.
      if (e instanceof SC.NetworkError) showQueued(action, await SCOffline.add(action, text, opId));
      else show("bad", "Error", [String(e.message || e)]);
    } finally {
      busy = false;
      renderQueue();
    }
  }

  // ------------------------------------------------------------------- camera
  function setStatus(t) { $("camStatus").textContent = t; }

  async function listCameras() {
    try {
      cameras = await Html5Qrcode.getCameras();
    } catch (e) { cameras = []; }
    const sel = $("cameraSelect");
    sel.innerHTML = cameras.length
      ? cameras.map((c, i) => `<option value="${i}">${SC.esc(c.label || "Camera " + (i + 1))}</option>`).join("")
      : '<option value="">Default camera</option>';
    // prefer a rear camera when the labels tell us which one it is
    const back = cameras.findIndex((c) => /back|rear|environment/i.test(c.label || ""));
    camIndex = back >= 0 ? back : 0;
    sel.value = String(camIndex);
    $("switchBtn").classList.toggle("d-none", cameras.length < 2);
  }

  async function start() {
    if (typeof Html5Qrcode === "undefined") return setStatus("Scanner library not loaded (no internet?). Use image upload instead.");
    if (running) return;
    if (!scanner) scanner = new Html5Qrcode("reader", { verbose: false });
    try {
      if (!cameras.length) await listCameras();
      const source = cameras.length ? { deviceId: { exact: cameras[camIndex].id } } : { facingMode: "environment" };
      await scanner.start(source, { fps: 10, qrbox: { width: 240, height: 240 } }, handleText, () => {});
      running = true;
      $("startBtn").classList.add("d-none"); $("stopBtn").classList.remove("d-none");
      setStatus("Scanning… hold the QR code inside the square.");
    } catch (e) {
      setStatus("Could not open the camera: " + (e && e.message ? e.message : e) + ". Allow camera access, or use image upload.");
    }
  }

  async function stop() {
    if (!scanner || !running) return;
    try { await scanner.stop(); } catch (e) { /* already stopped */ }
    running = false;
    $("stopBtn").classList.add("d-none"); $("startBtn").classList.remove("d-none");
    setStatus("Camera is off.");
  }

  $("startBtn").addEventListener("click", start);
  $("stopBtn").addEventListener("click", stop);
  $("cameraSelect").addEventListener("change", async () => {
    camIndex = Number($("cameraSelect").value) || 0;
    if (running) { await stop(); start(); }
  });
  $("switchBtn").addEventListener("click", async () => {
    camIndex = (camIndex + 1) % cameras.length;
    $("cameraSelect").value = String(camIndex);
    if (running) { await stop(); start(); }
  });

  // ------------------------------------------------- fallbacks: image + manual
  $("qrFile").addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    if (typeof Html5Qrcode === "undefined") return show("bad", "Scanner library not loaded", ["Paste the QR text instead."]);
    try {
      const reader = new Html5Qrcode("readerFile", { verbose: false });
      const text = await reader.scanFile(file, false);
      handleText(text);
    } catch (ex) {
      show("bad", "No QR code found in that image", ["Try a sharper, well-lit picture."]);
    }
    e.target.value = "";
  });
  $("manualBtn").addEventListener("click", () => { handleText($("manualToken").value); $("manualToken").value = ""; });
  $("manualToken").addEventListener("keydown", (e) => { if (e.key === "Enter") $("manualBtn").click(); });

  // ------------------------------------------------------------- offline queue
  async function renderQueue() {
    const body = $("queueRows");
    let rows = [];
    try { rows = (await SCOffline.all()).slice().reverse().slice(0, 25); } catch (e) { rows = []; }
    body.innerHTML = rows.length ? rows.map((r) => `<tr>
      <td class="small">${SC.fmtTime(r.scanned_at)}</td><td>${label(r.type)}</td><td>${SC.badge(r.status)}</td>
      <td class="small">${SC.esc(r.visitor ? r.visitor + " - " : "")}${SC.esc(r.message || (r.status === "PENDING" ? "Not verified yet" : ""))}</td></tr>`).join("")
      : '<tr><td colspan="4" class="text-muted text-center">No offline scans.</td></tr>';
  }
  SC.on("offline-changed", renderQueue);
  SC.on("sync-done", (s) => SC.notify(`Offline scans synced: ${s.success} verified, ${s.failed} rejected.`, s.failed ? "warning" : "success"));
  $("syncNow").addEventListener("click", async () => {
    if (!SC.canReachServer()) return SC.toast("Still offline - nothing was sent.", "warning");
    const s = await SCOffline.sync();
    if (!s || !s.total) SC.toast(s && s.error ? s.error : "Nothing to sync.", "info");
  });
  $("clearDone").addEventListener("click", () => SCOffline.clearFinished());

  // --------------------------------------------------------------------- init
  if (!window.isSecureContext) $("httpsWarn").classList.remove("d-none");
  window.addEventListener("beforeunload", () => { if (scanner && running) scanner.stop().catch(() => {}); });
  renderQueue();
})();
