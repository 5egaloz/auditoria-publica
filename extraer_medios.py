#!/usr/bin/env python3
"""Extractor del Modulo F3 — concentracion de concesiones de radiodifusion.

Lee el listado de concesiones vigentes de SUBTEL ya ingerido y mide cuan
concentradas estan por titular: concesiones por RUT, HHI, numero efectivo de
titulares, y el detalle por tipo de servicio y por region.

Limite que se declara en la propia salida y no se puede omitir al citarla:
esto mide concentracion de CONCESIONES POR TITULAR REGISTRADO, no propiedad
final. Un mismo controlador puede tener varias sociedades con RUT distinto, y
la fuente no publica esa relacion. Por lo tanto la cifra es un PISO de la
concentracion real, nunca un techo.

El sistema mide; no dice si el nivel resultante es alto o bajo
(CLAUDE.md, Bloque 0).

Sin dependencias: solo stdlib. Reutiliza el lector XLSX de extraer_fiscal.py.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from extraer_fiscal import leer_xlsx

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
SALIDA = RAIZ / "data" / "derived" / "concentracion"

HOJA = "Listado"
FILA_ENCABEZADO = 5
COLUMNAS = {"tipo_servicio": "B", "region": "D", "zona_servicio": "E",
            "nombre_radio": "H", "concesionaria": "I", "rut": "J"}


def entradas_manifiesto() -> list[dict]:
    with MANIFIESTO.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def filas_de_hoja(hoja: dict) -> dict[int, dict[str, str]]:
    por_fila: dict[int, dict[str, str]] = defaultdict(dict)
    for celda, valor in hoja.items():
        m = re.match(r"([A-Z]+)(\d+)$", celda)
        if m:
            por_fila[int(m.group(2))][m.group(1)] = valor
    return por_fila


def indices(conteos: dict[str, int]) -> dict:
    total = sum(conteos.values())
    if not total:
        return {"total": 0, "titulares": 0, "hhi": None,
                "hhi_escala_10000": None, "numero_efectivo_titulares": None}
    cuotas = [n / total for n in conteos.values()]
    h = sum(c * c for c in cuotas)
    return {
        "total": total,
        "titulares": len(conteos),
        "hhi": round(h, 6),
        "hhi_escala_10000": round(h * 10000, 1),
        "numero_efectivo_titulares": round(1 / h, 3) if h else None,
    }


def main() -> int:
    entrada = next((e for e in entradas_manifiesto()
                    if e["ruta_local"].endswith("subtel-radiodifusion-junio-2026.xlsx")), None)
    if entrada is None:
        raise SystemExit("Falta el listado de SUBTEL en el manifiesto; ingieralo con ingesta.py")

    hojas = leer_xlsx(RAIZ / entrada["ruta_local"])
    if HOJA not in hojas:
        raise SystemExit(f"El archivo no trae la hoja '{HOJA}'")
    por_fila = filas_de_hoja(hojas[HOJA])

    concesiones = []
    for numero in sorted(por_fila):
        if numero <= FILA_ENCABEZADO:
            continue
        fila = por_fila[numero]
        rut = (fila.get(COLUMNAS["rut"]) or "").strip()
        concesionaria = (fila.get(COLUMNAS["concesionaria"]) or "").strip()
        if not rut or not concesionaria:
            continue  # fila sin titular: no se completa ni se estima
        concesiones.append({
            "tipo_servicio": (fila.get(COLUMNAS["tipo_servicio"]) or "").strip(),
            "region": (fila.get(COLUMNAS["region"]) or "").strip(),
            "zona_servicio": (fila.get(COLUMNAS["zona_servicio"]) or "").strip(),
            "nombre_radio": (fila.get(COLUMNAS["nombre_radio"]) or "").strip(),
            "concesionaria": concesionaria,
            "rut": rut,
        })
    if not concesiones:
        raise SystemExit("No se leyo ninguna concesion; revise el formato del archivo")

    por_rut: dict[str, int] = defaultdict(int)
    nombre_de: dict[str, str] = {}
    por_tipo: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    por_region: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in concesiones:
        por_rut[c["rut"]] += 1
        nombre_de.setdefault(c["rut"], c["concesionaria"])
        por_tipo[c["tipo_servicio"]][c["rut"]] += 1
        por_region[c["region"]][c["rut"]] += 1

    ranking = sorted(
        ({"rut": rut, "concesionaria": nombre_de[rut], "concesiones": n,
          "cuota": round(n / len(concesiones), 6)} for rut, n in por_rut.items()),
        key=lambda x: (-x["concesiones"], x["concesionaria"]))

    acumulado = 0
    for puesto, fila in enumerate(ranking, 1):
        acumulado += fila["concesiones"]
        fila["puesto"] = puesto
        fila["cuota_acumulada"] = round(acumulado / len(concesiones), 6)

    def top(n: int) -> dict:
        corte = ranking[:n]
        return {"titulares": len(corte),
                "concesiones": sum(f["concesiones"] for f in corte),
                "cuota": round(sum(f["concesiones"] for f in corte) / len(concesiones), 6)}

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    salida = {
        "descripcion": "Concentracion de las concesiones vigentes de radiodifusion sonora "
                       "por titular registrado, segun el listado publicado por SUBTEL. "
                       "Cada concesion se atribuye al RUT que la fuente declara como "
                       "concesionaria. El sistema no califica el nivel de concentracion.",
        "generado_utc": ahora,
        "generado_por": "extraer_medios.py",
        "derivado": True,
        "sha256_origen": entrada["sha256"],
        "url_fuente": entrada["url_fuente"],
        "ruta_local": entrada["ruta_local"],
        "limite_de_la_medicion": "Mide concesiones por TITULAR REGISTRADO, no propiedad "
                                 "final. Un mismo controlador puede tener varias sociedades "
                                 "con RUT distinto y la fuente no publica esa relacion, por "
                                 "lo que estas cifras son un piso de la concentracion real, "
                                 "nunca un techo. No corresponde presentarlas como propiedad "
                                 "de medios sin esta advertencia.",
        "formulas": {
            "hhi": "suma de los cuadrados de las cuotas de concesiones por titular "
                   "(0 a 1); en escala 0 a 10000 se multiplica por 10000",
            "numero_efectivo_titulares": "1 / hhi (Laakso-Taagepera)",
            "cuota_acumulada": "suma de las cuotas desde el puesto 1 hasta el actual",
        },
        "concesiones_leidas": len(concesiones),
        "indices_nacionales": indices(por_rut),
        "top_1": top(1), "top_5": top(5), "top_10": top(10), "top_20": top(20),
        "por_tipo_servicio": {t: indices(d) for t, d in sorted(por_tipo.items())},
        "por_region": {r: indices(d) for r, d in sorted(por_region.items())},
        "total_registros": len(ranking),
        "registros": ranking,
    }
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / "concesiones-radiodifusion-2026.json"
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    idx = salida["indices_nacionales"]
    print(f"OK: {len(concesiones)} concesiones de {idx['titulares']} titulares "
          f"-> {ruta.relative_to(RAIZ).as_posix()}")
    print(f"   HHI {idx['hhi_escala_10000']} | titulares efectivos "
          f"{idx['numero_efectivo_titulares']} | top-10 = "
          f"{round(100 * salida['top_10']['cuota'], 1)}% de las concesiones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
