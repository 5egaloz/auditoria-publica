# Auditoría Cívica de Datos Abiertos (Chile)

Sistema de auditoría de datos públicos chilenos **sin sesgo ideológico**, tipo X-Road: todo dato publicado lleva fuente, URL, fecha de captura y hash SHA-256 verificable por cualquiera. Nacido como respuesta técnica a la ola de acusaciones constitucionales: que el debate vuelva al dato.

## Estado

**Fases 1–4 COMPLETAS** (2026-07-01): core criptográfico + módulo Fiscal + módulo Legislativo + web pública. El manifiesto tiene 18 artefactos oficiales encadenados. Todo el diseño vive en [`CLAUDE.md`](CLAUDE.md), el prompt maestro que guía la construcción. Fase pendiente (opcional): **Fase 5 — ingesta automática periódica**.

**Sitio público:** https://5egaloz.github.io/auditoria-publica/

## Qué contiene hoy

- **Fiscal:** serie del Balance del Gobierno Central (efectivo y cíclicamente ajustado, % del PIB, años 2025–2030) según 5 publicaciones IFP de Dipres (1T2025 → 1T2026), extraída celda por celda de los cuadros Excel oficiales — 36 registros, cada uno con hash + hoja + celda de origen.
- **Legislativo:** las 669 votaciones en Sala de la Cámara (2026) y las 13 votaciones de Acusación Constitucional con su voto nominal completo, conteo verificado contra los totales declarados por la fuente.
- **Web:** tablas + gráfico + fichas AC + manifiesto navegable + página de verificación criptográfica en el navegador.

## Cómo verificar (cualquier persona, sin confiar en nosotros)

Requisito: Python 3 (sin dependencias).

```
python verificar.py
```

Valida la cadena completa del manifiesto (`manifest.jsonl`): secuencia contigua, hash-chain (`sha256_prev`), integridad de cada entrada (`sha256_linea`) y SHA-256 de cada archivo en `data/raw/`. Salida esperada: `CADENA OK (N entradas)`. Cualquier byte alterado — en un archivo o en el manifiesto — reporta el `seq` exacto donde se rompe.

Para verificar contra la fuente oficial: descargar el artefacto desde la `url_fuente` de su entrada del manifiesto y comparar su SHA-256 (`sha256sum <archivo>` o `Get-FileHash`).

## Cómo ingerir un artefacto nuevo

```
python ingesta.py <URL> --modulo fiscal|legislativo --desc "descripcion factual"
```

Descarga el original, calcula su SHA-256, lo guarda intacto en `data/raw/<modulo>/<fecha>/` y agrega la entrada encadenada al manifiesto. Si la descarga falla no se registra nada; si el mismo hash ya existe, no duplica. Después de cada corrida: un commit (`ingesta: <modulo> <fecha>`).

## Cómo se usa este proyecto (sesiones de Claude Code)

1. Abrir una sesión de Claude Code en esta carpeta — lee `CLAUDE.md` automáticamente.
2. Pedir la fase siguiente de la Hoja de Ruta (al final del CLAUDE.md).
3. Nunca saltarse el pipeline de ingesta ni las Reglas de IA (Bloque 4): aplican a todo texto público del sistema.

## Módulos

- 💰 **Fiscal:** Dipres (ejecución presupuestaria, IFP) + CFA — proyecciones vs. realidad, en números.
- 📜 **Legislativo:** Cámara + Senado (XML) — proyectos de ley, votaciones nominales, y las AC como datos literales.
- 🛡️ **Core:** manifiesto append-only con hash-chain SHA-256; Git público como timestamping.
- 🌐 **Salida:** web estática en GitHub Pages con página de verificación client-side. Gasto $0.

## Bitácora

- **2026-07-01 (2)** — Fase 1 completa: `ingesta.py` + `verificar.py` (stdlib pura) + génesis del manifiesto con 2 artefactos reales (Ejecución Presupuestaria a mayo 2026 nivel Partida, Dipres vía datos.gob.cl; Votaciones Cámara 2026, opendata.camara.cl). Verificado: `CADENA OK (2 entradas)`; detección de alteración probada en archivo y en manifiesto (ambas reportan el seq exacto); anti-duplicado probado.
- **2026-07-01** — CLAUDE.md versión inicial (esqueleto de 5 bloques de Fer + fuentes verificadas + hoja de ruta).
