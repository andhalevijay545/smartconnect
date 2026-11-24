/*
 * offline.js - the offline queue (Module 8). Loaded on the security pages.
 *
 * Problem: guards scan QR codes where Wi-Fi/mobile data can drop. We must not lose scans AND
 * must never treat an unverified scan as an authorised entry.
 *
 * Solution
 *   1. When the server cannot be reached, the scan is saved in IndexedDB (a database inside
 *      the browser that survives page reloads and restarts) with status PENDING.
 *   2. Every operation gets a random operation_id created on the phone.
 *   3. When the connection is back, all PENDING operations are sent to POST /api/sync.
 *   4. The server verifies each QR token. Only then does an operation become SUCCESS
 *      (verified) or FAILED (rejected, with the reason). Until then it is only "pending".
 *   5. Because the server remembers every operation_id (idempotency), sending the same
 *      operation twice - for example after a lost response - never creates a duplicate visit.
 *
 * States:  PENDING -> SYNCING -> SUCCESS | FAILED      (SYNCING falls back to PENDING on error)
 */
(function () {
  "use strict";
  const SC = window.SC;
  const DB_NAME = "smartconnect", STORE = "ops", BATCH = 50;
  let dbPromise = null;
  let syncing = false;

  function openDb() {
    if (!window.indexedDB) return Promise.reject(new Error("IndexedDB not supported"));
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const s = req.result.createObjectStore(STORE, { keyPath: "operation_id" });
        s.createIndex("status", "status");
        s.createIndex("created", "created");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }

  function run(mode, fn) {
    return openDb().then((db) => new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const out = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(out && "result" in out ? out.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    }));
  }

  const Q = {};
  Q.put = (rec) => run("readwrite", (s) => s.put(rec));
  Q.remove = (id) => run("readwrite", (s) => s.delete(id));
  Q.all = () => run("readonly", (s) => s.getAll()).then((a) => (a || []).sort((x, y) => x.created - y.created));

  // opId is optional: when an online attempt failed halfway we RE-USE its id so the server can
  // recognise the retry (idempotency) instead of treating it as a brand-new scan.
  Q.add = async function (type, token, opId) {
    const rec = {
      operation_id: opId || "op-" + SC.uuid(),
      type,                       // "check-in" | "check-out"
      token,                      // secret QR token - removed as soon as the server has processed it
      scanned_at: new Date().toISOString(),
      status: "PENDING",
      created: Date.now(),
      attempts: 0, code: null, message: null,
    };
    await Q.put(rec);
    changed();
    return rec;
  };

  Q.counts = async function () {
    const c = { PENDING: 0, SYNCING: 0, SUCCESS: 0, FAILED: 0 };
    (await Q.all()).forEach((r) => { c[r.status] = (c[r.status] || 0) + 1; });
    return c;
  };

  Q.clearFinished = async function () {
    for (const r of await Q.all()) if (r.status === "SUCCESS" || r.status === "FAILED") await Q.remove(r.operation_id);
    changed();
  };

  function changed() { SC.emit("offline-changed", {}); }

  // An interrupted page may leave records in SYNCING - they were never confirmed, so retry them.
  async function resetStuck() {
    for (const r of await Q.all()) if (r.status === "SYNCING") { r.status = "PENDING"; await Q.put(r); }
  }

  Q.sync = async function () {
    if (syncing || !SC.canReachServer()) return null;
    syncing = true;
    const summary = { total: 0, success: 0, failed: 0, kept: 0, error: null };
    try {
      const pending = (await Q.all()).filter((r) => r.status === "PENDING");
      for (let i = 0; i < pending.length; i += BATCH) {
        const chunk = pending.slice(i, i + BATCH);
        for (const r of chunk) { r.status = "SYNCING"; r.attempts += 1; await Q.put(r); }
        changed();
        let resp;
        try {
          resp = await SC.api("/api/sync", {
            method: "POST",
            body: {
              device_id: SC.deviceId,
              operations: chunk.map((r) => ({ operation_id: r.operation_id, type: r.type, token: r.token, scanned_at: r.scanned_at })),
            },
          });
        } catch (e) { resp = null; }

        if (!resp || !resp.ok) {                     // network lost, 401, 429, 5xx ... -> try again later
          for (const r of chunk) { r.status = "PENDING"; await Q.put(r); }
          summary.kept += chunk.length;
          summary.error = resp ? SC.errText(resp) : "Server unreachable";
          break;
        }
        const byId = {};
        resp.data.results.forEach((x) => { byId[x.operation_id] = x; });
        for (const r of chunk) {
          const x = byId[r.operation_id];
          if (!x) { r.status = "PENDING"; await Q.put(r); summary.kept += 1; continue; }
          r.status = x.status === "success" ? "SUCCESS" : "FAILED";
          r.code = x.result && x.result.code;
          r.message = x.result && x.result.message;
          r.visitor = x.result && x.result.visitor ? x.result.visitor.full_name : null;
          r.token = "";                                // secret no longer needed on this device
          r.synced_at = new Date().toISOString();
          await Q.put(r);
          summary.total += 1;
          if (r.status === "SUCCESS") summary.success += 1; else summary.failed += 1;
        }
      }
    } finally {
      syncing = false;
      changed();
    }
    if (summary.total) SC.emit("sync-done", summary);
    return summary;
  };

  Q.isSyncing = () => syncing;

  // ------------------------------------------------------------ automatic retry
  SC.on("online", () => Q.sync());
  setInterval(async () => {
    if (SC.canReachServer() && !syncing && (await Q.counts()).PENDING > 0) Q.sync();
  }, 15000);
  resetStuck().then(() => { changed(); setTimeout(() => Q.sync(), 1500); }).catch(() => {});

  window.SCOffline = Q;
})();
