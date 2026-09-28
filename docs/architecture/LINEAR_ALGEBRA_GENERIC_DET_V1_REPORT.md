# LINEAR-ALGEBRA-GENERIC-DET-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC_CAPABILITIES_V1_REPORT](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [LINEAR_ALGEBRA_DET_V1_REPORT](LINEAR_ALGEBRA_DET_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_LU_V1_REPORT](LINEAR_ALGEBRA_GENERIC_LU_V1_REPORT.md).

## Desbloqueo y API final

El bloqueo del reporte anterior quedó resuelto por
`LINEAR-ALGEBRA-GENERIC-LU-V1`: `lu` es ahora una única declaración
`LU<T> lu<T: IEEEFloat>(Matrix<T> A)`. Por eso la ruta Matrix de `det` resuelve
directamente esa identidad genérica durante el análisis paramétrico. No se
implementó ni se necesitó resolución diferida de overloads.

Los cuatro overloads concretos fueron reemplazados por exactamente estas dos
declaraciones públicas:

```aether
T det<T: IEEEFloat>(ref LU<T> factor);
T det<T: IEEEFloat>(Matrix<T> A);
```

No quedan declaraciones `det` concretas para `float32` o `float64`, wrappers,
helpers por precisión, `TypeId` ni dispatch runtime. El dominio público sigue
siendo exactamente `float32` y `float64` mediante el marker sellado
`IEEEFloat`.

## Kernels y equivalencia con DET-V1

La ruta owning conserva primero:

```aether
shapeGuard(rows(A) == columns(A));
```

Después construye `LU<T> factor = lu(A);` una sola vez y retorna
`det(factor)`. No existe un segundo kernel ni una copia defensiva.

La ruta de factor mantiene exactamente los cuatro guards DET-V1 y su orden:

```text
rows(L) == columns(L)
rows(U) == columns(U)
rows(L) == rows(U)
dimension(permutation) == rows(U)
```

Luego inicializa `T result = 1`, lo niega sólo cuando
`permutationSign < 0`, y multiplica `U[i,i]` en orden ascendente para
`i = 1..n`. El signo entero nunca se convierte a `T`.

Esto preserva el oráculo DET-V1: singular devuelve cero sin
`SingularMatrixException`, no existe epsilon, `det(0×0) = +1`, el signo viene
de `permutationSign` y el producto conserva el orden anterior. `+0.0`, `-0.0`,
NaN, infinito y subnormales pasan por las mismas operaciones IEEE de cada
precisión, sin normalización ni promoción.

## HIR, MIR, SSA y LLVM

El HIR paramétrico del kernel contiene exactamente las familias numéricas que
requiere su source:

- `AlgebraicValue::One` para el acumulador;
- `CapabilityUnary::Negate` para aplicar el signo;
- `CapabilityBinary::Mul` para el producto diagonal.

Las instancias HIR concretas sustituyen completamente `T` y usan las
operaciones float ordinarias `NegateFloat` y `MultiplyFloat`; no retienen nodos
capability. MIR y SSA contienen sólo operaciones concretas de `float32` o
`float64`, sin `GenericParam`, witnesses ni vtables. LLVM emite instancias
separadas para ambas precisiones, con `fneg`/`fmul` concretos y llamadas
directas; no hay `TypeId`, witnesses, vtables ni indirect dispatch.

## Ownership, allocations y costo

`det(Matrix<T>)` consume `A`, ejecuta una sola LU y cuesta O(n³) más el loop
O(n). Reutiliza el backing de entrada según el contrato de LU y no agrega
copias ni allocations a las propias de la factorización.

`det(ref LU<T>)` conserva un shared borrow, cuesta O(n), hace cero allocations
y no mueve ni copia `L`, `U` o `permutation`. No materializa `P`; el mismo
factor puede reutilizarse después con `solve` y con nuevas llamadas a `det`.

## Qualification

El consumer versionado compara las instancias genéricas `float64` y `float32`
contra la cobertura del oráculo DET-V1: `0×0`, `1×1`, identidad, diagonal,
triangulares, uno y varios swaps, singular, matriz cero, fila cero, `-0.0`, el
caso conocido de determinante 100 y reutilización del factor con `solve`. La
cobertura IEEE vigente de LU conserva además NaN, infinito y subnormales sin
cambiar el orden ni las operaciones del determinante.

La prueba Rust fija también la deduplicación de source, la única llamada a
`lu`, ausencia del cast de signo, orden y presencia de los guards, ownership,
cero allocations en la ruta factor, diagnósticos, lowering paramétrico y
reificación concreta en O0/O2.

Constructores genéricos, LU genérico, los overloads concretos de `solve`
Vector/Matrix, QR concreto y el consumer completo permanecen dentro de la
regresión. `solve` y QR no fueron migrados.

## Validación

Se ejecutó la matriz requerida con el binario `aether` del checkout:

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

## Fuera de scope

No se implementaron resolución diferida de overloads, migración genérica de
`solve` o QR, determinant de `MatrixView`, epsilon/tolerancias, una excepción
de singularidad, matriz `P` densa, `Complex`, witnesses, vtables ni dispatch
por tipo.
