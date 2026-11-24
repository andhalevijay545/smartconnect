/*
 * dashboard.js - live statistics for the admin, security and host dashboards (Module 6).
 * Numbers come from GET /api/dashboard/stats and are refreshed
 *   * immediately whenever a WebSocket event arrives (visitor registered / checked in / ...),
 *   * and every 30 seconds as a safety net.
 */
(function () {
  "use strict";
  const SC = window.SC;
  const set = (id, v) => { const el = SC.$(id); if (el) el.textContent = v; };

  const ICON = { registered: "NEW", check_in: "IN", check_out: "OUT", approved: "OK", rejected: "NO" };
  const TEXT = {
    registered: "registered", check_in: "checked in", check_out: "checked out",
    approved: "approved", rejected: "rejected",
  };

  function render(d) {
    set("statInside", d.inside_now);
    set("statIn", d.today_check_ins);
    set("statOut", d.today_check_outs);
    set("statPending", d.pending_approvals);
    set("statRegistered", d.registered_today);
    set("statExpected", d.expected_today);
    set("statDate", d.date);

    SC.chart("chartHourly", {
      type: "bar",
      labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0")),
      datasets: [{ label: "Check-ins", data: d.hourly_check_ins }],
    });
    const sc = d.status_counts;
    SC.chart("chartStatus", {
      type: "doughnut",
      labels: Object.keys(sc).map((s) => s.charAt(0) + s.slice(1).toLowerCase()),
      datasets: [{ data: Object.values(sc) }],
    });

    const gateBody = SC.$("gateRows");
    if (gateBody) {
      gateBody.innerHTML = d.gates.length ? d.gates.map((g) => `<tr>
        <td>${SC.esc(g.name)} ${g.is_active ? "" : '<span class="badge text-bg-secondary">disabled</span>'}</td>
        <td class="text-end">${g.inside_now}</td><td class="text-end">${g.check_ins_today}</td>
        <td class="text-end">${g.check_outs_today}</td><td class="text-end">${g.check_ins_total}</td></tr>`).join("")
        : '<tr><td colspan="5" class="text-muted text-center">No gates yet.</td></tr>';
    }
    const feed = SC.$("feed");
    if (feed) {
      feed.innerHTML = d.recent.length ? d.recent.map((e) => `<li>
        <span class="ico ${e.type}">${ICON[e.type] || "•"}</span>
        <div><div><strong>${SC.esc(e.name)}</strong> ${TEXT[e.type] || e.type}</div>
        <div class="small text-muted">${SC.esc(e.detail)} · ${SC.fmt(e.at)}</div></div></li>`).join("")
        : '<li class="text-muted">No activity yet.</li>';
    }
    const gate = SC.$("myGate");
    if (gate && d.my_gate) gate.textContent = d.my_gate.name || "No gate assigned";
    SC.emit("dashboard-data", d);
  }

  async function load() {
    try {
      const r = await SC.api("/api/dashboard/stats");
      if (r.ok) render(r.data);
    } catch (e) { /* offline: keep the numbers that are already on screen */ }
  }
  const soon = SC.debounce(load, 400);
  SC.on("ws:any", soon);
  SC.on("online", load);
  setInterval(load, 30000);
  load();
})();
