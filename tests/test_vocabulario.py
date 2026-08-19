"""
Tests de core/vocabulario.py y de su integración con core.cleaner.clasificar_columna.

Vocabulario de prueba pequeño, definido aquí mismo: nunca se importan los datos
reales del Archivo en los tests (Brief 5.4). Los índices reales del módulo se
sustituyen vía monkeypatch antes de cada test.

Cascada de resolución cubierta, de más a menos autoridad: tabla de variantes,
clave exacta, clave ortográfica, búsqueda difusa (con filtro de género antes del
margen). Ver el docstring de core/vocabulario.py para el detalle completo.

Ejecutar desde la raíz del proyecto:
    pytest -v
"""

import pandas as pd
import pytest

from core import aprendizaje
from core import vocabulario as voc
from core.cleaner import VALOR_DESCONEGUT, clasificar_columna
from core.normalizacion import clave
from core.vocabulario import (
    Estado,
    VOCABULARIO_LLINATGES,
    VOCABULARIO_NOMS,
    clasificar_palabra,
    es_forma_conocida,
)

# --------------------------------------------------------------------------- #
# Vocabulario de prueba
# --------------------------------------------------------------------------- #

HOMES = ("Miquel", "Antoni", "Joan", "Julià")
DONES = ("Miquela", "Antonina", "Maria", "Júlia")
LLINATGES = ("Rosselló", "Bennassar", "Ferrer", "Rosell", "de Aguilar")
VARIANTS = (("Bennasar", "Bennassar"),)


@pytest.fixture(autouse=True)
def vocabulario_de_prueba(monkeypatch):
    """
    Sustituye los índices reales del módulo por el vocabulario de prueba y
    limpia la caché de búsqueda difusa antes y después de cada test, para que
    un test no contamine al siguiente con resultados calculados sobre el
    vocabulario anterior (la caché está indexada solo por palabra+vocabulario,
    no sabe que el vocabulario ha cambiado entre tests).

    También reemplaza el estado del aprendizaje (punto D) por un diccionario
    vacío y desactiva `aprendizaje.guardar()` (un no-op): sin esto, cada test
    que confirma una corrección escribiría de verdad en
    `correccions_apreses.json`, en la raíz del proyecto, contaminando tests
    posteriores y el propio repositorio.
    """
    # Referencia a la función cacheada real, guardada ANTES de que algún test
    # pueda sustituir voc._mejores_candidatos por un lambda de prueba: si
    # llamáramos a cache_clear() sobre el atributo del módulo en el teardown,
    # podría estar apuntando al lambda del test (que no tiene cache_clear) en
    # vez de a la función original, según el orden de deshecho de monkeypatch.
    funcion_cacheada = voc._mejores_candidatos

    indice_noms, genero_noms = voc._indexar_noms(HOMES, DONES)
    indice_llinatges = voc._indexar(LLINATGES)
    formas_noms = tuple(dict.fromkeys(f for fs in indice_noms.values() for f in fs))
    formas_llinatges = tuple(dict.fromkeys(f for fs in indice_llinatges.values() for f in fs))

    monkeypatch.setattr(voc, "_INDICE_NOMS", indice_noms)
    monkeypatch.setattr(voc, "_GENERO_NOMS", genero_noms)
    monkeypatch.setattr(voc, "_INDICE_LLINATGES", indice_llinatges)
    monkeypatch.setattr(voc, "_FORMAS_NOMS", formas_noms)
    monkeypatch.setattr(voc, "_FORMAS_LLINATGES", formas_llinatges)
    monkeypatch.setattr(voc, "_INDICE_ORTOGRAFICO_NOMS", voc._indexar_ortografico(formas_noms))
    monkeypatch.setattr(voc, "_INDICE_ORTOGRAFICO_LLINATGES", voc._indexar_ortografico(formas_llinatges))
    monkeypatch.setattr(
        voc, "_INDICE_VARIANTS", {clave(v): c for v, c in VARIANTS}
    )
    monkeypatch.setattr(voc, "_APRENDIDAS", {})
    monkeypatch.setattr(aprendizaje, "guardar", lambda entradas: None)
    funcion_cacheada.cache_clear()
    yield
    funcion_cacheada.cache_clear()


# --------------------------------------------------------------------------- #
# Los estados básicos (clave exacta)
# --------------------------------------------------------------------------- #

def test_estado_valida_grafia_exacta():
    c = clasificar_palabra("Rosselló", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.VALIDA
    assert c.propuesta is None


def test_estado_normalizable_por_acentos_y_mayusculas():
    c = clasificar_palabra("ROSSELLO", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.NORMALIZABLE
    assert c.propuesta == "Rosselló"


@pytest.mark.parametrize("palabra", ["Desenfocat", "***", "?", "no llegible"])
def test_g7_marca_ilegible_es_ilegible_con_propuesta_desconegut(palabra):
    # G.7: máxima prioridad en la cascada, antes incluso que VARIANTS; nunca
    # se compara contra el vocabulario.
    c = clasificar_palabra(palabra, VOCABULARIO_LLINATGES)
    assert c.estado is Estado.ILEGIBLE
    assert c.propuesta == VALOR_DESCONEGUT


def test_estado_desconocida_sin_candidato():
    # A.3: por debajo de UMBRAL_PROPUESTA (o sin ningún candidato), se propone
    # igualmente "Desconegut" en vez de dejar la propuesta vacía.
    c = clasificar_palabra("Xkcdqwz", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.DESCONOCIDA
    assert c.propuesta == VALOR_DESCONEGUT


def test_desconocida_conserva_puntuacion_real_cuando_la_busqueda_si_se_ejecuto(monkeypatch):
    """
    Caso "Isabel" (diagnóstico con datos reales): la búsqueda difusa SÍ se
    ejecutó y SÍ encontró candidatos, pero ninguno llegó a UMBRAL_PROPUESTA.
    Antes, ese intento se descartaba por completo (puntuacio=None ->
    mostrado como 0%, sin alternativas). Ahora se conserva la puntuación real
    y las alternativas: la propuesta sigue siendo "Desconegut", pero ya no
    parece "no se intentó nada".
    """
    monkeypatch.setattr(
        voc, "_mejores_candidatos",
        lambda palabra, vocab: (("Elisabet", 57.0), ("Gabriela", 57.0), ("Albert", 50.0)),
    )
    c = clasificar_palabra("Isabel", VOCABULARIO_NOMS)
    assert c.estado is Estado.DESCONOCIDA
    assert c.propuesta == VALOR_DESCONEGUT
    assert c.puntuacio == 57.0
    assert c.alternatives == (voc.Candidato("Gabriela", 57.0), voc.Candidato("Albert", 50.0))


def test_desconocida_sin_ningun_candidato_no_tiene_puntuacion(monkeypatch):
    # A diferencia del caso anterior: aquí no hay NADA que mostrar, ni
    # siquiera un intento fallido, así que puntuacio sigue siendo None (la
    # interfaz lo trata como 0% igualmente, pero por una razón distinta).
    monkeypatch.setattr(voc, "_mejores_candidatos", lambda palabra, vocab: ())
    c = clasificar_palabra("Xkcdqwz", VOCABULARIO_LLINATGES)
    assert c.puntuacio is None
    assert c.alternatives == ()


def test_b3_clave_ambigua_es_ambigua_con_opciones_no_desconocida_muda(monkeypatch):
    """
    Análogo al caso real "María" contra "Marià"/"Maria" (el vocabulario del
    Archivo tiene ese par y otros nueve iguales); en el vocabulario de
    prueba, el par -ià/-ia es "Julià"/"Júlia". El programa sabe cuáles son
    las formas candidatas -- se ofrecen como opciones en vez de "Desconegut"
    sin nada detrás. Confirma también que la búsqueda difusa NUNCA se llega
    a ejecutar: el corte pasa en el paso de clave exacta, antes del paso 6.
    """
    llamadas = []

    def espia(palabra, vocabulario):
        llamadas.append(palabra)
        return ()

    monkeypatch.setattr(voc, "_mejores_candidatos", espia)
    c = clasificar_palabra("JULIA", VOCABULARIO_NOMS)
    assert c.estado is Estado.AMBIGUA
    assert c.propuesta is None
    assert set(c.opciones) == {"Julià", "Júlia"}
    assert llamadas == []


def test_b3_clave_ambigua_se_devuelve_como_palabraambigua_via_columna():
    resultado = clasificar_columna(
        ["JULIA"], columnas=("Nom",), vocabulario_id=VOCABULARIO_NOMS
    )
    assert not any(s.error == "JULIA" for s in resultado.sugerencias)
    assert len(resultado.ambiguas) == 1
    assert set(resultado.ambiguas[0].opciones) == {"Julià", "Júlia"}


# --------------------------------------------------------------------------- #
# J.4 — Tabla de variantes: máxima prioridad, gana a cualquier otra vía
# --------------------------------------------------------------------------- #

def test_tabla_variantes_gana_a_todo_lo_demas(monkeypatch):
    # Si "Bennasar" cayera a la búsqueda difusa, el candidato inventado abajo
    # se propondría en su lugar. La tabla de variantes se consulta antes: la
    # búsqueda difusa no debe ni llegar a ejecutarse.
    llamadas = []

    def espia(palabra, vocabulario):
        llamadas.append(palabra)
        return (("Ferrer", 99.0),)

    monkeypatch.setattr(voc, "_mejores_candidatos", espia)
    c = clasificar_palabra("Bennasar", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.VARIANTE
    assert c.propuesta == "Bennassar"
    assert llamadas == []


# --------------------------------------------------------------------------- #
# J.1/J.2 — Clave ortográfica
# --------------------------------------------------------------------------- #

def test_ortografica_una_sola_forma_candidata():
    # "Rossello" (sin acento) ya sería NORMALIZABLE por clave exacta si
    # coincidiera; probamos con una errata de dobles que solo coincide a nivel
    # ortográfico: "Roselo" (una sola 'l') colapsa igual que "Rosselló".
    c = clasificar_palabra("Roselo", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.ORTOGRAFICA
    assert c.propuesta == "Rosselló"


def test_ortografica_no_colapsa_apellidos_realmente_distintos():
    # "Rosell" está en el vocabulario de prueba como forma propia; su clave
    # ortográfica ("rosel") es DISTINTA de la de "Rosselló" ("roselo"): no deben
    # confundirse entre sí.
    c = clasificar_palabra("Rosell", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.VALIDA


def test_ortografica_dos_formas_candidatas_es_ambigua():
    indice_ortografico = dict(voc._INDICE_ORTOGRAFICO_LLINATGES)
    indice_ortografico["colel"] = ("Colell", "Collell")

    import pytest as _pytest  # evitar import global adicional solo para este test

    mp = _pytest.MonkeyPatch()
    mp.setattr(voc, "_INDICE_ORTOGRAFICO_LLINATGES", indice_ortografico)
    try:
        c = clasificar_palabra("Colel", VOCABULARIO_LLINATGES)
        assert c.estado is Estado.AMBIGUA
        assert set(c.opciones) == {"Colell", "Collell"}
        assert c.propuesta is None
    finally:
        mp.undo()


# --------------------------------------------------------------------------- #
# J.3 — Filtro de género ANTES del margen (caso Antònia/Antonina)
# --------------------------------------------------------------------------- #

def test_filtro_genero_antes_del_margen(monkeypatch):
    """
    "Antònia" no está en el listado. Sus dos candidatos por similitud son
    "Antonina" y "Antoni", con puntuaciones tan próximas que el margen por sí
    solo dejaría la palabra en AMBIGUA. Pero "Antoni" es variante de género de
    "Antònia": se descarta ANTES de mirar el margen, así que solo queda
    "Antonina" y se propone directamente, sin ambigüedad.
    """
    monkeypatch.setattr(
        voc,
        "_mejores_candidatos",
        lambda palabra, vocab: (("Antonina", 93.3), ("Antoni", 92.3)),
    )
    c = clasificar_palabra("Antònia", VOCABULARIO_NOMS)
    assert c.estado is Estado.CORREGIBLE
    assert c.propuesta == "Antonina"


def test_variante_de_genero_sin_alternativa_es_desconocida():
    # "Joana" no está en el listado; su único candidato razonable ("Joan") es
    # variante de género: tras descartarlo no queda nada real, pero A.3 sigue
    # dando una propuesta ("Desconegut") en vez de dejarla vacía.
    c = clasificar_palabra("Joana", VOCABULARIO_NOMS)
    assert c.estado is Estado.DESCONOCIDA
    assert c.propuesta == VALOR_DESCONEGUT


# --------------------------------------------------------------------------- #
# Punto A: corte en 65, sin regla de margen que bloquee la propuesta
# --------------------------------------------------------------------------- #

def test_un_solo_candidato_se_propone_sin_regla_de_margen(monkeypatch):
    monkeypatch.setattr(voc, "_mejores_candidatos", lambda palabra, vocab: (("Ferrer", 90.0),))
    c = clasificar_palabra("Ferrar", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.CORREGIBLE
    assert c.propuesta == "Ferrer"
    assert c.puntuacio == 90.0


def test_g1_score_70_se_propone_donde_antes_quedaba_desconocida(monkeypatch):
    # G.1: con el umbral antiguo (85) esto habría sido DESCONOCIDA; con el
    # corte en 65 (A.2) se propone directamente.
    monkeypatch.setattr(voc, "_mejores_candidatos", lambda palabra, vocab: (("Ferrer", 70.0),))
    c = clasificar_palabra("Ferrur", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.CORREGIBLE
    assert c.propuesta == "Ferrer"
    assert c.puntuacio == 70.0


def test_g2_score_60_propone_desconegut(monkeypatch):
    # G.2: por debajo de UMBRAL_PROPUESTA (65), la propuesta es "Desconegut",
    # no un campo vacío.
    monkeypatch.setattr(voc, "_mejores_candidatos", lambda palabra, vocab: (("Ferrer", 60.0),))
    c = clasificar_palabra("FXrrrr", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.DESCONOCIDA
    assert c.propuesta == VALOR_DESCONEGUT


def test_g3_empate_con_margen_insuficiente_propone_el_mejor_y_marca_ambigua(monkeypatch):
    # G.3/A.4: el margen (90 - 87 = 3 < MARGEN_MINIMO) ya NO bloquea la
    # propuesta: se propone el mejor candidato igual, y el segundo queda
    # disponible como alternativa puntuada para seleccionar con un clic.
    monkeypatch.setattr(
        voc, "_mejores_candidatos", lambda palabra, vocab: (("Ferrer", 90.0), ("Rosselló", 87.0))
    )
    c = clasificar_palabra("Xerrer", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.AMBIGUA
    assert c.propuesta == "Ferrer"
    assert c.puntuacio == 90.0
    assert c.alternatives == (voc.Candidato("Rosselló", 87.0),)


def test_margen_suficiente_propone_corregible_sin_marca_ambigua(monkeypatch):
    monkeypatch.setattr(
        voc, "_mejores_candidatos", lambda palabra, vocab: (("Ferrer", 95.0), ("Rosselló", 80.0))
    )
    c = clasificar_palabra("Xerrer", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.CORREGIBLE
    assert c.propuesta == "Ferrer"


# --------------------------------------------------------------------------- #
# Metadato de género: fusión de Homes y Dones
# --------------------------------------------------------------------------- #

def test_nombre_en_los_dos_generos_no_es_colision():
    indice, generos = voc._indexar_noms(("Desconegut",), ("Desconegut",))
    k = clave("Desconegut")
    assert indice[k] == ("Desconegut",)
    assert generos[k] == frozenset({"H", "D"})


def test_clave_ambigua_sin_coincidencia_exacta_es_ambigua_con_opciones():
    # "Julià" (H) y "Júlia" (D) normalizan a la misma clave ("julia"). B.3: el
    # programa sabe cuáles son las dos formas candidatas, así que se ofrecen
    # como opciones en vez de devolver "Desconegut" sin más (caso real:
    # "María" contra "Marià"/"Maria" en el vocabulario del Archivo).
    c = clasificar_palabra("JULIA", VOCABULARIO_NOMS)
    assert c.estado is Estado.AMBIGUA
    assert c.propuesta is None
    assert set(c.opciones) == {"Julià", "Júlia"}


def test_clave_ambigua_con_coincidencia_exacta_es_valida():
    assert clasificar_palabra("Júlia", VOCABULARIO_NOMS).estado is Estado.VALIDA
    assert clasificar_palabra("Julià", VOCABULARIO_NOMS).estado is Estado.VALIDA


# --------------------------------------------------------------------------- #
# Partículas
# --------------------------------------------------------------------------- #

def test_particulas_se_saltan():
    resultado = clasificar_columna(
        ["de", "Ferrer", "des", "sa"], columnas=("Llinatge 1",), vocabulario_id=VOCABULARIO_LLINATGES
    )
    assert resultado.validas == 1  # solo "Ferrer"
    assert not any(s.error in ("de", "des", "sa") for s in resultado.sugerencias)


# --------------------------------------------------------------------------- #
# Vocabulario vacío
# --------------------------------------------------------------------------- #

def test_vocabulario_vacio_no_rompe(monkeypatch):
    monkeypatch.setattr(voc, "_INDICE_NOMS", {})
    monkeypatch.setattr(voc, "_INDICE_LLINATGES", {})
    monkeypatch.setattr(voc, "_INDICE_ORTOGRAFICO_NOMS", {})
    monkeypatch.setattr(voc, "_INDICE_ORTOGRAFICO_LLINATGES", {})
    monkeypatch.setattr(voc, "_INDICE_VARIANTS", {})
    monkeypatch.setattr(voc, "_FORMAS_NOMS", ())
    monkeypatch.setattr(voc, "_FORMAS_LLINATGES", ())
    voc._mejores_candidatos.cache_clear()

    c = clasificar_palabra("Bennassar", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.DESCONOCIDA

    resultado = clasificar_columna(
        ["Bennassar"] * 5 + ["Benassar"] * 1,
        columnas=("Llinatge 1",),
        vocabulario_id=VOCABULARIO_LLINATGES,
    )
    assert any(s.error == "Benassar" and s.correccion == "Bennassar" for s in resultado.sugerencias)


def test_desconeguda_via_columna_conserva_puntuacion_y_alternativas(monkeypatch):
    """
    Igual que test_desconocida_conserva_puntuacion_real_cuando_la_busqueda_si_se_ejecuto
    pero comprobando el resultado final que ve la interfaz: la Sugerencia
    categoría "desconeguda" debe llevar la puntuación real (no 0.0 fijo) y
    las alternativas, para que el botón de intercambio (punto A) tenga algo
    que ofrecer en vez de quedarse sin candidatos.
    """
    monkeypatch.setattr(
        voc, "_mejores_candidatos",
        lambda palabra, vocab: (("Elisabet", 57.0), ("Gabriela", 57.0)),
    )
    resultado = clasificar_columna(
        ["Isabel"], columnas=("Nom",), vocabulario_id=VOCABULARIO_NOMS
    )
    desconegudes = [s for s in resultado.sugerencias if s.categoria == "desconeguda"]
    assert len(desconegudes) == 1
    sug = desconegudes[0]
    assert sug.correccion == VALOR_DESCONEGUT
    assert sug.puntuacio == 57.0
    assert sug.alternatives == (voc.Candidato("Gabriela", 57.0),)


# --------------------------------------------------------------------------- #
# Error sistemático mayoritario (la razón de ser del cambio original)
# --------------------------------------------------------------------------- #

def test_error_sistematico_mayoritario_se_detecta(monkeypatch):
    monkeypatch.setattr(
        voc,
        "_mejores_candidatos",
        lambda palabra, vocab: (("Ferrer", 95.0),) if palabra == "Ferrar" else (),
    )
    palabras = ["Ferrar"] * 10 + ["Ferrer"] * 1
    resultado = clasificar_columna(palabras, columnas=("Llinatge 1",), vocabulario_id=VOCABULARIO_LLINATGES)

    corregibles = [s for s in resultado.sugerencias if s.categoria == "corregible"]
    assert any(s.error == "Ferrar" and s.correccion == "Ferrer" for s in corregibles)
    assert resultado.validas == 1


# --------------------------------------------------------------------------- #
# J.5/J.6 — es_forma_conocida() y la incoherencia del punto F
# --------------------------------------------------------------------------- #

def test_es_forma_conocida():
    assert es_forma_conocida("Ferrer", VOCABULARIO_LLINATGES) is True
    assert es_forma_conocida("Ferrar", VOCABULARIO_LLINATGES) is False


def test_frecuencia_hacia_forma_no_verificada_se_marca(monkeypatch):
    """
    F: la heurística de frecuencia puede proponer una corrección hacia una
    forma que el propio vocabulario no reconoce (la mayoría del documento
    también puede estar equivocada). Esa propuesta debe marcarse como
    "frecuencia_no_verificada", no como "frecuencia" a secas.
    """
    monkeypatch.setattr(voc, "_mejores_candidatos", lambda palabra, vocab: ())
    # Ni "Xerrec" ni "Xerrecc" están en el vocabulario de prueba ni tienen
    # candidato: caen en desconocidas, y entre ellas la mayoría (6 apariciones)
    # se impone sobre la minoría (1 aparición) vía la heurística de frecuencia
    # de siempre. (Nota: la doble consonante final, no una vocal, evita que
    # es_variante_genero() confunda la errata con una marca de género.)
    palabras = ["Xerrec"] * 6 + ["Xerrecc"] * 1
    resultado = clasificar_columna(palabras, columnas=("Llinatge 1",), vocabulario_id=VOCABULARIO_LLINATGES)
    no_verificadas = [s for s in resultado.sugerencias if s.categoria == "frecuencia_no_verificada"]
    assert any(s.error == "Xerrecc" and s.correccion == "Xerrec" for s in no_verificadas)
    assert not any(s.categoria == "frecuencia" for s in resultado.sugerencias)


# --------------------------------------------------------------------------- #
# A.4 — el empate de la búsqueda difusa SÍ propone (Sugerencia categoría
# "ambigua"); solo el empate real de la clave ortográfica (paso 5, sin
# puntuación que desempate) se queda sin propuesta, como PalabraAmbigua.
# --------------------------------------------------------------------------- #

def test_empate_difuso_se_devuelve_como_sugerencia_ambigua_con_propuesta(monkeypatch):
    monkeypatch.setattr(
        voc, "_mejores_candidatos", lambda palabra, vocab: (("Ferrer", 90.0), ("Rosselló", 87.0))
    )
    resultado = clasificar_columna(
        ["Xerrer"], columnas=("Llinatge 1",), vocabulario_id=VOCABULARIO_LLINATGES
    )
    assert resultado.ambiguas == []  # no es el empate ortográfico: no va ahí

    ambiguas = [s for s in resultado.sugerencias if s.categoria == "ambigua"]
    assert len(ambiguas) == 1
    sug = ambiguas[0]
    assert sug.error == "Xerrer"
    assert sug.correccion == "Ferrer"
    assert sug.puntuacio == 90.0
    assert sug.alternatives == (voc.Candidato("Rosselló", 87.0),)


def test_empate_ortografico_real_se_devuelve_sin_propuesta_implicita():
    # A diferencia del empate difuso, aquí no hay puntuación que desempate:
    # PalabraAmbigua nunca lleva una "propuesta" implícita, solo opciones.
    indice_ortografico = dict(voc._INDICE_ORTOGRAFICO_LLINATGES)
    indice_ortografico["colel"] = ("Colell", "Collell")

    import pytest as _pytest  # evitar import global adicional solo para este test

    mp = _pytest.MonkeyPatch()
    mp.setattr(voc, "_INDICE_ORTOGRAFICO_LLINATGES", indice_ortografico)
    try:
        resultado = clasificar_columna(
            ["Colel"], columnas=("Llinatge 1",), vocabulario_id=VOCABULARIO_LLINATGES
        )
        assert not any(s.error == "Colel" for s in resultado.sugerencias)
        assert len(resultado.ambiguas) == 1
        ambigua = resultado.ambiguas[0]
        assert set(ambigua.opciones) == {"Colell", "Collell"}
        # PalabraAmbigua no tiene campo "correccion": no hay nada que aceptar
        # sin que el usuario elija primero (a diferencia de Sugerencia).
        assert not hasattr(ambigua, "correccion")
    finally:
        mp.undo()


# --------------------------------------------------------------------------- #
# Punto D — Aprendizaje de correcciones
# --------------------------------------------------------------------------- #

def test_apresa_se_propone_sin_pasar_por_la_busqueda_difusa(monkeypatch):
    # G.8: tras confirmar Alisebet -> Elisabet, una nueva clasificación debe
    # devolver "Elisabet" desde lo aprendido, NO "Alsebit" desde la búsqueda
    # difusa (que, sin aprendizaje, ganaría por puntuación: ver la prueba
    # diagnóstica anterior).
    llamadas = []

    def espia(palabra, vocabulario):
        llamadas.append(palabra)
        return (("Alsebit", 80.0), ("Elisabet", 75.0))

    monkeypatch.setattr(voc, "_mejores_candidatos", espia)

    voc.registrar_aprendida("Alisebet", "Elisabet", VOCABULARIO_NOMS)
    c = clasificar_palabra("Alisebet", VOCABULARIO_NOMS)

    assert c.estado is Estado.APRESA
    assert c.propuesta == "Elisabet"
    assert c.veces_apresa == 1
    assert llamadas == []  # ni siquiera se llegó a consultar la búsqueda difusa


def test_apresa_no_intercepta_una_grafia_ya_valida_con_la_misma_clave():
    """
    Regresión real (verificada contra correccions_apreses.json del Archivo):
    aprender "Carrio" -> "Carrió" (una corrección de acentuación) comparte
    clave con la forma YA VÁLIDA "Carrió". Sin esta comprobación, la próxima
    vez que aparece "Carrió" bien escrito, el paso de aprendizaje lo
    intercepta antes de la clave exacta y lo reclasifica como APRESA en vez
    de VALIDA -- mismo texto final, pero "vàlides" pierde esa frecuencia y se
    genera una fila de confirmación innecesaria. Con vocabulario de prueba:
    "Rosselló" es la forma válida; se simula haber aprendido "Rossello" (sin
    acento) -> "Rosselló", que comparte clave con la propia "Rosselló".
    """
    voc.registrar_aprendida("Rossello", "Rosselló", VOCABULARIO_LLINATGES)

    c_corregida = clasificar_palabra("Rossello", VOCABULARIO_LLINATGES)
    assert c_corregida.estado is Estado.APRESA
    assert c_corregida.propuesta == "Rosselló"

    c_ya_valida = clasificar_palabra("Rosselló", VOCABULARIO_LLINATGES)
    assert c_ya_valida.estado is Estado.VALIDA
    assert c_ya_valida.propuesta is None


def test_apresa_incrementa_contador_en_confirmaciones_repetidas():
    voc.registrar_aprendida("Alisebet", "Elisabet", VOCABULARIO_NOMS)
    voc.registrar_aprendida("Alisebet", "Elisabet", VOCABULARIO_NOMS)
    c = clasificar_palabra("Alisebet", VOCABULARIO_NOMS)
    assert c.veces_apresa == 2


def test_g10_variants_gana_a_una_entrada_aprendida_distinta():
    # G.10: VARIANTS (curada por el Archivo) tiene prioridad máxima, por
    # delante incluso de una corrección ya aprendida que diga otra cosa.
    # "Bennasar" -> "Bennassar" está en VARIANTS (fixture de este archivo).
    voc.registrar_aprendida("Bennasar", "Otracosa", VOCABULARIO_LLINATGES)
    c = clasificar_palabra("Bennasar", VOCABULARIO_LLINATGES)
    assert c.estado is Estado.VARIANTE
    assert c.propuesta == "Bennassar"


def test_g12_correccion_hacia_desconegut_no_se_aprende():
    resultado = voc.registrar_aprendida("Ferrar", VALOR_DESCONEGUT, VOCABULARIO_LLINATGES)
    assert resultado is None
    c = clasificar_palabra("Ferrar", VOCABULARIO_LLINATGES)
    assert c.estado is not Estado.APRESA


# --------------------------------------------------------------------------- #
# Punto B.4 — apellidos compuestos: la celda entera antes que descomponerla
# --------------------------------------------------------------------------- #

def test_g6_apellido_compuesto_es_valida_sin_descomponerse():
    # "de Aguilar" está en el vocabulario de prueba de LLINATGES tal cual.
    # extraer_palabras_llinatge() debe reconocerlo ANTES de partirlo, o
    # "de" (partícula) y "Aguilar" (una forma distinta) nunca llegarían a
    # clasificar_palabra() como la entrada compuesta real.
    from core.cleaner import extraer_palabras_llinatge

    serie = pd.Series(["de Aguilar"])
    palabras = extraer_palabras_llinatge(serie, lambda t: es_forma_conocida(t, VOCABULARIO_LLINATGES))
    assert palabras == ["de Aguilar"]

    resultado = clasificar_columna(
        palabras, columnas=("Llinatge 1",), vocabulario_id=VOCABULARIO_LLINATGES
    )
    assert resultado.validas == 1
    assert resultado.sugerencias == []
    assert resultado.ambiguas == []
