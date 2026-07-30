#!/usr/bin/env python3
"""Verificador de las cadenas del repositorio — Auditoria Civica de Datos Abiertos.

CADENA PRINCIPAL (manifest.jsonl). Valida (ver CLAUDE.md, Bloque 1):
  1. seq contiguos desde 0.
  2. hash-chain: sha256_prev de cada entrada == sha256_linea de la anterior
     (genesis: 64 ceros).
  3. sha256_linea de cada entrada (serializacion canonica con sha256_linea vacio).
  4. cada archivo de data/raw/ existe, pesa lo declarado y su SHA-256 coincide.

CADENA DE PRENSA (prensa/registro.jsonl), si existe. Valida 1, 2 y 3, y NO valida
el punto 4 por una razon que hay que decir en voz alta: de los articulos no se
guarda el texto —es obra ajena y el repo es publico— asi que no hay archivo local
que rehashear. El sha256 registrado prueba QUE bytes sirvio esa URL en ese
instante; si el medio edita o baja la nota, el hash prueba que cambio, no que
decia. Es una limitacion real del diseno y se declara en vez de disimularse.

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
    return verificar_prensa()


def verificar_prensa() -> int:
    """Cadena propia de los articulos de prensa. Sin archivos locales que rehashear."""
    registro = RAIZ / "prensa" / "registro.jsonl"
    if not registro.exists():
        return 0   # el modulo de prensa es opcional: sin registro no hay nada que validar

    campos = {"seq", "sha256", "sha256_prev", "sha256_linea", "url", "medio",
              "titulo", "fecha_publicacion", "timestamp_utc", "bytes"}
    prev = GENESIS_PREV
    total = 0
    with registro.open(encoding="utf-8") as f:
        for num, linea in enumerate(f):
            linea = linea.strip()
            if not linea:
                continue
            try:
                e = json.loads(linea)
            except json.JSONDecodeError as err:
                print(f"CADENA DE PRENSA ROTA en la linea {num + 1}: JSON invalido: {err}")
                return 1
            faltan = campos - set(e)
            if faltan:
                print(f"CADENA DE PRENSA ROTA en seq {e.get('seq', num)}: "
                      f"faltan campos {sorted(faltan)}")
                return 1
            if e["seq"] != total:
                print(f"CADENA DE PRENSA ROTA en seq {e['seq']}: no contiguo (esperado {total})")
                return 1
            if e["sha256_prev"] != prev:
                print(f"CADENA DE PRENSA ROTA en seq {e['seq']}: "
                      "sha256_prev no coincide con la entrada anterior")
                return 1
            if e["sha256_linea"] != hash_canonico(e):
                print(f"CADENA DE PRENSA ROTA en seq {e['seq']}: entrada alterada")
                return 1
            if e.get("texto_guardado"):
                # Invariante del diseno: si algun dia esto es True, alguien
                # empezo a republicar obra ajena desde un repo publico.
                print(f"CADENA DE PRENSA: seq {e['seq']} declara texto_guardado=true, "
                      "que este diseno no permite.")
                return 1
            print(f"  prensa seq {e['seq']} OK  [{e['medio']}] {e['url']}")
            prev = e["sha256_linea"]
            total += 1

    if total == 0:
        print("Cadena de prensa vacia: 0 entradas.")
        return 0
    print(f"CADENA DE PRENSA OK ({total} entradas) — sin archivos locales: "
          "de los articulos solo se sella el hash de lo que sirvio la URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
