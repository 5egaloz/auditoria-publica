# Auditoría Cívica de Datos Abiertos (Chile)

Sistema de auditoría de datos públicos chilenos **sin sesgo ideológico**, tipo X-Road: todo dato publicado lleva fuente, URL, fecha de captura y hash SHA-256 verificable por cualquiera. Nacido como respuesta técnica a la ola de acusaciones constitucionales: que el debate vuelva al dato.

## Estado

**Fases 1–4 COMPLETAS** (2026-07-01): core criptográfico + módulo Fiscal + módulo Legislativo + web pública. **Módulo de Prensa en marcha** (2026-07-30), con **mirada crítica en dos capas separadas** desde el 2026-07-31. El manifiesto tiene **679 artefactos** oficiales encadenados, más una cadena propia para los artículos de prensa. Todo el diseño vive en [`CLAUDE.md`](CLAUDE.md), el prompt maestro que guía la construcción. Fase pendiente (opcional): **Fase 5 — ingesta automática periódica**.

**Sitio público:** https://5egaloz.github.io/auditoria-publica/

## Qué contiene hoy

- **Fiscal:** serie del Balance del Gobierno Central (efectivo y cíclicamente ajustado, % del PIB, años 2025–2030) según 5 publicaciones IFP de Dipres (1T2025 → 1T2026), extraída celda por celda de los cuadros Excel oficiales — 36 registros, cada uno con hash + hoja + celda de origen.
- **Legislativo:** las 669 votaciones en Sala de la Cámara (2026) y las 13 votaciones de Acusación Constitucional con su voto nominal completo, conteo verificado contra los totales declarados por la fuente.
- **Web:** tablas + gráficos + fichas AC + manifiesto navegable + página de verificación criptográfica en el navegador. Cada cifra abre su **ficha de origen** (archivo, hoja, celda y hash) y distingue si fue *leída* de una fuente o *calculada* por un script.
- **Prensa:** de una nota se toman las frases **con cifra** y se comparan contra los archivos sellados. Cuatro veredictos por afirmación, sin adjetivos: `coincide`, `difiere`, `sin_dato_disponible`, `no_contrastable_con_este_corpus`. Sobre eso, dos capas más: indicadores estructurales sellables y una lectura crítica marcada como no verificable.

### Las tres capas de una nota, y cuál se puede rehacer

| capa | qué produce | ¿reproducible? |
|---|---|---|
| **A** — `extraer_prensa.py` + `contrastar_prensa.py` | afirmaciones con cifra y su veredicto contra el corpus sellado | sí, byte a byte |
| **A′** — `retorica.py` | 5 indicadores de forma del texto, contra listas publicadas en `prensa/lexico.json` | sí, byte a byte |
| **B** — `analisis_ia.py` | lectura crítica en prosa + posibles soluciones | **no**: la escribe un modelo |

### Qué NO hace el módulo de Prensa

No rotula frases como "ideológicas", no dice quién tiene razón y no usa el conocimiento de un modelo de lenguaje como fuente de ningún dato. Un sistema que etiqueta ideología emite un juicio y se vuelve, él mismo, el producto ideológico que este proyecto existe para evitar — y además esa etiqueta no la respalda ningún hash.

Lo que sí hace es medir **cuánto de un texto se puede contrastar** contra el registro. En el caso piloto, de 22 afirmaciones con cifra publicadas en dos notas, 2 se pudieron comparar: una coincide con la votación oficial y otra difiere. Las 20 restantes no tienen hoy un dato público contra el cual compararse, y eso se declara como lo que es.

### Los indicadores de forma (capa A′)

En vez de calificar el discurso —"esto es demagogia"—, se cuentan rasgos que cualquiera recuenta sobre el mismo texto: promesas de efecto futuro que no declaran con cargo a qué, cifras sin base de comparación, cifras sin decir quién las entregó, apelaciones a un colectivo que el texto no delimita, y densidad de palabras con carga de juicio. Ninguno dice que alguien mienta: dicen cuántas afirmaciones el lector no puede ir a comprobar a ninguna parte.

Las listas que los producen viven en `prensa/lexico.json`, publicadas y **simétricas por construcción** (cada término valorativo negativo tiene su par positivo). Cada salida graba el `sha256` del léxico: un indicador sin la versión de su criterio al lado no significa nada. Hay tests de simetría y de espejo — el mismo titular cambiando el actor tiene que dar el mismo número.

### La lectura crítica (capa B), y por qué va aparte

La prosa la escribe un modelo siguiendo `prompts/analisis-prensa.md`, cuyo hash se publica. Lo que se sella **no es la verdad sino la procedencia**: qué modelo, con qué prompt, sobre qué entrada, con qué salida. Se publica marcada `sellado: false` y `funda_algun_veredicto: false`, en un recuadro de borde punteado con el rótulo siempre a la vista. Si ese bloque desapareciera, ninguna cifra del sistema cambiaría.

Antes de sellarse pasa por `filtro.py`, el mismo validador determinista que gobierna al agente: rechaza cifras que no estén en el material, lenguaje valorativo, giros de juicio y etiquetas ideológicas sin fuente nombrada.

### Qué noticia entra (capa de selección)

`relevancia.py` aplica **cobertura cruzada**: entra un hecho cuando 2 o más medios de la lista lo publican en la misma ventana. La relevancia la decide la coincidencia entre redacciones que compiten, no este proyecto. El sesgo que arrastra igual está escrito en `prensa/relevancia.json` — hereda entero el de la lista de medios y castiga la exclusiva: un reportaje que publica un solo medio nunca alcanza el umbral.

**Del artículo no se guarda el texto** (obra ajena, repositorio público): solo la URL, el medio, la fecha y el hash del texto visible normalizado. Se cita únicamente la frase que se contrasta. Consecuencia honesta: si un medio edita o baja una nota, el sello prueba que **cambió**, no qué decía.

## Cómo verificar (cualquier persona, sin confiar en nosotros)

Requisito: Python 3 (sin dependencias).

```
python verificar.py
```

Valida las dos cadenas: la del manifiesto (`manifest.jsonl`) y la de prensa (`prensa/registro.jsonl`). En la de prensa no hay archivos locales que rehashear, porque de los artículos no se guarda el texto.

Las capas deterministas se comprueban solas, y la no determinista declara si su material cambió:

```
python retorica.py --autotest        # los indicadores de forma
python relevancia.py --autotest      # la selección por cobertura cruzada
python extraer_prensa.py --autotest  # la extracción de afirmaciones
python analisis_ia.py --verificar    # ¿los análisis siguen calzando con su prompt y su entrada?
python -m unittest tests_agente      # los 63 tests, incluidos simetría y espejo
```

`analisis_ia.py --verificar` reporta `DESFASADO` cuando el prompt o el material cambiaron desde que se escribió un análisis. No es corrupción: es que la instrucción ya no es la misma y ese texto hay que rehacerlo.

Valida la cadena completa del manifiesto (`manifest.jsonl`): secuencia contigua, hash-chain (`sha256_prev`), integridad de cada entrada (`sha256_linea`) y SHA-256 de cada archivo en `data/raw/`. Salida esperada: `CADENA OK (N entradas)`. Cualquier byte alterado — en un archivo o en el manifiesto — reporta el `seq` exacto donde se rompe.

Para verificar contra la fuente oficial: descargar el artefacto desde la `url_fuente` de su entrada del manifiesto y comparar su SHA-256 (`sha256sum <archivo>` o `Get-FileHash`).

## Cómo ingerir un artefacto nuevo

```
python ingesta.py <URL> --modulo fiscal|legislativo --desc "descripcion factual"
```

Descarga el original, calcula su SHA-256, lo guarda intacto en `data/raw/<modulo>/<fecha>/` y agrega la entrada encadenada al manifiesto. Si la descarga falla no se registra nada; si el mismo hash ya existe, no duplica. Después de cada corrida: un commit (`ingesta: <modulo> <fecha>`).

## Cómo procesar una nota de prensa, de principio a fin

```
python relevancia.py                          # 1. qué hechos cubren 2+ medios hoy
python ingesta_prensa.py <URL> --medio "..." --titulo "..." --fecha AAAA-MM-DD
                                              # 2. sella la nota (dos descargas, hash del texto visible)
#    3. declarar las anclas del cuerpo en prensa/cuerpos.json (inicio y fin literales)
python extraer_prensa.py   --sha256 <sha> --texto <archivo.txt>   # 4. afirmaciones con cifra
python contrastar_prensa.py --sha256 <sha>                        # 5. veredictos contra el corpus
python retorica.py         --sha256 <sha> --texto <archivo.txt>   # 6. indicadores de forma
#    7. escribir la lectura crítica siguiendo prompts/analisis-prensa.md
python analisis_ia.py      --sha256 <sha> --analisis <borrador.md> --revisar   # ensayo
python analisis_ia.py      --sha256 <sha> --analisis <borrador.md>             # sella la procedencia
```

El paso 3 no es opcional y el paso 4 se niega a correr sin él: el texto que sirve la URL de un medio trae el menú del sitio y los titulares de otras notas, y medir sobre eso publica números que no describen la nota. El archivo de texto de trabajo no se versiona — de los artículos no se guarda el texto.

Si el paso 7 no pasa el filtro de `analisis_ia.py`, **no se sella y se dice por qué**. El sistema sigue siendo útil sin esa capa: publica menos y lo declara.

## Cómo se usa este proyecto (sesiones de Claude Code)

1. Abrir una sesión de Claude Code en esta carpeta — lee `CLAUDE.md` automáticamente.
2. Pedir la fase siguiente de la Hoja de Ruta (al final del CLAUDE.md).
3. Nunca saltarse el pipeline de ingesta ni las Reglas de IA (Bloque 4): aplican a todo texto público del sistema.

## Módulos

- 💰 **Fiscal:** Dipres (ejecución presupuestaria, IFP) + CFA — proyecciones vs. realidad, en números.
- 📜 **Legislativo:** Cámara + Senado (XML) — proyectos de ley, votaciones nominales, y las AC como datos literales.
- 📰 **Prensa:** afirmaciones contrastadas + indicadores de forma (ambos sellables) + lectura crítica de IA (marcada no verificable). Selección por cobertura cruzada.
- 🛡️ **Core:** manifiesto append-only con hash-chain SHA-256; Git público como timestamping.
- 🌐 **Salida:** web estática en GitHub Pages con página de verificación client-side. Gasto $0.

## Licencia y datos

- **Código** (`ingesta.py`, `verificar.py`, extractores, web): licencia [MIT](LICENSE) — úsalo, cópialo, adáptalo.
- **Datos crudos** (`data/raw/`): documentos públicos del Estado de Chile (Dipres / Cámara de Diputadas y Diputados), citados con URL de origen y hash en el manifiesto. No son obra de este proyecto.
- **Datos derivados** (`data/derived/`) **y manifiesto**: de libre uso con atribución a este repositorio y a las fuentes oficiales.

## Bitácora

- **2026-07-31** — **Mirada crítica en Prensa, en dos capas separadas.** Nuevo: `retorica.py` (5 indicadores de forma, deterministas, contra `prensa/lexico.json` publicado y simétrico), `analisis_ia.py` (lectura crítica + posibles soluciones, sellada como **no verificable**: se sella la procedencia, no la verdad), `relevancia.py` (selección por cobertura cruzada, 2+ medios) y `prompts/analisis-prensa.md` (hasheado). `filtro.py` suma a su lista negra las etiquetas de estilo político (`demagog`, `populism`, `clientelar`…): no porque el fenómeno no exista, sino porque nombrarlo reemplaza el trabajo de mostrar el mecanismo. Dos hallazgos corrigieron números ya publicados: (1) **el texto servido por un medio no es el artículo** — de 9.252 caracteres de una nota, 2.308 eran menú, pie y titulares de otras notas, y la densidad valorativa de una nota cayó de 2,03 a 0,0 al recortar, porque sus adjetivos eran de titulares vecinos; se resolvió con anclas literales declaradas en `prensa/cuerpos.json`, no con una heurística, porque una heurística falla en silencio; (2) **las dos capas medían sobre textos distintos** (17 afirmaciones vs. 16), así que ahora comparten el recorte y un test lo exige. 63 tests en verde. Diseño completo en [`docs/fase6-prensa.md`](docs/fase6-prensa.md), Fase 7.
- **2026-07-30** — **Módulo de Prensa** (`ingesta_prensa.py`, `extraer_prensa.py`, `contrastar_prensa.py`, `prensa/`) y **giro didáctico de la web** (color por módulo como identidad, doble nivel de lectura, ficha de origen por cifra). Caso piloto: el proyecto de ley boletín **18216-05**, ingerido desde opendata.camara.cl para poder contrastar afirmaciones que antes caían en "sin dato disponible" — ante un hueco, el proyecto amplía el corpus, no estima. Dos aprendizajes medidos: sellar *los bytes servidos* no funciona (los CDN inyectan un identificador por petición, así que se sella el texto visible normalizado y se exige que sea estable en dos descargas), y citar toda frase con cifra republicaba el 29 % del texto de cada nota, así que ahora se cita solo lo que se contrasta (3,9 %). El sesgo de la lista de medios se publica junto con la lista, en `prensa/medios.json`.
- **2026-07-01 (2)** — Fase 1 completa: `ingesta.py` + `verificar.py` (stdlib pura) + génesis del manifiesto con 2 artefactos reales (Ejecución Presupuestaria a mayo 2026 nivel Partida, Dipres vía datos.gob.cl; Votaciones Cámara 2026, opendata.camara.cl). Verificado: `CADENA OK (2 entradas)`; detección de alteración probada en archivo y en manifiesto (ambas reportan el seq exacto); anti-duplicado probado.
- **2026-07-01** — CLAUDE.md versión inicial (esqueleto de 5 bloques de Fer + fuentes verificadas + hoja de ruta).
