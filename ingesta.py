#!/usr/bin/env python3
"""Pipeline unico de ingesta — Auditoria Civica de Datos Abiertos.

Todo dato entra al sistema por aqui (ver CLAUDE.md, Bloque 1):
  descargar original -> SHA-256 -> guardar intacto en data/raw/ -> manifiesto append-only.

Uso:
  python ingesta.py <URL> --modulo fiscal|legislativo --desc "descripcion" [--nombre archivo]

Sin dependencias: solo stdlib.
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
GENESIS_PREV = "0" * 64
USER_AGENT = "Mozilla/5.0 (auditoria-civica-datos-abiertos; +github.com/5egaloz)"


def hash_canonico(entrada: dict) -> str:
    """SHA-256 de la entrada serializada de forma canonica, con sha256_linea vacio."""
    copia = dict(entrada)
    copia["sha256_linea"] = ""
    canonico = json.dumps(copia, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def leer_manifiesto() -> list[dict]:
    if not MANIFIESTO.exists():
        return []
    entradas = []
    with MANIFIESTO.open(encoding="utf-8") as f:
        for num, linea in enumerate(f):
            linea = linea.strip()
            if linea:
                entradas.append(json.loads(linea))
    return entradas


def nombre_desde_respuesta(url: str, respuesta, nombre_cli: str | None) -> str:
    """Nombre del archivo: --nombre > Content-Disposition > ultimo segmento de la URL."""
    if nombre_cli:
        crudo = nombre_cli
    else:
        cd = respuesta.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            crudo = m.group(1)
        else:
            segmento = url.split("?")[0].rstrip("/").split("/")[-1]
            crudo = segmento or "artefacto"
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", crudo).strip("._") or "artefacto"
    return limpio


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url", help="URL del artefacto original en la fuente oficial")
    p.add_argument("--modulo", required=True,
                   choices=["fiscal", "legislativo", "medios", "gasto", "economia"])
    p.add_argument("--desc", required=True, help="Descripcion factual del artefacto (sin adjetivos)")
    p.add_argument("--nombre", help="Nombre de archivo a usar (opcional)")
    p.add_argument("--forzar", action="store_true",
                   help="Ingerir aunque el mismo sha256 ya exista en el manifiesto")
    args = p.parse_args()

    # 1. Descargar el original completo. Si falla, NO se registra nada.
    req = urllib.request.Request(args.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as respuesta:
            contenido = respuesta.read()
            nombre = nombre_desde_respuesta(args.url, respuesta, args.nombre)
    except Exception as e:
        print(f"ERROR: descarga fallida, no se registra nada: {type(e).__name__}: {e}")
        return 1
    if not contenido:
        print("ERROR: respuesta vacia, no se registra nada.")
        return 1

    # 2. Hash del artefacto byte a byte.
    sha256 = hashlib.sha256(contenido).hexdigest()

    entradas = leer_manifiesto()
    if not args.forzar:
        for e in entradas:
            if e["sha256"] == sha256:
                print(f"YA INGERIDO: mismo sha256 en seq {e['seq']} ({e['ruta_local']}). "
                      "Use --forzar para registrarlo igual.")
                return 0

    # 3. Guardar el original INTACTO (jamas se sobrescribe un raw existente).
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    directorio = RAIZ / "data" / "raw" / args.modulo / fecha
    directorio.mkdir(parents=True, exist_ok=True)
    destino = directorio / nombre
    base, sufijo, n = destino.stem, destino.suffix, 2
    while destino.exists():
        destino = directorio / f"{base}-{n}{sufijo}"
        n += 1
    destino.write_bytes(contenido)

    # 4. Entrada del manifiesto con hash-chain.
    prev = entradas[-1]["sha256_linea"] if entradas else GENESIS_PREV
    entrada = {
        "seq": len(entradas),
        "sha256": sha256,
        "sha256_prev": prev,
        "sha256_linea": "",
        "url_fuente": args.url,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bytes": len(contenido),
        "modulo": args.modulo,
        "descripcion": args.desc,
        "ruta_local": destino.relative_to(RAIZ).as_posix(),
    }
    entrada["sha256_linea"] = hash_canonico(entrada)

    try:
        with MANIFIESTO.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n")
    except Exception as e:
        destino.unlink(missing_ok=True)  # sin entrada en el manifiesto no existen archivos raw
        print(f"ERROR: no se pudo escribir el manifiesto, ingesta revertida: {e}")
        return 1

    print(f"INGERIDO seq {entrada['seq']}: {entrada['ruta_local']}")
    print(f"  sha256: {sha256}")
    print(f"  bytes:  {len(contenido)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
