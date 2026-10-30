// Caches the app shell, fonts and listing photos on the phone so launches and
// swipes don't wait on the server. API calls always go to the network.
const CACHE = "kindling-v1.13.2";
const SHELL = ["/", "/static/app.css", "/static/app.js", "/static/web.js", "/static/vendor/d3.min.js", "/static/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Serve the cached copy now, refresh it in the background for next time.
async function staleWhileRevalidate(req) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(req);
  const fresh = fetch(req).then((res) => {
    if (res.ok || res.type === "opaque") cache.put(req, res.clone());
    return res;
  });
  if (hit) { fresh.catch(() => {}); return hit; }
  return fresh;
}

// Listing photos never change once saved, so the first copy is the only copy.
async function cacheFirst(req) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === self.location.origin) {
    if (url.pathname.startsWith("/api/")) return;
    if (url.pathname.startsWith("/img/")) return e.respondWith(cacheFirst(req));
    if (url.pathname === "/" || url.pathname.startsWith("/static/")) return e.respondWith(staleWhileRevalidate(req));
    return;
  }
  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    e.respondWith(staleWhileRevalidate(req));
  }
});
