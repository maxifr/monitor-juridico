"""Alertas opcionales por Telegram (gratis): novedades de alto impacto y fuentes caídas.

Se activa definiendo TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID. Si no están, no hace nada.
"""

from __future__ import annotations

import logging
from html import escape

import httpx

from .almacen import Almacen
from .config import Ajustes

log = logging.getLogger(__name__)

MAX_ALERTAS = 6
UMBRAL_FALLAS = 3


def _enviar(ajustes: Ajustes, texto: str) -> None:
    try:
        httpx.post(
            f"https://api.telegram.org/bot{ajustes.telegram_token}/sendMessage",
            json={"chat_id": ajustes.telegram_chat_id, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        ).raise_for_status()
    except httpx.HTTPError as exc:
        # No se loguea el mensaje completo: la URL contiene el token del bot.
        estado = getattr(getattr(exc, "response", None), "status_code", "sin respuesta")
        log.warning("No se pudo enviar la alerta de Telegram (%s, %s)", type(exc).__name__, estado)


def notificar(ajustes: Ajustes, almacen: Almacen, nuevas_ids: list[str]) -> int:
    if not (ajustes.telegram_token and ajustes.telegram_chat_id):
        return 0
    enviadas = 0
    destacadas = [almacen.novedades[i] for i in nuevas_ids if i in almacen.novedades and almacen.novedades[i].get("alto_impacto")]
    for rec in destacadas[:MAX_ALERTAS]:
        enlace = f"{ajustes.portal_url}/#/n/{rec['id']}" if ajustes.portal_url else rec["url"]
        texto = (
            f"⚖️ <b>{escape(rec.get('titulo', ''))}</b>\n"
            f"<i>{escape(rec.get('tribunal') or rec.get('fuente_nombre', ''))} · {escape(rec.get('materia', ''))}</i>\n\n"
            f"{escape(rec.get('bajada', ''))}\n\n"
            f'<a href="{escape(enlace, quote=True)}">Ver ficha</a> · <a href="{escape(rec["url"], quote=True)}">Fuente</a>'
        )
        _enviar(ajustes, texto)
        enviadas += 1
    for clave, info in almacen.salud.items():
        if int(info.get("fallas_consecutivas", 0)) == UMBRAL_FALLAS:
            _enviar(ajustes, f"⚠️ La fuente <b>{escape(clave)}</b> falló {UMBRAL_FALLAS} corridas seguidas: "
                             f"{escape(str(info.get('ultimo_error', 'sin resultados')))[:200]}")
            enviadas += 1
    return enviadas
