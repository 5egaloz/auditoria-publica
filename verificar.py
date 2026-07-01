#!/usr/bin/env python3
"""Verificador de la cadena del manifiesto — Auditoria Civica de Datos Abiertos.

Valida (ver CLAUDE.md, Bloque 1):
  1. seq contiguos desde 0.
  2. hash-chain: sha256_prev de cada entrada == sha256_linea de la anterior
     (genesis: 64 ceros).
  3. sha256_linea de cada entrada (serializacion canonica con sha256_linea vacio).
  4. cada archivo de data/raw/ existe, pesa lo declarado y su SHA-256 coincide.

Salida: "CADENA OK (N entradas)" o el seq exacto donde se rompe (exit 1).
Sin dependencias: solo stdlib. Cualquier tercero puede correrlo.
"""

import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
GENESIS_PREV = "0" * 64

CAMPOS = {"seq", "sha256", "sha256_prev", "sha256_linea", "url_fuente",
          "timestamp_utc", "bytes", "modulo", "descripcion", "ruta_local"}


def hash_canonico(entrada: dict) -> str:
    copia = dict(entrada)
    copia["sha256_linea"] = ""
    canonico = json.dumps(copia, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def fallo(seq, motivo: str) -> int:
    print(f"CADENA ROTA en seq {seq}: {motivo}")
    return 1


def main() -> int:
    if not MANIFIESTO.exists():
        print("Sin manifiesto: manifest.jsonl no existe todavia.")
        return 1

    prev_linea = GENESIS_PREV
    total = 0
    with MANIFIESTO.open(encoding="utf-8") as f:
        for num, linea in enumerate(f):
            linea = linea.strip()
            if not linea:
                continue
            try:
                e = json.loads(linea)
            except json.JSONDecodeError as err:
                return fallo(num, f"JSON invalido en la linea {num + 1}: {err}")

            faltan = CAMPOS - set(e)
            if faltan:
                return fallo(e.get("seq", num), f"faltan campos {sorted(faltan)}")
            if e["seq"] != total:
                return fallo(e["seq"], f"seq no contiguo (esperado {total})")
            if e["sha256_prev"] != prev_linea:
                return fallo(e["seq"], "sha256_prev no coincide con la entrada anterior")
            if e["sha256_linea"] != hash_canonico(e):
                return fallo(e["seq"], "sha256_linea no coincide (entrada alterada)")

            archivo = RAIZ / e["ruta_local"]
            if not archivo.exists():
                return fallo(e["seq"], f"archivo ausente: {e['ruta_local']}")
            contenido = archivo.read_bytes()
            if len(contenido) != e["bytes"]:
                return fallo(e["seq"], f"peso distinto: {len(contenido)} vs {e['bytes']} declarados")
            if hashlib.sha256(contenido).hexdigest() != e["sha256"]:
                return fallo(e["seq"], f"sha256 del archivo no coincide: {e['ruta_local']}")

            print(f"  seq {e['seq']} OK  [{e['modulo']}] {e['ruta_local']}")
            prev_linea = e["sha256_linea"]
            total += 1

    if total == 0:
        print("Manifiesto vacio: 0 entradas.")
        return 1
    print(f"CADENA OK ({total} entradas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
