#!/usr/bin/env python3
"""Extractor del Modulo Legislativo — Auditoria Civica de Datos Abiertos.

Lee los XML oficiales de opendata.camara.cl ya ingeridos en data/raw/ y produce:
  1. data/derived/legislativo/votaciones-2026.json — todas las votaciones en
     Sala de la Camara de Diputadas y Diputados del anno 2026.
  2. data/derived/legislativo/acusaciones-constitucionales-2026.json — las
     votaciones cuya descripcion literal es de Acusacion Constitucional, con
     el voto nominal (diputado por diputado) de cada una.

Regla dura: los totales declarados por la fuente (TotalSi/TotalNo/...) se
comparan con el conteo nominal; si no cuadran, el script FALLA.

Sin dependencias: solo stdlib.
"""

import json
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
DERIVED = RAIZ / "data" / "derived" / "legislativo"
NS = {"v": "http://opendata.camara.cl/camaradiputados/v1"}


def entradas_manifiesto() -> list[dict]:
    with MANIFIESTO.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def texto(nodo, ruta):
    hijo = nodo.find(ruta, NS)
    return hijo.text if hijo is not None else None


def plano(cadena: str | None) -> str:
    """Minusculas sin acentos, para comparar la descripcion literal de la fuente."""
    d = unicodedata.normalize("NFD", cadena or "")
    return "".join(c for c in d if unicodedata.category(c) != "Mn").lower()


def es_acusacion_constitucional(ficha: dict) -> bool:
    """Criterio unico y literal: lo dice la descripcion de la propia fuente.

    Necesario desde que se ingiere el detalle nominal de TODAS las votaciones:
    sin este filtro, cualquier votacion con detalle entraria al modulo AC.
    """
    return "acusacion constitucional" in plano(ficha.get("descripcion_literal"))


def votacion_a_dict(nodo) -> dict:
    quorum, resultado, tipo = (nodo.find(f"v:{c}", NS) for c in ("Quorum", "Resultado", "Tipo"))
    return {
        "id": int(texto(nodo, "v:Id")),
        "descripcion_literal": texto(nodo, "v:Descripcion"),
        "fecha": texto(nodo, "v:Fecha"),
        "total_si": int(texto(nodo, "v:TotalSi")),
        "total_no": int(texto(nodo, "v:TotalNo")),
        "total_abstencion": int(texto(nodo, "v:TotalAbstencion")),
        "total_dispensado": int(texto(nodo, "v:TotalDispensado")),
        "quorum": quorum.text if quorum is not None else None,
        "resultado": resultado.text if resultado is not None else None,
        "tipo": tipo.text if tipo is not None else None,
    }


def main() -> int:
    entradas = entradas_manifiesto()
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- 1. Todas las votaciones 2026 -------------------------------------
    ent_lista = next(e for e in entradas if e["ruta_local"].endswith("votaciones-camara-2026.xml"))
    arbol = ET.parse(RAIZ / ent_lista["ruta_local"])
    votaciones = [votacion_a_dict(v) for v in arbol.getroot().findall("v:Votacion", NS)]
    votaciones.sort(key=lambda x: x["fecha"])

    DERIVED.mkdir(parents=True, exist_ok=True)
    salida1 = {
        "descripcion": "Votaciones en Sala de la Camara de Diputadas y Diputados, anno 2026, "
                       "segun opendata.camara.cl (WSLegislativo.retornarVotacionesXAnno). "
                       "Campos textuales copiados literalmente de la fuente.",
        "generado_utc": ahora,
        "generado_por": "extraer_legislativo.py",
        "sha256_origen": ent_lista["sha256"],
        "url_fuente": ent_lista["url_fuente"],
        "total_registros": len(votaciones),
        "registros": votaciones,
    }
    ruta1 = DERIVED / "votaciones-2026.json"
    ruta1.write_text(json.dumps(salida1, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(votaciones)} votaciones -> {ruta1.relative_to(RAIZ).as_posix()}")

    # --- 2. Acusaciones Constitucionales con voto nominal ------------------
    OPCIONES = {"Afirmativo": "afirmativo", "En Contra": "en_contra",
                "Abstención": "abstencion", "No Vota": "no_vota",
                "Dispensado": "dispensado", "Pareo": "pareo"}
    fichas = []
    for e in entradas:
        nombre = Path(e["ruta_local"]).name
        if not nombre.startswith("votacion-detalle-"):
            continue
        raiz_xml = ET.parse(RAIZ / e["ruta_local"]).getroot()
        ficha = votacion_a_dict(raiz_xml)
        if not es_acusacion_constitucional(ficha):
            continue
        votos, conteo = [], {}
        for voto in raiz_xml.findall("v:Votos/v:Voto", NS):
            dip = voto.find("v:Diputado", NS)
            opcion = texto(voto, "v:OpcionVoto")
            conteo[opcion] = conteo.get(opcion, 0) + 1
            votos.append({
                "diputado_id": int(texto(dip, "v:Id")),
                "nombre": " ".join(x for x in (texto(dip, "v:Nombre"),
                                               texto(dip, "v:ApellidoPaterno"),
                                               texto(dip, "v:ApellidoMaterno")) if x),
                "voto": opcion,
            })
        # Regla dura: el conteo nominal debe cuadrar con los totales declarados.
        chequeos = [("Afirmativo", ficha["total_si"]), ("En Contra", ficha["total_no"]),
                    ("Abstención", ficha["total_abstencion"])]
        for opcion, declarado in chequeos:
            contado = conteo.get(opcion, 0)
            if contado != declarado:
                raise SystemExit(f"ERROR votacion {ficha['id']}: la fuente declara "
                                 f"{declarado} '{opcion}' pero el detalle nominal trae {contado}.")
        ficha.update({
            "votos_nominales": sorted(votos, key=lambda x: x["nombre"]),
            "conteo_nominal": {OPCIONES.get(k, k): n for k, n in sorted(conteo.items())},
            "verificacion_conteo": "conteo nominal coincide con totales declarados (si/no/abstencion)",
            "sha256_origen": e["sha256"],
            "url_fuente": e["url_fuente"],
            "acusado": "sin dato disponible en esta fuente (el web service no publica "
                       "el nombre del acusado; la descripcion literal es la del campo "
                       "descripcion_literal)",
        })
        fichas.append(ficha)
    fichas.sort(key=lambda x: x["fecha"])

    salida2 = {
        "descripcion": "Votaciones en Sala de la Camara de Diputadas y Diputados (2026) cuya "
                       "descripcion literal en la fuente es de Acusacion Constitucional, con el "
                       "voto nominal de cada una (opendata.camara.cl, retornarVotacionDetalle). "
                       "Sin clasificacion ni valoracion: datos copiados de la fuente.",
        "generado_utc": ahora,
        "generado_por": "extraer_legislativo.py",
        "total_registros": len(fichas),
        "registros": fichas,
    }
    ruta2 = DERIVED / "acusaciones-constitucionales-2026.json"
    ruta2.write_text(json.dumps(salida2, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(fichas)} fichas AC -> {ruta2.relative_to(RAIZ).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
