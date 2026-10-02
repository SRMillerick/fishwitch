/* baromoon service worker — field mode.
   Network-first for pages (always prefer fresh forecasts/sky math), falling
   back to the cached copy when service is gone; cache-first for the
   URL-versioned static assets. Affiliate /out/ redirects are never cached. */
const V = "baromoon-v3";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== V).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;        // fonts/tiles stay live
  if (url.pathname.startsWith("/out/")) return;      // never cache redirects

  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((resp) => {
          if (resp.ok) {
            const copy = resp.clone();
            caches.open(V).then((c) => c.put(req, copy));
          }
          return resp;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
    );
    return;
  }

  e.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req).then((resp) => {
        if (resp.ok && url.pathname.startsWith("/static/")) {
          const copy = resp.clone();
          caches.open(V).then((c) => c.put(req, copy));
        }
        return resp;
      });
    })
  );
});
