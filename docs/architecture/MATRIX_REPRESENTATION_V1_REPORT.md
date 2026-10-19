# MATRIX-REPRESENTATION-V1 — reporte de cierre

Estado: **CLOSED**, 2026-10-15.

Autoridad normativa:

- [MATRIX-REPRESENTATION-ARCH-1](MATRIX_REPRESENTATION_ARCH_1.md);
- [MATRIX-REPRESENTATION-ARCH-1-REPORT](MATRIX_REPRESENTATION_ARCH_1_REPORT.md);
- [GENERIC-INFERENCE-REF-ARGUMENT-V1](GENERIC_INFERENCE_REF_ARGUMENT_V1_REPORT.md).

## Resultado

`compiler-next` expone el package canónico `std.Math.LinearAlgebra` como un
package toolchain sintético real. Su unidad tiene identidad y path lógico std,
participa en discovery/imports y su contenido atraviesa el parser, HIR,
monomorfización y lowering ordinarios. No es un alias del package OAL
`linearAlgebra` ni una colección de intrinsics ocultos.

El package implementa en source Aether ordinario las tres firmas cerradas:

```aether
public Matrix<T> transposeCopy<T: Storable + Copy + Zero>(
    ref Matrix<T> source);

public Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(
    ref Vector<T,Column> values);

public Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(
    ref Vector<T,Row> values);
```

`transposeCopy` lee una Matrix `m×n` por indexación lógica y devuelve un owner
independiente `n×m`, sin consumir ni mutar la fuente. `diagonalMatrix` tiene
overloads nominales para Column y Row; ambos producen una Matrix dense `k×k`,
copian el Vector sobre la diagonal y conservan Zero fuera de ella. No se
agregaron aliases al package OAL ni variantes especializadas por tipo.

## Capabilities, extents y allocations

Las tres firmas exigen exactamente `Storable + Copy + Zero`. `Storable`
habilita el storage owning, `Copy` permite poblar el resultado desde una
entrada shared y `Zero` alimenta la inicialización segura mediante
`matrixFilled`. Para `diagonalMatrix`, Zero forma además parte del resultado;
en `transposeCopy` es la constraint del builder seguro disponible, no una
semántica numérica adicional.

La construcción conserva los zero extents:

- `transposeCopy(0×n)` produce `n×0`;
- `transposeCopy(m×0)` produce `0×m`;
- `transposeCopy(0×0)` produce `0×0`;
- `diagonalMatrix` de un Vector de dimensión cero produce `0×0`.

Un resultado no vacío usa una sola allocation, la de `matrixFilled`, y no
crea buffers auxiliares. Un resultado con cero celdas conserva sus extents sin
backing y realiza cero allocations. El coste de `transposeCopy` es `O(m*n)` y
el de `diagonalMatrix` es `O(k²)` por la Matrix dense inicializada; las fuentes
y los resultados conservan ownership y cleanup independientes.

## Integración con views y factores

Las APIs owning complementan, sin sustituirlas, las operaciones existentes
`transpose_view` y `transpose_view_mut`. Las views continúan siendo descriptores
`O(1)`, sin allocation ni copia, con los mismos shape/strides, provenance,
lifetime y reglas de mutabilidad. `transposeCopy` se usa sólo cuando el
consumer necesita materializar un owner independiente; no existe conversión
implícita de view a owner.

La integración SVD real queda disponible con la sintaxis natural:

```aether
var factor = la.svd(A);
Matrix<double> Sigma = mat.diagonalMatrix(factor.S);
Matrix<double> V = mat.transposeCopy(factor.Vt);
```

Ambas llamadas funcionan **sin argumentos de tipo explícitos** y sin cambiar
`SVD<T>` ni agregar getters. El consumer también puede observar `Vt` mediante
`transpose_view(factor.Vt)` cuando no necesita materialización.

La misma composición se mantiene para QR: `factor.Q` y `factor.R` siguen
siendo Matrix owners ordinarios; un consumer puede usar
`transpose_view(factor.Q)` sin copia o `mat.transposeCopy(factor.Q)` para una
transpuesta owning. No se modificaron `QR<T>`, el algoritmo Householder, sus
shapes ni sus allocations internas.

## IR y monomorfización

El source genérico conserva sus parámetros, capabilities, borrows shared,
loops e indexación 1-based en HIR. La instanciación ordinaria sustituye `T` por
el tipo concreto antes de MIR/SSA/LLVM; el resultado contiene
`MatrixFilled`, loads y stores normales, no generic residue, witnesses,
dispatch por `TypeId` ni opcodes de transpose/diagonal nuevos.

Estas APIs no requirieron cambios de runtime ni de semántica del compilador:
son algoritmos source sobre primitives ya existentes. El único cambio de
frontend relacionado con el consumer natural es
`GENERIC-INFERENCE-REF-ARGUMENT-V1`, una corrección separada y general de la
inferencia desde argumentos `Place` adaptados a `ref`. No forma parte de la
API matricial, no reconoce SVD/Matrix/Vector por nombre y no agrega una ruta
especial de lowering.

## Validación ejecutada

```text
cargo test --workspace                                      PASS
cargo fmt --all --check                                     PASS
cargo clippy --workspace --all-targets -- -D warnings       PASS
bash compiler-next/tests/run-differential.sh                PASS (21/21)
git diff --check                                            PASS
```

La qualification cubre el import canónico del package sintético, las tres
firmas source, lowering HIR/MIR/SSA/LLVM, Row/Column, la integración SVD sin
type arguments explícitos y la regresión general de inferencia. La regresión
global mantiene los consumers y kernels QR existentes.

No se rediseñó Matrix, no se agregó funcionalidad derivada y no se modificó
source productivo durante este cierre documental.
