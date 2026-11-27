"""Pruebas de las correcciones de noviembre de 2026: reparto justo entre fuentes, pendientes que
no se pierden, registro de descartes, PDF de sentencias, Pensamiento Penal y citas tolerantes."""

from datetime import timedelta

from conftest import HTTPFalso, RespuestaFalsa

from monitor.almacen import Almacen
from monitor.fuentes.medios import PensamientoPenal
from monitor.modelos import Candidato
from monitor.pdf import buscar_pdf, texto_de_pdf
from monitor.pipeline import Pipeline
from monitor.seguridad import verificar_anclaje
from monitor.textos import ahora


def _cands(fuente, n, base="https://www.ejemplo.gob.ar"):
    momento = ahora()
    return [Candidato(fuente=fuente, url=f"{base}/{fuente}/{i}", titulo=f"Nota {i} de {fuente}",
                      fecha=momento - timedelta(hours=i)) for i in range(n)]


def test_reparto_reserva_lugar_para_los_medios(ajustes):
    pipe = Pipeline(ajustes, http=HTTPFalso({}), claves=["saij_boletin", "mpf", "infobae", "diario_judicial"])
    candidatos = _cands("saij_boletin", 80) + _cands("mpf", 30) + _cands("infobae", 12) + _cands("diario_judicial", 3)
    elegidos, diferidos = pipe._repartir(candidatos, tope=20)
    cuenta = {f: sum(c.fuente == f for c in elegidos) for f in ("saij_boletin", "mpf", "infobae", "diario_judicial")}
    assert len(elegidos) == 20 and len(diferidos) == len(candidatos) - 20
    assert cuenta["infobae"] == 5 and cuenta["diario_judicial"] == 3  # antes: 0 y 0
    assert cuenta["saij_boletin"] >= 5
    # Se procesan por jerarquía (oficiales primero) para que la deduplicación prefiera la fuente oficial.
    prioridades = [pipe.mapa[c.fuente].prioridad for c in elegidos]
    assert prioridades == sorted(prioridades, reverse=True)


def test_reparto_prioriza_lo_que_mas_espera(ajustes):
    pipe = Pipeline(ajustes, http=HTTPFalso({}), claves=["infobae"])
    ajustes_piso = pipe.ajustes
    viejos = _cands("infobae", 8)
    pipe.almacen.encolar_pendiente(viejos[7].url_hash, viejos[7].a_dict(), "cupo")
    elegidos, _ = pipe._repartir(viejos, tope=ajustes_piso.cupo_minimo_fuente)
    assert viejos[7] in elegidos  # la más vieja en espera entra aunque haya 7 más recientes


def test_esperar_turno_no_cuenta_como_fallo(tmp_path):
    almacen = Almacen(tmp_path)
    cand = Candidato(fuente="infobae", url="https://www.infobae.com/judiciales/2026/11/26/x", titulo="x")
    for _ in range(10):  # diez corridas sin lugar en el cupo
        almacen.encolar_pendiente(cand.url_hash, cand.a_dict(), "cupo")
    almacen.podar()
    assert cand.url_hash in almacen.pendientes
    assert almacen.pendientes[cand.url_hash]["postergaciones"] == 10
    cand.intentos = 5  # cinco errores reales
    almacen.encolar_pendiente(cand.url_hash, cand.a_dict(), "fallo")
    almacen.podar()
    assert cand.url_hash not in almacen.pendientes


def test_descartes_quedan_registrados_y_se_pueden_reprocesar(tmp_path):
    almacen = Almacen(tmp_path)
    almacen.marcar_visto("h1", "descartado_triage", fuente="diario_judicial")
    almacen.marcar_visto("h2", "publicado", "id2", fuente="diario_judicial")
    almacen.marcar_visto("h3", "descartado_ia", fuente="mpf")
    almacen.registrar_descarte(url="https://x", fuente="diario_judicial", titulo="El error que nadie vio",
                               etapa="triage", motivo="título sin contexto")
    almacen.guardar()
    otra = Almacen(tmp_path).cargar()
    assert otra.descartes()[0]["motivo"] == "título sin contexto"
    assert otra.reprocesar({"diario_judicial"}) == 1
    assert "h1" not in otra.vistos and "h2" in otra.vistos and "h3" in otra.vistos


def test_anclaje_tolera_abreviaturas_y_erratas():
    fuente = ("La Cámara resolvió que, conforme el art. 18 de la Constitución Nacional, nadie puede ser "
              "obligado a declarar contra sí mismo en ninguna causa penal seguida en su contra.")
    expandida = verificar_anclaje(fuente, ["conforme el artículo 18 de la Constitución Nacional nadie puede"], 1)
    assert expandida.ok and expandida.citas_literales == []  # anclada, pero no se muestra como textual
    errata = verificar_anclaje(fuente, ["nadie podrá ser obligado a declarar contra sí mismo en ninguna causa"], 1)
    assert errata.ok
    inventada = verificar_anclaje(fuente, ["la defensa pidió la absolución del imputado por falta de pruebas"], 1)
    assert not inventada.ok
    # Con mínimo 1, una cita buena alcanza y las malas se quitan de la ficha.
    mezcla = verificar_anclaje(fuente, ["nadie puede ser obligado a declarar contra sí mismo",
                                        "el tribunal ordenó la inmediata libertad del imputado"], 1)
    assert mezcla.ok and mezcla.citas_ok == ["nadie puede ser obligado a declarar contra sí mismo"]


def _pdf_con_texto(texto: str) -> bytes:
    """PDF mínimo válido con una línea de texto (sin dependencias extra)."""
    renglones = [texto[i:i + 80] for i in range(0, len(texto), 80)]
    flujo = ("BT /F1 11 Tf 40 760 Td " + " ".join(f"({r}) Tj 0 -14 Td" for r in renglones) + " ET").encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(flujo)).encode() + b" >>\nstream\n" + flujo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    salida = bytearray(b"%PDF-1.4\n")
    posiciones = []
    for i, obj in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for p in posiciones:
        salida += f"{p:010d} 00000 n \n".encode()
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(salida)


def test_lee_texto_de_pdf():
    texto = texto_de_pdf(_pdf_con_texto("SE RESUELVE: Hacer lugar al recurso de casacion interpuesto por la defensa"))
    assert "Hacer lugar al recurso de casacion" in texto


PP_FALLO = """<html><head><title>Fallo</title></head><body><article>
<h1>Revocan la absolución de un ginecólogo</h1>
<div class="field field--name-field-juzgado"><div class="field__item">Juzgado de Control y Faltas 7</div></div>
<div class="field field--name-field-fecha-fallo"><div class="field__label">Fecha Fallo</div>
  <div class="field__item">Miércoles, Octubre 21, 2026 - 12:00</div></div>
<div class="field field--name-field-voces"><div class="field__item">Violencia de género</div></div>
<div class="field field--name-field-sumario"><p>Una médica denunció que el ginecólogo la trató con expresiones
infantilizantes durante una ecografía. El juzgado revocó la absolución y lo sancionó por maltrato agravado
conforme el Código de Convivencia Ciudadana.</p></div>
<div class="field field--name-field-caratula"><div class="field__label">Carátula</div>
  <div class="field__item">“B., F. – Infracción al Código de Convivencia Ciudadana (ley 10.326)”</div></div>
<div class="field field--name-field-archivo"></div>
<iframe src="/libraries/pdf.js/web/viewer.html?file=https%3A%2F%2Fwww.pensamientopenal.com.ar%2Fsystem%2Ffiles%2FDocumento_Editado4125.pdf"></iframe>
<a href="https://carga-material.pensamientopenal.com.ar/storage/publico/Dossier%20Especial.pdf?v1=">Dossier</a>
</article></body></html>"""


def test_pensamiento_penal_usa_sumario_y_enlaza_la_sentencia():
    url = "https://www.pensamientopenal.com.ar/fallos/92000-revocan-absolucion"
    http = HTTPFalso({url: PP_FALLO})
    fuente = PensamientoPenal(http)
    cand = Candidato(fuente="pensamiento_penal", url=url, titulo="Revocan la absolución de un ginecólogo")
    fuente.cargar_detalle(cand)
    assert cand.resumen.startswith("Una médica denunció")  # antes: "Juzgado de Control… Fecha Fallo…"
    assert cand.oficial["tribunal"] == "Juzgado de Control y Faltas 7"
    assert cand.oficial["caratula"].startswith("B., F. – Infracción")
    assert cand.oficial["url_fallo"] == "https://www.pensamientopenal.com.ar/system/files/Documento_Editado4125.pdf"
    # En modo referencia (ai-train=no, plan gratuito) a la IA llega el sumario, no el encabezado.
    cand.modo_ia = "referencia"
    assert "revocó la absolución" in cand.texto_para_ia()


def test_buscar_pdf_ignora_enlaces_ajenos():
    html = '<a href="/uploads/0000063326-original.pdf">Fallo</a><a href="https://otro.com/x.pdf">x</a>'
    patron = r"^https://(www\.)?diariojudicial\.com/uploads/[^?#]+\.pdf"
    assert buscar_pdf(html, "https://www.diariojudicial.com/news-1-x", patron) == \
        "https://www.diariojudicial.com/uploads/0000063326-original.pdf"
    assert buscar_pdf('<a href="https://otro.com/x.pdf">x</a>', "https://www.diariojudicial.com/n", patron) == ""


def test_diario_judicial_agrega_la_sentencia_al_cuerpo():
    from monitor.fuentes.medios import DiarioJudicial

    nota = "https://www.diariojudicial.com/news-300001-el-error"
    pdf = "https://www.diariojudicial.com/uploads/0000063319-original.pdf"
    html = ('<html><head><meta property="og:description" content="El TSJ porteño anuló una sentencia."></head>'
            '<body><div class="nota-cuerpo"><p>' + "El Tribunal Superior de Justicia declaró la nulidad. " * 8 +
            f'</p><a href="{pdf}">Ver fallo</a></div></body></html>')
    texto_fallo = "SE RESUELVE: declarar la nulidad de la sentencia de la Sala IV " * 8

    class HTTPConPDF(HTTPFalso):
        def get(self, url, **kw):
            if url == pdf:
                self.pedidos.append(url)
                return RespuestaFalsa(_pdf_con_texto(texto_fallo), "application/pdf")
            return super().get(url, **kw)

    http = HTTPConPDF({nota: html})
    fuente = DiarioJudicial(http)
    cand = Candidato(fuente="diario_judicial", url=nota, titulo="El error que nadie vio")
    fuente.cargar_detalle(cand)
    assert cand.resumen == "El TSJ porteño anuló una sentencia."  # bajada para el triage
    assert cand.oficial["url_fallo"] == pdf
    fuente.cargar_adjunto(cand)
    assert "TEXTO DE LA SENTENCIA" in cand.texto and "declarar la nulidad" in cand.texto
    fuente.cargar_adjunto(cand)  # no se descarga dos veces
    assert http.pedidos.count(pdf) == 1
