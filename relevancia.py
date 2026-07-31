#!/usr/bin/env python3
"""Seleccion de noticias politicas por COBERTURA CRUZADA. Sin IA.

EL PROBLEMA QUE RESUELVE
  "Las noticias politicas mas relevantes" es una frase que esconde una decision.
  Alguien tiene que decidir cuales, y esa decision es el sesgo mas grande de todo
  el modulo: lo que no entra no existe para el sistema. Si la lista la escribe el
  autor del proyecto, el sistema publica su agenda con formato de dato.

LA REGLA
  La relevancia no la decide este proyecto: la decide la coincidencia entre salas
  de redaccion que compiten entre si. Un hecho entra cuando al menos 2 medios de
  prensa/medios.json lo publican dentro de la misma ventana. Es una senal
  externa, simetrica (no sabe de que sector es la noticia) y falsable: cualquiera
  baja los mismos RSS el mismo dia y obtiene la misma lista.

  Todos los parametros —umbral, ventana, minimo de medios, terminos de alcance
  politico— viven en prensa/relevancia.json, publicados y versionados, junto con
  el sesgo que el criterio arrastra igual.

QUE HACE Y QUE NO
  · Lee RSS. NO descarga articulos: de cada item toma titular, enlace y fecha.
    La descarga y el sello son de ingesta_prensa.py, y solo para lo seleccionado.
  · NO ordena por importancia ni puntua. Un hecho esta o no esta sobre el umbral.
  · NO agrega por medio: no cuenta cuanto publica cada uno ni los compara.
  · Declara SIEMPRE cuanto quedo fuera. Un recorte silencioso se lee como
    "aca esta todo", que es la unica mentira que un sistema de datos no puede
    permitirse.

Uso:
  python relevancia.py                 (lee los RSS y escribe la seleccion del dia)
  python relevancia.py --sin-red --items items.json    (reproducir sobre items ya bajados)
  python relevancia.py --autotest

Sin dependencias: solo stdlib.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MEDIOS = RAIZ / "prensa" / "medios.json"
CRITERIO = RAIZ / "prensa" / "relevancia.json"
SALIDA = RAIZ / "data" / "derived" / "prensa"
USER_AGENT = "Mozilla/5.0 (auditoria-civica-datos-abiertos; +github.com/5egaloz)"


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


# --------------------------------------------------------------------------
# Lectura de RSS.
#
# Se aceptan RSS 2.0 y Atom porque los feeds chilenos usan los dos. Un feed que
# no se puede leer no aborta la corrida: se anota el motivo y el medio queda
# declarado como ausente en la salida. Un medio caido que desaparece en silencio
# sesgaria la seleccion sin que nadie lo note.
# --------------------------------------------------------------------------

ATOM = "{http://www.w3.org/2005/Atom}"


def _texto(nodo, *rutas) -> str:
    for r in rutas:
        hijo = nodo.find(r)
        if hijo is not None:
            if hijo.text and hijo.text.strip():
                return hijo.text.strip()
            enlace = hijo.get("href")
            if enlace:
                return enlace.strip()
    return ""


def _fecha(crudo: str) -> datetime | None:
    if not crudo:
        return None
    try:
        d = parsedate_to_datetime(crudo)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(crudo.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)


def leer_feed(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as r:
        raiz = ET.fromstring(r.read())
    items = raiz.findall(".//item") or raiz.findall(f".//{ATOM}entry")
    salida = []
    for it in items:
        titulo = _texto(it, "title", f"{ATOM}title")
        enlace = _texto(it, "link", f"{ATOM}link")
        fecha = _fecha(_texto(it, "pubDate", "published", f"{ATOM}published", f"{ATOM}updated"))
        if titulo and enlace:
            salida.append({"titulo": titulo, "url": enlace,
                           "fecha": fecha.isoformat() if fecha else None})
    return salida


# --------------------------------------------------------------------------
# Agrupacion de titulares en hechos.
#
# Dos titulares son del mismo hecho si comparten suficientes palabras
# significativas (Jaccard sobre el titular). El umbral esta publicado en
# prensa/relevancia.json para que se pueda discutir: subirlo parte un hecho en
# dos, bajarlo junta hechos distintos.
#
# El recorrido es en orden fijo (medio, fecha, titulo) para que la agrupacion sea
# determinista: con enlace simple, el orden de llegada cambia los grupos, y un
# resultado que depende del orden en que respondieron los servidores no lo puede
# reproducir nadie.
# --------------------------------------------------------------------------

def tokens(titulo: str, vacias: set[str]) -> set[str]:
    palabras = re.findall(r"[a-z0-9]+", sin_tildes(titulo))
    return {p for p in palabras if len(p) >= 4 and p not in vacias}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def agrupar(items: list[dict], umbral: float, ventana_h: int) -> list[list[dict]]:
    ordenados = sorted(items, key=lambda i: (i["medio"], i.get("fecha") or "", i["titulo"]))
    grupos: list[list[dict]] = []
    for it in ordenados:
        # Se entra al PRIMER grupo que ya tenga un titular parecido y dentro de
        # la ventana. Con el recorrido ordenado, "el primero" es siempre el mismo
        # y la agrupacion no depende de que servidor respondio antes.
        destino = next((g for g in grupos
                        if any(jaccard(it["tokens"], o["tokens"]) >= umbral and
                               dentro_de_ventana(it, o, ventana_h) for o in g)), None)
        if destino is None:
            destino = []
            grupos.append(destino)
        destino.append(it)
    return grupos


def dentro_de_ventana(a: dict, b: dict, horas: int) -> bool:
    """Sin fecha en el feed no se puede descartar por tiempo: se acepta y se anota."""
    fa, fb = a.get("fecha"), b.get("fecha")
    if not fa or not fb:
        return True
    return abs(datetime.fromisoformat(fa) - datetime.fromisoformat(fb)) <= timedelta(hours=horas)


def es_politico(titulo: str, terminos: list[str]) -> list[str]:
    """Terminos de alcance politico presentes en el titular, como palabra completa.

    El limite por los DOS lados no es un detalle: con el limite solo a la
    izquierda, "ley" calzaba dentro de "leyenda" y la muerte de un futbolista
    entraba al corpus como noticia legislativa. Se admite el plural en -s/-es
    porque es regular en castellano y no genera ese tipo de choque.
    """
    plano = sin_tildes(titulo)
    return [t for t in terminos
            if re.search(rf"(?<![0-9a-z]){re.escape(sin_tildes(t))}(?:es|s)?(?![0-9a-z])", plano)]


def seleccionar(items: list[dict], criterio: dict) -> dict:
    p = criterio["parametros"]
    vacias = {sin_tildes(v) for v in criterio.get("palabras_vacias", [])}
    terminos = criterio["alcance_politico"]["terminos"]

    leidos = len(items)
    politicos, descartados_tema = [], 0
    for it in items:
        tocados = es_politico(it["titulo"], terminos)
        if not tocados:
            descartados_tema += 1
            continue
        it = dict(it, terminos_de_alcance=tocados, tokens=tokens(it["titulo"], vacias))
        if len(it["tokens"]) < p["minimo_tokens_titular"]:
            descartados_tema += 1
            continue
        politicos.append(it)

    grupos = agrupar(politicos, p["umbral_similitud"], p["ventana_horas"])
    hechos, bajo_umbral = [], 0
    for g in grupos:
        medios = sorted({i["medio"] for i in g})
        if len(medios) < p["minimo_medios"]:
            bajo_umbral += 1
            continue
        # El titular representante es el primero en orden alfabetico de medio:
        # una regla arbitraria pero fija, para no elegir "el mejor titular", que
        # seria una opinion editorial de este sistema sobre la prensa.
        g = sorted(g, key=lambda i: (i["medio"], i.get("fecha") or "", i["titulo"]))
        hechos.append({
            "medios_que_lo_cubren": len(medios),
            "medios": medios,
            "terminos_de_alcance": sorted({t for i in g for t in i["terminos_de_alcance"]}),
            "notas": [{"medio": i["medio"], "titulo": i["titulo"], "url": i["url"],
                       "fecha": i.get("fecha")} for i in g],
        })
    # Orden de salida: por cobertura y luego por el titular de la primera nota.
    # Sin desempate fijo, dos corridas con los mismos datos publicarian otro orden.
    hechos.sort(key=lambda h: (-h["medios_que_lo_cubren"], h["notas"][0]["titulo"]))
    return {
        "items_leidos": leidos,
        "descartados_por_alcance": descartados_tema,
        "hechos_formados": len(grupos),
        "hechos_seleccionados": len(hechos),
        "hechos_bajo_el_umbral": bajo_umbral,
        "hechos": hechos,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sin-red", action="store_true",
                   help="No descargar: usar los items de --items (para reproducir una corrida)")
    p.add_argument("--items", help="JSON con [{medio, titulo, url, fecha}] ya capturados")
    p.add_argument("--autotest", action="store_true")
    args = p.parse_args()

    if args.autotest:
        return autotest()

    criterio = json.loads(CRITERIO.read_text(encoding="utf-8"))
    medios = json.loads(MEDIOS.read_text(encoding="utf-8")).get("medios", [])

    items, leidos_por_medio, sin_feed = [], {}, []
    if args.sin_red:
        if not args.items:
            print("ERROR: --sin-red requiere --items")
            return 2
        items = json.loads(Path(args.items).read_text(encoding="utf-8"))
        for i in items:
            leidos_por_medio[i["medio"]] = leidos_por_medio.get(i["medio"], 0) + 1
    else:
        for m in medios:
            url = m.get("rss", "")
            if not url.startswith("http"):
                sin_feed.append({"medio": m["medio"], "motivo": url or "sin rss declarado"})
                continue
            try:
                nuevos = leer_feed(url)
            except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError, OSError) as e:
                sin_feed.append({"medio": m["medio"], "motivo": f"{type(e).__name__}: {e}"})
                continue
            for n in nuevos:
                items.append(dict(n, medio=m["medio"]))
            leidos_por_medio[m["medio"]] = len(nuevos)

    if not items:
        print("SIN ITEMS: ningun feed entrego notas. No se escribe nada.")
        for s in sin_feed:
            print(f"  {s['medio']}: {s['motivo']}")
        return 1

    r = seleccionar(items, criterio)
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    salida = {
        "descripcion": "Hechos politicos seleccionados por cobertura cruzada: los que al menos "
                       f"{criterio['parametros']['minimo_medios']} medios de prensa/medios.json "
                       "publicaron dentro de la misma ventana. La relevancia la decide la "
                       "coincidencia entre redacciones, no este proyecto.",
        "generado_por": "relevancia.py",
        "derivado": True,
        "fecha_corrida_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "criterio": {
            "archivo": "prensa/relevancia.json",
            "version": criterio.get("version"),
            "parametros": criterio["parametros"],
            "sesgo_que_arrastra": criterio["que_sesgo_arrastra_igual"],
        },
        "cobertura_de_la_corrida": {
            "medios_declarados": len(medios),
            "medios_leidos": len(leidos_por_medio),
            "items_por_medio": dict(sorted(leidos_por_medio.items())),
            "medios_sin_feed_utilizable": sin_feed,
            "advertencia": "Un hecho que solo cubrio un medio NO entra, por importante que sea. "
                           "El criterio premia el consenso y castiga la exclusiva; es una "
                           "consecuencia del metodo, no un efecto que se pueda parchar.",
        },
        **r,
    }
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / f"relevancia-{hoy}.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"SELECCION {destino.relative_to(RAIZ).as_posix()}")
    print(f"  items leidos: {r['items_leidos']} de {len(leidos_por_medio)} medios")
    for s in sin_feed:
        print(f"   sin feed: {s['medio']} — {s['motivo'][:70]}")
    print(f"  descartados por alcance (no politicos): {r['descartados_por_alcance']}")
    print(f"  hechos formados: {r['hechos_formados']} · seleccionados: {r['hechos_seleccionados']} "
          f"· bajo el umbral: {r['hechos_bajo_el_umbral']}")
    for h in r["hechos"]:
        print(f"   [{h['medios_que_lo_cubren']} medios] {h['notas'][0]['titulo'][:78]}")
        for n in h["notas"]:
            print(f"      · {n['medio']}: {n['url']}")
    return 0


def autotest() -> int:
    criterio = json.loads(CRITERIO.read_text(encoding="utf-8"))
    fallos = 0

    def item(medio, titulo, fecha="2026-07-31T10:00:00+00:00"):
        return {"medio": medio, "titulo": titulo, "url": f"https://x/{medio}", "fecha": fecha}

    # Dos medios sobre el mismo hecho politico: entra.
    r = seleccionar([
        item("A", "Senado aplaza votacion de la megarreforma tributaria hasta agosto"),
        item("B", "Gobierno retira urgencia y el Senado aplaza la megarreforma tributaria"),
    ], criterio)
    if r["hechos_seleccionados"] != 1:
        print(f"FALLA: dos medios sobre el mismo hecho deberían formar 1 hecho, dio "
              f"{r['hechos_seleccionados']}")
        fallos += 1

    # Un solo medio: no entra, y queda contado como bajo el umbral.
    r = seleccionar([item("A", "Senado aplaza votacion de la megarreforma tributaria")], criterio)
    if r["hechos_seleccionados"] != 0 or r["hechos_bajo_el_umbral"] != 1:
        print("FALLA: una exclusiva de un solo medio no debería entrar, y debe quedar contada")
        fallos += 1

    # Dos medios pero sobre hechos distintos: ninguno alcanza el umbral.
    r = seleccionar([
        item("A", "Senado aplaza votacion de la megarreforma tributaria"),
        item("B", "Contraloria abre sumario por contratos en el ministerio de obras"),
    ], criterio)
    if r["hechos_seleccionados"] != 0:
        print("FALLA: dos hechos distintos no deberían agruparse")
        fallos += 1

    # Fuera de alcance politico: se descarta aunque coincidan los dos medios.
    r = seleccionar([
        item("A", "Colo Colo gana el clasico y se acerca al titulo del campeonato"),
        item("B", "Colo Colo gana el clasico ante la U y se acerca al titulo"),
    ], criterio)
    if r["hechos_seleccionados"] != 0 or r["descartados_por_alcance"] != 2:
        print(f"FALLA: deportes no debería entrar: seleccionados={r['hechos_seleccionados']}, "
              f"descartados={r['descartados_por_alcance']}")
        fallos += 1

    # El caso que costo una corrida real: 'ley' dentro de 'leyenda'. El termino
    # tiene que calzar como palabra, no como prefijo.
    terminos = criterio["alcance_politico"]["terminos"]
    for titulo in ("Murio Franco Baresi, leyenda de AC Milan y de la seleccion italiana",
                   "La leyenda del club se retira tras veinte temporadas"):
        if es_politico(titulo, terminos):
            print(f"FALLA: '{titulo[:40]}…' entró como política por {es_politico(titulo, terminos)}")
            fallos += 1
    # Y las formas que si tienen que entrar, incluido el plural regular.
    for titulo, esperado in (("Promulgan la ley de presupuestos", "ley"),
                             ("Las leyes despachadas por el Senado", "ley"),
                             ("Cambios tributarios en el proyecto", "tributario"),
                             ("Los diputados votan la reforma", "diputado")):
        if esperado not in es_politico(titulo, terminos):
            print(f"FALLA: '{titulo}' debería calzar con '{esperado}' y dio "
                  f"{es_politico(titulo, terminos)}")
            fallos += 1

    # Fuera de la ventana de tiempo: no es el mismo hecho.
    r = seleccionar([
        item("A", "Senado aplaza votacion de la megarreforma tributaria", "2026-07-01T10:00:00+00:00"),
        item("B", "Senado aplaza la votacion de la megarreforma tributaria", "2026-07-31T10:00:00+00:00"),
    ], criterio)
    if r["hechos_seleccionados"] != 0:
        print("FALLA: dos notas separadas por un mes no deberían ser el mismo hecho")
        fallos += 1

    # Determinismo: el orden de llegada no cambia el resultado.
    lote = [item("A", "Senado aplaza votacion de la megarreforma tributaria hasta agosto"),
            item("B", "Gobierno retira urgencia y el Senado aplaza la megarreforma tributaria"),
            item("C", "Contraloria abre sumario por contratos del ministerio de obras publicas"),
            item("A", "Contraloria abre un sumario por los contratos del ministerio de obras")]
    uno = json.dumps(seleccionar(lote, criterio), sort_keys=True)
    otro = json.dumps(seleccionar(list(reversed(lote)), criterio), sort_keys=True)
    if uno != otro:
        print("FALLA: el resultado depende del orden en que llegaron los items")
        fallos += 1

    # Simetria: el criterio no puede depender de quien protagoniza la noticia.
    # Se corre el mismo titular cambiando solo el actor y debe dar lo mismo.
    for actor in ("el Gobierno", "la Contraloria", "el Tribunal Constitucional"):
        r = seleccionar([
            item("A", f"Senado aplaza votacion tras el informe que presento {actor}"),
            item("B", f"Aplazan en el Senado la votacion tras el informe de {actor}"),
        ], criterio)
        if r["hechos_seleccionados"] != 1:
            print(f"FALLA: el criterio cambió al cambiar el actor ({actor})")
            fallos += 1

    print("AUTOTEST OK" if not fallos else f"AUTOTEST: {fallos} fallas")
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
