#!/usr/bin/env python3
"""Capa A' del modulo de Prensa — indicadores estructurales, deterministas y sellables.

POR QUE EXISTE
  La pregunta que motiva este archivo es "cuanta demagogia o populismo hay en
  esta nota". Esa pregunta, respondida con una etiqueta, no se puede sellar: no
  hay hash que respalde la palabra "populista", y el Bloque 4 del CLAUDE.md la
  tiene ademas en su lista negra. Un sistema que rotula ideologia emite un juicio
  y se vuelve el producto ideologico que este proyecto existe para evitar.

  Entonces la pregunta se da vuelta y se vuelve medible: en vez de calificar el
  discurso, se cuentan RASGOS DE FORMA que cualquiera puede recontar sobre el
  mismo texto y obtener el mismo numero.

    · promesas de efecto futuro que NO declaran de donde salen los recursos
    · cifras que NO traen base de comparacion
    · cifras que NO traen atribucion de fuente
    · apelaciones a un colectivo cuyo alcance el texto no delimita
    · densidad de palabras valorativas por cada 1.000 palabras

  Ninguno de esos cinco numeros dice que alguien mienta. Dicen que hay
  afirmaciones que el lector no puede ir a comprobar a ninguna parte — que es
  precisamente lo que se pierde cuando el debate se corre de lo tecnico a lo
  ideologico. El lector concluye; el sistema no.

QUE LO HACE SELLABLE
  Sin IA, sin red, sin azar. Misma entrada -> misma salida byte a byte. El
  criterio no vive en este codigo sino en prensa/lexico.json, que se publica, y
  cada salida graba el sha256 de ese archivo: un indicador sin la version de su
  criterio al lado no significa nada.

QUE NO HACE
  · No promedia por medio. Un promedio por medio seria un ranking de prensa.
  · No emite veredictos: eso es de contrastar_prensa.py, contra datos sellados.
  · No guarda el texto del articulo. Solo citas literales acotadas, con el mismo
    tope que extraer_prensa.py: 30 palabras y 240 caracteres, una sola oracion.

Uso:
  python retorica.py --sha256 <sha del articulo en prensa/registro.jsonl> \\
      --texto prensa/textos/nota.txt
  python retorica.py --autotest

Sin dependencias: solo stdlib.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
REGISTRO = RAIZ / "prensa" / "registro.jsonl"
LEXICO = RAIZ / "prensa" / "lexico.json"
CUERPOS = RAIZ / "prensa" / "cuerpos.json"
SALIDA = RAIZ / "data" / "derived" / "prensa" / "retorica"

MAX_PALABRAS_CITA = 30
MAX_CARACTERES_CITA = 240

# Mismo patron numerico que extraer_prensa.py: formato es-CL, punto de miles y
# coma decimal. Se repite a proposito en vez de importarlo — las dos capas deben
# poder correrse por separado y un tercero que solo audite esta no deberia
# necesitar el resto del repo.
NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d+)?"


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def oraciones(texto: str) -> list[str]:
    """Corta en oraciones. Identico a extraer_prensa.py, por la misma razon."""
    t = re.sub(r"\s+", " ", texto).strip()
    partes = re.split(r"(?<=[.!?…])\s+(?=[\"«A-ZÁÉÍÓÚÑ])", t)
    return [p.strip() for p in partes if p.strip()]


def recortar_cita(oracion: str) -> str:
    palabras = oracion.split()
    recortada = " ".join(palabras[:MAX_PALABRAS_CITA])
    if len(recortada) > MAX_CARACTERES_CITA:
        recortada = recortada[:MAX_CARACTERES_CITA].rstrip()
    if recortada != oracion.strip():
        recortada = recortada.rstrip(" ,;:.") + "…"
    return recortada


# --------------------------------------------------------------------------
# Emparejamiento lexico.
#
# Regla unica y publicada: se compara sin tildes, en minuscula y sobre PALABRA
# COMPLETA. Lo ultimo importa mas de lo que parece: sin el limite de palabra,
# "grave" contaria dentro de "gravemente" y "us$" dentro de cualquier cosa, y el
# indicador subiria por una razon que no tiene nada que ver con lo que dice medir.
# --------------------------------------------------------------------------

def _patron_de(termino: str) -> re.Pattern:
    plano = sin_tildes(termino)
    partes = [re.escape(p) for p in plano.split()]
    cuerpo = r"\s+".join(partes)
    # \b no funciona junto a los simbolos con que terminan varios terminos del
    # lexico ("us$", "%", "vs."): ahi el limite se pide como "no seguido de letra
    # ni digito", que es lo que \b intenta decir y no puede tras un no-alfanumerico.
    izq = r"(?<![0-9a-z])" if plano[:1].isalnum() else r""
    der = r"(?![0-9a-z])" if plano[-1:].isalnum() else r""
    return re.compile(izq + cuerpo + der)


class Lexico:
    """Las listas de prensa/lexico.json, compiladas una vez y con su hash."""

    def __init__(self, datos: dict, sha256: str):
        self.datos = datos
        self.sha256 = sha256
        self.version = datos.get("version")
        listas = datos.get("listas", {})
        self.patrones = {
            nombre: [(t, _patron_de(t)) for t in lista.get("terminos", [])]
            for nombre, lista in listas.items()
        }
        self.delimitadores = [_patron_de(t) for t in
                              listas.get("colectivo_indefinido", {}).get("delimitadores", [])]

    def hallazgos(self, nombre: str, texto_plano: str) -> list[str]:
        """Terminos de una lista presentes en el texto. Orden fijo = determinista."""
        return [t for t, p in self.patrones.get(nombre, []) if p.search(texto_plano)]

    def toca(self, nombre: str, texto_plano: str) -> bool:
        return any(p.search(texto_plano) for _, p in self.patrones.get(nombre, []))

    def delimitado(self, texto_plano: str) -> bool:
        """El colectivo viene acotado: un numero, un tramo, un porcentaje, una region."""
        if re.search(NUM, texto_plano):
            return True
        return any(p.search(texto_plano) for p in self.delimitadores)


def cargar_lexico(ruta: Path = LEXICO) -> Lexico:
    crudo = ruta.read_bytes()
    return Lexico(json.loads(crudo.decode("utf-8")), hashlib.sha256(crudo).hexdigest())


# --------------------------------------------------------------------------
# El recorte del cuerpo.
#
# El texto que sirve la URL de un medio no es el articulo: es el articulo mas el
# menu, la barra de secciones, los titulares de OTRAS notas y el pie de pagina.
# Comprobado sobre las dos notas del caso piloto: casi la mitad de los caracteres
# servidos no son la nota, y el titular de una nota vecina entraba al conteo de
# palabras valorativas de esta. Medir sobre todo eso publica un numero que no
# describe lo que dice describir.
#
# La solucion no es adivinar donde termina el menu con una heuristica —eso falla
# en silencio y en silencio es como se cuelan los errores que nadie audita— sino
# declarar las anclas en prensa/cuerpos.json, versionadas como todo lo demas.
# Si un ancla ya no aparece, la pagina cambio y no se mide.
# --------------------------------------------------------------------------

def cargar_cuerpos(ruta: Path = CUERPOS) -> dict:
    if not ruta.exists():
        return {}
    return json.loads(ruta.read_text(encoding="utf-8")).get("cuerpos", {})


def recortar_cuerpo(texto: str, anclas: dict | None) -> tuple[str, dict]:
    """Devuelve (texto del articulo, como se recorto). Lanza si un ancla no esta."""
    servido = len(texto)
    if not anclas:
        return texto, {
            "alcance": "pagina_completa",
            "apto_para_publicar": False,
            "caracteres_servidos": servido,
            "caracteres_medidos": servido,
            "por_que": "Este articulo no tiene anclas declaradas en prensa/cuerpos.json, asi que "
                       "la medicion incluye menu, titulares de otras notas y pie de pagina. Los "
                       "indicadores NO describen el articulo y no deben publicarse como si lo "
                       "hicieran.",
        }
    inicio, fin = anclas.get("inicio", ""), anclas.get("fin", "")
    i = texto.find(inicio) if inicio else 0
    if i < 0:
        raise ValueError(f"el ancla de inicio no aparece en el texto: «{inicio[:60]}…». "
                         "La pagina cambio: no se mide.")
    j = texto.find(fin, i + len(inicio)) if fin else len(texto)
    if j < 0:
        raise ValueError(f"el ancla de fin no aparece despues del inicio: «{fin[:60]}…». "
                         "La pagina cambio: no se mide.")
    cuerpo = texto[i:j].strip()
    return cuerpo, {
        "alcance": "cuerpo_del_articulo",
        "apto_para_publicar": True,
        "caracteres_servidos": servido,
        "caracteres_medidos": len(cuerpo),
        "descartado": servido - len(cuerpo),
        "ancla_inicio": inicio,
        "ancla_fin": fin,
        "excluye": anclas.get("excluye", []),
        "regla": "desde la primera aparicion literal del ancla de inicio (incluida) hasta justo "
                 "antes de la primera aparicion literal del ancla de fin posterior a ella",
    }


# --------------------------------------------------------------------------
# Los cinco indicadores.
#
# Cada uno devuelve un conteo y las oraciones que lo produjeron, con cita
# acotada, para que el numero se pueda auditar frase por frase en vez de tener
# que creerle. Un indicador que no muestra sus casos es un adjetivo con formato
# de numero.
# --------------------------------------------------------------------------

def medir(texto: str, lex: Lexico) -> dict:
    frases = oraciones(texto)
    planas = [sin_tildes(f) for f in frases]
    palabras = len(re.findall(r"\b[\wÁÉÍÓÚÑáéíóúñü]+\b", texto))

    promesas: list[dict] = []
    cifras: list[dict] = []
    colectivos: list[dict] = []
    valorativas: list[dict] = []

    for i, (frase, plana) in enumerate(zip(frases, planas)):
        # -- vecindad: el castellano periodistico parte la informacion entre
        # oraciones contiguas. Exigir todo en la misma oracion inflaria los tres
        # indicadores por una razon gramatical y no por una del texto.
        anterior = planas[i - 1] if i > 0 else ""
        siguiente = planas[i + 1] if i + 1 < len(frases) else ""

        # 1) Promesa de efecto futuro sin fuente de financiamiento declarada.
        giros = lex.hallazgos("promesa", plana)
        if giros:
            fin = lex.hallazgos("financiamiento", plana) or lex.hallazgos("financiamiento", siguiente)
            promesas.append({
                "oracion": i,
                "cita": recortar_cita(frase),
                "giros_de_promesa": giros,
                "financiamiento_declarado": bool(fin),
                "terminos_de_financiamiento": fin,
                "ventana_financiamiento": "misma oracion y la siguiente",
            })

        # 2 y 3) Cifra sin base de comparacion / sin atribucion de fuente.
        if re.search(NUM, frase):
            comp = (lex.hallazgos("comparacion", plana)
                    or lex.hallazgos("comparacion", anterior)
                    or lex.hallazgos("comparacion", siguiente))
            atr = lex.hallazgos("atribucion", plana) or lex.hallazgos("atribucion", anterior)
            cifras.append({
                "oracion": i,
                "cita": recortar_cita(frase),
                "base_de_comparacion": bool(comp),
                "terminos_de_comparacion": comp,
                "atribucion_de_fuente": bool(atr),
                "terminos_de_atribucion": atr,
                "ventana_comparacion": "la oracion anterior, la misma y la siguiente",
                "ventana_atribucion": "la oracion anterior y la misma",
            })

        # 4) Colectivo invocado sin delimitar su alcance.
        invocados = lex.hallazgos("colectivo_indefinido", plana)
        if invocados:
            acotado = lex.delimitado(plana)
            colectivos.append({
                "oracion": i,
                "cita": recortar_cita(frase),
                "colectivos": invocados,
                "delimitado_en_la_oracion": acotado,
            })

        # 5) Palabras valorativas: se guarda la oracion, no solo el conteo.
        halladas = lex.hallazgos("valorativas", plana)
        if halladas:
            valorativas.append({
                "oracion": i,
                "cita": recortar_cita(frase),
                "terminos": halladas,
            })

    # El conteo de valorativas es por OCURRENCIA, no por oracion: una frase con
    # tres adjetivos pesa tres. La densidad se publica por 1.000 palabras porque
    # el valor absoluto solo mide el largo de la nota.
    ocurrencias = sum(len(v["terminos"]) for v in valorativas)
    densidad = round(ocurrencias / palabras * 1000, 2) if palabras else 0.0

    promesas_sin_fin = [p for p in promesas if not p["financiamiento_declarado"]]
    cifras_sin_comp = [c for c in cifras if not c["base_de_comparacion"]]
    cifras_sin_atr = [c for c in cifras if not c["atribucion_de_fuente"]]
    colectivos_sin_delim = [c for c in colectivos if not c["delimitado_en_la_oracion"]]

    return {
        "total_oraciones": len(frases),
        "total_palabras": palabras,
        "indicadores": {
            "promesas_sin_financiamiento_declarado": {
                "valor": len(promesas_sin_fin),
                "de_un_total_de": len(promesas),
                "unidad": "oraciones",
                "que_cuenta": "Oraciones que anuncian un efecto futuro sin declarar, ni en esa "
                              "oracion ni en la siguiente, de donde salen los recursos o cuanto cuesta.",
                "que_no_cuenta": "No dice que la promesa sea falsa. Dice que hoy no hay contra que "
                                 "comprobarla.",
            },
            "cifras_sin_base_de_comparacion": {
                "valor": len(cifras_sin_comp),
                "de_un_total_de": len(cifras),
                "unidad": "oraciones con cifra",
                "que_cuenta": "Oraciones con una cantidad que no traen, en su vecindad, contra que "
                              "compararla (otro periodo, una mediana, un promedio, otro pais).",
                "que_no_cuenta": "No dice que la cifra sea incorrecta ni que la comparacion faltante "
                                 "cambiaria el sentido.",
            },
            "cifras_sin_atribucion_de_fuente": {
                "valor": len(cifras_sin_atr),
                "de_un_total_de": len(cifras),
                "unidad": "oraciones con cifra",
                "que_cuenta": "Oraciones con una cantidad donde el texto no dice quien la entrego.",
                "que_no_cuenta": "No dice que la cifra este inventada. Dice que el lector no tiene "
                                 "a quien ir a preguntarle.",
            },
            "colectivos_sin_delimitar": {
                "valor": len(colectivos_sin_delim),
                "de_un_total_de": len(colectivos),
                "unidad": "ocurrencias",
                "que_cuenta": "Apelaciones a un sujeto colectivo ('la gente', 'las familias') sin "
                              "un numero, tramo, decil o region que acote de quienes se habla.",
                "que_no_cuenta": "No dice que quien habla sea populista. Un colectivo sin delimitar "
                                 "tambien es economia de lenguaje.",
            },
            "densidad_valorativa": {
                "valor": densidad,
                "de_un_total_de": palabras,
                "unidad": "ocurrencias por cada 1.000 palabras",
                "ocurrencias": ocurrencias,
                "que_cuenta": "Cuanta palabra con carga de juicio contiene el texto publicado, "
                              "contra la lista simetrica de prensa/lexico.json.",
                "que_no_cuenta": "No dice que la nota sea tendenciosa. El adjetivo puede venir dentro "
                                 "de una cita literal a un tercero, y el conteo no los separa.",
            },
        },
        "casos": {
            "promesas": promesas,
            "cifras": cifras,
            "colectivos": colectivos,
            "valorativas": valorativas,
        },
    }


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


def autotest() -> int:
    lex = cargar_lexico()
    fallos = 0

    def ind(texto, clave):
        return medir(texto, lex)["indicadores"][clave]["valor"]

    casos = [
        # Promesa sin financiamiento: cuenta.
        ("La medida permitira crear miles de empleos en todo el pais.",
         "promesas_sin_financiamiento_declarado", 1),
        # Misma promesa CON financiamiento en la oracion siguiente: no cuenta.
        ("La medida permitira crear empleos. Se financia con cargo a la partida de Hacienda.",
         "promesas_sin_financiamiento_declarado", 0),
        # Cifra sin base de comparacion ni atribucion.
        ("El plan considera 45 obras.", "cifras_sin_base_de_comparacion", 1),
        ("El plan considera 45 obras.", "cifras_sin_atribucion_de_fuente", 1),
        # La misma cifra con ambas cosas: no cuenta en ninguno de los dos.
        ("Segun Dipres, el plan considera 45 obras frente a 30 del ano anterior.",
         "cifras_sin_base_de_comparacion", 0),
        ("Segun Dipres, el plan considera 45 obras frente a 30 del ano anterior.",
         "cifras_sin_atribucion_de_fuente", 0),
        # Colectivo sin delimitar vs. delimitado por una cifra en la misma oracion.
        ("Esto es por la gente que trabaja.", "colectivos_sin_delimitar", 1),
        ("Beneficia a las familias del primer quintil, unas 800 mil.",
         "colectivos_sin_delimitar", 0),
        # Texto sin nada de esto: todo en cero.
        ("El proyecto ingreso a tramite el lunes.", "promesas_sin_financiamiento_declarado", 0),
        ("El proyecto ingreso a tramite el lunes.", "colectivos_sin_delimitar", 0),
    ]
    for texto, clave, esperado in casos:
        obtenido = ind(texto, clave)
        if obtenido != esperado:
            print(f"FALLA: '{texto[:52]}…' {clave}: esperaba {esperado} y dio {obtenido}")
            fallos += 1

    # Densidad valorativa: dos adjetivos de la lista en una frase corta.
    r = medir("Fue un fracaso historico para el gobierno.", lex)
    d = r["indicadores"]["densidad_valorativa"]
    if d["ocurrencias"] != 2:
        print(f"FALLA: se esperaban 2 valorativas y hubo {d['ocurrencias']}")
        fallos += 1

    # Palabra completa: 'grave' NO debe contarse dentro de 'gravemente'.
    if medir("El proyecto avanza gravemente lento.", lex)["indicadores"][
            "densidad_valorativa"]["ocurrencias"] != 0:
        print("FALLA: el emparejamiento contó una subcadena en vez de una palabra completa")
        fallos += 1

    # Simetria: los pares opuestos de la lista pesan igual. Si no, el instrumento
    # castigaria un lado del espectro y seria el producto ideologico que el
    # proyecto existe para no ser.
    for a, b in [("Fue un exito rotundo.", "Fue un fracaso rotundo."),
                 ("Una medida responsable.", "Una medida irresponsable."),
                 ("Un balance solido.", "Un balance debil.")]:
        oa = medir(a, lex)["indicadores"]["densidad_valorativa"]["ocurrencias"]
        ob = medir(b, lex)["indicadores"]["densidad_valorativa"]["ocurrencias"]
        if oa != ob or oa == 0:
            print(f"FALLA: asimetria entre '{a}' ({oa}) y '{b}' ({ob})")
            fallos += 1

    # Tildes: el mismo texto acentuado y sin acentuar da el mismo numero, y la
    # cita publicada conserva los acentos del original.
    con = medir("La reforma permitirá más empleo según el informe.", lex)
    sin = medir("La reforma permitira mas empleo segun el informe.", lex)
    if (con["indicadores"]["promesas_sin_financiamiento_declarado"]["valor"]
            != sin["indicadores"]["promesas_sin_financiamiento_declarado"]["valor"]):
        print("FALLA: el resultado cambia según los acentos")
        fallos += 1
    if "permitirá" not in con["casos"]["promesas"][0]["cita"]:
        print("FALLA: la cita perdió los acentos del original")
        fallos += 1

    # Determinismo: dos corridas byte a byte iguales.
    t = ("Segun Hacienda, la reforma permitira recaudar 2.000 millones de dolares. "
         "Es un exito para la gente.")
    if json.dumps(medir(t, lex), sort_keys=True) != json.dumps(medir(t, lex), sort_keys=True):
        print("FALLA: la medición no es determinista")
        fallos += 1

    # Recorte del cuerpo: se mide el articulo, no el menu del sitio.
    pagina = ("Menu Inicio Politica Economia Deportes CUERPO La reforma permitira crecer. "
              "FIN Entradas relacionadas: Un fracaso historico del gobierno")
    cuerpo, info = recortar_cuerpo(pagina, {"inicio": "CUERPO", "fin": "FIN"})
    if "menu" in cuerpo.lower() or "fracaso" in cuerpo.lower():
        print(f"FALLA: el recorte dejo pasar texto de fuera del articulo: '{cuerpo}'")
        fallos += 1
    if info["alcance"] != "cuerpo_del_articulo" or not info["apto_para_publicar"]:
        print("FALLA: un recorte con anclas válidas debería quedar apto para publicar")
        fallos += 1
    # Un titular vecino con adjetivo NO debe contarse dentro del articulo.
    if medir(cuerpo, lex)["indicadores"]["densidad_valorativa"]["ocurrencias"] != 0:
        print("FALLA: el conteo tomó palabras de fuera del cuerpo recortado")
        fallos += 1
    # Sin anclas: se mide igual, pero marcado como NO publicable.
    _, info = recortar_cuerpo(pagina, None)
    if info["alcance"] != "pagina_completa" or info["apto_para_publicar"]:
        print("FALLA: sin anclas la medición debería quedar marcada como no publicable")
        fallos += 1
    # Un ancla que ya no aparece significa que la pagina cambio: se falla, no se
    # recorta a medias ni se mide la pagina entera en silencio.
    for anclas in ({"inicio": "NO EXISTE", "fin": "FIN"}, {"inicio": "CUERPO", "fin": "NO EXISTE"}):
        try:
            recortar_cuerpo(pagina, anclas)
            print(f"FALLA: un ancla ausente {anclas} debería abortar la medición")
            fallos += 1
        except ValueError:
            pass

    # Tope de cita: ninguna cita publicada excede lo declarado.
    largo = " ".join(["palabra"] * 80) + " y 45 obras."
    for grupo in medir(largo, lex)["casos"].values():
        for c in grupo:
            if len(c["cita"].split()) > MAX_PALABRAS_CITA + 1 or len(c["cita"]) > MAX_CARACTERES_CITA + 1:
                print(f"FALLA: cita sobre el tope declarado ({len(c['cita'])} caracteres)")
                fallos += 1

    print("AUTOTEST OK" if not fallos else f"AUTOTEST: {fallos} fallas")
    return 0 if not fallos else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sha256", help="sha256 del articulo, ya registrado en prensa/registro.jsonl")
    p.add_argument("--texto", help="Archivo de trabajo con el texto del articulo (no se versiona)")
    p.add_argument("--pagina-completa", action="store_true",
                   help="Medir sin anclas de cuerpo. La salida queda marcada apto_para_publicar=false")
    p.add_argument("--autotest", action="store_true")
    args = p.parse_args()

    if args.autotest:
        return autotest()
    if not args.sha256 or not args.texto:
        print("ERROR: se requieren --sha256 y --texto (o --autotest)")
        return 2

    entrada = buscar_entrada(args.sha256)
    if not entrada:
        print(f"ERROR: {args.sha256[:12]}… no esta en prensa/registro.jsonl. "
              "Primero se registra el articulo con ingesta_prensa.py: sin sello no hay medicion.")
        return 1

    ruta = Path(args.texto)
    if not ruta.exists():
        print(f"ERROR: no existe {ruta}")
        return 1

    lex = cargar_lexico()
    anclas = cargar_cuerpos().get(entrada["sha256"])
    if not anclas and not args.pagina_completa:
        print(f"ERROR: {args.sha256[:12]}… no tiene anclas de cuerpo en prensa/cuerpos.json.")
        print("  El texto servido por un medio trae menu, titulares de otras notas y pie de")
        print("  pagina: medir sobre eso publica numeros que no describen la nota. Declara las")
        print("  anclas alli, o corre con --pagina-completa para obtener una medicion marcada")
        print("  como no publicable.")
        return 1
    try:
        cuerpo, recorte = recortar_cuerpo(ruta.read_text(encoding="utf-8"), anclas)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    resultado = medir(cuerpo, lex)

    salida = {
        "descripcion": "Indicadores estructurales de un articulo de prensa, medidos por reglas "
                       "deterministas contra las listas publicadas en prensa/lexico.json. Miden "
                       "FORMA del texto: que tanto de lo afirmado trae con que comprobarse. No "
                       "miden verdad, ni intencion, ni ideologia, y no se promedian por medio.",
        "generado_por": "retorica.py",
        "derivado": True,
        "capa": "A' (determinista, sin IA, sellable)",
        "lexico": {
            "archivo": "prensa/lexico.json",
            "sha256": lex.sha256,
            "version": lex.version,
            "por_que_va_el_hash": "Cambiar una lista cambia todos los numeros. Un indicador sin la "
                                  "version de su criterio al lado no significa nada.",
        },
        "tope_de_cita": {"palabras": MAX_PALABRAS_CITA, "caracteres": MAX_CARACTERES_CITA},
        "recorte_del_cuerpo": recorte,
        "advertencia_de_lectura": "Un indicador alto no prueba demagogia y uno bajo no prueba "
                                  "honestidad. El emparejamiento es lexico: no distingue una "
                                  "promesa afirmada de una negada ni de una citada.",
        "articulo": {
            "sha256": entrada["sha256"],
            "sha256_texto": entrada.get("sha256_texto", ""),
            "seq_registro": entrada["seq"],
            "medio": entrada["medio"],
            "titulo": entrada["titulo"],
            "url": entrada["url"],
            "fecha_publicacion": entrada["fecha_publicacion"],
            "tema": entrada.get("tema", ""),
        },
        **resultado,
    }
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / f"{entrada['sha256']}.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"MEDIDO {destino.relative_to(RAIZ).as_posix()}")
    print(f"  lexico sha256: {lex.sha256[:16]}… (v{lex.version})")
    if recorte["alcance"] == "cuerpo_del_articulo":
        print(f"  cuerpo: {recorte['caracteres_medidos']} de {recorte['caracteres_servidos']} "
              f"caracteres servidos ({recorte['descartado']} descartados: menu, notas vecinas, pie)")
    else:
        print("  AVISO: medido sobre la pagina completa (sin anclas). NO publicable: los numeros")
        print("  incluyen menu y titulares de otras notas.")
    print(f"  oraciones: {resultado['total_oraciones']} · palabras: {resultado['total_palabras']}")
    for nombre, i in resultado["indicadores"].items():
        print(f"   {nombre}: {i['valor']} de {i['de_un_total_de']} ({i['unidad']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
