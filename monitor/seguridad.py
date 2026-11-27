"""Defensa en profundidad contra prompt injection y alucinaciones.

Capas que actúan ANTES y DESPUÉS del modelo:

1. Saneamiento: sólo llega a la IA el texto visible de la página (se eliminan scripts,
   comentarios, nodos ocultos por CSS/atributos y caracteres Unicode invisibles).
2. Allowlist de dominios: sólo se procesan URLs de las fuentes registradas.
3. Escáner heurístico con niveles: "alto" (órdenes dirigidas a una IA, etiquetas de
   rol, texto oculto con instrucciones) va directo a cuarentena; "medio" (menciones
   que pueden ser legítimas, como una nota sobre IA) pasa al curador con aviso.
4. Verificación determinista de citas (grounding): las citas literales que devuelve la
   IA tienen que existir en el texto descargado.
5. Saneamiento de la salida: se descartan carátulas, expedientes y normas que no
   aparecen en la fuente, se eliminan etiquetas HTML y URLs, y se vuelve a escanear el
   resultado por si la IA "repitió" una instrucción inyectada.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment

from .textos import contiene_normalizado, limpiar_espacios, normalizar

# --------------------------------------------------------------------------- 1. saneamiento

_INVISIBLES = {
    "​", "‌", "‍", "‎", "‏", "⁠", "⁡", "⁢",
    "⁣", "⁤", "﻿", "­", "᠎", "‪", "‫", "‬",
    "‭", "‮", "⁦", "⁧", "⁨", "⁩",
}

_ESTILO_OCULTO = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0+)?\s*(;|$)|"
    r"font-size\s*:\s*0(px|pt|em|rem|%)?\s*(;|$)|color\s*:\s*transparent|"
    r"text-indent\s*:\s*-\d{3,}|left\s*:\s*-\d{4,}px|clip\s*:\s*rect\(0|"
    r"(height|width)\s*:\s*0(px)?\s*;\s*overflow\s*:\s*hidden)",
    re.IGNORECASE,
)
_CLASES_OCULTAS = re.compile(r"(?<![\w-])(sr-only|visually-hidden|screen-reader-text|hidden|invisible)(?![\w-])", re.I)
_CLASE_VISIBLE_RESPONSIVA = re.compile(r"(?<![\w-])d-(sm|md|lg|xl|xxl)-(block|flex|inline|inline-block|grid|table)(?![\w-])")


def _clases_ocultan(clases: str) -> bool:
    if _CLASES_OCULTAS.search(clases):
        return True
    # "d-none" sólo cuenta como oculto si no se muestra en otra resolución (Bootstrap).
    return bool(re.search(r"(?<![\w-])d-none(?![\w-])", clases)) and not _CLASE_VISIBLE_RESPONSIVA.search(clases)


def limpiar_unicode_invisible(texto: str) -> str:
    """Quita caracteres de ancho cero, marcas bidi y el bloque Unicode Tags (U+E0000–E007F)."""
    salida = []
    for ch in texto:
        codigo = ord(ch)
        if 0xE0000 <= codigo <= 0xE007F or ch in _INVISIBLES:
            continue
        if unicodedata.category(ch) == "Co":  # uso privado
            continue
        salida.append(ch)
    return "".join(salida)


@dataclass
class TextoSaneado:
    texto: str
    nodos_ocultos: int = 0
    texto_oculto: str = ""  # muestra de lo eliminado, para auditar en cuarentena


def html_a_texto_seguro(html: str | None) -> TextoSaneado:
    """Extrae únicamente el texto visible; registra lo que estaba oculto."""
    sopa = BeautifulSoup(html or "", "lxml")
    for comentario in sopa.find_all(string=lambda t: isinstance(t, Comment)):
        comentario.extract()
    for etiqueta in sopa(["script", "style", "noscript", "iframe", "svg", "template", "meta", "link", "object", "embed"]):
        etiqueta.decompose()

    ocultos: list[str] = []
    for el in list(sopa.find_all(True)):
        if getattr(el, "decomposed", False):
            continue
        try:
            estilo = el.get("style") or ""
            clases = " ".join(el.get("class") or [])
            oculto = (
                el.has_attr("hidden")
                or el.get("aria-hidden") == "true"
                or (estilo and _ESTILO_OCULTO.search(estilo))
                or (clases and _clases_ocultan(clases))
            )
        except AttributeError:  # nodo ya eliminado junto con su padre
            continue
        if oculto:
            contenido = el.get_text(" ", strip=True)
            if contenido:
                ocultos.append(contenido)
            el.decompose()

    texto = limpiar_unicode_invisible(sopa.get_text(" ", strip=True))
    return TextoSaneado(
        texto=limpiar_espacios(texto),
        nodos_ocultos=len(ocultos),
        texto_oculto=limpiar_espacios(" | ".join(ocultos))[:1500],
    )


def texto_plano_seguro(texto: str | None) -> str:
    """Para textos que ya vienen sin HTML (JSON, RSS): quita invisibles y espacios."""
    if texto and "<" in texto and ">" in texto:
        return html_a_texto_seguro(texto).texto
    return limpiar_espacios(limpiar_unicode_invisible(texto or ""))


# --------------------------------------------------------------------------- 2. dominios


def dominio_permitido(url: str, dominios: set[str] | frozenset[str]) -> bool:
    try:
        partes = urlsplit(url)
    except ValueError:
        return False
    if partes.scheme not in ("http", "https"):
        return False
    host = (partes.hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in dominios)


# --------------------------------------------------------------------------- 3. heurística

_PATRONES_ALTOS = [
    r"ignor(a|á|e|en|ad|ar)\s+(todas?\s+)?(las\s+|tus\s+|sus\s+)?(instrucciones|indicaciones|reglas|ordenes|órdenes)\s+(anteriores|previas|del\s+sistema|recibidas)",
    r"olvid(a|á|e|ate|ate)\s+(todo\s+lo\s+anterior|tus\s+instrucciones|las\s+instrucciones)",
    r"(a\s+partir\s+de\s+ahora|desde\s+ahora)\s*,?\s+(sos|eres|actu(a|á)s?|respond(e|é)s?)\b",
    r"actu(a|á)\s+como\s+(si\s+fueras\s+)?(un\s+)?(modelo|asistente|ia)\s+(sin\s+restricciones|liberad)",
    r"(nuevas|estas\s+son\s+tus)\s+instrucciones\s*:",
    r"(devolv|respond|public|escrib)(e|é|á|i|í)\s+(exactamente|únicamente|unicamente|solamente|solo|sólo)\s+(el\s+siguiente|lo\s+siguiente|este)\s+(json|texto|titular|resultado)",
    r"\bignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
    r"\bdisregard\s+(all\s+|the\s+)?(previous|prior|above)\b",
    r"\byou\s+are\s+now\s+(a|an|the|in)\b",
    r"\bnew\s+instructions\s*:",
    r"\b(respond|reply|answer|output)\s+(only|exclusively)\s+with\b",
    r"\bact\s+as\s+(an?\s+)?(unrestricted|jailbroken|dan)\b",
    r"<\s*/?\s*(system|assistant|tool_call|tool|instructions?|im_start|im_end)\s*>",
    r"<\|\s*(im_start|im_end|system|endoftext)\s*\|>",
    r"\[/?INST\]",
    r"(^|\s)#{2,}\s*(instruction|system|instrucciones)\b",
    r"(es_relevante|posible_prompt_injection|alto_impacto)\s*[:=]\s*(true|false)",
    r"\b(modelo|asistente|inteligencia\s+artificial|ia|llm|chatgpt|gemini|claude|ai)\b[^.\n]{0,60}\b(deb(e|és|es)|tenés\s+que|tienes\s+que|must|should)\s+(ignorar|publicar|responder|clasificar|marcar|ignore|output|mark)\b",
]
_PATRONES_MEDIOS = [
    r"\bsystem\s*prompt\b",
    r"\bprompt\s+injection\b",
    r"\binyecci(o|ó)n\s+de\s+(prompt|instrucciones)\b",
    r"\bjailbreak\b",
    r"\binstrucciones\s+del\s+sistema\b",
]
_RE_ALTOS = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _PATRONES_ALTOS]
_RE_MEDIOS = [re.compile(p, re.IGNORECASE) for p in _PATRONES_MEDIOS]


@dataclass
class Riesgo:
    nivel: str = "ninguno"  # "ninguno" | "medio" | "alto"
    motivos: list[str] = field(default_factory=list)

    @property
    def bloquear(self) -> bool:
        return self.nivel == "alto"


def escanear_inyeccion(texto: str, texto_oculto: str = "") -> Riesgo:
    """Clasifica el riesgo antes de gastar cuota de IA."""
    riesgo = Riesgo()
    plano = limpiar_unicode_invisible(texto or "")
    for patron in _RE_ALTOS:
        m = patron.search(plano)
        if m:
            riesgo.nivel = "alto"
            riesgo.motivos.append(f"Patrón de instrucción dirigida a IA: «{m.group(0)[:80]}»")
            return riesgo
    if texto_oculto:
        for patron in _RE_ALTOS + _RE_MEDIOS:
            m = patron.search(texto_oculto)
            if m:
                riesgo.nivel = "alto"
                riesgo.motivos.append(f"Texto oculto con instrucciones: «{m.group(0)[:80]}»")
                return riesgo
    for patron in _RE_MEDIOS:
        m = patron.search(plano)
        if m:
            riesgo.nivel = "medio"
            riesgo.motivos.append(f"Mención sensible (puede ser legítima): «{m.group(0)[:60]}»")
    return riesgo


# --------------------------------------------------------------------------- 4. grounding


@dataclass
class ResultadoAnclaje:
    ok: bool
    verificadas: int
    total: int
    detalle: str = ""
    citas_ok: list[str] = field(default_factory=list)  # exactas o casi exactas
    citas_literales: list[str] = field(default_factory=list)  # copias exactas (se pueden mostrar)


# Abreviaturas que la IA suele expandir (o abreviar) al copiar una cita.
_EQUIVALENCIAS = {
    "art": "articulo", "arts": "articulos", "inc": "inciso", "incs": "incisos", "fs": "fojas",
    "fs.": "fojas", "dr": "doctor", "dra": "doctora", "dres": "doctores", "sr": "senor", "sra": "senora",
    "nro": "numero", "num": "numero", "pag": "pagina", "cn": "constitucion nacional", "cp": "codigo penal",
    "cpp": "codigo procesal penal", "csjn": "corte suprema de justicia de la nacion",
}
UMBRAL_CASI_LITERAL = 0.90


def _tokens_cita(texto: str) -> list[str]:
    salida: list[str] = []
    for t in normalizar(texto).split():
        salida.extend(_EQUIVALENCIAS.get(t, t).split())
    return salida


def _casi_literal(cita: list[str], fuente: list[str], indice: dict[str, list[int]]) -> bool:
    """La cita aparece en la fuente con diferencias mínimas (una palabra corregida, un signo, etc.)."""
    n = len(cita)
    if n < 4:
        return False
    inicios: set[int] = set()
    for pos, tok in enumerate(cita[:4] + cita[-4:]):
        desplazamiento = pos if pos < 4 else n - (8 - pos)
        for i in indice.get(tok, ()):
            inicio = i - desplazamiento
            if 0 <= inicio <= len(fuente) - max(1, n - 2):
                inicios.add(inicio)
    for inicio in inicios:
        for largo in (n, n - 1, n + 1):
            ventana = fuente[inicio: inicio + largo]
            if ventana and SequenceMatcher(None, cita, ventana, autojunk=False).ratio() >= UMBRAL_CASI_LITERAL:
                return True
    return False


def verificar_anclaje(texto_fuente: str, citas: list[str], minimo: int = 2) -> ResultadoAnclaje:
    """Cada cita (≥ 4 palabras) tiene que existir en la fuente: literal (normalizada) o casi literal.

    Casi literal = misma secuencia de palabras con un 90 % de coincidencia, después de equiparar
    abreviaturas ("art." = "artículo"). Cubre los retoques típicos del modelo (corrige una errata,
    expande una abreviatura) sin aceptar paráfrasis.
    """
    utiles = [c for c in (citas or []) if len(normalizar(c).split()) >= 4]
    if not utiles:
        return ResultadoAnclaje(False, 0, len(citas or []), "La IA no aportó citas textuales verificables.")
    fuente_norm = normalizar(texto_fuente)
    fuente_tokens = _tokens_cita(texto_fuente)
    fuente_equiv = " ".join(fuente_tokens)
    indice: dict[str, list[int]] = {}
    for i, tok in enumerate(fuente_tokens):
        indice.setdefault(tok, []).append(i)
    literales: list[str] = []
    ancladas: list[str] = []
    for cita in utiles:
        tokens = _tokens_cita(cita)
        if normalizar(cita) in fuente_norm:
            literales.append(cita)
            ancladas.append(cita)
        elif " ".join(tokens) in fuente_equiv or _casi_literal(tokens, fuente_tokens, indice):
            ancladas.append(cita)
    requeridas = min(max(minimo, 1), len(utiles))
    if len(ancladas) < requeridas:
        return ResultadoAnclaje(
            False,
            len(ancladas),
            len(utiles),
            f"Fallo de anclaje: {len(ancladas)}/{len(utiles)} citas figuran en el texto original "
            f"(se exigían {requeridas}).",
        )
    return ResultadoAnclaje(True, len(ancladas), len(utiles), citas_ok=ancladas, citas_literales=literales)


# --------------------------------------------------------------------------- 5. salida

_URL = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
_TAG = re.compile(r"<[^>]{0,200}>")
_LIMITES = {
    "titulo": 140, "bajada": 420, "tribunal": 160, "caratula": 260, "identificador_legal": 80,
    "holding": 1400, "impacto_practico": 700, "cita_sugerida": 320, "jurisdiccion": 60,
}


def _numeros(texto: str) -> set[str]:
    """Números de un texto sin separadores de miles: 'Ley 27.828' -> {'27828'}."""
    sin_miles = re.sub(r"(?<=\d)[.](?=\d{3}\b)", "", texto or "")
    return set(re.findall(r"\d+", sin_miles))


def _limpiar_campo(valor: str, maximo: int) -> str:
    valor = _TAG.sub(" ", valor or "")
    valor = _URL.sub("", valor)
    valor = limpiar_espacios(limpiar_unicode_invisible(valor))
    return valor[:maximo].rstrip()


def sanear_salida(campos: dict, texto_fuente: str, oficial: dict | None = None) -> tuple[dict, list[str]]:
    """Limpia la ficha de la IA y descarta datos que no surgen de la fuente.

    Devuelve (campos_saneados, avisos). Los metadatos `oficial` (publicados por la propia
    fuente de forma estructurada) prevalecen sobre la IA para carátula y expediente.
    """
    oficial = oficial or {}
    avisos: list[str] = []
    salida = dict(campos)

    for clave, maximo in _LIMITES.items():
        if isinstance(salida.get(clave), str):
            salida[clave] = _limpiar_campo(salida[clave], maximo)
    for clave in ("puntos_clave", "normas_citadas", "etiquetas", "citas_textuales_verificables"):
        salida[clave] = [_limpiar_campo(str(x), 400) for x in (salida.get(clave) or []) if str(x).strip()]

    # Carátula y expediente: si la fuente los publica, mandan; si no, deben figurar en el texto.
    for clave in ("caratula", "identificador_legal"):
        if oficial.get(clave):
            salida[clave] = limpiar_espacios(str(oficial[clave]))
        elif salida.get(clave) and not contiene_normalizado(texto_fuente, salida[clave]):
            avisos.append(f"{clave} descartado: no figura en la fuente")
            salida[clave] = ""

    # Normas citadas: sólo las que aparecen (por su número) en la fuente.
    numeros_fuente = _numeros(texto_fuente)
    normas_ok = []
    for norma in salida.get("normas_citadas", []):
        claves = [n for n in _numeros(norma) if len(n) >= 2]
        if claves and all(c in numeros_fuente for c in claves):
            normas_ok.append(norma)
        elif not claves and contiene_normalizado(texto_fuente, norma):
            normas_ok.append(norma)
        else:
            avisos.append(f"norma descartada: {norma[:60]}")
    salida["normas_citadas"] = normas_ok[:8]
    salida["puntos_clave"] = salida["puntos_clave"][:4]
    salida["etiquetas"] = [e.lower()[:40] for e in salida["etiquetas"]][:6]

    # Re-escaneo: la IA no debería devolver nada que parezca una instrucción.
    texto_salida = " ".join(
        str(v) if not isinstance(v, list) else " ".join(map(str, v))
        for k, v in salida.items()
        if k != "citas_textuales_verificables"
    )
    riesgo = escanear_inyeccion(texto_salida)
    if riesgo.bloquear:
        avisos.append("SALIDA_SOSPECHOSA: " + "; ".join(riesgo.motivos))
    return salida, avisos
