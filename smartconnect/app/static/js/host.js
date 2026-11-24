/* host.js - approval requests for host employees (GET /api/approvals, POST /api/approvals/<id>/decision). */
(function () {
  "use strict";
  const SC = window.SC;
  const list = SC.$("approvalList");
  const filter = SC.$("approvalFilter");

  function card(a) {
    const v = a.visitor;
    const actions = a.status === "PENDING" ? `
      <input class="form-control form-control-sm mb-2" placeholder="Remarks (optional)" maxlength="255" data-remarks>
      <div class="d-flex gap-2">
        <button class="btn btn-success btn-sm flex-fill" data-decision="approve">Approve</button>
        <button class="btn btn-outline-danger btn-sm flex-fill" data-decision="reject">Reject</button>
      </div>` : `<div class="small text-muted">${a.remarks ? "Remarks: " + SC.esc(a.remarks) : ""}<br>Decided ${SC.fmt(a.decided_at)}</div>`;
    return `<div class="col-md-6 col-xl-4"><div class="card h-100" data-id="${a.id}"><div class="card-body">
      <div class="d-flex justify-content-between"><strong>${SC.esc(v.full_name)}</strong>${SC.badge(a.status)}</div>
      <div class="small text-muted mb-2">${SC.esc(v.mobile)} · ${SC.esc(v.email || "")}</div>
      <div class="small"><b>Purpose:</b> ${SC.esc(v.purpose)}</div>
      <div class="small"><b>Expected:</b> ${SC.fmt(v.expected_at)}</div>
      <div class="small mb-3"><b>Department:</b> ${SC.esc(v.department || "")}</div>${actions}</div></div></div>`;
  }

  async function load() {
    try {
      const r = await SC.api("/api/approvals?status=" + encodeURIComponent(filter.value));
      if (!r.ok) return;
      list.innerHTML = r.data.items.length ? r.data.items.map(card).join("")
        : '<div class="col-12 text-muted text-center py-4">Nothing here.</div>';
      if (filter.value === "PENDING") SC.$("pendingBadge").textContent = r.data.items.length;
    } catch (e) { SC.toast("Offline - cannot refresh approvals.", "warning"); }
  }

  list.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-decision]");
    if (!btn) return;
    const cardEl = btn.closest("[data-id]");
    btn.disabled = true;
    try {
      const r = await SC.api(`/api/approvals/${cardEl.dataset.id}/decision`, {
        method: "POST",
        body: { decision: btn.dataset.decision, remarks: cardEl.querySelector("[data-remarks]").value },
      });
      if (!r.ok) SC.toast(SC.errText(r), "danger");
      else SC.toast(btn.dataset.decision === "approve" ? "Visitor approved." : "Visitor rejected.", "success");
    } catch (ex) { SC.toast("You are offline. Try again when connected.", "warning"); }
    load();
  });

  filter.addEventListener("change", load);
  SC.on("ws:visitor_registered", load);
  SC.on("ws:approval_updated", load);
  SC.on("online", load);
  load();
})();
