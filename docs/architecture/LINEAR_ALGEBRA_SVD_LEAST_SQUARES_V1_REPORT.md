# LINEAR-ALGEBRA-SVD-LEAST-SQUARES-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-18.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1-REPORT](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-CUTOFF-V1](LINEAR_ALGEBRA_SVD_CUTOFF_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-PSEUDOINVERSE-V1](LINEAR_ALGEBRA_SVD_PSEUDOINVERSE_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md).

## Resultado y API

`linearAlgebra/src/lib.ae` incorpora exactamente los ocho overloads públicos
de `leastSquares`: RHS `Vector<T,Column>` y `Matrix<T>`, cada uno desde
`Matrix<T>` o desde `SVD<T>` precomputada, con variantes default y cutoff
absoluto explícito. No se modificó ningún overload de `solve`.

Para `A:m×n`, `b:m` y `B:m×q`, los resultados owning tienen respectivamente
shapes `n` y `n×q`. Las rutas aceptan matrices square, tall, wide y rank
deficient; en presencia de nullspace retornan la solución de norma mínima del
problema truncado definido por el prefijo retenido.

## Guards, precedencia y cutoff

Las rutas sobre factor comprueban primero, en orden, que
`columns(U)==dimension(S)` y `rows(Vt)==dimension(S)`, y después la
compatibilidad del RHS con `rows(U)`. Sólo entonces un overload explícito
valida el cutoff. Las rutas desde Matrix comprueban la compatibilidad del RHS
con `rows(A)` antes de validar cutoff y antes de ejecutar SVD.

La clasificación delega exclusivamente a los overloads privados existentes
de `retainedSingularValueCount`. No replica la fórmula default ni la
comparación explícita. Por ello comparte exactamente con `pseudoInverse` la
comparación estricta, el tratamiento de cero y la excepción
`InvalidSingularValueCutoffException`.

Cada ruta Matrix llama una vez a `svd(A)` y luego reutiliza la ruta del factor.
No traduce shape mismatch a una excepción numérica ni altera las excepciones
de input no finito o falta de convergencia producidas por SVD.

## Kernel Vector

El helper privado `leastSquaresVectorRetained` crea un único Vector cero de
dimensión `n` y fija el traversal `r/i/j`:

```text
for r in retained prefix:
    projection = 0
    for i in 1..m:
        projection = projection + U[i,r] * b[i]
    coefficient = projection / S[r]
    for j in 1..n:
        result[j] = result[j] + Vt[r,j] * coefficient
```

El árbol source usa acumulación en `T`, sin promoted accumulator, FMA o
reassociation contractuales. Su coste es `O(r*(m+n))`, donde `r` es el número
de singular values retenidos.

## Kernel Matrix

`leastSquaresMatrixRetained` crea una única Matrix cero `n×q` y fija el
traversal `c/r/i/j`. Proyecta cada columna directamente sobre una columna de
`U`, divide una vez por triplet y acumula con la fila correspondiente de
`Vt`. Su coste es `O(r*q*(m+n))`.

Ningún kernel construye pseudoinversa, `V`, `U^T`, `Sigma+`, `U^T B`, Vector
de projections, outputs Vector por columna ni owner por triplet. Tampoco forma
normal equations ni usa QR o LAPACK.

## Ownership, allocations y casos degenerados

Todos los inputs son shared y siguen utilizables. Una ruta de factor Vector
asigna exactamente el output cuando `n>0`; una ruta de factor Matrix asigna
exactamente el output cuando `n*q>0`. No hay owners numéricos auxiliares y los
resultados no aliasan inputs. Las rutas Matrix agregan sólo las allocations de
la SVD y su output.

Los casos `m×0`, `0×n`, `q==0` y factor con `p==0` conservan sus extents
lógicos y retornan outputs vacíos o cero según corresponda. Los guards siguen
ejecutándose. Rank deficiency y un prefijo retenido vacío son casos normales,
no excepciones.

## Qualification, oráculo y minimum norm

`linear_algebra_svd_least_squares_v1.rs` ejecuta float32/float64 en O0/O2 y
cubre square, tall, wide, sistemas consistentes e inconsistentes, rank
deficiency, singular values repetidos, cutoff default, explícito y cero,
direcciones diminutas, shapes vacías y aritmética IEEE extrema.

El oráculo independiente usa `numpy.linalg.lstsq` sólo en el host de tests. El
default reproduce `max(m,n)*finfo(dtype).eps`; un cutoff absoluto se convierte
a `rcond` mediante el mayor singular value del oráculo, con caso explícito
para espectro vacío o `sigmaMax==0`.

La qualification comprueba residual y condiciones normales, norma mínima
frente a perturbaciones conocidas del nullspace, equivalencia de cada columna
del RHS Matrix con la ruta Vector y la propiedad cruzada
`leastSquares(A,b) ≈ pseudoInverse(A)*b`. Esta última sólo aparece en tests;
el kernel productivo no llama a `pseudoInverse`.

## Reutilización e IR

La instrumentación usa un único factor para dos RHS Vector y un RHS Matrix,
confirma cero SVD adicionales y observa únicamente las allocations de los
outputs. Para rutas Matrix confirma un único call source a SVD. MIR/SSA/LLVM
confirman monomorfización float32/float64, loops ordinarios y ausencia de
generic residue, witnesses, vtables, `TypeId`, LAPACK, opcode least-squares,
normal-equation kernel y llamada a pseudoinversa desde los kernels.

El consumer público demuestra la ruta desde factor, la ruta directa y un RHS
Matrix, y vuelve a usar `A`, factor y RHS después de las llamadas.

## Validación

```text
compiler-next/target/debug/aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_svd_least_squares_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```
