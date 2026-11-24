/*
 * admin_network.js - Network Monitoring Dashboard (Module 9).
 *   GET /api/network/status   -> server, database, connection, WebSocket clients, sync counts
 *   GET /api/network/metrics  -> numbers calculated from the communication_logs table
 *   GET /api/network/dns      -> timed DNS lookup
 * The "browser round trip" chart is measured in THIS browser (see common.js heartbeat).
 * Nothing is simulated: with no traffic the charts are simply empty.
 */
(function () {
  "use strict";
  const SC = window.SC;
  const $ = SC.$;
  const set = (id, v, sub) => { $(id).textContent = v; if (sub !== undefined) $(id + "Sub") && ($(id + "Sub").textContent = sub); };
  const ms = (v) => (v == null ? "–" : `${Number(v).toFixed(1)} ms`);

  function drawLive() {
    const h = SC.conn.history;
    SC.chart("cLive", { type: "line", labels: h.map((x) => new Date(x.t).toLocaleTimeString()),
      datasets: [{ label: "Round trip (ms)", data: h.map((x) => +x.rtt.toFixed(1)) },
        { label: "Server work (ms)", data: h.map((x) => (x.serverMs == null ? null : +x.serverMs.toFixed(1))) }] });
    if (h.length) { const last = h[h.length - 1]; set("mRtt", ms(last.rtt)); $("mRttSub").textContent = last.serverMs != null ? `network ≈ ${Math.max(last.rtt - last.serverMs, 0).toFixed(1)} ms` : ""; }
  }

  async function loadStatus() {
    try {
      const r = await SC.api("/api/network/status");
      if (!r.ok) return;
      const s = r.data;
      $("mAvail").innerHTML = s.available && s.database.ok ? '<span class="text-success">Online</span>' : '<span class="text-danger">Degraded</span>';
      const up = s.uptime_seconds; $("mUptime").textContent = `Up ${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m · ${s.server.mode} mode`;
      $("mWs").textContent = s.websocket.connected;
      $("mDb").textContent = ms(s.database.latency_ms); $("mDbEngine").textContent = s.database.engine || "";
      $("wsRows").innerHTML = s.websocket.clients.map((c) => `<tr><td>${SC.esc(c.role)}</td><td class="mono">${SC.esc(String(c.device_id).slice(0, 14))}</td><td class="mono">${SC.esc(c.ip)}</td><td>${SC.esc(c.network_type)}</td></tr>`).join("")
        || '<tr><td colspan="4" class="text-center text-muted">No clients.</td></tr>';
      const sy = s.sync;
      SC.chart("cSync", { type: "doughnut", labels: ["Pending", "Verified", "Failed"], datasets: [{ data: [sy.pending, sy.success, sy.failed], backgroundColor: ["#f0a30a", "#1f9d55", "#d64545"] }] });
      $("syncLast").textContent = sy.last_sync_at ? `Last offline sync: ${SC.fmt(sy.last_sync_at)}` : "No offline sync yet.";
      const c = s.connection;
      $("connInfo").innerHTML = [
        ["Your IP address", c.client_ip + (c.client_port ? ":" + c.client_port : "")], ["Network type", c.network_type + (c.network_type === "LAN" ? " (private address)" : " (public Internet)")],
        ["Protocol", `${c.scheme.toUpperCase()} · ${c.http_version || ""}`], ["TLS encryption", c.tls ? "Yes - traffic is encrypted" : "No (plain HTTP)"],
        ["Host header", c.host_header], ["Server host name", s.server.hostname], ["Server LAN IPs", (s.server.lan_ips || []).join(", ") || "–"],
        ["Server port", s.server.port || "–"], ["WebSocket engine", s.server.async_mode],
      ].map(([k, v]) => `<dt class="col-5">${SC.esc(k)}</dt><dd class="col-7 mono">${SC.esc(v)}</dd>`).join("");
    } catch (e) { $("mAvail").innerHTML = '<span class="text-danger">Unreachable</span>'; }
  }

  async function loadMetrics() {
    try {
      const r = await SC.api("/api/network/metrics?minutes=" + $("window").value);
      if (!r.ok) return;
      const m = r.data, t = m.totals, rt = m.response_time_ms;
      $("mTotal").textContent = t.requests; $("mOk").textContent = t.successful; $("mFail").textContent = t.failed;
      $("mRate").textContent = t.success_rate == null ? "No traffic yet" : `${t.success_rate}% success · ${t.tls_requests} over TLS`;
      $("mAvg").textContent = t.requests ? ms(rt.avg) : "–";
      $("mPct").textContent = t.requests ? `p50 ${rt.p50} · p95 ${rt.p95} · max ${rt.max} ms` : "No traffic yet";
      SC.chart("cTimeline", { type: "bar", labels: m.timeline.map((x) => new Date(x.t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })),
        datasets: [{ label: "Requests", data: m.timeline.map((x) => x.count), yAxisID: "y" },
          { label: "Avg ms", type: "line", data: m.timeline.map((x) => x.avg_ms), yAxisID: "y1", borderColor: "#f0a30a", backgroundColor: "#f0a30a", fill: false }],
        options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false } } } } });
      SC.chart("cCodes", { type: "bar", labels: Object.keys(m.status_codes), datasets: [{ label: "Responses", data: Object.values(m.status_codes) }] });
      SC.chart("cNet", { type: "doughnut", labels: Object.keys(m.network_types), datasets: [{ data: Object.values(m.network_types) }] });
      $("topRows").innerHTML = m.top_endpoints.map((e) => `<tr><td class="mono">${SC.esc(e.method)} ${SC.esc(e.endpoint)}</td><td class="text-end">${e.count}</td><td class="text-end">${e.avg_ms}</td><td class="text-end">${e.errors}</td></tr>`).join("")
        || '<tr><td colspan="4" class="text-center text-muted">No traffic yet.</td></tr>';
      $("histRows").innerHTML = m.history.map((h) => `<tr class="${h.success ? "" : "table-danger"}"><td class="small">${SC.fmtTime(h.t)}</td>
        <td class="mono">${SC.esc(String(h.device_id).slice(0, 12))}</td><td>${SC.esc(h.network || "")}</td><td>${SC.esc(h.method)}</td>
        <td class="mono">${SC.esc(h.endpoint)}</td><td class="text-end">${h.status}</td><td class="text-end">${h.ms}</td><td>${h.tls ? "yes" : "no"}</td></tr>`).join("")
        || '<tr><td colspan="8" class="text-center text-muted">No requests recorded in this window.</td></tr>';
    } catch (e) { /* offline */ }
  }

  $("dnsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const host = $("dnsHost").value.trim();
    const r = await SC.api("/api/network/dns" + (host ? "?host=" + encodeURIComponent(host) : ""));
    $("dnsOut").innerHTML = r.ok
      ? `<strong>${SC.esc(r.data.hostname)}</strong> → ${r.data.scope.map((a) => `<span class="mono">${SC.esc(a.ip)}</span> (${SC.esc(a.network)})`).join(", ")}<br>Lookup took <strong>${r.data.lookup_ms} ms</strong>`
      : `<span class="text-danger">${SC.esc(SC.errText(r))}</span>`;
  });

  const refresh = () => { loadStatus(); loadMetrics(); drawLive(); };
  SC.on("heartbeat", drawLive);
  SC.on("ws:network_status_changed", loadStatus);
  SC.on("ws:sync_completed", loadStatus);
  $("window").addEventListener("change", loadMetrics);
  setInterval(refresh, 5000);
  refresh();
})();
