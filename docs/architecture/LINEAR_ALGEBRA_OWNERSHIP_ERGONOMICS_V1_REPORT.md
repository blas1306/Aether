# LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-29.

Autoridad normativa:

- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1-REPORT](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1_REPORT.md);
- los reportes V1 genéricos de LU, QR, Cholesky, determinant y solve.

## Resultado y API final

Los nombres cotidianos reciben `ref Matrix<T>` y preservan por completo la
entrada. Los nombres `InPlace` reciben `Matrix<T>` owning, consumen el binding y
mantienen la reutilización histórica del backing.

```aether
LU<T> lu<T: IEEEFloat>(ref Matrix<T> A);
LU<T> luInPlace<T: IEEEFloat>(Matrix<T> A);
QR<T> qr<T: IEEEFloat>(ref Matrix<T> A);
QR<T> qrInPlace<T: IEEEFloat>(Matrix<T> A);
Cholesky<T> cholesky<T: IEEEFloat>(ref Matrix<T> A);
Cholesky<T> choleskyInPlace<T: IEEEFloat>(Matrix<T> A);
T det<T: IEEEFloat>(ref Matrix<T> A);
T detInPlace<T: IEEEFloat>(Matrix<T> A);
Vector<T,Column> solve<T: IEEEFloat>(ref Matrix<T> A, ref Vector<T,Column> b);
Vector<T,Column> solveInPlace<T: IEEEFloat>(Matrix<T> A, ref Vector<T,Column> b);
Matrix<T> solve<T: IEEEFloat>(ref Matrix<T> A, ref Matrix<T> B);
Matrix<T> solveInPlace<T: IEEEFloat>(Matrix<T> A, ref Matrix<T> B);
```

`det(ref LU<T>)` y los dos `solve(ref LU<T>, ref RHS)` no cambiaron. Tampoco se
conservó ningún overload legacy owning con el nombre base. `qrFloat32` sigue
siendo consuming y delega directamente a `qrInPlace`.

## Kernels y copia preserving

Los cuerpos numéricos anteriores se renombraron literalmente a `luInPlace`,
`qrInPlace` y `choleskyInPlace`. No se cambiaron loops, pivoting, Householder,
validación, orden IEEE, excepciones, shapes ni allocations de esos kernels. Hay
una sola implementación numérica por algoritmo.

El helper interno `copyMatrixForFactorization` obtiene los dos extents, crea una
Matrix exact-capacity mediante `matrixFilled(..., 0)` y copia por filas sólo el
rectángulo lógico usando indexación Matrix ordinaria. No usa `memcpy`, intrinsic
ni opcode nuevo. La indexación fuente respeta `columnCapacity`; la copia no lee
padding. Un extent cero conserva ambos extents y produce backing null.

Cada wrapper preserving hace exactamente una copia y mueve ese workspace al
kernel `InPlace`. Por ello la fuente conserva owner, descriptor, capacities,
stride, valores, backing y padding, mientras el factor recibe almacenamiento
independiente.

## `det`, `solve` y orden de errores

Las rutas Matrix de `det` y `solve` mantienen sus guards externos, en el mismo
orden y antes de la copia. Después realizan exactamente una `lu(A)` y delegan
al overload desde factor. Sus variantes `InPlace` conservan los mismos guards,
llaman exactamente una vez a `luInPlace(A)` y delegan igualmente.

Cholesky preserving no pre-valida: copia primero y llama a
`choleskyInPlace`. Dentro del único kernel permanece la precedencia
shape → no finito → asimetría → pivot no positivo. Si hay exception, unwind
limpia el workspace y deja viva la fuente; la ruta `InPlace` limpia una sola vez
el owner consumido.

## Ownership, backing y costos

La qualification positiva usa repetidamente la misma Matrix con `lu`, `qr`,
`cholesky`, `det` y `solve`, incluida sintaxis implícita y `&A` explícita. La
qualification negativa fija use-after-move para cada variante `InPlace`.

La reutilización de backing permanece:

- LU: `U` para `m <= n`, `L` para `m > n`;
- QR: `R`;
- Cholesky: `L`.

En O0 y O2, cada factorización preserving no vacía agrega exactamente un
backing sobre el presupuesto histórico; las variantes `InPlace` mantienen el
presupuesto previo. Cholesky preserving asigna una Matrix y Cholesky InPlace no
hace allocations numéricas internas. Para `m*n == 0` la copia no asigna.

El costo adicional preserving es `O(m*n)` de tiempo, `m*n` elementos y una
allocation cuando el rectángulo es no vacío. No hay alias, clon adicional ni
workspace residual.

## Layout padded e IR

La prueba dedicada altera una Matrix literal en SSA para obtener
`columnCapacity > columns`. Verifica el stride dinámico de las lecturas, valores
lógicos intactos, destino exact-capacity y exactamente una allocation de copia.
También cubre una fuente vacía con reserva positiva: la copia conserva `0×0` y
no transfiere ni crea backing. Casos `m×0` y `0×n` califican ambos extents en las
factorizaciones.

HIR contiene `CallScopedSharedBorrow` para las entradas preserving. MIR y SSA
contienen el `EndBorrow` correspondiente, mientras el workspace nuevo se mueve
al entry point owning. Las rutas `InPlace` conservan el Move y los verificadores
existentes siguen siendo autoridad contra borrow escape, owner duplicado,
missing `EndBorrow` y double-drop. No se añadió opcode, intrinsic, allowlist ni
tratamiento especial de `linearAlgebra`.

La inferencia genérica de calls shared fue completada para unificar una forma
`ref P<T>` con el tipo exacto `P<U>` del owner antes de materializar el borrow.
Esto permite las calls normales requeridas (`lu(A)`, `det(A)`, `solve(A,b)`) y
mantiene cerradas conversiones, borrows mutables y selección por ownership.

## Consumer y compatibilidad

El consumer real muestra LU y QR preserving sobre la misma `A`, imprime `A` y
ambos factores mediante PRINT-VALUE-V1, y muestra `luInPlace` sobre una Matrix
separada. Los forwarders preserving reciben `ref Matrix<T>`.

Las pruebas históricas que medían consumo, backing reuse o allocations del
kernel migraron a `*InPlace`. Sus oráculos numéricos, tolerancias, excepciones y
lowering concreto de `float32`/`float64` permanecen sin cambios. Se agregó la
suite `linear_algebra_ownership_ergonomics_v1.rs` para la nueva frontera.

## Validación

La matriz de cierre comprende:

```text
aether check linearAlgebra
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

No se agregó copy/clone público, copy assignment, COW, ARC/GC Matrix,
last-use optimization, solve/det desde Cholesky, BLAS/LAPACK ni cambio
numérico.
