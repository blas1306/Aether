# NUMERIC-PARSING-V1 — implementation report

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-21. Autoridad normativa:
[NUMERIC_PARSING_ARCH_1](NUMERIC_PARSING_ARCH_1.md).

## Resultado

`std.Text` expone exactamente `IntParseResult`, `DoubleParseResult`, `parseInt`
y `parseDouble` con las firmas y variantes cerradas por la arquitectura. Las
declaraciones bootstrap son declaration-only; `TextOp::ParseInt` y
`TextOp::ParseDouble` son el puente privado. No se agregó syntax, `parse<T>`,
`Result<T,E>`, member de `string`, excepción, sentinel ni builtin Core.

HIR, MIR y SSA conservan el `ref string`, el `CallSiteId`, el resultado nominal
y el carácter Copy del enum. Los verificadores comparten `verify_text_op` y
rechazan operandos o resultados que no sean exactamente los tipos canónicos.
El lowering no crea owner, Drop ni successor excepcional.

## Runtime

`parseInt` recorre los bytes length-aware una vez. Acumula una magnitud unsigned
contra límites separados de `int64.max` y `abs(int64.min)`, deja de actualizarla
al detectar overflow y continúa validando hasta el final. Construye el patrón de
`int64.min` sin una negación signed overflowing. De este modo un suffix inválido
tiene precedencia sobre un overflow ya observado.

`parseDouble` separa scanner y conversión exacta. El scanner implementa sólo la
grammar ASCII normativa, cuenta punto/exponente con aritmética saturada y
preserva signo y condición de cero matemático. El conversor privado versionado
en `numeric_parse_runtime.c` usa enteros multiprecisión base 2^32 sobre cinco
buffers fijos de 192 limbs; el IR generado queda incorporado en
`numeric_parse_runtime.inc`. No usa libc numérica, locale, `errno`, `strlen`,
allocation ni operaciones floating-point.

El fragmento incorporado se genera con
`python3 scripts/generate_numeric_parse_runtime.py` y Clang 21.x para el target
explícito `x86_64-pc-linux-gnu`. `--check` vuelve a generarlo y falla si el
archivo versionado no coincide. El generador elimina sólo encabezados de
módulo, metadata de optimización y la declaración de `llvm.memcpy` que ya
pertenece al runtime común; no reescribe instrucciones ni atributos LLVM.

Esta fijación de dialecto corrige una regeneración accidental con LLVM 22. El
IR de LLVM 22 contenía `nocreateundeforpoison` y la ABI nueva, sin parámetro de
tamaño, de `llvm.lifetime.start/end`; Clang 21 rechaza respectivamente el
atributo y, después, el tipo de argumento del intrínseco. El fragmento canónico
usa la ABI de dos argumentos de LLVM 21 y no contiene el atributo exclusivo de
LLVM 22. No se modificó el C ni el algoritmo numérico. Clang 21.x es requisito
sólo para regenerar el artefacto; la aceptación del IR incorporado se verifica
con el Clang del toolchain nativo soportado.

Para exponentes decimales no negativos convierte `C * 5^q` y redondea sus bits;
para exponentes negativos divide exactamente `C * 2^k` por `5^-q`. Cociente,
resto y comparación con medio ulp deciden round-to-nearest, ties-to-even. Se
conservan hasta 780 dígitos significativos y sticky; ese bound excede los 752
dígitos necesarios para representar exactamente cualquier frontera halfway de
binary64. Exponentes fuera de la ventana relevante se clasifican después de
validar toda la syntax. Cero exacto se resuelve antes de rango y conserva signo.

Los helpers se emiten por reachability independiente: usar sólo `parseInt` no
incluye el motor multiprecisión de `parseDouble`, y usar otras APIs Text no
incluye ninguno de los dos parsers.

## Qualification

La suite `numeric_parsing_v1.rs` ejecuta source→native en O0 y O2. Cubre límites
y vecinos de int64, leading zeros, signos, `-0`, overflow largo seguido de byte
inválido, NUL y no-ASCII. Para double cubre todas las formas positivas de la
grammar, rechazos estructurales y especiales IEEE textuales, signed zero,
normal/subnormal mínimo y máximo, frontera max/infinity, frontera zero/minimum
subnormal y halfway ties-to-even alrededor de 1.0.

También comprueba round-trip de `str(double)` para ambos ceros, extremos,
subnormales y un corpus determinista de patrones binary64 finitos; ejercita un
significando de 4.000 dígitos con suffix inválido; verifica imports, arity,
operandos, identidad nominal y separación de reachability. La fixture
`examples/expense_tracker/numeric_parsing_v1_fixture.ae` demuestra el parsing
natural de dos campos enteros y un amount double sin portar aún la aplicación.

Durante qualification del motor se compararon además 50.000 decimales
deterministas y 10.000 significandos largos contra conversión binary64 de
referencia bit a bit. La implementación no consulta ni modifica el rounding
mode host, por lo que locale y modo ambiental no forman parte de su ejecución.

La validación final incluye `cargo test --workspace`, `cargo fmt --all --check`,
`cargo clippy --workspace --all-targets -- -D warnings`, `git diff --check`, el
differential completo y ejecución nativa O0/O2 de la fixture representativa.
La prueba unitaria del backend fija además la ABI de intrínsecos de LLVM 21, y
`numeric_parsing_v1` y `expense_tracker_alpt1_codec_v1` hacen que Clang compile
y ejecute el runtime incorporado a O0 y O2, incluidos ceros con signo, límites
normal/subnormal, overflow y empates IEEE 754 ties-to-even.

La reparación de compatibilidad se verificó el 2026-10-26 con Rust 1.99.1 y
Clang 21.1.8: `cargo check --workspace`, las suites focalizadas y
`cargo test --workspace` pasaron. La suite completa requiere la dependencia de
test ya declarada `numpy==2.4.2`; se ejecutó desde un entorno temporal. El gate
global `cargo clippy --workspace --all-targets -- -D warnings` aún no es verde
con Rust 1.99.1 por lints nuevos en código preexistente fuera de este cambio
(`assert_is_empty` y `needless_borrows_for_generic_args`). No se modificaron
esos sitios ajenos al runtime numérico.
