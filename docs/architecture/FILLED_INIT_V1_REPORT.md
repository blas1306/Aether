# FILLED-INIT-V1 — reporte

Estado: **IMPLEMENTADO**, 2026-09-27.

Autoridad normativa:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)
- [MATRIX_DYNAMIC_DESCRIPTOR_V1_REPORT](MATRIX_DYNAMIC_DESCRIPTOR_V1_REPORT.md)

## Superficie source

Se eligió la superficie intrínseca mínima:

```aether
Vector<T,Row> r = vectorFilled<T,Row>(length, initializedValue);
Vector<T,Column> c = vectorFilled<T,Column>(length, initializedValue);
Matrix<T> a = matrixFilled<T>(rows, columns, initializedValue);
```

Los nombres son intrínsecos globales de bajo nivel, como las queries de shape,
y por eso tienen la misma disponibilidad en todo package. No consultan nombre,
metadata ni status OAL del package. Los argumentos de tipo y orientación son
explícitos: no fue necesario adelantar overload resolution contextual.

Ambas operaciones exigen `T: Storable + Copy` y el valor inicializado es
obligatorio. No se agregó constructor sin valor, `fill`, raw pointer, capacity,
memoria uninitialized ni `assume_init`. Tampoco se modificó `linearAlgebra`.

## Representación IR y verificación

HIR, MIR y SSA poseen operaciones distintas `VectorFilled` y `MatrixFilled`;
no se expanden a stores ordinarios visibles en esos IR.

- `VectorFilled` retiene `element_type`, orientación, length, valor, y en
  MIR/SSA los traps cerrados de tamaño y fallo de allocation.
- `MatrixFilled` retiene `element_type`, rows, columns, row capacity, column
  capacity, valor y traps. El frontend fija las capacidades a los extents; MIR
  y SSA las conservan como operandos separados y exigen independientemente
  `rows == row_capacity` y `columns == column_capacity`.
- La clase de operación define el contrato verificable de exactamente `length`
  stores o `rows*columns` stores lógicos antes de producir su resultado. No
  existe valor IR para una transacción incompleta ni una instrucción para
  publicar su descriptor antes del commit.
- Los tres verificadores comprueban tipo owner/elemento, orientación, operands
  `usize`, valor T, admisión Storable, Copy, capacidades exactas y traps.

Las pruebas de corrupción alteran HIR, MIR y SSA y confirman rechazo fail-closed.

## Lowering, allocation e inicialización

Vector no vacío usa una llamada a `aether_vector_fill_T`, que delega en una
única allocation comprobada, escribe todo el rango y recién retorna el owner.
Length cero retorna directamente `{null,0}` sin cruzar el allocator.

Matrix usa `aether_matrix_fill_T`. Primero `aether_matrix_new_T` valida:

- `rows <= row_capacity` y `columns <= column_capacity`;
- producto lógico `rows*columns`;
- producto de capacidades;
- producto por tamaño de elemento en el allocator fijo.

Con capacidades exactas realiza una única allocation cuando ambos ejes son no
cero. Para `0×0`, `m×0` y `0×n`, el producto es cero, el pointer queda null y
las cinco palabras conservan toda la metadata. La inicialización itera el
rectángulo lógico y calcula cada slot como
`row * columnCapacity + column`; por tanto el stride no se reconstruye desde
columns.

Allocation y stores son operaciones no-unwind del runtime cerrado. Los únicos
fallos internos posibles en este milestone son los traps comprobados de shape,
producto, byte size o allocation, todos anteriores al primer store. Como Copy
no requiere drop y un store no falla, no existe salida fallida después de
iniciar el prefijo; en consecuencia no hay prefijo que limpiar. Si una futura
inicialización introduce una operación fallable después del primer store,
deberá agregar una transacción con contador de prefijo y cleanup antes de poder
reutilizar estas operaciones.

## Cobertura

La calificación cubre:

- Vector Row, Column y vacío;
- Matrix square, tall, wide, `0×0`, `m×0` y `0×n`;
- int, float32, float64 y un struct Copy no escalar;
- repetición del valor, indexing y MatrixView;
- moves, returns y fields;
- ejecución nativa O0 y O2;
- overflow constante rechazado y overflow runtime que trapea;
- corrupción HIR, MIR y SSA;
- rechazo de `Buffer<int>` como T no-Copy;
- uso genérico desde un package ordinario importado.

Quedaron fuera deliberadamente `Matrix.add`, slices, slice assignment,
overloads contextuales, `linearAlgebra.zeros/ones/identity` y el workaround QR.

## Validación

Se ejecutan para el cierre:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

