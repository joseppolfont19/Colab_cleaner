# Excel Name Cleaner

[![tests](https://github.com/USUARIO/excel-name-cleaner/actions/workflows/tests.yml/badge.svg)](https://github.com/USUARIO/excel-name-cleaner/actions/workflows/tests.yml)

Corrector tipográfico para tablas de nombres transcritos a una hoja de cálculo.
Detecta variantes erróneas de un mismo nombre o apellido y las propone al usuario
una por una, sin tocar nada sin confirmación. Admite **Excel (`.xlsx`) y
LibreOffice/OpenOffice (`.ods`)**.

![Captura de la aplicación](docs/captura.png)

---

## El problema

Un equipo de colaboradores transcribe registros históricos (bautismos, defunciones,
padrones) a hojas de cálculo. Cada uno lee una caligrafía distinta, con la
herramienta que tenga a mano —unos Excel, otros LibreOffice—, en jornadas largas.
El resultado es que **el mismo apellido acaba escrito de cinco maneras**:

| Any  | Llinatge 1  | Nom            |
|------|-------------|----------------|
| 1789 | Bennassar   | Joan Miquel    |
| 1790 | Benassar    | Joan Miquell   |
| 1792 | Roselló     | Joan Miquell   |

Para quien mira la tabla, son obviamente la misma familia. Para un `Ctrl+F`, para un
filtro de Excel o para una consulta SQL, son personas distintas. Una búsqueda de
"Bennassar" devuelve 6 fichas de las 7 que existen, y nadie se entera: **el error no
da un aviso, da un resultado incompleto**. En una base de datos genealógica eso
significa árboles rotos y ramas que no se conectan.

## Por qué no basta con buscar y reemplazar

La respuesta obvia es "buscar y reemplazar". No sirve, por tres razones:

1. **Hay que saber qué buscar.** Buscar y reemplazar corrige errores que ya conoces.
   El problema real es que no sabes cuáles son: nadie ha leído las 4.000 filas.
2. **Corrige de más.** Reemplazar `Ana` por `Anna` en toda la hoja convierte
   `Anastasia` en `Annastasia`. Excel no entiende de límites de palabra.
3. **No distingue el error de la variante legítima.** `Miquel` y `Miquela` se parecen
   muchísimo, pero son dos personas de distinto sexo. Un reemplazo masivo se las come.

Lo que hace falta es algo que **encuentre** los candidatos solo y luego **pregunte**.

## La solución, en dos fases

**Fase 1 — Limpieza automática.** Todo lo que no admite discusión se arregla sin
preguntar: espacios dobles, tabuladores, saltos de línea, apóstrofos y puntos sueltos
al principio de la celda, espacios delante de la puntuación. `"  'Joan   Miquel "`
queda en `"Joan Miquel"`.

**Fase 2 — Clasificación contra el vocabulario oficial.** El Archivo dispone de dos
listados normalizados (nombres y apellidos) que son la autoridad: cada palabra se
compara contra ellos, no contra lo que hizo la mayoría de colaboradores. Ver
[«El vocabulario normalizado»](#el-vocabulario-normalizado) más abajo para el
detalle. Si el listado no reconoce una palabra ni encuentra un candidato razonable,
entra en juego la heurística de frecuencia original (RapidFuzz, similitud ≥ 85%,
criterio de OpenRefine: la forma más repetida se asume correcta) — pero solo entre
esas palabras desconocidas, nunca sobre las que el vocabulario ya validó.

Cada propuesta se muestra con su número de apariciones y un campo editable, para
aceptarla, corregirla a mano o descartarla. El archivo original nunca se sobrescribe:
el resultado se guarda como `nombre_corregit`, con la extensión de partida.

## El vocabulario normalizado

El prototipo original detectaba erratas por frecuencia: si diez colaboradores
escriben "Bennasar", la mayoría se convierte en la norma y el error nunca se
detecta. El Archivo dispone ahora de dos listados oficiales —`docs/noms.xlsx`
(con hojas `Homes` y `Dones`) y `docs/llinatges.xlsx`— que pasan a ser la
autoridad: una palabra se valida contra el listado, no contra lo que hizo la
mayoría.

Cada palabra se resuelve como una **cascada**: se para en la primera regla que
acierta, de más a menos autoridad.

| # | Estado | Condición | Confianza |
|---|---|---|---|
| 0 | **Ilegible** | Es una marca de ilegibilidad ("desenfocat", "***", "s/n"...), no un dato | Máxima (propuesta fija "Desconegut") |
| 1 | — | Partícula ("de", "sa", "i"...) o palabra muy corta | (excluida, ni se analiza) |
| 2 | **Variante** | Está en la tabla de criterio de unificación fijada por el Archivo | Máxima |
| 3 | **Apresa** | El archivero ya confirmó esta misma corrección antes | Alta (marcada como aprendizaje, no como puntuación) |
| 4a | **Válida** | Está en el listado con esa misma grafía | — |
| 4b | **Normalizable** | Está en el listado pero difiere en acentos/mayúsculas | Alta |
| 5a | **Ortográfica** | No está, pero colapsa a una única forma del listado al unificar dobles (`ss`→`s`, `ll`→`l`...) y `ç`→`c` | Alta |
| 5b | **Ambigua** (sin puntuación) | Dos o más formas colapsan a la misma clave ortográfica: empate real, sin base numérica para elegir | — (se listan las opciones, sin preseleccionar) |
| 6a | **Corregible** | Mejor candidato ≥ 65% de similitud y sin competencia real (margen ≥ 5 puntos sobre el segundo) | Puntuada |
| 6b | **Ambigua** (con puntuación) | Mejor candidato ≥ 65%, pero el segundo le pisa los talones (margen < 5): se propone igual el mejor, marcado como competido | Puntuada, con alternativas seleccionables con un clic |
| 6c | **Desconocida** | Ningún candidato llega al 65% de similitud | — (propuesta fija "Desconegut") |

Desde la revisión de 2026, el criterio ya no es "cuándo el programa debe
callar" sino "cuándo debe proponer y dejar visible cuánto se puede fiar de
esa propuesta": **toda fila con propuesta muestra su puntuación** (o una
insignia "apresa" si viene del aprendizaje), y el archivero acepta, edita o
descarta con esa cifra delante — incluida la fila "sin nada mejor que
Desconegut", que existe para que nunca haya un campo vacío sin ninguna
propuesta que revisar. Solo el empate real de la clave ortográfica (5b, sin
ninguna puntuación de por medio) se sigue quedando sin propuesta implícita.

### Por qué hace falta la clave ortográfica

`Roselló` y `Rossell` se parecen mucho (93% y 92% de similitud contra el listado
real), pero son dos apellidos reales y distintos: fusionarlos sería justo el error
que el margen mínimo existe para evitar, y con un umbral fijo el programa los
habría dejado como "ambigua" sin poder distinguir un problema real de una simple
consonante doble. La clave ortográfica lo resuelve al nivel correcto: colapsa
`Roselló` y `Rosselló` a la misma forma "pelada" (`roselo`), porque son la misma
palabra con una consonante de más o de menos, mientras que `Rossell` colapsa a
otra distinta (`rosel`). Cuando la clave ortográfica encuentra una única forma
candidata, es una corrección de mayor confianza que la similitud difusa: no es
"se parece", es "es la misma palabra". Cuando encuentra dos o más (`Rosell` /
`Rossell` colapsan igual entre sí), pasa a ser "ambigua": el programa sabe cuáles
son las opciones, pero no puede elegir por su cuenta.

### El filtro de género se aplica antes del margen mínimo

Contra un listado de miles de entradas es frecuente que varias formas superen el
umbral de similitud a la vez. El margen mínimo (`MARGEN_MINIMO`, 5 puntos por
defecto) ya no bloquea la propuesta cuando no se alcanza —el Archivo prefiere
ver la puntuación y decidir, a no recibir nada—: si el mejor candidato no
supera al segundo por ese margen, se propone igual el mejor, pero la fila se
marca "ambigua" y el segundo candidato queda a un clic como alternativa. Pero
el filtro de género (`es_variante_genero()`, ver más abajo) se aplica
**antes** de mirar el margen, no después: si "Antònia" tiene como
candidatos a "Antonina" (93,3) y "Antoni" (92,3), un margen insuficiente sin más
la dejaría como ambigua entre las dos, cuando en realidad "Antoni" nunca fue un
destino válido —es la misma raíz en otro género, no una errata— y descartarlo
antes dejaría "Antonina" sola, sin ambigüedad. El género de los nombres es
además un dato explícito del listado (viene de qué hoja lo contiene: `Homes` o
`Dones`), no algo que haya que inferir; cuando el filtro heurístico ya descartó un
candidato por variante de género, ese dato se usa para descartar también
cualquier otro candidato exclusivamente del mismo género, aunque la heurística no
lo hubiera comparado directamente. Un nombre presente en las dos hojas con la
misma grafía (p. ej. "Desconegut") es válido en ambos géneros, no una colisión.

### La tabla de variantes: criterio de unificación, no corrección lingüística

`VARIANTS` no es un diccionario de erratas: es donde el Archivo fija su
**criterio de unificación para el buscador interno**, con prioridad máxima
sobre cualquier otra regla de la cascada (segunda solo tras las marcas de
ilegibilidad). La distinción importa porque el criterio no siempre coincide
con "la forma más correcta en catalán": `Antònia` → `Antonina` es la norma
del Archivo aunque `Antònia` sea perfectamente válida como nombre propio —lo
que se busca es que todas las fichas de la misma persona aterricen en la
misma grafía al buscar, no arbitrar cuál es "más catalana". Algunas entradas
sí son erratas no derivables de acentos, dobles ni similitud (`Bennassar` →
`Bennàsser`: una vocal que cambia el sonido sin acercarse lo bastante a nada
más por similitud), pero el mecanismo es el mismo.

Es opcional — si no se genera con `--variants`, esta categoría simplemente no
aparece nunca, sin romper nada más. El listado vigente (`docs/variants.xlsx`)
tiene 5 entradas iniciales confirmadas por el Archivo: `Antònia`→`Antonina`,
`Francisca`→`Francina`, `Caterina`→`Catalina`, `Joseph`→`Josep`,
`Bennassar`→`Bennàsser`. `tools/generar_vocabulario.py` aborta con un mensaje
claro si alguna variante apunta a una forma que no existe ni en `NOMS` ni en
`LLINATGES`, así que la tabla nunca puede corregir hacia algo que el propio
vocabulario tampoco reconoce.

**Nota de cobertura:** la tabla solo une lo que se le indica literalmente.
`Bennassar` (doble ene) está cubierta; `Benassar` (una sola ene, la otra
grafía histórica del mismo apellido) no lo está, y hoy cae en la búsqueda
difusa igual que cualquier otra palabra — ver la sección de la puntuación más
abajo para lo que eso implica en la práctica.

### Cuando la heurística de frecuencia no verifica su propio resultado

Entre las palabras "desconocida", la heurística de frecuencia original sigue
actuando (la forma minoritaria se propone hacia la mayoritaria dentro de ese
grupo), pero ninguna de las dos está en el vocabulario: puede que la mayoría del
documento también esté equivocada. Esas propuestas se marcan como
**"no verificadas"**: siguen siendo útiles para unificar grafías dentro del
documento, pero no hay que confundirlas con una forma oficial.

### Regenerar el vocabulario

`core/datos_vocabulario.py` es un módulo generado que **no se sube al repositorio**
(son datos internos del Archivo, excluidos en `.gitignore`) y el programa
funciona perfectamente sin él, solo con la heurística de frecuencia. Para
generarlo o actualizarlo a partir de los listados maestros:

```bash
python tools/generar_vocabulario.py --noms docs/noms.xlsx --llinatges docs/llinatges.xlsx
```

Añade `--variants tabla_variants.xlsx` (dos columnas: variante, forma correcta)
si el Archivo mantiene una tabla de erratas documentadas; el script aborta con un
mensaje claro si alguna variante apunta a una forma que no existe ni en `NOMS` ni
en `LLINATGES`. El script lee las hojas `Homes`/`Dones` de `--noms` por separado
(conservando el género) y la hoja activa de `--llinatges`; avisa por consola de
duplicados o grafías inconsistentes entre listados. Ver
`python tools/generar_vocabulario.py -h` para las opciones si los archivos no
tienen exactamente esta forma.

### De vuelta al Archivo: exportar lo que el vocabulario no resuelve

Las palabras "desconocida" y "ambigua" son, en realidad, el diagnóstico de las
lagunas del listado maestro. El botón *Exportar desconegudes/ambigües (CSV)*
vuelca ambas categorías —con su frecuencia, columna y candidatos, si los hay— a
un CSV. Ese archivo es el material con el que el Archivo alimenta el vocabulario
(si resulta ser un nombre legítimo que faltaba) o la tabla de variantes (si es
una errata sistemática): el vocabulario mejora con el uso, no es una foto fija.

## Solo el primer nombre

La documentación histórica que trata el Archivo registraba a veces cinco o
seis nombres por persona, y la práctica archivística es conservar solo el
primero — el diccionario de nombres está construido igual, sin compuestos.
`core.cleaner.truncar_columna_nom()` aplica esto automáticamente a la columna
Nom, sin casilla opcional ni confirmación fila a fila (es un paso de
normalización, como la limpieza de espacios, no una corrección que haya que
validar una por una), y **antes** de clasificar: solo se compara y se guarda
el primer nombre real, saltando las partículas iniciales ("de", "la", "los",
"d'"...) si las hay. `"Maria de los Dolores"` queda en `"Maria"`.

Los apellidos son harina de otro costal: nunca se truncan, y antes de partir
una celda en palabras se comprueba si coincide TAL CUAL con una entrada
compuesta del vocabulario (82 apellidos con espacio, como "de Aguilar"). Sin
esa comprobación, la celda se partiría en "de" (partícula, descartada) y
"Aguilar" (un apellido distinto), y el compuesto real no sería alcanzable
nunca.

## Marcas de ilegibilidad

Un transcriptor que no puede leer una palabra suele anotarlo en vez de dejar
la celda vacía: "desenfocat", "il·legible", "s/n", o simplemente asteriscos e
interrogantes. `core.cleaner.es_marca_ilegible()` reconoce estas anotaciones
—por una lista documentada y ampliable, y por patrón (una celda formada solo
por símbolos, sin ninguna letra)— **antes que cualquier otra regla** de la
cascada, y las convierte en una propuesta fija: "Desconegut". No es un
intento de adivinar qué ponía ahí; es una plantilla para que el archivero
decida a mano, en vez de un campo vacío sin nada que aceptar o editar. Se
cuentan aparte en el resumen ("... il·legibles"): son un indicador de la
calidad de la transcripción original, no de la calidad del programa.

## Aprendizaje de correcciones

El vocabulario oficial es fijo hasta que el Archivo lo regenera a mano; el
criterio del día a día —qué hacer con la próxima "Alisebet" que aparezca— se
escribe solo. Cada vez que el archivero confirma una corrección fila a fila
(la escribe a mano, edita la propuesta, elige el segundo candidato, o
simplemente acepta la que ya estaba), el programa la recuerda, y la próxima
vez que aparezca la misma grafía la propone directamente, marcada como
"apresa · N vegades", sin pasar por la búsqueda difusa.

Puntos que merece la pena conocer:

- **Dónde se guarda:** `correccions_apreses.json`, junto al ejecutable — no
  dentro del paquete, y no en el directorio temporal que PyInstaller borra al
  cerrar. Es JSON legible y editable a mano a propósito: a diferencia del
  vocabulario oficial (un módulo Python generado), esto se escribe en tiempo
  de ejecución y el archivero debe poder revisarlo con un editor de texto. Si
  el fichero no existe, se crea vacío al primer guardado; si está corrupto,
  el programa avisa por el log y sigue arrancando sin él.
- **Qué se aprende y qué no:** solo decisiones fila a fila. "Acceptar tots
  els canvis" (o el aceptar en bloque por tramo de puntuación) **nunca**
  enseña nada, porque ahí no ha habido revisión individual y aprender de un
  aceptar masivo propagaría cualquier error. Tampoco se aprende una
  corrección hacia "Desconegut": no es un dato, es la ausencia de uno.
- **Conflictos:** si la misma grafía errónea se corrige alguna vez hacia un
  destino distinto del ya aprendido, la entrada se actualiza y el programa
  avisa — puede significar que la entrada anterior estaba mal.
- **Gestión:** el botón *Correccions apreses* abre una ventana con todas las
  entradas y un botón para borrar cada una; un error aprendido se repetiría
  indefinidamente si no hubiera forma de deshacerlo.
- **Exportación:** el botón *Exportar apreses a VARIANTS* vuelca lo aprendido
  a un `.xlsx` con el mismo formato que espera `--variants`, para que el
  Archivo pueda promover lo consolidado al vocabulario oficial.
- **Es local:** el aprendizaje vive en el ordenador donde se confirmó cada
  corrección. Si varios puestos usan el programa, cada uno acumula el suyo
  por separado hasta que alguien exporta y comparte un `.xlsx` de variantes;
  no hay sincronización automática entre instalaciones.

## Los dos formatos

Un colaborador que trabaja con LibreOffice entrega un `.ods`, y pedirle que
convierta a `.xlsx` antes de enviarlo es justo el tipo de paso manual que introduce
errores. Así que la herramienta acepta los dos.

Leer es fácil: pandas se encarga, con `openpyxl` para XLSX y `odfpy` para ODS.
**Guardar es lo que tiene miga.** No se genera un archivo nuevo desde cero, sino que
se sobrescriben solo las celdas de datos del original, para conservar formatos,
colores, anchos de columna y cualquier otra hoja. Y eso se hace de forma muy
distinta en cada formato, así que `core/workbook_io.py` define una interfaz común
(`LibroOriginal`) con dos implementaciones.

La de ODS tiene una trampa que merece la pena contar: **el formato comprime las
celdas repetidas**. Diez celdas vacías consecutivas no se guardan diez veces, se
guardan una sola con el atributo `number-columns-repeated="10"`. Para escribir en la
tercera celda de ese bloque hay que partirlo antes en tres trozos (2 + 1 + 2),
replicando el estilo en cada uno y sin alterar el número total de columnas. Si no,
escribir una celda modifica silenciosamente a sus nueve vecinas. Hay un test
dedicado solo a eso.

## El problema de los falsos positivos de género

Al primer intento, la mitad de las propuestas eran basura. Todas del mismo tipo:

```
Miquela  →  Miquel     (92% de similitud)
Antònia  →  Antoni
Catalino →  Catalina
```

En catalán y castellano, el género se marca con la última letra. Para un algoritmo
de distancia de edición, `Miquel` y `Miquela` están a una sola letra de distancia,
exactamente igual que `Miquel` y `Miquell`. Pero uno es una persona distinta y el
otro es una errata, y una herramienta que propone fusionar a Miquela con su marido
Miquel es una herramienta que nadie va a usar dos veces.

La solución es `es_variante_genero()`: antes de proponer un cambio, se comprueba si
la diferencia entre las dos palabras **es exactamente una marca de género**. Dos
casos:

- **Misma longitud, cambia la última letra** y el cambio sigue un patrón conocido
  (`a`/`o`, `ana`/`ano`, `ina`/`ino`): `Mariana`/`Mariano`, `Catalina`/`Catalino`.
- **Una palabra es la otra más una letra final**, y esa letra es `a`, `e` o `i`:
  `Miquel`/`Miquela`, `Antoni`/`Antònia`.

Si encaja en alguno, la pareja se descarta. Si no encaja, es una errata de verdad:
`Miquell` es `Miquel` más una `l`, y una `l` no marca género, así que sí se propone.
La comparación ignora mayúsculas y acentos, porque `Antoni`/`Antònia` no se
reconocería letra a letra con la tilde de por medio.

Este filtro está cubierto por tests precisamente porque es la parte que decide si la
herramienta se usa o se abandona.

## Estructura

```
excel-name-cleaner/
├── core/cleaner.py             ← lógica pura, sin Tkinter: testeable y reutilizable
├── core/vocabulario.py         ← clasificación contra el vocabulario oficial (la cascada)
├── core/aprendizaje.py         ← aprendizaje de correcciones (JSON, punto D)
├── core/normalizacion.py       ← clave() normalizada y Candidato, compartidos por todo el programa
├── core/workbook_io.py         ← lectura y escritura de XLSX y ODS
├── core/datos_vocabulario.py   ← generado, no se sube al repo (ver más arriba)
├── tools/generar_vocabulario.py ← convierte los Excel de listados (y --variants) en el módulo anterior
├── tools/generar_icono.py      ← convierte docs/clean.png en los assets/icona* del programa
├── ui/app.py                   ← interfaz CustomTkinter
├── ui/tema.py                  ← todos los colores y tipografías del programa (punto B.4)
├── assets/icona.png            ← icono a máxima resolución, recortado y transparente
├── assets/icona_64.png         ← variante para el banner
├── assets/icona.ico            ← multirresolución de Windows (16 a 256px)
├── data/ejemplo.xlsx           ← datos de prueba ficticios con erratas sembradas
├── data/ejemplo.ods            ← los mismos datos en formato LibreOffice
├── correccions_apreses.json    ← generado en tiempo de ejecución, junto al ejecutable (punto D)
├── tests/test_cleaner.py
├── tests/test_vocabulario.py
├── tests/test_aprendizaje.py
├── tests/test_ui_wiring.py     ← comprobación estática de ui/app.py, sin importar customtkinter
├── tests/test_workbook_io.py
└── docs/clean.png              ← icono original aportado por el Archivo
```

La separación no es decorativa: `core/cleaner.py` no importa nada de Tkinter, así que
se puede probar en CI sin servidor gráfico, y la misma lógica serviría para una
versión de línea de comandos o web sin tocar una línea.

## Cómo probarlo

```bash
git clone https://github.com/USUARIO/excel-name-cleaner
cd excel-name-cleaner
pip install -r requirements.txt

python data/generar_ejemplo.py   # crea data/ejemplo.xlsx y data/ejemplo.ods
python -m ui.app                 # abre la aplicación
```

Carga `data/ejemplo.xlsx` (o `data/ejemplo.ods`, da igual) desde el botón
*Carregar full de càlcul*. Los dos archivos tienen 18 registros ficticios
idénticos, con erratas sembradas para ejercitar cada categoría y varias trampas.

**Sin `core/datos_vocabulario.py`** (el caso por defecto: no se distribuye con el
repositorio), el comportamiento es el mismo que en el prototipo original, todo por
heurística de frecuencia. Deberías ver estas tres propuestas (las dos filas nuevas,
`Cerdà`/`CERDA` y `Rosel`, no se repiten lo bastante como para que la frecuencia
las note por sí sola):

| Error | Corrección | Apariciones |
|-------|-----------|-------------|
| `Benassar` | `Bennassar` | 1 |
| `Roselló` | `Rosselló` | 1 |
| `Miquell` | `Miquel` | 2 |

Y **ninguna** propuesta sobre `Miquela`, `Antònia` ni `Catalino`: son variantes de
género legítimas y el filtro las descarta.

**Con el vocabulario real del Archivo cargado** (incluyendo `VARIANTS`, punto
E), cada errata sembrada aterriza así:

| Palabra | Categoría | Propuesta | Puntuación |
|---|---|---|---|
| `Bennassar` (la forma mayoritaria) | **variante** | `Bennàsser` | cert (tabla del Archivo) |
| `Antònia` | **variante** | `Antonina` | cert (tabla del Archivo) |
| `Roselló` | **ortográfica** | `Rosselló` | cert |
| `Miquell` | **ortográfica** | `Miquel` | cert |
| `CERDA` | **normalizable** | `Cerdà` | cert |
| `Rosel` | **ambigua** (sin puntuación) | — | `Rosell` / `Rossell` (dos apellidos reales y distintos, sin base para elegir) |
| `Benassar` (la otra grafía histórica, una sola ene) | **ambigua** (con puntuación) | `Bassa` | 77% — no está en `VARIANTS` (nota de cobertura, más arriba), así que compite en la búsqueda difusa y el mejor candidato NO es `Bennàsser` |
| `Catalino` | **corregible** | `Catoldo` | 67% — por encima del corte en 65, un nombre real pero probablemente NO el destino correcto: exactamente el tipo de propuesta que el archivero debe revisar por la puntuación visible, no aceptar en bloque sin mirar |

Las dos últimas filas no son un fallo del programa: son la consecuencia
visible de que el corte de propuesta bajó de 85 a 65 (punto A) — el Archivo
decidió que ver la puntuación y poder rechazar o corregir a mano compensa
recibir alguna propuesta de más. `Miquela` sigue sin generar ninguna
propuesta: sigue siendo una variante de género legítima, y el filtro la
descarta antes de que la puntuación entre en juego.

Acepta las que quieras, guarda, y abre `data/ejemplo_corregit.xlsx` (o `.ods`). Fíjate
en la fila 3: `Joan Miquell` ha pasado a `Joan Miquel` **dentro** de un nombre
compuesto, sin tocar el resto de la celda. Ese es el caso que una corrección
celda-a-celda se dejaba silenciosamente.

## Tests

```bash
pytest -v
```

128 tests. Sobre las funciones puras (`test_cleaner.py`): detección de variantes de
género, limpieza de celdas, corrección respetando límites de palabra y alcance por
columna, truncado al primer nombre (punto B) y marcas de ilegibilidad (punto C).
Sobre el vocabulario (`test_vocabulario.py`): la cascada completa —ilegible,
variantes, aprendizaje, clave exacta, clave ortográfica, búsqueda difusa con el
corte en 65 sin regla de margen que bloquee (punto A)—, el filtro de género
aplicado antes del margen, el género como metadato, apellidos compuestos (punto
B.4), la marca de "no verificada" en la heurística de frecuencia y el
funcionamiento con el vocabulario vacío — todo con un vocabulario de prueba
pequeño, nunca los datos reales del Archivo. Sobre el aprendizaje
(`test_aprendizaje.py`): carga/guardado, arranque con el fichero ausente o
corrupto, conflictos de destino y exportación a VARIANTS. Sobre `ui/app.py`
(`test_ui_wiring.py`): una comprobación estática por árbol sintáctico —sin
importar customtkinter, que la CI no instala a propósito— de que aceptar en
bloque nunca aprende, solo la confirmación fila a fila. Y sobre la capa de E/S: el
ciclo leer-corregir-guardar se ejecuta **parametrizado en los dos formatos**, así
que cualquier divergencia entre XLSX y ODS sale a la luz sin duplicar tests.

## Requisitos

Python 3.10 o superior. Dependencias en `requirements.txt`: `customtkinter`,
`pandas`, `openpyxl` (XLSX), `odfpy` (ODS), `rapidfuzz`, `pytest`, `Pillow`
(iconos del banner y de la ventana, punto B). `tools/generar_icono.py` usa
además `numpy`/`scipy` para aislar el motivo principal del icono en los
tamaños pequeños; son opcionales y solo hacen falta para regenerar los
assets, no para ejecutar el programa.

## Icono del programa

`docs/clean.png` es el original que aporta el Archivo (a la máxima resolución
disponible). `tools/generar_icono.py` lo convierte en los tres archivos que
usa la aplicación, guardados en `assets/` (a diferencia del vocabulario, estos
SÍ se suben al repositorio: son recursos de interfaz pequeños que no cambian
en cada ejecución):

```bash
python tools/generar_icono.py --origen docs/clean.png
```

Genera `assets/icona.png` (recorte a máxima resolución), `assets/icona_64.png`
(variante para el banner) e `assets/icona.ico` (multirresolución de Windows:
16/32/48/64/128/256 px en un solo archivo). Si el PNG de origen no tiene
transparencia real —pasó con la primera entrega, con el fondo horneado como
color sólido en vez de alpha—, el script la extrae por diferencia de color; si
además trae alguna decoración suelta en una esquina, las variantes pequeñas se
recortan solo al motivo principal para que seas legibles a 16-64px. Avisa por
consola si el origen queda por debajo de 512px, el mínimo recomendado para que
el icono del ejecutable se vea nítido en la vista de iconos grandes de
Windows.

Si se borra `assets/` (o falta cualquiera de los tres archivos), el programa
arranca igual, sin icono: nunca es un fallo bloqueante.

## Empaquetado con PyInstaller

```bash
pyinstaller ui/app.py --name colab-cleaner --onedir --windowed \
    --icon=assets/icona.ico \
    --add-data "assets;assets" \
    --collect-all customtkinter \
    --collect-all rapidfuzz \
    --collect-all odf \
    --collect-all openpyxl
```

En Linux/macOS, `--add-data "assets:assets"` (los dos puntos en vez del
punto y coma). Notas:

- **`--onedir`, no `--onefile`.** Un `--onefile` se descomprime entero en un
  directorio temporal en cada arranque, notablemente más lento en equipos con
  disco lento o poca memoria.
- **`--collect-all odf` (y no solo `--hidden-import=odf`).** `pandas.read_excel(engine="odf")`
  resuelve el lector de ODS en tiempo de ejecución a partir de la cadena
  `"odf"`, no de un `import` literal que el análisis estático de PyInstaller
  pueda seguir; `odfpy` además reparte su código en muchos submódulos
  (`odf.opendocument`, `odf.table`, `odf.text`...). `--hidden-import` solo
  garantiza el paquete raíz, no todo el árbol, y el fallo típico es
  `Import odfpy failed. Use pip or conda to install the odfpy package.` al
  cargar un `.ods` en el ejecutable compilado, aunque `odfpy` esté instalado
  y el programa funcione bien en desarrollo. `--collect-all` sí arrastra
  todos los submódulos (y cualquier dato del paquete). Por el mismo motivo de
  fondo (motor de pandas elegido por cadena, no por import) se aplica también
  a `openpyxl` y, para las extensiones C de la búsqueda difusa, a `rapidfuzz`.
  Si el error persiste tras añadir el flag, confirma que PyInstaller se
  ejecutó desde el mismo entorno virtual donde está instalado `odfpy`
  (`pip show odfpy` en ese entorno) — si no lo encuentra al analizar, ningún
  flag lo arregla.
- **Rutas de recursos.** `assets/` no es un módulo importado (a diferencia del
  vocabulario, ver más abajo), así que viaja como dato empaquetado y hay que
  resolver su ruta en tiempo de ejecución: compilado, PyInstaller lo
  descomprime en `sys._MEIPASS` (un directorio temporal), no junto al
  ejecutable. `ui/app.py` centraliza esto en `_base_recursos()`/`_ruta_recurso()`,
  usadas para todo acceso a `assets/`.
- **No confundir con el aprendizaje.** `correccions_apreses.json` es justo lo
  contrario: datos que el programa ESCRIBE, y por eso viven junto al
  ejecutable (`sys.executable`), nunca en `_MEIPASS`, que se borra al cerrar
  el programa. Esa ruta se resuelve aparte, en
  `core.aprendizaje._directorio_datos()` — son dos funciones distintas a
  propósito, para no mezclar por error un recurso de solo lectura con un dato
  que se escribe.
- El vocabulario se empaqueta solo por ser un módulo Python importado
  (`core/datos_vocabulario.py`); no necesita `--add-data`.
