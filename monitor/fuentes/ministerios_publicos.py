"""Ministerio Público Fiscal (fiscales.gob.ar) y Ministerio Público de la Defensa (mpd.gov.ar).

fiscales.gob.ar corre sobre WordPress pero hoy tiene deshabilitados la API REST
(«Only authenticated users») y los feeds RSS («No feeds available»), así que el plan
original de usar wp-json fallaría: se lee la portada directamente.
"""

from __future__ import annotations

import re

from ..modelos import Candidato
from ..textos import limpiar_espacios
from .base import Fuente, absoluta

_CATEGORIAS_DESCARTADAS = {"concursos"}


class MPF(Fuente):
    clave = "mpf"
    nombre = "Ministerio Público Fiscal"
    portada = "https://www.fiscales.gob.ar/"
    dominios = frozenset({"fiscales.gob.ar"})
    prioridad = 88
    oficial = True
    selectores_cuerpo = ("div.article-content", "div.entry-content", "article")

    def listar(self) -> list[Candidato]:
        sopa = self.sopa(self.portada)
        vistos: set[str] = set()
        salida: list[Candidato] = []
        for tarjeta in sopa.select("article.news-card"):
            enlace = tarjeta.select_one("a[href]")
            titulo_el = tarjeta.select_one(".news-card-title")
            if not enlace or not titulo_el:
                continue
            url = absoluta(self.portada, enlace["href"])
            if url in vistos or not url.startswith("https://www.fiscales.gob.ar/"):
                continue
            vistos.add(url)
            categoria = limpiar_espacios(" ".join(c.get_text(" ", strip=True) for c in tarjeta.select(".category")))
            salida.append(self.candidato(url, titulo_el.get_text(" ", strip=True), seccion=categoria))
        return salida[: self.max_candidatos]

    def prefiltro(self, cand: Candidato) -> str | None:
        ruta = cand.url.split("fiscales.gob.ar/", 1)[-1].split("/", 1)[0]
        if ruta in _CATEGORIAS_DESCARTADAS or cand.seccion.lower().strip() in _CATEGORIAS_DESCARTADAS:
            return "categoría institucional (concursos)"
        return None


class MPD(Fuente):
    clave = "mpd"
    nombre = "Ministerio Público de la Defensa"
    portada = "https://www.mpd.gov.ar/index.php/noticias-h"
    dominios = frozenset({"mpd.gov.ar"})
    prioridad = 86
    oficial = True
    selectores_cuerpo = ("div.com-content-article__body", "div[itemprop=articleBody]", "div.item-page", "article")

    def listar(self) -> list[Candidato]:
        sopa = self.sopa(self.portada)
        vistos: set[str] = set()
        salida: list[Candidato] = []
        for enlace in sopa.select("a[href*='/noticias-h/']"):
            titulo = enlace.get_text(" ", strip=True)
            url = absoluta(self.portada, enlace["href"])
            if len(titulo) < 25 or url in vistos:
                continue
            vistos.add(url)
            bloque = enlace.find_parent(class_=re.compile("item-content|blog-item"))
            resumen = ""
            if bloque:
                parrafos = [p.get_text(" ", strip=True) for p in bloque.find_all("p")]
                resumen = limpiar_espacios(" ".join(parrafos))[:600]
            # Los títulos vienen en mayúsculas; se dejan así (pasarlos a minúscula rompería los
            # nombres propios) y el titular publicado lo redacta el curador.
            salida.append(self.candidato(url, titulo, resumen=resumen))
        return salida[: self.max_candidatos]
