# SLICE-READ-V1 — reporte

Estado: **IMPLEMENTADO**, 2026-09-27.

Autoridad normativa:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)
- [SLICE_SELECTORS_V1_REPORT](SLICE_SELECTORS_V1_REPORT.md)

## Resultado

Compiler-next ejecuta ahora lectura real de los selectors `Closed` y `Full`
introducidos por `SLICE-SELECTORS-V1`. La ruta rvalue deja de emitir `E0456`
para las familias soportadas. La ruta Place de asignación conserva `E0456`, por
lo que este vertical no habilita slice assignment.

- `Array<T>[a:b]` y `Array<T>[:]` producen un `Array<T>` owner independiente.
- `List<T>[a:b]` y `List<T>[:]` producen un `List<T>` owner independiente con
  `length == capacity`.
- Ambas copias owning exigen `T:Copy`, son `O(k)`, usan a lo sumo una allocation
  no vacía y producen el descriptor vacío canónico sin allocation para `[:]`
  sobre extent cero.
- `Vector`, `VectorView` y `VectorViewMut` producen siempre un
  `VectorView<T,O>` compartido, conservando orientación y stride en `O(1)` sin
  allocation.
- Matrix y MatrixView implementan scalar/slice, slice/scalar y slice/slice sin
  rank collapse. Los resultados conservan row/column strides, incluso desde
  owners padded, transposes y subviews encadenadas.
- `Full` llega como selector real al backend. No se sintetizan extremos; por
  eso funcionan `v[:]` vacío, `A[:,:]` con `0×0`, `m×0` y `0×n`, además de las
  proyecciones de fila/columna cuyo eje resultante es vacío.

## Orden, bounds y evaluación

El container se resuelve una vez y los operands de cada selector se congelan
una vez en orden source. Un `Closed` valida primero `first <= last`, después el
dominio 0-based o 1-based, y sólo entonces calcula `last-first+1` y convierte a
offset físico. Los traps nuevos son `SliceOrderError` y `SliceBoundsError`; un
selector escalar de Matrix dentro de una lectura mixta conserva
`IndexOutOfBounds`.

La implementación evita underflow 1-based porque ninguna resta de uno se emite
antes del lower-bound check. `Full` usa directamente offset cero y el extent
del descriptor.

## HIR, MIR y SSA

HIR incorpora `SliceRead`, que retiene el `HirSubscript` tipado completo y el
tipo elemental. MIR y SSA exponen operaciones separadas:

- `CollectionSliceCopy`;
- `VectorSliceView`;
- `MatrixSliceView` (axis view o subview según selectors/result metadata).

Los verificadores recalculan y exigen familia exacta, base, semántica, eje,
orientación, clase de resultado, tipos de endpoints, receta de stride y traps.
Las pruebas de corrupción cubren metadata HIR y contratos MIR/SSA; los IR
corruptos fallan cerrados.

## Ownership y provenance

Las copias de Array/List no crean un borrow persistente y el source queda
usable. Los slices matemáticos participan en el mismo tracking de provenance y
no-escape que los views existentes. Un view de slice bloquea move, reemplazo o
mutación estructural del owner durante su vida. Leer desde `VectorViewMut` o
`MatrixViewMut` degrada deliberadamente a view compartido; no se crea un view
mutable escapable implícito.

## Cobertura

La suite `slice_read_v1` cubre O0/O2, owners independientes, `T:Copy`, capacidad
exacta de List, slices closed/full, orientación Row/Column, views sobre views,
strides mayores que uno, owners Matrix padded, transpose/subviews, slices de
longitud uno sin colapso, los tres zero-shapes, traps dinámicos, evaluación una
vez, provenance/no-escape, frontera de assignment y corrupción MIR/SSA. La
suite frontend agrega corrupción HIR y `slice_selectors_v1` fue actualizada al
vertical ejecutable.

## Fuera de alcance preservado

No se implementaron slice assignment, snapshot de overlap, resize por slice,
broadcasting, overloads contextuales, `zeros`/`ones`, migración legacy ni
materialización implícita de slices matemáticos a owners.

## Validación

Se ejecutaron:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```
