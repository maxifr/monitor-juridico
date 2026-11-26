from monitor.almacen import Almacen, codificar_vector, decodificar_vector
from monitor.dedup import fusionar, normalizar_identificador
from monitor.textos import parsear_fecha


def test_identificadores_equivalentes():
    assert normalizar_identificador("FLP 001221/2024/CS001") == normalizar_identificador("FLP 1221/2024")
    assert normalizar_identificador("Ley N° 27.828") == normalizar_identificador("LEY 27828") == "LEY 27828"
    assert normalizar_identificador("DNU 70/2023") == normalizar_identificador("Decreto 70/2023")
    assert normalizar_identificador("") is None


def test_vectores_ida_y_vuelta():
    v = [0.1, -0.5, 0.25, 0.0]
    assert [round(x, 3) for x in decodificar_vector(codificar_vector(v))] == v


def test_similares_y_fusion_con_jerarquia(tmp_path):
    alm = Almacen(tmp_path)
    diario = {"id": "a1", "fuente": "diario_judicial", "fuente_nombre": "Diario Judicial", "url": "https://dj/1",
              "prioridad": 60, "titulo": "Nota", "fecha": "2026-11-20T10:00:00+00:00",
              "ingresado": "2099-01-01T00:00:00+00:00", "fuentes_adicionales": []}
    alm.agregar_novedad(diario, [1.0, 0.0, 0.0])
    assert alm.similares([0.99, 0.05, 0.0], 30, 0.8)[0][0]["id"] == "a1"
    assert not alm.similares([0.0, 1.0, 0.0], 30, 0.8)

    oficial = {"id": "b2", "fuente": "csjn", "fuente_nombre": "CSJN", "url": "https://csjn/1", "prioridad": 100,
               "titulo": "Fallo oficial", "caratula": "X c/ Y", "fecha": "2026-11-19T12:00:00+00:00"}
    assert fusionar(alm, diario, oficial, None) == "promovida_fuente_superior"
    rec = alm.novedades["a1"]
    assert rec["fuente"] == "csjn" and rec["url"] == "https://csjn/1"
    assert rec["fuentes_adicionales"][0]["url"] == "https://dj/1"
    # Una cobertura de menor jerarquía sólo se agrega como enlace.
    otra = {"fuente": "eldial", "fuente_nombre": "elDial", "url": "https://eldial/1", "prioridad": 58, "titulo": "t"}
    assert fusionar(alm, rec, otra, None) == "agregada_como_cobertura"
    assert fusionar(alm, rec, otra, None) == "ya_vinculada"


def test_fechas():
    assert parsear_fecha("19/11/2026").day == 19
    assert parsear_fecha("Wed, 25 Nov 2026 18:08:41 +0000").hour == 18
    assert parsear_fecha("2026-11-20T09:14:13-03:00").month == 11
    assert parsear_fecha("20261125").day == 25
    assert parsear_fecha("Viernes 20 de noviembre de 2026").day == 20
    assert parsear_fecha("sin fecha") is None
