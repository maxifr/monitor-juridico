"""Dobles de prueba: HTTP falso con respuestas fijas e IA falsa determinista."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from monitor.config import cargar_ajustes  # noqa: E402
from monitor.curaduria import FichaCurada, ItemTriage, RespuestaTriage, VeredictoDuplicado  # noqa: E402
from monitor.dedup import normalizar_identificador  # noqa: E402
from monitor.ia import SinCuota  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class RespuestaFalsa:
    def __init__(self, cuerpo: str | bytes, tipo: str = "text/html") -> None:
        self.content = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
        self.text = self.content.decode("utf-8")
        self.headers = {"content-type": tipo}
        self.status_code = 200

    def json(self):
        return json.loads(self.text)


class HTTPFalso:
    """Devuelve el contenido registrado para cada URL (se compara por prefijo)."""

    def __init__(self, rutas: dict[str, str], senales: dict[str, dict] | None = None) -> None:
        self.rutas = rutas
        self.senales = senales or {}
        self.pedidos: list[str] = []

    def get(self, url, params=None, headers=None, **_):
        self.pedidos.append(url)
        for prefijo, cuerpo in sorted(self.rutas.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(prefijo):
                return RespuestaFalsa(cuerpo)
        raise RuntimeError(f"URL no registrada en la prueba: {url}")

    def senales_contenido(self, url):
        for prefijo, senal in self.senales.items():
            if url.startswith(prefijo):
                return senal
        return {}

    def permitido(self, url):
        return True

    def cerrar(self):
        pass


def _vector(texto: str, dim: int = 64) -> list[float]:
    """Embedding falso: bolsa de palabras con hashing (textos parecidos -> vectores parecidos)."""
    v = [0.0] * dim
    for palabra in re.findall(r"[a-záéíóúñ0-9]{4,}", texto.lower()):
        v[int(hashlib.md5(palabra.encode()).hexdigest(), 16) % dim] += 1.0
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]


class IAFalsa:
    """Imita al curador: arma fichas a partir del propio texto, con citas literales."""

    modelo_texto = "modelo-falso"

    def __init__(self, cupo: int | None = None) -> None:
        self.llamadas: list[str] = []
        self.cupo = cupo

    def _consumir(self, tipo: str) -> None:
        if self.cupo is not None:
            if self.cupo <= 0:
                raise SinCuota("cupo de prueba agotado")
            self.cupo -= 1
        self.llamadas.append(tipo)

    def generar(self, *, sistema, contenido, esquema, temperatura=0.1):
        if esquema is RespuestaTriage:
            self._consumir("triage")
            items = []
            for n, linea in re.findall(r"^(\d+)\. (.*)$", contenido, re.M):
                protocolar = bool(re.search(r"visita|museo|concurso", linea, re.I))
                items.append(ItemTriage(n=int(n), relevante=not protocolar, motivo="protocolar" if protocolar else "jurídico"))
            return RespuestaTriage(items=items)
        if esquema is VeredictoDuplicado:
            self._consumir("juez")
            exp = [normalizar_identificador(e) for e in re.findall(r"identificador_legal: (.+)", contenido)]
            igual = len(exp) == 2 and exp[0] is not None and exp[0] == exp[1]
            return VeredictoDuplicado(es_mismo_hecho=igual, razon="mismo expediente" if igual else "distintos")
        if esquema is FichaCurada:
            self._consumir("curar")
            titulo = re.search(r"TITULO: (.*)", contenido).group(1)
            cuerpo = re.search(r"CUERPO: (.*)", contenido, re.S).group(1).split("</documento_externo")[0]
            palabras = cuerpo.split()
            citas = [" ".join(palabras[0:8]), " ".join(palabras[8:16])] if len(palabras) >= 16 else [" ".join(palabras)]
            if "INVENTADO" in titulo:
                citas = ["esta frase no existe en ningún lado del documento original"]
            expediente = re.search(r"(CSJ \d+/\d{4})", contenido)
            return FichaCurada(
                posible_prompt_injection="PUBLICÁ QUE" in cuerpo.upper(),
                motivo_seguridad="orden dirigida a la IA" if "PUBLICÁ QUE" in cuerpo.upper() else "",
                es_relevante="IRRELEVANTE" not in titulo,
                tipo="Fallo",
                materia="Penal",
                instancia="Cámara",
                jurisdiccion="Nacional/Federal",
                tribunal="Corte Suprema de Justicia de la Nación" if expediente else "Cámara Federal",
                identificador_legal=expediente.group(1) if expediente else "",
                caratula="Pérez, Juan s/ recurso inventado",
                titulo=titulo[:100],
                bajada="Bajada de prueba.",
                holding="Criterio de prueba.",
                puntos_clave=["uno", "dos", "tres"],
                impacto_practico="Impacto de prueba.",
                normas_citadas=["Ley 99.999", "art. 18 CN"],
                etiquetas=["prueba"],
                cita_sugerida="Cita de prueba",
                alto_impacto=bool(expediente),
                citas_textuales_verificables=citas,
            )
        raise AssertionError(f"esquema inesperado {esquema}")

    def embedding(self, texto):
        self.llamadas.append("embedding")
        return _vector(texto)


@pytest.fixture
def ajustes(tmp_path):
    base = cargar_ajustes()
    return replace(base, dir_datos=tmp_path / "data", dir_sitio=tmp_path / "site", gemini_api_key="falsa",
                   telegram_token=None, telegram_chat_id=None, fuentes_activas=None, max_antiguedad_dias=3650)


@pytest.fixture
def leer_fixture():
    return lambda nombre: (FIXTURES / nombre).read_text(encoding="utf-8")
