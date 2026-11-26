"""Estructuras de datos compartidas por todo el pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .textos import a_iso, desde_iso

_PARAMS_RASTREO = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "cache")


def normalizar_url(url: str) -> str:
    """Forma canónica de una URL para detectar duplicados exactos.

    Baja a minúsculas el esquema y el host, quita parámetros de rastreo, la barra final
    y el fragmento (salvo los fragmentos sintéticos que generamos nosotros: '#id-...').
    """
    partes = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(partes.query, keep_blank_values=True)
        if not k.lower().startswith(_PARAMS_RASTREO)
    ]
    fragmento = partes.fragment if partes.fragment.startswith("id-") else ""
    ruta = partes.path.rstrip("/") or "/"
    return urlunsplit(
        (partes.scheme.lower(), partes.netloc.lower(), ruta, urlencode(query), fragmento)
    )


def hash_url(url: str) -> str:
    return hashlib.sha256(normalizar_url(url).encode("utf-8")).hexdigest()


@dataclass
class Candidato:
    """Una pieza detectada en una fuente, antes de pasar por la IA.

    `resumen` es lo que la portada de la fuente muestra (bajada / copete) y `texto` es
    el cuerpo completo, ya saneado, que se carga sólo si el candidato pasa el triage.
    `oficial` guarda metadatos estructurados que la fuente publica (carátula,
    expediente, materia...): cuando existen, prevalecen sobre lo que diga la IA.
    """

    fuente: str
    url: str
    titulo: str
    resumen: str = ""
    fecha: datetime | None = None
    seccion: str = ""
    oficial: dict = field(default_factory=dict)
    texto: str = ""
    detalle_cargado: bool = False
    modo_ia: str = "completo"  # "completo" | "referencia" (sólo título + bajada)
    alertas_seguridad: list[str] = field(default_factory=list)
    intentos: int = 0
    triado: bool = False

    @property
    def url_hash(self) -> str:
        return hash_url(self.url)

    @property
    def id(self) -> str:
        return self.url_hash[:12]

    def texto_para_ia(self) -> str:
        if self.modo_ia == "referencia":
            return self.resumen
        return self.texto or self.resumen

    def a_dict(self) -> dict:
        d = asdict(self)
        d["fecha"] = a_iso(self.fecha)
        return d

    @classmethod
    def desde_dict(cls, d: dict) -> "Candidato":
        datos = dict(d)
        datos["fecha"] = desde_iso(datos.get("fecha"))
        campos = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in datos.items() if k in campos})
