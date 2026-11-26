"""Portales de los poderes judiciales: Justicia.ar (federal, desarrollado por la CSJN) e
iJudicial (agencia de noticias del Poder Judicial de la Ciudad de Buenos Aires)."""

from __future__ import annotations

from ..modelos import Candidato
from ..seguridad import texto_plano_seguro
from ..textos import parsear_fecha
from .base import Fuente, token_csrf
from .medios import FuenteRSS


class JusticiaAR(Fuente):
    """Novedades de todos los poderes judiciales del país. Muchas son institucionales: el
    triage las filtra."""

    clave = "justicia_ar"
    nombre = "Justicia.ar"
    portada = "https://www.justicia.ar/novedades"
    dominios = frozenset({"justicia.ar"})
    prioridad = 84
    oficial = True
    selectores_cuerpo = ("section.detalleNovedad", "main")

    def listar(self) -> list[Candidato]:
        token = token_csrf(self.http.get(self.portada).text)
        resp = self.http.post(
            "https://www.justicia.ar/novedades/dataNoticias",
            json={"start": 0, "length": self.max_candidatos, "formBusqueda": {"temas": []}},
            headers={"X-CSRF-TOKEN": token, "X-Requested-With": "XMLHttpRequest", "Referer": self.portada,
                     "Accept": "application/json, */*; q=0.01"},
        )
        salida: list[Candidato] = []
        for nota in (resp.json() or {}).get("listaDatos") or []:
            ident = str(nota.get("idNoticia") or "").strip()
            titulo = texto_plano_seguro(nota.get("titulo"))
            ruta = str(nota.get("url") or "").strip()
            if not ident.isdigit() or not titulo or not ruta.startswith("/"):
                continue
            jurisdiccion = (nota.get("jurisdiccion") or {}).get("nombre") or ""
            tema = (nota.get("tema") or {}).get("descripcion") or ""
            organo = jurisdiccion if any(p in jurisdiccion for p in ("Corte", "Consejo", "Ministerio")) else (
                f"Poder Judicial de {jurisdiccion}" if jurisdiccion else "")
            salida.append(self.candidato(
                f"https://www.justicia.ar/novedades/{ident}/{nota.get('anio')}/{nota.get('mes')}{ruta}",
                titulo,
                resumen=texto_plano_seguro(nota.get("resumen"))[:600],
                fecha=parsear_fecha(nota.get("fecha")),
                seccion=" · ".join(p for p in (jurisdiccion, tema) if p),
                oficial={"tribunal": organo} if organo else {},
            ))
        return salida


class IJudicial(FuenteRSS):
    clave = "ijudicial"
    nombre = "iJudicial (Poder Judicial de la Ciudad)"
    portada = "https://ijudicial.gob.ar/"
    feed = "https://ijudicial.gob.ar/feed/"
    dominios = frozenset({"ijudicial.gob.ar"})
    prioridad = 82
    oficial = True
    selectores_cuerpo = ("div.entry-content", "article", "main")

    def prefiltro(self, cand: Candidato) -> str | None:
        categorias = {c.strip().lower() for c in cand.seccion.split(",")}
        if "institucionales" in categorias and not categorias & {"fallos", "difusión judicial", "procesos colectivos"}:
            return "nota institucional (actos, visitas, jornadas)"
        return None
