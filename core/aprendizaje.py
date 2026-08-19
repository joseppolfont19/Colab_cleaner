"""
Aprendizaje de correcciones (punto D del encargo).

Cuando el archivero valida una corrección a mano, el programa la recuerda y
la propone automáticamente la próxima vez que aparezca la misma grafía, sin
pasar por la búsqueda difusa. Es el mecanismo con el que el criterio del
Archivo se va escribiendo solo.

Módulo sin dependencias de interfaz (no importa Tkinter ni CustomTkinter):
solo `core.normalizacion`, `json` y `pandas` (esta última solo para la
exportación a VARIANTS, punto D.9).

Formato de almacenamiento: JSON, no un módulo Python generado (a diferencia
de `core.datos_vocabulario`). El vocabulario oficial lo genera una
herramienta a partir de listados curados por el Archivo y se distribuye
dentro del ejecutable; esto, en cambio, se escribe en tiempo de ejecución,
crece solo, y el archivero debe poder abrirlo, revisarlo y corregirlo con un
editor de texto (D.1).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from enum import Enum
from typing import NamedTuple

from core.normalizacion import clave

logger = logging.getLogger(__name__)

NOMBRE_FICHERO = "correccions_apreses.json"

# Claves del diccionario de entradas: (vocabulario, clave_erronea) -> EntradaAprendida.
ClaveEntrada = tuple[str, str]


class ResultadoRegistro(Enum):
    """Qué pasó al registrar una corrección (D.6)."""

    NUEVA = "nueva"          # no existía ninguna entrada para esa forma
    REPETIDA = "repetida"    # ya existía, mismo destino: se incrementa el contador
    CAMBIADA = "cambiada"    # ya existía con un destino DISTINTO: puede indicar
                              # que la entrada anterior era errónea; hay que avisar


class EntradaAprendida(NamedTuple):
    forma_erronea: str       # última grafía literal vista (para que un humano la reconozca)
    clave_erronea: str       # clave() normalizada: es la que se usa para buscar
    correccion: str
    vocabulario: str         # "noms" o "llinatges" (VOCABULARIO_NOMS / VOCABULARIO_LLINATGES)
    veces: int
    ultima_confirmacion: str  # fecha ISO (YYYY-MM-DD)


# --------------------------------------------------------------------------- #
# Ubicación del fichero (D.2)
# --------------------------------------------------------------------------- #


def _directorio_datos() -> str:
    """
    Directorio donde vive el fichero de aprendizaje: junto al ejecutable,
    nunca dentro del paquete.

    Con PyInstaller, `sys.executable` apunta al .exe final; `sys._MEIPASS` es
    un directorio temporal que se descomprime al arrancar y se borra al
    cerrar, así que cualquier cosa escrita ahí desaparecería con el programa.
    En modo desarrollo (no congelado), se usa la raíz del proyecto.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ruta_fichero() -> str:
    return os.path.join(_directorio_datos(), NOMBRE_FICHERO)


# --------------------------------------------------------------------------- #
# Carga y guardado
# --------------------------------------------------------------------------- #


def cargar() -> dict[ClaveEntrada, EntradaAprendida]:
    """
    Carga el fichero de correcciones aprendidas.

    Si no existe todavía, se devuelve un diccionario vacío (se crea al primer
    guardado). Si existe pero está corrupto o con un formato inesperado, se
    avisa por el log y se continúa con un diccionario vacío: el aprendizaje
    nunca debe impedir que el programa arranque (D.2).
    """
    ruta = _ruta_fichero()
    if not os.path.exists(ruta):
        return {}

    try:
        with open(ruta, "r", encoding="utf-8") as f:
            bruto = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("No se pudo leer %s (%s); se continúa sin aprendizaje.", ruta, exc)
        return {}

    if not isinstance(bruto, list):
        logger.warning("%s no tiene el formato esperado (lista); se continúa sin aprendizaje.", ruta)
        return {}

    entradas: dict[ClaveEntrada, EntradaAprendida] = {}
    for item in bruto:
        try:
            vocabulario = item["vocabulario"]
            clave_erronea = item["clave"]
            entrada = EntradaAprendida(
                forma_erronea=item.get("forma_erronea", clave_erronea),
                clave_erronea=clave_erronea,
                correccion=item["correccion"],
                vocabulario=vocabulario,
                veces=int(item.get("veces", 1)),
                ultima_confirmacion=item.get("ultima_confirmacion", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Entrada ignorada en %s (%s): %r", ruta, exc, item)
            continue
        entradas[(vocabulario, clave_erronea)] = entrada
    return entradas


def guardar(entradas: dict[ClaveEntrada, EntradaAprendida]) -> None:
    """Escribe el fichero completo (lo crea si no existía todavía, D.2)."""
    ruta = _ruta_fichero()
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    bruto = [
        {
            "clave": e.clave_erronea,
            "forma_erronea": e.forma_erronea,
            "correccion": e.correccion,
            "vocabulario": e.vocabulario,
            "veces": e.veces,
            "ultima_confirmacion": e.ultima_confirmacion,
        }
        for e in sorted(entradas.values(), key=lambda e: (e.vocabulario, e.clave_erronea))
    ]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(bruto, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Consulta y modificación (D.4/D.6/D.8)
# --------------------------------------------------------------------------- #


def proponer(
    entradas: dict[ClaveEntrada, EntradaAprendida], palabra: str, vocabulario: str
) -> EntradaAprendida | None:
    """Busca una corrección aprendida para `palabra` en `vocabulario`."""
    return entradas.get((vocabulario, clave(palabra)))


def registrar_correccion(
    entradas: dict[ClaveEntrada, EntradaAprendida],
    forma_erronea: str,
    correccion: str,
    vocabulario: str,
) -> tuple[dict[ClaveEntrada, EntradaAprendida], ResultadoRegistro]:
    """
    Añade o actualiza una entrada aprendida a partir de una decisión deliberada
    del archivero (D.4: escribir a mano, editar la propuesta, elegir el
    candidato 2/3, o simplemente confirmar una fila individual).

    Devuelve un diccionario NUEVO (no muta `entradas`) y el resultado del
    registro (D.6): NUEVA, REPETIDA (mismo destino, se incrementa el
    contador) o CAMBIADA (destino distinto al aprendido antes: se sustituye y
    se incrementa el contador, pero quien llame debe avisar, porque puede
    indicar que la entrada anterior era errónea).

    No hace ninguna comprobación sobre `correccion` (p. ej. si es
    VALOR_DESCONEGUT): esa decisión —qué SÍ se aprende— es de quien llama
    (D.5), no de este módulo.
    """
    k = clave(forma_erronea)
    clave_dict = (vocabulario, k)
    actuales = dict(entradas)
    existente = actuales.get(clave_dict)
    hoy = dt.date.today().isoformat()

    if existente is None:
        resultado = ResultadoRegistro.NUEVA
        veces = 1
    elif existente.correccion == correccion:
        resultado = ResultadoRegistro.REPETIDA
        veces = existente.veces + 1
    else:
        resultado = ResultadoRegistro.CAMBIADA
        veces = existente.veces + 1

    actuales[clave_dict] = EntradaAprendida(
        forma_erronea=forma_erronea,
        clave_erronea=k,
        correccion=correccion,
        vocabulario=vocabulario,
        veces=veces,
        ultima_confirmacion=hoy,
    )
    return actuales, resultado


def eliminar(
    entradas: dict[ClaveEntrada, EntradaAprendida], forma_erronea: str, vocabulario: str
) -> dict[ClaveEntrada, EntradaAprendida]:
    """
    Borra una entrada aprendida (D.8). Un error aprendido se repetiría
    indefinidamente si no hubiera forma de deshacerlo.
    """
    actuales = dict(entradas)
    actuales.pop((vocabulario, clave(forma_erronea)), None)
    return actuales


# --------------------------------------------------------------------------- #
# Exportación a VARIANTS (D.9)
# --------------------------------------------------------------------------- #


def exportar_a_variants(entradas: dict[ClaveEntrada, EntradaAprendida]) -> list[tuple[str, str]]:
    """
    Traduce las entradas aprendidas al formato (variante, forma correcta) de
    `tools/generar_vocabulario.py --variants`: el Archivo puede promover lo
    consolidado al vocabulario oficial y compartirlo entre puestos de trabajo
    (el aprendizaje en sí es local a cada instalación, D.10).
    """
    return [(e.forma_erronea, e.correccion) for e in entradas.values()]


def exportar_a_variants_xlsx(entradas: dict[ClaveEntrada, EntradaAprendida], ruta: str) -> int:
    """
    Como exportar_a_variants(), pero escribe directamente un .xlsx con las
    columnas y la fila de cabecera que `tools/generar_vocabulario.py --variants`
    espera por defecto (columnas 0 y 1, cabecera en la fila 0). Devuelve el
    número de filas exportadas.
    """
    import pandas as pd

    filas = exportar_a_variants(entradas)
    df = pd.DataFrame(filas, columns=["Variant", "Correcció"])
    df.to_excel(ruta, index=False)
    return len(filas)
