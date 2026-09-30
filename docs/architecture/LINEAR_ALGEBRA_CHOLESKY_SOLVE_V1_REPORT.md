# LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1 — reporte de implementación

## Resultado

`linearAlgebra` incorpora solve reutilizable desde un factor Cholesky real como
código source ordinario. La implementación no modifica las rutas existentes
desde `Matrix<T>` o `LU<T>`, ni agrega soporte especial al compilador.

## API

Se agregaron exactamente estos overloads:

```aether
Vector<T,Column> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Matrix<T> B);
```

No se agregaron wrappers por precisión, variantes `InPlace` ni selector de
algoritmo. Ambos argumentos son shared borrows y el resultado es owning e
independiente.

## Guards y política del factor

El overload Vector ejecuta, en orden, el guard de cuadratura de `factor.L` y el
guard `dimension(b) == rows(factor.L)`. El overload Matrix ejecuta el mismo
primer guard y luego `rows(B) == rows(factor.L)`. Todos ocurren antes de crear el
workspace, indexar o hacer aritmética. Sólo después se leen `n` y, para Matrix,
`q`.

`solve` no revalida el factor. No inspecciona por separado diagonal, finitud,
triangularidad, upper físico, SPD ni procedencia. Un `Cholesky<T>` construido
manualmente que satisface shape entra directamente a los loops IEEE. Por ello
estos overloads no lanzan `SingularMatrixException`,
`NotPositiveDefiniteException` ni una excepción nueva de factor inválido.

## Algoritmo Vector

Se crea un único `Vector<T,Column> w` de longitud `n`, lleno de `Zero`. El mismo
owner almacena primero `y` durante forward substitution y luego `x` durante
backward substitution.

Forward recorre `i` creciente y, por cada celda, carga `b[i]`, acumula en `j`
creciente con `value = value - L[i,j] * w[j]`, divide una vez por `L[i,i]` y
almacena. Backward usa el patrón descendente seguro para `usize`; carga `w[i]`,
recorre `j` creciente desde `i+1`, lee exclusivamente `L[j,i]`, divide una vez
por `L[i,i]` y reemplaza `w[i]`. Para `n == 0` el loop descendente no entra.

## Algoritmo Matrix

Se crea una única `Matrix<T> W` de shape `n×q`, llena de `Zero`. No existe
Vector temporal ni delegación por columna. Forward y backward respetan el orden
contractual `i/c/j`. Cada celda carga primero el RHS actual, ejecuta en `j`
creciente un `Mul` seguido de `Sub`, hace una única `Div` final y almacena.
Backward lee exclusivamente `factor.L[j,i]`; nunca materializa `L^T` y nunca
consulta el upper físico.

## Shapes cero

- `L 0×0` y Vector de longitud cero producen Vector de longitud cero sin
  backing.
- `L 0×0` y `B 0×q` producen `0×q`, preservan `q` y no crean backing.
- `L n×n` y `B n×0` producen `n×0`, preservan `n`, no leen la diagonal, no
  ejecutan aritmética y no crean backing.
- Cualquier incompatibilidad llega a `ShapeMismatch` antes de allocation o
  acceso.

## Orden numérico y capabilities

El orden por celda es literal: carga del RHS, `j` creciente, `Mul`, `Sub`, una
única `Div` y store. No hay reassociation, FMA contractual, acumulador promovido,
reducción paralela, tolerancia ni refinamiento iterativo. El body paramétrico
usa sobre `T` sólo `Zero`, `Mul`, `Sub` y `Div`; la frontera pública permanece
`T: IEEEFloat`.

## Ownership y allocations

El factor y el RHS sólo se leen. No se hace move, clone, alias, retain, COW ni
copia de sus backings. El mismo factor puede resolver múltiples RHS Vector y
Matrix en cualquier orden y todos los inputs permanecen utilizables.

Vector crea exactamente un backing de resultado si `n > 0` y ninguno si
`n == 0`. Matrix crea exactamente un backing si `n*q > 0` y ninguno si el
producto es cero. No se crean transpose, factor copy, RHS copy, Matrix auxiliar,
Vector adicional, owner por columna ni tabla de pivots.

## HIR, MIR y SSA

La funcionalidad vive enteramente en `linearAlgebra/src/lib.ae`. HIR conserva
los shared borrows, guards, una construcción de resultado, loops/indexing y las
cuatro capabilities permitidas. Después de monomorphization, MIR/SSA contienen
operaciones concretas float32/float64, branches e indexing, sin parámetros
genéricos, nodos de capability, transpose, TypeId, witness, boxing o dispatch
indirecto. No se agregó opcode, intrinsic, builtin, helper runtime ni
reconocimiento nominal del compilador.

## Qualification

La suite `linear_algebra_cholesky_solve_v1` califica en O0 y O2:

- API, guards y estructura literal de ambos kernels;
- HIR/MIR/SSA y ausencia de residuos genéricos o transpose;
- float32 y float64, factor reutilizable, Vector/Matrix mezclados, comparación
  con LU e inputs intactos;
- `0×0`, `0×q` y `n×0`;
- precedencia de `ShapeMismatch` para L rectangular y RHS incompatibles;
- conteo exacto de allocations/backings;
- aggregates manuales con diagonal `+0`, `-0`, negativa, NaN, `+Inf`, `-Inf`,
  upper no cero y lower no canónico;
- invariancia del resultado ante cambios arbitrarios del upper físico.

El consumidor del package además resuelve dos vectores y una matriz con el
mismo factor, imprime el factor y los resultados, comprueba residual, compara
contra LU y cubre ambas precisiones.

## Fuera de scope

No se implementaron solve Cholesky automático desde Matrix, selector de método,
determinante o inverse por Cholesky, Complex, triangular packed, views RHS,
solve in-place, BLAS/LAPACK ni refinamiento iterativo.
