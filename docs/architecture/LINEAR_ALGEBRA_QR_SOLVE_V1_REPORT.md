# LINEAR-ALGEBRA-QR-SOLVE-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-30.

Autoridad normativa:

- [LINEAR-ALGEBRA-QR-SOLVE-ARCH-1](LINEAR_ALGEBRA_QR_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-QR-SOLVE-ARCH-1-REPORT](LINEAR_ALGEBRA_QR_SOLVE_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-SOLVE-V1](LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_V1_REPORT.md).

## Resultado y API

`linearAlgebra` incorpora exactamente los dos overloads genéricos previstos:

```aether
Vector<T,Column> solve<T: IEEEFloat>(
    ref QR<T> factor,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref QR<T> factor,
    ref Matrix<T> B);
```

También se agregó la excepción pública `RankDeficientMatrixException`. No se
agregaron `leastSquares`, variantes `InPlace`, wrappers por precisión ni un
selector de método. Los overloads existentes de Matrix, LU y Cholesky no
cambiaron.

## Guards, rango y dominio

Ambas rutas ejecutan literalmente los cuatro guards normativos: cuadratura de
`Q`, igualdad de filas de `R` y `Q`, dominio tall/square de `R` y compatibilidad
del RHS. Todos preceden extents locales, acceso elemental, aritmética, scan y
allocation.

Después de los guards se recorre la diagonal efectiva de `R` en orden
creciente. La comparación exacta con cero lanza
`RankDeficientMatrixException`; por ello `+0` y `-0` fallan, mientras NaN,
infinitos y subnormales no cero continúan por la aritmética IEEE. El scan se
ejecuta completo antes del workspace y también para Matrix RHS con `q==0`.

El dominio implementado es `m>=n`: square resuelve `A x=b` y tall devuelve la
solución unique least-squares para un factor legítimo full-column-rank. Wide
falla por el tercer `shapeGuard`. No se implementaron variables libres ni
minimum-norm.

## Algoritmo, orden numérico y ownership

Vector crea un único `w:n`, calcula sólo las primeras `n` componentes de
`Q^T b` en orden `i/k`, y lo sobrescribe mediante backward substitution en
orden `i` descendente y `j` creciente. Matrix crea un único `W:n×q`, usa
exactamente los órdenes `i/c/k` e `i/c/j`, y no delega por columnas.

Cada acumulación inicializa `value` con cero y materializa `product` antes de
`Add` o `Sub`; cada celda de la sustitución realiza una sola `Div` final. No se
materializa transpose, residual, copia del factor/RHS, segundo workspace,
ecuaciones normales ni reducción alternativa.

Factor y RHS permanecen shared y reutilizables. El resultado es owning e
independiente. Vector crea un backing exactamente cuando `n>0`; Matrix cuando
`n*q>0`. Los casos `m×0`, `0×0`, `0×q` y `n×0` conservan sus extents sin
backing de resultado.

## Aggregate manual y lowering

La implementación no certifica ortogonalidad de `Q`, triangularidad o
procedencia de `R`, reconstrucción ni finitud. Tras shapes y scan usa `Q` y el
upper efectivo de `R` literalmente; ignora lower y las filas de `R` posteriores
a `n`. No existe `InvalidQRFactorException`.

El feature vive íntegramente en `linearAlgebra/src/lib.ae`. HIR contiene
borrows, guards, capabilities `Zero`, `Equal`, `Add`, `Mul`, `Sub` y `Div`,
loops e indexación ordinaria. MIR/SSA quedan concretos para float32/float64, sin
genericidad, transpose, witness, vtable, `TypeId`, opcode o helper runtime
especializado.

## Qualification

La suite `linear_algebra_qr_solve_v1` cubre el contrato source literal,
lowering, ambas precisiones, square y tall least-squares, Vector y Matrix,
reutilización e inputs intactos, exact-zero con `-0`, diagonal NaN, RHS Matrix
vacío, shapes cero y conteos exactos de backing en O0/O2. El consumer del
package ejercita además square, tall, ambos RHS, ambas precisiones, reutilización
y la excepción nominal.

Validación ejecutada:

```text
compiler-next/target/debug/aether check linearAlgebra
compiler-next/target/debug/aether run linearAlgebra/tests/consumer -O0
compiler-next/target/debug/aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_qr_solve_v1
cargo test -p aether-driver --test linear_algebra_solve_v1
cargo test -p aether-driver --test linear_algebra_solve_matrix_v1
cargo test -p aether-driver --test linear_algebra_cholesky_solve_v1
cargo test -p aether-driver --test linear_algebra_qr_v1
cargo test -p aether-driver --test numeric_generic_migration_closure_1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

## Fuera de scope

No se agregó QR pivoted/rank-revealing, tolerancia o `rcond`, pseudoinverse,
minimum-norm para wide, residual-returning API, Complex, views RHS,
Householder implícito ni BLAS/LAPACK.
