# NUMERIC-GENERIC-MIGRATION-CLOSURE-1 — reporte de cierre

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-28.

Autoridad:

- [NUMERIC-CAPABILITIES-ARCH-1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-CONSTRUCTORS-V1](LINEAR_ALGEBRA_GENERIC_CONSTRUCTORS_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-LU-V1](LINEAR_ALGEBRA_GENERIC_LU_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-DET-V1](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-SOLVE-V1](LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md).

## Resultado

La migración de `linearAlgebra` quedó cerrada. `zeros`, `ones`, `identity`,
LU, determinant, solve Vector, solve Matrix y QR tienen una sola implementación
source genérica por overload o familia. No quedan kernels, helpers numéricos,
casts ni ramas separados por `float32`/`float64`.

La única entrada por precisión restante es:

```aether
QR<float32> qrFloat32(Matrix<float32> A) {
    return qr(A);
}
```

Es un wrapper temporal de compatibilidad source, sin loops ni lógica numérica.
No se agregaron aliases o wrappers por precisión.

## Capabilities y API final

Los constructores conservan exactamente sus constraints mínimas:

```text
zeros:    T: Storable + Copy + Zero
ones:     T: Storable + Copy + One
identity: T: Storable + Copy + Zero + One
```

Todos los kernels numéricos exponen sólo `T: IEEEFloat`; ninguno enumera la
expansión de `RealOps` ni agrega constraints redundantes. La superficie final
es nueve overloads constructores, `LU<T> lu<T: IEEEFloat>`, dos overloads
`det<T: IEEEFloat>`, cuatro `solve<T: IEEEFloat>`, `QR<T> qr<T: IEEEFloat>` y
el wrapper `qrFloat32`. `LU<T: Storable>` y `QR<T: Storable>` continúan siendo
aggregates representacionales; su constraint no intenta expresar el dominio de
los kernels que los producen.

## Orden real de dependencias

La secuencia demostrada es:

```text
capabilities → constructors → LU → det → solve → QR → closure → Cholesky
```

LU tuvo que preceder `det` y `solve`. El resolver selecciona identidades de
calls durante el análisis paramétrico y no hace deferred overload resolution
después de monomorfizar. Sólo después de convertir `lu` en una única declaración
genérica pudieron `det(Matrix<T>)` y `solve(Matrix<T>, ...)` resolver `lu(A)`.
No se modificó esa política ni se rediseñó el resolver.

El bloqueo histórico de generic det queda preservado en la documentación de su
desbloqueo. La autoridad vigente es `LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md`:
det está implementado y ya no está bloqueado. El reporte DET-V1 concreto está
marcado explícitamente como contrato/oráculo histórico superado en API.

## Inferencia y dogfood

Los calls con `Matrix<T>` infieren `T` desde sus argumentos. Los constructores
continúan usando expected-result inference para elemento, Matrix/Vector y
orientación. La inferencia ocurre antes de borrow adaptation; por eso un call
con resultado `var` y primer argumento `LU<T>` todavía puede requerir:

```aether
var x = solve<float64>(factor, b);
var d = det<float64>(factor);
```

Un resultado explícitamente tipado sí aporta expected type. No se cambió esta
política. El consumer integrado factoriza, imprime `L`/`U`, reutiliza el mismo
factor en solve y det con argumentos explícitos, factoriza QR e imprime `Q`/`R`.

## Ownership, allocations y coste

La calificación conjunta conserva estos contratos:

| familia | owners y allocations vigentes |
|---|---|
| constructors | un backing por resultado no vacío; cero cuando el producto de extents es cero |
| LU | tres en el caso no vacío calificado: input, permutation y un factor adicional; el input se reutiliza como el otro factor |
| `det(ref LU)` | cero allocations; préstamo shared reutilizable |
| `solve(ref LU, Vector)` | una allocation si y sólo si `n > 0` |
| `solve(ref LU, Matrix)` | una allocation si y sólo si `n*q > 0` |
| QR | dos en el caso no vacío calificado: input reutilizado como `R` y `Q` |

La genericidad no introduce clones, `Alias`, copias temporales de owners ni
workspaces Matrix/Vector adicionales. Las rutas owning de det/solve agregan
sólo el coste de la LU que construyen.

## IR, ABI y estructura

La prueba conjunta
`aether-driver/tests/numeric_generic_migration_closure_1.rs` fija la cantidad y
constraints exactas de declaraciones, la única excepción `qrFloat32` y la
ausencia de funciones numéricas por precisión, `TypeId`, witnesses y vtables.

HIR paramétrico contiene `AlgebraicValue`, `CapabilityBinary`,
`CapabilityUnary`, `CapabilityCompare` y `CapabilityMath`. Las instancias HIR
concretas contienen operaciones float concretas y no necesitan dispatch de
capability. MIR y SSA no contienen parameters ni nodes capability. LLVM no
contiene `TypeId`, witnesses o vtables y emite símbolos e instrucciones
distintos para `float32` y `float64`, incluidas llamadas directas a
`fabs[f]`/`sqrt[f]`. No cambió el ABI concreto.

## Regresión y calificación

El consumer conjunto mantiene los oráculos vigentes de ambas precisiones para
LU, det, solve Vector, solve Matrix y QR: shapes cero, pivoting, singularidad o
rank deficiency, signed zero y los casos NaN/Inf/subnormal aplicables. Conserva
las tolerancias publicadas y se ejecuta en O0/O2. Las suites dedicadas fijan
además guards, unwind, allocations, ownership y lowering por familia.

La calificación de cierre usa el binario del checkout, no la instalación global:

```text
compiler-next/target/debug/aether check linearAlgebra
compiler-next/target/debug/aether run linearAlgebra/tests/consumer -O0
compiler-next/target/debug/aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test numeric_generic_migration_closure_1
cargo test -p aether-driver --test linear_algebra_constructors_v1
cargo test -p aether-driver --test linear_algebra_lu_v1
cargo test -p aether-driver --test linear_algebra_det_v1
cargo test -p aether-driver --test linear_algebra_solve_v1
cargo test -p aether-driver --test linear_algebra_solve_matrix_v1
cargo test -p aether-driver --test linear_algebra_qr_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

Si una instalación global de `aether` queda desactualizada, la corrección es
reinstalarla con `cargo install --path compiler-next/crates/aether-cli --force`;
el compilador no se adapta a un binario global viejo.

## Estado previo a Cholesky

La frontera `IEEEFloat`, los constructores y todos los kernels numéricos
existentes están deduplicados y calificados. El siguiente milestone puede ser
Cholesky. Este cierre no implementa Cholesky, `Complex`, capabilities numéricas
de usuario ni resolución diferida de overloads.
