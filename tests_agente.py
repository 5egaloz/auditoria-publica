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
from pathlib import Path

import analisis_ia
import filtro
import herramientas as h
import relevancia
import retorica

RAIZ = Path(__file__).resolve().parent


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
            "votaciones_de_proyecto": {"boletin": "18216-05"},
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
        # votaciones_de_proyecto solo responde por proyectos INGERIDOS: pedir un
        # boletin que no esta no puede devolver resultados de otro proyecto.
        vacio = h.invocar("votaciones_de_proyecto", {"boletin": "00000-00"})
        self.assertFalse(vacio["hay_dato"])
        self.assertEqual(vacio["resultados"], [])
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


class TestRetorica(unittest.TestCase):
    """La capa que mide FORMA del texto. Lo que se vigila aca no es que cuente
    bien, sino que no se pueda usar como marcador ideologico."""

    @classmethod
    def setUpClass(cls):
        cls.lex = retorica.cargar_lexico()

    def _ocurrencias(self, texto):
        return retorica.medir(texto, self.lex)["indicadores"]["densidad_valorativa"]["ocurrencias"]

    def test_la_lista_valorativa_es_simetrica(self):
        """Si un par opuesto pesara distinto, el indicador castigaria a un lado."""
        for a, b in (("exito", "fracaso"), ("responsable", "irresponsable"),
                     ("solido", "debil"), ("logro", "desastre"),
                     ("avance", "retroceso"), ("triunfo", "derrota")):
            with self.subTest(par=(a, b)):
                self.assertEqual(self._ocurrencias(f"Fue un {a} para el sector."),
                                 self._ocurrencias(f"Fue un {b} para el sector."))

    def test_el_resultado_no_depende_del_actor(self):
        """Test de espejo: cambiar quien protagoniza no puede mover un indicador."""
        plantilla = "{actor} asegura que la medida permitira crear empleo en la region."
        valores = set()
        for actor in ("El Gobierno", "La oposicion", "El Partido Comunista",
                      "El Partido Republicano", "La Contraloria"):
            r = retorica.medir(plantilla.format(actor=actor), self.lex)
            valores.add(json.dumps({k: v["valor"] for k, v in r["indicadores"].items()},
                                   sort_keys=True))
        self.assertEqual(1, len(valores), "un indicador cambio al cambiar el actor")

    def test_ningun_indicador_nombra_una_ideologia(self):
        """El sistema mide mecanismo; nombrar la etiqueta seria el juicio que no emite.

        Se revisa lo que el sistema AFIRMA —nombres de indicador, unidades y los
        casos medidos—, no los descargos: 'no dice que quien habla sea populista'
        contiene la palabra justamente para negarla, y borrarla de ahi debilitaria
        el descargo en vez de reforzar la regla.
        """
        prohibidas = ("populis", "demagog", "ideolog", "izquierda", "derecha",
                      "progresista", "conservador")
        r = retorica.medir("La medida permitira crear empleo. Es por la gente.", self.lex)
        afirmado = json.dumps(
            {"nombres": sorted(r["indicadores"]),
             "unidades": [i["unidad"] for i in r["indicadores"].values()],
             "casos": r["casos"]}, ensure_ascii=False).lower()
        for p in prohibidas:
            with self.subTest(termino=p):
                self.assertNotIn(p, afirmado)

    def test_los_descargos_solo_nombran_la_etiqueta_para_negarla(self):
        """Si un descargo la afirmara, el indicador seria el clasificador que no es."""
        for i in retorica.medir("Es por la gente.", self.lex)["indicadores"].values():
            with self.subTest(indicador=i["que_cuenta"][:40]):
                self.assertNotIn("populis", i["que_cuenta"].lower())
                if "populis" in i["que_no_cuenta"].lower():
                    self.assertIn("no dice", i["que_no_cuenta"].lower())

    def test_cada_indicador_publica_su_descargo(self):
        """Un numero sin 'que NO cuenta' al lado se lee como una acusacion."""
        r = retorica.medir("Segun Hacienda, son 45 obras. La medida permitira crecer.", self.lex)
        for nombre, i in r["indicadores"].items():
            with self.subTest(indicador=nombre):
                self.assertTrue(i["que_cuenta"].strip())
                self.assertTrue(i["que_no_cuenta"].strip())

    def test_el_recorte_del_cuerpo_excluye_el_menu(self):
        """Sin esto, el titular de otra nota entra al conteo de esta."""
        pagina = "Inicio Politica Deportes CUERPO Ingreso a tramite el lunes. FIN Un fracaso historico"
        cuerpo, info = retorica.recortar_cuerpo(pagina, {"inicio": "CUERPO", "fin": "FIN"})
        self.assertTrue(info["apto_para_publicar"])
        self.assertEqual(0, self._ocurrencias(cuerpo))

    def test_sin_anclas_la_medicion_no_es_publicable(self):
        _, info = retorica.recortar_cuerpo("cualquier texto", None)
        self.assertFalse(info["apto_para_publicar"])
        self.assertEqual("pagina_completa", info["alcance"])

    def test_un_ancla_ausente_aborta(self):
        """Si la pagina cambio, se falla; no se recorta a medias en silencio."""
        with self.assertRaises(ValueError):
            retorica.recortar_cuerpo("hola mundo", {"inicio": "NO ESTA", "fin": "FIN"})

    def test_las_dos_capas_recortan_igual(self):
        """Denominadores distintos para la misma nota serian un dato falso.

        extraer_prensa.py importa el recorte de retorica.py justamente por esto:
        cuando cada capa tenia el suyo, una contaba 17 afirmaciones sobre la
        pagina completa y la otra 16 sobre el cuerpo.
        """
        import extraer_prensa
        self.assertIs(extraer_prensa.recortar_cuerpo, retorica.recortar_cuerpo)

    def test_el_lexico_viaja_con_su_hash(self):
        """Cambiar una lista cambia los numeros: sin la version, no significan nada."""
        self.assertEqual(64, len(self.lex.sha256))
        otro = retorica.cargar_lexico()
        self.assertEqual(self.lex.sha256, otro.sha256)


class TestAnalisisIA(unittest.TestCase):
    """La capa NO sellada. Se vigila que no pueda colarse como si fuera dato."""

    def _base(self):
        return ("## Lo que se puede comprobar hoy\n" + "palabra " * 90 +
                "\n## Lo que no queda contra qué comprobar\n" + "palabra " * 90 +
                "\n## Posibles soluciones\n" + "palabra " * 90 +
                "\n## Lo que este análisis no pudo evaluar\n" + "palabra " * 40 +
                "\n\n" + analisis_ia.CIERRE)

    def _material(self):
        return ({"indicadores": {"x": {"valor": 4}}},
                {"afirmaciones": [{"cita_manifiesto": {"seq": 3, "sha256": "ab" * 32}}]})

    def _con_cita(self, texto):
        return texto.replace("palabra palabra", f" seq 3 hash {'ab' * 32} ", 1)

    def test_rechaza_una_cifra_que_no_esta_en_el_material(self):
        ret, afi = self._material()
        informe = analisis_ia.revisar(
            self._con_cita(self._base()).replace("palabra palabra", "917 casos", 1), ret, afi)
        self.assertFalse(informe["aprobado"])
        self.assertTrue(any("sin respaldo" in m for m in informe["motivos"]))

    def test_rechaza_la_etiqueta_ideologica(self):
        ret, afi = self._material()
        for etiqueta in ("es demagogia pura", "un discurso populista", "puro populismo"):
            with self.subTest(etiqueta=etiqueta):
                informe = analisis_ia.revisar(
                    self._con_cita(self._base()).replace("palabra palabra", etiqueta, 1), ret, afi)
                self.assertFalse(informe["aprobado"])

    def test_exige_las_cuatro_secciones_y_el_cierre(self):
        base = self._con_cita(self._base())
        self.assertFalse(analisis_ia.revisar_estructura(base))
        self.assertTrue(analisis_ia.revisar_estructura(base.replace(analisis_ia.CIERRE, "")))
        for seccion in analisis_ia.SECCIONES:
            with self.subTest(seccion=seccion):
                self.assertTrue(analisis_ia.revisar_estructura(base.replace(seccion, "## Otra")))

    def test_los_analisis_publicados_pasan_su_propio_filtro(self):
        """Lo que esta en data/derived tiene que seguir cumpliendo hoy."""
        carpeta = RAIZ / "data" / "derived" / "prensa" / "analisis"
        if not carpeta.is_dir() or not any(carpeta.glob("*.json")):
            self.skipTest("todavia no hay analisis sellados")
        for ruta in sorted(carpeta.glob("*.json")):
            with self.subTest(archivo=ruta.name):
                d = json.loads(ruta.read_text(encoding="utf-8"))
                # Se publica marcado como lo que es, en tres campos distintos:
                # que un lector confunda esto con un dato seria un fallo del sistema.
                self.assertFalse(d["sellado"])
                self.assertTrue(d["derivado_no_determinista"])
                self.assertFalse(d["funda_algun_veredicto"])
                ret, afi = analisis_ia.material(d["articulo"]["sha256"])
                informe = analisis_ia.revisar(d["texto"], ret, afi)
                self.assertTrue(informe["aprobado"], informe["motivos"])

    def test_el_prompt_publicado_calza_con_su_hash(self):
        """Si el prompt pudiera cambiar en silencio, el sello no probaria nada."""
        hashes = json.loads((RAIZ / "prompts" / "hashes.json").read_text(encoding="utf-8"))
        registro = {r["archivo"]: r["sha256"] for r in hashes["registros"]}
        ruta = "prompts/analisis-prensa.md"
        self.assertIn(ruta, registro)
        self.assertEqual(registro[ruta], analisis_ia.sha256_de(RAIZ / ruta))


class TestRelevancia(unittest.TestCase):
    """La seleccion de noticias: el mayor vector de sesgo del modulo."""

    @classmethod
    def setUpClass(cls):
        cls.criterio = json.loads(
            (RAIZ / "prensa" / "relevancia.json").read_text(encoding="utf-8"))

    def _item(self, medio, titulo, fecha="2026-07-31T10:00:00+00:00"):
        return {"medio": medio, "titulo": titulo, "url": f"https://x/{medio}", "fecha": fecha}

    def test_un_solo_medio_no_alcanza_el_umbral(self):
        r = relevancia.seleccionar(
            [self._item("A", "Senado aplaza la votacion de la reforma tributaria")], self.criterio)
        self.assertEqual(0, r["hechos_seleccionados"])
        self.assertEqual(1, r["hechos_bajo_el_umbral"])

    def test_el_criterio_no_depende_del_actor(self):
        """Test de espejo: la seleccion no puede favorecer a un sector."""
        for actor in ("el Gobierno", "la oposicion", "el Partido Comunista",
                      "el Partido Republicano"):
            with self.subTest(actor=actor):
                r = relevancia.seleccionar([
                    self._item("A", f"Senado aplaza la votacion tras el informe de {actor}"),
                    self._item("B", f"Aplazan en el Senado la votacion tras el informe de {actor}"),
                ], self.criterio)
                self.assertEqual(1, r["hechos_seleccionados"])

    def test_es_determinista_ante_el_orden_de_llegada(self):
        """Un resultado que depende de que servidor respondio antes no lo reproduce nadie."""
        lote = [self._item("A", "Senado aplaza la votacion de la reforma tributaria"),
                self._item("B", "El Senado aplaza votacion de la reforma tributaria hoy"),
                self._item("C", "Contraloria abre sumario por contratos del ministerio")]
        uno = json.dumps(relevancia.seleccionar(lote, self.criterio), sort_keys=True)
        otro = json.dumps(relevancia.seleccionar(list(reversed(lote)), self.criterio),
                          sort_keys=True)
        self.assertEqual(uno, otro)

    def test_el_termino_calza_como_palabra_y_no_como_prefijo(self):
        """'ley' dentro de 'leyenda' metia deportes al corpus como legislacion."""
        terminos = self.criterio["alcance_politico"]["terminos"]
        self.assertFalse(relevancia.es_politico("Murio Baresi, leyenda del AC Milan", terminos))
        self.assertIn("ley", relevancia.es_politico("Promulgan la ley de presupuestos", terminos))

    def test_declara_siempre_cuanto_quedo_fuera(self):
        """Un recorte silencioso se lee como 'aca esta todo'."""
        r = relevancia.seleccionar([
            self._item("A", "Senado aplaza la votacion de la reforma tributaria"),
            self._item("B", "Colo Colo gana el clasico del futbol chileno"),
        ], self.criterio)
        for campo in ("items_leidos", "descartados_por_alcance",
                      "hechos_formados", "hechos_bajo_el_umbral"):
            self.assertIn(campo, r)
        self.assertEqual(2, r["items_leidos"])
        self.assertEqual(1, r["descartados_por_alcance"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
