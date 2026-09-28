# LINEAR-ALGEBRA-LU-ARCH-1 — reporte de arquitectura

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Autoridad normativa:
[LINEAR_ALGEBRA_LU_ARCH_1](LINEAR_ALGEBRA_LU_ARCH_1.md).

Este reporte cierra el milestone documental de arquitectura. No registra una
implementación ni modifica `linearAlgebra`, el compilador, el runtime o sus
tests. El futuro vertical de implementación tendrá un reporte independiente.

## Resultado

LU V1 acepta `Matrix<float32>` y `Matrix<float64>` de cualquier shape runtime
rectangular `m×n`. No promete soporte genérico basado sólo en `Storable`, porque
la factorización necesita `abs`, comparación, división y aritmética flotante.

Con `r = min(m,n)`, el resultado satisface:

```text
P A = L U
L : m×r, trapezoidal inferior y con diagonal unitaria
U : r×n, trapezoidal superior
P : m×m, representada mediante una permutación de filas
```

La API cerrada es:

```aether
struct LU<T: Storable> {
    Vector<usize,Column> permutation;
    int permutationSign;
    Matrix<T> L;
    Matrix<T> U;
}

LU<float64> lu(Matrix<float64> A);
LU<float32> lu(Matrix<float32> A);
```

Ambos overloads usan el nombre público `lu`; no se expone el algoritmo como
`luPartialPivoting` ni se crea un nombre especial para `float32`.

## Permutación y paridad

`permutation` es un vector owning 1-based de longitud `m`, inicialmente
`[1,2,...,m]`, cuya dirección normativa es:

```text
(P A)[i,j] = A[permutation[i],j]
(P b)[i]   = b[permutation[i]]
P[i,permutation[i]] = 1
```

Por lo tanto no hay ambigüedad con la permutación inversa. Cada swap de filas
intercambia las entradas correspondientes del vector.

`permutationSign` vale `+1` o `-1`, comienza en `+1` y cambia de signo por cada
swap real. Representa `det(P)`. Para una factorización square permite calcular:

```text
det(A) = permutationSign * product(diag(U))
```

No se materializa una `P` densa: ocuparía O(m²), mientras la representación
vectorial ocupa O(m), permite aplicar `P` por gather y conserva la paridad en
O(1). Una materialización futura será explícita.

## Storage y algoritmo

La API materializa `L` y `U` por separado. Durante la factorización, el owner
`A` funciona como workspace packed: `U` ocupa la diagonal y parte superior, los
multiplicadores de `L` viven debajo de la diagonal y los unos de `L` son
implícitos. Esta representación no forma parte del contrato público.

Al finalizar se recicla el backing de `A` como uno de los factores y se asigna
el otro factor de shape `r×r`:

- si `m <= n`, `A` se convierte en `U` y se materializa `L`;
- si `m > n`, `A` se convierte en `L` y se materializa `U`.

En cada paso `k`, el pivot es la fila de mayor `abs(A[i,k])` para `i >= k`.
Los empates conservan la fila de menor índice porque sólo una magnitud
estrictamente mayor reemplaza al candidato. Se intercambia la fila packed
completa, incluyendo multiplicadores de pasos anteriores. No hay complete,
rook, scaled ni threshold pivoting.

Los row swaps recorren las `n` columnas con un temporal escalar. Cada swap
cuesta O(n) tiempo y O(1) storage extra. Los slices actuales son views; usarlos
como temporal dejaría aliasing, y materializar una fila agregaría una allocation
innecesaria. No se requiere una primitiva especial del compilador.

## Singularidad y valores especiales

Un pivot IEEE exactamente cero, incluido `-0.0`, hace que se omitan la división
y la actualización de ese paso. `lu(A)` devuelve factores también para matrices
square singulares: no trapea, no devuelve un outcome y no introduce una
tolerancia.

Una matriz casi singular cuyo pivot sea distinto de cero se factoriza
normalmente. LU V1 no estima rank ni condición. NaN e infinito usan las
operaciones IEEE ordinarias y no reciben un contrato especial.

## Shapes degenerados

Las shapes económicas quedan cerradas así:

| entrada | `permutation` | `L` | `U` | signo inicial/final sin swaps |
|---|---:|---:|---:|---:|
| square `n×n` | `n` | `n×n` | `n×n` | `+1` |
| tall `m×n` | `m` | `m×n` | `n×n` | `+1` |
| wide `m×n` | `m` | `m×m` | `m×n` | `+1` |
| `0×0` | `0` | `0×0` | `0×0` | `+1` |
| `m×0` | `m` | `m×0` | `0×0` | `+1` |
| `0×n` | `0` | `0×0` | `0×n` | `+1` |

En shapes vacíos no se ejecutan pivots. Filled-init conserva metadata de shape
sin asignar backing cuando el número de celdas es cero.

## Preparación para operaciones futuras

La representación permite implementar `solve` square aplicando primero
`b[permutation[i]]`, seguido de sustitución forward con `L` y backward con `U`.
También permite implementar `det` con `permutationSign` y `diag(U)`. Ninguna
operación necesita materializar `P` ni cambiar la representación de `LU<T>`.

Este milestone no define el outcome de `solve` singular, políticas de overwrite
del RHS ni una API pública para materializar o aplicar permutaciones.

## Costos

Para `r = min(m,n)`:

- tiempo de factorización: O(m·n·r), aproximadamente `2/3 n³` en square;
- búsqueda, swaps y materialización square: O(n²);
- storage público: `m*r + r*n` elementos de `T`, `m` índices y un signo;
- allocations internas nuevas: un factor `r×r` y el vector de permutación,
  reutilizando el backing `m×n` de `A`;
- workspace escalar adicional: O(1);
- materializar una `P` futura: O(m²) tiempo/storage;
- aplicar la permutación directamente: O(m) para un vector y O(mq) para una
  matriz RHS `m×q`.

No hay allocation de fila ni copia completa de matriz por paso.

## Fuera de scope

Quedan fuera de LU V1:

- `solve`, `det`, inverse, Cholesky, SVD, eigenvalues y rank;
- LU sin pivoting como API principal;
- complete, rook, scaled y threshold pivoting;
- tolerancias, estimación de rank o condición;
- sparse/block LU, paralelismo y BLAS/LAPACK;
- `Complex<T>` y escalares genéricos;
- variante in-place pública, entrada `MatrixView` y factores compactos públicos;
- helpers públicos para aplicar/materializar `P`.

## Orden del milestone de implementación

El vertical posterior debe ejecutarse en este orden:

1. declarar `LU<T>` y los dos overloads concretos `lu` sin ampliar el dominio;
2. implementar la permutación identidad, su signo y row swap escalar O(n);
3. implementar el kernel packed con pivoting parcial y skip de pivot cero;
4. materializar los factores económicos reutilizando el backing de `A`;
5. agregar el consumer con square, tall, wide, singular y zero shapes para
   `float32`/`float64`;
6. verificar `P*A ≈ L*U`, estructura, biyección y paridad en O0/O2;
7. calificar HIR/MIR/SSA/LLVM, allocations y ausencia de compiler magic;
8. ejecutar la suite completa y publicar un reporte de implementación separado.

No quedan decisiones arquitectónicas abiertas que autoricen rediseñar la API,
agregar tolerancias o incorporar `solve`/`det` dentro de ese vertical.
