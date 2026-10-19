# LINEAR-ALGEBRA-SVD-LOW-RANK-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-19.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1-REPORT](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md);
- [LINEAR-ALGEBRA-STABLE-NORM-V1](LINEAR_ALGEBRA_STABLE_NORM_V1_REPORT.md).

## API y semántica de rank

`linearAlgebra/src/lib.ae` agrega exactamente los overloads desde `Matrix<T>`
y `SVD<T>` de `lowRankApproximation`, `lowRankSpectralError` y
`lowRankFrobeniusError`, todos bajo `T: IEEEFloat`.

Para `p=dimension(factor.S)`, el dominio es literalmente `0 <= rank <= p`.
Las rutas de factor comprueban primero
`columns(factor.U)==p` y `rows(factor.Vt)==p`, y después ejecutan
`shapeGuard(rank <= p)`. No hay clamp, cutoff, consulta de `numericalRank` ni
selección automática. Un cero almacenado dentro del prefijo pedido participa
como cualquier otro triplet y aporta cero.

Las rutas `Matrix` llaman una única vez a `svd(A)` y delegan inmediatamente a
la ruta de factor. `A` y los factores son entradas shared y siguen siendo
reutilizables.

## Kernel de reconstrucción

La ruta de factor asigna sólo la `Matrix<T>` resultado `m x n`, inicializada en
cero, y usa el traversal determinista `r/i/j`. El árbol source de cada aporte
queda fijado exactamente como:

```text
scaledU = U[i,r] * S[r]
contribution = scaledU * Vt[r,j]
result[i,j] = result[i,j] + contribution
```

No se forma `Sigma`, un factor truncado, un transpose owning ni un
`Vector`/`Matrix` temporal. El coste es `O(m*n*rank)`. `rank==0` conserva la
matriz cero; `rank==p` reconstruye todo el factor thin. Los casos `0x0`,
`mx0`, `0xn` y factores manuales con `p` no canónico conservan sus extents y
no requieren `p==min(m,n)`.

## Errores Eckart–Young/Mirsky

Después de los guards, el error espectral es `S[rank+1]` cuando `rank<p` y
`+0` cuando `rank==p`. Por tanto cuesta `O(1)` y no asigna ni materializa la
aproximación o el residual.

El error Frobenius evalúa la norma del sufijo `S[rank+1..p]`. Reutiliza
`stableNormRange`, la única autoridad privada de suma de cuadrados escalada
del módulo. No duplica el algoritmo ni forma cuadrados directos; cuesta
`O(p-rank)`, usa sólo escalares y retorna `+0` para el sufijo vacío. La
qualification incluye escalas donde una suma ingenua de cuadrados
overflowearía o underflowearía en float32 y float64.

## Ownership, allocations y coste

Sobre un factor, la aproximación crea un solo owner cuando `m*n>0`; las dos
consultas de error crean cero owners. Las rutas Matrix pagan el workspace y
los factores de una SVD, y sólo la aproximación agrega su Matrix resultado.
Ninguna ruta crea residual, `Sigma`, copia de factores ni helper de selección
de rank.

## Qualification matemática y optimalidad

`linear_algebra_svd_low_rank_v1.rs` cubre float32/float64 y O0/O2, matrices
square, tall y wide, cero, rank-deficient, espectros repetidos y separados,
rangos cero, uno, intermedios y completos, `rank>p`, factores con shapes
inválidas y shapes vacías.

Un oráculo independiente NumPy/LAPACK construye `U[:, :k] Sigma[:k]
Vt[:k, :]` y compara tanto las rutas Matrix como factor. Los errores se
comparan contra el siguiente singular value y contra la norma independiente
del tail. No se comparan vectores singulares individualmente en espectros
repetidos. Un fixture pequeño compara la aproximación truncada con un candidato
rank-k perturbado y confirma que el segundo no mejora ni la norma espectral ni
la Frobenius del residual.

La qualification de factor rank-deficient verifica explícitamente que
`numericalRank(factor)<p` no altera `lowRankApproximation(factor,p)`: se usan
literalmente todos los triplets pedidos. También confirma que rank cero produce
una salida cero y que los errores para rank completo son `+0`.

## IR y consumer

La inspección MIR/SSA/LLVM confirma monomorfización float32/float64, ausencia
de generic parameters, witnesses, vtables, `TypeId`, LAPACK productivo y
opcodes low-rank. Las rutas de factor no contienen SVD; las consultas no crean
una Matrix y no aparece `retainedSingularValueCount`.

El consumer real factoriza una vez, obtiene `A2`, el error espectral y el error
Frobenius para rank dos, y vuelve a reutilizar el mismo factor para rank cero.
Comprueba además que tanto `A` como el factor permanecen utilizables.

## Validación

```text
aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_svd_low_rank_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```
