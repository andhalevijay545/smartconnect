/* admin_users.js - manage security staff, hosts and admins (/api/admin/users). */
(function () {
  "use strict";
  const SC = window.SC;
  const $ = SC.$;
  const modal = new bootstrap.Modal($("userModal"));
  let role = "security", users = [], gates = [], depts = [], editing = null;
  const FIELDS = { username: "uUsername", full_name: "uName", email: "uEmail", password: "uPassword", gate_id: "uGate", department_id: "uDept" };

  const currentRole = () => document.querySelector('input[name="role"]:checked').value;

  async function loadRefs() {
    const [g, d] = await Promise.all([SC.api("/api/gates"), SC.api("/api/departments")]);
    gates = g.data.items || []; depts = d.data.items || [];
    $("uGate").innerHTML = '<option value="">(none)</option>' + gates.map((x) => `<option value="${x.id}">${SC.esc(x.name)}</option>`).join("");
    $("uDept").innerHTML = depts.map((x) => `<option value="${x.id}">${SC.esc(x.name)}</option>`).join("");
  }

  async function load() {
    role = currentRole();
    $("extraTh").textContent = role === "security" ? "Gate" : role === "host" ? "Department" : "—";
    const r = await SC.api("/api/admin/users?role=" + role);
    users = r.data.items || [];
    $("rows").innerHTML = users.length ? users.map((u) => `<tr>
      <td><strong>${SC.esc(u.full_name)}</strong></td><td class="mono">${SC.esc(u.username)}</td><td>${SC.esc(u.email)}</td>
      <td>${SC.esc(role === "security" ? (u.gate_name || "Unassigned") : role === "host" ? (u.department_name || "") : "")}</td>
      <td>${u.is_active ? '<span class="badge text-bg-success">Active</span>' : '<span class="badge text-bg-secondary">Disabled</span>'}</td>
      <td class="small">${SC.fmt(u.last_login_at)}</td>
      <td class="text-end"><button class="btn btn-outline-primary btn-sm" data-edit="${u.id}">Edit</button></td></tr>`).join("")
      : '<tr><td colspan="7" class="text-center text-muted py-4">No accounts.</td></tr>';
  }

  function showErrors(details) {
    Object.entries(FIELDS).forEach(([k, id]) => {
      const el = $(id), msg = details && details[k];
      el.classList.toggle("is-invalid", !!msg);
      const fb = el.parentElement.querySelector(".invalid-feedback");
      if (fb) fb.textContent = msg || "";
    });
  }

  function openForm(user) {
    editing = user || null;
    showErrors(null); $("uError").classList.add("d-none");
    $("uTitle").textContent = user ? "Edit " + user.username : "Add " + (role === "security" ? "security staff" : role === "host" ? "host employee" : "admin");
    $("uUsername").value = user ? user.username : ""; $("uUsername").disabled = !!user;
    $("uName").value = user ? user.full_name : ""; $("uEmail").value = user ? user.email : "";
    $("uPassword").value = ""; $("pwHint").textContent = user ? "(leave empty to keep the current password)" : "(min 8, upper + lower + digit)";
    $("uGate").value = user && user.gate_id ? String(user.gate_id) : "";
    if (depts.length) $("uDept").value = user && user.department_id ? String(user.department_id) : String(depts[0].id);
    $("uPhone").value = user && user.phone ? user.phone : "";
    $("gateWrap").classList.toggle("d-none", role !== "security");
    $("deptWrap").classList.toggle("d-none", role !== "host");
    $("phoneWrap").classList.toggle("d-none", role !== "host" || !!user);
    $("activeWrap").classList.toggle("d-none", !user);
    $("uActive").checked = user ? user.is_active : true;
    modal.show();
  }

  $("userForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { full_name: $("uName").value, email: $("uEmail").value };
    if ($("uPassword").value) body.password = $("uPassword").value;
    if (role === "security") body.gate_id = $("uGate").value ? Number($("uGate").value) : null;
    if (role === "host") body.department_id = Number($("uDept").value);
    let r;
    if (editing) {
      body.is_active = $("uActive").checked;
      r = await SC.api(`/api/admin/users/${role}/${editing.id}`, { method: "PATCH", body });
    } else {
      Object.assign(body, { role, username: $("uUsername").value, password: $("uPassword").value });
      if (role === "host") body.phone = $("uPhone").value;
      r = await SC.api("/api/admin/users", { method: "POST", body });
    }
    if (r.ok) { modal.hide(); SC.toast("Saved.", "success"); load(); return; }
    showErrors(r.error && r.error.details);
    $("uError").textContent = SC.errText(r); $("uError").classList.remove("d-none");
  });

  $("addBtn").addEventListener("click", () => openForm(null));
  $("rows").addEventListener("click", (e) => {
    const b = e.target.closest("[data-edit]");
    if (b) openForm(users.find((u) => String(u.id) === b.dataset.edit));
  });
  document.querySelectorAll('input[name="role"]').forEach((r) => r.addEventListener("change", load));
  loadRefs().then(load);
})();
