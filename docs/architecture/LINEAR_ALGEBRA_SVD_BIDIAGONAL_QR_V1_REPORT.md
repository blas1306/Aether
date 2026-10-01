# LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-01.

Autoridad normativa:
[LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_QR_ARCH_1.md).

## Resultado

`linearAlgebra/src/lib.ae` incorpora la fase privada QR bidiagonal y el
aggregate privado `BidiagonalSVDConverged<T>`. El kernel muta exclusivamente
los owners `d/e/U/Vt`; shifts, bloques, Givens y bulges son aggregates o
scalars fixed-size. La frontera owning de resultado mueve `d/U/Vt`, deja
destruir `e` y descarta la orientación. No se publicó `svd` ni ninguna API.

Los casos `k==0` y `k==1` retornan antes de obtener epsilon o calcular el
budget. No cambian signo, no ejecutan deflation ni aplican rotaciones.

## Deflation y splitting

Para `k>=2` se obtiene `epsilon<T>()` una vez. El pase creciente calcula
literalmente:

```text
a=abs(d[i]); b=abs(d[i+1]); scale=max(a,b)
threshold=0                                      si scale==0
threshold=(eps*scale)*((a/scale)+(b/scale))      en otro caso
```

La comparación es `abs(e[i])<=threshold` y toda entrada deflacionada se
reescribe `+0`. No se forma `a+b`. Después se busca desde `k` el bloque no
singleton de mayor `hi`, sin lista ni bookkeeping persistente.

## Shift, Givens y chase

El único Givens usa `stableHypot(f,g)`, `c=f/r`, `s=g/r` y la identidad exacta
si `r==0`, bajo la convención `G=[[c,-s],[s,c]]`.

El shift de Wilkinson lee el trailing `2x2` correcto, normaliza por la máxima
magnitud de `x/y/z/w` y conserva `(sigma,lambda)`. La corrección usa
`abs(R)*(abs(R)/(abs(delta)+stableHypot(delta,R)))`; nunca se materializan el
shift dimensional ni cuadrados dimensionales. El par implícito inicial usa
`t=max(abs(d[lo]),abs(e[lo]),sigma)` y conserva el árbol normativo de `f/g`.

Antes de un sweep se busca un diagonal cero desde `hi-1` hasta `lo`. Esa ruta
usa el primer Givens sobre `(d[j],e[j])`, ejecuta el mismo chase alternado y
canonicaliza `e[hi-1]`. El sweep shifted y el chase especial comparten el
pseudocódigo escalar: cada grupo lee los valores viejos, calcula y valida sus
temporales y sólo entonces escribe. No queda bulge al terminar el step.

## Acumulación y orientación

Las postrotaciones de columnas y las premultiplicaciones de filas implementan
los árboles source fijados, con traversal lógico creciente y validación antes
de store. El dispatch es:

| Rotación | `Upper` | `TransposedUpper` |
|---|---|---|
| derecha `Q` | filas de `Vt` | columnas de `U` |
| izquierda `P` | columnas de `U` | filas de `Vt` |

No se materializan `P/Q` ni se transpone ningún owner.

## Budget, finitud y salida

El entry productivo calcula con aritmética checked `64*(k*k)`. Deflation y
selección preceden el chequeo del cap; cada sweep o zero chase consume una
unidad; los splits no reinician el contador. El helper white-box permite
inyectar un cap, incluido cero.

La finitud privada usa exactamente `(x-x)==0`. Se validan shift, Givens,
nuevos valores de `d/e`, actualizaciones de `U/Vt` y, tras cada step, el estado
completo. Budget agotado o estado no finito lanza la declaración nominal
module-private `NumericalConvergenceException`.

Antes del resultado se comprueba y reescribe todo `e` como `+0`. La salida
mantiene `d` signed y unordered: no aplica valor absoluto, corrección de signo,
sort, permutación ni base canónica.

## Allocations y qualification

La fase QR no crea Matrix, Vector, listas, historiales ni transpose owners. La
qualification instrumentada confirma cero allocations adicionales y lowering
monomorfizado ordinario, sin generic residue, `TypeId`, opcode QR/SVD, helper
runtime ni LAPACK.

`linear_algebra_svd_bidiagonal_qr_v1.rs` cubre O0/O2, float32/float64,
privacidad, Givens, shift analítico y escalado, deflation en el umbral, cap
cero y suficiente, no finitos, `k=0/1`, diagonal, 2x2/3x3, zero chase, cero
trailing, rango deficiente, repetidos, signed zero, subnormales, escalas muy
separadas, reconstrucción desde seeds reales upper/transposed, ortogonalidad,
IR y allocations.

Permanecen fuera de scope `svd` público, normalización `S>=0`, sort,
permutaciones correlacionadas, pseudoinverse, rank, condition number, LAPACK y
Complex.
