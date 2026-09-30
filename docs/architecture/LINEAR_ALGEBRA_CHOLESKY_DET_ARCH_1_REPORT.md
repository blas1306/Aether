# LINEAR-ALGEBRA-CHOLESKY-DET-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-29.

Documento normativo:
[LINEAR-ALGEBRA-CHOLESKY-DET-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_DET_ARCH_1.md).

Autoridad relacionada:

- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-V1](LINEAR_ALGEBRA_CHOLESKY_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-DET-V1](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md).

## Resultado

Quedó diseñado, pero no implementado, el overload reutilizable:

```aether
T det<T: IEEEFloat>(ref Cholesky<T> factor);
```

Para `A = L L^T` calcula `product(diag(L))^2`. `factor` es shared, no se
mueve, clona, copia ni modifica y permanece utilizable para nuevos determinants,
observación y `solve`.

## Guard y aggregate manual

La primera sentencia es el único guard:

```aether
shapeGuard(rows(factor.L) == columns(factor.L));
```

Ocurre antes de acceso elemental o aritmética. No se revalidan diagonal,
finitud, triangularidad, upper cero ni procedencia. Un aggregate manual square
ejecuta directamente la aritmética IEEE; no se lanza
`NotPositiveDefiniteException`, `SingularMatrixException` ni una nueva
`InvalidCholeskyFactorException`.

El kernel lee exclusivamente `L[i,i]`. Cambiar arbitrariamente upper o lower
off-diagonal, incluso a NaN o infinito, no cambia el resultado si la diagonal
permanece bitwise igual.

## Orden numérico cerrado

Se eligió normativamente la forma A:

```text
p = 1
for i = 1..n ascending:
    p = p * L[i,i]
return p * p
```

Frente al producto de cuadrados, esta forma sigue literalmente la identidad
matemática, usa `n+1` multiplicaciones en vez de `2n` para `n>1`, introduce
menos redondeos y demora overflow/underflow de cuadrados individuales. No
elimina overflow/underflow de productos parciales ni del cuadrado final.

No se permiten reassociation, fast-math, FMA contractual, reducción paralela,
log-domain, escalado, producto compensado ni acumulador promovido. Diagonales
negativas, ceros, NaN, infinitos y subnormales participan normalmente. Un
producto finito que llega a `±0` termina en `+0` al cuadrarse; cero combinado
con infinito produce NaN.

## Zero shape, capabilities y coste

Para `L 0×0`, el producto vacío conserva `One` y el cuadrado final produce
`+1`, sin acceso elemental ni allocation.

El body usa exactamente `One` y `Mul` sobre `T`; la frontera pública permanece
`T: IEEEFloat`. El costo es `O(n)`, el storage auxiliar `O(1)`, se leen
exactamente `n` diagonales y se realizan cero allocations para todo `n`.

No se crean Matrix, Vector, transpose, workspace, view owning ni objeto
Exception. El resultado es un scalar `T`.

## Relación con LU y lowering

`det(ref LU<T>)` y `det(ref Matrix<T>)` permanecen sin cambios. Cholesky y LU
conservan kernels separados porque tienen guards, signo, capabilities y
semántica operacional distintas; no se introduce una unificación con branches
o flags.

La implementación será source ordinario de `linearAlgebra`. HIR conservará el
shared borrow, guard, loop diagonal y capabilities `One`/`Mul`. Después de
monomorphization, MIR/SSA contendrán sólo operaciones concretas `float32` o
`float64`, sin opcode especial, intrinsic, compiler recognition, `TypeId`,
witness, boxing ni dispatch runtime.

## Qualification y consumer cerrados

La qualification futura cubrirá ambas precisiones, O0/O2, `0×0`, `1×1`,
identity, SPD diagonal y dense, comparación tolerante con `det(A)` y
`det(ref LU)`, reutilización posterior del factor y cero allocations.

Los aggregates manuales cubrirán diagonales negativas, `±0`, NaN, `±Inf`,
subnormales, overflow, underflow y casos que distinguen las formas A/B. Se
probará invariancia bitwise ante cambios arbitrarios de upper y lower
off-diagonal, además del guard único y la ausencia de excepciones nominales.

El consumer calculará `det(ch)`, imprimirá `ch.L` y el scalar, y reutilizará
después `ch` en `solve`, demostrando la semántica shared.

## Alcance del cierre

Se crearon únicamente el documento normativo y este reporte. No se modificó
source, consumer, tests, compiler ni runtime. Quedan fuera logdet/slogdet,
determinant automático vía Cholesky desde Matrix, Complex, factor manual
validated, productos compensados, arbitrary precision y BLAS/LAPACK.
