# SLICE-ASSIGNMENT-V1 — reporte

Estado: **IMPLEMENTADO**, 2026-09-27.

Autoridad normativa:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)
- [SLICE_SELECTORS_V1_REPORT](SLICE_SELECTORS_V1_REPORT.md)
- [SLICE_READ_V1_REPORT](SLICE_READ_V1_REPORT.md)

## Resultado

Compiler-next implementa reemplazo de contenido mediante slice-place directo sin
cambiar length, capacity, rows, columns u orientación:

- `Array<T>[a:b]` / `[:]` desde un `Array<T>` de longitud exacta;
- `List<T>[a:b]` / `[:]` desde un `List<T>` de longitud exacta, conservando la
  estructura del receptor;
- `Vector<T,O>` y `VectorViewMut<T,O>` desde Vector/VectorView de igual `T`, `O`
  y dimensión;
- filas y columnas Matrix desde Vector/VectorView con orientación exacta;
- submatrices y Matrix completas desde Matrix/MatrixView con shape exacta.

El receptor puede ser un owner escribible o un view mutable explícito. Un
`VectorView`/`MatrixView` compartido, storage const o una procedencia con borrow
incompatible se rechaza. La sintaxis directa no construye un
`VectorViewMut`/`MatrixViewMut` escapable.

Todos los elementos exigen `T: Copy`. No existe fallback a Clone, movimiento de
subowners no-Copy, broadcasting, padding, truncation, conversión Row/Column ni
resize por slice.

## Evaluación, validación y atomicidad

HIR resuelve primero el Place receptor y congela cada selector en orden source.
MIR evalúa después el RHS una sola vez. Antes del primer store el backend:

1. valida orden y bounds de todos los selectors;
2. valida selectores escalares Matrix con `IndexOutOfBounds`;
3. valida length o rows/columns exactos con `ShapeMismatch`;
4. captura todos los elementos RHS en orden lógico;
5. escribe el snapshot sobre los offsets físicos del LHS.

Por tanto un mismatch no puede producir mutación parcial. `Full` no sintetiza
endpoints y admite extents cero. `0×0`, `m×0`, `0×n` y vectores/colecciones
vacíos preservan su shape y realizan cero stores.

La orientación se comprueba estáticamente y permanece además en el contrato IR
junto con `OrientationMismatch`; no hay conversión contextual o dinámica entre
Row y Column.

## Overlap y strides

La implementación V1 usa siempre un temporal independiente de `k` elementos.
Esto implementa literalmente `RHS snapshot before first LHS write`, sin intentar
inferir no-overlap mediante igualdad de punteros. Funciona para:

- desplazamientos forward y backward;
- filas/columnas y bloques solapados;
- owners Matrix con padding;
- VectorView/MatrixView strided;
- transpose views y subviews.

El recorrido de lectura y escritura calcula offsets físicos usando los strides
del descriptor correspondiente, pero el snapshot usa orden lógico row-major.

## HIR, MIR y SSA

HIR incorpora `HirStmtKind::SliceAssign` y MIR/SSA incorporan la operación
explícita `SliceAssign`. Las tres capas conservan y verifican:

- Place base y capacidad mutable;
- familia exacta del container;
- selector, axis, semántica e index base;
- clase de resultado slice-place;
- tipo RHS y tipo elemental;
- contrato exacto de length/axis/shape;
- política `RhsBeforeWrite`;
- traps `SliceOrderError`, `SliceBoundsError`, `IndexOutOfBounds`,
  `ShapeMismatch` y `OrientationMismatch`.

Los verificadores recalculan estos contratos desde los TypeId y fallan cerrados
ante corrupción de familia, eje, base, resultado, orientación, shape, snapshot
adyacente o trap set.

## Cobertura

La suite `slice_assignment_v1` ejecuta O0 y O2 y cubre:

- Array/List closed/full, owner exacto, estructura preservada y `T: Copy`;
- Vector Row/Column, full/closed, overlap y views strided;
- filas, columnas, submatrices y Matrix completa;
- owners padded, transpose view, overlap vertical/horizontal y snapshot;
- shapes `0×0`, `m×0`, `0×n` y vectores vacíos;
- mismatch previo a stores, orientación, const/shared rejection;
- evaluación única y orden observable de endpoints/RHS;
- corrupción HIR, MIR y SSA.

## Fuera de alcance preservado

No se agregaron overloads contextuales, `zeros`/`ones`/`identity`, migración
legacy, broadcasting, resize por slice ni materialización implícita de views
matemáticos.

## Validación

Se ejecutaron satisfactoriamente:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

El diferencial verificó 21 casos con 0 fallos.
