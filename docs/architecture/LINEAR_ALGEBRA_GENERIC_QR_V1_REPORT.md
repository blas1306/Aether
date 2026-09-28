# LINEAR-ALGEBRA-GENERIC-QR-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC_CAPABILITIES_V1_REPORT](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [LINEAR_ALGEBRA_OAL_V1_QR_REPORT](LINEAR_ALGEBRA_OAL_V1_QR_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_CONSTRUCTORS_V1_REPORT](LINEAR_ALGEBRA_GENERIC_CONSTRUCTORS_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_LU_V1_REPORT](LINEAR_ALGEBRA_GENERIC_LU_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT](LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT.md).

## API final y deduplicación

El aggregate representacional conserva `QR<T: Storable>` y sus matrices `Q` y
`R`. Los kernels concretos fueron reemplazados por una única implementación:

```aether
QR<T> qr<T: IEEEFloat>(Matrix<T> A);
```

`qrFloat32` permanece sólo como wrapper de compatibilidad deprecated y su body
es exactamente `return qr(A);`. No contiene loops, lógica numérica, casts ni
ramas por precisión. La inferencia desde `Matrix<float64>` y `Matrix<float32>`,
el resultado esperado y la sintaxis explícita `qr<float32>(A)` están
calificados, junto con forwarding desde una función genérica externa.

## Equivalencia del kernel

El cuerpo genérico es una sustitución directa del Householder vigente. Conserva
`Q: m×m`, `R: m×n`, `p=min(m,n)`, el orden y límites de todos los loops, la
acumulación `Q <- Q H`, el reflector alojado temporalmente bajo `R[k,k]` y la
actualización de columnas posteriores antes de limpiar ese storage. No se
materializan matrices `H`, transposes, slices ni owners auxiliares.

La norma mantiene el mismo scaled sum of squares, incluida la secuencia de
`abs`, comparaciones, ratios y `sqrt`. La selección de signo de `alpha`, el
tratamiento exacto de columnas cero y la admisión de rank deficiency tampoco
cambian. Por ello se preservan las rutas IEEE existentes para signed zero, NaN,
infinito y subnormales, sin fast-math ni simplificaciones algebraicas.

`Q` se construye mediante `identity<T>(m)`. El kernel declara una vez `zero`,
`one` y `two = one + one`; no usa literal genérico `2` ni casts desde enteros.

## Capabilities y lowering

La única constraint pública es `T: IEEEFloat`. El HIR paramétrico contiene las
operaciones efectivamente usadas: `Zero`, `One`, `Add`, `Sub`, `Mul`, `Div`,
`Negate`, `Equal`, `Order`, `Abs` y `Sqrt`. Las instancias concretas sustituyen
completamente `T`; MIR y SSA no retienen nodos capability ni parámetros
genéricos.

LLVM emite instancias separadas `float32` y `float64`, llamadas directas a
`fabsf`/`fabs` y `sqrtf`/`sqrt`, y aritmética concreta. No aparecen witnesses,
vtables, `TypeId` ni llamadas numéricas indirectas.

## Ownership, allocations y shapes

`qr(Matrix<T> A)` consume la entrada y reutiliza su backing como `R`. La única
Matrix adicional es `Q`; la prueba instrumentada observa exactamente dos
allocations y dos frees para una entrada tall no vacía tanto en O0 como en O2.
La genericidad no agrega workspaces ni allocations.

El consumer verifica `0×0`, `0×n`, `m×0`, `1×1`, square, tall, wide, identidad,
diagonal, columnas cero, rank deficiency y varios reflectores en ambas
precisiones. Comprueba shapes, triangularidad de `R`, reconstrucción `A ≈ Q*R`
y ortogonalidad `QᵀQ ≈ I` con las tolerancias QR-V1 vigentes. También comprueba
igualdad elemento a elemento entre `qrFloat32(A)` y `qr<float32>(A)`.

## Validación

```text
aether check linearAlgebra
aether check linearAlgebra/tests/consumer
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_qr_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

## Fuera de scope

No se cambió el algoritmo Householder, la representación de `QR`, las
tolerancias, el modelo de ownership, la política de inferencia ni se agregó
soporte para `Complex` o tipos numéricos de usuario.
