#!/usr/bin/env python3
"""Extractor del Modulo F2 — concentracion del poder legislativo (medicion).

El sistema MIDE la concentracion; no propone como cambiarla ni dice si es mucha
o poca (CLAUDE.md, Bloque 0: el sistema expone, no concluye). Produce:

  1. data/derived/concentracion/escanos-camara-2026.json
     Composicion de la Camara por partido, indice HHI y numero efectivo de
     partidos (Laakso-Taagepera).
  2. data/derived/concentracion/pivotalidad-camara-2026.json
     Cuantas veces cada partido fue pivote: votaciones en que su bloque es al
     menos tan grande como el margen, de modo que votando al reves el resultado
     cambiaba de signo.

Dos honestidades que cambian los numeros y por eso se publican ambas:

  - Los independientes aparecen en la fuente bajo un mismo identificador. Contarlos
    como un bloque unico sobreestima la concentracion; contarlos como actores
    separados la subestima. Se publican LAS DOS lecturas, no un promedio.
  - La pivotalidad solo se calcula sobre votaciones de quorum simple, donde el
    resultado depende del signo del margen. Con quorum calificado la regla es
    otra; esas votaciones se cuentan aparte y se declaran, no se mezclan.

Sin dependencias: solo stdlib.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DERIVED = RAIZ / "data" / "derived" / "legislativo"
SALIDA = RAIZ / "data" / "derived" / "concentracion"

ID_INDEPENDIENTES = "IND"


def cargar(nombre: str) -> dict:
    ruta = DERIVED / nombre
    if not ruta.exists():
        raise SystemExit(f"Falta {ruta.relative_to(RAIZ).as_posix()}; corra antes extraer_nominal.py")
    return json.loads(ruta.read_text(encoding="utf-8"))


def sha256_conjunto(hashes: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()


def partido_en(militancias: list[dict], fecha: str) -> tuple[str | None, str | None]:
    for m in militancias:
        desde, hasta = m.get("desde"), m.get("hasta")
        if desde and fecha < desde[:19]:
            continue
        if hasta and fecha > hasta[:19]:
            continue
        return m.get("partido_id"), m.get("partido_nombre")
    return None, None


def hhi(cuotas: list[float]) -> float:
    """Herfindahl-Hirschman sobre participaciones que suman 1. Escala 0 a 1."""
    return sum(c * c for c in cuotas)


def numero_efectivo(cuotas: list[float]) -> float:
    """Laakso-Taagepera: 1/HHI. Lee como 'cuantos actores de igual peso equivalen'."""
    h = hhi(cuotas)
    return (1 / h) if h else 0.0


def indices(conteos: dict[str, int]) -> dict:
    total = sum(conteos.values())
    if not total:
        return {"total": 0, "hhi": None, "hhi_escala_10000": None,
                "numero_efectivo_partidos": None}
    cuotas = [n / total for n in conteos.values()]
    return {
        "total": total,
        "hhi": round(hhi(cuotas), 6),
        "hhi_escala_10000": round(hhi(cuotas) * 10000, 1),
        "numero_efectivo_partidos": round(numero_efectivo(cuotas), 3),
    }


def main() -> int:
    nominal = cargar("votos-nominales-2026.json")
    padron = cargar("diputados.json")
    votaciones = nominal["registros"]
    if not votaciones:
        raise SystemExit("Sin votaciones con voto nominal; corra antes ingesta_masiva.py")

    militancias = {str(r["id"]): r["militancias"] for r in padron["registros"]}
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fecha_ref = max(v["fecha"] for v in votaciones)
    procedencia = {
        "generado_utc": ahora,
        "generado_por": "extraer_concentracion.py",
        "derivado": True,
        "artefactos_usados": len(votaciones),
        "sha256_conjunto": sha256_conjunto([v["sha256_origen"] for v in votaciones]),
        "sha256_conjunto_formula": "sha256 de los sha256 de cada artefacto usado, "
                                   "ordenados alfabeticamente y unidos por salto de linea",
        "sha256_padrones": [p["sha256"] for p in padron["padrones_fusionados"]],
    }
    SALIDA.mkdir(parents=True, exist_ok=True)

    # --- 1. Composicion de la Camara y concentracion -----------------------
    # El corpus abarca dos periodos legislativos, asi que "quien integra la Camara"
    # no se infiere de las fechas de periodo de la fuente (que traen registros
    # inconsistentes): se OBSERVA. La composicion es la de quienes registran voto
    # en la ultima votacion del corpus, cada uno con su militancia a esa fecha.
    ultima = max(votaciones, key=lambda v: v["fecha"])
    presentes = set(ultima["votos"])
    total_votantes_corpus = len({d for v in votaciones for d in v["votos"]})
    bloque: dict[str, int] = {}
    nombres_partido: dict[str, str] = {}
    individual: dict[str, int] = {}
    sin_partido = 0
    for d in presentes:
        pid, pnombre = partido_en(militancias.get(d, []), fecha_ref)
        if pid is None:
            sin_partido += 1
            continue
        nombres_partido[pid] = pnombre
        bloque[pid] = bloque.get(pid, 0) + 1
        # Lectura alternativa: cada independiente cuenta como un actor propio.
        clave = f"{ID_INDEPENDIENTES}:{d}" if pid == ID_INDEPENDIENTES else pid
        individual[clave] = individual.get(clave, 0) + 1

    reparto = sorted(
        ({"partido_id": pid, "partido_nombre": nombres_partido[pid], "escanos": n,
          "cuota": round(n / sum(bloque.values()), 6)} for pid, n in bloque.items()),
        key=lambda x: -x["escanos"])

    (SALIDA / "escanos-camara-2026.json").write_text(json.dumps({
        "descripcion": "Composicion de la Camara de Diputadas y Diputados por partido, "
                       "contando a quienes registran voto en las votaciones de Sala del "
                       "corpus, con la militancia que la Camara registra para la fecha de "
                       "referencia. Se acompanan dos indices de concentracion de uso "
                       "estandar. El sistema no califica el nivel resultante.",
        **procedencia,
        "fecha_referencia": fecha_ref,
        "votacion_de_referencia": ultima["id"],
        "criterio_composicion": "Integran la Camara quienes registran voto en la votacion "
                                "de referencia (la ultima del corpus). Es una observacion, "
                                "no una inferencia a partir de fechas de periodo.",
        "personas_en_la_votacion_de_referencia": len(presentes),
        "personas_que_votaron_en_todo_el_corpus": total_votantes_corpus,
        "personas_sin_militancia_registrada_a_esa_fecha": sin_partido,
        "nota_dos_periodos": "El corpus cubre votaciones de dos periodos legislativos "
                             "(el actual comenzo el 2026-03-11), por eso votaron mas "
                             "personas de las que integran la Camara en la fecha de "
                             "referencia.",
        "formulas": {
            "hhi": "suma de los cuadrados de las cuotas de escanos (0 a 1); "
                   "en escala 0 a 10000 se multiplica por 10000",
            "numero_efectivo_partidos": "1 / hhi (Laakso-Taagepera)",
        },
        "lectura_independientes_como_bloque": indices(bloque),
        "lectura_independientes_por_separado": indices(individual),
        "nota_independientes": "Las dos lecturas se publican juntas porque cambian el "
                               "resultado: agrupar a los independientes bajo un mismo "
                               "identificador eleva la concentracion medida, y separarlos "
                               "la reduce. La fuente no declara cual corresponde.",
        "total_registros": len(reparto),
        "registros": reparto,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: escanos de {len(reparto)} partidos "
          f"(HHI bloque {indices(bloque)['hhi_escala_10000']}, "
          f"separado {indices(individual)['hhi_escala_10000']})")

    # --- 2. Pivotalidad: cuando un partido decide el signo del resultado ----
    simples = decisivas_totales = 0
    otras_quorum = 0
    pivote: dict[str, int] = {}
    participaciones: dict[str, int] = {}
    for v in votaciones:
        if (v.get("quorum") or "").strip().lower() != "quórum simple":
            otras_quorum += 1
            continue
        simples += 1
        si = sum(1 for c in v["votos"].values() if c == "A")
        no = sum(1 for c in v["votos"].values() if c == "C")
        margen = abs(si - no)
        por_partido: dict[str, int] = {}
        for d, codigo in v["votos"].items():
            if codigo not in ("A", "C"):
                continue
            pid, _ = partido_en(militancias.get(d, []), v["fecha"])
            if pid is None:
                continue
            por_partido[pid] = por_partido.get(pid, 0) + 1
        hubo = False
        for pid, n in por_partido.items():
            participaciones[pid] = participaciones.get(pid, 0) + 1
            # Si el bloque es al menos tan grande como el margen, votando al reves
            # el signo del resultado cambia: el partido fue pivote.
            if n >= margen:
                pivote[pid] = pivote.get(pid, 0) + 1
                hubo = True
        decisivas_totales += int(hubo)

    filas = sorted(
        ({"partido_id": pid,
          "partido_nombre": nombres_partido.get(pid),
          "votaciones_en_que_participo": participaciones.get(pid, 0),
          "votaciones_en_que_fue_pivote": n,
          "pivote_pct": round(100 * n / participaciones[pid], 2) if participaciones.get(pid) else None,
          "es_agregacion_no_comparable": pid == ID_INDEPENDIENTES}
         for pid, n in pivote.items()),
        key=lambda x: -x["votaciones_en_que_fue_pivote"])

    (SALIDA / "pivotalidad-camara-2026.json").write_text(json.dumps({
        "descripcion": "Veces en que cada partido fue pivote en votaciones de Sala de "
                       "quorum simple: su bloque de votos es al menos tan grande como el "
                       "margen entre a favor y en contra, de modo que votando al reves el "
                       "resultado cambiaba de signo. Es una medicion de poder decisorio "
                       "observado, no una evaluacion de conducta.",
        **procedencia,
        "formula": "pivote si votos_del_partido >= |a_favor - en_contra| en la votacion; "
                   "pivote_pct = 100 * votaciones_en_que_fue_pivote / "
                   "votaciones_en_que_participo",
        "alcance": "Solo votaciones de quorum simple, donde el resultado depende del signo "
                   "del margen. Las de quorum calificado siguen otra regla y quedan fuera.",
        "nota_independientes": "La fila de independientes agrupa a personas que no forman "
                               "un bloque y no deciden en conjunto: su cifra no es "
                               "comparable con la de un partido y va marcada con "
                               "es_agregacion_no_comparable.",
        "votaciones_de_quorum_simple": simples,
        "votaciones_de_otro_quorum_excluidas": otras_quorum,
        "votaciones_con_al_menos_un_pivote": decisivas_totales,
        "concentracion_del_poder_decisorio": indices(pivote),
        "total_registros": len(filas),
        "registros": filas,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: pivotalidad sobre {simples} votaciones de quorum simple "
          f"({otras_quorum} de otro quorum excluidas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
