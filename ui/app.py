"""
Interfaz gráfica del corrector (CustomTkinter).

Esta capa solo se ocupa de mostrar cosas y recoger decisiones del usuario.
Toda la lógica de detección y corrección vive en core/cleaner.py y
core/vocabulario.py; la decisión de qué se aplica y qué se aprende al pulsar
"Acceptar els canvis" vive en core.cleaner.preparar_aceptacion() (punto E),
una función pura sin ningún widget, para poder testearla sin Tkinter. Los
colores y tipografías viven en ui/tema.py (punto B.4): ningún valor de color
suelto aquí.

Ejecutar desde la raíz del proyecto:
    python -m ui.app
"""

from __future__ import annotations

import csv
import logging
import os
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pandas as pd

# Permite ejecutar el archivo directamente (python ui/app.py) además de -m ui.app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import tema  # noqa: E402

from core.aprendizaje import ResultadoRegistro  # noqa: E402
from core.cleaner import (  # noqa: E402
    DecisionFila,
    ResultadoClasificacion,
    aplicar_correcciones,
    clasificar_columna,
    combinar_resultados,
    extraer_palabras,
    extraer_palabras_llinatge,
    limpiar_dataframe,
    preparar_aceptacion,
    truncar_columna_nom,
)
from core.vocabulario import (  # noqa: E402
    VARIANTS,
    VOCABULARIO_DISPONIBLE,
    VOCABULARIO_LLINATGES,
    VOCABULARIO_NOMS,
    LLINATGES,
    NOMS_DONES,
    NOMS_HOMES,
    es_forma_conocida,
    eliminar_aprendida,
    exportar_aprendidas_a_variants_xlsx,
    listar_aprendidas,
    registrar_aprendida,
)
from core.workbook_io import (  # noqa: E402
    FILTROS_DIALOGO,
    FormatoNoSoportado,
    abrir_libro,
    leer_tabla,
    ruta_de_salida,
)

logger = logging.getLogger(__name__)

# B.0/B.4: modo oscuro fijo -- la paleta de referencia es un fondo oscuro con
# acento teal, así que "System" dejaría de tener sentido en un equipo en modo
# claro. `set_default_color_theme` ya no aporta nada: los colores que importan
# se aplican explícitamente desde ui/tema.py en cada widget.
ctk.set_appearance_mode("dark")

# La fila 2 del Excel contiene las cabeceras -> header=1, datos desde la fila 3.
FILA_CABECERA = 1
PRIMERA_FILA_DATOS = FILA_CABECERA + 2

# Posiciones de columna esperadas: A=Any, B=Llinatge 1, C=Llinatge 2, D=Nom, E=Foli
IDX_LLINATGES = (1, 2)
IDX_NOM = 3

# Punto C: tamaño uniforme para TODA la columna de candidatos, tenga o no
# botones esa fila -- así los botones de aceptar/descartar quedan siempre
# alineados verticalmente (C.2) y ninguna fila fuerza el alto por culpa de
# un contenedor vacío sin tamaño explícito (punto B: CTkFrame() sin width ni
# height declarados por defecto pide 200x200; con pack_propagate(False) y un
# tamaño fijo, una fila sin candidatos ocupa exactamente lo mismo que una con
# ellos, ni un píxel más).
ANCHO_COLUMNA_CANDIDATS = 230
ALTO_FILA_CANDIDATS = 28
ANCHO_COLUMNA_PUNTUACIO = 90  # C.3: ancho fijo, no se desplaza según el texto

# Categorías "ciertas": no hay puntuación real que mostrar ni alternativas
# que ofrecer (sug.alternatives está vacío para todas ellas).
CATEGORIAS_CIERTAS = frozenset({"apresa", "variante", "ortografica", "normalizacion", "ilegible"})

# --------------------------------------------------------------------------- #
# Recursos gráficos (punto B): se cargan UNA vez al arrancar (ver
# LimpiadorApp._cargar_recursos), nunca por fila ni en caliente (B.3).
# --------------------------------------------------------------------------- #


def _base_recursos() -> str:
    """
    Directorio base para recursos de SOLO LECTURA empaquetados (assets/).

    Compilado con PyInstaller, esos archivos viven en `sys._MEIPASS` (el
    directorio temporal que el arrancador descomprime en cada ejecución), no
    junto al ejecutable; en desarrollo, en la raíz del proyecto. Sin esta
    función, el programa encontraría los assets en desarrollo y fallaría al
    compilar -- el error clásico de mezclar rutas de desarrollo con las del
    binario.

    OJO: esto es solo para lo que se LEE y viaja dentro del ejecutable. Los
    datos que el programa ESCRIBE (`correccions_apreses.json`) usan una base
    completamente distinta -- junto al ejecutable, nunca `_MEIPASS`, que se
    borra al cerrar -- y esa lógica ya vive aparte, en
    `core.aprendizaje._directorio_datos()`. No confundir las dos.
    """
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ruta_recurso(*partes: str) -> str:
    return os.path.join(_base_recursos(), *partes)


# B.2: tres archivos generados desde el PNG del Archivo (ver
# tools/generar_icono.py) -- máxima resolución, tamaño de banner, y el .ico
# multi-resolución de Windows.
RUTA_ICONO_PNG = _ruta_recurso("assets", "icona.png")
RUTA_ICONO_BANNER = _ruta_recurso("assets", "icona_64.png")
RUTA_ICONO_ICO = _ruta_recurso("assets", "icona.ico")

# Junto al ejecutable (no en _MEIPASS): igual que correccions_apreses.json,
# es algo que el programa ESCRIBE, no un recurso empaquetado. Reutilizado por
# main() para el último recinto y por aceptar_els_canvis() para cualquier
# fallo al aplicar/guardar -- ver el porqué en _registrar_error_critico().
RUTA_LOG_ERRORES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error_log.txt")

ETIQUETAS_DESGLOSE = (
    ("validas", "Vàlides"),
    ("variante", "Per taula (variants)"),
    ("apresa", "Apreses"),
    ("ortografica", "Ortogràfiques"),
    ("normalizacion", "Normalitzables"),
    ("corregible", "Corregibles"),
    ("ambigua", "Ambigües"),
    ("ilegible", "Il·legibles"),
    ("frecuencia", "Per freqüència"),
    ("frecuencia_no_verificada", "No verificades"),
    ("desconeguda", "Desconegudes"),
)

if not VOCABULARIO_DISPONIBLE:
    logger.warning(
        "No s'ha trobat cap vocabulari carregat (core/datos_vocabulario.py). "
        "El programa seguirà funcionant només amb l'heurística de freqüència."
    )
else:
    logger.info(
        "Vocabulari carregat: %d llinatges, %d noms (%d homes, %d dones).",
        len(LLINATGES),
        len(NOMS_HOMES) + len(NOMS_DONES),
        len(NOMS_HOMES),
        len(NOMS_DONES),
    )


class _FilaIntercambio:
    """
    Gestiona el intercambio de candidatos de una fila de Sugerencia (punto A).

    Antes, pulsar un botón de alternativa SOBREESCRIBÍA el campo de texto: lo
    que hubiera escrito o elegido antes se perdía sin forma de recuperarlo
    salvo recargando el archivo entero. Aquí, el campo y los botones
    comparten un conjunto FIJO de candidatos (la propuesta y sus
    alternativas, cada una con su puntuación): en todo momento, uno de ellos
    ocupa el campo y el resto ocupa los botones. Pulsar un botón intercambia
    su candidato con el que hay en el campo — la puntuación viaja con su
    palabra (A.1/A.2) — y los candidatos no mostrados en ese momento no
    desaparecen, solo esperan en otro botón (A.3).

    Si el usuario escribe a mano un valor que no es ninguno de los
    candidatos, ese texto se queda tal cual (no se toca nunca lo que hay en
    el campo salvo al pulsar un botón), pero el candidato que el campo tenía
    asignado hasta entonces queda "liberado": la próxima vez que se pulse
    cualquier botón, ese candidato liberado vuelve a aparecer como uno más,
    junto a los demás, en vez de quedarse perdido (A.4). Confirmar la fila
    siempre lee el texto literal del campo en ese momento (A.5); esta clase
    no interviene en absoluto en la confirmación.
    """

    def __init__(self, contenedor_botones, entry, actualizar_puntuacion_campo, candidatos):
        self._contenedor = contenedor_botones
        self._entry = entry
        self._actualizar_puntuacion_campo = actualizar_puntuacion_campo
        self._candidatos = list(candidatos)  # [(forma, puntuacio), ...], fijo, nunca se pierde nada
        self._indice_en_campo = 0 if self._candidatos else None
        self._redibujar_botones()

    def _indices_en_botones(self) -> list[int]:
        return [i for i in range(len(self._candidatos)) if i != self._indice_en_campo]

    def _redibujar_botones(self) -> None:
        for widget in self._contenedor.winfo_children():
            widget.destroy()
        for indice in self._indices_en_botones():
            forma, puntuacio = self._candidatos[indice]
            ctk.CTkButton(
                self._contenedor,
                text=f"{forma} ({puntuacio:.0f}%)",
                width=110,
                height=ALTO_FILA_CANDIDATS,
                fg_color=tema.TEAL_ACCENT_OSCURO,
                hover_color=tema.TEAL_ACCENT_OSCURO_HOVER,
                corner_radius=tema.RADIO_ESQUINA_FILA,  # B.3: se repite por fila, ver tema.py
                font=tema.fuente(),
                command=lambda idx=indice: self._pulsar(idx),
            ).pack(side="left", padx=2)

    def _liberar_si_edicion_manual(self) -> None:
        """A.4: si lo que hay en el campo ya no es el candidato que tenía
        asignado (el usuario escribió encima a mano), ese candidato deja de
        estar "en el campo" y vuelve a quedar disponible como botón."""
        if self._indice_en_campo is None:
            return
        forma_asignada = self._candidatos[self._indice_en_campo][0]
        if self._entry.get() != forma_asignada:
            self._indice_en_campo = None

    def _pulsar(self, indice: int) -> None:
        self._liberar_si_edicion_manual()
        forma, puntuacio = self._candidatos[indice]
        self._entry.delete(0, "end")
        self._entry.insert(0, forma)
        self._indice_en_campo = indice
        self._actualizar_puntuacion_campo(puntuacio)
        self._redibujar_botones()


class LimpiadorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Colab cleaner — Netejador de dades col·laboratives")
        self.geometry("1000x680")
        self.minsize(760, 520)  # B.7: usable a 1366x768 y en ventanas más pequeñas
        self.configure(fg_color=tema.FONDO_APP)

        self._icono_banner: ctk.CTkImage | None = None
        self._cargar_recursos()

        self.df: pd.DataFrame | None = None
        self.file_path = ""
        self.sugerencias_activas: list[tuple] = []
        self.ambiguas_activas: list[tuple] = []
        self.libro_original = None
        self.col_nom: str | None = None
        self.col_llinatges: list[str] = []
        self.ultimo_resultado: ResultadoClasificacion | None = None
        # Punto A: referencia a cada ventana secundaria mientras está abierta,
        # para poder traerla al frente en vez de abrir una segunda (A.5).
        self._ventanas_secundarias: dict[str, ctk.CTkToplevel] = {}

        self.setup_ui()

    @staticmethod
    def _aplicar_icono_ventana(ventana) -> None:
        """
        B.5: aplica el icono a `ventana` (principal o secundaria), detectando
        el sistema -- Windows admite `.ico` vía `iconbitmap()`; Linux/macOS
        no, así que ahí se usa `iconphoto()` con el PNG a máxima resolución.
        Si falta el archivo o falla la carga, se avisa por el log y se sigue
        sin icono: nunca debe impedir el arranque.
        """
        if sys.platform.startswith("win"):
            if not os.path.exists(RUTA_ICONO_ICO):
                logger.info("Icono no encontrado en %s; se usa el del sistema.", RUTA_ICONO_ICO)
                return
            try:
                ventana.iconbitmap(RUTA_ICONO_ICO)
            except tk.TclError as exc:
                logger.warning("No se pudo aplicar el icono (%s).", exc)
        else:
            if not os.path.exists(RUTA_ICONO_PNG):
                logger.info("Icona no trobada a %s; s'arrenca sense ella.", RUTA_ICONO_PNG)
                return
            try:
                imagen = tk.PhotoImage(file=RUTA_ICONO_PNG)
                ventana.iconphoto(True, imagen)
                # Sin esta referencia, el recolector de basura de Python
                # eliminaría la PhotoImage y el icono desaparecería aunque Tk
                # siga "usándola" internamente.
                ventana._icono_photoimage = imagen
            except tk.TclError as exc:
                logger.warning("No se pudo aplicar el icono (%s).", exc)

    def _cargar_recursos(self) -> None:
        """
        Carga los recursos gráficos una sola vez al arrancar (B.2/B.3): el
        icono de la ventana principal y el de la barra de tareas, y el de la
        escoba del banner (PNG con transparencia, ver assets/icona_64.png).
        Si falta cualquiera, o si Pillow no está disponible, la aplicación
        arranca igual, sin él -- nunca falla por esto (C.3).

        Empaquetado con PyInstaller: `assets/` no es un módulo importado (a
        diferencia del vocabulario), así que necesita
        `--add-data "assets;assets"` (Windows) o `--add-data "assets:assets"`
        (Linux/macOS) al compilar -- el separador cambia según el sistema.
        Las rutas se resuelven con `_ruta_recurso()`, que ya tiene en cuenta
        `sys._MEIPASS` para el ejecutable compilado.
        """
        self._aplicar_icono_ventana(self)

        if not os.path.exists(RUTA_ICONO_BANNER):
            logger.info("Icona del banner no trobada a %s; s'arrenca sense ella.", RUTA_ICONO_BANNER)
            return
        try:
            from PIL import Image

            imagen = Image.open(RUTA_ICONO_BANNER)
            self._icono_banner = ctk.CTkImage(light_image=imagen, dark_image=imagen, size=(64, 64))
        except Exception as exc:  # noqa: BLE001 - un icono que falla no debe tumbar el arranque
            logger.warning("No s'ha pogut carregar la icona del banner (%s).", exc)
            self._icono_banner = None

    # ------------------------------------------------------------------ #
    # Punto A: ventanas secundarias en primer plano
    # ------------------------------------------------------------------ #

    def _centrar_sobre_padre(self, ventana, ancho: int, alto: int) -> None:
        """A.4: centra `ventana` sobre la ventana principal, no en la esquina
        de pantalla (que es donde la coloca CTkToplevel por defecto)."""
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - ancho) // 2
        y = self.winfo_y() + (self.winfo_height() - alto) // 2
        ventana.geometry(f"{ancho}x{alto}+{max(x, 0)}+{max(y, 0)}")

    def _abrir_secundaria(self, clave: str, titulo: str, ancho: int, alto: int, poblar) -> ctk.CTkToplevel:
        """
        Abre una ventana secundaria al frente, con foco, centrada y modal
        (A.1-A.4); si ya hay una abierta bajo esa `clave`, la trae al frente
        en vez de abrir una segunda (A.5). `poblar(ventana)` construye su
        contenido una sola vez, al crearla.
        """
        existente = self._ventanas_secundarias.get(clave)
        if existente is not None and existente.winfo_exists():
            existente.lift()
            existente.focus_force()
            return existente

        ventana = ctk.CTkToplevel(self)
        ventana.title(titulo)
        self._aplicar_icono_ventana(ventana)  # B.5: también en las ventanas secundarias
        self._ventanas_secundarias[clave] = ventana

        def _al_cerrar() -> None:
            try:
                ventana.grab_release()
            except tk.TclError:
                pass
            self._ventanas_secundarias.pop(clave, None)
            ventana.destroy()

        ventana.protocol("WM_DELETE_WINDOW", _al_cerrar)

        poblar(ventana)
        self._centrar_sobre_padre(ventana, ancho, alto)

        # A.2: lift()+focus_force() alzan la ventana; un pulso breve de
        # "-topmost" fuerza que quede por delante incluso cuando el gestor de
        # ventanas ignora el foco solicitado por una app en segundo plano
        # (habitual en Windows). Se desactiva en el mismo paso siguiente: NO
        # debe quedar flotando sobre el resto de aplicaciones del sistema.
        # transient()+grab_set() se aplican con el mismo pequeño retardo,
        # porque la ventana todavía no está mapeada en el instante de crearla.
        ventana.attributes("-topmost", True)
        ventana.lift()
        ventana.focus_force()

        def _asentar() -> None:
            ventana.attributes("-topmost", False)
            ventana.transient(self)
            ventana.grab_set()  # A.3: modal mientras está abierta

        ventana.after(10, _asentar)
        return ventana

    @staticmethod
    def _texto_estado_inicial() -> str:
        if not VOCABULARIO_DISPONIBLE:
            return (
                "Esperant arxiu (.xlsx o .ods)...\n"
                "⚠ No hi ha vocabulari carregat: només s'utilitzarà la freqüència."
            )
        return (
            f"Esperant arxiu (.xlsx o .ods)... "
            f"Vocabulari: {len(LLINATGES)} llinatges, {len(NOMS_HOMES) + len(NOMS_DONES)} noms."
        )

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #

    def _boton(self, master, texto, comando, *, fg=None, hover=None, width=190, height=34) -> ctk.CTkButton:
        """Botón con icono+texto siempre visible (B.5) y estilo consistente."""
        return ctk.CTkButton(
            master,
            text=texto,
            command=comando,
            fg_color=fg or tema.GRIS_BOTON,
            hover_color=hover or tema.GRIS_BOTON_HOVER,
            text_color=tema.TEXTO_PRIMARIO,
            corner_radius=tema.RADIO_ESQUINA_BOTON,
            font=tema.fuente(),
            width=width,
            height=height,
        )

    def _construir_banner(self) -> None:
        """
        B.2: banner con la escoba a la IZQUIERDA (A.1) y, a su derecha, el
        nombre en dos pesos y el subtítulo debajo. Icono y bloque de texto
        van en el mismo frame `contenido`, empaquetados con `side="left"`
        sin `fill`: el gestor de geometría de Tk centra cada uno
        verticalmente en el hueco perpendicular a la dirección de empaquetado
        por defecto, así que el icono queda centrado respecto al bloque de
        texto sin más (A.2) con solo dejarlos así. Altura del banner fija
        (B.2) para no robar espacio al listado.
        """
        banner = ctk.CTkFrame(self, fg_color=tema.FONDO_BANNER, corner_radius=0, height=90)
        banner.pack(fill="x")
        banner.pack_propagate(False)

        # A.4: el lado derecho del banner queda deliberadamente libre -- un
        # futuro "versió X.Y · vocabulari compilat el ..." se empaquetaría
        # aquí con side="right", sin tocar el resto del banner.
        contenido = ctk.CTkFrame(banner, fg_color="transparent")
        contenido.pack(side="left", padx=24, pady=12)

        if self._icono_banner is not None:
            # A.3: separación holgada (18px) entre el icono y el texto.
            ctk.CTkLabel(contenido, image=self._icono_banner, text="").pack(side="left", padx=(0, 18))

        bloque_texto = ctk.CTkFrame(contenido, fg_color="transparent")
        bloque_texto.pack(side="left")

        fila_titulo = ctk.CTkFrame(bloque_texto, fg_color="transparent")
        fila_titulo.pack(anchor="w")
        ctk.CTkLabel(
            fila_titulo, text="Colab", font=tema.fuente(tema.TAMANO_TITULO, "normal"), text_color=tema.TEXTO_PRIMARIO
        ).pack(side="left")
        ctk.CTkLabel(
            fila_titulo, text=" cleaner", font=tema.fuente(tema.TAMANO_TITULO, "bold"), text_color=tema.TEAL_ACCENT
        ).pack(side="left")

        ctk.CTkLabel(
            bloque_texto,
            text="Netejador de dades col·laboratives",
            font=tema.fuente(tema.TAMANO_SUBTITULO),
            text_color=tema.TEXTO_SECUNDARIO,
        ).pack(anchor="w")

    def _construir_peu_pagina(self) -> None:
        """Aviso de copyright, discreto, anclado siempre al borde inferior de
        la ventana (se empaqueta con side="bottom" antes que scroll_frame,
        para que reserve su franja antes de que este reclame el resto)."""
        ctk.CTkLabel(
            self,
            text="© Josep Pol i Font 2026",
            font=tema.fuente(11),
            text_color=tema.TEXTO_SECUNDARIO,
        ).pack(side="bottom", pady=(0, 6))

    def setup_ui(self) -> None:
        self._construir_banner()
        self._construir_peu_pagina()

        barra_superior = ctk.CTkFrame(self, fg_color="transparent")
        barra_superior.pack(pady=(14, 6))

        self.btn_cargar = self._boton(
            barra_superior, "📂 Carregar full de càlcul", self.iniciar_carga_hilo,
            fg=tema.TEAL_ACCENT_OSCURO, hover=tema.TEAL_ACCENT_OSCURO_HOVER, width=220,
        )
        self.btn_cargar.pack(side="left", padx=5)

        # F.2: el desglose ya no vive en una línea de estado permanente, sino
        # en esta ventana emergente. D.8/D.9/F.6: ninguno de los tres botones
        # de esta barra depende de tener un archivo cargado en este momento.
        self._boton(
            barra_superior, "📊 Dades de correcció", self.abrir_dades_correccio,
        ).pack(side="left", padx=5)

        self._boton(
            barra_superior, "📖 Correccions apreses", self.abrir_gestor_apreses,
        ).pack(side="left", padx=5)

        self._boton(
            barra_superior, "📤 Exportar apreses a VARIANTS", self.exportar_apreses_variants, width=230,
        ).pack(side="left", padx=5)

        self.label_estado = ctk.CTkLabel(
            self, text=self._texto_estado_inicial(), text_color=tema.TEXTO_SECUNDARIO, font=tema.fuente()
        )
        self.label_estado.pack(pady=5)

        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color=tema.FONDO_APP)
        self.scroll_frame.pack(pady=10, padx=15, fill="both", expand=True)

        # Contenedor fijo para el botón inferior: así no se acumulan frames
        # sueltos cada vez que se carga un archivo nuevo.
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")

    # ------------------------------------------------------------------ #
    # Carga y análisis
    # ------------------------------------------------------------------ #

    def iniciar_carga_hilo(self) -> None:
        self.file_path = filedialog.askopenfilename(filetypes=FILTROS_DIALOGO)
        if not self.file_path:
            return

        self.label_estado.configure(text="Carregant i analitzant dades... Per favor, espera.")
        self.btn_cargar.configure(state="disabled")

        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        for widget in self.button_frame.winfo_children():
            widget.destroy()
        self.button_frame.pack_forget()

        threading.Thread(target=self.procesar_archivo, daemon=True).start()

    def procesar_archivo(self) -> None:
        """Se ejecuta en un hilo aparte para no congelar la ventana."""
        try:
            df = leer_tabla(self.file_path, fila_cabecera=FILA_CABECERA)
            self.libro_original = abrir_libro(self.file_path)

            # FASE 1: limpieza automática de espacios y símbolos.
            df = limpiar_dataframe(df)

            col_llinatges = [df.columns[i] for i in IDX_LLINATGES]
            col_nom = df.columns[IDX_NOM]
            self.col_llinatges = col_llinatges
            self.col_nom = col_nom

            # Punto B: la columna Nom se queda solo con el primer nombre.
            # Automático, sin confirmación fila a fila (B.5), y ANTES de
            # clasificar (B.3), para que solo se compare/guarde ese nombre.
            df = truncar_columna_nom(df, col_nom)
            self.df = df

            # FASE 2: clasificación contra el vocabulario oficial, siempre a
            # nivel de palabra. Cada columna consulta su propio vocabulario:
            # nunca se puede "corregir" un nombre convirtiéndolo en apellido.
            # Punto B.4: los apellidos compuestos con espacio ("de Aguilar")
            # no se descomponen si coinciden tal cual con el vocabulario.
            palabras_llinatges = extraer_palabras_llinatge(
                df[col_llinatges].stack(future_stack=True),
                lambda t: es_forma_conocida(t, VOCABULARIO_LLINATGES),
            )
            palabras_nombres = extraer_palabras(df[col_nom])

            resultado_llinatges = clasificar_columna(
                palabras_llinatges, columnas=col_llinatges, vocabulario_id=VOCABULARIO_LLINATGES
            )
            resultado_nombres = clasificar_columna(
                palabras_nombres, columnas=[col_nom], vocabulario_id=VOCABULARIO_NOMS
            )
            resultado = combinar_resultados(resultado_llinatges, resultado_nombres)

            self.after(0, self.mostrar_resultado, resultado)

        except FormatoNoSoportado as exc:
            logger.warning("Formato rechazado: %s", exc)
            self.after(0, self.mostrar_error, str(exc))
        except Exception as exc:  # noqa: BLE001 - frontera del hilo: se reporta al usuario
            logger.exception("Fallo al procesar el archivo")
            self.after(0, self.mostrar_error, str(exc))

    # ------------------------------------------------------------------ #
    # Presentación de sugerencias
    # ------------------------------------------------------------------ #

    def _vocabulario_de_columnas(self, columnas: tuple) -> str:
        """A qué vocabulario consultar para validar una forma escrita a mano."""
        if self.col_nom is not None and self.col_nom in columnas:
            return VOCABULARIO_NOMS
        return VOCABULARIO_LLINATGES

    @staticmethod
    def _contar_categorias(resultado: ResultadoClasificacion) -> dict[str, int]:
        contadores = {cat: 0 for cat in tema.COLOR_POR_CATEGORIA}
        for s in resultado.sugerencias:
            contadores[s.categoria] = contadores.get(s.categoria, 0) + 1
        contadores["ambigua"] += len(resultado.ambiguas)
        return contadores

    def mostrar_resultado(self, resultado: ResultadoClasificacion) -> None:
        self.btn_cargar.configure(state="normal")
        self.sugerencias_activas = []
        self.ambiguas_activas = []
        self.ultimo_resultado = resultado

        # F.1: el desglose detallado ya no vive aquí, sino en la finestra
        # "Dades de correcció" (F.3); esta línia és només un resum breu.
        total_files = len(resultado.sugerencias) + len(resultado.ambiguas)
        if total_files == 0:
            resum = f"{resultado.validas} paraules, totes vàlides. Cap correcció pendent."
        else:
            resum = f"{total_files} files per revisar. Consulta «Dades de correcció» per al desglossament."
        if not VOCABULARIO_DISPONIBLE:
            resum = "⚠ Sense vocabulari carregat (només freqüència). " + resum
        self.label_estado.configure(text=resum)

        sugerencias_ordenadas = sorted(resultado.sugerencias, key=lambda s: -s.puntuacio)
        for sug in sugerencias_ordenadas:
            self._montar_fila_sugerencia(sug)
        for ambigua in resultado.ambiguas:
            self._montar_fila_ambigua(ambigua)

        self._montar_boton_inferior()

    def _fila_base(self, texto_izquierda, color):
        """Construye el frame y la etiqueta izquierda comunes a toda fila."""
        row_frame = ctk.CTkFrame(self.scroll_frame, fg_color=tema.FONDO_PANEL, corner_radius=tema.RADIO_ESQUINA)
        row_frame.pack(fill="x", pady=3, padx=5)

        ctk.CTkLabel(
            row_frame, text=texto_izquierda, width=170, anchor="e", text_color=color, font=tema.fuente()
        ).pack(side="left", padx=(14, 10), pady=8)
        ctk.CTkLabel(row_frame, text="➔", text_color=tema.TEXTO_SECUNDARIO, font=tema.fuente()).pack(side="left")
        return row_frame

    def _boton_descartar(self, master, frame) -> ctk.CTkButton:
        # B.3: sin redondeado (RADIO_ESQUINA_FILA=0) -- se repite por fila,
        # a diferencia de los botones que se construyen una sola vez.
        return ctk.CTkButton(
            master,
            text="❌ Descartar",
            width=100,
            fg_color=tema.ROJO_DESCARTAR,
            hover_color=tema.ROJO_DESCARTAR_HOVER,
            corner_radius=tema.RADIO_ESQUINA_FILA,
            font=tema.fuente(),
            command=lambda frm=frame: self.descartar_fila(frm),
        )

    def _montar_fila_sugerencia(self, sug) -> None:
        color = tema.COLOR_POR_CATEGORIA.get(sug.categoria, tema.COLOR_POR_CATEGORIA["frecuencia"])
        prefijo = "⚠ " if sug.categoria == "frecuencia_no_verificada" else ""

        row_frame = self._fila_base(f"{prefijo}({sug.frecuencia}) {sug.error}", color)

        entry_sugerencia = ctk.CTkEntry(
            row_frame, width=150, corner_radius=tema.RADIO_ESQUINA_FILA,
            fg_color=tema.FONDO_APP, text_color=tema.TEXTO_PRIMARIO, font=tema.fuente(),
        )
        entry_sugerencia.insert(0, sug.correccion)
        entry_sugerencia.pack(side="left", padx=10)

        # A.5/D.7: puntuación del candidato propuesto, o insignia de
        # aprendizaje en vez de puntuación (el archivero debe distinguir
        # siempre de dónde sale cada propuesta). C.3: ancho fijo.
        categoria_puntuada = sug.categoria not in CATEGORIAS_CIERTAS
        if sug.categoria == "apresa":
            texto_puntuacio = f"apresa · {sug.apresa_vegades}x"
        elif not categoria_puntuada:
            texto_puntuacio = "cert"
        else:
            texto_puntuacio = f"{sug.puntuacio:.0f}%"
        lbl_puntuacio = ctk.CTkLabel(
            row_frame, text=texto_puntuacio, width=ANCHO_COLUMNA_PUNTUACIO, text_color=color, font=tema.fuente()
        )
        lbl_puntuacio.pack(side="left", padx=5)

        # Punto B/C: contenedor de ancho y alto FIJOS para la columna de
        # candidatos, la tenga o no esta fila -- así ninguna fila reserva de
        # más (B) y aceptar/descartar quedan siempre en la misma columna (C.2).
        contenedor_botones = ctk.CTkFrame(
            row_frame, fg_color="transparent", width=ANCHO_COLUMNA_CANDIDATS, height=ALTO_FILA_CANDIDATS
        )
        contenedor_botones.pack(side="left")
        contenedor_botones.pack_propagate(False)
        if sug.alternatives:
            candidatos = [(sug.correccion, sug.puntuacio)] + [
                (a.forma, a.puntuacio) for a in sug.alternatives
            ]
            _FilaIntercambio(
                contenedor_botones,
                entry_sugerencia,
                (lambda p: lbl_puntuacio.configure(text=f"{p:.0f}%")) if categoria_puntuada else (lambda _: None),
                candidatos,
            )

        self._boton_descartar(row_frame, row_frame).pack(side="left", padx=(5, 14))

        self.sugerencias_activas.append((sug, entry_sugerencia, row_frame))

    def _montar_fila_ambigua(self, ambigua) -> None:
        """
        Empate real de la clave ortográfica (paso 5 de la cascada): dos formas
        distintas sin ninguna puntuación que las desempate. Ningún candidato
        preseleccionado: la elige el usuario, o escribe otra cosa.
        """
        row_frame = self._fila_base(f"({ambigua.frecuencia}) {ambigua.palabra}", tema.COLOR_AMBIGUA_ORTOGRAFICA)

        entry = ctk.CTkEntry(
            row_frame, width=150, placeholder_text="Tria una opció…", corner_radius=tema.RADIO_ESQUINA_FILA,
            fg_color=tema.FONDO_APP, text_color=tema.TEXTO_PRIMARIO, font=tema.fuente(),
        )
        entry.pack(side="left", padx=10)

        ctk.CTkLabel(
            row_frame, text="cert", width=ANCHO_COLUMNA_PUNTUACIO,
            text_color=tema.COLOR_AMBIGUA_ORTOGRAFICA, font=tema.fuente(),
        ).pack(side="left", padx=5)

        contenedor_botones = ctk.CTkFrame(
            row_frame, fg_color="transparent", width=ANCHO_COLUMNA_CANDIDATS, height=ALTO_FILA_CANDIDATS
        )
        contenedor_botones.pack(side="left")
        contenedor_botones.pack_propagate(False)
        for opcion in ambigua.opciones:
            ctk.CTkButton(
                contenedor_botones,
                text=opcion,
                width=70,
                height=ALTO_FILA_CANDIDATS,
                fg_color=tema.MORADO_BOTON,
                hover_color=tema.MORADO_BOTON_HOVER,
                corner_radius=tema.RADIO_ESQUINA_FILA,  # B.3: se repite por fila, ver tema.py
                font=tema.fuente(),
                command=lambda ent=entry, valor=opcion: (ent.delete(0, "end"), ent.insert(0, valor)),
            ).pack(side="left", padx=2)

        self._boton_descartar(row_frame, row_frame).pack(side="left", padx=(5, 14))

        self.ambiguas_activas.append((ambigua, entry, row_frame))

    def _montar_boton_inferior(self) -> None:
        """D.4: en la barra inferior solo queda un botón (punto E), destacado
        como la acción principal (B.5)."""
        self.button_frame.pack(pady=12)
        ctk.CTkButton(
            self.button_frame,
            text="✔ Acceptar els canvis",
            command=self.aceptar_els_canvis,
            fg_color=tema.VERDE_ACEPTAR,
            hover_color=tema.VERDE_ACEPTAR_HOVER,
            corner_radius=tema.RADIO_ESQUINA_BOTON,
            font=tema.fuente(tema.TAMANO_SECCION, "bold"),
            width=240,
            height=42,
        ).pack(side="left", padx=5)

    # ------------------------------------------------------------------ #
    # Descarte de filas
    # ------------------------------------------------------------------ #

    def descartar_fila(self, frame) -> None:
        """E.2: una fila descartada con ❌ no se aplica ni se aprende: se
        quita de las listas activas antes de que "Acceptar els canvis"
        pueda verla."""
        frame.destroy()
        self.sugerencias_activas = [item for item in self.sugerencias_activas if item[2] is not frame]
        self.ambiguas_activas = [item for item in self.ambiguas_activas if item[2] is not frame]

    # ------------------------------------------------------------------ #
    # Punto E: botón único "Acceptar els canvis"
    # ------------------------------------------------------------------ #

    @staticmethod
    def _registrar_error_critico(contexto: str, exc: Exception) -> None:
        """
        Escribe el traceback completo en RUTA_LOG_ERRORES, junto al log
        normal. Necesario porque los callbacks de un botón (a diferencia de
        lo que escapa de mainloop(), capturado en main()) los intercepta
        Tkinter por su cuenta y por defecto solo los imprime por stderr: en
        un ejecutable compilado con --windowed no hay consola, así que ese
        stderr no lo ve nadie -- ni el usuario en el momento, ni nadie
        diagnosticándolo después. El archivo es el único rastro garantizado
        pase lo que pase con la consola.
        """
        logger.exception("Fallo al %s", contexto)
        try:
            with open(RUTA_LOG_ERRORES, "a", encoding="utf-8") as f:
                f.write(f"\n--- fallo al {contexto} ---\n")
                f.write(traceback.format_exc())
        except OSError:
            pass  # si ni siquiera se puede escribir el log, no hay más que hacer

    def _aprender_si_corresponde(self, error: str, nueva_palabra: str, columnas) -> None:
        """
        Registra una corrección aprendida y avisa si sustituye a una
        distinta ya aprendida antes (D.6). `registrar_aprendida()` ya
        descarta por su cuenta las correcciones hacia VALOR_DESCONEGUT (D.5)
        y las que no cambiarían nada sobre una grafía ya válida, devolviendo
        None en esos casos.
        """
        vocabulario_id = self._vocabulario_de_columnas(columnas)
        resultado = registrar_aprendida(error, nueva_palabra, vocabulario_id)
        if resultado is ResultadoRegistro.CAMBIADA:
            messagebox.showwarning(
                "Atenció",
                f"«{error}» ja s'havia après amb una altra correcció. "
                f"S'ha actualitzat a «{nueva_palabra}»: revisa si l'anterior era un error.",
            )

    def aceptar_els_canvis(self) -> None:
        if self.df is None or self.libro_original is None:
            return

        filas = [
            DecisionFila(sug.error, entry.get(), sug.columnas, sug.correccion)
            for sug, entry, _ in self.sugerencias_activas
        ] + [
            DecisionFila(amb.palabra, entry.get(), amb.columnas, None)
            for amb, entry, _ in self.ambiguas_activas
        ]

        vacias = sum(1 for f in filas if not f.valor_final.strip())
        if vacias:
            messagebox.showwarning(
                "Atenció",
                f"Hi ha {vacias} fila(es) sense cap valor. "
                "Omple-les o descarta-les (❌) abans de continuar.",
            )
            return

        correcciones, aprendizajes = preparar_aceptacion(filas)

        if not correcciones:
            messagebox.showinfo("Atenció", "No hi ha cap fila activa per aplicar.")
            return

        # E.4: confirmación modal, con el recuento de lo que va a pasar.
        confirmado = messagebox.askyesno(
            "Confirmació",
            "Segur que vols realitzar els canvis?\n\n"
            f"{len(correcciones)} correccions s'aplicaran.\n"
            f"{len(aprendizajes)} s'aprendran.",
        )
        if not confirmado:
            return  # E.6: no es toca ni s'aplica ni s'aprèn res; tot queda intacte

        # E.5: aplicar + guardar automàticament, sense cap clic més. Va ANTES
        # que el aprendizaje a propósito: si algo falla aquí, no queremos
        # "recordar" una corrección que nunca llegó a aplicarse a ningún
        # archivo real. Se captura cualquier excepción, no solo OSError:
        # un .ods concreto puede fallar dentro de escribir_datos()/guardar()
        # por motivos que no son de sistema de archivos (una estructura
        # interna inesperada, por ejemplo), y sin esto el fallo era invisible
        # -- silencioso del todo en un ejecutable --windowed, sin consola.
        nuevo_path = ruta_de_salida(self.file_path)
        try:
            df_actualizado, celdas = aplicar_correcciones(self.df, correcciones)
            self.libro_original.escribir_datos(df_actualizado, PRIMERA_FILA_DATOS)
            self.libro_original.guardar(nuevo_path)
        except Exception as exc:  # noqa: BLE001 - debe verse siempre, compilado o no
            self._registrar_error_critico("aplicar o guardar l'arxiu corregit", exc)
            self.mostrar_error(
                f"No s'ha pogut guardar l'arxiu corregit.\n\n{exc}\n\n"
                f"Detalls complets a:\n{RUTA_LOG_ERRORES}"
            )
            return

        for error, valor, columnas in aprendizajes:
            self._aprender_si_corresponde(error, valor, columnas)

        self.button_frame.pack_forget()
        self.label_estado.configure(text=f"Canvis guardats a:\n{nuevo_path}")
        messagebox.showinfo(
            "Èxit",
            f"Arxiu guardat correctament en:\n{nuevo_path}\n\n"
            f"{celdas} cel·les corregides. Formats originals mantinguts.",
        )

    # ------------------------------------------------------------------ #
    # Punto F: ventana "Dades de correcció"
    # ------------------------------------------------------------------ #

    def abrir_dades_correccio(self) -> None:
        self._abrir_secundaria("dades", "Dades de correcció", 480, 560, self._poblar_dades_correccio)

    def _poblar_dades_correccio(self, ventana) -> None:
        ventana.configure(fg_color=tema.FONDO_APP)
        contenedor = ctk.CTkScrollableFrame(ventana, width=450, height=520, fg_color=tema.FONDO_APP)
        contenedor.pack(pady=10, padx=10, fill="both", expand=True)

        ctk.CTkLabel(
            contenedor, text="Vocabulari carregat", font=tema.fuente(tema.TAMANO_SECCION, "bold"),
            text_color=tema.TEAL_ACCENT,
        ).pack(anchor="w", pady=(0, 5))
        for etiqueta, valor in (
            ("Noms (homes)", len(NOMS_HOMES)),
            ("Noms (dones)", len(NOMS_DONES)),
            ("Llinatges", len(LLINATGES)),
            ("Variants (taula del Arxiu)", len(VARIANTS)),
            ("Correccions apreses", len(listar_aprendidas())),
        ):
            ctk.CTkLabel(
                contenedor, text=f"{etiqueta}: {valor}", anchor="w", text_color=tema.TEXTO_PRIMARIO, font=tema.fuente()
            ).pack(fill="x")

        ctk.CTkLabel(contenedor, text="").pack(pady=5)
        ctk.CTkLabel(
            contenedor, text="Últim anàlisi", font=tema.fuente(tema.TAMANO_SECCION, "bold"),
            text_color=tema.TEAL_ACCENT,
        ).pack(anchor="w", pady=(0, 5))

        if self.ultimo_resultado is None:
            ctk.CTkLabel(
                contenedor, text="Encara no s'ha analitzat cap arxiu.", anchor="w",
                text_color=tema.TEXTO_SECUNDARIO, font=tema.fuente(),
            ).pack(fill="x")
            return

        contadores = self._contar_categorias(self.ultimo_resultado)
        contadores["validas"] = self.ultimo_resultado.validas
        for clave, etiqueta in ETIQUETAS_DESGLOSE:
            ctk.CTkLabel(
                contenedor, text=f"{etiqueta}: {contadores[clave]}", anchor="w",
                text_color=tema.TEXTO_PRIMARIO, font=tema.fuente(),
            ).pack(fill="x")

        # F.5: el CSV de lo pendiente de revisar vive aquí, no en la barra inferior.
        self._boton(contenedor, "📤 Exportar per revisar (CSV)", self.exportar_csv, width=220).pack(pady=15)

    # ------------------------------------------------------------------ #
    # Punto D.8: gestión de correcciones apreses
    # ------------------------------------------------------------------ #

    def abrir_gestor_apreses(self) -> None:
        self._abrir_secundaria("apreses", "Correccions apreses", 650, 400, self._construir_gestor_apreses)

    def _construir_gestor_apreses(self, ventana) -> None:
        ventana.configure(fg_color=tema.FONDO_APP)
        contenedor = ctk.CTkScrollableFrame(ventana, width=620, height=350, fg_color=tema.FONDO_APP)
        contenedor.pack(pady=10, padx=10, fill="both", expand=True)
        self._poblar_gestor_apreses(contenedor)

    def _poblar_gestor_apreses(self, contenedor) -> None:
        for widget in contenedor.winfo_children():
            widget.destroy()

        entradas = listar_aprendidas()
        if not entradas:
            ctk.CTkLabel(
                contenedor, text="Encara no hi ha cap correcció apresa.",
                text_color=tema.TEXTO_SECUNDARIO, font=tema.fuente(),
            ).pack(pady=20)
            return

        for entrada in entradas:
            fila = ctk.CTkFrame(contenedor, fg_color=tema.FONDO_PANEL, corner_radius=tema.RADIO_ESQUINA)
            fila.pack(fill="x", pady=3, padx=5)

            texto = (
                f"[{entrada.vocabulario}] {entrada.forma_erronea} → {entrada.correccion}"
                f"   ·   {entrada.veces} vegades   ·   última: {entrada.ultima_confirmacion}"
            )
            ctk.CTkLabel(
                fila, text=texto, anchor="w", text_color=tema.TEXTO_PRIMARIO, font=tema.fuente()
            ).pack(side="left", padx=10, pady=6, fill="x", expand=True)

            ctk.CTkButton(
                fila,
                text="🗑️ Esborrar",
                width=100,
                fg_color=tema.ROJO_DESCARTAR,
                hover_color=tema.ROJO_DESCARTAR_HOVER,
                corner_radius=tema.RADIO_ESQUINA_BOTON,
                font=tema.fuente(),
                command=lambda e=entrada, c=contenedor: self._esborrar_apresa(e, c),
            ).pack(side="right", padx=8)

    def _esborrar_apresa(self, entrada, contenedor) -> None:
        """D.8: un error aprendido se repetiría indefinidamente sin esto."""
        eliminar_aprendida(entrada.forma_erronea, entrada.vocabulario)
        self._poblar_gestor_apreses(contenedor)

    # ------------------------------------------------------------------ #
    # Punto D.9: exportación a VARIANTS
    # ------------------------------------------------------------------ #

    def exportar_apreses_variants(self) -> None:
        destino = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="variants_apreses.xlsx",
        )
        if not destino:
            return

        n = exportar_aprendidas_a_variants_xlsx(destino)
        if n == 0:
            messagebox.showinfo("Exportar", "No hi ha cap correcció apresa per exportar.")
            return

        messagebox.showinfo(
            "Exportar",
            f"Exportades {n} correccions a:\n{destino}\n\n"
            "El Arxiu pot passar aquest fitxer amb --variants a "
            "tools/generar_vocabulario.py per promoure-les al vocabulari oficial.",
        )

    # ------------------------------------------------------------------ #
    # Exportar lo pendiente de revisar
    # ------------------------------------------------------------------ #

    def exportar_csv(self) -> None:
        """
        Exporta a CSV lo que sigue necesitando revisión: ambigües (con
        propuesta y sin ella), il·legibles y desconegudes. Es el diagnóstico
        de las lagunas del listado maestro: con qué el Archivo alimenta el
        vocabulario (si es un nombre legítimo que falta) o la tabla de
        variantes (si es una errata sistemática).
        """
        if self.ultimo_resultado is None:
            return

        categorias_revisar = {"ambigua", "ilegible", "desconeguda"}
        sugerencias_revisar = [
            s for s in self.ultimo_resultado.sugerencias if s.categoria in categorias_revisar
        ]
        if not sugerencias_revisar and not self.ultimo_resultado.ambiguas:
            messagebox.showinfo("Exportar", "No hi ha res pendent de revisar per exportar.")
            return

        destino = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="paraules_per_revisar.csv",
        )
        if not destino:
            return

        with open(destino, "w", newline="", encoding="utf-8-sig") as f:
            escritor = csv.writer(f)
            escritor.writerow(["tipus", "paraula", "frequencia", "columnes", "proposta", "puntuacio", "candidats"])
            for s in sugerencias_revisar:
                escritor.writerow(
                    [s.categoria, s.error, s.frecuencia, "|".join(s.columnas), s.correccion, s.puntuacio,
                     "|".join(f"{a.forma} ({a.puntuacio:.0f}%)" for a in s.alternatives)]
                )
            for a in self.ultimo_resultado.ambiguas:
                escritor.writerow(
                    ["ambigua_ortografica", a.palabra, a.frecuencia, "|".join(a.columnas), "", "", "|".join(a.opciones)]
                )

        messagebox.showinfo("Exportar", f"Exportat a:\n{destino}")

    def mostrar_error(self, mensaje: str) -> None:
        self.label_estado.configure(text="Ha ocorregut un error.")
        self.btn_cargar.configure(state="normal")
        messagebox.showerror("Error", mensaje)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        LimpiadorApp().mainloop()
    except Exception:  # noqa: BLE001 - último recinto: deja rastro antes de morir
        with open(RUTA_LOG_ERRORES, "w", encoding="utf-8") as f:
            f.write("Error al ejecutar el Revisor d'excels:\n\n")
            f.write(traceback.format_exc())
        messagebox.showerror(
            "Error", f"Ha ocorregut un error.\nDetalls guardats en: {RUTA_LOG_ERRORES}"
        )
        raise


if __name__ == "__main__":
    main()
