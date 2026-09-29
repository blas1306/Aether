# PRINT-VALUE-V1 — implementation report

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-29.

La autoridad normativa permanece en
[PRINT_VALUE_ARCH_1.md](PRINT_VALUE_ARCH_1.md). Este vertical implementa
`print(value)` y `println(value)` en `compiler-next` sin cambiar la ABI de
output ni agregar overloads públicos.

## Resultado

`print` y `println` aceptan exactamente un argumento admitido por FORMAT:
`string`, escalares canónicos y owners `Vector<T,Row>`, `Vector<T,Column>` y
`Matrix<T>` admitidos por MATH-FORMAT. La representación directa es
byte-exactamente la de un único hole `${value}`. Views y tipos fuera del perfil
continúan fallando con E0340; aridad cero/múltiple y type arguments siguen
rechazados.

La ruta string existente permanece especializada. Literals y lvalues se pasan
al Core output sin una publicación FORMAT nueva; temporales, incluidos fields
proyectados de un root temporal, conservan el backing vivo durante el write.
No se agregan quotes, escaping ni reinterpretación de los bytes.

## Autoridad FORMAT e IR

`format_admission(types, formatted_type)` es ahora la única consulta cerrada
que produce `StringBorrow`, `CanonicalScalarFormat` o
`MathematicalAggregateFormat(recipe)`. Tanto los holes source como direct-value
output usan esa función, y `verify_string_op` reconstruye la misma admisión.

HIR conserva `OutputArgumentKind::ExistingString | DirectFormat { format_site
}`. Un `DirectFormat` debe ser un `StringOp::Interpolate` fresh, checked-exact,
con un único hole y sin texto; el verifier reconstruye su site, acceso, tipo y
conversión. No se agregaron opcodes de formatting ni output por tipo.

MIR baja el plan a las operaciones existentes: estabilización, borrow FORMAT,
`Interpolate`, `FormatEndBorrow`, Core `Print`/`Println` y Drops. Para un rvalue
owner, el borrow termina después de publicar el string pero el root permanece
en la pila de cleanup hasta completar stdout. En éxito y unwind se destruye
primero el string publicado y después el root. MIR y SSA permiten la lectura
observacional acotada de un field string proyectado y continúan rechazando el
escape de una referencia FORMAT.

Backend, runtime y frontera IO no cambiaron: Core output sigue recibiendo un
`string`, `println` agrega un único LF y los fallos conservan
`std.IO.IOException`. No hay boxing, witness, reflection, TypeId dispatch,
fallback runtime, Clone, Alias, retain ni COW para el source formateado.

## Qualification

`crates/aether-driver/tests/print_value_v1.rs` cubre O0/O2 para escalares,
`string`, interpolación existente, Row/Column/Matrix, fields, shared/ref-mut,
temporales directos y proyectados, reutilización posterior del owner, aridad,
E0340 y reachability de FORMAT. Comprueba además la metadata HIR
`ExistingString`/`DirectFormat` y la presencia de `FormatEndBorrow` en MIR/SSA.

La regresión de FORMAT/MATH-FORMAT permanece verde y valida spellings, floats,
U+0000, zero-shapes, borrow regions y corrupciones de planes. La calificación
de cierre ejecutó la suite workspace, formatting, clippy estricto y
`git diff --check`.
