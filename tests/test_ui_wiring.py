"""
Comprobación estática de ui/app.py (puntos D.9/E/H), sin importar el módulo.

ui/app.py importa customtkinter, que la CI no instala a propósito (ver
.github/workflows/tests.yml: "los tests no abren ninguna ventana"). Para no
requerir un entorno gráfico, este test analiza el ÁRBOL SINTÁCTICO del
fichero en vez de ejecutarlo.

Desde el punto E, todo el flujo de "qué se aplica y qué se aprende" pasa por
`core.cleaner.preparar_aceptacion()` -- una función PURA, sin Tkinter, que sí
se testea en tests/test_cleaner.py de forma directa (H.1/H.2/H.3/H.6: "aceptar
sin cambios no aprende", "cambiar de candidato sí aprende", "escribir a mano sí
aprende", "fila descartada no se aplica ni se aprende"). Lo que queda por
comprobar aquí, a nivel de interfaz, es que el botón único delega en esa
función y que la confirmación (E.4/E.6) ocurre ANTES que cualquier efecto
(aplicar, aprender, guardar) -- nunca después.
"""

import ast
import os

RUTA_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "app.py")


def _arbol() -> ast.Module:
    with open(RUTA_APP, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=RUTA_APP)


def _nombres_de_llamadas(func: ast.FunctionDef) -> set[str]:
    """Nombres de todo lo que se llama dentro de una función (recursivo)."""
    nombres = set()
    for nodo in ast.walk(func):
        if isinstance(nodo, ast.Call):
            objetivo = nodo.func
            if isinstance(objetivo, ast.Name):
                nombres.add(objetivo.id)
            elif isinstance(objetivo, ast.Attribute):
                nombres.add(objetivo.attr)
    return nombres


def _lineas_de_llamada(func: ast.FunctionDef, nombre: str) -> list[int]:
    """Números de línea de cada llamada a `nombre` dentro de la función."""
    lineas = []
    for nodo in ast.walk(func):
        if isinstance(nodo, ast.Call):
            objetivo = nodo.func
            id_llamada = objetivo.id if isinstance(objetivo, ast.Name) else getattr(objetivo, "attr", None)
            if id_llamada == nombre:
                lineas.append(nodo.lineno)
    return lineas


def _metodos_de_la_clase(arbol: ast.Module, clase: str) -> dict[str, ast.FunctionDef]:
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef) and nodo.name == clase:
            return {n.name: n for n in nodo.body if isinstance(n, ast.FunctionDef)}
    raise AssertionError(f"No se encontró la clase {clase!r} en {RUTA_APP}")


def _metodo_aceptar():
    metodos = _metodos_de_la_clase(_arbol(), "LimpiadorApp")
    assert "aceptar_els_canvis" in metodos, "punto D.4/E: debe existir un único botón 'Acceptar els canvis'"
    return metodos["aceptar_els_canvis"]


# --------------------------------------------------------------------------- #
# D: el modelo antiguo de accept-por-tramo/individual ha desaparecido
# --------------------------------------------------------------------------- #

def test_d_no_quedan_metodos_del_modelo_antiguo():
    metodos = _metodos_de_la_clase(_arbol(), "LimpiadorApp")
    for nombre_obsoleto in ("aceptar_todos_cambios", "aplicar_cambio", "aplicar_cambio_ambigua", "guardar_archivo"):
        assert nombre_obsoleto not in metodos, f"{nombre_obsoleto} debería haberse fusionado en aceptar_els_canvis (D.2)"


# --------------------------------------------------------------------------- #
# E: el botón único delega en la función pura y guarda automáticamente
# --------------------------------------------------------------------------- #

def test_e1_aceptar_els_canvis_usa_preparar_aceptacion():
    llamadas = _nombres_de_llamadas(_metodo_aceptar())
    assert "preparar_aceptacion" in llamadas


def test_e4_muestra_dialogo_de_confirmacion():
    llamadas = _nombres_de_llamadas(_metodo_aceptar())
    assert "askyesno" in llamadas


def test_h5_confirmar_aplica_y_guarda_automaticamente():
    llamadas = _nombres_de_llamadas(_metodo_aceptar())
    assert "aplicar_correcciones" in llamadas
    assert "escribir_datos" in llamadas
    assert "guardar" in llamadas


def test_h4_e6_nada_ocurre_antes_de_confirmar():
    """
    La confirmación (askyesno) debe ocurrir ANTES, en el orden del código,
    que cualquier efecto: aplicar correcciones, aprender, o guardar. Así,
    cancelar el diálogo dentro de la propia función (el `if not confirmado:
    return` que sigue inmediatamente) deja esos efectos sin alcanzar nunca.
    """
    metodo = _metodo_aceptar()
    linea_confirmacion = min(_lineas_de_llamada(metodo, "askyesno"))
    for efecto in ("aplicar_correcciones", "escribir_datos", "guardar", "_aprender_si_corresponde"):
        lineas_efecto = _lineas_de_llamada(metodo, efecto)
        assert lineas_efecto, f"se esperaba una llamada a {efecto} dentro de aceptar_els_canvis"
        assert min(lineas_efecto) > linea_confirmacion, (
            f"{efecto} se llama antes de confirmar (línea {min(lineas_efecto)} <= {linea_confirmacion})"
        )


def test_h6_fila_descartada_se_quita_de_las_listas_activas():
    metodos = _metodos_de_la_clase(_arbol(), "LimpiadorApp")
    assert "descartar_fila" in metodos
    fuente = ast.dump(metodos["descartar_fila"])
    assert "sugerencias_activas" in fuente
    assert "ambiguas_activas" in fuente


# --------------------------------------------------------------------------- #
# D.5 sigue viviendo en core.vocabulario, no reimplementado en la interfaz
# --------------------------------------------------------------------------- #

def test_aprender_si_corresponde_delega_en_registrar_aprendida():
    metodos = _metodos_de_la_clase(_arbol(), "LimpiadorApp")
    assert "registrar_aprendida" in _nombres_de_llamadas(metodos["_aprender_si_corresponde"])
