# LINEAR-ALGEBRA-V1-SURFACE-CLOSURE-1 — reporte de auditoría

Estado: **CLOSED / V1 COMPLETE**, 2026-10-19.

Decisión normativa:
[LINEAR_ALGEBRA_V1_SURFACE_CLOSURE_1](LINEAR_ALGEBRA_V1_SURFACE_CLOSURE_1.md).

## 1. Método y notación

Se inspeccionó la totalidad de `linearAlgebra/src/lib.ae`, no sólo reportes
históricos. El inventario incluye cada declaración `public`, sus overloads,
fields de aggregates, guards, owners creados y entry points deprecated. Se
contrastó con el package sintético vigente `std.Math.LinearAlgebra`, la tabla
de producto matemático del core y las qualifications verticales existentes.

Notación usada en las tablas:

- `A:m×n`, `k=min(m,n)`, `B:m×q` y `rank=r`;
- “preserving” significa préstamo shared: el input no se mueve ni se escribe;
- “consuming/InPlace” significa que el owner entra por valor, se mueve y su
  backing puede ser workspace; no implica mutación observable de un owner que
  siga en poder del caller;
- los conteos se refieren a backings numéricos. Un owner con cero celdas
  conserva shape pero no asigna backing;
- salvo constructores y el wrapper indicado, todos los algoritmos numéricos
  públicos exigen `T: IEEEFloat`, actualmente satisfecho por `float32` y
  `float64`.

`shapeGuard` termina en el trap core `ShapeMismatch`. No es una octava clase
de excepción declarada por la OAL ni un failure capturable equivalente a las
siete excepciones nominales.

## 2. Helpers y constructores públicos

| API | Propósito y shapes | Ownership / allocations | Complejidad y tipos | Relación con std/core |
|---|---|---|---|---|
| `zeros<T>(size) -> Matrix<T>` | Matrix square `size×size` en cero. | Crea un owner; un backing si `size²>0`. | `O(size²)`; `Storable+Copy+Zero`. | Convenience OAL sobre `matrixFilled`; no existe alias std. |
| `zeros<T>(rows,columns) -> Matrix<T>` | Matrix `rows×columns` en cero. | Crea un owner; un backing si el producto es no cero. | `O(rows*columns)`; `Storable+Copy+Zero`. | Igual. |
| `zeros<T>(length) -> Vector<T,Row>` | Row de longitud `length`. El expected result selecciona orientación. | Un owner/backing si no vacío. | `O(length)`; `Storable+Copy+Zero`. | Convenience OAL sobre `vectorFilled`. |
| `zeros<T>(length) -> Vector<T,Column>` | Column de longitud `length`. | Igual. | Igual. | Igual. |
| Los cuatro overloads `ones` | Mismas shapes que `zeros`, relleno con uno. | Un owner/backing no vacío. | Lineal en celdas; `Storable+Copy+One`. | Convenience OAL; no alias std. |
| `identity<T>(size) -> Matrix<T>` | Identidad owning `size×size`. | Un owner/backing no vacío; zero-fill y stores diagonales. | `O(size²)`; `Storable+Copy+Zero+One`. | Ya cubre identidad. No se mueve durante este cierre. |

Helpers como `copyMatrixForFactorization`, norma escalada, reducers bidiagonal
y tridiagonal, Givens, cutoff y materializadores son privados. No forman una
API implícita y no se congelan como superficie pública.

## 3. LU, determinant y solve LU

```aether
public struct LU<T: Storable> {
    Vector<usize,Column> permutation;
    int permutationSign;
    Matrix<T> L;
    Matrix<T> U;
}
```

Para `A:m×n` y `k=min(m,n)`, `permutation:m`, `L:m×k` y `U:k×n` satisfacen
`P*A ~= L*U`, con `(P*A)[i,j]=A[permutation[i],j]`. La permutación es 1-based;
no se materializa `P`. LU usa pivoting parcial con test de pivot exactamente
cero.

| API | Dominio / resultado | Preserving o mutating; allocations | Complejidad | std |
|---|---|---|---|---|
| `lu(ref A)` | Rectangular; devuelve LU económica. | Preserva `A`. Los tres owners visibles son permutation/L/U; la copia de `A` pasa a ser L o U y se crean los otros dos backings no vacíos. | `O(m*n*k)`; storage visible `O(mk+kn+m)`. | Descomposición OAL, sin contraparte std actual. |
| `luInPlace(A)` | Mismo contrato. | Consume `A`; reutiliza su backing como U si `m<=n`, como L si `m>n`; crea permutation y el factor `k×k`. | Igual; `O(1)` workspace escalar aparte de resultados. | Sin contraparte std. |
| `det(ref LU)` | Factor square coherente de orden `n`; signo por permutation y producto de diagonal U. | Preserva factor; cero owners/allocations numéricos. | `O(n)`. | Consulta OAL. |
| `det(ref Matrix)` | `A:n×n`; factoriza una vez con LU. | Preserva `A`; factors temporales y ningún owner de salida. | `O(n³)`. | OAL. |
| `detInPlace(Matrix)` | Igual. | Consume `A`, lo usa en LU temporal. | `O(n³)`; evita la copia preserving. | OAL. |
| `solve(ref LU, ref Column b)` | Factor orden `n`, `b:n`; devuelve `x:n`. | Preserva factor y `b`; un Vector resultado. | `O(n²)`. | Solver OAL. |
| `solve(ref Matrix A, ref Column b)` | `A:n×n`, `b:n`; una LU y solución `n`. | Preserva ambos; allocations de LU temporal más Vector resultado. | `O(n³+n²)`. | Solver OAL default. |
| `solveInPlace(Matrix A, ref Column b)` | Igual. | Consume sólo `A`; preserva `b`; reutiliza backing vía LU y crea resultado. | Igual, sin copia de `A`. | OAL. |
| `solve(ref LU, ref Matrix B)` | Factor orden `n`, `B:n×q`; devuelve `X:n×q`. | Preserva inputs; una Matrix resultado. | `O(n+n²q)`, y `O(n²q)` para `q>0`. | OAL. |
| `solve(ref Matrix A, ref Matrix B)` | `A:n×n`, `B:n×q`. | Preserva ambos; LU temporal y una Matrix resultado. | `O(n³+n²q)`. | OAL. |
| `solveInPlace(Matrix A, ref Matrix B)` | Igual. | Consume sólo `A`; preserva `B`. | Igual, sin copia preserving. | OAL. |

Los solve LU rechazan un pivot diagonal U exactamente cero con
`SingularMatrixException`. No aplican tolerancia de rango.

## 4. Cholesky

```aether
public struct Cholesky<T: Storable> { Matrix<T> L; }
```

El dominio es `A:n×n`, finita, exactamente simétrica y positive definite;
`A=L*L^T`, con `L:n×n` lower y diagonal positiva.

| API | Propósito / shapes | Ownership / allocations | Complejidad | std |
|---|---|---|---|---|
| `cholesky(ref A)` | Factor SPD. | Preserva `A`; una copia `n×n` que se convierte en el único owner visible L. | `O(n³)`, peak adicional `n²`. | Descomposición OAL. |
| `choleskyInPlace(A)` | Mismo resultado. | Consume A y reutiliza su backing; cero owners numéricos auxiliares. | `O(n³)`, `O(1)` escalar auxiliar. | OAL. |
| `det(ref Cholesky)` | Producto de diagonal de L y cuadrado. | Preserva factor; cero allocations. | `O(n)`. | Consulta OAL. |
| `solve(ref Cholesky, ref Column b)` | `b:n`; forward/back substitution, `x:n`. | Preserva inputs; un Vector resultado. | `O(n²)`. | Solver especializado OAL. |
| `solve(ref Cholesky, ref Matrix B)` | `B:n×q`; devuelve `X:n×q`. | Preserva inputs; una Matrix resultado. | `O(n²q)`. | OAL. |

No hay overload directo `solve(A,b)` que seleccione Cholesky: factorizar de
forma explícita expresa la precondición SPD y permite reutilización. No es un
hueco V1.

## 5. QR y solve QR

```aether
public struct QR<T: Storable> { Matrix<T> Q; Matrix<T> R; }
```

Para `A:m×n`, la factorización Householder materializa `Q:m×m` y `R:m×n`, con
`A ~= Q*R`. No hace pivoting ni rechaza rank deficiency al factorizar.

| API | Propósito / shapes | Ownership / allocations | Complejidad | std |
|---|---|---|---|---|
| `qr(ref A)` | QR rectangular completa. | Preserva `A`; copia `m×n` que se vuelve R y crea Q `m×m`. | `O(m*k*(m+n))`, `k=min(m,n)`; storage visible `m²+mn`. | Descomposición OAL. |
| `qrInPlace(A)` | Igual. | Consume A, reutiliza backing como R y crea sólo Q. | Igual. | OAL. |
| `qrFloat32(Matrix<float32> A)` | Wrapper deprecated de compatibilidad. | Consume A y delega a `qrInPlace`; no agrega allocation. | Igual; sólo `float32`. | No debe generar nuevos wrappers por precisión. |
| `solve(ref QR, ref Column b)` | Requiere `Q:m×m`, `R:m×n`, `m>=n`, `b:m` y diagonal R no cero; devuelve `x:n`. | Preserva inputs; un Vector resultado. | `O(n + mn + n²)`. | Solver OAL. |
| `solve(ref QR, ref Matrix B)` | `B:m×q`; devuelve `X:n×q`. | Preserva inputs; una Matrix resultado. | `O(n + mnq+n²q)`. | Solver OAL. |

El solve QR produce la solución square o least-squares única tall para un
factor full-column-rank. Wide falla por shape y diagonal exactamente cero lanza
`RankDeficientMatrixException`. Minimum-norm wide/rank-deficient ya está
cubierto por la familia SVD.

## 6. Thin SVD y política de cutoff

```aether
public struct SVD<T: Storable> {
    Matrix<T> U;
    Vector<T,Column> S;
    Matrix<T> Vt;
}
```

Para `A:m×n`, `k=min(m,n)`: `U:m×k`, `S:k` no negativa y descendente,
`Vt:k×n`. La entrada debe ser finita. La SVD pública es siempre preserving.

| API | Propósito / shapes | Ownership / allocations | Complejidad | std |
|---|---|---|---|---|
| `svd(ref A)` | Thin SVD rectangular. | Preserva A. Ruta general: workspace `m×n`, U, Vt, S/d, e, tauLeft y tauRight: hasta siete backings; sólo U/S/Vt escapan. | Objetivo dense `O(m*n*k)` más iteración bidiagonal acotada; storage peak `O(mn+mk+kn+k)`. | Descomposición OAL. |
| `nonzeroSingularValueCount(ref SVD)` | Cuenta valores almacenados `!=0`, sin cutoff numérico. | Preserva factor; cero allocations. | `O(k)`. | Consulta OAL. |

La política default compartida por pseudoinversa, least-squares y rango retiene
el prefijo con `S[i]>0` y `S[i]/S[1] > max(m,n)*epsilon<T>()`. La política
explícita retiene `S[i] > cutoff`. Cutoff negativo, NaN o infinito lanza
`InvalidSingularValueCutoffException`.

## 7. Pseudoinversa y least-squares

| API | Propósito / shapes | Ownership / allocations | Complejidad | std |
|---|---|---|---|---|
| `pseudoInverse(ref SVD factor)` | Devuelve `A+:n×m` con cutoff default. | Preserva factor; exactamente una Matrix resultado no vacía, sin `Sigma`, transposes ni vectors temporales. | `O(n*m*r)`, `r` retenidos. | Derivada OAL. |
| `pseudoInverse(ref SVD factor, cutoff)` | Igual, cutoff absoluto explícito. | Igual. | Igual. | OAL. |
| `pseudoInverse(ref Matrix A)` | Factoriza una vez y devuelve `n×m`. | Preserva A; SVD temporal más resultado. | coste SVD + `O(n*m*r)`. | OAL. |
| `pseudoInverse(ref Matrix A, cutoff)` | Igual con cutoff validado antes de SVD. | Igual. | Igual. | OAL. |
| `leastSquares(ref SVD, ref Column b)` | `b:m`; solución minimum-norm `x:n`, cutoff default. | Preserva inputs; un Vector resultado, sin pseudoinversa materializada. | `O(r*(m+n))`. | Derivada OAL. |
| `leastSquares(ref SVD, ref Column b, cutoff)` | Igual con cutoff explícito. | Igual. | Igual. | OAL. |
| `leastSquares(ref Matrix A, ref Column b)` | Factoriza A una vez; `b:m`, `x:n`. | Preserva inputs; SVD temporal y resultado. | coste SVD + `O(r*(m+n))`. | OAL. |
| `leastSquares(ref Matrix A, ref Column b, cutoff)` | Igual con cutoff. | Igual. | Igual. | OAL. |
| `leastSquares(ref SVD, ref Matrix B)` | `B:m×q`; devuelve `X:n×q`, cutoff default. | Preserva inputs; una Matrix resultado. | `O(r*q*(m+n))`. | OAL. |
| `leastSquares(ref SVD, ref Matrix B, cutoff)` | Igual con cutoff. | Igual. | Igual. | OAL. |
| `leastSquares(ref Matrix A, ref Matrix B)` | Factoriza una vez; devuelve `n×q`. | Preserva inputs; SVD temporal y resultado. | coste SVD + `O(r*q*(m+n))`. | OAL. |
| `leastSquares(ref Matrix A, ref Matrix B, cutoff)` | Igual con cutoff. | Igual. | Igual. | OAL. |

Estas rutas cubren square, tall, wide y rank-deficient. El resultado es el de
norma mínima bajo el prefijo singular retenido; no forma ecuaciones normales.

## 8. Rango, condición y low-rank

| API | Propósito / shapes | Ownership / allocations | Complejidad | std |
|---|---|---|---|---|
| `numericalRank(ref SVD)` | Número de valores retenidos por cutoff default. | Preserva; cero allocations. | `O(k)`. | Consulta OAL. |
| `numericalRank(ref SVD, cutoff)` | Rango con cutoff absoluto. | Preserva; cero allocations. | `O(k)`. | OAL. |
| `numericalRank(ref Matrix A)` | SVD única y consulta. | Preserva A; SVD temporal. | coste SVD + `O(k)`. | OAL. |
| `numericalRank(ref Matrix A, cutoff)` | Igual, validando cutoff antes de SVD. | Igual. | Igual. | OAL. |
| `condition2(ref SVD)` | `S[1]/S[k]` sobre espectro completo; `+Inf` si vacío o mínimo exactamente cero. | Preserva; cero allocations. | `O(1)` tras guards. | Consulta OAL. |
| `condition2(ref Matrix A)` | SVD única y condición. | Preserva A; SVD temporal. | coste SVD + `O(1)`. | OAL. |
| `lowRankApproximation(ref SVD, rank)` | Reconstruye prefijo literal, Matrix `m×n`; exige `rank<=k`. | Preserva; una Matrix resultado, sin factores truncados/Sigma. | `O(m*n*rank)`. | Derivada OAL. |
| `lowRankApproximation(ref Matrix A, rank)` | SVD única y reconstrucción. | Preserva A; SVD temporal más resultado. | coste SVD + `O(m*n*rank)`. | OAL. |
| `lowRankSpectralError(ref SVD, rank)` | Error Eckart–Young `S[rank+1]`, o cero en rank completo. | Preserva; cero allocations. | `O(1)`. | OAL. |
| `lowRankSpectralError(ref Matrix A, rank)` | SVD única y consulta. | Preserva A; SVD temporal. | coste SVD + `O(1)`. | OAL. |
| `lowRankFrobeniusError(ref SVD, rank)` | Norma escalada del tail singular. | Preserva; cero allocations. | `O(k-rank)`. | OAL; no equivale a una Frobenius pública general. |
| `lowRankFrobeniusError(ref Matrix A, rank)` | SVD única y consulta. | Preserva A; SVD temporal. | coste SVD + `O(k-rank)`. | OAL. |

Low-rank usa el rank literal solicitado y no consulta el cutoff de rango
numérico. `condition2` tampoco aplica ese cutoff.

## 9. Eigen real simétrico

```aether
public struct SymmetricEigen<T: Storable> {
    Vector<T,Column> values;
    Matrix<T> vectors;
}
```

| API | Propósito / shapes | Ownership / allocations | Complejidad | std |
|---|---|---|---|---|
| `symmetricEigen(ref Matrix A)` | `A:n×n`, finita y exactamente simétrica. Devuelve `values:n` ascendentes y `vectors:n×n`, con eigenvectors en columnas correlacionadas. | Preserva A. Ruta general `n>=3`: seis backings internos (`workspace`, values, e, tau, work, vectors), de los cuales values/vectors escapan; ruta diagonal usa dos; `0×0`, ninguno. | `O(n³)`, storage peak `2n²+O(n)`. | Descomposición OAL. |

La ruta general normaliza por escala, reduce a tridiagonal con Householder,
aplica QR implícito, reescala y ordena pares. No usa SVD, characteristic
polynomial, Matrix diagonal ni transpose owner.

## 10. Excepciones públicas

| Excepción | La producen | Condición observable | Relación con std |
|---|---|---|---|
| `SingularMatrixException` | solve desde LU/Matrix-LU | Diagonal U exactamente `+0` o `-0` durante backward substitution. | Nominal OAL. |
| `NotSymmetricMatrixException` | Cholesky; symmetric eigen | Par finito off-diagonal distinto bajo simetría exacta. | Nominal OAL compartida. |
| `NotPositiveDefiniteException` | Cholesky | Input no finito en su validación o pivot calculado no finito/no positivo. | Nominal OAL. |
| `NonFiniteMatrixException` | SVD; symmetric eigen | NaN o infinito en la entrada durante el scan público. | Nominal OAL compartida. |
| `NumericalConvergenceException` | SVD; symmetric eigen | Estado interno no finito, presupuesto agotado o resultado no finito. | Nominal OAL compartida. |
| `InvalidSingularValueCutoffException` | pseudoinversa, least-squares, rango con cutoff | Cutoff negativo, NaN o infinito. | Nominal OAL. |
| `RankDeficientMatrixException` | solve QR | Algún `R[i,i]` es exactamente cero. | Nominal OAL. |

Todas son clases públicas sin payload. Las precedencias detalladas siguen los
guards de cada ruta: shape precede allocation; SVD/symmetric eigen separan
input no finito de fallo de convergencia; las rutas Matrix con cutoff explícito
lo validan antes de factorizar cuando sus guards externos ya pasaron.

## 11. Relación efectiva con core y `std.Math.LinearAlgebra`

La composición V1 disponible es:

| Necesidad | Autoridad actual | Coste / ownership |
|---|---|---|
| Filled constructors | core `matrixFilled<T>(m,n,value)` y `vectorFilled<T,O>(k,value)` | Un owner/backing no vacío; lineal en las celdas. Son la base de `zeros`/`ones`. |
| Shape queries | core `rows`, `columns`, `dimension` | `O(1)`, cero allocation. |
| Vista normal y ejes | core `matrix_view[_mut]`, `vector_view[_mut]`, `row[_mut]`, `column[_mut]` | Descriptores borrowed O(1), cero allocation; Row/Column se preserva. |
| Row·Column | core `Row * Column` | `O(k)`, cero allocation. |
| Outer | core `Column * Row` | `O(mn)`, un owner Matrix no vacío. |
| Matrix×Column / Row×Matrix | core `*` | Inputs borrowed, un Vector owning de salida. |
| Matrix×Matrix | core `*` | Inputs borrowed, un Matrix owning de salida. |
| Transpose shared/mutable | core `transpose_view[_mut]` | `O(1)`, cero allocation, backing compartido. |
| Transpose Vector owning | core `transpose(Vector)` | Consume owner, cambia orientación, sin copiar backing. |
| Transpose Matrix owning | std `transposeCopy` | Preserving, `O(mn)`, un owner. |
| Vector→Matrix diagonal | std `diagonalMatrix(Row/Column)` | Preserving, `O(k²)`, un owner dense. |
| Identity | OAL `identity` | `O(n²)`, un owner. |

Por tanto QR, SVD y symmetric eigen pueden reconstruirse y verificarse sin
aliases nuevos. No existe una función native `dot`, `outer` o `matmul`, pero la
operación no falta: el operador tipado es la API canónica.

Los faltantes reales de primitive nombrada son norma vectorial estable, norma
Frobenius general y `trace`. Conforme al límite ya usado por
`transposeCopy`/`diagonalMatrix`, pertenecen a futuros verticales de std. No
dependen de una descomposición, no requieren privilegio de compiler y su
ausencia no impide ninguna operación pública de la OAL.

El módulo Python legacy registra además `inner`, `norm`, `transpose`,
`conjtranspose`, `matmul`, `solve`, `eig`, `SVD`, `LU`, `LDU`, `zeros`, `ones`,
`eye`, `N`, `R` y `rank`. Esos nombres operan sobre el modelo/runtime legacy y
varios delegan a NumPy/SciPy; no son declaraciones del package source canónico
de `compiler-next`, no se importan al consumir la OAL y no convierten una
colisión de spelling en equivalencia de contrato. Este cierre evita tanto
contarlos como superficie nativa como intentar hacerlos coincidir mediante
aliases OAL.

## 12. Huecos y no-huecos V1

Resultado de la auditoría:

- **Huecos OAL V1 bloqueantes: ninguno.**
- **Follow-ups std no bloqueantes:** norma euclídea estable de Row/Column,
  Frobenius estable y `trace`.
- **Ya resuelto por core/std:** dot, outer, Matrix/Vector/Matrix multiplication,
  transpose view/owning y construcción diagonal.
- **Ya resuelto históricamente en OAL:** identity owning.
- **V2/fuera de scope:** catálogo adicional de normas, extracción diagonal y
  predicates estructurales/tolerantes.

No se considera hueco la ausencia de full SVD, inverse nominal, P materializada,
Sigma materializada, solve automático por método, factores implícitos ni
overloads duplicados. La superficie existente permite esas composiciones o
evita deliberadamente una política oculta.

## 13. Scope V2 congelado

Este cierre separa expresamente:

- general real eigen / Schur;
- complex eigen;
- generalized eigenproblem;
- sparse matrices;
- iterative Krylov solvers;
- randomized SVD;
- BLAS/LAPACK backend;
- SIMD/GPU kernels;
- distributed algebra.

Ninguno es condición de completitud para una primera superficie dense real.

## 14. Conclusión

La superficie pública efectiva cubre las cinco factorizaciones/eigensistemas
seleccionados, cuatro dominios de solve, la familia SVD derivada completa,
constructores mínimos, ownership explícito y failures nominales. Los huecos
fundamentales restantes están correctamente fuera de la OAL y no justifican
seguir expandiéndola antes de trabajar en otras OALs.

**LINEAR-ALGEBRA-V1 COMPLETE**

Estado final: **CLOSED / V1 COMPLETE**.

Este cierre es exclusivamente documental: no modifica source productivo,
tests, compiler, runtime ni manifests.
