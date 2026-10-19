# LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO; CLOSED**, 2026-10-19.

Autoridad normativa:

- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1-REPORT](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-STABLE-NORM-V1](LINEAR_ALGEBRA_STABLE_NORM_V1_REPORT.md).

## Resultado y alcance

`linearAlgebra/src/lib.ae` implementa el vertical privado completo

```text
normalizedWorkspace
    -> reducción Householder simétrica compacta
    -> materialización de Qh
    -> SymmetricTridiagonalSeed(d,e,vectors)
```

No se agregó API pública ni se implementaron QR tridiagonal, shifts,
deflation, sorting, rescale o `symmetricEigen`. Tampoco hubo cambios de
compiler, runtime, capabilities u opcodes.

Los aggregates module-private son exactamente
`CompactSymmetricTridiagonalReduction<T>` con `workspace/d/e/tau` y
`SymmetricTridiagonalSeed<T>` con `d/e/vectors`. La qualification desde un
módulo consumidor confirma que ni los tipos ni los entry points pueden
importarse.

## Extents y ownership

Los extents se forman con branches que no evalúan underflow:

```text
offDiagonal = n>0 ? n-1 : 0
reflectors  = n>2 ? n-2 : 0
```

La implementación es total para `n=0`, `n=1`, `n=2` y `n>=3`. El entry
owning evita partial moves: mantiene `normalizedWorkspace`, `d`, `e`, `tau` y
`work` como owners locales, materializa `vectors` mediante borrows compartidos
del workspace compacto y `tau`, y mueve sólo `d/e/vectors` al seed. El retorno
normal y unwind ordinario destruyen una vez los owners restantes. No fue
necesaria ninguna extensión del lenguaje.

En la ruta general se observan exactamente seis backings, contando el input:

```text
W, d, e, tau, work, vectors
```

La qualification repite el conteo en órdenes 3 y 5, en O0 y O2. El resultado
es seis allocations y seis frees en ambos tamaños; no existe allocation por
reflector. El peak sigue siendo `2*n^2+4*n-3` elementos.

## Householder y layout compacto

Cada step creciente `k=1..n-2` usa
`stableNormRange(column(W,k),k+1,n)` y conserva literalmente el árbol cerrado:

```text
beta = norm; si pivot>=+0, beta=-norm
pivotRatio = pivot/beta
tail = (x/beta)/(pivotRatio-1)
tau = 1-pivotRatio
```

Norma cero no ejecuta divisiones y publica `beta=e[k]=tau[k]=+0`. No se usa
epsilon. Se comprueban con `requireFiniteInternal` norma, escalares, tails y
todo valor producido antes de almacenarlo o reutilizarlo.

La diagonal se copia a `d[k]` antes de formar el reflector; `e[k]` se congela
al formar `beta`; las dos últimas diagonales y la última off-diagonal se
copian al salir. No existe un extraction pass general.

El lower triangle queda particionado sin ambigüedad:

- `W[i,i]` duplica `d[i]`;
- `W[i+1,i]` duplica `e[i]`;
- `W[r,k]`, para `r>=k+2`, contiene la cola del reflector `k`.

El pivot contiene `beta`, nunca el uno implícito. Un `tau==0` inhibe toda
lectura de la cola; la prueba white-box reemplaza deliberadamente una cola
inactiva por NaN y comprueba que la materialización sigue produciendo la
identidad. También califica `tau==2` con tail cero, pivots `+0/-0` activos y
canonicalización `+0` del off-diagonal degenerado.

## Update rank-2 y materialización

El trailing block usa exclusivamente lecturas simétricas del lower triangle,
un `Vector work` reutilizado y loops crecientes. Implementa sin reassociation
deliberada:

```text
w = tau*A*v
alpha = -(tau/2)*(v^T*w)
w = w+alpha*v
A = A-v*w^T-w*v^T
```

No se materializan `A`, `H`, el upper triangle ni una tridiagonal dense. Cada
acumulador, valor de `work`, `alpha` y store del bloque se valida finito.

`materializeSymmetricTridiagonalQ` crea una sola `identity<T>(n)` y aplica los
reflectores en orden creciente. Para cada fila termina el dot antes del primer
store, calcula `scale=tau*dot` y actualiza el pivot y la cola sin Vector
temporal. No hay allocations dentro de materialización. El resultado es
`Qh=H1*...*H(n-2)` y por construcción `T=Qh^T*W0*Qh`.

Reducción y materialización conservan coste `O(n^3)` y storage
`2*n^2+O(n)` incluido el resultado.

## Qualification numérica y white-box

`compiler-next/crates/aether-driver/tests/linear_algebra_symmetric_tridiagonal_v1.rs`
ejecuta float32/float64 en O0/O2. Cubre matrices `0x0`, `1x1`, `2x2`,
diagonal, identidad, cero con signed zeros, dense, positive definite,
indefinite, rank-deficient, bloques desconectados, reflector de norma cero,
tail cero, pivots signed-zero activos y escalas extremas ya normalizadas.

El host conserva `W0`, recibe `d/e/Qh` del fixture Aether y reconstruye con
loops Rust independientes:

```text
L = Qh^T W0 Qh
T = tridiagonal(d,e)
O = Qh^T Qh-I
```

Los límites documentados, expresados con la epsilon del tipo productivo, son:

```text
||L-T||F / max(1,||W0||F) <= 512*n*epsilon(T)
||O||F                    <= 256*n*epsilon(T)
off-band max              <= 256*n*epsilon(T)*max(1,||W0||F)
```

El factor 512 cubre acumulación cúbica, redondeo de output y el corpus de
escalas mezcladas; los límites 256 separan ortogonalidad y residuo off-band.
No son tolerancias productivas. Todos los casos pasan los tres checks.

Las pruebas white-box verifican además shapes exactos, pivots, tails, taus,
partición de slots y lectura inhibida. Los source scans fijan el único kernel,
la fórmula Householder, el árbol rank-2 y ausencia de constructors allocadores
dentro de los loops.

## Lowering e IR

HIR/MIR/SSA/LLVM muestran instancias concretas float32 y float64 de
`reduceSymmetricTridiagonal`. Después de monomorfización no quedan
`GenericParam`, witnesses, vtables, boxing ni `TypeId`. La implementación usa
sólo operaciones escalares y owners/views ordinarios; no aparecen LAPACK,
BLAS, QR público, transpose owner, Matrix Householder, dense T, intrinsic o
runtime especial.

## Validación

El cierre quedó verde con:

```text
aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_symmetric_tridiagonal_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

`cargo test --workspace` incluye la publicación OAL y ejecución del consumer
real de `linearAlgebra` en O0/O2.

CLOSED
