/* admin_reports.js - daily / weekly / monthly reports (GET /api/reports/<period>) and CSV export. */
(function () {
  "use strict";
  const SC = window.SC;
  const $ = SC.$;
  const today = new Date();
  $("anchor").value = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"), String(today.getDate()).padStart(2, "0")].join("-");

  async function load() {
    const q = `?date=${encodeURIComponent($("anchor").value)}`;
    $("csvBtn").href = `/api/reports/${$("period").value}/export${q}`;
    const r = await SC.api(`/api/reports/${$("period").value}${q}`);
    if (!r.ok) return SC.toast(SC.errText(r), "danger");
    const d = r.data, s = d.summary;
    $("label").textContent = `${d.period[0].toUpperCase() + d.period.slice(1)} report: ${d.label}`;
    $("sReg").textContent = s.registered; $("sApp").textContent = s.approved; $("sRej").textContent = s.rejected;
    $("sIn").textContent = s.check_ins; $("sOut").textContent = s.check_outs; $("sAvg").textContent = s.avg_visit_minutes;

    SC.chart("cDay", { type: "line", labels: d.by_day.map((x) => x.date.slice(5)),
      datasets: [{ label: "Registered", data: d.by_day.map((x) => x.registered) }, { label: "Check-ins", data: d.by_day.map((x) => x.check_ins) }] });
    SC.chart("cDept", { type: "doughnut", labels: d.by_department.map((x) => x.department), datasets: [{ data: d.by_department.map((x) => x.check_ins) }] });
    SC.chart("cGate", { type: "bar", labels: d.by_gate.map((x) => x.gate),
      datasets: [{ label: "In", data: d.by_gate.map((x) => x.check_ins) }, { label: "Out", data: d.by_gate.map((x) => x.check_outs) }] });

    $("tDept").innerHTML = d.by_department.map((x) => `<tr><td>${SC.esc(x.department)}</td><td class="text-end">${x.registered}</td><td class="text-end">${x.check_ins}</td></tr>`).join("");
    $("tGate").innerHTML = d.by_gate.map((x) => `<tr><td>${SC.esc(x.gate)}</td><td class="text-end">${x.check_ins}</td><td class="text-end">${x.check_outs}</td></tr>`).join("");
    $("tHist").innerHTML = d.history.map((x) => `<tr><td>${SC.esc(x.visitor)}</td><td>${SC.esc(x.department)}</td><td>${SC.esc(x.host)}</td>
      <td class="small">${SC.esc(x.purpose)}</td><td class="small">${SC.fmt(x.check_in_at)}</td><td class="small">${SC.fmt(x.check_out_at)}</td>
      <td>${SC.esc(x.entry_gate)}</td><td>${SC.esc(x.exit_gate)}</td><td class="text-end">${x.duration_min == null ? "—" : x.duration_min}</td></tr>`).join("")
      || '<tr><td colspan="9" class="text-center text-muted py-3">No visits in this period.</td></tr>';
  }
  $("loadBtn").addEventListener("click", load);
  $("period").addEventListener("change", load);
  load();
})();
