# Fase 6 — Prensa: separar el dato verificable de la lectura

> Documento de diseño. No modifica `CLAUDE.md` (que solo se toca por decisión
> explícita). Nada de esto está implementado.

## El problema con el enunciado

El fin del proyecto es *desmenuzar la ideología política de lo técnico*. Tomado
literal, eso pide un clasificador que marque frases como "ideológicas". Eso
choca de frente con el Bloque 4 del propio proyecto: **cero lenguaje valorativo
en toda salida**, todo juicio convertido en *magnitud + base de comparación*.

Un sistema que rotula "esto es ideología" emite un juicio y se vuelve, él mismo,
el producto ideológico que el proyecto existe para evitar. Y no es verificable:
no hay hash que respalde la etiqueta.

## La inversión que lo hace posible

**No se clasifica ideología. Se mide cuánto de un artículo se puede contrastar
contra el registro sellado.**

Ante una noticia, el sistema no dice qué es ideológico. Dice:

> De las 14 afirmaciones de este artículo, 3 son contrastables contra el
> registro. De esas, 2 coinciden con la fuente oficial y 1 difiere: el artículo
> dice 3,0 % del PIB, el IFP 1T2026 de Dipres dice 2,80 % del PIB
> (`sha256 b68869ea…`). Las otras 11 no contienen un dato resolvible en este
> corpus.

Eso es magnitud con base de comparación, cada cifra con fuente y hash, y el
hueco declarado como hueco. El lector saca la conclusión — que es exactamente lo
que el sitio ya promete en su bajada. La ideología no se nombra: se vuelve
visible como el resto que no se puede anclar a un dato.

**Métrica publicada:** `densidad_contrastable = contrastables / afirmaciones`.
Nunca "sesgo", nunca "ideológico", nunca un adjetivo.

## Custodia: registro aparte, no `manifest.jsonl`

`manifest.jsonl` está reservado a originales descargados de fuentes del Estado
(Bloque 1). Un artículo de prensa no lo es. Se aplica el mismo criterio que
`sellar_prompts.py` usa para los prompts: **artefacto sellado con su SHA-256,
custodia en el historial de Git del repo público**, fuera del manifiesto.

```
prensa/
  registro.jsonl          # cadena propia de artículos vistos (hash-chain igual que el manifiesto)
  afirmaciones/<sha256>.json   # afirmaciones extraídas y veredictos de un artículo
  medios.json             # lista de medios + criterio de selección, versionada
```

Entrada de `registro.jsonl` (misma forma que el manifiesto, cadena independiente):

| campo | contenido |
|---|---|
| `seq`, `sha256_prev`, `sha256_linea` | encadenamiento, génesis en 64 ceros |
| `medio`, `titulo`, `url`, `fecha_publicacion` | identificación |
| `timestamp_utc`, `http_status`, `bytes` | condiciones de la captura |
| `sha256` | hash de los bytes servidos por la URL en ese instante |

**No se guarda ni se republica el texto del artículo.** El repo es público: el
texto es obra ajena con derechos. Se guarda el hash (que prueba qué se sirvió),
la URL y, en la salida, citas cortas de la frase contrastada. Solo RSS, y
respetando `robots.txt` y términos de cada medio.

Consecuencia honesta y hay que decirla en el sitio: sin el texto guardado, un
tercero no puede reproducir la extracción sobre el artículo original si el medio
lo edita o lo baja. El hash prueba que *cambió*, no qué decía.

## Dos capas, y solo una puede sellarse

**Capa A — determinista (`extraer_prensa.py`).** Extracción por reglas de las
frases que contienen una cantidad resolvible: porcentaje, monto, conteo de votos,
año, nombre de partido + número. Sin IA. Misma entrada → misma salida byte a
byte, así que cualquiera la re-corre y obtiene lo mismo. **Solo esta capa
sostiene un veredicto publicado.**

**Capa B — no determinista (opcional, LLM).** Normaliza una frase a una
plantilla cuando la regla no alcanza. Un LLM no es reproducible, así que su
salida no puede fundar una afirmación sellada. Se sella como lo que es:
`{modelo, version, sha256_prompt, sha256_entrada, sha256_salida}` marcado
`derivado_no_determinista`. Precedente ya existente en el repo:
`prompts/hashes.json`.

Si la Capa B no se implementa, el sistema sigue siendo útil: extrae menos
afirmaciones y lo declara.

## Plantillas contrastables (lo que hoy se puede resolver)

Solo contra los módulos ya ingeridos:

| plantilla | dataset | ejemplo de frase |
|---|---|---|
| balance del Gobierno Central, % del PIB, año Y | `fiscal/balance-gobierno-central.json` | "el déficit de 2025 fue de 2,8 % del PIB" |
| votos a favor / en contra de una AC en fecha D | `legislativo/acusaciones-constitucionales-2026.json` | "la acusación se aprobó con 78 votos" |
| escaños del partido P | `concentracion/escanos-camara-2026.json` | "los 28 diputados republicanos" |
| cohesión del partido P | `tendencia/cohesion-partidos-2026.json` | "el partido votó dividido" (sin número → no contrastable) |
| votos emitidos por el partido P | derivado de `votos-nominales-2026.json` | "el partido votó 1.200 veces en Sala" |

Todo lo que no calce: `no_contrastable_con_este_corpus`. Es un estado legítimo y
esperado para la mayoría de las frases, no una falla.

## Veredictos (cuatro estados, ningún adjetivo)

- `coincide` — la cifra del artículo y la del dataset son iguales. Se publica el
  `sha256_linea` de la entrada del manifiesto contra la que se comprobó.
- `difiere` — se publican **las dos cifras y el hash**, sin calificar la
  diferencia. Puede ser un error del medio, una fuente distinta, otro año o otra
  definición; el sistema no lo dictamina.
- `sin_dato_disponible` — la afirmación cae en el alcance pero el dato no está
  ingerido.
- `no_contrastable_con_este_corpus` — la frase no contiene un dato resolvible acá.

## El riesgo grande: no agregar por medio

Publicar `densidad_contrastable` **por medio** convierte el instrumento en un
marcador de sesgo de prensa. Cada número sería cierto y el resultado sería un
ranking de medios — el producto ideológico que el proyecto existe para no ser.
Además la métrica no mide lo que ese ranking sugeriría: una columna de opinión
tiene densidad baja por definición, y eso no la hace falsa.

**Recomendación: solo por artículo.** Sin promedios por medio, sin ranking, sin
serie de tiempo por medio. Si algún día se agrega, tiene que ser decisión
explícita tuya y con el descargo escrito al lado.

## Sesgo de selección, declarado

Qué medios se leen y qué artículos se ingieren es, en sí mismo, un vector de
sesgo. `medios.json` versiona la lista **y el criterio** que la produjo, y el
sitio publica ambos. Si un día se recortan artículos por volumen, se dice
cuántos quedaron fuera: un recorte silencioso se lee como "acá está todo".

## Salida en el sitio

Pestaña nueva **Prensa**, con el mismo sistema visual del registro:

- Por artículo: medio, fecha, enlace, `densidad_contrastable`, y la tabla de
  afirmaciones (cita corta · valor del dataset · hash · veredicto).
- Los cuatro veredictos usan la paleta de **estado** ya definida, nunca las
  ranuras de serie, y siempre con etiqueta de texto además del color.
- Vista de tabla en todo, como el resto de la página.

## Operación

GitHub Actions diario: lee RSS → sella entradas nuevas en `prensa/registro.jsonl`
→ corre la Capa A → escribe `afirmaciones/` → commit. Gasto $0. Se monta sobre la
Fase 5 (ingesta automática), que ya estaba pendiente.

`verificar.py` y el verificador del navegador se extienden para comprobar la
cadena de `prensa/registro.jsonl` igual que la del manifiesto.

## Lo que hay que decidir antes de escribir código

1. **Lista de medios.** Cuáles y con qué criterio. Es la decisión con más peso de
   todo el diseño.
2. **¿Capa B (LLM) sí o no?** Sin ella el sistema extrae menos y es 100 %
   reproducible. Con ella extrae más y arrastra un derivado no determinista.
3. **Largo de la cita.** Cuánto texto ajeno se muestra por afirmación.
4. **Paywalls.** Qué se hace con lo que el RSS anuncia pero no entrega.
5. **Agregación por medio.** La recomendación es no. Es tu llamado.

---

# Fase 7 — Mirada crítica: dos capas, y solo una se puede rehacer

> Decidido por Fer el 2026-07-31 e implementado el mismo día. Esta sección
> registra la decisión, el conflicto que abría y cómo se resolvió.

## El conflicto, dicho completo

El encargo fue: que en Prensa aparezcan las noticias políticas más relevantes y
que la IA "baje la información de demagogismos, populismo etc", con mirada
crítica y posibles soluciones.

Eso choca de frente con dos cosas del propio proyecto. El **anti-objetivo del
Bloque 0** ("si una salida pudiera leerse como editorial, está mal construida") y
la **lista negra del Bloque 4**, donde *populista* está escrito con todas sus
letras. Y con lo que este mismo documento argumentó más arriba: una etiqueta de
"esto es demagogia" no la respalda ningún hash.

La salida no fue elegir un lado. Fue **separar lo que se puede sellar de lo que
no**, y publicar cada cosa con su etiqueta.

## Capa A′ — indicadores estructurales (`retorica.py`), sellable

En vez de calificar el discurso, se cuentan rasgos de **forma** que cualquiera
recuenta sobre el mismo texto:

| indicador | qué cuenta |
|---|---|
| `promesas_sin_financiamiento_declarado` | efecto futuro anunciado sin decir con cargo a qué |
| `cifras_sin_base_de_comparacion` | cantidad sin nada contra qué leerla |
| `cifras_sin_atribucion_de_fuente` | cantidad sin decir quién la entregó |
| `colectivos_sin_delimitar` | "la gente", "las familias", sin tramo, número ni región |
| `densidad_valorativa` | palabras con carga de juicio por cada 1.000 |

Ninguno dice que alguien mienta. Dicen que hay afirmaciones que el lector no
puede ir a comprobar a ninguna parte — que es exactamente lo que se pierde cuando
el debate se corre de lo técnico a lo ideológico.

El criterio no vive en el código sino en **`prensa/lexico.json`**, publicado, y
cada salida graba su `sha256`: un indicador sin la versión de su criterio al lado
no significa nada. Las listas son **simétricas por construcción** (cada término
valorativo negativo tiene su par positivo) y hay un test que lo comprueba, más un
test de espejo que corre el mismo titular cambiando el actor y exige el mismo
número.

## Capa B — la lectura crítica (`analisis_ia.py`), NO sellable

La prosa la escribe el modelo siguiendo `prompts/analisis-prensa.md`, cuyo hash
se publica. Lo que se sella **no es la verdad sino la procedencia**: qué modelo,
con qué prompt, sobre qué entrada, con qué salida. Se publica marcada
`derivado_no_determinista`, `sellado: false`, `funda_algun_veredicto: false`, en
un recuadro de borde punteado con el rótulo siempre visible.

Antes de sellarse pasa por **`filtro.py`**, el mismo validador que gobierna al
agente, con el material sellado como payload. Rechaza si aparece una cifra que no
está en el material, lenguaje valorativo, un giro de juicio o una etiqueta
ideológica sin fuente nombrada. Se le agregaron a la lista negra las etiquetas de
estilo político (`demagog`, `populism`, `clientelar`, `asistencialist`,
`tecnocrat`): no porque el fenómeno no exista, sino porque nombrarlo reemplaza el
trabajo de mostrar el mecanismo.

## Selección: cobertura cruzada (`relevancia.py`)

"Las noticias más relevantes" esconde una decisión, y si la toma el autor del
proyecto el sistema publica su agenda con formato de dato. Entra un hecho cuando
**2 o más medios** de `medios.json` lo publican en la misma ventana. La
relevancia la decide la coincidencia entre redacciones que compiten.

El sesgo que arrastra igual está publicado en `prensa/relevancia.json`: hereda
entero el de la lista de medios, y **castiga la exclusiva** — un reportaje que un
solo medio publica nunca alcanza el umbral. Es consecuencia del método, no un
efecto parchable.

## Dos hallazgos que cambiaron números publicados

1. **El texto servido por un medio no es el artículo.** De 9.252 caracteres de
   una nota, 2.308 eran menú, pie y titulares de otras notas. La densidad
   valorativa de la nota de la U. de Chile bajó de 2,03 a **0,0** al recortar: sus
   adjetivos eran de titulares vecinos. Se resolvió con anclas literales
   declaradas en `prensa/cuerpos.json` — no con una heurística, porque una
   heurística falla en silencio.
2. **Las dos capas medían distinto.** `extraer_prensa.py` contaba 17 afirmaciones
   sobre la página completa y `retorica.py` 16 sobre el cuerpo. Publicar dos
   denominadores para la misma nota es un dato falso. Ahora `extraer_prensa.py`
   importa el recorte de `retorica.py` (la única función compartida entre capas,
   con el motivo escrito al lado) y hay un test que exige que sea la misma.

## Lo que sigue pendiente

- La lista de medios sigue sin RSS de Emol, El Mostrador, DF, T13 y El Líbero:
  el sesgo declarado en `medios.json` aplica multiplicado a la cobertura cruzada.
- `relevancia.py` corre a mano. Falta el cron de la Fase 5 que lo encadene con
  `ingesta_prensa.py` → `extraer` → `contrastar` → `retorica`.
- Las anclas de `cuerpos.json` son por artículo. Si un medio mantiene su
  plantilla, podrían declararse por medio en `medios.json`.
