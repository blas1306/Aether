# LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1 — QR implícito sobre bidiagonal real

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-01.

Este milestone es exclusivamente documental. No modifica `linearAlgebra`,
tests, consumer, compiler, runtime, standard library ni APIs públicas. Cierra
la fase iterativa privada que consume el seed producido por
[LINEAR-ALGEBRA-SVD-BIDIAGONAL-V1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_V1_REPORT.md).

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md) y su
  [reporte](LINEAR_ALGEBRA_SVD_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1.md)
  y los reportes
  [ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1_REPORT.md) y
  [V1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_V1_REPORT.md);
- [LINEAR-ALGEBRA-STABLE-NORM-ARCH-1](LINEAR_ALGEBRA_STABLE_NORM_ARCH_1.md) y
  [LINEAR-ALGEBRA-STABLE-NORM-V1](LINEAR_ALGEBRA_STABLE_NORM_V1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-ARCH-1](IEEE_FLOAT_CONSTANTS_ARCH_1.md) y
  [IEEE-FLOAT-CONSTANTS-V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md).

## 1. Decisión resumida

La implementación futura aplica iteración Golub–Kahan/Reinsch QR implícita,
shifted y con bulge chasing directamente sobre los vectores owning `d/e`.
Cada sweep usa un shift de Wilkinson del trailing `2×2` de `B^T B`, calculado
en coordenadas normalizadas; nunca forma `B`, `B^T B`, `d*d` ni el shift
dimensional cuando esas expresiones podrían desbordar.

La convención ortogonal única es:

```text
G(c,s) = [ c -s ]
         [ s  c ]
```

Una rotación derecha ejecuta `B <- B*G` y pertenece a `Q`; una rotación
izquierda ejecuta `B <- G^T*B` y pertenece a `P`. Al converger,
`D=P^T*B*Q`, por lo que `B=P*D*Q^T`.

La correspondencia central, que ningún helper puede invertir, es:

```text
orientation=Upper:
    rotación P -> U  <- U*G
    rotación Q -> Vt <- G^T*Vt

orientation=TransposedUpper:
    rotación Q -> U  <- U*G
    rotación P -> Vt <- G^T*Vt
```

La fase termina sólo cuando toda entrada de `e` es exactamente `+0`. Entrega
`d`, `U` y `Vt`; descarta `e` y `orientation`. No aplica `abs(d)`, no ordena y
no permuta triplets.

## 2. Entrada, estado e invariantes

La frontera privada es el aggregate owning ya implementado, equivalente a:

```aether
struct BidiagonalSVDSeed<T: Storable> {
    Vector<T,Column> d;
    Vector<T,Column> e;
    Matrix<T> U;
    Matrix<T> Vt;
    BidiagonalOrientation orientation;
}
```

Sea `k=dimension(d)`. Se exige `dimension(e)=max(k-1,0)`,
`columns(U)=k` y `rows(Vt)=k`; las demás shapes son las producidas por la
reducción. El estado mutable exacto es:

```text
d[1..k]
e[1..k-1]
U, Vt
orientation
usedSteps, maxSteps
lo, hi                    // sólo scalars del bloque elegido
```

`d/e/U/Vt` se mutan in place. `lo/hi`, shift, bulges y rotaciones son locals
fixed-size. No existe Matrix bidiagonal owning, lista de bloques, historial de
Givens ni allocation dependiente de iteraciones.

En todo punto entre rotaciones completas, `d/e` más a lo sumo un scalar
`upperBulge` o `lowerBulge` representan el centro. Al terminar cada step no
queda bulge y vuelve a existir una bidiagonal upper estricta. Las rotaciones se
acumulan inmediatamente; no se difieren ni se almacenan.

El seed legítimo proviene de una bidiagonalización finita. Shapes inválidas son
corrupción interna y conservan los traps generales; no son un fallo de
convergencia ni motivan una API de validación.

## 3. Casos vacíos y triviales

Antes de pedir `epsilon<T>()` o calcular el budget:

- `k==0` transfiere los owners `d/U/Vt` a un resultado vacío y termina;
- `k==1` transfiere `d/U/Vt` sin tocar el signo de `d[1]`;
- por construcción ambos casos tienen `e` de dimensión cero y ejecutan cero
  deflations, shifts, `stableHypot` o rotaciones.

Más generalmente, si `e` tiene dimensión cero no existe step QR. No se llama
`epsilon<T>()` en ningún camino que no pueda observar una off-diagonal.

## 4. Deflation normativa y cero canónico

Se obtiene una sola vez `eps=epsilon<T>()` para `k>=2`. Para cada
`i=1..k-1`, en orden creciente, se evalúa exactamente:

```text
a = abs(d[i])
b = abs(d[i+1])
scale = a
if scale < b: scale = b

if scale == +0:
    threshold = +0
else:
    normalizedSum = (a / scale) + (b / scale)
    threshold = (eps * scale) * normalizedSum

if abs(e[i]) <= threshold:
    e[i] = +0
```

Los paréntesis y el orden son normativos. `a/scale` y `b/scale` están en
`[0,1]`; `normalizedSum<=2`; y multiplicar `eps*scale` antes de la suma evita
formar el potencialmente no representable `a+b`. No se usa
`scale*normalizedSum`, una tolerancia decimal, una tolerancia absoluta global
ni exact-zero como política general. Un underflow del threshold muy pequeño a
`+0` sigue la aritmética IEEE concreta.

La comparación es `<=`: igualdad exacta deflaciona. Toda deflation escribe el
literal `+0`, incluso si `e[i]` era `-0`. `+0` es el único separador canónico
producido por la fase. Las búsquedas posteriores comparan `e[i]==+0`; aunque
IEEE también hace igual a `-0`, el pase de deflation lo reescribe antes de que
se seleccione un bloque.

## 5. Splitting y selección determinista

Después de un pase completo de deflation, se elige el bloque no singleton de
mayor índice. El algoritmo exacto one-based es:

```text
hi = k
while hi > 1 and e[hi-1] == +0:
    hi = hi - 1

if hi == 1:
    no queda bloque activo
else:
    lo = hi
    while lo > 1 and e[lo-1] != +0:
        lo = lo - 1
```

El resultado no vacío satisface `lo<hi`, contiene `d[lo..hi]` y
`e[lo..hi-1]`, y está limitado por `lo==1 || e[lo-1]==+0` y
`hi==k || e[hi]==+0`. El primer loop salta cuantos singletons y separadores
trailing sean necesarios. Por eso jamás devuelve un bloque singleton ni
mezcla dos bloques ya separados. Si sólo quedan singletons, la fase convergió.

No se mantiene una lista: tras cada step se vuelve a deflacionar y buscar desde
`k`. Esta política procesa siempre el `hi` más grande y favorece convergencia
bottom-right.

## 6. Givens único

Para un par finito `(f,g)`, el constructor privado ejecuta:

```text
r = stableHypot(f,g)
if r == +0:
    c = 1
    s = +0
else:
    c = f / r
    s = g / r
```

Así `G^T*[f,g]^T=[r,0]^T` y `[f,g]*G=[r,0]`. No se cambia el signo positivo
de `r`, no se duplica hypot y no se llama libm. El caso ambos ceros es la
identidad exacta. `stableHypot` es la autoridad privada existente, con su orden
de operaciones vigente.

Cada `r/c/s` se valida como finito antes de usarlo. Para valores finitos cuyo
hypot matemático no sea representable, `r` puede ser infinito y se toma el
failure de convergencia definido en §13; no se intenta una rotación con
`c=s=0` accidental.

## 7. Shift de Wilkinson escalado

Para el bloque `lo..hi`, `hi>lo`, se usan las entradas del trailing principal
`2×2` de `B^T B`. Sea:

```text
x = d[hi-1]
y = e[hi-1]
z = d[hi]
w = (hi-2 >= lo) ? e[hi-2] : +0
sigma = max(abs(x), abs(y), abs(z), abs(w))
```

`w=+0` en un bloque de tamaño dos porque `e[lo-1]` es el separador externo, no
parte del bloque. Un bloque activo garantiza `sigma!=0`. Se normaliza:

```text
xn = x / sigma
yn = y / sigma
zn = z / sigma
wn = w / sigma

A = (xn * xn) + (wn * wn)
C = (zn * zn) + (yn * yn)
R = xn * yn
delta = (A - C) / (1 + 1)
h = stableHypot(delta, R)
denominator = abs(delta) + h

if denominator == +0:
    correction = +0
else:
    magnitudeR = abs(R)
    correction = magnitudeR * (magnitudeR / denominator)

if delta < +0:
    lambda = C + correction
else:
    lambda = C - correction

if lambda < +0:
    lambda = +0
```

La convención `delta==0` elige determinísticamente el eigenvalue menor. El
clamp final corrige sólo un valor negativo por redondeo de una Matrix
semidefinida positiva; no es una tolerancia ni una decisión de rango.

El shift se conserva como el par fixed-size `(sigma,lambda)`, cuyo significado
es `mu=sigma^2*lambda`. **Nunca se materializa `mu`**: `sigma^2` puede
desbordar aunque todos los cocientes necesarios sean representables. Todas las
entradas normalizadas tienen magnitud a lo sumo uno; `A/C` a lo sumo dos; y la
forma `|R|*(|R|/denominator)` evita cuadrar `R` antes de dividir. Todos los
intermedios se validan como finitos.

Si `d[hi]==+0` o `-0` y no se ejecutó antes el chase especial de §9, se fuerza
`lambda=+0` y `sigma=+0`: el step es QR no shifted. Esta regla
evita depender de la elección del eigenvalue en el extremo rank-deficient y
permite deflacionar el cero trailing sin dividir por él.

## 8. Par implícito inicial sin overflow

El primer Givens derecho representa el par clásico
`(d[lo]^2-mu, d[lo]*e[lo])`, pero se calcula dividido por una escala común al
cuadrado. Para el shift `(sigma,lambda)` de §7:

```text
t = max(abs(d[lo]), abs(e[lo]), sigma)

dn = d[lo] / t
en = e[lo] / t
sn = sigma / t

f = (dn * dn) - ((sn * sn) * lambda)
g = dn * en
```

En un bloque activo `t!=0`. `(f,g)` es proporcional al par dimensional por el
factor positivo `1/t^2`, por lo que genera la misma rotación en aritmética
exacta. No se forman `d*d`, `d*e`, `sigma*sigma` ni `mu` dimensionales. El
árbol de `f` mostrado es normativo. Para el override de shift cero se usan
`sigma=0, lambda=0`; así `t=max(abs(d[lo]),abs(e[lo]))` y valores tiny no se
aplanan por normalizarlos innecesariamente contra uno.

## 9. Cero diagonal dentro del bloque

Rank deficiency es normal. Antes del sweep shifted se busca, en orden
`j=hi-1..lo` decreciente, el primer `d[j]==+0` (la comparación incluye `-0`).
Si existe, se ejecuta un **chase de cero hacia abajo** en lugar del sweep. El
primer Givens derecho se construye desde el par real `(d[j],e[j])`; como el
bloque está activo, `e[j]!=0`, de modo que esa rotación vuelve `d[j]` no cero,
anula `e[j]` y traslada un cero exacto a `d[j+1]`. El mismo chase alternado de
§10 lleva ese cero hasta `d[hi]` y deja `e[hi-1]=+0` al terminar.

Exactamente:

```text
(cRight,sRight,rRight) = givens(d[j], e[j])
chase(j, hi, cRight, sRight, initialPairIsMatrixEntries=true)
e[hi-1] = +0
```

En la primera iteración no se escribe `rRight` por separado: la actualización
local de `d[j]/e[j]` produce ese mismo par. En iteraciones posteriores el
Givens derecho elimina el `upperBulge` como en §10. Multiplicaciones por el
`cRight=0` inicial mantienen el siguiente diagonal en signed zero; cada
rotación izquierda lo traslada una posición. La escritura final canonicaliza
el separador.

Si no hay cero en `lo..hi-1` pero `d[hi]==0`, rige el shift cero de §7. Por
tanto todo cero diagonal tiene una ruta cerrada, ninguna ruta divide por
`d[j]`, y un cero nunca causa rank failure. Si coexisten un cero interno y uno
trailing, el cero interno de mayor índice se persigue primero; la siguiente
selección resolverá los bloques resultantes.

El chase especial completo consume una unidad del mismo budget que un sweep
shifted. No introduce un loop interior no acotado: hace exactamente
`hi-j` pares de rotaciones.

## 10. Bulge chase escalar exacto

Este pseudocódigo es normativo. Todos los índices son one-based. `givens`
significa §6 y cada operación de acumulación significa §11. Los assignments de
un grupo se calculan primero en scalars temporales y sólo después se escriben,
para no leer un valor ya sobrescrito.

Un sweep shifted obtiene el primer `(cRight,sRight)` desde `(f,g)` de §8 y
llama `chase(lo,hi,...,false)`. El chase de cero usa la entrada indicada en §9.

```text
p = start
haveUpperBulge = false

while p < hi:
    if p > start:
        // fila p-1: [ e[p-1]  upperBulge ] * G
        (cRight,sRight,rRight) = givens(e[p-1], upperBulge)
        e[p-1] = rRight

    // B <- B*G sobre columnas p,p+1; filas p,p+1
    oldD0 = d[p]
    oldE0 = e[p]
    oldD1 = d[p+1]

    nextD0 = (cRight * oldD0) + (sRight * oldE0)
    nextE0 = (-sRight * oldD0) + (cRight * oldE0)
    lowerBulge = sRight * oldD1
    nextD1 = cRight * oldD1

    d[p] = nextD0
    e[p] = nextE0
    d[p+1] = nextD1
    accumulateQ(p,p+1,cRight,sRight)

    // B <- G^T*B sobre filas p,p+1; elimina lowerBulge
    (cLeft,sLeft,rLeft) = givens(d[p], lowerBulge)
    oldE0 = e[p]
    oldD1 = d[p+1]

    nextE0 = (cLeft * oldE0) + (sLeft * oldD1)
    nextD1 = (-sLeft * oldE0) + (cLeft * oldD1)
    d[p] = rLeft
    e[p] = nextE0
    d[p+1] = nextD1

    if p < hi-1:
        oldE1 = e[p+1]
        upperBulge = sLeft * oldE1
        e[p+1] = cLeft * oldE1
        haveUpperBulge = true
    else:
        haveUpperBulge = false

    accumulateP(p,p+1,cLeft,sLeft)
    p = p + 1
```

Para el sweep shifted, el primer Givens es implícito: `(f,g)` no son entries de
una fila de `B`; recién el bloque `B<-B*G` modifica `d/e`. Para el chase de
cero, `(d[start],e[start])` sí es la primera fila, y las mismas cuatro fórmulas
la convierten en `[rRight,0]`.

Tras la rotación derecha hay un único bulge debajo de la diagonal en
`(p+1,p)`. La izquierda lo elimina y, salvo en el borde, crea uno encima de la
superdiagonal en `(p,p+2)`. La siguiente derecha lo elimina. Al salir no queda
bulge. No se salta una rotación identidad: también se acumula como identidad
mediante un camino que puede omitirse sin cambiar bits del factor.

## 11. Acumulación exacta en `U/Vt`

Postmultiplicar una Matrix `M` por `G` sobre columnas `p,q` usa, para cada fila
`r=1..rows(M)` creciente:

```text
x = M[r,p]
y = M[r,q]
M[r,p] = (c*x) + (s*y)
M[r,q] = (-s*x) + (c*y)
```

Premultiplicar una Matrix `M` por `G^T` sobre filas `p,q` usa, para cada
columna `r=1..columns(M)` creciente:

```text
x = M[p,r]
y = M[q,r]
M[p,r] = (c*x) + (s*y)
M[q,r] = (-s*x) + (c*y)
```

En ambos casos se leen `x/y` antes de cualquier store. No hay reducción,
vector intrinsic, SIMD contractual, FMA ni reassociation.

El dispatch privado por orientación es exactamente:

| rotación del centro | `Upper` | `TransposedUpper` |
|---|---|---|
| derecha `Q` (`B<-B*G`) | filas de `Vt`, `Vt<-G^T*Vt` | columnas de `U`, `U<-U*G` |
| izquierda `P` (`B<-G^T*B`) | columnas de `U`, `U<-U*G` | filas de `Vt`, `Vt<-G^T*Vt` |

No se transpone un owner y no se construye `P` o `Q`. Esta tabla implementa
directamente `Upper: U<-U*P, Vt<-Q^T*Vt` y
`TransposedUpper: U<-U*Q, Vt<-P^T*Vt`.

## 12. Timing, budget y loop exterior

La política productiva única es:

```text
maxSteps = checkedMultiply(64, checkedMultiply(k,k))
usedSteps = 0

loop:
    deflate todas las e, en orden creciente
    seleccionar el bloque de mayor hi
    si no existe: éxito

    si usedSteps == maxSteps:
        lanzar NumericalConvergenceException

    si existe d[j]==0 para j=hi-1..lo:
        ejecutar un chase de cero
    si no:
        calcular shift (o shift cero si d[hi]==0)
        ejecutar un sweep shifted completo

    usedSteps = usedSteps + 1
    validar estado finito
    deflate todas las e inmediatamente, en orden creciente
```

La cabecera vuelve a ejecutar deflation deliberadamente: una sola función
normativa sirve tanto al estado inicial como al posterior, y la repetición no
cambia entries ya canonicalizadas. Deflation y selección preceden al chequeo
del cap, de modo que un step final que consume la unidad número `maxSteps`
puede converger y retornar. Sólo se lanza si aún queda un bloque cuando ya no
hay unidad disponible. Cada sweep o chase especial completo consume
exactamente una unidad; splits no reinician el contador.

Se elige `64*k*k`: es un bound total `O(k²)`, ampliamente superior a las
decenas de iteraciones por valor singular usadas como guard histórico en
implementaciones QR clásicas, sin convertir esa observación en garantía de
convergencia. `64` es política privada, no API. Ambos productos usan aritmética
checked de extents; un overflow imposible para owners válidos conserva el trap
estructural general, no se traduce a convergencia.

La implementación tendrá un entry white-box que recibe un override opcional
de `maxSteps`; el entry productivo siempre pasa el valor calculado. El hook es
module-private, no cambia firmas públicas y permite probar cap cero/pequeño sin
buscar una matriz adversarial.

## 13. Estado no finito y precedencia

El helper privado de finitud usa exactamente el patrón ya autorizado:

```text
isFiniteInternal(x) = ((x - x) == +0)
```

No se agrega `isFinite` público. Todo scalar calculado para shift o Givens se
valida antes de aplicarlo. Cada nuevo valor de `d/e` y cada combinación de
columnas de `U` o filas de `Vt` se calcula en temporales, se valida y recién
entonces se almacena. Al terminar el step se hace además un pase defensivo por
`d/e` y por `U/Vt`, en sus traversals lógicos crecientes. Encontrar NaN o
infinito en cualquier punto lanza `NumericalConvergenceException` y no se
publica el aggregate mutado parcialmente; unwind destruye sus owners.

La precedencia exacta es:

1. deflation y splitting normal del estado finito previo;
2. éxito si no queda bloque;
3. fallo de budget si queda bloque y no hay unidad;
4. cálculo validado y aplicación de un step;
5. incremento de `usedSteps`;
6. validación defensiva completa;
7. deflation inmediata y nueva selección en la cabecera.

Un no finito detectado durante el step gana sobre el agotamiento futuro: el
step ya tenía presupuesto y falla inmediatamente. Un estado que convergió en
la última unidad gana sobre el cap. Input no finito no llega aquí: el assembly
público lo rechaza antes con `NonFiniteMatrixException`.

La declaración nominal `NumericalConvergenceException` pertenece finalmente a
`SVD-ASSEMBLY-V1`, como fijó `SVD-ARCH-1`. Para permitir qualification del
vertical QR sin publicar `svd`, QR-V1 puede introducir esa misma declaración
module-private y lanzarla desde sus helpers white-box; Assembly sólo promoverá
su visibilidad a `public`, sin reemplazar su identidad ni traducir otra
excepción. No se expone el cap.

## 14. Salida y ownership

El resultado interno es equivalente a:

```aether
struct BidiagonalSVDConverged<T: Storable> {
    Vector<T,Column> d;
    Matrix<T> U;
    Matrix<T> Vt;
}
```

Antes de construirlo se comprueba que cada `e[i]` es exactamente igual a cero
y se escribe nuevamente `+0`; luego se destruye el owner `e`. `orientation` no
sobrevive: todas sus consecuencias ya fueron incorporadas en `U/Vt`. `d/U/Vt`
se transfieren, no se copian. En excepción no hay resultado parcial y unwind
libera una vez cada owner del seed.

`d` puede contener valores positivos, negativos, `+0` o `-0`. La fase no usa
`abs`, no corrige signos correlacionados, no ordena y no permuta. Valores
singulares repetidos o cero pueden producir cualquier base ortonormal válida
del subespacio degenerado y nunca causan por sí mismos una excepción.

## 15. Capabilities, lowering y allocations

Todos los helpers permanecen bajo `T: IEEEFloat`. Las operaciones observadas
están dentro de sus guarantees existentes:

```text
Zero, One, Add, Sub, Mul, Div, Negate, Equal, Order, Abs, Sqrt
```

`Sqrt` se ejerce a través de `stableHypot`; `epsilon<T>()` usa su autoridad
Core/prelude y no agrega capability. Epsilon aparece exclusivamente en
deflation/convergencia, no en rank, detección de diagonal cero, Givens, shift,
Householder ni normalización final.

Todo es source ordinario. Después de monomorphization quedan float32/float64,
loops y operaciones escalares concretas. No hay opcode QR-bidiagonal, Givens
intrinsic, backend SVD, LAPACK, `TypeId`, witness, vtable, boxing ni dispatch
numérico indirecto. Inlining de `stableHypot`, `abs`, `sqrt` y `epsilon` es
válido si conserva la semántica source.

La fase hace **cero heap allocations adicionales**. Reutiliza in place los
cuatro owners del seed y sólo crea scalars/fixed-size locals. Quedan prohibidos
Matrix/Vector temporales, arrays de shifts/rotaciones, active-block lists,
histories y transpose owners.

## 16. Complejidad

Sea `k=min(m,n)`. Un sweep del centro toca `O(k)` scalars. El cap permite
`O(k²)` sweeps totales en el peor caso de política; por ello el trabajo escalar
del centro está acotado conservadoramente por `O(k³)`, aunque la convergencia
esperada con deflation realiza `O(k²)` rotaciones/updates escalares acumulados
a través de bloques.

Cada par de rotaciones actualiza una vez columnas de `U` o filas de `Vt`, con
coste `O(m+n)`. El coste esperado de acumulación es
`O((m+n)*k²)` y el cap da un techo conservador mayor si una ejecución
patológica no deflaciona. Dentro de la SVD dense, el objetivo global permanece
compatible con `O(m*n*k)` más la iteración/acumulación bidiagonal. No se
prometen FLOPs exactos ni tiempo subcúbico.

## 17. Qualification V1

La qualification será white-box sobre seeds sintéticos y seeds producidos por
la bidiagonalización. Cubrirá float32/float64 y O0/O2, y comprobará:

- `e` termina íntegramente en `+0`, incluido mediante signo del recíproco;
- para `Upper`, el centro original se conserva como `P*diag(d)*Q^T`; para
  `TransposedUpper`, se conserva la identidad transpuesta correspondiente;
- reconstrucción full de `A` con los `U/Vt` acumulados;
- `U^T U≈I` y `Vt Vt^T≈I`, con tolerancias dependientes de tipo, dimensión y
  escala;
- ausencia de assumptions sobre signo, orden o base de multiplicidades;
- cero allocations/frees adicionales durante QR y transferencia de owners;
- visibilidad privada, HIR/MIR/SSA ordinarios y concretización por tipo.

Los casos conocidos mínimos son: `1×1`, diagonal ya convergida, `2×2`, simple
`3×3`, cero, cero diagonal interno, cero trailing, repeated singular values,
rank deficient, escalas muy diferentes, huge/tiny representables, subnormales
y `e` con signed zero.

Los tests de deflation construyen valores respecto del threshold calculado por
el tipo, no constantes decimales: claramente menor, claramente mayor, igualdad
exacta, escala local cero, very large y very small. Verifican que `<=` incluye
igualdad y que el threshold no desborda por formar `a+b`.

Los tests de shift usan casos `2×2` analíticos y un oráculo de mayor precisión.
Comprueban el trailing `2×2` correcto, finitud, invariancia razonable al escalar
y casos donde cuadrados dimensionales desbordarían. El oráculo no reutiliza los
mismos intermedios normalizados. Los tests de Givens verifican
`c*c+s*s≈1`, la componente eliminada y los casos exactos cero/identidad.

El hook de budget prueba cap suficiente, cap cero e insuficiente, la excepción
nominal, ausencia de output parcial y cleanup exacto. Casos no finitos
inyectados después de una operación ejercitan shift, Givens, `d/e` y
acumulación. No se usa una matriz adversarial como única prueba del failure.

LAPACK o mayor precisión pueden ser oráculos test-only; nunca implementación
productiva. No se compara `U/Vt` elemento a elemento para valores repetidos.

## 18. Milestone y fuera de scope

Shift, zero chase, bulge chase, acumulación, cap y fallos quedaron cerrados con
pseudocódigo suficiente para un único vertical posterior
`LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-V1`; no hace falta otro submilestone de
arquitectura numérica. Cualquier cambio de convención de Givens, dirección de
chase, shift o fórmula de deflation reabre este documento.

Permanecen fuera de scope: `svd` público, assembly preserving, normalización
de signos, `S>=0`, sort descendente, permutación final, pseudoinverse, rank,
condition number, low-rank, LAPACK productivo, Complex, full SVD y tuning
SIMD/blocked.
