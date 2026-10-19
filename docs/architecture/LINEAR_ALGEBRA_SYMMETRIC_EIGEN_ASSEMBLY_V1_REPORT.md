# LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ASSEMBLY-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO; CLOSED**, 2026-10-19.

Autoridad normativa:

- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1-REPORT](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_V1_REPORT.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_QR_V1_REPORT.md);
- [MATRIX-REPRESENTATION-V1](MATRIX_REPRESENTATION_V1_REPORT.md).

## API y contrato

`linearAlgebra/src/lib.ae` agrega exactamente la frontera preserving:

```aether
public struct SymmetricEigen<T: Storable> {
    Vector<T,Column> values;
    Matrix<T> vectors;
}

public SymmetricEigen<T> symmetricEigen<T: IEEEFloat>(
    ref Matrix<T> A);
```

No se agregaron aliases, options, tolerance, ruta values-only ni variante
in-place. Para una entrada real simétrica `n×n`, `values` tiene dimensión
`n`, `vectors` es `n×n`, los eigenvectors son columnas correspondientes y los
eigenvalues salen en orden ascendente.

El consumer público usa una Matrix simétrica indefinida, imprime ambos fields
y vuelve a leer `A` después de la llamada. La qualification confirma además
que los owners de resultado son independientes y que la entrada permanece
usable tanto en éxito como en excepciones capturables.

## Validación y precedencia

La implementación ejecuta antes de cualquier allocation numérica:

1. `shapeGuard(rows(*A)==columns(*A))`;
2. scan row-major completo de finitud, acumulando
   `matrixScale=max(abs(A[i,j]))`;
3. scan lower row-major de simetría IEEE exacta;
4. detección de fast path o allocation de la ruta general.

Por construcción, cualquier NaN o infinito global produce
`NonFiniteMatrixException` antes que cualquier asimetría finita. Una pareja
finita distinta produce `NotSymmetricMatrixException`; no existe tolerance.
Los fallos no finitos producidos durante cálculo o rescale usan
`NumericalConvergenceException`.

## Scaling y fast paths

La ruta general sólo se alcanza para `n>=2`, Matrix no diagonal y
`matrixScale>0`. Crea un único workspace zero-filled y copia exclusivamente
el triángulo inferior autorizado como `A[i,j]/matrixScale`, una sola vez por
entrada. El upper triangle nunca se consulta como autoridad.

Las rutas directas son:

- `0×0`: owners lógicamente vacíos, cero backings;
- `1×1`: valor original e identidad;
- diagonal exacta: copia de diagonal e identidad, canonicalización y sort;
- cero: incluida en la ruta diagonal, con todos los valores escritos `+0`.

No se aplica Householder ni QR en estos casos y ninguna Matrix almost-diagonal
se trata como diagonal.

## Composición, rescale y ordering

La ruta general reutiliza sin modificar los kernels calificados
`reduceSymmetricTridiagonal`, `materializeSymmetricTridiagonalQ` y
`convergeSymmetricTridiagonalState`. El assembly mantiene `values`, `e` y
`vectors` como owners locales separados porque Aether prohíbe partial moves de
`SymmetricTridiagonalSeed`; esto es el mismo plumbing owner que implementan
los wrappers `symmetricTridiagonalSeedInPlace` y `symmetricTridiagonalQR`, sin
duplicar ni rediseñar sus kernels matemáticos.

Tras QR se comprueba que toda `e` sea cero y se escribe literalmente `+0`.
Cada valor se reescala una vez como `matrixScale*value`; un resultado no finito
lanza `NumericalConvergenceException`, y todo zero se canonicaliza a `+0` sin
cambiar el signo de ningún valor no cero.

El ordenamiento es selection sort determinista ascendente. Para cada posición
busca sólo valores estrictamente menores y hace como máximo un swap del valor
y de las dos columnas completas. `swapSymmetricEigenColumns` usa un único
temporal escalar por fila, valida ambos índices con `shapeGuard` y no asigna
un Vector temporal. No se promete orden estable dentro de multiplicidades ni
se canonicalizan signos de eigenvectors.

Antes del retorno se recorren completamente values y vectors, se exige
finitud y ordering, y no se reconstruye `A` ni se valida ortogonalidad dentro
del producto.

## Ownership, allocations y complejidad

En la ruta general de orden al menos tres, la instrumentación observa los seis
backings internos normativos:

```text
workspace, values/d, e, tau, work, vectors
```

QR agrega cero allocations y assembly no crea un séptimo backing. La prueba
instrumentada cuenta siete junto con la Matrix literal de entrada. La ruta
diagonal cuenta sólo `values` y `vectors` además de la entrada, y la ruta
`0×0` cuenta cero allocations y cero frees. Todos los temporales se destruyen
exactamente una vez; ninguna view escapa.

El storage peak es `2n²+O(n)`. Validación, copia y sort cuestan `O(n²)`; el
movimiento total de columnas del selection sort es `O(n²)`; reducción,
materialización y acumulación de QR conservan el total `O(n³)`. No existen
matrices dense `T`, `H`, `G` o diagonal, transpose owner, characteristic
polynomial, SVD, QR dense, LAPACK ni BLAS.

## Qualification, oracle e IR

Se agregó
`compiler-next/crates/aether-driver/tests/linear_algebra_symmetric_eigen_assembly_v1.rs`.
Ejecuta float32/float64 en O0/O2 y cubre `0×0`, `1×1`, diagonal desordenada,
identidad, cero, dense symmetric, positive definite, semidefinite, singular,
indefinite, valores repetidos, clusters, bloques separados, escalas uniformes
grandes/pequeñas, signed zeros, shape no square, simetría aproximada, NaN/Inf
con precedencia y overflow de rescale.

El host acumula con norma Frobenius escalada y comprueba:

```text
||A*Q-Q*diag(values)||F / scale <= 2048*n*epsilon(T)
||Q^T*Q-I||F                   <= 2048*n*epsilon(T)
||Q*diag(values)*Q^T-A||F/scale <= 2048*n*epsilon(T)
```

Los valores se comparan independientemente con `numpy.linalg.eigvalsh` y con
los valores retornados por `numpy.linalg.eigh`. En spectra repetidos o
clustered no se comparan columnas individuales: se comparan los proyectores
de los subespacios completos, y residual, ortogonalidad y reconstrucción
califican además el eigenspace y la correspondencia value/column.

MIR/SSA/LLVM contienen instancias float32/float64 concretas de la API,
reducción y convergencia. LLVM no conserva `GenericParam`, witness, vtable,
boxing, `TypeId`, opcode/helper eigen, Matrix intrinsic, LAPACK o BLAS. Los
source scans fijan la superficie pública, la copia lower-authoritative y la
ausencia de rutas productivas prohibidas.

## Validación

El cierre quedó verde con:

```text
aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_symmetric_eigen_assembly_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

También quedaron verdes las regresiones de tridiagonalización, QR
tridiagonal, todos los verticales SVD, LU, QR, Cholesky y representación de
Matrix incluidas por el workspace y el diferencial.

CLOSED
