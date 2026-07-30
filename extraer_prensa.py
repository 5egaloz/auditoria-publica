#!/usr/bin/env python3
"""Capa A del modulo de Prensa — extraccion determinista de afirmaciones con cifra.

Sin IA. Misma entrada -> misma salida byte a byte: cualquiera re-corre esto sobre
el mismo texto y obtiene el mismo resultado. Es la unica capa que puede sostener
un veredicto publicado (un LLM no es reproducible, asi que no funda nada sellado).

QUE HACE
  1. Parte el texto en oraciones.
  2. Se queda SOLO con las que contienen una cantidad resoluble.
  3. Clasifica cada una en una plantilla contrastable contra el corpus ya sellado.
  4. Emite la afirmacion con una cita LITERAL corta (tope declarado abajo).

QUE NO HACE
  · No resume, no parafrasea, no interpreta y no clasifica ideologia. Una frase
    sin cantidad no es "sospechosa": es no_contrastable_con_este_corpus, que es
    un estado legitimo y el mas frecuente.
  · No guarda el texto del articulo. Del texto solo sobreviven las citas cortas
    de las frases que contienen un numero. El resto se descarta.

EL TOPE DE CITA es una decision, no un detalle: 30 palabras y 240 caracteres por
afirmacion, una sola oracion, nunca oraciones consecutivas del mismo articulo
pegadas. Es lo minimo para que se entienda que se esta contrastando, y muy lejos
de reconstruir la nota.

Uso:
  python extraer_prensa.py --sha256 <sha del articulo en prensa/registro.jsonl> \\
      --texto prensa/textos/nota.txt
  python extraer_prensa.py --autotest

Sin dependencias: solo stdlib.
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
REGISTRO = RAIZ / "prensa" / "registro.jsonl"
SALIDA = RAIZ / "data" / "derived" / "prensa" / "afirmaciones"

MAX_PALABRAS_CITA = 30
MAX_CARACTERES_CITA = 240


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def a_numero(crudo: str) -> float | None:
    """Lee un numero en formato es-CL: punto de miles, coma decimal.

    Devuelve None ante cualquier ambiguedad en vez de arriesgar una cifra que no
    es: "1.500" son mil quinientos, pero "1.5" no es formato chileno valido y no
    se adivina.
    """
    t = crudo.strip().replace("−", "-").replace("–", "-").replace("—", "-")
    t = t.replace(" ", "").replace(" ", "")
    negativo = t.startswith("-")
    t = t.lstrip("-+")
    if not t:
        return None
    if "," in t:
        entera, _, decimal = t.partition(",")
        if "," in decimal or not decimal.isdigit():
            return None
    else:
        entera, decimal = t, ""
    grupos = entera.split(".")
    if len(grupos) > 1:
        # Puntos: solo se aceptan como separador de miles bien formado.
        if not all(len(g) == 3 for g in grupos[1:]) or not grupos[0].isdigit():
            return None
        entera = "".join(grupos)
    if not entera.isdigit():
        return None
    valor = float(entera + ("." + decimal if decimal else ""))
    return -valor if negativo else valor


# --------------------------------------------------------------------------
# Plantillas contrastables. Cada una declara CON QUE herramienta se resuelve.
# Agregar una plantilla es agregar una forma de comprobar, no de opinar.
# --------------------------------------------------------------------------

NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d+)?"

PLANTILLAS = [
    {
        "id": "votacion_totales",
        "herramienta": "buscar_votaciones",
        "descripcion": "votos a favor y en contra de una votacion",
        "patrones": [
            rf"(?P<favor>{NUM})\s+votos?\s+a\s+favor\D{{0,60}}?(?P<contra>{NUM})\s+(?:votos?\s+)?(?:en\s+contra|contra)",
            rf"(?P<favor>{NUM})\s+votos?\s+(?:a\s+favor\s+)?contra\s+(?P<contra>{NUM})",
            rf"por\s+(?P<favor>{NUM})\s+votos?\s+contra\s+(?P<contra>{NUM})",
        ],
        "campos": ["favor", "contra"],
    },
    {
        "id": "balance_pib",
        "herramienta": "serie_balance",
        "descripcion": "balance del Gobierno Central como % del PIB",
        "patrones": [rf"(?P<valor>-?{NUM})\s*%\s*d[eu]l?\s*PIB"],
        "campos": ["valor"],
    },
    {
        "id": "escanos_partido",
        "herramienta": "concentracion_camara",
        "descripcion": "escanos o diputados de un partido",
        "patrones": [
            rf"(?P<valor>{NUM})\s+(?:diputad[oa]s?|escanos?|escaños?)\s+(?:de[l]?\s+|que\s+tiene\s+el\s+)(?P<partido>[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\s]{2,40}?)(?=[,.;]|\s+(?:y|que|en|con|para)\s)",
        ],
        "campos": ["valor", "partido"],
    },
    {
        "id": "tasa_impuesto",
        "herramienta": None,   # fuera del corpus actual: dispara ampliacion
        "descripcion": "tasa de un impuesto establecida por un proyecto o ley",
        "patrones": [
            rf"(?:impuesto|tasa|tributación|tributacion)\D{{0,40}}?(?P<valor>{NUM})\s*%",
            rf"(?P<valor>{NUM})\s*%\D{{0,25}}?(?:de\s+impuesto|impuesto\s+a\s+las?\s+empresas)",
        ],
        "campos": ["valor"],
        "necesita": "texto oficial del proyecto o de la ley (BCN / Ley Chile), no ingerido",
    },
]


def oraciones(texto: str) -> list[str]:
    """Corta en oraciones sin romper abreviaturas ni cifras con punto de miles."""
    t = re.sub(r"\s+", " ", texto).strip()
    # El corte va tras . ! ? ... seguido de espacio y mayuscula o comilla.
    partes = re.split(r"(?<=[.!?…])\s+(?=[\"«A-ZÁÉÍÓÚÑ])", t)
    return [p.strip() for p in partes if p.strip()]


def recortar_cita(oracion: str) -> str:
    """Cita literal acotada. Si hay que recortar, se marca con puntos suspensivos."""
    palabras = oracion.split()
    recortada = " ".join(palabras[:MAX_PALABRAS_CITA])
    if len(recortada) > MAX_CARACTERES_CITA:
        recortada = recortada[:MAX_CARACTERES_CITA].rstrip()
    if recortada != oracion.strip():
        recortada = recortada.rstrip(" ,;:.") + "…"
    return recortada


def clasificar(oracion: str) -> list[dict]:
    """Devuelve una afirmacion por plantilla que calce. Orden fijo = determinista."""
    encontradas = []
    plano = sin_tildes(oracion)
    for plantilla in PLANTILLAS:
        for patron in plantilla["patrones"]:
            # Se busca primero sobre el texto tal cual y, si no calza, sobre el
            # mismo texto sin tildes (el medio puede escribir "deficit" o
            # "déficit"). NO se le quitan las tildes al PATRON: eso lo pasaria a
            # minusculas y destruiria los grupos nombrados (?P<favor>...).
            # En castellano quitar tildes conserva la longitud —cada vocal
            # acentuada decompone a una base + una marca que se descarta— asi que
            # las posiciones del match sirven para recortar el texto ORIGINAL y
            # la cita publicada nunca pierde sus acentos.
            m = re.search(patron, oracion, flags=re.IGNORECASE)
            sobre_plano = False
            if not m:
                m = re.search(patron, plano, flags=re.IGNORECASE)
                sobre_plano = True
            if not m:
                continue
            parametros = {}
            valido = True
            for campo in plantilla["campos"]:
                crudo = (m.groupdict().get(campo) or "").strip()
                if campo == "partido":
                    parametros[campo] = crudo
                    continue
                valor = a_numero(crudo)
                if valor is None:
                    valido = False
                    break
                parametros[campo] = valor
            if not valido:
                continue
            encontradas.append({
                "plantilla": plantilla["id"],
                "descripcion_plantilla": plantilla["descripcion"],
                "herramienta": plantilla["herramienta"],
                "parametros": parametros,
                # Del texto original, no del normalizado: lo que se publica es literal.
                "fragmento_que_calzo": (oracion[m.start():m.end()] if sobre_plano
                                        else m.group(0)).strip(),
                "necesita": plantilla.get("necesita"),
            })
            break   # una plantilla calza una vez por oracion
    return encontradas


def extraer(texto: str) -> dict:
    frases = oraciones(texto)
    afirmaciones = []
    con_cifra = 0
    for i, frase in enumerate(frases):
        tiene_numero = bool(re.search(rf"{NUM}", frase))
        if not tiene_numero:
            continue
        con_cifra += 1
        calces = clasificar(frase)
        if not calces:
            afirmaciones.append({
                "n": len(afirmaciones) + 1,
                "oracion": i,
                "cita": recortar_cita(frase),
                "plantilla": None,
                "veredicto": "no_contrastable_con_este_corpus",
                "detalle": "La frase trae una cantidad, pero no calza con ninguna plantilla "
                           "que este corpus sepa resolver.",
            })
            continue
        for c in calces:
            afirmaciones.append({
                "n": len(afirmaciones) + 1,
                "oracion": i,
                "cita": recortar_cita(frase),
                "plantilla": c["plantilla"],
                "descripcion_plantilla": c["descripcion_plantilla"],
                "herramienta": c["herramienta"],
                "parametros": c["parametros"],
                "fragmento_que_calzo": c["fragmento_que_calzo"],
                "veredicto": "pendiente_de_contraste",
                "necesita": c.get("necesita"),
            })
    return {
        "total_oraciones": len(frases),
        "oraciones_con_cantidad": con_cifra,
        "afirmaciones": afirmaciones,
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
    """Comprobaciones minimas de la capa determinista."""
    casos = [
        ("La reforma se aprobo con 26 votos a favor y 24 en contra.",
         "votacion_totales", {"favor": 26.0, "contra": 24.0}),
        ("El deficit llego a 2,8% del PIB el ano pasado.",
         "balance_pib", {"valor": 2.8}),
        ("El impuesto a las empresas baja de 27% a 23%.",
         "tasa_impuesto", None),
        ("El proyecto genera confianza y ordena las cuentas.",
         None, None),
    ]
    fallos = 0
    for texto, esperada, params in casos:
        r = extraer(texto)
        ids = [a.get("plantilla") for a in r["afirmaciones"]]
        if esperada is None:
            if r["afirmaciones"]:
                print(f"FALLA: '{texto}' no deberia producir afirmaciones y produjo {ids}")
                fallos += 1
            continue
        if esperada not in ids:
            print(f"FALLA: '{texto}' esperaba {esperada} y dio {ids}")
            fallos += 1
            continue
        if params:
            hallada = next(a for a in r["afirmaciones"] if a.get("plantilla") == esperada)
            if hallada["parametros"] != params:
                print(f"FALLA: parametros {hallada['parametros']} != {params}")
                fallos += 1
    # Determinismo: dos corridas identicas.
    t = "Aprobado por 26 votos contra 24. El deficit fue 2,8% del PIB."
    if json.dumps(extraer(t), sort_keys=True) != json.dumps(extraer(t), sort_keys=True):
        print("FALLA: la extraccion no es determinista")
        fallos += 1
    # Numeros ambiguos: no se adivinan.
    for malo in ["1.5", "1.50", "2..3", ""]:
        if a_numero(malo) is not None:
            print(f"FALLA: a_numero('{malo}') deberia ser None")
            fallos += 1
    if a_numero("1.500") != 1500.0 or a_numero("2,80") != 2.8:
        print("FALLA: lectura es-CL incorrecta")
        fallos += 1
    # El recorte de la cita se hace sobre el texto original: quitar tildes tiene
    # que conservar la longitud o las posiciones del match apuntarian a otra parte.
    for muestra in ["déficit del año pasado", "está aquí la señal", "ÁÉÍÓÚÑü"]:
        if len(sin_tildes(muestra)) != len(muestra):
            print(f"FALLA: sin_tildes cambia la longitud de '{muestra}'")
            fallos += 1
    # Una frase con tildes tiene que calzar igual y devolver la cita CON tildes.
    r = extraer("El déficit alcanzó 2,8% del PIB según el informe.")
    if not r["afirmaciones"] or "déficit" not in r["afirmaciones"][0]["cita"]:
        print("FALLA: la cita perdio los acentos del original")
        fallos += 1
    print("AUTOTEST OK" if not fallos else f"AUTOTEST: {fallos} fallas")
    return 0 if not fallos else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sha256", help="sha256 del articulo, ya registrado en prensa/registro.jsonl")
    p.add_argument("--texto", help="Archivo de trabajo con el texto del articulo (no se versiona)")
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
              "Primero se registra el articulo con ingesta_prensa.py: sin sello no hay extraccion.")
        return 1

    ruta = Path(args.texto)
    if not ruta.exists():
        print(f"ERROR: no existe {ruta}")
        return 1
    texto = ruta.read_text(encoding="utf-8")

    resultado = extraer(texto)
    salida = {
        "descripcion": "Afirmaciones con cantidad extraidas de un articulo de prensa por reglas "
                       "deterministas, para contrastarlas contra el corpus sellado. No se guarda "
                       "el texto del articulo: solo citas literales acotadas de las frases con cifra.",
        "generado_por": "extraer_prensa.py",
        "derivado": True,
        "capa": "A (determinista, sin IA)",
        "tope_de_cita": {"palabras": MAX_PALABRAS_CITA, "caracteres": MAX_CARACTERES_CITA},
        "articulo": {
            "sha256": entrada["sha256"],
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

    print(f"EXTRAIDO {destino.relative_to(RAIZ).as_posix()}")
    print(f"  oraciones: {resultado['total_oraciones']} · con cantidad: {resultado['oraciones_con_cantidad']}")
    print(f"  afirmaciones: {len(resultado['afirmaciones'])}")
    for a in resultado["afirmaciones"]:
        print(f"   [{a['n']}] {a.get('plantilla') or 'sin plantilla'} -> {a['veredicto']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
