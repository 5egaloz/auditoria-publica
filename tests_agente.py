#!/usr/bin/env python3
"""Tests de las capas deterministas del agente (herramientas.py y filtro.py).

Cubren, ademas de lo funcional, las garantias que el proyecto vende:
  - toda cifra devuelta viaja con cita al manifiesto (seq + hash + URL);
  - una cifra inventada no pasa el filtro;
  - un adjetivo valorativo o un giro de juicio no pasa el filtro;
  - una etiqueta ideologica sin fuente nombrada no pasa el filtro;
  - test de espejo: la misma pregunta con los actores intercambiados produce
    respuestas de estructura identica;
  - test de simetria: los indicadores se calculan sobre el universo completo.

Uso:  python -m unittest tests_agente -v
"""

import json
import unittest

import filtro
import herramientas as h


class TestSobres(unittest.TestCase):
    """Todo sobre tiene la misma forma; sin eso el filtro no puede trabajar."""

    CAMPOS = {"herramienta", "argumentos", "hay_dato", "resultados",
              "derivado", "formula", "n", "cobertura", "mensaje"}

    def test_todas_las_herramientas_devuelven_el_sobre_completo(self):
        muestras = {
            "resumen_corpus": {},
            "serie_balance": {"variable": "balance_efectivo_pct_pib"},
            "comparar_publicaciones": {"variable": "balance_efectivo_pct_pib", "anno": 2026},
            "votacion": {"id": 87507},
            "buscar_votaciones": {"texto": "Acusacion"},
            "serie_ac": {},
            "partido_de": {"parlamentario": "Romero Leiva"},
            "votos_de": {"parlamentario": "Romero Leiva"},
            "coincidencia": {"parlamentario_a": "Romero Leiva",
                             "parlamentario_b": "Barrera Moreno"},
            "cohesion": {},
            "eje_empirico": {},
            "concentracion_camara": {},
            "pivotalidad": {},
            "concentracion_medios": {},
            "concentracion_gasto": {},
        }
        self.assertEqual(set(muestras), set(h.CATALOGO), "el catalogo cambio sin tests")
        for nombre, args in muestras.items():
            with self.subTest(herramienta=nombre):
                sobre = h.invocar(nombre, args)
                self.assertEqual(self.CAMPOS, set(sobre))
                self.assertEqual(sobre["n"], len(sobre["resultados"]))
                self.assertEqual(sobre["hay_dato"], bool(sobre["resultados"]))
                if not sobre["hay_dato"]:
                    self.assertIn(h.SIN_DATO, sobre["mensaje"])

    def test_herramienta_inexistente_no_inventa(self):
        sobre = h.invocar("tendencia_ideologica", {"quien": "todos"})
        self.assertFalse(sobre["hay_dato"])
        self.assertIn(h.SIN_DATO, sobre["mensaje"])

    def test_argumentos_invalidos_no_revientan(self):
        sobre = h.invocar("votacion", {"identificador": 1})
        self.assertFalse(sobre["hay_dato"])
        self.assertIn(h.SIN_DATO, sobre["mensaje"])


class TestCitas(unittest.TestCase):

    def test_toda_cifra_fiscal_viaja_con_cita_al_manifiesto(self):
        sobre = h.serie_balance()
        self.assertTrue(sobre["hay_dato"])
        for r in sobre["resultados"]:
            self.assertIsNotNone(r["cita"]["seq"], r)
            self.assertEqual(64, len(r["cita"]["sha256"]))
            self.assertTrue(r["cita"]["url_fuente"].startswith("http"))

    def test_toda_votacion_ac_viaja_con_cita_al_manifiesto(self):
        for r in h.serie_ac()["resultados"]:
            self.assertIsNotNone(r["cita"]["seq"], r)
            self.assertEqual(64, len(r["cita"]["sha256"]))


class TestFiscal(unittest.TestCase):

    def test_filtra_por_variable_y_anno(self):
        sobre = h.serie_balance(variable="balance_efectivo_pct_pib", anno=2026)
        self.assertTrue(sobre["hay_dato"])
        for r in sobre["resultados"]:
            self.assertEqual("balance_efectivo_pct_pib", r["variable"])
            self.assertEqual(2026, r["anno"])

    def test_variable_inexistente_da_sin_dato(self):
        sobre = h.serie_balance(variable="deuda_bruta_pct_pib")
        self.assertFalse(sobre["hay_dato"])
        self.assertEqual(h.SIN_DATO, sobre["mensaje"])

    def test_comparar_publicaciones_marca_derivado_y_formula(self):
        sobre = h.comparar_publicaciones("balance_efectivo_pct_pib", 2026)
        self.assertTrue(sobre["hay_dato"])
        self.assertTrue(sobre["derivado"])
        self.assertIn("=", sobre["formula"])
        ultimo = sobre["resultados"][-1]
        self.assertEqual(0, ultimo["diferencia_pp_vs_referencia"],
                         "la referencia comparada consigo misma debe dar 0")


class TestLegislativo(unittest.TestCase):

    def test_votacion_ac_trae_voto_nominal(self):
        sobre = h.votacion(87507)
        self.assertTrue(sobre["hay_dato"])
        r = sobre["resultados"][0]
        self.assertTrue(r["tiene_voto_nominal"])
        self.assertEqual(155, len(r["votos_nominales"]))

    def test_votacion_sin_detalle_lo_declara(self):
        sobre = h.votacion(87057)
        self.assertTrue(sobre["hay_dato"])
        self.assertFalse(sobre["resultados"][0]["tiene_voto_nominal"])

    def test_votacion_inexistente_da_sin_dato(self):
        sobre = h.votacion(1)
        self.assertFalse(sobre["hay_dato"])

    def test_buscar_votaciones_respeta_el_limite_y_lo_declara(self):
        sobre = h.buscar_votaciones(limite=5)
        self.assertEqual(5, sobre["n"])
        self.assertIn("coincidencias totales", sobre["mensaje"])

    def test_votos_de_nombre_ambiguo_pide_precision(self):
        sobre = h.votos_de("a")
        self.assertFalse(sobre["hay_dato"])
        self.assertIn("ambiguo", sobre["mensaje"])

    def test_votos_de_desconocido_da_sin_dato(self):
        sobre = h.votos_de("Zzzz")
        self.assertFalse(sobre["hay_dato"])
        self.assertEqual(h.SIN_DATO, sobre["mensaje"])


class TestUniversoYSimetria(unittest.TestCase):

    def test_simetria_todas_las_ac_cubren_el_universo_completo(self):
        """Ningun indicador se calcula sobre un subconjunto de parlamentarios."""
        for r in h.serie_ac()["resultados"]:
            detalle = h.votacion(r["id"])["resultados"][0]
            self.assertEqual(155, len(detalle["votos_nominales"]), r["id"])

    def test_coincidencia_entrega_base_y_formula(self):
        sobre = h.coincidencia("Romero Leiva", "Barrera Moreno")
        self.assertTrue(sobre["hay_dato"], sobre["mensaje"])
        r = sobre["resultados"][0]
        self.assertTrue(sobre["derivado"])
        self.assertIn("=", sobre["formula"])
        self.assertGreater(r["votaciones_comunes"], 0)
        self.assertLessEqual(r["votaciones_iguales"], r["votaciones_comunes"])
        self.assertAlmostEqual(r["coincidencia_pct"],
                               100 * r["votaciones_iguales"] / r["votaciones_comunes"], places=1)

    def test_coincidencia_de_alguien_consigo_mismo_se_rechaza(self):
        sobre = h.coincidencia("Romero Leiva", "Romero Leiva")
        self.assertFalse(sobre["hay_dato"])
        self.assertIn(h.SIN_DATO, sobre["mensaje"])


class TestTendenciaYConcentracion(unittest.TestCase):

    def test_eje_declara_varianza_y_advierte_del_signo(self):
        sobre = h.eje_empirico()
        if not sobre["hay_dato"]:
            self.assertIn(h.SIN_DATO, sobre["mensaje"])
            return
        r = sobre["resultados"][0]
        self.assertGreaterEqual(r["varianza_explicada"], 0.40)
        self.assertIn("arbitrario", r["advertencia"])
        self.assertIn("componente", sobre["formula"])

    def test_eje_no_usa_lenguaje_ideologico(self):
        """El eje describe cercania de voto; nombrarlo izquierda-derecha lo invalida."""
        sobre = h.eje_empirico()
        texto = json.dumps(sobre, ensure_ascii=False).lower()
        for prohibida in ("izquierdista", "derechista", "progresista", "conservador"):
            self.assertNotIn(prohibida, texto)

    def test_cohesion_solo_partidos_con_base_suficiente(self):
        sobre = h.cohesion()
        self.assertTrue(sobre["hay_dato"])
        for r in sobre["resultados"]:
            self.assertGreaterEqual(r["votaciones_consideradas"], 30)
            self.assertGreaterEqual(r["cohesion_rice_promedio"], 0)
            self.assertLessEqual(r["cohesion_rice_promedio"], 1)

    def test_concentracion_publica_las_dos_lecturas(self):
        """Agrupar o separar independientes cambia el numero: van ambas."""
        sobre = h.concentracion_camara()
        self.assertTrue(sobre["hay_dato"])
        r = sobre["resultados"][0]
        bloque = r["lectura_independientes_como_bloque"]
        separado = r["lectura_independientes_por_separado"]
        self.assertEqual(bloque["total"], separado["total"])
        self.assertGreater(bloque["hhi"], separado["hhi"])
        self.assertIn("independientes", r["nota_independientes"].lower())

    def test_pivotalidad_marca_la_fila_no_comparable(self):
        sobre = h.pivotalidad()
        self.assertTrue(sobre["hay_dato"])
        for r in sobre["resultados"]:
            self.assertLessEqual(r["votaciones_en_que_fue_pivote"],
                                 r["votaciones_en_que_participo"])
            if r["partido_id"] == "IND":
                self.assertTrue(r["es_agregacion_no_comparable"])

    def test_medios_siempre_lleva_el_limite_de_la_medicion(self):
        """La cifra de radiodifusion es un piso; sin esa advertencia, engana."""
        sobre = h.concentracion_medios()
        self.assertTrue(sobre["hay_dato"])
        r = sobre["resultados"][0]
        limite = r["limite_de_la_medicion"].lower()
        self.assertIn("titular registrado", limite)
        self.assertIn("piso", limite)
        self.assertNotIn("propiedad de medios", sobre["cobertura"].split("NO incluye")[0])
        detalle = h.concentracion_medios(titular="universidad")
        for fila in detalle["resultados"]:
            self.assertIn("piso", fila["limite_de_la_medicion"].lower())

    def test_medios_cuota_acumulada_es_coherente(self):
        sobre = h.concentracion_medios()
        mayores = sobre["resultados"][0]["mayores_titulares"]
        for anterior, siguiente in zip(mayores, mayores[1:]):
            self.assertGreaterEqual(anterior["concesiones"], siguiente["concesiones"])
            self.assertGreater(siguiente["cuota_acumulada"], anterior["cuota_acumulada"])

    def test_gasto_publica_sensibilidad_y_advertencia(self):
        """Los indices estan dominados por pocas lineas; sin sensibilidad, enganan."""
        sobre = h.concentracion_gasto()
        self.assertTrue(sobre["hay_dato"])
        r = sobre["resultados"][0]
        self.assertIn("no deben citarse solos",
                      r["advertencia_valores_atipicos"].replace("NO", "no"))
        self.assertGreaterEqual(len(r["sensibilidad"]), 2)
        declarado = r["indices_declarados"]["hhi"]
        recortes = [v["hhi"] for v in r["sensibilidad"].values()]
        self.assertTrue(any(x < declarado for x in recortes),
                        "excluir lineas atipicas debe bajar la concentracion medida")
        for linea in r["mayores_lineas"]:
            self.assertTrue(linea["enlace_fuente"].startswith("https://"))
            self.assertTrue(linea["codigo_externo"])

    def test_gasto_no_convierte_monedas(self):
        """Convertir exige un tipo de cambio que no esta en la fuente."""
        sobre = h.concentracion_gasto()
        limite = sobre["resultados"][0]["limite_de_la_medicion"].lower()
        self.assertIn("no se convierten", limite)
        self.assertIn("licitaciones", limite)

    def test_resumen_corpus_refleja_el_estado_real(self):
        """Si el inventario miente, el agente respondera 'sin dato' teniendo dato."""
        r = h.resumen_corpus()["resultados"][0]
        self.assertEqual(len(h._NOMINAL["registros"]), r["votaciones_con_voto_nominal"])
        self.assertTrue(r["hay_partido_o_bancada"])
        self.assertGreater(r["parlamentarios_en_el_padron"], 0)
        self.assertGreater(r["concesiones_de_radiodifusion"], 0)
        self.assertGreater(r["lineas_de_adjudicacion"], 0)

    def test_indicadores_agregados_citan_la_huella_del_conjunto(self):
        """Sin seq unico, el ancla es el sha256 del conjunto de artefactos."""
        for sobre in (h.cohesion(), h.pivotalidad(), h.concentracion_camara()):
            with self.subTest(herramienta=sobre["herramienta"]):
                cita = sobre["resultados"][0]["cita"]
                self.assertEqual("conjunto_de_artefactos", cita["tipo"])
                self.assertEqual(64, len(cita["sha256"]))
                self.assertGreater(cita["artefactos"], 0)


def _respuesta_valida() -> tuple[str, dict]:
    """Una respuesta bien construida sobre datos reales del corpus."""
    sobre = h.serie_balance(variable="balance_efectivo_pct_pib",
                            publicacion="IFP 1T2026", anno=2026)
    r = sobre["resultados"][0]
    texto = (f"Balance efectivo proyectado para {r['anno']}: {r['valor']:.2f} "
             f"{r['unidad']}, segun {r['publicacion']} "
             f"(seq {r['cita']['seq']}, hash {r['cita']['sha256'][:12]}).")
    return texto, sobre


class TestFiltro(unittest.TestCase):

    def test_aprueba_una_respuesta_bien_construida(self):
        texto, sobre = _respuesta_valida()
        informe = filtro.revisar(texto, sobre)
        self.assertTrue(informe["aprobado"], informe["motivos"])

    def test_acepta_decimales_con_coma_chilena(self):
        sobre = h.serie_balance(variable="balance_efectivo_pct_pib",
                                publicacion="IFP 1T2026", anno=2026)
        r = sobre["resultados"][0]
        con_coma = f"{r['valor']:.2f}".replace(".", ",")
        texto = (f"Balance efectivo {r['anno']}: {con_coma} % del PIB "
                 f"(seq {r['cita']['seq']}, hash {r['cita']['sha256'][:12]}).")
        informe = filtro.revisar(texto, sobre)
        self.assertTrue(informe["aprobado"], informe["motivos"])

    def test_rechaza_cifra_inventada(self):
        texto, sobre = _respuesta_valida()
        informe = filtro.revisar(texto + " La deuda bruta llego a 47,3 % del PIB.", sobre)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("sin respaldo" in m for m in informe["motivos"]))

    def test_rechaza_monto_largo_inventado(self):
        """Una corrida larga de digitos es cifra, no hash."""
        texto, sobre = _respuesta_valida()
        informe = filtro.revisar(texto + " El gasto fue de 12345678 pesos.", sobre)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("12345678" in m for m in informe["motivos"]))

    def test_cifra_sin_signo_pasa_pero_queda_advertida(self):
        """Un deficit escrito en positivo se acepta y se anota para revision."""
        sobre = h.serie_balance(variable="balance_efectivo_pct_pib",
                                publicacion="IFP 1T2026", anno=2025)
        r = sobre["resultados"][0]
        self.assertLess(r["valor"], 0, "el caso exige una cifra negativa")
        sin_signo = f"{abs(r['valor']):.2f}".replace(".", ",")
        texto = (f"Deficit de {sin_signo} % del PIB segun {r['publicacion']} "
                 f"(seq {r['cita']['seq']}, hash {r['cita']['sha256'][:12]}).")
        informe = filtro.revisar(texto, sobre)
        self.assertTrue(informe["aprobado"], informe["motivos"])
        self.assertTrue(any("signo" in a for a in informe["advertencias"]),
                        informe["advertencias"])

    def test_rechaza_adjetivo_valorativo(self):
        texto, sobre = _respuesta_valida()
        informe = filtro.revisar(texto + " La cifra es preocupante.", sobre)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("valorativo" in m for m in informe["motivos"]))

    def test_rechaza_giro_de_juicio(self):
        texto, sobre = _respuesta_valida()
        informe = filtro.revisar(texto + " Queda demostrado que el gobierno miente.", sobre)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("juicio" in m for m in informe["motivos"]))

    def test_rechaza_etiqueta_ideologica_sin_fuente(self):
        texto, sobre = _respuesta_valida()
        informe = filtro.revisar(texto + " El diputado es de derecha.", sobre)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("etiqueta ideologica" in m for m in informe["motivos"]))

    def test_acepta_etiqueta_ideologica_con_fuente_nombrada(self):
        texto, sobre = _respuesta_valida()
        r = sobre["resultados"][0]
        atribuida = (f" Clasificacion de derecha segun el pacto electoral registrado "
                     f"(seq {r['cita']['seq']}, hash {r['cita']['sha256'][:12]}).")
        informe = filtro.revisar(texto + atribuida, sobre)
        self.assertTrue(informe["aprobado"], informe["motivos"])

    def test_rechaza_falta_de_cita(self):
        sobre = h.serie_balance(variable="balance_efectivo_pct_pib",
                                publicacion="IFP 1T2026", anno=2026)
        r = sobre["resultados"][0]
        informe = filtro.revisar(f"Balance efectivo {r['anno']}: {r['valor']:.2f} % del PIB.", sobre)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("cita" in m or "hash" in m for m in informe["motivos"]))

    def test_sin_dato_exige_decirlo_y_no_dar_cifras(self):
        sobre = h.serie_balance(variable="deuda_bruta_pct_pib")
        malo = filtro.revisar("La deuda bruta fue de 41,2 % del PIB.", sobre)
        self.assertFalse(malo["aprobado"])
        bueno = filtro.revisar(
            "Sin dato disponible: la deuda bruta no esta en el corpus de este sistema.", sobre)
        self.assertTrue(bueno["aprobado"], bueno["motivos"])

    def test_cita_literal_exenta_y_declarada(self):
        """Modulo D: la afirmacion que se contrasta va entre comillas."""
        texto, sobre = _respuesta_valida()
        contraste = texto + ' La afirmacion consultada indica "un deficit de 9,9 % del PIB".'
        informe = filtro.revisar(contraste, sobre)
        self.assertTrue(informe["aprobado"], informe["motivos"])
        self.assertIn("9,9", informe["cifras_citadas"])

    def test_aprueba_indicador_agregado_anclado_en_la_huella(self):
        """Un derivado de cientos de artefactos se ancla en el hash del conjunto."""
        sobre = h.pivotalidad()
        r = sobre["resultados"][0]
        texto = (f"{r['partido_nombre']} fue pivote en {r['votaciones_en_que_fue_pivote']} "
                 f"de {r['votaciones_en_que_participo']} votaciones de quorum simple "
                 f"(conjunto de artefactos {r['cita']['sha256'][:12]}).")
        informe = filtro.revisar(texto, sobre)
        self.assertTrue(informe["aprobado"], informe["motivos"])

    def test_rechaza_indicador_agregado_sin_ancla(self):
        sobre = h.pivotalidad()
        r = sobre["resultados"][0]
        informe = filtro.revisar(
            f"{r['partido_nombre']} fue pivote en {r['votaciones_en_que_fue_pivote']} "
            f"votaciones.", sobre)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("hash" in m for m in informe["motivos"]))

    def test_espejo_misma_estructura_al_intercambiar_actores(self):
        """La respuesta no puede cambiar de tono segun quien sea el actor."""
        sobre = h.serie_ac()
        base = sobre["resultados"][0]
        cita = f"(seq {base['cita']['seq']}, hash {base['cita']['sha256'][:12]})"
        plantilla = ("En la votacion {vid} el resultado registrado es {res}: "
                     "{si} a favor, {no} en contra. " + cita)
        a = plantilla.format(vid=base["id"], res=base["resultado"],
                             si=base["total_si"], no=base["total_no"])
        b = plantilla.format(vid=base["id"], res=base["resultado"],
                             si=base["total_no"], no=base["total_si"])
        ia, ib = filtro.revisar(a, sobre), filtro.revisar(b, sobre)
        self.assertTrue(ia["aprobado"], ia["motivos"])
        self.assertTrue(ib["aprobado"], ib["motivos"])
        self.assertEqual(ia["motivos"], ib["motivos"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
