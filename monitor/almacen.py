"""Almacenamiento en archivos JSON dentro del propio repositorio (sin servicios pagos).

Reemplaza a Supabase en la versión 100 % gratuita: GitHub guarda el historial de cada
cambio y el sitio estático lee los datos exportados. Estructura en `data/`:

    novedades/AAAA-MM.json   fichas publicadas, un archivo por mes
    vistos.json              todo lo procesado (publicado, fusionado, descartado...) para
                             no volver a gastar cuota de IA en lo mismo
    embeddings.json          vectores de las novedades recientes (sólo la ventana de dedup)
    pendientes.json          candidatos que quedaron sin procesar por falta de cuota
    cuarentena.jsonl         bloqueos de seguridad, para auditar
    uso_ia.json              llamadas a la IA por día (las cuotas se reinician 00:00 PT)
    salud_fuentes.json       historial de cada extractor
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import struct
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .textos import a_iso, ahora, desde_iso

log = logging.getLogger(__name__)

RETENCION_VISTOS_DIAS = 200
RETENCION_CUARENTENA_DIAS = 120
RETENCION_PENDIENTES_DIAS = 4


def _escribir_atomico(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=".tmp-", suffix=ruta.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(contenido)
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _leer_json(ruta: Path, defecto):
    if not ruta.exists():
        return defecto
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.error("No se pudo leer %s (%s); se usa un valor vacío.", ruta, exc)
        return defecto


def _volcar(datos) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


# --------------------------------------------------------------------------- vectores


def codificar_vector(vector: list[float]) -> str:
    """float16 + base64: ~2 KB por vector de 768 dimensiones."""
    return base64.b64encode(struct.pack(f"<{len(vector)}e", *vector)).decode("ascii")


def decodificar_vector(texto: str) -> list[float]:
    crudo = base64.b64decode(texto)
    return list(struct.unpack(f"<{len(crudo) // 2}e", crudo))


def normalizar_vector(vector: list[float]) -> list[float]:
    norma = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norma for x in vector]


def coseno(a: list[float], b: list[float]) -> float:
    """Ambos vectores ya normalizados: el coseno es el producto punto."""
    return sum(x * y for x, y in zip(a, b))


# --------------------------------------------------------------------------- almacén


class Almacen:
    def __init__(self, directorio: Path) -> None:
        self.dir = Path(directorio)
        self.novedades: dict[str, dict] = {}
        self.vistos: dict[str, dict] = {}
        self.embeddings: dict[str, list[float]] = {}
        self.pendientes: dict[str, dict] = {}
        self.uso_ia: dict[str, dict[str, int]] = {}
        self.salud: dict[str, dict] = {}
        self._meses_modificados: set[str] = set()
        self._cuarentena_nueva: list[dict] = []

    # ------------------------------------------------------------------ carga / guardado
    def cargar(self) -> "Almacen":
        for archivo in sorted((self.dir / "novedades").glob("*.json")):
            for rec in _leer_json(archivo, []):
                if isinstance(rec, dict) and rec.get("id"):
                    self.novedades[rec["id"]] = rec
        self.vistos = _leer_json(self.dir / "vistos.json", {})
        self.pendientes = _leer_json(self.dir / "pendientes.json", {})
        self.uso_ia = _leer_json(self.dir / "uso_ia.json", {})
        self.salud = _leer_json(self.dir / "salud_fuentes.json", {})
        crudos = _leer_json(self.dir / "embeddings.json", {})
        for clave, valor in crudos.items():
            try:
                self.embeddings[clave] = decodificar_vector(valor)
            except (ValueError, struct.error):
                continue
        log.info("Almacén: %d novedades, %d vistos, %d pendientes", len(self.novedades), len(self.vistos), len(self.pendientes))
        return self

    def guardar(self) -> None:
        self.podar()
        por_mes: dict[str, list[dict]] = {}
        for rec in self.novedades.values():
            por_mes.setdefault(self.mes_de(rec), []).append(rec)
        meses = self._meses_modificados or set(por_mes)
        for mes in meses:
            recs = sorted(por_mes.get(mes, []), key=lambda r: (r.get("fecha") or "", r["id"]), reverse=True)
            _escribir_atomico(self.dir / "novedades" / f"{mes}.json", _volcar(recs))
        self._meses_modificados.clear()
        _escribir_atomico(self.dir / "vistos.json", _volcar(self.vistos))
        _escribir_atomico(self.dir / "pendientes.json", _volcar(self.pendientes))
        _escribir_atomico(self.dir / "uso_ia.json", _volcar(self.uso_ia))
        _escribir_atomico(self.dir / "salud_fuentes.json", _volcar(self.salud))
        _escribir_atomico(
            self.dir / "embeddings.json",
            json.dumps({k: codificar_vector(v) for k, v in self.embeddings.items()}, separators=(",", ":")) + "\n",
        )
        if self._cuarentena_nueva:
            ruta = self.dir / "cuarentena.jsonl"
            previas = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
            nuevas = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self._cuarentena_nueva)
            _escribir_atomico(ruta, previas + nuevas)
            self._cuarentena_nueva.clear()

    @staticmethod
    def mes_de(rec: dict) -> str:
        fecha = rec.get("fecha") or rec.get("ingresado") or a_iso(ahora())
        return str(fecha)[:7]

    # ------------------------------------------------------------------ vistos
    def ya_visto(self, url_hash: str) -> bool:
        return url_hash in self.vistos

    def marcar_visto(self, url_hash: str, estado: str, novedad_id: str | None = None, fuente: str = "") -> None:
        self.vistos[url_hash] = {
            "estado": estado,
            "fecha": a_iso(ahora()),
            **({"novedad": novedad_id} if novedad_id else {}),
            **({"fuente": fuente} if fuente else {}),
        }
        self.pendientes.pop(url_hash, None)

    # ------------------------------------------------------------------ novedades
    def agregar_novedad(self, rec: dict, embedding: list[float] | None = None) -> None:
        self.novedades[rec["id"]] = rec
        self._meses_modificados.add(self.mes_de(rec))
        if embedding:
            self.embeddings[rec["id"]] = normalizar_vector(embedding)

    def actualizar_novedad(self, novedad_id: str, cambios: dict, embedding: list[float] | None = None) -> dict:
        rec = self.novedades[novedad_id]
        mes_anterior = self.mes_de(rec)
        rec.update(cambios)
        rec["actualizado"] = a_iso(ahora())
        self._meses_modificados.update({mes_anterior, self.mes_de(rec)})
        if embedding:
            self.embeddings[novedad_id] = normalizar_vector(embedding)
        return rec

    def recientes(self, dias: int) -> list[dict]:
        limite = ahora() - timedelta(days=dias)
        salida = []
        for rec in self.novedades.values():
            referencia = desde_iso(rec.get("ingresado")) or desde_iso(rec.get("fecha"))
            if referencia and referencia >= limite:
                salida.append(rec)
        return salida

    def por_identificador(self, identificador: str, dias: int) -> list[dict]:
        return [r for r in self.recientes(dias) if r.get("id_legal_norm") == identificador]

    def similares(self, vector: list[float], dias: int, umbral: float, k: int = 3) -> list[tuple[dict, float]]:
        vector = normalizar_vector(vector)
        resultados = []
        for rec in self.recientes(dias):
            otro = self.embeddings.get(rec["id"])
            if otro and len(otro) == len(vector):
                sim = coseno(vector, otro)
                if sim >= umbral:
                    resultados.append((rec, sim))
        resultados.sort(key=lambda par: par[1], reverse=True)
        return resultados[:k]

    # ------------------------------------------------------------------ pendientes
    def encolar_pendiente(self, url_hash: str, candidato: dict) -> None:
        previo = self.pendientes.get(url_hash, {})
        self.pendientes[url_hash] = {
            "candidato": candidato,
            "desde": previo.get("desde") or a_iso(ahora()),
            "intentos": int(previo.get("intentos", 0)) + 1,
        }

    def tomar_pendientes(self) -> list[dict]:
        return [p["candidato"] for p in self.pendientes.values() if p.get("candidato")]

    # ------------------------------------------------------------------ cuarentena
    def registrar_cuarentena(self, *, url: str, fuente: str, capa: str, motivo: str, extracto: str = "") -> None:
        self._cuarentena_nueva.append(
            {
                "fecha": a_iso(ahora()),
                "url": url,
                "fuente": fuente,
                "capa": capa,
                "motivo": motivo[:500],
                "extracto": (extracto or "")[:1500],
            }
        )

    def cuarentena(self) -> list[dict]:
        ruta = self.dir / "cuarentena.jsonl"
        registros = []
        if ruta.exists():
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                try:
                    registros.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue
        return registros + self._cuarentena_nueva

    # ------------------------------------------------------------------ uso de IA
    def contar_uso(self, dia: str, modelo: str, n: int = 1) -> int:
        del_dia = self.uso_ia.setdefault(dia, {})
        del_dia[modelo] = del_dia.get(modelo, 0) + n
        return del_dia[modelo]

    def uso(self, dia: str, modelo: str | None = None) -> int:
        del_dia = self.uso_ia.get(dia, {})
        if modelo:
            return del_dia.get(modelo, 0)
        return sum(del_dia.values())

    # ------------------------------------------------------------------ salud de fuentes
    def registrar_salud(self, clave: str, *, ok: bool, cantidad: int, error: str = "", duracion: float = 0.0) -> dict:
        info = self.salud.setdefault(clave, {"historial": []})
        momento = a_iso(ahora())
        info["historial"] = (info.get("historial", []) + [{"f": momento, "ok": ok, "n": cantidad}])[-30:]
        info["ultima"] = momento
        info["ultimo_estado"] = "ok" if ok and cantidad else ("sin_datos" if ok else "error")
        if ok and cantidad:
            info["ultimo_ok"] = momento
            info["fallas_consecutivas"] = 0
        else:
            info["fallas_consecutivas"] = int(info.get("fallas_consecutivas", 0)) + 1
        if error:
            info["ultimo_error"] = error[:300]
        info["duracion_s"] = round(duracion, 1)
        return info

    # ------------------------------------------------------------------ mantenimiento
    def podar(self) -> None:
        momento = ahora()

        def viejo(fecha_iso: str | None, dias: int) -> bool:
            fecha = desde_iso(fecha_iso)
            return fecha is not None and fecha < momento - timedelta(days=dias)

        self.vistos = {h: v for h, v in self.vistos.items() if not viejo(v.get("fecha"), RETENCION_VISTOS_DIAS)}
        self.pendientes = {
            h: p for h, p in self.pendientes.items()
            if not viejo(p.get("desde"), RETENCION_PENDIENTES_DIAS) and int(p.get("intentos", 0)) <= 6
        }
        recientes = {r["id"] for r in self.recientes(35)}
        self.embeddings = {k: v for k, v in self.embeddings.items() if k in recientes}
        dias_ordenados = sorted(self.uso_ia)
        self.uso_ia = {d: self.uso_ia[d] for d in dias_ordenados[-14:]}

    def podar_cuarentena(self) -> None:
        ruta = self.dir / "cuarentena.jsonl"
        if not ruta.exists():
            return
        limite = ahora() - timedelta(days=RETENCION_CUARENTENA_DIAS)
        conservar = []
        for reg in self.cuarentena():
            fecha = desde_iso(reg.get("fecha"))
            if fecha is None or fecha >= limite:
                conservar.append(reg)
        _escribir_atomico(ruta, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in conservar))
        self._cuarentena_nueva.clear()

    def todas(self) -> Iterable[dict]:
        return self.novedades.values()


def fecha_corta(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")
