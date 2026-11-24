/*
 * sw.js - Service Worker (Module 8: offline resources).
 *
 * A service worker is a script the browser runs in the background BETWEEN the web page and
 * the network. Every request of the site passes through it, so it can answer from a cache
 * when the network is gone. Here it:
 *   1. pre-caches the app's CSS / JS files and the /offline page when it is installed,
 *   2. serves static files from the cache first (fast, works offline),
 *   3. for HTML pages: network first, then the last saved copy, then /offline,
 *   4. NEVER caches /api/ or /socket.io/ - live data must always come from the server.
 *
 * Privacy: HTML pages of a logged-in user are cached so the scanner opens offline. When the
 * user logs out the page cache is wiped (see app-shell.js -> "clear-pages" message).
 */
const VERSION = "v3";
const STATIC_CACHE = "sc-static-" + VERSION;
const PAGE_CACHE = "sc-pages-" + VERSION;

const PRECACHE = [
  "/offline",
  "/static/css/style.css",
  "/static/js/common.js", "/static/js/app-shell.js", "/static/js/offline.js", "/static/js/scanner.js",
  "/static/js/charts.js", "/static/js/dashboard.js", "/static/js/queue_panel.js",
  "/static/js/login.js", "/static/js/register.js", "/static/js/pass.js",
  "/static/img/icon.svg", "/static/manifest.webmanifest",
  // local copies (exist after `python scripts/download_vendor.py`) ...
  "/static/vendor/bootstrap.min.css", "/static/vendor/bootstrap.bundle.min.js", "/static/vendor/chart.umd.min.js",
  "/static/vendor/socket.io.min.js", "/static/vendor/html5-qrcode.min.js",
  // ... and the CDN copies used otherwise
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
  "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js",
  "https://cdn.jsdelivr.net/npm/socket.io-client@4.7.5/dist/socket.io.min.js",
  "https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);
    // One by one, so a single missing file (e.g. no local vendor copy) cannot break the install.
    await Promise.all(PRECACHE.map(async (url) => {
      try {
        const cross = new URL(url, self.location.origin).origin !== self.location.origin;
        const resp = await fetch(url, cross ? { mode: "no-cors" } : { credentials: "same-origin" });
        if (resp && (resp.ok || resp.type === "opaque")) await cache.put(url, resp);
      } catch (e) { /* ignore */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== STATIC_CACHE && key !== PAGE_CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data === "clear-pages") event.waitUntil(caches.delete(PAGE_CACHE));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                       // POSTs always go to the network
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  if (sameOrigin && (url.pathname.startsWith("/api/") || url.pathname.startsWith("/socket.io/") ||
      url.pathname === "/sw.js" || url.pathname === "/health")) return;   // live data: never cached

  // HTML pages: network first -> cached copy -> /offline
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const resp = await fetch(req);
        // Cache only real pages (not redirects to /login, not errors).
        if (resp.ok && !resp.redirected) (await caches.open(PAGE_CACHE)).put(req, resp.clone());
        return resp;
      } catch (e) {
        return (await caches.match(req)) || (await caches.match("/offline")) ||
          new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } });
      }
    })());
    return;
  }

  // Static files and CDN libraries: cache first, refresh in the background.
  const isLibrary = url.hostname === "cdn.jsdelivr.net" || url.hostname === "unpkg.com";
  if ((sameOrigin && url.pathname.startsWith("/static/")) || isLibrary) {
    event.respondWith((async () => {
      const cached = await caches.match(req, { ignoreSearch: sameOrigin });
      const network = fetch(req).then(async (resp) => {
        if (resp && (resp.ok || resp.type === "opaque")) (await caches.open(STATIC_CACHE)).put(req, resp.clone());
        return resp;
      }).catch(() => null);
      return cached || (await network) || new Response("", { status: 504 });
    })());
  }
});
