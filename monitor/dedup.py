"""Deduplicación semántica multi-fuente con jerarquía oficial.

Problema: dos portales cuentan el mismo fallo con palabras distintas, pero dos condenas
distintas por narcotráfico del mismo mes se parecen muchísimo. Por eso se decide en capas:

1. Atajo determinista: mismo expediente o norma (normalizado) en la ventana → mismo hecho
   si además coincide la fecha o lo confirma el juez.
2. Similitud de embeddings (vectores guardados en el repo, sólo de la ventana):
   ≥ umbral_auto y mismo tribunal → mismo hecho; zona gris → decide un juez LLM.
3. Si no hay embeddings (cuota agotada) → similitud léxica de títulos + juez.

Al fusionar, gana la fuente de mayor jerarquía (CSJN > Boletín/SAIJ > ministerios
públicos > revistas > diarios) y las demás quedan como coberturas adicionales.
"""

from __future__ import annotations

import logging
import re

from .almacen import Almacen
from .curaduria import mismo_hecho
from .ia import ClienteIA, ErrorIA, SinCuota
from .textos import jaccard, normalizar, sin_tildes

log = logging.getLogger(__name__)


def normalizar_identificador(valor: str | None) -> str | None:
    """Clave canónica para comparar expedientes y normas entre fuentes.

    'FLP 001221/2024/CS001' y 'FLP 1221/2024' -> 'FLP 1221/2024'
    'Ley N° 27.828' -> 'LEY 27828'      'DNU 70/2023' y 'Decreto 70/2023' -> 'DECRETO 70/2023'
    """
    if not valor:
        return None
    texto = sin_tildes(valor.upper())
    texto = re.sub(r"\bN(RO|°|º|\.)\s*", "", texto)
    texto = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", texto)  # separador de miles
    texto = re.sub(r"\b(DECRETO DE NECESIDAD Y URGENCIA|DNU)\b", "DECRETO", texto)
    for abreviatura, completa in ((r"RES\.?\s*GRAL\.?", "RESOLUCION GENERAL"), (r"RES\.", "RESOLUCION"),
                                  (r"DEC\.", "DECRETO"), (r"DISP\.", "DISPOSICION"), (r"ACORD\.", "ACORDADA")):
        texto = re.sub(r"\b" + abreviatura + r"\s*", completa + " ", texto)
    expediente = re.search(r"\b([A-Z]{2,5})\s*0*(\d{1,7})\s*/\s*(\d{4})\b", texto)
    if expediente and expediente.group(1) != "LEY":
        return f"{expediente.group(1)} {int(expediente.group(2))}/{expediente.group(3)}"
    norma = re.search(
        r"\b(LEY|DECRETO|RESOLUCION GENERAL|RESOLUCION CONJUNTA|RESOLUCION|DISPOSICION|ACORDADA|DECISION ADMINISTRATIVA)"
        r"\s+(\d+)(?:\s*/\s*(\d{2,4}))?",
        texto,
    )
    if norma:
        anio = norma.group(3)
        if anio and len(anio) == 2:
            anio = "20" + anio
        return f"{norma.group(1)} {norma.group(2)}" + (f"/{anio}" if anio else "")
    texto = re.sub(r"\s+", " ", texto).strip(" .,-")
    return texto if len(texto) >= 5 and re.search(r"\d", texto) else None


def texto_semantico(ficha: dict) -> str:
    partes = [
        f"Tribunal: {ficha.get('tribunal')}" if ficha.get("tribunal") else "",
        f"Expediente/Norma: {ficha.get('identificador_legal')}" if ficha.get("identificador_legal") else "",
        f"Carátula: {ficha.get('caratula')}" if ficha.get("caratula") else "",
        f"Título: {ficha.get('titulo')}",
        f"Holding: {ficha.get('holding')}",
    ]
    return "\n".join(p for p in partes if p)


def _mismo_tribunal(a: dict, b: dict) -> bool:
    ta, tb = normalizar(a.get("tribunal")), normalizar(b.get("tribunal"))
    return bool(ta and tb and (ta in tb or tb in ta))


class Deduplicador:
    def __init__(self, almacen: Almacen, ia: ClienteIA | None, ventana_dias: int, umbral_gris: float, umbral_auto: float):
        self.almacen = almacen
        self.ia = ia
        self.ventana = ventana_dias
        self.umbral_gris = umbral_gris
        self.umbral_auto = umbral_auto
        self.consultas_juez = 0

    def _juez(self, existente: dict, nueva: dict) -> bool:
        if self.ia is None:
            return False
        try:
            self.consultas_juez += 1
            veredicto = mismo_hecho(self.ia, existente, nueva)
            log.info("Juez de duplicados: %s (%s)", veredicto.es_mismo_hecho, veredicto.razon[:90])
            return veredicto.es_mismo_hecho
        except (ErrorIA, SinCuota) as exc:
            log.warning("Juez de duplicados no disponible (%s): se publica por separado.", exc)
            return False

    def buscar(self, ficha: dict, embedding: list[float] | None) -> dict | None:
        """Devuelve la novedad existente que trata el mismo hecho, o None."""
        ident = ficha.get("id_legal_norm")
        if ident:
            for existente in self.almacen.por_identificador(ident, max(self.ventana, 60)):
                misma_fecha = (existente.get("fecha") or "")[:10] == (ficha.get("fecha") or "")[:10]
                if misma_fecha or self._juez(existente, ficha):
                    return existente

        if embedding:
            for existente, sim in self.almacen.similares(embedding, self.ventana, self.umbral_gris):
                # Dos expedientes o normas distintos nunca se fusionan automáticamente
                # (p. ej. dos resoluciones casi idénticas del mismo ministerio): decide el juez.
                ids_distintos = bool(ident and existente.get("id_legal_norm") and existente["id_legal_norm"] != ident)
                if (sim >= self.umbral_auto and not ids_distintos
                        and (_mismo_tribunal(existente, ficha) or not ficha.get("tribunal"))):
                    log.info("Duplicado por similitud %.3f con %s", sim, existente["id"])
                    return existente
                if self._juez(existente, ficha):
                    return existente
            return None

        # Sin embeddings: aproximación léxica conservadora.
        candidatos = sorted(
            (
                (jaccard(f"{e.get('titulo')} {e.get('holding')}", f"{ficha.get('titulo')} {ficha.get('holding')}"), e)
                for e in self.almacen.recientes(self.ventana)
            ),
            key=lambda par: par[0],
            reverse=True,
        )
        for puntaje, existente in candidatos[:2]:
            if puntaje >= 0.35 and self._juez(existente, ficha):
                return existente
        return None


CAMPOS_FICHA = (
    "titulo", "bajada", "tipo", "materia", "instancia", "jurisdiccion", "tribunal", "caratula",
    "identificador_legal", "id_legal_norm", "holding", "puntos_clave", "impacto_practico", "normas_citadas", "etiquetas",
    "cita_sugerida", "alto_impacto", "verificacion", "oficial", "modelo", "citas_textuales", "extracto_oficial",
)


def fusionar(almacen: Almacen, existente: dict, nueva: dict, embedding: list[float] | None) -> str:
    """Integra una cobertura nueva a una novedad existente respetando la jerarquía."""
    cobertura_nueva = {"fuente": nueva["fuente"], "fuente_nombre": nueva["fuente_nombre"], "url": nueva["url"],
                       "titulo": nueva.get("titulo_original") or nueva.get("titulo"), "fecha": nueva.get("fecha")}
    adicionales = list(existente.get("fuentes_adicionales") or [])
    urls = {existente["url"]} | {a.get("url") for a in adicionales}
    if nueva["url"] in urls:
        return "ya_vinculada"

    if int(nueva.get("prioridad", 50)) > int(existente.get("prioridad", 50)):
        # La fuente nueva tiene más jerarquía: pasa a ser la principal y la anterior queda como cobertura.
        adicionales.append({"fuente": existente["fuente"], "fuente_nombre": existente.get("fuente_nombre"),
                            "url": existente["url"], "titulo": existente.get("titulo_original") or existente.get("titulo"),
                            "fecha": existente.get("fecha")})
        cambios = {k: nueva[k] for k in CAMPOS_FICHA if k in nueva}
        cambios.update({
            "fuente": nueva["fuente"], "fuente_nombre": nueva["fuente_nombre"], "url": nueva["url"],
            "prioridad": nueva["prioridad"], "titulo_original": nueva.get("titulo_original"),
            "fuentes_adicionales": adicionales, "fecha": nueva.get("fecha") or existente.get("fecha"),
            "dominio_publico": nueva.get("dominio_publico", False),
        })
        if not cambios.get("caratula"):
            cambios["caratula"] = existente.get("caratula", "")
        almacen.actualizar_novedad(existente["id"], cambios, embedding)
        return "promovida_fuente_superior"

    adicionales.append(cobertura_nueva)
    almacen.actualizar_novedad(existente["id"], {"fuentes_adicionales": adicionales})
    return "agregada_como_cobertura"
