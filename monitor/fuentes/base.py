"""Clase base de las fuentes y utilidades comunes de extracción.

Cada fuente es un módulo aislado: si un portal cambia su diseño y el extractor se
rompe, el resto del pipeline sigue funcionando y el radar de fuentes lo muestra.

Flujo de una fuente:
    listar()          -> candidatos con título, bajada, fecha y metadatos (barato)
    prefiltro()       -> descarta por reglas lo obviamente irrelevante (gratis)
    cargar_detalle()  -> trae el cuerpo completo sólo de lo que pasó el triage
"""

from __future__ import annotations

import json
import logging
import re
from typing import ClassVar
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import ClienteHTTP
from ..modelos import Candidato
from ..pdf import buscar_pdf, texto_de_pdf
from ..seguridad import dominio_permitido, html_a_texto_seguro, texto_plano_seguro
from ..textos import limpiar_espacios, parsear_fecha

log = logging.getLogger(__name__)


class Fuente:
    clave: ClassVar[str] = ""
    nombre: ClassVar[str] = ""
    portada: ClassVar[str] = ""
    dominios: ClassVar[frozenset[str]] = frozenset()
    prioridad: ClassVar[int] = 50
    oficial: ClassVar[bool] = False
    # Fuentes oficiales de fallos y normas: el portal puede citar fragmentos textuales.
    # En el resto (medios privados) sólo se publica síntesis propia + enlace.
    dominio_publico: ClassVar[bool] = False
    selectores_cuerpo: ClassVar[tuple[str, ...]] = ("article", "main")
    min_citas: ClassVar[int] = 2
    # True si la portada no da contexto suficiente y conviene leer la nota antes del triage.
    detalle_antes_del_triage: ClassVar[bool] = False
    # Antigüedad máxima propia (días). SAIJ carga fallos y leyes semanas o meses después.
    antiguedad_maxima: ClassVar[int | None] = None
    # Las fuentes desactivadas por defecto sólo corren si se las nombra en FUENTES_ACTIVAS.
    activa_por_defecto: ClassVar[bool] = True
    # Sentencia adjunta en PDF: expresión regular de su URL. Si coincide se guarda como
    # "Ver sentencia" (oficial.url_fallo); con leer_pdf=True además se le pasa el texto a la IA.
    patron_pdf: ClassVar[str] = ""
    leer_pdf: ClassVar[bool] = False

    def __init__(self, http: ClienteHTTP, max_candidatos: int = 20) -> None:
        self.http = http
        self.max_candidatos = max_candidatos

    # ------------------------------------------------------------------ interfaz
    def listar(self) -> list[Candidato]:  # pragma: no cover - lo implementa cada fuente
        raise NotImplementedError

    def prefiltro(self, cand: Candidato) -> str | None:
        """Devuelve un motivo si el candidato se descarta sin gastar IA."""
        return None

    def cargar_detalle(self, cand: Candidato) -> None:
        if cand.detalle_cargado:
            return
        resp = self.http.get(cand.url)
        art = extraer_articulo(resp.text, cand.url, self.selectores_cuerpo)
        cand.texto = art["texto"] or cand.resumen
        cand.resumen = cand.resumen or art["descripcion"]
        cand.fecha = cand.fecha or art["fecha"]
        cand.seccion = cand.seccion or art["seccion"]
        if art["nodos_ocultos"]:
            cand.alertas_seguridad.append(f"oculto:{art['texto_oculto']}")
        self._registrar_pdf(cand, resp.text)
        cand.detalle_cargado = True

    def _registrar_pdf(self, cand: Candidato, html: str) -> None:
        if not self.patron_pdf or cand.oficial.get("url_fallo"):
            return
        url_pdf = buscar_pdf(html, cand.url, self.patron_pdf)
        if url_pdf and dominio_permitido(url_pdf, self.dominios):
            cand.oficial["url_fallo"] = url_pdf

    def cargar_adjunto(self, cand: Candidato) -> None:
        """Agrega al cuerpo el texto de la sentencia en PDF (una sola vez por pieza)."""
        url_pdf = cand.oficial.get("url_fallo", "")
        if not self.leer_pdf or not url_pdf or cand.oficial.get("pdf_leido"):
            return
        cand.oficial["pdf_leido"] = True
        texto = texto_de_pdf(self.http.get(url_pdf).content)
        if len(texto) < 300:  # escaneado o vacío
            return
        nota = cand.texto[:6000]
        cand.texto = f"{nota}\n\nTEXTO DE LA SENTENCIA (PDF adjunto a la nota): {texto}"
        log.info("PDF de la sentencia leído (%d caracteres): %s", len(texto), url_pdf)

    # ------------------------------------------------------------------ ayudas
    def candidato(self, url: str, titulo: str, **kwargs) -> Candidato:
        return Candidato(fuente=self.clave, url=url, titulo=limpiar_espacios(titulo), **kwargs)

    def sopa(self, url: str, parser: str = "lxml") -> BeautifulSoup:
        return BeautifulSoup(self.http.get(url).content, parser)

    def info(self) -> dict:
        return {
            "clave": self.clave,
            "nombre": self.nombre,
            "portada": self.portada,
            "prioridad": self.prioridad,
            "oficial": self.oficial,
        }


# --------------------------------------------------------------------------- extracción


def _meta(sopa: BeautifulSoup, *nombres: str) -> str:
    for nombre in nombres:
        el = sopa.find("meta", attrs={"property": nombre}) or sopa.find("meta", attrs={"name": nombre}) or sopa.find(
            "meta", attrs={"itemprop": nombre}
        )
        if el and el.get("content"):
            return limpiar_espacios(el["content"])
    return ""


def _json_ld(sopa: BeautifulSoup) -> list[dict]:
    bloques = []
    for script in sopa.find_all("script", type="application/ld+json"):
        try:
            datos = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in datos if isinstance(datos, list) else [datos]:
            if isinstance(item, dict):
                bloques.extend(item.get("@graph", [item]) if "@graph" in item else [item])
    return bloques


def extraer_articulo(html: str, url: str, selectores: tuple[str, ...] = ("article", "main")) -> dict:
    """Título, bajada, fecha, sección y cuerpo visible de una página de nota."""
    sopa = BeautifulSoup(html, "lxml")
    ld = _json_ld(sopa)
    articulo_ld = next((b for b in ld if str(b.get("@type", "")).endswith(("Article", "NewsArticle", "BlogPosting"))), {})
    migas = next((b for b in ld if b.get("@type") == "BreadcrumbList"), {})

    titulo = _meta(sopa, "og:title", "twitter:title") or (sopa.h1.get_text(" ", strip=True) if sopa.h1 else "")
    descripcion = _meta(sopa, "og:description", "description", "twitter:description")
    fecha = parsear_fecha(
        _meta(sopa, "article:published_time", "datePublished", "date", "pubdate")
        or articulo_ld.get("datePublished")
        or (sopa.find("time").get("datetime") if sopa.find("time") else None)
        or (sopa.find("time").get_text(" ", strip=True) if sopa.find("time") else None)
    )
    seccion = _meta(sopa, "article:section")
    if not seccion and migas.get("itemListElement"):
        elementos = migas["itemListElement"]
        if len(elementos) >= 3:
            seccion = limpiar_espacios(str(elementos[-2].get("name", "")))

    cuerpo_html = ""
    for selector in selectores:
        nodo = sopa.select_one(selector)
        if nodo and len(nodo.get_text(" ", strip=True)) > 200:
            cuerpo_html = str(nodo)
            break
    if not cuerpo_html:
        cuerpo_html = str(_bloque_mas_largo(sopa) or "")
    saneado = html_a_texto_seguro(cuerpo_html)
    return {
        "url": url,
        "titulo": texto_plano_seguro(titulo),
        "descripcion": texto_plano_seguro(descripcion),
        "fecha": fecha,
        "seccion": seccion,
        "texto": saneado.texto[:12000],
        "nodos_ocultos": saneado.nodos_ocultos,
        "texto_oculto": saneado.texto_oculto,
    }


def _bloque_mas_largo(sopa: BeautifulSoup):
    """Heurística tipo 'readability': el contenedor con más texto en párrafos directos."""
    mejor, puntaje = None, 0
    for nodo in sopa.find_all(["div", "article", "section", "main"]):
        parrafos = nodo.find_all("p", recursive=False)
        total = sum(len(p.get_text(" ", strip=True)) for p in parrafos)
        if total > puntaje:
            mejor, puntaje = nodo, total
    return mejor


def absoluta(base: str, href: str) -> str:
    return urljoin(base, (href or "").strip())


def token_csrf(html: str) -> str:
    """Token anti-CSRF que algunos portales (CSJN, Justicia.ar) exigen para sus listados JSON."""
    m = re.search(r"(?:var|const|let)\s+(?:token|csrfToken)\s*=\s*[\"']([0-9a-fA-F-]{16,})[\"']", html)
    return m.group(1) if m else ""
