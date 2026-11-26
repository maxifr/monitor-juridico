# Monitor Jurídico AR

Portal de novedades jurídicas y judiciales de la Argentina que se actualiza solo dos veces por día. Recolecta fallos de la Corte Suprema, normas del Boletín Oficial y del SAIJ, comunicados de los ministerios públicos y notas de medios jurídicos; descarta lo irrelevante; arma una **ficha jurídica** de cada novedad con IA; **verifica por código** que lo que dice la ficha surja de la fuente; junta en una sola ficha las notas de distintos portales que hablan del mismo hecho, y lo publica como un sitio web con buscador.

Todo corre en servicios gratuitos: GitHub (código, datos, automatización y hosting) y el plan gratuito de la API de Gemini.

```
                               ┌──────────── GitHub Actions (2 veces por día, gratis) ────────────┐
 CSJN (fallos y noticias)      │                                                                   │
 InfoLeg · Boletín Oficial     │  recolección ─► vistos + allowlist + reglas ─► triage IA en lote   │
 SAIJ (leyes, boletín, TDF)    │      │                                              │              │
 MPF · MPD · PJ TDF        ──► │      ▼                                              ▼              │──► data/ (JSON en el repo)
 Justicia.ar · iJudicial       │  cuerpo de la nota ─► capa 1: heurística anti-injection            │──► GitHub Pages: el portal
 APP · Pensamiento Penal       │      ─► capa 2: curador Gemini aislado con nonce                   │──► feed.xml (RSS)
 Palabras del Derecho          │      ─► capa 3: citas verificadas + saneamiento de la salida       │──► Telegram (opcional)
 Al Día · Diario Judicial      │      ─► capa 4: deduplicación (expediente + embeddings + juez)     │
 Infobae Judiciales            │                                                                   │
                               └───────────────────────────────────────────────────────────────────┘
```

## Costo: $0

| Pieza | Servicio | Condición para que sea gratis |
|---|---|---|
| Código, datos e historial | Repositorio de GitHub | Repositorio **público** |
| Corridas automáticas | GitHub Actions | Gratis e ilimitado en repositorios públicos |
| Sitio web con HTTPS | GitHub Pages | Repositorio público; la dirección es `https://TU-USUARIO.github.io/monitor-juridico/` |
| IA (triage, fichas, embeddings) | API de Gemini, plan gratuito de Google AI Studio | Sin tarjeta. El programa respeta los límites por minuto y frena antes del tope diario |
| Alertas | Bot de Telegram | Gratis |

Lo único que no es gratis es un dominio propio (`.com.ar`), y no hace falta.

## Puesta en marcha (unos 20 minutos)

1. **Crear la cuenta y el repositorio.** En GitHub, creá un repositorio **público** llamado `monitor-juridico` y subí todo el contenido de esta carpeta (botón *Add file → Upload files*, arrastrando las carpetas; o con Git).
   Los dos archivos de `flujos-github/` son la automatización y en el repositorio tienen que quedar en `.github/workflows/`. La forma más segura desde la web: *Add file → Create new file*, escribir `.github/workflows/sincronizar.yml` como nombre, pegar el contenido de `flujos-github/sincronizar.yml` y guardar; lo mismo con `pruebas.yml`.
2. **Sacar la clave de Gemini.** Entrá a <https://aistudio.google.com/apikey> con una cuenta de Google y creá una clave (*Create API key*). No pide tarjeta.
3. **Guardar la clave en GitHub.** En el repositorio: *Settings → Secrets and variables → Actions → New repository secret*. Nombre: `GEMINI_API_KEY`; valor: la clave.
4. **Activar el sitio.** *Settings → Pages → Build and deployment → Source:* elegí **GitHub Actions**.
5. **Definir la dirección del portal** (para el RSS y los enlaces). *Settings → Secrets and variables → Actions → pestaña Variables → New repository variable*: `PORTAL_URL` = `https://TU-USUARIO.github.io/monitor-juridico`.
6. **Primera corrida.** Pestaña *Actions → Sincronizar y publicar → Run workflow*. Tarda entre 5 y 15 minutos (va despacio a propósito para no exceder el límite por minuto de Gemini). Al terminar, el portal queda en la dirección del paso 5.

Desde ahí corre solo a las 8:17 y a las 18:17 (hora argentina). Si algún día querés forzar una actualización, repetí el paso 6.

### Opcional

- **Alertas por Telegram** de lo marcado como alto impacto y de fuentes caídas: creá un bot con @BotFather y cargá los secrets `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
- **Perfil editorial**: la variable `PERFIL_EDITORIAL` orienta los casos dudosos del triage. Ejemplo: `Defensa pública penal en Tierra del Fuego: priorizar penal, procesal penal y garantías.`
- **Nombre del portal**: variable `PORTAL_NOMBRE`.
- **Fuentes**: variable `FUENTES_ACTIVAS` con las claves separadas por coma (ver tabla de fuentes). Si la definís, corren sólo esas; para sumar elDial a las de siempre, listalas todas más `eldial`.

## Verlo en tu PC

Con Python 3.10 o superior:

```bash
pip install -r requirements.txt
python main.py --demo          # carga fichas de ejemplo (no necesita clave)
python scripts/servir.py       # abre http://localhost:8000
```

Para correr el monitor real en tu PC, copiá `.env.example` como `.env`, pegá tu `GEMINI_API_KEY` y ejecutá `python main.py`. Otros comandos:

| Comando | Qué hace |
|---|---|
| `python main.py --probar-fuentes` | Prueba los extractores sin IA y sin guardar nada |
| `python main.py --fuentes csjn,bora` | Corre sólo esas fuentes |
| `python main.py --exportar` | Regenera el sitio con los datos guardados |
| `python main.py --cuarentena` | Muestra lo que bloquearon los controles de seguridad |
| `python -m pytest` | Corre las pruebas |

**Modo híbrido.** Si algún portal estatal bloqueara las IP de GitHub (el radar de fuentes lo muestra en rojo), `scripts/ejecutar_local.ps1` corre el monitor desde tu conexión y sube los datos; GitHub vuelve a publicar el sitio automáticamente. Se puede programar con el Programador de tareas de Windows.

## Fuentes

Las 18 fuentes activas por defecto (todas de acceso libre) y elDial, disponible pero desactivada:

| Clave | Fuente | Cómo se lee | Prioridad | Notas |
|---|---|---|---|---|
| `csjn` | CSJN, Secretaría de Jurisprudencia | JSON de la página de novedades | 100 | Expediente, carátula, materia y síntesis oficial |
| `csjn_noticias` | CSJN, noticias institucionales | JSON (con token de la página) | 98 | Acordadas, comunicados e informes |
| `infoleg` | InfoLeg, novedades legislativas | HTML | 96 | Leyes de mayor alcance; fecha y resumen oficial |
| `bora` | Boletín Oficial, 1.ª sección | HTML | 95 | Reglas gratuitas descartan designaciones, prórrogas y trámites |
| `saij` | SAIJ, leyes nacionales | API JSON del buscador | 95 | |
| `saij_tdf` | SAIJ, jurisprudencia de Tierra del Fuego | API JSON | 94 | Fallos con sus sumarios |
| `saij_boletin` | Boletín de novedades del SAIJ | HTML | 93 | Normas nacionales y provinciales, acordadas y fallos con síntesis oficial |
| `mpf` | Ministerio Público Fiscal | HTML | 88 | Su API de WordPress y su RSS están cerrados |
| `mpd` | Ministerio Público de la Defensa | HTML | 86 | |
| `pj_tdf` | Poder Judicial de Tierra del Fuego | RSS | 86 | |
| `justicia_ar` | Justicia.ar (portal federal de la CSJN) | JSON (con token de la página) | 84 | Novedades de todos los poderes judiciales; muchas institucionales, las filtra el triage |
| `ijudicial` | iJudicial, Poder Judicial de la Ciudad | RSS | 82 | Las notas sólo "Institucionales" se descartan por reglas |
| `palabras_derecho` | Palabras del Derecho | HTML | 72 | |
| `pensamiento_penal` | Pensamiento Penal (revista) | RSS + nota | 70 | Pide no usar su contenido para entrenar IA: ver más abajo |
| `app` | Asociación Pensamiento Penal (comunicados) | RSS | 68 | |
| `aldia` | Al Día Argentina (Microjuris) | RSS con texto completo | 63 | Sólo el portal abierto; se omite la "Selección Editorial" diaria |
| `diario_judicial` | Diario Judicial | HTML | 60 | |
| `infobae` | Infobae Judiciales | RSS de la sección | 40 | Muy rápida en causas federales; jerarquía baja y triage estricto |
| `eldial` | elDial.com (desactivada) | Portada pública | 58 | Activala con `FUENTES_ACTIVAS` sólo si tenés suscripción: sus notas están detrás de un muro de pago |

Si un mismo hecho aparece en varias, la ficha principal queda con la fuente de mayor prioridad y las demás quedan como "también lo informaron". Ejemplo: si Infobae publica primero un fallo de la Corte y horas después sale en la Secretaría de Jurisprudencia, la ficha pasa a apoyarse en el texto oficial y la nota de Infobae queda como cobertura.

**Evaluadas y descartadas.** Por ser pagas o de suscripción: La Ley Next, Westlaw y Legal One (Thomson Reuters), el buscador de Microjuris (sí entra su portal abierto Al Día), Errepar/Erreius, El Derecho, AI Legales, JurisprudenciaARG, Lejister y Actualidad Jurídica. Campus Judicial, porque es una plataforma de cursos. LegisLaw, porque al revisarla resultó ser un directorio de enlaces a códigos y leyes sin novedades (su feed está vacío).

Para sumar una fuente: crear su clase en `monitor/fuentes/` (hay ejemplos de HTML, RSS y JSON), agregarla a `monitor/fuentes/__init__.py` y probarla con `python main.py --probar-fuentes --fuentes clave_nueva`.

## Cómo se evita publicar información falsa

1. **Sólo texto visible.** Antes de llegar a la IA se eliminan scripts, comentarios, nodos ocultos por CSS o atributos y caracteres Unicode invisibles (el vector más común de *prompt injection* indirecta). Lo oculto se guarda para auditar.
2. **Allowlist de dominios.** Sólo se procesan URLs de las fuentes registradas.
3. **Escáner heurístico con niveles.** Órdenes dirigidas a una IA ("ignorá las instrucciones…", etiquetas de rol, texto oculto con instrucciones) van directo a cuarentena sin gastar cuota. Menciones que pueden ser legítimas (una nota *sobre* prompt injection) pasan con aviso al curador.
4. **Curador aislado.** El texto externo va dentro de una etiqueta con un token aleatorio que un atacante no puede cerrar desde el HTML; la salida es JSON con esquema estricto e incluye un campo para que el propio modelo denuncie intentos de manipulación.
5. **Citas verificadas por código.** La IA tiene que copiar 2 o 3 fragmentos literales; si no aparecen en la fuente, la ficha no se publica.
6. **Saneamiento de la salida.** Se descartan carátulas, expedientes y normas que no figuren en el texto original (si la fuente los publica de forma estructurada, como la Corte, mandan los oficiales), se quitan etiquetas HTML y URLs y se vuelve a escanear el resultado.
7. **Sitio sin HTML ajeno.** El portal inserta todo como texto (nunca como HTML) y tiene una política de seguridad de contenidos estricta.

Todo lo bloqueado queda en `data/cuarentena.jsonl` con la capa que lo frenó y el motivo.

## Detección de duplicados

1. Mismo expediente o norma (normalizado: `FLP 001221/2024/CS001` = `FLP 1221/2024`; `DNU 70/2023` = `Decreto 70/2023`; `Res. Gral. 5928/26` = `Resolución General 5928/2026`).
2. Similitud de *embeddings* de `gemini-embedding-001` dentro de una ventana de 21 días. Muy alta y mismo tribunal: se fusiona; zona gris: decide un "juez" de IA con la consigna de que compartir el tema no alcanza. Dos expedientes distintos nunca se fusionan solos.
3. Si se agotó la cuota de embeddings, una comparación léxica conservadora más el juez.

Los vectores viven en `data/embeddings.json` y sólo se guardan los de la ventana, para que el repositorio no crezca.

## Uso del plan gratuito de Gemini

- El programa consulta qué modelos habilita tu clave y elige el primero de su lista de preferencia (los Flash-Lite tienen la cuota diaria gratuita más amplia). Si Google cambia nombres o retira un modelo, pasa al siguiente. Se puede forzar uno con `GEMINI_MODELO`.
- Una sola llamada clasifica hasta 30 titulares (triage en lote) y sólo se descargan y procesan las notas que pasan.
- Cada URL procesada queda registrada (publicada, fusionada, descartada o en cuarentena) para no volver a gastar cuota en ella.
- Si se agota la cuota, lo que falta queda en `data/pendientes.json` y se procesa en la corrida siguiente.
- En el plan gratuito, Google puede usar lo que se envía para mejorar sus productos. Por eso el programa lee las señales `Content-Signal` del `robots.txt` de cada sitio: si piden `ai-train=no` (hoy, Pensamiento Penal), a la IA sólo viajan el título y las primeras líneas. Con un plan pago se puede cambiar con `IA_PLAN_PAGO=1`.

## El portal

- Portada con la novedad principal presentada como carátula, normativa reciente y la semana por materia.
- Filtros por materia, período, fuente, tipo y alto impacto; vista de tarjetas o de lista compacta.
- Buscador con `Ctrl K` o `/` sobre títulos, carátulas, expedientes, normas y etiquetas (sin importar tildes; `27.802` = `27802`).
- Ficha de lectura con tamaño de letra ajustable, cita sugerida para copiar, fragmentos textuales de las fuentes oficiales, coberturas de otros medios y navegación con `j` / `k`.
- Mi biblioteca: fichas guardadas en el navegador, con opción de copiar todas las citas.
- Aviso de novedades desde la última visita, enlaces directos a cada ficha (`#n-…`), modo oscuro, se puede instalar en el teléfono y funciona sin conexión con lo último cargado.
- Radar de fuentes: estado de cada extractor en las últimas corridas.
- RSS en `feed.xml`.

## Mantenimiento

- **Una fuente aparece en rojo en el radar.** Casi siempre es un cambio de diseño del sitio. Corré `python main.py --probar-fuentes --fuentes CLAVE` y ajustá los selectores en `monitor/fuentes/`. El resto sigue funcionando mientras tanto.
- **GitHub pausa los workflows programados** de un repositorio público tras 60 días sin actividad. Como cada corrida guarda datos, eso no debería pasar; si pasara, en *Actions* aparece un botón para reactivarlo.
- **Tamaño del repositorio.** Las fichas pesan ~3 KB cada una y se guardan por mes en `data/novedades/`. Los registros de vistos y cuarentena se podan solos.

## Diferencias con el plan original

| Plan | Implementación | Por qué |
|---|---|---|
| Supabase + pgvector | JSON versionados en el propio repositorio | Una cuenta menos, sin pausas por inactividad, sin claves en el frontend y con historial de cada cambio |
| Playwright para la CSJN | Endpoint JSON de la propia página | Sin navegador: más rápido, más estable y con datos oficiales estructurados |
| API de WordPress para fiscales.gob.ar | Lectura de la portada | Hoy la API y el RSS de ese sitio están cerrados |
| `gemini-2.5-flash` fijo | Autodetección de modelo con respaldo | Los Gemini 2.5 ya no se habilitan para proyectos nuevos |
| Una llamada de IA por nota | Triage en lote + registro de vistos + cola de pendientes | Entra holgado en la cuota gratuita y no repite trabajo |
| `hash()` de Python para URLs sin enlace | SHA-256 | `hash()` cambia en cada ejecución y generaba duplicados |
| Fuero que mezclaba tribunal y materia ("CSJN", "Penal") | Materia, tipo e instancia por separado | Un fallo penal de la Corte aparece al filtrar Penal |
| Next.js / Astro | Sitio estático sin compilación | Nada que instalar ni compilar; GitHub Pages lo sirve tal cual |
| — | SAIJ, Boletín Oficial, MPD, Palabras del Derecho y jurisprudencia de Tierra del Fuego | El plan las mencionaba pero no las implementaba |
| Selectores HTML supuestos para las fuentes nuevas | JSON de CSJN y Justicia.ar, RSS de iJudicial, APP, Al Día e Infobae | Se verificó cada sitio: son más estables que leer el HTML |
| LegisLaw como fuente de novedades | Descartada | Es un directorio de enlaces sin novedades |
| Quitar elDial para que todo sea de acceso libre | Desactivada por defecto, se puede reactivar | Así no se pierde si alguien tiene suscripción |
| — | Radar de fuentes, alertas por Telegram, RSS, modo sin conexión | Para enterarse cuando algo se rompe y leer desde cualquier lado |

## Estructura

```
main.py                     punto de entrada (ver comandos arriba)
monitor/
  fuentes/                  un extractor por fuente
  seguridad.py              saneamiento, heurística, allowlist, verificación de citas
  curaduria.py              triage en lote, ficha jurídica, juez de duplicados
  ia.py                     cliente Gemini: autodetección, ritmo y tope diario
  dedup.py                  deduplicación multi-fuente
  almacen.py                datos en JSON
  pipeline.py               orquestador
  exportar.py               datos del sitio y RSS
  alertas.py                Telegram
site/                       el portal (HTML, CSS y JS sin dependencias)
data/                       lo genera el pipeline (se guarda en el repo)
scripts/                    demo, servidor local y modo híbrido
tests/                      pruebas con páginas que reproducen la estructura de las fuentes
flujos-github/              sincronización + publicación y pruebas (van en .github/workflows/)
```

Las fichas son síntesis automáticas: no reemplazan la lectura del fallo o la norma. Antes de citar, consultá siempre la fuente primaria.
