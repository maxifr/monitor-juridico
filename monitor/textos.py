"""Utilidades de texto: normalización sin tildes, tokens, similitud léxica y fechas."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Argentina no tiene horario de verano desde 2009: UTC-3 fijo evita depender de tzdata.
ZONA_AR = timezone(timedelta(hours=-3), "ART")

_ESPACIOS = re.compile(r"\s+")
_NO_ALNUM = re.compile(r"[^a-z0-9]+")

PALABRAS_VACIAS = frozenset(
    """a al ante bajo con contra de del desde durante e el en entre hacia hasta la las le les lo los
    mediante para por que se sin sobre su sus tras un una unos unas y o u ni es son fue ser ha han
    como mas pero sus este esta estos estas ese esa eso aquel muy ya no si sí tambien también cual
    cuando donde quien quienes""".split()
)


def limpiar_espacios(texto: str | None) -> str:
    return _ESPACIOS.sub(" ", texto or "").strip()


def sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes ni signos: base para comparar textos de forma robusta."""
    base = sin_tildes((texto or "").lower())
    return _ESPACIOS.sub(" ", _NO_ALNUM.sub(" ", base)).strip()


def recortar(texto: str | None, maximo: int) -> str:
    texto = limpiar_espacios(texto)
    if len(texto) <= maximo:
        return texto
    corte = texto[: maximo - 1].rsplit(" ", 1)[0]
    return corte.rstrip(",;:.-") + "…"


def tokens(texto: str | None) -> set[str]:
    return {t for t in normalizar(texto).split() if len(t) > 2 and t not in PALABRAS_VACIAS}


def jaccard(a: str | None, b: str | None) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def contiene_normalizado(fuente: str, fragmento: str) -> bool:
    nf = normalizar(fragmento)
    return bool(nf) and nf in normalizar(fuente)


# --------------------------------------------------------------------------- fechas

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def parsear_fecha(valor: str | None) -> datetime | None:
    """Acepta ISO 8601, RFC 822 (RSS), dd/mm/aaaa, dd.mm.aaaa, aaaammdd y '20 de noviembre de 2026'."""
    if not valor:
        return None
    valor = limpiar_espacios(str(valor))
    # ISO 8601
    try:
        iso = valor.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=ZONA_AR)
    except ValueError:
        pass
    # RFC 822 (feeds RSS)
    try:
        dt = parsedate_to_datetime(valor)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b", valor)
    if m:
        d, mes, a = (int(x) for x in m.groups())
        try:
            return datetime(a, mes, d, 12, 0, tzinfo=ZONA_AR)
        except ValueError:
            return None
    m = re.search(r"\b(20\d{2})(\d{2})(\d{2})\b", valor)
    if m:
        a, mes, d = (int(x) for x in m.groups())
        try:
            return datetime(a, mes, d, 12, 0, tzinfo=ZONA_AR)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})-([a-z]{3})-(\d{4})\b", sin_tildes(valor.lower()))  # InfoLeg: 09-mar-2026
    if m:
        mes = next((n for nombre, n in _MESES.items() if nombre.startswith(m.group(2))), None)
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(1)), 12, 0, tzinfo=ZONA_AR)
            except ValueError:
                return None
    m = re.search(r"\b(\d{1,2}) de ([a-záéíóú]+) de (\d{4})\b", sin_tildes(valor.lower()))
    if m and m.group(2) in _MESES:
        try:
            return datetime(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)), 12, 0, tzinfo=ZONA_AR)
        except ValueError:
            return None
    return None


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def a_iso(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    return dt.isoformat()


def desde_iso(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
