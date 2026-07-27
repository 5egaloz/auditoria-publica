#!/usr/bin/env python3
"""Extractor del Modulo C (Tendencia) — coincidencia de voto medida.

Calcula, desde el voto nominal ya ingerido y verificado:
  1. Cohesion por partido (indice de Rice) por votacion y promedio del periodo.
  2. Matriz de coincidencia entre parlamentarios (% de votaciones con voto igual).
  3. Eje empirico: primer componente principal de la matriz de votos.

Tres reglas que hacen publicable esto (CLAUDE.md, Bloques 0 y 4):

  - El eje NO se llama izquierda-derecha ni nada parecido. Es un orden por
    cercania de voto, y su SIGNO ES ARBITRARIO (invertirlo da el mismo eje).
    Cualquier etiqueta ideologica es un dato de otra fuente, no de este calculo.
  - Si el primer componente explica poca varianza, el eje NO se publica: un
    orden de parlamentarios que no describe los datos seria un adorno.
  - Solo se computan votaciones con posicion sustantiva (a favor, en contra o
    abstencion). Una ausencia no es una posicion, y contarla como tal inventaria
    coincidencias que nadie expreso.

El partido de cada persona es el que la Camara registra para la fecha de la
votacion; no se interpreta ni se agrupa en coaliciones.

Sin dependencias: solo stdlib.
"""

import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DERIVED = RAIZ / "data" / "derived" / "legislativo"
SALIDA = RAIZ / "data" / "derived" / "tendencia"

# Opciones que expresan una posicion. "No Vota", "Dispensado" y "Pareo" quedan
# fuera: son ausencia o acuerdo de no votar, no una postura.
POSICIONES = {"A", "C", "B"}

MIN_VOTACIONES = 30          # base minima para publicar cualquier indicador
MIN_COMUNES_PAR = 20         # votaciones en comun minimas para comparar dos personas
MIN_MIEMBROS_PARTIDO = 3     # bajo esto, la cohesion describe personas, no un partido
MIN_VARIANZA_EJE = 0.40      # si PC1 explica menos, el eje no se publica


def cargar(nombre: str) -> dict:
    ruta = DERIVED / nombre
    if not ruta.exists():
        raise SystemExit(f"Falta {ruta.relative_to(RAIZ).as_posix()}; corra antes extraer_nominal.py")
    return json.loads(ruta.read_text(encoding="utf-8"))


def sha256_conjunto(hashes: list[str]) -> str:
    """Huella unica del conjunto de artefactos usados: reproducible por terceros."""
    unido = "\n".join(sorted(hashes)).encode("utf-8")
    return hashlib.sha256(unido).hexdigest()


def partido_en(militancias: list[dict], fecha: str) -> tuple[str | None, str | None]:
    """Partido registrado por la Camara para esa persona en esa fecha."""
    for m in militancias:
        desde, hasta = m.get("desde"), m.get("hasta")
        if desde and fecha < desde[:19]:
            continue
        if hasta and fecha > hasta[:19]:
            continue
        return m.get("partido_id"), m.get("partido_nombre")
    return None, None


# --------------------------------------------------------------------------
# 1. Cohesion por partido (indice de Rice)
# --------------------------------------------------------------------------

def cohesion_por_partido(votaciones: list[dict], padron: dict) -> list[dict]:
    militancias = {str(r["id"]): r["militancias"] for r in padron["registros"]}
    nombres = {str(r["id"]): r["nombre"] for r in padron["registros"]}
    acumulado: dict[str, dict] = {}

    for v in votaciones:
        por_partido: dict[tuple, list[str]] = {}
        for id_dip, codigo in v["votos"].items():
            if codigo not in ("A", "C"):   # Rice se define sobre a favor / en contra
                continue
            pid, pnombre = partido_en(militancias.get(id_dip, []), v["fecha"])
            if pid is None:
                continue
            por_partido.setdefault((pid, pnombre), []).append(codigo)
        for (pid, pnombre), codigos in por_partido.items():
            si = codigos.count("A")
            no = codigos.count("C")
            if si + no < MIN_MIEMBROS_PARTIDO:
                continue
            rice = abs(si - no) / (si + no)
            registro = acumulado.setdefault(pid, {
                "partido_id": pid, "partido_nombre": pnombre,
                "votaciones_consideradas": 0, "suma_rice": 0.0, "miembros": set()})
            registro["votaciones_consideradas"] += 1
            registro["suma_rice"] += rice
        for id_dip in v["votos"]:
            pid, _ = partido_en(militancias.get(id_dip, []), v["fecha"])
            if pid in acumulado:
                acumulado[pid]["miembros"].add(nombres.get(id_dip, id_dip))

    salida = []
    for registro in acumulado.values():
        n = registro["votaciones_consideradas"]
        if n < MIN_VOTACIONES:
            continue
        salida.append({
            "partido_id": registro["partido_id"],
            "partido_nombre": registro["partido_nombre"],
            "miembros_observados": len(registro["miembros"]),
            "votaciones_consideradas": n,
            "cohesion_rice_promedio": round(registro["suma_rice"] / n, 4),
        })
    salida.sort(key=lambda x: -x["cohesion_rice_promedio"])
    return salida


# --------------------------------------------------------------------------
# 2. Matriz de coincidencia
# --------------------------------------------------------------------------

def matriz_coincidencia(votaciones: list[dict], nombres: dict) -> tuple[list[dict], list[str]]:
    ids = sorted({d for v in votaciones for d in v["votos"]}, key=lambda x: int(x))
    posicion = {d: {} for d in ids}
    for v in votaciones:
        for d, codigo in v["votos"].items():
            if codigo in POSICIONES:
                posicion[d][v["id"]] = codigo

    pares = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            va, vb = posicion[a], posicion[b]
            comunes = va.keys() & vb.keys()
            if len(comunes) < MIN_COMUNES_PAR:
                continue
            iguales = sum(1 for k in comunes if va[k] == vb[k])
            pares.append({
                "a": int(a), "b": int(b),
                "nombre_a": nombres.get(a), "nombre_b": nombres.get(b),
                "votaciones_comunes": len(comunes),
                "votaciones_iguales": iguales,
                "coincidencia_pct": round(100 * iguales / len(comunes), 2),
            })
    return pares, ids


# --------------------------------------------------------------------------
# 3. Eje empirico (primer componente principal, por iteracion de potencia)
# --------------------------------------------------------------------------

def eje_empirico(votaciones: list[dict], ids: list[str], nombres: dict) -> dict:
    """Primer componente de la matriz de votos (+1 a favor, -1 en contra, 0 resto).

    Se centra por columna y se itera u <- X (X^T u) hasta converger. El resultado
    es un ORDEN por cercania de voto: el signo no tiene significado.
    """
    indice = {d: i for i, d in enumerate(ids)}
    columnas = []
    for v in votaciones:
        col = [0.0] * len(ids)
        aporta = 0
        for d, codigo in v["votos"].items():
            if codigo == "A":
                col[indice[d]] = 1.0
                aporta += 1
            elif codigo == "C":
                col[indice[d]] = -1.0
                aporta += 1
        if aporta >= MIN_MIEMBROS_PARTIDO:
            media = sum(col) / len(col)
            columnas.append([x - media for x in col])

    n_dip, n_vot = len(ids), len(columnas)
    if n_vot < MIN_VOTACIONES:
        return {"publicable": False,
                "motivo": f"sin dato disponible: {n_vot} votaciones utilizables, "
                          f"el minimo es {MIN_VOTACIONES}"}

    total_varianza = sum(x * x for col in columnas for x in col)
    if total_varianza == 0:
        return {"publicable": False, "motivo": "sin dato disponible: varianza nula"}

    random.seed(0)  # reproducible: un tercero obtiene exactamente el mismo eje
    u = [random.uniform(-1, 1) for _ in range(n_dip)]
    valor = 0.0
    for _ in range(300):
        w = [sum(col[i] * u[i] for i in range(n_dip)) for col in columnas]
        nuevo = [0.0] * n_dip
        for j, col in enumerate(columnas):
            wj = w[j]
            if wj:
                for i in range(n_dip):
                    nuevo[i] += col[i] * wj
        norma = sum(x * x for x in nuevo) ** 0.5
        if norma == 0:
            return {"publicable": False, "motivo": "sin dato disponible: el componente no converge"}
        u = [x / norma for x in nuevo]
        if abs(norma - valor) < 1e-10:
            break
        valor = norma

    varianza_pc1 = valor  # ||X X^T u|| con u unitario = autovalor dominante
    proporcion = varianza_pc1 / total_varianza
    posiciones = sorted(
        ({"diputado_id": int(ids[i]), "nombre": nombres.get(ids[i]),
          "puntaje_eje": round(u[i], 6)} for i in range(n_dip)),
        key=lambda x: x["puntaje_eje"])
    for orden, p in enumerate(posiciones, 1):
        p["orden"] = orden

    if proporcion < MIN_VARIANZA_EJE:
        return {"publicable": False,
                "varianza_explicada": round(proporcion, 4),
                "motivo": f"sin dato disponible: el primer componente explica "
                          f"{round(100 * proporcion, 1)}% de la varianza y el minimo "
                          f"para publicarlo es {round(100 * MIN_VARIANZA_EJE)}%"}

    return {
        "publicable": True,
        "varianza_explicada": round(proporcion, 4),
        "votaciones_utilizadas": n_vot,
        "advertencia_signo": "El signo del eje es arbitrario: invertirlo describe el mismo "
                             "orden. El eje mide cercania de voto, no ideologia, y no "
                             "corresponde a ninguna etiqueta politica.",
        "formula": "primer componente principal de la matriz diputado x votacion "
                   "(+1 a favor, -1 en contra, 0 sin posicion), centrada por votacion; "
                   "obtenido por iteracion de potencia con semilla fija 0",
        "posiciones": posiciones,
    }


def main() -> int:
    nominal = cargar("votos-nominales-2026.json")
    padron = cargar("diputados.json")
    votaciones = nominal["registros"]
    nombres = {str(r["id"]): r["nombre"] for r in padron["registros"]}
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    huella = sha256_conjunto([v["sha256_origen"] for v in votaciones])

    procedencia = {
        "generado_utc": ahora,
        "generado_por": "extraer_tendencia.py",
        "derivado": True,
        "artefactos_usados": len(votaciones),
        "sha256_conjunto": huella,
        "sha256_conjunto_formula": "sha256 de los sha256 de cada artefacto usado, "
                                   "ordenados alfabeticamente y unidos por salto de linea",
        "sha256_padrones": [p["sha256"] for p in padron["padrones_fusionados"]],
        "criterio_posicion": "solo votaciones con posicion sustantiva (a favor, en contra "
                             "o abstencion); las ausencias no cuentan como posicion",
    }

    SALIDA.mkdir(parents=True, exist_ok=True)

    cohesion = cohesion_por_partido(votaciones, padron)
    (SALIDA / "cohesion-partidos-2026.json").write_text(json.dumps({
        "descripcion": "Indice de Rice de cohesion por partido en las votaciones de Sala "
                       "de la Camara con voto nominal publicado. Rice = |a favor - en contra| "
                       "/ (a favor + en contra) entre los miembros del partido en cada "
                       "votacion; se informa el promedio del periodo. El partido de cada "
                       "persona es el que la Camara registra para la fecha de la votacion.",
        **procedencia,
        "formula": "cohesion_rice_promedio = promedio por votacion de "
                   "|a_favor - en_contra| / (a_favor + en_contra) entre miembros del partido",
        "umbrales": {"min_miembros_por_votacion": MIN_MIEMBROS_PARTIDO,
                     "min_votaciones_por_partido": MIN_VOTACIONES},
        "total_registros": len(cohesion),
        "registros": cohesion,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: cohesion de {len(cohesion)} partidos")

    pares, ids = matriz_coincidencia(votaciones, nombres)
    (SALIDA / "coincidencia-pares-2026.json").write_text(json.dumps({
        "descripcion": "Porcentaje de votaciones en que cada par de diputadas y diputados "
                       "registro la misma opcion, sobre las votaciones en que ambos fijaron "
                       "posicion. Es una medicion de coincidencia de voto: no clasifica ni "
                       "ordena ideologicamente a nadie.",
        **procedencia,
        "formula": "coincidencia_pct = 100 * votaciones_iguales / votaciones_comunes",
        "umbrales": {"min_votaciones_comunes": MIN_COMUNES_PAR},
        "total_registros": len(pares),
        "registros": pares,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OK: {len(pares)} pares de coincidencia")

    eje = eje_empirico(votaciones, ids, nombres)
    (SALIDA / "eje-empirico-2026.json").write_text(json.dumps({
        "descripcion": "Ordenamiento de diputadas y diputados por cercania de voto "
                       "(primer componente principal de la matriz de votaciones). "
                       "NO es una escala ideologica y su signo es arbitrario.",
        **procedencia,
        **eje,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    if eje.get("publicable"):
        print(f"OK: eje empirico publicable, varianza explicada "
              f"{round(100 * eje['varianza_explicada'], 1)}%")
    else:
        print(f"EJE NO PUBLICABLE: {eje['motivo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
