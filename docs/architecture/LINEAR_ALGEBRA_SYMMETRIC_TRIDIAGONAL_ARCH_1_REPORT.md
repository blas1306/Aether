# LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Documento normativo:
[LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_ARCH_1.md).

## Resultado

Quedó cerrado, sin modificar source productivo, el vertical privado que reduce
un workspace simétrico normalizado mediante

```text
T = Qh^T W0 Qh
```

sin materializar `T` ni matrices Householder. `T` queda representada por
`d:n` y `e:n-1`; `Qh` se materializa después desde colas compactas y
`tau:n-2`.

No se encontró contradicción entre la arquitectura superior, los reportes de
norma/ownership y el source vigente.

## Auditoría y reutilización

Se reutilizan literalmente `stableNormRange`, `column`, `matrixFilled`,
`vectorFilled`, `identity`, `requireFiniteInternal` y la formación escalar
Householder ya implementada por la bidiagonalización SVD:

```text
beta=-norm si pivot>=+0
pivotRatio=pivot/beta
tail=(x/beta)/(pivotRatio-1)
tau=1-pivotRatio
```

El QR Householder y la bidiagonalización sólo fijan convenciones para las
partes que no son comunes: ninguno implementa el update simétrico rank-2.
`copyMatrixForFactorization` tampoco se invoca literalmente porque no escala
y copia ambos triángulos; el assembly usará un helper derivado que cree una
única copia lower-authoritative normalizada.

## Frontera y representación

Scaling, validación pública y creación de `W` pertenecen exclusivamente al
assembly. Este vertical consume una Matrix `n×n` owning ya normalizada; no
recibe `matrixScale` y no duplica checks de finitud/simetría del input.

Se fijaron dos aggregates module-private:

- reducción compacta: `workspace/d/e/tau`;
- seed para QR: `d/e/vectors`.

`work:n` es scratch local, se asigna una vez y no cruza la frontera. El
aggregate compacto impide separar accidentalmente tails y taus; el seed evita
que el futuro QR interprete storage Householder.

## Kernel cerrado

Para `k=1..n-2`, el kernel calcula la norma estable de `W[k+1:n,k]`, forma
`H_k=I-tau*v*v^T`, escribe `e[k]`, `tau[k]` y la tail en
`W[k+2:n,k]`, y actualiza exclusivamente el lower trailing block mediante:

```text
w = tau*A*v
alpha = -(tau/2)*(v^T*w)
w = w+alpha*v
A = A-v*w^T-w*v^T
```

La arquitectura fija loops crecientes, lectura simétrica
`W[max(i,j),min(i,j)]`, árboles aritméticos, temporales y checks de finitud
antes de stores. `work` no aliasa `W`; la view de norma expira antes de
mutarlo; no hay allocation dentro del loop.

La derivación prueba tanto `H*x=[beta,0,...]^T` como la equivalencia exacta
del rank-2 con `H*A*H`. Norma cero produce reflector identidad y `+0` en
`e/tau`; tail cero con pivot no cero produce `tau=2`, no identidad. Signed
zeros y `n=0,1,2` quedaron especificados sin underflow de extents.

## Storage y materialización

El lower triangle final se particiona sin solapamiento:

- diagonal: duplicado visible de `d`;
- primera subdiagonal: duplicado visible de `e`;
- posiciones inferiores restantes: tail de un único reflector.

`tau==0` vuelve inactiva cualquier cola stale. `d/e` se escriben cuando cada
entrada queda congelada; no hay pase general de extracción final.

`vectors=identity(n)` se postmultiplica por `H_k` en orden creciente, fila por
fila y sin temporales owning. Así produce exactamente
`Qh=H_1...H_(n-2)` y conserva `T=Qh^T W0 Qh`. Después se liberan
`workspace/tau`; QR recibe sólo `d/e/vectors`.

## Recursos y complejidad

La ruta general contiene:

```text
W n×n, d n, e n-1, tau n-2, work n, vectors n×n
```

El assembly asigna `W`; este vertical consume `W` y asigna los otros cinco
owners. El peak es `2n²+4n-3` elementos para `n>=3`. No hay `H`, dense `T`,
axis owner, transpose owning ni allocation por step.

El matvec simétrico y update triangular suman `O(n³)`; materializar `Qh` suma
otro `O(n³)`. Copia/zero-fill lower, vectores auxiliares e identidad agregan
los pases `O(n²)`/`O(n)` explícitamente documentados. El total sigue siendo
`O(n³)` tiempo y `2n²+O(n)` storage incluido el resultado.

## Qualification posterior

`LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1` calificará float32/float64 y O0/O2
con `0×0`, `1×1`, `2×2`, diagonal, zero, dense symmetric, indefinite,
repeticiones, rank deficiency, escalas ya normalizadas, reflectores
degenerados y signed zeros.

Un oracle host independiente reconstruirá `Qh^T W0 Qh`, la tridiagonal desde
`d/e` y `Qh^T Qh`; medirá igualdad tridiagonal, ortogonalidad y residual fuera
de banda sin llamar al futuro QR. Qualification white-box inspeccionará
layout/tau/tails, privacidad, extents, seis backings generales y ausencia de
allocation por step.

Los gates source/IR prohibirán Matrix `H`, dense `T`, LAPACK/BLAS, call al
`qr` público, owners por reflector, intrinsic nuevo y cambios de
compiler/runtime. También exigirán concretización ordinaria float32/float64,
sin witnesses, vtables, boxing ni calls indirectas numéricas.

Milestone de implementación: `LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1`.

CLOSED
