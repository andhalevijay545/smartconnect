/* login.js - staff login form (POST /api/auth/login). */
(function () {
  "use strict";
  const SC = window.SC;
  const form = SC.$("loginForm");
  const err = SC.$("loginError");
  const btn = SC.$("loginBtn");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.classList.add("d-none");
    btn.disabled = true;
    try {
      const r = await SC.api("/api/auth/login", {
        method: "POST",
        quiet401: true,
        body: { role: SC.$("role").value, username: SC.$("username").value, password: SC.$("password").value },
      });
      if (r.ok) {
        SC.csrf = r.data.csrf_token || SC.csrf;
        window.location.href = r.data.redirect;
        return;
      }
      err.textContent = SC.errText(r);
    } catch (ex) {
      err.textContent = "Cannot reach the server. Check your Wi-Fi / internet connection.";
    }
    err.classList.remove("d-none");
    btn.disabled = false;
  });
})();
