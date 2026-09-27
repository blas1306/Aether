# MATRIX-DYNAMIC-DESCRIPTOR-V1 — reporte

Estado: **IMPLEMENTADO**, 2026-09-27.

Autoridad normativa:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)

## Resultado

`Matrix<T>` owner usa ahora el descriptor de cinco palabras:

```text
{ ptr, rows, columns, rowCapacity, columnCapacity }
```

El layout de tipos, lowering LLVM, helpers de allocation/indexing/drop,
materialización de resultados algebraicos y elementwise, creación de views y
proyecciones de filas/columnas fueron migrados en conjunto. `Vector`,
`Array` y `List` no cambiaron.

Las construcciones existentes publican capacidad exacta. HIR, MIR y SSA
retienen además `row_capacity` y `column_capacity` en `MatrixInit`, lo que hace
verificables independientemente `rows <= rowCapacity`,
`columns <= columnCapacity` y el producto de capacidades. No se agregó sintaxis
source ni crecimiento.

## Layout, stride y views

- El layout owner pasó de 24 a 40 bytes en x86-64.
- El offset owner es `r0 * columnCapacity + c0`.
- El helper de índice valida primero los límites lógicos 1-based y sólo después
  calcula la dirección con `columnCapacity`.
- `MatrixView` conserva `{ptr,rows,columns,rowStride,columnStride}`.
- Una view directa de owner recibe `{ptr,rows,columns,columnCapacity,1}`.
- Transpuestas y axis views conservan y permutan strides; no reconstruyen el
  stride owner desde `columns`.
- Los stores de inicialización de matrices con padding también usan
  `columnCapacity`. Los resultados actuales siguen usando capacidad exacta.

## Allocation, overflow y shapes cero

El helper de allocation recibe shape y capacity por separado. Rechaza shapes
mayores que su capacidad, comprueba `rowCapacity * columnCapacity` con overflow
y delega la comprobación del byte size al allocator fijo comprobado.

Cuando el producto de capacidades es cero, el backing es null, pero rows y
columns se insertan siempre en el descriptor. Así se conservan separadamente
`0×0`, `m×0` y `0×n` a través de resultados algebraicos, queries, views,
transpuestas, moves, returns y fields. Un shape lógico vacío con reserva no
nula también se representa correctamente cuando su capacity product es
positivo; esto mantiene cerrado el invariante backing/capacity.

## Drop

El drop de Matrix ya no aplana `rows * columns`. Recorre en orden inverso sólo
el rectángulo lógico mediante dos loops y obtiene cada slot con
`row * columnCapacity + column`. Por lo tanto no lee ni destruye padding.

La liberación usa el tamaño de la reserva
`rowCapacity * columnCapacity` y sólo llama al allocator cuando `ptr != null`.
Los tres shapes con eje cero destruyen cero elementos. Se calificó además un
owner padded de `Buffer<int>` para comprobar elementos no-Copy/needs-drop y un
shape lógico `0×0` con reserva positiva para comprobar que el padding nunca se
droppea.

## Verificación y corrupción

Los verificadores HIR, MIR y SSA rechazan de forma independiente:

- `rows > row_capacity`;
- `columns > column_capacity`;
- overflow de `row_capacity * column_capacity`;
- las corrupciones previas de shape, row boundaries, tipo, traps e indexing;
- recipes de views/axis views que no corresponden al stride cerrado esperado.

El constructor runtime cerrado vuelve a validar shape/capacity y garantiza la
relación null/non-null del backing. Como source e IR no exponen raw pointers,
no existe una operación pública capaz de fabricar otra combinación.

## Cobertura

La cobertura añadida fuerza capacidades `3×5` sobre matrices lógicas `2×3` y
`2×2`, y comprueba:

- indexado 1-based;
- row/column views y transpose views;
- moves, returns y fields;
- drop de elementos owning sin tocar padding;
- backing reservado para un shape lógico vacío;
- `0×0`, `m×0` y `0×n`, queries y transpuestas;
- ejecución nativa con clang O0 y O2;
- corrupción de capacidades en HIR, MIR y SSA.

Las suites existentes continúan cubriendo matrices square/tall/wide,
operaciones elementwise, productos algebraicos, módulos y `linearAlgebra`. No
se cambió `Matrix.add`, slices, slice assignment, filled-init, overloads
contextuales ni la API de `linearAlgebra`; QR conserva su workaround actual.

## Validación

Se ejecutaron las validaciones exigidas por el milestone:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

