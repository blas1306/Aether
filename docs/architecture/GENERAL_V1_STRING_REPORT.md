# GENERAL-V1 — immutable UTF-8 string spine

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-12, para el backend nativo
bootstrap Linux x86-64 de `compiler-next`. Este vertical implementa sólo la
primera superficie aprobada por
[GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md); no promueve ninguna API de texto
adicional.

## Representación y literals

`string` es un `TypeId` canónico fundamental, no una clase. Un valor runtime es
un handle opaco no nulo de una palabra. En el target calificado apunta a un
objeto privado contiguo con tres palabras de cabecera —byte length, strong count
y flags— seguidas de los bytes UTF-8 y un cero auxiliar fuera del contenido.
Los offsets y flags siguen siendo ABI privada.

Los literales se decodifican y validan en frontend, se conservan como bytes en
la operación tipada y se emiten como constantes privadas inmortales. Literales
iguales se deduplican dentro del módulo. `""` usa un singleton estático no nulo.
Asignar, pasar o retornar un literal no asigna heap. ASCII, UTF-8 multibyte,
vacío, escapes y U+0000 embebido están cubiertos por ejecución nativa.

Las propiedades centrales son exactamente `Copy=false`, `Relocatable=true`,
`Storable=true`, `needs_drop=true`. `Storable` expresa la propiedad verdadera
del valor; GENERAL-V1 mantiene gates separados que todavía rechazan fields,
payloads, colecciones y genéricos de string.

## Ownership y ARC

Una lectura owning de lvalue genera `Alias`; el source continúa válido y el
nuevo owner adquiere su propia obligación. Un fresh result se mueve mediante
la ruta general `Transfer`/`Move`, sin retain. Assignment adquiere o produce el
RHS antes de destruir el owner reemplazado; el caso `x = x` se reconoce sin
introducir un ciclo retain/release innecesario. Parámetros directos by-value y
returns distinguen lvalue de fresh con la misma regla. Cada owner restante
termina en `Drop` en salida normal, return temprano o unwind.

El backing heap comienza con strong count 1 y usa ARC no atómico. Alias hace
retain; Drop hace release; el último release invalida el count, incrementa la
evidencia de free y libera exactamente una vez. Overflow de retain, underflow,
null o flags inválidos son corrupción y hacen trap. Un literal conserva las
mismas obligaciones lógicas, pero retain/release no toca su strong count ni lo
libera; un contador privado permite observar estos no-op durante qualification.

## Concat, igualdad y longitud

`string + string` evalúa izquierda y derecha en orden y presta ambos operands.
Si uno está vacío retorna un Alias del otro. Con dos operands no vacíos usa dos
sumas checked, una allocation exacta, una copia de cada rango y un cero auxiliar;
el resultado es un fresh owner y ninguno de los operands se modifica. Overflow
de tamaño y OOM siguen las trampas `AllocationSizeOverflow` y
`AllocationFailure`; ambos caminos se ejecutan mediante inyección de LLVM en la
qualification.

`==` y `!=` son igualdad/desigualdad por contenido. La implementación usa
fast paths de mismo handle, distinta longitud y vacío, y luego `memcmp` sobre la
longitud exacta. No hay identidad pública ni comparación por terminador.

`byteLength(s) -> usize` es el único spelling bootstrap de longitud. Lee la
longitud almacenada en O(1) y cuenta bytes, no Unicode scalar values ni
graphemes. No se introdujo un protocolo general de properties o members.

## Output, UTF-8 y U+0000

En este vertical `print` y `println` aceptan únicamente `string`. El runtime
escribe el rango `(data, byte_length)` con un loop que tolera writes parciales;
`println` agrega exactamente un byte LF. No usa `strlen`, `%s` ni el cero
auxiliar para decidir dónde termina el contenido. La prueba nativa verifica los
siete bytes `A 00 B h C3 A9 0A`.

Todo valor publicable proviene de un literal UTF-8 validado o de concat de dos
valores ya válidos, por lo que el invariant de UTF-8 se preserva. U+0000 es un
byte válido dentro del contenido. No se añadió `Bytes`, decode, normalización,
case folding, collation ni manejo de graphemes.

## HIR, MIR y SSA

El vocabulario común `StringOp<O>` contiene `Literal`, `Alias`, `Concat`,
`Equal`, `ByteLength` y `Output`. HIR conserva literal bytes, tipo/result y la
decisión lvalue Alias; `StringOutput` es un efecto explícito. MIR materializa
owners temporales, `Move`/Transfer y `Drop`, incluyendo cleanup antes de returns
y en landing pads. SSA conserva las operaciones tipadas y añade una auditoría
independiente: todo value string owning necesita un consumo explícito por Move,
call by-value, return, phi o Drop.

Los verificadores de las tres fases reconstruyen tipos de operands y results.
HIR rechaza Alias que no provenga de lvalue y bytes no UTF-8; MIR valida metadata
y su ledger path-sensitive; SSA valida metadata, dominancia/tipos y descarga de
owners. Las pruebas corrompen de forma independiente UTF-8 y result type en HIR,
result/op en MIR, result type y Drop en SSA, y comprueban rechazo en la fase
correspondiente.

## Runtime y LLVM

El backend traduce únicamente `StringOp`, Move y Drop ya verificados. Un módulo
backend separado concentra literals y el ABI runtime privado:
`length/data/retain/release/concat/equal/write`. Los helpers se emiten sólo si
una firma o body compilado usa string; un programa escalar no contiene símbolos
`aether_string_*`. Cuando excepciones y string coexisten, la declaración común
de `write` se emite una sola vez.

Concat usa `llvm.uadd.with.overflow.i64`, `llvm.memcpy`, el allocator central y
su trap de OOM. Equality usa `memcmp`; output usa `write`. El lifecycle usa loads
y stores ordinarios, nunca atomics, lo cual deja el perfil explícitamente
single-thread. Los objetos literales y el vacío son constantes privadas con el
mismo header y flag inmortal.

## Qualification y corrupciones

La fixture `compiler-next/tests/programs/general_v1_string_smoke.ae` y
`crates/aether-driver/tests/general_v1_string.rs` cubren:

- literals ASCII, multibyte, vacío y NUL; locals, assignment y self-assignment;
- Alias literal/heap, Transfer fresh, parámetros y returns lvalue/fresh;
- concat no vacío, ambos fast paths vacíos, igualdad/desigualdad literal/heap;
- byteLength ASCII/multibyte/NUL y output binario exacto;
- ramas, early return, free final único y ausencia de heap para literal
  assignment/pass/return;
- overflow y OOM inyectados como traps, corrupción HIR/MIR/SSA y ausencia del
  runtime string en un programa sin string;
- unwind después de inicializar un heap string: un release y un free exactos,
  en O0 y O2.

Los casos instrumentados observan los mismos eventos lógicos en O0 y O2. Por
ejemplo: fresh concat produce `(alloc=1, free=1, retain=0, release=1,
concat=1)`; agregar un heap Alias produce `(1,1,1,2,1)`; pasar el fresh concat
by-value vuelve a `(1,1,0,1,1)`; cada fast path vacío produce cero alloc/free y
un concat, con ARC de literals únicamente en la ruta no-op. Literal
assignment/pass/return permanecen en cero alloc/free/retain/release.

## Medición O0/O2

Medición descriptiva realizada sobre la fixture anterior con el driver y
toolchain locales, no como garantía ABI ni claim de costo cero:

| build | archivo ELF | text | data | bss | alloc/free semántico | ARC/ops |
|---|---:|---:|---:|---:|---|---|
| O0 | 18,136 B | 5,467 B | 616 B | 88 B | según el mismo programa | sin elisión string |
| O2 | 17,040 B | 3,762 B | 616 B | 80 B | igual a O0 | mismos retain/release/concat/equality |

Como control, `return_zero.ae`, que no usa string, produjo 16,504 B / 1,406 B
de text en O0 y 15,896 B / 1,129 B de text en O2, sin runtime string. La
diferencia de tamaño mezcla helpers, literals y el programa de prueba; no aísla
un costo marginal universal. O2 reduce código de máquina general, pero este
vertical no incorpora una pasada de elisión ARC específica para string y no se
hace ningún claim zero-cost.

## Scope cerrado y deuda restante

Permanecen rechazados fields de struct/class y payloads de enum;
Array/List/Buffer/Vector/Matrix de string; genéricos y referencias con string;
indexing, slicing/views, iteration, Bytes, interpolation/formatting,
parsing/Text APIs, hashing, COW, SSO, normalization/graphemes, public FFI y
threads.

Deuda deliberada: extraer/versionar el runtime privado fuera del emisor textual
cuando exista el mecanismo de runtime artifacts; calificar targets además de
Linux x86-64; decidir una futura política de ARC optimization para string con
reverificación; y promover por vertical separado cualquier almacenamiento en
aggregates/collections, borrowing, Unicode/Text o frontera pública. Nada de esa
deuda queda implícitamente admitido por GENERAL-V1.
