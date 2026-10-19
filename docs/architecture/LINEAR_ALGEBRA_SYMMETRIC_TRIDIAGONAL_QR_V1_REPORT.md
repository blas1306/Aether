# LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1 — reporte de implementación

Estado: **CLOSED**, 2026-10-19.

Autoridad normativa:
[LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_QR_ARCH_1.md).

## Resultado

Se implementó la fase privada que consume
`SymmetricTridiagonalSeed(d,e,vectors)`, ejecuta QR simétrico tridiagonal
implícito con shift de Wilkinson trailing y retorna el mismo aggregate con
toda `e` canonicalizada a `+0`. El vertical no agrega API pública, rescale,
sort, validación pública, eigenvalues-only, QL ni dirección adaptativa.

El kernel `convergeSymmetricTridiagonalState` valida exactamente los shapes
`n`, `n-1` y `n×n`. `n=0/1` retorna después de esos guards. Los wrappers
owning con cap explícito y productivo preservan el owner consumido; el segundo
usa la multiplicación checked ordinaria `64*n`.

## Refactor común

Las autoridades generales usadas antes sólo por SVD se renombraron sin
cambiar su convención ni sus traversals:

```text
BidiagonalGivens             -> GivensRotation
bidiagonalGivens             -> givensRotation
rotateBidiagonalColumns      -> rotateColumnsByGivens
rotateBidiagonalRows         -> rotateRowsByGivens
BidiagonalActiveBlock        -> TrailingActiveBlock
deflateBidiagonal            -> deflateAdjacentOffDiagonal
selectBidiagonalBlock        -> selectTrailingActiveBlock
```

Todos los callsites y la qualification SVD usan ahora las autoridades
neutrales. Queda una sola implementación productiva de Givens, rotación de
columnas, deflation adyacente y selección trailing. El shift y chase
bidiagonales permanecen separados.

## Deflation y selección

`deflateAdjacentOffDiagonal` recorre `e` de izquierda a derecha y calcula el
threshold escalado desde `epsilon<T>()`, con comparación inclusiva. Los
ratios, suma normalizada y threshold se validan como finitos. Toda entrada
deflacionada, incluidos `-0`, se escribe con el literal `+0`.

`selectTrailingActiveBlock` selecciona el bloque no singleton de mayor `hi`.
El loop vuelve a seleccionar después de cada sweep, sin lista de bloques y
sin reiniciar `usedSweeps`. Success y canonicalización preceden al control del
cap.

## Shift, Givens y similaridad local

El shift usa exclusivamente el trailing `2x2`, normaliza por
`sigma=max(abs(a),abs(b),abs(c))` y forma la corrección cerrada
`abs(bn)*(abs(bn)/(abs(delta)+stableHypot(delta,bn)))`. `sigma`, denominador y
todos los temporales se validan; no se materializa el shift dimensional.
`delta==±0` toma la rama cerrada `else`.

El primer Givens se forma desde los cocientes por
`max(abs(d[lo]),abs(e[lo]),sigma)`. `givensRotation` conserva
`G=[[c,-s],[s,c]]`, `r=stableHypot(f,g)` e identidad exacta para el par de
zeros, sin corrección ad hoc de signos.

Cada paso del chase evalúa literalmente el árbol normalizado de
`G^T*T*G`. El caso `localScale==0` evita divisiones y produce tres `+0`. La
conexión siguiente se conserva sólo en los scalars `bulge`, `nextBulge` y
`nextZ`; el último paso no accede a `e[hi]`.

## Eigenvectors, budget y failure

Cada rotación postmultiplica inmediatamente las columnas `p,p+1` de
`vectors`. Ambos resultados de una fila se calculan y validan antes del primer
store. No se asignan columnas temporales.

El contador es global a toda la fase. Una unidad cubre shift, primer Givens,
chase completo y acumulación de eigenvectors. Después del sweep se validan
íntegramente `d/e/vectors`. Cap agotado o cualquier no finito interno lanza
`NumericalConvergenceException`; el wrapper owning no publica estado parcial.

## Recursos e IR

El centro opera sobre los owners existentes y agrega sólo scalars y
aggregates fixed-size. La qualification instrumentada confirmó cero
allocations y cero frees adicionales durante QR en O0 y O2. No existen Matrix
`T/G`, Vector temporal, lista de bloques ni historial de rotaciones.

MIR, SSA y LLVM confirman monomorfización float32/float64 sin `GenericParam`,
witness, vtable, boxing o `TypeId` residual. No hay LAPACK/BLAS, FFI,
instrucción Matrix especial, QR dense ni reuse del shift/chase bidiagonal.

## Qualification

Se agregó
`compiler-next/crates/aether-driver/tests/linear_algebra_symmetric_tridiagonal_qr_v1.rs`.
La qualification O0/O2 cubre shapes y `n=0/1`, diagonal, `2x2`, `3x3`,
deflation exacta y vecinos representables, signed zero, `scale==0`, escalas
grandes/pequeñas/subnormales, múltiples bloques y singleton trailing, las
tres ramas de `delta`, ambos signos de `b`, par Givens cero, similaridad local
cero, spectra repetidos/clustered/indefinidos/extremos, cap cero, cap mínimo,
budget compartido y fallo no finito.

El oracle reconstruye `T0`, comprueba similaridad y ortogonalidad tanto con
`Q0=I` como con `Q0!=I`, y compara copias host ordenadas de los eigenvalues
con `numpy.linalg.eigvalsh`. El producto no ordena `d`.

La regresión ejecutó todos los verticales SVD y los dos cierres derivados sin
cambio numérico observable.

## Validación

```text
aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_symmetric_tridiagonal_qr_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

CLOSED
