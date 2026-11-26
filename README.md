# Monitor Jurídico AR

Portal de novedades jurídicas y judiciales de la Argentina que se actualiza solo dos veces por día. Recolecta fallos de la Corte Suprema, normas del Boletín Oficial y del SAIJ, comunicados de los ministerios públicos y notas de medios jurídicos; descarta lo irrelevante; arma una **ficha jurídica** de cada novedad con IA; **verifica por código** que lo que dice la ficha surja de la fuente; junta en una sola ficha las notas de distintos portales que hablan del mismo hecho, y lo publica como un sitio web con buscador.

## Fuentes

Las 18 fuentes activas por defecto (todas de acceso libre) y elDial, disponible pero desactivada:

| Clave | Fuente | Cómo se lee | Prioridad | Notas |
| --- | --- | --- | --- | --- |
| `csjn` | CSJN, Secretaría de Jurisprudencia | JSON de la página de novedades | 100 | Expediente, carátula, materia y síntesis oficial |
| `csjn_noticias` | CSJN, noticias institucionales | JSON (con token de la página) | 98 | Acordadas, comunicados e informes |
| `infoleg` | InfoLeg, novedades legislativas | HTML | 96 | Leyes de mayor alcance; fecha y resumen oficial |
| `bora` | Boletín Oficial, 1.ª sección | HTML | 95 | Reglas gratuitas descartan designaciones, prórrogas y trámites |
| `saij` | SAIJ, leyes nacionales | API JSON del buscador | 95 |  |
| `saij_tdf` | SAIJ, jurisprudencia de Tierra del Fuego | API JSON | 94 | Fallos con sus sumarios |
| `saij_boletin` | Boletín de novedades del SAIJ | HTML | 93 | Normas nacionales y provinciales, acordadas y fallos con síntesis oficial |
| `mpf` | Ministerio Público Fiscal | HTML | 88 | Su API de WordPress y su RSS están cerrados |
| `mpd` | Ministerio Público de la Defensa | HTML | 86 |  |
| `pj_tdf` | Poder Judicial de Tierra del Fuego | RSS | 86 |  |
| `justicia_ar` | Justicia.ar (portal federal de la CSJN) | JSON (con token de la página) | 84 | Novedades de todos los poderes judiciales; muchas institucionales, las filtra el triage |
| `ijudicial` | iJudicial, Poder Judicial de la Ciudad | RSS | 82 | Las notas sólo "Institucionales" se descartan por reglas |
| `palabras_derecho` | Palabras del Derecho | HTML | 72 |  |
| `pensamiento_penal` | Pensamiento Penal (revista) | RSS + nota | 70 | Pide no usar su contenido para entrenar IA: ver más abajo |
| `app` | Asociación Pensamiento Penal (comunicados) | RSS | 68 |  |
| `aldia` | Al Día Argentina (Microjuris) | RSS con texto completo | 63 | Sólo el portal abierto; se omite la "Selección Editorial" diaria |
| `diario_judicial` | Diario Judicial | HTML | 60 |  |
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

## El portal

- Portada con la novedad principal presentada como carátula, normativa reciente y la semana por materia.
- Filtros por materia, período, fuente, tipo y alto impacto; vista de tarjetas o de lista compacta.
- Buscador con `Ctrl K` o `/` sobre títulos, carátulas, expedientes, normas y etiquetas (sin importar tildes; `27.802` = `27802`).
- Ficha de lectura con tamaño de letra ajustable, cita sugerida para copiar, fragmentos textuales de las fuentes oficiales, coberturas de otros medios y navegación con `j` / `k`.
- Mi biblioteca: fichas guardadas en el navegador, con opción de copiar todas las citas.
- Aviso de novedades desde la última visita, enlaces directos a cada ficha (`#n-…`), modo oscuro, se puede instalar en el teléfono y funciona sin conexión con lo último cargado.
- Radar de fuentes: estado de cada extractor en las últimas corridas.
- RSS en `feed.xml`.

## 
