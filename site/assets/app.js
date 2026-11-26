/* Monitor Jurídico AR — portal estático.
 * Todo lo que viene de los datos se inserta como texto (textContent), nunca como HTML:
 * las fichas se originan en páginas de terceros y no se confía en ellas. */
(() => {
  "use strict";

  // ------------------------------------------------------------------ constantes
  const MATERIAS = [
    ["Penal", "penal"], ["Constitucional", "constitucional"], ["Civil y Comercial", "civil"], ["Familia", "familia"],
    ["Laboral", "laboral"], ["Previsional", "previsional"], ["Contencioso Administrativo", "administrativo"],
    ["Tributario", "tributario"], ["Consumo", "consumo"], ["Derechos Humanos", "ddhh"], ["Institucional", "institucional"],
  ];
  const COLOR = Object.fromEntries(MATERIAS.map(([n, k]) => [n, `var(--m-${k})`]));
  const CORTO_MATERIA = { "Contencioso Administrativo": "Contencioso adm.", "Derechos Humanos": "DD. HH." };
  const TIPOS = ["Fallo", "Dictamen", "Norma", "Acordada", "Doctrina", "Noticia"];
  const CORTO_FUENTE = {
    csjn: "CSJN", csjn_noticias: "CSJN", infoleg: "InfoLeg", bora: "Boletín Oficial", saij: "SAIJ",
    saij_tdf: "SAIJ (TDF)", saij_boletin: "Boletín del SAIJ", mpf: "MPF",
    justicia_ar: "Justicia.ar", ijudicial: "iJudicial", palabras_derecho: "Palabras del Derecho",
    pensamiento_penal: "Pensamiento Penal", app: "APP", aldia: "Al Día (Microjuris)", diario_judicial: "Diario Judicial",
    eldial: "elDial", infobae: "Infobae",
  };
  let DOMINIOS = ["csjn.gov.ar", "infoleg.gob.ar", "boletinoficial.gob.ar", "saij.gob.ar", "fiscales.gob.ar",
    "justicia.ar", "ijudicial.gob.ar", "palabrasdelderecho.com.ar", "pensamientopenal.com.ar",
    "pensamientopenal.org", "aldiaargentina.microjuris.com", "diariojudicial.com", "eldial.com", "infobae.com"];
  const ZONA = "America/Argentina/Buenos_Aires";
  const PASO = 60;
  const EN_MARCO = (() => { try { return window.self !== window.top; } catch (e) { return true; } })();

  // ------------------------------------------------------------------ utilidades
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const leer = (k, d) => { try { const v = localStorage.getItem("mj:" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } };
  const guardar = (k, v) => { try { localStorage.setItem("mj:" + k, JSON.stringify(v)); } catch (e) { /* sin almacenamiento */ } };

  function el(tag, props, ...hijos) {
    const n = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === "class") n.className = v;
        else if (k === "style") for (const [p, val] of Object.entries(v)) n.style.setProperty(p, val);
        else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
        else if (k === "dataset") Object.assign(n.dataset, v);
        else n.setAttribute(k, v === true ? "" : String(v));
      }
    }
    for (const h of hijos.flat(Infinity)) {
      if (h == null || h === false || h === "") continue;
      n.append(h instanceof Node ? h : document.createTextNode(String(h)));
    }
    return n;
  }

  const ICONOS = {
    guardar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
    externo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
    copiar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
  };
  function icono(nombre) {
    const t = document.createElement("template");
    t.innerHTML = ICONOS[nombre]; // cadenas fijas del propio código, nunca datos
    return t.content.firstChild;
  }

  const plegarCar = (c) => { const f = c.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); return f.length === 1 ? f : (f[0] || " "); };
  const plegar = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/(\d)\.(?=\d{3}\b)/g, "$1");
  function plegarAlineado(s) { let o = ""; for (let i = 0; i < s.length; i++) o += plegarCar(s[i]); return o; }
  const tokensDe = (q) => plegar(q).split(/[\s,;]+/).map((t) => t.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")).filter((t) => t.length >= 2);

  function resaltar(texto, tokens) {
    const frag = document.createDocumentFragment();
    texto = texto || "";
    if (!tokens.length) { frag.append(texto); return frag; }
    const base = plegarAlineado(texto);
    const rangos = [];
    for (const t of tokens) {
      let i = 0;
      while ((i = base.indexOf(t, i)) !== -1) { rangos.push([i, i + t.length]); i += t.length; }
    }
    rangos.sort((a, b) => a[0] - b[0]);
    let pos = 0;
    for (const [a, b] of rangos) {
      if (b <= pos) continue;
      const ini = Math.max(a, pos);
      if (ini > pos) frag.append(texto.slice(pos, ini));
      frag.append(el("mark", null, texto.slice(ini, b)));
      pos = b;
    }
    frag.append(texto.slice(pos));
    return frag;
  }

  function urlSegura(u) {
    try {
      const url = new URL(u);
      if (url.protocol !== "https:" && url.protocol !== "http:") return null;
      const host = url.hostname.toLowerCase();
      return DOMINIOS.some((d) => host === d || host.endsWith("." + d)) ? url.href : null;
    } catch (e) { return null; }
  }
  const idValido = (id) => typeof id === "string" && /^[a-z0-9]{6,40}$/i.test(id);

  // ------------------------------------------------------------------ fechas
  const fFecha = (o) => new Intl.DateTimeFormat("es-AR", { timeZone: ZONA, ...o });
  const F_DIA = fFecha({ weekday: "long", day: "numeric", month: "long" });
  const F_DIA_ANIO = fFecha({ weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const F_CORTA = fFecha({ day: "numeric", month: "short" });
  const F_LARGA = fFecha({ day: "numeric", month: "long", year: "numeric" });
  const F_HORA = fFecha({ hour: "2-digit", minute: "2-digit" });
  const F_CLAVE = fFecha({ year: "numeric", month: "2-digit", day: "2-digit" });
  const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const aFecha = (iso) => { const d = new Date(iso); return isNaN(d) ? null : d; };
  function claveDia(d) {
    const p = Object.fromEntries(F_CLAVE.formatToParts(d).map((x) => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day}`;
  }
  function rotuloDia(clave) {
    const hoy = claveDia(new Date());
    const ayer = claveDia(new Date(Date.now() - 864e5));
    if (clave === hoy) return "Hoy";
    if (clave === ayer) return "Ayer";
    const d = new Date(clave + "T12:00:00-03:00");
    return capital((d.getFullYear() === new Date().getFullYear() ? F_DIA : F_DIA_ANIO).format(d));
  }
  function hace(iso) {
    const d = aFecha(iso);
    if (!d) return "";
    const min = Math.round((Date.now() - d) / 6e4);
    if (min < 2) return "recién";
    if (min < 60) return `hace ${min} min`;
    const h = Math.round(min / 60);
    if (h < 24) return `hace ${h} h`;
    const dias = Math.round(h / 24);
    return dias === 1 ? "ayer" : `hace ${dias} días`;
  }
  const fechaCorta = (iso) => { const d = aFecha(iso); return d ? F_CORTA.format(d).replace(".", "") : ""; };
  const fechaLarga = (iso) => { const d = aFecha(iso); return d ? F_LARGA.format(d) : ""; };

  // ------------------------------------------------------------------ estado
  const estado = {
    meta: null,
    porId: new Map(),
    items: [],
    cargado: false,
    error: null,
    filtros: { materia: "", rango: 0, fuente: "", tipo: "", impacto: false, biblioteca: false, nuevas: false, q: "" },
    vista: leer("vista", "tarjetas"),
    escala: leer("escala", 1),
    biblioteca: leer("biblioteca", {}),
    ultimaVisita: leer("ultima_visita", null),
    mesesCargados: new Set(),
    limite: PASO,
    lista: [],
    abierta: null,
    abiertaPorClic: false,
    pendiente: null,
  };
  if (typeof estado.biblioteca !== "object" || Array.isArray(estado.biblioteca) || !estado.biblioteca) estado.biblioteca = {};

  function preparar(it) {
    const d = aFecha(it.fecha) || aFecha(it.ingresado) || new Date();
    const autos = [it.caratula, it.identificador_legal].filter(Boolean).join(" ");
    const temas = [...(it.etiquetas || []), ...(it.normas_citadas || [])].join(" ");
    const corto = CORTO_FUENTE[it.fuente] || it.fuente_nombre || "";
    return Object.assign({}, it, {
      _t: d.getTime(),
      _dia: claveDia(d),
      _ftit: plegar(it.titulo),
      _fid: plegar(autos),
      _ftag: plegar(temas),
      _busq: plegar([it.titulo, it.bajada, it.holding, autos, temas, it.tribunal, corto, it.fuente_nombre,
        (it.puntos_clave || []).join(" "), it.materia, it.tipo, it.jurisdiccion].join(" ")),
      _nuevo: !!(estado.ultimaVisita && it.ingresado && it.ingresado > estado.ultimaVisita),
    });
  }
  const valido = (it) => it && idValido(it.id) && typeof it.titulo === "string" && it.titulo.length > 0;
  const ordenar = (a, b) => b._t - a._t || (b.ingresado || "").localeCompare(a.ingresado || "");

  function incorporar(items) {
    for (const it of items || []) if (valido(it)) estado.porId.set(it.id, preparar(it));
    estado.items = Array.from(estado.porId.values()).sort(ordenar);
  }

  async function cargarJSON(ruta) {
    const r = await fetch(ruta, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${ruta} respondió ${r.status}`);
    return r.json();
  }

  async function cargar() {
    const [meta, ultimas] = await Promise.all([cargarJSON("data/meta.json"), cargarJSON("data/ultimas.json")]);
    estado.meta = meta;
    if (Array.isArray(meta.dominios) && meta.dominios.length) DOMINIOS = meta.dominios.filter((d) => typeof d === "string" && /^[a-z0-9.-]+$/.test(d));
    incorporar(ultimas.items);
    estado.cargado = true;
    estado.error = null;
  }

  // ------------------------------------------------------------------ filtrado
  const sinFiltros = () => {
    const f = estado.filtros;
    return !f.materia && !f.rango && !f.fuente && !f.tipo && !f.impacto && !f.biblioteca && !f.nuevas && !f.q;
  };
  function base() {
    if (!estado.filtros.biblioteca) return estado.items;
    return Object.values(estado.biblioteca).filter(valido).map(preparar)
      .sort((a, b) => (b._guardado || "").localeCompare(a._guardado || "") || ordenar(a, b));
  }
  function filtrar(items, ignorar = "") {
    const f = estado.filtros;
    const tokens = tokensDe(f.q);
    const desde = f.rango ? Date.now() - f.rango * 864e5 : 0;
    const hoy = claveDia(new Date());
    return items.filter((it) => {
      if (ignorar !== "materia" && f.materia && it.materia !== f.materia) return false;
      if (f.rango === 1 ? it._dia !== hoy : (desde && it._t < desde)) return false;
      if (f.fuente && it.fuente !== f.fuente && !(it.fuentes_adicionales || []).some((a) => a.fuente === f.fuente)) return false;
      if (f.tipo && it.tipo !== f.tipo) return false;
      if (f.impacto && !it.alto_impacto) return false;
      if (f.nuevas && !it._nuevo) return false;
      for (const t of tokens) if (!it._busq.includes(t)) return false;
      return true;
    });
  }

  // ------------------------------------------------------------------ piezas comunes
  const organo = (it) => it.instancia === "CSJN" ? "Corte Suprema" : (it.tribunal || "").slice(0, 60);
  const verificado = (it) => it.verificacion && it.verificacion.citas_verificadas > 0;
  const enBiblioteca = (id) => Object.prototype.hasOwnProperty.call(estado.biblioteca, id);

  function textoFuentes(it) {
    const principal = CORTO_FUENTE[it.fuente] || it.fuente_nombre;
    const n = (it.fuentes_adicionales || []).length;
    return n ? `${principal} y ${n === 1 ? "1 cobertura más" : n + " coberturas más"}` : principal;
  }

  function botonGuardar(it, clase = "guardar") {
    const activo = enBiblioteca(it.id);
    const b = el("button", {
      class: clase, type: "button", "aria-pressed": activo ? "true" : "false",
      "aria-label": activo ? `Quitar de mi biblioteca: ${it.titulo}` : `Guardar en mi biblioteca: ${it.titulo}`,
      dataset: { guardar: it.id },
    }, icono("guardar"));
    return b;
  }

  function sello(it, animar) {
    const v = it.verificacion || {};
    const ref = v.modo === "referencia";
    return el("div", {
      class: "sello" + (animar ? " estampar" : ""),
      title: `${v.citas_verificadas} de ${v.citas_total} citas textuales de la IA coinciden con el texto publicado por la fuente`,
    }, ref ? "Verificado con la bajada" : "Verificado en la fuente",
    el("small", null, `${v.citas_verificadas} de ${v.citas_total} ${v.citas_total === 1 ? "cita" : "citas"}`));
  }

  function enlaceExterno(url, texto, clase) {
    const segura = urlSegura(url);
    if (!segura) return null;
    return el("a", { class: clase, href: segura, target: "_blank", rel: "noopener noreferrer" }, texto, icono("externo"));
  }

  // ------------------------------------------------------------------ cabecera
  function pintarCabecera() {
    const meta = estado.meta;
    if (meta && meta.portal && meta.portal.nombre) {
      $("#nombre-portal").textContent = meta.portal.nombre;
      document.title = meta.portal.nombre;
    }
    $("#fecha-edicion").textContent = "Edición del " + F_DIA_ANIO.format(new Date());
    const sync = $("#estado-sync");
    if (meta && meta.generado) {
      sync.textContent = `Actualizado ${hace(meta.generado)}`;
      const d = aFecha(meta.generado);
      sync.title = d ? `Última sincronización: ${F_LARGA.format(d)}, ${F_HORA.format(d)} h` : "";
    }
    $("#cuenta-biblioteca").textContent = String(Object.keys(estado.biblioteca).length);
    $("#btn-biblioteca").setAttribute("aria-pressed", estado.filtros.biblioteca ? "true" : "false");
  }

  // ------------------------------------------------------------------ filtros
  function pintarFiltros() {
    const f = estado.filtros;
    const conteo = {};
    for (const it of filtrar(base(), "materia")) conteo[it.materia] = (conteo[it.materia] || 0) + 1;
    const total = Object.values(conteo).reduce((a, b) => a + b, 0);
    const chips = [el("button", { class: "chip", type: "button", "aria-pressed": !f.materia ? "true" : "false", dataset: { materia: "" } },
      "Todas", el("span", { class: "n" }, String(total)))];
    for (const [nombre] of MATERIAS) {
      if (!conteo[nombre] && f.materia !== nombre) continue;
      chips.push(el("button", {
        class: "chip", type: "button", "aria-pressed": f.materia === nombre ? "true" : "false", dataset: { materia: nombre },
      }, el("span", { class: "punto", style: { "--c": COLOR[nombre] } }), CORTO_MATERIA[nombre] || nombre,
      el("span", { class: "n" }, String(conteo[nombre] || 0))));
    }
    $("#materias").replaceChildren(...chips);

    for (const b of $$("#rango button")) b.setAttribute("aria-pressed", String(Number(b.dataset.rango) === f.rango));
    for (const b of $$("#vista button")) b.setAttribute("aria-pressed", String(b.dataset.vista === estado.vista));
    $("#btn-impacto").setAttribute("aria-pressed", String(f.impacto));

    const selFuente = $("#fuente");
    if (estado.meta && selFuente.options.length === 1) {
      for (const fu of estado.meta.fuentes || []) selFuente.append(el("option", { value: fu.clave }, fu.nombre));
    }
    selFuente.value = f.fuente;
    const selTipo = $("#tipo");
    if (selTipo.options.length === 1) for (const t of TIPOS) selTipo.append(el("option", { value: t }, t === "Noticia" ? "Noticias" : t + "s"));
    selTipo.value = f.tipo;

    const activos = [];
    if (f.q) activos.push(el("button", { class: "etiqueta-filtro", type: "button", dataset: { quitar: "q" }, "aria-label": `Quitar la búsqueda ${f.q}` }, `Búsqueda: ${f.q}`, " ✕"));
    if (f.biblioteca) {
      activos.push(el("button", { class: "etiqueta-filtro", type: "button", dataset: { quitar: "biblioteca" } }, "Mi biblioteca ✕"));
      if (Object.keys(estado.biblioteca).length) activos.push(el("button", { class: "etiqueta-filtro", type: "button", dataset: { accion: "copiar-biblioteca" } }, "Copiar todas las citas"));
    }
    if (f.nuevas) activos.push(el("button", { class: "etiqueta-filtro", type: "button", dataset: { quitar: "nuevas" } }, "Nuevas desde tu última visita ✕"));
    $("#activos").replaceChildren(...activos);
  }

  // ------------------------------------------------------------------ portada
  function elegirDestacado(items) {
    const limite = Date.now() - 12 * 864e5;
    return items.find((i) => i.instancia === "CSJN" && i._t >= limite)
      || items.find((i) => i.alto_impacto && i._t >= limite)
      || items[0];
  }

  function pintarPortada() {
    const portada = $("#portada");
    if (!sinFiltros() || !estado.items.length) { portada.hidden = true; return null; }
    const items = estado.items;
    const hero = elegirDestacado(items);
    const autos = hero.caratula;
    const expte = hero.identificador_legal;
    const fuente = enlaceExterno(hero.url, `Ir a ${CORTO_FUENTE[hero.fuente] || "la fuente"}`, "boton");
    const caratula = el("article", { class: "caratula", "aria-labelledby": "t-destacado" },
      el("div", { class: "caratula-marco" },
        verificado(hero) && sello(hero, false),
        el("p", { class: "caratula-org" }, el("span", null, hero.tribunal || hero.fuente_nombre), el("time", { datetime: hero.fecha }, fechaLarga(hero.fecha))),
        el("h2", { id: "t-destacado" }, el("a", { href: "#n-" + hero.id }, hero.titulo)),
        (autos || expte) && el("div", { class: "caratula-autos" },
          autos && el("span", { class: "autos" }, autos),
          expte && el("span", { class: "expte" }, "Expte. " + expte)),
        hero.bajada && el("p", { class: "bajada" }, hero.bajada),
        el("div", { class: "botones" }, el("a", { class: "boton primario", href: "#n-" + hero.id }, "Leer la ficha"), fuente)));

    const normas = items.filter((i) => i.tipo === "Norma" || i.fuente === "bora").slice(0, 5);
    const panelNormas = el("section", { class: "panel", "aria-labelledby": "t-normas" },
      el("h2", { id: "t-normas" }, "Normativa reciente"),
      normas.length
        ? el("ul", { class: "normas" }, normas.map((n) => el("li", null, el("a", { href: "#n-" + n.id },
          el("span", { class: "id" }, n.identificador_legal || fechaCorta(n.fecha)),
          el("span", { class: "t" }, n.titulo)))))
        : el("p", { class: "nota-panel" }, "Sin normas nuevas en los últimos días."));

    const semana = items.filter((i) => i._t >= Date.now() - 7 * 864e5);
    const porMateria = {};
    for (const i of semana) porMateria[i.materia] = (porMateria[i.materia] || 0) + 1;
    const filas = Object.entries(porMateria).sort((a, b) => b[1] - a[1]).slice(0, 7);
    const maximo = Math.max(1, ...filas.map((f) => f[1]));
    const panelPulso = el("section", { class: "panel", "aria-labelledby": "t-pulso" },
      el("h2", { id: "t-pulso" }, "La semana por materia"),
      el("p", { class: "nota-panel" }, `${semana.length} ${semana.length === 1 ? "novedad" : "novedades"} en los últimos 7 días`),
      filas.length
        ? el("ul", { class: "barras" }, filas.map(([m, n]) => el("li", null,
          el("button", { type: "button", dataset: { materia: m }, title: `Ver ${m}` }, CORTO_MATERIA[m] || m),
          el("span", { class: "riel", "aria-hidden": "true" }, el("span", { class: "relleno", style: { width: `${(n / maximo) * 100}%`, "--c": COLOR[m] || "var(--sello)" } })),
          el("span", { class: "cant" }, String(n)))))
        : el("p", { class: "nota-panel" }, "Todavía no hay datos de esta semana."));

    portada.replaceChildren(caratula, el("div", { class: "costado" }, panelNormas, panelPulso));
    portada.hidden = false;
    return hero.id;
  }

  // ------------------------------------------------------------------ listado
  function tarjeta(it, tokens) {
    return el("article", { class: "nota", dataset: { id: it.id } },
      el("div", { class: "nota-meta" },
        el("span", { class: "mat", style: { "--c": COLOR[it.materia] || "var(--tenue)" } }, CORTO_MATERIA[it.materia] || it.materia || "Sin materia"),
        organo(it) && el("span", null, organo(it)),
        el("time", { datetime: it.fecha }, fechaCorta(it.fecha)),
        it.alto_impacto && el("span", { class: "impacto" }, "Alto impacto"),
        it._nuevo && el("span", { class: "nuevo" }, "Nuevo")),
      el("h3", null, el("a", { href: "#n-" + it.id }, resaltar(it.titulo, tokens))),
      it.bajada && el("p", { class: "bajada" }, resaltar(it.bajada, tokens)),
      (it.caratula || it.identificador_legal) && el("p", { class: "autos" },
        it.caratula && el("span", null, resaltar(it.caratula, tokens)),
        it.identificador_legal && el("span", { class: "expte" }, resaltar("Expte. " + it.identificador_legal, tokens))),
      el("div", { class: "nota-pie" },
        el("span", { class: "fuentes" }, textoFuentes(it)),
        verificado(it) && el("span", { class: "marca-sello", title: "Citas verificadas contra la fuente" }, "Verificado"),
        botonGuardar(it)));
  }

  function fila(it, tokens) {
    return el("div", { class: "fila", dataset: { id: it.id } },
      el("time", { class: "f", datetime: it.fecha }, fechaCorta(it.fecha)),
      el("span", { class: "mat", style: { "--c": COLOR[it.materia] || "var(--tenue)" } }, CORTO_MATERIA[it.materia] || it.materia),
      el("a", { href: "#n-" + it.id }, resaltar(it.titulo, tokens)),
      el("span", { class: "org" }, organo(it)),
      botonGuardar(it));
  }

  function vacio(titulo, texto, ...botones) {
    return el("div", { class: "vacio" }, el("h2", null, titulo), el("p", null, texto), botones.length && el("div", { class: "botones" }, botones));
  }

  function pintarListado(excluir) {
    const destino = $("#listado");
    const f = estado.filtros;
    const tokens = tokensDe(f.q);
    if (estado.error && !estado.items.length) {
      destino.replaceChildren(vacio("No se pudieron cargar las novedades",
        location.protocol === "file:"
          ? "El navegador no deja leer los datos si abrís el archivo directamente. Desde la carpeta del proyecto, ejecutá python scripts/servir.py y entrá a la dirección que muestra."
          : "Revisá la conexión y volvé a intentar. Si el problema sigue, la última sincronización puede haber fallado.",
        el("button", { class: "boton primario", type: "button", dataset: { accion: "reintentar" } }, "Reintentar")));
      estado.lista = [];
      return;
    }
    if (!estado.cargado) return;
    const lista = filtrar(base()).filter((it) => it.id !== excluir);
    estado.lista = excluir && estado.porId.has(excluir) ? [estado.porId.get(excluir), ...lista] : lista;
    if (!estado.items.length && !f.biblioteca) {
      destino.replaceChildren(vacio("Todavía no hay novedades publicadas",
        "La sincronización corre dos veces por día. Si recién instalaste el portal, ejecutá el flujo «Sincronizar» desde la pestaña Actions del repositorio."));
      return;
    }
    if (!lista.length) {
      destino.replaceChildren(f.biblioteca && !Object.keys(estado.biblioteca).length
        ? vacio("Tu biblioteca está vacía", "Guardá fichas con el marcador para tenerlas a mano. Se guardan sólo en este navegador.",
          el("button", { class: "boton", type: "button", dataset: { quitar: "biblioteca" } }, "Volver a las novedades"))
        : vacio("Ninguna novedad coincide con estos filtros", "Probá con otro período o materia, o buscá en los meses anteriores.",
          el("button", { class: "boton primario", type: "button", dataset: { accion: "limpiar" } }, "Quitar filtros")));
      return;
    }
    const visibles = lista.slice(0, estado.limite);
    const grupos = new Map();
    for (const it of visibles) {
      const clave = f.biblioteca ? "biblioteca" : it._dia;
      if (!grupos.has(clave)) grupos.set(clave, []);
      grupos.get(clave).push(it);
    }
    const conteoDia = {};
    for (const it of lista) conteoDia[it._dia] = (conteoDia[it._dia] || 0) + 1;
    const secciones = [];
    for (const [clave, items] of grupos) {
      const n = clave === "biblioteca" ? lista.length : conteoDia[clave];
      const titulo = clave === "biblioteca" ? "Guardadas en este navegador" : rotuloDia(clave);
      const cuerpo = estado.vista === "lista"
        ? el("div", { class: "lista" }, items.map((it) => fila(it, tokens)))
        : el("div", { class: "grilla" }, items.map((it) => tarjeta(it, tokens)));
      secciones.push(el("section", { class: "dia", "aria-label": titulo },
        el("h2", null, titulo, el("span", null, `${n} ${n === 1 ? "novedad" : "novedades"}`)), cuerpo));
    }
    destino.replaceChildren(...secciones);

    const mas = [];
    if (lista.length > estado.limite) mas.push(el("button", { class: "boton", type: "button", dataset: { accion: "mostrar-mas" } }, `Mostrar ${Math.min(PASO, lista.length - estado.limite)} más`));
    const mes = mesPorCargar();
    if (mes && !f.biblioteca) mas.push(el("button", { class: "boton", type: "button", dataset: { accion: "archivo", mes: mes.mes } }, `Cargar el archivo de ${nombreMes(mes.mes)}`));
    $("#mas").replaceChildren(...mas);
  }

  function nombreMes(clave) {
    const [a, m] = clave.split("-").map(Number);
    return new Intl.DateTimeFormat("es-AR", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(a, m - 1, 15)));
  }
  function mesPorCargar() {
    if (!estado.meta) return null;
    const presentes = {};
    for (const it of estado.items) { const k = (it.fecha || "").slice(0, 7); presentes[k] = (presentes[k] || 0) + 1; }
    return (estado.meta.meses || []).find((m) => /^\d{4}-\d{2}$/.test(m.mes) && !estado.mesesCargados.has(m.mes) && (presentes[m.mes] || 0) < m.cantidad) || null;
  }
  async function cargarMes(mes) {
    try {
      const datos = await cargarJSON(`data/archivo/${mes}.json`);
      estado.mesesCargados.add(mes);
      const antes = estado.porId.size;
      incorporar(datos.items);
      toast(`Se sumaron ${estado.porId.size - antes} novedades de ${nombreMes(mes)}.`);
      pintar();
    } catch (e) {
      toast("No se pudo cargar ese mes del archivo.");
    }
  }

  // ------------------------------------------------------------------ radar y avisos
  function pintarRadar() {
    const fuentes = (estado.meta && estado.meta.fuentes) || [];
    $("#radar").replaceChildren(...fuentes.map((f) => {
      let detalle;
      if (f.estado === "ok") detalle = `Leída ${hace(f.ultima)}. ${f.publicadas} ${f.publicadas === 1 ? "ficha" : "fichas"} en el portal.`;
      else if (f.estado === "error") detalle = `Con errores en ${f.fallas_consecutivas} ${f.fallas_consecutivas === 1 ? "corrida" : "corridas seguidas"}. Última lectura correcta: ${f.ultimo_ok ? hace(f.ultimo_ok) : "nunca"}.`;
      else detalle = f.ultima ? "La última lectura no trajo publicaciones." : "Todavía sin lecturas.";
      const estadoTexto = { ok: "funcionando", error: "con errores", sin_datos: "sin datos" }[f.estado] || "sin datos";
      const portada = urlSegura(f.portada);
      return el("li", { class: f.estado || "sin_datos" },
        el("span", { class: "luz", role: "img", "aria-label": estadoTexto }),
        el("span", { class: "nom" }, portada ? el("a", { href: portada, target: "_blank", rel: "noopener noreferrer" }, f.nombre) : f.nombre),
        el("span", { class: "hist", "aria-hidden": "true" }, (f.historial || []).map((ok) => el("i", { class: ok ? "" : "f" }))),
        el("span", { class: "det" }, detalle));
    }));
  }

  function pintarAviso() {
    const demo = estado.meta && typeof estado.meta.demo === "string" ? estado.meta.demo : "";
    const avisoDemo = $("#aviso-demo");
    avisoDemo.textContent = demo;
    avisoDemo.hidden = !demo;
    const aviso = $("#aviso-nuevas");
    const nuevas = estado.items.filter((i) => i._nuevo).length;
    if (!nuevas || estado.filtros.nuevas || !estado.ultimaVisita) { aviso.hidden = true; return; }
    const d = aFecha(estado.ultimaVisita);
    aviso.replaceChildren(
      el("span", null, `${nuevas === 1 ? "Hay 1 novedad" : `Hay ${nuevas} novedades`} desde tu última visita${d ? ` (${F_DIA.format(d)}, ${F_HORA.format(d)} h)` : ""}.`),
      el("button", { type: "button", dataset: { accion: "ver-nuevas" } }, nuevas === 1 ? "Verla" : "Ver sólo esas"),
      el("button", { type: "button", dataset: { accion: "marcar-vistas" } }, "Marcar como vistas"));
    aviso.hidden = false;
  }

  function pintar() {
    pintarCabecera();
    pintarFiltros();
    pintarAviso();
    const destacado = pintarPortada();
    pintarListado(destacado);
    pintarRadar();
  }

  // ------------------------------------------------------------------ lector
  const lector = $("#lector");
  const cuerpo = $("#lector-cuerpo");
  let foco = null;

  function seccion(titulo, ...contenido) {
    const partes = contenido.flat().filter(Boolean);
    return partes.length ? el("section", null, el("h3", null, titulo), partes) : null;
  }

  function abrir(id) {
    const crudo = estado.porId.get(id) || (estado.biblioteca[id] && preparar(estado.biblioteca[id]));
    if (!crudo) {
      if (!estado.cargado) { estado.pendiente = id; return; }
      toast("Esa novedad ya no está en la portada: buscala en el archivo.");
      return;
    }
    const it = crudo;
    estado.abierta = it.id;
    const v = it.verificacion || {};
    const adicionales = (it.fuentes_adicionales || []).map((a) => {
      const enlace = enlaceExterno(a.url, CORTO_FUENTE[a.fuente] || a.fuente_nombre || "Fuente", "");
      return enlace && el("li", null, enlace, a.titulo ? el("span", null, ` — ${a.titulo}`) : null);
    }).filter(Boolean);
    const temas = [...(it.normas_citadas || []), ...(it.etiquetas || [])];
    const urlFallo = it.oficial && it.oficial.url_fallo;
    const pos = estado.lista.findIndex((x) => x.id === it.id);
    const anterior = pos > 0 ? estado.lista[pos - 1] : null;
    const siguiente = pos >= 0 && pos < estado.lista.length - 1 ? estado.lista[pos + 1] : null;
    const ingreso = aFecha(it.ingresado);

    cuerpo.replaceChildren(...[
      el("p", { class: "tipo" },
        el("span", { class: "mat", style: { "--c": COLOR[it.materia] || "var(--tenue)" } }, it.materia),
        el("span", null, it.tipo), it.alto_impacto && el("span", null, "Alto impacto"), it.jurisdiccion && el("span", null, it.jurisdiccion)),
      el("h2", { id: "lector-titulo", tabindex: "-1" }, it.titulo),
      it.bajada && el("p", { class: "bajada" }, it.bajada),
      el("div", { class: "ficha" },
        el("dl", null,
          it.tribunal && [el("dt", null, "Órgano"), el("dd", null, it.tribunal)],
          el("dt", null, "Fecha"), el("dd", null, el("time", { datetime: it.fecha }, fechaLarga(it.fecha))),
          it.caratula && [el("dt", null, "Carátula"), el("dd", { class: "autos" }, it.caratula)],
          it.identificador_legal && [el("dt", null, it.tipo === "Norma" ? "Norma" : "Expediente"), el("dd", null, it.identificador_legal)],
          it.instancia && it.instancia !== "Otro" && [el("dt", null, "Instancia"), el("dd", null, it.instancia)],
          el("dt", null, "Publicado por"), el("dd", null, it.fuente_nombre)),
        verificado(it) && sello(it, true)),
      seccion("Qué se resolvió", it.holding && el("p", { class: "lectura" }, it.holding)),
      seccion("Puntos clave", (it.puntos_clave || []).length && el("ul", { class: "puntos" }, it.puntos_clave.map((p) => el("li", null, p)))),
      seccion("Impacto práctico", it.impacto_practico && el("p", { class: "lectura" }, it.impacto_practico)),
      seccion("Del texto oficial", (it.citas_textuales || []).map((c) => el("blockquote", null, `«${c}»`)),
        !(it.citas_textuales || []).length && it.extracto_oficial && el("p", { class: "extracto" }, it.extracto_oficial)),
      seccion("Normas y temas", temas.length && el("div", { class: "fichas-normas" },
        temas.map((t) => el("button", { type: "button", dataset: { buscar: t }, title: `Buscar «${t}» en el portal` }, t)))),
      seccion("Fuentes",
        el("div", { class: "botones" },
          enlaceExterno(it.url, `Leer en ${CORTO_FUENTE[it.fuente] || it.fuente_nombre}`, "boton primario"),
          urlFallo && enlaceExterno(urlFallo, "Ver el fallo completo", "boton")),
        adicionales.length && el("ul", { class: "fuentes-lista" }, el("li", null, "También lo informaron:"), adicionales)),
      seccion("Cita sugerida", it.cita_sugerida && el("div", { class: "cita" },
        el("p", null, it.cita_sugerida),
        el("button", { class: "herr", type: "button", dataset: { accion: "copiar-cita" }, "aria-label": "Copiar la cita" }, icono("copiar")))),
      el("p", { class: "descargo" },
        "Síntesis redactada con IA a partir de la publicación original. ",
        v.citas_total ? `${v.citas_verificadas} de ${v.citas_total} citas textuales fueron comprobadas por código contra la fuente. ` : "",
        v.modo === "referencia" ? "Por pedido de la fuente, la IA sólo leyó el título y la bajada. " : "",
        ingreso ? `Ingresó al portal el ${F_LARGA.format(ingreso)} a las ${F_HORA.format(ingreso)} h. ` : "",
        "Antes de citar, verificá en la fuente primaria."),
      el("nav", { class: "lector-nav", "aria-label": "Otras novedades" },
        anterior ? el("a", { class: "boton", href: "#n-" + anterior.id, title: anterior.titulo }, "Anterior") : el("span"),
        siguiente ? el("a", { class: "boton", href: "#n-" + siguiente.id, title: siguiente.titulo }, "Siguiente") : el("span")),
    ].filter(Boolean));

    const guardarBtn = $("#lec-guardar");
    guardarBtn.setAttribute("aria-pressed", String(enBiblioteca(it.id)));
    guardarBtn.querySelector("span").textContent = enBiblioteca(it.id) ? "Guardada" : "Guardar";
    $("#lec-imprimir").hidden = EN_MARCO;
    cuerpo.style.setProperty("--escala", String(estado.escala));
    cuerpo.scrollTop = 0;
    $("#progreso").style.width = "0";

    if (lector.hidden) {
      foco = document.activeElement;
      lector.classList.add("entrando");
      lector.hidden = false;
      $("#velo").hidden = false;
      document.body.classList.add("bloqueado", "lector-abierto");
      requestAnimationFrame(() => requestAnimationFrame(() => lector.classList.remove("entrando")));
    }
    $("#lector-titulo").focus({ preventScroll: true });
    document.title = `${it.titulo} — ${(estado.meta && estado.meta.portal && estado.meta.portal.nombre) || "Monitor Jurídico AR"}`;
  }

  function cerrar(desdeHash) {
    if (lector.hidden) return;
    lector.hidden = true;
    $("#velo").hidden = true;
    document.body.classList.remove("bloqueado", "lector-abierto");
    estado.abierta = null;
    document.title = (estado.meta && estado.meta.portal && estado.meta.portal.nombre) || "Monitor Jurídico AR";
    if (!desdeHash && /^#n-/.test(location.hash)) {
      if (estado.abiertaPorClic) history.back();
      else history.replaceState(null, "", location.pathname + location.search);
    }
    estado.abiertaPorClic = false;
    if (foco && document.contains(foco)) foco.focus({ preventScroll: true });
  }

  function rutear() {
    const m = location.hash.match(/^#n-([a-z0-9]{6,40})$/i);
    if (m) abrir(m[1]);
    else {
      cerrar(true);
      if (location.hash === "#biblioteca" && !estado.filtros.biblioteca) { estado.filtros.biblioteca = true; pintar(); }
    }
  }

  // ------------------------------------------------------------------ biblioteca
  function alternarGuardado(id) {
    if (enBiblioteca(id)) {
      delete estado.biblioteca[id];
      toast("Se quitó de tu biblioteca.");
    } else {
      const it = estado.porId.get(id);
      if (!it) return;
      const copia = {};
      for (const [k, v] of Object.entries(it)) if (!k.startsWith("_")) copia[k] = v;
      copia._guardado = new Date().toISOString();
      estado.biblioteca[id] = copia;
      toast("Guardada en tu biblioteca (sólo en este navegador).");
    }
    guardar("biblioteca", estado.biblioteca);
    for (const b of $$(`[data-guardar="${id}"]`)) b.setAttribute("aria-pressed", String(enBiblioteca(id)));
    if (estado.abierta === id) {
      const g = $("#lec-guardar");
      g.setAttribute("aria-pressed", String(enBiblioteca(id)));
      g.querySelector("span").textContent = enBiblioteca(id) ? "Guardada" : "Guardar";
    }
    $("#cuenta-biblioteca").textContent = String(Object.keys(estado.biblioteca).length);
    if (estado.filtros.biblioteca) pintarListado(null);
  }

  // ------------------------------------------------------------------ portapapeles y avisos
  let temporizador = null;
  function toast(texto) {
    const t = $("#toast");
    t.textContent = texto;
    t.classList.add("visible");
    clearTimeout(temporizador);
    temporizador = setTimeout(() => t.classList.remove("visible"), 3200);
  }
  async function copiar(texto, mensaje) {
    try {
      await navigator.clipboard.writeText(texto);
      toast(mensaje);
    } catch (e) {
      const area = el("textarea", { style: { position: "fixed", top: "0", left: "0", opacity: "0" } });
      area.value = texto;
      document.body.append(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
      area.remove();
      toast(ok ? mensaje : "No se pudo copiar automáticamente: seleccioná el texto y copialo a mano.");
    }
  }
  function citaCompleta(it) {
    const url = urlSegura(it.url);
    return `${it.cita_sugerida || it.titulo}${url ? `. Disponible en: ${url}` : ""}`;
  }

  // ------------------------------------------------------------------ paleta de búsqueda
  const paleta = $("#paleta");
  const entrada = $("#paleta-q");
  const resultados = $("#paleta-res");
  let opciones = [];
  let seleccion = 0;

  function puntaje(it, tokens) {
    let s = 0;
    for (const t of tokens) {
      if (!it._busq.includes(t)) return 0;
      s += 1 + (it._ftit.includes(t) ? 4 : 0) + (it._fid.includes(t) ? 4 : 0) + (it._ftag.includes(t) ? 2 : 0);
    }
    return s + Math.max(0, 2 - (Date.now() - it._t) / (15 * 864e5));
  }

  function opcionesPaleta() {
    const q = entrada.value.trim();
    const tokens = tokensDe(q);
    const salida = [];
    if (!tokens.length) {
      salida.push({ grupo: "Atajos" });
      salida.push({ accion: () => { estado.filtros.impacto = true; aplicar(); }, t: "Ver sólo lo de alto impacto" });
      salida.push({ accion: () => { estado.filtros.biblioteca = true; aplicar(); }, t: `Abrir mi biblioteca (${Object.keys(estado.biblioteca).length})` });
      salida.push({ accion: alternarTema, t: "Cambiar entre modo claro y oscuro" });
      for (const [m] of MATERIAS.slice(0, 6)) salida.push({ accion: () => { estado.filtros.materia = m; aplicar(); }, t: `Filtrar por ${m}` });
      salida.push({ grupo: "Lo último" });
      for (const it of estado.items.slice(0, 6)) salida.push({ item: it });
      return salida;
    }
    const encontrados = estado.items.map((it) => [puntaje(it, tokens), it]).filter((p) => p[0] > 0).sort((a, b) => b[0] - a[0]);
    if (!encontrados.length) {
      salida.push({ grupo: `Sin resultados para «${q}» en lo cargado` });
      const mes = mesPorCargar();
      if (mes) salida.push({ accion: () => { cerrarPaleta(); cargarMes(mes.mes); }, t: `Cargar el archivo de ${nombreMes(mes.mes)} y volver a buscar` });
      return salida;
    }
    salida.push({ accion: () => { estado.filtros.q = q; aplicar(); }, t: `Ver los ${encontrados.length} resultados en el listado` });
    salida.push({ grupo: "Novedades" });
    for (const [, it] of encontrados.slice(0, 12)) salida.push({ item: it, tokens });
    return salida;
  }

  function pintarPaleta() {
    opciones = opcionesPaleta();
    const elegibles = opciones.filter((o) => !o.grupo);
    seleccion = Math.min(seleccion, Math.max(0, elegibles.length - 1));
    let i = 0;
    resultados.replaceChildren(...opciones.map((o) => {
      if (o.grupo) return el("li", { class: "grupo", role: "presentation" }, o.grupo);
      const idx = i++;
      const props = { role: "option", id: `op-${idx}`, "aria-selected": String(idx === seleccion), dataset: { idx: String(idx) } };
      if (o.item) {
        const it = o.item;
        return el("li", props,
          el("span", { class: "t" }, resaltar(it.titulo, o.tokens || [])),
          el("span", { class: "s" }, el("span", null, it.materia), el("span", null, organo(it)), el("span", null, fechaCorta(it.fecha)),
            it.identificador_legal && el("span", null, resaltar(it.identificador_legal, o.tokens || []))));
      }
      return el("li", { ...props, class: "accion" }, el("span", { class: "t" }, o.t));
    }));
    entrada.setAttribute("aria-activedescendant", elegibles.length ? `op-${seleccion}` : "");
  }

  function elegir(idx) {
    const o = opciones.filter((x) => !x.grupo)[idx];
    if (!o) return;
    if (o.item) { cerrarPaleta(); estado.abiertaPorClic = true; location.hash = "n-" + o.item.id; }
    else { cerrarPaleta(); o.accion(); }
  }

  function abrirPaleta(q = "") {
    paleta.hidden = false;
    document.body.classList.add("bloqueado");
    entrada.value = q;
    seleccion = 0;
    pintarPaleta();
    entrada.focus();
  }
  function cerrarPaleta() {
    if (paleta.hidden) return;
    paleta.hidden = true;
    if (lector.hidden) document.body.classList.remove("bloqueado");
  }

  // ------------------------------------------------------------------ acciones generales
  function aplicar() {
    estado.limite = PASO;
    pintar();
    if (!sinFiltros()) $("#contenido").scrollIntoView({ block: "start" });
  }
  function alternarTema() {
    const raiz = document.documentElement;
    const actual = raiz.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const nuevo = actual === "dark" ? "light" : "dark";
    raiz.setAttribute("data-theme", nuevo);
    guardar("tema", nuevo);
    toast(nuevo === "dark" ? "Modo oscuro" : "Modo claro");
  }
  async function actualizar() {
    const antes = new Set(estado.porId.keys());
    const boton = $("#btn-actualizar");
    boton.disabled = true;
    try {
      await cargar();
      const nuevas = Array.from(estado.porId.keys()).filter((id) => !antes.has(id)).length;
      pintar();
      toast(nuevas ? `${nuevas === 1 ? "Llegó 1 novedad" : `Llegaron ${nuevas} novedades`}.` : "No hay novedades nuevas desde la última actualización.");
    } catch (e) {
      estado.error = e;
      toast("No se pudo actualizar. Revisá la conexión.");
    } finally {
      boton.disabled = false;
    }
  }
  function marcarVistas() {
    estado.ultimaVisita = new Date().toISOString();
    guardar("ultima_visita", estado.ultimaVisita);
    for (const it of estado.porId.values()) it._nuevo = false;
    estado.filtros.nuevas = false;
    pintar();
  }

  function atraparFoco(e, contenedor) {
    if (e.key !== "Tab") return;
    const focos = $$('a[href], button:not([disabled]):not([hidden]), input, select, [tabindex]:not([tabindex="-1"])', contenedor)
      .filter((n) => n.offsetParent !== null);
    if (!focos.length) return;
    const primero = focos[0], ultimo = focos[focos.length - 1];
    if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
    else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
  }

  // ------------------------------------------------------------------ eventos
  document.addEventListener("click", (e) => {
    const objetivo = e.target.closest("button, a");
    if (!objetivo) return;
    const d = objetivo.dataset;
    if (objetivo.tagName === "A" && /^#n-/.test(objetivo.getAttribute("href") || "")) {
      if (!lector.hidden && objetivo.closest("#lector")) {
        // Anterior/Siguiente reemplazan la entrada del historial: "atrás" vuelve al listado.
        e.preventDefault();
        const id = objetivo.getAttribute("href").slice(3);
        history.replaceState(null, "", "#n-" + id);
        abrir(id);
        return;
      }
      estado.abiertaPorClic = true;
      return;
    }
    if (d.guardar) { e.preventDefault(); alternarGuardado(d.guardar); return; }
    if (d.materia !== undefined && objetivo.closest("#materias, .barras")) { estado.filtros.materia = d.materia; aplicar(); return; }
    if (d.rango !== undefined) { estado.filtros.rango = Number(d.rango); aplicar(); return; }
    if (d.vista) { estado.vista = d.vista; guardar("vista", d.vista); pintar(); return; }
    if (d.quitar) {
      estado.filtros[d.quitar] = d.quitar === "q" ? "" : false;
      if (d.quitar === "biblioteca" && location.hash === "#biblioteca") history.replaceState(null, "", location.pathname + location.search);
      aplicar(); return;
    }
    if (d.buscar) { cerrar(false); estado.filtros.q = d.buscar; aplicar(); return; }
    switch (d.accion) {
      case "limpiar": Object.assign(estado.filtros, { materia: "", rango: 0, fuente: "", tipo: "", impacto: false, biblioteca: false, nuevas: false, q: "" }); aplicar(); break;
      case "mostrar-mas": estado.limite += PASO; pintarListado(sinFiltros() ? (elegirDestacado(estado.items) || {}).id : null); break;
      case "archivo": cargarMes(d.mes); break;
      case "reintentar": iniciar(); break;
      case "ver-nuevas": estado.filtros.nuevas = true; aplicar(); break;
      case "marcar-vistas": marcarVistas(); break;
      case "copiar-cita": { const it = estado.porId.get(estado.abierta) || estado.biblioteca[estado.abierta]; if (it) copiar(citaCompleta(it), "Cita copiada."); break; }
      case "copiar-biblioteca": copiar(Object.values(estado.biblioteca).filter(valido).map(citaCompleta).join("\n\n"), "Se copiaron las citas de tu biblioteca."); break;
      default: break;
    }
  });

  $("#fuente").addEventListener("change", (e) => { estado.filtros.fuente = e.target.value; aplicar(); });
  $("#tipo").addEventListener("change", (e) => { estado.filtros.tipo = e.target.value; aplicar(); });
  $("#btn-impacto").addEventListener("click", () => { estado.filtros.impacto = !estado.filtros.impacto; aplicar(); });
  $("#btn-biblioteca").addEventListener("click", () => { estado.filtros.biblioteca = !estado.filtros.biblioteca; aplicar(); });
  $("#btn-tema").addEventListener("click", alternarTema);
  $("#btn-actualizar").addEventListener("click", actualizar);
  $("#btn-buscar").addEventListener("click", () => abrirPaleta(estado.filtros.q));

  $("#lec-cerrar").addEventListener("click", () => cerrar(false));
  $("#velo").addEventListener("click", () => cerrar(false));
  $("#lec-guardar").addEventListener("click", () => estado.abierta && alternarGuardado(estado.abierta));
  $("#lec-copiar").addEventListener("click", () => {
    const it = estado.porId.get(estado.abierta) || estado.biblioteca[estado.abierta];
    if (it) copiar(citaCompleta(it), "Cita copiada.");
  });
  $("#lec-enlace").addEventListener("click", () => {
    if (estado.abierta) copiar(`${location.href.split("#")[0]}#n-${estado.abierta}`, "Enlace a la ficha copiado.");
  });
  $("#lec-imprimir").addEventListener("click", () => { try { window.print(); } catch (e) { toast("Este visor no permite imprimir."); } });
  const cambiarEscala = (delta) => {
    estado.escala = Math.min(1.4, Math.max(0.85, Math.round((estado.escala + delta) * 100) / 100));
    guardar("escala", estado.escala);
    cuerpo.style.setProperty("--escala", String(estado.escala));
  };
  $("#lec-mas").addEventListener("click", () => cambiarEscala(0.1));
  $("#lec-menos").addEventListener("click", () => cambiarEscala(-0.1));
  cuerpo.addEventListener("scroll", () => {
    const max = cuerpo.scrollHeight - cuerpo.clientHeight;
    $("#progreso").style.width = max > 0 ? `${Math.min(100, (cuerpo.scrollTop / max) * 100)}%` : "100%";
  }, { passive: true });

  entrada.addEventListener("input", () => { seleccion = 0; pintarPaleta(); });
  entrada.addEventListener("keydown", (e) => {
    const total = opciones.filter((o) => !o.grupo).length;
    if (e.key === "ArrowDown") { e.preventDefault(); seleccion = (seleccion + 1) % Math.max(total, 1); pintarPaleta(); $(`#op-${seleccion}`)?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "ArrowUp") { e.preventDefault(); seleccion = (seleccion - 1 + total) % Math.max(total, 1); pintarPaleta(); $(`#op-${seleccion}`)?.scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter") { e.preventDefault(); elegir(seleccion); }
  });
  resultados.addEventListener("click", (e) => { const li = e.target.closest("li[data-idx]"); if (li) elegir(Number(li.dataset.idx)); });
  paleta.addEventListener("click", (e) => { if (e.target === paleta) cerrarPaleta(); });

  document.addEventListener("keydown", (e) => {
    const escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); paleta.hidden ? abrirPaleta() : cerrarPaleta(); return; }
    if (e.key === "Escape") { if (!paleta.hidden) cerrarPaleta(); else cerrar(false); return; }
    if (!paleta.hidden) { atraparFoco(e, paleta); return; }
    if (!lector.hidden) {
      atraparFoco(e, lector);
      if (!escribiendo && (e.key === "j" || e.key === "k")) {
        const pos = estado.lista.findIndex((x) => x.id === estado.abierta);
        const otro = estado.lista[pos + (e.key === "j" ? 1 : -1)];
        if (otro) history.replaceState(null, "", "#n-" + otro.id), abrir(otro.id);
      }
      return;
    }
    if (!escribiendo && e.key === "/") { e.preventDefault(); abrirPaleta(); }
  });

  window.addEventListener("hashchange", rutear);
  const registrarVisita = () => guardar("ultima_visita", new Date().toISOString());
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") registrarVisita(); });
  window.addEventListener("pagehide", registrarVisita);
  setInterval(() => { if (estado.meta) pintarCabecera(); }, 60000);

  // ------------------------------------------------------------------ inicio
  async function iniciar() {
    pintarCabecera();
    try {
      await cargar();
    } catch (e) {
      estado.error = e;
    }
    pintar();
    if (estado.pendiente) { const id = estado.pendiente; estado.pendiente = null; abrir(id); }
    else rutear();
  }

  if ("serviceWorker" in navigator && /^https?:$/.test(location.protocol) && !EN_MARCO) {
    window.addEventListener("load", () => { navigator.serviceWorker.register("sw.js").catch(() => { /* sin modo sin conexión */ }); });
  }
  iniciar();
})();
