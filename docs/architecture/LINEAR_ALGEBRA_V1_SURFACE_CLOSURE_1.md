# LINEAR-ALGEBRA-V1-SURFACE-CLOSURE-1 — criterio de cierre

Estado: **ARQUITECTURA CERRADA; SÓLO DOCUMENTACIÓN**, 2026-10-19.

Este documento decide cuándo la superficie pública del package OAL
`linearAlgebra` puede congelarse funcionalmente como V1. No diseña un catálogo
enciclopédico de álgebra lineal y no autoriza cambios de source, movimientos de
API ni aliases entre packages.

La auditoría que aplica este criterio está en
[LINEAR_ALGEBRA_V1_SURFACE_CLOSURE_1_REPORT](LINEAR_ALGEBRA_V1_SURFACE_CLOSURE_1_REPORT.md).

## 1. Alcance y autoridades

La autoridad primaria es la superficie `public` efectiva de
`linearAlgebra/src/lib.ae` en `83059f1f`. Los reportes verticales existentes
explican sus contratos y qualifications, pero una firma histórica sustituida
no prevalece sobre el source actual.

La comparación de capas usa tres autoridades distintas:

- el core del lenguaje posee `Vector`/`Matrix`, orientación Row/Column, views,
  transpose views, shape queries y la tabla algebraica nativa de `*`;
- el package canónico actual `std.Math.LinearAlgebra` posee
  `transposeCopy` y los dos overloads de `diagonalMatrix`;
- la OAL `linearAlgebra` posee constructores de conveniencia y algoritmos
  densos de factorización, resolución y análisis espectral.

`src/aether/stdlib/math/linear_algebra.py` pertenece al frontend/runtime Python
legacy y contiene nombres históricos adicionales. No define la superficie del
package toolchain que consume `compiler-next` y no se usa para declarar
presente una API V1 nativa.

## 2. Qué significa completar V1

`LINEAR-ALGEBRA-V1 COMPLETE` significa que un consumer de matrices densas
reales de precisión IEEE puede:

1. construir owners básicos y componerlos con las operaciones algebraicas del
   core;
2. factorizar mediante LU, Cholesky, QR, thin SVD y eigendecomposition real
   simétrica;
3. resolver sistemas square, SPD y tall full-column-rank desde factores, y
   resolver mínimos cuadrados/minimum-norm generales mediante SVD;
4. calcular determinant, pseudoinversa, rango numérico, condición 2 y
   aproximaciones low-rank sin materializaciones intermedias obligatorias;
5. elegir de manera visible entre entrada preserving y las variantes
   `InPlace` que realmente ofrece la superficie;
6. observar shapes, ownership, tipo escalar y failures nominales estables;
7. reconstruir y combinar resultados con `*`, transpose views,
   `transposeCopy` y `diagonalMatrix` sin que la OAL duplique primitives del
   core o de std.

No significa que toda rutina convencional de LAPACK, todo convenience wrapper
ni toda política numérica tenga que existir.

## 3. Gates explícitos de cierre

La declaración `LINEAR-ALGEBRA-V1 COMPLETE` requiere simultáneamente:

| Gate | Condición |
|---|---|
| Superficie | Todas las declaraciones `public` están inventariadas por familia, incluidas overloads legacy y excepciones. |
| Shapes | Cada familia fija shapes de entrada/salida, incluidos zero extents y restricciones square/tall/symmetric. |
| Ownership | Cada parámetro owning/shared y cada variante `InPlace` tiene semántica no ambigua; no existe mutación escondida de un préstamo shared. |
| Recursos | Allocations visibles y complejidad asintótica están documentadas por ruta. |
| Tipos | Los algoritmos numéricos tienen una frontera coherente `T: IEEEFloat`; los constructores conservan sus capabilities más generales. |
| Composición | Producto, transpose y diagonal necesarios para consumir factores están disponibles en core/std o se identifica un blocker concreto. |
| Fallos | Las siete excepciones nominales OAL y el trap de shape se distinguen y tienen causa observable. |
| Cobertura densa | LU, Cholesky, QR, solve, thin SVD, pseudoinversa, least-squares, rango, condición, low-rank y eigen simétrico tienen rutas públicas calificadas. |
| No duplicación | Ninguna ausencia que pertenece al core o a `std.Math.LinearAlgebra` se “resuelve” inflando la OAL. |
| Scope | Todo lo explícitamente diferido a V2 permanece diferido sin bloquear V1. |

Un blocker V1 debe nombrar una capacidad de consumer denso real que no pueda
componerse con la superficie existente, que pertenezca a la OAL según este
límite de capas y cuya ausencia rompa uno de los gates. “Es habitual en otra
biblioteca” no es criterio suficiente.

## 4. Decisiones sobre primitives fundamentales

La clasificación pedida es exclusiva: **(1) ya existe**, **(2) debe vivir en
`std.Math.LinearAlgebra`**, **(3) debe vivir en la OAL**, o **(4) V2/fuera de
scope**.

| Primitive | Decisión | Razón de capa y efecto sobre el cierre |
|---|---:|---|
| Dot product de vectores orientados | **1** | Ya es `Row * Column -> T` en core, para owners y views; no se necesita `dot()` OAL. |
| Outer product | **1** | Ya es `Column * Row -> Matrix<T>` en core, con shape exacto y owner nuevo. |
| Multiplicación Matrix/Vector y Matrix/Matrix | **1** | La tabla de `*` cubre `Matrix*Column`, `Row*Matrix` y `Matrix*Matrix`; el resultado es owning y los inputs se leen mediante owners/views. |
| Norma euclídea estable de Vector | **2** | Falta una API pública nativa. Es una reducción general sobre Vector, no una descomposición OAL. V1 de la OAL no se bloquea; un vertical std separado debe fijar nombre, Row/Column, finitud y acumulación escalada. |
| Otras normas vectoriales (`L1`, `Linf`, `Lp`) | **4** | Requieren catálogo y políticas adicionales; no son necesarias para consumir la OAL V1. |
| Norma Frobenius estable | **2** | Falta públicamente y es una reducción general sobre Matrix. Debe compartir autoridad numérica con la futura norma vectorial, sin exportar el helper privado OAL. No bloquea el freeze de esta OAL. |
| Normas matriciales inducidas distintas de Frobenius | **4** | La norma 2 exacta implica SVD y las demás requieren nomenclatura/política propias; fuera del cierre. |
| `trace` | **2** | Falta públicamente; es un recorrido general square/diagonal expresable en source std y no una factorización. No bloquea la OAL. |
| `identity` owning | **1** | Existe como `linearAlgebra.identity<T>(n)`, un owner `n×n`. Su ubicación histórica se congela; este cierre no la mueve ni duplica. |
| Matrix diagonal owning desde Vector | **1** | Existe en std como `diagonalMatrix` para Row y Column. |
| Extracción de diagonal | **4** | Puede diseñarse después como view o copy; no es necesaria para reconstrucción ni consumo de factores V1. |
| Transpose sin ownership | **1** | `transpose_view`/`transpose_view_mut` son primitives core O(1), sin allocation. |
| Transpose owning de Matrix | **1** | `std.Math.LinearAlgebra.transposeCopy` preserva la fuente y crea un owner independiente. |
| Transpose owning de Vector | **1** | `transpose(Vector)` consume el owner y cambia Row/Column sin copiar el backing. |
| Predicado square | **1** | Se expresa sin allocation como `rows(A) == columns(A)` con queries core. |
| Predicados `isSymmetric`, `isDiagonal`, triangularidad, ortogonalidad, SPD y finitud global | **4** | No existe familia pública. Exactitud frente a tolerancia, dominio y coste necesitan un diseño separado; los algoritmos V1 validan internamente sólo sus precondiciones contractuales. |

Las entradas clasificadas **2** son follow-ups de std, no huecos que deban
rellenarse en la OAL. Publicarlas en `linearAlgebra` crearía una segunda
autoridad justo cuando `std.Math.LinearAlgebra` ya es el hogar de algoritmos
generales de materialización.

## 5. Superficie que se congela

Se congelan funcionalmente estas familias:

- constructores `zeros`, `ones`, `identity`;
- aggregates `LU`, `Cholesky`, `QR`, `SVD`, `SymmetricEigen`;
- `lu`/`luInPlace`, `cholesky`/`choleskyInPlace`, `qr`/`qrInPlace` y el wrapper
  deprecated `qrFloat32`;
- `det` desde Matrix/LU/Cholesky y `detInPlace` desde Matrix;
- `solve` desde Matrix/LU/Cholesky/QR, con RHS Vector o Matrix donde está
  publicado, y `solveInPlace` desde Matrix;
- `svd`, `pseudoInverse`, `leastSquares`, `numericalRank`, `condition2`,
  `nonzeroSingularValueCount` y la familia low-rank;
- `symmetricEigen`;
- las siete excepciones nominales auditadas.

“Congelar” impide agregar por conveniencia overloads redundantes, aliases de
std, variantes por precisión, materializaciones `P`/`Sigma` o getters que
dupliquen fields. Correcciones de bugs, qualification, documentación y mejoras
internas que preserven contrato siguen permitidas. Una ruptura o ampliación de
la superficie requiere un milestone posterior explícito.

## 6. Ausencias evaluadas que no bloquean

No son blockers:

- un nombre `inverse`: `solve` es la primitive preferida y
  `pseudoInverse` cubre el caso general;
- `svdInPlace`, `symmetricEigenInPlace` o overloads Matrix directos para cada
  método: la preserving API y la reutilización de factors ya permiten
  composición sin ambigüedad;
- QR con pivoting, full SVD, eigenvalues-only, explicit residual returns o
  selección automática de solver;
- copy/clone universal de Matrix;
- aliases OAL de `transposeCopy`, `diagonalMatrix` o productos core;
- soporte complejo o tipos numéricos definidos por usuario.

## 7. V2, explícitamente separado

Queda fuera de V1 y no puede usarse para reabrir este cierre:

- general real eigen / Schur;
- complex eigen;
- generalized eigenproblem;
- sparse matrices;
- iterative Krylov solvers;
- randomized SVD;
- BLAS/LAPACK backend;
- SIMD/GPU kernels;
- distributed algebra.

También quedan fuera las políticas de tolerancia configurables globales,
formatos packed/banded y families de predicates/normas no seleccionadas en
§4.

## 8. Decisión

Todos los gates de §3 están satisfechos por la superficie auditada. Los únicos
follow-ups fundamentales detectados —norma euclídea, Frobenius y `trace`— son
responsabilidad de std y no impiden usar, componer ni congelar la OAL.

**LINEAR-ALGEBRA-V1 COMPLETE**

Estado final: **CLOSED / V1 COMPLETE**.
