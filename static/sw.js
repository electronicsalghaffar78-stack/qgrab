/* QGrab service worker — caches the app shell so the installed app
   opens instantly and the homepage works offline. API calls and media
   downloads are NEVER cached; they always go to the network. */
const CACHE = "qgrab-shell-v5";
const SHELL = [
  "/",
  "/static/manifest.webmanifest",
  "/static/icons/qgrab-logo.webp",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never intercept API or download traffic.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/download")) {
    return;
  }

  // Page navigations: network first, fall back to the cached shell offline.
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          // Refresh the cached shell ONLY from the homepage itself.
          // (Audit fix: this used to store EVERY navigation's
          // response under "/", so after visiting e.g. /terms the
          // offline fallback served the Terms page as the homepage.)
          if (url.pathname === "/" && resp && resp.status === 200) {
            const copy = resp.clone();
            caches.open(CACHE).then((cache) => cache.put("/", copy));
          }
          return resp;
        })
        .catch(() => caches.match("/"))
    );
    return;
  }

  // Static assets: cache first, then network (and refresh the cache).
  event.respondWith(
    caches.match(event.request).then((hit) => {
      const network = fetch(event.request).then((resp) => {
        if (resp && resp.status === 200) {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return resp;
      }).catch(() => hit);
      return hit || network;
    })
  );
});
