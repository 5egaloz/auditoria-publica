#!/usr/bin/env python3
"""Contraste de afirmaciones de prensa contra el corpus sellado. Sin IA.

Toma la salida de extraer_prensa.py y resuelve cada afirmacion con las mismas
herramientas deterministas que usa el agente (herramientas.py), de modo que toda
cifra del sistema siga saliendo del corpus y viajando con su cita al manifiesto.

CUATRO VEREDICTOS, ninguno con adjetivos:

  coincide                        la cifra del articulo y la del corpus son iguales
  difiere                         se publican LAS DOS y el hash; el sistema no
                                  dictamina por que difieren (puede ser otro ano,
                                  otra definicion, otra fuente o un error)
  sin_dato_disponible             la afirmacion cae dentro del alcance del sistema
                                  pero ese dato no esta ingerido todavia
  no_contrastable_con_este_corpus la frase no contiene un dato que este corpus
                                  sepa resolver

Lo que este archivo NO hace: decir quien tiene razon, calificar al medio, ni
rellenar un hueco con una estimacion. Un "sin_dato_disponible" es una tarea de
ingesta pendiente, y se publica como tal.

Uso:
  python contrastar_prensa.py --sha256 <sha del articulo>
  python contrastar_prensa.py --todos
  python contrastar_prensa.py --autotest

Sin dependencias externas: solo stdlib + herramientas.py del propio repo.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import herramientas as h

RAIZ = Path(__file__).resolve().parent
AFIRMACIONES = RAIZ / "data" / "derived" / "prensa" / "afirmaciones"

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
         "noviembre": 11, "diciembre": 12}


def fecha_en(texto: str) -> str | None:
    """Fecha explicita dentro de la frase, en ISO. None si no hay una sola clara."""
    if not isinstance(texto, str):
        return None
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", texto)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-zA-ZáéíóúÁÉÍÓÚ]+)(?:\s+de\s+(\d{4}))?", texto)
    if m:
        dia, mes_txt, anno = m.group(1), m.group(2).lower(), m.group(3)
        mes = MESES.get(mes_txt)
        if mes and anno:
            return f"{int(anno):04d}-{mes:02d}-{int(dia):02d}"
    return None


def anno_en(texto: str) -> int | None:
    """Un unico ano de cuatro digitos en la frase. Si hay varios, no se adivina."""
    if not isinstance(texto, str):
        return None
    annos = sorted({int(a) for a in re.findall(r"\b(19\d{2}|20\d{2})\b", texto)})
    return annos[0] if len(annos) == 1 else None


def _resultado(veredicto: str, detalle: str, **extra) -> dict:
    """El veredicto de una afirmacion.

    OJO con el nombre de la cita: la afirmacion ya trae un campo 'cita', que es la
    cita LITERAL del articulo. La cita al manifiesto viaja aparte, como
    'cita_manifiesto'. Cuando las dos se llamaban igual, el contraste pisaba la
    frase del medio con un objeto y la web publicaba «[object Object]» en el lugar
    donde debia ir lo que el medio dijo.
    """
    return {"veredicto": veredicto, "detalle": detalle, **extra}


# --------------------------------------------------------------------------
# Un resolutor por plantilla. Cada uno devuelve SIEMPRE uno de los 4 veredictos.
# --------------------------------------------------------------------------

def caso_de(tema: str | None) -> dict | None:
    """El caso declarado en prensa/casos.json, con el boletin que se ingirio para el."""
    if not tema:
        return None
    ruta = RAIZ / "prensa" / "casos.json"
    if not ruta.exists():
        return None
    for c in json.loads(ruta.read_text(encoding="utf-8")).get("casos", []):
        if c.get("tema") == tema:
            return c
    return None


def resolver_votacion(af: dict, caso: dict | None = None) -> dict:
    favor = af["parametros"].get("favor")
    contra = af["parametros"].get("contra")
    fecha = fecha_en(af["cita"])
    cobertura = ("El corpus cubre votaciones de Sala de la Camara de Diputados de 2026. "
                 "No cubre el Senado ni las comisiones.")
    if not fecha and caso and caso.get("boletin"):
        # Sin fecha en la frase, pero el articulo declara su caso y para ese caso
        # se ingirio un boletin: la busqueda queda acotada a ESE proyecto. No es
        # pescar totales que calcen por casualidad en todo el corpus.
        sobre = h.votaciones_de_proyecto(boletin=caso["boletin"], limite=500)
        calces = [r for r in sobre["resultados"]
                  if r.get("total_si") == favor and r.get("total_no") == contra]
        if len(calces) == 1:
            r = calces[0]
            return _resultado(
                "coincide",
                f"El boletin {caso['boletin']} registra {r['total_si']} a favor, {r['total_no']} "
                f"en contra y {r.get('total_abstencion')} abstenciones en la votacion {r['id']} "
                f"del {str(r.get('fecha'))[:10]} ({r.get('descripcion_literal') or 'sin descripcion'}).",
                cita_manifiesto=r.get("cita"),
                del_articulo={"a_favor": favor, "en_contra": contra},
                del_corpus={"a_favor": r["total_si"], "en_contra": r["total_no"],
                            "abstencion": r.get("total_abstencion"), "id_votacion": r["id"],
                            "fecha": str(r.get("fecha"))[:10], "boletin": caso["boletin"]})
        if len(calces) > 1:
            return _resultado(
                "sin_dato_disponible",
                f"{len(calces)} votaciones del boletin {caso['boletin']} tienen esos mismos "
                "totales y la frase no dice cual. No se elige una.",
                cobertura=cobertura)
        if sobre["hay_dato"]:
            return _resultado(
                "difiere",
                f"El articulo dice {favor:g} a favor y {contra:g} en contra. Ninguna de las "
                f"{len(sobre['resultados'])} votaciones registradas del boletin {caso['boletin']} "
                "en la Camara tiene esos dos totales. Puede tratarse de una votacion del Senado, "
                "que no esta en el corpus: el sistema no dictamina a que se debe la diferencia.",
                cita_manifiesto=sobre["resultados"][0].get("cita") if sobre["resultados"] else None,
                del_articulo={"a_favor": favor, "en_contra": contra})
    if not fecha:
        return _resultado(
            "sin_dato_disponible",
            "La frase da los totales pero no dice de que votacion son. Para contrastarla "
            "hace falta la fecha, el identificador de la votacion o un caso declarado con "
            "su boletin ingerido.",
            cobertura=cobertura)
    # Se mira en los dos lugares: las votaciones de Sala del ano y, si un boletin
    # concreto fue ingerido para poder contrastar justamente esto, tambien ahi.
    sobre = h.buscar_votaciones(desde=fecha, hasta=fecha, limite=50)
    del_proyecto = h.votaciones_de_proyecto(fecha=fecha, limite=50)
    if del_proyecto["hay_dato"]:
        sobre = {**del_proyecto,
                 "resultados": del_proyecto["resultados"] + (sobre["resultados"] if sobre["hay_dato"] else []),
                 "hay_dato": True}
    if not sobre["hay_dato"]:
        return _resultado(
            "sin_dato_disponible",
            f"No hay ninguna votacion del {fecha} en el corpus. Para contrastar esta "
            "afirmacion hay que ingerir esa votacion desde la fuente oficial.",
            cobertura=cobertura, fecha_buscada=fecha,
            ingesta_pendiente=f"votaciones del {fecha}")
    # Puede haber varias votaciones ese dia: se busca una cuyos DOS totales calcen.
    calces = [r for r in sobre["resultados"]
              if r.get("total_si") == favor and r.get("total_no") == contra]
    if calces:
        r = calces[0]
        return _resultado(
            "coincide",
            f"El corpus registra {r.get('total_si')} a favor y {r.get('total_no')} en contra "
            f"en la votacion {r.get('id')} del {str(r.get('fecha'))[:10]}.",
            cita_manifiesto=r.get("cita"), del_corpus={"a_favor": r.get("total_si"),
                                            "en_contra": r.get("total_no"),
                                            "id_votacion": r.get("id")},
            del_articulo={"a_favor": favor, "en_contra": contra})
    # Hay votaciones ese dia, pero ninguna con esos totales.
    muestra = sobre["resultados"][0]
    return _resultado(
        "difiere",
        f"El articulo dice {favor:g} a favor y {contra:g} en contra. Ese dia el corpus "
        f"registra {len(sobre['resultados'])} votacion(es) de Sala; ninguna con esos dos "
        "totales. El sistema no dictamina a que se debe la diferencia.",
        cita_manifiesto=muestra.get("cita"),
        del_articulo={"a_favor": favor, "en_contra": contra},
        del_corpus=[{"id": r.get("id"), "a_favor": r.get("total_si"),
                     "en_contra": r.get("total_no"), "materia": r.get("descripcion_literal")}
                    for r in sobre["resultados"][:5]])


def resolver_balance(af: dict) -> dict:
    valor = af["parametros"].get("valor")
    anno = anno_en(af["cita"])
    if anno is None:
        return _resultado(
            "sin_dato_disponible",
            "La frase da un porcentaje del PIB pero no dice de que ano, y el corpus tiene "
            "una cifra por ano y por publicacion.")
    sobre = h.serie_balance(variable="balance_efectivo_pct_pib", anno=anno)
    if not sobre["hay_dato"]:
        return _resultado(
            "sin_dato_disponible",
            f"No hay balance efectivo de {anno} en el corpus.",
            ingesta_pendiente=f"IFP con el balance de {anno}")
    # El articulo suele citar el valor sin signo; se compara en magnitud y se
    # publica el signo del corpus, que es el que manda.
    del_corpus = sobre["resultados"]
    iguales = [r for r in del_corpus if abs(abs(r["valor"]) - abs(valor)) < 0.005]
    if iguales:
        r = iguales[0]
        return _resultado(
            "coincide",
            f"El corpus registra {r['valor']:.2f}% del PIB para {anno} segun {r['publicacion']}.",
            cita_manifiesto=r.get("cita"),
            del_articulo={"valor": valor}, del_corpus={"valor": r["valor"],
                                                       "publicacion": r["publicacion"],
                                                       "caracter": r.get("caracter")})
    return _resultado(
        "difiere",
        f"El articulo dice {valor:g}% del PIB para {anno}. El corpus tiene "
        + "; ".join(f"{r['valor']:.2f}% segun {r['publicacion']}" for r in del_corpus[:4])
        + ". Publicaciones distintas del mismo ano dan cifras distintas: el sistema "
          "no dictamina cual corresponde a la frase.",
        cita_manifiesto=del_corpus[0].get("cita"),
        del_articulo={"valor": valor},
        del_corpus=[{"valor": r["valor"], "publicacion": r["publicacion"],
                     "caracter": r.get("caracter")} for r in del_corpus[:4]])


def resolver_escanos(af: dict) -> dict:
    valor = af["parametros"].get("valor")
    partido = (af["parametros"].get("partido") or "").strip()
    sobre = h.concentracion_camara()
    if not sobre["hay_dato"]:
        return _resultado("sin_dato_disponible", "El corpus no tiene la composicion de la Camara.")
    reparto = sobre["resultados"][0].get("reparto", [])
    aguja = h._plano(partido)
    calces = [r for r in reparto if aguja and aguja in h._plano(r.get("partido_nombre", ""))]
    if not calces:
        return _resultado(
            "sin_dato_disponible",
            f"'{partido}' no figura con ese nombre en la composicion registrada. "
            "El corpus usa los nombres de partido tal como los publica la Camara.")
    r = calces[0]
    if r.get("escanos") == valor:
        return _resultado(
            "coincide", f"El corpus registra {r['escanos']} escanos para {r['partido_nombre']}.",
            cita_manifiesto=sobre["resultados"][0].get("cita"),
            del_articulo={"escanos": valor, "partido": partido},
            del_corpus={"escanos": r["escanos"], "partido": r["partido_nombre"]})
    return _resultado(
        "difiere",
        f"El articulo dice {valor:g} y el corpus registra {r['escanos']} para "
        f"{r['partido_nombre']}, contados sobre la votacion de referencia "
        f"{sobre['resultados'][0].get('votacion_de_referencia')}.",
        cita_manifiesto=sobre["resultados"][0].get("cita"),
        del_articulo={"escanos": valor, "partido": partido},
        del_corpus={"escanos": r["escanos"], "partido": r["partido_nombre"]})


def resolver_fuera_de_corpus(af: dict) -> dict:
    """Plantillas reconocidas cuyo dato NO esta ingerido: es tarea de ingesta."""
    return _resultado(
        "sin_dato_disponible",
        "La afirmacion es del tipo que el sistema sabe contrastar, pero la fuente que la "
        "resuelve no esta ingerida todavia.",
        ingesta_pendiente=af.get("necesita") or "fuente oficial por definir")


RESOLUTORES = {
    "votacion_totales": resolver_votacion,
    "balance_pib": resolver_balance,
    "escanos_partido": resolver_escanos,
    "tasa_impuesto": resolver_fuera_de_corpus,
}


def contrastar_archivo(ruta: Path) -> dict:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    caso = caso_de(datos.get("articulo", {}).get("tema"))
    conteo = {"coincide": 0, "difiere": 0, "sin_dato_disponible": 0,
              "no_contrastable_con_este_corpus": 0}
    def redactar(af: dict) -> None:
        """Se cita SOLO lo que se contrasta.

        Una frase que el sistema no puede resolver no gana nada con ser
        reproducida, y reproducirla si tiene un costo: medido sobre el piloto,
        citar todas las frases con cifra republicaba el 29% del texto de cada
        nota en un repositorio publico. Eso ya no es cita corta.
        """
        if af.get("veredicto") == "no_contrastable_con_este_corpus":
            af["cita"] = None
            af["cita_no_publicada"] = ("La oracion no se reproduce: el sistema no puede "
                                       "contrastarla y citarla solo republicaria texto ajeno.")

    for af in datos.get("afirmaciones", []):
        if af.get("veredicto") == "no_contrastable_con_este_corpus":
            conteo["no_contrastable_con_este_corpus"] += 1
            redactar(af)
            continue
        resolutor = RESOLUTORES.get(af.get("plantilla"))
        salida = (resolutor(af, caso) if resolutor is resolver_votacion else
                  resolutor(af) if resolutor else
                  _resultado("no_contrastable_con_este_corpus",
                             "No hay resolutor para esta plantilla."))
        af.update(salida)
        conteo[af["veredicto"]] = conteo.get(af["veredicto"], 0) + 1
        redactar(af)

    total = len(datos.get("afirmaciones", []))
    contrastables = conteo["coincide"] + conteo["difiere"]
    datos["contraste"] = {
        "generado_por": "contrastar_prensa.py",
        "conteo": conteo,
        "total_afirmaciones": total,
        # Se publica POR ARTICULO y nunca agregada por medio: un promedio por medio
        # convertiria esto en un marcador de sesgo de prensa, que es justo el
        # producto ideologico que el proyecto existe para no ser. Ademas la metrica
        # no mide lo que ese ranking sugeriria: una columna de opinion tiene
        # densidad baja por definicion, y eso no la hace falsa.
        "densidad_contrastable": round(contrastables / total, 4) if total else None,
        "formula_densidad": "densidad_contrastable = (coincide + difiere) / total_afirmaciones",
        "ingestas_pendientes": sorted({af["ingesta_pendiente"]
                                       for af in datos["afirmaciones"]
                                       if af.get("ingesta_pendiente")}),
    }
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return datos


def escribir_indice() -> dict:
    """Indice de articulos contrastados. La web es estatica y no puede listar una
    carpeta; sin este archivo la pestana Prensa no sabria que existe."""
    articulos = []
    for ruta in sorted(AFIRMACIONES.glob("*.json")):
        d = json.loads(ruta.read_text(encoding="utf-8"))
        if "contraste" not in d:
            continue
        articulos.append({
            **d["articulo"],
            "archivo": f"afirmaciones/{ruta.name}",
            "conteo": d["contraste"]["conteo"],
            "total_afirmaciones": d["contraste"]["total_afirmaciones"],
            "densidad_contrastable": d["contraste"]["densidad_contrastable"],
            "ingestas_pendientes": d["contraste"]["ingestas_pendientes"],
        })
    articulos.sort(key=lambda a: (a.get("fecha_publicacion") or "", a.get("medio") or ""))
    indice = {
        "descripcion": "Articulos de prensa cuyas afirmaciones con cifra fueron contrastadas "
                       "contra el corpus sellado. Se publica por articulo y nunca agregado por "
                       "medio: un promedio por medio convertiria esto en un marcador de sesgo "
                       "de prensa, y ademas no mide lo que ese ranking sugeriria.",
        "generado_por": "contrastar_prensa.py",
        "veredictos": {
            "coincide": "la cifra del articulo y la del corpus son iguales",
            "difiere": "se publican las dos cifras y el hash; el sistema no dictamina por que",
            "sin_dato_disponible": "cae en el alcance del sistema pero ese dato no esta ingerido",
            "no_contrastable_con_este_corpus": "la frase no trae un dato que este corpus resuelva",
        },
        "limitacion_declarada": "Del articulo no se guarda el texto (obra ajena, repo publico). "
                               "Si el medio lo edita o lo baja, el hash prueba que cambio, no que decia.",
        "total_articulos": len(articulos),
        "articulos": articulos,
    }
    destino = AFIRMACIONES.parent / "indice.json"
    destino.write_text(json.dumps(indice, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return indice


def autotest() -> int:
    fallos = 0
    # Una votacion sin fecha en la frase no se puede resolver: sin_dato, no un calce
    # inventado buscando totales que coincidan por casualidad.
    r = resolver_votacion({"cita": "Se aprobo con 26 votos a favor y 24 en contra.",
                           "parametros": {"favor": 26.0, "contra": 24.0}})
    if r["veredicto"] != "sin_dato_disponible":
        print(f"FALLA: votacion sin fecha deberia dar sin_dato_disponible, dio {r['veredicto']}")
        fallos += 1
    # Un ano sin dato en el corpus tampoco se rellena.
    r = resolver_balance({"cita": "El deficit fue 9,9% del PIB en 1999.",
                          "parametros": {"valor": 9.9}})
    if r["veredicto"] != "sin_dato_disponible":
        print(f"FALLA: balance de 1999 deberia dar sin_dato_disponible, dio {r['veredicto']}")
        fallos += 1
    # Un ano que SI esta y con la cifra correcta tiene que coincidir.
    r = resolver_balance({"cita": "El balance de 2025 fue -2,80% del PIB.",
                          "parametros": {"valor": 2.8018041699923066}})
    if r["veredicto"] != "coincide":
        print(f"FALLA: balance 2025 = 2,80 deberia coincidir, dio {r['veredicto']} ({r['detalle']})")
        fallos += 1
    # Y una cifra que no calza tiene que decir difiere, con las DOS cifras.
    r = resolver_balance({"cita": "El balance de 2025 fue 9,10% del PIB.",
                          "parametros": {"valor": 9.1}})
    if r["veredicto"] != "difiere" or "del_corpus" not in r:
        print(f"FALLA: balance 2025 = 9,10 deberia diferir con las dos cifras, dio {r['veredicto']}")
        fallos += 1
    # Fechas
    if fecha_en("el 16 de julio de 2026 se voto") != "2026-07-16":
        print("FALLA: lectura de fecha en castellano")
        fallos += 1
    if anno_en("entre 2025 y 2029") is not None:
        print("FALLA: con dos anos no se debe adivinar uno")
        fallos += 1
    print("AUTOTEST OK" if not fallos else f"AUTOTEST: {fallos} fallas")
    return 0 if not fallos else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sha256")
    p.add_argument("--todos", action="store_true")
    p.add_argument("--autotest", action="store_true")
    args = p.parse_args()

    if args.autotest:
        return autotest()
    if not AFIRMACIONES.exists():
        print("No hay afirmaciones extraidas todavia.")
        return 1
    rutas = ([AFIRMACIONES / f"{args.sha256}.json"] if args.sha256
             else sorted(AFIRMACIONES.glob("*.json")))
    if not rutas or not rutas[0].exists():
        print("ERROR: no hay archivo de afirmaciones para ese sha256.")
        return 1
    for ruta in rutas:
        datos = contrastar_archivo(ruta)
        c = datos["contraste"]["conteo"]
        art = datos["articulo"]
        print(f"\n{art['medio']} — {art['titulo'][:70]}")
        print(f"  {datos['contraste']['total_afirmaciones']} afirmaciones con cifra: "
              f"{c['coincide']} coinciden · {c['difiere']} difieren · "
              f"{c['sin_dato_disponible']} sin dato · "
              f"{c['no_contrastable_con_este_corpus']} no contrastables")
        for pend in datos["contraste"]["ingestas_pendientes"]:
            print(f"  ingesta pendiente: {pend}")
    indice = escribir_indice()
    print(f"\nINDICE actualizado: {indice['total_articulos']} articulo(s) en "
          "data/derived/prensa/indice.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
