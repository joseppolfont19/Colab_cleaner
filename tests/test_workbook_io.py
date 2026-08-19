"""
Tests de la capa de entrada/salida (XLSX y ODS).

Los archivos se crean en un directorio temporal, así que no hacen falta datos
de ejemplo en el repositorio ni queda basura tras ejecutarlos.
"""

import pandas as pd
import pytest

from core.cleaner import Correccion, aplicar_correcciones
from core.workbook_io import (
    EXTENSIONES_SOPORTADAS,
    FormatoNoSoportado,
    abrir_libro,
    extension_de,
    leer_tabla,
    ruta_de_salida,
)

FILA_CABECERA = 1
PRIMERA_FILA_DATOS = 3

TABLA = pd.DataFrame(
    {
        "Any": [1789, 1790, 1791],
        "Llinatge 1": ["Bennassar", "Benassar", "Bennassar"],
        "Llinatge 2": ["Pons", "Mas", "Ferrer"],
        "Nom": ["Joan Miquel", "Joan Miquell", None],
        "Foli": ["12r", "13r", "14r"],
    }
)

MOTOR_POR_EXTENSION = {".xlsx": "openpyxl", ".ods": "odf"}


@pytest.fixture(params=EXTENSIONES_SOPORTADAS)
def archivo(request, tmp_path):
    """Genera el mismo contenido en cada formato soportado."""
    ruta = tmp_path / f"registre{request.param}"
    # startrow=1 deja la fila 1 libre, igual que los archivos reales.
    TABLA.to_excel(
        ruta,
        index=False,
        startrow=1,
        engine=MOTOR_POR_EXTENSION[request.param],
    )
    return str(ruta)


# --------------------------------------------------------------------------- #
# Detección de formato
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "ruta, esperado",
    [
        ("registre.xlsx", ".xlsx"),
        ("registre.ods", ".ods"),
        ("REGISTRE.XLSX", ".xlsx"),   # Windows suele dar la extensión en mayúsculas
        ("/ruta/amb espais/re.ods", ".ods"),
    ],
)
def test_extension_reconocida(ruta, esperado):
    assert extension_de(ruta) == esperado


@pytest.mark.parametrize("ruta", ["datos.csv", "libro.xls", "notas.txt", "sinextension"])
def test_extension_rechazada(ruta):
    with pytest.raises(FormatoNoSoportado):
        extension_de(ruta)


def test_ruta_de_salida_conserva_la_extension():
    assert ruta_de_salida("/tmp/registre.ods") == "/tmp/registre_corregit.ods"
    assert ruta_de_salida("/tmp/registre.xlsx") == "/tmp/registre_corregit.xlsx"


# --------------------------------------------------------------------------- #
# Ciclo completo, idéntico en los dos formatos
# --------------------------------------------------------------------------- #

def test_lectura_devuelve_las_columnas_esperadas(archivo):
    df = leer_tabla(archivo, fila_cabecera=FILA_CABECERA)
    assert list(df.columns) == list(TABLA.columns)
    assert len(df) == len(TABLA)


def test_ciclo_leer_corregir_guardar(archivo):
    """La corrección debe sobrevivir al guardado en cualquiera de los dos formatos."""
    df = leer_tabla(archivo, fila_cabecera=FILA_CABECERA)

    corregido, _ = aplicar_correcciones(
        df,
        [
            Correccion("Benassar", "Bennassar", ("Llinatge 1",)),
            Correccion("Miquell", "Miquel", ("Nom",)),
        ],
    )

    libro = abrir_libro(archivo)
    libro.escribir_datos(corregido, PRIMERA_FILA_DATOS)
    salida = ruta_de_salida(archivo)
    libro.guardar(salida)

    releido = leer_tabla(salida, fila_cabecera=FILA_CABECERA)
    assert releido["Llinatge 1"].tolist() == ["Bennassar"] * 3
    assert releido["Nom"].tolist()[:2] == ["Joan Miquel", "Joan Miquel"]


def test_las_celdas_vacias_no_se_convierten_en_texto_nan(archivo):
    """pandas usa NaN para las celdas vacías; escrito tal cual saldría el texto 'nan'."""
    df = leer_tabla(archivo, fila_cabecera=FILA_CABECERA)

    libro = abrir_libro(archivo)
    libro.escribir_datos(df, PRIMERA_FILA_DATOS)
    salida = ruta_de_salida(archivo)
    libro.guardar(salida)

    releido = leer_tabla(salida, fila_cabecera=FILA_CABECERA)
    assert pd.isna(releido.loc[2, "Nom"])


def test_los_numeros_siguen_siendo_numeros(archivo):
    df = leer_tabla(archivo, fila_cabecera=FILA_CABECERA)

    libro = abrir_libro(archivo)
    libro.escribir_datos(df, PRIMERA_FILA_DATOS)
    salida = ruta_de_salida(archivo)
    libro.guardar(salida)

    releido = leer_tabla(salida, fila_cabecera=FILA_CABECERA)
    assert pd.api.types.is_numeric_dtype(releido["Any"])
    assert releido["Any"].tolist() == [1789, 1790, 1791]


def test_abrir_libro_rechaza_formatos_no_soportados(tmp_path):
    csv = tmp_path / "datos.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(FormatoNoSoportado):
        abrir_libro(str(csv))


# --------------------------------------------------------------------------- #
# Particularidades del formato ODS
# --------------------------------------------------------------------------- #

def test_ods_parte_correctamente_los_bloques_de_celdas_repetidas(tmp_path):
    """
    ODS comprime las celdas iguales con `number-columns-repeated`. Para escribir
    en medio de un bloque hay que partirlo sin alterar el total de columnas ni
    perder el estilo.
    """
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow

    from core.workbook_io import LibroOds

    NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    ATTR_REPETIR = (NS_TABLE, "number-columns-repeated")
    ATTR_ESTILO = (NS_TABLE, "style-name")

    doc = OpenDocumentSpreadsheet()
    tabla = Table(name="Hoja")
    fila = TableRow()
    fila.addElement(TableCell(numbercolumnsrepeated=5, stylename="ce1"))
    tabla.addElement(fila)
    doc.spreadsheet.addElement(tabla)
    ruta = tmp_path / "repetidas.ods"
    doc.save(str(ruta))

    libro = LibroOds(str(ruta))
    objetivo = libro._celda_en(libro._fila_en(0), 2)
    libro._escribir_celda(objetivo, "AQUI")

    celdas = [n for n in libro._fila_en(0).childNodes if n.qname[1] == "table-cell"]
    anchos = [int(c.attributes.get(ATTR_REPETIR, 1)) for c in celdas]

    assert anchos == [2, 1, 2]                       # el bloque se parte en tres
    assert sum(anchos) == 5                          # sin inventar ni perder columnas
    assert all(c.attributes.get(ATTR_ESTILO) == "ce1" for c in celdas)  # estilo intacto
    assert str(celdas[1]) == "AQUI"


def test_ods_parte_un_bloque_repetido_en_mas_de_un_punto_de_la_misma_fila(tmp_path):
    """
    Regresión de un fallo real reportado contra un documento del Archivo:
    escribir en dos columnas que caen dentro del MISMO bloque de celdas
    repetidas obliga a partirlo dos veces -- la segunda partición cae sobre
    un trozo creado por la primera, no sobre el bloque original.

    Sin `_insertar_y_registrar()`, ese trozo (insertado con `insertBefore()`)
    nunca queda registrado en el documento -- bug real de odfpy, que tiene un
    comentario "FIXME: update ownerDocument.element_dict or find other
    solution" en su propio `Element.removeChild()` -- y el intento de
    quitarlo para partirlo de nuevo revienta con
    `ValueError: list.remove(x): x not in list`.
    """
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow

    from core.workbook_io import LibroOds

    NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    ATTR_REPETIR = (NS_TABLE, "number-columns-repeated")

    doc = OpenDocumentSpreadsheet()
    tabla = Table(name="Hoja")
    fila = TableRow()
    fila.addElement(TableCell(numbercolumnsrepeated=5, stylename="ce1"))
    tabla.addElement(fila)
    doc.spreadsheet.addElement(tabla)
    ruta = tmp_path / "doble_particion.ods"
    doc.save(str(ruta))

    libro = LibroOds(str(ruta))
    # Igual que escribir_datos(): se obtiene la fila UNA vez y se reutiliza
    # para varias columnas, tal como ocurre al escribir una fila real.
    fila_cargada = libro._fila_en(0)

    celda1 = libro._celda_en(fila_cargada, 1)
    libro._escribir_celda(celda1, "UNO")

    # Esta columna cae ahora dentro del trozo "posterior" que dejó la
    # primera partición, no en el bloque de 5 original.
    celda3 = libro._celda_en(fila_cargada, 3)
    libro._escribir_celda(celda3, "TRES")

    celdas = [n for n in fila_cargada.childNodes if n.qname[1] == "table-cell"]
    anchos = [int(c.attributes.get(ATTR_REPETIR, 1)) for c in celdas]

    assert sum(anchos) == 5          # sin inventar ni perder columnas
    assert str(celdas[1]) == "UNO"
    assert str(celdas[3]) == "TRES"

    # El documento debe poder guardarse sin reventar (ciclo completo).
    destino = tmp_path / "doble_particion_guardado.ods"
    libro.guardar(str(destino))
    assert destino.exists()
