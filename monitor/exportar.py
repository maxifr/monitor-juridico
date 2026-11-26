"""Exporta los datos que lee el sitio estático y el feed RSS del portal.

    site/data/ultimas.json        portada: últimas N semanas
    site/data/archivo/AAAA-MM.json archivo histórico por mes (se carga a demanda)
    site/data/meta.json           portal, salud de fuentes, meses disponibles, última corrida
    site/feed.xml                 RSS 2.0 con las últimas 50 novedades
"""

from __future__ import annotations

import json
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from . import fuentes as registro
from .almacen import Almacen, _escribir_atomico
from .config import Ajustes
from .textos import a_iso, ahora, desde_iso

CAMPOS_PUBLICOS = (
    "id", "fuente", "fuente_nombre", "url", "fuente_oficial", "dominio_publico", "titulo", "bajada", "tipo",
    "materia", "instancia", "jurisdiccion", "tribunal", "caratula", "identificador_legal", "holding",
    "puntos_clave", "impacto_practico", "normas_citadas", "etiquetas", "cita_sugerida", "alto_impacto",
    "citas_textuales", "extracto_oficial", "oficial", "fecha", "ingresado", "actualizado",
    "fuentes_adicionales", "verificacion",
)
MINIMO_PORTADA = 60


def publico(rec: dict) -> dict:
    salida = {k: rec[k] for k in CAMPOS_PUBLICOS if k in rec and rec[k] not in (None, "", [], {})}
    salida.setdefault("alto_impacto", False)
    return salida


def _clave_orden(rec: dict) -> tuple:
    return (rec.get("fecha") or "", rec.get("ingresado") or "", rec.get("prioridad", 0))


def _json(datos) -> str:
    return json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n"


def exportar(almacen: Almacen, ajustes: Ajustes, demo: str | None = None) -> dict:
    sitio = Path(ajustes.dir_sitio)
    datos = sitio / "data"
    registros = sorted(almacen.todas(), key=_clave_orden, reverse=True)
    momento = ahora()
    generado = a_iso(momento)

    limite = momento - timedelta(days=ajustes.dias_portada)
    portada = [r for r in registros if (desde_iso(r.get("ingresado")) or momento) >= limite or (desde_iso(r.get("fecha")) or momento) >= limite]
    if len(portada) < MINIMO_PORTADA:
        portada = registros[:MINIMO_PORTADA]
    _escribir_atomico(datos / "ultimas.json", _json({"generado": generado, "items": [publico(r) for r in portada]}))

    por_mes: dict[str, list[dict]] = {}
    for rec in registros:
        por_mes.setdefault(Almacen.mes_de(rec), []).append(publico(rec))
    for mes, items in por_mes.items():
        _escribir_atomico(datos / "archivo" / f"{mes}.json", _json({"mes": mes, "items": items}))

    ultima = {}
    ruta_ultima = ajustes.dir_datos / "ultima_ejecucion.json"
    if ruta_ultima.exists():
        try:
            crudo = json.loads(ruta_ultima.read_text(encoding="utf-8"))
            ultima = {k: crudo.get(k) for k in ("inicio", "fin", "duracion_s", "publicados", "fusionados", "cuarentena",
                                                 "curados", "pendientes", "sin_cuota", "candidatos")}
        except (json.JSONDecodeError, OSError):
            ultima = {}

    fuentes_info = []
    for info in registro.info_fuentes(ajustes.fuentes_activas):
        salud = almacen.salud.get(info["clave"], {})
        historial = salud.get("historial", [])[-14:]
        fuentes_info.append({
            **info,
            "estado": salud.get("ultimo_estado", "sin_datos"),
            "ultimo_ok": salud.get("ultimo_ok"),
            "ultima": salud.get("ultima"),
            "fallas_consecutivas": salud.get("fallas_consecutivas", 0),
            "historial": [1 if h.get("ok") and h.get("n") else 0 for h in historial],
            "publicadas": sum(1 for r in registros if r.get("fuente") == info["clave"]
                              or any(a.get("fuente") == info["clave"] for a in r.get("fuentes_adicionales", []))),
        })

    meta = {
        "portal": {"nombre": ajustes.portal_nombre, "descripcion": ajustes.portal_descripcion, "url": ajustes.portal_url},
        "generado": generado,
        "total": len(registros),
        "en_portada": len(portada),
        "ventana_dias": ajustes.dias_portada,
        "meses": [{"mes": m, "cantidad": len(v)} for m, v in sorted(por_mes.items(), reverse=True)],
        "fuentes": fuentes_info,
        "ultima_ejecucion": ultima,
        "dominios": sorted(registro.dominios_permitidos()),
    }
    if demo:
        meta["demo"] = demo
    _escribir_atomico(datos / "meta.json", _json(meta))
    _escribir_atomico(sitio / "feed.xml", _rss(registros[:50], ajustes))
    return meta


def _rss(registros: list[dict], ajustes: Ajustes) -> str:
    base = ajustes.portal_url or ""
    items = []
    for rec in registros:
        enlace = f"{base}/#/n/{rec['id']}" if base else rec["url"]
        fecha = desde_iso(rec.get("fecha")) or ahora()
        descripcion = rec.get("bajada", "")
        if rec.get("holding"):
            descripcion += f"\n\nCriterio: {rec['holding']}"
        descripcion += f"\n\nFuente: {rec.get('fuente_nombre')} — {rec['url']}"
        categorias = "".join(f"<category>{escape(c)}</category>" for c in (rec.get("materia"), rec.get("tipo")) if c)
        items.append(
            "<item>"
            f"<title>{escape(rec.get('titulo', ''))}</title>"
            f"<link>{escape(enlace)}</link>"
            f"<guid isPermaLink=\"false\">{escape(rec['id'])}</guid>"
            f"<pubDate>{format_datetime(fecha)}</pubDate>"
            f"{categorias}"
            f"<description>{escape(descripcion)}</description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{escape(ajustes.portal_nombre)}</title>"
        f"<link>{escape(base or 'https://github.com')}</link>"
        f"<description>{escape(ajustes.portal_descripcion)}</description>"
        "<language>es-AR</language>"
        f"<lastBuildDate>{format_datetime(ahora())}</lastBuildDate>"
        + "".join(items)
        + "</channel></rss>\n"
    )
