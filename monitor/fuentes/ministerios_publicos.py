"""Ministerio Público Fiscal (fiscales.gob.ar).

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
