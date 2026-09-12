# GENERAL-ARCH-1 — reporte de decisión de `string`

Estado: **ARQUITECTURA DISEÑADA; SIN IMPLEMENTACIÓN**, 2026-09-12. El contrato
completo está en [GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md). No se modificaron
parser, HIR, MIR, SSA, LLVM ni runtime.

## Modelo elegido

`string` es un tipo fundamental owning, inmutable, no nulo y estáticamente
tipado. Tiene semántica de valor e igualdad por contenido, pero backing
compartido. No es `class String`, no tiene identidad pública, dynamic typing,
mutación ni copy-on-write.

Se elige **immutable ARC backing** para el bootstrap. Deep copy oculta costos
O(n) en asignaciones y calls; COW agrega estados sin beneficiar a un valor
inmutable; una class introduce identidad/dispatch impropios; SSO queda diferida
hasta contar con perfiles.

## Representación

Un valor ocupa un handle opaco no nulo de una palabra. Apunta a un objeto
conceptual con `byte_length: usize`, strong count `u64`, flags privados, bytes
UTF-8 inline y un cero auxiliar fuera del contenido. Heap object y payload usan
una allocation contigua en el bootstrap. Offsets, padding, flags y nombres de
helpers son ABI privada, no el layout legacy ni una ABI C pública.

El strong ARC inicial es no atómico y sólo habilita el perfil single-thread.
No hay weak references, cycle collector, hash cache ni capacity en un string.

## Ownership

`string` tiene `Copy=false`, `Relocatable=true`, `Storable=true` y
`needs_drop=true`. La inmutabilidad no lo vuelve `Copy`: duplicarlo crea una
obligación owning y cleanup.

```aether
string a = "hello";
string b = a;
```

`b = a` es `Alias`: ambos siguen válidos; un backing dinámico hace retain y uno
inmortal no-op. Resultados frescos usan `Transfer`. `Drop` hace release y el
último libera una vez. Assignment adquiere el RHS antes de liberar el valor
reemplazado. Parámetros by-value y returns siguen el mismo Alias/Transfer de
OOP-V1; un `ref string` futuro evita ownership explícitamente.

OOP-OPT-1 permite eliminar RC físico con prueba y reverificación, sin borrar
las operaciones lógicas ni mover la destrucción final.

`T: Copy` no acepta `string`. Alias es inicialmente intrínseco al tipo; un
aggregate que contiene string es no-Copy y conserva las reglas actuales de
whole-value move hasta que exista una capability general de Alias/Clone.

## Literales

Los literals se validan/codifican en compile time como objetos read-only
`IMMORTAL` con el mismo handle que un string heap. Viven todo el proceso y no se
copian al heap por asignación, call o return. `""` es un singleton no nulo.
Deduplicar literals es una optimización no observable, no interning público.

## UTF-8 y Unicode

Todo string publicado es UTF-8 estricto y representa Unicode scalar values.
U+0000 es contenido válido. No hay normalización, case folding, collation ni
locale implícitos. `char` es un scalar Unicode; graphemes y normalización
pertenecen a `Text.Unicode` con datos versionados.

Input byte inválido se rechaza antes de publicación. Decode lossy debe ser una
API futura explícita. Datos arbitrarios o UTF-8 inválido pertenecen a `Bytes`.

## Length e indexing

La longitud almacenada y O(1) es byte length, expuesta por una operación core
de nombre explícito como `byteLength(s) -> usize`. Code-point count es O(n) y
pertenece a `Text`; grapheme count requiere la capa Unicode.

No existe `s[i]`: no se oculta si el índice cuenta bytes, scalars o graphemes.
Byte access ocurre sobre `Bytes`/byte view; code-point access futuro es una
función `Text` de costo explícito.

## Concatenación e igualdad

```aether
string c = a + " world";
```

`+` toma prestados los operandos y produce un owner. Para dos textos no vacíos,
el bootstrap comprueba tamaños, hace una allocation exacta y copia ambos rangos:
O(suma de bytes). El resultado se transfiere a `c`; `a` sigue válido. Un fast
path vacío puede Alias el otro operando. No hay COW ni fusión obligatoria.

`==`/`!=` comparan contenido: identidad como fast path, luego longitud y bytes
exactos. Son allocation-free, O(n) worst-case e independientes de locale y
normalización. No se admiten operadores relacionales.

Hashing futuro debe usar los mismos bytes. Map/Set usarán seed por proceso; un
hash persistente será otra API versionada. No se cachea hash inicialmente.

## Slicing e iteración

El bootstrap no ofrece slicing ni views. La primera substring recomendada es
una operación `Text` por límites de code points que devuelve copia owned. Una
futura `StringView` será un descriptor borrowed distinto, con provenance, no
Storable bajo el lifetime actual; espera el diseño general de lifetimes.

La futura iteración canónica de `string` es por `char`, borrowed, sin allocation
y O(byteLength) total. Bytes y graphemes requieren APIs explícitas distintas.

## Core, runtime y standard library

| Frontera | Contenido |
|---|---|
| Lenguaje/core | tipo/literals, UTF-8 e inmutabilidad, lifecycle, `+`, igualdad, byte length y futura iteración por `char` |
| Runtime privado | layout, literals/vacío, allocation, validation, ARC, concat/equality, accessors y output length-aware |
| Core/IO | `print`/`println` toman string borrowed; no definen formatting general |
| STD `Text` | count/access por scalar, substring owned, search/replace/split/trim, parsing y formatting |
| STD `Text.Unicode` | graphemes, normalización, case y collation |
| Storage futuro | `Bytes`, byte views y eventualmente builder público |

`print` escribe exactamente los bytes por longitud, nunca usa `%s`/`strlen`.
Formatting/interpolation futuros son estáticos, left-to-right y pueden usar un
builder privado; no convierten string en mutable ni en class.

## FFI, fallos y exceptions

C recibe preferentemente un span borrowed `{data,length}` con keepalive, o un
opaque owned handle con retain/release versionados. El header no cruza la ABI.
Entrada externa se valida y copia. Un adapter `const char *` debe tratar NUL
embebido explícitamente. Ninguna excepción cruza `extern "C"`.

Size overflow, allocation failure y corrupción ARC son traps fail-fast no
capturables y sin promesa de unwind. Decode inválido es un error esperado
estructurado futuro. Bajo exceptions, strings ya inicializados ejecutan Drop en
cleanup; retain/release/drop nunca lanzan.

## Primer vertical acotado

**GENERAL-V1 — immutable UTF-8 string spine**, Linux x86-64 single-thread:

- literals/vacío, locals, assignment, direct by-value params y returns;
- Alias/Transfer/Drop, concat heap, igualdad y byte length;
- `print`/`println` borrowed y length-aware;
- cleanup normal, branches/early return y ARC no atómico;
- verificación independiente futura de HIR/MIR/SSA;
- O0/O2, counters, UTF-8 multibyte, NUL, overflow/OOM y sanitizers.

Quedan fuera aggregates/collections, generics, public FFI, threads, Bytes,
indexing, slicing/views, iteration, formatting/interpolation, Text algorithms,
hashing, COW, SSO, normalization, graphemes y recoverable exceptions.

## Decisiones abiertas

- spelling final de byte length y protocolo de miembros;
- grammar de escapes/multiline literals;
- layout físico y máximo por target/runtime;
- globales no literales y module initialization;
- vertical de composición en aggregates/collections;
- sintaxis de iteración y lifetimes de `StringView`;
- diseño de `Bytes` y resultado de UTF-8 decode;
- formatting/interpolation, locale y cleanup excepcional;
- hashing/container seed, concurrencia y ABI pública versionada;
- SSO, hash cache e interning dinámico sólo después de medición.
