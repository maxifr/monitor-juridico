"""Lectura del texto de sentencias adjuntas en PDF (Diario Judicial, Pensamiento Penal, etc.).

Muchas notas de medios jurídicos traen dos párrafos y el fallo completo en un PDF o en un
visor pdf.js. Este módulo encuentra el enlace al PDF y extrae su texto, con topes de páginas
y de caracteres para no exceder la cuota de la IA. Los PDF escaneados (imágenes) no tienen
texto: se devuelve cadena vacía y la nota se procesa igual.
"""

from __future__ import annotations

import io
import logging
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .seguridad import texto_plano_seguro

log = logging.getLogger(__name__)

MAX_PAGINAS = 15
MAX_CARACTERES = 10000


def buscar_pdf(html: str, url_base: str, patron: str) -> str:
    """Primer PDF de la página cuya URL cumple `patron` (enlace directo o visor pdf.js)."""
    if not patron:
        return ""
    regex = re.compile(patron, re.IGNORECASE)
    sopa = BeautifulSoup(html or "", "lxml")
    candidatos: list[str] = []
    for iframe in sopa.find_all("iframe", src=True):
        src = iframe["src"]
        archivo = parse_qs(urlsplit(src).query).get("file", [""])[0]
        if archivo:
            candidatos.append(unquote(archivo))
        elif ".pdf" in src.lower():
            candidatos.append(src)
    for enlace in sopa.find_all("a", href=True):
        candidatos.append(enlace["href"])
    for crudo in candidatos:
        absoluta = urljoin(url_base, crudo.strip())
        if regex.search(absoluta):
            return absoluta.split("#")[0]
    return ""


def texto_de_pdf(contenido: bytes, max_paginas: int = MAX_PAGINAS, max_caracteres: int = MAX_CARACTERES) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        log.warning("Falta pypdf (pip install pypdf): no se leen los PDF adjuntos.")
        return ""
    try:
        lector = PdfReader(io.BytesIO(contenido))
        partes: list[str] = []
        total = 0
        for pagina in lector.pages[:max_paginas]:
            texto = pagina.extract_text() or ""
            partes.append(texto)
            total += len(texto)
            if total >= max_caracteres:
                break
    except Exception as exc:  # PDF dañado o cifrado
        log.warning("PDF ilegible: %s", exc)
        return ""
    # Une palabras cortadas con guion al final de renglón y normaliza espacios.
    unido = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", "\n".join(partes))
    return texto_plano_seguro(unido)[:max_caracteres]
