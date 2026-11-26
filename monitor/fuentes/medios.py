"""Medios jurídicos (Diario Judicial, Pensamiento Penal, Palabras del Derecho, elDial) y
fuentes por RSS (incluido el Poder Judicial de Tierra del Fuego).

Regla editorial para los medios privados: nunca se republica su texto; el portal
publica una síntesis propia y enlaza siempre a la nota original. De elDial sólo se lee
la portada pública (el resto es contenido para suscriptores).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

from ..modelos import Candidato
from ..seguridad import texto_plano_seguro
from ..textos import ahora, limpiar_espacios, parsear_fecha
from .base import Fuente, absoluta

_NS_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


class DiarioJudicial(Fuente):
    clave = "diario_judicial"
    nombre = "Diario Judicial"
    portada = "https://www.diariojudicial.com/"
    dominios = frozenset({"diariojudicial.com"})
    prioridad = 60
    selectores_cuerpo = ("div.nota-cuerpo", "article")
    _patron = re.compile(r"^https://www\.diariojudicial\.com/news-\d+-")

    def listar(self) -> list[Candidato]:
        sopa = self.sopa(self.portada)
        vistos: set[str] = set()
        salida: list[Candidato] = []
        for enlace in sopa.select("a[href*='/news-']"):
            url = absoluta(self.portada, enlace["href"]).split("?")[0]
            titulo = enlace.get_text(" ", strip=True)
            if not self._patron.match(url) or len(titulo) < 15 or url in vistos:
                continue
            vistos.add(url)
            salida.append(self.candidato(url, titulo))
        return salida[: self.max_candidatos]


class PalabrasDelDerecho(Fuente):
    clave = "palabras_derecho"
    nombre = "Palabras del Derecho"
    portada = "https://www.palabrasdelderecho.com.ar/"
    dominios = frozenset({"palabrasdelderecho.com.ar"})
    prioridad = 72
    selectores_cuerpo = ("div.col-lg-8.col-md-8.col-sm-12", "article")
    _patron = re.compile(r"/articulo/\d+/")

    def listar(self) -> list[Candidato]:
        sopa = self.sopa(self.portada)
        vistos: set[str] = set()
        salida: list[Candidato] = []
        for enlace in sopa.select("a[href*='/articulo/']"):
            url = absoluta(self.portada, enlace["href"])
            titulo = enlace.get_text(" ", strip=True)
            numero = self._patron.search(url)
            if not numero or len(titulo) < 25 or numero.group(0) in vistos:
                continue
            vistos.add(numero.group(0))
            salida.append(self.candidato(url, titulo))
        return salida[: self.max_candidatos]

    def cargar_detalle(self, cand: Candidato) -> None:
        super().cargar_detalle(cand)
        if cand.fecha is None:  # la nota muestra la fecha como "24-11-2026" junto a la firma
            m = re.search(r"\b(\d{2})-(\d{2})-(20\d{2})\b", cand.texto[:600])
            if m:
                cand.fecha = parsear_fecha(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")


class ElDial(Fuente):
    clave = "eldial"
    nombre = "elDial.com"
    portada = "https://www.eldial.com/nuevo/nuevo_diseno/v2/index.asp"
    dominios = frozenset({"eldial.com"})
    prioridad = 58
    min_citas = 1  # sólo hay bajadas breves de portada
    # Desactivada por defecto: el contenido está detrás de un muro de pago, así que el
    # enlace "Leer en la fuente" no lo puede abrir cualquier lector. Se activa con
    # FUENTES_ACTIVAS si se tiene suscripción.
    activa_por_defecto = False

    def listar(self) -> list[Candidato]:
        sopa = self.sopa(self.portada, parser="html.parser")  # el HTML de elDial rompe lxml
        salida: list[Candidato] = []
        vistos: set[str] = set()
        hoy = ahora()

        # 1) "Fallos del día": <h3>Jurisprudencia / Jurisdicción / Materia</h3><h4><a>Título</a></h4><p>Sumario</p>
        for li in sopa.select("ul.fallos_del_dia li"):
            enlace = li.select_one("h4 a[href]")
            if not enlace:
                continue
            url = self._canonica(absoluta(self.portada, enlace["href"]))
            if url in vistos:
                continue
            vistos.add(url)
            miga = li.find("h3").get_text(" ", strip=True) if li.find("h3") else ""
            resumen = li.find("p").get_text(" ", strip=True) if li.find("p") else ""
            titulo = enlace.get("title") or enlace.get_text(" ", strip=True)
            salida.append(
                self.candidato(url, f"{titulo} ({miga.replace('Jurisprudencia / ', '')})" if miga else titulo,
                               resumen=resumen, seccion=miga, fecha=hoy, texto=f"{miga}. {titulo}. {resumen}",
                               detalle_cargado=True)
            )

        # 2) Destacados de legislación / doctrina: <div class="texto"><h2>Sección</h2><h3>Título</h3><p>…</p></div><a class="mas">
        for li in sopa.select("div.contenedor li"):
            texto = li.select_one("div.texto")
            enlace = li.select_one("a.mas[href]")
            if not texto or not enlace or not texto.find("h3"):
                continue
            url = self._canonica(absoluta(self.portada, enlace["href"]))
            if url in vistos:
                continue
            vistos.add(url)
            seccion = texto.find("h2").get_text(" ", strip=True) if texto.find("h2") else ""
            titulo = texto.find("h3").get_text(" ", strip=True)
            resumen = texto.find("p").get_text(" ", strip=True) if texto.find("p") else ""
            if titulo.isupper():
                titulo = titulo.capitalize()
            salida.append(
                self.candidato(url, titulo, resumen=resumen, seccion=seccion, fecha=hoy,
                               texto=f"{seccion}. {titulo}. {resumen}", detalle_cargado=True)
            )
        return salida[: self.max_candidatos]

    @staticmethod
    def _canonica(url: str) -> str:
        """fallo4.asp?base=14&id=67036&t=j&h=u y fallo4.asp?id=67036&base=14 son la misma pieza."""
        partes = urlsplit(url)
        params = parse_qs(partes.query)
        if "id" in params:
            pagina = partes.path.rsplit("/", 1)[-1]
            base = params.get("base", [""])[0]
            return f"https://www.eldial.com/nuevo/nuevo_diseno/v2/{pagina}?base={base}&id={params['id'][0]}"
        return url

    def cargar_detalle(self, cand: Candidato) -> None:  # contenido para suscriptores: no se descarga
        cand.detalle_cargado = True


class FuenteRSS(Fuente):
    """Fuente genérica a partir de un feed RSS 2.0 (WordPress, Drupal, Arc, etc.)."""

    feed: str = ""
    usar_contenido_del_feed = True
    filtro_url: str = ""  # expresión regular que deben cumplir los enlaces (vacío = todos)

    def ajustar(self, cand: Candidato) -> Candidato | None:
        """Gancho para retocar o descartar cada ítem del feed."""
        return cand

    def listar(self) -> list[Candidato]:
        resp = self.http.get(self.feed)
        raiz = ET.fromstring(resp.content)
        salida: list[Candidato] = []
        for item in raiz.iter("item"):
            url = limpiar_espacios(item.findtext("link"))
            titulo = texto_plano_seguro(item.findtext("title"))
            if not url or not titulo or (self.filtro_url and not re.search(self.filtro_url, url)):
                continue
            descripcion = texto_plano_seguro(item.findtext("description"))
            contenido = item.find(_NS_CONTENT)
            cand = self.candidato(
                url,
                titulo,
                resumen=descripcion[:600],
                fecha=parsear_fecha(item.findtext("pubDate")),
                seccion=", ".join(c.text or "" for c in item.findall("category"))[:120],
            )
            if self.usar_contenido_del_feed and contenido is not None and contenido.text:
                cand.texto = texto_plano_seguro(contenido.text)[:12000]
                cand.resumen = cand.resumen or cand.texto[:600]
                cand.detalle_cargado = True
            cand = self.ajustar(cand)
            if cand is not None:
                salida.append(cand)
            if len(salida) >= self.max_candidatos:
                break
        return salida


class PensamientoPenal(FuenteRSS):
    clave = "pensamiento_penal"
    nombre = "Pensamiento Penal"
    portada = "https://www.pensamientopenal.com.ar/"
    feed = "https://www.pensamientopenal.com.ar/rss.xml"
    dominios = frozenset({"pensamientopenal.com.ar"})
    prioridad = 70
    selectores_cuerpo = ("div.field--name-body", "div.node__content", "article")
    # Su robots.txt declara "Content-Signal: ai-train=no": el pipeline lo detecta y sólo
    # envía a la IA título y bajada (modo referencia). Con una bajada breve basta 1 cita.
    min_citas = 1

    def listar(self) -> list[Candidato]:
        salida = super().listar()
        for cand in salida:
            ruta = urlsplit(cand.url).path.strip("/").split("/", 1)[0]
            cand.seccion = {"fallos": "Fallos", "doctrina": "Doctrina", "legislacion": "Legislación"}.get(ruta, cand.seccion)
        return salida


class APPInstitucional(FuenteRSS):
    """Comunicados y posicionamientos de la Asociación Pensamiento Penal (sitio .org)."""

    clave = "app"
    nombre = "Asociación Pensamiento Penal"
    portada = "https://www.pensamientopenal.org/"
    feed = "https://www.pensamientopenal.org/feed/"
    dominios = frozenset({"pensamientopenal.org"})
    prioridad = 68
    selectores_cuerpo = ("div.entry-content", "article")


class AlDiaMicrojuris(FuenteRSS):
    """Portal abierto de Microjuris (el buscador documental, en cambio, es pago)."""

    clave = "aldia"
    nombre = "Al Día Argentina (Microjuris)"
    portada = "https://aldiaargentina.microjuris.com/"
    feed = "https://aldiaargentina.microjuris.com/feed/"
    dominios = frozenset({"aldiaargentina.microjuris.com"})
    prioridad = 63
    selectores_cuerpo = ("div.entry-content", "article")
    _rotulo = re.compile(r"^#(Fallos|Doctrina|Legislaci[oó]n|Opini[oó]n|Novedades)\s+", re.IGNORECASE)

    def ajustar(self, cand: Candidato) -> Candidato | None:
        if cand.titulo.lower().startswith(("selección editorial", "seleccion editorial")):
            return None  # resumen diario que repite notas sueltas
        m = self._rotulo.match(cand.titulo)
        if m:
            cand.seccion = m.group(1).capitalize()
            cand.titulo = cand.titulo[m.end():]
        return cand


class InfobaeJudiciales(FuenteRSS):
    """Sección Judiciales de Infobae: rápida en causas federales; jerarquía baja y triage estricto."""

    clave = "infobae"
    nombre = "Infobae Judiciales"
    portada = "https://www.infobae.com/judiciales/"
    feed = "https://www.infobae.com/arc/outboundfeeds/rss/category/judiciales/"
    dominios = frozenset({"infobae.com"})
    prioridad = 40
    filtro_url = r"^https://www\.infobae\.com/judiciales/\d{4}/"
    selectores_cuerpo = ("article", "div.body-article", "main")
