"""
Tema visual de "Colab cleaner" (punto B).

Todos los colores del programa viven en este único módulo: ui/app.py no debe
tener ningún valor de color suelto (B.4). La aplicación fuerza el modo
oscuro (`ctk.set_appearance_mode("dark")` en ui/app.py) porque la paleta de
referencia es un fondo oscuro con acento teal; en modo claro no tendría
sentido, así que aquí los colores son valores únicos, no las tuplas
(claro, oscuro) que CustomTkinter admite normalmente.

Contraste verificado con la fórmula de luminancia relativa de WCAG 2.1
(texto sobre fondo, o texto blanco de botón sobre su color de fondo). Todos
los pares usados en la interfaz llegan como mínimo a 4.5:1 -- la cifra de
cada uno está documentada junto al color; la maqueta de referencia con texto
gris sobre teal oscuro que NO lo cumplía no se ha copiado (B.4).

No es un tema de CustomTkinter completo (no toca `set_default_color_theme`):
son constantes que ui/app.py aplica explícitamente donde hace falta, más
ligero que generar y cargar un JSON de tema.
"""

from __future__ import annotations

import customtkinter as ctk

# --------------------------------------------------------------------------- #
# Fondos
# --------------------------------------------------------------------------- #

FONDO_APP = "#101B1C"        # ventana principal y ventanas secundarias
FONDO_PANEL = "#16262A"      # filas de la lista, tarjetas
FONDO_BANNER = "#0C2E2C"     # franja del banner superior (color plano, B.2/B.3:
                              # nada de degradado generado por imagen -- un
                              # plano ya cumple "color plano o degradado muy
                              # suave" y no cuesta nada construirlo)

# --------------------------------------------------------------------------- #
# Texto
# --------------------------------------------------------------------------- #

TEXTO_PRIMARIO = "#EAF5F3"     # 15.8:1 sobre FONDO_APP, 14.0:1 sobre FONDO_PANEL
TEXTO_SECUNDARIO = "#A9C3C0"   # 9.4:1 / 8.4:1 -- subtítulos, texto de apoyo

# --------------------------------------------------------------------------- #
# Acento teal (identidad de marca)
# --------------------------------------------------------------------------- #

TEAL_ACCENT = "#2DD4BF"          # 9.4:1 sobre FONDO_APP, 7.8:1 sobre FONDO_BANNER
TEAL_ACCENT_OSCURO = "#0F766E"   # 5.5:1 con texto blanco -- botones secundarios
TEAL_ACCENT_OSCURO_HOVER = "#0B5C56"

# --------------------------------------------------------------------------- #
# Acciones -- oscurecidos respecto al tono "de tramo" equivalente para que el
# texto blanco del botón llegue a 4.5:1 (el verde/rojo claro de los tramos de
# abajo no lo cumplía como fondo de botón, solo como texto)
# --------------------------------------------------------------------------- #

VERDE_ACEPTAR = "#15803D"        # 5.0:1 con texto blanco
VERDE_ACEPTAR_HOVER = "#116830"
ROJO_DESCARTAR = "#DC2626"       # 4.8:1 con texto blanco
ROJO_DESCARTAR_HOVER = "#B91C1C"

# --------------------------------------------------------------------------- #
# Botones neutros (acciones secundarias: "Correccions apreses", "Dades de
# correcció", "Exportar...", "Esborrar" en el gestor)
# --------------------------------------------------------------------------- #

GRIS_BOTON = "#374151"           # 8.4:1 con texto blanco
GRIS_BOTON_HOVER = "#1F2937"

# Botones de opción de la fila AMBIGUA sin propuesta (empate ortográfico
# real): mismo morado de familia que COLOR_POR_CATEGORIA["ambigua"], pero
# más oscuro -- ese tono claro (5.91:1 como TEXTO) no llega a 4.5:1 con texto
# blanco como FONDO de botón (2.64:1); este sí (6.98:1).
MORADO_BOTON = "#7E22CE"
MORADO_BOTON_HOVER = "#6B21A8"

# --------------------------------------------------------------------------- #
# Tramos de confianza de cada Sugerencia.categoria, leídos como texto sobre
# FONDO_PANEL -- todos entre 5.65:1 y 8.96:1
# --------------------------------------------------------------------------- #

COLOR_POR_CATEGORIA: dict[str, str] = {
    "variante": "#5FB6FF",                  # 7.15:1 -- azul, tabla documentada del Archivo
    "apresa": "#34D399",                    # 8.12:1 -- verde intenso, aprendizaje confirmado
    "ortografica": "#2DD4BF",               # 8.39:1 -- teal, misma paraula, doble distinta
    "normalizacion": "#4ADE80",             # 8.96:1 -- verde, cambio seguro
    "corregible": "#F5A524",                # 7.65:1 -- naranja, corrección sin competencia
    "ambigua": "#C084FC",                   # 5.91:1 -- morado, empate (A.4)
    "ilegible": "#9CA3AF",                  # 6.15:1 -- gris, marca de ilegibilidad
    "desconeguda": "#F87171",               # 5.65:1 -- rojo, sin match real
    "frecuencia": "#F87171",                # 5.65:1 -- rojo, heurística de mayoría
    "frecuencia_no_verificada": "#FCA5A5",  # 8.23:1 -- rojo apagado, destino no verificado
}
COLOR_AMBIGUA_ORTOGRAFICA = COLOR_POR_CATEGORIA["ambigua"]

# --------------------------------------------------------------------------- #
# Geometría compartida
# --------------------------------------------------------------------------- #

RADIO_ESQUINA = 10   # esquinas redondeadas (B.0): frames, botones, entries
RADIO_ESQUINA_BOTON = 8

# B.3 (ligereza): el redondeado de CustomTkinter no es gratis -- dibuja cada
# esquina con varias primitivas de canvas por widget, y con corner_radius>0
# duplica con creces el tiempo de construir 300 filas frente a 0 (medido:
# ~4.3s a radio 0 frente a ~8s a radio 10 para el mismo lote de widgets). En
# los botones/entradas que se repiten POR FILA (candidatos, descartar, campo
# de texto) se usa 0: son docenas por archivo y nadie los mira aislados fila
# a fila. La tarjeta de la fila (RADIO_ESQUINA) y los botones que se
# construyen una sola vez (barra superior, "Acceptar els canvis", ventanas
# emergentes) sí llevan el redondeado completo: ahí no hay coste que escale.
RADIO_ESQUINA_FILA = 0

# --------------------------------------------------------------------------- #
# Tipografía -- fuente de sistema (B.4), nunca la fuente empaquetada por
# defecto de CustomTkinter. "Segoe UI" es la fuente de sistema en Windows (la
# plataforma del Archivo); en otros sistemas, Tk sustituye automáticamente
# por la fuente por defecto si "Segoe UI" no existe, sin fallar.
# --------------------------------------------------------------------------- #

FAMILIA_FUENTE = "Segoe UI"
TAMANO_BASE = 13       # B.4: mínimo 12px en el listado -- se lee durante horas
TAMANO_TITULO = 26
TAMANO_SUBTITULO = 13
TAMANO_SECCION = 15


_CACHE_FUENTES: dict[tuple[int, str], ctk.CTkFont] = {}


def fuente(size: int = TAMANO_BASE, weight: str = "normal") -> ctk.CTkFont:
    """
    Fuente de sistema con el peso indicado (B.4/B.2: pesos distintos en el
    banner), MEMOIZADA por (size, weight).

    Ligereza (B.3): `ctk.CTkFont(...)` no es gratis -- además de crear un
    `tkinter.font.Font`, CustomTkinter registra cada instancia en una lista
    global para reescalarla si cambia el DPI. Sin caché, una lista de 300
    filas (varias fuentes por fila: etiqueta, entrada, puntuación, botones)
    llegaba a construir miles de fuentes solo para pintar la lista una vez y
    tardaba segundos; con esta caché, cada combinación (tamaño, peso) se crea
    una única vez y se reutiliza el mismo objeto en cada fila.
    """
    clave = (size, weight)
    if clave not in _CACHE_FUENTES:
        _CACHE_FUENTES[clave] = ctk.CTkFont(family=FAMILIA_FUENTE, size=size, weight=weight)
    return _CACHE_FUENTES[clave]
