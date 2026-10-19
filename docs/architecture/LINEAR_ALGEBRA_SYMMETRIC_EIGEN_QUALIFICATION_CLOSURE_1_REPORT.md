# LINEAR-ALGEBRA-SYMMETRIC-EIGEN-QUALIFICATION-CLOSURE-1 — reporte de cierre

Estado: **CLOSED**, 2026-10-19.

Autoridad normativa:

- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_V1_REPORT.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_QR_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_QR_V1_REPORT.md);
- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ASSEMBLY-V1](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ASSEMBLY_V1_REPORT.md).

## Resultado

La eigendecomposition real simétrica pública queda calificada conjuntamente
para `float32` y `float64`, en O0 y O2. No apareció un bug productivo. Este
cierre no modifica `linearAlgebra/src/lib.ae`, no agrega API y no cambia
algoritmos, thresholds, budgets ni contratos de ownership.

Se agregó exclusivamente la qualification cross-property
`compiler-next/crates/aether-driver/tests/linear_algebra_symmetric_eigen_qualification_closure_1.rs`.
Complementa los verticales con una batería end-to-end más amplia, escala
subnormal no diagonal y una prueba explícita de independencia entre dos
resultados. Los hooks privados siguen perteneciendo a las qualifications V1;
el cierre nuevo usa sólo la API pública y análisis source/IR.

## Composición y matemática

La ruta general observada conserva la composición cerrada:

```text
A finita y exactamente simétrica
  -> copia lower y normalización por max(abs(A))
  -> reducción Householder simétrica compacta
  -> materialización de Qh
  -> QR implícito shifted sobre d/e
  -> rescale
  -> selection sort de pares (value, column)
```

No hay una conversión de contrato entre fases: la reducción entrega `d/e` y
columnas de `Qh`; QR actualiza esos mismos owners por similaridad y deja `e`
en cero; assembly reescala únicamente `d` y permuta cada columna junto con su
valor. Para todo fixture se comprobaron, con acumulación host normalizada:

```text
A*Q ~= Q*diag(values)
Q^T*Q ~= I
Q*diag(values)*Q^T ~= A
values[i] <= values[i+1]
```

Residual y reconstrucción califican además la correspondencia entre cada
valor y la columna del mismo índice. Los bounds son de qualification, no una
tolerancia productiva:

```text
8192*n*epsilon(T) + 16*leastSubnormal(T)/scale(A)
```

La segunda suma sólo modela la cuantización inevitable del fixture cuando la
escala completa es subnormal. Todos los productos se forman con `A/scale` y
`values/scale`; así la prueba sigue siendo significativa sin desbordar ni
convertir el residual subnormal en cero antes de medirlo.

## Espectros, shapes y escala

La batería conjunta cubre:

- spectrum simple dense `6x6`;
- valores repetidos y un cluster conocido;
- positive definite, semidefinite, singular, indefinite y zero;
- `0x0`, `1x1`, diagonal desordenada, dense y tres split blocks;
- escala uniforme large, small y subnormal, para ambos tipos.

Los casos con spectrum repetido o clustered no comparan eigenvectors
individuales. Comparan los projectors del subespacio completo contra NumPy y,
además, residual, ortogonalidad y reconstrucción. No se exige signo ni base
canónica. El caso diagonal desordenado y todos los casos generales fijan el
ordering ascendente y la permutación correlacionada de columnas.

La qualification assembly conserva además identidad, signed zero, escalas
uniformes extremas adicionales y failure de rescale. La qualification QR
conserva los casos dirigidos de deflation, splitting, Wilkinson shift,
clusters, multiplicidades y subnormales internos.

## Errores y convergencia

La precedencia observable queda cerrada así:

1. non-square llega a `ShapeMismatch` antes de cualquier scan o allocation;
2. NaN o infinito en cualquier posición produce
   `NonFiniteMatrixException`, incluso si también hay asimetría;
3. una Matrix finita que no es exactamente simétrica produce
   `NotSymmetricMatrixException`;
4. failure interno, estado no finito o cap agotado produce
   `NumericalConvergenceException`.

El cierre público vuelve a ejecutar NaN, infinito y asimetría exacta en O0 y
O2 y comprueba que los inputs siguen usables después de la captura. Assembly
conserva non-square y overflow de rescale. El vertical QR conserva estado
activo con cap cero, cap mínimo, budget compartido entre splits y no finitos
producidos internamente. No hay traducción a otra clase de error.

## Recursos y preservation

Los verticales instrumentados fijan los budgets exactos:

```text
ruta general n>=3 : 6 owners/backings internos
                    workspace, values/d, e, tau, work, vectors
ruta diagonal     : 2 owners/backings internos (values, vectors)
ruta 0x0          : 0 backings
fase QR            : 0 allocations y 0 frees adicionales
```

Al contar la Matrix literal del consumer, assembly observa `7`, `3` y `0`
allocations/frees respectivamente. No hay Matrix tridiagonal, Householder,
Givens o diagonal owning, transpose owning, Vector de columna temporal, lista
de bloques ni historial de rotaciones.

La qualification nueva calcula dos decompositions desde el mismo `A`, muta
los fields del primer resultado y comprueba que ni el segundo resultado ni
`A` cambian. Esto cierra conjuntamente preservación y backings independientes;
los verticales mantienen los conteos exactos y cleanup de failure.

## Oráculo independiente

El host entrega los mismos valores ya redondeados al dtype concreto a Aether
y NumPy. Ejecuta por separado `numpy.linalg.eigvalsh` y
`numpy.linalg.eigh`, exige acuerdo numérico entre ambos y usa el primero para
los eigenvalues y el segundo sólo para projectors conocidos. NumPy/LAPACK es
test-only: no aparece en source Aether, LLVM ni el ejecutable productivo.

No se exige igualdad bitwise entre `eigvalsh` y `eigh`, porque son rutas de
oráculo independientes y pueden redondear de modo distinto. Tampoco se
comparan columnas individuales, aun para spectra simples; los invariantes
matemáticos son la autoridad sobre los eigenvectors.

## Source, IR y regresión

Los scans source y MIR/SSA/LLVM confirman:

- una única API `SymmetricEigen`/`symmetricEigen`, sin nueva superficie;
- ausencia de characteristic polynomial, dense QR iterativo y SVD como
  eigensolver;
- ausencia productiva de LAPACK/BLAS, eigen opcode, Matrix intrinsic o helper
  runtime especial;
- instancias concretas `float32`/`float64` de assembly, reducción y QR;
- ausencia post-monomorfización de `GenericParam`, witness, vtable y `TypeId`;
- selección ascendente y swap correlacionado sin Vector temporal.

`cargo test --workspace` cubre y dejó verdes symmetric tridiagonal V1,
symmetric tridiagonal QR V1, assembly y cierre conjunto; SVD y su derived
closure; QR, LU y Cholesky; y Matrix representation. El differential terminó
con `checked=21 failures=0`.

## Validación ejecutada

```text
cargo test -p aether-driver --test linear_algebra_symmetric_eigen_qualification_closure_1
cargo test -p aether-driver \
  --test linear_algebra_symmetric_tridiagonal_v1 \
  --test linear_algebra_symmetric_tridiagonal_qr_v1 \
  --test linear_algebra_symmetric_eigen_assembly_v1 \
  --test linear_algebra_symmetric_eigen_qualification_closure_1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
aether check linearAlgebra
git diff --check
```

Todos los comandos terminaron correctamente. No se agregó funcionalidad.

**CLOSED**
