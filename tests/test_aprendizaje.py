"""
Tests de core/aprendizaje.py (punto D): carga/guardado del fichero JSON,
registro de correcciones, conflictos, borrado y exportación a VARIANTS.

Todos los tests redirigen `_directorio_datos()` a un `tmp_path` de pytest, así
que nunca tocan el `correccions_apreses.json` real del proyecto.
"""

import json

import pytest

from core import aprendizaje
from core.aprendizaje import ResultadoRegistro


@pytest.fixture(autouse=True)
def directorio_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(aprendizaje, "_directorio_datos", lambda: str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# G.11 — arranque con el fichero ausente o corrupto
# --------------------------------------------------------------------------- #

def test_g11_fichero_ausente_devuelve_vacio():
    assert aprendizaje.cargar() == {}


def test_g11_fichero_corrupto_no_impide_el_arranque(directorio_temporal):
    ruta = directorio_temporal / aprendizaje.NOMBRE_FICHERO
    ruta.write_text("esto no es json {{{", encoding="utf-8")
    assert aprendizaje.cargar() == {}


def test_g11_fichero_con_formato_inesperado_no_impide_el_arranque(directorio_temporal):
    ruta = directorio_temporal / aprendizaje.NOMBRE_FICHERO
    ruta.write_text(json.dumps({"no": "es una lista"}), encoding="utf-8")
    assert aprendizaje.cargar() == {}


def test_g11_entrada_incompleta_se_ignora_sin_romper_las_demas(directorio_temporal):
    ruta = directorio_temporal / aprendizaje.NOMBRE_FICHERO
    bruto = [
        {"clave": "alisebet", "correccion": "Elisabet", "vocabulario": "noms", "veces": 1, "ultima_confirmacion": "2026-01-01"},
        {"clave": "sin_correccion", "vocabulario": "noms"},  # falta "correccion": se ignora
    ]
    ruta.write_text(json.dumps(bruto), encoding="utf-8")
    entradas = aprendizaje.cargar()
    assert len(entradas) == 1
    assert ("noms", "alisebet") in entradas


# --------------------------------------------------------------------------- #
# Carga/guardado normal
# --------------------------------------------------------------------------- #

def test_guardar_y_cargar_ciclo_completo(directorio_temporal):
    entradas, _ = aprendizaje.registrar_correccion({}, "Alisebet", "Elisabet", "noms")
    aprendizaje.guardar(entradas)

    releidas = aprendizaje.cargar()
    assert len(releidas) == 1
    entrada = releidas[("noms", "alisebet")]
    assert entrada.correccion == "Elisabet"
    assert entrada.forma_erronea == "Alisebet"
    assert entrada.veces == 1


def test_guardar_crea_el_fichero_si_no_existia(directorio_temporal):
    ruta = directorio_temporal / aprendizaje.NOMBRE_FICHERO
    assert not ruta.exists()
    aprendizaje.guardar({})
    assert ruta.exists()


# --------------------------------------------------------------------------- #
# D.6 — registro, repetición y conflicto
# --------------------------------------------------------------------------- #

def test_registrar_correccion_nueva():
    entradas, resultado = aprendizaje.registrar_correccion({}, "Alisebet", "Elisabet", "noms")
    assert resultado is ResultadoRegistro.NUEVA
    assert entradas[("noms", "alisebet")].veces == 1


def test_registrar_correccion_repetida_incrementa_contador():
    entradas, _ = aprendizaje.registrar_correccion({}, "Alisebet", "Elisabet", "noms")
    entradas, resultado = aprendizaje.registrar_correccion(entradas, "Alisebet", "Elisabet", "noms")
    assert resultado is ResultadoRegistro.REPETIDA
    assert entradas[("noms", "alisebet")].veces == 2


def test_registrar_correccion_con_destino_distinto_es_cambiada():
    entradas, _ = aprendizaje.registrar_correccion({}, "Alisebet", "Elisabet", "noms")
    entradas, resultado = aprendizaje.registrar_correccion(entradas, "Alisebet", "Elisabeth", "noms")
    assert resultado is ResultadoRegistro.CAMBIADA
    assert entradas[("noms", "alisebet")].correccion == "Elisabeth"
    assert entradas[("noms", "alisebet")].veces == 2


def test_registrar_correccion_no_muta_el_diccionario_original():
    original = {}
    aprendizaje.registrar_correccion(original, "Alisebet", "Elisabet", "noms")
    assert original == {}


def test_vocabularios_distintos_no_colisionan():
    entradas, _ = aprendizaje.registrar_correccion({}, "Bennassar", "Bennàsser", "llinatges")
    entradas, _ = aprendizaje.registrar_correccion(entradas, "Bennassar", "OtraCosa", "noms")
    assert entradas[("llinatges", "bennassar")].correccion == "Bennàsser"
    assert entradas[("noms", "bennassar")].correccion == "OtraCosa"


# --------------------------------------------------------------------------- #
# D.8 — borrado
# --------------------------------------------------------------------------- #

def test_eliminar_borra_la_entrada():
    entradas, _ = aprendizaje.registrar_correccion({}, "Alisebet", "Elisabet", "noms")
    entradas = aprendizaje.eliminar(entradas, "Alisebet", "noms")
    assert entradas == {}


def test_eliminar_entrada_inexistente_no_falla():
    assert aprendizaje.eliminar({}, "NoExiste", "noms") == {}


# --------------------------------------------------------------------------- #
# D.9 — exportación a VARIANTS
# --------------------------------------------------------------------------- #

def test_exportar_a_variants_formato_tupla():
    entradas, _ = aprendizaje.registrar_correccion({}, "Alisebet", "Elisabet", "noms")
    entradas, _ = aprendizaje.registrar_correccion(entradas, "Bennassar", "Bennàsser", "llinatges")
    exportado = aprendizaje.exportar_a_variants(entradas)
    assert set(exportado) == {("Alisebet", "Elisabet"), ("Bennassar", "Bennàsser")}


def test_exportar_a_variants_xlsx_escribe_fichero_legible(directorio_temporal):
    import pandas as pd

    entradas, _ = aprendizaje.registrar_correccion({}, "Alisebet", "Elisabet", "noms")
    destino = directorio_temporal / "variants_apreses.xlsx"

    n = aprendizaje.exportar_a_variants_xlsx(entradas, str(destino))

    assert n == 1
    assert destino.exists()
    df = pd.read_excel(str(destino))
    assert df.iloc[0]["Variant"] == "Alisebet"
    assert df.iloc[0]["Correcció"] == "Elisabet"
