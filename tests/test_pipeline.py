"""Prueba de punta a punta con fuentes reales (CSJN, MPF, Diario Judicial) sobre HTML de prueba."""

import json

from conftest import HTTPFalso, IAFalsa

from monitor.almacen import Almacen
from monitor.exportar import exportar
from monitor.modelos import hash_url
from monitor.pipeline import Pipeline

CSJN = "https://sjconsulta.csjn.gov.ar/sjconsulta"


def _http(leer):
    return HTTPFalso({
        f"{CSJN}/novedades/consulta.html": leer("csjn_consulta.html"),
        f"{CSJN}/novedades/paginarNovedades.html": leer("csjn_novedades.json"),
        "https://www.fiscales.gob.ar/fiscalias/condenaron": leer("mpf_nota_1.html"),
        "https://www.fiscales.gob.ar/fiscalias/nota-con-trampa": leer("mpf_nota_trampa.html"),
        "https://www.fiscales.gob.ar/": leer("mpf_portada.html"),
        "https://www.diariojudicial.com/news-200001": leer("dj_nota_1.html"),
        "https://www.diariojudicial.com/news-200002": leer("dj_nota_2.html"),
        "https://www.diariojudicial.com/": leer("dj_portada.html"),
    })


def _correr(ajustes, leer, ia):
    pipe = Pipeline(ajustes, ia=ia, http=_http(leer), claves=["csjn", "mpf", "diario_judicial"])
    return pipe, pipe.ejecutar()


def test_corrida_completa(ajustes, leer_fixture):
    ia = IAFalsa()
    pipe, resumen = _correr(ajustes, leer_fixture, ia)

    # MPF: concurso -> prefiltro; museo -> triage. Los enlaces a otros dominios ni se listan.
    assert resumen.prefiltrados == 1
    assert resumen.descartados_triage == 1
    # Texto oculto con instrucciones -> heurística; titular "INVENTADO" -> falla de citas.
    capas = sorted(r["capa"] for r in pipe.almacen.cuarentena())
    assert capas == ["grounding", "heuristica"]

    novedades = pipe.almacen.novedades
    # 2 fallos CSJN + 1 estafa MPF publicados; la nota de Diario Judicial sobre el fallo de la Corte se fusiona.
    assert resumen.publicados == 3
    assert resumen.fusionados == 1
    fallo = next(r for r in novedades.values() if r.get("identificador_legal") == "CSJ 123/2024/RH1")
    assert fallo["fuente"] == "csjn"
    assert fallo["caratula"] == "PÉREZ, JUAN s/ RECURSO EXTRAORDINARIO"  # oficial, no la inventada por la IA
    assert fallo["instancia"] == "CSJN"
    assert [a["fuente"] for a in fallo["fuentes_adicionales"]] == ["diario_judicial"]
    assert "Ley 99.999" not in fallo["normas_citadas"]  # norma inexistente descartada
    assert fallo["citas_textuales"]  # fuente oficial: se pueden mostrar citas literales
    estafa = next(r for r in novedades.values() if r["fuente"] == "mpf")
    assert estafa["caratula"] == ""  # la IA la inventó: no figura en la nota
    assert estafa["citas_textuales"] == []  # fuente no oficial de dominio público: sin citas literales

    # Lo procesado queda registrado: la segunda corrida no gasta IA.
    llamadas_previas = len(ia.llamadas)
    pipe2, resumen2 = _correr(ajustes, leer_fixture, ia)
    assert resumen2.publicados == 0 and resumen2.curados == 0
    assert len(ia.llamadas) == llamadas_previas
    assert resumen2.ya_vistos >= 8


def test_cuota_agotada_deja_pendientes(ajustes, leer_fixture):
    ia = IAFalsa(cupo=2)  # 1 triage + 1 curaduría
    pipe, resumen = _correr(ajustes, leer_fixture, ia)
    assert resumen.sin_cuota
    assert resumen.publicados == 1
    assert resumen.pendientes >= 3
    guardado = json.loads((ajustes.dir_datos / "pendientes.json").read_text(encoding="utf-8"))
    assert guardado and all(p["candidato"]["triado"] for p in guardado.values())

    # Con cuota renovada, la corrida siguiente termina el trabajo sin repetir el triage.
    ia2 = IAFalsa()
    _, resumen2 = _correr(ajustes, leer_fixture, ia2)
    assert resumen2.publicados + resumen2.fusionados >= 2
    assert not Almacen(ajustes.dir_datos).cargar().pendientes


def test_exportacion_publica(ajustes, leer_fixture):
    pipe, _ = _correr(ajustes, leer_fixture, IAFalsa())
    meta = exportar(pipe.almacen, ajustes)
    ultimas = json.loads((ajustes.dir_sitio / "data" / "ultimas.json").read_text(encoding="utf-8"))
    assert meta["total"] == 3 and len(ultimas["items"]) == 3
    for item in ultimas["items"]:
        assert "url_hash" not in item and "id_legal_norm" not in item and "prioridad" not in item
    assert {f["clave"] for f in meta["fuentes"]} >= {"csjn", "mpf", "diario_judicial"}
    rss = (ajustes.dir_sitio / "feed.xml").read_text(encoding="utf-8")
    assert rss.count("<item>") == 3
    # Los embeddings sólo viven en data/, nunca en el sitio público.
    assert (ajustes.dir_datos / "embeddings.json").exists()
    assert not list((ajustes.dir_sitio).rglob("embeddings*"))


def test_hash_url_canonica():
    assert hash_url("https://WWW.Ejemplo.com/nota/?utm_source=x") == hash_url("https://www.ejemplo.com/nota")


def test_allowlist_de_dominios(ajustes, leer_fixture):
    from monitor.modelos import Candidato

    pipe = Pipeline(ajustes, ia=IAFalsa(), http=_http(leer_fixture), claves=["mpf"])
    ajeno = Candidato(fuente="mpf", url="https://fiscales.gob.ar.example.com/falsa", titulo="Nota con dominio parecido")
    assert pipe.filtrar([ajeno]) == []
    assert pipe.almacen.cuarentena()[0]["capa"] == "dominio"
