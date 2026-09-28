# LINEAR-ALGEBRA-SOLVE-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [LINEAR-ALGEBRA-SOLVE-ARCH-1](LINEAR_ALGEBRA_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-SOLVE-ARCH-1-REPORT](LINEAR_ALGEBRA_SOLVE_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [SHAPE-GUARD-V1](SHAPE_GUARD_V1_REPORT.md).

## Resultado

El package ordinario `linearAlgebra` publica `SingularMatrixException` y los
cuatro overloads cerrados de `solve`: matriz owning o `ref LU`, RHS
`ref Vector<T,Column>` y precisiones `float64`/`float32`. No se agregaron
nombres alternativos, método seleccionable, overload genérico, RHS Matrix ni
RHS view.

Los overloads de Matrix validan primero que `A` sea square y que el RHS tenga
la longitud correcta. Luego consumen `A`, llaman una vez a `lu(A)` y delegan al
overload de factor de su precisión. Los overloads de LU preservan el orden
normativo de cinco `shapeGuard`: square de `L`, square de `U`, orden común,
longitud de permutación y longitud del RHS. Todos preceden la allocation y los
accesos.

## Kernel y singularidad

Cada precisión asigna un solo `Vector<T,Column>` y lo reutiliza como `P b`,
`y` y `x`. La permutación se aplica mediante gather; no se materializa `P`. La
sustitución forward usa la diagonal unitaria de `L` sin leerla ni dividir por
ella. La sustitución backward termina en `i=1` sin underflow de `usize`.

Inmediatamente antes de cada división se compara el pivot con cero exacto de
su precisión. Tanto `+0.0` como `-0.0` lanzan
`SingularMatrixException`; no se usa tolerancia. NaN, infinito y pivots no cero
arbitrariamente pequeños conservan la aritmética IEEE ordinaria.

El caso de orden cero pasa los guards y devuelve un Column owner vacío. El
filled-init vacío no crea backing, de modo que resolver desde una LU vacía no
realiza allocations.

## Ownership y cleanup

`solve(A,b)` consume el owner `A`; el frontend diagnostica cualquier uso
posterior como use-after-move. `solve(factor,b)` sólo proyecta a través de los
dos préstamos shared, sin mover ni copiar `permutation`, `L` o `U`. El consumer
reutiliza una misma LU con dos RHS y comprueba que factor y vectores permanecen
intactos.

La calificación nativa instrumentada comprueba balance de allocations/frees al
capturar singularidad tanto desde una LU prestada como desde el overload
directo. Por tanto el unwind limpia el workspace único y, en la ruta directa,
la LU temporal; los owners prestados siguen disponibles en el handler.

## Calificación

El consumer independiente cubre ambas precisiones en O0/O2: identidad,
diagonal, triangulares superior e inferior, swaps, RHS cero, un sistema pequeño
arbitrario con solución conocida, residual, orden cero, `1×1`, singularidad
compatible e incompatible, pivot casi singular no cero y reutilización de LU.

La prueba `aether-driver/tests/linear_algebra_solve_v1.rs` fija además:

- exactamente cuatro overloads y una excepción pública;
- consumo de Matrix y préstamos reutilizables de LU/RHS;
- `ShapeMismatch` para Matrix/LU rectangular y RHS incompatible;
- `E0460` para Row, precisiones mezcladas y tipos no soportados;
- `ShapeGuard` y `VectorFilled` visibles en HIR/MIR/SSA;
- una sola allocation adicional desde LU no vacía y cero en orden cero;
- cleanup de workspace y factor temporal por unwind;
- ausencia de helper/intrinsic `aether_solve`.

No se modificaron parser, HIR, MIR, SSA, optimizadores, backend ni runtime.

## Fuera de scope

No se implementaron determinant, inverse, RHS Matrix, VectorView RHS, least
squares, sistemas underdetermined, QR/Cholesky solve, métodos iterativos ni
estimación de condición.
