# LINEAR-ALGEBRA-GENERIC-LU-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC_CAPABILITIES_V1_REPORT](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [LINEAR_ALGEBRA_LU_ARCH_1](LINEAR_ALGEBRA_LU_ARCH_1.md);
- [LINEAR_ALGEBRA_LU_V1_REPORT](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_CONSTRUCTORS_V1_REPORT](LINEAR_ALGEBRA_GENERIC_CONSTRUCTORS_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md).

## API final y deduplicación

`linearAlgebra` conserva el aggregate representacional y reemplaza los dos
kernels concretos por una única declaración e implementación source:

```aether
struct LU<T: Storable> {
    Vector<usize,Column> permutation;
    int permutationSign;
    Matrix<T> L;
    Matrix<T> U;
}

LU<T> lu<T: IEEEFloat>(Matrix<T> A);
```

No quedan wrappers `float32`/`float64`, helpers alternativos ni dispatch por
tipo. `det`, los dos `solve` y QR conservan sus APIs y cuerpos concretos.
Inferencia desde `Matrix<float64>` y `Matrix<float32>`, resultado esperado y la
sintaxis explícita `lu<float32>(A)` quedan calificados. Otros elementos, incluido
`int`, se rechazan por el constraint general `IEEEFloat`.

## Equivalencia exacta con LU-V1

El cuerpo genérico es la sustitución directa del kernel concreto previo. No se
cambió el orden de loops, comparaciones, swaps, divisiones ni updates. Para
`A : m×n`, `r=min(m,n)`, siguen valiendo:

- `L : m×r`, `U : r×n` y `P A ≈ L U`;
- pivoting parcial por `abs`, búsqueda ascendente y reemplazo sólo con `>`;
- permutación owning `Vector<usize,Column>` 1-based y signo inicial `+1`, negado
  una vez por row swap;
- pivot cero decidido por igualdad IEEE exacta, sin epsilon; si es cero se
  omiten división y update, sin excepción;
- matrices singulares y rank-deficient producen factores ordinarios;
- `0×0`, `0×n` y `m×0` conservan sus shapes y rutas de backing vacío.

NaN, infinitos, signed zero y subnormales siguen exactamente la semántica de
las operaciones IEEE existentes. No se materializa `P`, no hay transpose,
slices ni owners temporales de fila.

## Capabilities, HIR y código concreto

El único constraint declarado es `T: IEEEFloat`. El kernel define `T zero = 0`
y `T one = 1` y usa exactamente las familias requeridas por sus expresiones:

- `AlgebraicValue`: `Zero` y `One`;
- `CapabilityMath`: `Abs`;
- `CapabilityCompare`: `Equal` y `Order`;
- `CapabilityBinary`: `Div`, `Sub` y `Mul`.

La prueba de lowering comprueba estas operaciones en HIR paramétrico. Las
instancias HIR concretas sustituyen `T`; MIR y SSA no contienen operaciones
capability ni parámetros genéricos residuales. LLVM contiene instancias `lu`
separadas para `float32` y `float64`, llamadas directas a `fabsf` y `fabs`, y
accesos/fills de Matrix de la precisión correspondiente. No aparecen `TypeId`,
witnesses, vtables ni indirect dispatch.

## Ownership y allocations

`lu(Matrix<T> A)` continúa consumiendo `A` y usando su backing como workspace y
como uno de los factores finales. La única Matrix adicional es `r×r`; la otra
allocation propia del algoritmo es la permutación. La qualification tall no
vacía sigue observando exactamente tres allocations y tres frees en O0 y O2:
entrada, permutación y factor adicional. La genericidad no agrega allocations.

## Oráculo numérico y regresión

El consumer versionado conserva el oráculo previo de ambos kernels concretos:
square, tall, wide, shapes cero, identidad, diagonal, triangulares, uno y varios
swaps, empate de pivots, rank deficiency, pivot cero, matrices cero, `-0.0` y
los casos IEEE ya cubiertos. Verifica factores, shapes, permutación, signo,
triangularidad, diagonal unitaria y reconstrucción. Los mismos casos pasan para
`float64` y `float32` después de la deduplicación, en O0 y O2.

Constructores genéricos, `det` concreto, ambos `solve`, QR y el consumer completo
permanecen verdes. No se migró `det` en este milestone.

## Desbloqueo de generic det

Una función externa al package se analiza, monomorfiza y ejecuta correctamente:

```aether
LU<T> genericLU<T: IEEEFloat>(Matrix<T> A) {
    return linearAlgebra.lu(A);
}
```

Esto elimina la condición de bloqueo documentada por
`LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT`: el body paramétrico ya resuelve una única
declaración genérica `lu`, sin overload resolution diferida.

## Validación

Se ejecutó correctamente:

```text
aether check linearAlgebra
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_lu_v1
```

La matriz completa adicional del repositorio se ejecutó al cierre del cambio:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

## Fuera de scope

No se implementaron resolución diferida de overloads, migración genérica de
`det`/`solve`/QR, Cholesky, `Complex`, tipos numéricos de usuario, pivoting
alternativo, tolerancias ni integración BLAS/LAPACK.
