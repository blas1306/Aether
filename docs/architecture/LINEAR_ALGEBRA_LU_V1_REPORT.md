# LINEAR-ALGEBRA-LU-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [LINEAR_ALGEBRA_LU_ARCH_1](LINEAR_ALGEBRA_LU_ARCH_1.md);
- [LINEAR_ALGEBRA_LU_ARCH_1_REPORT](LINEAR_ALGEBRA_LU_ARCH_1_REPORT.md).

## Resultado

El package ordinario `linearAlgebra` publica exactamente la superficie cerrada:

```aether
struct LU<T: Storable> {
    Vector<usize,Column> permutation;
    int permutationSign;
    Matrix<T> L;
    Matrix<T> U;
}

LU<float64> lu(Matrix<float64> A);
LU<float32> lu(Matrix<float32> A);
```

No se agregó un overload genérico, nombres alternativos, helpers públicos de
permutación ni un campo de singularidad. QR y los constructores existentes no
cambiaron de contrato.

Para `A` de shape `m×n` y `r=min(m,n)`, el resultado materializado tiene
`permutation` de longitud `m`, `L` de shape `m×r` y `U` de shape `r×n`, y
satisface:

```text
(P A)[i,j] = A_original[permutation[i],j]
P A ≈ L U
```

La permutación owning es 1-based, comienza como `[1,2,...,m]` y se intercambia
junto con cada row swap. `permutationSign` comienza en `+1` y se niega sólo
cuando el pivot elegido está en otra fila.

## Kernel y storage

Cada overload usa su argumento owning como workspace packed. En cada paso
selecciona por `abs` el mayor pivot de la columna activa y sólo reemplaza al
candidato ante una desigualdad estricta, por lo que los empates conservan el
menor índice. Un swap recorre escalarmente las `n` columnas completas y usa un
único temporal del tipo elemental; no crea slices ni owners de fila.

Un pivot exactamente igual a cero, incluido `-0.0`, omite la división y la
actualización del paso. No hay epsilon, preescaneo, trap, excepción ni outcome
nominal. NaN e infinito quedan bajo las operaciones IEEE ordinarias usadas por
el kernel.

La materialización económica recicla el backing recibido:

- si `m <= n`, se copian los multiplicadores a un `L` nuevo `m×m`, se limpia
  el triángulo inferior del workspace y éste se devuelve como `U`;
- si `m > n`, se copia el triángulo superior a un `U` nuevo `n×n`, se convierte
  el workspace en el `L` `m×n` escribiendo su diagonal unitaria y limpiando su
  parte superior.

Además del owner de entrada sólo se asignan el vector de permutación y un
factor `r×r`. Nunca se materializa `P` ni se conserva públicamente el packed.

## Calificación numérica

El consumer independiente prueba `float64` con tolerancia `1e-12` y `float32`
con tolerancia `2e-5`. Para ambos tipos cubre:

- ausencia de swaps, exactamente un swap y múltiples swaps;
- desempate por módulo y dirección exacta de la permutación;
- identidad, diagonal, triangular superior e inferior y pivots negativos;
- `-0.0`, singular square, fila cero y matriz cero;
- `0×0`, `m×0`, `0×n` y `1×1`;
- tall y wide, tanto full-rank como rank-deficient.

Cada caso verifica shapes económicas exactas, biyección 1-based, signo,
estructura triangular, diagonal unitaria de `L` y reconstrucción mediante el
gather `A_original[permutation[i],j]`. Los casos de pivot cero confirman por
ejecución que no hay trap.

## Calificación estructural

La prueba Rust
`aether-driver/tests/linear_algebra_lu_v1.rs` fija estas propiedades:

- existe una sola declaración pública de cada overload concreto y no aparecen
  nombres alternativos ni helpers fuera de scope;
- HIR, MIR y SSA conservan `MatrixRows`, `MatrixColumns`, `MatrixFilled` y
  `VectorFilled` ordinarios;
- LLVM contiene los accesos y filled-init generales de Matrix/Vector para
  `float32`, `float64` y `usize`, y no contiene un helper o intrinsic `aether_lu`;
- una factorización tall no vacía realiza exactamente tres allocations y tres
  frees en O0 y O2: owner de entrada, permutación y factor adicional.

El diff no modifica parser, HIR, MIR, SSA, optimizadores, backend, runtime ni
allowlists. El loop de pivot contiene únicamente búsqueda escalar, swap
escalar, indexing, assignment, `abs` y aritmética ordinaria del package.

## Package dogfood y registry

El consumer versionado conserva toda la cobertura anterior de constructors y
QR y ejecuta además LU V1 para ambos tipos. `aether publish linearAlgebra
--dry-run` produce el archive cerrado con sólo `aether.toml` y `src/lib.ae`.

La prueba de registry local existente publica el package real, lo marca
official, lo agrega y sincroniza en un consumer independiente y ejecuta ese
consumer ampliado en O0 y O2. Por lo tanto el consumo LU queda calificado sin
agregar infraestructura ni ampliar el scope del package manager.

## Validación

Se ejecutó correctamente con el binario del workspace:

```text
aether check linearAlgebra
aether check linearAlgebra/tests/consumer
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_lu_v1
cargo test -p aether-registry --test registry \
  linear_algebra_oal_publishes_and_runs_real_qr_consumer
aether publish linearAlgebra --dry-run
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

La suite diferencial completó 21 casos sin fallos.

## Fuera de scope

No se implementaron `solve`, `det`, inverse, Cholesky, SVD, eigenvalues, rank,
pivoting complete/rook/scaled/threshold, tolerancias de singularidad,
variantes sparse/block, `Complex<T>` ni integración BLAS/LAPACK.
