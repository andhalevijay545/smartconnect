/* admin_audit.js - read-only audit trail (GET /api/admin/audit). */
(function () {
  "use strict";
  const SC = window.SC;
  const $ = SC.$;
  let page = 1, pages = 1;
  async function load() {
    const p = new URLSearchParams({ page, per_page: 25 });
    if ($("aAction").value.trim()) p.set("action", $("aAction").value.trim());
    const r = await SC.api("/api/admin/audit?" + p);
    if (!r.ok) return;
    pages = r.data.pages || 1;
    $("rows").innerHTML = r.data.items.map((a) => `<tr><td class="small">${SC.fmt(a.timestamp)}</td>
      <td>${SC.esc(a.actor_type)}${a.actor_id ? " #" + a.actor_id : ""}</td><td class="mono">${SC.esc(a.action)}</td>
      <td class="small">${SC.esc(a.entity_type || "")} ${SC.esc(a.entity_id || "")}</td><td class="small">${SC.esc(a.details || "")}</td>
      <td class="mono">${SC.esc(a.ip || "")}</td></tr>`).join("") || '<tr><td colspan="6" class="text-center text-muted py-4">No entries.</td></tr>';
    $("pageInfo").textContent = `Page ${r.data.page} of ${pages} · ${r.data.total} entries`;
    $("prevBtn").disabled = page <= 1; $("nextBtn").disabled = page >= pages;
  }
  $("aAction").addEventListener("input", SC.debounce(() => { page = 1; load(); }, 300));
  $("prevBtn").addEventListener("click", () => { if (page > 1) { page--; load(); } });
  $("nextBtn").addEventListener("click", () => { if (page < pages) { page++; load(); } });
  load();
})();
