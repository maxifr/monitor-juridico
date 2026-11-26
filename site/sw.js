// Service worker: el portal se puede instalar en el teléfono y abrir sin conexión.
// Datos: primero la red (siempre lo último) y, si no hay conexión, la última copia.
// Interfaz: copia local inmediata y actualización en segundo plano.
const VERSION = "mj-v1";
const INTERFAZ = [
  "./",
  "index.html",
  "assets/estilos.css",
  "assets/app.js",
  "assets/tema.js",
  "assets/icono.svg",
  "assets/fonts/newsreader.woff2",
  "assets/fonts/newsreader-italic.woff2",
  "assets/fonts/encode-sans.woff2",
  "manifest.webmanifest",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(VERSION).then((c) => c.addAll(INTERFAZ)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (evento) => {
  const pedido = evento.request;
  if (pedido.method !== "GET" || new URL(pedido.url).origin !== self.location.origin) return;
  const esDato = /\/data\/|feed\.xml$/.test(new URL(pedido.url).pathname);

  if (esDato) {
    evento.respondWith(
      fetch(pedido)
        .then((resp) => {
          if (resp.ok) { const copia = resp.clone(); caches.open(VERSION).then((c) => c.put(pedido, copia)); }
          return resp;
        })
        .catch(() => caches.match(pedido).then((r) => r || Response.error()))
    );
    return;
  }

  evento.respondWith(
    caches.match(pedido).then((enCache) => {
      const red = fetch(pedido).then((resp) => {
        if (resp.ok) { const copia = resp.clone(); caches.open(VERSION).then((c) => c.put(pedido, copia)); }
        return resp;
      }).catch(() => enCache);
      return enCache || red;
    })
  );
});
