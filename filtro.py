#!/usr/bin/env python3
"""Capa 4 del agente — filtro determinista de salida. Sin IA.

Ninguna respuesta del agente se publica sin pasar por aqui. Rechaza si:

  (a) aparece lenguaje valorativo (CLAUDE.md, Bloque 4, lista negra);
  (b) aparece una cifra que NO esta en el payload de las herramientas;
  (c) hay cifras pero falta la cita (seq del manifiesto + hash);
  (d) hay un verbo o giro de juicio ("miente", "es falso", "deberia", ...);
  (e) aparece una etiqueta ideologica sin decir QUIEN la asigno.

Excepcion deliberada: el texto entre comillas es cita literal (Bloque 4, regla 5).
Dentro de comillas no se aplican (a), (d) ni (e), y sus cifras no se exigen al
corpus: son la afirmacion que se esta contrastando. Se devuelven aparte, en
'cifras_citadas', para que la web las marque como no verificadas por el sistema.

Sin dependencias: solo stdlib.

Uso manual:
  python filtro.py --texto "..." --payload payload.json
"""

import argparse
import json
import re
import sys
import unicodedata

# --- (a) Lista negra: raices de palabras valorativas (Bloque 4) --------------
# Son raices, no palabras completas: "fracas" cubre fracaso/fracasado/fracasar.
RAICES_VALORATIVAS = [
    "fracas", "exitos", "historic", "record", "populist", "irresponsab",
    "escandalos", "alarmant", "preocupant", "solid", "debil", "desastr",
    "logro", "mezquin", "generos", "auster", "derrochad", "sesgad",
    "valient", "cobard", "desmedid", "desbordad", "exorbitant", "insuficient",
    "excesiv", "razonabl", "prudent", "temerari", "grav", "lev",
    "optimist", "pesimist", "polemic", "controvertid", "cuestionabl",
    # Etiquetas de estilo politico. No se prohiben porque el fenomeno no exista,
    # sino porque nombrarlo aplica una categoria que ningun dato de este sistema
    # respalda, y ademas reemplaza el trabajo de mostrar el mecanismo: decir
    # "demagogia" ahorra tener que decir a que colectivo se apela sin delimitar.
    "demagog", "populism", "clientelar", "asistencialist", "tecnocrat",
]
# "responsable" y "responsabilidad" se usan en sentido institucional; se vigila
# solo la forma adjetiva valorativa.
EXPRESIONES_VALORATIVAS = [
    "poco responsable", "muy responsable", "nada responsable",
]

# --- (d) Verbos y giros de juicio ------------------------------------------
GIROS_DE_JUICIO = [
    "miente", "mintio", "esta mintiendo", "es falso", "es verdad", "es mentira",
    "engana", "enganos", "manipul", "tergivers", "distorsion",
    "deberia", "deberian", "tendria que", "hay que reconocer",
    "queda demostrado", "queda claro", "esta claro que", "sin duda",
    "claramente", "evidentemente", "obviamente", "por supuesto",
    "incumpl", "no cumplio", "fallo en", "acierta", "se equivoca",
    "lo mejor", "lo peor", "mejor que", "peor que",
]

# --- (e) Etiquetas ideologicas: solo con fuente nombrada --------------------
ETIQUETAS_IDEOLOGICAS = [
    "izquierda", "derecha", "centroizquierda", "centroderecha", "ultraderecha",
    "ultraizquierda", "progresista", "conservador", "oficialismo", "oposicion",
]
# Marcadores que acreditan que la etiqueta la puso una fuente, no el sistema.
MARCADORES_DE_FUENTE = [
    "segun", "autoubicacion", "autoubicad", "declarad", "fuente", "pacto",
    "registrad", "clasificacion de", "conforme a", "de acuerdo a", "seq ",
]

SIN_DATO = "sin dato disponible"
TOLERANCIA = 1e-9

_RE_URL = re.compile(r"https?://\S+")
# Hash = 8 a 64 caracteres hexadecimales con AL MENOS una letra: una corrida de
# solo digitos es una cifra (un monto en pesos, por ejemplo) y debe verificarse.
_RE_HASH = re.compile(r"\b(?=[0-9a-fA-F]{8,64}\b)[0-9a-fA-F]*[a-fA-F][0-9a-fA-F]*\b")
_RE_NUMERO = re.compile(r"-?\d+(?:[.,]\d+)*")
_RE_SEQ = re.compile(r"\bseq\s*:?\s*(\d+)\b", re.IGNORECASE)
# Comillas rectas, tipograficas y angulares.
_RE_COMILLAS = re.compile(r"\"[^\"]*\"|“[^”]*”|«[^»]*»")


def _plano(texto: str) -> str:
    """Minusculas sin acentos, para que 'Fracasó' y 'fracaso' se traten igual."""
    d = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in d if unicodedata.category(c) != "Mn").lower()


def _partir_por_comillas(texto: str) -> tuple[str, list[str]]:
    """Devuelve (texto sin las citas literales, lista de citas literales)."""
    citas = [m.group(0) for m in _RE_COMILLAS.finditer(texto)]
    return _RE_COMILLAS.sub(" ", texto), citas


def _candidatos_numericos(token: str) -> list[tuple[float, int]]:
    """Interpreta un token numerico. Devuelve [(valor, decimales_escritos)].

    Convencion chilena: la coma es decimal y el punto separa miles. Cuando solo
    hay puntos, el token es ambiguo (puede venir de un JSON con punto decimal),
    asi que se prueban ambas lecturas y basta que una calce.
    """
    limpio = token.replace(" ", "").replace(" ", "")
    negativo = limpio.startswith("-")
    limpio = limpio.lstrip("-")
    salida = []
    if "," in limpio:
        entero, _, decimal = limpio.rpartition(",")
        entero = entero.replace(".", "")
        try:
            salida.append((float(f"{entero or '0'}.{decimal}"), len(decimal)))
        except ValueError:
            pass
    else:
        sin_puntos = limpio.replace(".", "")
        if sin_puntos.isdigit():
            salida.append((float(sin_puntos), 0))  # lectura "punto = miles"
        if limpio.count(".") == 1:
            entero, _, decimal = limpio.partition(".")
            try:
                salida.append((float(f"{entero or '0'}.{decimal}"), len(decimal)))
            except ValueError:
                pass
    return [(-v if negativo else v, d) for v, d in salida]


def _numeros_del_texto(texto: str) -> list[str]:
    sin_url = _RE_URL.sub(" ", texto)
    sin_hash = _RE_HASH.sub(" ", sin_url)
    return [m.group(0).strip() for m in _RE_NUMERO.finditer(sin_hash)]


def _valores_permitidos(payload) -> set[float]:
    """Todos los numeros que aparecen en la salida de las herramientas.

    Incluye los numeros embebidos en cadenas (fechas, ids, 'IFP 3T2025'), porque
    el redactor legitimamente los reproduce.
    """
    valores: set[float] = set()

    def recorrer(nodo):
        if isinstance(nodo, bool) or nodo is None:
            return
        if isinstance(nodo, (int, float)):
            valores.add(float(nodo))
        elif isinstance(nodo, str):
            for token in _numeros_del_texto(nodo):
                for valor, _ in _candidatos_numericos(token):
                    valores.add(valor)
        elif isinstance(nodo, dict):
            for v in nodo.values():
                recorrer(v)
        elif isinstance(nodo, (list, tuple)):
            for v in nodo:
                recorrer(v)

    recorrer(payload)
    return valores


def _calza(valor: float, decimales: int, permitidos: set[float]) -> bool:
    for p in permitidos:
        if abs(p - valor) < TOLERANCIA:
            return True
        if decimales and abs(round(p, decimales) - valor) < TOLERANCIA:
            return True
    return False


def _sobres(payload) -> list[dict]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [s for s in payload if isinstance(s, dict)]
    return []


def revisar(texto: str, payload) -> dict:
    """Revisa una respuesta contra el payload de herramientas que la sustenta."""
    motivos: list[str] = []
    advertencias: list[str] = []
    fuera, citas_literales = _partir_por_comillas(texto)
    plano = _plano(fuera)

    # (a) lenguaje valorativo
    for raiz in RAICES_VALORATIVAS:
        if re.search(rf"\b{raiz}\w*", plano):
            motivos.append(f"lenguaje valorativo: raiz '{raiz}' (Bloque 4, lista negra)")
    for expresion in EXPRESIONES_VALORATIVAS:
        if expresion in plano:
            motivos.append(f"lenguaje valorativo: '{expresion}'")

    # (d) giros de juicio
    for giro in GIROS_DE_JUICIO:
        if giro in plano:
            motivos.append(f"giro de juicio: '{giro}' (el sistema expone, no concluye)")

    # (e) etiqueta ideologica sin fuente nombrada, frase por frase
    for frase in re.split(r"[.;\n]", fuera):
        plano_frase = _plano(frase)
        etiquetas = [e for e in ETIQUETAS_IDEOLOGICAS if re.search(rf"\b{e}\w*", plano_frase)]
        if etiquetas and not any(m in plano_frase for m in MARCADORES_DE_FUENTE):
            motivos.append(
                f"etiqueta ideologica sin fuente nombrada: {sorted(set(etiquetas))} "
                "(toda etiqueta debe decir quien la asigno, con seq y hash)")

    # (b) cifras: cada una debe existir en el payload
    permitidos = _valores_permitidos(payload)
    magnitudes = {abs(p) for p in permitidos}
    no_respaldadas = []
    for token in _numeros_del_texto(fuera):
        candidatos = _candidatos_numericos(token)
        if not candidatos:
            continue
        if any(_calza(v, d, permitidos) for v, d in candidatos):
            continue
        # Un deficit se escribe a veces sin el signo ("2,8 % del PIB" por -2,80).
        # Se acepta la magnitud, pero queda anotado para revision humana.
        if any(_calza(abs(v), d, magnitudes) for v, d in candidatos):
            advertencias.append(f"cifra '{token}' calza en magnitud pero no en signo")
            continue
        no_respaldadas.append(token)
    for token in sorted(set(no_respaldadas)):
        motivos.append(f"cifra sin respaldo en el payload: '{token}'")

    cifras_citadas = sorted({t for c in citas_literales for t in _numeros_del_texto(c)})

    # (c) citas: si hay dato, tiene que haber seq + hash verificables
    sobres = _sobres(payload)
    hay_dato = any(s.get("hay_dato") for s in sobres)
    hashes = set()
    seqs = set()
    for s in sobres:
        for r in s.get("resultados", []):
            cita = r.get("cita") if isinstance(r, dict) else None
            if isinstance(cita, dict):
                if cita.get("sha256"):
                    hashes.add(cita["sha256"].lower())
                if cita.get("seq") is not None:
                    seqs.add(int(cita["seq"]))

    if hay_dato:
        # Un indicador derivado de cientos de artefactos no tiene un seq unico:
        # se ancla en la huella del conjunto. Por eso el seq se exige solo cuando
        # el payload trae seqs; el hash de origen se exige siempre.
        if seqs:
            seqs_citados = {int(m.group(1)) for m in _RE_SEQ.finditer(texto)}
            if not seqs_citados & seqs:
                motivos.append(f"falta la cita al manifiesto: ninguna referencia 'seq N' "
                               f"de las esperadas {sorted(seqs)}")
        fragmentos = [h.group(0).lower() for h in _RE_HASH.finditer(texto)]
        if not any(any(h.startswith(f) for h in hashes) for f in fragmentos):
            motivos.append("falta el hash de origen: ninguna cifra queda anclada a "
                           "un artefacto del manifiesto")
    else:
        if _plano(SIN_DATO) not in _plano(texto):
            motivos.append("sin dato en el payload: la respuesta debe decir "
                           f"'{SIN_DATO}' y no entregar cifras")
        elif no_respaldadas:
            pass  # ya reportado arriba

    return {
        "aprobado": not motivos,
        "motivos": motivos,
        "advertencias": advertencias,
        "cifras_citadas": cifras_citadas,
        "citas_literales": len(citas_literales),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--texto", required=True, help="respuesta redactada a revisar")
    p.add_argument("--payload", help="archivo JSON con el/los sobres de herramientas")
    a = p.parse_args()
    payload = json.loads(open(a.payload, encoding="utf-8").read()) if a.payload else {}
    informe = revisar(a.texto, payload)
    print(json.dumps(informe, ensure_ascii=False, indent=1))
    return 0 if informe["aprobado"] else 1


if __name__ == "__main__":
    sys.exit(main())
