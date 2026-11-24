/*
 * app-shell.js - loaded on every logged-in page (admin / security / host).
 *   * sidebar toggle on phones, logout button
 *   * WebSocket (Socket.IO) connection for live updates
 *   * notification panel
 *
 * WebSocket vs HTTP: normal HTTP is "ask, then answer". A WebSocket is ONE long-lived TCP
 * connection that stays open, so the server can PUSH an event the moment something happens
 * (a visitor registers, a guard scans a pass) without the browser polling.
 * The server decides which "rooms" each connection joins (role:admin, host:3 ...), so a user
 * only ever receives events they are allowed to see.
 */
(function () {
  "use strict";
  const SC = window.SC;

  // ---------------------------------------------------------- sidebar + logout
  const side = SC.$("sidebar");
  const toggle = SC.$("sidebarToggle");
  if (toggle && side) toggle.addEventListener("click", () => side.classList.toggle("open"));

  async function logout() {
    try { await SC.api("/api/auth/logout", { method: "POST", quiet401: true }); } catch (e) { /* ignore */ }
    // Remove cached copies of private pages from this device.
    if (navigator.serviceWorker && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage("clear-pages");
    window.location.href = "/login";
  }
  document.querySelectorAll('[data-action="logout"]').forEach((b) => b.addEventListener("click", logout));
  SC.on("auth-expired", () => { window.location.href = "/login"; });

  // ------------------------------------------------------------ notifications
  const list = SC.$("notifList");
  const countEl = SC.$("notifCount");
  let unread = 0;

  SC.notify = function (text, kind) {
    if (!list) return;
    if (list.querySelector(".text-muted")) list.innerHTML = "";
    const item = document.createElement("div");
    item.className = "notif-item";
    item.innerHTML = `<div>${SC.esc(text)}</div><div class="text-muted small">${new Date().toLocaleTimeString()}</div>`;
    list.prepend(item);
    unread += 1;
    if (countEl) { countEl.textContent = unread; countEl.classList.remove("d-none"); }
    if (kind) SC.toast(text, kind);
  };
  const clear = SC.$("notifClear");
  if (clear) clear.addEventListener("click", () => {
    list.innerHTML = '<div class="text-muted p-3 small">No notifications yet.</div>';
    unread = 0; if (countEl) countEl.classList.add("d-none");
  });

  // ---------------------------------------------------------------- WebSocket
  const wsBadge = SC.$("wsBadge");
  function wsState(on, text) {
    SC.wsConnected = on;
    if (wsBadge) wsBadge.innerHTML = `<span class="dot ${on ? "on" : "off"}"></span><span class="txt">${SC.esc(text)}</span>`;
  }

  const EVENTS = {
    visitor_registered: (d) => [`New visitor: ${d.full_name} (to meet ${d.host || "?"})`, "primary"],
    approval_updated: (d) => [`${d.full_name} was ${String(d.approval_status || "").toLowerCase()}`,
      d.approval_status === "APPROVED" ? "success" : "danger"],
    visitor_checked_in: (d) => [`${d.full_name} checked in at ${d.gate || "a gate"}`, "success"],
    visitor_checked_out: (d) => [`${d.full_name} checked out at ${d.gate || "a gate"}`, null],
    sync_completed: (d) => [`Offline sync finished: ${d.success} ok, ${d.failed} failed (${d.total} total)`, "info"],
    network_status_changed: (d) => [`Live clients: ${d.ws_clients} (${String(d.reason || "").replace("_", " ")})`, null],
  };

  if (window.io) {
    // The login cookie travels with the handshake, so the server knows who we are.
    const socket = io({ auth: { device_id: SC.deviceId }, withCredentials: true });
    SC.socket = socket;
    wsState(false, "Live: connecting");
    socket.on("connect", () => wsState(true, "Live: on"));
    socket.on("disconnect", () => wsState(false, "Live: off"));
    socket.on("connect_error", () => wsState(false, "Live: off"));
    Object.keys(EVENTS).forEach((name) => {
      socket.on(name, (data) => {
        const [text, kind] = EVENTS[name](data || {});
        if (name !== "network_status_changed") SC.notify(text, kind);
        SC.emit("ws:" + name, data || {});
        SC.emit("ws:any", { name, data: data || {} });
      });
    });
  } else {
    wsState(false, "Live: unavailable");
  }
})();
