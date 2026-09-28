# LINEAR-ALGEBRA-GENERIC-SOLVE-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC_CAPABILITIES_V1_REPORT](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [LINEAR_ALGEBRA_SOLVE_V1_REPORT](LINEAR_ALGEBRA_SOLVE_V1_REPORT.md);
- [LINEAR_ALGEBRA_SOLVE_MATRIX_V1_REPORT](LINEAR_ALGEBRA_SOLVE_MATRIX_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_LU_V1_REPORT](LINEAR_ALGEBRA_GENERIC_LU_V1_REPORT.md);
- [LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md).

## API final y deduplicación

Los ocho overloads concretos fueron reemplazados por exactamente cuatro
declaraciones e implementaciones source:

```aether
Vector<T,Column> solve<T: IEEEFloat>(Matrix<T> A, ref Vector<T,Column> b);
Vector<T,Column> solve<T: IEEEFloat>(ref LU<T> factor, ref Vector<T,Column> b);
Matrix<T> solve<T: IEEEFloat>(Matrix<T> A, ref Matrix<T> B);
Matrix<T> solve<T: IEEEFloat>(ref LU<T> factor, ref Matrix<T> B);
```

No quedan kernels, wrappers, casts ni ramas por `float32`/`float64`. QR no fue
modificado. `SingularMatrixException` continúa siendo una única declaración.

## Contratos numéricos y de shapes

Las rutas que consumen `Matrix<T> A` conservan sus guards iniciales, llaman una
sola vez a `lu(A)` y delegan al overload de factor. Las rutas `ref LU<T>`
mantienen los cinco guards originales y su orden antes de allocation o acceso.

El solve vectorial conserva un único `Vector<T,Column>` para `Pb`, `Y` y `X`.
El solve matricial conserva una única `Matrix<T>` para `PB`, `Y` y `X`, con los
loops row-major originales `i/j/c`; no materializa `P`, vectores por columna ni
copias de los factores. Los casos `0×0` y `n×0` preservan sus shapes y backing
vacío. En particular, el pivot de `U` se comprueba fuera del loop de columnas,
por lo que un RHS `n×0` singular sigue lanzando.

La singularidad continúa definida sólo por igualdad IEEE exacta con cero y
lanza `SingularMatrixException`; no se añadieron tolerancias ni comprobaciones
de NaN/infinito. El dominio público sigue siendo `T: IEEEFloat`. El HIR
paramétrico usa `Zero`, `Equal`, `Sub`, `Mul` y `Div`.

## Ownership, allocations y lowering

`A` se consume; los RHS y los factores se prestan y sobreviven tanto al retorno
como al unwind. No se mueven ni clonan `L`, `U` o `permutation`. La ruta factor
vectorial conserva una allocation sólo si `n>0`; la matricial, una sólo si
`n*q>0`. Las rutas Matrix agregan únicamente las allocations propias de LU.

Las instancias concretas sustituyen `T` antes de MIR. MIR/SSA contienen sólo
tipos float concretos y LLVM emite instancias separadas para `float32` y
`float64`, sin witnesses, vtables, `TypeId` ni llamadas numéricas indirectas.

Por la política vigente de inferencia antes de borrow adaptation, los usos con
`var` que reciben un factor y no tienen expected result califican `T`, por
ejemplo `solve<float64>(factor, b)`. Las llamadas con resultado tipado y las
rutas que consumen `Matrix<T>` continúan infiriendo `T` desde los argumentos.

## Qualification

Las suites versionadas de solve vectorial y matricial cubren ambas precisiones,
shapes, permutación, reutilización, allocations, singularidad catchable,
limpieza en unwind y RHS matricial vacío. La calificación genérica comprueba
además deduplicación source, forwarding paramétrico, operaciones capability en
HIR, eliminación de residuos genéricos en MIR/SSA y emisión LLVM concreta.

Comandos de validación:

```text
aether check linearAlgebra
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_solve_v1
cargo test -p aether-driver --test linear_algebra_solve_matrix_v1
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

## Fuera de scope

No se migró QR ni se cambió el método LU, la política de inferencia, el modelo
de singularidad, el layout, las tolerancias o el soporte para `Complex`.
