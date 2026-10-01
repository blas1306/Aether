# LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-01.

Documento normativo:
[LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1.md).

## Resultado

Quedó diseñada, sin implementar código, la reducción Householder compacta que
será la primera fase productiva de la SVD thin real. La futura entrada
preserving se copia una vez a `W:m×n`; un descriptor mutable normal para
`m>=n` o transpuesto O(1) para `m<n` presenta al único kernel una matriz
`M×N`, `M>=N=k`. Wide no materializa una copia de `A^T`.

El kernel reduce esa orientación a una bidiagonal upper mediante, por step,
un reflector izquierdo sobre la columna `i..M` y, si `i<N`, uno derecho sobre
la fila `i+1..N`. La identidad cerrada es:

```text
X0 = QL B QR^T
QL = H_1 ... H_N
QR = G_1 ... G_(N-1)
```

Tall/square entrega `A=U0 B Vt0`; wide intercambia roles y entrega
`A=U0 B^T Vt0`. Un tag privado conserva la diferencia para la iteración QR.

## Reflectors y layout

La convención única es `H=I-tau*v*v^T`, con primer elemento de `v` implícito
igual a uno. Norma y signo de `beta` siguen la autoridad estable y QR vigente:
`beta=-norm` cuando el pivot compara `>=+0`, y `beta=+norm` en otro caso. La
cola y `tau` usan la forma escalada algebraicamente equivalente basada en
`pivot/beta`, que evita formar el potencialmente desbordante `pivot-beta`.
Norma cero produce `beta=tau=+0` y reflector identidad, sin división.

Los pivots `d` y `e` quedan sobre diagonal y superdiagonal del workspace. Las
colas izquierdas ocupan el triángulo inferior y las derechas la región encima
de la superdiagonal; esas celdas no representan ceros aunque la `B`
matemática sí los tenga. `tauLeft/tauRight` son vectores O(k). `d/e` se
escriben durante la reducción y sobreviven independientemente al workspace;
no hay extracción posterior.

La norma se llama exclusivamente mediante `stableNormRange`: columnas usan
`column(X,i), i..M`, y filas usan
`transpose_view(row(X,i)), i+1..N`. No se duplica `scale/scaledSquares`, no se
usa `sqrt(sum(x*x))` y las views no asignan.

## Materialización thin y casos degenerados

Los reflectors izquierdos se aplican en orden descendente a una identidad
thin para construir `QL[:,1..k]`; los derechos se aplican en el orden que
forma directamente `QR` o `QR^T`. Tall materializa `U0=QL[:,1..k]` y
`Vt0=QR^T`. Wide materializa directamente `U0=QR` y
`Vt0=QL[:,1..k]^T`, sin factor full ni transpose/copy intermedio.

La construcción no usa `d/e` ni divide por singular values. Rank deficiency y
matriz cero producen bases ortonormales deterministas desde identidades thin;
los reflectors cero simplemente se omiten. `m×0`, `0×n` y `0×0` conservan sus
extents vacíos exactos.

## Estado entregado y coste

La frontera privada con `SVD-BIDIAGONAL-QR-ARCH-1` contiene `d`, `e`, `U`,
`Vt` y orientación `Upper`/`TransposedUpper`. Los valores siguen signed y sin
ordenar. La fase siguiente deberá intercambiar la acumulación de rotaciones
izquierdas/derechas para el tag wide: si `B=P*Sigma*Q^T`, tall acumula `P` en
`U` y `Q^T` en `Vt`, mientras wide acumula `Q` en `U` y `P^T` en `Vt`. No
recibirá colas Householder.

El budget de peak es el workspace `m*n`, outputs `m*k` y `k*n`, más cuatro
vectores lineales `d/e/tauLeft/tauRight`. Después de materializar ambos
factors se liberan workspace y taus. El objetivo temporal es `O(m*n*k)`;
quedan prohibidos Matrix/Vector por reflector, factors full descartados,
transpose owning y allocations dentro de inner loops.

## Qualification y alcance

El futuro vertical `LINEAR-ALGEBRA-SVD-BIDIAGONAL-V1` comprobará
reconstrucción `A≈U0 B Vt0` o `A≈U0 B^T Vt0`, ortogonalidad, shapes, layout,
allocations, visibilidad privada y lowering ordinario para float32/float64 en
O0/O2. Cubrirá square, tall, wide extremo, cero, rank deficiency, repeticiones,
signed zeros, escalas extremas y todos los zero extents. No usará `A^T A` como
oráculo ni publicará helpers de test.

Este cierre no implementa código ni API `svd`, iteración QR, shifts, Givens,
deflation, epsilon, convergence cap, ordering, signos finales, pseudoinverse,
LAPACK productivo o Complex.
