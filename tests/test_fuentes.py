"""Extractores sobre páginas que reproducen la estructura real de cada portal."""

from conftest import HTTPFalso

from monitor import fuentes as registro
from monitor.fuentes.base import token_csrf
from monitor.fuentes.medios import AlDiaMicrojuris, InfobaeJudiciales
from monitor.fuentes.oficiales import SAIJBoletin
from monitor.modelos import hash_url
from monitor.textos import parsear_fecha

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Selección Editorial 25-11-2026</title><link>https://aldiaargentina.microjuris.com/2026/11/25/seleccion/</link><pubDate>Wed, 25 Nov 2026 12:00:00 +0000</pubDate></item>
<item><title>#Fallos CSJN: es infundada la inconstitucionalidad de la ley 23.928</title><link>https://aldiaargentina.microjuris.com/2026/11/25/fallos-csjn/</link><pubDate>Wed, 25 Nov 2026 09:00:00 +0000</pubDate></item>
</channel></rss>"""

INFOBAE = """<?xml version="1.0"?><rss><channel>
<item><title>Fallo judicial</title><link>https://www.infobae.com/judiciales/2026/11/25/nota/</link><pubDate>Wed, 25 Nov 2026 21:00:00 +0000</pubDate></item>
<item><title>Otra sección</title><link>https://www.infobae.com/politica/2026/11/25/nota/</link><pubDate>Wed, 25 Nov 2026 21:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_boletin_saij(leer_fixture):
    http = HTTPFalso({"https://www.saij.gob.ar/boletin-saij/": leer_fixture("saij_boletin.html")})
    fuente = SAIJBoletin(http)
    candidatos = fuente.listar()
    assert len(candidatos) == 2
    drones, designacion = candidatos
    assert "utm_" not in drones.url
    assert drones.oficial == {"identificador_legal": "Resolución 904/26", "tribunal": "Administración Nacional de Aviación Civil"}
    assert drones.fecha.day == 24 and drones.detalle_cargado
    assert fuente.prefiltro(drones) is None
    assert fuente.prefiltro(designacion)  # designaciones: descartadas sin gastar IA


def test_rss_con_ajustes():
    aldia = AlDiaMicrojuris(HTTPFalso({AlDiaMicrojuris.feed: RSS}))
    (cand,) = aldia.listar()  # la "Selección Editorial" diaria se descarta
    assert cand.titulo.startswith("CSJN:") and cand.seccion == "Fallos"
    infobae = InfobaeJudiciales(HTTPFalso({InfobaeJudiciales.feed: INFOBAE}))
    assert [c.url for c in infobae.listar()] == ["https://www.infobae.com/judiciales/2026/11/25/nota/"]


def test_fuentes_por_defecto():
    claves = {f.clave for f in registro.construir(HTTPFalso({}))}
    assert "eldial" not in claves  # muro de pago: sólo si se pide en FUENTES_ACTIVAS
    assert {"csjn_noticias", "infoleg", "saij_boletin", "justicia_ar", "ijudicial", "infobae"} <= claves
    assert "eldial" in {f.clave for f in registro.construir(HTTPFalso({}), ["eldial"])}


def test_utilidades():
    assert token_csrf('<script>var token = "7ad519d4-6543-4dba-be0b-5a544ce990f7";</script>') == "7ad519d4-6543-4dba-be0b-5a544ce990f7"
    assert token_csrf('const csrfToken = "af72bb11-b03e-42aa-9a5c-c79a18f59f2b";').startswith("af72")
    assert parsear_fecha("Publicada en el Boletín Oficial del 09-mar-2026").month == 3
    assert hash_url("https://www.saij.gob.ar/NV52859?utm_source=x") == hash_url("https://www.saij.gob.ar/NV52859")
