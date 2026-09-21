# TEXT-BYTE-ACCESS-ARCH-1 — acceso byte seguro sobre texto UTF-8

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-21.

Este milestone define la superficie pública mínima que permite decodificar
framing con longitudes UTF-8 en bytes sin debilitar el invariante de `string`.
No modifica lexer, parser, AST, HIR, MIR, SSA, backend, runtime, tests ni la
superficie actualmente admitida. La implementación y qualification pertenecen
a **TEXT-BYTE-ACCESS-V1**.

La motivación inmediata es la auditoría de
[expense_tracker](EXPENSE_TRACKER_NEXT_PORT_REPORT.md): ALPT1 representa cada
campo como `<longitud decimal en bytes>:<payload UTF-8>`. El payload puede
contener espacios, LF, CRLF, `:`, cualquier otro delimitador del framing y
scalars multibyte. `std.Text.substring` usa posiciones scalar y `split`/`lines`
no conservan ese framing.

## 1. Decisión resumida

`std.Text` agrega conceptualmente esta API:

```aether
uint8 std.Text.byteAt(ref string value, usize offset);
bool std.Text.isByteBoundary(ref string value, usize offset);
std.Text.ByteSliceResult std.Text.byteSlice(
    ref string value,
    usize start,
    usize endExclusive
);

enum std.Text.ByteSliceResult {
    Slice(string),
    InvalidRange,
    OutOfBounds,
    InvalidBoundary
}
```

Las firmas son normativas; su lowering no convierte estas operaciones en
syntax, miembros mágicos de `string` ni un sistema público de buffers.

- `byteAt` observa un byte de la representación UTF-8 y devuelve su valor
  unsigned exacto en `0...255`. No decodifica Unicode y no asigna.
- `isByteBoundary` determina si un offset válido es una frontera UTF-8. Tanto
  cero como `byteLength(value)` son fronteras.
- `byteSlice` usa el rango semiabierto `[start, endExclusive)` y sólo publica
  un `string` si ambos extremos son fronteras. Los fallos atribuibles a datos
  externos son variantes recuperables, no traps.
- Los offsets se expresan como `usize`. El nombre de cada operación y
  `endExclusive` hacen explícita la unidad; no se agrega un wrapper nominal ni
  una conversión sólo para volver a envolver el `usize` que ya entrega
  `byteLength`.
- No se agrega `TextByteCursor`. Las tres primitivas componen directamente en
  un decoder lineal con un único offset local y no introducen storage borrowed,
  lifetimes nuevos ni una segunda familia de resultados.

Todo `string` de entrada y salida conserva UTF-8 válido. En particular, observar
un continuation byte es válido; convertir un rango que comienza o termina en
uno no lo es.

## 2. Autoridad y alcance

Esta decisión extiende [TEXT-ARCH-1](TEXT_ARCH_1.md) sin cambiar sus operaciones
scalar. Conserva:

- `string` immutable, owning, no nulo y UTF-8 válido;
- `byteLength(string) -> usize` O(1) en Core;
- Alias/Transfer/Drop y el layout/lifecycle de GENERAL-V1/V2;
- offsets scalar para `substring`, `find` y `findFrom`;
- la semántica vigente de `split`, `lines` y `trim`;
- el modelo de traps para precondiciones de programación;
- enums nominales ordinarios para resultados que el caller debe inspeccionar.

Quedan fuera buffers mutables, bytes inválidos, lectura binaria, `Bytes`, views
prestadas, iteradores/cursors persistentes, indexing `s[i]`, slicing sintáctico,
decodificación desde bytes arbitrarios, validación de un buffer externo y
parsing decimal. Este vertical hace posible el scanner bytewise de ALPT1, pero
no implementa su parser numérico, argv ni persistencia atómica.

## 3. Unidad, offsets y rangos

Un byte offset cuenta octetos desde el comienzo de la representación UTF-8.
Para un string `value` de longitud `L = byteLength(value)`:

```text
posición byte válida: 0 <= offset <= L
byte observable:      0 <= offset <  L
rango byte acotado:   0 <= start <= endExclusive <= L
```

El final `L` es una posición y una frontera válidas, pero no designa un byte.
Los rangos son semiabiertos. Así, el rango vacío se representa sin `end + 1` y
el rango completo es `[0, L)`.

`byteSlice` recibe un final, no una longitud. Para extraer exactamente `N` bytes
desde `start`, un decoder de datos externos debe comprobar primero:

```aether
usize total = byteLength(value);
if (start <= total && n <= total - start) {
    usize endExclusive = start + n;
    // start + n no puede overflow después de esa prueba.
}
```

Esta forma conserva un caso explícito `InvalidRange`, evita que la propia API
haga una suma potencialmente overflowing y hace visible el rango `[start,end)`
en diagnostics y qualification. Un helper futuro orientado a longitudes puede
envolver esta operación, pero no forma parte del mínimo.

No se introduce `ByteOffset`: a diferencia de `ScalarOffset`, estos valores se
comparan y restan directamente con `byteLength`, y esa interoperabilidad es el
caso de uso. No hay conversión implícita entre scalar y byte; las APIs scalar
siguen exigiendo `ScalarOffset`.

## 4. Semántica de las operaciones

### 4.1 `byteAt`

```aether
uint8 byteAt(ref string value, usize offset);
```

La precondición es `offset < byteLength(value)`. La función comprueba bounds en
la frontera segura y produce `TextByteOffsetOutOfBounds` si se viola. Es un trap
fail-fast, no una variante recuperable: un decoder puede y debe comprobar el
límite antes de observar el siguiente byte.

El retorno canónico es `uint8`; `byte` sigue siendo su alias source existente,
pero la firma de STD no depende del alias. Un byte ASCII retorna su código. Un
byte `>= 0x80`, incluido un leading o continuation byte, retorna exactamente el
valor unsigned `128...255`; no retorna `char`, no sign-extends y no valida ni
decodifica el scalar que lo contiene.

La operación hace un load borrowed de un byte, cuesta O(1), no asigna, no hace
Alias/retain y no publica un puntero o borrow al backing.

### 4.2 `isByteBoundary`

```aether
bool isByteBoundary(ref string value, usize offset);
```

La precondición es `offset <= byteLength(value)`. Un offset mayor produce
`TextByteOffsetOutOfBounds`. Para un offset válido:

```text
offset == 0                         => true
offset == byteLength(value)         => true
(byteAt(value, offset) & 0xC0) != 0x80 => true
otherwise                           => false
```

Esta regla es suficiente porque el source ya es UTF-8 válido: dentro de una
secuencia multibyte, todos y sólo los bytes posteriores al leading byte tienen
prefijo `10xxxxxx`. No recorre desde el comienzo, no decodifica el scalar y no
revalida el string entero. Cuesta O(1), no asigna y no altera lifecycle.

Un offset fuera del string no se interpreta como “no boundary”; mezclar ambos
casos ocultaría un error de indexado. El caller que procesa datos externos
comprueba bounds o usa directamente `byteSlice`, que sí devuelve el motivo.

### 4.3 `byteSlice`

```aether
ByteSliceResult byteSlice(
    ref string value,
    usize start,
    usize endExclusive
);
```

La clasificación es total y ocurre en este orden:

1. si `start > endExclusive`, `InvalidRange`;
2. si cualquier extremo es mayor que `byteLength(value)`, `OutOfBounds`;
3. si cualquier extremo no es frontera UTF-8, `InvalidBoundary`;
4. en otro caso, `Slice(result)`.

El orden es observable cuando una entrada viola más de una condición y evita
loads fuera de bounds. No se usa un string vacío, `null`, un offset especial ni
un entero sentinel para señalar error.

`Slice(result)` posee un owner independiente:

- un rango vacío en una frontera válida usa Alias del singleton vacío;
- el rango completo puede hacer Alias owned de `value`;
- un rango propio no vacío crea una string fresh y copia exactamente
  `endExclusive - start` bytes.

El resultado puede sobrevivir al borrow de entrada. No es una view, no retiene
de forma oculta un backing grande y nunca depende del lifetime del source.
Como el source completo es UTF-8 válido y ambos extremos son fronteras, el rango
es UTF-8 válido por construcción; no se requiere una segunda pasada de
validación.

`ByteSliceResult` es un enum nominal ordinario. Su variante `Slice` contiene el
único owner activo; match, move y Drop usan las reglas estructurales existentes.
Las variantes de error no poseen payload ni allocation. Un caller no puede
usar el string sin resolver la variante.

## 5. Framing length-prefixed

La superficie permite un decoder de `<decimal byte length>:<payload>` con este
esquema, omitiendo sólo el parsing decimal que pertenece a otro milestone:

```aether
usize total = byteLength(input);
usize cursor = 0;

// Scan de dígitos ASCII y ':' con byteAt mientras cursor < total.
// El parser produce payloadLength sin overflow.
usize payloadStart = cursor;
if (payloadLength > total - payloadStart) {
    // framing truncado
}
usize payloadEnd = payloadStart + payloadLength;

match (std.Text.byteSlice(input, payloadStart, payloadEnd)) {
    std.Text.ByteSliceResult.Slice(payload) => {
        // payload contiene exactamente N bytes y es string UTF-8 válido.
    }
    std.Text.ByteSliceResult.InvalidBoundary => {
        // la longitud externa cortó un code point
    }
    std.Text.ByteSliceResult.InvalidRange => { /* framing inválido */ }
    std.Text.ByteSliceResult.OutOfBounds => { /* framing truncado */ }
}
```

El scanner reconoce sólo los bytes ASCII del framing. Nunca busca delimitadores
dentro del payload: después de conocer `N`, avanza directamente a
`payloadEnd`. Por ello LF, CRLF, `:`, dígitos, NUL y cualquier delimiter dentro
del payload son contenido ordinario. Cada byte de framing se inspecciona a lo
sumo una vez y cada payload materializado se copia una vez.

## 6. Errores: precondición frente a dato externo

La API separa dos responsabilidades:

| Situación | Contrato | Representación |
|---|---|---|
| `byteAt` con `offset >= L` | bug de cursor/caller | trap `TextByteOffsetOutOfBounds` |
| `isByteBoundary` con `offset > L` | bug de cursor/caller | trap `TextByteOffsetOutOfBounds` |
| `byteSlice` con `start > end` | rango externo inválido | `InvalidRange` |
| `byteSlice` con extremo `> L` | input truncado/rango externo | `OutOfBounds` |
| `byteSlice` con extremo dentro de scalar | longitud externa inválida | `InvalidBoundary` |
| OOM/size no representable | fallo global no recuperable | traps existentes |
| backing `string` corrupto | violación runtime | runtime invariant trap |

No se hace capturable un trap existente. `byteSlice` prevalida y retorna un
resultado nominal antes de llamar a la primitive de copia; no intenta atrapar
`copyUtf8ByteRange`. Esta es la misma distinción entre validación esperada y
precondición interna usada por el modelo de errores: el dato externo se
clasifica antes de ejecutar una operación cuyo contrato ya está probado.

No se usan exceptions para `ByteSliceResult`: no hay IO ni fallo no local; el
resultado de validación forma parte normal del protocolo de decoding y sus
cuatro estados son pequeños, exhaustivos y allocation-free salvo el string de
éxito.

## 7. Complejidad y allocation

Sea `L` la longitud total y `R = endExclusive - start` la longitud copiada:

| Operación/caso | Tiempo worst-case | Allocation / lifecycle |
|---|---:|---|
| `byteAt` | O(1) | ninguna; borrow shared |
| `isByteBoundary` | O(1) | ninguna; borrow shared |
| `byteSlice`, fallo | O(1) | ninguna |
| `byteSlice`, vacío | O(1) | singleton vacío |
| `byteSlice`, completo | O(1) | Alias owned del source |
| `byteSlice`, propio | O(R) | una string de R bytes |

Un decoder que avanza monótonamente, comprueba `remaining = total - cursor` y
copia payloads disjuntos cuesta O(L) más el parsing decimal. No se permite
implementar estas APIs mediante `substring` scalar repetido, scanning desde
cero por consulta, concatenación temporal ni reconstrucción code-point a
code-point.

## 8. Cursor evaluado y rechazado

Un `TextByteCursor` podría agrupar source, posición y remaining, pero no reduce
las primitives necesarias: aún requeriría observar bytes, validar fronteras y
materializar un owner. En el runtime actual además obligaría a decidir si una
struct almacena un borrow `ref string`, qué lifetime puede escapar, cómo se
mueve y si retiene el source. Ese subsistema es desproporcionado para un decoder
que sólo necesita `usize cursor` y `byteLength`.

Las funciones elegidas permiten escribir un cursor local de biblioteca sin
privilegios y sin allocation. Si varios protocolos demuestran después patrones
repetidos, un cursor puede agregarse como wrapper normal sobre esta superficie,
sin cambiar su semántica ni el backing de string.

## 9. Frontera STD/runtime y reutilización

TEXT-V1 ya posee conceptualmente las primitives privadas:

```text
textByteAt(ref string value, usize offset) -> uint8
copyUtf8ByteRange(
    ref string value,
    usize start,
    usize endExclusive
) -> string
```

`byteAt` reutiliza directamente `textByteAt`. `isByteBoundary` combina
`byteLength`, los dos fast paths de extremos y un único `textByteAt` con la
máscara de continuation byte. `byteSlice` clasifica orden, bounds y boundaries
en std y, sólo en éxito, llama `copyUtf8ByteRange`.

`copyUtf8ByteRange` conserva sus comprobaciones defensivas de orden, bounds y
fronteras antes de publicar. Esa repetición en la frontera de representación no
es una segunda validación lineal ni una semántica Unicode duplicada: son checks
O(1) que protegen el invariante aunque una stdlib incorrecta invoque la
primitive. La única regla de boundary es el test de continuation byte sobre un
source cuya validez ya garantiza el runtime.

No se agrega una primitive para ALPT1, delimitadores, scanning, decimal ni
cursor. Tampoco se expone `textByteAt` por su nombre privado.

## 10. HIR, MIR, SSA y backend

Source resuelve estas identidades dentro del módulo canónico `std.Text`, con
arity, borrows y tipos nominales ordinarios. No hay token, AST node, operador,
literal, member de string ni regla de inference nuevos.

El bootstrap actual representa las llamadas intrínsecas del módulo distribuido
mediante `TextOp`. TEXT-BYTE-ACCESS-V1 puede agregar tres variantes a esa familia
como puente de implementación de la stdlib declaration-only; no debe agregarlas
a `StringOp` ni hacer que una llamada sin `import std.Text` sea válida. Ese
detalle no concede al compilador conocimiento de framing: sólo conserva la
identidad de función, tipos, borrow, resultado nominal y efectos.

- HIR verifica `ref string`/`usize`, `uint8`/`bool`/`ByteSliceResult`, y marca
  únicamente `byteSlice` como capaz de producir owner en la variante `Slice`.
- MIR conserva la call y el enum owner, y hace explícitos Transfer/Drop después
  del match; los traps de las consultas no tienen exceptional successor.
- SSA vuelve a validar tipos, dominancia, payload activo y consumos. O2 no puede
  borrar bounds/boundary checks salvo prueba equivalente.
- LLVM reutiliza los helpers internos existentes. `uint8` baja a `i8` y se
  interpreta unsigned; el resultado enum usa el layout nominal verificado.

Una implementación futura con cuerpos Aether reales en `std.Text` puede retirar
esas variantes `TextOp` sin cambio source. La autoridad semántica es esta API y
el módulo STD, no el nombre del helper LLVM ni el dispatch bootstrap.

## 11. Qualification de TEXT-BYTE-ACCESS-V1

La admisión debe probar la ruta source→native completa en O0 y O2.

### Valores y boundaries

- ASCII `"Aether"`, `"éxito"`, `"λ"` y un emoji de cuatro bytes;
- `byteAt` para cada byte, incluidos valores `>= 0x80` sin sign-extension;
- primer y último byte; offset final rechazado por `byteAt`;
- boundary cero/final, leading byte y cada continuation byte;
- offset de boundary fuera de rango con el trap preciso.

### Slices y fallos

- slice ASCII y cada scalar multibyte completo;
- comienzo o final dentro de un code point → `InvalidBoundary`;
- vacío en cada frontera válida y vacío dentro de scalar inválido;
- rango completo, propio, invertido y extremos fuera de bounds;
- precedencia exacta `InvalidRange` → `OutOfBounds` → `InvalidBoundary`;
- input vacío y U+0000;
- lifecycle Alias/fresh/singleton, match, early return y Drop exacto.

### Decoders

- `<N>:<payload>` para payload ASCII y multibyte;
- payload con espacios, LF, CRLF, `:`, dígitos, NUL y delimitadores repetidos;
- múltiples fields ALPT1-like, incluidos vacíos y mezcla ASCII/multibyte;
- longitud truncada, no decimal, overflowing o que corta un scalar;
- delimiter ausente y bytes extra conforme a la policy del decoder de prueba;
- instrumentación que demuestre avance lineal sin scalar rescans ni temporales.

### Capas y regresión

- resolución sólo tras `import std.Text`, alias de import y rechazo de aridad o
  tipos incorrectos;
- verificadores HIR/MIR/SSA ante tipo, borrow, enum payload y ownership
  corruptos;
- ausencia de helpers nuevos cuando no se usan;
- semántica sin cambios para `substring`, `split`, `lines`, `trim`, equality,
  concat y `byteLength`;
- suite workspace, fmt, clippy, differential y `git diff --check`.

## 12. Alternativas evaluadas

| Alternativa | Decisión |
|---|---|
| `byteSlice -> string` con trap | rechazada: una longitud externa que corta UTF-8 debe poder rechazarse sin abortar |
| `byteSlice -> string?`/string vacío | rechazada: pierde el motivo, confunde slice vacío válido y usa sentinel |
| exception de boundary | rechazada: validación local frecuente; un enum exhaustivo es más explícito y no localiza control mediante unwind |
| vista pública de bytes | diferida: exige tipo, lifetime, indexing y quizá strings inválidos sin ser necesario para este vertical |
| `TextByteCursor` owning o borrowed | rechazada en V1: duplica estado/resultados y abre lifetimes; un `usize` local conserva O(n) |
| offsets scalar y acumulación de `byteLength` | rechazada: rescanning/allocation y riesgo O(n²) |
| revalidar UTF-8 completo en cada slice | rechazada: source válido + dos boundaries prueban el rango |
| wrapper nominal `ByteOffset` | rechazado: dificulta composición directa con `byteLength` sin aportar seguridad entre strings concretos |
| start + length en la firma | rechazada para V1: oculta overflow e impide representar rango invertido; `[start,end)` compone con las APIs actuales |
| `int` como byte | rechazada: rango y signedness menos precisos; `uint8` ya existe y es Copy |

## 13. Consecuencias

El programa puede inspeccionar la representación UTF-8 de un string sin poder
mutarla ni publicar bytes arbitrarios como string. Los protocolos length-prefixed
pueden avanzar en offsets byte, distinguir truncamiento de boundary inválida y
materializar exactamente el payload en tiempo lineal.

La superficie agrega un solo enum nominal y tres funciones. No agrega layout a
`string`, tablas de índices, sistema de buffers, cursor, lifetime o semántica
especial de lenguaje. Las operaciones scalar existentes conservan su unidad y
su contrato; byte access permanece explícito en nombre y módulo.
