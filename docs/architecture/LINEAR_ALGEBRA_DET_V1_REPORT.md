# LINEAR-ALGEBRA-DET-V1 — reporte de implementación

Estado: **IMPLEMENTADO; API HISTÓRICA SUPERADA**, 2026-09-28.

Este reporte conserva el contrato y el oráculo del determinant concreto
original. La autoridad vigente para la API deduplicada y para el desbloqueo de
la migración es
[LINEAR-ALGEBRA-GENERIC-DET-V1](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md): `det`
ya no está bloqueado y expone dos overloads genéricos `T: IEEEFloat`.

Autoridad relacionada:

- [LINEAR-ALGEBRA-LU-ARCH-1](LINEAR_ALGEBRA_LU_ARCH_1.md);
- [LINEAR-ALGEBRA-LU-ARCH-1-REPORT](LINEAR_ALGEBRA_LU_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [SHAPE-GUARD-V1](SHAPE_GUARD_V1_REPORT.md);
- [LINEAR-ALGEBRA-SOLVE-V1](LINEAR_ALGEBRA_SOLVE_V1_REPORT.md).

## Resultado

El package ordinario `linearAlgebra` publica exactamente los cuatro overloads
cerrados:

```aether
float64 det(Matrix<float64> A);
float32 det(Matrix<float32> A);

float64 det(ref LU<float64> factor);
float32 det(ref LU<float32> factor);
```

No se agregó `determinant`, `detFloat32`, un overload genérico, entrada
`MatrixView` ni forma método. Los overloads owning validan primero que la
matriz sea square, consumen su backing, llaman una vez a `lu(A)` y delegan al
overload de factor de la misma precisión. No existe un segundo kernel para la
ruta de matriz ni una copia defensiva.

## Kernel, shapes y aritmética

Cada overload de `LU<T>` conserva el préstamo shared y ejecuta, antes del
primer acceso elemental, los cuatro guards del contrato:

```text
rows(L) = columns(L)
rows(U) = columns(U)
rows(L) = rows(U)
dimension(permutation) = rows(U)
```

Después inicializa el acumulador convirtiendo `permutationSign` directamente
a la precisión concreta y multiplica en orden `U[1,1] ... U[n,n]`. No recorre
la triangularidad, la diagonal de `L` ni la biyección de `permutation`, porque
son invariantes de una LU legítima. Tampoco materializa `P`, multiplica
matrices ni promueve el kernel `float32` a `float64`.

La identidad usada es:

```text
P A = L U
det(A) = permutationSign * product(diag(U))
```

La singularidad no es una ruta excepcional. Un pivot `+0.0` o `-0.0` entra al
producto IEEE ordinario y produce determinante cero; no hay tolerancia,
estimación de rank ni referencia a `SingularMatrixException`. NaN e infinito
conservan igualmente la aritmética ordinaria. Para orden cero, el acumulador
comienza en `+1` y el loop vacío devuelve `1` tanto desde `Matrix` como desde
`LU`.

## Ownership y costos

`det(Matrix<T>)` cuesta O(n³) por LU más O(n) por el producto y usa sólo las
allocations normales de la factorización. El owner de entrada se consume y su
backing puede ser reciclado por LU.

`det(ref LU<T>)` cuesta O(n), no asigna memoria y no mueve ni copia `L`, `U` o
`permutation`. El consumer reutiliza el mismo factor en la secuencia
`det(factor)`, `solve(factor,b)`, `det(factor)` y comprueba el mismo resultado,
la solución esperada y la permutación intacta. La instrumentación nativa fija
tres allocations/frees totales para construir y destruir una LU no vacía y
cero para una LU `0×0`; llamar a `det` no agrega ninguna.

## Calificación numérica y de diagnósticos

El consumer real cubre en `float64` y `float32`:

- `0×0` desde matriz y factor, `1×1`, identidad y diagonal;
- triangulares superior e inferior y pivots negativos;
- un swap y múltiples swaps;
- determinantes positivo y negativo, y un caso pequeño conocido de valor 100;
- singular, fila cero y matriz cero;
- `-0.0`, incluido el signo observado mediante su recíproco IEEE;
- paridad explícita cuando `product(diag(U))` tiene signo opuesto al
  determinante final;
- reutilización del factor entre determinant y solve.

La prueba Rust `aether-driver/tests/linear_algebra_det_v1.rs` fija además
`ShapeMismatch` para matriz y factores rectangulares o inconsistentes antes de
los accesos, `E0460` para tipos, views y precisión de resultado no admitidos,
consumo del owner de matriz y préstamo reutilizable del factor.

## Calificación estructural

La misma prueba comprueba que existen exactamente cuatro overloads `det`, que
los dos overloads de matriz aportan una única llamada adicional a `lu(A)` por
precisión y que no aparecen aliases ni `aether_det`. HIR, MIR y SSA conservan
`ShapeGuard`, consultas ordinarias de rows/columns y el loop escalar; LLVM usa
los accesos generales de Matrix para `float64`/`float32`. No se agregó helper,
intrinsic, multiplicación matricial ni comportamiento especial del
compiler/runtime.

El diff productivo se limita al package ordinario. Constructors, QR, LU y
solve permanecen en el mismo consumer, y la prueba de registry existente
publica y ejecuta ese consumer ampliado sin infraestructura nueva.

## Validación

Se ejecutó correctamente con el binario `aether` construido por el workspace:

```text
aether check linearAlgebra
aether check linearAlgebra/tests/consumer
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_det_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

La instalación global encontrada en el `PATH` era anterior a SHAPE-GUARD-V1 y
rechazaba `shapeGuard` con `E0212`; por eso las cuatro invocaciones `aether`
anteriores se calificaron con `compiler-next/target/debug/aether`, construido
desde este mismo checkout.

## Fuera de scope

No se implementaron inverse, `logDet`, determinant de `MatrixView`,
determinant genérico, Cholesky, SVD, eigenvalues, rank, condition number,
`Complex<T>` ni integración BLAS/LAPACK.
