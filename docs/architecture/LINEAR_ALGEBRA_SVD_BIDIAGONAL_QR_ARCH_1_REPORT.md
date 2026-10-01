# LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-01.

Documento normativo:
[LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_QR_ARCH_1.md).

## Resultado

Quedó diseñada, sin implementar código, la iteración QR implícita shifted que
consume el `BidiagonalSVDSeed` owning ya producido. La fase mutará `d`, `e`,
`U` y `Vt` in place, sin Matrix bidiagonal, historial de rotaciones, lista de
bloques ni allocation adicional. Al converger transferirá sólo `d/U/Vt`; `e`
será íntegramente `+0` y la orientación se descartará.

La deflation usa una única fórmula local segura:

```text
scale=max(abs(d[i]),abs(d[i+1]))
threshold=(epsilon<T>()*scale)*
          (abs(d[i])/scale + abs(d[i+1])/scale)
```

con branch `scale==0`, comparación `<=` y canonicalización inmediata a `+0`.
Los bloques se buscan desde el final y se elige siempre el no singleton de
mayor `hi`; no se almacena bookkeeping persistente.

## Shift, Givens y chase

El shift único es Wilkinson sobre el trailing `2×2` de `B^T B`. Sus cuatro
entradas bidiagonales se dividen primero por su máxima magnitud. La corrección
del eigenvalue usa `|R|*(|R|/(|delta|+stableHypot(delta,R)))`; el shift queda
representado como `(sigma,lambda)` y nunca se forma `sigma²*lambda`. El par
implícito inicial también se divide por una escala común antes de formar
cuadrados o productos.

La convención cerrada es `G=[[c,-s],[s,c]]`, con
`r=stableHypot(f,g)`, `c=f/r`, `s=g/r`, e identidad si `r==0`. Cada sweep
alterna exactamente `B<-B*G` y `B<-G^T*B`: el primer paso crea un bulge bajo la
diagonal, el izquierdo lo elimina y crea el bulge sobre la superdiagonal que
consume el siguiente paso derecho. El documento fija índices, temporales,
árboles de actualización y stores.

Un cero diagonal interno se persigue explícitamente hacia `hi`: la primera
rotación derecha parte de `(d[j],e[j])`, mueve el cero una posición y el mismo
chase lo lleva al borde, donde `e[hi-1]` se vuelve `+0`. Un cero en `d[hi]`
fuerza shift cero. Ninguna ruta divide por una diagonal ni interpreta rank
deficiency como fallo.

## Acumulación y orientación

Para `Upper`, las rotaciones izquierdas `P` postmultiplican columnas de `U` y
las derechas `Q` premultiplican filas de `Vt` por `G^T`. Para
`TransposedUpper` se intercambian los destinos: `Q` actualiza columnas de `U`
y `P` filas de `Vt`. Columnas de `U` recorren filas crecientes; filas de `Vt`
recorren columnas crecientes. No existe transpose owner.

Así quedan preservadas exactamente:

```text
Upper:           U <- U*P;  Vt <- Q^T*Vt
TransposedUpper: U <- U*Q;  Vt <- P^T*Vt
```

## Terminación y fallos

El budget productivo es `64*k*k`, calculado con arithmetic checked. Cada sweep
shifted o chase especial consume una unidad; deflation y splitting no reinician
el contador. La fase deflaciona antes de seleccionar y después de cada step, y
permite que la última unidad converja antes de decidir agotamiento.

Un hook module-private podrá forzar un cap pequeño o cero. Shift, Givens,
stores y estado completo se validan con `(x-x)==0`; cualquier NaN/infinito o
agotamiento produce `NumericalConvergenceException`, sin output parcial. QR-V1
puede introducir la declaración con visibilidad privada para calificarla;
SVD-ASSEMBLY-V1 promoverá esa misma identidad nominal, no una traducción.

## Qualification y alcance

El futuro vertical único `LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-V1` calificará
seeds sintéticos y reales, reconstrucción, ortogonalidad, signed zero,
deflation alrededor del umbral, shifts extremos, ceros diagonales, repeated y
zero singular values, cap/failure, cleanup, cero allocations, privacidad e IR
ordinario en float32/float64 y O0/O2.

Este cierre no implementa ni modifica código. Permanecen fuera de scope API
`svd`, sign normalization, ordering, permutaciones finales, pseudoinverse,
rank, condition number, low-rank, LAPACK productivo y Complex.
