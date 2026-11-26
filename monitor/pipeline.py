"""Orquestador: recolección → filtros → triage → seguridad → curaduría → dedup → publicación.

    [Fuentes] → [vistos + allowlist + antigüedad + prefiltro]  (gratis)
             → [triage IA en lote]                              (1 llamada cada 30)
             → [descarga del cuerpo + Content-Signal]
             → [Capa 1: heurística]        → cuarentena
             → [Capa 2: curador con nonce] → cuarentena si detecta inyección
             → [Capa 3: citas verificadas + saneamiento de salida] → cuarentena
             → [Capa 4: dedup multi-fuente] → fusión o publicación
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta

from . import fuentes as registro
from .almacen import Almacen
from .config import Ajustes
from .curaduria import FichaCurada, curar, triage_lote
from .dedup import Deduplicador, fusionar, normalizar_identificador, texto_semantico
from .http import ClienteHTTP
from .ia import ClienteGemini, ClienteIA, ErrorIA, SinCuota
from .modelos import Candidato
from .seguridad import dominio_permitido, escanear_inyeccion, sanear_salida, verificar_anclaje
from .textos import a_iso, ahora, limpiar_espacios

log = logging.getLogger(__name__)

TAMANO_LOTE_TRIAGE = 30
MAX_DETALLES_PREVIOS = 25


@dataclass
class Resumen:
    inicio: str = field(default_factory=lambda: a_iso(ahora()) or "")
    fin: str = ""
    duracion_s: float = 0.0
    modelo: str = ""
    candidatos: int = 0
    ya_vistos: int = 0
    prefiltrados: int = 0
    antiguos: int = 0
    descartados_triage: int = 0
    curados: int = 0
    descartados_ia: int = 0
    cuarentena: int = 0
    publicados: int = 0
    fusionados: int = 0
    pendientes: int = 0
    sin_cuota: bool = False
    por_fuente: dict = field(default_factory=dict)
    errores: list = field(default_factory=list)
    nuevas: list = field(default_factory=list)

    def texto(self) -> str:
        filas = [
            f"Candidatos detectados: {self.candidatos} (ya vistos {self.ya_vistos}, prefiltro {self.prefiltrados}, antiguos {self.antiguos})",
            f"Triage: {self.descartados_triage} descartados | Curados por IA: {self.curados} | Descartados por IA: {self.descartados_ia}",
            f"Publicados: {self.publicados} | Fusionados como cobertura: {self.fusionados} | Cuarentena: {self.cuarentena}",
            f"Pendientes para la próxima corrida: {self.pendientes}" + (" (cuota de IA agotada)" if self.sin_cuota else ""),
        ]
        for clave, info in self.por_fuente.items():
            estado = "OK" if info.get("ok") else f"ERROR: {info.get('error', '')[:80]}"
            filas.append(f"  · {clave}: {info.get('candidatos', 0)} candidatos, {info.get('nuevos', 0)} nuevos — {estado}")
        return "\n".join(filas)


# --------------------------------------------------------------------------- helpers


def _construir_registro(cand: Candidato, ficha: dict, fuente, anclaje, avisos: list[str], modelo: str) -> dict:
    momento = ahora()
    oficial = {
        k: v for k, v in cand.oficial.items()
        if k in ("relevancia", "inconstitucional", "sentencia_arbitraria", "url_fallo", "materia_oficial") and v
    }
    tribunal = ficha.get("tribunal") or cand.oficial.get("tribunal", "")
    instancia = "CSJN" if cand.fuente == "csjn" else ficha.get("instancia", "Otro")
    return {
        "id": cand.id,
        "url_hash": cand.url_hash,
        "fuente": cand.fuente,
        "fuente_nombre": fuente.nombre,
        "url": cand.url,
        "prioridad": fuente.prioridad,
        "fuente_oficial": fuente.oficial,
        "dominio_publico": fuente.dominio_publico,
        "titulo": ficha.get("titulo") or cand.titulo,
        "titulo_original": cand.titulo,
        "bajada": ficha.get("bajada", ""),
        "tipo": ficha.get("tipo", "Noticia"),
        "materia": ficha.get("materia", "Institucional"),
        "instancia": instancia,
        "jurisdiccion": ficha.get("jurisdiccion", ""),
        "tribunal": tribunal,
        "caratula": ficha.get("caratula", ""),
        "identificador_legal": ficha.get("identificador_legal", ""),
        "id_legal_norm": normalizar_identificador(ficha.get("identificador_legal")),
        "holding": ficha.get("holding", ""),
        "puntos_clave": ficha.get("puntos_clave", []),
        "impacto_practico": ficha.get("impacto_practico", ""),
        "normas_citadas": ficha.get("normas_citadas", []),
        "etiquetas": ficha.get("etiquetas", []),
        "cita_sugerida": ficha.get("cita_sugerida", ""),
        "alto_impacto": bool(ficha.get("alto_impacto")),
        # Los fallos y normas oficiales pueden citarse textualmente; los medios privados, no.
        "citas_textuales": ficha.get("citas_textuales_verificables", [])[:3] if fuente.dominio_publico else [],
        "extracto_oficial": cand.resumen[:700] if fuente.dominio_publico else "",
        "oficial": oficial,
        "fecha": a_iso(cand.fecha or momento),
        "ingresado": a_iso(momento),
        "fuentes_adicionales": [],
        "verificacion": {
            "citas_verificadas": anclaje.verificadas,
            "citas_total": anclaje.total,
            "modo": cand.modo_ia,
            "avisos": [a for a in avisos if not a.startswith("SALIDA")][:5],
        },
        "modelo": modelo,
    }


class Pipeline:
    def __init__(self, ajustes: Ajustes, *, ia: ClienteIA | None = None, http: ClienteHTTP | None = None,
                 almacen: Almacen | None = None, claves: list[str] | None = None) -> None:
        self.ajustes = ajustes
        self.almacen = almacen or Almacen(ajustes.dir_datos).cargar()
        self.http = http or ClienteHTTP()
        self._ia = ia
        self.fuentes = registro.construir(self.http, claves or ajustes.fuentes_activas, ajustes.max_candidatos_fuente)
        self.mapa = {f.clave: f for f in self.fuentes}
        self.dominios = registro.dominios_permitidos()
        self.resumen = Resumen()

    @property
    def ia(self) -> ClienteIA:
        if self._ia is None:
            self._ia = ClienteGemini(self.ajustes, self.almacen)
        return self._ia

    # ------------------------------------------------------------------ 1. recolección
    def recolectar(self) -> list[Candidato]:
        todos: list[Candidato] = []
        for fuente in self.fuentes:
            t0 = time.monotonic()
            info = {"candidatos": 0, "nuevos": 0, "ok": True}
            try:
                candidatos = fuente.listar()
                info["candidatos"] = len(candidatos)
                todos.extend(candidatos)
                log.info("%s: %d candidatos", fuente.clave, len(candidatos))
            except Exception as exc:  # una fuente rota no frena al resto
                info.update(ok=False, error=f"{type(exc).__name__}: {exc}")
                self.resumen.errores.append(f"{fuente.clave}: {exc}")
                log.error("Fuente %s falló: %s", fuente.clave, exc)
            self.resumen.por_fuente[fuente.clave] = info
            self.almacen.registrar_salud(fuente.clave, ok=info["ok"], cantidad=info["candidatos"],
                                         error=info.get("error", ""), duracion=time.monotonic() - t0)
        # Lo que quedó sin procesar en corridas anteriores (cuota agotada) va primero.
        previos = [Candidato.desde_dict(p) for p in self.almacen.tomar_pendientes()]
        previos = [c for c in previos if c.fuente in self.mapa]
        self.resumen.candidatos = len(todos)
        return previos + todos

    # ------------------------------------------------------------------ 2. filtros gratuitos
    def _demasiado_vieja(self, cand: Candidato) -> bool:
        dias = self.mapa[cand.fuente].antiguedad_maxima or self.ajustes.max_antiguedad_dias
        return bool(cand.fecha and cand.fecha < ahora() - timedelta(days=dias))

    def filtrar(self, candidatos: list[Candidato]) -> list[Candidato]:
        vistos_corrida: set[str] = set()
        nuevos: list[Candidato] = []
        for cand in candidatos:
            h = cand.url_hash
            if h in vistos_corrida:
                continue
            vistos_corrida.add(h)
            es_pendiente = h in self.almacen.pendientes
            if self.almacen.ya_visto(h) and not es_pendiente:
                self.resumen.ya_vistos += 1
                continue
            fuente = self.mapa[cand.fuente]
            if not dominio_permitido(cand.url, self.dominios):
                self.almacen.registrar_cuarentena(url=cand.url, fuente=cand.fuente, capa="dominio",
                                                  motivo="Dominio fuera de la allowlist", extracto=cand.titulo)
                self.almacen.marcar_visto(h, "cuarentena", fuente=cand.fuente)
                self.resumen.cuarentena += 1
                continue
            if self._demasiado_vieja(cand) and not es_pendiente:
                self.almacen.marcar_visto(h, "antiguo", fuente=cand.fuente)
                self.resumen.antiguos += 1
                continue
            motivo = fuente.prefiltro(cand)
            if motivo:
                self.almacen.marcar_visto(h, "prefiltro", fuente=cand.fuente)
                self.resumen.prefiltrados += 1
                continue
            nuevos.append(cand)
            if cand.fuente in self.resumen.por_fuente:
                self.resumen.por_fuente[cand.fuente]["nuevos"] += 1
        return nuevos

    # ------------------------------------------------------------------ 3. triage
    def _cargar_detalle(self, cand: Candidato) -> bool:
        try:
            self.mapa[cand.fuente].cargar_detalle(cand)
            return True
        except Exception as exc:
            log.warning("No se pudo leer %s: %s", cand.url, exc)
            return False

    def triage(self, candidatos: list[Candidato]) -> list[Candidato]:
        pendientes_triage = [c for c in candidatos if not c.triado]
        ya_triados = [c for c in candidatos if c.triado]
        # Fuentes cuya portada no da contexto: se lee la nota antes de decidir.
        previos = 0
        for cand in list(pendientes_triage):
            fuente = self.mapa[cand.fuente]
            if fuente.detalle_antes_del_triage and not cand.detalle_cargado and previos < MAX_DETALLES_PREVIOS:
                previos += 1
                self._cargar_detalle(cand)
                # Con el texto completo, las reglas gratuitas vuelven a mirar (p. ej. prórrogas de
                # designación, o la fecha, que algunas fuentes sólo muestran dentro de la nota).
                if fuente.prefiltro(cand):
                    self.almacen.marcar_visto(cand.url_hash, "prefiltro", fuente=cand.fuente)
                    self.resumen.prefiltrados += 1
                    pendientes_triage.remove(cand)
                elif self._demasiado_vieja(cand):
                    self.almacen.marcar_visto(cand.url_hash, "antiguo", fuente=cand.fuente)
                    self.resumen.antiguos += 1
                    pendientes_triage.remove(cand)
        relevantes: list[Candidato] = []
        for inicio in range(0, len(pendientes_triage), TAMANO_LOTE_TRIAGE):
            lote = pendientes_triage[inicio: inicio + TAMANO_LOTE_TRIAGE]
            try:
                veredictos = triage_lote(self.ia, lote, self.ajustes.perfil_editorial)
            except SinCuota:
                self._encolar(pendientes_triage[inicio:])
                self.resumen.sin_cuota = True
                break
            except ErrorIA as exc:
                log.warning("Triage no disponible (%s): se curan todos los del lote.", exc)
                veredictos = {}
            for i, cand in enumerate(lote, 1):
                veredicto = veredictos.get(i)
                cand.triado = True
                if veredicto is not None and not veredicto.relevante:
                    self.almacen.marcar_visto(cand.url_hash, "descartado_triage", fuente=cand.fuente)
                    self.resumen.descartados_triage += 1
                else:
                    relevantes.append(cand)
        return ya_triados + relevantes

    def _encolar(self, candidatos: list[Candidato]) -> None:
        for cand in candidatos:
            self.almacen.encolar_pendiente(cand.url_hash, cand.a_dict())
        self.resumen.pendientes += len(candidatos)

    # ------------------------------------------------------------------ 4. curaduría y publicación
    def procesar(self, candidatos: list[Candidato]) -> None:
        ordenados = sorted(
            candidatos,
            key=lambda c: (self.mapa[c.fuente].prioridad, a_iso(c.fecha) or ""),
            reverse=True,
        )
        tope = self.ajustes.max_curadas_por_corrida
        if len(ordenados) > tope:
            self._encolar(ordenados[tope:])
            ordenados = ordenados[:tope]
        dedup = Deduplicador(self.almacen, self.ia, self.ajustes.ventana_dedup_dias,
                             self.ajustes.umbral_gris, self.ajustes.umbral_auto)

        for posicion, cand in enumerate(ordenados):
            try:
                self._procesar_uno(cand, dedup)
            except SinCuota:
                self.resumen.sin_cuota = True
                self._encolar(ordenados[posicion:])
                log.warning("Cuota de IA agotada: %d piezas quedan para la próxima corrida.", len(ordenados) - posicion)
                break
            except ErrorIA as exc:
                self.resumen.errores.append(f"IA en {cand.url}: {exc}")
                cand.intentos += 1
                self._encolar([cand])
            except Exception as exc:  # nunca frenar la corrida por una pieza
                log.exception("Error procesando %s", cand.url)
                self.resumen.errores.append(f"{cand.url}: {exc}")
                cand.intentos += 1
                self._encolar([cand])

    def _cuarentena(self, cand: Candidato, capa: str, motivo: str) -> None:
        log.warning("Cuarentena [%s] %s: %s", capa, cand.url, motivo)
        self.almacen.registrar_cuarentena(url=cand.url, fuente=cand.fuente, capa=capa, motivo=motivo,
                                          extracto=f"{cand.titulo}\n{cand.texto_para_ia()}")
        self.almacen.marcar_visto(cand.url_hash, "cuarentena", fuente=cand.fuente)
        self.resumen.cuarentena += 1

    def _procesar_uno(self, cand: Candidato, dedup: Deduplicador) -> None:
        fuente = self.mapa[cand.fuente]
        if not cand.detalle_cargado and not self._cargar_detalle(cand):
            if len(cand.resumen) < 80:
                cand.intentos += 1
                self._encolar([cand])
                return

        # Señales de contenido del sitio (robots.txt): con el plan gratuito, "ai-train=no" se respeta.
        if not self.ajustes.ia_plan_pago and self.http.senales_contenido(cand.url).get("ai-train") == "no":
            cand.modo_ia = "referencia"
            if not cand.resumen:
                cand.resumen = limpiar_espacios(cand.texto[:300])

        texto_fuente = limpiar_espacios(f"{cand.titulo}. {cand.texto_para_ia()}")
        if len(texto_fuente) < 60:
            self.almacen.marcar_visto(cand.url_hash, "sin_contenido", fuente=cand.fuente)
            return

        # Capa 1: heurística (antes de gastar cuota).
        oculto = " ".join(a.split(":", 1)[1] for a in cand.alertas_seguridad if a.startswith("oculto:"))
        riesgo = escanear_inyeccion(texto_fuente, oculto)
        if riesgo.bloquear:
            self._cuarentena(cand, "heuristica", "; ".join(riesgo.motivos))
            return
        if riesgo.nivel == "medio":
            cand.alertas_seguridad.append("riesgo_medio: " + "; ".join(riesgo.motivos))

        # Capa 2: curaduría aislada.
        ficha: FichaCurada = curar(self.ia, cand, self.ajustes.perfil_editorial)
        self.resumen.curados += 1
        if ficha.posible_prompt_injection:
            self._cuarentena(cand, "llm_injection", ficha.motivo_seguridad or "El curador detectó instrucciones dirigidas a la IA")
            return
        if not ficha.es_relevante:
            self.almacen.marcar_visto(cand.url_hash, "descartado_ia", fuente=cand.fuente)
            self.resumen.descartados_ia += 1
            return

        # Capa 3: citas verificables + saneamiento de salida.
        minimo = 1 if cand.modo_ia == "referencia" else fuente.min_citas
        anclaje = verificar_anclaje(texto_fuente, ficha.citas_textuales_verificables, minimo)
        if not anclaje.ok:
            self._cuarentena(cand, "grounding", anclaje.detalle)
            return
        datos, avisos = sanear_salida(ficha.model_dump(), texto_fuente, cand.oficial)
        if any(a.startswith("SALIDA_SOSPECHOSA") for a in avisos):
            self._cuarentena(cand, "salida", "; ".join(avisos))
            return

        registro_nuevo = _construir_registro(cand, datos, fuente, anclaje, avisos, self.ia.modelo_texto)

        # Capa 4: deduplicación multi-fuente.
        embedding = self.ia.embedding(texto_semantico(registro_nuevo))
        existente = dedup.buscar(registro_nuevo, embedding)
        if existente:
            accion = fusionar(self.almacen, existente, registro_nuevo, embedding)
            self.almacen.marcar_visto(cand.url_hash, "fusionado", existente["id"], cand.fuente)
            self.resumen.fusionados += 1
            log.info("Duplicado (%s): %s → %s", accion, cand.fuente, existente["id"])
            return

        self.almacen.agregar_novedad(registro_nuevo, embedding)
        self.almacen.marcar_visto(cand.url_hash, "publicado", registro_nuevo["id"], cand.fuente)
        self.resumen.publicados += 1
        self.resumen.nuevas.append(registro_nuevo["id"])
        log.info("Publicado [%s | %s] %s", cand.fuente, registro_nuevo["materia"], registro_nuevo["titulo"])

    # ------------------------------------------------------------------ corrida completa
    def ejecutar(self, guardar: bool = True) -> Resumen:
        t0 = time.monotonic()
        try:
            candidatos = self.filtrar(self.recolectar())
            log.info("Nuevos a evaluar: %d", len(candidatos))
            if candidatos:
                _ = self.ia  # falla rápido y con un mensaje claro si falta la clave de Gemini
                relevantes = self.triage(candidatos)
                log.info("Relevantes tras triage: %d", len(relevantes))
                self.procesar(relevantes)
            self.resumen.modelo = self.ia.modelo_texto if self._ia else ""
        finally:
            self.resumen.fin = a_iso(ahora()) or ""
            self.resumen.duracion_s = round(time.monotonic() - t0, 1)
            if guardar:
                self.almacen.guardar()
                (self.ajustes.dir_datos / "ultima_ejecucion.json").write_text(
                    json.dumps(asdict(self.resumen), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
                )
            self.http.cerrar()
        _resumen_github(self.resumen)
        return self.resumen


def _resumen_github(resumen: Resumen) -> None:
    """En GitHub Actions, deja el resumen visible en la página de la corrida."""
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    if not destino:
        return
    try:
        with open(destino, "a", encoding="utf-8") as fh:
            fh.write("## Monitor Jurídico AR — resultado de la corrida\n\n```\n" + resumen.texto() + "\n```\n")
    except OSError:
        pass
