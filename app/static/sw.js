/* WRU TGS Tracker service worker.
 *
 * Exists so the app can be installed as a PWA. Live data still comes from the
 * server (SSE + revision poll) — this worker must not cache API or HTML.
 */
const VERSION = "__WRU_ASSET_V__";

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith("wru-")).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  let url;
  try {
    url = new URL(req.url);
  } catch {
    return;
  }
  if (url.origin !== self.location.origin) return;
  // Let the browser handle APIs and SSE so live updates are never buffered.
  if (url.pathname.startsWith("/api/")) return;

  event.respondWith(
    fetch(req, { cache: req.mode === "navigate" ? "no-store" : "no-cache" }).catch(() => {
      if (req.mode === "navigate") {
        return new Response("WRU TGS Tracker is offline. Reconnect and try again.", {
          status: 503,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        });
      }
      return Response.error();
    })
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "skip-waiting") self.skipWaiting();
  if (event.data && event.data.type === "version") {
    event.source?.postMessage({ type: "sw-version", version: VERSION });
  }
});
