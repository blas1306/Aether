# LINEAR-ALGEBRA-SOLVE-MATRIX-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [LINEAR-ALGEBRA-SOLVE-MATRIX-ARCH-1](LINEAR_ALGEBRA_SOLVE_MATRIX_ARCH_1.md);
- [LINEAR-ALGEBRA-SOLVE-MATRIX-ARCH-1-REPORT](LINEAR_ALGEBRA_SOLVE_MATRIX_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SOLVE-V1](LINEAR_ALGEBRA_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [SHAPE-GUARD-V1](SHAPE_GUARD_V1_REPORT.md).

## Resultado

El package ordinario `linearAlgebra` publica los cuatro overloads Matrix
cerrados para `float64` y `float32`, tanto desde una Matrix owning como desde
una `ref LU`. Coexisten con los cuatro overloads vectoriales sin modificarlos:
hay exactamente ocho declaraciones `solve` y no se agregaron aliases,
genéricos falsos, selector de método ni RHS `MatrixView`.

La ruta owning comprueba primero que `A` sea square y después que las filas de
`B` coincidan. Consume `A`, factoriza exactamente una vez y delega en el
overload desde LU. `B` se presta shared y permanece intacta.

## Kernel Matrix desde LU

Cada precisión ejecuta los cinco `shapeGuard` normativos, en orden, antes de
allocation o accesos: `L` square, `U` square, orden común, dimensión de la
permutación y filas del RHS. Luego crea una única `Matrix<T> W` de shape
`n×q`, usada sucesivamente como `P B`, `Y` y `X`.

La permutación se aplica por gather, sin materializar `P`. Forward y backward
substitution recorren `i`, `j`, `c`, dejando contiguo el loop de columnas. No
se lee la diagonal unitaria de `L`. Backward substitution carga y compara el
pivote exacto de `U` antes de los loops dependientes de `q`, por lo que una LU
singular lanza `SingularMatrixException` incluso para un RHS `n×0`.

No existen owners separados para `P B`, `Y` o `X`, copias de `L`/`U`, ni un
helper o intrinsic `aether_solve_matrix`. Una LU prestada se reutiliza con
múltiples Matrix RHS, con el solve vectorial y con `det`.

## Shapes vacías, allocations y unwind

`0×0 + 0×0` conserva `0×0`; `0×0 + 0×q` conserva `0×q`; una LU no singular
`n×n + n×0` conserva `n×0`. `matrixFilled` no crea backing cuando el producto
de extents es cero. Para un resultado no vacío, el kernel desde LU agrega una
sola allocation: la Matrix devuelta.

La calificación nativa instrumentada comprueba balance de allocations y frees
en éxito y durante unwind por singularidad. El workspace se limpia y el factor
y RHS prestados siguen utilizables después del `catch`.

## Calificación

El consumer independiente cubre ambas precisiones en O0/O2: identidad,
diagonal, triangulares, pivoting con múltiples swaps, `B=A*XKnown`, solución
conocida, residual, `q=1` contra solve vectorial, `q>1`, `q=0`, `n=0`, `1×1`,
singularidad con RHS vacío y no vacío, reutilización de LU, `det` y preservación
del RHS.

La prueba
`aether-driver/tests/linear_algebra_solve_matrix_v1.rs` fija además:

- exactamente cuatro overloads Matrix y ocho overloads `solve` totales;
- consumo de `A` y préstamos reutilizables de factor/RHS;
- `ShapeMismatch` para Matrix rectangular, RHS incompatible y cada
  inconsistencia estructural de LU, antes de singularidad;
- `E0460` para precisión mezclada, elemento no soportado y `MatrixView` RHS;
- `ShapeGuard` y `MatrixFilled` visibles en HIR/MIR/SSA;
- una allocation de resultado no vacío y cero backing para extents vacíos;
- singularidad para `q=0`, cleanup excepcional y reutilización tras unwind;
- ausencia de `aether_solve_matrix` y de cambios en compiler/runtime.

Validación ejecutada:

```text
aether check linearAlgebra                         PASS
aether check linearAlgebra/tests/consumer          PASS
aether run linearAlgebra/tests/consumer -O0        PASS
aether run linearAlgebra/tests/consumer -O2        PASS
cargo test -p aether-driver \
  --test linear_algebra_solve_matrix_v1             PASS
cargo test -p aether-driver \
  --test linear_algebra_solve_v1 \
  --test linear_algebra_det_v1 \
  --test linear_algebra_lu_v1 \
  --test linear_algebra_constructors_v1             PASS
cargo test -p aether-registry --test registry \
  linear_algebra_oal_publishes_and_runs_real_qr_consumer
                                                    PASS
```

## Fuera de scope

No se implementaron inverse, RHS view, solve in-place, least squares,
underdetermined solve, QR/Cholesky/sparse/iterativo, rank/condición,
`Complex<T>` ni BLAS/LAPACK.
