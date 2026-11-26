"""Registro de fuentes. Para sumar una fuente nueva: crear su clase y agregarla acá.

El orden de procesamiento es por prioridad (las oficiales primero), de modo que si el
mismo fallo aparece en varios portales la ficha se arma con el texto oficial y los
medios quedan como coberturas adicionales.
"""

from __future__ import annotations

from ..http import ClienteHTTP
from .base import Fuente
from .csjn import CSJN, CSJNNoticias
from .medios import (
    AlDiaMicrojuris,
    APPInstitucional,
    DiarioJudicial,
    ElDial,
    InfobaeJudiciales,
    PalabrasDelDerecho,
    PensamientoPenal,
    PoderJudicialTDF,
)
from .ministerios_publicos import MPD, MPF
from .oficiales import BoletinOficial, InfoLeg, SAIJBoletin, SAIJJurisprudenciaTDF, SAIJLegislacion
from .poderes_judiciales import IJudicial, JusticiaAR

# Fuentes evaluadas y descartadas (ver README): La Ley/Westlaw, Microjuris (buscador),
# Errepar/Erreius, El Derecho, AI Legales, JurisprudenciaARG, Lejister y Actualidad
# Jurídica (pagas); Campus Judicial (cursos); LegisLaw (directorio de enlaces sin
# novedades: su feed está vacío). elDial queda disponible pero desactivada por defecto.
CLASES: tuple[type[Fuente], ...] = (
    CSJN,
    CSJNNoticias,
    InfoLeg,
    BoletinOficial,
    SAIJLegislacion,
    SAIJJurisprudenciaTDF,
    SAIJBoletin,
    MPF,
    MPD,
    PoderJudicialTDF,
    JusticiaAR,
    IJudicial,
    PalabrasDelDerecho,
    PensamientoPenal,
    APPInstitucional,
    AlDiaMicrojuris,
    DiarioJudicial,
    ElDial,
    InfobaeJudiciales,
)

POR_CLAVE: dict[str, type[Fuente]] = {c.clave: c for c in CLASES}


def todas_las_claves() -> list[str]:
    return [c.clave for c in CLASES]


def construir(http: ClienteHTTP, claves: tuple[str, ...] | list[str] | None = None, max_candidatos: int = 20) -> list[Fuente]:
    elegidas = [POR_CLAVE[c] for c in claves if c in POR_CLAVE] if claves else [c for c in CLASES if c.activa_por_defecto]
    desconocidas = [c for c in (claves or []) if c not in POR_CLAVE]
    if desconocidas:
        raise ValueError(f"Fuentes desconocidas: {', '.join(desconocidas)}. Disponibles: {', '.join(POR_CLAVE)}")
    fuentes = [cls(http, max_candidatos) for cls in elegidas]
    return sorted(fuentes, key=lambda f: f.prioridad, reverse=True)


def dominios_permitidos() -> frozenset[str]:
    dominios: set[str] = set()
    for cls in CLASES:
        dominios |= set(cls.dominios)
    return frozenset(dominios)


def info_fuentes(claves: tuple[str, ...] | list[str] | None = None) -> list[dict]:
    elegidas = [c for c in CLASES if (c.clave in claves if claves else c.activa_por_defecto)]
    return [
        {"clave": c.clave, "nombre": c.nombre, "portada": c.portada, "prioridad": c.prioridad, "oficial": c.oficial}
        for c in sorted(elegidas, key=lambda c: c.prioridad, reverse=True)
    ]


def prioridad(clave: str) -> int:
    cls = POR_CLAVE.get(clave)
    return cls.prioridad if cls else 50


def nombre(clave: str) -> str:
    cls = POR_CLAVE.get(clave)
    return cls.nombre if cls else clave
