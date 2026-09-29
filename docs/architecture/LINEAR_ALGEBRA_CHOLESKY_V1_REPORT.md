# LINEAR-ALGEBRA-CHOLESKY-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-28.

Autoridad normativa:

- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1-REPORT](LINEAR_ALGEBRA_CHOLESKY_ARCH_1_REPORT.md);
- [NUMERIC-CAPABILITIES-ARCH-1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [NUMERIC-GENERIC-MIGRATION-CLOSURE-1](NUMERIC_GENERIC_MIGRATION_CLOSURE_1_REPORT.md).

## Resultado y API

`linearAlgebra` implementa Cholesky real V1 como package code ordinario, con
una sola implementación source:

```aether
struct Cholesky<T: Storable> {
    Matrix<T> L;
}

public class NotSymmetricMatrixException : Exception {
    public init() {}
}

public class NotPositiveDefiniteException : Exception {
    public init() {}
}

Cholesky<T> cholesky<T: IEEEFloat>(Matrix<T> A);
```

No se agregaron overloads ni wrappers por precisión, selector upper/lower,
tolerancia o soporte especial de compiler. `T` se infiere desde la Matrix y
también admite argumento genérico explícito.

## Dominio y orden de validación

La primera operación del kernel es
`shapeGuard(rows(A) == columns(A))`. Por ello toda Matrix rectangular,
incluidas `0×n` y `m×0`, conserva el trap abortivo `ShapeMismatch` antes de
cualquier acceso dependiente de square shape.

Antes de mutar la entrada se ejecuta el pase normativo por filas crecientes:
primero `A[i,i]` y luego cada par `A[i,j]`, `A[j,i]` con `j < i` creciente.
Cada valor se considera finito exactamente cuando `(x - x) == 0`. Un no finito
lanza `NotPositiveDefiniteException`; dos valores finitos distintos lanzan
`NotSymmetricMatrixException`. La comparación es IEEE exacta, sin epsilon ni
comparación bitwise, de modo que `+0` y `-0` son simétricos.

La precedencia observable queda fijada como shape, no finitud, asimetría y
pivot calculado no positivo. Las dos excepciones nominales se califican con
catches separados; `ShapeMismatch` no se convierte en Exception.

## Algoritmo y semántica IEEE

El kernel es Cholesky lower, clásico, unblocked y row-oriented. Para cada
`(i,j)`, `value` comienza en `A[i,j]`; el loop `k` creciente ejecuta
literalmente multiplicación seguida de resta. La diagonal comprueba, antes de
`sqrt`, `(value - value) == 0` y `value > 0`. Las entradas inferiores dividen
por la diagonal ya calculada.

Así se rechazan `+0`, `-0`, negativos, NaN e infinitos, incluidos no finitos
producidos durante el cálculo. Un subnormal positivo es válido cuando la
aritmética concreta conserva un pivot positivo. No hay reassociation, FMA
contractual, acumulador promovido, fast-math ni check off-diagonal adicional.

Una vez completada toda la factorización se escribe el triángulo superior con
el `Zero` concreto, que materializa `+0`. La qualification comprueba signo de
cero, diagonal positiva, finitud, shape y reconstrucción `A ≈ L L^T`.

## Ownership, allocations y zero shape

`cholesky(Matrix<T> A)` consume la entrada y reutiliza exactamente su backing
como `Cholesky.L`. No crea Matrix, Vector, transpose, symmetric copy ni owner
auxiliar. La ruta válida tiene cero allocations internas del kernel en O0 y
O2; sólo existe la allocation realizada por el caller para una entrada no
vacía.

En exception, unwind destruye la entrada exactamente una vez y no publica un
factor parcial. La instrumentación comprueba balance de allocations/frees y
ausencia de double-drop en ambas clases de excepción.

`0×0` ejecuta naturalmente loops vacíos, conserva shape `0×0`, mueve el owner
vacío al resultado y no asigna backing ni lanza excepción.

## Capabilities y lowering

La frontera pública es únicamente `T: IEEEFloat`. El cuerpo paramétrico usa
`Zero`, `Sub`, `Mul`, `Div`, `Equal`, `Order` y `Sqrt`; no exige
explícitamente `One`, `Add`, `Negate` ni `Abs` para `T`.

HIR conserva los nodos capability genéricos correspondientes. Las instancias
concretas sustituyen `T`; MIR y SSA no contienen generic parameters ni nodos
capability. LLVM emite instancias separadas `float32`/`float64`, calls directas
a `sqrtf`/`sqrt`, y no contiene `TypeId`, witnesses, vtables ni dispatch
numérico indirecto.

## Qualification y regresión

El consumer integrado cubre ambas precisiones, `0×0`, escalar positiva,
identity, diagonal, SPD dense con factor conocido, SPD general, SPD
razonablemente condicionada, inferencia, argumento genérico explícito,
forwarding genérico, reconstrucción y formatting del factor.

La suite dedicada
`aether-driver/tests/linear_algebra_cholesky_v1.rs` agrega estructura source,
lowering O0/O2, constraints, move semantics, allocations y unwind. Sus casos
inválidos incluyen rectangulares con extents cero, PSD/singular, indefinida,
diagonal negativa, pivots `±0`, diferencia simétrica de un ULP, NaN e
infinitos en diagonal/off-diagonal, no finitos intermedios y subnormal
negativo. También confirma aceptación de ceros con signos opuestos y
subnormales positivos en ambas precisiones.

Se mantienen sin cambios las APIs de constructors, LU, determinant, solve y
QR. Cholesky no implementa solve, determinant, inverse, Complex/Hermitian,
pivoting, sparse, blocked BLAS ni variantes unchecked.

Validación del milestone:

```text
compiler-next/target/debug/aether check linearAlgebra
compiler-next/target/debug/aether run linearAlgebra/tests/consumer -O0
compiler-next/target/debug/aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_cholesky_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```
