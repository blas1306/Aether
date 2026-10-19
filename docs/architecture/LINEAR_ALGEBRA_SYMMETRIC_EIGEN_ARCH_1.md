# LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1 — eigenproblem real simétrico

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Este milestone es exclusivamente documental. No modifica
`linearAlgebra/src/lib.ae`, consumer, tests, compiler, runtime, standard
library ni capabilities. La implementación y la qualification se dividen en
verticales posteriores (§22).

Autoridad relacionada:

- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_QR_ARCH_1.md);
- [LINEAR-ALGEBRA-STABLE-NORM-V1](LINEAR_ALGEBRA_STABLE_NORM_V1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md);
- [SHAPE-GUARD-V1](SHAPE_GUARD_V1_REPORT.md);
- [MATRIX-REPRESENTATION-V1](MATRIX_REPRESENTATION_V1_REPORT.md).

Como contraste algorítmico se auditaron también las interfaces documentadas
de LAPACK
[`DSYTRD`](https://www.netlib.org/lapack/explore-html/d5/d7a/dsytrd_8f_source.html)
y
[`DSTEQR`](https://www.netlib.org/lapack/explore-html/d9/d3f/dsteqr_8f_source.html).
Son referencias matemáticas, no source ni arquitectura copiada. Este diseño no
consulta ni reutiliza el compiler legacy.

## 1. Decisión resumida

V1 ofrecerá una única eigendecomposition real simétrica, preserving:

```aether
public struct SymmetricEigen<T: Storable> {
    Vector<T,Column> values;
    Matrix<T> vectors;
}

public SymmetricEigen<T> symmetricEigen<T: IEEEFloat>(
    ref Matrix<T> A);
```

Para `A:n×n`, un retorno legítimo cumple, sujeto al redondeo IEEE:

```text
A ≈ vectors * diag(values) * vectors^T
vectors^T * vectors ≈ I
A * vectors[:,j] ≈ values[j] * vectors[:,j]
values[1] <= ... <= values[n]
```

Cada eigenvector es una **columna** de `vectors` y corresponde al valor del
mismo índice. La entrada debe ser square, finita y exactamente simétrica. No
se exige positive definiteness: matrices semidefinidas, indefinidas, cero y
con multiplicidades pertenecen al dominio.

El algoritmo productivo es:

```text
validación exacta y escala común
    -> reducción Householder simétrica compacta a tridiagonal
    -> materialización del Q de reducción
    -> QR implícito shifted sobre d/e con deflation y bulge chasing
    -> rescale, orden ascendente y ensamblado
```

No se forma una Matrix Householder, una tridiagonal dense, un characteristic
polynomial ni se llama repetidamente al `qr` público. Jacobi no es el kernel
V1.

## 2. Auditoría de la infraestructura real

### 2.1 Reutilizable directamente

La implementación vigente permite reutilizar:

- `Matrix<T>` y `Vector<T,O>` owning, move-only, con índices one-based y
  shapes runtime que conservan ejes cero;
- `matrixFilled`/`vectorFilled`, que asignan una vez, validan extents y
  producen capacidad exacta en las rutas del package;
- `identity<T>(n)` para el factor ortogonal materializado;
- `copyMatrixForFactorization`, o un helper privado estrechamente derivado,
  para copiar sólo el rectángulo lógico sin asumir stride igual a columns;
- `StableScaledSquares`, `stableNormRange` y `stableHypot`, ya calificados para
  `float32` y `float64`;
- la convención Householder compacta de SVD, `H=I-tau*v*v^T` con `v[1]=1`;
- el constructor conceptual de Givens y la actualización de pares de columnas
  usados por la fase QR bidiagonal;
- `epsilon<T>()` y el dominio sellado `T: IEEEFloat`;
- `shapeGuard` para la precondición square;
- `NonFiniteMatrixException`, `NotSymmetricMatrixException` y
  `NumericalConvergenceException` ya públicas;
- el patrón preserving `ref Matrix<T>` y resultado owning independiente.

### 2.2 Reutilizable como convención, no como kernel

El QR Householder público materializa `Q:m×m` y `R:m×n` para una Matrix
general. No sirve para ejecutar `qr(T)` en cada iteración: hacerlo materializa
matrices dense, pierde la estructura tridiagonal y eleva tiempo y allocations.
Sólo se reutilizan su selección de signo y norma estable.

La bidiagonalización SVD usa reflectores a izquierda y derecha y produce dos
factores thin. La reducción simétrica usa el **mismo** reflector en ambos lados
y una actualización rank-2 del trailing block. Su storage y fórmulas no son
intercambiables.

El QR bidiagonal alterna rotaciones izquierdas y derechas sobre una Matrix no
simétrica y actualiza `U/Vt`. El kernel tridiagonal aplica cada rotación como
similaridad `T <- G^T*T*G` y actualiza una sola Matrix `vectors <- vectors*G`.
Pueden compartirse helpers escalares generales después de renombrarlos, pero
no se delega al chase bidiagonal ni se conserva un nombre privado que atribuya
la operación nueva a SVD.

### 2.3 Infraestructura que falta pero no exige lenguaje nuevo

Faltan únicamente helpers source privados para:

- validar finitud y simetría con la precedencia de §7;
- copiar y normalizar el triángulo inferior;
- reducir simétricamente y materializar sus reflectors;
- ejecutar el chase tridiagonal por similaridad;
- ordenar pares `(value,column)` en forma ascendente.

Todo es expresable con APIs y capabilities actuales. No se necesita primitive,
intrinsic, opcode, FFI, BLAS/LAPACK ni ampliación de `IEEEFloat`.

## 3. API pública, naming y shapes

`SymmetricEigen` declara el dominio en el tipo. `Eigen` solo sugeriría soporte
para matrices generales y spectra complejos; `Eigh` importaría una abreviatura
de otros ecosistemas sin aclarar el contrato. `symmetricEigen` sigue lower
camel case como `pseudoInverse` y conserva el mismo sustantivo que el tipo.

Los fields descriptivos `values` y `vectors` se eligen sobre `D/Q`: el
aggregate ya es nominal, `D` sugeriría una Matrix diagonal que no existe, y
`Q` no expresa por sí solo la correspondencia por columnas. Los fields lower
case son coherentes con `LU.permutation`; las mayúsculas de `LU/QR/SVD` se
reservan para símbolos matemáticos universales de esas familias.

El aggregate usa sólo `T: Storable`, como `LU`, `QR`, `Cholesky` y `SVD`.
Almacenar o mover un resultado no requiere aritmética; la operación productora
es la que exige `T: IEEEFloat`.

Para toda entrada admitida:

```text
values  : Vector<T,Column> de dimensión n
vectors : Matrix<T> n×n
```

`Vector<T,Column>` coincide con `SVD.S`, evita una orientación nueva y permite
que `vectors[:,j]` y `values[j]` formen el par natural. `diag(values)` es sólo
notación; la operación no materializa esa Matrix.

V1 no agrega `symmetricEigenvalues`. La única frontera pública entrega la
descomposición pedida completa, igual que `svd` entrega sus vectores. Una ruta
values-only puede omitir la materialización y acumulación de `vectors`, pero
merece API, cost model y qualification propios. Las fases privadas quedan
separadas para permitirla sin cambiar `symmetricEigen`.

Tampoco se agrega variante `InPlace`: el workspace compacto y la Matrix final
coexisten durante parte del assembly, y todavía no hay evidencia de una
reutilización pública de backing suficientemente clara.

## 4. Ordering y no unicidad

Los eigenvalues se publican en orden **ascendente**:

```text
values[1] <= values[2] <= ... <= values[n]
```

Ésta es la convención de las familias simétricas `eigh`/LAPACK y coloca el
extremo algebraicamente menor primero. SVD es descendente porque sus valores
son no negativos y sus consumers truncados usan prefijos dominantes; esa razón
no existe para un spectrum con signo. Forzar descendente sólo por semejanza
visual con `SVD.S` perjudicaría interoperabilidad y no simplificaría un
consumer espectral.

Tras converger y reescalar, un selection sort determinista busca desde cada
posición el valor estrictamente menor restante. Cada swap de values intercambia
las dos columnas completas correspondientes. Hace `O(n²)` comparaciones y a lo
sumo `n-1` swaps de columnas, sin allocation ni coste `O(n³)` de un bubble sort
de columnas.

La comparación estricta evita intercambiar directamente valores iguales, pero
el sort **no promete estabilidad** dentro de una multiplicidad: un swap por un
valor menor puede cambiar el orden relativo de iguales. Tampoco existe orden
matemático individual dentro de un eigenspace repetido.

No se canonicaliza el signo de eigenvectors. Si `q` es válido, `-q` también.
El algoritmo será determinista para la misma implementación, tipo, input y
optimization contract, pero esa observación no se eleva a garantía de signo o
base frente a otras implementaciones.

Todo zero eigenvalue se escribe como el literal `+0` antes del sort. No se
cambian signos de valores negativos distintos de cero.

## 5. Dominio y simetría exacta

La condición square es estructural:

```aether
shapeGuard(rows(*A) == columns(*A));
```

Un fallo conserva el trap abortivo `ShapeMismatch`. No se crea una Exception
para shapes.

La simetría se comprueba mediante igualdad IEEE ordinaria:

```text
A[i,j] == A[j,i]
```

- dos finitos deben comparar exactamente iguales;
- `+0` y `-0` sí forman una pareja simétrica;
- no existe tolerance absoluta, relativa, por ULP ni derivada de epsilon;
- una Matrix aproximadamente simétrica es responsabilidad explícita del
  caller, que debe construir un solo triángulo y reflejarlo o simetrizar según
  la escala y el modelo de error de su aplicación.

Una tolerancia silenciosa no puede distinguir error de redondeo aceptable de
asimetría relevante sin conocer unidades, escala y provenance. V1 tampoco
agrega un overload con tolerance: hacerlo exigiría definir validez del scalar,
precedencia y cómo producir la Matrix simétrica efectiva usada por el kernel.

Se reutiliza la clase pública existente:

```aether
NotSymmetricMatrixException
```

No se introduce el alias incompatible `NonSymmetricMatrixException`.

## 6. No finitos y precedencia de errores

La operación ejecuta, antes de asignar el workspace numérico:

1. `shapeGuard` square;
2. un pase row-major completo que exige `(x-x)==0` para cada elemento;
3. un pase por `i=2..n`, `j=1..i-1` que exige igualdad exacta entre ambos
   triángulos;
4. allocation/copia normalizada y cálculo.

Por tanto cualquier NaN o infinito de la Matrix gana globalmente sobre
cualquier asimetría finita y lanza `NonFiniteMatrixException`. Separar los dos
pases hace esa precedencia inequívoca; no convierte un NaN en asimetría por la
semántica unordered de `==`.

Entre varias asimetrías finitas gana la primera pareja del recorrido lower
row-major indicado. Las excepciones no llevan payload, por lo que el índice no
es observable hoy.

Un NaN o infinito **producido** después por una operación interna no es input
inválido. Se rechaza con `NumericalConvergenceException`, como ya hace SVD para
estados/resultados iterativos no finitos. No se crea otra clase de numerical
breakdown.

## 7. Escala global y casos rápidos

Durante el pase de finitud se obtiene:

```text
matrixScale = max(abs(A[i,j]))
```

Para una Matrix no diagonal y no cero, el workspace guarda el triángulo
inferior de `A/matrixScale`. La similaridad no cambia eigenvectors; al final
se calcula `values[i] = matrixScale * d[i]`. Esta normalización exacta en
intención mantiene el input interno con magnitud máxima uno, protege norma,
rank-2 update, shift y chase frente a overflow/underflow prematuros, y no es
una tolerance ni altera deflation.

Una razón más pequeña que el rango representable puede underflowear al
normalizar. Es pérdida normwise inevitable al combinar escalas más separadas
que el formato; V1 no promete alta precisión relativa de cada eigenvalue tiny.

Antes de crear el workspace general se resuelven:

- `0×0`: `values` dimensión cero y `vectors` `0×0`;
- `1×1`: el valor finito original y `vectors=[1]`;
- Matrix exactamente diagonal: copia de la diagonal más identidad, seguida
  sólo por canonicalización de cero y sort de pares;
- Matrix cero: es el caso diagonal; retorna `n` ceros positivos e identidad.

La ruta diagonal evita perder valores pequeños por la escala común y no entra
en Householder ni QR. No convierte una Matrix casi diagonal en diagonal.

El producto final se valida antes de publicar. Si un eigenvalue reescalado no
es finito, el spectrum no cabe en `T` bajo esta ejecución y se lanza
`NumericalConvergenceException`.

## 8. Reducción Householder simétrica

Sea `W=A/matrixScale` y `k=1..n-2`. Se trabaja sólo con el triángulo inferior
como autoridad. La columna activa es:

```text
x = W[k+1:n,k]
```

`stableNormRange(column(W,k),k+1,n)` calcula su norma sin slice owning. Para
`norm!=0` se usa exactamente la convención ya calificada:

```text
beta = norm
if W[k+1,k] >= 0: beta = -norm
pivotRatio = W[k+1,k] / beta
v[k+1] = 1 implícito
v[i] = (W[i,k] / beta) / (pivotRatio - 1), i=k+2..n
tau = 1 - pivotRatio
```

Se escribe `e[k]=beta`, `tau[k]=tau` y la cola de `v` debajo de la primera
subdiagonal de la columna `k`. Si `norm==0`, se escriben `e[k]=+0` y
`tau[k]=+0`; el reflector es identidad y no hay división. Un vector cuya cola
es cero pero primer elemento no lo es sigue produciendo un reflector válido,
normalmente un cambio de signo; no se trata como degenerado.

Con `v` embebido en `k+1..n`, el trailing block se actualiza sin formar `H`:

```text
w     = tau * W_trailing * v
alpha = -(tau / (1+1)) * (v^T * w)
w     = w + alpha * v
W_trailing = W_trailing - v*w^T - w*v^T
```

Sólo se escribe su triángulo inferior. Cuando una multiplicación necesita la
otra mitad se lee `W[max(i,j),min(i,j)]`; el upper triangle puede permanecer
en cero o stale y nunca adquiere autoridad. Cada nuevo scalar se calcula en
temporales y se valida como finito antes del store.

Al terminar:

```text
d[i] = W[i,i], i=1..n
e[i] = T[i+1,i], i=1..n-1
T = tridiagonal(d,e)
T = Qh^T * (A/matrixScale) * Qh
```

El workspace contiene, además de la diagonal/subdiagonal, las colas de los
reflectors y `tau`. No existe Matrix `T` owning.

## 9. Materialización del Q de reducción

Se crea `vectors=identity<T>(n)` y se aplican los reflectors almacenados en
orden creciente:

```text
vectors <- vectors * H_1
vectors <- vectors * H_2
...
vectors <- vectors * H_(n-2)
```

Cada aplicación recorre las filas de `vectors` y actualiza sólo las columnas
`k+1..n` mediante `I-tau*v*v^T`. No se materializa `H_k`, no se crea una axis
owning y no se conserva un historial adicional.

Ese orden produce `Qh=H_1 H_2 ... H_(n-2)`, coherente con:

```text
T = Qh^T * (A/matrixScale) * Qh
```

Materializar después de reducir, en vez de acumular durante la actualización
dense, conserva una frontera futura values-only: esa ruta podría descartar
reflectors tras obtener `d/e` sin asignar `vectors`.

## 10. Elección QR frente a QL

QR y QL implícitos son algoritmos espejo sobre una tridiagonal simétrica. QR
usa shift del extremo inferior y persigue el bulge de `lo` a `hi`; QL usa el
extremo superior y lo persigue de `hi` a `lo`. Ambos admiten Wilkinson,
deflation, splitting y la misma complejidad. LAPACK puede escoger dirección
por bloque según el extremo menor, pero eso exige dos traversals y dos juegos
de fórmulas.

V1 elige **QR implícito, trailing-shift, top-to-bottom**:

- el chase interior incrementa `usize` one-based y no necesita el patrón
  decreciente con `break` explícito que ya es una fuente de bordes delicados;
- coincide con la selección trailing de bloques y el vocabulario del kernel
  bidiagonal ya calificado;
- puede reutilizar `stableHypot`, la convención de Givens y la rotación de
  columnas;
- materializa eigenvectors por columnas directamente con `vectors<-vectors*G`;
- QL no ofrece una mejora de estabilidad general que justifique duplicar el
  kernel V1.

Esto no llama al `qr` dense ni impide una dirección adaptativa futura. Un
vertical posterior podrá agregar el chase espejo internamente si medición y
qualification muestran una ventaja, sin cambiar API, ordering ni resultado
matemático.

## 11. Deflation, splitting y bloques

Para `eps=epsilon<T>()`, cada `e[i]` se prueba en orden creciente:

```text
a = abs(d[i])
b = abs(d[i+1])
scale = max(a,b)

if scale == 0:
    threshold = 0
else:
    normalizedSum = (a/scale) + (b/scale)
    threshold = (eps*scale) * normalizedSum

if abs(e[i]) <= threshold:
    e[i] = +0
```

Es `eps*(|d_i|+|d_(i+1)|)` evaluado sin formar una suma potencialmente
desbordable. No hay decimal mágico, tolerance global ni deflation sólo por
exact-zero. La igualdad deflaciona y siempre canonicaliza a `+0`.

Después del pase se elige el bloque activo de mayor `hi`:

```text
hi = n
while hi > 1 and e[hi-1] == 0: hi = hi-1
if hi == 1: convergió

lo = hi
while lo > 1 and e[lo-1] != 0: lo = lo-1
```

Los separadores exactos desacoplan bloques. Eigenvalues repetidos o clustered
no reciben tratamiento por igualdad aproximada; continúan iterando hasta que
los `e` satisfacen el criterio local. Una `e` inicialmente cero separa sin
consumir budget.

## 12. Shift de Wilkinson escalado

Para `lo<hi`, se toma el trailing `2×2`:

```text
a = d[hi-1]
b = e[hi-1]
c = d[hi]
sigma = max(abs(a),abs(b),abs(c))
an=a/sigma; bn=b/sigma; cn=c/sigma
delta = (an-cn)/(1+1)
h = stableHypot(delta,bn)
denominator = abs(delta)+h
correction = abs(bn) * (abs(bn)/denominator)

if delta < 0: muNormalized = cn + correction
else:         muNormalized = cn - correction
```

Un bloque activo garantiza `b!=0`, `sigma!=0` y denominator distinto de cero.
`delta==0` elige determinísticamente el eigenvalue inferior del `2×2`. La
forma de correction evita `bn*bn` antes de dividir y `stableHypot` evita
overflow/underflow en la raíz.

No se materializa `mu=sigma*muNormalized`. El primer Givens usa un par
proporcional a `(d[lo]-mu,e[lo])`:

```text
t = max(abs(d[lo]),abs(e[lo]),sigma)
f = d[lo]/t - (sigma/t)*muNormalized
g = e[lo]/t
```

`t!=0`, todos los cocientes tienen magnitud acotada y una escala común
positiva no cambia la rotación. Así tampoco se resta directamente dos valores
dimensionales extremos.

## 13. Givens y chase tridiagonal

La convención única es:

```text
G(c,s) = [ c -s ]
         [ s  c ]

r = stableHypot(f,g)
(f,g)==(0,0) -> c=1, s=0
otro caso     -> c=f/r, s=g/r
```

Cada step ejecuta una similaridad `T<-G^T*T*G`. Para el primer par se usa el
`(f,g)` de §12. En iteraciones posteriores se construye el Givens desde
`(e[p-1],bulge)` para anular el bulge de la fila anterior.

Sea el bloque local antes de rotar índices `p,p+1`:

```text
[ a  b  0 ]
[ b  c  z ]
[ 0  z  . ]
```

El `2×2` se actualiza por similaridad en coordenadas normalizadas por
`localScale=max(abs(a),abs(b),abs(c))`, y sólo después se reescala. Esto evita
formar `c-a`, `2*b` o cuadrados dimensionales extremos. Matemáticamente:

```text
a' = cr^2*a + 2*cr*sr*b + sr^2*c
c' = sr^2*a - 2*cr*sr*b + cr^2*c
b' = (cr^2-sr^2)*b + cr*sr*(c-a)
bulge = sr*z
z'    = cr*z
```

Las fórmulas se evalúan sobre `a/localScale`, `b/localScale` y
`c/localScale`; `cr/sr` nombran cosine/sine para no confundirlos con el
diagonal `c`. Los tres resultados y el nuevo bulge se validan antes de store.
El próximo Givens anula ese bulge. Al salir por `p==hi-1` no queda elemento
fuera de la tridiagonal.

La acumulación es inmediata:

```text
vectors <- vectors * G

newColumnP = cr*oldColumnP + sr*oldColumnQ
newColumnQ = -sr*oldColumnP + cr*oldColumnQ
```

Cada fila lee ambos valores antes de escribir. No se almacena una lista de
rotaciones, no se forma `G` y no hay allocation por sweep.

## 14. Convergencia y budget

La unidad de budget es un **sweep completo de un bloque activo**, desde la
rotación inicial hasta expulsar el bulge por `hi`. Splits, deflation scans,
sorting y reflectors no consumen unidades.

La política productiva es:

```text
maxSweeps = checkedMultiply(64,n)
usedSweeps = 0

loop:
    deflate e
    select trailing active block
    if none: success
    if usedSweeps == maxSweeps: throw NumericalConvergenceException
    compute scaled Wilkinson shift
    chase one complete QR sweep and accumulate vectors
    usedSweeps += 1
    validate d/e/vectors finite
```

`64*n` deja más del doble del guard clásico de 30 iteraciones por eigenvalue
usado como referencia en tridiagonal QR, sin presentarlo como teorema. El
budget es global: un split no lo reinicia. El producto usa aritmética checked;
un overflow de extent conserva el fallo estructural general.

Esta elección también acota el trabajo: a lo sumo `O(n²)` rotaciones
tridiagonales y `O(n³)` scalar updates de eigenvectors. Usar `64*n²` sweeps
permitiría un worst-case artificial `O(n⁴)` al acumular columnas y queda
rechazado.

Deflation y success se prueban antes del cap, por lo que un último sweep que
consume la unidad final puede converger. Un no finito producido durante un
sweep falla inmediatamente y gana sobre el posible agotamiento siguiente. No
se retorna un aggregate parcial.

Habrá un entry module-private con `maxSweeps` explícito para qualification del
failure path. La función pública siempre calcula la política anterior; el cap
no es argumento ni opción pública.

## 15. Assembly, rescale y validación final

Al converger, toda `e[i]` debe comparar exactamente igual a cero y se
canonicaliza a `+0`. Luego:

1. cada `d[i]` se multiplica por `matrixScale`;
2. cada resultado se exige finito;
3. todo zero se escribe `+0`;
4. se ordenan values ascendentes y se permutan columnas;
5. se valida finitud completa de `values` y `vectors`;
6. se retorna `SymmetricEigen<T>(values,vectors)` transfiriendo ambos owners.

El kernel no vuelve a consultar `A`, no reconstruye para certificar el
resultado y no impone signo. Las garantías numéricas se califican externamente
mediante residual, ortogonalidad y reconstrucción.

## 16. Casos especiales normativos

| entrada | resultado/conducta |
|---|---|
| `0×0` | values `0`, vectors `0×0`, éxito sin backing |
| `1×1 [a]` | values `[a]`, vectors `[1]` |
| diagonal | diagonal ordenada y columnas de identidad permutadas |
| cero `n×n` | `n` valores `+0`, vectors identidad |
| repeated | multiplicidad preservada; base ortonormal no canónica |
| clustered | iteración y deflation local; no se fusionan valores |
| positive definite | todos los values calculados positivos salvo error de redondeo; no se usa Cholesky |
| indefinite | valores de ambos signos, sin excepción |
| singular/semidefinite | zeros ordinarios, sin rank failure |
| no square | `ShapeMismatch` antes de scans/allocation |
| no finita | `NonFiniteMatrixException` antes de simetría |
| aproximadamente simétrica | `NotSymmetricMatrixException` si alguna pareja difiere |
| escala uniforme extrema | normalización por `matrixScale`, rescale final validado |

No se promete preservar positive definiteness representacional en el último
bit: un eigenvalue exacto muy pequeño puede redondear a cero o cambiar de
signo dentro del backward error del algoritmo. La API no clasifica definitud.

## 17. Ownership y preservation

`symmetricEigen(ref Matrix<T> A)` presta shared. La call ordinaria
`symmetricEigen(A)` usa borrow adaptation y después del retorno o una Exception
capturada el caller conserva el mismo owner, shape, capacities, stride,
backing y valores.

`values` y `vectors` son owners independientes de `A` y entre sí. Ninguna view
escapa. El workspace normalizado también es owning independiente y se destruye
antes de retorno; en throw, unwind destruye exactamente una vez todos los
temporales.

El orden shape/validación antes de allocation es deliberado. A diferencia del
wrapper Cholesky histórico, este milestone no necesita compartir validación
con una variante `InPlace`; puede rechazar inputs inválidos sin copiar primero.

## 18. Allocations y storage

En la ruta general `n>=2`, no diagonal, existen:

- `W:n×n`, workspace compacto con trailing lower triangle y reflectors;
- `values:n`, que comienza como `d` y se transfiere al resultado;
- `e:n-1`;
- `tau:n-2`;
- `work:n` para el vector `w` de la actualización rank-2;
- `vectors:n×n`, que se transfiere al resultado.

Son dos matrices `n×n` simultáneas —una temporal y una de resultado— más
`O(n)` scalars. No existe tercera Matrix dense, transpose owning, Matrix
tridiagonal, Matrix diagonal, lista de bloques o allocation por reflector,
rotación o sweep.

La ruta diagonal sólo asigna los dos owners de resultado. Los constructors
zero-filled pueden escribir inicialmente el backing antes de llenarlo, como
en el package vigente; eso es un pase de inicialización, no otra allocation.

## 19. Complejidad

Para dense `n×n`:

- validación, scale y copy: `O(n²)`;
- tridiagonalización Householder: `O(n³)`;
- materialización de reflectors en `vectors`: `O(n³)`;
- QR sobre `d/e`: `O(n²)` scalar work típico y también acotado por budget;
- acumulación de rotaciones en `vectors`: `O(n³)` típico y acotado;
- sort: `O(n²)` comparisons y `O(n²)` movement total de columnas;
- memoria peak adicional, incluido resultado: `2n²+O(n)` elementos.

El coste total es `O(n³)` bajo el cap productivo. El algoritmo shifted suele
converger mucho antes del cap, pero V1 no promete una cantidad de sweeps por
eigenvalue ni convergencia para todo input representable. El modo de fallo
acotado es parte del contrato.

## 20. Qualification

La qualification ejecutará `float32` y `float64` en O0 y O2, tanto por import
consumer como mediante white-box para fases privadas. Cubrirá:

- `0×0`, `1×1`, diagonal, identidad y cero;
- symmetric dense determinista;
- positive definite construida como `B^T B + alpha I`;
- indefinite con spectrum mixto;
- singular y semidefinite;
- eigenvalues repetidos con eigenspaces de dimensión mayor que uno;
- clusters separados por pocas ulps y clusters bien separados del resto;
- off-diagonal cero y múltiples bloques ya desacoplados;
- escala uniforme large, small, normal y subnormal;
- shape no square, simetría aproximada rechazada, signed zeros;
- NaN/infinito y su precedencia sobre asimetría;
- cap cero/pequeño mediante hook y estado interno no finito;
- preservation del input, independencia de backings y shapes vacías;
- ausencia source/IR de `qr(T)`, characteristic polynomial, LAPACK y
  allocations dentro del loop iterativo.

Para cada retorno se medirán con acumulación host suficientemente robusta:

```text
R_eigen = A*Q - Q*diag(values)
R_orth  = Q^T*Q - I
R_recon = Q*diag(values)*Q^T - A
```

Los umbrales serán relativos a escala y dimensión, de orden
`C*n*epsilon(T)`, usando normas escaladas; `C` es margen de qualification
documentado por métrica, no tolerance productiva. Zero y casos exactos tienen
assertions específicas para evitar dividir por norma cero.

`numpy.linalg.eigh` y `numpy.linalg.eigvalsh` se invocarán sólo desde el host
de test como oracle independiente. Se comparan los values ordenados con error
absoluto/relativo escalado por la norma de `A`; el product source y binario no
importan NumPy.

No se comparan columnas individualmente con NumPy. Para spectra simples basta
residual más ortogonalidad. Para multiplicidades/clusters conocidos se
comparan projectors `Q_cluster*Q_cluster^T` o ángulos de subespacio; nunca
signos ni una base particular. La reconstrucción completa ofrece además una
prueba independiente de la correspondencia value/column.

Los runs O0/O2 no necesitan ser bitwise idénticos; ambos deben satisfacer el
mismo contrato, ordering, clases de error y bounds numéricos.

## 21. Alternativas rechazadas

**Jacobi two-sided como kernel V1:** es simple conceptualmente y robusto para
eigenvectors, pero requiere sweeps sobre toda la Matrix dense, un criterio
global de convergencia y más traffic `O(n³)` iterativo. No aprovecha la
infraestructura compacta `d/e` ya desarrollada. Puede servir como oráculo
independiente o variante futura de alta precisión.

**Characteristic polynomial/root finding:** amplifica conditioning, no entrega
eigenvectors de forma estable y abandona la estructura simétrica. Queda
prohibido.

**QR dense repetido:** materializa `Q/R` en cada step, destruye el coste
`O(n)` del sweep tridiagonal y asigna storage innecesario.

**Formar powers o inverse iteration por eigenvalue:** duplica trabajo, necesita
políticas de shift/normalización separadas y complica multiplicidades.

**QL fijo o QR/QL adaptativo:** QL fijo no aporta ventaja general y hace el
chase decreciente menos natural en el source actual. La dirección adaptativa
puede acelerar algunos bloques pero duplica superficie privada y qualification;
se difiere hasta disponer de mediciones.

**Orden descendente:** copia una propiedad útil de SVD a un spectrum signed
sin su motivación de prefijos dominantes y diverge de `eigh`/LAPACK.

**Tolerance pública de simetría:** no existe un valor universal ni una Matrix
efectiva inequívoca cuando los dos triángulos difieren.

## 22. Secuencia de implementación posterior

Este cierre no autoriza implementación. La secuencia recomendada es:

1. `LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1/V1`: aggregates privados,
   escala, reducción compacta y materialización de `Qh`;
2. `LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1/V1`: deflation, shift,
   chase, budget y hooks white-box;
3. `LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ASSEMBLY-V1`: validación pública, casos
   rápidos, rescale, sort y aggregate;
4. `LINEAR-ALGEBRA-SYMMETRIC-EIGEN-QUALIFICATION-CLOSURE-1`: oracle,
   residuals, subspaces, O0/O2 y cierre de recursos.

Cada vertical debe conservar los nombres y contratos públicos de este
documento. Cambiar algoritmo interno sin cambiar API sigue requiriendo
qualification equivalente.

## 23. Fuera de scope confirmado

Quedan fuera de V1:

- eigenproblem real no simétrico y eigenvalues complejos;
- generalized eigenproblems;
- partial spectrum, interval/index selection y largest-`k`;
- eigenvalues-only;
- `symmetricEigenInPlace`;
- tolerance o symmetrization automática;
- canonicalización de signos/bases;
- divide-and-conquer, MRRR, Lanczos y sparse matrices;
- matrices Hermitian complex;
- GPU/SIMD/BLAS/LAPACK backends;
- clasificación automática de definitud, rank o condition number.

Estas extensiones no deben cambiar el significado de `SymmetricEigen<T>`, el
orden ascendente ni la correspondencia columnar cerrada aquí.
