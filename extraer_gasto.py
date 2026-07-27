#!/usr/bin/env python3
"""Extractor del Modulo F1 — concentracion de adjudicaciones del Estado.

Lee el archivo mensual de licitaciones de ChileCompra ya ingerido y mide cuanto
del monto adjudicado se concentra en cuantos proveedores: monto y numero de
adjudicaciones por RUT, HHI, numero efectivo de proveedores y cuotas top-N,
a nivel nacional y por region del organismo comprador.

Tres limites que se declaran en la propia salida y deben viajar con la cifra:

  - Es LICITACIONES, no todo el gasto del Estado. Quedan fuera Convenio Marco,
    Compra Agil y trato directo, que son canales distintos con sus propios
    archivos. Presentar esto como "el gasto del Estado" seria inexacto.
  - Es un MES. No se extrapola a un anno ni se compara con otros periodos que
    no esten ingeridos.
  - Solo se suman montos en pesos chilenos. Las lineas en dolar, UF o euro NO
    se convierten (convertir exige un tipo de cambio que no esta en la fuente,
    y este sistema no estima); se cuentan aparte y se informan.
  - La fuente contiene lineas cuya magnitud excede cualquier rango plausible
    (una sola linea puede superar el presupuesto anual del pais). No se corrigen
    ni se borran: borrarlas seria una decision editorial y corregirlas seria
    inventar. Se publica el agregado tal como lo declara la fuente Y su
    sensibilidad a excluir las lineas sobre umbrales declarados, mas el detalle
    de las mayores lineas con su codigo para que cualquiera las verifique.

Criterio de adjudicacion: fila con Estado "Adjudicada" y oferta "Seleccionada",
tomando el monto de la columna MontoLineaAdjudica.

El sistema mide; no dice si el nivel de concentracion es alto o bajo.

Sin dependencias: solo stdlib.
"""

import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
SALIDA = RAIZ / "data" / "derived" / "concentracion"

ARCHIVO = "chilecompra-licitaciones-2026-06.zip"
MONEDA_BASE = "Peso Chileno"

csv.field_size_limit(10_000_000)


def entradas_manifiesto() -> list[dict]:
    with MANIFIESTO.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def indices(montos: dict[str, float]) -> dict:
    total = sum(montos.values())
    if not total:
        return {"total": 0, "actores": 0, "hhi": None,
                "hhi_escala_10000": None, "numero_efectivo": None}
    cuotas = [m / total for m in montos.values()]
    h = sum(c * c for c in cuotas)
    return {
        "total": round(total, 2),
        "actores": len(montos),
        "hhi": round(h, 6),
        "hhi_escala_10000": round(h * 10000, 1),
        "numero_efectivo": round(1 / h, 3) if h else None,
    }


def main() -> int:
    entrada = next((e for e in entradas_manifiesto()
                    if e["ruta_local"].endswith(ARCHIVO)), None)
    if entrada is None:
        raise SystemExit(f"Falta {ARCHIVO} en el manifiesto; ingieralo con ingesta.py")

    z = zipfile.ZipFile(RAIZ / entrada["ruta_local"])
    nombre_csv = z.namelist()[0]

    monto_por_rut: dict[str, float] = defaultdict(float)
    lineas_por_rut: dict[str, int] = defaultdict(int)
    nombre_de: dict[str, str] = {}
    monto_por_region: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    monto_por_organismo: dict[str, float] = defaultdict(float)

    filas = adjudicadas = usadas = 0
    lineas: list[tuple] = []
    otra_moneda: dict[str, int] = defaultdict(int)
    sin_monto = sin_rut = 0

    with z.open(nombre_csv) as f:
        lector = csv.reader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")
        encabezado = next(lector)
        col = {c: i for i, c in enumerate(encabezado)}
        for campo in ("Estado", "Oferta seleccionada", "RutProveedor",
                      "RazonSocialProveedor", "MontoLineaAdjudica",
                      "Moneda de la Oferta", "RegionUnidad", "NombreOrganismo"):
            if campo not in col:
                raise SystemExit(f"El archivo no trae la columna '{campo}'")

        for fila in lector:
            filas += 1
            if len(fila) != len(encabezado):
                continue
            if fila[col["Estado"]] != "Adjudicada":
                continue
            if fila[col["Oferta seleccionada"]].strip() != "Seleccionada":
                continue
            adjudicadas += 1

            moneda = (fila[col["Moneda de la Oferta"]] or "").strip()
            if moneda != MONEDA_BASE:
                otra_moneda[moneda or "sin declarar"] += 1
                continue  # no se convierte: convertir seria estimar

            rut = (fila[col["RutProveedor"]] or "").strip()
            if not rut:
                sin_rut += 1
                continue
            try:
                monto = float((fila[col["MontoLineaAdjudica"]] or "0").replace(",", "."))
            except ValueError:
                monto = 0.0
            if monto <= 0:
                sin_monto += 1
                continue

            usadas += 1
            lineas.append((monto, fila[col["CodigoExterno"]], rut,
                           nombre_de.get(rut) or (fila[col["RazonSocialProveedor"]] or "").strip(),
                           (fila[col["NombreOrganismo"]] or "").strip()))
            monto_por_rut[rut] += monto
            lineas_por_rut[rut] += 1
            nombre_de.setdefault(rut, (fila[col["RazonSocialProveedor"]] or "").strip())
            monto_por_region[(fila[col["RegionUnidad"]] or "sin dato disponible").strip()][rut] += monto
            monto_por_organismo[(fila[col["NombreOrganismo"]] or "sin dato disponible").strip()] += monto

    if not monto_por_rut:
        raise SystemExit("No se sumo ninguna adjudicacion; revise el formato del archivo")

    total = sum(monto_por_rut.values())
    ranking = sorted(
        ({"rut": rut, "razon_social": nombre_de.get(rut, ""),
          "monto_adjudicado_clp": round(m, 2),
          "lineas_adjudicadas": lineas_por_rut[rut],
          "cuota": round(m / total, 6)} for rut, m in monto_por_rut.items()),
        key=lambda x: (-x["monto_adjudicado_clp"], x["rut"]))
    acumulado = 0.0
    for puesto, fila in enumerate(ranking, 1):
        acumulado += fila["monto_adjudicado_clp"]
        fila["puesto"] = puesto
        fila["cuota_acumulada"] = round(acumulado / total, 6)

    def top(n: int) -> dict:
        corte = ranking[:n]
        suma = sum(f["monto_adjudicado_clp"] for f in corte)
        return {"proveedores": len(corte), "monto_clp": round(suma, 2),
                "cuota": round(suma / total, 6)}

    compradores = sorted(
        ({"organismo": o, "monto_adjudicado_clp": round(m, 2),
          "cuota": round(m / total, 6)} for o, m in monto_por_organismo.items()),
        key=lambda x: -x["monto_adjudicado_clp"])[:25]

    # Sensibilidad: como cambian los indices si se excluyen las lineas sobre
    # cada umbral. No se elige un umbral "correcto": se muestran varios para que
    # el lector vea de cuantos registros depende el resultado.
    UMBRALES = [10 ** 12, 10 ** 11, 10 ** 10]
    sensibilidad = {}
    for umbral in UMBRALES:
        recorte: dict[str, float] = defaultdict(float)
        excluidas = 0
        for monto, _cod, rut, _rs, _org in lineas:
            if monto > umbral:
                excluidas += 1
                continue
            recorte[rut] += monto
        indice = indices(recorte)
        indice["lineas_excluidas"] = excluidas
        indice["umbral_clp"] = umbral
        sensibilidad[f"excluyendo lineas sobre {umbral:,} CLP".replace(",", ".")] = indice

    mayores = [{
        "monto_clp": round(m, 2), "codigo_externo": cod, "rut_proveedor": rut,
        "razon_social": rs, "organismo": org,
        "enlace_fuente": "https://www.mercadopublico.cl/Procurement/Modules/RFB/"
                         f"DetailsAcquisition.aspx?idlicitacion={cod}",
    } for m, cod, rut, rs, org in sorted(lineas, key=lambda x: -x[0])[:25]]

    montos_ordenados = sorted(m for m, *_ in lineas)
    mediana = montos_ordenados[len(montos_ordenados) // 2]

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    salida = {
        "descripcion": "Concentracion de las adjudicaciones de licitaciones publicadas en "
                       "Mercado Publico durante junio de 2026, por proveedor adjudicado. "
                       "El monto de cada linea es el que declara la fuente en "
                       "MontoLineaAdjudica. El sistema no califica el nivel resultante.",
        "generado_utc": ahora,
        "generado_por": "extraer_gasto.py",
        "derivado": True,
        "sha256_origen": entrada["sha256"],
        "url_fuente": entrada["url_fuente"],
        "ruta_local": entrada["ruta_local"],
        "periodo": "2026-06",
        "limite_de_la_medicion": "Cubre LICITACIONES de un solo mes. Quedan fuera Convenio "
                                 "Marco, Compra Agil y trato directo, que son canales "
                                 "distintos: esto no es el total del gasto del Estado ni "
                                 "puede extrapolarse a un anno. Solo se suman montos en "
                                 "pesos chilenos; las lineas en otra moneda no se convierten "
                                 "y se informan aparte.",
        "criterio_de_seleccion": "filas con Estado 'Adjudicada' y Oferta seleccionada "
                                 "'Seleccionada', con monto mayor que cero en pesos chilenos",
        "formulas": {
            "hhi": "suma de los cuadrados de las cuotas de monto adjudicado por proveedor "
                   "(0 a 1); en escala 0 a 10000 se multiplica por 10000",
            "numero_efectivo": "1 / hhi (Laakso-Taagepera)",
            "cuota_acumulada": "suma de las cuotas desde el puesto 1 hasta el actual",
        },
        "filas_leidas": filas,
        "lineas_adjudicadas_y_seleccionadas": adjudicadas,
        "lineas_usadas": usadas,
        "lineas_en_otra_moneda_no_convertidas": dict(sorted(otra_moneda.items())),
        "lineas_sin_monto_positivo": sin_monto,
        "lineas_sin_rut_de_proveedor": sin_rut,
        "monto_total_adjudicado_clp": round(total, 2),
        "advertencia_valores_atipicos": "La fuente publica lineas cuya magnitud excede "
                                        "cualquier rango plausible: la mayor de este mes "
                                        "supera por si sola el presupuesto anual del pais. "
                                        "No se corrigen ni se eliminan. Por eso los indices "
                                        "declarados estan dominados por unos pocos registros "
                                        "y NO deben citarse solos: cite junto a ellos la "
                                        "seccion sensibilidad y revise mayores_lineas.",
        "mediana_monto_por_linea_clp": round(mediana, 2),
        "indices_nacionales": indices(monto_por_rut),
        "sensibilidad": sensibilidad,
        "mayores_lineas": mayores,
        "top_1": top(1), "top_10": top(10), "top_100": top(100), "top_1000": top(1000),
        "por_region": {r: indices(d) for r, d in sorted(monto_por_region.items())},
        "mayores_organismos_compradores": compradores,
        "total_registros": len(ranking),
        "registros": ranking[:2000],
        "nota_registros": "Se publican los 2000 proveedores de mayor monto; los indices y "
                          "los totales se calculan sobre el universo completo.",
    }
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / "adjudicaciones-licitaciones-2026-06.json"
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    idx = salida["indices_nacionales"]
    print(f"OK: {usadas} lineas adjudicadas de {idx['actores']} proveedores "
          f"-> {ruta.relative_to(RAIZ).as_posix()}")
    print(f"   monto total {total/1e9:.1f} mil millones CLP | HHI {idx['hhi_escala_10000']} | "
          f"proveedores efectivos {idx['numero_efectivo']}")
    print(f"   top-10 = {round(100 * salida['top_10']['cuota'], 1)}% | "
          f"top-100 = {round(100 * salida['top_100']['cuota'], 1)}% del monto")
    print(f"   mediana por linea {mediana/1e6:.1f} millones CLP | mayor linea "
          f"{mayores[0]['monto_clp']/1e12:.1f} billones CLP ({mayores[0]['codigo_externo']})")
    for etiqueta, indice in sensibilidad.items():
        print(f"   {etiqueta}: HHI {indice['hhi_escala_10000']}, "
              f"efectivos {indice['numero_efectivo']}, "
              f"{indice['lineas_excluidas']} lineas fuera")
    if otra_moneda:
        print(f"   lineas en otra moneda no convertidas: {dict(otra_moneda)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
