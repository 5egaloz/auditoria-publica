#!/usr/bin/env python3
"""Extractor del padron y del voto nominal completo — Modulo Legislativo.

Lee los XML oficiales de opendata.camara.cl ya ingeridos y produce:
  1. data/derived/legislativo/diputados.json — padron del periodo con el
     historial de militancia por partido y sus fechas, copiado literal.
  2. data/derived/legislativo/votos-nominales-2026.json — el voto de cada
     diputado en cada votacion de Sala con detalle disponible, en formato
     compacto (id de diputado -> codigo de opcion) para que la web lo baje.

Regla dura heredada (ver extraer_legislativo.py): el conteo nominal se compara
con los totales que declara la fuente. Aqui, con cientos de votaciones, una
votacion que no cuadra NO se descarta en silencio: queda fuera de 'registros' y
entra en 'discrepancias' con sus cifras, para que el hueco se vea (Bloque 4,
regla 3). El partido NO se interpreta: es la militancia vigente a la fecha de
la votacion segun la propia Camara.

Sin dependencias: solo stdlib.
"""

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
DERIVED = RAIZ / "data" / "derived" / "legislativo"
NS = {"v": "http://opendata.camara.cl/camaradiputados/v1"}

# Codigos compactos: el archivo guarda una letra por voto, no la palabra.
CODIGOS = {"Afirmativo": "A", "En Contra": "C", "Abstención": "B",
           "No Vota": "N", "Dispensado": "D", "Pareo": "P"}


def entradas_manifiesto() -> list[dict]:
    with MANIFIESTO.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def texto(nodo, ruta):
    hijo = nodo.find(ruta, NS)
    return hijo.text if hijo is not None else None


def extraer_padron(entradas: list[dict], ahora: str) -> int:
    """Fusiona todos los padrones ingeridos (uno por periodo legislativo).

    Hace falta mas de uno: el periodo cambio el 2026-03-11 y las votaciones
    anteriores son de parlamentarios que ya no figuran en el padron vigente.
    """
    fuentes = [e for e in entradas
               if Path(e["ruta_local"]).name.startswith("diputados-")]
    if not fuentes:
        print("AVISO: falta el padron en el manifiesto; corra ingesta_masiva.py --que padron")
        return 0

    por_id: dict[int, dict] = {}
    for entrada in fuentes:
        raiz = ET.parse(RAIZ / entrada["ruta_local"]).getroot()
        for periodo in raiz.findall("v:DiputadoPeriodo", NS):
            dip = periodo.find("v:Diputado", NS)
            if dip is None:
                continue
            id_dip = int(texto(dip, "v:Id"))
            nombre = " ".join(x for x in (texto(dip, "v:Nombre"),
                                          texto(dip, "v:ApellidoPaterno"),
                                          texto(dip, "v:ApellidoMaterno")) if x)
            sexo = dip.find("v:Sexo", NS)
            registro = por_id.setdefault(id_dip, {
                "id": id_dip, "nombre": nombre,
                "sexo": sexo.text if sexo is not None else None,
                "periodos": [], "militancias": [],
                "sha256_origen": [],
            })
            # Un mismo parlamentario aparece en varios padrones; se unen sus
            # militancias sin repetir, conservando la fuente de cada padron.
            for m in dip.findall("v:Militancias/v:Militancia", NS):
                partido = m.find("v:Partido", NS)
                militancia = {
                    "desde": texto(m, "v:FechaInicio"),
                    "hasta": texto(m, "v:FechaTermino"),
                    "partido_id": texto(partido, "v:Id") if partido is not None else None,
                    "partido_nombre": texto(partido, "v:Nombre") if partido is not None else None,
                    "partido_alias": texto(partido, "v:Alias") if partido is not None else None,
                }
                if militancia not in registro["militancias"]:
                    registro["militancias"].append(militancia)
            periodo_dict = {"desde": texto(periodo, "v:FechaInicio"),
                            "hasta": texto(periodo, "v:FechaTermino")}
            if periodo_dict not in registro["periodos"]:
                registro["periodos"].append(periodo_dict)
            if entrada["sha256"] not in registro["sha256_origen"]:
                registro["sha256_origen"].append(entrada["sha256"])

    for registro in por_id.values():
        registro["militancias"].sort(key=lambda x: x["desde"] or "")
        registro["periodos"].sort(key=lambda x: x["desde"] or "")

    registros = sorted(por_id.values(), key=lambda x: x["nombre"])
    salida = {
        "descripcion": "Padron de diputadas y diputados con su historial de militancia "
                       "por partido y las fechas de cada militancia, segun "
                       "opendata.camara.cl (WSDiputado). Se fusionan los padrones de "
                       "todos los periodos legislativos ingeridos, porque una votacion "
                       "puede ser de un periodo anterior al vigente. Campos copiados "
                       "literalmente de la fuente; el partido de una persona en una fecha "
                       "es el que la Camara registra para esa fecha.",
        "generado_utc": ahora,
        "generado_por": "extraer_nominal.py",
        "padrones_fusionados": [
            {"sha256": e["sha256"], "url_fuente": e["url_fuente"],
             "ruta_local": e["ruta_local"]} for e in fuentes],
        "total_registros": len(registros),
        "registros": registros,
    }
    ruta = DERIVED / "diputados.json"
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(registros)} diputados -> {ruta.relative_to(RAIZ).as_posix()}")
    return len(registros)


def extraer_votos(entradas: list[dict], ahora: str) -> int:
    registros, discrepancias = [], []
    for e in entradas:
        if not Path(e["ruta_local"]).name.startswith("votacion-detalle-"):
            continue
        raiz = ET.parse(RAIZ / e["ruta_local"]).getroot()
        ficha = {
            "id": int(texto(raiz, "v:Id")),
            "fecha": texto(raiz, "v:Fecha"),
            "descripcion_literal": texto(raiz, "v:Descripcion"),
            "total_si": int(texto(raiz, "v:TotalSi")),
            "total_no": int(texto(raiz, "v:TotalNo")),
            "total_abstencion": int(texto(raiz, "v:TotalAbstencion")),
            "total_dispensado": int(texto(raiz, "v:TotalDispensado")),
        }
        for campo in ("Quorum", "Resultado", "Tipo"):
            nodo = raiz.find(f"v:{campo}", NS)
            ficha[campo.lower()] = nodo.text if nodo is not None else None

        votos, conteo = {}, {}
        for voto in raiz.findall("v:Votos/v:Voto", NS):
            dip = voto.find("v:Diputado", NS)
            opcion = texto(voto, "v:OpcionVoto")
            conteo[opcion] = conteo.get(opcion, 0) + 1
            votos[str(int(texto(dip, "v:Id")))] = CODIGOS.get(opcion, opcion)

        # Regla dura: el conteo nominal debe cuadrar con los totales declarados.
        problemas = []
        for opcion, declarado in (("Afirmativo", ficha["total_si"]),
                                  ("En Contra", ficha["total_no"]),
                                  ("Abstención", ficha["total_abstencion"])):
            contado = conteo.get(opcion, 0)
            if contado != declarado:
                problemas.append({"opcion": opcion, "declarado": declarado,
                                  "contado_nominal": contado})
        if problemas:
            discrepancias.append({"id": ficha["id"], "fecha": ficha["fecha"],
                                  "sha256_origen": e["sha256"],
                                  "url_fuente": e["url_fuente"],
                                  "diferencias": problemas})
            continue

        ficha["votantes"] = len(votos)
        ficha["votos"] = votos
        ficha["sha256_origen"] = e["sha256"]
        ficha["url_fuente"] = e["url_fuente"]
        registros.append(ficha)

    registros.sort(key=lambda x: x["fecha"])
    salida = {
        "descripcion": "Voto nominal de cada diputada y diputado en cada votacion de Sala "
                       "de la Camara con detalle publicado (opendata.camara.cl, "
                       "WSLegislativo.retornarVotacionDetalle). El voto se guarda con un "
                       "codigo por opcion; ver codigos_opcion. Sin clasificacion ni "
                       "valoracion: datos copiados de la fuente.",
        "generado_utc": ahora,
        "generado_por": "extraer_nominal.py",
        "codigos_opcion": {v: k for k, v in CODIGOS.items()},
        "criterio_exclusion": "Se excluye de 'registros' toda votacion cuyo conteo nominal "
                              "no coincide con los totales declarados por la fuente; esas "
                              "votaciones se listan integras en 'discrepancias'.",
        "total_registros": len(registros),
        "total_discrepancias": len(discrepancias),
        "discrepancias": discrepancias,
        "registros": registros,
    }
    ruta = DERIVED / "votos-nominales-2026.json"
    # Compacto a proposito: indentado, este archivo pasa de ~1 MB a ~10 MB.
    ruta.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    kb = ruta.stat().st_size / 1024
    print(f"OK: {len(registros)} votaciones con voto nominal "
          f"({len(discrepancias)} en discrepancia) -> "
          f"{ruta.relative_to(RAIZ).as_posix()} ({kb:.0f} KB)")
    if discrepancias:
        print("   discrepancias publicadas (no se descartan en silencio): " +
              ", ".join(str(d["id"]) for d in discrepancias[:20]))
    return len(registros)


def main() -> int:
    DERIVED.mkdir(parents=True, exist_ok=True)
    entradas = entradas_manifiesto()
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    extraer_padron(entradas, ahora)
    extraer_votos(entradas, ahora)
    return 0


if __name__ == "__main__":
    sys.exit(main())
