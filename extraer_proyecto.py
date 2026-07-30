#!/usr/bin/env python3
"""Extractor de las votaciones de UN proyecto de ley, desde el XML sellado.

Nace de una necesidad concreta del modulo de Prensa: una nota afirma "la Camara
aprobo por 80 votos a favor, 48 en contra y dos abstenciones" y el corpus no
tenia ese proyecto. En vez de dejar la afirmacion en "sin dato disponible" para
siempre, se amplia el corpus con la fuente oficial: es la unica forma de
contrastarla sin recurrir a la memoria de nadie.

Lee data/raw/legislativo/<fecha>/proyecto-<boletin>.xml (ya sellado en el
manifiesto) y emite data/derived/legislativo/proyecto-<boletin>.json con una
fila por votacion.

TRAMPA DE LA FUENTE, comprobada y respetada aca: el campo <Resultado> del web
service de la Camara NO significa lo que su nombre sugiere (aparece "Aprobado"
en votaciones claramente divididas). Se copia literal porque es lo que dice la
fuente, pero los unicos campos que este extractor usa para comparar son
TotalSi / TotalNo / TotalAbstencion, que si son consistentes.

Uso:
  python extraer_proyecto.py --boletin 18216-05

Sin dependencias: solo stdlib.
"""

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
DERIVED = RAIZ / "data" / "derived" / "legislativo"


def sin_ns(etiqueta: str) -> str:
    return etiqueta.split("}")[-1]


def texto(nodo, *nombres):
    """Primer hijo cuyo tag (sin namespace) calce con alguno de los nombres."""
    if nodo is None:
        return None
    for hijo in nodo:
        if sin_ns(hijo.tag) in nombres:
            return (hijo.text or "").strip() or None
    return None


def entrada_del_manifiesto(boletin: str) -> dict | None:
    """La entrada sellada del XML de ese boletin. Sin sello, no se deriva nada."""
    if not MANIFIESTO.exists():
        return None
    candidatas = []
    with MANIFIESTO.open(encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                e = json.loads(linea)
                if f"proyecto-{boletin}.xml" in e.get("ruta_local", ""):
                    candidatas.append(e)
    return candidatas[-1] if candidatas else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--boletin", required=True, help="Numero de boletin, ej 18216-05")
    args = p.parse_args()

    entrada = entrada_del_manifiesto(args.boletin)
    if not entrada:
        print(f"ERROR: no hay ningun proyecto-{args.boletin}.xml sellado en el manifiesto. "
              "Primero se ingiere con ingesta.py: sin sello no se deriva nada.")
        return 1

    archivo = RAIZ / entrada["ruta_local"]
    crudo = archivo.read_bytes()
    if hashlib.sha256(crudo).hexdigest() != entrada["sha256"]:
        print(f"ERROR: {entrada['ruta_local']} no coincide con su hash sellado. Se detiene.")
        return 1

    raiz = ET.fromstring(crudo)
    ficha = {
        "boletin": None, "titulo": None, "fecha_ingreso": None,
        "tipo_iniciativa": None, "camara_origen": None,
    }
    for hijo in raiz.iter():
        t = sin_ns(hijo.tag)
        valor = (hijo.text or "").strip()
        if t == "NumeroBoletin" and not ficha["boletin"]:
            ficha["boletin"] = valor
        elif t == "Nombre" and not ficha["titulo"] and len(valor) > 20:
            ficha["titulo"] = valor
        elif t == "FechaIngreso" and not ficha["fecha_ingreso"]:
            ficha["fecha_ingreso"] = valor

    votaciones = []
    for nodo in raiz.iter():
        if sin_ns(nodo.tag) != "VotacionProyectoLey":
            continue
        registro = {}
        for hijo in nodo:
            registro[sin_ns(hijo.tag)] = (hijo.text or "").strip() or None
        def num(*claves):
            for c in claves:
                v = registro.get(c)
                if v is not None and str(v).strip().lstrip("-").isdigit():
                    return int(v)
            return None
        votaciones.append({
            "id": num("Id"),
            "fecha": registro.get("Fecha"),
            "descripcion_literal": registro.get("Descripcion"),
            "total_si": num("TotalSi", "Si"),
            "total_no": num("TotalNo", "No"),
            "total_abstencion": num("TotalAbstencion", "Abstencion"),
            "total_dispensado": num("TotalDispensado", "Dispensado"),
            "quorum": registro.get("Quorum") or registro.get("TipoQuorum"),
            # Se copia literal y se advierte: la fuente lo usa de forma inconsistente.
            "resultado_literal_de_la_fuente": registro.get("Resultado"),
            "tramite": registro.get("Tramite"),
        })
    votaciones = [v for v in votaciones if v["id"] is not None]
    votaciones.sort(key=lambda v: (v.get("fecha") or "", v["id"]))

    salida = {
        "descripcion": f"Votaciones registradas para el boletin {ficha['boletin'] or args.boletin} "
                       "en el web service de la Camara de Diputados. Una fila por votacion.",
        "generado_por": "extraer_proyecto.py",
        "generado_utc": entrada["timestamp_utc"],
        "boletin": ficha["boletin"] or args.boletin,
        "titulo_oficial": ficha["titulo"],
        "fecha_ingreso": ficha["fecha_ingreso"],
        "sha256_origen": entrada["sha256"],
        "url_fuente": entrada["url_fuente"],
        "advertencia_resultado": "El campo Resultado del web service aparece como 'Aprobado' incluso "
                                 "en votaciones divididas, asi que no se usa para comparar: solo se "
                                 "usan total_si, total_no y total_abstencion.",
        "cobertura": "Solo votaciones de la Camara de Diputados. El Senado publica su tramitacion en "
                     "otro servicio y sus totales de votos no vienen en registro legible por maquina.",
        "total_registros": len(votaciones),
        "registros": votaciones,
    }
    DERIVED.mkdir(parents=True, exist_ok=True)
    destino = DERIVED / f"proyecto-{salida['boletin']}.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"DERIVADO {destino.relative_to(RAIZ).as_posix()}")
    print(f"  boletin: {salida['boletin']} — {salida['titulo_oficial']}")
    print(f"  votaciones: {len(votaciones)}")
    con_totales = [v for v in votaciones if v["total_si"] is not None]
    print(f"  con totales: {len(con_totales)}")
    for v in con_totales[-4:]:
        print(f"   id {v['id']} {str(v['fecha'])[:10]} -> {v['total_si']} si / "
              f"{v['total_no']} no / {v['total_abstencion']} abst")
    return 0


if __name__ == "__main__":
    sys.exit(main())
