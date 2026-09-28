# LINEAR-ALGEBRA-SOLVE-MATRIX-ARCH-1 — reporte de arquitectura

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Autoridad normativa:
[LINEAR-ALGEBRA-SOLVE-MATRIX-ARCH-1](LINEAR_ALGEBRA_SOLVE_MATRIX_ARCH_1.md).

Autoridad relacionada:

- [LINEAR-ALGEBRA-SOLVE-ARCH-1](LINEAR_ALGEBRA_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-SOLVE-V1](LINEAR_ALGEBRA_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [SHAPE-GUARD-V1](SHAPE_GUARD_V1_REPORT.md).

Este reporte cierra el milestone documental. No registra una implementación y
no modifica `linearAlgebra`, el compilador, el runtime ni los tests.

## Resultado

Se cerró la extensión de `solve` para `A X=B`, con `A:n×n`, `B:n×q` y
resultado `X:n×q`, exclusivamente para `float64` y `float32`. La superficie
nueva consta de cuatro overloads:

```aether
Matrix<float64> solve(Matrix<float64> A, ref Matrix<float64> B);
Matrix<float32> solve(Matrix<float32> A, ref Matrix<float32> B);
Matrix<float64> solve(ref LU<float64> factor, ref Matrix<float64> B);
Matrix<float32> solve(ref LU<float32> factor, ref Matrix<float32> B);
```

Todos conservan el nombre `solve`. No se incorporan `solveMatrix`,
`solveMultiple`, selector `method` ni un genérico falso. El segundo argumento
`Matrix` los distingue sin ambigüedad de los cuatro overloads vectoriales
existentes; tipo del primer argumento y precisión completan la resolución.

## Ownership y reutilización

`solve(A,B)` consume `A`, por lo que `lu(A)` puede reciclar su backing sin una
copia defensiva. `B` se presta shared y permanece intacta. La ruta valida,
factoriza exactamente una vez y delega en el overload desde LU.

`solve(factor,B)` presta shared tanto la LU como el RHS. No mueve, copia ni
modifica `permutation`, `L`, `U` o `B`. Devuelve una Matrix owner nueva, usada
internamente como único workspace. Una misma factorización puede resolver
múltiples matrices y vectores RHS y alternarse con `det(factor)` sin
refactorización ni materialización de `P`.

`ref Matrix<T>` es suficiente para V1: el algoritmo sólo consulta extents y
lee elementos durante el gather. `MatrixView` no aporta una capacidad necesaria
y queda como futura extensión aditiva, evitando duplicar ahora la superficie y
la política de owners/views.

## Shapes y fallos

La ruta owning exige primero `rows(A)=columns(A)` y después `rows(B)=rows(A)`.
La ruta de factor exige, en orden, `L` square, `U` square, igual orden de ambos,
permutación de longitud `n` y `rows(B)=n`. Todos los `shapeGuard` preceden la
allocation y los accesos. Una violación produce `ShapeMismatch`, con
precedencia sobre singularidad.

No se revalidan triangularidad, diagonal unitaria de `L` o biyección de la
permutación, que son invariantes de una LU legítima. Una LU rectangular o con
extents incoherentes sí falla siempre mediante los guards publicados.

Las mezclas de precisión, tipos no soportados y Matrix/Vector/View incorrectos
se rechazan por resolución ordinaria de overload, sin diagnostics especiales
de álgebra lineal.

## Decisión de `q=0`

La ausencia de columnas RHS no elimina la precondición de que el sistema sea
no singular. Para `B:n×0`:

- un factor no singular devuelve `X:n×0` sin backing;
- un factor singular lanza `SingularMatrixException`;
- con `n=0` no existen pivots y cualquier `B:0×q` devuelve `X:0×q`.

El check de `U[i,i]` queda fuera del loop de columnas y se ejecuta una vez por
fila incluso cuando `q=0`. Así singularidad sigue siendo propiedad del factor,
coincide con la semántica anticipada por SOLVE-ARCH-1 y no depende de la
cantidad de RHS.

## Algoritmo y layout

Para `P A=L U`, una única Matrix `W:n×q` se inicializa mediante:

```text
W[i,c] = B[permutation[i],c]
```

sin construir `P`. Después se resuelven en sitio `L Y=P B` y `U X=Y` mediante
actualizaciones de filas. El orden elegido para ambas sustituciones es fila
objetivo `i` exterior, fila dependiente `j` intermedia y columna RHS `c`
interior. Matrix es row-major: este orden recorre contiguamente las filas de
`W`, reutiliza cada coeficiente `L[i,j]` o `U[i,j]` sobre todos los RHS y evita
el stride de resolver una columna completa por vez.

Backward substitution revisa primero `U[i,i] == 0` exacto, actualiza la fila y
la divide por ese pivot. El descenso evita underflow. Para cada RHS, `j`
mantiene el mismo orden ascendente de restas que el solve vectorial.

No se crean matrices separadas para `P B`, `Y` y `X`, no se cambia el layout de
Matrix y no se agregan transposes, views, blocking o intrinsics.

## Singularidad

El contrato coincide con el solve vectorial: un pivot exactamente cero,
incluidos `+0.0` y `-0.0`, lanza `SingularMatrixException`. No hay tolerancia,
estimación de rank/condición ni `Result`/`Option`. NaN, infinito y pivots no
cero arbitrariamente pequeños siguen la aritmética IEEE ordinaria.

La excepción se comprueba una vez por fila, no una vez por RHS. En unwind se
limpia el único workspace y los owners prestados permanecen reutilizables.

## Costos y allocations

Desde Matrix, el tiempo es O(n³+n²q): una LU más gather y sustituciones. Desde
LU, para `q>=1` es O(n²q). La forma general precisa es O(n+n²q), porque el
contrato singular obliga a inspeccionar n pivots aun con `q=0`; ese caso cuesta
O(n) deliberadamente.

Desde LU se asigna exactamente una Matrix resultado cuando `n*q>0`. Si `n=0`
o `q=0`, se conserva la shape del descriptor pero no se asigna backing. El
workspace adicional es O(1). No se copian factor o RHS y no existen `P`, `P B`,
`Y` o `X` como owners separados.

## Interacción con solve vectorial

Los overloads vectoriales no cambian. Una Matrix `n×1` y un Vector Column de
longitud `n` deben producir valores concordantes dentro de la tolerancia de su
precisión, pero cada uno conserva su tipo de resultado y kernel sin temporales
de conversión.

La selección continúa inequívoca:

```text
solve(A, vector)       -> Vector
solve(A, matrix)       -> Matrix
solve(factor, vector)  -> Vector
solve(factor, matrix)  -> Matrix
```

## Casos cerrados y calificación futura

Quedan definidos `0×0 + 0×0`, `0×0 + 0×q`, `n×n + n×0`, `1×1` con múltiples
columnas, identidad, diagonal, triangulares, swaps, singularidad, filas de RHS
incompatibles, LU rectangular/inconsistente y ambas precisiones.

El futuro vertical deberá probar en O0/O2 identidad con varios RHS, diagonal,
triangulares, swaps, `B=A*XKnown`, residual, `q=1` contra solve vectorial,
`q>1`, todos los vacíos anteriores, singular con `q>0` y `q=0`, reutilización
de LU y coexistencia con solve vectorial y det.

La calificación estructural deberá fijar una única allocation no vacía desde
LU, cero backing para producto de extents cero, guards antes de efectos,
préstamos preservados, cleanup excepcional, loops row-major, una sola llamada a
LU en la ruta owning y ausencia de `P`, copias de factores e intrinsic
`aether_solve_matrix`.

## Orden de implementación

1. Agregar los dos overloads desde LU y sus cinco guards por precisión.
2. Implementar una única `W`, gather y sustituciones row-major.
3. Mantener el check diagonal fuera del loop RHS y calificar `q=0`/unwind.
4. Agregar las dos rutas owning que validan, factorizan una vez y delegan.
5. Ampliar consumer y pruebas de diagnostics, IR, allocations y convivencia en
   O0/O2.
6. Ejecutar la suite completa y emitir un reporte de implementación separado.

## Futuro y fuera de scope

Una futura `inverse(A)` podría reutilizar conceptualmente
`solve(A,identity(n))`; no forma parte de este milestone y no se implementa.
También quedan fuera MatrixView RHS, variantes in-place, least squares,
underdetermined solve, QR/Cholesky/sparse/iterativos, rank/condición,
`Complex<T>`, tolerancias y BLAS/LAPACK.

No quedan decisiones arquitectónicas abiertas dentro del dominio de múltiples
RHS. Este milestone no modifica código.
