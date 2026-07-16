# Formato oficial de persistencia Aether v1

Estado: RFC aprobada e implementación ALPT1 inicial disponible en perfil 20.

## Implementación de referencia (perfil 20)

`examples/expense_tracker/Persistence.ae` implementa manualmente el codec puro
`encodeLedger`/`decodeLedger` para `Transaction` y `List<Transaction>`, y los
wrappers `loadLedger`/`saveLedger`. La lógica de schema permanece en Aether;
el namespace interno `text` aporta sólo cursor por bytes, slicing UTF-8 seguro,
formatting decimal y concatenación lineal de fragmentos. No hay reflection,
schema dinámico, JSON, CSV ni serialización genérica.

La implementación fija los siguientes límites de recursos v1: 10.000 records,
64 fields por record y 1.048.576 bytes por payload. Los errores retornan lista
o contenido vacío y un `LedgerStatus`; el offset es el comienzo del token
ofensivo, el byte de framing ofensivo o EOF para truncación. Nunca se publica
un prefijo válido.

El writer usa decimal i32 canónico y `%.17g` bajo locale C para binary64. Es
determinista y conserva round-trip, incluido zero con signo; Expense Tracker
rechaza zero, NaN e infinitos porque `amount` debe ser finito y positivo. El
reader acepta la gramática decimal finita de `parseDouble`, tal como especifica
esta RFC, y exige spelling canónico para enteros y longitudes.

`saveLedger` usa `io.writeText` y por tanto **no es atómico**. La fase pendiente
es agregar temp file en el mismo directorio, flush/fsync, rename de reemplazo y
sync del directorio antes de prometer atomicidad o durabilidad ante corte.

Esta RFC define el formato textual de persistencia Aether v1 y usa Expense
Tracker como primer schema. No agrega APIs, sintaxis ni capacidades al
lenguaje. Tampoco convierte `split` en un parser de formatos estructurados.

Las palabras **DEBE**, **NO DEBE**, **DEBERÍA** y **PUEDE** expresan requisitos
normativos de esta RFC.

## Decisión ejecutiva

La recomendación es **Aether Length-Prefixed Text 1 (ALPT1)**: un formato UTF-8
con un plano de control line-based ASCII y payloads precedidos por su longitud
exacta en bytes UTF-8.

La combinación es deliberada:

- el encabezado, los nombres de campo y los tipos usan líneas simples y una
  gramática cerrada;
- el contenido de cada campo se consume por longitud, no buscando un
  separador;
- cada registro identifica sus campos por nombre y tipo, por lo que no depende
  del orden físico de `Transaction`;
- el archivo declara versión de formato, aplicación, schema y revisión de
  schema antes de los datos;
- un lector puede saltar campos aditivos desconocidos sin entender su valor;
- `io.readText` ya proporciona la frontera UTF-8, preserva NUL y newlines y
  devuelve errores estructurados.

ALPT1 no es CSV, JSON ni un volcado del layout en memoria. Es un contrato de
bytes estable y manualmente esquematizado. No requiere reflection, `Map`, GC,
I/O binario ni serialización automática.

## Alcance y no objetivos

Esta RFC decide:

- el framing del archivo y de los campos;
- el encabezado y el versionado;
- el schema inicial del Expense Tracker;
- las reglas de strings, escalares, compatibilidad y corrupción;
- el modelo de errores esperado para una implementación futura;
- la estrategia de escritura segura y el roadmap.

Quedan fuera de alcance:

- implementar el lector, el escritor o una API pública;
- modificar el compilador, runtime, IR, SSA, LLVM o CLI;
- modificar Expense Tracker;
- serialización genérica o basada en reflection;
- compresión, cifrado, firmas, checksums e índices;
- acceso concurrente, locking y transacciones multiarchivo;
- prometer recuperación parcial de un archivo corrupto.

## Restricciones actuales de Aether

El diseño parte de strings UTF-8 length-aware con ARC, `byteLength`, parsing
numérico explícito, structs, enums, `Array`/`List` e I/O de texto. En particular,
`io.readText` valida UTF-8, preserva NUL y newlines, y `io.writeText` escribe
exactamente `byteLength` bytes.

Estas propiedades permiten representar ALPT1 como un `string` Aether sin
confundir NUL con fin de texto. Los codecs serán específicos por schema y
podrán construir `Transaction` directamente; no necesitan inspeccionar el
layout de un struct.

Hay dos límites importantes:

1. `split` preserva campos vacíos, pero no entiende quoting, escaping ni
   longitudes. No es suficiente para parsear payloads ALPT1.
2. La superficie pública actual no incluye substring por bytes ni formatting
   numérico canónico. Por eso la primera implementación del codec pertenece al
   runtime/stdlib y no debe fingirse como una composición insegura de `split`.
   El formato, sin embargo, sólo usa los bytes UTF-8, parsers y valores que el
   runtime ya representa; no requiere una nueva categoría de valor o de I/O.

## Alternativas evaluadas

### CSV

Ventajas:

- formato textual conocido;
- pequeño para registros tabulares;
- fácil de producir si se prohíben comas, comillas y newlines.

Desventajas para Aether:

- CSV real necesita una máquina de estados para quoting, comillas duplicadas y
  registros multilinea; `split(",")` no lo implementa;
- sus dialectos difieren en separador, newline, encoding, encabezado y reglas
  de quoting;
- normalmente asocia columnas por posición y pierde estabilidad al reordenar
  o agregar campos;
- no expresa por sí solo schema, tipos, versión ni enum simbólico;
- un error de quoting puede desalinear todos los registros posteriores;
- la compatibilidad con hojas de cálculo no es una prioridad de esta RFC.

Un dialecto CSV completamente especificado sería viable, pero tendría casi el
mismo trabajo de parser que un formato propio y peor framing para recuperación.
No se recomienda.

### JSON

Ventajas:

- objetos con campos nombrados, independientes del orden;
- ecosistema amplio y reglas conocidas para strings, arrays y números;
- agregar propiedades suele ser compatible con lectores tolerantes.

Desventajas para Aether:

- Aether no posee parser, writer, valor dinámico, `Map` ni reflection JSON;
- implementar correctamente escapes, pares surrogate, números y profundidad
  requiere un subsistema considerable;
- JSON no admite NUL literal: debe escaparse y luego reconstruirse;
- un parser genérico crea una representación intermedia que el codec manual de
  `Transaction` no necesita;
- no trae versionado, atomicidad ni schema por sí mismo;
- la recuperación tras un token o string truncado es limitada.

JSON sería una buena capacidad de intercambio futura, pero es una dependencia
demasiado grande para la primera persistencia. No se recomienda para v1.

### Texto con longitudes prefijadas

Ventajas:

- cualquier string UTF-8 válido, incluido NUL, newline y separadores, puede
  transportarse sin transformación;
- los campos vacíos son inequívocos (`length=0`);
- el lector conoce el límite antes de interpretar el valor;
- los campos desconocidos pueden saltarse por longitud;
- la truncación y el trailing data se detectan con precisión;
- el parser es una máquina de estados pequeña y determinista.

Desventajas:

- no puede parsearse sólo por líneas;
- una longitud corrupta impide confiar en el framing posterior;
- editar el archivo manualmente exige actualizar longitudes;
- el escritor debe medir bytes UTF-8, no caracteres.

Es la base recomendada porque `byteLength` y el I/O exacto ya forman parte del
modelo Aether y porque reduce la ambigüedad del parser.

### Formato propio puramente line-based

Ventajas:

- implementación y diagnóstico sencillos para valores sin newlines;
- encabezados y registros visibles con herramientas de texto;
- puede incorporar nombres de campo y versión.

Desventajas para Aether:

- necesita prohibir contenido o inventar escaping para newline, backslash,
  separadores y NUL;
- escaping y unescaping requieren otro parser, no sólo `split`;
- una línea truncada o un escape perdido puede cambiar los límites lógicos;
- extender la gramática sin colisiones se vuelve progresivamente difícil.

ALPT1 conserva líneas sólo para el plano de control restringido y evita esta
alternativa para los valores.

### Formato binario

Ventajas:

- compacto y potencialmente más rápido;
- longitudes y números pueden representarse sin conversión decimal;
- permite checksums e índices eficientes en versiones avanzadas.

Desventajas para Aether:

- no existe I/O binario público;
- exige definir endianess, tamaños, representación de `double`, alineación y
  límites antes de disponer de primitivas para manejarlos;
- un volcado del struct sería dependiente del backend, padding, enum ordinal y
  ownership, y por tanto queda expresamente prohibido;
- inspección y diagnóstico requieren herramientas adicionales;
- aumenta mucho el alcance de v1.

Puede considerarse como otro `format-version` futuro, no como evolución
silenciosa de ALPT1.

## Comparación resumida

| Alternativa | Parser nuevo | Campos nombrados | Strings arbitrarios | Salto de campos | Adecuación v1 |
|---|---:|---:|---:|---:|---|
| CSV | sí | opcional | con quoting complejo | débil | baja |
| JSON | sí, grande | sí | con escaping | sí | media futura |
| Length-prefixed text | sí, pequeño | sí | sí, directos | sí | alta |
| Line-based puro | sí | sí | sólo con escaping | variable | media-baja |
| Binario | sí + binary I/O | depende | sí | depende | baja |

## Contrato de bytes ALPT1

### Encoding y newline de control

El archivo completo DEBE ser UTF-8 válido según la misma validación estricta
de `io.readText`. No se admite BOM. La secuencia U+000A, byte `0A`, es el único
newline del plano de control. `CRLF` y `CR` aislado son inválidos en control.

Los payloads no están sujetos a esa regla: pueden contener LF, CRLF, CR, NUL,
espacios o cualquier otro contenido que siga siendo UTF-8 válido.

Todas las longitudes y offsets de esta RFC se miden en **bytes UTF-8**, nunca en
code points, graphemes ni unidades del host.

### Tokens de control

Los identificadores del plano de control usan únicamente ASCII:

```text
identifier := lower (lower | digit | "-" | ".")*
lower      := "a" ... "z"
digit      := "0" ... "9"
uint       := "0" | nonzero digit*
nonzero    := "1" ... "9"
```

No se permiten espacios al inicio o final, tabs, comentarios, líneas vacías ni
normalización Unicode en el plano de control. Cada línea tiene palabras
separadas por un único byte space (`20`). La gramática cerrada hace seguro usar
comparación exacta o `split(" ")` sólo después de aislar una línea de control.

### Gramática estructural

En la siguiente gramática, `LF` es un byte `0A`; `PAYLOAD(n)` son exactamente
`n` bytes; y los valores entre `<...>` cumplen el token indicado.

```text
file =
    "AETHER-PERSISTENCE" LF
    "format-version 1" LF
    "application " <identifier> LF
    "schema " <identifier> LF
    "schema-revision " <uint> LF
    "schema-min-reader " <uint> LF
    "record-count " <uint> LF
    *optional-header
    "end-header" LF
    record{record-count}
    "end-file" LF

optional-header = "optional-" <identifier> " " <identifier> LF

record =
    "record " <identifier> " " <uint:field-count> LF
    field{field-count}
    "end-record" LF

field =
    "field " <identifier:name> " " <identifier:type> " " <uint:length> LF
    PAYLOAD(length) LF
```

No hay whitespace implícito. El LF posterior a `PAYLOAD` es framing y no forma
parte del valor. Para longitud cero debe aparecer inmediatamente, produciendo
visualmente una línea vacía. El lector consume primero la cantidad declarada y
después exige exactamente ese LF; nunca busca un LF dentro del payload.

Tras el LF de `end-file` DEBE alcanzarse EOF. Incluso whitespace o un segundo
newline constituye `TrailingData`.

### Encabezado obligatorio

Las dos primeras líneas son fijas y permiten identificar el formato con un
prefijo mínimo:

```text
AETHER-PERSISTENCE
format-version 1
```

Se eligió un magic legible, no específico de Expense Tracker, para evitar que
cada aplicación invente su framing. `format-version` versiona la gramática y
semántica comunes. Un lector v1 DEBE rechazar cualquier valor distinto de `1`;
no debe intentar adivinar ni degradar.

Las demás claves obligatorias significan:

- `application`: namespace estable del productor/consumidor;
- `schema`: identidad estable del modelo persistido;
- `schema-revision`: revisión escrita del schema;
- `schema-min-reader`: revisión mínima de lector que puede interpretarlo sin
  pérdida semántica conocida;
- `record-count`: cantidad exacta de registros posteriores.

Las claves obligatorias aparecen en el orden indicado para simplificar el
bootstrap del parser. Una versión futura que cambie este orden debe usar otro
`format-version`.

Las únicas extensiones de encabezado admitidas en formato 1 comienzan con
`optional-`, tienen un valor token ASCII y pueden ignorarse. Cualquier otra
línea de encabezado desconocida es error: una semántica obligatoria nunca se
degrada silenciosamente a opcional. Ninguna clave, incluida una extensión
opcional, puede aparecer más de una vez.

## Schema de Expense Tracker

### Identidad

El primer schema propuesto usa:

```text
application aether.expense-tracker
schema expense-ledger
schema-revision 1
schema-min-reader 1
```

El tipo de registro es `transaction`.

### Campos

Los cinco campos solicitados se representan por nombre, no por posición:

| Campo wire | Tipo wire | Campo Aether | Requerido | Regla |
|---|---|---|---:|---|
| `id` | `int` | `id` | sí | entero i32 canónico |
| `type` | `enum` | `type` | sí | `Expense` o `Income` |
| `amount` | `double` | `amount` | sí | finito y mayor que cero |
| `category` | `string` | `category` | sí | UTF-8, puede estar vacío en wire |
| `description` | `string` | `description` | sí | UTF-8, puede estar vacío en wire |

El `Transaction` actual del repositorio contiene además `date: string`. Para
que el dogfood futuro no pierda datos, la revisión 1 real del schema DEBE
incluirlo también:

| Campo wire | Tipo wire | Campo Aether | Requerido | Regla |
|---|---|---|---:|---|
| `date` | `string` | `date` | sí | UTF-8; v1 no interpreta ni valida calendario |

La diferencia queda documentada en vez de ocultar el sexto campo o modificar
el ejemplo. Por tanto un registro `transaction` revisión 1 tiene seis campos
requeridos. La validación de dominio del Expense Tracker puede imponer reglas
adicionales sobre categoría y descripción después del parse estructural.

El orden de aparición de los fields dentro de un registro NO es significativo.
El writer DEBERÍA emitir el orden de las tablas anteriores para obtener diffs
deterministas, pero el reader despacha por nombre. Ningún nombre de campo,
conocido o desconocido, puede repetirse; no se aplica first-wins ni last-wins.

### Tipos escalares

`int` usa decimal ASCII canónico:

- `0` o `-?[1-9][0-9]*`;
- sin `+`, whitespace, ceros iniciales ni `-0`;
- dentro del rango de `int` Aether;
- debe ser aceptado por `parseInt` y luego superar la validación canónica.

`double` usa decimal ASCII finito aceptado por `parseDouble`. El writer futuro
DEBE producir una representación locale-independent que, al parsearse, recupere
el mismo valor IEEE-754; se recomienda el decimal más corto round-trip, con `e`
minúscula y sin `+` redundante. `NaN`, infinitos y spellings dependientes del
backend están prohibidos. El display actual de `print`/interpolación no es un
codec de persistencia y NO DEBE usarse si no garantiza round-trip.

`enum` persiste el nombre estable de la variante, nunca su ordinal, dirección
ni discriminante interno. Expense Tracker revisión 1 acepta exactamente
`Expense` e `Income`.

`string` usa el payload UTF-8 tal cual. No se aplica trim, normalización Unicode,
escaping ni terminador NUL observable.

Para todos los tipos, la longitud declarada cubre el spelling o contenido
exactos del payload, no el LF de framing.

### Ejemplo normativo

Este archivo representa una transacción. Las longitudes de los strings son
longitudes UTF-8; los campos se muestran en el orden recomendado, no en el
orden del struct actual:

```text
AETHER-PERSISTENCE
format-version 1
application aether.expense-tracker
schema expense-ledger
schema-revision 1
schema-min-reader 1
record-count 1
end-header
record transaction 6
field id int 1
7
field type enum 7
Expense
field amount double 5
19.95
field category string 4
food
field description string 18
Lunch with friends
field date string 10
2026-07-16
end-record
end-file
```

Un ejemplo con `description` igual a `línea 1\nlínea 2`, donde `\n` representa
un LF real y no dos caracteres escapados, declara longitud 17: ambas `í` ocupan
dos bytes y el LF dentro del payload ocupa uno. El parser no confunde ese LF
con el LF de framing porque ya conoce la longitud.

## Schema: opciones consideradas

### Orden fijo

Un registro podría contener sólo seis valores en un orden documentado. Es el
parser más pequeño, pero acopla el archivo al orden externo, dificulta agregar
campos y hace que una omisión desplace el resto. Tampoco satisface por sí solo
la independencia respecto del orden implícito del struct. Se descarta.

### Pares clave-valor

Nombrar cada field desacopla wire y layout, permite detectar duplicados/faltantes
y saltar adiciones. El costo es repetir nombres y despachar explícitamente. Es
la opción elegida para los registros.

### Schema explícito dentro de cada archivo

Una sección que declare columnas, tipos, obligatoriedad y defaults sería más
autodescriptiva. Sin reflection ni tipos dinámicos, el lector todavía tendría
que comparar ese schema con código nominal; además duplica validación y abre
problemas de evolución del propio lenguaje de schemas.

ALPT1 usa un punto medio: identidad y revisión de schema explícitas en el
encabezado, fields nombrados y tipados en cada registro, y definición normativa
del schema en el codec/documentación. No depende del orden del struct ni intenta
crear reflection indirecta.

## Strings, delimitadores y longitudes

### Reglas completas

- **UTF-8:** todo el archivo debe ser UTF-8 válido. No hay normalización; dos
  secuencias Unicode canónicamente equivalentes siguen siendo bytes distintos.
- **NUL embebido:** permitido dentro de payloads y contado como un byte. Está
  prohibido en el plano de control por su gramática ASCII.
- **Newlines:** cualquier secuencia está permitida dentro de payloads. Control
  usa sólo LF.
- **Separadores:** spaces, puntos, guiones o la palabra `field` dentro del
  payload no tienen significado especial.
- **Campos vacíos:** se codifican con longitud cero y un LF de framing inmediato.
- **Longitudes:** decimal ASCII canónico, sin signo ni ceros iniciales salvo
  `0`; se miden en bytes UTF-8.
- **Escaping:** no existe en payloads ALPT1. Un backslash es un backslash y
  `\n` son dos bytes salvo que el valor real contenga un LF.

### Escaping frente a quoting frente a length-prefix

Escaping necesita definir al menos escape, orden de decodificación, escapes
inválidos y representación de Unicode/NUL. También expande contenido y hace que
una pérdida de backslash cambie el valor.

Quoting resuelve separadores sólo con reglas adicionales para quote dentro del
valor y multilinea. En la práctica requiere la máquina de estados CSV que se
quiere evitar.

Length-prefix mide el string que Aether ya posee, no lo transforma y separa
framing de contenido. Su principal riesgo es una longitud corrupta; ALPT1 lo
mitiga con límites, conteo de fields, `end-record`, conteo de records y
`end-file`. No intenta continuar si la longitud dejó de ser confiable.

## Algoritmo conceptual de lectura

Un lector conforme mantiene un cursor de byte y sigue estos pasos:

1. Obtiene el archivo con `io.readText` y diferencia error de I/O, UTF-8
   inválido y archivo vacío.
2. Consume magic y `format-version` exactos.
3. Valida el resto del encabezado, compatibilidad de schema y límites globales.
4. Para cada registro declarado, consume su header y exactamente `field-count`
   fields.
5. Para cada field, valida el header, comprueba la longitud antes de sumar o
   reservar, consume exactamente el payload y exige el LF de framing.
6. Rechaza cualquier nombre duplicado. Despacha fields conocidos por nombre,
   comprueba tipo y valor, y salta fields desconocidos usando su longitud aunque
   su type token también sea desconocido.
7. Exige todos los fields requeridos, valida invariantes de dominio y sólo
   entonces construye/agrega el `Transaction` staged.
8. Tras el número declarado de registros, exige `end-file` y EOF exacto.
9. Publica la lista sólo si todo el archivo es válido.

El lector NO DEBE mutar el ledger visible registro a registro. Ante cualquier
error devuelve fallo y descarta el estado staged; así un archivo corrupto no se
convierte en una carga parcial accidental.

Las sumas `cursor + length`, contadores y allocations DEBEN comprobar overflow
antes de ejecutarse. El máximo representable del formato v1 es `2147483647`
bytes por payload, coherente con `byteLength` público, pero una implementación
PUEDE imponer límites de recursos menores y documentados.

## Corrupción y política de rechazo

| Situación | Comportamiento v1 |
|---|---|
| Archivo vacío | `EmptyFile`; no se interpreta como ledger vacío |
| Archivo truncado | `UnexpectedEnd` con el offset y contexto disponibles |
| Magic incorrecto | `InvalidMagic` |
| `format-version` desconocida | `UnsupportedFormatVersion`; no fallback |
| Aplicación/schema desconocido | `UnsupportedSchema` |
| Revisión incompatible | `UnsupportedSchemaRevision` |
| Header obligatorio faltante/duplicado | `InvalidHeader`/`DuplicateHeader` |
| Campo desconocido | se valida framing y se salta; no se conserva al reescribir |
| Campo requerido faltante | `MissingField` al cerrar el registro |
| Nombre de campo duplicado, conocido o no | `DuplicateField` |
| Tipo incorrecto en campo conocido | `TypeMismatch` |
| Longitud no canónica, negativa, overflow o sobre límite | `InvalidLength`/`ResourceLimitExceeded` |
| Payload más corto que la longitud | `UnexpectedEnd` |
| UTF-8 inválido | error `InvalidUtf8` de `readText`, antes del parser ALPT1 |
| Registro incompleto o `end-record` ausente | `IncompleteRecord` |
| Conteo de fields/records inconsistente | `InvalidFieldCount`/`InvalidRecordCount` |
| Valor escalar o enum inválido | `InvalidValue` |
| Bytes después de `end-file` | `TrailingData` |

V1 es fail-closed. Los marcadores redundantes mejoran diagnóstico y detección,
pero no autorizan resynchronization: después de una longitud corrupta no existe
una forma segura de distinguir contenido de control. Una futura recuperación
parcial necesitaría frames de registro independientes con checksum o índice y
debe pertenecer a otra versión del formato.

No hay checksum en v1 porque Aether no posee todavía una primitiva estable para
calcularlo y un checksum no reemplaza atomicidad. El formato detecta corrupción
estructural y muchos valores inválidos, no bit flips que produzcan otro archivo
válido.

## Resultados estructurados, sin excepciones ni sentinels

La futura API debe usar enums y structs nominales. El siguiente bosquejo define
la forma del contrato, no nombres públicos aprobados ni código a implementar en
esta fase:

```text
PersistenceStatus =
    Success | IoError | InvalidUtf8 | EmptyFile | InvalidMagic |
    UnsupportedFormatVersion | UnsupportedSchema |
    UnsupportedSchemaRevision | InvalidHeader | DuplicateHeader |
    InvalidRecordCount | InvalidFieldCount | InvalidRecordHeader |
    InvalidFieldHeader | InvalidLength | ResourceLimitExceeded |
    UnexpectedEnd | IncompleteRecord | DuplicateField | MissingField |
    TypeMismatch | InvalidValue | TrailingData

PersistenceError = {
    status,
    byteOffset,
    recordIndex,
    fieldName,
    detail
}

ExpenseLedgerReadResult = {
    transactions,
    error
}
```

`status == Success` es la única condición para consumir `transactions`. En
error, la lista vacía/default no comunica el fallo y no es un sentinel: el
caller DEBE inspeccionar `status`. `byteOffset`, `recordIndex` y `fieldName`
son contexto diagnóstico; su valor default cuando no aplica tampoco decide el
resultado. El error de I/O debería conservar o mapear explícitamente el
`FileStatus` existente.

El writer necesita un resultado equivalente con status diferenciado para
validación de dominio, límites, creación temporal, escritura, flush y rename.
Ningún fallo esperado debe lanzar excepción.

## Versionado y compatibilidad

### Versión de formato

`format-version` cambia sólo cuando cambia la gramática común o una regla que
un lector anterior no puede saltar de forma segura. Los lectores v1 aceptan
exactamente `1`. Una implementación puede soportar varios parsers y elegirlos
después de leer magic/version, pero nunca debe probar parsers por heurística.

### Revisión de schema

`schema-revision` evoluciona el significado de `expense-ledger`.
`schema-min-reader` expresa el lector más antiguo conocido que puede cargar el
archivo correctamente.

Un lector de revisión `R` acepta una revisión de archivo mayor que `R` sólo si
`schema-min-reader <= R`, y aplica las reglas de fields desconocidos. Si
`schema-min-reader > R`, rechaza. Una revisión menor puede cargarse mediante
defaults/migraciones explícitos que el codec de `R` documente; no se inventan
defaults automáticamente.

### Operaciones de evolución

- **Agregar un campo opcional:** incrementar `schema-revision`, mantener
  `schema-min-reader`, usar un nombre nuevo y definir un default semántico para
  lectores nuevos. Lectores viejos lo saltan por longitud.
- **Agregar un campo requerido:** sólo es backward-compatible si lectores
  anteriores ya pueden derivarlo sin ambigüedad. En otro caso, incrementar
  `schema-min-reader`.
- **Eliminar un campo:** primero deprecarlo y seguir aceptándolo. Un writer que
  deba producir archivos para lectores antiguos sigue emitiéndolo. Eliminar un
  campo requerido o cambiar su significado eleva `schema-min-reader` o crea un
  schema nuevo.
- **Renombrar un campo:** tratarlo como agregar nombre nuevo y deprecar el
  anterior. Durante una ventana compatible, el writer puede emitir sólo el
  antiguo o ambos según el target; si aparecen ambos, el codec debe tener una
  regla explícita y nunca last-wins. Un rename directo es breaking.
- **Cambiar tipo o unidad:** es breaking. Se usa un nombre nuevo, una migración
  explícita o un schema nuevo; nunca se reinterpreta el payload silenciosamente.
- **Agregar una variante enum:** requiere decidir si ignorarla perdería
  semántica. Para `TransactionType`, un lector viejo no puede clasificar un
  tercer tipo, por lo que se eleva `schema-min-reader`.

Un lector que salta campos desconocidos no promete preservarlos al reescribir.
Por eso una herramienta antigua no debe cargar y guardar in-place un archivo
de revisión superior salvo que el usuario acepte esa pérdida o el writer tenga
un modo de preservación raw futuro.

## Escritura segura y atomicidad

`io.writeText(path, content)` trunca el destino y no proporciona por sí solo
una actualización atómica. Una implementación de persistencia no debe anunciar
durabilidad segura usando sólo esa secuencia.

La estrategia objetivo es:

1. validar todo el ledger y construir el contenido completo;
2. crear un archivo temporal único en el mismo directorio del destino;
3. escribir todos los bytes y comprobar short writes/errores;
4. hacer flush del archivo y, si se promete durabilidad ante corte de energía,
   sincronizarlo;
5. cerrar el temporal;
6. renombrarlo sobre el destino mediante rename atómico de mismo filesystem;
7. sincronizar el directorio cuando la plataforma lo requiera;
8. limpiar el temporal en todo fallo previo al rename.

Permisos, symlinks, colisiones, Windows y semántica de reemplazo deben definirse
en la API de archivos que habilite esta fase. `appendText` NO es apropiado para
ALPT1: invalidaría `record-count` y `end-file`, y un crash podría dejar un
registro parcial.

Hasta que existan primitivas de temporal/flush/rename, puede haber un writer
experimental explícitamente no atómico, pero no debe llamarse persistencia
segura ni ser usado por defecto por Expense Tracker.

## Escala, lectura completa y streaming

### Recomendación v1

V1 debe usar lectura completa mediante `io.readText`, seguida de parse staged
en memoria. Es la única API de lectura pública actual, simplifica UTF-8 y
ownership, permite validar EOF/conteos antes de publicar estado y es adecuada
para el dogfood inicial del Expense Tracker.

El costo máximo aproximado incluye el string del archivo, payloads/temporales y
la `List<Transaction>`. La implementación debe limitar tamaño total, número de
registros, fields por registro y longitud por payload antes de reservar.

### Lectura incremental futura

ALPT1 es compatible con un cursor incremental: control termina en LF y payloads
tienen longitud. Un reader futuro puede conservar bytes incompletos entre
chunks y alimentar una máquina de estados sin cambiar el archivo.

Validar UTF-8 incremental exige mantener estado entre chunks, especialmente si
un code point cruza el límite. Construir un `Transaction` sólo al terminar su
registro sigue siendo obligatorio.

### Streaming público futuro

Streaming de transacciones reduce memoria, pero cambia la semántica de errores:
el consumidor puede haber actuado sobre registros anteriores cuando se descubre
corrupción. Por eso no es el default v1. Una API futura deberá distinguir
claramente entre iteración best-effort y carga transaccional completa; no debe
reutilizar el mismo resultado como si ambas ofrecieran atomicidad lógica.

## Dogfood en Expense Tracker

La integración futura debe ser manual y nominal:

- un codec de `expense-ledger` convierte fields conocidos a `Transaction`;
- el enum se escribe por nombre y se valida explícitamente;
- `id` usa parsing entero estricto, `amount` parsing double estricto y reglas de
  dominio, y los strings conservan bytes exactos;
- los registros válidos se acumulan en una nueva `List<Transaction>`;
- sólo después de `end-file` válido se reemplaza el ledger visible;
- guardar construye el archivo completo y usa la estrategia atómica cuando la
  API necesaria exista.

`persist-check` actual continúa siendo sólo una prueba de I/O textual. No debe
reinterpretarse ni migrarse silenciosamente. El ejemplo no se modifica durante
la aprobación de esta RFC.

Un primer dogfood posterior debería cubrir al menos:

- round-trip de ambas variantes de `TransactionType`;
- strings vacíos, multibyte, con LF, CRLF, NUL y palabras de control;
- fields en orden distinto;
- field aditivo desconocido;
- todos los casos de corrupción de la tabla anterior;
- no publicación parcial ante error;
- paridad AST/native de valores, no igualdad textual accidental del formatter.

## Roadmap

### Fase 0 — Aprobación del formato

- revisar y aprobar magic, gramática, nombres y schema de Expense Tracker;
- fijar límites mínimos y política de decimal round-trip;
- producir corpus de archivos válidos/inválidos y golden bytes;
- decidir nombres públicos de resultados por separado de esta RFC.

No se modifica runtime ni ejemplo en esta fase.

### Fase 1 — Codec interno y runtime

- implementar cursor byte-aware, parser/escritor ALPT1 y límites checked;
- implementar formatting numérico locale-independent y round-trip;
- mapear I/O/UTF-8 a errores estructurados;
- probar UTF-8 multibyte, NUL, truncación, overflow y trailing data en AST y
  native;
- mantener codecs específicos sin reflection ni representación dinámica.

### Fase 2 — API pública mínima

- exponer resultados nominales de lectura/escritura, sin excepciones;
- definir ownership de contenido, errores y listas staged;
- incorporar primitivas seguras de archivo temporal, flush y rename o marcar
  de forma inequívoca el writer como no atómico hasta tenerlas;
- documentar límites de recursos y garantías por plataforma.

### Fase 3 — Dogfood de Expense Tracker

- agregar codec `expense-ledger` revisión 1;
- integrar comandos explícitos de load/save sin cambiar sintaxis del lenguaje;
- migrar sólo mediante una acción consciente, sin confundir `persist-check` con
  el formato oficial;
- ejecutar corpus E2E y escenarios de crash/error de escritura.

### Fase 4 — Optimización y evolución

- evaluar parser incremental y streaming con semántica separada;
- agregar preservación de fields desconocidos sólo si hay un caso real;
- medir tamaño/tiempo antes de introducir índices, checksum o compresión;
- considerar JSON o un formato binario como otro `format-version`, nunca como
  reinterpretación de archivos ALPT1.

## Criterios de aceptación documental

La RFC queda lista para aprobación cuando:

- un archivo puede parsearse sin conocer el orden del struct;
- cada byte pertenece inequívocamente a control, payload o framing;
- NUL, newlines, separadores y strings vacíos tienen representación definida;
- formato y schema tienen estrategias de versión separadas;
- todos los fallos solicitados producen un status estructurado;
- las reglas de compatibilidad no dependen de heurísticas;
- atomicidad y streaming no prometen capacidades ausentes;
- la discrepancia del field `date` actual está resuelta sin modificar el
  ejemplo;
- el roadmap separa aprobación, implementación, API, dogfood y optimización.
