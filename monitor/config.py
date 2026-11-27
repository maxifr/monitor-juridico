"""Configuración centralizada: variables de entorno con valores por defecto sensatos.

Todo lo que puede cambiar sin tocar código vive acá. Los valores por defecto están
pensados para entrar holgados en el plan gratuito de Gemini (Google AI Studio).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Modelos preferidos, en orden. El cliente consulta qué modelos habilita tu clave y
# usa el primero disponible; si Google renombra o retira alguno, cae al siguiente.
# Los "Flash-Lite" tienen la cuota gratuita diaria más amplia.
MODELOS_TEXTO_PREFERIDOS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
)
MODELOS_EMBEDDING_PREFERIDOS = ("gemini-embedding-001", "gemini-embedding-2")


def _env(nombre: str, defecto: str | None = None) -> str | None:
    valor = os.getenv(nombre)
    if valor is None:
        return defecto
    valor = valor.strip()
    return valor if valor else defecto


def _int(nombre: str, defecto: int) -> int:
    try:
        return int(_env(nombre, str(defecto)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defecto


def _float(nombre: str, defecto: float) -> float:
    try:
        return float(_env(nombre, str(defecto)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defecto


def _lista(nombre: str) -> tuple[str, ...] | None:
    valor = _env(nombre)
    if not valor:
        return None
    return tuple(p.strip() for p in valor.split(",") if p.strip())


@dataclass(frozen=True)
class Ajustes:
    dir_datos: Path
    dir_sitio: Path
    # IA
    gemini_api_key: str | None
    modelo_texto: str | None
    modelos_texto_preferidos: tuple[str, ...]
    modelo_embeddings: str | None
    modelos_embedding_preferidos: tuple[str, ...]
    dimension_embeddings: int
    rpm_texto: int
    rpm_embeddings: int
    max_llamadas_dia: int
    max_embeddings_dia: int
    max_curadas_por_corrida: int
    cupo_minimo_fuente: int
    max_detalles_previos_fuente: int
    perfil_editorial: str
    # Deduplicación
    ventana_dedup_dias: int
    umbral_gris: float
    umbral_auto: float
    # Recolección
    fuentes_activas: tuple[str, ...] | None
    max_candidatos_fuente: int
    max_antiguedad_dias: int
    ia_plan_pago: bool
    # Publicación
    dias_portada: int
    portal_nombre: str
    portal_descripcion: str
    portal_url: str
    # Alertas opcionales
    telegram_token: str | None
    telegram_chat_id: str | None


def cargar_ajustes() -> Ajustes:
    """Lee la configuración del entorno (y de un archivo .env si existe)."""
    try:  # .env es opcional: en GitHub Actions se usan Secrets
        from dotenv import load_dotenv

        load_dotenv(RAIZ / ".env")
    except ImportError:  # pragma: no cover
        pass

    return Ajustes(
        dir_datos=Path(_env("MONITOR_DIR_DATOS", str(RAIZ / "data"))),  # type: ignore[arg-type]
        dir_sitio=Path(_env("MONITOR_DIR_SITIO", str(RAIZ / "site"))),  # type: ignore[arg-type]
        gemini_api_key=_env("GEMINI_API_KEY"),
        modelo_texto=_env("GEMINI_MODELO"),
        modelos_texto_preferidos=_lista("GEMINI_MODELOS_PREFERIDOS") or MODELOS_TEXTO_PREFERIDOS,
        modelo_embeddings=_env("GEMINI_MODELO_EMBEDDINGS"),
        modelos_embedding_preferidos=MODELOS_EMBEDDING_PREFERIDOS,
        dimension_embeddings=_int("GEMINI_DIMENSION_EMBEDDINGS", 768),
        rpm_texto=_int("GEMINI_RPM", 8),
        rpm_embeddings=_int("GEMINI_RPM_EMBEDDINGS", 60),
        max_llamadas_dia=_int("GEMINI_MAX_LLAMADAS_DIA", 400),
        max_embeddings_dia=_int("GEMINI_MAX_EMBEDDINGS_DIA", 800),
        max_curadas_por_corrida=_int("MAX_CURADAS_POR_CORRIDA", 60),
        # Lugares reservados por corrida para cada fuente con material en espera, para que las
        # fuentes de prioridad baja (medios) no queden siempre detrás de las oficiales.
        cupo_minimo_fuente=_int("CUPO_MINIMO_FUENTE", 5),
        # Notas que se leen completas antes del triage, por fuente (sólo descarga HTTP, sin IA).
        max_detalles_previos_fuente=_int("MAX_DETALLES_PREVIOS_FUENTE", 25),
        perfil_editorial=_env("PERFIL_EDITORIAL", "") or "",
        ventana_dedup_dias=_int("VENTANA_DEDUP_DIAS", 21),
        umbral_gris=_float("UMBRAL_SIMILITUD", 0.80),
        umbral_auto=_float("UMBRAL_SIMILITUD_AUTO", 0.95),
        fuentes_activas=_lista("FUENTES_ACTIVAS"),
        max_candidatos_fuente=_int("MAX_CANDIDATOS_POR_FUENTE", 20),
        max_antiguedad_dias=_int("MAX_ANTIGUEDAD_DIAS", 30),
        # En el plan gratuito Google puede usar lo enviado para mejorar sus productos: con
        # IA_PLAN_PAGO=0 se respeta "ai-train=no" y de esas fuentes sólo viaja título y bajada.
        ia_plan_pago=(_env("IA_PLAN_PAGO", "0") or "0").lower() in ("1", "true", "si", "sí", "yes"),
        dias_portada=_int("DIAS_PORTADA", 45),
        portal_nombre=_env("PORTAL_NOMBRE", "Monitor Jurídico AR") or "Monitor Jurídico AR",
        portal_descripcion=_env(
            "PORTAL_DESCRIPCION",
            "Novedades jurídicas y judiciales de la Argentina, curadas con IA y verificadas contra la fuente.",
        )
        or "",
        portal_url=(_env("PORTAL_URL", "") or "").rstrip("/"),
        telegram_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
    )
