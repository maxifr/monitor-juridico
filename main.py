"""Monitor Jurídico AR — punto de entrada.

Uso:
    python main.py                      corrida completa (recolecta, cura con IA, publica y exporta el sitio)
    python main.py --probar-fuentes     prueba los extractores sin IA y sin guardar nada
    python main.py --fuentes csjn,mpf   limita la corrida a algunas fuentes
    python main.py --exportar           sólo regenera los datos del sitio (site/data) y el RSS
    python main.py --cuarentena         muestra lo bloqueado por seguridad en los últimos días
    python main.py --demo               genera datos de ejemplo para ver el sitio sin clave de IA
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from monitor import fuentes as registro
from monitor.alertas import notificar
from monitor.almacen import Almacen
from monitor.config import cargar_ajustes
from monitor.exportar import exportar
from monitor.http import ClienteHTTP
from monitor.ia import ErrorIA


def _configurar_logs(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    for ruidoso in ("httpx", "httpcore", "google_genai", "urllib3"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def probar_fuentes(claves: list[str] | None) -> int:
    fallas = 0
    with ClienteHTTP(pausa=(0.8, 1.6)) as http:
        for fuente in registro.construir(http, claves, 20):
            t0 = time.monotonic()
            try:
                candidatos = fuente.listar()
            except Exception as exc:
                fallas += 1
                print(f"✗ {fuente.nombre}: {type(exc).__name__}: {exc}")
                continue
            descartados = sum(1 for c in candidatos if fuente.prefiltro(c))
            estado = "✓" if candidatos else "!"
            print(f"{estado} {fuente.nombre}: {len(candidatos)} candidatos "
                  f"({descartados} descartados por reglas) en {time.monotonic() - t0:.1f}s")
            for cand in [c for c in candidatos if not fuente.prefiltro(c)][:3]:
                fecha = cand.fecha.date().isoformat() if cand.fecha else "s/f"
                print(f"    {fecha}  {cand.titulo[:100]}")
            if not candidatos:
                fallas += 1
    return 1 if fallas else 0


def mostrar_cuarentena(ajustes) -> int:
    registros = Almacen(ajustes.dir_datos).cargar().cuarentena()
    if not registros:
        print("La cuarentena está vacía.")
        return 0
    for reg in registros[-30:]:
        print(f"[{reg.get('fecha', '')[:16]}] {reg.get('capa'):<13} {reg.get('fuente'):<18} {reg.get('url')}")
        print(f"    motivo: {reg.get('motivo')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor Jurídico AR")
    parser.add_argument("--fuentes", help="claves separadas por coma: " + ", ".join(registro.todas_las_claves()))
    parser.add_argument("--probar-fuentes", action="store_true", help="prueba los extractores sin IA ni escritura")
    parser.add_argument("--exportar", action="store_true", help="sólo regenera site/data y el RSS")
    parser.add_argument("--cuarentena", action="store_true", help="lista los bloqueos de seguridad")
    parser.add_argument("--demo", action="store_true", help="carga datos de ejemplo para previsualizar el sitio")
    parser.add_argument("--sin-exportar", action="store_true", help="no regenera el sitio al terminar")
    parser.add_argument("-v", "--verboso", action="store_true")
    args = parser.parse_args(argv)
    _configurar_logs(args.verboso)
    ajustes = cargar_ajustes()
    claves = [c.strip() for c in args.fuentes.split(",")] if args.fuentes else None

    if args.probar_fuentes:
        return probar_fuentes(claves)
    if args.cuarentena:
        return mostrar_cuarentena(ajustes)
    if args.demo:
        from scripts.datos_demo import exportar_demo

        meta = exportar_demo(ajustes)
        print(f"Sitio de demostración listo ({meta['total']} fichas). Abrilo con: python scripts/servir.py")
        return 0
    if args.exportar:
        meta = exportar(Almacen(ajustes.dir_datos).cargar(), ajustes)
        print(f"Sitio exportado: {meta['total']} novedades ({meta['en_portada']} en portada).")
        return 0

    from monitor.pipeline import Pipeline

    try:
        pipeline = Pipeline(ajustes, claves=claves)
        resumen = pipeline.ejecutar()
    except ErrorIA as exc:
        logging.error("%s", exc)
        return 2
    print("\n" + resumen.texto())
    if not args.sin_exportar:
        exportar(pipeline.almacen, ajustes)
    notificar(ajustes, pipeline.almacen, resumen.nuevas)
    # Falla la corrida (y GitHub avisa por mail) sólo si todas las fuentes cayeron.
    if resumen.por_fuente and not any(i.get("ok") for i in resumen.por_fuente.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
