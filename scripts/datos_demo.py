"""Exporta al sitio (site/data) las fichas de demostración, sin tocar data/.

Sirve para ver el portal funcionando antes de configurar la clave de Gemini:
    python main.py --demo
    python scripts/servir.py

Las fichas de scripts/demo/datos_demo.json se redactaron a mano sobre publicaciones
reales del 25/11/2026 y pasaron por el pipeline real: extracción de las fuentes,
verificación de citas textuales, saneamiento y deduplicación multi-fuente.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from monitor.almacen import Almacen
from monitor.config import Ajustes
from monitor.exportar import exportar

RUTA = Path(__file__).resolve().parent / "demo" / "datos_demo.json"
AVISO = (
    "Datos de demostración: fichas redactadas a mano sobre publicaciones reales del 25 de noviembre de 2026. "
    "La primera sincronización con Gemini las reemplaza."
)


def exportar_demo(ajustes: Ajustes) -> dict:
    datos = json.loads(RUTA.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        almacen = Almacen(Path(tmp))
        for rec in datos["novedades"]:
            almacen.novedades[rec["id"]] = rec
        almacen.salud = datos.get("salud", {})
        return exportar(almacen, replace(ajustes, dir_datos=Path(tmp)), demo=AVISO)
