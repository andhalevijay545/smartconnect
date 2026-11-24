/* admin_gates.js - manage gates and departments (Module 11). */
(function () {
  "use strict";
  const SC = window.SC;
  const $ = SC.$;
  const modal = new bootstrap.Modal($("nameModal"));
  let kind = "gate", editing = null, gates = [], depts = [];

  async function load() {
    const [g, s, d] = await Promise.all([SC.api("/api/gates"), SC.api("/api/gates/stats"), SC.api("/api/departments")]);
    const stats = {};
    (s.data.items || []).forEach((x) => { stats[x.gate_id] = x; });
    gates = g.data.items || []; depts = d.data.items || [];
    $("gateRows").innerHTML = gates.map((x) => { const st = stats[x.id] || {}; return `<tr>
      <td><strong>${SC.esc(x.name)}</strong></td><td>${SC.esc(x.location || "")}</td>
      <td class="text-end">${st.inside_now || 0}</td><td class="text-end">${st.check_ins_today || 0}</td><td class="text-end">${st.check_outs_today || 0}</td>
      <td>${x.is_active ? '<span class="badge text-bg-success">Active</span>' : '<span class="badge text-bg-secondary">Disabled</span>'}</td>
      <td class="text-end text-nowrap"><button class="btn btn-outline-primary btn-sm" data-gedit="${x.id}">Edit</button>
      <button class="btn btn-outline-secondary btn-sm" data-gtoggle="${x.id}">${x.is_active ? "Disable" : "Enable"}</button></td></tr>`; }).join("")
      || '<tr><td colspan="7" class="text-center text-muted py-3">No gates.</td></tr>';
    $("deptRows").innerHTML = depts.map((x) => `<tr><td><strong>${SC.esc(x.name)}</strong></td>
      <td>${x.is_active ? '<span class="badge text-bg-success">Active</span>' : '<span class="badge text-bg-secondary">Disabled</span>'}</td>
      <td class="text-end text-nowrap"><button class="btn btn-outline-primary btn-sm" data-dedit="${x.id}">Rename</button>
      <button class="btn btn-outline-secondary btn-sm" data-dtoggle="${x.id}">${x.is_active ? "Disable" : "Enable"}</button></td></tr>`).join("")
      || '<tr><td colspan="3" class="text-center text-muted py-3">No departments.</td></tr>';
  }

  function open(k, item) {
    kind = k; editing = item || null;
    $("nTitle").textContent = (item ? "Edit " : "Add ") + (k === "gate" ? "gate" : "department");
    $("nName").value = item ? item.name : "";
    $("nLoc").value = item && item.location ? item.location : "";
    $("locWrap").classList.toggle("d-none", k !== "gate");
    $("nError").classList.add("d-none");
    modal.show();
  }

  $("nameForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const base = kind === "gate" ? "/api/gates" : "/api/departments";
    const body = { name: $("nName").value };
    if (kind === "gate") body.location = $("nLoc").value;
    const r = editing ? await SC.api(`${base}/${editing.id}`, { method: "PATCH", body })
                      : await SC.api(base, { method: "POST", body });
    if (r.ok) { modal.hide(); SC.toast("Saved.", "success"); load(); }
    else { $("nError").textContent = SC.errText(r); $("nError").classList.remove("d-none"); }
  });

  async function toggle(base, item) {
    const r = await SC.api(`${base}/${item.id}`, { method: "PATCH", body: { is_active: !item.is_active } });
    if (!r.ok) SC.toast(SC.errText(r), "danger");
    load();
  }

  $("addGate").addEventListener("click", () => open("gate"));
  $("addDept").addEventListener("click", () => open("dept"));
  document.body.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    const find = (list, id) => list.find((x) => String(x.id) === id);
    if (t.dataset.gedit) open("gate", find(gates, t.dataset.gedit));
    if (t.dataset.dedit) open("dept", find(depts, t.dataset.dedit));
    if (t.dataset.gtoggle) toggle("/api/gates", find(gates, t.dataset.gtoggle));
    if (t.dataset.dtoggle) toggle("/api/departments", find(depts, t.dataset.dtoggle));
  });
  load();
})();
