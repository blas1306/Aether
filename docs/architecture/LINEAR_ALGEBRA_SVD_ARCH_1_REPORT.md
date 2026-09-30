# LINEAR-ALGEBRA-SVD-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-30.

Documento normativo:
[LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md).

## Resultado

Quedó diseñada, pero no implementada, la SVD real thin de `linearAlgebra`:

```aether
struct SVD<T: Storable> {
    Matrix<T> U;
    Vector<T,Column> S;
    Matrix<T> Vt;
}

SVD<T> svd<T: IEEEFloat>(ref Matrix<T> A);
```

Para `A:m×n` y `k=min(m,n)`, el contrato exacto es `U:m×k`, `S:k` y
`Vt:k×n`, con reconstrucción `A≈U diag(S) Vt`, columnas de `U` y filas de
`Vt` ortonormales, y valores finitos `S[1]>=...>=S[k]>=+0`. La entrada es
preserving y todas las matrices rectangulares, vacías, cero o rank-deficient
pertenecen al dominio.

Thin se eligió sobre full porque conserva todos los triplets necesarios para
pseudoinverse, minimum-norm, rank, condición y Eckart–Young sin almacenar
complementos ortogonales inútiles. `S` es Vector column; no existe Sigma dense.
Una futura SVD full tendrá una operación explícita y no cambiará `svd`.

## No unicidad y orden

La corrección de una diagonal negativa niega la fila asociada de `Vt` y
`abs` normaliza cada singular value, incluido `-0`. Después se ordenan los
triplets en forma descendente mediante un sort estable que permuta a la vez
`S`, columnas de `U` y filas de `Vt`.

No se canonicalizan signos. Ante valores repetidos —incluidos ceros— tampoco se
canonicalizan bases dentro del subespacio. Qualification comprobará
reconstrucción, ortogonalidad y proyectores/subespacios, no igualdad elemental
de vectores contra un oráculo.

## Dominio, errores y terminación

Antes del algoritmo se rechaza NaN o infinito de entrada con la nueva excepción
reusable `NonFiniteMatrixException`. Rank deficiency nunca es error.

La iteración queda siempre acotada por un presupuesto interno `O(k²)`. Agotarlo
o llegar a un estado/resultados no finitos lanza la excepción general
`NumericalConvergenceException`. No hay loop ilimitado, factor parcial ni
tolerancia pública.

La deflation usa machine epsilon del tipo y escalas bidiagonales locales, no
exact-zero ni decimales hardcoded. Se identificó un gap bloqueante: Aether aún
no expone machine epsilon genérico. Un milestone previo diseñará y calificará
[`epsilon<T: IEEEFloat>()`](IEEE_FLOAT_CONSTANTS_ARCH_1.md) sin modificar
capabilities durante este cierre.

## Algoritmo y recursos

El objetivo productivo es Golub–Kahan/Reinsch: Householder bidiagonal compacto,
QR implícito shifted, deflation/splitting y acumulación de vectores thin. Wide
usa conceptualmente el kernel tall sobre la orientación transpuesta y permuta
roles al ensamblar. Se prohíben `A^T A`/`A A^T` por pérdida de precisión de
valores pequeños. One-sided Jacobi queda como alternativa futura u oráculo.

La reducción conserva reflectors compactos en una copia `m×n`, usa arrays
`O(k)` y materializa sólo `U:m×k`/`Vt:k×n`. Puede existir storage transitorio
acotado `O(mk+kn)`; no se fuerza una allocation artificial. No se permiten
factors full, Matrix Sigma, transpose materializada, allocations por iteración
ni historial no acotado.

La norma interna y las hipotenusas usarán scaling estable. El patrón vigente de
QR se extraerá como una sola autoridad privada y se recalificará sin cambiar el
contrato QR. `copysign`/`hypot` públicos no son prerrequisitos demostrados.

## Ownership, lowering y evolución

`svd(A)` adapta el owner a `ref Matrix<T>`, copia el rectángulo lógico y deja
`A` intacta y reusable incluso tras una excepción capturada. El resultado posee
tres owners independientes. No se agrega `svdInPlace` hasta demostrar con el
kernel real una reutilización de backing valiosa y segura.

SVD será package source ordinario, sin opcode, intrinsic de descomposición,
LAPACK oculto o reconocimiento del package. La frontera es `T: IEEEFloat` para
`float32`/`float64`; MIR/SSA quedan concretos después de monomorphization.
Backends LAPACK futuros podrán preservar esta misma semántica pública.

## Qualification y próximos milestones

La qualification reconstruirá por suma de triplets sin crear `diag(S)`, medirá
ambas ortogonalidades y comparará singular values con un oráculo independiente.
Cubrirá tall/wide/square, vacíos, cero, rank deficiency, multiplicidades,
ill-conditioning, escalas extremas, ambas precisiones, rejection de no finitos,
failure de convergencia, ownership, allocations y O0/O2.

La secuencia cerrada es:

1. `IEEE-FLOAT-CONSTANTS-ARCH-1/V1`;
2. `LINEAR-ALGEBRA-STABLE-NORM-V1`;
3. `LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1/V1`;
4. `LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1/V1`;
5. `LINEAR-ALGEBRA-SVD-ASSEMBLY-V1`;
6. `LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1`.

Se crearon únicamente este reporte y el documento normativo. No se modificó
source, consumer, tests, compiler, runtime ni standard library.
