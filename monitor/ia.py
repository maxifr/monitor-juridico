"""Cliente de IA pensado para el plan gratuito de Gemini (Google AI Studio).

- Autodetecta el modelo: consulta qué modelos habilita la clave y toma el primero de la
  lista de preferencias (los nombres cambian seguido; los Gemini 2.5 ya no se habilitan
  para proyectos nuevos). Se puede forzar con GEMINI_MODELO.
- Respeta el límite por minuto (pausa entre llamadas) y lleva la cuenta diaria en
  data/uso_ia.json para frenar antes de agotar la cuota (se reinicia 00:00 hora del Pacífico).
- Ante 429 reintenta con espera; si la cuota diaria se agotó, pasa al siguiente modelo y,
  si no queda ninguno, lanza SinCuota: el pipeline guarda lo que falta para la próxima corrida.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .almacen import Almacen
from .config import Ajustes

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class SinCuota(RuntimeError):
    """No queda cuota de IA disponible para esta corrida."""


class ErrorIA(RuntimeError):
    pass


class ClienteIA(Protocol):
    modelo_texto: str

    def generar(self, *, sistema: str, contenido: str, esquema: type[T], temperatura: float = 0.1) -> T: ...

    def embedding(self, texto: str) -> list[float] | None: ...


def dia_pacifico(momento: datetime | None = None) -> str:
    """Las cuotas diarias de Gemini se reinician a medianoche del Pacífico."""
    momento = momento or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        return momento.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:  # sin base de zonas horarias: aproximación UTC-8
        return (momento - timedelta(hours=8)).strftime("%Y-%m-%d")


def _codigo(exc: Exception) -> int | None:
    for atributo in ("code", "status_code"):
        valor = getattr(exc, atributo, None)
        if isinstance(valor, int):
            return valor
    return None


def _filtros_permisivos(types) -> list:
    """Las sentencias penales describen delitos (abusos, homicidios, drogas): que el filtro de
    seguridad de Gemini no corte la respuesta por el contenido fáctico de un fallo."""
    ajustes = []
    for nombre in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                   "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"):
        try:
            ajustes.append(types.SafetySetting(category=getattr(types.HarmCategory, nombre),
                                               threshold=types.HarmBlockThreshold.BLOCK_NONE))
        except Exception:  # SDK sin esa categoría: se usa el valor por defecto
            continue
    return ajustes


def _motivo_fin(resp) -> str:
    """finish_reason / block_reason de una respuesta vacía (SAFETY, RECITATION, MAX_TOKENS…)."""
    try:
        bloqueo = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
        if bloqueo:
            return f"prompt bloqueado: {bloqueo}"
        candidatos = getattr(resp, "candidates", None) or []
        if candidatos:
            return str(getattr(candidatos[0], "finish_reason", "") or "")
    except Exception:
        pass
    return ""


def _es_cuota_diaria(exc: Exception) -> bool:
    texto = str(exc).lower()
    return "perday" in texto.replace(" ", "") or "per day" in texto or "daily" in texto or "requests_per_day" in texto


class ClienteGemini:
    def __init__(self, ajustes: Ajustes, almacen: Almacen) -> None:
        if not ajustes.gemini_api_key:
            raise ErrorIA("Falta GEMINI_API_KEY (creala gratis en https://aistudio.google.com/apikey).")
        from google import genai  # import diferido: el resto del sistema funciona sin el SDK

        self._genai = genai
        self._cliente = genai.Client(api_key=ajustes.gemini_api_key)
        self.ajustes = ajustes
        self.almacen = almacen
        self._ultimo: dict[str, float] = {}
        self._agotados: set[str] = set()
        disponibles = self._modelos_disponibles()
        self._cadena_texto = self._elegir(ajustes.modelo_texto, ajustes.modelos_texto_preferidos, disponibles, "flash")
        self._cadena_embed = self._elegir(
            ajustes.modelo_embeddings, ajustes.modelos_embedding_preferidos, disponibles, "embedding"
        )
        log.info("IA: texto=%s | embeddings=%s", self._cadena_texto, self._cadena_embed)

    # ------------------------------------------------------------------ modelos
    def _modelos_disponibles(self) -> set[str]:
        nombres: set[str] = set()
        try:
            for modelo in self._cliente.models.list():
                nombre = (getattr(modelo, "name", "") or "").removeprefix("models/")
                if nombre:
                    nombres.add(nombre)
        except Exception as exc:  # sin listado: se confía en la lista de preferencias
            log.warning("No se pudo listar modelos (%s); se usan los preferidos.", exc)
        return nombres

    @staticmethod
    def _elegir(forzado: str | None, preferidos: tuple[str, ...], disponibles: set[str], familia: str) -> list[str]:
        if forzado:
            return [forzado] + [m for m in preferidos if m != forzado and (not disponibles or m in disponibles)]
        if not disponibles:
            return list(preferidos)
        cadena = [m for m in preferidos if m in disponibles]
        if not cadena:  # ninguno de los conocidos: el más parecido que exista
            similares = sorted(
                (m for m in disponibles if familia in m and "preview" not in m and "image" not in m and "tts" not in m),
                key=lambda m: ("lite" not in m, m),
            )
            cadena = similares[:3]
        if not cadena:
            raise ErrorIA(f"Tu clave no habilita ningún modelo '{familia}'. Revisá Google AI Studio.")
        return cadena

    @property
    def modelo_texto(self) -> str:
        vivos = [m for m in self._cadena_texto if m not in self._agotados]
        return vivos[0] if vivos else self._cadena_texto[-1]

    # ------------------------------------------------------------------ control de cuota
    def _turno(self, modelo: str, rpm: int) -> None:
        intervalo = 60.0 / max(rpm, 1)
        anterior = self._ultimo.get(modelo)
        if anterior is not None:
            espera = intervalo - (time.monotonic() - anterior)
            if espera > 0:
                time.sleep(espera)
        self._ultimo[modelo] = time.monotonic()

    def _verificar_presupuesto(self, tipo: str) -> None:
        dia = dia_pacifico()
        if tipo == "texto" and self.almacen.uso(dia, "texto") >= self.ajustes.max_llamadas_dia:
            raise SinCuota(f"Se alcanzó el tope diario configurado ({self.ajustes.max_llamadas_dia} llamadas).")
        if tipo == "embedding" and self.almacen.uso(dia, "embedding") >= self.ajustes.max_embeddings_dia:
            raise SinCuota("Se alcanzó el tope diario de embeddings.")

    # ------------------------------------------------------------------ texto
    def _contar(self, clave: str) -> None:
        self.almacen.contar_uso(dia_pacifico(), clave)

    def generar(self, *, sistema: str, contenido: str, esquema: type[T], temperatura: float = 0.1) -> T:
        from google.genai import types

        tarea = esquema.__name__  # RespuestaTriage, FichaCurada, VeredictoDuplicado
        filtros = _filtros_permisivos(types)
        saturado: Exception | None = None
        for modelo in [m for m in self._cadena_texto if m not in self._agotados]:
            for intento in range(3):
                self._verificar_presupuesto("texto")
                self._turno(modelo, self.ajustes.rpm_texto)
                self._contar(f"tarea:{tarea}" if intento == 0 else f"reintento:{tarea}")
                try:
                    resp = self._cliente.models.generate_content(
                        model=modelo,
                        contents=contenido,
                        config=types.GenerateContentConfig(
                            system_instruction=sistema,
                            response_mime_type="application/json",
                            response_schema=esquema,
                            temperature=temperatura,
                            **({"safety_settings": filtros} if filtros else {}),
                        ),
                    )
                except Exception as exc:
                    codigo = _codigo(exc)
                    self._contar(f"error:{codigo or type(exc).__name__}")
                    if codigo == 429:
                        if _es_cuota_diaria(exc) or intento == 2:
                            log.warning("Cuota agotada en %s: paso al siguiente modelo.", modelo)
                            self._agotados.add(modelo)
                            break
                        time.sleep(20 * (intento + 1))
                        continue
                    if codigo in (500, 502, 503, 504):
                        if intento < 2:
                            time.sleep(10 * (intento + 1))
                            continue
                        # Modelo saturado: se prueba el siguiente de la cadena para esta pieza.
                        log.warning("%s saturado (%s): pruebo el siguiente modelo.", modelo, codigo)
                        saturado = exc
                        break
                    if codigo == 404:  # modelo retirado
                        self._agotados.add(modelo)
                        break
                    raise ErrorIA(f"{modelo}: {exc}") from exc
                finally:
                    self.almacen.contar_uso(dia_pacifico(), "texto")
                    self.almacen.contar_uso(dia_pacifico(), modelo)
                parsed = getattr(resp, "parsed", None)
                if isinstance(parsed, esquema):
                    return parsed
                try:  # algunos modelos devuelven el JSON sin parsear
                    return esquema.model_validate_json(resp.text or "")
                except Exception as exc:
                    motivo = _motivo_fin(resp)
                    self._contar(f"vacia:{motivo or 'json_invalido'}")
                    if motivo and any(m in motivo.upper() for m in ("SAFETY", "BLOCK", "PROHIBITED", "RECITATION")):
                        # Reintentar no cambia un bloqueo: se informa con el motivo y sigue la corrida.
                        raise ErrorIA(f"{modelo} no respondió ({motivo})") from exc
                    if intento < 2:
                        continue
                    raise ErrorIA(f"{modelo} devolvió un JSON inválido ({motivo or 'sin motivo'})") from exc
        if saturado is not None:
            raise ErrorIA(f"Todos los modelos están saturados: {saturado}")
        raise SinCuota("No queda cuota en ningún modelo de texto disponible.")

    # ------------------------------------------------------------------ embeddings
    def embedding(self, texto: str) -> list[float] | None:
        from google.genai import types

        for modelo in [m for m in self._cadena_embed if m not in self._agotados]:
            for intento in range(3):
                try:
                    self._verificar_presupuesto("embedding")
                except SinCuota:
                    return None
                self._turno(modelo, self.ajustes.rpm_embeddings)
                try:
                    resp = self._cliente.models.embed_content(
                        model=modelo,
                        contents=texto[:6000],
                        config=types.EmbedContentConfig(
                            task_type="SEMANTIC_SIMILARITY",
                            output_dimensionality=self.ajustes.dimension_embeddings,
                        ),
                    )
                    self.almacen.contar_uso(dia_pacifico(), "embedding")
                    return list(resp.embeddings[0].values)
                except Exception as exc:
                    self.almacen.contar_uso(dia_pacifico(), "embedding")
                    codigo = _codigo(exc)
                    if codigo == 429 and not _es_cuota_diaria(exc) and intento < 2:
                        time.sleep(15 * (intento + 1))
                        continue
                    if codigo in (500, 502, 503, 504) and intento < 2:
                        time.sleep(8)
                        continue
                    log.warning("Embedding no disponible en %s: %s", modelo, exc)
                    self._agotados.add(modelo)
                    break
        return None  # la deduplicación cae al modo léxico
