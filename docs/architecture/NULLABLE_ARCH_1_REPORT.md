# NULLABLE-ARCH-1 — design report

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-21.

Documento normativo: [NULLABLE_ARCH_1.md](NULLABLE_ARCH_1.md).

Sólo se agregaron documentos. No se modificó lexer, parser, AST, HIR, MIR, SSA,
backend, runtime, tests ni la superficie source admitida.

## Resultado

Se cerró `T?` como constructor de tipo canónico y no como metadata de un
binding. `TypeData::Nullable(T)` distingue T de T? en equality, generics,
signatures, fields, containers, substitution, mangling, layout y ABI. `void?` y
nullable nested se rechazan.

`null` queda como literal contextual sin tipo source autónomo. Sólo se convierte
en HIR cuando existe un expected `T?` concreto; no aporta evidencia para inferir
un generic. `var x = null` y `f<T>(T?)(null)` sin otra evidencia fallan. El caso
cerrado `null == null`/`!=` baja a bool constante sin inventar un Null TypeId.

La única coerción nueva es T→T?, explícita en HIR. Copia T si es Copy o
transfiere ownership si es owning; no clona, retiene, boxea ni puede fallar. No
existe T?→T implícito ni trap de unwrap.

## Sintaxis y references

`?` es postfix. Como `ref` consume un `type` completo, `ref T?` significa
`ref (T?)`. Se agrega grouping de tipos para expresar `(ref T)?`; la misma regla
aplica a `ref mut`. Esto separa inequívocamente una referencia non-null a storage
nullable de una referencia nullable.

Un `(ref T)?` local puede refinarse y luego dereferenciarse como `ref T`.
`ref T? slot` es en sí non-null; comparar `*slot` inspecciona el pointee, pero no
genera un fact persistente en V1 porque dereference es una projection susceptible
de aliasing. La alternativa es snapshotear una vez en un local.

## Refinement y ownership

El tipo declarado del binding nunca cambia. El checker mantiene facts
`Unknown/Null/NonNull` por local o parámetro root y por path. `x != null` refina
el then y `x == null` refina el else. `&&`, `||` y `!` tienen short-circuit real
y propagan respectivamente el entorno true, false o intercambiado.

Assignments recalculan el fact; mutable borrows, Stores por alias y calls que
puedan escribir invalidan. Un join conserva un fact sólo cuando todos los
predecesores alcanzables coinciden. Fields, indexes, calls y dereferences no se
refinan. El análisis de loops usa un punto fijo conservador que incluye cero
iteraciones.

Un uso refinado baja a `NullablePayload` con proof, root y versión verificables.
Para T Copy puede copiar el payload. Para T owning sólo permite borrow/observación:
no se puede consumir, retornar por ownership ni mover el payload mediante el
simple refinement. El T? completo sí se mueve normalmente. Esta frontera evita
containers parcialmente movidos y deja una futura operación `take` como diseño
independiente.

Null posee cero owners; present posee exactamente el owner T. Drop consulta
presencia y ejecuta Drop(T) cero o una vez. Move transfiere el nullable completo;
los drop flags siguen perteneciendo al container y no reemplazan su discriminante
interior.

## Layout y ABI

Se centralizó la decisión conceptual en `NullableLayout::Niche | Tagged`.
NULLABLE-V1 aprueba pointer-zero niche únicamente para contratos ya auditados
como non-null: string, class handles, Function y references. Conservan size y
alignment de T. Interfaces, collections/descriptors, structs, enums, números y
todo tipo no aprobado usan tag, aunque una versión futura pueda demostrar más
niches.

Tagged usa tag byte lógico 0/1 y offsets calculados por el layout engine; bytes
de payload ausente nunca se leen ni dropean. No hay boxing. El ABI clasifica el
layout real y el mangling nullable exacto
`N<decimal-byte-length>x<payload-mangle>` distingue siempre T de T?, incluso
cuando niche hace idéntica la representación física.

## IR y verificación

HIR preservará Null, Inject, IsNull, Payload y short-circuit explícitos. MIR y
SSA mantendrán operaciones nullable semánticas hasta el lowering físico. Cada
payload access exige una proof non-null dominante para el mismo root/ValueId y
versión, sin Store/Move/call invalidante intermedio. Los optimizadores deben
reverificar esas propiedades.

El backend es el único nivel que traduce la operación semántica a pointer-zero
o tag. Los corruption tests cubren tipos discordantes, proofs ausentes o stale,
payload Move owning, phis inválidos, Drop en null, layouts adulterados y
colisiones de mangling.

## Scope y próximo vertical

NULLABLE-V1 incluye locals, parámetros, returns, defaults caller-side, const,
generics, null tests, refinement then/else, invalidación/joins, short-circuit,
references, Function, classes, string, collections/aggregates, lifecycle,
layout/ABI, O0/O2 y verificación de todas las IR.

Quedan fuera safe navigation, coalescing, unwrap, patterns, nested/deep
nullability, igualdad nullable general, ordering, refinamiento de projections,
inferencia desde null solo, boxing y FFI annotations.

## Validación del milestone

- Se crearon únicamente el documento normativo y este reporte.
- Se preservaron todos los cambios preexistentes del working tree.
- Se cerraron sintaxis/precedencia, literal null, TypeId, conversión, equality,
  refinement e invalidación, short-circuit, ownership/Drop/Move, references,
  composición, generics/defaults/const, layout/niches, ABI, IR y diagnósticos.
- No queda una decisión abierta dentro del alcance V1.
- No se declara implementada ninguna conducta source nueva.
