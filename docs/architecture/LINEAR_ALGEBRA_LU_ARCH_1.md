# LINEAR-ALGEBRA-LU-ARCH-1 — LU con pivoting parcial

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este milestone define el próximo vertical numérico del package ordinario
`linearAlgebra`. No modifica `linearAlgebra/src/lib.ae`, el compilador, el
runtime ni los tests. Este documento normativo y su
[reporte de cierre](LINEAR_ALGEBRA_LU_ARCH_1_REPORT.md) completan el milestone
de arquitectura. La implementación pertenece a un milestone posterior y
tendrá su propio reporte separado.

Autoridad relacionada:

- [LINEAR-ALGEBRA-OAL-V1-QR](LINEAR_ALGEBRA_OAL_V1_QR_REPORT.md);
- [LINEAR-ALGEBRA-CONSTRUCTORS-V1](LINEAR_ALGEBRA_CONSTRUCTORS_V1_REPORT.md);
- [DYNAMIC-SHAPES-AND-SLICES-ARCH-1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md);
- [CONTEXTUAL-OVERLOADS-V1](CONTEXTUAL_OVERLOADS_V1_REPORT.md).

## 1. Decisión resumida

LU V1 factoriza matrices reales `float32` y `float64`, incluidas matrices
rectangulares, mediante eliminación gaussiana con pivoting parcial por filas.
Para una entrada `A` de forma `m×n`, con `r = min(m,n)`, devuelve factores
económicos que satisfacen:

```text
P A = L U

P : m×m, representada sin materializar
L : m×r, trapezoidal inferior y con diagonal unitaria
U : r×n, trapezoidal superior
```

La superficie pública propuesta es:

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

Ejemplo de uso:

```aether
LU<float64> factor = linearAlgebra.lu(A);
```

Los dos overloads se llaman `lu`. El algoritmo no se filtra al nombre público
como `luPartialPivoting`, y `float32` no recibe un nombre secundario. Los
overloads actuales distinguen las firmas por el tipo del argumento, sin
necesitar contexto de resultado.

No se ofrece un genérico falso. `Storable` sólo hace posible almacenar `T`; no
expresa `abs`, orden total útil para elegir pivots, división ni aritmética de
punto flotante. Por eso el cuerpo numérico se califica separadamente para los
dos tipos concretos.

## 2. Dominio V1: rectangular real

Se aceptan todas las formas runtime `m×n`, incluidas square, tall, wide y las
formas con algún extent cero.

Las alternativas evaluadas son:

| dominio | ventaja | costo o pérdida |
|---|---|---|
| sólo square | contrato mínimo para `solve` y `det` | rechaza una factorización rectangular bien definida y diverge del dominio rectangular de QR |
| sólo tall/square | sirve para varios problemas de mínimos cuadrados | restricción asimétrica sin simplificar materialmente el kernel |
| rectangular económica | factor matemático general, reutiliza el mismo kernel y preserva shapes útiles | exige cerrar dos shapes de salida y sus casos degenerados |

Se elige rectangular porque la selección de pivot, los swaps y la eliminación
ya recorren `k = 1..min(m,n)`. La complejidad adicional queda limitada a la
materialización de factores económicos. No se promete que LU con sólo
pivoting por filas revele el rank de una matriz rectangular; ese problema
permanece fuera de scope.

`solve` y `det`, cuando se diseñen, exigirán una factorización square. Esa
precondición pertenece a esas operaciones y no obliga a limitar `lu`.

No se admiten `int`, `usize`, `Complex<T>`, tipos definidos por usuarios ni un
tipo arbitrario que casualmente sea `Storable`.

## 3. Contrato de la permutación

`permutation` es un `Vector<usize,Column>` owning de longitud `m`. Es una
permutación de los índices públicos `1..m`; por lo tanto también es 1-based.
Su dirección queda definida por:

```text
(P A)[i,j] = A[permutation[i],j]
(P b)[i]   = b[permutation[i]]
```

Equivalentemente, si se materializa una matriz densa, para cada fila `i`:

```text
P[i,permutation[i]] = 1
```

y las demás entradas son cero. Esta definición evita la ambigüedad habitual
entre una permutación y su inversa. El vector comienza como `[1,2,...,m]`; al
intercambiar las filas activas `k` y `p`, se intercambian también
`permutation[k]` y `permutation[p]`.

`permutationSign` vale exactamente `+1` o `-1`. Comienza en `+1` y cambia de
signo una vez por cada swap real (`p != k`). Es `det(P)` y no el número de
swaps. Para una matriz square:

```text
det(A) = permutationSign * product(diag(U))
```

porque `det(P)⁻¹ = det(P)`. Guardar el signo hace que el futuro determinante no
tenga que recomputar la paridad en O(m), mientras el vector final permite
aplicar `P` a uno o varios RHS sin construir una matriz densa.

La representación se considera parte de la API matemática, no storage
accidental del algoritmo. El caller puede aplicar la permutación con un loop
de gather en O(m) para un vector o O(mq) para una matriz RHS `m×q`.

Una API auxiliar futura puede ofrecer overloads ordinarios equivalentes a:

```aether
Vector<float64,Column> permuteRows(
    VectorView<usize,Column> permutation,
    VectorView<float64,Column> value);

Matrix<float64> permuteRows(
    VectorView<usize,Column> permutation,
    MatrixView<float64> value);

Matrix<float64> permutationMatrix(
    VectorView<usize,Column> permutation);
```

con sus equivalentes `float32`. Esas funciones no forman parte del vertical de
implementación LU inicial. Si se admiten después, validarán que el vector sea
una biyección del tamaño correcto antes de leer el RHS. Materializar `P` es una
operación explícita O(m²), no un costo oculto de `lu`.

### Alternativa rechazada: `Matrix<T> P`

Un resultado `{P,L,U}` es familiar y facilita escribir literalmente
`P*A`. Sin embargo, `P` contiene sólo `m` unos entre `m²` celdas, requiere una
allocation y zero-fill O(m²), y aplicar `P` mediante multiplicación genérica
cuesta O(m²n) en lugar de un gather O(mn). Tampoco lleva por sí sola la paridad
en O(1). Por eso V1 no materializa `P`.

### Alternativa rechazada: historial de pivots

Guardar el índice elegido en cada paso es compacto y se parece a LAPACK, pero
obliga al usuario a reproducir swaps secuenciales y a conocer su dirección.
V1 publica la permutación final, que tiene semántica directa para `P*A`, y
mantiene el historial sólo como posible detalle local durante el cálculo.

## 4. Storage y ownership

La API pública materializa `L` y `U` por separado. No expone una matriz packed
porque obligaría a todos los consumidores a conocer qué triángulo contiene
multiplicadores, haría menos legible la reconstrucción y congelaría una
decisión de implementación.

Internamente, `A` se usa como workspace packed:

- la diagonal y la parte superior contienen `U`;
- debajo de la diagonal se guardan los multiplicadores de `L`;
- la diagonal unitaria de `L` es implícita mientras se factoriza.

Esto es coherente con la firma owning existente de QR: `lu(Matrix<T> A)` toma
ownership del argumento y puede reutilizar su backing. Preservar la matriz de
entrada requiere que el caller entregue una copia owning; V1 no agrega un
overload de `MatrixView` que esconda esa copia.

Al terminar se materializan los factores sin conservar una tercera matriz
packed:

- si `m <= n`, el backing de `A` se limpia bajo la diagonal y se devuelve como
  `U`; se asigna `L` de forma `m×m`;
- si `m > n`, el backing de `A` se transforma en `L` de forma `m×n`; se asigna
  `U` de forma `n×n`;
- en ambos casos sólo se asigna un factor adicional `r×r`, además del vector
  de permutación. La diagonal de `L` se escribe como uno del tipo concreto.

La estrategia exacta de cuál factor recicla `A` no es observable y puede
cambiar. El contrato estable sólo contiene `permutation`,
`permutationSign`, `L` y `U` materializados.

## 5. Algoritmo normativo

Sea `W` el workspace packed inicialmente igual al owner recibido y
`r = min(m,n)`. Para `k = 1..r`:

1. Inicializar `p = k` y `best = abs(W[k,k])`.
2. Recorrer `i = k+1..m`. Reemplazar `p` y `best` sólo si
   `abs(W[i,k]) > best`.
3. Si `p != k`, intercambiar las filas completas `k` y `p` de `W`,
   intercambiar las entradas correspondientes de `permutation` y negar
   `permutationSign`.
4. Si `W[k,k] == 0`, no dividir ni actualizar mediante ese pivot; continuar
   con el paso siguiente.
5. Para cada `i = k+1..m`, guardar
   `W[i,k] = W[i,k] / W[k,k]` y actualizar, para `j = k+1..n`,
   `W[i,j] = W[i,j] - W[i,k] * W[k,j]`.

Se intercambia la fila packed completa, no sólo la cola activa. Por ello un
swap posterior intercambia automáticamente los multiplicadores ya calculados
en las columnas `1..k-1`. En una implementación que materializara `L` durante
el loop sería obligatorio intercambiar precisamente `L[k,1:k-1]` con
`L[p,1:k-1]`; omitirlo produciría factores incorrectos.

El desempate es estable y determinista: gana la fila de menor índice porque
una igualdad no reemplaza al candidato actual. No se implementan complete,
rook, scaled ni threshold pivoting.

## 6. Ceros, `-0.0`, NaN e infinito

El único pivot singular reconocido por el kernel es el cero IEEE exacto.
`+0.0 == -0.0`, por lo que ambos saltan la división. `abs(-0.0)` participa como
cero en la búsqueda. No se exige canonicalizar el signo de los ceros guardados
en `L` o `U`.

NaN e infinito no tienen contrato especial en V1:

- no se preescanea ni rechaza la entrada;
- no se define una política alternativa de orden para NaN;
- se usan `abs`, `>`, `==`, división, multiplicación y resta IEEE ordinarias;
- no se promete reconstrucción útil, detección de singularidad ni valores
  finitos si la entrada o la aritmética intermedia contienen NaN/Inf.

En particular, el desempate determinista anterior es una garantía para
magnitudes ordenables, no una normalización de NaN. Agregar una política
`isFinite` sería otro contrato y no debe aparecer accidentalmente en el
vertical de implementación.

## 7. Singularidad

`lu(A)` devuelve factores aun cuando una matriz square sea singular. No lanza,
no trapea y no necesita un outcome nominal por un pivot cero. El paso se omite
porque, después de buscar el máximo módulo en la columna activa, un pivot cero
implica que todos los candidatos de esa columna son cero en la aritmética
observada. Así se evita división por cero y se conserva `P*A = L*U`.

Para una entrada square finita, un cero exacto en `diag(U)` identifica
singularidad exacta respecto de la aritmética ejecutada. No se agrega un campo
`singular`: `det` obtiene naturalmente cero del producto y un futuro `solve`
puede inspeccionar la diagonal y aplicar su propio contrato de fallo.

Una matriz casi singular con pivot no cero se factoriza normalmente. LU V1 no
usa epsilon absoluto, epsilon relativo, norma de `A` ni tolerancia dependiente
del tipo. Elegir una tolerancia sería estimación de rank/condición, no
factorización LU.

En matrices rectangulares no se usa el término singular como estado del
resultado. Los pivots diagonales cero tampoco convierten esta LU en una
descomposición rank-revealing, porque V1 no pivotea columnas.

Los traps generales de allocation, overflow de tamaño e indexación corrupta
conservan sus contratos. No se reinterpretan como singularidad recuperable.

## 8. Estabilidad numérica

El pivoting parcial es el default porque selecciona el mayor módulo disponible
en la columna activa. Cuando el pivot es no cero, los multiplicadores
calculados satisfacen `abs(L[i,k]) <= 1` salvo efectos de NaN/Inf, reduciendo la
amplificación inmediata que produce dividir por un pivot pequeño pudiendo usar
uno mayor.

Esto no convierte LU en un algoritmo infalible: existen matrices con
crecimiento grande aun con pivoting parcial. V1 documenta esa limitación y no
agrega escalado, estimación de condición, complete/rook pivoting ni decisiones
por threshold.

Las operaciones públicas necesarias ya son generales:

- `rows`, `columns` y `min` expresado con control de flujo;
- indexación 1-based de Matrix/Vector y assignment escalar;
- `abs`, comparación, división, multiplicación, resta y casts literales para
  `float32`/`float64`;
- `matrixFilled`/`vectorFilled` para shapes runtime inicializados.

No se requiere compiler magic ni una operación privilegiada para LU.

## 9. Intercambio de filas

Los slices actuales son views O(1) y slice assignment promete snapshot sólo
para esa asignación individual. Este patrón no implementa un swap:

```aether
tmp = W[k,:];
W[k,:] = W[p,:];
W[p,:] = tmp;
```

`tmp` seguiría siendo un view alias del storage ya sobrescrito; además no hay
materialización owning implícita. Materializar una fila permitiría hacerlo,
pero agregaría una allocation y O(n) storage por swap.

V1 usa un loop de columnas y un único temporal escalar:

```text
for j = 1..n:
    tmp = W[k,j]
    W[k,j] = W[p,j]
    W[p,j] = tmp
```

Cuesta O(n) por swap, O(1) storage, no copia matrices completas y funciona con
la infraestructura actual. Puede encapsularse como helper source privado y
ordinario para los dos tipos concretos. No se justifica todavía una primitiva
de compilador `swapRows`; si luego se publica una operación reusable deberá
ser general para Matrix/views mutables y conservar sus reglas de bounds,
strides, aliasing y `Copy`.

## 10. Shapes y casos límite

Con `r = min(m,n)`:

| entrada | `permutation` | `L` | `U` | resultado |
|---|---:|---:|---:|---|
| square `n×n` | `n` | `n×n` | `n×n` | LU square ordinaria |
| tall `m×n`, `m>n` | `m` | `m×n` | `n×n` | factores económicos |
| wide `m×n`, `m<n` | `m` | `m×m` | `m×n` | factores económicos |
| `0×0` | `0` | `0×0` | `0×0` | identidad vacía, signo `+1` |
| `m×0` | `m` | `m×0` | `0×0` | permutación identidad, signo `+1` |
| `0×n` | `0` | `0×0` | `0×n` | permutación vacía, signo `+1` |
| `1×1` | `1` | `[1]` | copia del único valor | no hay swap |

`L` es trapezoidal inferior: `L[i,j] = 0` para `i < j`, y
`L[i,i] = 1` para `i <= r`. `U` es trapezoidal superior:
`U[i,j] = 0` para `i > j`. Estas propiedades incluyen filas cero, pivots
negativos, pivots cero y cualquier cantidad de swaps.

Para `float32` se ejecuta toda la aritmética y se almacenan ambos factores en
`float32`; no se promociona silenciosamente el kernel a `float64`. La
permutación y el signo son independientes de `T`.

## 11. Preparación para `solve` y `det`

La representación ya contiene todo lo necesario sin refactor:

```text
solve square:
    rhsPermuted[i] = b[permutation[i]]
    forward substitution con L
    backward substitution con U

det square:
    permutationSign * product(U[i,i])
```

Ninguno requiere materializar `P`. Un futuro solve con varios RHS aplica el
mismo gather por filas a una matriz. El diseño de `SolveMethod.LU`, el outcome
de un sistema singular y las políticas de overwrite/copia del RHS quedan para
su propio milestone.

## 12. Costos

Para `r = min(m,n)`, la eliminación cuesta:

```text
O(m*n*r) tiempo
O(1) workspace escalar, además del resultado y del owner A reutilizado
```

En el caso square el término dominante es aproximadamente `2/3 n³`
operaciones aritméticas, más O(n²) búsqueda de pivots, swaps y materialización.
No hay copia completa por paso.

El resultado almacena:

```text
m*r + r*n elementos de T
m índices usize
un signo int
```

La implementación recomendada recicla el backing `m*n` de `A`, asigna un
factor adicional `r*r` y asigna el vector de `m` índices. Los shapes vacíos no
asignan backing por el contrato de filled-init. Construir una `P` densa en una
API futura agregaría O(m²) tiempo/storage; aplicar la permutación directamente
no lo hace.

## 13. Calificación del futuro vertical

La implementación deberá agregar un consumer independiente y calificación de
package/IR sin reemplazar la batería QR existente.

Casos numéricos mínimos para ambos tipos:

- matriz que no requiere pivoting;
- exactamente un swap y múltiples swaps;
- empate de módulos para probar que gana la menor fila;
- identidad, diagonal y triangular superior/inferior;
- pivots negativos y presencia de `-0.0`;
- singular square, fila cero y matriz cero;
- `0×0`, `m×0`, `0×n` y `1×1`;
- tall y wide, tanto full-rank como deficientes;
- `float64` y `float32` con tolerancias específicas del tipo.

Cada caso aplicable debe verificar:

1. shapes exactos de `L`, `U` y longitud de la permutación;
2. que `permutation` es una biyección 1-based;
3. `permutationSign` contra el número conocido de swaps y contra la paridad
   recomputada;
4. estructura trapezoidal y diagonal unitaria de `L`;
5. reconstrucción elemento a elemento `P*A ≈ L*U`, aplicando el vector por
   gather y sin depender de una matriz `P` pública;
6. que un pivot cero singular no trapea ni produce una división por cero;
7. mismo resultado contractual y salida exitosa en O0 y O2.

Las comparaciones de reconstrucción usan tolerancias, no igualdad flotante.
Las propiedades discretas de permutación, signo, shapes y ceros escritos por
materialización sí se comprueban exactamente. NaN/Inf no se usan para exigir
identidades numéricas; sólo pueden calificarse, si resulta útil, como ausencia
de una ruta especial o trap inventado.

La calificación estructural debe confirmar que:

- sólo existen los overloads `lu(Matrix<float32>)` y
  `lu(Matrix<float64>)`;
- no se materializa `P` ni se multiplica por ella dentro de `lu`;
- no hay allocation de fila dentro del loop de pivots;
- no hay copia/multiplicación full-matrix por paso;
- HIR/MIR/SSA y LLVM preservan los loops, accesos y ownership ordinarios, sin
  intrinsic ni allowlist para `linearAlgebra`.

## 14. Fuera de scope

Este diseño no implementa ni admite:

- `solve`, `det`, inverse, Cholesky, SVD, eigenvalues o rank;
- LU sin pivoting como API principal;
- complete, rook, scaled o threshold pivoting;
- estimación de rank o condición y tolerancias de singularidad;
- sparse LU, block LU, paralelismo o BLAS/LAPACK;
- `Complex<T>` o tipos escalares genéricos;
- variante in-place pública, views de entrada o factores compactos públicos;
- materialización pública de `P` y helpers públicos de permutación.

No quedan decisiones abiertas que bloqueen el futuro milestone de
implementación LU. Ese milestone deberá implementar exactamente esta
superficie, demostrar sus costos y publicar un reporte separado; no deberá
rediseñar `solve` o `det` como parte de LU.
