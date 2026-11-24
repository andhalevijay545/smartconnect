/* register.js - visitor registration (GET /api/lookups, POST /api/visitors/register). */
(function () {
  "use strict";
  const SC = window.SC;
  const form = SC.$("regForm");
  const fields = ["full_name", "mobile", "email", "expected_at", "address", "purpose", "department_id", "host_id"];
  let lookups = { departments: [], hosts: [] };

  // datetime-local wants "YYYY-MM-DDTHH:MM" in LOCAL time.
  function localInputValue(d) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  async function loadLookups() {
    try {
      const r = await SC.api("/api/lookups");
      lookups = r.data;
      const dep = SC.$("department_id");
      dep.innerHTML = '<option value="">Select department</option>' +
        lookups.departments.map((d) => `<option value="${d.id}">${SC.esc(d.name)}</option>`).join("");
    } catch (e) {
      SC.$("regError").textContent = "Cannot reach the server. Registration needs a connection.";
      SC.$("regError").classList.remove("d-none");
    }
  }

  SC.$("department_id").addEventListener("change", () => {
    const id = Number(SC.$("department_id").value);
    const hosts = lookups.hosts.filter((h) => h.department_id === id);
    SC.$("host_id").innerHTML = hosts.length
      ? '<option value="">Select host</option>' + hosts.map((h) => `<option value="${h.id}">${SC.esc(h.full_name)}</option>`).join("")
      : '<option value="">No hosts in this department</option>';
  });

  function showErrors(details) {
    fields.forEach((f) => {
      const el = SC.$(f);
      const msg = details && details[f];
      el.classList.toggle("is-invalid", !!msg);
      if (el.nextElementSibling) el.nextElementSibling.textContent = msg || "";
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showErrors(null);
    const err = SC.$("regError");
    err.classList.add("d-none");
    const body = {};
    fields.forEach((f) => { body[f] = SC.$(f).value; });
    body.department_id = Number(body.department_id) || null;
    body.host_id = Number(body.host_id) || null;
    // The server treats a time without a zone as its own local time zone.
    SC.$("regBtn").disabled = true;
    try {
      const r = await SC.api("/api/visitors/register", { method: "POST", body });
      if (r.ok) {
        // Keep the private link on THIS device only (never in the URL).
        localStorage.setItem("sc_visit", JSON.stringify({
          public_id: r.data.visitor.public_id,
          access_key: r.data.access_key,
          qr_image: r.data.qr.image,
          qr_expires_at: r.data.qr.expires_at,
        }));
        window.location.href = "/visitor/pass";
        return;
      }
      if (r.error && r.error.details) showErrors(r.error.details);
      err.textContent = r.status === 422 ? "Please correct the highlighted fields." : SC.errText(r);
    } catch (ex) {
      err.textContent = "Cannot reach the server. Check your connection and try again.";
    }
    err.classList.remove("d-none");
    SC.$("regBtn").disabled = false;
  });

  SC.$("expected_at").value = localInputValue(new Date(Date.now() + 60 * 60 * 1000));
  loadLookups();
})();
