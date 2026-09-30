# LINEAR-ALGEBRA-QR-SOLVE-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-30.

Documento normativo:
[LINEAR-ALGEBRA-QR-SOLVE-ARCH-1](LINEAR_ALGEBRA_QR_SOLVE_ARCH_1.md).

Autoridad relacionada:

- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-SOLVE-V1](LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_V1_REPORT.md).

## Resultado

Quedaron diseñados, pero no implementados, dos overloads reutilizables desde
un factor QR real:

```aether
Vector<T,Column> solve<T: IEEEFloat>(
    ref QR<T> factor,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref QR<T> factor,
    ref Matrix<T> B);
```

`solve` es el único nombre; no se agrega `leastSquares`. Para `Q : m×m` y
`R : m×n`, el dominio cerrado es `m>=n` con rango columna completo. `m==n`
resuelve el sistema square y `m>n` devuelve la solución least-squares única.
Vector devuelve dimensión `n`; Matrix transforma `m×q` en `n×q`.

No hay selector, wrappers por precisión ni variantes `InPlace`. Los overloads
coexisten nominalmente con Matrix, LU y Cholesky.

## Guards, rango y excepción

El orden estructural queda fijado como: `Q` square, filas de `R` iguales a las
filas de `Q`, `rows(R)>=columns(R)` y compatibilidad del RHS con `rows(Q)`.
Cada relación usa `shapeGuard`; todas preceden allocation, indexación,
aritmética y scan de rango. No hacen falta otras relaciones de extents.

Después de todos los guards y antes de crear el resultado se recorren en orden
creciente los `n` pivots de `R1=R[1:n,1:n]`. `R[i,i] == 0` usa igualdad IEEE
exacta, cuenta `+0` y `-0`, y lanza la nueva:

```aether
public class RankDeficientMatrixException : Exception {
    public init() {}
}
```

No se reutiliza `SingularMatrixException`, porque una Matrix tall
rank-deficient no es una matriz singular square. No hay epsilon, tolerancia,
heurística, finiteness scan ni rank revelation. NaN, infinitos y subnormales no
cero pasan el test exact-zero.

El scan también se ejecuta para un RHS Matrix `m×0`; un pivot cero lanza antes
de allocation. Así la comprobación de solvabilidad no depende de `q`.

## Algoritmos y orden IEEE

Vector crea un único `w : n`: primero aloja las primeras `n` componentes de
`Q^T b` y después se sobrescribe mediante backward substitution sobre `R1`.
Matrix crea una única `W : n×q`, sin Vector por columna. No se materializa
`Q^T`, no se reconstruye `A` y no se calculan residual ni ecuaciones normales.

`Q^T b` usa `i/k`; `Q^T B` usa `i/c/k`. Cada acumulador comienza en cero,
recorre `k` creciente, evalúa `Mul` y después `Add`. Backward usa `i`
descendente, `j` creciente para Vector e `i/c/j` para Matrix; evalúa `Mul`,
luego `Sub` y una única `Div` final. No hay reassociation, FMA contractual,
reduction tree, promoción ni compensación.

Las capabilities exactas son `Zero`, `Equal`, `Add`, `Mul`, `Sub` y `Div`; la
frontera pública permanece `T: IEEEFloat`.

## Factor manual, ownership y allocations

`QR<T>` sigue siendo representacional. No se revalidan ortogonalidad,
triangularidad, reconstrucción, finitud ni procedencia Householder. Después de
shapes y exact-zero, `Q` arbitraria y el upper efectivo de `R` participan tal
cual; lower y filas de `R` bajo `R1` se ignoran. Diagonales NaN/Inf no cuentan
como cero y se propagan mediante las operaciones ordinarias. No existe
`InvalidQRFactorException`.

Factor y RHS son shared, no se consumen, copian ni modifican. El resultado es
owning e independiente y el factor queda reusable para múltiples Vector y
Matrix RHS.

Vector crea exactamente un backing si `n>0`; Matrix, uno si `n*q>0`. Los casos
`n==0`, `m==n==0`, `0×q` y `n×0` preservan sus extents y no crean backing. En
rank failure no se crea backing de resultado. No hay transpose, factor/RHS
copy, residual, segundo workspace ni owner por columna.

## Lowering y qualification cerrada

La implementación será package source ordinario, sin opcode, intrinsic,
runtime helper, compiler recognition ni `TypeId` dispatch. HIR mostrará shared
borrows, cuatro guards, scan `Equal`, una construcción de resultado y loops
ordinarios. Tras monomorphization, MIR/SSA contendrán sólo float32/float64
concretos y ninguna capability o genericidad residual.

La qualification futura cubrirá en ambas precisiones square `0×0`, `1×1`,
diagonal y dense; comparación con LU y residuales; Matrix `q=1/>1`; tall
consistente e inconsistente con optimalidad independiente
`A^T(Ax-b)≈0`; reutilización e inputs intactos; exact-zero square/tall,
incluido `-0` y `q=0`; guards y allocations; y aggregates manuales con `Q` no
ortogonal, lower no cero, off-diagonales arbitrarias, NaN e infinitos.

El consumer futuro mostrará solves square y tall, Vector y Matrix, y el uso de
`factor.Q`/`factor.R` después de resolver.

## Alcance del cierre

Se crearon únicamente el documento normativo y este reporte. No se modificó
source, consumer, tests, compiler ni runtime. Quedan fuera minimum-norm para
`m<n`, LQ/QR de transpose, pivoted o rank-revealing QR, tolerancias/rcond,
pseudoinverse, residual-returning APIs, Q economy/Householder implícito,
Complex y BLAS/LAPACK.
