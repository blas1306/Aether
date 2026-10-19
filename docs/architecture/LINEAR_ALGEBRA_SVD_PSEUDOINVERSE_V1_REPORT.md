# LINEAR-ALGEBRA-SVD-PSEUDOINVERSE-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-15.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1-REPORT](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-CUTOFF-V1](LINEAR_ALGEBRA_SVD_CUTOFF_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1](LINEAR_ALGEBRA_SVD_QUALIFICATION_CLOSURE_1_REPORT.md).

## Resultado y API

`linearAlgebra/src/lib.ae` publica exactamente los cuatro overloads acordados:

```aether
public Matrix<T> pseudoInverse<T: IEEEFloat>(ref Matrix<T> A);
public Matrix<T> pseudoInverse<T: IEEEFloat>(ref Matrix<T> A, T cutoff);
public Matrix<T> pseudoInverse<T: IEEEFloat>(ref SVD<T> factor);
public Matrix<T> pseudoInverse<T: IEEEFloat>(ref SVD<T> factor, T cutoff);
```

No se agregaron variantes exactas, in-place, options, `Result`/`Option` ni
wrappers especializados por precisión. Para una entrada `m×n`, la salida
owning tiene shape `n×m`.

## Kernel y orden aritmético

El helper privado `pseudoInverseRetained` asigna una única Matrix cero `n×m` y
recorre determinísticamente `r`, luego `j`, luego `i`. Para cada par `(r,j)`
fija el árbol source:

```text
scaledV     = Vt[r,j] / S[r]
contribution = scaledV * U[i,r]
result[j,i] = result[j,i] + contribution
```

La división ocurre una vez por `(r,j)`. Se eligió esta parentización porque no
forma primero el reciprocal potencialmente mayor `1/S[r]` y permite reutilizar
el escalar en toda la columna de salida. Frente a dividir `U[i,r]`, ninguno de
los dos árboles domina universalmente en rango —ambos factores ortonormales
tienen magnitud acotada—; el árbol sobre `Vt` reduce las divisiones de
`O(n*m*r)` a `O(n*r)` con el traversal fijado. No se contrata FMA,
reassociation ni igualdad bitwise entre niveles de optimización.

No se materializan `V`, `U^T`, `Sigma+`, diagonal, Vector, índices,
permutaciones ni transpose owner/view auxiliar. Un reciprocal o intermedio no
representable sigue la aritmética IEEE y puede producir infinito; no se
traduce a `NumericalConvergenceException`.

## Cutoff, guards y rutas

Los overloads de factor delegan exclusivamente a
`retainedSingularValueCount(factor)` o
`retainedSingularValueCount(factor, cutoff)`. Por tanto usan literalmente el
prefijo y la comparación estricta ya calificados por
LINEAR-ALGEBRA-SVD-CUTOFF-V1, sin duplicar fórmulas ni agregar tolerancias.
Cutoff cero retiene los valores almacenados no cero e igualdad con un cutoff
explícito queda descartada.

La autoridad común ejecuta primero:

```text
columns(U) == dimension(S)
rows(Vt) == dimension(S)
```

No exige `p==min(m,n)` ni recertifica un factor manual. Después valida que un
cutoff explícito sea finito y no negativo. En la ruta Matrix explícita, la
validación ocurre antes del scan de finitud y de la factorización. Cada ruta
Matrix llama exactamente una vez a `svd(A)` y luego reutiliza el mismo kernel
sobre el factor temporal; las rutas de factor llaman cero veces a SVD.

## Ownership, allocations y complejidad

`A`, `U`, `S` y `Vt` son shared borrows y permanecen utilizables. No hay
partial moves ni alias entre resultado e input. La ruta de factor crea una
única Matrix de salida cuando `n*m>0`, cero backings cuando la salida no tiene
celdas y sólo escalares `O(1)`. La qualification instrumentada observa además
que dos calls sobre el mismo factor agregan sólo sus dos outputs, sin nueva
factorización.

Con `r` singular values retenidos, el kernel cuesta `O(n*m*r)`. La ruta Matrix
cuesta la SVD pública más `O(n*m*r)` y no promete una cota menor.

## Shapes degeneradas y rango deficiente

Las rutas `m×0`, `0×n` y `0×0` retornan respectivamente `0×m`, `n×0` y
`0×0`, sin backing. Un factor estructuralmente válido con `p==0` produce una
Matrix cero `n×m`; sólo posee backing si ambos ejes son no cero. Si el retained
count es cero, se retorna la Matrix cero ordinaria. Rank deficiency y espectro
cero no lanzan excepciones.

## Qualification matemática y oráculo

`linear_algebra_svd_pseudoinverse_v1.rs` ejecuta en O0 y O2 para float32 y
float64. Cubre square, tall, wide, full rank, rank deficient, cero, extents
vacíos, singular values repetidos, valores diminutos descartados por default,
cutoff explícito y cero, igualdad con cutoff y escalas grandes/pequeñas.

Para los casos aplicables comprueba con tolerancias dependientes de tipo y
escala las cuatro identidades:

```text
A A+ A ~= A
A+ A A+ ~= A+
(A A+)^T ~= A A+
(A+ A)^T ~= A+ A
```

El oráculo independiente es `numpy.linalg.pinv`, invocado sólo por el host de
test. Para default, el host calcula `rcond=max(m,n)*finfo(dtype).eps`; para
cutoff absoluto calcula el `rcond` equivalente a partir del mayor singular
value del oráculo. NumPy/LAPACK no aparece en source productivo ni en el
ejecutable Aether.

## Recursos e IR

La instrumentación de heap confirma un output y ningún buffer numérico oculto
en rutas de factor, cero allocations para output sin celdas y allocations de
SVD más un output en rutas Matrix. La inspección MIR/SSA/LLVM confirma
monomorfización float32/float64, ausencia de generic residue, witnesses,
vtables, `TypeId`, LAPACK productivo, opcode de pseudoinversa y helpers de
runtime especiales. La inspección de la superficie confirma cuatro APIs y dos
únicos call sites source a `svd`, ambos en los overloads Matrix.

El consumer público crea `P` desde un factor reutilizable y `P2` directamente
desde `A`; valida shapes y valores, vuelve a usar el factor con otro cutoff y
comprueba que `A` sigue intacta.

## Validación

```text
compiler-next/target/debug/aether check linearAlgebra
cargo test -p aether-driver --test linear_algebra_svd_pseudoinverse_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```
