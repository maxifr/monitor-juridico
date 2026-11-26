"""Corte Suprema de Justicia de la Nación — Secretaría de Jurisprudencia (novedades).

Mejora respecto del plan original: en lugar de Playwright (Chromium, pesado y frágil),
se usa el mismo endpoint JSON que consume la página de novedades de sjconsulta. Trae
datos oficiales estructurados: expediente, carátula, materia, relevancia y la síntesis
redactada por la propia Secretaría (texto público, citable).
"""

from __future__ import annotations

from ..modelos import Candidato
from ..seguridad import html_a_texto_seguro, texto_plano_seguro
from ..textos import parsear_fecha
from .base import Fuente, token_csrf

BASE = "https://sjconsulta.csjn.gov.ar/sjconsulta"


class CSJN(Fuente):
    clave = "csjn"
    nombre = "CSJN — Secretaría de Jurisprudencia"
    portada = f"{BASE}/novedades/consulta.html"
    dominios = frozenset({"csjn.gov.ar"})
    prioridad = 100
    oficial = True
    dominio_publico = True

    def listar(self) -> list[Candidato]:
        # La primera visita crea la sesión (cookie) que exige el endpoint JSON.
        self.http.get(self.portada)
        candidatos: list[Candidato] = []
        indice = 0
        while len(candidatos) < self.max_candidatos:
            resp = self.http.get(
                f"{BASE}/novedades/paginarNovedades.html",
                params={"indice": indice},
                # Sin este Accept el servidor responde XML en lugar de JSON.
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.portada,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
            )
            registros = (resp.json() or {}).get("Records") or []
            if not registros:
                break
            for reg in registros:
                cand = self._a_candidato(reg)
                if cand:
                    candidatos.append(cand)
            indice += len(registros)
            if len(registros) < 10:
                break
        return candidatos[: self.max_candidatos]

    def _a_candidato(self, reg: dict) -> Candidato | None:
        id_analisis = str(reg.get("idAnalisis") or "").strip()
        titulo = texto_plano_seguro(reg.get("titulo"))
        if not id_analisis or not titulo:
            return None
        saneado = html_a_texto_seguro(reg.get("cabecilla") or "")
        caratula = texto_plano_seguro(reg.get("caratula"))
        expediente = texto_plano_seguro(reg.get("identificadorExpediente"))
        materia = texto_plano_seguro(reg.get("materia"))
        relevancia = str(reg.get("htmlRelevancia") or "").count("asterisk")
        codigo = reg.get("codigo")
        cuerpo = " ".join(
            p for p in (f"Carátula: {caratula}." if caratula else "", f"Expediente: {expediente}." if expediente else "",
                        f"Materia: {materia}." if materia else "", saneado.texto) if p
        )
        cand = self.candidato(
            f"{BASE}/novedades/consulta.html?id={id_analisis}",
            titulo,
            resumen=saneado.texto[:600],
            fecha=parsear_fecha(reg.get("fecha")),
            seccion=materia,
            texto=cuerpo,
            detalle_cargado=True,
            oficial={
                "caratula": caratula,
                "identificador_legal": expediente,
                "tribunal": "Corte Suprema de Justicia de la Nación",
                "materia_oficial": materia,
                "relevancia": relevancia,
                "inconstitucional": bool(reg.get("inconstitucional")),
                "sentencia_arbitraria": bool(reg.get("sentenciaArbitraria")),
                "url_fallo": f"{BASE}/documentos/verDocumentoByIdLinksJSP.html?idDocumento={codigo}" if codigo else "",
            },
        )
        if saneado.nodos_ocultos:
            cand.alertas_seguridad.append(f"oculto:{saneado.texto_oculto}")
        return cand


class CSJNNoticias(Fuente):
    """Noticias institucionales de la Corte (acordadas, comunicados, informes) en csjn.gov.ar/novedades.

    Complementa a la Secretaría de Jurisprudencia: la página carga el listado desde un
    endpoint JSON que exige el token anti-CSRF de la propia página.
    """

    clave = "csjn_noticias"
    nombre = "CSJN — Noticias institucionales"
    portada = "https://www.csjn.gov.ar/novedades"
    dominios = frozenset({"csjn.gov.ar"})
    prioridad = 98
    oficial = True
    selectores_cuerpo = ("#contenedorTexto", "article", "main")

    def listar(self) -> list[Candidato]:
        token = token_csrf(self.http.get(self.portada).text)
        resp = self.http.post(
            "https://www.csjn.gov.ar/novedades/dataNovedades",
            json={"draw": 1, "start": 0, "length": self.max_candidatos, "order": [], "formBusqueda": {}},
            headers={"X-CSRF-TOKEN": token, "X-Requested-With": "XMLHttpRequest", "Referer": self.portada,
                     "Accept": "application/json, */*; q=0.01"},
        )
        salida: list[Candidato] = []
        for nota in (resp.json() or {}).get("data") or []:
            ident = str(nota.get("idNoticia") or "").strip()
            titulo = texto_plano_seguro(nota.get("titulo"))
            if not ident.isdigit() or not titulo:
                continue
            salida.append(self.candidato(
                f"https://www.csjn.gov.ar/novedades/detalle/{ident}",
                titulo,
                resumen=texto_plano_seguro(nota.get("resumen"))[:600],
                fecha=parsear_fecha(nota.get("fechaPublicacion")),
                seccion=texto_plano_seguro(nota.get("descripcionTema")),
                oficial={"tribunal": "Corte Suprema de Justicia de la Nación"},
            ))
        return salida
