# TEXT-UTF8-BUILDER-ARCH-1 — materialización owned de UTF-8 dinámico

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Este milestone cierra la capability general que faltaba para publicar como
`string` un prefijo dinámico de bytes UTF-8. No modifica source productivo,
compiler, runtime, tests ni la superficie actualmente admitida. La
implementación y qualification pertenecen a **TEXT-UTF8-BUILDER-V1**.

La motivación inmediata fue el bloqueo documentado por
[GRAPHICS-SVG-BACKEND-ARCH-1](GRAPHICS_SVG_BACKEND_ARCH_1.md), pero la decisión
pertenece exclusivamente a `std.Text`: no conoce Scene, SVG, XML, graphics ni
ningún consumer concreto.

## 1. Decisión resumida

`std.Text` agrega exactamente esta superficie pública:

```aether
package std.Text;

public class InvalidUtf8Exception : Exception {
    public init() {}
}

public string fromUtf8(ref Buffer<uint8> bytes, usize length);
```

`length` selecciona el prefijo semiabierto `[0, length)` del Buffer. La función:

1. comprueba `length <= length(*bytes)`;
2. retorna el singleton vacío si `length == 0`;
3. valida estrictamente sólo el prefijo seleccionado;
4. ante UTF-8 inválido lanza `std.Text.InvalidUtf8Exception`;
5. ante éxito crea un string exacto e independiente copiando el prefijo una
   sola vez.

La materialización exitosa es O(`length`). La validación y la copia pueden ser
dos recorridos lineales; no se exige one-pass.

No entra `TextBuilder` en este vertical. `fromUtf8` es la primitive fundamental
y suficiente para un serializer que ya mantiene bytes dinámicos. Un builder
público posterior puede centralizar growth y usar esta función en `finish`, sin
cambiar su contrato.

El nombre del milestone conserva “BUILDER” por continuidad con el prerrequisito
identificado por graphics; no implica que una class builder forme parte de la
API cerrada.

## 2. Autoridad y alcance

Esta decisión compone con:

- [AETHER_V1_SEMANTIC_CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md): `uint8`,
  `usize`, borrows, Buffer, bounds, traps y string UTF-8;
- [GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md) y GENERAL-V1/V2: representación
  opaca, singleton vacío, ARC, Alias/Transfer/Drop y ownership de string;
- [TEXT-BYTE-ACCESS-ARCH-1](TEXT_BYTE_ACCESS_ARCH_1.md): observación bytewise
  sin exponer el backing;
- [FORMAT-ARCH-1](FORMAT_ARCH_1.md) y FORMAT-V1: formatting existente y
  construcción lineal privada de strings;
- [EXCEPTION-ARCH-2](EXCEPTION_ARCH_2.md): exceptions nominales unchecked,
  unwind determinista y separación respecto de traps;
- el Buffer/storage/lifecycle vigente y su descriptor interno contiguo.

La decisión no agrega sintaxis, indexing de string, raw pointers, FFI, Bytes,
normalización, transcoding, un formatter, un writer genérico, transferencia de
backing ni un constructor público unchecked.

## 3. Por qué `fromUtf8` y no `TextBuilder`

Se evaluaron las dos superficies pedidas.

### 3.1 Primitive elegida

```aether
public string fromUtf8(ref Buffer<uint8> bytes, usize length);
```

Es el mínimo irreducible: toda solución segura debe validar bytes externos y
crear el owner string sin revelar su layout. Resuelve Buffers exactos y Buffers
con capacidad sobrante, y permite que cada producer elija su propia estrategia
de storage sin introducir estado mutable nuevo en `std.Text`.

El caller puede implementar growth geométrico con el Buffer fijo vigente:
reserva uno mayor, copia el prefijo lógico y reemplaza el owner anterior. La
suma de copias de growth es O(total de bytes), y `fromUtf8` agrega una última
validación y copia O(total). No hay concatenación de strings.

### 3.2 Builder diferido

La alternativa considerada fue una class mutable one-shot con Buffer privado,
logical length, growth geométrico, append de byte/ASCII/string y `finish()`.
Sería útil si muchos consumers repiten exactamente esa policy, pero obliga a
cerrar ahora cuestiones adicionales:

- constructors, capacidad inicial, growth y overflow;
- estado después de `finish` y error de uso posterior;
- si `appendByte` admite bytes arbitrarios o mantiene UTF-8 válido en cada paso;
- append de rangos, ASCII y strings, y su tratamiento de errores;
- mutabilidad, methods, exception safety y cleanup de una class pública;
- relación futura con un byte writer general, IO streaming y formatting.

Nada de eso es necesario para publicar correctamente un Buffer ya construido.
El consumer que originó el requisito ya necesita buffers privados adicionales y
growth propio, por lo que un builder no elimina su maquinaria completa.

La decisión es por ello **primitive ahora, builder sólo por evidencia posterior**.
No se reservan hoy nombres de methods ni invariantes de `TextBuilder`.

## 4. Firma, borrow y prefijo

`bytes` es exactamente `ref Buffer<uint8>`:

- el Buffer debe existir durante la call;
- la función no lo consume, mueve, reemplaza ni modifica;
- no conserva el reference después del retorno o unwind;
- `uint8` expresa octetos sin semántica textual previa;
- `length` es `usize`, como el length y los índices de Buffer.

La comprobación de bounds precede cualquier lectura. Si `B` es el length físico:

```text
length <= B  -> se procesa exactamente [0,length)
length > B   -> trap IndexOutOfBounds, sin leer storage
```

Los bytes `[length, B)` no se leen ni validan. Pueden contener capacidad sin
usar, ceros de fill o UTF-8 inválido. En cambio, si el prefijo termina en medio
de una secuencia cuyo resto está después de `length`, el prefijo es truncado y
se rechaza.

No se agregan overloads para `Array<uint8>`, `View<uint8>`, `List<uint8>` ni un
rango `(start,end)`. No hay evidencia que justifique cuatro superficies, y una
futura abstracción byte-span debe cerrar lifetime y composición de forma general
antes de reemplazar o envolver esta primitive. El prefijo cubre el caso real de
capacidad mayor que longitud lógica sin otra allocation.

## 5. Validación UTF-8 normativa

La validación consume exactamente el prefijo y acepta sólo estas formas:

```text
00..7F
C2..DF 80..BF
E0 A0..BF 80..BF
E1..EC 80..BF 80..BF
ED 80..9F 80..BF
EE..EF 80..BF 80..BF
F0 90..BF 80..BF 80..BF
F1..F3 80..BF 80..BF 80..BF
F4 80..8F 80..BF 80..BF
```

Esto admite ASCII, extremos Unicode, secuencias de dos/tres/cuatro bytes,
emoji, combining marks, BOM, U+0000, TAB, LF, CR y los demás controles o
noncharacters que sean Unicode scalar values válidos. Los bytes se preservan
exactamente.

Se rechazan:

- continuation bytes aislados;
- lead bytes `C0`, `C1`, `F5..FF`;
- continuations ausentes o fuera de `80..BF`;
- secuencias truncadas;
- encodings overlong;
- encodings de `U+D800..U+DFFF`;
- code points mayores que U+10FFFF;
- cualquier otra forma no incluida arriba.

No se normaliza, no se aplica case folding y no se reemplaza con U+FFFD. Dos
secuencias canónicamente equivalentes pero bytewise distintas permanecen
distintas, de acuerdo con el contrato vigente de string.

## 6. Resultado y ownership

Un retorno normal produce un owner `string` ordinario:

- es immutable, non-null, UTF-8 válido y length-aware;
- su byte length es exactamente `length`;
- contiene exactamente `bytes[0:length]`, incluido cualquier U+0000;
- usa Transfer/Drop, ARC y relocation ordinarios;
- no expone identidad de backing ni capacidad sobrante;
- no aliasa la allocation del Buffer.

Después del retorno, mutar elementos del Buffer o destruirlo no cambia el
resultado. Destruir el string tampoco afecta el Buffer. Esta independencia es
obligatoria incluso si una implementación futura detecta que el Buffer parece
tener un solo owner.

No se promete zero-copy. La firma borrowed no transfiere el Buffer, su backing
no tiene el header/lifecycle de string y puede ser mutable. Una futura operación
de transferencia requeriría una primitive y prueba de layout/lifetime distintas.

## 7. Vacío

Tras comprobar bounds, `length == 0` retorna un owner lógico del singleton
canónico `""`. No valida ni observa bytes posteriores y no hace allocation heap.
El retain/release físico del literal inmortal permanece no-op, aunque el valor
source conserva su obligación ordinaria de owner.

No se construye un objeto heap de header más terminador para el vacío y no se
retorna `null` ni un handle especial nuevo.

## 8. Errores y precedencia

Los fallos se separan así:

| Situación | Resultado público | Cleanup/unwind |
|---|---|---|
| `length > buffer length` | trap `IndexOutOfBounds` | fail-fast, no unwind prometido |
| prefijo UTF-8 inválido | `throw std.Text.InvalidUtf8Exception()` | unwind ordinario |
| `length + overhead` no representable | trap `AllocationSizeOverflow` | fail-fast |
| allocation final falla | trap `AllocationFailure` | fail-fast |
| corrupción de runtime/ARC | trap de invariante | fail-fast |

Bounds tiene precedencia sobre vacío, validación y allocation. Validación
tiene precedencia sobre la allocation del string final. No se intenta ocultar
un bug de rango como “UTF-8 inválido”, y OOM no se convierte en una exception de
contenido.

`InvalidUtf8Exception` es final, no tiene fields, message, offset ni copia de
los bytes ofensivos en V1. Es unchecked como toda exception Aether; la firma no
incorpora `throws`. El caller puede capturarla y continuar usando el Buffer,
que no fue consumido ni modificado. Si construir la propia exception no puede
asignar, rige `AllocationFailure`: no se sustituye por otra exception ni se
publica un string.

No se reutiliza `std.IO.InvalidTextEncodingException`: esa clase deriva de
`IOException` y clasifica un fallo de una operación IO. Hacer que `std.Text`
dependa de IO invertiría la capa y volvería engañosa la jerarquía. Tampoco
`std.Process.InvalidArgumentEncodingException` es general. Por eso una
exception específica de la conversión UTF-8 es necesaria; no se crea una
jerarquía nueva ni una exception graphics.

Esta elección cierra la “forma estructurada” que GENERAL-ARCH-1 había dejado
abierta para esta API concreta. No obliga a que todo parser o validator futuro
use exceptions: los resultados nominales vigentes de `parseInt`, `parseDouble`
y `byteSlice` conservan su contrato.

## 9. Atomicidad

El orden normativo es:

```text
capturar borrow y descriptor
check bounds
fast path vacío
validar todo el prefijo
si inválido: construir/lanzar exception
comprobar tamaño de la allocation string
reservar backing final exacto
inicializar header privado
copiar length bytes
escribir terminador privado si el layout lo requiere
publicar el owner de retorno
```

La validación no asigna ni escribe. No existe un string parcial durante ella.
En la ruta válida, después de obtener la allocation final sólo quedan stores y
una copia que no lanzan; el owner se entrega al programa una vez inicializado
por completo.

Si bounds o validación fallan, no hay allocation string. Si el checked size o
allocator hacen trap, no se publica owner. La exception de UTF-8 es un owner de
clase separado y sigue el lifecycle/unwind general; no es un string parcial.

Dos pasadas son deliberadas. Validar antes de reservar/copy simplifica el
lifecycle, evita liberar un objeto string provisional ante input inválido y
mantiene la precedencia observable de errores.

## 10. Representación y allocations exactas

La representación bootstrap auditada es un handle opaco a un objeto contiguo
con byte length, strong count, flags privados, `length` bytes y un cero auxiliar.
El header vigente ocupa 24 bytes y la allocation heap no vacía solicita
exactamente `length + 25` bytes con alineación 8. Esos números son evidencia del
bootstrap y gates de qualification, no ABI pública.

Por call:

| Ruta | Allocations de string | Otras allocations nuevas |
|---|---:|---|
| bounds trap | 0 | 0 |
| `length == 0` | 0 | 0; singleton inmortal |
| UTF-8 inválido | 0 | una class `InvalidUtf8Exception`; el record privado de unwind sigue la policy general |
| éxito no vacío | exactamente 1 | 0 |
| overflow/OOM final | 0 owners publicados | un intento de allocation como máximo |

El Buffer de entrada y cualquier allocation previa del producer no cuentan
como allocations creadas por `fromUtf8`. La validación usa O(1) storage auxiliar
y no crea string por byte, lista, tabla de scalars ni copia temporal.

En éxito no vacío, la infraestructura vigente `aether_string_allocate` /
`aether_string_from_buffer` ya ofrece allocation exacta, terminador privado,
copy y count uno. La implementación debe reutilizar esa infraestructura, no
duplicar el layout en std source.

## 11. Complejidad y peak

Para `n = length`:

```text
bounds:       O(1)
validation:   O(n), cada byte leído un número constante de veces
publication:  O(n), una copia exacta
total:        O(n)
auxiliar:     O(1), excluyendo resultado
peak propio:  O(n), exactamente un backing string no vacío
```

Durante el retorno exitoso coexisten el Buffer del caller y el string final.
Por tanto el peak del flujo completo incluye ambos owners; `fromUtf8` no
promete adoptar ni liberar el source.

Para un producer con growth geométrico, append total es amortized O(total de
bytes) y la materialización final agrega O(total). Esto sigue siendo O(total),
aunque el constant factor incluya growth, validation y final copy.

Quedan prohibidos en la implementación:

- concatenación incremental de strings;
- `byte -> string` por iteración;
- lista de strings seguida de concat repetida;
- rescanning desde el inicio por cada code point;
- allocation o exception por byte válido;
- cualquier algoritmo O(n²).

## 12. Frontera std/runtime

La función y la exception pertenecen al package canónico `std.Text`. La
superficie source no conoce raw pointers ni el layout de string.

El source Aether ordinario puede comprobar bytes mediante indexing de Buffer,
pero no puede reservar/publicar un string sin romper la opacidad del tipo. Por
ello TEXT-UTF8-BUILDER-V1 debe agregar un helper runtime **general** y privado,
conceptualmente:

```text
tryTextFromUtf8Prefix(data, bufferLength, length)
    -> Invalid | OwnedString
```

Su ABI física puede ser un tag más un handle privado. Debe:

- comprobar bounds antes de dereference;
- aplicar el validador estricto general;
- retornar status inválido sin crear string;
- reutilizar la allocation/copy general de string en éxito;
- no lanzar una exception Aether por sí mismo;
- no aceptar package, consumer, graphics o SVG como argumento/allowlist.

El adapter de la función STD traduce únicamente el status inválido a
`InvalidUtf8Exception`. Así la frontera runtime sigue independiente del modelo
de clases y la call pública conserva un exceptional edge explícito.

El validador LLVM hoy llamado `aether_process_utf8` ya implementa los rangos
estrictos correctos, pero su ownership nominal por Process es accidental. El
vertical debe extraerlo o reemplazarlo por un helper general compartido. No
debe copiar ese algoritmo por tercera vez. Process e IO pueden reutilizarlo sin
cambiar sus APIs o excepciones.

`aether_string_from_buffer` ya es general y length-aware, pero presupone bytes
válidos. Permanece privado. La nueva frontera combina validación y publicación
de modo que ningún package OAL pueda invocar un constructor unchecked.

## 13. HIR, MIR, SSA y efectos

`fromUtf8` se representa como una **call directa ordinaria** a la identidad
canónica toolchain `std.Text.fromUtf8`, no como `StringOp`, `TextOp` ni syntax.
La razón es semántica: puede lanzar una exception y las calls ordinarias ya
conservan successors de unwind y cleanup; los `TextOp` vigentes son Rvalues sin
flujo excepcional.

El resolver especial bootstrap de `std.Text` debe delegar esta identidad al
catálogo de funciones ordinario y adaptar exactamente:

```text
arg0: ref Buffer<uint8>
arg1: usize
ret:  string fresh owner
effect: may_allocate + may_unwind + may_trap
```

- HIR conserva `FunctionInstanceInfo`, `CallSiteId`, borrow y resultado owning.
- MIR termina el borrow en retorno normal o unwind y no inicializa el destino
  antes del retorno exitoso.
- SSA exige el exceptional successor cuando hay cleanup vivo, verifica tipos y
  conserva la obligación de Drop del string sólo en el path normal.
- LLVM materializa la call/std adapter por identidad canónica y baja el helper
  runtime privado. O0/O2 no pueden borrar bounds/validación ni mover la
  publicación antes de ellos.

Un import alias resuelve a la misma identidad. Un package usuario llamado
`std.Text`, una función homónima o un package con el mismo spelling fuera del
origin Toolchain no adquiere el adapter. No hay allowlist de consumers.

## 14. Reachability

Importar `std.Text` sin usar `fromUtf8` no emite el helper de conversión, el
validador por esta causa ni el descriptor de `InvalidUtf8Exception`. Usar otras
operaciones Text tampoco debe arrastrar la nueva ruta.

Cuando `fromUtf8` es alcanzable, se emiten la función STD, helper general y
metadata de exception necesaria. Si Process/IO ya hacen alcanzable el mismo
validador, debe existir una sola definición privada por artefacto.

Reachability se decide por identidades verificadas, nunca buscando el texto
`fromUtf8` en source o concediendo privilegios a `graphics.svg`.

## 15. Interacción con formatting

FORMAT-V1 no cambia. `str(int)`, `str(double)` y las demás conversiones
canónicas pueden seguir creando strings temporales. Un serializer puede copiar
sus bytes mediante `std.Text.byteAt`, destruir el temporal y finalmente llamar
`fromUtf8` una vez.

Esto puede producir allocations escalares secuenciales, pero no concat
cuadrática y no bloquea este vertical. `appendFormat`, format-to-writer,
protocols de formatting y fusión con un builder quedan para decisiones futuras.

La interpolation conserva su ruta fusionada de una allocation exacta. No se
reescribe en términos de `fromUtf8`, ni esta API expone su builder privado.

## 16. Dirección compatible para un builder futuro

Si evidencia posterior justifica `TextBuilder`, la dirección compatible es:

- class mutable, owning y one-shot;
- Buffer `uint8` privado, logical length y growth geométrico checked;
- append total amortized O(bytes);
- append de string por borrow y copia bytewise/privada;
- `finish()` llama conceptualmente `fromUtf8`, publica un owner independiente y
  sella el builder;
- finish O(total), sin concat ni generic formatting.

Si ofrece append de bytes arbitrarios, el builder puede estar temporalmente
inválido y `finish` debe lanzar `InvalidUtf8Exception`. Si promete validez
incremental, no puede admitir un byte suelto de una secuencia multibyte sin un
estado decoder explícito. Esa elección queda abierta y es precisamente una razón
para no agregar la class ahora.

## 17. Qualification de TEXT-UTF8-BUILDER-V1

La fixture dedicada recomendada es:

```text
compiler-next/crates/aether-driver/tests/text_utf8_builder_v1.rs
compiler-next/tests/programs/text_utf8_builder_v1_smoke.ae
```

Debe ejecutar source→native en O0 y O2.

### 17.1 Casos positivos

- Buffer vacío y prefijo cero sobre Buffer no vacío/inválido;
- ASCII y extremos `U+0000`, `U+007F`, `U+0080`, `U+07FF`, `U+0800`,
  `U+FFFF`, `U+10000`, `U+10FFFF` cuando sean scalars;
- UTF-8 de dos, tres y cuatro bytes, emoji y combining marks sin normalizar;
- BOM, TAB, CR, LF y NUL embebido;
- prefijo válido con trailing garbage o secuencia inválida no seleccionada;
- payload dinámico grande con growth previo;
- byte length y bytes exactos del resultado mediante `byteLength`/`byteAt`;
- Buffer mutado y destruido después del retorno sin cambiar el string;
- resultado retornado, almacenado, movido y destruido con lifecycle ordinario.

### 17.2 Casos negativos

- `length > buffer length` en subprocess y trap `IndexOutOfBounds` preciso;
- `80..BF` aislados, `C0`, `C1`, `F5..FF`;
- secuencias 2/3/4 truncadas en cada boundary;
- continuation ausente o byte ASCII en su lugar;
- overlong de 2/3/4 bytes;
- `ED A0..BF ...` (surrogates);
- `F4 90..BF ...` y otros valores mayores que U+10FFFF;
- prefijo que corta una secuencia aunque sus continuations existan en trailing;
- catch nominal de `InvalidUtf8Exception` y Buffer aún usable después;
- exception no capturada reportada con identidad `std.Text`.

### 17.3 Atomicidad y lifecycle

- cero string allocations en bounds, vacío e invalid UTF-8;
- una string allocation exacta en cada éxito no vacío;
- count uno y un free final para resultado heap;
- singleton sin free para vacío;
- no owner string parcial en el path excepcional;
- exception owner y record liberados por catch/unwind conforme al runtime;
- Buffer no consumido y allocation/free balance global cero al salir;
- cleanup correcto si una exception posterior ocurre con el resultado vivo.

### 17.4 Performance/resource gate

El gate no debe depender sólo de wall-clock. Instrumentación de test o
inspección del lowering debe demostrar para payloads crecientes:

- bytes validados y copiados proporcionales a `n`;
- una allocation string no vacía, independiente de `n`;
- cero `aether_string_concat`;
- cero allocations por byte;
- storage auxiliar constante;
- un loop de validación y una copia/publicación, sin loops anidados sobre el
  mismo prefijo.

### 17.5 IR y source gates

- call canónica ordinaria, result owner y unwind edge visibles en HIR/MIR/SSA;
- rechazo independiente de operand type, return type, borrow metadata, Drop y
  exceptional successor corruptos;
- ausencia de `TextOp::FromUtf8`, opcode SVG, FFI y raw string constructor
  público;
- ausencia de import/dependencia `graphics` o `graphics.svg`;
- ausencia de package/consumer allowlists y dispatch por spelling;
- helper/exception ausentes cuando no son alcanzables;
- O0/O2 con bytes y clasificación de fallos equivalentes.

## 18. Regresiones y cierre del vertical

TEXT-UTF8-BUILDER-V1 debe ejecutar, como mínimo:

```text
cargo test -p aether-driver --test text_utf8_builder_v1
cargo test -p aether-driver --test text_byte_access_v1
cargo test -p aether-driver --test text_v1
cargo test -p aether-driver --test general_v1_string
cargo test -p aether-driver --test general_v2_string_composition
cargo test -p aether-driver --test format_v1
cargo test -p aether-driver --test process_args_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

La suite debe cubrir además Buffer bounds/ownership/drop, exception catch y
unwind, strings/interpolation/formatting y los tests IO que ya validan UTF-8.
Los nombres exactos de targets existentes pueden ajustarse si Cargo difiere;
las áreas de regresión son normativas.

## 19. Alternativas evaluadas

| Alternativa | Decisión |
|---|---|
| `fromUtf8(ref Buffer<uint8>, usize)` | **elegida**: primitive mínima, prefijo, borrow, validación y owner exacto |
| `TextBuilder` como única API | diferida: aún necesita publicación privilegiada y abre demasiado contrato mutable |
| primitive más Builder en el mismo vertical | rechazada: dos superficies sin evidencia; Builder puede construirse encima después |
| consumir `Buffer<uint8>` y adoptar backing | rechazada: firma/lifecycle/layout incompatibles y no sirve a callers que conservan el Buffer |
| overloads Array/View/List | diferidos: conveniencia sin necesidad demostrada y mayor matriz de lifetime/storage |
| `Utf8Result` nuevo | rechazada para esta firma: la API cerrada retorna string y usa la exception nominal recuperable solicitada |
| reutilizar exception IO/Process | rechazada: categoría y dirección de dependencia incorrectas |
| reemplazar inválidos con U+FFFD | rechazada: lossy y rompe preservación exacta |
| normalizar Unicode | rechazada: cambia bytes y contrato de igualdad |
| public raw/unchecked string constructor | rechazada: permite violar el invariante fundamental |
| concatenación incremental | rechazada: O(n²) y allocations intermedias |
| helper específico SVG/allowlist | rechazada: acoplamiento y privilegio por consumer |
| zero-copy borrowed string | rechazada: mutabilidad/lifetime incompatibles con owner string |

## 20. Consecuencias y secuencia

La arquitectura queda **CLOSED**. La superficie pública crece en una función
y una exception nominal, sin Builder, overloads ni layout expuesto.

La secuencia autorizada es:

```text
TEXT-UTF8-BUILDER-V1
GRAPHICS-SVG-BACKEND-V1
```

Al calificarse el primer vertical, el blocker de materialización descrito por
GRAPHICS-SVG-BACKEND-ARCH-1 queda resuelto. Esto no implementa graphics ni
reabre el contrato SVG; simplemente le entrega, como a cualquier serializer,
una conversión general segura y O(n).
