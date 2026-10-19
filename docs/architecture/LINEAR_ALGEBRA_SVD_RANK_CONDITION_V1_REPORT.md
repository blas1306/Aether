# LINEAR-ALGEBRA-SVD-RANK-CONDITION-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-19.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1-REPORT](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-CUTOFF-V1](LINEAR_ALGEBRA_SVD_CUTOFF_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md).

## Resultado y API

`linearAlgebra/src/lib.ae` incorpora exactamente cuatro overloads públicos de
`numericalRank` —desde `Matrix<T>` y desde `SVD<T>`, cada uno con policy
default o cutoff absoluto explícito— y dos overloads públicos de `condition2`,
desde Matrix o factor. La frontera sigue siendo `T: IEEEFloat` y todas las
entradas son préstamos shared.

No se agregó un cutoff a `condition2`, un estimador alternativo, rango
matemático exacto, `effectiveCondition2`, constante Infinity ni soporte de
runtime/compiler. `nonzeroSingularValueCount(ref SVD<T>)` continúa siendo la
única API de conteo representacional y no fue duplicada.

## Rango numérico y autoridad compartida

Las rutas de factor de `numericalRank` retornan directamente el resultado del
overload correspondiente de `retainedSingularValueCount`. No copian la fórmula
default, epsilon, comparación, validación ni traversal. En consecuencia,
`numericalRank`, `pseudoInverse` y `leastSquares` observan exactamente el mismo
prefijo retenido.

Las rutas Matrix ejecutan una única SVD y delegan al overload del factor. En la
ruta de cutoff explícito, la autoridad común valida primero el escalar para
preservar la precedencia normativa frente al scan de finitud de SVD. Negativos,
NaN y ambos infinitos producen `InvalidSingularValueCutoffException`; `+0` y
`-0` son válidos, y un singular value igual al cutoff queda descartado.

La distinción pública es deliberada:

- `nonzeroSingularValueCount` observa si cada valor almacenado es distinto de
  cero, sin epsilon ni policy;
- `numericalRank` declara el rango efectivo del espectro calculado bajo la
  policy compartida de truncamiento.

Por ello un singular value almacenado, positivo y menor que el threshold
default cuenta para la primera consulta pero puede no contar para la segunda.
Ninguna de las dos afirma rango algebraico exacto de la Matrix matemática.

## Condición espectral 2

`condition2` valida las dos relaciones estructurales del factor y después usa
todo el espectro thin. Para `p=dimension(S)`, retorna `S[1]/S[p]`; si `p==0` o
`S[p]==0`, retorna infinito mediante la aritmética IEEE genérica `one/zero`.
Un valor mínimo diminuto pero no cero nunca se reinterpreta mediante cutoff.
Si el cociente overflowea, el infinito IEEE resultante es válido.

Esta definición acepta matrices rectangulares. Una Matrix tall o wide full
rank puede tener condición finita; rank deficiency representada por el mínimo
singular value igual a cero produce infinito. Los espectros vacíos de `0×0`,
`m×0` y `0×n`, y las matrices cero no vacías, también producen infinito según
la convención V1.

## Guards, ownership y complejidad

Cada ruta de factor ejecuta antes de acceder al espectro:

```text
columns(U) == dimension(S)
rows(Vt) == dimension(S)
```

No exige `p==min(m,n)` ni recertifica finitud, ordering, ortogonalidad o
reconstrucción de un aggregate manual. Las rutas Matrix heredan el rechazo de
input no finito y los failures de convergencia de `svd`.

Sobre un factor, ambas consultas crean cero owners y cero allocations.
`numericalRank` es `O(p)` como máximo a través de la autoridad compartida;
`condition2` es `O(1)` después de los guards y usa sólo escalares. No se mueve
ni copia `U`, `S` o `Vt`. Las rutas Matrix agregan exclusivamente el coste y
las allocations de una sola SVD.

## Qualification y oráculo

`linear_algebra_svd_rank_condition_v1.rs` ejecuta float32 y float64 en O0/O2.
Para rango cubre full rank, rank deficiency exacta y numérica, espectro cero,
repetidos, subnormales, igualdad y vecinos del threshold, cutoff explícito y
cero, las tres families de extents vacíos y factores manuales. También prueba
que el conteo representacional puede diferir del rango numérico y que
pseudoinversa y least-squares descartan el mismo prefijo.

Para condición cubre espectros controlados `[10,2,1]`, `[10,2,0]`, un único
valor diminuto, vacío, repetidos, cociente grande representable y overflow a
infinito, además de Matrix cero y rectangular full rank. Un oráculo host
independiente compara matrices no diagonales float32/float64 con
`numpy.linalg.cond(A, 2)`; NumPy/LAPACK no participa en el producto.

La qualification comprueba también cutoff inválido, guards de factors,
reutilización de entradas y herencia de `NonFiniteMatrixException`.

## Consumer e IR

El consumer público factoriza una Matrix, consulta rango y condición desde el
factor, imprime ambos valores, ejercita las rutas directas desde Matrix y
vuelve a usar `A` y el factor.

La instrumentación de allocations confirma que las rutas de factor no agregan
ninguna allocation. La inspección source y MIR/SSA/LLVM confirma que las rutas
de factor no ejecutan SVD, cada ruta Matrix contiene una única SVD,
`condition2` no recorre el espectro, y las instancias float32/float64 quedan
monomorfizadas sin `TypeId`, witnesses, vtables, LAPACK productivo, opcode de
rank/cond ni helper numérico de runtime.

## Validación

```text
aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_svd_rank_condition_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```
