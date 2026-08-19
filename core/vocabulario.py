"""
Consulta del vocabulario normalizado del Archivo.

Módulo sin dependencias de interfaz (no importa Tkinter ni CustomTkinter): solo
`core.datos_vocabulario` (los datos generados), `core.aprendizaje` (punto D) y
`rapidfuzz` para la búsqueda difusa de los casos que no están en el listado.

`core/datos_vocabulario.py` no se distribuye con el repositorio (son datos del
Archivo, ver `.gitignore`) y se genera con `tools/generar_vocabulario.py`. Si no
existe, este módulo se queda con los índices vacíos y `VOCABULARIO_DISPONIBLE`
en `False`; el resto del programa debe seguir funcionando solo con la heurística
de frecuencia de `core.cleaner.detectar_errores()`.

Clasificación como una cascada (`clasificar_palabra()`): se resuelve en la
primera regla que acierta, de más a menos autoridad:

    0. Marca de ilegibilidad (punto C)        -> ILEGIBLE, propuesta "Desconegut"
    1. Partícula o palabra demasiado corta -> excluida (responsabilidad de quien
       llama, ver `core.cleaner.clasificar_columna`; esta función nunca la ve).
    2. Tabla de variantes documentadas       -> VARIANTE   (confianza máxima,
       criterio de unificación fijado a mano por el Archivo)
    3. Aprendizaje de correcciones (punto D)  -> APRESA     (criterio del
       Archivo escrito solo, a partir de decisiones ya confirmadas)
    4. Clave exacta en el índice             -> VALIDA / NORMALIZABLE
    5. Clave ortográfica (dobles, ç)         -> ORTOGRAFICA / AMBIGUA (sin
       propuesta: empate real, sin puntuación que desempate)
    6. Búsqueda difusa, filtrada por género  -> CORREGIBLE / AMBIGUA (con
       propuesta, punto A.4) / DESCONOCIDA (propuesta "Desconegut", punto A.3)
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import NamedTuple

from rapidfuzz import fuzz, process

from core import aprendizaje
from core.cleaner import VALOR_DESCONEGUT, es_marca_ilegible, es_variante_genero
from core.normalizacion import Candidato, clave, clave_ortografica

try:
    from core.datos_vocabulario import LLINATGES, NOMS_DONES, NOMS_HOMES
except ImportError:
    NOMS_HOMES = ()
    NOMS_DONES = ()
    LLINATGES = ()

try:
    from core.datos_vocabulario import VARIANTS
except ImportError:
    VARIANTS = ()

VOCABULARIO_DISPONIBLE = bool(NOMS_HOMES or NOMS_DONES or LLINATGES)

# --------------------------------------------------------------------------- #
# Parámetros de calibración
# --------------------------------------------------------------------------- #

# A.2: puntuación mínima de rapidfuzz para proponer un cambio. Sustituye al
# antiguo acoplamiento con `core.cleaner.UMBRAL_SIMILITUD` (85): son dos
# mecanismos deliberadamente independientes desde el corte en 65 — ese sigue
# siendo el umbral de `detectar_errores()` (heurística de frecuencia, caso F),
# que no cambia.
UMBRAL_PROPUESTA = 65

# A.4: diferencia de puntuación entre el primer y el segundo candidato (tras
# descartar variantes de género) para considerar que NO hay competencia. Ya no
# bloquea la propuesta si no se alcanza: solo decide si la fila se marca
# "ambigua" (se propone igual el mejor) o "corregible" (sin competencia real).
MARGEN_MINIMO = 5

# Preposiciones y artículos: no estarán en el vocabulario y generarían ruido
# masivo si se analizaran como si fueran nombres o apellidos. Incluye también
# las partículas castellanas que aparecen en documentación histórica bilingüe
# ("los", "las") y el apóstrofo catalán ("d'"), relevantes sobre todo para
# `core.cleaner.primer_nom()` (punto B.2).
PARTICULAS: frozenset[str] = frozenset(
    {"de", "des", "del", "sa", "ses", "es", "i", "y", "la", "na", "en", "los", "las", "d'"}
)

# Identificadores de vocabulario, usados por clasificar_palabra() y por quien la
# llame (core.cleaner) para decir contra qué listado comparar cada columna.
VOCABULARIO_NOMS = "noms"
VOCABULARIO_LLINATGES = "llinatges"

# Máximo de candidatos que se ofrecen en un estado AMBIGUA sin propuesta (el
# empate real de la clave ortográfica, paso 5). Una fila con más de tres
# opciones deja de ser "elige uno" y se convierte en ruido.
MAXIMO_OPCIONES_AMBIGUA = 3


class Estado(Enum):
    """
    Los estados en los que puede caer una palabra frente al vocabulario, de
    mayor a menor confianza: VARIANTE > APRESA > ORTOGRAFICA > NORMALIZABLE >
    CORREGIBLE > AMBIGUA > ILEGIBLE > DESCONOCIDA. VALIDA no es una propuesta,
    es la ausencia de una.
    """

    VALIDA = "valida"
    NORMALIZABLE = "normalizable"
    VARIANTE = "variante"
    APRESA = "apresa"
    ORTOGRAFICA = "ortografica"
    CORREGIBLE = "corregible"
    AMBIGUA = "ambigua"
    ILEGIBLE = "ilegible"
    DESCONOCIDA = "desconocida"


class Clasificacion(NamedTuple):
    """
    Resultado de clasificar_palabra().

    `propuesta` lleva la forma canónica cuando hay una única candidata
    (VALIDA no tiene propuesta: no hace falta corregir nada). Desde el corte
    en 65 (punto A), DESCONOCIDA e ILEGIBLE SÍ llevan propuesta: siempre
    `core.cleaner.VALOR_DESCONEGUT` ("Desconegut"), para que el archivero
    reciba siempre algo que aceptar, editar o descartar (A.3/C.3).

    `puntuacio` es la puntuación de rapidfuzz del candidato propuesto (paso
    6); None cuando la propuesta viene de una fuente cierta (variante,
    aprendizaje, clave exacta u ortográfica) o cuando no hay candidato real
    que puntuar (DESCONOCIDA por clave ambigua, sin pasar por la búsqueda
    difusa).

    `alternatives` son el 2º y 3r candidato de la búsqueda difusa, con su
    puntuación, para seleccionar con un clic (A.5). Solo se rellena en
    CORREGIBLE/AMBIGUA (paso 6).

    `opciones` solo se rellena en el AMBIGUA SIN propuesta (empate real de la
    clave ortográfica, paso 5): los candidatos entre los que el programa no
    puede elegir, sin base numérica para preferir ninguno.

    `veces_apresa` solo se rellena en APRESA: cuántas veces ha confirmado el
    archivero esa corrección (D.7), para que la interfaz lo muestre en vez de
    una puntuación.
    """

    estado: Estado
    propuesta: str | None
    puntuacio: float | None = None
    alternatives: tuple[Candidato, ...] = ()
    opciones: tuple[str, ...] = ()
    veces_apresa: int | None = None


# --------------------------------------------------------------------------- #
# Construcción de índices (una sola vez, al importar el módulo)
# --------------------------------------------------------------------------- #


def _indexar(entradas: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """
    clave normalizada -> formas canónicas que comparten esa clave.

    Casi siempre una sola forma por clave. `tools/generar_vocabulario.py` ya
    resuelve las colisiones dentro de un mismo listado (misma clave, grafías
    distintas) quedándose con una sola grafía y avisando por consola, así que
    aquí solo puede haber más de una forma cuando se fusionan dos listados
    distintos (ver `_indexar_noms`).
    """
    indice: dict[str, list[str]] = {}
    for forma in entradas:
        indice.setdefault(clave(forma), []).append(forma)
    return {k: tuple(dict.fromkeys(formas)) for k, formas in indice.items()}


def _indexar_noms(
    homes: tuple[str, ...], dones: tuple[str, ...]
) -> tuple[dict[str, tuple[str, ...]], dict[str, frozenset[str]]]:
    """
    Índice de nombres fusionando Homes y Dones, más el género de cada clave.

    El género es un dato explícito del listado (no se infiere). Un nombre en las
    dos hojas con la misma grafía (p. ej. "Desconegut") es válido en ambos
    géneros: comparte clave y forma, no genera ambigüedad.

    Una minoría de nombres (el patrón catalán "-ià" masculino / "-ia" femenino:
    "Marià"/"Maria", "Julià"/"Júlia"...) normaliza a la misma clave con grafías
    realmente distintas. Ahí sí hay dos formas candidatas por clave, y
    `clasificar_palabra()` las trata como ambiguas si la palabra no coincide
    exactamente con ninguna de las dos.
    """
    generos: dict[str, set[str]] = {}
    indice: dict[str, list[str]] = {}

    for forma in homes:
        k = clave(forma)
        indice.setdefault(k, []).append(forma)
        generos.setdefault(k, set()).add("H")
    for forma in dones:
        k = clave(forma)
        indice.setdefault(k, []).append(forma)
        generos.setdefault(k, set()).add("D")

    indice_final = {k: tuple(dict.fromkeys(formas)) for k, formas in indice.items()}
    generos_final = {k: frozenset(g) for k, g in generos.items()}
    return indice_final, generos_final


def _indexar_ortografico(formas: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """clave_ortografica -> formas canónicas distintas que colapsan a ella."""
    indice: dict[str, list[str]] = {}
    for forma in formas:
        indice.setdefault(clave_ortografica(forma), []).append(forma)
    return {k: tuple(dict.fromkeys(fs)) for k, fs in indice.items()}


_INDICE_LLINATGES: dict[str, tuple[str, ...]] = _indexar(LLINATGES)
_INDICE_NOMS, _GENERO_NOMS = _indexar_noms(NOMS_HOMES, NOMS_DONES)

# Listas planas de formas canónicas, para la búsqueda difusa del paso 6.
_FORMAS_LLINATGES: tuple[str, ...] = tuple(
    dict.fromkeys(forma for formas in _INDICE_LLINATGES.values() for forma in formas)
)
_FORMAS_NOMS: tuple[str, ...] = tuple(
    dict.fromkeys(forma for formas in _INDICE_NOMS.values() for forma in formas)
)

_INDICE_ORTOGRAFICO_LLINATGES = _indexar_ortografico(_FORMAS_LLINATGES)
_INDICE_ORTOGRAFICO_NOMS = _indexar_ortografico(_FORMAS_NOMS)

# clave(variante) -> forma correcta. Tabla explícita del Archivo: el
# instrumento con prioridad máxima para fijar su criterio de UNIFICACIÓN para
# el buscador interno (punto E) — no de corrección lingüística: "Antònia" ->
# "Antonina" o "Bennassar" -> "Bennàsser" son la norma del Archivo aunque
# existan otras variantes válidas en catalán. Opcional: si no se generó,
# queda vacía y este paso de la cascada no encuentra nunca nada, sin romper
# el resto.
_INDICE_VARIANTS: dict[str, str] = {clave(variante): correccion for variante, correccion in VARIANTS}

# --------------------------------------------------------------------------- #
# Aprendizaje de correcciones (punto D): estado mutable, cargado al importar
# el módulo y actualizado en caliente según el archivero va confirmando.
# --------------------------------------------------------------------------- #

_APRENDIDAS: dict[aprendizaje.ClaveEntrada, aprendizaje.EntradaAprendida] = aprendizaje.cargar()


def registrar_aprendida(
    forma_erronea: str, correccion: str, vocabulario: str
) -> aprendizaje.ResultadoRegistro | None:
    """
    Registra una corrección confirmada por el archivero (D.4) y la persiste
    inmediatamente en el fichero de aprendizaje. Devuelve el resultado
    (D.6: NUEVA/REPETIDA/CAMBIADA) para que la interfaz avise si corresponde.

    D.5: una corrección hacia VALOR_DESCONEGUT nunca se aprende (no es un
    dato, es la ausencia de uno, y depende del documento concreto). Se
    comprueba aquí, no en la interfaz, para que sea un invariante del propio
    mecanismo de aprendizaje y no una convención que cada llamante deba
    recordar por su cuenta. Devuelve None en ese caso: no hubo registro.
    """
    if correccion == VALOR_DESCONEGUT:
        return None
    global _APRENDIDAS
    _APRENDIDAS, resultado = aprendizaje.registrar_correccion(
        _APRENDIDAS, forma_erronea, correccion, vocabulario
    )
    aprendizaje.guardar(_APRENDIDAS)
    return resultado


def eliminar_aprendida(forma_erronea: str, vocabulario: str) -> None:
    """Borra una entrada aprendida y persiste el cambio (D.8)."""
    global _APRENDIDAS
    _APRENDIDAS = aprendizaje.eliminar(_APRENDIDAS, forma_erronea, vocabulario)
    aprendizaje.guardar(_APRENDIDAS)


def listar_aprendidas() -> list[aprendizaje.EntradaAprendida]:
    """Todas las entradas aprendidas, para la ventana de gestión (D.8)."""
    return sorted(_APRENDIDAS.values(), key=lambda e: (e.vocabulario, e.clave_erronea))


def exportar_aprendidas_a_variants_xlsx(ruta: str) -> int:
    """Exporta lo aprendido al formato de VARIANTS (D.9). Devuelve cuántas filas."""
    return aprendizaje.exportar_a_variants_xlsx(_APRENDIDAS, ruta)


# --------------------------------------------------------------------------- #
# Búsqueda difusa memorizada (paso 6 de la cascada)
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=4096)
def _mejores_candidatos(palabra: str, vocabulario: str) -> tuple[tuple[str, float], ...]:
    """
    Los mejores candidatos por similitud para `palabra`, SIN filtrar por
    umbral todavía (A.1: el corte se aplica después, en clasificar_palabra,
    para poder distinguir "no hay nada por debajo de 65" de "el mejor
    candidato saca 62" a la hora de decidir entre AMBIGUA y DESCONOCIDA).

    Cacheada por `(palabra, vocabulario)` — dos cadenas, ambas hashables — nunca
    por la lista de candidatos ni por el índice: esos se leen del ámbito del
    módulo dentro de la función, no se pasan como argumento. La misma errata se
    repite decenas de veces en un archivo real y no tiene sentido recalcularla
    cada vez; `maxsize=4096` acota la memoria en equipos modestos.
    """
    formas = _FORMAS_NOMS if vocabulario == VOCABULARIO_NOMS else _FORMAS_LLINATGES
    if not formas:
        return ()
    coincidencias = process.extract(palabra, formas, scorer=fuzz.ratio, limit=5)
    return tuple((candidata, score) for candidata, score, _ in coincidencias)


def _filtrar_genero_contrario(
    palabra: str, candidatos: tuple[tuple[str, float], ...]
) -> tuple[tuple[str, float], ...]:
    """
    Descarta de `candidatos` las variantes de género de `palabra` (heurística
    `es_variante_genero`) y, además, cualquier otro candidato cuyo único género
    conocido (metadato `_GENERO_NOMS`) coincida con el de las ya descartadas.

    La segunda parte generaliza la heurística con el dato: si "Antònia" descarta
    a "Antoni" (H) por variante de género, un tercer candidato que sea
    exclusivamente masculino también queda descartado, aunque la heurística
    palabra-a-palabra no lo hubiera pillado directamente. Solo actúa cuando la
    heurística ya confirmó al menos una vez que hay un género "equivocado" de
    por medio; nunca adivina el género de `palabra` en el vacío.
    """
    restantes: list[tuple[str, float]] = []
    descartados: list[tuple[str, float]] = []
    for forma, score in candidatos:
        if es_variante_genero(palabra, forma):
            descartados.append((forma, score))
        else:
            restantes.append((forma, score))

    if not descartados:
        return tuple(restantes)

    generos_equivocados: set[str] = set()
    for forma, _ in descartados:
        generos_equivocados |= _GENERO_NOMS.get(clave(forma), frozenset())
    if not generos_equivocados:
        return tuple(restantes)

    return tuple(
        (forma, score)
        for forma, score in restantes
        if not _GENERO_NOMS.get(clave(forma), frozenset()) <= generos_equivocados
        or not _GENERO_NOMS.get(clave(forma))
    )


# --------------------------------------------------------------------------- #
# Clasificación
# --------------------------------------------------------------------------- #


def clasificar_palabra(palabra: str, vocabulario: str) -> Clasificacion:
    """
    Clasifica `palabra` contra el vocabulario indicado ("noms" o "llinatges").

    Ver la cascada de resolución en el docstring del módulo. Las partículas
    deben filtrarse antes de llamar a esta función: no se analizan aquí.
    """
    if vocabulario == VOCABULARIO_NOMS:
        indice, indice_ortografico = _INDICE_NOMS, _INDICE_ORTOGRAFICO_NOMS
    elif vocabulario == VOCABULARIO_LLINATGES:
        indice, indice_ortografico = _INDICE_LLINATGES, _INDICE_ORTOGRAFICO_LLINATGES
    else:
        raise ValueError(f"Vocabulario desconocido: {vocabulario!r}")

    # 0. Marca de ilegibilidad (punto C): máxima prioridad, ni siquiera se
    # compara contra el vocabulario.
    if es_marca_ilegible(palabra):
        return Clasificacion(Estado.ILEGIBLE, VALOR_DESCONEGUT)

    # 2. Tabla de variantes: máxima autoridad tras la ilegibilidad, se
    # consulta antes que nada más.
    propuesta_variante = _INDICE_VARIANTS.get(clave(palabra))
    if propuesta_variante is not None:
        return Clasificacion(Estado.VARIANTE, propuesta_variante)

    # 3. Aprendizaje de correcciones (punto D): justo después de VARIANTS
    # (que siempre gana, por ser curado por el Archivo) y antes de la clave
    # exacta. La búsqueda es por CLAVE, no por grafía literal, a propósito
    # (para reconocer la misma errata en mayúsculas o sin acento) — pero eso
    # significa que la clave de una corrección aprendida puede coincidir con
    # la de su propio destino ya bien escrito ("Carrio"->"Carrió" comparte
    # clave con "Carrió"; "Orpi"->"Orpí" con "Orpí"). Si no se comprobara
    # esto, la primera vez que apareciera la forma YA VÁLIDA se reclasificaría
    # como "apresa" en vez de "válida" -- un no-op en el texto final, pero una
    # fila de confirmación de más y una validación perdida (hallazgo real
    # verificado contra datos del Archivo: 11 "vàlides" convertidas en
    # "apresa" de esta forma). Si la corrección aprendida coincide
    # literalmente con la palabra tal cual está escrita, no hay nada que
    # aprender aquí: se deja caer a la cascada normal, que la resolverá como
    # VALIDA por sí sola.
    entrada_aprendida = aprendizaje.proponer(_APRENDIDAS, palabra, vocabulario)
    if entrada_aprendida is not None and entrada_aprendida.correccion != palabra:
        return Clasificacion(
            Estado.APRESA, entrada_aprendida.correccion, veces_apresa=entrada_aprendida.veces
        )

    # 4. Clave exacta en el índice.
    k = clave(palabra)
    formas = indice.get(k)
    if formas is not None:
        if palabra in formas:
            return Clasificacion(Estado.VALIDA, None)
        if len(formas) == 1:
            return Clasificacion(Estado.NORMALIZABLE, formas[0])
        # Clave ambigua a nivel exacto (p. ej. "Marià"/"Maria", "María" no
        # coincide con ninguna de las dos) — el programa SÍ sabe cuáles son
        # las formas candidatas: descartarlas como "Desconegut" sería tirar
        # información que ya se tiene. Se ofrecen como opciones seleccionables
        # (B.3), igual que el empate de la clave ortográfica (paso 5): no hay
        # puntuación que las desempate, así que tampoco aquí hay propuesta
        # implícita.
        return Clasificacion(Estado.AMBIGUA, None, opciones=formas[:MAXIMO_OPCIONES_AMBIGUA])

    # 5. Clave ortográfica: misma palabra, distinta grafía de dobles/ç.
    ko = clave_ortografica(palabra)
    formas_orto = indice_ortografico.get(ko)
    if formas_orto is not None:
        if len(formas_orto) == 1:
            return Clasificacion(Estado.ORTOGRAFICA, formas_orto[0])
        # Empate real entre dos formas DISTINTAS que colapsan a la misma
        # clave ortográfica (p. ej. "Colell"/"Collell"): a diferencia del
        # empate de la búsqueda difusa (paso 6), aquí no hay ninguna
        # puntuación que desempate, así que sigue sin propuesta.
        return Clasificacion(Estado.AMBIGUA, None, opciones=formas_orto[:MAXIMO_OPCIONES_AMBIGUA])

    # 6. Búsqueda difusa, con el filtro de género aplicado ANTES del margen:
    # un candidato que es variante de género nunca fue un destino válido, así
    # que no debe contar para decidir si hay ambigüedad entre los que quedan.
    candidatos = _mejores_candidatos(palabra, vocabulario)
    if vocabulario == VOCABULARIO_NOMS:
        candidatos = _filtrar_genero_contrario(palabra, candidatos)

    # A.2/A.3: por debajo de UMBRAL_PROPUESTA (o sin ningún candidato), el
    # Archivo prefiere revisar y asignar el valor a mano antes que no recibir
    # ninguna propuesta.
    if not candidatos:
        return Clasificacion(Estado.DESCONOCIDA, VALOR_DESCONEGUT)

    mejor_forma, mejor_score = candidatos[0]
    alternatives = tuple(Candidato(forma, score) for forma, score in candidatos[1:3])

    if mejor_score < UMBRAL_PROPUESTA:
        # La búsqueda difusa SÍ se ejecutó y SÍ encontró candidatos reales;
        # simplemente ninguno llega al umbral de propuesta. Se conserva su
        # puntuación real y las alternativas (en vez de descartarlas junto
        # con la decisión) para que la interfaz pueda mostrar qué se probó y
        # se descartó, no un 0% que parece "no se intentó nada". La propuesta
        # por defecto sigue siendo "Desconegut": esto no cambia la decisión,
        # solo la hace visible.
        return Clasificacion(Estado.DESCONOCIDA, VALOR_DESCONEGUT, mejor_score, alternatives)

    if len(candidatos) == 1:
        return Clasificacion(Estado.CORREGIBLE, mejor_forma, mejor_score, alternatives)

    _, segundo_score = candidatos[1]
    if (mejor_score - segundo_score) >= MARGEN_MINIMO:
        return Clasificacion(Estado.CORREGIBLE, mejor_forma, mejor_score, alternatives)

    # A.4: el margen ya NO bloquea la propuesta. Se propone igual el mejor
    # candidato; la fila queda marcada AMBIGUA para que el archivero sepa que
    # hay un segundo candidato competitivo (visible en `alternatives`).
    return Clasificacion(Estado.AMBIGUA, mejor_forma, mejor_score, alternatives)


def es_forma_conocida(forma: str, vocabulario: str) -> bool:
    """
    True si `forma` es exactamente una grafía canónica del vocabulario indicado.

    Para el caso F del addendum: una propuesta de la heurística de frecuencia
    puede apuntar a una forma que el vocabulario no reconoce (la mayoría del
    documento puede estar tan equivocada como la minoría). `core.cleaner` usa
    esto para marcar esas propuestas como "no verificadas" en vez de dejarlas
    con la misma confianza que una propuesta respaldada por el listado oficial.

    También la usa `core.cleaner.extraer_palabras_llinatge()` (punto B.4) para
    reconocer apellidos compuestos con espacio antes de partir la celda.
    """
    if vocabulario == VOCABULARIO_NOMS:
        indice = _INDICE_NOMS
    elif vocabulario == VOCABULARIO_LLINATGES:
        indice = _INDICE_LLINATGES
    else:
        raise ValueError(f"Vocabulario desconocido: {vocabulario!r}")
    return forma in indice.get(clave(forma), ())
