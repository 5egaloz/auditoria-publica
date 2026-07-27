#!/usr/bin/env python3
"""Ingesta masiva del detalle nominal de votaciones — Modulo Legislativo.

Mismo pipeline y mismas reglas duras que ingesta.py (CLAUDE.md, Bloque 1):
  descargar original -> SHA-256 -> guardar intacto en data/raw/ -> manifiesto.
Aqui solo se agrega el recorrido de una lista de URLs, con pausa entre
descargas y reintentos. Reutiliza las funciones de ingesta.py; no duplica el core.

Propiedades:
  - REANUDABLE: un artefacto cuyo sha256 ya esta en el manifiesto se omite,
    asi que el script se puede cortar y volver a correr sin duplicar nada.
  - SIN ENTRADAS PARCIALES: si una descarga falla tras los reintentos, no se
    registra nada de ella y el recorrido sigue; el fallo queda en el resumen.
  - APPEND-ONLY: cada entrada se escribe y se sincroniza a disco antes de
    pasar a la siguiente, para que un corte no deje el manifiesto a medias.

Uso:
  python ingesta_masiva.py --que padron          # padron de diputados vigente
  python ingesta_masiva.py --que detalles        # detalle nominal de las votaciones 2026
  python ingesta_masiva.py --que detalles --limite 50   # por tandas
  python ingesta_masiva.py --que todo

Sin dependencias: solo stdlib.
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ingesta import (GENESIS_PREV, MANIFIESTO, RAIZ, USER_AGENT, hash_canonico,
                     leer_manifiesto)

WS = "https://opendata.camara.cl/camaradiputados/WServices"
URL_DETALLE = WS + "/WSLegislativo.asmx/retornarVotacionDetalle?prmVotacionId={id}"
URL_PADRON = WS + "/WSDiputado.asmx/retornarDiputadosPeriodoActual"
URL_PADRON_PERIODO = WS + "/WSDiputado.asmx/retornarDiputadosXPeriodo?prmPeriodoId={id}"
# El periodo legislativo cambio el 2026-03-11: las votaciones de enero a marzo de
# 2026 son de quienes integraban el periodo 2022-2026, que no estan en el padron
# actual. Sin este artefacto, esos parlamentarios quedarian sin partido.
PERIODOS_ADICIONALES = {10: "2022-2026"}
DERIVED = RAIZ / "data" / "derived" / "legislativo"


def descargar(url: str, intentos: int = 3, espera: float = 3.0) -> bytes | None:
    """Descarga con reintentos. Devuelve None si no se logro: no se registra nada."""
    for intento in range(1, intentos + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as respuesta:
                contenido = respuesta.read()
            if contenido:
                return contenido
            print(f"    respuesta vacia (intento {intento}/{intentos})")
        except Exception as e:
            print(f"    {type(e).__name__}: {e} (intento {intento}/{intentos})")
        if intento < intentos:
            time.sleep(espera * intento)
    return None


def registrar(contenido: bytes, url: str, nombre: str, descripcion: str,
              entradas: list[dict], directorio: Path) -> dict | None:
    """Guarda el original intacto y agrega su entrada al manifiesto. Reglas de ingesta.py."""
    sha256 = hashlib.sha256(contenido).hexdigest()
    for e in entradas:
        if e["sha256"] == sha256:
            return None  # ya ingerido: el manifiesto no repite artefactos

    directorio.mkdir(parents=True, exist_ok=True)
    destino = directorio / nombre
    base, sufijo, n = destino.stem, destino.suffix, 2
    while destino.exists():
        destino = directorio / f"{base}-{n}{sufijo}"
        n += 1
    destino.write_bytes(contenido)

    entrada = {
        "seq": len(entradas),
        "sha256": sha256,
        "sha256_prev": entradas[-1]["sha256_linea"] if entradas else GENESIS_PREV,
        "sha256_linea": "",
        "url_fuente": url,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bytes": len(contenido),
        "modulo": "legislativo",
        "descripcion": descripcion,
        "ruta_local": destino.relative_to(RAIZ).as_posix(),
    }
    entrada["sha256_linea"] = hash_canonico(entrada)
    try:
        with MANIFIESTO.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n")
            f.flush()
    except Exception as e:
        destino.unlink(missing_ok=True)  # sin entrada en el manifiesto no existen raw
        raise SystemExit(f"ERROR al escribir el manifiesto, ingesta detenida: {e}")
    entradas.append(entrada)
    return entrada


def ids_de_votaciones() -> list[int]:
    archivo = DERIVED / "votaciones-2026.json"
    if not archivo.exists():
        raise SystemExit("Falta data/derived/legislativo/votaciones-2026.json; "
                         "corra antes extraer_legislativo.py")
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    return [r["id"] for r in datos["registros"]]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--que", choices=["padron", "detalles", "todo"], default="todo")
    p.add_argument("--limite", type=int, help="maximo de artefactos nuevos por corrida")
    p.add_argument("--pausa", type=float, default=0.4,
                   help="segundos entre descargas (cortesia con el servicio publico)")
    a = p.parse_args()

    entradas = leer_manifiesto()
    ya_ingeridas = {e["url_fuente"] for e in entradas}
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    directorio = RAIZ / "data" / "raw" / "legislativo" / fecha

    pendientes: list[tuple[str, str, str]] = []  # (url, nombre, descripcion)
    if a.que in ("padron", "todo"):
        pendientes.append((
            URL_PADRON, "diputados-periodo-actual.xml",
            "Padron de diputadas y diputados del periodo actual con su historial "
            "de militancia por partido y fechas (WSDiputado.retornarDiputadosPeriodoActual)"))
        for id_periodo, etiqueta in PERIODOS_ADICIONALES.items():
            pendientes.append((
                URL_PADRON_PERIODO.format(id=id_periodo),
                f"diputados-periodo-{id_periodo}.xml",
                f"Padron de diputadas y diputados del periodo legislativo {etiqueta} "
                f"con su historial de militancia por partido y fechas "
                f"(WSDiputado.retornarDiputadosXPeriodo, prmPeriodoId={id_periodo})"))
    if a.que in ("detalles", "todo"):
        for id_votacion in ids_de_votaciones():
            pendientes.append((
                URL_DETALLE.format(id=id_votacion),
                f"votacion-detalle-{id_votacion}.xml",
                f"Detalle nominal de la votacion en Sala {id_votacion} de la Camara "
                f"de Diputadas y Diputados (WSLegislativo.retornarVotacionDetalle)"))

    nuevas = [t for t in pendientes if t[0] not in ya_ingeridas]
    print(f"Manifiesto actual: {len(entradas)} entradas.")
    print(f"Objetivos: {len(pendientes)} | ya ingeridos: {len(pendientes) - len(nuevas)} | "
          f"por descargar: {len(nuevas)}")
    if a.limite:
        nuevas = nuevas[:a.limite]
        print(f"Limitado a {len(nuevas)} en esta corrida.")

    ingeridos = omitidos = fallidos = 0
    fallos: list[str] = []
    for i, (url, nombre, descripcion) in enumerate(nuevas, 1):
        print(f"[{i}/{len(nuevas)}] {nombre}")
        contenido = descargar(url)
        if contenido is None:
            fallidos += 1
            fallos.append(url)
            print("    FALLIDA: no se registra nada")
        else:
            entrada = registrar(contenido, url, nombre, descripcion, entradas, directorio)
            if entrada is None:
                omitidos += 1
                print("    omitida: mismo sha256 ya presente en el manifiesto")
            else:
                ingeridos += 1
                print(f"    seq {entrada['seq']}  {entrada['bytes']} bytes  "
                      f"{entrada['sha256'][:12]}")
        time.sleep(a.pausa)

    print(f"\nRESUMEN: ingeridos {ingeridos} | omitidos {omitidos} | fallidos {fallidos}")
    print(f"Manifiesto: {len(entradas)} entradas.")
    if fallos:
        print("URLs fallidas (reintentar volviendo a correr el script):")
        for u in fallos:
            print("  " + u)
    print("Siguiente paso: python verificar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
