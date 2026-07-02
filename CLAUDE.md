# PROMPT MAESTRO — Sistema de Auditoría Cívica de Datos Abiertos (Chile)

> **Este documento es la fuente única de verdad del proyecto.** Toda sesión de Claude Code que trabaje aquí debe leerlo completo antes de tocar código. Si una instrucción de sesión contradice este documento, prima este documento salvo que Fer diga explícitamente lo contrario.
>
> Estado: **FASES 1-4 COMPLETAS Y PUBLICADAS** (especificación creada 2026-07-01; core + fiscal + legislativo + web construidos y auditados el mismo día). Ver Hoja de Ruta al final.

---

## 🎯 BLOQUE 0 — Rol y Objetivo

**Rol que asumes:** Arquitecto de Software de Datos Abiertos. Construyes un sistema de auditoría de datos públicos chilenos **sin sesgo ideológico**, inspirado en X-Road (Estonia): datos con trazabilidad e inmutabilidad criptográfica de punta a punta.

**Motivación del proyecto:** la ola de acusaciones constitucionales (AC) en Chile ha desplazado el debate desde lo técnico hacia lo ideológico. Este sistema existe para que cualquier ciudadano pueda ver **el dato puro, verificable y con fuente**, y sacar sus propias conclusiones.

### Principios innegociables

1. **Neutralidad:** el sistema no opina, expone. Jamás produce una conclusión política. Presenta magnitudes, series y comparaciones con base explícita.
2. **Verificabilidad:** todo dato publicado lleva **fuente + URL + fecha de captura (UTC) + hash SHA-256** del artefacto original del cual salió.
3. **Gasto $0:** solo infraestructura gratuita — GitHub (repo + Pages + Actions). Ninguna dependencia de pago.
4. **Reproducibilidad:** un tercero con el manifiesto puede re-descargar las fuentes, re-calcular los hashes y re-derivar cada cifra publicada. Si algo no es reproducible, no se publica.
5. **Simetría:** las reglas se aplican igual a todo gobierno, coalición, parlamentario o período. El sistema no conoce "oficialismo" ni "oposición" — solo instituciones, fechas y números.

### Anti-objetivo explícito

El sistema **NUNCA** concluye "quién tiene razón", "quién lo hizo bien/mal", ni recomienda votar/apoyar/rechazar nada. Si una salida del sistema pudiera leerse como editorial, está mal construida y debe corregirse.

---

## 🛡️ BLOQUE 1 — Motor Central (Core criptográfico de ingesta)

Todo dato entra al sistema por **un único camino**: el pipeline de ingesta. Nada se publica si no pasó por aquí.

### Flujo de ingesta (obligatorio para todo artefacto)

```
descargar original (CSV/XML/JSON/PDF)
  → calcular SHA-256 del archivo byte a byte
  → guardar el original INTACTO en /data/raw/<modulo>/<YYYY-MM-DD>/<archivo>
  → registrar entrada en el manifiesto append-only
  → recién entonces: extraer/derivar datos
```

### El manifiesto (`manifest.jsonl`)

Archivo **JSON Lines, append-only** (solo se agregan líneas al final; editar o borrar una línea = corrupción). Una línea por artefacto ingerido:

```json
{
  "seq": 42,
  "sha256": "<hash del artefacto>",
  "sha256_prev": "<campo sha256_linea de la entrada seq 41>",
  "sha256_linea": "<SHA-256 del JSON de esta entrada, calculado con sha256_linea vacío>",
  "url_fuente": "https://...",
  "timestamp_utc": "2026-07-01T14:30:00Z",
  "bytes": 183024,
  "modulo": "fiscal | legislativo",
  "descripcion": "Ejecución presupuestaria Gobierno Central, mayo 2026",
  "ruta_local": "data/raw/fiscal/2026-07-01/ejecucion-2026-05.csv"
}
```

### Hash-chain (inmutabilidad)

- Cada entrada incluye `sha256_prev` = hash de la línea anterior → **alterar cualquier entrada pasada rompe toda la cadena posterior**. Es el mismo principio de un ledger, sin blockchain ni costo.
- La entrada `seq: 0` (génesis) usa `sha256_prev: "0".repeat(64)`.
- El manifiesto vive en el **repo Git público** → cada commit de GitHub queda con fecha y hash de commit públicos = timestamping de terceros gratuito. Regla operativa: **un commit por corrida de ingesta**, mensaje `ingesta: <modulo> <fecha>`.

### Verificador

Dos implementaciones del mismo chequeo, para que nadie tenga que confiar en nosotros:
1. **Script `verificar.py`** (stdlib pura, sin dependencias): recorre el manifiesto, valida la cadena (`sha256_prev` y `sha256_linea`) y re-calcula el hash de cada archivo en `data/raw/`. Salida: `CADENA OK (N entradas)` o el `seq` exacto donde se rompe.
2. **Página `/verificar` en GitHub Pages**: el visitante arrastra un archivo descargado de la fuente oficial y el navegador re-calcula su SHA-256 con **Web Crypto API** (`crypto.subtle.digest`) y lo busca en el manifiesto. Cero servidor.

### Reglas duras del core

- Los archivos de `data/raw/` **jamás se editan, renombran ni borran**. Si una fuente corrige un dato, se ingiere el artefacto nuevo como entrada nueva (la historia de la corrección también es dato).
- Si una descarga falla o el hash no se puede calcular, **no se registra nada** — no existen entradas parciales.
- El pipeline registra QUÉ descargó, nunca interpreta durante la ingesta. Extracción y derivación son etapas posteriores y separadas.

---

## 💰 BLOQUE 2 — Módulo Fiscal (A)

### Fuentes (verificadas 2026-07-01, todas gratuitas)

| Fuente | Qué entrega | Formato | Dónde |
|---|---|---|---|
| **Dipres — Datos Abiertos** | Ejecución presupuestaria mensual Gobierno Central desde 2013; Ley de Presupuestos inicial y vigente | CSV / API (datos.gob.cl) | https://datos.gob.cl (buscar "Dipres") · portal: https://www.dipres.gob.cl |
| **Dipres — IFP** (Informe de Finanzas Públicas, trimestral) | Proyecciones macro oficiales: PIB, demanda interna, balance efectivo y estructural, deuda | PDF (+ anexos XLSX cuando existan) | https://www.dipres.gob.cl/598/w3-propertyvalue-25624.html |
| **CFA** (Consejo Fiscal Autónomo) | Evaluación independiente del balance estructural, sostenibilidad de deuda, desvíos de metas | PDF | https://cfachile.cl/publicaciones-del-cfa/informes-del-consejo |

### Variables numéricas a extraer (solo números, cero prosa)

Por cada IFP / dataset ingerido:
- **Proyección de crecimiento PIB** (% real, por año proyectado).
- **Balance efectivo** y **balance estructural (cíclicamente ajustado)** del Gobierno Central, en % del PIB.
- **Deuda bruta** del Gobierno Central (% PIB y MM$).
- **Ejecución presupuestaria**: % ejecutado por partida (mensual y acumulado año).
- **Desviación proyección vs. realizado**: para cada variable, diferencia entre lo proyectado en IFPs anteriores y el dato efectivo posterior — la serie de desviaciones es el producto estrella del módulo (mide calidad de proyección, sin adjetivos).
- **Meta de balance estructural vigente** (decreto de política fiscal) vs. resultado, y el desvío que reporte el CFA.

### Reglas de extracción de PDFs (IFP y CFA)

- Se extraen **solo tablas y cifras**; cada cifra registra `pagina_origen` del PDF.
- El PDF completo queda hasheado en el manifiesto ANTES de extraer — el dato extraído siempre apunta al `sha256` de su PDF.
- La prosa del informe no se resume ni parafrasea. Si una cifra solo existe dentro de un párrafo, se extrae la cifra y se cita el fragmento **textual entre comillas** (máx. 1 oración).
- Extracción con salida a `data/derived/fiscal/*.json`, cada registro: `{variable, valor, unidad, periodo, sha256_origen, pagina_origen, formula: null}`.

---

## 📜 BLOQUE 3 — Módulo Legislativo (B)

### Fuentes (verificadas 2026-07-01, todas gratuitas)

| Fuente | Qué entrega | Formato | Dónde |
|---|---|---|---|
| **Cámara de Diputados — Open Data** | Proyectos de ley, votaciones por boletín (voto nominal), diputados, urgencias, trámites constitucionales | XML (web services) | https://opendata.camara.cl |
| **Senado — Datos Abiertos Legislativos** | Tramitación en el Senado, votaciones, senadores | XML | https://www.senado.cl/transparencia/datos-abiertos-legislativos |
| **BCN — Ley Chile** | Texto de normas publicadas (ley resultante de un boletín) | API / XML | https://www.leychile.cl |

### Datos por proyecto de ley

Registro por boletín: `numero_boletin, titulo_oficial (literal), fecha_ingreso, camara_origen, estado_tramitacion, urgencias (tipo + fechas), tramite_actual, fechas_por_tramite, votaciones[]`.

Cada votación: `fecha, sesion, materia (literal), quorum_requerido, si, no, abstencion, pareo, detalle_nominal[] (parlamentario, partido, voto)`.

Derivados permitidos (siempre marcados como derivados, con fórmula): días totales de tramitación, días por trámite, % de asistencia a votaciones por parlamentario, tasa de urgencias por Ejecutivo/período.

### Submódulo AC — Acusaciones Constitucionales (el motivador del proyecto)

Las AC se tratan como **cualquier otro dato**, con el máximo de literalidad:
- `fecha_presentacion, acusado (cargo e institución), causal_invocada` — la causal se registra con el **texto literal** del libelo/boletín, sin parafrasear ni clasificar en "grave/leve".
- Tramitación completa con fechas: cuestión previa (resultado y votos), votación en la Cámara (nominal), votación en el Senado por capítulo (nominal), resultado final.
- Quórums exigidos vs. obtenidos, en números.
- Serie histórica: cantidad de AC por período legislativo, tiempos de tramitación, tasas de aprobación por etapa — **sin ninguna valoración sobre si son "muchas" o "pocas"**: el lector compara.

---

## 🧠 BLOQUE 4 — Reglas de IA (Filtro de lenguaje)

Estas reglas aplican a **toda salida del sistema**: textos de la web, descripciones de datasets, mensajes de commit, alertas, README públicos. También aplican a ti, Claude, cuando escribas cualquier contenido de este proyecto.

### Lista negra (prohibido en toda salida pública)

Adjetivos y sustantivos valorativos, entre otros: *fracaso, éxito, histórico, récord, populista, irresponsable, responsable, escandaloso, alarmante, preocupante, sólido, débil, desastre, logro, mezquino, generoso, austero, derrochador, sesgado, valiente, cobarde*. La lista es ilustrativa, no taxativa: **la regla es "cero lenguaje que implique juicio de valor"**, y ante la duda, se reescribe.

### Regla de traducción (adjetivo → dato)

Todo juicio se reemplaza por **magnitud + base de comparación explícita**:

| ❌ Prohibido | ✅ Correcto |
|---|---|
| "gasto desbordado" | "gasto ejecutado 12,4% sobre lo presupuestado; percentil 93 de la serie 2013–2026" |
| "proyección optimista" | "proyección de PIB 1,8 pp sobre la mediana de proyecciones de los 8 IFP anteriores para el mismo horizonte" |
| "tramitación exprés" | "34 días entre ingreso y despacho; mediana histórica de la misma categoría: 412 días" |
| "AC sin fundamento" | "cuestión previa acogida por 78 votos contra 65 (quórum: mayoría simple)" |

### Reglas duras de salida

1. **Toda afirmación = número + fuente + hash.** Una frase sin las tres cosas no se publica.
2. **Separación dato/derivado:** todo campo calculado se marca `derivado: true` y lleva su `formula` legible (ej: `"dias_tramitacion = fecha_despacho - fecha_ingreso"`). El lector siempre distingue lo que dijo la fuente de lo que calculamos.
3. **Sin dato = "sin dato disponible".** Nunca estimar, interpolar ni rellenar. Un hueco en la serie se muestra como hueco.
4. **Comparaciones solo con base explícita:** nunca "más que antes"; siempre "X vs. Y del período Z, fuente W".
5. **Texto literal entre comillas** cuando se cite una causal, título o materia — nunca paráfrasis propia.
6. **Simetría de trato:** los mismos derivados se calculan para todos los actores/períodos; jamás un indicador que solo se aplique a un sector.

---

## 🌐 BLOQUE 5 — Salida (web estática en GitHub Pages)

- **Stack:** HTML/CSS/JS puro (patrón ya probado en los proyectos 5egaloz.github.io), sin frameworks ni build; los JSON de `data/derived/` se consumen por `fetch` directo desde el mismo repo. Costo: $0.
- **Estructura:** página por módulo (Fiscal / Legislativo / AC) con tablas y series; **cada celda enlaza a su entrada del manifiesto** (seq + hash) y de ahí a la URL de la fuente oficial.
- **Página `/verificar`:** re-cálculo de hashes client-side (Web Crypto API) + validador de la cadena del manifiesto en el navegador.
- **Cero analytics, cero cookies, cero publicidad:** un sistema que audita no puede a la vez rastrear.
- Los gráficos muestran siempre el eje desde donde corresponda estadísticamente y declaran unidad y fuente en la propia imagen (los ejes truncados sin aviso son la versión visual del adjetivo).

---

## 🗺️ Hoja de Ruta (para futuras sesiones de Claude Code)

Cada fase termina con algo verificable. No saltar fases.

- **Fase 1 — Core:** repo Git + `ingesta.py` (descarga→hash→raw→manifiesto, stdlib pura) + `verificar.py` + génesis del manifiesto con 1 artefacto real de prueba de cada módulo. **Criterio de salida:** `verificar.py` da `CADENA OK` y un tercero puede reproducirlo con el README.
- **Fase 2 — Módulo Fiscal:** conector Dipres datos abiertos (CSV/API) + extractor de tablas del IFP y CFA (PDF) → `data/derived/fiscal/`. **Criterio de salida:** serie de balance estructural proyectado vs. efectivo con ≥3 IFPs, cada cifra con hash y página de origen.
- **Fase 3 — Módulo Legislativo:** conector opendata.camara.cl + Senado (XML) → registros por boletín + votaciones nominales; submódulo AC con al menos las AC del período en curso. **Criterio de salida:** ficha completa de 1 AC real, 100% literal y con fuentes.
- **Fase 4 — Web:** GitHub Pages con las páginas por módulo + `/verificar`. **Criterio de salida:** una persona externa verifica un hash de punta a punta sin ayuda.
- **Fase 5 — Automatización (opcional):** cron en GitHub Actions para ingesta periódica + commit automático.

### Convenciones del repo

```
Auditoria-Publica/
├── CLAUDE.md            ← este documento (fuente única de verdad)
├── README.md            ← qué es, estado, cómo verificar
├── manifest.jsonl       ← manifiesto append-only (Fase 1)
├── ingesta.py           ← pipeline único de entrada (Fase 1)
├── verificar.py         ← validador de cadena y hashes (Fase 1)
├── data/
│   ├── raw/<modulo>/<fecha>/   ← originales intactos, jamás editados
│   └── derived/<modulo>/       ← JSON extraídos/derivados, con formula y sha256_origen
└── web/                 ← GitHub Pages (Fase 4)
```

- Python **stdlib pura** donde sea posible (hashlib, urllib, json, xml.etree); dependencias solo si un PDF lo exige (ej. pdfplumber) y se congelan en `requirements.txt`.
- Commits en español, un commit por corrida de ingesta.
- Este CLAUDE.md solo se modifica con decisión explícita de Fer, y el cambio se registra en la bitácora del README.
