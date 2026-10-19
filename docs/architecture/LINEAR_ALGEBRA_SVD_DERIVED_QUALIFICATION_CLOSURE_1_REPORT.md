# LINEAR-ALGEBRA-SVD-DERIVED-QUALIFICATION-CLOSURE-1 — reporte de cierre

Estado: **CLOSED**, 2026-10-19.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-CUTOFF-V1](LINEAR_ALGEBRA_SVD_CUTOFF_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-PSEUDOINVERSE-V1](LINEAR_ALGEBRA_SVD_PSEUDOINVERSE_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-LEAST-SQUARES-V1](LINEAR_ALGEBRA_SVD_LEAST_SQUARES_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-RANK-CONDITION-V1](LINEAR_ALGEBRA_SVD_RANK_CONDITION_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-LOW-RANK-V1](LINEAR_ALGEBRA_SVD_LOW_RANK_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1](LINEAR_ALGEBRA_SVD_QUALIFICATION_CLOSURE_1_REPORT.md).

## Resultado

La familia derivada completa de la SVD thin queda calificada conjuntamente
para `float32` y `float64`, en O0 y O2. No se detectó un bug productivo durante
el cierre. Este milestone no agrega API, no cambia algoritmos y no modifica
`linearAlgebra/src/lib.ae`; agrega solamente la qualification cruzada
`linear_algebra_svd_derived_qualification_closure_1.rs` y este reporte.

Las qualifications verticales continúan siendo autoridad sobre el detalle de
cada operación. La nueva suite demuestra las propiedades que sólo son
visibles al tratar cutoff, pseudoinversa, least-squares, rango, condición y
low-rank como una familia única.

## Cutoff y precedencia compartidos

Un factor diagonal controlado demuestra que `numericalRank`,
`pseudoInverse` y `leastSquares` observan el mismo prefijo. Con espectro
`[8,2,1e-20]` y cutoff `2`, el rango es uno y los dos outputs dense descartan
el valor exactamente igual al cutoff. Cutoff cero retiene los tres valores
almacenados no cero, mientras que el default descarta la dirección diminuta.

Los tres consumers lanzan `InvalidSingularValueCutoffException` para el mismo
cutoff inválido. En rutas Matrix, esa excepción precede al scan SVD incluso si
la Matrix contiene NaN. En rutas de factor y least-squares, la instrumentación
de traps confirma que los guards estructurales de factor o RHS preceden a la
validación del cutoff, según el orden normativo.

## Pseudoinversa y mínimos cuadrados

La qualification compara en las dos precisiones y desde Matrix y factor
precomputado:

```text
leastSquares(A,b) ~= pseudoInverse(A) * b
leastSquares(f,b) ~= pseudoInverse(f) * b
```

Un sistema wide con nullspace conocido verifica que la solución elegida tiene
norma menor que una perturbación no nula del nullspace y conserva el mismo
residual. Un sistema tall inconsistente verifica directamente `A^T(Ax-b) ~= 0`.
Las suites verticales mantienen además el corpus NumPy para square, tall,
wide, rank-deficient y RHS Matrix.

## Rank explícito, Eckart–Young y condición

`numericalRank(f)==2` para el factor controlado anterior, pero
`lowRankApproximation(f,3)` reconstruye los tres triplets, incluida la
dirección `1e-20`. Rank cero produce exactamente la Matrix cero y rank completo
reconstruye todo el factor thin. Por tanto low-rank no consulta rango numérico
ni cutoff.

El oráculo host independiente ejecuta `numpy.linalg.svd` sobre casos square,
tall y wide de ambas precisiones. Para el rank solicitado construye
`U[:,:k] * S[:k] @ Vt[:k,:]`; la aproximación Aether coincide dentro de las
tolerancias fijas de tipo. El error espectral coincide con el siguiente
singular value y el error Frobenius con la norma del tail. NumPy/LAPACK sólo se
ejecuta desde Rust test-only y no aparece en source o link productivo.

`condition2` usa el espectro completo: el mismo valor diminuto descartado por
`numericalRank` produce una condición finita grande. Un singular value mínimo
exactamente cero y los espectros vacíos producen `+Infinity`; un tiny no cero
de un espectro unitario produce condición uno. La inspección source confirma
que `condition2` no contiene cutoff, epsilon ni clasificación retenida.

## Reuse, rutas y recursos

Una única llamada pública a `svd(A)` alimenta consecutivamente
`pseudoInverse`, `leastSquares`, `numericalRank`, `condition2`,
`lowRankApproximation` y ambos errores low-rank. En O0 el IR contiene una sola
call a SVD; ningún overload de factor alcanza otra factorización. En O2 el
programa optimizado conserva los mismos resultados.

La ejecución instrumentada observa exactamente doce allocations y doce frees:
los owners de `A` y `b`, los siete backings ya contratados por la SVD pública y
los tres outputs dense. Las consultas escalares no agregan allocations y no
aparece un temporal dense oculto. Todos los inputs y el factor siguen siendo
utilizables después de cada consulta.

Otro consumer llama una vez a cada uno de los doce overloads desde Matrix. El
IR O0 contiene exactamente doce calls SVD, una por ruta, y ninguna segunda
factorización. Las bodies source delegan directamente desde cada ruta Matrix a
su ruta de factor.

## Shapes y factores manuales

La suite conjunta cubre square, tall, wide, rank-deficient y zero spectrum,
además de `m×0`, `0×n` y `0×0`. Pseudoinversa, least-squares y aproximación
low-rank conservan ambos extents lógicos aun cuando no existe backing.

Un factor manual estructuralmente válido y no canónico con shapes `3×2`, `2`
y `2×4` recorre toda la familia. Sus outputs preservan las shapes `4×3`, `4`
y `3×4`, y las consultas escalares usan literalmente el espectro almacenado.
Los factores y RHS permanecen intactos.

## IR y cierre de superficie

MIR, SSA y LLVM de las instancias conjuntas confirman:

- cero `GenericParam`, witnesses, vtables o `TypeId` residuales;
- cero LAPACK productivo y cero opcode especial para pseudoinversa,
  least-squares, rank, condición o low-rank;
- cero llamada a `pseudoInverse` dentro de least-squares y cero normal
  equations;
- cero clasificación de cutoff dentro de `condition2` y low-rank;
- kernels directos sobre shared borrows, sin `Sigma`, transpose owner,
  residual ni segundo factor.

No se agregó funcionalidad ni se alteraron los algoritmos cerrados por las
verticales.

## Validación ejecutada

```text
compiler-next/target/debug/aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_svd_derived_qualification_closure_1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

Todos los comandos terminan correctamente. La qualification específica
ejecuta siete tests, todos verdes. El differential informa 21 casos y cero
fallos. El workspace completo, incluidas las qualifications SVD verticales y
el consumer publicado de `linearAlgebra`, queda verde.
