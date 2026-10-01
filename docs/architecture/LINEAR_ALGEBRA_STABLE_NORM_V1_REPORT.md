# LINEAR-ALGEBRA-STABLE-NORM-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-10-01.

Autoridad normativa:

- [LINEAR-ALGEBRA-STABLE-NORM-ARCH-1](LINEAR_ALGEBRA_STABLE_NORM_ARCH_1.md);
- [LINEAR-ALGEBRA-STABLE-NORM-ARCH-1-REPORT](LINEAR_ALGEBRA_STABLE_NORM_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md).

## Gate de visibilidad

El gate inicial falló: el pipeline aceptaba calls calificadas a toda función y
constructor de struct top-level aunque la declaración omitiera `public`.
Antes de modificar QR se implementó el vertical mínimo de visibilidad ordinaria
para funciones y structs:

- el parser, AST y metadata de firmas conservan `public` explícito;
- una función top-level sin `public` no participa en resolución calificada
  desde otro módulo;
- un struct sin `public` no puede nombrarse ni construirse desde otro módulo;
- las APIs preexistentes se migraron a `public` explícito para no reducir la
  superficie anterior.

La qualification negativa independiente intenta referenciar
`StableScaledSquares`, `stableScaledSquaresRange`,
`finishStableNormNonzero`, `stableNormRange` y `stableHypot`; los cinco fallan
por resolución/visibilidad ordinaria. Ninguno usa underscore, export
condicional o wrapper público de test.

## Autoridad source privada

`linearAlgebra/src/lib.ae` contiene un único aggregate privado
`StableScaledSquares<T: Storable>` con `scale` y `scaledSquares`, y cuatro
helpers privados bajo `T: IEEEFloat`:

```aether
StableScaledSquares<T> stableScaledSquaresRange(...);
T finishStableNormNonzero(...);
T stableNormRange(...);
T stableHypot(T a, T b);
```

La recurrencia se copió literalmente con recorrido inclusivo one-based,
estado inicial `scale=+0` y `scaledSquares=1`, y rango vacío canónico `1..0`.
Se preservan los árboles `(scaledSquares * ratio) * ratio` y `ratio * ratio`
antes del `Add`; no se agregó FMA, reassociation, acumulador promovido,
reducción vectorial, fast-math ni `epsilon<T>()`.

La finalización no agrega checks y ejecuta exactamente
`state.scale * sqrt(state.scaledSquares)`. El wrapper devuelve el literal
`+0` cuando la escala es cero. `stableHypot` mantiene el swap explícito de
`high`/`low` y finaliza con `high * sqrt(one + ratio * ratio)`.

## Ceros, NaN e infinito

Qualification white-box en float32/float64 y O0/O2 cubre vacío, elemento
positivo/negativo, `3,4 -> 5`, ambos órdenes de hypot, invariancia de signo,
signed zeros, subnormales, magnitudes very small y huge/tiny. Vacío y toda
mezcla de ceros retorna exactamente `+0`, verificado también mediante el signo
del recíproco.

No se agregó validación de finitud ni excepción. Las rutas operacionales
observadas son las normativas: NaN más ceros puede dejar escala cero, NaN con
finito no nulo contamina el resultado, un infinito aislado produce infinito y
dos infinitos producen NaN. Hypot propaga NaN, produce infinito para infinito
más finito y NaN para dos infinitos.

Los casos `{1e308,1e308}`/`{1e-200,1e-200}` en float64 y sus equivalentes
float32 demuestran un resultado representable donde el cuadrado directo
overflowearía o underflowearía prematuramente. No se exige correctly-rounded.

## Views, extracción QR y fixture congelado

`qrInPlace` construye `column(R,k)` en O(1) y llama
`stableScaledSquaresRange<T>(...,k,m)`. La branch sigue siendo exactamente
`if (state.scale != zero)` y sólo dentro invoca
`finishStableNormNonzero`; selección de `alpha`, storage del reflector,
actualizaciones Q/R y loops posteriores no cambiaron.

La qualification conserva una copia test-only del loop pre-extraction y
compara Q/R completos contra el QR extraído en float32/float64, O0/O2, cero,
signed zero, escalas extremas y rutas NaN/Inf. No existe una segunda
implementación productiva. Los descriptors `VectorView` de `column` son
valores de stride/shape ya calificados y no materializan Vector ni slice owner;
la misma firma admite en el futuro `transpose_view(row(A,r))` sin implementar
consumers SVD.

## Coste, capabilities y lowering

Las pruebas instrumentadas observan una sola allocation/free atribuible a la
Matrix de entrada del fixture y ninguna adicional por norma o hypot. La prueba
QR conserva el budget histórico de dos allocations/frees y el workspace R.

Los helpers usan exactamente `Zero`, `One`, `Add`, `Mul`, `Div`, `Equal`,
`Order`, `Abs` y `Sqrt`; no usan `Sub`, `Negate` ni epsilon. HIR conserva esas
operaciones capability en source paramétrico. Las instancias float32/float64
eliminan `GenericParam`, operaciones capability, witnesses, vtables, boxing y
calls indirectas antes de MIR/SSA; LLVM contiene las calls concretas a
`fabs[f]`/`sqrt[f]`, sin opcode o runtime especial de norma/hypot.

## Validación

El cierre se calificó con:

```text
aether check linearAlgebra
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_stable_norm_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

Permanecen fuera de scope SVD, bidiagonalización, Givens, APIs públicas de
norma/hypot, tolerancias epsilon, SIMD y BLAS/LAPACK.
