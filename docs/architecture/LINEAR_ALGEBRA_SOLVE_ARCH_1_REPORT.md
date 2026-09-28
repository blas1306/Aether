# LINEAR-ALGEBRA-SOLVE-ARCH-1 — reporte de arquitectura

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Autoridad normativa:
[LINEAR-ALGEBRA-SOLVE-ARCH-1](LINEAR_ALGEBRA_SOLVE_ARCH_1.md).

Este reporte cierra el milestone documental. No registra una implementación y
no modifica `linearAlgebra`, el compilador, el runtime ni sus tests.

## Resultado

`solve` V1 queda limitado a sistemas reales square no singulares con un único
RHS `Vector<T,Column>`, para `float32` y `float64`. No mezcla square solve con
least squares, sistemas underdetermined, selección de método o RHS Matrix.

La superficie cerrada es:

```aether
class SingularMatrixException : Exception {
    public init() {}
}

Vector<float64,Column> solve(
    Matrix<float64> A,
    ref Vector<float64,Column> b);
Vector<float32,Column> solve(
    Matrix<float32> A,
    ref Vector<float32,Column> b);
Vector<float64,Column> solve(
    ref LU<float64> factor,
    ref Vector<float64,Column> b);
Vector<float32,Column> solve(
    ref LU<float32> factor,
    ref Vector<float32,Column> b);
```

Los cuatro overloads usan el nombre `solve`. No hay genérico ficticio,
`solveFloat32`, `solveLU` ni parámetro `method`.

## Dominio y shapes

Se requiere `A : n×n`, `b` Column de longitud `n` y matriz no singular. Una LU
recibida debe tener `L` y `U` square `n×n`, permutación de longitud `n` y el
contrato semántico publicado por LU V1. Una LU rectangular producida por `lu`
es válida como factorización, pero no como argumento de `solve`.

`0×0` con Column vacío es válido y devuelve un Column owner vacío sin backing.
`1×1` divide normalmente si el único valor es no cero y lanza por `+0.0` o
`-0.0`. Identidad, matrices triangulares, permutaciones no triviales y RHS cero
usan el mismo algoritmo sin fast paths públicos.

Matrix/Vector conservan extents runtime: V1 no puede prometer diagnóstico
estático de square o length en una call ordinaria. Row, precisiones mezcladas y
tipos no soportados sí se rechazan estáticamente con el diagnóstico de no
matching overload `E0460`; no hay conversión implícita de orientación o tipo.

Los mismatches dinámicos de shape producen `ShapeMismatch` antes de
factorización, allocation, acceso o división. La auditoría encontró un bloqueo
real: package source no puede emitir hoy ese trap general ni transportar una
precondición de shape al call site. El vertical de implementación debe estar
precedido por una capacidad general mínima de guard de shape; quedan prohibidos
un intrinsic `solve`, compiler magic de álgebra lineal y una multiplicación
dummy usada sólo para trapear.

## Ownership y reutilización

`solve(A,b)` consume `A` para que `lu(A)` recicle su backing; no existe copia
defensiva oculta. `b` es un préstamo shared, queda intacto y reutilizable, y el
resultado es un owner independiente.

`solve(factor,b)` presta la `LU<T>` completa mediante `ref`. Las proyecciones de
`permutation`, `L` y `U` no se mueven, copian ni retienen. Por tanto:

```aether
LU<float64> factor = linearAlgebra.lu(A);
Vector<float64,Column> x1 = linearAlgebra.solve(factor, b1);
Vector<float64,Column> x2 = linearAlgebra.solve(factor, b2);
```

reutiliza la misma factorización sin recomputar y deja `factor`, `b1` y `b2`
intactos. El borrow implícito exacto de BORROW-ERGONOMICS-V1 permite esa sintaxis
sin Alias, Clone, owner o allocation adicional.

No se aceptan VectorView en V1. Admitirlos después será una extensión aditiva;
el owner RHS ya se presta y no se consume.

## Algoritmo

Para `P A=L U`, todos los índices son 1-based y un único vector resultado `w`
cumple tres papeles:

```text
w[i] = b[permutation[i]]

para i = 1..n:
    w[i] = w[i] - sum(j=1..i-1, L[i,j] * w[j])

para i = n..1:
    si U[i,i] == 0: throw SingularMatrixException()
    w[i] = (w[i] - sum(j=i+1..n, U[i,j] * w[j])) / U[i,i]
```

No se divide por `diag(L)=1`, no se materializa `P` y el loop descendente evita
underflow de `usize`. `solve(A,b)` valida, factoriza exactamente una vez y
delega en esta ruta; no duplica el kernel.

## Singularidad

Un pivot diagonal de `U` exactamente cero bajo igualdad IEEE, incluido
`-0.0`, lanza la excepción nominal y capturable
`SingularMatrixException`. Singularidad no es `ShapeMismatch`, bounds trap ni
outcome `Option`/`Result`.

No se usa tolerancia. Una matriz casi singular con diagonal no cero se resuelve
normalmente aunque el error sea grande. NaN/Inf siguen la aritmética IEEE y no
reciben política especial.

V1 no clasifica un sistema singular como compatible o incompatible: ambos
lanzan la misma excepción y no producen solución parcial observable. Durante
unwind se limpia el workspace y, en el overload directo, el factor temporal;
una LU y un RHS prestados permanecen reutilizables después del catch.

## Costos

Desde una matriz square de orden `n`:

- O(n³) por LU más O(n²) por gather y sustituciones;
- LU asigna permutación y un segundo factor, reciclando el backing de `A`;
- solve asigna un solo Vector resultado para `n>0`;
- no copia `b`, `L` o `U` y no materializa `P`.

Desde una LU:

- O(n²) tiempo;
- una allocation para el Vector resultado no vacío, cero para longitud cero;
- O(1) workspace escalar fuera del resultado;
- ninguna refactorización, copia completa o allocation asociada al borrow.

Después de una LU, resolver `k` vectores cuesta O(k n²), con un resultado por
call. El mismo owner resultado contiene sucesivamente `P b`, `y` y `x`.

## Múltiples RHS y extensibilidad

`solve(A,B)` y `solve(factor,B)` con `B : n×q` quedan explícitamente para V2.
La extensión devolverá `X : n×q`, costará O(n²q) desde factor y podrá reutilizar
la misma LU por columnas. Deberá validar singularidad incluso para `q=0`; la
recomendación es que un factor no singular produzca `n×0`.

El nombre `solve` queda extensible por tipos de factor. Cholesky y QR futuros
podrán agregar overloads sobre sus propios factores y contratos. Los métodos
iterativos tendrán configuración/resultado propios. V1 no congela una mega API
ni promete cambiar silenciosamente el método de `solve(A,b)`, que es LU con
pivoting parcial.

## Calificación futura

El vertical de implementación debe cubrir `float32` y `float64`, O0/O2,
identidad, diagonal, triangulares, swaps simples/múltiples, RHS cero, casos
aleatorios pequeños con solución conocida, residual `||Ax-b||`, `0×0`, `1×1`,
singular compatible/incompatible, casi singular, reutilización de LU, shapes
incorrectos y rechazos de orientación/tipo.

La calificación estructural debe probar una sola llamada a `lu`, una sola
allocation vectorial desde factor no vacío, cero en el vacío, préstamos sin
copia/consumo, cleanup excepcional, guards antes de efectos y ausencia de `P`,
productos dummy, copia de factores o intrinsic `aether_solve`.

## Orden recomendado

1. Calificar un guard general de shape para package source, separado de solve.
2. Agregar la excepción y los overloads desde LU prestada.
3. Implementar guards, gather y sustituciones para ambos tipos.
4. Agregar los overloads owning Matrix que llaman `lu` una vez y delegan.
5. Ampliar consumer, pruebas de diagnostics/IR/allocations/unwind y O0/O2.
6. Ejecutar la suite completa y publicar un reporte de implementación separado.

## Fuera de scope

Quedan fuera determinant, inverse, rank/condición, RHS Matrix, VectorView,
least squares, underdetermined solve, QR/Cholesky solve, sparse e iterativos,
selección de método, variantes in-place, solución de sistemas singulares,
tolerancias, `Complex<T>` y BLAS/LAPACK.

No quedan decisiones arquitectónicas abiertas dentro del dominio V1. El guard
general de shape es un prerequisito explícito de implementación, no una razón
para rediseñar `LU<T>` ni para introducir una ruta privilegiada de solve.
