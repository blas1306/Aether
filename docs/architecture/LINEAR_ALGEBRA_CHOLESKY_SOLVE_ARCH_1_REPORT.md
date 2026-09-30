# LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-29.

Documento normativo:
[LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_ARCH_1.md).

Autoridad relacionada:

- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-V1](LINEAR_ALGEBRA_CHOLESKY_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-SOLVE-V1](LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md).

## Resultado

Quedaron diseñados, pero no implementados, dos overloads reutilizables de
`solve` desde un factor Cholesky real:

```aether
Vector<T,Column> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Matrix<T> B);
```

Resuelven primero `L y = rhs` y después `L^T x = y`, leyendo la transpose por
índices invertidos. No reconstruyen `A`, no materializan `L^T` y no modifican
los overloads desde Matrix o LU.

## Guards y factor manual

El orden vectorial queda fijado como `L square` y luego longitud del RHS. El
orden matricial es `L square` y luego filas del RHS. Cada relación usa
`shapeGuard` antes de allocation o acceso; su fallo conserva el trap
`ShapeMismatch`.

No se revalida diagonal, finitud, lower triangularidad ni upper cero. Un factor
legítimo de `cholesky` ya garantiza esas propiedades. Un aggregate manual que
pasa shape pero viola la representación queda fuera de esa precondición y
ejecuta las operaciones IEEE ordinarias: cero/NaN/Inf se propagan según
`Mul/Sub/Div`, una diagonal negativa se usa, el upper se ignora y un lower no
canónico se trata como el triangular indicado.

Por ello el solve no lanza automáticamente `SingularMatrixException`,
`NotPositiveDefiniteException` ni una excepción nueva. LU conserva su política
distinta porque su productor puede devolver legítimamente un factor singular;
Cholesky checked no puede hacerlo. Para un RHS `n×0` tampoco se inspecciona la
diagonal y se devuelve `n×0`.

## Algoritmos y orden IEEE

El overload Vector crea un solo Vector `w`. Forward substitution lo llena con
`y`; backward substitution descendente sobrescribe el mismo backing con `x`.

El overload Matrix crea una sola Matrix `W : n×q`. Ambos pases usan orden
`i/c/j`: filas, columnas RHS y dot product ascendente. Cada acumulador empieza
en el RHS actual, evalúa multiplicación seguida de resta para cada `j` y divide
una vez al final. Backward usa `L[j,i]`; nunca lee el upper.

No se permite fast-math, reassociation, FMA contractual, acumulador promovido
ni reducción paralela. Las únicas capabilities escalares requeridas son
`Zero`, `Mul`, `Sub` y `Div`; la frontera pública sigue siendo `IEEEFloat`.

## Ownership, shapes cero y allocations

Factor y RHS son shared, permanecen intactos y reutilizables, y no se clonan.
El resultado es owning, independiente y el único workspace. No hay alias,
Vector por columna ni owners temporales.

Vector asigna exactamente un backing si y sólo si `n>0`. Matrix asigna uno si
y sólo si `n*q>0`. `0×0` vectorial devuelve length cero; `0×q` conserva `q` y
`n×0` conserva `n`, todos sin backing. Un shape inválido falla antes de
allocation.

## Lowering y qualification cerrada

La implementación será package source ordinario, sin opcode, intrinsic,
runtime helper, compiler recognition ni cambios de HIR/MIR/SSA. HIR mostrará
shared borrows, guards, una construcción de resultado y loops/indexing
ordinarios. Después de monomorphization, MIR/SSA contendrán sólo `float32` o
`float64` concretos y ninguna genericidad o capability residual.

La qualification futura cubrirá ambas precisiones, `0×0`, `1×1`, diagonal y
SPD dense; `q=0/1/>1`; `n=0`; residuales contra `A*x`/`A*X`; comparación con
LU; reutilización secuencial; inputs intactos; allocations; guards y factors
manuales con diagonal cero, negativa, NaN, Inf, upper no cero y lower no
canónico. El consumer mostrará el factor todavía usable y dos solves sobre el
mismo `Cholesky`.

## Alcance del cierre

Se crearon únicamente el documento normativo y este reporte. No se modificó
source, consumer, tests, compiler ni runtime. Quedan fuera solve automático
desde Matrix vía Cholesky, selector de método, inverse, Complex, packed
storage, BLAS/LAPACK, iterative refinement y determinant Cholesky; sólo se
reserva la futura firma `det<T: IEEEFloat>(ref Cholesky<T> factor)`.
