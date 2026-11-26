"""Cliente HTTP cortés: cabeceras de navegador, pausas por host, reintentos y robots.txt.

- Pausa aleatoria entre pedidos al mismo host (evita bloqueos anti-bot y no sobrecarga
  portales públicos).
- Reintentos con espera creciente ante 429/5xx/timeouts.
- Respeta robots.txt (reglas para "*") y lee las señales `Content-Signal`
  (p. ej. `ai-train=no`) para que el pipeline sepa qué fuentes pidieron no usar su
  contenido para entrenar IA.
"""

from __future__ import annotations

import logging
import random
import time
from collections import Counter
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

AGENTE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CABECERAS = {
    "User-Agent": AGENTE,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.6",
}
MAX_BYTES = 6 * 1024 * 1024


class ErrorHTTP(RuntimeError):
    pass


class ClienteHTTP:
    def __init__(
        self,
        pausa: tuple[float, float] = (1.2, 2.8),
        timeout: float = 25.0,
        reintentos: int = 2,
        respetar_robots: bool = True,
    ) -> None:
        self._cliente = httpx.Client(headers=CABECERAS, timeout=timeout, follow_redirects=True)
        self._pausa = pausa
        self._reintentos = reintentos
        self._respetar_robots = respetar_robots
        self._ultimo: dict[str, float] = {}
        self._robots: dict[str, tuple[RobotFileParser | None, dict[str, str]]] = {}
        self.estadisticas: Counter[str] = Counter()

    # ------------------------------------------------------------------ robots
    def _cargar_robots(self, host: str, esquema: str) -> tuple[RobotFileParser | None, dict[str, str]]:
        if host in self._robots:
            return self._robots[host]
        parser: RobotFileParser | None = None
        senales: dict[str, str] = {}
        try:
            resp = self._cliente.get(f"{esquema}://{host}/robots.txt", timeout=12)
            if resp.status_code == 200 and "html" not in resp.headers.get("content-type", ""):
                lineas = resp.text.splitlines()
                parser = RobotFileParser()
                parser.parse(lineas)
                for linea in lineas:
                    if linea.lower().startswith("content-signal:"):
                        for par in linea.split(":", 1)[1].split(","):
                            if "=" in par:
                                clave, valor = (x.strip().lower() for x in par.split("=", 1))
                                # La señal más restrictiva gana.
                                if senales.get(clave) != "no":
                                    senales[clave] = valor
        except httpx.HTTPError as exc:
            log.debug("robots.txt no disponible en %s: %s", host, exc)
        self._robots[host] = (parser, senales)
        return parser, senales

    def permitido(self, url: str) -> bool:
        if not self._respetar_robots:
            return True
        partes = urlsplit(url)
        parser, _ = self._cargar_robots(partes.netloc, partes.scheme or "https")
        return True if parser is None else parser.can_fetch("*", url)

    def senales_contenido(self, url: str) -> dict[str, str]:
        partes = urlsplit(url)
        return self._cargar_robots(partes.netloc, partes.scheme or "https")[1]

    # ------------------------------------------------------------------ pedidos
    def _esperar_turno(self, host: str) -> None:
        anterior = self._ultimo.get(host)
        if anterior is not None:
            espera = random.uniform(*self._pausa) - (time.monotonic() - anterior)
            if espera > 0:
                time.sleep(espera)
        self._ultimo[host] = time.monotonic()

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self._pedir("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self._pedir("POST", url, **kwargs)

    def _pedir(self, metodo: str, url: str, **kwargs) -> httpx.Response:
        if not self.permitido(url):
            raise ErrorHTTP(f"robots.txt no permite {url}")
        host = urlsplit(url).netloc
        ultimo_error: Exception | None = None
        for intento in range(self._reintentos + 1):
            self._esperar_turno(host)
            try:
                resp = self._cliente.request(metodo, url, **kwargs)
                self.estadisticas[host] += 1
                if resp.status_code in (429, 500, 502, 503, 504) and intento < self._reintentos:
                    time.sleep(3 * (intento + 1) + random.random())
                    continue
                if resp.status_code >= 400:
                    raise ErrorHTTP(f"HTTP {resp.status_code} en {url}")
                if len(resp.content) > MAX_BYTES:
                    raise ErrorHTTP(f"Respuesta demasiado grande en {url}")
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                ultimo_error = exc
                if intento < self._reintentos:
                    time.sleep(3 * (intento + 1))
                    continue
        raise ErrorHTTP(f"No se pudo obtener {url}: {ultimo_error}")

    def cerrar(self) -> None:
        self._cliente.close()

    def __enter__(self) -> "ClienteHTTP":
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()
