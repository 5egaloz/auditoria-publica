#!/usr/bin/env python3
"""Extractor del Modulo Fiscal — Auditoria Civica de Datos Abiertos.

Lee los cuadros Excel oficiales de los IFP (Dipres) ya ingeridos en data/raw/
(via ingesta.py) y produce data/derived/fiscal/balance-gobierno-central.json:
la serie de Balance Efectivo y Balance Ciclicamente Ajustado del Gobierno
Central (% del PIB) segun cada publicacion IFP, celda por celda, cada cifra
con su artefacto de origen (sha256 + hoja + celda).

Regla dura: cada extraccion valida la etiqueta de la fila en el cuadro; si
Dipres cambia el layout, el script FALLA en vez de extraer un numero errado.

Sin dependencias: solo stdlib (los .xlsx se leen como zip+XML).
"""

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
SALIDA = RAIZ / "data" / "derived" / "fiscal" / "balance-gobierno-central.json"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def leer_xlsx(ruta: Path):
    """Lector minimo de .xlsx (zip + XML): devuelve {hoja: {celda: valor}}."""
    z = zipfile.ZipFile(ruta)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    rels = {rel.get("Id"): rel.get("Target")
            for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    hojas = {}
    for sh in wb.find("m:sheets", NS):
        destino = rels[sh.get("{%s}id" % NS["r"])].lstrip("/")
        if not destino.startswith("xl/"):
            destino = "xl/" + destino
        celdas = {}
        for c in ET.fromstring(z.read(destino)).iter("{%s}c" % NS["m"]):
            v = c.find("m:v", NS)
            if v is None:
                continue
            val = shared[int(v.text)] if c.get("t") == "s" else v.text
            celdas[c.get("r")] = val
        hojas[sh.get("name")] = celdas
    return hojas


def buscar_en_manifiesto(nombre_archivo: str) -> dict:
    with MANIFIESTO.open(encoding="utf-8") as f:
        for linea in f:
            e = json.loads(linea)
            if e["ruta_local"].endswith(nombre_archivo):
                return e
    raise SystemExit(f"ERROR: {nombre_archivo} no esta en el manifiesto — ingerirlo primero.")


# ---------------------------------------------------------------------------
# MAPEO DE EXTRACCION — verificado a mano contra cada cuadro el 2026-07-01.
# Formato por registro: (hoja, celda_valor, celda_etiqueta, texto_esperado_en_etiqueta,
#                        variable, anno, caracter, publicacion, nota)
# variable: balance_efectivo_pct_pib | balance_ciclicamente_ajustado_pct_pib | meta_bca_pct_pib
# caracter: proyeccion | cierre_estimado | meta
# ---------------------------------------------------------------------------

E, B = "balance_efectivo_pct_pib", "balance_ciclicamente_ajustado_pct_pib"
META = "meta_bca_pct_pib"

MAPEO = {
    "ifp-2025-3T-cuadros.xlsx": [
        # Cuadro I.4.2: balance 2025 con acciones correctivas, segun IFP 1T25 / 2T25 / 3T25
        ("C I.4.2", "D11", "B11", "Balance Efectivo", E, 2025, "proyeccion", "IFP 1T2025",
         "con acciones correctivas; cifra de IFP 1T2025 segun la reporta IFP 3T2025"),
        ("C I.4.2", "D12", "B12", "Balance C", B, 2025, "proyeccion", "IFP 1T2025",
         "con acciones correctivas; cifra de IFP 1T2025 segun la reporta IFP 3T2025"),
        ("C I.4.2", "F11", "B11", "Balance Efectivo", E, 2025, "proyeccion", "IFP 2T2025",
         "con acciones correctivas; cifra de IFP 2T2025 segun la reporta IFP 3T2025"),
        ("C I.4.2", "F12", "B12", "Balance C", B, 2025, "proyeccion", "IFP 2T2025",
         "con acciones correctivas; cifra de IFP 2T2025 segun la reporta IFP 3T2025"),
        ("C I.4.2", "H11", "B11", "Balance Efectivo", E, 2025, "proyeccion", "IFP 3T2025",
         "con acciones correctivas"),
        ("C I.4.2", "H12", "B12", "Balance C", B, 2025, "proyeccion", "IFP 3T2025",
         "con acciones correctivas"),
        # Cuadro II.5.1: balance 2026 (% del PIB)
        ("C II.5.1", "C6", "B6", "Balance Devengado", E, 2026, "proyeccion", "IFP 3T2025",
         "publicado como 'Balance Devengado'"),
        ("C II.5.1", "C18", "B18", "Balance C", B, 2026, "proyeccion", "IFP 3T2025", None),
        # Cuadro III.8.1: meta BCA 2027-2030
        ("C III.8.1", "C9", "B9", "Meta BCA", META, 2027, "meta", "IFP 3T2025", None),
        ("C III.8.1", "D9", "B9", "Meta BCA", META, 2028, "meta", "IFP 3T2025", None),
        ("C III.8.1", "E9", "B9", "Meta BCA", META, 2029, "meta", "IFP 3T2025", None),
        ("C III.8.1", "F9", "B9", "Meta BCA", META, 2030, "meta", "IFP 3T2025", None),
    ],
    "ifp-2025-4T-cuadros.xlsx": [
        # Cuadro I.5.1: balance 2025, proyeccion IFP 4T25 (columnas E/F)
        ("C I.5.1", "F10", "B10", "Balance Efectivo", E, 2025, "proyeccion", "IFP 4T2025", None),
        ("C I.5.1", "F11", "B11", "Balance C", B, 2025, "proyeccion", "IFP 4T2025", None),
        # Cuadro II.4.2: balance 2026, proyeccion IFP 4T25 (columnas E/F)
        ("C II.4.2 ", "F10", "B10", "Balance Efectivo", E, 2026, "proyeccion", "IFP 4T2025", None),
        ("C II.4.2 ", "F11", "B11", "Balance C", B, 2026, "proyeccion", "IFP 4T2025", None),
        # Cuadro III.6.2: balances 2027-2030 en % del PIB (sin acciones correctivas)
        ("C III.6.2", "C9", "B9", "Balance Efectivo", E, 2027, "proyeccion", "IFP 4T2025", None),
        ("C III.6.2", "D9", "B9", "Balance Efectivo", E, 2028, "proyeccion", "IFP 4T2025", None),
        ("C III.6.2", "E9", "B9", "Balance Efectivo", E, 2029, "proyeccion", "IFP 4T2025", None),
        ("C III.6.2", "F9", "B9", "Balance Efectivo", E, 2030, "proyeccion", "IFP 4T2025", None),
        ("C III.6.2", "C11", "B11", "Balance C", B, 2027, "proyeccion", "IFP 4T2025", None),
        ("C III.6.2", "D11", "B11", "Balance C", B, 2028, "proyeccion", "IFP 4T2025", None),
        ("C III.6.2", "E11", "B11", "Balance C", B, 2029, "proyeccion", "IFP 4T2025", None),
        ("C III.6.2", "F11", "B11", "Balance C", B, 2030, "proyeccion", "IFP 4T2025", None),
    ],
    "ifp-2026-1T-cuadros.xlsx": [
        # Cuadro I.7.2: balance 2025 efectivo y estructural (cierre estimado)
        ("C I.7.2", "C6", "A6", "Balance efectivo", E, 2025, "cierre_estimado", "IFP 1T2026", None),
        ("C I.7.2", "C13", "A13", "Balance Estructural", B, 2025, "cierre_estimado", "IFP 1T2026",
         "publicado como 'Balance Estructural'"),
        # Cuadro II.4.2: balance 2026, proyeccion IFP 1T26 (columnas E/F)
        ("C II.4.2", "F10", "B10", "Balance Efectivo", E, 2026, "proyeccion", "IFP 1T2026", None),
        ("C II.4.2", "F11", "B11", "Balance C", B, 2026, "proyeccion", "IFP 1T2026", None),
        # Cuadro III.6.1: balances 2027-2030, filas de % del PIB (13 y 15)
        ("C III.6.1", "C13", "B12", "Balance Efectivo", E, 2027, "proyeccion", "IFP 1T2026", None),
        ("C III.6.1", "D13", "B12", "Balance Efectivo", E, 2028, "proyeccion", "IFP 1T2026", None),
        ("C III.6.1", "E13", "B12", "Balance Efectivo", E, 2029, "proyeccion", "IFP 1T2026", None),
        ("C III.6.1", "F13", "B12", "Balance Efectivo", E, 2030, "proyeccion", "IFP 1T2026", None),
        ("C III.6.1", "C15", "B14", "Balance C", B, 2027, "proyeccion", "IFP 1T2026", None),
        ("C III.6.1", "D15", "B14", "Balance C", B, 2028, "proyeccion", "IFP 1T2026", None),
        ("C III.6.1", "E15", "B14", "Balance C", B, 2029, "proyeccion", "IFP 1T2026", None),
        ("C III.6.1", "F15", "B14", "Balance C", B, 2030, "proyeccion", "IFP 1T2026", None),
    ],
}


def main() -> int:
    registros = []
    for archivo, specs in MAPEO.items():
        entrada = buscar_en_manifiesto(archivo)
        ruta = RAIZ / entrada["ruta_local"]
        hojas = leer_xlsx(ruta)
        # los nombres de hoja de Dipres a veces traen espacios extra
        por_nombre = {h.strip(): h for h in hojas}
        for (hoja, celda, celda_etq, esperado, variable, anno, caracter, publicacion, nota) in specs:
            real = por_nombre.get(hoja.strip())
            if real is None:
                raise SystemExit(f"ERROR: hoja '{hoja}' no existe en {archivo}")
            celdas = hojas[real]
            hoja = real
            etiqueta = celdas.get(celda_etq, "")
            if esperado.lower() not in etiqueta.lower():
                raise SystemExit(
                    f"ERROR: etiqueta inesperada en {archivo} {hoja}!{celda_etq}: "
                    f"'{etiqueta}' no contiene '{esperado}' — layout cambiado, revisar mapeo.")
            bruto = celdas.get(celda)
            if bruto is None:
                raise SystemExit(f"ERROR: celda vacia {archivo} {hoja}!{celda}")
            try:
                valor = float(bruto)
            except ValueError:
                raise SystemExit(f"ERROR: valor no numerico en {archivo} {hoja}!{celda}: '{bruto}'")
            registros.append({
                "variable": variable,
                "anno": anno,
                "valor": valor,
                "unidad": "% del PIB",
                "caracter": caracter,
                "publicacion": publicacion,
                "nota": nota,
                "sha256_origen": entrada["sha256"],
                "origen": {"archivo": entrada["ruta_local"], "hoja": hoja, "celda": celda,
                           "etiqueta_fila": etiqueta.strip()},
                "derivado": False,
                "formula": None,
            })

    salida = {
        "descripcion": "Balance del Gobierno Central Total (% del PIB) segun cada publicacion "
                       "IFP de Dipres. Cifras extraidas celda por celda de los cuadros Excel "
                       "oficiales; cada registro apunta al sha256 de su artefacto en el manifiesto.",
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generado_por": "extraer_fiscal.py",
        "total_registros": len(registros),
        "registros": registros,
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(registros)} registros -> {SALIDA.relative_to(RAIZ).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
