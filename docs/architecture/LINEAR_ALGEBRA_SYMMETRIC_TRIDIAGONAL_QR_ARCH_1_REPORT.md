# LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Documento normativo:
[LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_QR_ARCH_1.md).

## Resultado

Quedó cerrado, sin modificar source productivo, el QR implícito shifted que
consume `SymmetricTridiagonalSeed(d,e,vectors)`, converge `e` íntegramente a
`+0` y acumula cada similaridad en las columnas de `vectors`.

El kernel mutará los tres owners in place bajo shapes exactas `n`, `n-1` y
`n×n`. Un wrapper owning reutiliza el aggregate privado ya implementado; no se
agrega aggregate ni API pública. `n=0/1` retorna sin epsilon ni sweeps y los
casos activos usan un cap explícito para qualification o `64*n` checked en el
entry productivo.

## Deflation y bloques

La deflation recorre `e` en orden creciente y conserva literalmente:

```text
scale=max(abs(d[i]),abs(d[i+1]))
threshold=0                                      si scale==0
threshold=(epsilon<T>()*scale)*
          (abs(d[i])/scale+abs(d[i+1])/scale)    en otro caso
```

La comparación `<=` incluye igualdad y toda deflation escribe `+0`. No se
forma `abs(d[i])+abs(d[i+1])`, no hay tolerance global y signed zero no
sobrevive como separador.

Después se selecciona desde `n` el bloque no singleton de mayor `hi`. Bloques
`1x1` y `e` inicialmente cero no consumen budget; múltiples bloques se
procesan desde abajo sin lista y comparten un único contador. Repeticiones y
clusters no tienen branches especiales.

## Shift y primer Givens

El shift de Wilkinson usa el trailing `2x2`, normalizado por
`sigma=max(abs(a),abs(b),abs(c))`. La corrección cerrada es:

```text
abs(bn)*(abs(bn)/(abs(delta)+stableHypot(delta,bn)))
```

Un bloque activo prueba que `sigma` y el denominador son positivos.
`delta==±0` toma la rama del eigenvalue menor. El shift dimensional no se
materializa.

El primer par divide por `t=max(abs(d[lo]),abs(e[lo]),sigma)` y forma
exactamente:

```text
f=d[lo]/t-(sigma/t)*muNormalized
g=e[lo]/t
```

El Givens único usa `G=[[c,-s],[s,c]]`, `r=stableHypot(f,g)`, `c=f/r` y
`s=g/r`, con identidad exacta para dos zeros y sin ajustes ad hoc de signo.

## Similaridad y bulge chase

Cada step ejecuta `T<-G^T*T*G`. El bloque `a/b/c` se divide primero por
`localScale=max(abs(a),abs(b),abs(c))`; en esas coordenadas se fijaron los
árboles de `a'/b'/c'` sin formar `c-a`, `2*b` ni cuadrados dimensionales. Un
triple de zeros evita divisiones y se canonicaliza.

La conexión siguiente produce `bulge=s*z` y `z'=c*z`. Para `p>lo`, el nuevo
Givens parte de `(e[p-1],bulge)` y escribe exactamente su hypot `r` en
`e[p-1]`. El bulge vive sólo en un scalar. `e[p]` contiene el `b'` local y
`e[p+1]` recibe `z'` sólo después de guardar el viejo `z`. El último step no
lee storage fuera de `d/e` y deja la tridiagonal estricta.

Cada Givens postmultiplica columnas `p,p+1`:

```text
newP=c*oldP+s*oldQ
newQ=-s*oldP+c*oldQ
```

por filas crecientes, leyendo y validando ambos resultados antes del primer
store. Esto conserva exactamente
`T=Q^T*W0*Q` cuando `Q` se reemplaza por `Q*G`.

## Budget, finitud y failure

Un sweep comprende shift, primer Givens, chase completo hasta `hi-1` y todas
las actualizaciones de `vectors`. Sólo entonces incrementa `usedSweeps`.
Deflation, splitting y el sort futuro no consumen unidades. Success se decide
antes del cap, un split no reinicia el contador y la última unidad puede
converger.

Se validan todos los escalares de deflation, shift, Givens y update local;
bulge y conexión; ambos resultados de cada fila de `vectors`; y el estado
`d/e/vectors` completo después de cada sweep. Cualquier no finito interno o
agotamiento lanza `NumericalConvergenceException`; el owner consumido no se
publica parcialmente.

## Reuse y recursos

`stableHypot`, `isFiniteInternal` y `requireFiniteInternal` se reutilizan
literalmente. El constructor/aggregate Givens, la rotación de columnas, la
deflation adyacente y la selección trailing actuales ya son generales en
semántica aunque conservan nombres bidiagonales: V1 sólo los renombrará a
autoridades neutrales y actualizará callsites SVD. No se duplicará su lógica.

No se reutilizan shift ni chase bidiagonales: trabajan sobre `B^T B` y
alternan rotaciones izquierda/derecha, mientras este kernel requiere una sola
similaridad simétrica.

La fase hace cero allocations y usa sólo el estado existente `d/e/vectors`
más scalars. Con `64*n` sweeps hay como máximo `64*n*(n-1)=O(n²)` rotaciones
tridiagonales y `O(n³)` updates escalares de eigenvectors. El scratch es
`O(1)`, el estado compacto `O(n)` y no existe Matrix `T` o `G`; una política
que habilite `O(n⁴)` queda expresamente prohibida.

## Qualification posterior

`LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1` calificará float32/float64 en
O0/O2: umbral exacto, igualdad, predecessor/successor, signed zeros, splitting,
shift contra host, `2x2`, step local, sweep completo, repetidos/clusters,
cap cero/mínimo suficiente, no finitos, preservación y ortogonalidad de
`vectors`.

El host reconstruirá `T0`. Para `Q0=I` verificará `Q^T*T0*Q≈D`; con un
`vectors=Q0` inicial no identidad usará `Z=Q0^T*Q` y comprobará
`Z^T*T0*Z≈D`, o reconstruirá `A0=Q0*T0*Q0^T`. NumPy será sólo oracle test-only
y comparará copias host ordenadas, porque este vertical no ordena `d`.

Los gates demostrarán privacidad, cero allocation por sweep/rotación, ausencia
de Matrix temporales, QR dense, reuse bidiagonal indebido, LAPACK/BLAS y
opcode especial, además de monomorfización float32/float64 sin residuo generic.

Milestone posterior:

```text
LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1
```

CLOSED
