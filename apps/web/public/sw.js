const SHELL_CACHE = "enano-coach-shell-v3";
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/assets/app.js",
  "/assets/index.css",
  "/manifest.webmanifest",
  "/icons/mark.svg",
  "/offline.html"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => Promise.all(
      SHELL_ASSETS.map((asset) => cache.add(asset).catch(() => undefined))
    ))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith("enano-coach-shell-") && key !== SHELL_CACHE)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  // Private BFF responses are network-only. A failed request is allowed to
  // reject rather than being replaced by stale health data.
  if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(request));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("/offline.html"))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
