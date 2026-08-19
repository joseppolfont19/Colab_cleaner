"""
Clave de búsqueda normalizada, compartida por todo el programa.

Un único sitio para esta función: `core/cleaner.py`, `core/vocabulario.py` y
`tools/generar_vocabulario.py` la importan de aquí. Si alguno de ellos tuviera su
propia copia y las dos divergieran, el índice del vocabulario dejaría de encontrar
entradas sin avisar de nada.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple


class Candidato(NamedTuple):
    """
    Un candidato de la búsqueda difusa, con su puntuación de rapidfuzz.

    Vive aquí (módulo hoja, sin dependencias del resto del proyecto) porque lo
    usan tanto `core.cleaner` (en `Sugerencia.alternatives`) como
    `core.vocabulario` (en `Clasificacion.alternatives`), y esos dos módulos ya
    se importan entre sí en el otro sentido (`vocabulario` importa de
    `cleaner`): ponerlo en cualquiera de los dos crearía un ciclo.
    """

    forma: str
    puntuacio: float


def clave(palabra: str) -> str:
    """
    Forma normalizada para comparar o indexar: minúsculas y sin acentos.

    'Rosselló', 'ROSSELLO' y 'rossello' producen la misma clave.
    """
    descompuesta = unicodedata.normalize("NFD", palabra.casefold())
    return "".join(c for c in descompuesta if not unicodedata.combining(c))


_LETRAS_REPETIDAS = re.compile(r"(.)\1+")


def clave_ortografica(palabra: str) -> str:
    """
    Clave más agresiva que `clave()`: además de acentos y mayúsculas, colapsa
    las letras repetidas consecutivas ('ss'->'s', 'll'->'l', 'nn'->'n', 'rr'->'r',
    y cualquier otra consonante o vocal doblada) y unifica 'ç' con 'c'.

    Existe para un caso muy concreto: variantes ortográficas donde de verdad es
    la misma palabra escrita con distinta grafía consonántica ('Roselló' /
    'Rosselló'), a diferencia de dos apellidos realmente distintos que además
    resultan parecidos ('Roselló' / 'Rosell'). `clave()` no los distingue de una
    errata cualquiera; esta función sí, porque compara la forma "pelada" de
    dobles, no la similitud de dos cadenas.
    """
    base = clave(palabra).replace("ç", "c")
    return _LETRAS_REPETIDAS.sub(r"\1", base)
