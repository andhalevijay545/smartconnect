/* queue_panel.js - shows the offline queue counts on the security dashboard. */
(function () {
  "use strict";
  const SC = window.SC;
  async function draw() {
    if (!window.SCOffline) return;
    try {
      const c = await SCOffline.counts();
      SC.$("qPending").textContent = c.PENDING;
      SC.$("qSyncing").textContent = c.SYNCING;
      SC.$("qSuccess").textContent = c.SUCCESS;
      SC.$("qFailed").textContent = c.FAILED;
    } catch (e) { /* IndexedDB unavailable */ }
  }
  SC.on("offline-changed", draw);
  SC.$("syncNow").addEventListener("click", async () => {
    if (!SC.canReachServer()) return SC.toast("Still offline - nothing was sent.", "warning");
    const s = await SCOffline.sync();
    SC.toast(s && s.total ? `Synced ${s.total} scan(s): ${s.success} verified, ${s.failed} rejected.` : "Nothing to sync.", "info");
  });
  SC.on("sync-done", (s) => SC.notify(`Offline scans synced: ${s.success} verified, ${s.failed} rejected.`));
  draw();
})();
