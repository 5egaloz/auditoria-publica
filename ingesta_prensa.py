#!/usr/bin/env python3
"""Ingesta de prensa — cadena propia, sin republicar texto ajeno.

Por que NO entra al manifiesto principal (CLAUDE.md, Bloque 1): `manifest.jsonl`
esta reservado a originales descargados de fuentes del Estado, que se guardan
intactos en data/raw/ y se pueden redistribuir. Un articulo de prensa no es
ninguna de las dos cosas: es obra ajena con derechos y el repo es publico.

Entonces se aplica el mismo criterio que ya usa sellar_prompts.py: artefacto
sellado con su SHA-256, custodia en el historial de Git, cadena aparte.

    prensa/registro.jsonl   <- cadena hash-chain propia, genesis en 64 ceros

QUE SE GUARDA: la URL, el medio, el titulo, la fecha, las condiciones de la
captura (timestamp, http_status, bytes) y el sha256 de los bytes que la URL
sirvio en ese instante.

QUE NO SE GUARDA: el texto del articulo. Ni completo ni en partes.

Consecuencia honesta, y hay que decirla en el sitio: sin el texto guardado, un
tercero no puede reproducir la extraccion sobre el articulo original si el medio
lo edita o lo baja. El hash prueba que CAMBIO, no que decia. Es el precio de no
republicar obra ajena, y se declara en vez de disimularse.

Uso:
  python ingesta_prensa.py <URL> --medio "La Tercera" --titulo "..." \
      --fecha 2026-07-16 [--tema mega-reforma]
  python ingesta_prensa.py --verificar

Sin dependencias: solo stdlib.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DIR_PRENSA = RAIZ / "prensa"
REGISTRO = DIR_PRENSA / "registro.jsonl"
MEDIOS = DIR_PRENSA / "medios.json"
GENESIS_PREV = "0" * 64
USER_AGENT = "Mozilla/5.0 (auditoria-civica-datos-abiertos; +github.com/5egaloz)"


# --------------------------------------------------------------------------
# El sello del TEXTO, no solo el de los bytes.
#
# Comprobado en la practica sobre medios chilenos: dos descargas seguidas del
# mismo articulo, sin cambio editorial, devuelven bytes distintos (los CDN
# inyectan un identificador de peticion, hay publicidad rotativa y marcas de
# tiempo). Sellar solo los bytes publicaba una huella que ningun tercero puede
# recalcular — justo lo contrario de lo que este proyecto promete.
#
# Entonces se sella ademas el texto visible normalizado con una regla fija y
# publicada, que cualquiera puede repetir:
#   1. se descartan <script>, <style>, <template>, <noscript> y los comentarios;
#   2. se quitan todas las etiquetas;
#   3. se resuelven las entidades HTML;
#   4. se normaliza a Unicode NFC y se colapsa todo espacio en blanco a uno solo.
# El resultado NO se guarda: solo su SHA-256.
# --------------------------------------------------------------------------

NORMALIZACION_TEXTO = ("descartar script/style/template/noscript y comentarios; quitar etiquetas; "
                       "resolver entidades HTML; normalizar a NFC; colapsar espacios en blanco")


def texto_visible(crudo: bytes, content_type: str = "") -> str:
    codificacion = "utf-8"
    m = re.search(r"charset=([\w-]+)", content_type or "", flags=re.IGNORECASE)
    if m:
        codificacion = m.group(1)
    try:
        html = crudo.decode(codificacion, errors="ignore")
    except LookupError:
        html = crudo.decode("utf-8", errors="ignore")
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    html = re.sub(r"<(script|style|template|noscript)\b.*?</\1>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = unescape(html)
    html = unicodedata.normalize("NFC", html)
    return re.sub(r"\s+", " ", html).strip()


def hash_canonico(entrada: dict) -> str:
    """Identico a ingesta.py: el hash de la entrada con sha256_linea vacio.

    Se repite la funcion a proposito en vez de importarla: las dos cadenas deben
    poder verificarse por separado, y un verificador de terceros que solo mire
    prensa/ no deberia necesitar el resto del repo.
    """
    copia = dict(entrada)
    copia["sha256_linea"] = ""
    canonico = json.dumps(copia, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def leer_registro() -> list[dict]:
    if not REGISTRO.exists():
        return []
    with REGISTRO.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def medios_declarados() -> dict:
    if not MEDIOS.exists():
        return {}
    datos = json.loads(MEDIOS.read_text(encoding="utf-8"))
    return {m["medio"]: m for m in datos.get("medios", [])}


def verificar_cadena(entradas: list[dict]) -> tuple[bool, str]:
    """Misma comprobacion que verificar.py sobre el manifiesto principal."""
    prev = GENESIS_PREV
    for i, e in enumerate(entradas):
        if e.get("seq") != i:
            return False, f"seq fuera de orden en la posicion {i}: declara {e.get('seq')}"
        if e.get("sha256_prev") != prev:
            return False, (f"cadena rota en seq {i}: se esperaba {prev[:12]}… "
                           f"y declara {str(e.get('sha256_prev'))[:12]}…")
        propio = hash_canonico(e)
        if propio != e.get("sha256_linea"):
            return False, (f"entrada seq {i} alterada: declara {str(e.get('sha256_linea'))[:12]}… "
                           f"y recalcula {propio[:12]}…")
        prev = e["sha256_linea"]
    return True, f"CADENA DE PRENSA OK ({len(entradas)} entradas)"


def ingerir(url: str, medio: str, titulo: str, fecha: str, tema: str | None,
            forzar: bool) -> int:
    conocidos = medios_declarados()
    if conocidos and medio not in conocidos:
        # La lista de medios es un vector de sesgo declarado: si se pudiera
        # agregar cualquiera al vuelo, el criterio publicado dejaria de describir
        # lo que el sistema realmente lee.
        print(f"ERROR: '{medio}' no esta en prensa/medios.json. Agregalo alli primero, "
              "con su criterio, para que la seleccion quede declarada y versionada.")
        return 1

    # DOS descargas, no una. Comprobado en la practica: latercera.com devolvio
    # TRES sha256 distintos para el mismo articulo sin cambio editorial, porque
    # su CDN (Akamai) inyecta un beacon con timestamp en cada respuesta. Sellar
    # el hash de una sola descarga habria publicado una huella que ningun tercero
    # puede reproducir — es decir, lo contrario de lo que el sitio promete.
    # Si las dos descargas no dan el mismo hash, NO se sella y se dice por que.
    def bajar():
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(), r.status, r.headers.get("Content-Type", ""), r.geturl()

    try:
        cuerpo, estado, tipo, url_final = bajar()
        cuerpo2, _, _, _ = bajar()
    except urllib.error.HTTPError as e:
        print(f"ERROR: la URL respondio {e.code}, no se registra nada.")
        return 1
    except Exception as e:
        print(f"ERROR: descarga fallida, no se registra nada: {type(e).__name__}: {e}")
        return 1
    if not cuerpo:
        print("ERROR: respuesta vacia, no se registra nada.")
        return 1

    sha256 = hashlib.sha256(cuerpo).hexdigest()
    sha256_segunda = hashlib.sha256(cuerpo2).hexdigest()
    bytes_estables = sha256 == sha256_segunda

    # El sello que de verdad ancla la nota: el texto visible normalizado.
    texto = texto_visible(cuerpo, tipo)
    texto2 = texto_visible(cuerpo2, tipo)
    sha256_texto = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    texto_estable = sha256_texto == hashlib.sha256(texto2.encode("utf-8")).hexdigest()

    if not texto_estable and not forzar:
        print("ERROR: ni los bytes ni el texto son reproducibles en este dominio.")
        print(f"  bytes    descarga 1/2: {sha256[:16]}… / {sha256_segunda[:16]}…")
        print(f"  texto    descarga 1/2: {sha256_texto[:16]}… / "
              f"{hashlib.sha256(texto2.encode('utf-8')).hexdigest()[:16]}…")
        print("  Dos descargas seguidas dan texto distinto (contenido rotativo dentro de la")
        print("  pagina). Un sello que nadie puede recalcular no prueba nada, asi que no se")
        print("  registra. Usar --forzar deja constancia del problema en la propia entrada.")
        return 1

    # Un 200 no significa "obtuve la nota": puede ser la pagina del muro de pago.
    # Se cuentan las marcas y se registra el CONTEO, no un veredicto: casi todos
    # los medios traen widgets de suscripcion en notas perfectamente abiertas, y
    # publicar "muro de pago" sobre una nota abierta seria un error de hecho.
    # La senal fuerte es la combinacion: muchas marcas Y un cuerpo demasiado corto.
    bajo = cuerpo.decode("utf-8", errors="ignore").lower()
    marcas_muro = sum(bajo.count(m) for m in ("paywall", "suscríbete", "suscribete",
                                              "contenido exclusivo", "solo para suscriptores"))
    entradas = leer_registro()

    if not forzar:
        for e in entradas:
            if e["sha256"] == sha256:
                print(f"YA REGISTRADO: mismos bytes en seq {e['seq']} ({e['url']}).")
                return 0
        # Misma URL con bytes distintos NO es un duplicado: es una version nueva
        # del articulo, y que haya cambiado es exactamente el hecho que la cadena
        # existe para dejar registrado.
        previas = [e for e in entradas if e["url"] == url]
        if previas:
            print(f"AVISO: la URL ya estaba en seq {previas[-1]['seq']} con otro sha256. "
                  "Se registra como version nueva; el cambio queda en la cadena.")

    prev = entradas[-1]["sha256_linea"] if entradas else GENESIS_PREV
    entrada = {
        "seq": len(entradas),
        "sha256": sha256,
        "sha256_prev": prev,
        "sha256_linea": "",
        "url": url,
        "url_final": url_final,
        "medio": medio,
        "titulo": titulo,
        "fecha_publicacion": fecha,
        "tema": tema or "",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "http_status": estado,
        "content_type": tipo.split(";")[0].strip(),
        "bytes": len(cuerpo),
        "texto_guardado": False,
        # Condiciones de la captura, porque cambian lo que el sello prueba: el
        # ancla real de la nota es sha256_texto (reproducible aunque el CDN
        # inyecte identificadores por peticion); sha256 son los bytes servidos.
        "sha256_texto": sha256_texto,
        "normalizacion_texto": NORMALIZACION_TEXTO,
        "caracteres_texto": len(texto),
        "bytes_reproducibles": bytes_estables,
        "texto_reproducible": texto_estable,
        "sha256_segunda_descarga": sha256_segunda,
        "marcas_de_muro_en_la_pagina": marcas_muro,
        "cuerpo_sospechosamente_corto": len(texto) < 1200,
    }
    entrada["sha256_linea"] = hash_canonico(entrada)

    DIR_PRENSA.mkdir(parents=True, exist_ok=True)
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entrada, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")) + "\n")

    print(f"REGISTRADO seq {entrada['seq']}: {medio} — {titulo}")
    print(f"  sha256: {sha256}")
    print(f"  bytes:  {len(cuerpo)} · http {estado}")
    print(f"  sha256 del texto visible: {sha256_texto}   <- el sello que ancla la nota")
    print(f"  reproducible en dos descargas: texto {'si' if texto_estable else 'NO'} · "
          f"bytes {'si' if bytes_estables else 'NO'}")
    if not bytes_estables:
        print("  (los bytes cambian entre descargas: el CDN inyecta un identificador por")
        print("   peticion. Por eso el ancla es el texto, no los bytes.)")
    print(f"  texto visible: {len(texto)} caracteres · marcas de suscripcion en la pagina: {marcas_muro}")
    if marcas_muro and len(texto) < 1200:
        print("  AVISO: pocas palabras y marcas de suscripcion: puede ser la pagina del muro y no")
        print("  la nota. No conviene extraer afirmaciones de aqui.")
    print("  el texto NO se guardo (obra ajena, repo publico)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", nargs="?", help="URL del articulo")
    p.add_argument("--medio", help="Nombre del medio, tal como figura en prensa/medios.json")
    p.add_argument("--titulo", help="Titulo literal del articulo")
    p.add_argument("--fecha", help="Fecha de publicacion (AAAA-MM-DD)")
    p.add_argument("--tema", help="Etiqueta del caso, ej: mega-reforma")
    p.add_argument("--forzar", action="store_true",
                   help="Registrar aunque los mismos bytes ya esten en la cadena")
    p.add_argument("--verificar", action="store_true", help="Solo validar la cadena de prensa")
    args = p.parse_args()

    if args.verificar:
        entradas = leer_registro()
        if not entradas:
            print("CADENA DE PRENSA VACIA (0 entradas): no hay nada que verificar.")
            return 0
        ok, mensaje = verificar_cadena(entradas)
        print(mensaje)
        return 0 if ok else 1

    faltan = [n for n, v in (("url", args.url), ("--medio", args.medio),
                             ("--titulo", args.titulo), ("--fecha", args.fecha)) if not v]
    if faltan:
        print("ERROR: faltan argumentos: " + ", ".join(faltan))
        return 2
    return ingerir(args.url, args.medio, args.titulo, args.fecha, args.tema, args.forzar)


if __name__ == "__main__":
    sys.exit(main())
