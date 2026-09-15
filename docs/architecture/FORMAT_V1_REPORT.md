# FORMAT-V1 — canonical scalar strings and interpolation

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-14, para el target bootstrap
Linux x86-64 de `compiler-next`.

## Resultado

Core/prelude incorpora la familia cerrada `str(value) -> string` para todos los
enteros signed/unsigned, `isize`/`usize`, `float32`/`float64`, `bool` y `char`.
Los aliases transparentes resuelven a la misma firma canónica. `string`, tipos
nominales, collections, tipos matemáticos, genéricos y referencias continúan
rechazados. La identidad resuelta permanece como `CoreCall`; cada resultado no
vacío es un owner heap fresh y el vacío usa el singleton existente.

Los enteros se emiten en decimal ASCII sin negar el mínimo signed en su propio
tipo. Bool usa exclusivamente `true`/`false`. `char` es ahora un scalar Copy de
cuatro bytes y su formatter valida el Unicode scalar value antes de emitir de
uno a cuatro bytes UTF-8; U+0000 conserva el byte cero como contenido.

El formatter float obtiene el significando decimal shortest del tipo IEEE
original mediante la frontera locale-independent `to_chars` del toolchain
bootstrap y aplica dentro del runtime Aether la policy normativa: fixed para
exponente ajustado `[-6, 21)`, scientific fuera, `.`/`e`, signo de exponente
obligatorio y sin ceros iniciales. Signed zero, infinities y NaN se clasifican
por bits y producen `0`, `-0`, `Inf`, `-Inf` y `NaN`. La policy y los bytes
publicados son del runtime Aether; no se usa `%f`, `snprintf`, locale ni rounding
mode ambiental. Extraer/versionar el motor shortest para independizarlo del
runtime C++ del target queda como deuda de portabilidad, no como superficie.

## Parser e interpolación

El lexer conserva una literal interpolada como una unidad y busca el `}` de
profundidad cero respetando strings, comentarios y braces internos. Sólo `${`
abre un field. `$`, braces aislados, `{{` y `}}` son texto ordinario; `\${`
decodifica a `${` sin abrir un field. El parser vuelve a usar la gramática de
expresiones ordinaria para cada hole con offsets y `SourceId` originales.
`${}` y fields sin cierre tienen diagnósticos dedicados y spans field-wide.
Una literal sin holes conserva `StringOp::Literal` inmortal.

HIR representa `StringOp::Interpolate` como una secuencia ordenada de
`InterpolationFragment`: chunks UTF-8 y holes con expresión, `TypeId`, span y
conversión `StringBorrow` o `CanonicalScalarFormat`. El plan lleva ownership
`Fresh` y tamaño `CheckedExact`. El verifier reconstruye tipos y conversiones,
valida UTF-8, orden/no solapamiento de spans y metadata de resultado. No existe
desugaring a `str + concat`.

## Evaluación, ownership y allocation

MIR baja los operands una vez y de izquierda a derecha. Un string lvalue pierde
el `Alias` sintético y queda borrowed; un string temporary queda capturado como
owner. Los temporales capturados se registran durante la evaluación de holes
posteriores, de modo que landing pads los destruyen en orden inverso. Después
de publicar el resultado se destruyen exactamente una vez en el camino normal.

SSA conserva el plan completo. Sus verificadores ordinarios, junto con el
verifier de `StringOp`, validan tipos de operands/results, ownership único y
Drop por camino; el orden está fijado por el vector de fragments y sus spans.
El backend suma cada longitud con `llvm.uadd.with.overflow`, reserva/publica un
único backing exacto no vacío y copia/escribe cada fragment directamente. Los
escalares usan buffers privados de tamaño acotado, nunca owners `string`; no hay
cadenas de concat ni strings intermedios. El resultado vacío retorna el
singleton sin heap allocation.

## Output y runtime

`print(string)` y `println(string)` no cambiaron. Una interpolación usada como
argumento se presta a output y su owner se libera una vez tanto al retornar
como en el landing pad de `IOException`. El runtime conserva operaciones
length-aware, por lo que U+0000 no corta output.

Los helpers privados cubren decimal signed/unsigned, bool, UTF-8 char, float
shortest/normalización y allocation/publicación. Se emite el bloque FORMAT sólo
si existe un `CoreCall::Str` o `StringOp::Interpolate`; programas que sólo usan
strings ordinarios no enlazan formatting. La selección más fina por categoría
de helper queda como deuda menor del bootstrap.

## Qualification

`crates/aether-driver/tests/format_v1.rs` cubre O0/O2, MIN/MAX representativos
de todos los anchos, aliases canónicos por contextualización, bool, chars UTF-8
de uno a cuatro bytes y U+0000, signed zero, NaN/Inf, umbrales fixed/scientific,
output byte-exact, texto `$`/braces/`\${`, fields vacíos/sin cierre, rechazo de
tipos no soportados, presencia del plan en HIR/MIR/SSA, ausencia de concat y
reachability. Las suites generales existentes siguen calificando integer/float
conversion, ownership path-sensitive, traps, IO excepcional y equivalencia
nativa O0/O2.

La calificación de cierre ejecuta `cargo test --workspace`, `cargo fmt
--all --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
`git diff --check` y `compiler-next/tests/run-differential.sh`.

## Scope y deuda restante

No se implementó `std.Format`, parsing string→number, specifiers, width,
padding, sign policy, formatting user-defined, output variádico, builders
públicos, reflection ni logging. También quedan como trabajo posterior una
partición exhaustiva automatizada de los 2³² patrones binary32 (la frontera
shortest usada por el target ya está calificada por su propia implementación),
un corpus property mayor para binary64, selección de helpers por categoría y
extracción/versionado del motor float privado para targets adicionales.
