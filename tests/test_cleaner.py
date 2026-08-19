"""
Tests de la lógica pura. No necesitan Excel ni interfaz gráfica.

Ejecutar desde la raíz del proyecto:
    pytest -v
"""

import pandas as pd
import pytest

from core.cleaner import (
    Correccion,
    DecisionFila,
    aplicar_correcciones,
    corregir_texto,
    detectar_errores,
    es_marca_ilegible,
    es_variante_genero,
    extraer_palabras,
    extraer_palabras_llinatge,
    limpiar_celda,
    limpiar_dataframe,
    preparar_aceptacion,
    primer_nom,
    truncar_columna_nom,
)


# --------------------------------------------------------------------------- #
# es_variante_genero
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "palabra1, palabra2",
    [
        ("Miquel", "Miquela"),    # letra final femenina añadida
        ("Miquela", "Miquel"),    # simétrico
        ("Mariana", "Mariano"),   # a/o
        ("Raimunda", "Raimundo"),
        ("Catalina", "Catalino"),
        ("Antoni", "Antonia"),
        ("Antoni", "Antònia"),    # insensible a los acentos
        ("MIQUEL", "miquela"),    # insensible a mayúsculas
    ],
)
def test_variantes_de_genero_no_son_errores(palabra1, palabra2):
    assert es_variante_genero(palabra1, palabra2) is True


@pytest.mark.parametrize(
    "palabra1, palabra2",
    [
        ("Miquell", "Miquel"),    # consonante doblada: errata real
        ("Miquel", "Miquell"),
        ("Joan", "Joam"),         # letra final cambiada, no marca género
        ("Pons", "Ponts"),        # letra intercalada
        ("Rosselló", "Rossello"),  # tilde ausente: errata, no género
        ("Miquel", "Miquel"),     # idénticas: no son variantes
        ("Joan", "Joanet"),       # diferencia de más de una letra
        ("", "Miquel"),           # entrada vacía
    ],
)
def test_erratas_reales_no_se_confunden_con_genero(palabra1, palabra2):
    assert es_variante_genero(palabra1, palabra2) is False


# --------------------------------------------------------------------------- #
# limpiar_celda
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("Joan    Miquel", "Joan Miquel"),        # espacios múltiples
        ("  Pons  ", "Pons"),                     # espacios en los extremos
        ("'Ferrer", "Ferrer"),                    # apóstrofo inicial de transcripción
        (".Mas,", "Mas"),                         # puntuación en los extremos
        ("Joan\tMiquel\nPons", "Joan Miquel Pons"),  # tabuladores y saltos de línea
        ("Rosselló .", "Rosselló"),               # espacio antes de punto
        ("Bennàssar", "Bennàssar"),               # acentos intactos
    ],
)
def test_limpiar_celda_normaliza_texto(entrada, esperado):
    assert limpiar_celda(entrada) == esperado


def test_limpiar_celda_respeta_los_valores_no_textuales():
    assert limpiar_celda(1789) == 1789
    assert limpiar_celda(None) is None
    assert pd.isna(limpiar_celda(float("nan")))


def test_limpiar_dataframe_no_muta_el_original():
    df = pd.DataFrame({"Nom": ["  Joan   Miquel ", "'Antònia"], "Any": [1789, 1790]})
    limpio = limpiar_dataframe(df)

    assert limpio["Nom"].tolist() == ["Joan Miquel", "Antònia"]
    assert df["Nom"].tolist() == ["  Joan   Miquel ", "'Antònia"]  # intacto
    assert limpio["Any"].tolist() == [1789, 1790]                  # numérico sin tocar


# --------------------------------------------------------------------------- #
# corregir_texto  (el bug de los nombres compuestos)
# --------------------------------------------------------------------------- #

def test_corrige_dentro_de_un_nombre_compuesto():
    """Este es el caso que DataFrame.replace() se dejaba sin corregir."""
    assert corregir_texto("Joan Miquell Pons", "Miquell", "Miquel") == "Joan Miquel Pons"


def test_corrige_la_palabra_tambien_cuando_va_sola():
    assert corregir_texto("Miquell", "Miquell", "Miquel") == "Miquel"


def test_no_corrige_dentro_de_otra_palabra():
    """Los límites de palabra evitan que 'Ana' destroce 'Anastasia'."""
    assert corregir_texto("Anastasia", "Ana", "Anna") == "Anastasia"
    assert corregir_texto("Ana Maria", "Ana", "Anna") == "Anna Maria"


def test_corrige_todas_las_apariciones_de_la_celda():
    assert corregir_texto("Miquell Miquell", "Miquell", "Miquel") == "Miquel Miquel"


# --------------------------------------------------------------------------- #
# detectar_errores
# --------------------------------------------------------------------------- #

def test_detecta_la_forma_minoritaria_como_error():
    palabras = ["Bennassar"] * 5 + ["Benassar"]
    sugerencias = detectar_errores(palabras, columnas=["Llinatge 1"])

    assert len(sugerencias) == 1
    assert sugerencias[0].error == "Benassar"
    assert sugerencias[0].correccion == "Bennassar"
    assert sugerencias[0].frecuencia == 1
    assert sugerencias[0].columnas == ("Llinatge 1",)


def test_no_propone_corregir_variantes_de_genero():
    palabras = ["Miquel"] * 8 + ["Miquela"] * 2
    assert detectar_errores(palabras) == []


def test_ignora_palabras_demasiado_cortas():
    palabras = ["de"] * 10 + ["da"]
    assert detectar_errores(palabras) == []


# --------------------------------------------------------------------------- #
# aplicar_correcciones  (alcance por columna)
# --------------------------------------------------------------------------- #

def test_la_correccion_solo_toca_su_columna():
    """
    Un apellido mal escrito no debe modificar la columna de nombres, aunque
    la misma cadena aparezca en las dos.
    """
    df = pd.DataFrame(
        {
            "Llinatge 1": ["Miquell", "Pons"],
            "Nom": ["Miquell", "Joan Miquell"],
        }
    )
    correccion = Correccion("Miquell", "Miquel", ("Llinatge 1",))

    resultado, celdas = aplicar_correcciones(df, [correccion])

    assert resultado["Llinatge 1"].tolist() == ["Miquel", "Pons"]
    assert resultado["Nom"].tolist() == ["Miquell", "Joan Miquell"]  # sin tocar
    assert celdas == 1


def test_aplicar_correcciones_alcanza_nombres_compuestos():
    df = pd.DataFrame({"Nom": ["Joan Miquell Pons", "Miquell", "Antònia"]})
    correccion = Correccion("Miquell", "Miquel", ("Nom",))

    resultado, celdas = aplicar_correcciones(df, [correccion])

    assert resultado["Nom"].tolist() == ["Joan Miquel Pons", "Miquel", "Antònia"]
    assert celdas == 2


def test_aplicar_correcciones_no_muta_el_original():
    df = pd.DataFrame({"Nom": ["Joan Miquell"]})
    aplicar_correcciones(df, [Correccion("Miquell", "Miquel", ("Nom",))])
    assert df["Nom"].tolist() == ["Joan Miquell"]


# --------------------------------------------------------------------------- #
# Punto B — primer_nom() / truncar_columna_nom()
# --------------------------------------------------------------------------- #

def test_g4_conserva_solo_el_primer_nombre():
    assert primer_nom("Joan Antoni") == "Joan"
    assert primer_nom("Miquel Antoni Josep") == "Miquel"


def test_g5_descarta_particulas_iniciales_antes_del_primer_nombre():
    assert primer_nom("Maria de los Dolores") == "Maria"
    assert primer_nom("de la Concepció") == "Concepció"


def test_primer_nom_respeta_valores_no_textuales():
    assert primer_nom(None) is None
    assert primer_nom(1789) == 1789


def test_primer_nom_celda_solo_particulas_no_destruye_el_dato():
    assert primer_nom("de la") == "de la"


def test_truncar_columna_nom_aplica_a_toda_la_columna_sin_mutar_el_original():
    df = pd.DataFrame({"Nom": ["Joan Antoni", "Maria de los Dolores"], "Any": [1789, 1790]})
    truncado = truncar_columna_nom(df, "Nom")

    assert truncado["Nom"].tolist() == ["Joan", "Maria"]
    assert df["Nom"].tolist() == ["Joan Antoni", "Maria de los Dolores"]  # intacto
    assert truncado["Any"].tolist() == [1789, 1790]


# --------------------------------------------------------------------------- #
# Punto C — es_marca_ilegible() / extraer_palabras()
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "texto",
    ["Desenfocat", "desconegut", "IL·LEGIBLE", "***", "?", "??", "???", "--", "xx", "no llegible", "s/n"],
)
def test_g7_marcas_de_ilegibilidad_reconocidas(texto):
    assert es_marca_ilegible(texto) is True


@pytest.mark.parametrize("texto", ["Bennassar", "Miquel", "Pons"])
def test_palabras_reales_no_son_ilegibles(texto):
    assert es_marca_ilegible(texto) is False


def test_x_e_xx_son_marca_de_ilegibilidad_no_iniciales_reales():
    # "x"/"xx" están documentadas en MARCAS_ILEGIBLE (C.1): una letra que el
    # transcriptor no pudo leer, no una inicial real.
    assert es_marca_ilegible("x") is True
    assert es_marca_ilegible("xx") is True


def test_g7_no_llegible_llega_entera_a_extraer_palabras_sin_partirse():
    """
    "no llegible" tiene un espacio: si extraer_palabras() la partiera como
    cualquier otra celda, llegarían "no" y "llegible" por separado, y ninguna
    de las dos, sueltas, sería reconocible como marca de ilegibilidad.
    """
    serie = pd.Series(["no llegible", "Joan Miquel"])
    assert extraer_palabras(serie) == ["no llegible", "Joan", "Miquel"]


# --------------------------------------------------------------------------- #
# Punto B.4 — extraer_palabras_llinatge()
# --------------------------------------------------------------------------- #

def test_apellido_compuesto_conocido_no_se_descompone():
    conocidos = {"de Aguilar"}
    serie = pd.Series(["de Aguilar", "Pons"])
    palabras = extraer_palabras_llinatge(serie, lambda t: t in conocidos)
    assert palabras == ["de Aguilar", "Pons"]


def test_apellido_no_reconocido_se_descompone_igual_que_antes():
    serie = pd.Series(["de Pons"])
    palabras = extraer_palabras_llinatge(serie, lambda t: False)
    assert palabras == ["de", "Pons"]


# --------------------------------------------------------------------------- #
# Punto E — preparar_aceptacion() (qué se aplica y qué se aprende)
# --------------------------------------------------------------------------- #

def test_h1_aceptar_sin_modificar_no_genera_aprendizaje():
    filas = [DecisionFila("Ferrar", "Ferrer", ("Llinatge 1",), propuesta_original="Ferrer")]
    correcciones, aprendizajes = preparar_aceptacion(filas)
    assert correcciones == [Correccion("Ferrar", "Ferrer", ("Llinatge 1",))]
    assert aprendizajes == []


def test_h2_cambiar_de_candidato_si_genera_aprendizaje():
    # El valor final ("Rosselló") difiere de la propuesta automática
    # original ("Ferrer"): el archivero pulsó un botón de alternativa.
    filas = [DecisionFila("Xerrer", "Rosselló", ("Llinatge 1",), propuesta_original="Ferrer")]
    correcciones, aprendizajes = preparar_aceptacion(filas)
    assert correcciones == [Correccion("Xerrer", "Rosselló", ("Llinatge 1",))]
    assert aprendizajes == [("Xerrer", "Rosselló", ("Llinatge 1",))]


def test_h3_escribir_a_mano_si_genera_aprendizaje():
    filas = [DecisionFila("Alsebit", "Elisabet", ("Nom",), propuesta_original="Alsebit")]
    correcciones, aprendizajes = preparar_aceptacion(filas)
    assert aprendizajes == [("Alsebit", "Elisabet", ("Nom",))]


def test_fila_ambigua_sin_propuesta_original_siempre_se_aprende():
    # Empate ortográfico real (paso 5): no hay "tal cual venía" que aceptar.
    filas = [DecisionFila("Colel", "Collell", ("Llinatge 1",), propuesta_original=None)]
    correcciones, aprendizajes = preparar_aceptacion(filas)
    assert aprendizajes == [("Colel", "Collell", ("Llinatge 1",))]


def test_h6_fila_con_campo_vacio_se_ignora():
    filas = [DecisionFila("Xerrer", "", ("Llinatge 1",), propuesta_original="Ferrer")]
    correcciones, aprendizajes = preparar_aceptacion(filas)
    assert correcciones == []
    assert aprendizajes == []


def test_preparar_aceptacion_mezcla_varias_filas_correctamente():
    filas = [
        DecisionFila("Ferrar", "Ferrer", ("Llinatge 1",), propuesta_original="Ferrer"),  # sin cambios
        DecisionFila("Xerrer", "Rosselló", ("Llinatge 1",), propuesta_original="Ferrer"),  # candidato distinto
        DecisionFila("Alsebit", "Elisabet", ("Nom",), propuesta_original="Alsebit"),  # a mano
        DecisionFila("Colel", "Collell", ("Llinatge 1",), propuesta_original=None),  # ambigua sin propuesta
    ]
    correcciones, aprendizajes = preparar_aceptacion(filas)
    assert len(correcciones) == 4
    assert {a[0] for a in aprendizajes} == {"Xerrer", "Alsebit", "Colel"}
