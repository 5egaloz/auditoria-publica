#!/usr/bin/env python3
"""Capa B del modulo de Prensa — la lectura critica, sellada como NO verificable.

QUE ES
  El resto del sistema produce afirmaciones que un tercero recalcula: un hash, un
  conteo, una cifra leida de una celda. Esta capa no. Aca un modelo de lenguaje
  escribe una lectura critica en prosa sobre el material ya sellado, y un modelo
  de lenguaje no es reproducible: la misma entrada puede dar dos salidas.

  Entonces el sello no dice "esto es cierto". Dice EXACTAMENTE QUE PRODUJO ESTE
  TEXTO: que modelo, con que prompt, sobre que entrada, y con que salida. Es
  trazabilidad de procedencia, no de verdad, y se publica con esa etiqueta.

  Precedente en el repo: prompts/hashes.json hace lo mismo con los prompts del
  agente. La custodia es el historial de Git, no manifest.jsonl, que esta
  reservado a originales del Estado (CLAUDE.md, Bloque 1).

QUE NO HACE
  · No funda ningun veredicto ni aporta ninguna cifra al sistema. Si un numero de
    esta capa desapareciera, ningun dato publicado cambiaria.
  · No llama a ninguna API. El texto lo escribe el modelo en sesion, siguiendo
    prompts/analisis-prensa.md, y este script lo recibe, lo revisa y lo sella.
    Gasto $0, stdlib pura, sin red.

LA REVISION QUE SI ES DETERMINISTA
  Antes de sellar, el texto pasa por filtro.py — el mismo validador que gobierna
  las respuestas del agente — con el material sellado como payload. Rechaza si:
  aparece una cifra que no esta en el material, lenguaje valorativo, un giro de
  juicio, o una etiqueta ideologica sin fuente nombrada. Mas los chequeos
  estructurales del prompt: las cuatro secciones, el cierre literal y la
  extension. Un analisis que no pasa NO se sella y se dice por que.

  El texto entre comillas queda exento, porque es cita literal del articulo: esa
  excepcion ya existe en filtro.py (Bloque 4, regla 5).

Uso:
  python analisis_ia.py --sha256 <sha del articulo> --analisis borrador.md \\
      --modelo claude-opus-5
  python analisis_ia.py --revisar --analisis borrador.md --sha256 <sha>   (sin sellar)
  python analisis_ia.py --verificar
  python analisis_ia.py --autotest

Sin dependencias: solo stdlib.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import filtro

RAIZ = Path(__file__).resolve().parent
REGISTRO = RAIZ / "prensa" / "registro.jsonl"
PROMPT = RAIZ / "prompts" / "analisis-prensa.md"
DERIVADO = RAIZ / "data" / "derived" / "prensa"
SALIDA = DERIVADO / "analisis"

SECCIONES = [
    "## Lo que se puede comprobar hoy",
    "## Lo que no queda contra qué comprobar",
    "## Posibles soluciones",
    "## Lo que este análisis no pudo evaluar",
]
CIERRE = ("Este análisis es una lectura de un modelo de lenguaje sobre el material sellado. "
          "No es verificable y no sostiene ninguna cifra del sistema: las cifras están en "
          "los bloques sellados de arriba, con su hash.")
MIN_PALABRAS, MAX_PALABRAS = 250, 500


def sha256_de(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def buscar_entrada(sha256: str) -> dict | None:
    if not REGISTRO.exists():
        return None
    with REGISTRO.open(encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                e = json.loads(linea)
                if e.get("sha256") == sha256:
                    return e
    return None


def material(sha256: str) -> tuple[dict, dict]:
    """Las dos salidas selladas sobre las que el analisis puede razonar.

    Si falta cualquiera de las dos, no hay analisis: escribir una lectura critica
    sin el material medido seria pedirle al modelo que opine de memoria, que es
    justo lo que este proyecto no hace en ninguna parte.
    """
    ret = DERIVADO / "retorica" / f"{sha256}.json"
    afi = DERIVADO / "afirmaciones" / f"{sha256}.json"
    faltan = [p.relative_to(RAIZ).as_posix() for p in (ret, afi) if not p.exists()]
    if faltan:
        raise FileNotFoundError(
            "falta el material sellado: " + ", ".join(faltan) +
            ". Corre antes retorica.py y contrastar_prensa.py sobre este articulo.")
    return (json.loads(ret.read_text(encoding="utf-8")),
            json.loads(afi.read_text(encoding="utf-8")))


def payload_para_el_filtro(retorica: dict, afirmaciones: dict) -> list[dict]:
    """Arma el 'sobre' que filtro.py espera, a partir del material sellado.

    Se declara hay_dato solo si alguna afirmacion llego a contrastarse. La
    consecuencia esta buscada: cuando NADA del articulo se pudo comparar, filtro
    exige que el texto diga literalmente 'sin dato disponible', que es
    exactamente lo que hay que decir en ese caso.
    """
    resultados = []
    for a in afirmaciones.get("afirmaciones", []):
        cita = a.get("cita_manifiesto") or {}
        if cita.get("sha256"):
            resultados.append({"cita": {"seq": cita.get("seq"), "sha256": cita["sha256"]}})
    # El documento entero de afirmaciones viaja ademas como resultado: el prompt
    # se lo entrega completo al modelo, asi que todo numero que hay adentro —el
    # boletin, las cifras del corpus, los conteos— es material legitimo. Si solo
    # viajaran las citas, el filtro rechazaria por "sin respaldo" un numero que
    # el modelo si tenia a la vista, y estaria midiendo otra cosa.
    return [
        {"herramienta": "retorica", "hay_dato": True, "resultados": [retorica]},
        {"herramienta": "afirmaciones", "hay_dato": bool(resultados),
         "resultados": resultados + [afirmaciones]},
    ]


# Los ordinales de una lista markdown ("1.", "2.") no son afirmaciones del texto:
# son numeracion. Sin quitarlos, el filtro rechaza el analisis por una cifra que
# nadie afirmo — y un validador que se dispara con el formato entrena a ignorarlo.
_RE_ORDINAL = re.compile(r"^\s{0,3}\d{1,2}[.)]\s+", re.MULTILINE)


def sin_numeracion(texto: str) -> str:
    return _RE_ORDINAL.sub("", texto)


def revisar_estructura(texto: str) -> list[str]:
    """Los chequeos del prompt que se pueden comprobar sin interpretar nada."""
    motivos = []
    for s in SECCIONES:
        if s not in texto:
            motivos.append(f"falta la seccion obligatoria: '{s}'")
    # El cierre se compara con los espacios colapsados: el texto puede venir con
    # el parrafo cortado en varias lineas y eso no cambia lo que dice.
    if re.sub(r"\s+", " ", CIERRE) not in re.sub(r"\s+", " ", texto):
        motivos.append("falta el cierre literal obligatorio del prompt")
    cuerpo = re.sub(r"^#.*$", " ", texto, flags=re.MULTILINE)
    cuerpo = cuerpo.replace(re.sub(r"\s+", " ", CIERRE), " ")
    palabras = len(re.findall(r"\b[\wÁÉÍÓÚÑáéíóúñü]+\b", cuerpo))
    if not MIN_PALABRAS <= palabras <= MAX_PALABRAS:
        motivos.append(f"extension fuera del rango del prompt: {palabras} palabras "
                       f"(se piden entre {MIN_PALABRAS} y {MAX_PALABRAS})")
    return motivos


def revisar(texto: str, retorica: dict, afirmaciones: dict) -> dict:
    informe = filtro.revisar(sin_numeracion(texto), payload_para_el_filtro(retorica, afirmaciones))
    estructurales = revisar_estructura(texto)
    return {
        "aprobado": informe["aprobado"] and not estructurales,
        "motivos": informe["motivos"] + estructurales,
        "advertencias": informe["advertencias"],
        "cifras_citadas_del_articulo": informe["cifras_citadas"],
        "citas_literales": informe["citas_literales"],
        "revisado_por": "filtro.py (cifras, lenguaje valorativo, giros de juicio, "
                        "etiquetas ideologicas) + chequeos estructurales de analisis_ia.py",
    }


def sellar(sha256: str, ruta_analisis: Path, modelo: str, solo_revisar: bool) -> int:
    entrada = buscar_entrada(sha256)
    if not entrada:
        print(f"ERROR: {sha256[:12]}… no esta en prensa/registro.jsonl.")
        return 1
    try:
        retorica, afirmaciones = material(sha256)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1
    if not ruta_analisis.exists():
        print(f"ERROR: no existe {ruta_analisis}")
        return 1
    if not PROMPT.exists():
        print(f"ERROR: no existe {PROMPT.relative_to(RAIZ).as_posix()}: sin prompt publicado "
              "no se puede declarar bajo que instrucciones se escribio el analisis.")
        return 1

    texto = ruta_analisis.read_text(encoding="utf-8").strip()
    informe = revisar(texto, retorica, afirmaciones)

    if not informe["aprobado"]:
        print("RECHAZADO: el analisis no se sella.")
        for m in informe["motivos"]:
            print(f"  · {m}")
        if informe["advertencias"]:
            print("  advertencias:")
            for a in informe["advertencias"]:
                print(f"  · {a}")
        return 1
    if solo_revisar:
        print("REVISION OK: el analisis pasa el filtro. No se sello (--revisar).")
        for a in informe["advertencias"]:
            print(f"  advertencia: {a}")
        return 0

    salida = {
        "descripcion": "Lectura critica de un modelo de lenguaje sobre el material sellado de un "
                       "articulo. NO es verificable: un modelo no es reproducible, asi que la "
                       "misma entrada puede dar otra salida. Lo que se sella aca es la "
                       "PROCEDENCIA (que modelo, con que prompt, sobre que entrada), no la verdad "
                       "de lo que dice.",
        "generado_por": "analisis_ia.py",
        "capa": "B (no determinista, NO sellable como dato)",
        "derivado_no_determinista": True,
        "sellado": False,
        "funda_algun_veredicto": False,
        "como_leerlo": "Es opinion. Si este bloque desapareciera, ninguna cifra publicada por el "
                       "sistema cambiaria. Los datos estan en los bloques sellados, con su hash.",
        "procedencia": {
            "modelo": modelo,
            "prompt": {
                "archivo": PROMPT.relative_to(RAIZ).as_posix(),
                "sha256": sha256_de(PROMPT),
                "tambien_publicado_en": "prompts/hashes.json",
            },
            "entrada": {
                "articulo_sha256": entrada["sha256"],
                "articulo_sha256_texto": entrada.get("sha256_texto", ""),
                "retorica_sha256": sha256_de(DERIVADO / "retorica" / f"{sha256}.json"),
                "afirmaciones_sha256": sha256_de(DERIVADO / "afirmaciones" / f"{sha256}.json"),
                "lexico_sha256": (retorica.get("lexico") or {}).get("sha256", ""),
            },
            "salida": {
                "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
                "palabras": len(re.findall(r"\b[\wÁÉÍÓÚÑáéíóúñü]+\b", texto)),
            },
            "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "que_prueba_esto": "Que este texto salio de ese prompt sobre ese material, y que no "
                               "cambio desde entonces. NO prueba que sea correcto.",
            "que_no_prueba": "Nada sobre la veracidad del analisis. Otra corrida del mismo modelo "
                             "con el mismo prompt puede escribir algo distinto, y ninguna de las "
                             "dos versiones es mas valida que la otra por venir sellada.",
        },
        "revision": informe,
        "articulo": {
            "sha256": entrada["sha256"],
            "seq_registro": entrada["seq"],
            "medio": entrada["medio"],
            "titulo": entrada["titulo"],
            "url": entrada["url"],
            "fecha_publicacion": entrada["fecha_publicacion"],
            "tema": entrada.get("tema", ""),
        },
        "texto": texto,
    }
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / f"{sha256}.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"SELLADO (como NO verificable) {destino.relative_to(RAIZ).as_posix()}")
    print(f"  modelo:  {modelo}")
    print(f"  prompt:  {salida['procedencia']['prompt']['sha256'][:16]}…")
    print(f"  entrada: retorica {salida['procedencia']['entrada']['retorica_sha256'][:12]}… · "
          f"afirmaciones {salida['procedencia']['entrada']['afirmaciones_sha256'][:12]}…")
    print(f"  salida:  {salida['procedencia']['salida']['sha256'][:16]}… "
          f"({salida['procedencia']['salida']['palabras']} palabras)")
    for a in informe["advertencias"]:
        print(f"  advertencia: {a}")
    return 0


def verificar() -> int:
    """Comprueba que cada analisis sellado siga calzando con lo que declara."""
    if not SALIDA.is_dir():
        print("SIN ANALISIS: no hay data/derived/prensa/analisis/. Nada que verificar.")
        return 0
    archivos = sorted(SALIDA.glob("*.json"))
    if not archivos:
        print("SIN ANALISIS: el directorio existe y esta vacio.")
        return 0
    fallos = 0
    for ruta in archivos:
        d = json.loads(ruta.read_text(encoding="utf-8"))
        p = d["procedencia"]
        propio = hashlib.sha256(d["texto"].encode("utf-8")).hexdigest()
        if propio != p["salida"]["sha256"]:
            print(f"ROTO {ruta.name}: el texto no calza con su sha256 declarado")
            fallos += 1
        if PROMPT.exists() and sha256_de(PROMPT) != p["prompt"]["sha256"]:
            print(f"DESFASADO {ruta.name}: el prompt cambio desde que se escribio este analisis "
                  f"(declara {p['prompt']['sha256'][:12]}…, hoy {sha256_de(PROMPT)[:12]}…). "
                  "No es corrupcion: es que la instruccion ya no es la misma y hay que rehacerlo.")
            fallos += 1
        for nombre, carpeta in (("retorica", "retorica"), ("afirmaciones", "afirmaciones")):
            origen = DERIVADO / carpeta / f"{d['articulo']['sha256']}.json"
            if origen.exists() and sha256_de(origen) != p["entrada"][f"{nombre}_sha256"]:
                print(f"DESFASADO {ruta.name}: {nombre} cambio desde que se escribio el analisis")
                fallos += 1
    print(f"ANALISIS OK ({len(archivos)})" if not fallos
          else f"ANALISIS: {fallos} problemas en {len(archivos)} archivos")
    return 0 if not fallos else 1


def autotest() -> int:
    fallos = 0
    base = ("## Lo que se puede comprobar hoy\n" + "palabra " * 90 +
            "\n## Lo que no queda contra qué comprobar\n" + "palabra " * 90 +
            "\n## Posibles soluciones\n" + "palabra " * 90 +
            "\n## Lo que este análisis no pudo evaluar\n" + "palabra " * 40 + "\n\n" + CIERRE)

    if revisar_estructura(base):
        print(f"FALLA: un analisis bien formado no debería tener reparos: {revisar_estructura(base)}")
        fallos += 1
    # Falta una seccion.
    if not revisar_estructura(base.replace("## Posibles soluciones", "## Otra cosa")):
        print("FALLA: debería detectar la sección faltante")
        fallos += 1
    # Falta el cierre obligatorio.
    if not revisar_estructura(base.replace(CIERRE, "")):
        print("FALLA: debería detectar la falta del cierre literal")
        fallos += 1
    # Demasiado corto.
    corto = "\n".join(SECCIONES) + "\ncuatro palabras nada mas\n\n" + CIERRE
    if not any("extension" in m for m in revisar_estructura(corto)):
        print("FALLA: debería detectar que el análisis es más corto que lo que pide el prompt")
        fallos += 1

    # El filtro rechaza una cifra que no esta en el material.
    ret = {"indicadores": {"x": {"valor": 4}}}
    afi = {"afirmaciones": [{"cita_manifiesto": {"seq": 3, "sha256": "ab" * 32}}]}
    con_hash = f" seq 3 hash {'ab' * 32} "
    ok = revisar(base.replace("palabra palabra", "4 promesas" + con_hash, 1), ret, afi)
    inventada = revisar(base.replace("palabra palabra", "917 promesas" + con_hash, 1), ret, afi)
    if not ok["aprobado"]:
        print(f"FALLA: una cifra que sí está en el material fue rechazada: {ok['motivos']}")
        fallos += 1
    if inventada["aprobado"] or not any("sin respaldo" in m for m in inventada["motivos"]):
        print("FALLA: debería rechazar una cifra que no está en el material")
        fallos += 1
    # Y rechaza la etiqueta que el prompt prohibe.
    etiquetado = revisar(base.replace("palabra palabra", "es demagogia pura" + con_hash, 1), ret, afi)
    if etiquetado["aprobado"]:
        print("FALLA: debería rechazar la etiqueta 'demagogia'")
        fallos += 1
    # La numeracion de una lista no es una cifra afirmada.
    numerada = base.replace("palabra palabra", con_hash + "\n\n1. uno\n2. dos\n3. tres\n", 1)
    if not revisar(numerada, ret, afi)["aprobado"]:
        print(f"FALLA: la numeración de una lista se contó como cifra: "
              f"{revisar(numerada, ret, afi)['motivos']}")
        fallos += 1
    if sin_numeracion("1. uno\n27) dos") != "uno\ndos":
        print("FALLA: sin_numeracion no quita los ordinales como se espera")
        fallos += 1

    print("AUTOTEST OK" if not fallos else f"AUTOTEST: {fallos} fallas")
    return 0 if not fallos else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sha256", help="sha256 del articulo en prensa/registro.jsonl")
    p.add_argument("--analisis", help="Archivo .md con la lectura critica escrita por el modelo")
    p.add_argument("--modelo", default="claude-opus-5",
                   help="Identificador del modelo que escribio el texto")
    p.add_argument("--revisar", action="store_true", help="Solo revisar, sin sellar")
    p.add_argument("--verificar", action="store_true",
                   help="Comprobar que los analisis sellados sigan calzando con su material")
    p.add_argument("--autotest", action="store_true")
    args = p.parse_args()

    if args.autotest:
        return autotest()
    if args.verificar:
        return verificar()
    if not args.sha256 or not args.analisis:
        print("ERROR: se requieren --sha256 y --analisis (o --verificar / --autotest)")
        return 2
    return sellar(args.sha256, Path(args.analisis), args.modelo, args.revisar)


if __name__ == "__main__":
    sys.exit(main())
