/*
 * pass.js - the visitor's own page: QR pass + live visit status.
 * The visitor has no password. Their device keeps {public_id, access_key} in localStorage and
 * sends the key in the X-Visitor-Key header. The server stores only a HASH of that key.
 */
(function () {
  "use strict";
  const SC = window.SC;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("sc_visit") || "null"); } catch (e) { saved = null; }

  if (!saved || !saved.public_id || !saved.access_key) {
    SC.$("noPass").classList.remove("d-none");
    return;
  }
  SC.$("passView").classList.remove("d-none");
  if (saved.qr_image) SC.$("qrImg").src = saved.qr_image;
  SC.$("qrExpiry").textContent = SC.fmt(saved.qr_expires_at);
  const keyHeader = { "X-Visitor-Key": saved.access_key };

  function timeline(v) {
    const approvedOrBeyond = ["APPROVED", "INSIDE", "COMPLETED"].includes(v.status);
    const steps = [
      ["Registered", true, false],
      v.status === "REJECTED"
        ? ["Rejected by host" + (v.approval && v.approval.remarks ? ": " + v.approval.remarks : ""), false, true]
        : ["Approved by host", approvedOrBeyond, false],
      ["Checked in at gate" + (v.last_check_in_at ? " · " + SC.fmt(v.last_check_in_at) : ""),
        ["INSIDE", "COMPLETED"].includes(v.status), false],
      ["Checked out" + (v.last_check_out_at ? " · " + SC.fmt(v.last_check_out_at) : ""), v.status === "COMPLETED", false],
    ];
    let current = steps.findIndex((s) => !s[1] && !s[2]);
    SC.$("timeline").innerHTML = steps.map((s, i) => {
      const cls = s[2] ? "bad" : s[1] ? "done" : i === current ? "current" : "";
      return `<li class="${cls}">${SC.esc(s[0])}</li>`;
    }).join("");
  }

  function render(v) {
    SC.$("vName").textContent = v.full_name;
    SC.$("vMeta").textContent = v.mobile;
    SC.$("vStatus").innerHTML = SC.badge(v.status);
    SC.$("vHost").textContent = v.host || "—";
    SC.$("vDept").textContent = v.department || "—";
    SC.$("vPurpose").textContent = v.purpose;
    SC.$("vExpected").textContent = SC.fmt(v.expected_at);
    SC.$("vPass").innerHTML = v.pass ? SC.badge(v.pass.state) : "—";
    timeline(v);
  }

  async function refresh() {
    try {
      const r = await SC.api("/api/visitors/" + saved.public_id, { headers: keyHeader, quiet401: true });
      if (r.ok) render(r.data.visitor);
      else if (r.status === 401) SC.toast("This pass link is no longer valid on this device.", "danger");
    } catch (e) { SC.toast("Offline - showing the last saved pass.", "warning"); }
  }

  SC.$("newPassBtn").addEventListener("click", async () => {
    if (!confirm("Get a new QR pass? The current one will stop working.")) return;
    try {
      const r = await SC.api("/api/qr/generate", { method: "POST", headers: keyHeader, body: { visitor_id: saved.public_id } });
      if (!r.ok) return SC.toast(SC.errText(r), "danger");
      saved.qr_image = r.data.qr.image; saved.qr_expires_at = r.data.qr.expires_at;
      localStorage.setItem("sc_visit", JSON.stringify(saved));
      SC.$("qrImg").src = saved.qr_image;
      SC.$("qrExpiry").textContent = SC.fmt(saved.qr_expires_at);
      SC.toast("New QR pass created.", "success");
      refresh();
    } catch (e) { SC.toast("You are offline. Try again when connected.", "warning"); }
  });

  // Live updates: this socket joins ONLY room visitor:<public_id> (proved by the access key).
  if (window.io) {
    const socket = io({ auth: { device_id: SC.deviceId, public_id: saved.public_id, key: saved.access_key } });
    ["approval_updated", "visitor_checked_in", "visitor_checked_out"].forEach((ev) => socket.on(ev, () => {
      SC.toast("Your visit was updated.", "primary");
      refresh();
    }));
  }
  refresh();
  setInterval(refresh, 30000);  // fallback if the WebSocket is blocked
})();
