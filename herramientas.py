#!/usr/bin/env python3
"""Capa 2 del agente — herramientas deterministas sobre el corpus verificado.

Ver CLAUDE.md (Bloques 1 a 4) y la arquitectura del agente:

    pregunta -> ROUTER (LLM) -> HERRAMIENTAS (este archivo, sin LLM)
             -> REDACTOR (LLM) -> FILTRO (filtro.py) -> SELLADO

Regla central: el LLM NUNCA produce cifras. Todas las cifras salen de aqui,
y cada una viaja dentro de un "sobre" con su cita al manifiesto:

    {
      "herramienta": ..., "argumentos": {...},
      "hay_dato": bool,            # False -> el redactor debe decir "sin dato disponible"
      "resultados": [ {..., "cita": {"seq":N, "sha256":..., "url_fuente":...}} ],
      "derivado": bool, "formula": str|None,
      "n": int, "cobertura": str,  # que universo cubre y que NO cubre
      "mensaje": str|None
    }

Sin dependencias: solo stdlib. Cualquier tercero puede correrlo.

Uso manual:
  python herramientas.py --catalogo
  python herramientas.py serie_balance --args '{"variable":"balance_efectivo_pct_pib"}'
"""

import argparse
import json
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANIFIESTO = RAIZ / "manifest.jsonl"
DERIVED = RAIZ / "data" / "derived"

SIN_DATO = "sin dato disponible"


# --------------------------------------------------------------------------
# Carga del corpus y citas al manifiesto
# --------------------------------------------------------------------------

def _leer_manifiesto() -> list[dict]:
    if not MANIFIESTO.exists():
        return []
    with MANIFIESTO.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _cargar(ruta_relativa: str) -> dict:
    archivo = DERIVED / ruta_relativa
    if not archivo.exists():
        return {"registros": []}
    return json.loads(archivo.read_text(encoding="utf-8"))


_MANIFIESTO = _leer_manifiesto()
_POR_SHA = {e["sha256"]: e for e in _MANIFIESTO}

_FISCAL = _cargar("fiscal/balance-gobierno-central.json")
_VOTACIONES = _cargar("legislativo/votaciones-2026.json")
_AC = _cargar("legislativo/acusaciones-constitucionales-2026.json")
_NOMINAL = _cargar("legislativo/votos-nominales-2026.json")
_PADRON = _cargar("legislativo/diputados.json")
_COHESION = _cargar("tendencia/cohesion-partidos-2026.json")
_EJE = _cargar("tendencia/eje-empirico-2026.json")
_PARES = _cargar("tendencia/coincidencia-pares-2026.json")
_ESCANOS = _cargar("concentracion/escanos-camara-2026.json")
_PIVOTE = _cargar("concentracion/pivotalidad-camara-2026.json")
_MEDIOS = _cargar("concentracion/concesiones-radiodifusion-2026.json")
_GASTO = _cargar("concentracion/adjudicaciones-licitaciones-2026-06.json")

_OPCIONES = _NOMINAL.get("codigos_opcion", {})
_NOMBRES = {str(r["id"]): r["nombre"] for r in _PADRON.get("registros", [])}


def _cita(sha256_origen: str | None) -> dict:
    """Cita verificable de un dato: seq del manifiesto + hash + URL oficial."""
    entrada = _POR_SHA.get(sha256_origen or "")
    if entrada is None:
        return {"seq": None, "sha256": sha256_origen, "url_fuente": None,
                "ruta_local": None,
                "nota": "artefacto no encontrado en el manifiesto"}
    return {"seq": entrada["seq"], "sha256": entrada["sha256"],
            "url_fuente": entrada["url_fuente"],
            "ruta_local": entrada["ruta_local"],
            "timestamp_utc": entrada["timestamp_utc"]}


def _cita_conjunto(datos: dict) -> dict:
    """Cita de un indicador derivado de cientos de artefactos a la vez.

    No hay un seq unico que citar: se cita la huella del CONJUNTO de artefactos
    usados, que cualquiera puede recomputar desde el manifiesto.
    """
    return {"seq": None,
            "sha256": datos.get("sha256_conjunto"),
            "tipo": "conjunto_de_artefactos",
            "artefactos": datos.get("artefactos_usados"),
            "formula_huella": datos.get("sha256_conjunto_formula"),
            "url_fuente": "https://opendata.camara.cl"}


def _sobre(herramienta: str, argumentos: dict, resultados: list, *,
           cobertura: str, derivado: bool = False, formula: str | None = None,
           mensaje: str | None = None) -> dict:
    """Envuelve un resultado en el formato unico que exige el filtro."""
    return {
        "herramienta": herramienta,
        "argumentos": argumentos,
        "hay_dato": bool(resultados),
        "resultados": resultados,
        "derivado": derivado,
        "formula": formula,
        "n": len(resultados),
        "cobertura": cobertura,
        "mensaje": mensaje if mensaje is not None else (None if resultados else SIN_DATO),
    }


def _plano(texto: str | None) -> str:
    """Minusculas sin acentos, para comparar nombres escritos de cualquier forma."""
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")
    return sin_acentos.lower().strip()


# --------------------------------------------------------------------------
# Cobertura del corpus
# --------------------------------------------------------------------------

COBERTURA_FISCAL = (
    "Balance del Gobierno Central en % del PIB segun los cuadros de las "
    "publicaciones IFP de Dipres ingeridas (1T2025, 2T2025, 3T2025, 4T2025, 1T2026). "
    "NO incluye: Estado de Operaciones de cierre definitivo, ejecucion por partida, "
    "deuda bruta, informes del CFA ni annos anteriores a 2025."
)
COBERTURA_VOTACIONES = (
    "Votaciones en Sala de la Camara de Diputadas y Diputados del anno 2026 "
    "(totales por votacion). NO incluye: Senado, annos anteriores a 2026, "
    "comisiones, ni el voto nominal de estas votaciones."
)
COBERTURA_NOMINAL = (
    "Voto nominal de cada diputada y diputado en las votaciones de Sala de la Camara "
    "de 2026 con detalle publicado. NO incluye: Senado, comisiones, annos anteriores "
    "a 2026, ni votaciones sin detalle nominal en la fuente."
)
COBERTURA_TENDENCIA = (
    "Coincidencia de voto medida sobre las votaciones de Sala de la Camara de 2026 "
    "con voto nominal. NO es una escala ideologica: mide con que frecuencia dos "
    "personas votaron igual. NO incluye Senado ni periodos anteriores."
)
COBERTURA_CONCENTRACION = (
    "Concentracion medida sobre la composicion y las votaciones de la Camara de "
    "Diputadas y Diputados en 2026. NO incluye: Senado, gasto del Estado ni "
    "concentracion economica."
)
COBERTURA_GASTO = (
    "Adjudicaciones de licitaciones publicadas en Mercado Publico en junio de 2026, "
    "por proveedor. NO incluye: Convenio Marco, Compra Agil, trato directo, otros "
    "meses, ni las lineas en moneda distinta del peso chileno."
)
COBERTURA_MEDIOS = (
    "Concesiones vigentes de radiodifusion sonora (AM, FM, minima cobertura y onda "
    "corta) segun el listado de SUBTEL, agrupadas por titular registrado. NO incluye: "
    "television, prensa escrita, medios digitales, ni la propiedad final detras de "
    "cada sociedad concesionaria."
)


def resumen_corpus() -> dict:
    """Que contiene el sistema y que no. Base para responder 'sin dato disponible'."""
    resultados = [{
        "artefactos_en_manifiesto": len(_MANIFIESTO),
        "registros_fiscales": len(_FISCAL.get("registros", [])),
        "votaciones_2026_con_totales": len(_VOTACIONES.get("registros", [])),
        "votaciones_con_voto_nominal": len(_NOMINAL.get("registros", [])),
        "acusaciones_constitucionales": len(_AC.get("registros", [])),
        "parlamentarios_en_el_padron": len(_PADRON.get("registros", [])),
        "hay_partido_o_bancada": bool(_PADRON.get("registros")),
        "partidos_con_cohesion_medida": len(_COHESION.get("registros", [])),
        "eje_empirico_publicable": bool(_EJE.get("publicable")),
        "concesiones_de_radiodifusion": _MEDIOS.get("concesiones_leidas", 0),
        "lineas_de_adjudicacion": _GASTO.get("lineas_usadas", 0),
        "fuera_de_cobertura": [
            "Senado", "annos anteriores a 2026 en lo legislativo",
            "comisiones de la Camara",
            "ejecucion presupuestaria por partida", "deuda bruta",
            "informes del CFA",
            "gasto del Estado fuera de licitaciones (Convenio Marco, Compra Agil, "
            "trato directo) y meses distintos de junio de 2026",
            "television, prensa escrita y medios digitales",
            "propiedad final detras de cada sociedad concesionaria",
            "concentracion economica (CMF y FNE)",
            "clasificacion ideologica de partidos o parlamentarios",
        ],
        "cita": None,
    }]
    return _sobre("resumen_corpus", {}, resultados,
                  cobertura="Inventario del propio sistema; no es un dato de fuente externa.")


# --------------------------------------------------------------------------
# Modulo Fiscal
# --------------------------------------------------------------------------

def serie_balance(variable: str | None = None, caracter: str | None = None,
                  publicacion: str | None = None, anno: int | None = None) -> dict:
    """Serie del balance del Gobierno Central (% del PIB) segun los IFP."""
    args = {"variable": variable, "caracter": caracter,
            "publicacion": publicacion, "anno": anno}
    resultados = []
    for r in _FISCAL.get("registros", []):
        if variable and r["variable"] != variable:
            continue
        if caracter and r["caracter"] != caracter:
            continue
        if publicacion and _plano(r["publicacion"]) != _plano(publicacion):
            continue
        if anno is not None and r["anno"] != int(anno):
            continue
        resultados.append({
            "variable": r["variable"], "anno": r["anno"], "valor": r["valor"],
            "unidad": r["unidad"], "caracter": r["caracter"],
            "publicacion": r["publicacion"], "nota": r.get("nota"),
            "origen": r.get("origen"), "cita": _cita(r["sha256_origen"]),
        })
    resultados.sort(key=lambda x: (x["variable"], x["anno"], x["publicacion"]))
    return _sobre("serie_balance", args, resultados, cobertura=COBERTURA_FISCAL)


def comparar_publicaciones(variable: str, anno: int) -> dict:
    """Como cambio la cifra de un mismo anno entre publicaciones IFP sucesivas.

    Derivado: diferencia en puntos porcentuales contra la publicacion mas reciente
    que informa ese anno. No es 'proyeccion vs efectivo': el cierre definitivo del
    Estado de Operaciones no esta en el corpus.
    """
    args = {"variable": variable, "anno": anno}
    base = [r for r in _FISCAL.get("registros", [])
            if r["variable"] == variable and r["anno"] == int(anno)]
    if not base:
        return _sobre("comparar_publicaciones", args, [], cobertura=COBERTURA_FISCAL)

    def orden(pub: str) -> int:  # "IFP 3T2025" -> 20253
        return int(pub[-4:]) * 10 + int(pub[4])

    base.sort(key=lambda r: orden(r["publicacion"]))
    referencia = base[-1]
    resultados = []
    for r in base:
        diferencia = round(r["valor"] - referencia["valor"], 6)
        resultados.append({
            "variable": r["variable"], "anno": r["anno"], "valor": r["valor"],
            "unidad": r["unidad"], "caracter": r["caracter"],
            "publicacion": r["publicacion"],
            "publicacion_referencia": referencia["publicacion"],
            "diferencia_pp_vs_referencia": diferencia,
            "cita": _cita(r["sha256_origen"]),
        })
    return _sobre("comparar_publicaciones", args, resultados,
                  cobertura=COBERTURA_FISCAL, derivado=True,
                  formula="diferencia_pp_vs_referencia = valor_publicacion - "
                          "valor_de_la_publicacion_mas_reciente_que_informa_el_mismo_anno")


# --------------------------------------------------------------------------
# Modulo Legislativo
# --------------------------------------------------------------------------

def _registro_votacion(id_votacion: int) -> tuple[dict | None, str | None]:
    """Devuelve (registro, sha256_origen). Prioriza la ficha con voto nominal."""
    for r in _AC.get("registros", []):
        if r["id"] == int(id_votacion):
            return r, r.get("sha256_origen")
    for r in _VOTACIONES.get("registros", []):
        if r["id"] == int(id_votacion):
            return r, _VOTACIONES.get("sha256_origen")
    return None, None


def votacion(id: int) -> dict:
    """Una votacion por su id, con voto nominal si el corpus lo tiene."""
    args = {"id": id}
    registro, sha = _registro_votacion(id)
    if registro is None:
        return _sobre("votacion", args, [], cobertura=COBERTURA_VOTACIONES)
    dato = {k: v for k, v in registro.items() if k not in ("sha256_origen", "url_fuente")}
    dato["tiene_voto_nominal"] = "votos_nominales" in registro
    dato["cita"] = _cita(sha)
    return _sobre("votacion", args, [dato], cobertura=COBERTURA_VOTACIONES)


def buscar_votaciones(texto: str | None = None, desde: str | None = None,
                      hasta: str | None = None, tipo: str | None = None,
                      resultado: str | None = None, limite: int = 25) -> dict:
    """Busca votaciones de Sala 2026 por texto literal, fecha, tipo o resultado."""
    args = {"texto": texto, "desde": desde, "hasta": hasta,
            "tipo": tipo, "resultado": resultado, "limite": limite}
    aguja = _plano(texto)
    encontrados = []
    for r in _VOTACIONES.get("registros", []):
        if aguja and aguja not in _plano(r["descripcion_literal"]):
            continue
        if desde and r["fecha"][:10] < desde:
            continue
        if hasta and r["fecha"][:10] > hasta:
            continue
        if tipo and _plano(r.get("tipo")) != _plano(tipo):
            continue
        if resultado and _plano(r.get("resultado")) != _plano(resultado):
            continue
        encontrados.append({**r, "cita": _cita(_VOTACIONES.get("sha256_origen"))})
    total = len(encontrados)
    encontrados.sort(key=lambda x: x["fecha"])
    recortados = encontrados[:max(1, int(limite))]
    mensaje = None
    if total > len(recortados):
        mensaje = (f"coincidencias totales: {total}; se devuelven las primeras "
                   f"{len(recortados)} por fecha")
    return _sobre("buscar_votaciones", args, recortados,
                  cobertura=COBERTURA_VOTACIONES, mensaje=mensaje or (None if recortados else SIN_DATO))


def serie_ac() -> dict:
    """Todas las votaciones de Acusacion Constitucional del corpus, sin voto nominal."""
    resultados = []
    for r in _AC.get("registros", []):
        resultados.append({
            "id": r["id"], "descripcion_literal": r["descripcion_literal"],
            "fecha": r["fecha"], "total_si": r["total_si"], "total_no": r["total_no"],
            "total_abstencion": r["total_abstencion"],
            "total_dispensado": r["total_dispensado"],
            "quorum": r["quorum"], "resultado": r["resultado"],
            "acusado": r.get("acusado"),
            "cita": _cita(r.get("sha256_origen")),
        })
    resultados.sort(key=lambda x: x["fecha"])
    return _sobre("serie_ac", {}, resultados, cobertura=COBERTURA_NOMINAL)


def _candidatos(nombre: str) -> list[dict]:
    """Parlamentarios del padron cuyo nombre contiene el texto buscado."""
    aguja = _plano(nombre)
    if not aguja:
        return []
    return [{"diputado_id": int(i), "nombre": n}
            for i, n in sorted(_NOMBRES.items(), key=lambda x: x[1])
            if aguja in _plano(n)]


def _resolver(nombre: str, herramienta: str, args: dict, cobertura: str,
              **extra) -> tuple[dict | None, dict | None]:
    """Devuelve (candidato_unico, sobre_de_error). Nunca adivina a quien se refiere."""
    candidatos = _candidatos(nombre)
    if not candidatos:
        return None, _sobre(herramienta, args, [], cobertura=cobertura, **extra)
    if len(candidatos) > 1:
        return None, _sobre(
            herramienta, args, [], cobertura=cobertura, **extra,
            mensaje=f"{SIN_DATO}: nombre ambiguo ({nombre}); precise cual: " +
                    "; ".join(c["nombre"] for c in candidatos[:12]))
    return candidatos[0], None


def partido_de(parlamentario: str, fecha: str | None = None) -> dict:
    """Partido que la Camara registra para esa persona en esa fecha.

    Dato administrativo, no una clasificacion ideologica: es la militancia
    declarada ante la propia Camara, con sus fechas de inicio y termino.
    """
    args = {"parlamentario": parlamentario, "fecha": fecha}
    unico, error = _resolver(parlamentario, "partido_de", args, COBERTURA_NOMINAL)
    if error:
        return error
    ficha = next((r for r in _PADRON.get("registros", [])
                  if r["id"] == unico["diputado_id"]), None)
    if ficha is None:
        return _sobre("partido_de", args, [], cobertura=COBERTURA_NOMINAL)
    momento = fecha or max((v["fecha"] for v in _NOMINAL.get("registros", [])), default=None)
    vigente = None
    for m in ficha["militancias"]:
        if m.get("desde") and momento and momento < m["desde"][:19]:
            continue
        if m.get("hasta") and momento and momento > m["hasta"][:19]:
            continue
        vigente = m
        break
    resultados = [{
        "diputado_id": ficha["id"], "nombre": ficha["nombre"],
        "fecha_consultada": momento,
        "partido_id": (vigente or {}).get("partido_id"),
        "partido_nombre": (vigente or {}).get("partido_nombre"),
        "militancia_desde": (vigente or {}).get("desde"),
        "militancia_hasta": (vigente or {}).get("hasta"),
        "historial_militancias": ficha["militancias"],
        "cita": _cita((ficha.get("sha256_origen") or [None])[0]),
    }]
    return _sobre("partido_de", args, resultados, cobertura=COBERTURA_NOMINAL)


def votos_de(parlamentario: str, limite: int = 50) -> dict:
    """Voto nominal de un parlamentario en las votaciones de Sala del corpus."""
    args = {"parlamentario": parlamentario, "limite": limite}
    unico, error = _resolver(parlamentario, "votos_de", args, COBERTURA_NOMINAL)
    if error:
        return error
    clave = str(unico["diputado_id"])
    resultados = []
    for v in _NOMINAL.get("registros", []):
        codigo = v["votos"].get(clave)
        if codigo is None:
            continue
        resultados.append({
            "diputado_id": unico["diputado_id"], "nombre": unico["nombre"],
            "voto": _OPCIONES.get(codigo, codigo),
            "votacion_id": v["id"], "fecha": v["fecha"],
            "descripcion_literal": v["descripcion_literal"],
            "resultado_votacion": v.get("resultado"),
            "cita": _cita(v.get("sha256_origen")),
        })
    resultados.sort(key=lambda x: x["fecha"])
    total = len(resultados)
    recortados = resultados[-max(1, int(limite)):] if total else []
    mensaje = None
    if total > len(recortados):
        mensaje = (f"votaciones totales con voto registrado: {total}; se devuelven "
                   f"las {len(recortados)} mas recientes")
    return _sobre("votos_de", args, recortados, cobertura=COBERTURA_NOMINAL,
                  mensaje=mensaje or (None if recortados else SIN_DATO))


def coincidencia(parlamentario_a: str, parlamentario_b: str) -> dict:
    """Porcentaje de votaciones en que dos parlamentarios votaron lo mismo.

    Derivado. Solo cuenta votaciones en que AMBOS fijaron posicion (a favor,
    en contra o abstencion): una ausencia no es una postura. Si la base comun
    queda por debajo del minimo, no se publica cifra.
    """
    args = {"parlamentario_a": parlamentario_a, "parlamentario_b": parlamentario_b}
    formula = ("coincidencia_pct = 100 * votaciones_iguales / votaciones_comunes, "
               "sobre las votaciones en que ambos fijaron posicion")
    extra = {"derivado": True, "formula": formula}
    uno, error = _resolver(parlamentario_a, "coincidencia", args, COBERTURA_TENDENCIA, **extra)
    if error:
        return error
    dos, error = _resolver(parlamentario_b, "coincidencia", args, COBERTURA_TENDENCIA, **extra)
    if error:
        return error
    if uno["diputado_id"] == dos["diputado_id"]:
        return _sobre("coincidencia", args, [], cobertura=COBERTURA_TENDENCIA, **extra,
                      mensaje=f"{SIN_DATO}: se indico dos veces a la misma persona.")

    a, b = sorted((uno["diputado_id"], dos["diputado_id"]))
    par = next((r for r in _PARES.get("registros", [])
                if r["a"] == a and r["b"] == b), None)
    if par is None:
        return _sobre("coincidencia", args, [], cobertura=COBERTURA_TENDENCIA, **extra,
                      mensaje=f"{SIN_DATO}: no comparten suficientes votaciones con "
                              "posicion fijada para calcular el indicador.")
    return _sobre("coincidencia", args, [{**par, "cita": _cita_conjunto(_PARES)}],
                  cobertura=COBERTURA_TENDENCIA, **extra)


def cohesion(partido: str | None = None) -> dict:
    """Indice de Rice de cohesion por partido: que tan parejo vota cada bancada."""
    args = {"partido": partido}
    aguja = _plano(partido)
    resultados = [{**r, "cita": _cita_conjunto(_COHESION)}
                  for r in _COHESION.get("registros", [])
                  if not aguja or aguja in _plano(r["partido_nombre"])
                  or aguja == _plano(r["partido_id"])]
    return _sobre("cohesion", args, resultados, cobertura=COBERTURA_TENDENCIA,
                  derivado=True, formula=_COHESION.get("formula"))


def eje_empirico(parlamentario: str | None = None) -> dict:
    """Orden de parlamentarios por cercania de voto. NO es una escala ideologica.

    El signo del eje es arbitrario y el orden solo describe con quien se vota
    parecido. Si el primer componente explica poca varianza, no se publica.
    """
    args = {"parlamentario": parlamentario}
    extra = {"derivado": True, "formula": _EJE.get("formula")}
    if not _EJE.get("publicable"):
        return _sobre("eje_empirico", args, [], cobertura=COBERTURA_TENDENCIA, **extra,
                      mensaje=_EJE.get("motivo", SIN_DATO))
    posiciones = _EJE.get("posiciones", [])
    if parlamentario:
        unico, error = _resolver(parlamentario, "eje_empirico", args,
                                 COBERTURA_TENDENCIA, **extra)
        if error:
            return error
        posiciones = [p for p in posiciones if p["diputado_id"] == unico["diputado_id"]]
    resultados = [{**p, "total_ordenados": len(_EJE.get("posiciones", [])),
                   "varianza_explicada": _EJE.get("varianza_explicada"),
                   "advertencia": _EJE.get("advertencia_signo"),
                   "cita": _cita_conjunto(_EJE)} for p in posiciones]
    return _sobre("eje_empirico", args, resultados, cobertura=COBERTURA_TENDENCIA, **extra)


def concentracion_camara() -> dict:
    """Concentracion de la composicion de la Camara: HHI y numero efectivo de partidos."""
    if not _ESCANOS.get("registros"):
        return _sobre("concentracion_camara", {}, [], cobertura=COBERTURA_CONCENTRACION,
                      derivado=True)
    resultados = [{
        "fecha_referencia": _ESCANOS.get("fecha_referencia"),
        "votacion_de_referencia": _ESCANOS.get("votacion_de_referencia"),
        "integrantes": _ESCANOS.get("personas_en_la_votacion_de_referencia"),
        "lectura_independientes_como_bloque": _ESCANOS.get("lectura_independientes_como_bloque"),
        "lectura_independientes_por_separado": _ESCANOS.get("lectura_independientes_por_separado"),
        "nota_independientes": _ESCANOS.get("nota_independientes"),
        "reparto": _ESCANOS.get("registros"),
        "cita": _cita_conjunto(_ESCANOS),
    }]
    return _sobre("concentracion_camara", {}, resultados,
                  cobertura=COBERTURA_CONCENTRACION, derivado=True,
                  formula=json.dumps(_ESCANOS.get("formulas", {}), ensure_ascii=False))


def concentracion_medios(titular: str | None = None) -> dict:
    """Concentracion de concesiones de radiodifusion por titular registrado.

    NO mide propiedad final: un mismo controlador puede tener varias sociedades
    con RUT distinto y la fuente no publica esa relacion. Es un piso de la
    concentracion real, y la advertencia viaja en cada resultado.
    """
    args = {"titular": titular}
    if not _MEDIOS.get("registros"):
        return _sobre("concentracion_medios", args, [],
                      cobertura=COBERTURA_MEDIOS, derivado=True)
    limite = _MEDIOS.get("limite_de_la_medicion")
    cita = _cita(_MEDIOS.get("sha256_origen"))
    if titular:
        aguja = _plano(titular)
        resultados = [{**r, "limite_de_la_medicion": limite, "cita": cita}
                      for r in _MEDIOS["registros"]
                      if aguja in _plano(r["concesionaria"]) or aguja == _plano(r["rut"])]
        return _sobre("concentracion_medios", args, resultados[:25],
                      cobertura=COBERTURA_MEDIOS, derivado=True,
                      formula=json.dumps(_MEDIOS.get("formulas", {}), ensure_ascii=False))
    resultados = [{
        "concesiones_leidas": _MEDIOS.get("concesiones_leidas"),
        "indices_nacionales": _MEDIOS.get("indices_nacionales"),
        "top_1": _MEDIOS.get("top_1"), "top_5": _MEDIOS.get("top_5"),
        "top_10": _MEDIOS.get("top_10"), "top_20": _MEDIOS.get("top_20"),
        "por_tipo_servicio": _MEDIOS.get("por_tipo_servicio"),
        "mayores_titulares": _MEDIOS["registros"][:10],
        "limite_de_la_medicion": limite,
        "cita": cita,
    }]
    return _sobre("concentracion_medios", args, resultados,
                  cobertura=COBERTURA_MEDIOS, derivado=True,
                  formula=json.dumps(_MEDIOS.get("formulas", {}), ensure_ascii=False))


def concentracion_gasto(proveedor: str | None = None) -> dict:
    """Concentracion de las adjudicaciones de licitaciones por proveedor.

    Los indices declarados estan dominados por unas pocas lineas cuya magnitud
    excede cualquier rango plausible y que la fuente publica asi. Por eso cada
    resultado viaja con la advertencia y con la seccion de sensibilidad: sin
    ellas, la cifra no significa nada.
    """
    args = {"proveedor": proveedor}
    if not _GASTO.get("registros"):
        return _sobre("concentracion_gasto", args, [], cobertura=COBERTURA_GASTO,
                      derivado=True)
    comun = {
        "periodo": _GASTO.get("periodo"),
        "limite_de_la_medicion": _GASTO.get("limite_de_la_medicion"),
        "advertencia_valores_atipicos": _GASTO.get("advertencia_valores_atipicos"),
        "cita": _cita(_GASTO.get("sha256_origen")),
    }
    formula = json.dumps(_GASTO.get("formulas", {}), ensure_ascii=False)
    if proveedor:
        aguja = _plano(proveedor)
        resultados = [{**r, **comun} for r in _GASTO["registros"]
                      if aguja in _plano(r["razon_social"]) or aguja == _plano(r["rut"])]
        return _sobre("concentracion_gasto", args, resultados[:25],
                      cobertura=COBERTURA_GASTO, derivado=True, formula=formula)
    resultados = [{
        **comun,
        "lineas_usadas": _GASTO.get("lineas_usadas"),
        "monto_total_adjudicado_clp": _GASTO.get("monto_total_adjudicado_clp"),
        "mediana_monto_por_linea_clp": _GASTO.get("mediana_monto_por_linea_clp"),
        "indices_declarados": _GASTO.get("indices_nacionales"),
        "sensibilidad": _GASTO.get("sensibilidad"),
        "mayores_lineas": _GASTO.get("mayores_lineas", [])[:5],
        "top_10": _GASTO.get("top_10"), "top_100": _GASTO.get("top_100"),
        "mayores_proveedores": _GASTO["registros"][:10],
    }]
    return _sobre("concentracion_gasto", args, resultados,
                  cobertura=COBERTURA_GASTO, derivado=True, formula=formula)


def pivotalidad(partido: str | None = None) -> dict:
    """Veces en que un partido pudo cambiar el signo del resultado de una votacion."""
    args = {"partido": partido}
    aguja = _plano(partido)
    resultados = [{**r,
                   "votaciones_de_quorum_simple": _PIVOTE.get("votaciones_de_quorum_simple"),
                   "cita": _cita_conjunto(_PIVOTE)}
                  for r in _PIVOTE.get("registros", [])
                  if not aguja or aguja in _plano(r.get("partido_nombre"))
                  or aguja == _plano(r.get("partido_id"))]
    return _sobre("pivotalidad", args, resultados, cobertura=COBERTURA_CONCENTRACION,
                  derivado=True, formula=_PIVOTE.get("formula"))


# --------------------------------------------------------------------------
# Catalogo (lo consume el router; ninguna herramienta se invoca fuera de aqui)
# --------------------------------------------------------------------------

CATALOGO = {
    "resumen_corpus": resumen_corpus,
    "serie_balance": serie_balance,
    "comparar_publicaciones": comparar_publicaciones,
    "votacion": votacion,
    "buscar_votaciones": buscar_votaciones,
    "serie_ac": serie_ac,
    "partido_de": partido_de,
    "votos_de": votos_de,
    "coincidencia": coincidencia,
    "cohesion": cohesion,
    "eje_empirico": eje_empirico,
    "concentracion_camara": concentracion_camara,
    "pivotalidad": pivotalidad,
    "concentracion_medios": concentracion_medios,
    "concentracion_gasto": concentracion_gasto,
}


def invocar(herramienta: str, argumentos: dict | None = None) -> dict:
    """Punto unico de entrada. Una herramienta fuera del catalogo no existe."""
    funcion = CATALOGO.get(herramienta)
    if funcion is None:
        return {"herramienta": herramienta, "argumentos": argumentos or {},
                "hay_dato": False, "resultados": [], "derivado": False,
                "formula": None, "n": 0, "cobertura": "",
                "mensaje": f"{SIN_DATO}: la herramienta '{herramienta}' no existe en el catalogo."}
    try:
        return funcion(**(argumentos or {}))
    except TypeError as e:
        return {"herramienta": herramienta, "argumentos": argumentos or {},
                "hay_dato": False, "resultados": [], "derivado": False,
                "formula": None, "n": 0, "cobertura": "",
                "mensaje": f"{SIN_DATO}: argumentos invalidos ({e})."}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("herramienta", nargs="?", help="nombre de la herramienta del catalogo")
    p.add_argument("--args", default="{}", help="argumentos en JSON")
    p.add_argument("--catalogo", action="store_true", help="lista las herramientas")
    a = p.parse_args()
    if a.catalogo or not a.herramienta:
        for nombre, funcion in CATALOGO.items():
            primera = (funcion.__doc__ or "").strip().split("\n")[0]
            print(f"{nombre}: {primera}")
        return 0
    salida = invocar(a.herramienta, json.loads(a.args))
    print(json.dumps(salida, ensure_ascii=False, indent=1))
    return 0 if salida["hay_dato"] else 1


if __name__ == "__main__":
    sys.exit(main())
