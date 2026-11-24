/*
 * common.js - loaded on EVERY page. Creates the global object `SC` with shared helpers.
 *
 *   SC.api(path, opts)   fetch() wrapper: adds the device id + CSRF header, measures the
 *                        round-trip time and detects "server unreachable" (network failure).
 *   SC.conn              live connection state (browser online? server reachable? latency?)
 *   SC.on / SC.emit      a tiny event bus so scripts can talk to each other
 *   SC.toast / SC.badge  small UI helpers
 *
 * Data-communication ideas shown here
 *   * Request/response cycle: every SC.api() call is one HTTP request + one response.
 *   * Latency: round-trip time (RTT) is measured with performance.now() around fetch().
 *   * Network error handling: a TypeError from fetch() means the request never reached
 *     the server (offline, DNS failure, connection refused) - we report it separately
 *     from HTTP errors such as 404/500.
 */
(function () {
  "use strict";
  const SC = (window.SC = window.SC || {});
  const meta = document.querySelector('meta[name="csrf-token"]');
  SC.csrf = meta ? meta.content : "";
  SC.role = document.body.dataset.role || "";

  // ------------------------------------------------------------------ helpers
  SC.$ = (id) => document.getElementById(id);
  SC.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  SC.fmt = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—");
  SC.fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
  SC.debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // Random id. crypto.randomUUID only exists on HTTPS/localhost, so we fall back.
  SC.uuid = function () {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const b = new Uint8Array(16);
    crypto.getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  };

  // Device id: random, created once per browser. It is sent as the X-Device-Id header and
  // stored in the server's communication log so each phone / PC can be told apart.
  SC.deviceId = (function () {
    try {
      let d = localStorage.getItem("sc_device_id");
      if (!d) { d = "dev-" + SC.uuid(); localStorage.setItem("sc_device_id", d); }
      return d;
    } catch (e) { return "dev-" + SC.uuid(); }
  })();

  // Status -> colour. Works for visitor, approval, sync and QR verdict states.
  const BADGE = {
    PENDING: ["warning", "Pending"], APPROVED: ["primary", "Approved"], REJECTED: ["danger", "Rejected"],
    INSIDE: ["success", "Inside"], COMPLETED: ["secondary", "Completed"],
    SUCCESS: ["success", "Verified"], FAILED: ["danger", "Failed"], SYNCING: ["info", "Syncing"],
    valid: ["success", "Valid"], expired: ["danger", "Expired"], invalid: ["danger", "Invalid"],
    already_used: ["danger", "Already used"], revoked: ["secondary", "Replaced"],
    active: ["success", "Active"], in_use: ["info", "In use"], used: ["secondary", "Used"],
  };
  SC.badge = function (s) {
    const b = BADGE[s] || ["secondary", s];
    return `<span class="badge badge-status text-bg-${b[0]}">${SC.esc(b[1])}</span>`;
  };

  SC.toast = function (message, kind) {
    const area = SC.$("toastArea");
    if (!area || !window.bootstrap) return;
    const el = document.createElement("div");
    el.className = `toast align-items-center text-bg-${kind || "primary"} border-0`;
    el.setAttribute("role", "status");
    el.innerHTML = `<div class="d-flex"><div class="toast-body">${SC.esc(message)}</div>` +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
    area.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: 4000 });
    el.addEventListener("hidden.bs.toast", () => el.remove());
    t.show();
  };

  // ------------------------------------------------------------------ events
  SC.on = (name, fn) => document.addEventListener("sc:" + name, (e) => fn(e.detail));
  SC.emit = (name, detail) => document.dispatchEvent(new CustomEvent("sc:" + name, { detail }));

  // ------------------------------------------------------- connection state
  SC.conn = { browserOnline: navigator.onLine, serverUp: true, rtt: null, serverMs: null, history: [] };
  SC.canReachServer = () => SC.conn.browserOnline && SC.conn.serverUp;
  let wasUp = true;

  function renderNet() {
    const badge = SC.$("netBadge");
    if (!badge) return;
    const c = SC.conn;
    let dot = "on", text = "Online";
    if (!c.browserOnline) { dot = "off"; text = "Offline"; }
    else if (!c.serverUp) { dot = "off"; text = "Server unreachable"; }
    else if (c.rtt != null) { text = `Online · ${Math.round(c.rtt)} ms`; if (c.rtt > 800) dot = "warn"; }
    badge.innerHTML = `<span class="dot ${dot}"></span><span class="txt">${SC.esc(text)}</span>`;
    badge.title = c.serverMs != null
      ? `Round trip ${c.rtt.toFixed(1)} ms = server work ${c.serverMs.toFixed(1)} ms + network ${Math.max(c.rtt - c.serverMs, 0).toFixed(1)} ms`
      : "Connection to the server";
    const banner = SC.$("offlineBanner");
    if (banner) banner.classList.toggle("d-none", SC.canReachServer());
  }

  function setConn(patch) {
    Object.assign(SC.conn, patch);
    renderNet();
    const up = SC.canReachServer();
    if (up !== wasUp) {
      wasUp = up;
      SC.emit(up ? "online" : "offline", SC.conn);
      SC.toast(up ? "Back online" : "Connection lost - working offline", up ? "success" : "warning");
    }
  }
  SC.setServerReachable = (v) => { if (SC.conn.serverUp !== v) setConn({ serverUp: v }); };
  window.addEventListener("online", () => { setConn({ browserOnline: true }); heartbeat(); });
  window.addEventListener("offline", () => setConn({ browserOnline: false }));

  // --------------------------------------------------------------------- API
  class NetworkError extends Error {}
  SC.NetworkError = NetworkError;

  /**
   * SC.api("/api/x", {method:"POST", body:{...}, headers:{...}})
   * Returns {ok, status, data, rtt, serverMs}.
   * Throws SC.NetworkError ONLY if the request could not reach the server at all.
   * API replies look like {ok:true,data:{...}} or {ok:false,error:{code,message,details}}.
   */
  SC.api = async function (path, opts) {
    opts = opts || {};
    const method = opts.method || "GET";
    const headers = Object.assign({ Accept: "application/json", "X-Device-Id": SC.deviceId }, opts.headers || {});
    const init = { method, headers, credentials: "same-origin", cache: "no-store" };
    if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
    if (method !== "GET" && SC.csrf) headers["X-CSRF-Token"] = SC.csrf;
    const t0 = performance.now();
    let resp;
    try {
      resp = await fetch(path, init);
    } catch (e) {
      SC.setServerReachable(false);
      throw new NetworkError("Network unreachable");
    }
    const rtt = performance.now() - t0;
    let json = {};
    try { json = await resp.json(); } catch (e) { /* body was not JSON */ }
    // A page served from the offline cache may carry an old CSRF token. Fetch a fresh one
    // once and repeat the request.
    if (resp.status === 403 && json.error && json.error.code === "csrf_failed" && !opts._retried && SC.role) {
      const me = await SC.api("/api/auth/me", { quiet401: true });
      if (me.ok && me.data.csrf_token) {
        SC.csrf = me.data.csrf_token;
        return SC.api(path, Object.assign({}, opts, { _retried: true }));
      }
    }
    const sm = parseFloat(resp.headers.get("X-Response-Time-ms"));
    // 502/503/504 come from a proxy when the real server is down or still waking up.
    SC.setServerReachable(![502, 503, 504].includes(resp.status));
    if (resp.status === 401 && !opts.quiet401 && SC.role) SC.emit("auth-expired", {});
    return {
      ok: resp.ok && json.ok !== false, status: resp.status,
      data: json.data || {}, error: json.error || null,
      rtt, serverMs: isNaN(sm) ? null : sm,
    };
  };

  // Human readable error text from an API reply (including field errors).
  SC.errText = function (r) {
    if (!r || !r.error) return "Something went wrong.";
    const d = r.error.details;
    if (d && typeof d === "object" && !d.visitor) {
      const parts = Object.values(d).filter((x) => typeof x === "string");
      if (parts.length) return parts.join(" ");
    }
    return r.error.message || "Something went wrong.";
  };

  // --------------------------------------------------------------- heartbeat
  // Every few seconds GET /api/network/ping and time it. These are REAL measurements and are
  // shown in the top bar and on the Network Monitor page.
  let hb = null;
  async function heartbeat() {
    clearTimeout(hb);
    try {
      const r = await SC.api("/api/network/ping", { quiet401: true });
      if (![502, 503, 504].includes(r.status)) {
        SC.conn.history.push({ t: Date.now(), rtt: r.rtt, serverMs: r.serverMs });
        if (SC.conn.history.length > 60) SC.conn.history.shift();
        setConn({ rtt: r.rtt, serverMs: r.serverMs, serverUp: true });
        SC.emit("heartbeat", r);
      }
    } catch (e) { /* already recorded by SC.api */ }
    hb = setTimeout(heartbeat, document.hidden ? 20000 : 5000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) heartbeat(); });

  // ----------------------------------------------------------- service worker
  // The service worker caches the app files so pages still open without a network.
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => { /* e.g. self-signed cert not accepted */ });
    });
  }

  document.addEventListener("DOMContentLoaded", () => { renderNet(); heartbeat(); });
})();
