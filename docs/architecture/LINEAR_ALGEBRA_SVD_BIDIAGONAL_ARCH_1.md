# LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1 — reducción bidiagonal real compacta

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-01.

Este milestone es exclusivamente documental. No modifica `linearAlgebra`,
tests, consumer, compiler, runtime, standard library ni APIs públicas. Diseña
la primera fase productiva de la SVD thin cerrada por
[LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md); la iteración QR
bidiagonal permanece fuera de este cierre.

Autoridad relacionada:

- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md) y su
  [reporte](LINEAR_ALGEBRA_SVD_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-STABLE-NORM-ARCH-1](LINEAR_ALGEBRA_STABLE_NORM_ARCH_1.md) y
  [LINEAR-ALGEBRA-STABLE-NORM-V1](LINEAR_ALGEBRA_STABLE_NORM_V1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md).

## 1. Decisión resumida

Para una entrada conceptual `A:m×n`, `k=min(m,n)`, la futura ruta preserving
creará un único workspace owning `W:m×n`. La reducción lo observa a través de
un descriptor mutable orientado `X:M×N`:

```text
si m >= n: X = matrix_view_mut(W),    M=m, N=n=k
si m <  n: X = transpose_view_mut(W), M=n, N=m=k
```

El descriptor es O(1), comparte el backing de `W` y no materializa `A^T`.
Así el único kernel recibe siempre `M>=N` y produce una bidiagonal upper
`B:N×N` mediante reflectors Householder izquierdos y derechos alternados.

El workspace conserva compactamente las colas de esos reflectors. Cuatro
vectores privados guardan `d:N`, `e:max(N-1,0)`, `tauLeft:N` y
`tauRight:max(N-1,0)`. Después se materializan directamente, sin factors full,
los seeds públicos futuros:

```text
U0  : m×k
Vt0 : k×n
```

Para tall/square se cumple `A = U0 B Vt0` en aritmética exacta. Para wide se
cumple `A = U0 B^T Vt0`: `B` sigue siendo la upper obtenida al reducir `A^T` y
los roles izquierdo/derecho se intercambian al materializar. Un tag privado
conserva esta orientación para la fase QR siguiente.

No se forma una Matrix Householder, transpose owning, `U:m×m` tall,
`V:n×n` wide, historial de transforms ni owner dentro de un inner loop.

## 2. Dominio, precondición y shapes vacías

La reducción admite square, tall, wide, rank-deficient, matriz cero y los tres
casos vacíos `m×0`, `0×n`, `0×0`. No exige full rank ni divide por un valor
singular.

El kernel privado tiene esta precondición establecida por el futuro assembly:
todos los elementos del workspace son finitos. No repite checks por elemento.
NaN o infinito de entrada nunca es un modo de uso válido del kernel; su rechazo
público pertenece a `SVD-ASSEMBLY-V1`.

Si `k==0`, no se construye una vista de eje ni se ejecuta Householder. Los
resultados internos conservan exactamente:

| entrada | `U0` | `d` | `e` | `Vt0` |
|---|---:|---:|---:|---:|
| `m×0` | `m×0` | `0` | `0` | `0×0` |
| `0×n` | `0×0` | `0` | `0` | `0×n` |
| `0×0` | `0×0` | `0` | `0` | `0×0` |

Los owners de extent cero pueden carecer de backing. No se fabrica una
identidad full para completar un eje vacío.

## 3. Identidad matemática y orden de transforms

Sea `X0` la orientación tall/square del workspace. En el step `i`, `H_i` es
el reflector izquierdo embebido sobre filas `i..M`; cuando `i<N`, `G_i` es el
reflector derecho embebido sobre columnas `i+1..N`. Ambos son reales,
simétricos y ortogonales.

El orden de reducción es exactamente:

```text
X <- H_i X
X <- X G_i       // sólo si i < N
```

por lo que al terminar:

```text
B  = H_N ... H_2 H_1 X0 G_1 G_2 ... G_(N-1)
QL = H_1 H_2 ... H_N
QR = G_1 G_2 ... G_(N-1)
X0 = QL B QR^T
```

`B` es `N×N` upper bidiagonal, con `B[i,i]=d[i]` y
`B[i,i+1]=e[i]`. No existe otro elemento matemáticamente no cero.

Para `m>=n`, `X0=A`, `N=k` y se materializa:

```text
U0  = QL[:,1..k] : m×k
Vt0 = QR^T        : k×n
A   = U0 B Vt0
```

Para `m<n`, `X0=A^T`, `N=k=m` y se intercambian roles y orientación:

```text
U0  = QR                 : m×m
Vt0 = QL[:,1..m]^T       : m×n
A   = U0 B^T Vt0
```

Ésta es la identidad exacta conceptual. El tag privado `Upper` o
`TransposedUpper` indica si `d/e` representan el centro entre `U0,Vt0` como
`B` o como `B^T`; no se transpone ni se reordena `d/e`.

## 4. Convención Householder única

Cada reflector usa exactamente:

```text
H(v,tau) = I - tau v v^T
v[1] = 1 implícito
```

La formación reutiliza la norma estable y la selección de signo del QR
vigente. Para un vector lógico `x[1..p]`, `p>=1`:

```text
norm = stableNormRange(view, first, last)

si norm == +0:
    beta = +0
    tau  = +0
    H    = I

si norm != +0:
    beta = norm
    si x[1] >= +0: beta = -norm
    pivotRatio = x[1] / beta
    denominatorRatio = pivotRatio - 1
    v[1] = 1
    v[j] = (x[j] / beta) / denominatorRatio, j=2..p
    tau = 1 - pivotRatio
```

En aritmética exacta, la cola anterior es
`x[j]/(x[1]-beta)` y `tau=2/(v^T v)`: es el mismo reflector y la misma
elección de signo que QR. Se fija la forma escalada porque formar directamente
`x[1]-beta` puede desbordar aunque `norm` y el reflector sean representables
(por ejemplo, un pivot grande y `beta` de signo opuesto). Como
`abs(x[j])<=abs(beta)` y `pivotRatio` está entre `-1` y cero para input finito
representable, los cocientes evitan ese overflow intermedio. No se agrega una
segunda norma ni se altera la autoridad `stableNormRange`.

`beta` queda en el pivot y la cola `v[2..p]` ocupa las posiciones eliminadas.
La aplicación a cada vector `y` es:

```text
dot = y[1] + sum(j=2..p, v[j]*y[j])
scale = tau * dot
y[1] = y[1] - scale
y[j] = y[j] - scale*v[j]
```

No se evalúan los cocientes y no se lee la cola como reflector cuando
`tau==+0`. Un vector cero, incluidos signed zeros, produce identidad y
`beta=+0`; sus celdas de cola pueden conservar cualquier signed zero porque
son semánticamente inactivas. Para un vector escalar no cero, `v=[1]`,
`tau=2` y el reflector cambia el signo según la misma regla.

`norm` puede desbordar sólo cuando el resultado matemático no es representable,
o una operación Householder posterior puede producir un no finito aun desde
input finito. Este kernel no inventa una excepción local: el chequeo de estado
algorítmico y su traducción a `NumericalConvergenceException` permanecen en la
frontera cerrada por `SVD-ARCH-1`. No se usa epsilon como detector.

## 5. Reutilización exacta de norma estable

No existe `sqrt(sum(x*x))`, una segunda recurrencia `scale/scaledSquares` ni
un helper separado para filas. En el step `i` del problema orientado:

```text
leftNorm = stableNormRange<T>(column(X,i), i, M)

rightNorm = stableNormRange<T>(
    transpose_view(row(X,i)), i+1, N)    // sólo si i < N
```

Los extremos son inclusivos y one-based. `column`, `row` y
`transpose_view` crean descriptors O(1), sin owner ni copia. El rango left
nunca es vacío dentro del loop. El rango right tampoco: sólo se forma cuando
`i<N`, incluso si contiene un único elemento. No se pasa el rango vacío
canónico al helper desde esta reducción.

La vida de la axis view termina antes de mutar nuevamente `X`. Esto hace
explícita la disciplina de borrow sin cambiar traversal ni allocation.

## 6. Loop exacto de reducción tall/square

El kernel ejecuta `i=1..N` en orden creciente:

1. calcula la norma de `X[i..M,i]` y forma `H_i`;
2. escribe inmediatamente `d[i]=betaLeft`, `tauLeft[i]=tauLeftValue` y
   `X[i,i]=betaLeft`; la cola queda en `X[i+1..M,i]`;
3. aplica `H_i` por la izquierda a cada columna `j=i+1..N`, recorriendo
   columnas y, dentro de cada dot/update, filas crecientes `i..M`;
4. si `i<N`, calcula la norma de `X[i,i+1..N]`, forma `G_i`, escribe
   `e[i]=betaRight`, `tauRight[i]=tauRightValue` y `X[i,i+1]=betaRight`;
   su cola queda en `X[i,i+2..N]`;
5. aplica `G_i` por la derecha a cada fila `r=i+1..M`, recorriendo filas y,
   dentro de cada dot/update, columnas crecientes `i+1..N`.

La columna pivot no se actualiza físicamente con `H_i`: se preserva la cola y
se escribe directamente el resultado matemático `betaLeft` en el pivot. De
igual modo, la fila pivot no se actualiza con `G_i`. Sólo se actualiza el
subproblema que todavía debe reducirse.

No existe reflector derecho cuando `i==N`. Por tanto `N==1` tiene un solo
reflector izquierdo y `e/tauRight` de dimensión cero. Cuando `N==0` tampoco
existe loop. Para `i==N-1`, el reflector derecho de longitud uno sí existe y
sigue la convención de §4.

## 7. Layout compacto del workspace

Al terminar, la interpretación de `X` es:

```text
X[i,i]       = d[i]                         pivot visible
X[i,i+1]     = e[i]                         pivot visible, i<N
X[r,i]       = tail de H_i, r=i+1..M        1 implícito en X[i,i]
X[i,c]       = tail de G_i, c=i+2..N        1 implícito en X[i,i+1]
```

El `1` implícito no se escribe: las celdas pivot contienen `beta`, no uno.
`tauLeft[i]` y `tauRight[i]` distinguen un reflector activo de identidad. Las
regiones de cola izquierda (debajo de diagonal) y derecha (encima de la
superdiagonal) son disjuntas, incluso sobre el backing original wide.

Es incorrecto interpretar toda celda fuera de diagonal/superdiagonal como un
cero almacenado. Sólo la Matrix matemática `B` test-only las interpreta como
cero. No se limpian físicamente esas regiones: hacerlo destruiría los
reflectors y agregaría trabajo inútil.

`d/e` se escriben **durante** la reducción y son la autoridad entregada a QR.
Los pivots duplicados en `X` pertenecen al layout compacto; no se hace un pase
de extracción posterior. Esta estrategia mantiene `d/e` independientes del
storage que será liberado después de materializar los factors.

## 8. Construcción thin desde reflectors

Todas las matrices se inicializan con `+0` y unos exactos en la diagonal
identity-like correspondiente. Aplicar un reflector con `tau==0` es un skip;
por ello las colas inactivas nunca se leen. Cada aplicación usa el dot y update
de §4, sin Matrix temporal.

### 8.1 Tall/square: `U0=QL[:,1..N]`

Se crea directamente `U0:M×N`, con `U0[c,c]=1` para `c=1..N`. Se recorren
`i=N..1`; para cada `i`, se premultiplica por `H_i` el bloque de filas `i..M`
de las columnas `c=i..N`. El orden descendente produce:

```text
U0 = H_1 H_2 ... H_N E = QL[:,1..N]
```

donde `E` son las primeras `N` columnas de la identidad `M×M`. Nunca existe
esa identidad full. Las columnas `c<i` son coordenadas ya invariantes y no se
recorren.

### 8.2 Tall/square: `Vt0=QR^T`

Se crea `Vt0:N×N` como identidad. Se recorren `i=1..N-1`; para cada reflector
se premultiplica `Vt0` por `G_i`, actuando sobre sus filas `i+1..N` para todas
las columnas `1..N`. Cada nuevo factor queda a la izquierda:

```text
Vt0 = G_(N-1) ... G_2 G_1 = QR^T
```

Así se construye directamente `Vt`, no primero `V` seguido de transpose.

### 8.3 Wide: `U0=QR`

Aquí `N=m`. Se crea `U0:N×N` como identidad y se recorren `i=1..N-1`.
Para cada `i`, se postmultiplica `U0` por `G_i`, actuando sobre columnas
`i+1..N` para todas las filas. Resulta directamente:

```text
U0 = G_1 G_2 ... G_(N-1) = QR
```

No se materializa `QR^T` para luego transponerlo.

### 8.4 Wide: `Vt0=QL[:,1..N]^T`

Se crea directamente `Vt0:N×M`, identity-like con `Vt0[c,c]=1`. Se recorren
`i=N..1`; para cada `i`, se postmultiplican por `H_i` las filas `r=i..N`
sobre columnas `i..M`. El orden descendente produce:

```text
Vt0 = E^T H_N ... H_2 H_1 = QL[:,1..N]^T
```

No se crea el factor `M×M`, ni siquiera `QL[:,1..N]` como Matrix intermedia.

Estas cuatro construcciones dependen sólo de reflectors, no de `d`, `e` ni
divisiones por singular values. Son válidas para reflector trivial, rank
deficiency y matriz cero.

## 9. Cero, rank deficiency y signed zero

Una cola de norma exactamente cero genera `tau=+0`, no excepción. Para una
matriz cero no vacía todos los reflectors son identidad; las inicializaciones
identity-like de §8 producen bases ortonormales deterministas con las shapes
thin correctas. No se completa una base mediante `A*v/s` o `A^T*u/s`, por lo
que nunca se divide por cero ni por un singular value pequeño.

La política de cero de esta fase es:

- `stableNormRange` retorna `+0` para vacío/todos signed zeros;
- todo pivot correspondiente a esa norma se almacena como `+0` en `d/e` y
  workspace;
- una cola inactiva puede retener `+0` o `-0`, pero no es observable después
  de liberar el workspace;
- un `beta` no cero conserva el signo elegido por Householder;
- no se aplica `abs(d)`, no se corrigen signs correlacionados y no se ordena.

Canonicalizar el cero producido por un reflector trivial no es la
normalización `S>=0`: `d/e` todavía son una bidiagonal signed y la política de
singular values pertenece al assembly final.

## 10. Tipos internos y frontera con QR bidiagonal

La implementación V1 debe usar dos aggregates privados equivalentes a:

```aether
enum BidiagonalOrientation { Upper, TransposedUpper }

struct CompactBidiagonalReduction<T: Storable> {
    Matrix<T> workspace;
    Vector<T,Column> d;
    Vector<T,Column> e;
    Vector<T,Column> tauLeft;
    Vector<T,Column> tauRight;
    BidiagonalOrientation orientation;
}

struct BidiagonalSVDSeed<T: Storable> {
    Vector<T,Column> d;
    Vector<T,Column> e;
    Matrix<T> U;
    Matrix<T> Vt;
    BidiagonalOrientation orientation;
}
```

Los nombres source exactos pueden variar sin cambiar esta arquitectura; los
fields, ownership y significado no. Ambos tipos y todos sus helpers omiten
`public`.

Primero se completa toda la reducción. Luego se materializa `U`, después
`Vt`, siempre en owners separados y sin escribir el workspace. Este orden es
normativo para V1 aunque el matemático inverso también sería válido: mantiene
una sola historia de cleanup y qualification. Sólo después de construir ambos
se liberan `workspace`, `tauLeft` y `tauRight`; antes de ese punto ambos juegos
de colas deben permanecer intactos. V1 no reutiliza el backing de `workspace`
como output porque esa reutilización todavía no está demostrada.

La frontera exacta recibida por
`LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1` es `BidiagonalSVDSeed`:

- `d/e` independientes y todavía signed, sin ordenar;
- `U/Vt` thin, ortonormales y ya en orientación pública;
- `orientation=Upper` significa centro `B`;
- `orientation=TransposedUpper` significa centro `B^T` y obliga a intercambiar
  qué rotaciones bidiagonales actualizan columnas de `U` y filas de `Vt`.

En particular, si la fase siguiente obtiene conceptualmente
`B=P*Sigma*Q^T`, la acumulación queda cerrada como:

```text
Upper:           U <- U*P;  Vt <- Q^T*Vt
TransposedUpper: U <- U*Q;  Vt <- P^T*Vt
```

El milestone QR decidirá shifts, chase, deflation, epsilon, cap y fórmulas de
Givens. No podrá cambiar estas shapes, transponer owners ni exigir reflectors
Householder ya liberados.

## 11. Capabilities, lowering y fallos internos

La constraint privada es `T: IEEEFloat`. La reducción y materialización usan
exactamente las operaciones aritméticas disponibles bajo:

```text
Zero, One, Add, Sub, Mul, Div, Negate, Equal, Order, Abs, Sqrt
```

`Abs` y `Sqrt` se ejercen dentro de la autoridad de norma; `Negate` elige
`beta`; las restantes forman y aplican reflectors. No se llama
`epsilon<T>()`: epsilon pertenece exclusivamente a deflation/convergencia de
la fase QR. Tampoco se agrega `copysign`, `hypot` público ni capability nueva.

Todo será source ordinario de `linearAlgebra`: loops, indexación y views. Tras
monomorphization habrá sólo float32/float64 concretos, sin opcode bidiagonal,
Householder intrinsic, LAPACK, `TypeId`, witness, vtable, boxing ni call
indirecta numérica.

Los índices y descriptors válidos son invariantes estructurales de helpers
privados. Bounds/overflow conservan los traps generales del lenguaje; no se
agrega una excepción nominal de corrupción. El kernel no captura ni traduce
traps y no publica resultado parcial.

## 12. Complejidad y budget de allocations

Sobre la orientación `M×N`, `M>=N=k`:

- bidiagonalización: `O(M*N^2)`;
- materialización del factor izquierdo thin: `O(M*N^2)`;
- materialización del factor derecho square: `O(N^3)`, absorbido por
  `O(M*N^2)`;
- total: `O(m*n*k)` tiempo, sin promesa de FLOPs exactos.

El peak no vacío permitido contiene estos owners:

```text
workspace W : m×n
U            : m×k
Vt           : k×n
d             k
e             max(k-1,0)
tauLeft       k
tauRight      max(k-1,0)
```

Tall y wide tienen el mismo budget; wide añade sólo un descriptor transpose
O(1). Los owners lineales pueden implicar allocations separadas. Tras crear el
seed se retienen sólo `U`, `Vt`, `d`, `e`; el workspace y taus se destruyen.

Quedan prohibidos Matrix/Vector owners por reflector, allocation dentro de un
inner Householder loop, transpose Matrix, full factor descartado, Matrix `B`,
Matrix `Sigma` e historial de transforms. Qualification fijará conteos reales
según la semántica de extents/backing, no exigirá una única allocation.

## 13. Qualification matemática

Los tests white-box construirán `B` sólo conceptualmente desde `d/e`. Para
tall/square comprobarán por acumulación test-only:

```text
A[i,j] ~= sum(r=1..k,
              U0[i,r] * (d[r]*Vt0[r,j]
              + (r<k ? e[r]*Vt0[r+1,j] : 0)))
```

que equivale a `A≈U0 B Vt0`. Para wide comprobarán `A≈U0 B^T Vt0`, por
ejemplo evaluando el centro sin materializarlo. Además verificarán:

```text
U0^T U0 ~= I_k
Vt0 Vt0^T ~= I_k
```

con norma escalada y tolerancias justificadas por tipo, dimensiones y escala.
No se compara `U/Vt` elemento a elemento con otro algoritmo y no se usa
`A^T A` para fabricar un oráculo.

La matriz de casos incluye float32/float64 y O0/O2 para square, tall, wide,
`m<<n`, diagonal, rectangular diagonal, cero, rank-deficient, filas/columnas
repetidas, signed zeros, subnormales y escalas huge/tiny cuyo resultado
matemático sea representable. Incluye `1×1`, `m×1`, `1×n`, `m×0`, `0×n` y
`0×0`.

Los residuos califican la reducción, todavía no singular values. LAPACK puede
usarse sólo como apoyo test-only, nunca como implementación productiva. Input
no finito queda fuera del kernel y se calificará en el assembly público.

## 14. Qualification estructural

La qualification V1 debe demostrar además:

- shapes exactas de workspace, arrays y factors en ambos branches;
- una sola implementación del kernel orientado tall;
- `transpose_view_mut(W)` O(1) para wide y ausencia de transpose owning;
- pivots, colas implícitas y taus conforme a §7 antes de materializar;
- `d/e` independientes del workspace y ausencia de pase de extracción;
- inexistencia de Matrix/Vector por reflector y de factors full descartados;
- cero allocations dentro de loops Householder;
- liberación del workspace sólo tras consumir ambos juegos de reflectors;
- visibilidad privada de aggregates/helpers y ausencia de API pública nueva;
- HIR/MIR/SSA ordinarios y concretización float32/float64 sin magic;
- `git diff --check` y diff limitado a implementación/qualification del
  vertical futuro, no al compiler salvo un gap demostrado por separado.

Los tests directos viven en fixture white-box o mecanismo interno equivalente.
No se expone un wrapper de producción sólo para probar el kernel.

## 15. Milestones y fuera de scope

La secuencia posterior permanece separada:

1. `LINEAR-ALGEBRA-SVD-BIDIAGONAL-V1` implementa exactamente esta reducción,
   materialización y qualification interna;
2. `LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1/V1` diseña e implementa iteración
   implícita sobre el seed;
3. `LINEAR-ALGEBRA-SVD-ASSEMBLY-V1` publica la API y aplica signos/ordering;
4. el cierre de qualification integra oráculo, failures y budgets públicos.

Quedan fuera de este milestone: API `svd`, iteración QR bidiagonal, shifts,
Givens chase, deflation, epsilon tests, iteration cap, normalización a
`S>=0`, ordenamiento, permutaciones correlacionadas, canonicalización de
signos, pseudoinverse, LAPACK productivo y Complex.
