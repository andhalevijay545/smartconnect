/* visitors_list.js - searchable visitor table + detail modal (GET /api/visitors, GET /api/visitors/<id>). */
(function () {
  "use strict";
  const SC = window.SC;
  const $ = SC.$;
  let page = 1, pages = 1;
  const canReissue = SC.role === "admin" || SC.role === "host";
  const modal = new bootstrap.Modal($("visitorModal"));

  function params() {
    const p = new URLSearchParams({ page, per_page: 15 });
    [["q", "fQ"], ["status", "fStatus"], ["department_id", "fDept"], ["date_from", "fFrom"], ["date_to", "fTo"]]
      .forEach(([k, id]) => { const v = $(id).value.trim(); if (v) p.set(k, v); });
    return p.toString();
  }

  async function load() {
    try {
      const r = await SC.api("/api/visitors?" + params());
      if (!r.ok) return;
      const d = r.data;
      pages = d.pages || 1;
      $("rows").innerHTML = d.items.length ? d.items.map((v) => `<tr>
        <td><strong>${SC.esc(v.full_name)}</strong><div class="small text-muted">${SC.esc(v.purpose)}</div></td>
        <td class="mono">${SC.esc(v.mobile)}</td><td>${SC.esc(v.host || "")}</td><td>${SC.esc(v.department || "")}</td>
        <td class="small">${SC.fmt(v.expected_at)}</td><td>${SC.badge(v.status)}</td><td>${SC.esc(v.last_gate || "—")}</td>
        <td class="text-end"><button class="btn btn-outline-primary btn-sm" data-id="${v.public_id}">View</button></td></tr>`).join("")
        : '<tr><td colspan="8" class="text-center text-muted py-4">No visitors found.</td></tr>';
      $("pageInfo").textContent = `Page ${d.page} of ${pages} · ${d.total} visitor(s)`;
      $("prevBtn").disabled = page <= 1; $("nextBtn").disabled = page >= pages;
    } catch (e) { $("rows").innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Offline - cannot load visitors.</td></tr>'; }
  }

  async function openDetail(id) {
    const r = await SC.api("/api/visitors/" + id);
    if (!r.ok) return SC.toast(SC.errText(r), "danger");
    const v = r.data.visitor;
    $("mTitle").textContent = v.full_name;
    const visits = (v.visits || []).map((x) => `<tr><td>${SC.fmt(x.check_in_at)}</td><td>${SC.esc(x.check_in_gate || "")}</td>
      <td>${SC.fmt(x.check_out_at)}</td><td>${SC.esc(x.check_out_gate || "")}</td><td>${SC.esc(x.source)}</td></tr>`).join("");
    $("mBody").innerHTML = `
      <div class="d-flex justify-content-between mb-2">${SC.badge(v.status)}
        <span class="small text-muted">Pass: ${v.pass ? SC.badge(v.pass.state) : "—"}</span></div>
      <dl class="row small mb-3">
        <dt class="col-4">Mobile</dt><dd class="col-8 mono">${SC.esc(v.mobile)}</dd>
        ${v.email ? `<dt class="col-4">Email</dt><dd class="col-8">${SC.esc(v.email)}</dd>` : ""}
        ${v.address ? `<dt class="col-4">Address</dt><dd class="col-8">${SC.esc(v.address)}</dd>` : ""}
        <dt class="col-4">Host</dt><dd class="col-8">${SC.esc(v.host || "")} (${SC.esc(v.department || "")})</dd>
        <dt class="col-4">Purpose</dt><dd class="col-8">${SC.esc(v.purpose)}</dd>
        <dt class="col-4">Expected</dt><dd class="col-8">${SC.fmt(v.expected_at)}</dd>
        <dt class="col-4">Approval</dt><dd class="col-8">${v.approval ? SC.badge(v.approval.status) + " " + SC.esc(v.approval.remarks || "") : "—"}</dd>
      </dl>
      <h6>Visit history</h6>
      <div class="table-wrap"><table class="table table-sm"><thead><tr><th>In</th><th>Gate</th><th>Out</th><th>Gate</th><th>Source</th></tr></thead>
      <tbody>${visits || '<tr><td colspan="5" class="text-muted text-center">No visits yet.</td></tr>'}</tbody></table></div>
      <div id="newQr" class="text-center mt-3"></div>`;
    $("mFoot").innerHTML = canReissue && !["REJECTED", "COMPLETED"].includes(v.status)
      ? '<button class="btn btn-outline-primary" id="reissueBtn">Issue new QR pass</button>' : "";
    const btn = $("reissueBtn");
    if (btn) btn.addEventListener("click", async () => {
      if (!confirm("Issue a new QR pass? The visitor's current pass will stop working.")) return;
      const g = await SC.api("/api/qr/generate", { method: "POST", body: { visitor_id: v.public_id } });
      if (!g.ok) return SC.toast(SC.errText(g), "danger");
      $("newQr").innerHTML = `<div class="qr-box d-inline-block"><img src="${g.data.qr.image}" alt="New QR pass" style="max-width:240px"></div>
        <div class="small text-muted mt-1">Valid until ${SC.fmt(g.data.qr.expires_at)}. Shown once - print or share it now.</div>`;
    });
    modal.show();
  }

  $("rows").addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) openDetail(b.dataset.id); });
  ["fQ", "fStatus", "fDept", "fFrom", "fTo"].forEach((id) =>
    $(id).addEventListener(id === "fQ" ? "input" : "change", SC.debounce(() => { page = 1; load(); }, 300)));
  $("prevBtn").addEventListener("click", () => { if (page > 1) { page--; load(); } });
  $("nextBtn").addEventListener("click", () => { if (page < pages) { page++; load(); } });
  SC.on("ws:any", SC.debounce(load, 600));

  SC.api("/api/lookups").then((r) => {
    $("fDept").innerHTML = '<option value="">All</option>' +
      (r.data.departments || []).map((d) => `<option value="${d.id}">${SC.esc(d.name)}</option>`).join("");
  }).catch(() => {});
  load();
})();
