#!/usr/bin/env python3
"""Sella los prompts del agente publicando su SHA-256.

Por que existe: si el prompt que gobierna al agente fuera secreto o pudiera
cambiarse en silencio, el sistema perderia justamente la propiedad que vende.
Los prompts viven en el repo publico y aqui se publica el hash de cada uno, para
que cualquiera compruebe que el archivo que lee es el que se uso.

Cadena de custodia: estos artefactos NO entran a manifest.jsonl, que esta
reservado a los originales descargados de las fuentes del Estado (CLAUDE.md,
Bloque 1). La custodia de los prompts es el historial de Git del repo publico,
que fecha y firma cada cambio.

Sin dependencias: solo stdlib.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PROMPTS = RAIZ / "prompts"


def main() -> int:
    if not PROMPTS.is_dir():
        raise SystemExit("No existe el directorio prompts/")
    archivos = sorted(p for p in PROMPTS.glob("*.md"))
    if not archivos:
        raise SystemExit("No hay prompts que sellar")

    registros = []
    for archivo in archivos:
        contenido = archivo.read_bytes()
        registros.append({
            "archivo": archivo.relative_to(RAIZ).as_posix(),
            "sha256": hashlib.sha256(contenido).hexdigest(),
            "bytes": len(contenido),
        })

    salida = {
        "descripcion": "SHA-256 de los prompts que gobiernan al agente. Para comprobarlos: "
                       "descargue el archivo del repo y calcule su sha256; debe coincidir "
                       "byte a byte con el valor publicado aqui.",
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generado_por": "sellar_prompts.py",
        "cadena_de_custodia": "El historial de Git del repositorio publico fecha cada cambio "
                              "de estos archivos. No entran a manifest.jsonl, reservado a los "
                              "originales descargados de las fuentes del Estado.",
        "total_registros": len(registros),
        "registros": registros,
    }
    ruta = PROMPTS / "hashes.json"
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in registros:
        print(f"  {r['sha256'][:12]}  {r['bytes']:6} B  {r['archivo']}")
    print(f"OK: {len(registros)} prompts sellados -> {ruta.relative_to(RAIZ).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
