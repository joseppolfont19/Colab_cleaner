"""
Convierte los listados de nombres y apellidos normalizados en un módulo Python.

Por qué un módulo .py y no un JSON o el propio Excel: el programa se distribuye
compilado con PyInstaller, y un módulo importado se empaqueta dentro del ejecutable
automáticamente, sin `--add-data`, sin rutas relativas que se rompen al mover el
binario y sin depender de que nadie copie los Excel al lado. El vocabulario deja de
ser un archivo y pasa a ser parte del programa.

Uso:
    python tools/generar_vocabulario.py \
        --noms      llistat_noms.xlsx \
        --llinatges llistat_llinatges.xlsx

Opciones útiles si los archivos no tienen la forma esperada:
    --columna-noms "Nom normalitzat"    nombre o índice (0, 1, ...) de la columna
    --columna-llinatges 0
    --hoja-noms-homes Homes             hoja de --noms con los nombres masculinos
    --hoja-noms-dones Dones             hoja de --noms con los nombres femeninos
    --hoja-llinatges normalitzats       hoja de --llinatges (por defecto, la activa)
    --fila-cabecera 0                   fila donde están los encabezados
    --sortida core/datos_vocabulario.py

El módulo generado NO se edita a mano: si el listado cambia, se vuelve a ejecutar
este script y se recompila.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cleaner import limpiar_celda  # noqa: E402
from core.normalizacion import clave  # noqa: E402
from core.workbook_io import leer_tabla  # noqa: E402

RUTA_SALIDA_POR_DEFECTO = os.path.join("core", "datos_vocabulario.py")
HOJA_NOMS_HOMES_POR_DEFECTO = "Homes"
HOJA_NOMS_DONES_POR_DEFECTO = "Dones"


def resolver_columna(df: pd.DataFrame, columna: str | None) -> str:
    """Acepta un nombre de columna, un índice numérico, o nada (primera columna)."""
    if columna is None:
        return df.columns[0]
    if columna in df.columns:
        return columna
    try:
        return df.columns[int(columna)]
    except (ValueError, IndexError):
        disponibles = ", ".join(repr(c) for c in df.columns)
        raise SystemExit(
            "No existe la columna {!r}. Columnas disponibles: {}".format(
                columna, disponibles
            )
        )


def extraer_vocabulario(
    ruta: str,
    columna: str | None,
    fila_cabecera: int,
    hoja: str | int = 0,
) -> list[str]:
    """
    Lee una columna de un listado y devuelve las entradas únicas, ya limpias y ordenadas.

    Avisa por pantalla de los duplicados y de las colisiones, porque son justo los
    problemas que conviene arreglar en el listado maestro y no aquí.
    """
    df = leer_tabla(ruta, fila_cabecera=fila_cabecera, hoja=hoja)
    nombre_columna = resolver_columna(df, columna)
    print("  Columna utilizada: {!r}".format(nombre_columna))

    canonicas: dict[str, str] = {}
    descartadas = 0
    colisiones: list[tuple[str, str]] = []

    for valor in df[nombre_columna]:
        if not isinstance(valor, str):
            if pd.notna(valor):
                valor = str(valor)
            else:
                descartadas += 1
                continue

        entrada = limpiar_celda(valor)
        if not entrada:
            descartadas += 1
            continue

        k = clave(entrada)
        existente = canonicas.get(k)
        if existente is None:
            canonicas[k] = entrada
        elif existente != entrada:
            # Dos grafías distintas que normalizan igual: alguien tendrá que decidir
            # cuál es la buena. Se conserva la primera y se avisa.
            colisiones.append((existente, entrada))

    if descartadas:
        print("  Filas vacías o no textuales descartadas: {}".format(descartadas))
    if colisiones:
        print("  AVISO: {} colisiones (se conserva la primera grafía):".format(len(colisiones)))
        for conservada, ignorada in colisiones[:10]:
            print("    {!r} vs {!r}".format(conservada, ignorada))
        if len(colisiones) > 10:
            print("    ... y {} más".format(len(colisiones) - 10))

    entradas = sorted(canonicas.values(), key=clave)
    print("  Entradas únicas: {}".format(len(entradas)))
    return entradas


def avisar_inconsistencias_genero(homes: list[str], dones: list[str]) -> None:
    """
    Compara los nombres de Homes y Dones y avisa solo de las inconsistencias reales.

    Un nombre presente en las dos hojas con la misma grafía (p. ej. 'Desconegut')
    es válido en ambos géneros y no es un problema. Solo se avisa cuando la misma
    clave normalizada tiene grafías distintas en cada hoja, porque eso sí es algo
    que el Archivo tendría que revisar en el listado maestro.
    """
    por_clave_homes = {clave(n): n for n in homes}
    por_clave_dones = {clave(n): n for n in dones}
    comunes = por_clave_homes.keys() & por_clave_dones.keys()
    inconsistentes = [
        (por_clave_homes[k], por_clave_dones[k])
        for k in sorted(comunes)
        if por_clave_homes[k] != por_clave_dones[k]
    ]

    if not inconsistentes:
        return

    print(
        "  AVISO: {} nombres con grafía distinta entre Homes i Dones:".format(
            len(inconsistentes)
        )
    )
    for homes_forma, dones_forma in inconsistentes[:10]:
        print("    {!r} (Homes) vs {!r} (Dones)".format(homes_forma, dones_forma))
    if len(inconsistentes) > 10:
        print("    ... y {} más".format(len(inconsistentes) - 10))


def formatear_tupla(nombre: str, entradas: list[str]) -> str:
    """Escribe una tupla, una entrada por línea, para que los diffs sean legibles."""
    if not entradas:
        return "{} = ()\n".format(nombre)
    lineas = ["{} = (".format(nombre)]
    lineas.extend("    {!r},".format(e) for e in entradas)
    lineas.append(")\n")
    return "\n".join(lineas)


def extraer_variantes(
    ruta: str,
    columna_variante,
    columna_correccion,
    fila_cabecera: int,
    hoja: str | int,
) -> list[tuple[str, str]]:
    """
    Lee la tabla de variantes documentadas: dos columnas, (variante, forma correcta).

    A diferencia de extraer_vocabulario(), no deduplica por clave normalizada:
    aquí el orden de las columnas importa, y dos variantes distintas pueden
    apuntar legítimamente a la misma forma correcta.
    """
    df = leer_tabla(ruta, fila_cabecera=fila_cabecera, hoja=hoja)
    col_variante = resolver_columna(df, columna_variante)
    col_correccion = resolver_columna(df, columna_correccion)
    print("  Columnas utilizadas: variant={!r}, correcció={!r}".format(col_variante, col_correccion))

    variantes: list[tuple[str, str]] = []
    descartadas = 0
    for variante, correccion in zip(df[col_variante], df[col_correccion]):
        if not isinstance(variante, str) or not isinstance(correccion, str):
            descartadas += 1
            continue
        variante = limpiar_celda(variante)
        correccion = limpiar_celda(correccion)
        if not variante or not correccion:
            descartadas += 1
            continue
        variantes.append((variante, correccion))

    if descartadas:
        print("  Filas vacías o incompletas descartadas: {}".format(descartadas))
    print("  Variantes leídas: {}".format(len(variantes)))
    return variantes


def validar_variantes(variantes: list[tuple[str, str]], formas_validas: set[str]) -> None:
    """
    Aborta con un mensaje claro si alguna variante apunta a una forma que no
    existe en NOMS ni en LLINATGES: una tabla de variantes que corrige hacia
    algo que el propio vocabulario no reconoce sería la incoherencia del punto F
    otra vez, pero fabricada a mano en vez de por la heurística de frecuencia.
    """
    faltantes = sorted({correccion for _, correccion in variantes if correccion not in formas_validas})
    if not faltantes:
        return
    raise SystemExit(
        "La tabla de variantes apunta a {} forma(s) que no existen en NOMS ni en "
        "LLINATGES. Corrígelas en el archivo de variantes antes de regenerar:\n  {}".format(
            len(faltantes), "\n  ".join(repr(f) for f in faltantes)
        )
    )


def formatear_tupla_variantes(nombre: str, entradas: list[tuple[str, str]]) -> str:
    if not entradas:
        return "{} = ()\n".format(nombre)
    lineas = ["{} = (".format(nombre)]
    lineas.extend("    ({!r}, {!r}),".format(variante, correccion) for variante, correccion in entradas)
    lineas.append(")\n")
    return "\n".join(lineas)


def generar_modulo(
    noms_homes: list[str],
    noms_dones: list[str],
    llinatges: list[str],
    variantes: list[tuple[str, str]],
    origen: dict[str, str],
) -> str:
    cabecera = [
        '"""',
        "Vocabulario normalizado del Archivo. ARCHIVO GENERADO: no editar a mano.",
        "",
        "Para actualizarlo, modifica los listados maestros y vuelve a ejecutar:",
        "    python tools/generar_vocabulario.py --noms ... --llinatges ... [--variants ...]",
        "",
        "Generado el {}".format(dt.date.today().isoformat()),
        "Origen nombres:   {}".format(origen["noms"]),
        "Origen apellidos: {}".format(origen["llinatges"]),
        "Origen variantes: {}".format(origen.get("variants", "(ninguno)")),
        '"""',
        "",
        "# Grafías canónicas, tal como deben aparecer en los documentos corregidos.",
        "# NOMS_HOMES y NOMS_DONES se mantienen separadas porque el género es un dato",
        "# explícito del listado, no algo que haya que volver a inferir.",
        "",
    ]
    return (
        "\n".join(cabecera)
        + "\n"
        + formatear_tupla("NOMS_HOMES", noms_homes)
        + "\n"
        + formatear_tupla("NOMS_DONES", noms_dones)
        + "\n"
        + formatear_tupla("LLINATGES", llinatges)
        + "\n"
        + "# (variante, forma correcta): erratas documentadas por el Archivo que no\n"
        + "# se pueden derivar de acentos, dobles ni similitud (p. ej. una vocal que\n"
        + "# cambia el sonido sin acercarse lo bastante a nada más). Opcional: vacía\n"
        + "# si no se proporcionó --variants.\n"
        + formatear_tupla_variantes("VARIANTS", variantes)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera el módulo de vocabulario a partir de los listados normalizados."
    )
    parser.add_argument("--noms", required=True, help="Listado de nombres (.xlsx o .ods)")
    parser.add_argument("--llinatges", required=True, help="Listado de apellidos (.xlsx o .ods)")
    parser.add_argument("--columna-noms", default=None)
    parser.add_argument("--columna-llinatges", default=None)
    parser.add_argument(
        "--hoja-noms-homes",
        default=HOJA_NOMS_HOMES_POR_DEFECTO,
        help="Hoja de nombres masculinos dentro de --noms (nombre o índice).",
    )
    parser.add_argument(
        "--hoja-noms-dones",
        default=HOJA_NOMS_DONES_POR_DEFECTO,
        help="Hoja de nombres femeninos dentro de --noms (nombre o índice).",
    )
    parser.add_argument(
        "--hoja-llinatges",
        default=0,
        help="Hoja de apellidos dentro de --llinatges (nombre o índice; por defecto la activa).",
    )
    parser.add_argument(
        "--variants",
        default=None,
        help="Tabla opcional de variantes documentadas (.xlsx o .ods), dos columnas: "
        "variante y forma correcta. Si no se indica, VARIANTS queda vacía.",
    )
    parser.add_argument("--columna-variant", default=0, help="Nombre o índice (por defecto 0).")
    parser.add_argument("--columna-correccio", default=1, help="Nombre o índice (por defecto 1).")
    parser.add_argument(
        "--hoja-variants", default=0, help="Hoja de --variants (nombre o índice; por defecto la activa)."
    )
    parser.add_argument("--fila-cabecera", type=int, default=0)
    parser.add_argument("--sortida", default=RUTA_SALIDA_POR_DEFECTO)
    args = parser.parse_args()

    print("Leyendo nombres masculinos desde {} (hoja {!r})".format(args.noms, args.hoja_noms_homes))
    noms_homes = extraer_vocabulario(
        args.noms, args.columna_noms, args.fila_cabecera, hoja=args.hoja_noms_homes
    )

    print("Leyendo nombres femeninos desde {} (hoja {!r})".format(args.noms, args.hoja_noms_dones))
    noms_dones = extraer_vocabulario(
        args.noms, args.columna_noms, args.fila_cabecera, hoja=args.hoja_noms_dones
    )

    avisar_inconsistencias_genero(noms_homes, noms_dones)

    print("Leyendo apellidos desde {} (hoja {!r})".format(args.llinatges, args.hoja_llinatges))
    llinatges = extraer_vocabulario(
        args.llinatges, args.columna_llinatges, args.fila_cabecera, hoja=args.hoja_llinatges
    )

    if not noms_homes or not noms_dones or not llinatges:
        raise SystemExit("Alguno de los tres listados está vacío. Revisa hojas y columnas indicadas.")

    variantes: list[tuple[str, str]] = []
    origen_variants = "(ninguno)"
    if args.variants:
        print("Leyendo variantes desde {} (hoja {!r})".format(args.variants, args.hoja_variants))
        variantes = extraer_variantes(
            args.variants,
            args.columna_variant,
            args.columna_correccio,
            args.fila_cabecera,
            hoja=args.hoja_variants,
        )
        formas_validas = set(noms_homes) | set(noms_dones) | set(llinatges)
        validar_variantes(variantes, formas_validas)
        origen_variants = os.path.basename(args.variants)

    contenido = generar_modulo(
        noms_homes,
        noms_dones,
        llinatges,
        variantes,
        {
            "noms": os.path.basename(args.noms),
            "llinatges": os.path.basename(args.llinatges),
            "variants": origen_variants,
        },
    )

    destino = os.path.abspath(args.sortida)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(contenido)

    tamano = os.path.getsize(destino) / 1024
    print(
        "\nEscrito {} ({:.1f} KB): {} nombres masculinos, {} nombres femeninos, {} apellidos, "
        "{} variantes.".format(
            destino, tamano, len(noms_homes), len(noms_dones), len(llinatges), len(variantes)
        )
    )


if __name__ == "__main__":
    main()
