# LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1 — reducción simétrica compacta

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Este milestone es exclusivamente documental. Cierra el vertical privado que,
para un workspace real simétrico ya normalizado, produce

```text
W0 -> Qh^T W0 Qh = T
```

donde `T` es simétrica tridiagonal. No modifica source productivo, tests,
consumer, compiler, runtime, standard library ni API pública.

Autoridad normativa, en orden:

- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1-REPORT](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-STABLE-NORM-V1](LINEAR_ALGEBRA_STABLE_NORM_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md).

No se encontró contradicción entre esas autoridades y el source vigente.

## 1. Alcance y resultado

El vertical implementará sólo source module-private de `linearAlgebra`:

1. reducción Householder simétrica usando el triángulo inferior;
2. almacenamiento compacto de las colas de los reflectores;
3. producción independiente de `d/e`;
4. materialización posterior de `Qh` desde esos reflectores;
5. entrega de `d/e/Qh` al futuro QR tridiagonal.

Para `W0:n×n`, el resultado matemático es:

```text
T[i,i]     = d[i]
T[i+1,i]   = e[i]
T[i,i+1]   = e[i]
T[i,j]     = 0, abs(i-j)>1
Qh         = H_1 H_2 ... H_(n-2)
T          = Qh^T W0 Qh
Qh^T Qh    = I                         // sujeto a redondeo IEEE
```

No existe owner para `T`, `H_k` ni una copia del upper triangle. Este vertical
no ejecuta QR, deflation, shifts, sorting, rescale ni assembly público.

## 2. Auditoría del source real

### 2.1 Reutilización literal

El source vigente permite reutilizar literalmente:

- `stableNormRange<T>(VectorView<T,Column>, first, last)`, con extremos
  inclusivos e índices one-based;
- `column(W,k)`, que crea un descriptor O(1) y no un owner;
- `matrixFilled`, `vectorFilled` e `identity<T>(n)`;
- `isFiniteInternal` y `requireFiniteInternal`, cuyo fallo algorítmico es
  `NumericalConvergenceException`;
- la formación Householder de `reduceTallBidiagonal`: selección de `beta`,
  `pivotRatio`, `denominatorRatio`, cola escalada y `tau`;
- el patrón de postmultiplicación por un reflector usado al materializar el
  factor derecho de una reducción: dot por fila, `scale=tau*dot` y update de
  columnas, sin Matrix temporal;
- loops crecientes `usize`, indexación ordinaria one-based y guards explícitos
  antes de formar expresiones como `n-1` o `n-2`.

En particular, la formación futura conserva el árbol:

```text
tail = (xj / beta) / (pivotRatio - one)
```

y no lo reemplaza por `xj/(x1-beta)`.

### 2.2 Reutilización sólo como convención

`qrInPlace` no es un kernel reutilizable. Forma `Q:m×m`, aplica reflectores a
una Matrix general, usa `first=x1-alpha`, vuelve a calcular `2/(v^T v)` y
borra las colas al producir `R`. Sólo fija la selección de signo, la identidad
`Q<-QH` y el orden one-based.

La bidiagonalización SVD sí aporta literalmente la formación escalar, pero no
su reducción: usa reflectores izquierdos y derechos distintos y updates
one-sided. Aquí el mismo `H_k` actúa a ambos lados y exige un update simétrico
rank-2. Tampoco se reutilizan su orientation tag, sus shapes thin ni sus
aggregates.

`copyMatrixForFactorization` copia todo el rectángulo lógico sin escalar. No se
invoca literalmente en este vertical: el assembly necesita un helper privado
derivado que cree `W` una vez y copie sólo el lower triangle dividido por la
escala. Sí se conserva su regla de leer por indexación Matrix ordinaria, sin
asumir `stride==columns` y sin leer padding.

Los Givens, `stableHypot`, QR bidiagonal y QR público no participan en esta
fase. No se requiere capability ausente.

## 3. Frontera de scaling y precondiciones

La frontera privada recibe un `Matrix<T>` owning ya preparado:

```aether
SymmetricTridiagonalSeed<T> symmetricTridiagonalSeedInPlace<T: IEEEFloat>(
    Matrix<T> normalizedWorkspace);
```

Su precondición interna es:

- shape `n×n` ya comprobada;
- lower triangle finito, simétrico por construcción y autoridad única;
- `normalizedWorkspace[i,j]=A[i,j]/matrixScale` para `i>=j`;
- `matrixScale` finito y positivo en la ruta general;
- upper triangle sin autoridad; con el helper previsto queda en `+0` por la
  inicialización de `matrixFilled`.

El assembly de `symmetricEigen` es la única autoridad para shape, finitud,
simetría exacta, `matrixScale`, casos rápidos y creación de `W`. Retiene
`matrixScale` para el rescale final; no lo pasa a este vertical. El vertical no
reescanea el input público, no divide otra vez y no traduce input inválido.

Los checks `requireFiniteInternal` descritos abajo sí pertenecen al kernel:
detectan breakdown producido por aritmética interna y conservan la excepción
`NumericalConvergenceException` ya cerrada.

La implementation V1 puede exponer además un entry module-private que consume
directamente el workspace sólo para composición interna. No habrá wrapper
público ni función test-only en el package.

## 4. Representación privada mínima

Se fijan dos fronteras nominales module-private, equivalentes a:

```aether
struct CompactSymmetricTridiagonalReduction<T: Storable> {
    Matrix<T> workspace;
    Vector<T,Column> d;
    Vector<T,Column> e;
    Vector<T,Column> tau;
}

struct SymmetricTridiagonalSeed<T: Storable> {
    Vector<T,Column> d;
    Vector<T,Column> e;
    Matrix<T> vectors;
}
```

El primero mantiene juntos los owners cuya interpretación depende del layout
compacto. Parámetros separados permitirían mover `workspace` o `tau` antes de
materializar `Qh` y harían implícita esa dependencia. El segundo es la frontera
exacta con `LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1`: esa fase necesita
sólo `d/e/vectors` y nunca debe ver colas Householder.

`work:n` es scratch local del kernel de reducción. No es estado matemático, no
sale en ninguno de los aggregates y se destruye al terminar la reducción.
Aunque materialización y reducción podrían recibir owners separados, los
entry points de composición consumirán/producirán los aggregates para hacer
explícito el orden de vidas.

Todos los tipos, fields auxiliares y funciones permanecen module-private. No
se añade API pública.

La composición se divide en helpers equivalentes a:

```aether
int reduceSymmetricTridiagonal<T: IEEEFloat>(
    MatrixViewMut<T> W,
    usize n,
    ref mut Vector<T,Column> d,
    ref mut Vector<T,Column> e,
    ref mut Vector<T,Column> tau,
    ref mut Vector<T,Column> work);

CompactSymmetricTridiagonalReduction<T>
compactSymmetricTridiagonalReduction<T: IEEEFloat>(Matrix<T> workspace);

Matrix<T> materializeSymmetricTridiagonalQ<T: IEEEFloat>(
    ref Matrix<T> workspace,
    ref Vector<T,Column> tau);
```

El wrapper compacto asigna una vez `d/e/tau/work`, llama al único kernel con
`matrix_view_mut(workspace)` y retorna `workspace/d/e/tau`; `work` muere allí.
El entry `symmetricTridiagonalSeedInPlace` materializa `vectors`, mueve
`d/e/vectors` al seed y deja morir `workspace/tau`. Estos nombres y la
existencia de un único kernel de reducción quedan fijados para V1.

## 5. Shapes y casos pequeños

Para todo `n` se calculan extents sin underflow:

```text
offDiagonal = 0; if n > 0: offDiagonal = n-1
reflectors  = 0; if n > 2: reflectors  = n-2

d       : n
e       : offDiagonal
tau     : reflectors
work    : n
vectors : n×n
```

- `0×0`: no hay step; `d/e/tau/work` tienen dimensión cero y `vectors` es
  `identity(0)`, exactamente `0×0` sin backing;
- `1×1`: `d[1]=W[1,1]`, `e/tau` vacíos y `vectors=[1]`;
- `2×2`: no hay reflector; se copian ambas diagonales y
  `e[1]=W[2,1]`; `vectors=I_2`;
- `n>=3`: se ejecuta `k=1..n-2`.

El assembly normalmente resuelve `0×0`, `1×1` y diagonal antes de esta
frontera, pero el helper privado queda total sobre esas shapes para poder
calificarlo aisladamente. Nunca se evalúa `n-1` si `n==0` ni `n-2` si `n<2`.

## 6. Formación exacta de cada reflector

En el step `k`, sea `p=k+1` y:

```text
x = W[p:n,k]
norm = stableNormRange<T>(column(W,k), p, n)
```

La view de columna termina antes de mutar `W`. Si `norm` no es finito,
`requireFiniteInternal(norm)` falla antes de cualquier store del reflector.

La formación normativa es:

```text
beta = +0
tauValue = +0

if norm != +0:
    beta = norm
    if W[p,k] >= +0: beta = -norm
    pivotRatio = W[p,k] / beta
    denominatorRatio = pivotRatio - 1
    for i = p+1..n increasing:
        W[i,k] = (W[i,k] / beta) / denominatorRatio
    tauValue = 1 - pivotRatio

W[p,k] = beta
e[k] = beta
tau[k] = tauValue
```

`beta`, `pivotRatio`, `denominatorRatio`, cada tail y `tauValue` se exige
finito antes de su store. No se usa epsilon. Cuando `norm==0` no se divide, se
escriben `beta=e[k]=tau[k]=+0`, y las celdas inferiores quedan semánticamente
inactivas. Materialización y update no leen una cola si `tauValue==0`.

### 6.1 Demostración algebraica

Para `norm!=0`, escriba `a=x[1]`, `beta^2=x^T x` y
`v=[1; x_tail/(a-beta)]`. La fórmula escalada del source es la misma porque:

```text
beta * (a/beta - 1) = a-beta.
```

Además:

```text
tau = 1-a/beta = (beta-a)/beta = 2/(v^T v)
v^T x = -beta
```

y por tanto:

```text
H x = x - tau*v*(v^T x)
    = x + (beta-a)*v
    = [beta, 0, ..., 0]^T.
```

Así `H=I-tau*v*v^T` anula exactamente en aritmética real las posiciones
`k+2..n` de la columna `k`. Como `H^T=H` y `H^2=I`, aplicar el mismo reflector
a ambos lados preserva simetría y eigenvalues.

### 6.2 Degenerados y signed zero

Si la cola es cero pero `x[1]` no, `norm=abs(x[1])`, `pivotRatio=-1`,
`tau=2` y `v=[1]`: el reflector cambia el signo del pivot. No se confunde con
identidad.

Si todo `x` contiene sólo `+0/-0`, `stableNormRange` retorna `+0`; el pivot
publicado en `e` y `W[p,k]` es `+0` y `tau=+0`. Un pivot `-0` con alguna
entrada posterior no nula compara `>=+0` según igualdad/orden IEEE y elige
`beta=-norm`, igual que SVD/QR. Las colas cero de un reflector activo pueden
conservar signo; no cambian su acción matemática.

## 7. Update simétrico rank-2

Tras formar un reflector activo, `A` denota el bloque lower-authoritative
`W[p:n,p:n]`. Con `v[p]=1` implícito se evalúa:

```text
w     = tauValue * A * v
alpha = -(tauValue / (1+1)) * (v^T * w)
w     = w + alpha*v
A     = A - v*w^T - w*v^T
```

No se forma `A` como otra Matrix. Una lectura simétrica es exactamente:

```text
A[i,j] = W[i,j] if i>=j else W[j,i]
```

### 7.1 Traversal y orden aritmético

El source V1 fijará estos loops y árboles, sin reassociation deliberada:

1. Para `i=p..n` creciente, iniciar `dot=W[i,p]`, que multiplica el uno
   implícito. Para `j=p+1..n` creciente, cargar `aij` desde el lower triangle y
   ejecutar `dot = dot + aij * W[j,k]`. Después calcular
   `work[i]=tauValue*dot`.
2. Calcular `dot=work[p]`; para `j=p+1..n` creciente ejecutar
   `dot = dot + W[j,k]*work[j]`.
3. Definir `two=one+one` y evaluar primero `tauValue/two`, luego su negación y
   finalmente la multiplicación por `dot`:
   `alpha=-(tauValue/two)*dot`.
4. Ejecutar `work[p]=work[p]+alpha`; para `i=p+1..n` creciente,
   `work[i]=work[i]+alpha*W[i,k]`.
5. Para `i=p..n` creciente y `j=p..i` creciente, cargar
   `vi = (i==p ? one : W[i,k])` y
   `vj = (j==p ? one : W[j,k])`, calcular:

   ```text
   first = W[i,j] - vi*work[j]
   next  = first - work[i]*vj
   W[i,j] = next
   ```

Cada `dot`, elemento de `work`, `alpha`, `first` y `next` se exige finito antes
de que un valor no finito sea almacenado o reutilizado. Los checks no cambian
el árbol aritmético productivo anterior.

`work[1..p-1]` es stale y nunca se lee en ese step. El owner se crea una vez
antes del loop de `k` y se reutiliza; no se limpia completo entre reflectores.

### 7.2 Derivación del update

Como `A=A^T` y `w=tau*A*v`:

```text
H A H = A - tau*v*v^T*A - tau*A*v*v^T
            + tau^2*v*(v^T*A*v)*v^T.
```

Además `v^T*w=tau*v^T*A*v` y
`alpha=-(tau/2)*(v^T*w)`. Entonces:

```text
A - v*(w+alpha*v)^T - (w+alpha*v)*v^T = H A H.
```

La forma rank-2 implementa por ello la similaridad completa escribiendo sólo
el lower triangle.

### 7.3 Alias y vistas

`workspace` y `work` son owners distintos. No hay view viva al entrar en el
update; la view usada por `stableNormRange` ya terminó. Los tails viven en la
columna `k`, fuera del trailing block `p:n,p:n`, y ninguna escritura del
update puede alterarlos. Todos los dots terminan antes del update in-place del
bloque. No existe alias entre `d/e/tau`, `work` y `W`.

## 8. Loop completo y copia de d/e

El kernel creciente ejecuta:

```text
k = 1
while k <= n-2:                    // sólo tras comprobar n>2
    d[k] = W[k,k]                  // diagonal ya congelada
    formar H_k y escribir e[k], tau[k], W[k+1,k]
    si tau[k] != +0: update rank-2 de W[k+1:n,k+1:n]
    k = k+1

si n == 1:
    d[1] = W[1,1]
si n >= 2:
    d[n-1] = W[n-1,n-1]
    d[n]   = W[n,n]
    e[n-1] = W[n,n-1]
```

Para `n==2` la rama final produce todo `d/e`. Para `n>=3`, los `d[k]` y
`e[k]` se copian en el momento en que quedan congelados; sólo los dos últimos
diagonales y el último off-diagonal se copian al salir. No hay pase de
extracción `O(n)` posterior. `d/e` son autoridades independientes durante toda
la vida de la reducción; las copias en `W` existen para describir el layout y
no serán consultadas por el QR posterior.

## 9. Layout compacto sin ambigüedad

Después de reducir:

```text
W[i,i]       = d[i]                         para i=1..n
W[i+1,i]     = e[i]                         para i=1..n-1
W[r,k]       = tail de H_k, r=k+2..n        para k=1..n-2
W[i,j], i<j  = no autoritativo; normalmente +0
```

El uno de cada `v_k` es implícito en la posición `k+1`; esa celda contiene
`beta=e[k]`, nunca uno. `tau[k]` decide si la cola es activa. Con `tau[k]==0`,
cualquier signed zero o valor stale de `W[k+2:n,k]` es irrelevante y está
prohibido leerlo.

Las categorías del lower triangle son disjuntas: diagonal, primera
subdiagonal o tail de exactamente un reflector. Al materializar `Qh` sólo se
leen `tau[k]` y `W[k+2:n,k]`; al entrar a QR sólo se mueven `d/e/vectors`.
Por ello ninguna fase posterior interpreta un slot de dos maneras.

## 10. Materialización exacta de Qh

Con la reducción compacta todavía viva se crea:

```text
vectors = identity<T>(n)
```

Luego se recorren obligatoriamente `k=1..n-2` en orden creciente. Para
`p=k+1`, si `tau[k]!=+0`, cada fila `r=1..n` se actualiza así:

```text
dot = vectors[r,p]
for j=p+1..n increasing:
    dot = dot + vectors[r,j]*W[j,k]
scale = tau[k]*dot
nextPivot = vectors[r,p]-scale
for j=p+1..n increasing:
    next = vectors[r,j]-scale*W[j,k]
```

`dot`, `scale`, `nextPivot` y cada `next` se verifican finitos antes del store.
El dot concluye antes de modificar la fila. Primero se almacena `nextPivot` y
luego los tails crecientes; esos stores ya no alimentan el mismo reflector.
No se crea Vector, axis owning, Matrix `H` ni allocation por step.

Esta es postmultiplicación por `H_k`. Partiendo de identidad y usando orden
creciente:

```text
vectors = I*H_1*H_2*...*H_(n-2) = Qh.
```

Como la reducción aplicó sucesivamente
`W_k=H_k*W_(k-1)*H_k`, la relación final es:

```text
T = H_(n-2)...H_1 W0 H_1...H_(n-2)
  = Qh^T W0 Qh.
```

Orden descendente produciría el producto inverso y queda prohibido.

Tras materializar con éxito, se destruyen `workspace/tau`; `d/e/vectors` se
mueven al `SymmetricTridiagonalSeed`. El QR tridiagonal actualiza `d/e` y
postmultiplica las mismas columnas de `vectors` por sus Givens.

## 11. Finitud y failure atomicity

La entrada pública ya fue validada. Dentro del vertical se chequean:

- norma, escalares de formación y cada tail;
- acumuladores y resultados de `work`;
- `alpha` y cada store del trailing block;
- acumuladores y stores de materialización;
- `d/e/tau` antes de entregar el aggregate.

Se reutiliza `requireFiniteInternal`; no hay nueva exception. Ante failure,
unwind destruye exactamente una vez `W`, `d`, `e`, `tau`, `work` y, si ya
existe, `vectors`. No sale estado parcial. No se intenta restaurar el workspace
consumido.

## 12. Allocations y ownership

En la ruta general no diagonal `n>=3` existen exactamente estos owners
numéricos:

```text
W       : Matrix<T> n×n
d       : Vector<T,Column> n
e       : Vector<T,Column> n-1
tau     : Vector<T,Column> n-2
work    : Vector<T,Column> n
vectors : Matrix<T> n×n
```

El assembly asigna y llena `W`; este vertical consume ese owner. El vertical
asigna `d/e/tau/work/vectors`. `d` se convierte después en `values`, `e` pasa
al QR y `vectors` es el futuro field público. `W/tau/work` son temporales del
vertical.

Todos se asignan una sola vez mediante constructors existentes. No hay
allocation dentro de `k`, del matvec rank-2, del update triangular ni de la
materialización. Views y aggregates son descriptors/valores O(1), no owners
de backing.

Para `n>=3`, una qualification del entry owning observa seis backings contando
el workspace de entrada; variar `n` no cambia ese número. En shapes pequeñas,
un extent cero no crea backing, según la semántica vigente. Los pases de
zero-fill de constructors sí cuentan como trabajo de inicialización.

El peak incluido el resultado es:

```text
2*n^2 + n + (n-1) + (n-2) + n = 2*n^2 + 4*n - 3
```

elementos para `n>=3`, más descriptors O(1).

## 13. Complejidad

Sea `m=n-k` el orden del trailing block del step `k`:

- norma y formación: `O(m)`;
- producto simétrico `A*v`: `O(m^2)`;
- dot, corrección de `work`: `O(m)`;
- escritura del lower trailing block: `m(m+1)/2 = O(m^2)`.

Por tanto:

```text
sum(k=1..n-2) O((n-k)^2) = O(n^3).
```

Materializar cada reflector actualiza `n` filas por `m` columnas:

```text
sum(k=1..n-2) O(n*(n-k)) = O(n^3).
```

También existen y no se ocultan:

- allocation/zero-fill/copia lower de `W`: `O(n^2)` en assembly;
- zero-fill de `d/e/tau/work`: `O(n)`;
- zero-fill y diagonal de `identity(n)`: `O(n^2)`;
- stores finales de los últimos `d/e`: `O(1)`.

El vertical completo es `O(n^3)` tiempo y `2n^2+O(n)` storage incluido
`vectors` y el workspace consumido.

## 14. Qualification V1

`LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1` añadirá qualification white-box
para `float32` y `float64`, O0 y O2. El fixture se compila como copia test-only
del módulo para alcanzar símbolos privados; no se publica un hook productivo.

### 14.1 Casos

La matriz mínima incluye:

- `0×0`, `1×1`, `2×2`;
- diagonal no constante e identidad;
- cero con mezclas de `+0/-0`;
- symmetric dense determinista;
- positive definite e indefinite;
- filas/columnas y bloques repetidos;
- rank-deficient y subbloques desacoplados;
- escala extrema **ya normalizada**, incluyendo mezcla de uno, valores tiny y
  subnormales representables;
- reflector cero;
- tail cero con primer componente positivo y negativo no cero, que debe dar
  `tau=2`;
- pivot `+0` y `-0` con tail no nula;
- tails con signed zeros.

Los tests de input no square, no finito y asimetría pertenecen al assembly y
no se duplican aquí. Sí se fuerza un breakdown interno no finito mediante un
fixture controlado si puede hacerse sin violar la precondición pública, para
verificar `NumericalConvergenceException` y cleanup.

### 14.2 Oráculo host independiente

El harness host conserva `W0` antes de mover el workspace, obtiene
`d/e/vectors` del fixture white-box y reconstruye por loops propios, sin llamar
a helpers de `linearAlgebra` ni al futuro QR:

```text
L = Qh^T * W0 * Qh
T(i,j) = d[i]                    si i==j
         e[min(i,j)]             si abs(i-j)==1
         0                       en otro caso
O = Qh^T * Qh - I
```

Comprueba por separado:

```text
||L-T|| / max(1,||W0||) <= C_tri*n*epsilon(T)
||O||                   <= C_orth*n*epsilon(T)
max(abs(L[i,j]), abs(i-j)>1) <= C_band*n*epsilon(T)*max(1,||W0||)
```

Las normas y productos del oracle se implementan en el host con acumulación
independiente y escalada; outputs float32 se acumulan al menos en float64. Las
constantes `C_tri/C_orth/C_band` se fijan y justifican en el reporte V1, no son
tolerances productivas. Para zero y casos exactos se usan assertions exactas
adicionales, incluida canonicalización `+0` de `e` degenerado.

También se comprueba directamente `W`/`tau` antes de materializar: pivots,
tails según la fórmula, `tau==0` que inhibe lecturas y partición exacta de
slots. La reconstrucción no forma parte del binario productivo.

### 14.3 Ownership, allocations e IR

La qualification demostrará:

- aggregates, entry points y helpers inaccesibles por import;
- preservación del `W0` host y consumo único del workspace Aether;
- shapes exactas, incluidos zero extents;
- exactamente seis backings para el entry owning general `n>=3`, con el
  workspace de entrada incluido, en O0/O2;
- el mismo conteo para al menos dos órdenes distintos, demostrando que no hay
  allocation por reflector;
- ningún `Matrix H`, `Matrix T`, transpose owning ni owner de axis;
- ausencia source/IR de call al `qr` público, LAPACK/BLAS, intrinsic
  Householder o compiler/runtime opcode nuevo;
- calls a `stableNormRange` y concretización float32/float64;
- ausencia post-monomorphization de `GenericParam`, witness, vtable, boxing,
  `TypeId` y call indirecta numérica;
- source scan del rango del kernel sin `matrixFilled`, `vectorFilled`,
  `identity` ni otra llamada allocadora dentro de los loops;
- `git diff --check`.

El diff del V1 se limitará a `linearAlgebra` y qualification. Cualquier gap de
lenguaje real se separará como milestone propio; esta arquitectura no autoriza
cambios de compiler/runtime.

## 15. Capabilities y lowering

La constraint privada es `T: IEEEFloat`. Las operaciones requeridas ya están
cubiertas por `Zero`, `One`, `Add`, `Sub`, `Mul`, `Div`, `Negate`, `Equal`,
`Order`, `Abs` y `Sqrt`; `Abs/Sqrt` se ejercen dentro de la norma estable. No se
agrega `copysign`, FMA, epsilon, SIMD, intrinsic, FFI ni capability.

Todo el algoritmo son structs privados, loops, branches, borrows, views e
indexación ordinaria. Bounds y overflow de índices conservan los traps
generales. No existe lowering especial para tridiagonalización.

## 16. Milestone y fuera de scope

El siguiente milestone implementable es:

```text
LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1
```

Debe implementar exactamente esta representación, reducción, materialización
y qualification privada. Después entregará `SymmetricTridiagonalSeed` a
`LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1/V1`.

Quedan fuera: QR/QL tridiagonal, deflation, Wilkinson shift, Givens, cap de
iteración, ordenamiento, rescale, API `symmetricEigen`, eigenvalues-only,
in-place público, tolerancia de simetría, dense `T`, dense `H`, BLAS/LAPACK,
Complex y cualquier cambio de compiler/runtime.
