"""Fuentes normativas oficiales: Boletín Oficial (primera sección) y SAIJ.

Ambas publican documentos públicos (normas y fallos), por lo que el portal puede citar
fragmentos textuales. El Boletín publica decenas de avisos por día: un prefiltro por
reglas descarta designaciones, renuncias y trámites antes de gastar cuota de IA.
"""

from __future__ import annotations

import json
import re

from ..modelos import Candidato
from ..seguridad import html_a_texto_seguro, texto_plano_seguro
from ..textos import limpiar_espacios, parsear_fecha
from .base import Fuente, absoluta

# --------------------------------------------------------------------------- Boletín Oficial

_TRAMITE = re.compile(
    r"\b(des[ií]gnase|designaci[oó]n|dase por designad|dase por prorrogad|dase por asignad|prorr[oó]gase|pr[oó]rroga de designaci|ac[eé]ptase la renuncia|"
    r"renuncia|rech[aá]zase (el )?recurso|as[ií]gnase (la )?funci[oó]n|tr[aá]sl[aá]dase|licencia|"
    r"dase por conclu|desaf[eé]ctase|ad[ií]rese|autor[ií]zase la (contrataci|comisi)|apru[eé]base la contrataci|"
    r"conv[oó]case|licitaci[oó]n|fe de erratas|nombramiento|mant[eé]nganse|ascenso)\b",
    re.IGNORECASE,
)
_TIPOS_SIEMPRE = re.compile(
    r"^(ley|decreto|decreto de necesidad y urgencia|resoluci[oó]n general|resoluci[oó]n conjunta|tratados)\b", re.IGNORECASE
)
_TIPOS_POR_ORGANISMO = re.compile(r"^(resoluci[oó]n|disposici[oó]n|decisi[oó]n administrativa|acordada)\b", re.IGNORECASE)
_ORGANISMOS_RELEVANTES = re.compile(
    r"(justicia|seguridad nacional|ministerio de seguridad|ministerio p[uú]blico|magistratura|procuraci[oó]n|"
    r"informaci[oó]n financiera|anses|seguridad social|riesgos del trabajo|acceso a la informaci[oó]n|"
    r"derechos humanos|corte suprema|registro nacional de reincidencia|servicio penitenciario|"
    r"defensa del consumidor|inspecci[oó]n general de justicia)",
    re.IGNORECASE,
)
_ORGANISMOS_EXCLUIDOS = re.compile(r"(relaciones y regulaciones del trabajo)", re.IGNORECASE)  # homologaciones de convenios
_OPERATIVA = re.compile(r"\b(RESUELVE|DECRETA|DISPONE|RESUELVEN|DISPONEN|ACUERDAN)\s*:", re.IGNORECASE)
_MINUSCULAS = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "para", "por", "a", "al", "o"}


def _titulo_es(texto: str) -> str:
    """'MINISTERIO DE JUSTICIA' -> 'Ministerio de Justicia'."""
    palabras = texto.lower().split()
    return " ".join(p if (i and p in _MINUSCULAS) else p[:1].upper() + p[1:] for i, p in enumerate(palabras))


class BoletinOficial(Fuente):
    clave = "bora"
    nombre = "Boletín Oficial (1.ª sección)"
    portada = "https://www.boletinoficial.gob.ar/seccion/primera"
    dominios = frozenset({"boletinoficial.gob.ar"})
    prioridad = 95
    oficial = True
    dominio_publico = True
    selectores_cuerpo = ("#cuerpoDetalleAviso", "div.detalle-cuerpo")
    # La portada del Boletín no trae sumario de la mayoría de las resoluciones: para que
    # el triage no decida "a ciegas", se descarga el texto de las que pasan el prefiltro.
    detalle_antes_del_triage = True

    def __init__(self, http, max_candidatos: int = 20) -> None:
        # El Boletín publica muchos avisos: se listan todos y el prefiltro decide.
        super().__init__(http, max(max_candidatos, 150))

    def listar(self) -> list[Candidato]:
        sopa = self.sopa(self.portada)
        salida: list[Candidato] = []
        vistos: set[str] = set()
        for enlace in sopa.select("a[href*='/detalleAviso/primera/']"):
            href = enlace["href"].split("?")[0]
            if href in vistos or "anexos" in enlace["href"]:
                continue
            parrafos = [limpiar_espacios(p.get_text(" ", strip=True)) for p in enlace.select("p")]
            if not parrafos:
                continue
            vistos.add(href)
            organismo = _titulo_es(parrafos[0]) if parrafos[0].isupper() else parrafos[0]
            norma = parrafos[1] if len(parrafos) > 1 else ""
            detalle = parrafos[2] if len(parrafos) > 2 else ""
            resumen = detalle.split(" - ", 1)[1] if " - " in detalle else ("" if re.match(r"^[A-Z]{2,}-\d{4}-", detalle) else detalle)
            titulo = f"{norma} — {organismo}" + (f": {resumen}" if resumen else "")
            salida.append(
                self.candidato(
                    absoluta(self.portada, href),
                    titulo,
                    resumen=resumen,
                    fecha=parsear_fecha(href.rsplit("/", 1)[-1]),
                    seccion=organismo,
                    oficial={"identificador_legal": norma, "tribunal": organismo, "sumario_portada": resumen},
                )
            )
        return salida[: self.max_candidatos]

    def prefiltro(self, cand: Candidato) -> str | None:
        norma = cand.oficial.get("identificador_legal", "")
        organismo = cand.seccion
        tramite = "acto administrativo de trámite (designación, renuncia, recurso, licencia…)"
        if _TRAMITE.search(cand.oficial.get("sumario_portada", cand.resumen)):
            return tramite
        if _TIPOS_SIEMPRE.search(norma):
            return None
        if _TIPOS_POR_ORGANISMO.search(norma) and _ORGANISMOS_RELEVANTES.search(organismo) and not _ORGANISMOS_EXCLUIDOS.search(organismo):
            # Ya leída la norma: si el artículo 1° es una designación o prórroga, es trámite.
            return tramite if _TRAMITE.search(cand.oficial.get("operativa", "")[:250]) else None
        return "tipo de aviso u organismo fuera del perfil jurídico"

    def cargar_detalle(self, cand: Candidato) -> None:
        sumario_portada = cand.resumen
        super().cargar_detalle(cand)
        # Para el triage sirve más la parte resolutiva que los "VISTO/CONSIDERANDO".
        m = _OPERATIVA.search(cand.texto)
        operativa = cand.texto[m.end(): m.end() + 500].strip() if m else ""
        cand.oficial["operativa"] = operativa[:300]
        cand.resumen = limpiar_espacios(f"{sumario_portada} {operativa}")[:600] or cand.resumen


# --------------------------------------------------------------------------- SAIJ

_BUSQUEDA = "https://www.saij.gob.ar/busqueda"
_FACETAS = "Total|Tipo de Documento/{tipo}|Fecha|Organismo|Publicación|Tema|Estado de Vigencia|Autor|Jurisdicción{juris}"


def _consultar_saij(http, tipo: str, juris: str, cantidad: int) -> list[dict]:
    resp = http.get(
        _BUSQUEDA,
        params={
            "o": 0,
            "p": cantidad,
            "f": _FACETAS.format(tipo=tipo, juris=juris),
            "s": "fecha-rango|DESC",
            "v": "colapsada",
        },
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, */*; q=0.01"},
    )
    documentos = []
    for doc in (resp.json().get("searchResults") or {}).get("documentResultList") or []:
        try:
            abstracto = json.loads(doc["documentAbstract"])["document"]
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        abstracto["uuid"] = doc.get("uuid")
        documentos.append(abstracto)
    return documentos


def _url_saij(doc: dict) -> str | None:
    amigable = (doc.get("metadata") or {}).get("friendly-url") or {}
    if not amigable.get("description") or not doc.get("uuid"):
        return None
    return f"https://www.saij.gob.ar/{amigable['description']}/{doc['uuid']}"


class SAIJLegislacion(Fuente):
    clave = "saij"
    nombre = "SAIJ — Leyes nacionales"
    portada = "https://www.saij.gob.ar/"
    dominios = frozenset({"saij.gob.ar"})
    prioridad = 95
    oficial = True
    dominio_publico = True
    min_citas = 1
    antiguedad_maxima = 120

    def listar(self) -> list[Candidato]:
        salida: list[Candidato] = []
        for doc in _consultar_saij(self.http, "Legislación/Ley", "/Nacional", self.max_candidatos):
            url = _url_saij(doc)
            contenido = doc.get("content") or {}
            if not url:
                continue
            tipo_doc = (doc.get("metadata") or {}).get("document-content-type")
            if tipo_doc == "novedad":
                numero = contenido.get("nro_norma")
                titulo = texto_plano_seguro(contenido.get("titulo_noticia") or contenido.get("titulo_1"))
                sintesis = texto_plano_seguro(contenido.get("sintesis"))
                ident = f"Ley {numero}" if numero else ""
                texto = f"{titulo}. {sintesis}"
            else:
                ident = texto_plano_seguro(contenido.get("nombre-coloquial"))
                titulo_norma = texto_plano_seguro(contenido.get("titulo-norma"))
                titulo = f"{ident}: {titulo_norma}" if ident else titulo_norma
                sumario = texto_plano_seguro(contenido.get("sumario"))
                sintesis = sumario.capitalize() if sumario.isupper() else sumario
                texto = f"{titulo}. Estado: {texto_plano_seguro(contenido.get('estado'))}. Temas: {sintesis}."
            if not titulo:
                continue
            salida.append(
                self.candidato(
                    url, titulo, resumen=sintesis[:600], fecha=parsear_fecha(contenido.get("fecha")),
                    seccion="Legislación", texto=texto, detalle_cargado=True,
                    oficial={"identificador_legal": _normalizar_ley(ident), "tribunal": "Congreso de la Nación"},
                )
            )
        return salida


def _normalizar_ley(texto: str) -> str:
    m = re.search(r"(?i)ley\s*(?:n[°º.]?\s*)?([\d.]+)", texto or "")
    return f"Ley {m.group(1).replace('.', '')}" if m else (texto or "")


class SAIJJurisprudenciaTDF(Fuente):
    """Fallos y sumarios de la justicia de Tierra del Fuego cargados en SAIJ."""

    clave = "saij_tdf"
    nombre = "SAIJ — Jurisprudencia de Tierra del Fuego"
    portada = "https://www.saij.gob.ar/"
    dominios = frozenset({"saij.gob.ar"})
    prioridad = 94
    oficial = True
    dominio_publico = True
    min_citas = 1
    antiguedad_maxima = 400

    def listar(self) -> list[Candidato]:
        juris = "/Local/Tierra del Fuego"
        fallos = _consultar_saij(self.http, "Jurisprudencia/Fallo", juris, 10)
        sumarios = _consultar_saij(self.http, "Jurisprudencia/Sumario", juris, 40)
        texto_sumario = {
            str((s.get("content") or {}).get("numero-sumario")): texto_plano_seguro((s.get("content") or {}).get("texto"))
            for s in sumarios
        }
        salida: list[Candidato] = []
        for doc in fallos:
            url = _url_saij(doc)
            c = doc.get("content") or {}
            if not url:
                continue
            actor = texto_plano_seguro(c.get("actor"))
            demandado = texto_plano_seguro(c.get("demandado"))
            sobre = texto_plano_seguro(c.get("sobre"))
            tribunal = texto_plano_seguro(c.get("tribunal")).title()
            caratula = " ".join(p for p in (actor, f"c/ {demandado}" if demandado else "", f"s/ {sobre}" if sobre else "") if p)
            relacionados = (c.get("sumarios-relacionados") or {}).get("sumario-relacionado") or []
            if isinstance(relacionados, str):
                relacionados = [relacionados]
            textos = [texto_sumario[r] for r in relacionados if texto_sumario.get(r)]
            if not textos:
                continue  # sin sumarios no hay sustancia para una ficha verificable
            cuerpo = f"{tribunal} de Tierra del Fuego. Carátula: {caratula}. Sumarios: " + " ".join(textos)
            salida.append(
                self.candidato(
                    url, f"{tribunal} (TDF): {caratula}", resumen=textos[0][:600],
                    fecha=parsear_fecha(c.get("fecha")), seccion="Jurisprudencia TDF", texto=cuerpo,
                    detalle_cargado=True,
                    oficial={"caratula": caratula, "tribunal": f"{tribunal} — Tierra del Fuego",
                             "identificador_legal": str(c.get("numero-fallo") or "")},
                )
            )
        return salida[: self.max_candidatos]


def texto_de_html(html: str) -> str:
    return html_a_texto_seguro(html).texto


# --------------------------------------------------------------------------- Boletín del SAIJ


class SAIJBoletin(Fuente):
    """Boletín de novedades del SAIJ: normas nacionales y provinciales, acordadas y fallos
    destacados, cada uno con una síntesis oficial."""

    clave = "saij_boletin"
    nombre = "SAIJ — Boletín de novedades"
    portada = "https://www.saij.gob.ar/boletin-saij/"
    dominios = frozenset({"saij.gob.ar"})
    prioridad = 93
    oficial = True
    dominio_publico = True
    min_citas = 1
    antiguedad_maxima = 45

    def __init__(self, http, max_candidatos: int = 20) -> None:
        super().__init__(http, max(max_candidatos, 100))  # el boletín trae decenas de normas juntas

    def listar(self) -> list[Candidato]:
        sopa = self.sopa(self.portada)
        salida: list[Candidato] = []
        vistos: set[str] = set()
        for bloque in sopa.select("div.detalle"):
            enlace = bloque.select_one(".titulo-norma a[href]")
            if not enlace:
                continue
            url = _sin_rastreo(absoluta(self.portada, enlace["href"]))
            if url in vistos:
                continue
            vistos.add(url)
            titulo = enlace.get_text(" ", strip=True)
            subtitulo = _texto(bloque, ".subtitulo-norma")
            publicacion = _texto(bloque, ".publicacion")
            sintesis = _texto(bloque, ".sintesis")
            norma, _, organismo = subtitulo.partition(" - ")
            salida.append(self.candidato(
                url, titulo, resumen=sintesis[:600], fecha=parsear_fecha(publicacion), seccion=organismo or subtitulo,
                texto=limpiar_espacios(f"{titulo}. {subtitulo}. {publicacion}. {sintesis}"), detalle_cargado=True,
                oficial={"identificador_legal": norma.strip(), "tribunal": organismo.strip()},
            ))
        return salida[: self.max_candidatos]

    def prefiltro(self, cand: Candidato) -> str | None:
        if _TRAMITE.search(f"{cand.titulo} {cand.oficial.get('identificador_legal', '')}"):
            return "acto administrativo de trámite (designación, renuncia, recurso, licencia…)"
        return None


def _texto(bloque, selector: str) -> str:
    nodo = bloque.select_one(selector)
    return limpiar_espacios(nodo.get_text(" ", strip=True)) if nodo else ""


def _sin_rastreo(url: str) -> str:
    """Quita los parámetros utm_ del boletín para que el enlace quede limpio."""
    base, _, consulta = url.partition("?")
    if not consulta:
        return url
    utiles = [p for p in consulta.replace("?", "&").split("&") if p and not p.lower().startswith("utm_")]
    return base + ("?" + "&".join(utiles) if utiles else "")
