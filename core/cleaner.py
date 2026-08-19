"""
Lógica pura del corrector de nombres.

Este módulo no importa Tkinter ni CustomTkinter: solo pandas y rapidfuzz.
Todo lo que hay aquí son funciones sin estado, testeables desde pytest sin
levantar ninguna ventana.

Flujo general:
    1. limpiar_dataframe()  -> normalización automática (Fase 1)
    2. detectar_errores()   -> propuestas de corrección (Fase 2)
    3. aplicar_correcciones() -> aplica las correcciones validadas por el usuario
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple, Sequence

import pandas as pd
from rapidfuzz import fuzz, process

from core.normalizacion import Candidato, clave as _normalizar

# --------------------------------------------------------------------------- #
# Constantes de configuración
# --------------------------------------------------------------------------- #

UMBRAL_SIMILITUD = 85          # score mínimo de rapidfuzz para detectar_errores()
                                # (heurística de frecuencia, caso F). No confundir con
                                # UMBRAL_PROPUESTA de core.vocabulario (corte en 65,
                                # decisión del Archivo): son dos mecanismos distintos
                                # y deliberadamente desacoplados.
LONGITUD_MINIMA_PALABRA = 3    # palabras más cortas se ignoran (partículas, iniciales)
SIMBOLOS_A_RECORTAR = "'.,-"   # símbolos que se eliminan al principio y al final

# Sufijos que distinguen género y NO deben tratarse como errores tipográficos.
PATRONES_GENERO: tuple[tuple[str, str], ...] = (
    ("a", "o"),      # Mariana / Mariano, Raimunda / Raimundo
    ("a", "e"),      # Maria / Marie
    ("ana", "ano"),  # Juana / Juano
    ("ina", "ino"),  # Catalina / Catalino
)

# Letras que, añadidas al final de un nombre, suelen marcar femenino.
LETRAS_FEMENINO = frozenset("aei")

# Valor que se escribe cuando el programa no tiene ninguna propuesta fiable
# (candidato por debajo de UMBRAL_PROPUESTA, o marca de ilegibilidad): el
# Archivo prefiere revisar y decidir a mano un valor explícito antes que un
# campo vacío sin ninguna propuesta que aceptar o editar (punto A.3 / C.3).
VALOR_DESCONEGUT = "Desconegut"

# Marcas de ilegibilidad documentadas por el Archivo (punto C.1): celdas o
# palabras que no son un nombre/apellido real, sino una anotación de que el
# original no se pudo leer. Comparadas por clave() normalizada, así que
# mayúsculas y acentos no importan. "no llegible" incluye un espacio a
# propósito: extraer_palabras() la reconoce como marca ANTES de partir la
# celda en palabras sueltas, así que llega aquí intacta.
MARCAS_ILEGIBLE: frozenset[str] = frozenset(
    _normalizar(m)
    for m in (
        "desenfocat", "desenfocado", "desconegut", "desconeguda", "desconocido",
        "il·legible", "illegible", "ilegible", "borroso", "borrós",
        "no llegible", "tachado", "ratllat", "s/n",
        "?", "??", "???", "*", "**", "***", "-", "--", "x", "xx",
    )
)

# C.2: celdas formadas solo por caracteres no alfabéticos (interrogantes,
# asteriscos, guiones, puntos, barras) también cuentan como ilegibles aunque
# no estén literalmente en MARCAS_ILEGIBLE (p. ej. "¿?" o "...").
PATRON_NO_ALFABETICO = re.compile(r"[^\wÀ-ÿ]+", re.UNICODE)


def es_marca_ilegible(texto: str) -> bool:
    """
    True si `texto` (una celda o una palabra) es una anotación de ilegibilidad,
    no un dato real (punto C).

    Dos criterios independientes, cualquiera de los dos basta:
      1. Coincide (por clave normalizada) con una entrada documentada en
         MARCAS_ILEGIBLE.
      2. No contiene ninguna letra: son solo símbolos de puntuación
         (asteriscos, interrogantes, guiones...), el patrón típico de "no sé
         qué ponía aquí" de una transcripción manual.
    """
    if not texto:
        return False
    if _normalizar(texto) in MARCAS_ILEGIBLE:
        return True
    return not any(c.isalpha() for c in texto)


class Sugerencia(NamedTuple):
    """Una corrección propuesta, todavía sin validar por el usuario."""

    error: str
    correccion: str
    frecuencia: int          # cuántas veces aparece la forma errónea
    columnas: tuple[str, ...]  # columnas donde se detectó, para acotar el reemplazo
    # De mayor a menor confianza: "variante" (tabla documentada del Archivo),
    # "apresa" (aprendizaje de correcciones, punto D), "ortografica" (misma
    # palabra, dobles/ç distintos), "normalizacion" (acentos/mayúsculas),
    # "corregible" (similitud contra el vocabulario, por encima del margen),
    # "ambigua" (similitud contra el vocabulario, empate por debajo del
    # margen: se propone igual el mejor candidato, punto A.4), "ilegible"
    # (marca de ilegibilidad, punto C), "desconeguda" (ni vocabulario ni
    # heurística de frecuencia dieron nada por encima de UMBRAL_PROPUESTA:
    # propuesta "Desconegut"), "frecuencia" (heurística de mayoría entre lo
    # que el vocabulario no reconoce, y su destino SÍ está en el vocabulario)
    # o "frecuencia_no_verificada" (igual, pero su destino tampoco está en el
    # vocabulario). Por defecto "frecuencia": es el valor de partida para las
    # sugerencias de detectar_errores(), que clasificar_columna() reclasifica a
    # "frecuencia_no_verificada" cuando corresponde.
    categoria: str = "frecuencia"
    # Puntuación de rapidfuzz del candidato propuesto (punto A.5). 100.0 para
    # las categorías "ciertas" (variante, apresa, ortografica, normalizacion,
    # ilegible: no hay ambigüedad real que puntuar). Para "desconeguda" es la
    # mejor puntuación encontrada (puede ser 0.0 si no hubo ningún candidato).
    puntuacio: float = 100.0
    # 2º y 3r candidato de la búsqueda difusa, seleccionables con un clic en
    # vez de teclearlos (punto A.5). Vacío salvo en "corregible"/"ambigua".
    alternatives: tuple[Candidato, ...] = ()
    # Si la propuesta viene del aprendizaje (punto D), cuántas veces la ha
    # confirmado el archivero. None en cualquier otra categoría.
    apresa_vegades: int | None = None


class Correccion(NamedTuple):
    """Una corrección ya validada (y posiblemente editada) por el usuario."""

    error: str
    correccion: str
    columnas: tuple[str, ...]


class PalabraAmbigua(NamedTuple):
    """
    Una palabra con dos o más candidatos plausibles, demasiado igualados entre
    sí para que el programa elija por su cuenta, y SIN base numérica para
    preferir uno (adendo, punto D / punto A.4).

    Desde el corte en 65 (punto A), el único caso que sigue aquí es el empate
    de la clave ortográfica (paso 4: dos formas distintas que colapsan a la
    misma clave sin dobles/ç, p. ej. "Colell"/"Collell"): no viene de
    rapidfuzz, así que no hay puntuación que desempate y no hay nada más
    razonable que ofrecer las opciones sin preseleccionar ninguna. El empate
    de la búsqueda difusa (paso 5, antes también AMBIGUA sin propuesta) ahora
    SÍ propone el mejor candidato igualmente (A.4) y se devuelve como
    Sugerencia de categoría "ambigua", no como PalabraAmbigua.

    `opciones` nunca preselecciona ninguna: la elige el usuario, o escribe
    otra cosa.
    """

    palabra: str
    frecuencia: int
    columnas: tuple[str, ...]
    opciones: tuple[str, ...]


class ResultadoClasificacion(NamedTuple):
    """
    Resultado de clasificar_columna(), listo para que la interfaz lo presente.

    Ya no hay una lista `desconocidas` aparte: desde el corte en 65 (punto A),
    toda palabra sin candidato fiable también recibe una propuesta ("Desconegut",
    punto A.3) y se devuelve como Sugerencia de categoría "desconeguda" —al
    igual que las marcas de ilegibilidad, categoría "ilegible" (punto C). Quien
    presente el resultado cuenta esas categorías dentro de `sugerencias` para
    el resumen (p. ej. "· 12 il·legibles"), en vez de leer una lista aparte.
    """

    validas: int
    sugerencias: list[Sugerencia]
    ambiguas: list[PalabraAmbigua]


# --------------------------------------------------------------------------- #
# Fase 1: limpieza automática
# --------------------------------------------------------------------------- #

def limpiar_celda(celda):
    """
    Normaliza el contenido de una celda de texto.

    - Colapsa espacios múltiples, tabuladores y saltos de línea en un solo espacio.
    - Elimina símbolos sueltos al principio y al final (comillas, puntos, comas, guiones).
    - Elimina el espacio sobrante antes de un signo de puntuación.

    Los valores que no son cadenas (números, NaN, fechas) se devuelven intactos.
    """
    if not isinstance(celda, str):
        return celda

    celda = " ".join(celda.split())
    celda = celda.strip(SIMBOLOS_A_RECORTAR)
    celda = celda.replace(" .", ".").replace(" ,", ",").replace(" -", "-")

    # El strip inicial puede dejar espacios al descubierto: "  'Joan " -> "Joan"
    return celda.strip()


def es_columna_texto(serie: pd.Series) -> bool:
    """
    Indica si una columna puede contener texto.

    Se comprueban los dos dtypes porque pandas 2 devuelve `object` para las
    columnas de texto y pandas 3 devuelve `str`; comparar contra "object" a
    secas hace que la limpieza no se aplique nunca en pandas 3.
    """
    return pd.api.types.is_object_dtype(serie) or pd.api.types.is_string_dtype(serie)


def limpiar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica limpiar_celda() a todas las columnas de texto.

    Devuelve una copia: el DataFrame de entrada no se modifica.
    """
    limpio = df.copy()
    for col in limpio.columns:
        if es_columna_texto(limpio[col]):
            limpio[col] = limpio[col].map(limpiar_celda)
    return limpio


# --------------------------------------------------------------------------- #
# Fase 2: detección de errores
# --------------------------------------------------------------------------- #

def es_variante_genero(palabra1: str, palabra2: str) -> bool:
    """
    Indica si dos palabras son la misma raíz en géneros distintos.

    Es el filtro de falsos positivos más importante del programa: en un registro
    parroquial, "Miquel" y "Miquela" son dos personas distintas, no una errata,
    aunque rapidfuzz les dé un 92% de similitud. En cambio "Miquell" y "Miquel"
    sí es una errata, porque la letra añadida (una "l") no marca género.

    La comparación ignora mayúsculas y acentos: en catalán, "Antoni" y "Antònia"
    son la misma raíz en dos géneros, y sin quitar la tilde la comparación
    letra a letra no lo vería.
    """
    if not palabra1 or not palabra2:
        return False

    p1 = _normalizar(palabra1)
    p2 = _normalizar(palabra2)

    if p1 == p2:
        return False
    if abs(len(p1) - len(p2)) > 1:
        return False

    # Caso 1: misma longitud, solo cambia la última letra (Mariana / Mariano).
    if len(p1) == len(p2):
        if p1[:-1] != p2[:-1]:
            return False
        for fem, masc in PATRONES_GENERO:
            if p1.endswith(fem) and p2.endswith(masc):
                return True
            if p1.endswith(masc) and p2.endswith(fem):
                return True
        return False

    # Caso 2: una palabra es la otra más una letra final (Miquel / Miquela).
    corta, larga = (p1, p2) if len(p1) < len(p2) else (p2, p1)
    if corta == larga[:-1] and larga[-1] in LETRAS_FEMENINO:
        return True

    return False


def _extraer_palabras_generico(serie: pd.Series, forma_completa_conocida=None) -> list[str]:
    """
    Descompone una serie de celdas en palabras sueltas, con dos excepciones que
    se comprueban sobre la celda ENTERA antes de partirla:

      1. Marcas de ilegibilidad (punto C): "no llegible" debe llegar como un
         único token de dos palabras, no como "no" + "llegible" por separado
         (ninguna de las dos, sueltas, sería reconocible).
      2. `forma_completa_conocida`, si se indica (punto B.4): apellidos
         compuestos con espacio ("de Aguilar") que SÍ están en el vocabulario
         tal cual. Sin este paso, "de Aguilar" se partiría en "de" (partícula,
         descartada) y "Aguilar" (una forma distinta a la que corresponde), y
         el apellido compuesto no sería alcanzable nunca.
    """
    palabras: list[str] = []
    for valor in serie.dropna():
        if isinstance(valor, str):
            texto = valor.strip()
            if texto and es_marca_ilegible(texto):
                palabras.append(texto)
            elif texto and forma_completa_conocida is not None and forma_completa_conocida(texto):
                palabras.append(texto)
            else:
                palabras.extend(valor.split())
        else:
            palabras.append(str(valor).strip())
    return [p for p in palabras if p]


def extraer_palabras(serie: pd.Series) -> list[str]:
    """
    Descompone una serie de celdas en palabras sueltas.

    Necesario porque los registros contienen nombres compuestos ("Joan Miquel")
    y un error tipográfico afecta a una palabra, no a la celda entera.
    """
    return _extraer_palabras_generico(serie)


def extraer_palabras_llinatge(serie: pd.Series, forma_completa_conocida) -> list[str]:
    """
    Como extraer_palabras(), pero para columnas de apellidos (punto B.4): antes
    de partir una celda en palabras, comprueba si coincide TAL CUAL con una
    entrada del vocabulario de apellidos. `forma_completa_conocida` es un
    predicado (texto) -> bool; quien llama pasa normalmente
    `lambda t: es_forma_conocida(t, VOCABULARIO_LLINATGES)`. Se inyecta así
    para no importar core.vocabulario aquí (crearía un ciclo: vocabulario ya
    importa de este módulo).
    """
    return _extraer_palabras_generico(serie, forma_completa_conocida)


# --------------------------------------------------------------------------- #
# Punto B: columna "Nom", solo el primer nombre
# --------------------------------------------------------------------------- #

def primer_nom(celda):
    """
    Conserva únicamente el primer nombre de la celda (punto B, decisión
    cerrada del Archivo: la documentación histórica registraba varios nombres
    y la práctica archivística es quedarse con el primero).

    "El primer nombre" es la primera palabra que no sea partícula (de, del,
    d', la, na, en, los, las...); si la celda empieza por una o más
    partículas, se descartan y se toma la primera palabra real que sigue
    (B.2). Si TODA la celda son partículas (caso degenerado, no debería darse
    en la práctica) se devuelve tal cual: mejor no destruir el dato que
    quedarse con una cadena vacía.

    El import de PARTICULAS es local por la misma razón que en
    clasificar_columna(): core.vocabulario importa de este módulo, así que un
    import a nivel de módulo en los dos sentidos crearía un ciclo.
    """
    if not isinstance(celda, str):
        return celda

    from core.vocabulario import PARTICULAS

    for palabra in celda.split():
        if _normalizar(palabra) not in PARTICULAS:
            return palabra
    return celda


def truncar_columna_nom(df: pd.DataFrame, columna: str) -> pd.DataFrame:
    """
    Aplica primer_nom() a `columna` en todo el DataFrame. Devuelve una copia.

    Es un paso de normalización automática (como limpiar_dataframe()), no una
    corrección que el archivero deba validar fila a fila: comportamiento por
    defecto y único de la columna Nom, sin casilla opcional (B.5).
    """
    resultado = df.copy()
    resultado[columna] = resultado[columna].map(primer_nom)
    return resultado


def detectar_errores(
    palabras: Iterable[str],
    columnas: Sequence[str] = (),
    umbral: int = UMBRAL_SIMILITUD,
    longitud_minima: int = LONGITUD_MINIMA_PALABRA,
) -> list[Sugerencia]:
    """
    Propone correcciones agrupando variantes similares de una misma palabra.

    Sigue el criterio de OpenRefine: dentro de un grupo de formas parecidas,
    la más frecuente se considera la correcta y las minoritarias, erratas.

    `columnas` se guarda en cada sugerencia para poder acotar después el
    reemplazo a las columnas donde realmente se detectó el error, en vez de
    aplicarlo a todo el DataFrame.
    """
    serie = pd.Series(list(palabras), dtype="object").astype(str).str.strip()
    serie = serie[serie != ""]
    if serie.empty:
        return []

    frecuencias = serie.value_counts()
    palabras_unicas: list[str] = frecuencias.index.tolist()

    sugerencias: list[Sugerencia] = []
    procesados: set[str] = set()
    columnas = tuple(columnas)

    for palabra_correcta in palabras_unicas:
        if palabra_correcta in procesados or len(palabra_correcta) < longitud_minima:
            continue

        coincidencias = process.extract(
            palabra_correcta,
            palabras_unicas,
            scorer=fuzz.ratio,
            limit=10,
        )

        for candidata, score, _ in coincidencias:
            if candidata in procesados or candidata == palabra_correcta:
                continue
            if not umbral <= score < 100:
                continue
            if frecuencias[candidata] >= frecuencias[palabra_correcta]:
                continue
            if es_variante_genero(candidata, palabra_correcta):
                procesados.add(candidata)
                continue

            sugerencias.append(
                Sugerencia(
                    error=candidata,
                    correccion=palabra_correcta,
                    frecuencia=int(frecuencias[candidata]),
                    columnas=columnas,
                )
            )
            procesados.add(candidata)

        procesados.add(palabra_correcta)

    return sugerencias


# --------------------------------------------------------------------------- #
# Fase 2b: clasificación contra el vocabulario normalizado
# --------------------------------------------------------------------------- #

def clasificar_columna(
    palabras: Iterable[str],
    columnas: Sequence[str],
    vocabulario_id: str,
) -> ResultadoClasificacion:
    """
    Clasifica las palabras de una o varias columnas contra el vocabulario oficial.

    Cada palabra única cae en un estado de `core.vocabulario.Estado`, resuelto
    como una cascada (ver el docstring de `clasificar_palabra`): ilegible,
    tabla de variantes, aprendizaje, clave exacta, clave ortográfica y, por
    último, similitud difusa con corte en `UMBRAL_PROPUESTA` (punto A). Salvo
    dos excepciones, cada estado con propuesta se devuelve como Sugerencia:

      - DESCONOCIDA (ni el vocabulario ni la búsqueda difusa dieron nada por
        encima de UMBRAL_PROPUESTA) NO se convierte en Sugerencia directamente:
        antes pasa por `detectar_errores()`, la heurística de frecuencia
        original, que aquí actúa solo sobre lo que el vocabulario no pudo
        resolver, nunca sobre lo que ya validó. Así un error sistemático
        (mayoritario en el documento) se sigue detectando primero: su
        frecuencia ya no lo protege, porque la autoridad es el listado, no la
        mayoría. Si el destino de una de esas propuestas por frecuencia
        tampoco está en el vocabulario, se marca "frecuencia_no_verificada"
        (punto F). Solo lo que la heurística de frecuencia NO resuelve cae,
        por fin, a una Sugerencia "desconeguda" con propuesta "Desconegut"
        (punto A.3): así el archivero siempre recibe algo que aceptar, editar
        o descartar, nunca un campo vacío.
      - AMBIGUA con `opciones` pero SIN `propuesta` (el empate real de la
        clave ortográfica, paso 4 de la cascada: no hay puntuación que
        desempate) se devuelve aparte como PalabraAmbigua, sin preseleccionar
        ninguna opción. AMBIGUA CON propuesta (empate de la búsqueda difusa,
        paso 5, margen insuficiente: A.4) sí se propone como Sugerencia de
        categoría "ambigua", con las alternativas puntuadas para elegir con
        un clic.

    El import de `core.vocabulario` es local a la función porque ese módulo
    importa de este mismo archivo (`es_variante_genero`, `es_marca_ilegible`,
    `VALOR_DESCONEGUT`); un import a nivel de módulo en los dos sentidos
    crearía un ciclo.
    """
    from core.vocabulario import PARTICULAS, Estado, clasificar_palabra, clave, es_forma_conocida

    columnas = tuple(columnas)
    serie = pd.Series(list(palabras), dtype="object").astype(str).str.strip()
    serie = serie[serie != ""]
    if serie.empty:
        return ResultadoClasificacion(validas=0, sugerencias=[], ambiguas=[])

    frecuencias = serie.value_counts()

    validas = 0
    sugerencias: list[Sugerencia] = []
    ambiguas: list[PalabraAmbigua] = []
    # (frecuencia, puntuación, alternativas) de cada DESCONOCIDA: se
    # conservan para que, si la heurística de frecuencia no la resuelve, la
    # Sugerencia "desconeguda" final pueda mostrar qué se probó y se
    # descartó de verdad (puntuación real y candidatos, si los hubo), en vez
    # de un 0% sin nada detrás.
    desconocidas_info: dict[str, tuple[int, float | None, tuple]] = {}

    categoria_por_estado = {
        Estado.NORMALIZABLE: "normalizacion",
        Estado.VARIANTE: "variante",
        Estado.APRESA: "apresa",
        Estado.ORTOGRAFICA: "ortografica",
        Estado.CORREGIBLE: "corregible",
        Estado.ILEGIBLE: "ilegible",
    }

    for palabra, frecuencia in frecuencias.items():
        if clave(palabra) in PARTICULAS:
            continue

        clasificacion = clasificar_palabra(palabra, vocabulario_id)
        frecuencia = int(frecuencia)
        estado = clasificacion.estado

        if estado is Estado.VALIDA:
            validas += frecuencia
        elif estado is Estado.AMBIGUA:
            if clasificacion.propuesta is not None:
                # A.4: empate de la búsqueda difusa, margen insuficiente. Se
                # propone igual el mejor candidato; la fila queda marcada
                # "ambigua" para que el archivero sepa que hay competencia.
                sugerencias.append(
                    Sugerencia(
                        palabra,
                        clasificacion.propuesta,
                        frecuencia,
                        columnas,
                        categoria="ambigua",
                        puntuacio=clasificacion.puntuacio,
                        alternatives=clasificacion.alternatives,
                    )
                )
            else:
                # Empate real de la clave ortográfica (paso 4): sin puntuación
                # que desempate, no hay candidato preferible.
                ambiguas.append(PalabraAmbigua(palabra, frecuencia, columnas, clasificacion.opciones))
        elif estado is Estado.DESCONOCIDA:
            desconocidas_info[palabra] = (frecuencia, clasificacion.puntuacio, clasificacion.alternatives)
        else:
            sugerencias.append(
                Sugerencia(
                    palabra,
                    clasificacion.propuesta,
                    frecuencia,
                    columnas,
                    categoria=categoria_por_estado[estado],
                    puntuacio=clasificacion.puntuacio if clasificacion.puntuacio is not None else 100.0,
                    alternatives=clasificacion.alternatives,
                    apresa_vegades=clasificacion.veces_apresa,
                )
            )

    # Entre las desconocidas, la heurística de frecuencia agrupa las que se
    # parecen entre sí: si una forma ausente del listado aparece 40 veces bien
    # escrita y 2 con una errata, la mayoría dentro de ese grupo sigue delatándola.
    palabras_repetidas = [p for p, (f, _, _) in desconocidas_info.items() for _ in range(f)]
    sugerencias_frecuencia = detectar_errores(palabras_repetidas, columnas=columnas)
    for sugerencia in sugerencias_frecuencia:
        verificada = es_forma_conocida(sugerencia.correccion, vocabulario_id)
        categoria = "frecuencia" if verificada else "frecuencia_no_verificada"
        sugerencias.append(sugerencia._replace(categoria=categoria))

    # A.3: lo que ni el vocabulario ni la frecuencia resolvieron recibe la
    # propuesta por defecto "Desconegut", igual que una marca de ilegibilidad.
    resueltas_por_frecuencia = {s.error for s in sugerencias_frecuencia}
    for palabra, (frecuencia, puntuacio, alternatives) in desconocidas_info.items():
        if palabra in resueltas_por_frecuencia:
            continue
        sugerencias.append(
            Sugerencia(
                palabra,
                VALOR_DESCONEGUT,
                frecuencia,
                columnas,
                categoria="desconeguda",
                puntuacio=puntuacio if puntuacio is not None else 0.0,
                alternatives=alternatives,
            )
        )

    return ResultadoClasificacion(validas=validas, sugerencias=sugerencias, ambiguas=ambiguas)


def combinar_resultados(*resultados: ResultadoClasificacion) -> ResultadoClasificacion:
    """Suma varios ResultadoClasificacion (uno por columna/grupo) en uno solo."""
    validas = sum(r.validas for r in resultados)
    sugerencias = [s for r in resultados for s in r.sugerencias]
    ambiguas = [a for r in resultados for a in r.ambiguas]
    return ResultadoClasificacion(validas=validas, sugerencias=sugerencias, ambiguas=ambiguas)


# --------------------------------------------------------------------------- #
# Aplicación de las correcciones
# --------------------------------------------------------------------------- #

class DecisionFila(NamedTuple):
    """
    Una fila de revisión con su valor final, tal como la ve el archivero en
    el momento de pulsar "Acceptar els canvis" (punto E). Pura, sin ningún
    widget: la interfaz la construye leyendo sus campos de texto, y esta
    misma forma es la que se puede testear sin Tkinter.

    `propuesta_original` es la sugerencia automática con la que empezó la
    fila (`Sugerencia.correccion`) — o None para las filas AMBIGUA sin
    propuesta (empate real de la clave ortográfica, paso 5): ahí no hay "tal
    cual venía" con quien comparar.
    """

    error: str
    valor_final: str
    columnas: tuple[str, ...]
    propuesta_original: str | None


def preparar_aceptacion(
    filas: Iterable[DecisionFila],
) -> tuple[list[Correccion], list[tuple[str, str, tuple[str, ...]]]]:
    """
    Punto E: decide qué se aplica y qué se aprende a partir del valor final
    de cada fila activa (no descartada con ❌: quien llama no debe incluirlas).

    E.1: el campo de texto es siempre la fuente de verdad — la sugerencia
    automática original, un candidato elegido con los botones, o un texto
    escrito a mano, todos se tratan igual: lo que hay en el campo ahora.

    E.3: se aprende de toda fila cuyo valor final DIFIERE de la sugerencia
    automática original (candidato cambiado o texto escrito a mano). Las
    filas aceptadas tal cual venían (valor_final == propuesta_original) NO
    se aprenden. Una fila sin sugerencia original (propuesta_original=None,
    el empate ortográfico real) siempre cuenta como "distinta": no había
    nada que aceptar "tal cual".

    Filas con el campo vacío se ignoran, ni se aplican ni se aprenden: quien
    llama debe haberlas resuelto (rellenado) o descartado antes de llegar
    aquí. Las exclusiones de qué NO se aprende nunca (destino "Desconegut",
    palabras ya VALIDA) las aplica `core.vocabulario.registrar_aprendida()`,
    no esta función: aquí solo se decide "cambió o no cambió".
    """
    correcciones: list[Correccion] = []
    aprendizajes: list[tuple[str, str, tuple[str, ...]]] = []
    for fila in filas:
        valor_final = fila.valor_final.strip()
        if not valor_final:
            continue
        correcciones.append(Correccion(fila.error, valor_final, fila.columnas))
        if valor_final != fila.propuesta_original:
            aprendizajes.append((fila.error, valor_final, fila.columnas))
    return correcciones, aprendizajes


def corregir_texto(texto: str, error: str, correccion: str) -> str:
    """
    Sustituye `error` por `correccion` dentro de un texto, palabra a palabra.

    Es la pieza que arregla el fallo silencioso de la versión anterior:
    DataFrame.replace() con escalares exige que el valor de la celda coincida
    entero, así que "Joan Miquell" nunca se corregía. Aquí la sustitución ocurre
    dentro de la celda, respetando los límites de palabra:

        corregir_texto("Joan Miquell Pons", "Miquell", "Miquel")
        -> "Joan Miquel Pons"

    Los límites de palabra evitan que "Ana" toque "Anastasia".
    """
    if not isinstance(texto, str) or not error:
        return texto

    patron = re.compile(rf"(?<!\w){re.escape(error)}(?!\w)")
    return patron.sub(correccion.replace("\\", r"\\"), texto)


def aplicar_correcciones(
    df: pd.DataFrame,
    correcciones: Iterable[Correccion],
) -> tuple[pd.DataFrame, int]:
    """
    Aplica las correcciones validadas y devuelve (DataFrame nuevo, nº de celdas cambiadas).

    Dos garantías respecto a la versión anterior:
      - la sustitución es por palabra, no por celda completa;
      - cada corrección solo toca las columnas donde se detectó el error, de modo
        que arreglar un apellido no puede alterar la columna de nombres.
    """
    resultado = df.copy()
    celdas_modificadas = 0

    for correccion in correcciones:
        objetivo = [c for c in correccion.columnas if c in resultado.columns]
        if not objetivo:
            objetivo = [c for c in resultado.columns if es_columna_texto(resultado[c])]

        for col in objetivo:
            antes = resultado[col]
            despues = antes.map(
                lambda v: corregir_texto(v, correccion.error, correccion.correccion)
            )
            # Dos NaN nunca son iguales entre sí: hay que excluirlos del recuento.
            cambiadas = antes.ne(despues) & ~(antes.isna() & despues.isna())
            celdas_modificadas += int(cambiadas.sum())
            resultado[col] = despues

    return resultado, celdas_modificadas
