{% load static %}
const CACHE_VERSION = "ggenre-pwa-v20260227";
const APP_SHELL_CACHE = `${CACHE_VERSION}-shell`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;
const IMAGE_CACHE = `${CACHE_VERSION}-images`;
const OFFLINE_URL = "{% url 'offline' %}";

const PRECACHE_URLS = [
  "/",
  "/manifest.webmanifest",
  "{% url 'content_list' %}",
  "{% url 'artist_list' %}",
  "{% url 'live_stream_index' %}",
  OFFLINE_URL,
  "{% static 'css/styles.css' %}",
  "{% static 'css/app-shell.css' %}",
  "{% static 'js/custom.js' %}",
  "{% static 'js/pages/base-shell.js' %}",
  "{% static 'img/favicon.png' %}",
  "{% static 'img/logo.png' %}",
  "{% static 'img/pwa/icon-192.png' %}",
  "{% static 'img/pwa/icon-512.png' %}"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(APP_SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
      .catch(() => Promise.resolve())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => !key.startsWith(CACHE_VERSION))
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

function canCacheResponse(response) {
  return response && (response.status === 200 || response.type === "opaque");
}

function networkFirst(request) {
  return fetch(request)
    .then((response) => {
      if (canCacheResponse(response)) {
        const cloned = response.clone();
        caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, cloned));
      }
      return response;
    })
    .catch(() =>
      caches.match(request).then((cached) => {
        if (cached) {
          return cached;
        }
        if (request.mode === "navigate") {
          return caches.match(OFFLINE_URL);
        }
        return Response.error();
      })
    );
}

function staleWhileRevalidate(request, cacheName) {
  return caches.match(request).then((cached) => {
    const fetchPromise = fetch(request)
      .then((response) => {
        if (canCacheResponse(response)) {
          const cloned = response.clone();
          caches.open(cacheName).then((cache) => cache.put(request, cloned));
        }
        return response;
      })
      .catch(() => cached);

    return cached || fetchPromise;
  });
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(staleWhileRevalidate(request, APP_SHELL_CACHE));
    return;
  }

  if (/\.(png|jpg|jpeg|webp|gif|svg|ico|mp4|webm|mp3|wav)$/i.test(url.pathname)) {
    event.respondWith(staleWhileRevalidate(request, IMAGE_CACHE));
    return;
  }

  event.respondWith(networkFirst(request));
});
