# LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-ARCH-1 — QR implícito simétrico tridiagonal

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Este milestone es exclusivamente documental. No modifica source productivo,
tests, consumer, compiler, runtime, standard library ni API pública. Cierra la
fase privada que consume el `SymmetricTridiagonalSeed` ya implementado y
converge su tridiagonal simétrica mediante QR implícito shifted.

Autoridad normativa, en orden:

- [LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_ARCH_1.md);
- [LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1](LINEAR_ALGEBRA_SYMMETRIC_TRIDIAGONAL_V1_REPORT.md);
- [LINEAR-ALGEBRA-STABLE-NORM-V1](LINEAR_ALGEBRA_STABLE_NORM_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_QR_ARCH_1.md).

No se encontró contradicción entre esas autoridades y el source vigente. Son
decisiones superiores y no se reabren aquí: QR y no QL, Wilkinson trailing,
chase top-to-bottom, eigenvectors por columnas, budget global `64*n` sweeps y
deflation derivada exclusivamente de `epsilon<T>()`.

## 1. Resultado e invariantes

La entrada representa

```text
T0 = tridiagonal(d,e)
Q0 = vectors
T0 = Q0^T * W0 * Q0
```

donde `W0` es el workspace simétrico normalizado de la arquitectura superior.
La fase produce in place una secuencia de Givens cuyo producto es `Z`:

```text
D  = Z^T * T0 * Z
Q  = Q0 * Z
D  = Q^T * W0 * Q
```

Al retornar normalmente, toda entrada de `e` es exactamente `+0`, `d` contiene
los eigenvalues todavía normalizados y **sin ordenar**, y `vectors=Q`. Esta
fase no reescala, no ordena, no canonicaliza columnas y no ensambla
`SymmetricEigen`.

Entre sweeps completos, `d/e` representan una tridiagonal simétrica estricta.
Dentro de un sweep existe como máximo un único `bulge` scalar fuera de banda.
No existe owner ni view persistente de una Matrix tridiagonal.

## 2. Frontera privada y ownership

El kernel normativo es equivalente a:

```aether
int convergeSymmetricTridiagonalState<T: IEEEFloat>(
    ref mut Vector<T,Column> d,
    ref mut Vector<T,Column> e,
    ref mut Matrix<T> vectors,
    usize maxSweeps);
```

Para composición y qualification se fijan además wrappers module-private
equivalentes a:

```aether
SymmetricTridiagonalSeed<T>
symmetricTridiagonalQRWithMaxSweeps<T: IEEEFloat>(
    SymmetricTridiagonalSeed<T> seed,
    usize maxSweeps);

SymmetricTridiagonalSeed<T>
symmetricTridiagonalQR<T: IEEEFloat>(
    SymmetricTridiagonalSeed<T> seed);
```

El primer wrapper consume el seed, llama al kernel con sus tres fields y
devuelve el mismo aggregate. El segundo calcula con aritmética checked:

```text
maxSweeps = checkedMultiply(64,n)
```

y delega al primero. El assembly futuro puede mover directamente sus owners
al wrapper productivo. No se crea un aggregate público ni otro aggregate
privado para el resultado: `SymmetricTridiagonalSeed<T>` ya es la frontera de
ownership exacta.

Una excepción puede dejar mutado el estado local consumido, pero ese estado no
se retorna ni cruza una frontera pública; unwind destruye sus owners. No se
intenta rollback transaccional. El fixture white-box puede llamar al kernel por
referencia sólo para inspeccionar fases privadas.

## 3. Precondiciones y shapes

Sea `n=dimension(d)`. Las precondiciones estructurales exactas son:

```text
dimension(e)       == (n>0 ? n-1 : 0)
rows(vectors)      == n
columns(vectors)   == n
```

El entry comprueba esas tres relaciones con los guards estructurales
ordinarios, formando `n-1` únicamente bajo `n>0`. Un fallo es corrupción de
composición interna y conserva el trap general de shape; no se traduce a
`NumericalConvergenceException`.

Los elementos de `d/e/vectors` llegan finitos desde la fase anterior.
`vectors` ya contiene `Qh`. El kernel no vuelve a certificar que `vectors` sea
ortogonal, que `d/e` provengan de una tridiagonalización ni que exista la
Matrix pública original. La validación defensiva posterior a cada sweep sí
detecta no finitos producidos internamente.

Los casos `n==0` y `n==1` retornan después de los shape guards, sin pedir
epsilon, deflacionar, seleccionar bloques, consumir budget ni tocar
`vectors`. Para `n>=2` se obtiene `eps=epsilon<T>()` una sola vez.

## 4. Deflation exacta

Cada scan recorre `i=1..n-1` en orden creciente y evalúa este árbol sin
reassociation deliberada:

```text
a = abs(d[i])
b = abs(d[i+1])
scale = a
if scale < b: scale = b

threshold = +0
if scale != +0:
    normalizedSum = (a / scale) + (b / scale)
    threshold = (eps * scale) * normalizedSum

if abs(e[i]) <= threshold:
    e[i] = +0
```

`normalizedSum` se forma después de ambas divisiones y la multiplicación es
primero `eps*scale`. No se evalúan `a+b`, `scale*normalizedSum`, una tolerance
decimal, una tolerance global ni una norma del bloque. La igualdad exacta
deflaciona. Si ambos diagonales son signed zero, `scale==+0`, el threshold es
el literal `+0` y `e[i]` sólo deflaciona si también compara como cero.

Toda entrada deflacionada se escribe como el literal `+0`, incluido un `-0`
de entrada. El scan no altera entries que superan el threshold. Underflow de
`eps*scale` a `+0` pertenece a la aritmética IEEE concreta y no se compensa
con una tolerance mínima.

## 5. Splitting y bloque activo trailing

Después de cada scan completo se selecciona determinísticamente el bloque no
singleton con mayor extremo `hi`:

```text
hi = n
while hi > 1 and e[hi-1] == +0:
    hi = hi-1

if hi == 1:
    convergió

lo = hi
while lo > 1 and e[lo-1] != +0:
    lo = lo-1
```

`n==0` ya retornó en §3. Un bloque activo satisface `lo<hi`; contiene
`d[lo..hi]` y `e[lo..hi-1]`; y está separado por `lo==1 || e[lo-1]==+0` y
`hi==n || e[hi]==+0`.

No se conserva una lista de bloques. Tras cada sweep se vuelve a buscar desde
`n`. Si hay múltiples bloques, se trabaja primero sobre el de mayor `hi`; al
convertirse en singletons, el mismo scan alcanza el siguiente bloque hacia
arriba. Bloques `1x1` nunca consumen un sweep. Si `e` llega íntegramente en
cero, el primer scan la canonicaliza y la fase retorna.

Valores repetidos no necesitan una branch: una tridiagonal irreducible con
off-diagonales no cero tiene spectrum simple; una multiplicidad exacta aparece
en los bloques ya separados o tras deflation. Valores clustered continúan
iterando hasta satisfacer el criterio local; no se fusionan por proximidad.

## 6. Shift de Wilkinson trailing escalado

Para `lo<hi` se leen exclusivamente las tres entradas del trailing `2x2`:

```text
a = d[hi-1]
b = e[hi-1]
c = d[hi]

sigma = abs(a)
if sigma < abs(b): sigma = abs(b)
if sigma < abs(c): sigma = abs(c)

an = a / sigma
bn = b / sigma
cn = c / sigma

two = one + one
delta = (an - cn) / two
h = stableHypot(delta,bn)
denominator = abs(delta) + h
magnitudeB = abs(bn)
correction = magnitudeB * (magnitudeB / denominator)

if delta < +0:
    muNormalized = cn + correction
else:
    muNormalized = cn - correction
```

El bloque activo garantiza `b!=0`; por tanto `sigma>0`. Además, el scan de
deflation inmediatamente anterior garantiza que `bn` no se aplana a cero: si
la máxima diagonal `D=max(abs(a),abs(c))` es normal respecto de `eps`, un `b`
activo satisface `abs(b)>eps*D`; si `eps*D` underflowea a cero, cualquier
`b` representable no cero dividido por ese `D` sigue teniendo magnitud de
orden `eps` o mayor; y si `D==0` o `abs(b)>D`, `abs(bn)==1`. Así `bn!=0`,
`h>0` y `denominator>0` en toda ejecución legítima.

El source comprueba defensivamente `sigma!=0` antes de dividir y
`denominator!=0` antes de formar la corrección. Una violación lanza
`NumericalConvergenceException`; no selecciona shift cero ni inventa otro
shift. Esas ramas califican una imposibilidad interna, no amplían el dominio.

`delta==+0` o `delta==-0` toma la rama `else`; así selecciona
determinísticamente el eigenvalue menor del trailing `2x2`. No se usa el signo
de cero para desempatar. `muNormalized` puede conservar el signed zero que
resulte de IEEE, pero es un temporal no observable y nunca funciona como
separador.

Todas las entradas `a/b/c` se validan al cargarse. Las normalizadas tienen
magnitud a lo sumo uno. La corrección
divide antes de completar el producto y no forma `bn*bn`. Se validan en orden
`sigma`, `an/bn/cn`, `delta`, `h`, `denominator`, `correction` y
`muNormalized`. No se materializa jamás el shift dimensional
`mu=sigma*muNormalized`.

## 7. Givens único y primer par implícito

La convención global es:

```text
G(c,s) = [ c -s ]
         [ s  c ]
```

Un constructor escalar recibe `(f,g)` y evalúa:

```text
r = stableHypot(f,g)
if f == +0 and g == +0:
    c = one
    s = +0
else:
    c = f / r
    s = g / r
```

La comparación incluye signed zeros. `r`, `c` y `s` se validan antes de uso.
No se cambia el signo de `r`, `c` o `s` ad hoc. En aritmética exacta:

```text
G^T * [f,g]^T = [r,0]^T
[f,g] * G     = [r,0]
```

Para el primer Givens del sweep se usa exactamente:

```text
t = abs(d[lo])
if t < abs(e[lo]): t = abs(e[lo])
if t < sigma:      t = sigma

dRatio = d[lo] / t
shiftRatio = sigma / t
f = dRatio - shiftRatio * muNormalized
g = e[lo] / t
```

Esto fija el árbol de la resta: se multiplica
`shiftRatio*muNormalized` y luego se resta de `dRatio`. En un bloque activo
`t>0`. El par es proporcional por `1/t` a `(d[lo]-mu,e[lo])`, pero ni `mu` ni
la resta dimensional extrema se forman. Se validan `t`, los tres cocientes,
el producto del shift, `f/g` y el Givens.

## 8. Similaridad local normalizada

En el step sobre índices `p,p+1`, antes de la rotación el bloque relevante es:

```text
      p  p+1 p+2
p   [ a   b   0 ]
p+1 [ b   c   z ]
p+2 [ 0   z   . ]
```

Aquí `a=d[p]`, `b=e[p]`, `c=d[p+1]` y, sólo si `p<hi-1`,
`z=e[p+1]`. Para `p==hi-1` no se lee `e[hi]` y `z` conceptualmente es `+0`.
La similaridad es siempre `T <- G^T*T*G`.

El update `2x2` usa:

```text
localScale = abs(a)
if localScale < abs(b): localScale = abs(b)
if localScale < abs(c): localScale = abs(c)
```

Si `localScale==+0`, los tres inputs son zeros IEEE y se fijan
`nextA=nextB=nextC=+0`, sin dividir. Este caso puede alcanzarse por redondeo
durante la propagación aunque el bloque al comienzo del sweep fuera activo.

En otro caso, el árbol normativo exacto es:

```text
an = a / localScale
bn = b / localScale
cn = c / localScale

cc = cr * cr
ss = sr * sr
cs = cr * sr

firstA = (cc * an) + (cs * bn)
normalizedA = (firstA + (cs * bn)) + (ss * cn)

firstC = (ss * an) - (cs * bn)
normalizedC = (firstC - (cs * bn)) + (cc * cn)

weightDifference = cc - ss
diagonalDifference = cn - an
normalizedB = (weightDifference * bn) +
              (cs * diagonalDifference)

nextA = localScale * normalizedA
nextB = localScale * normalizedB
nextC = localScale * normalizedC
```

Cada assignment visible en ese árbol produce un temporal y se valida antes de
reutilizarlo. Sólo las coordenadas normalizadas forman `cn-an`; no se forma
`c-a`. Los dos términos `cs*bn` se suman explícitamente; no se forma `2*b` ni
otro doble dimensional. No hay cuadrados de `a/b/c`.

Algebraicamente el árbol implementa:

```text
a' = cr^2*a + 2*cr*sr*b + sr^2*c
c' = sr^2*a - 2*cr*sr*b + cr^2*c
b' = (cr^2-sr^2)*b + cr*sr*(c-a)
```

La conexión con la siguiente fila se calcula desde el `z` viejo:

```text
nextBulge = sr * z
nextZ     = cr * z
```

Estos productos no requieren scaling adicional: cada uno multiplica una sola
entrada finita por un coeficiente de una rotación validada. Un resultado no
finito es breakdown, no motivo para cambiar el árbol.

## 9. Propagación exacta del bulge

El primer step usa directamente el Givens de §7. Para todo step posterior,
el estado antes de rotar contiene en la fila/columna anterior:

```text
[ e[p-1]  bulge ]
```

Se construye:

```text
rotation = givens(e[p-1],bulge)
cr = rotation.c
sr = rotation.s
e[p-1] = rotation.r
```

Con la convención fijada,
`[e[p-1],bulge]*G=[r,0]`; por simetría también desaparece la posición
transpuesta. El valor escrito en `e[p-1]` es exactamente el `r` no negativo
devuelto por `stableHypot`, o `+0` para el par de zeros. No se conserva el
signo previo de esa off-diagonal.

El sweep completo es:

```text
(cr,sr) = firstGivens
bulge = +0
p = lo

while p < hi:
    if p > lo:
        rotation = givens(e[p-1],bulge)
        cr = rotation.c
        sr = rotation.s
        e[p-1] = rotation.r

    oldA = d[p]
    oldB = e[p]
    oldC = d[p+1]
    validar oldA/oldB/oldC

    if p < hi-1:
        oldZ = e[p+1]
        validar oldZ

    calcular nextA/nextB/nextC por §8

    if p < hi-1:
        nextBulge = sr * oldZ
        nextZ = cr * oldZ

    validar todos los temporales del step
    d[p] = nextA
    e[p] = nextB
    d[p+1] = nextC
    if p < hi-1:
        e[p+1] = nextZ

    vectors <- vectors * G sobre columnas p,p+1

    if p < hi-1:
        bulge = nextBulge
    p = p+1
```

`bulge` es un único local scalar; nunca ocupa `d/e` ni una celda de Matrix.
`e[p]` se actualiza como `nextB` en el step `p` y, en el step `p+1`, se
reemplaza por el `r` que resulta de combinarla con el bulge. `e[p+1]` sólo se
actualiza a `nextZ` después de haber guardado su valor viejo.

En `p==hi-1`, el Givens posterior ya eliminó el bulge entrante, el bloque
trailing `2x2` se actualiza y no se lee ni escribe una conexión `z`. Por ello
no nace otro bulge y el sweep termina con storage estrictamente tridiagonal.
No se permite terminar temprano a mitad del bloque, incluso si alguna
rotación resulta identidad.

## 10. Acumulación de eigenvectors

Cada rotación del centro se acumula inmediatamente mediante
postmultiplicación:

```text
vectors <- vectors * G
```

Para `q=p+1`, cada fila `r=1..n` creciente evalúa:

```text
oldP = vectors[r,p]
oldQ = vectors[r,q]
nextP = (cr * oldP) + (sr * oldQ)
nextQ = (-sr * oldP) + (cr * oldQ)
validar nextP y nextQ
vectors[r,p] = nextP
vectors[r,q] = nextQ
```

Ambos valores viejos se leen y ambos nuevos se calculan y validan antes del
primer store de la fila. No se crea una columna, Vector, Matrix `G` ni lista de
rotaciones.

Si antes del step `T=Q^T*W0*Q`, entonces:

```text
T' = G^T*T*G
Q' = Q*G
Q'^T*W0*Q' = G^T*(Q^T*W0*Q)*G = T'.
```

Ésta es la razón exacta de los signos y de postmultiplicar columnas. Usar
`vectors<-vectors*G^T`, premultiplicar filas o invertir `s` rompería la
correspondencia value/column y queda prohibido.

## 11. Qué constituye un sweep

Una unidad de budget comprende indivisiblemente:

1. cálculo completo del shift trailing escalado;
2. construcción del primer Givens implícito;
3. todos los steps `p=lo..hi-1` del chase;
4. acumulación en `vectors` de cada Givens.

El sweep sólo termina cuando el bulge sale del extremo `hi`. Deflation,
selección/splitting, validación defensiva, canonicalización final y el sort
futuro no consumen budget.

## 12. Loop exterior y budget global

El kernel ejecuta exactamente:

```text
usedSweeps = 0

loop:
    deflation creciente de toda e
    seleccionar bloque trailing
    if no hay bloque activo:
        canonicalizar toda e a +0
        success

    if usedSweeps == maxSweeps:
        throw NumericalConvergenceException

    ejecutar un sweep completo sobre lo..hi
    usedSweeps = usedSweeps + 1
    validar d/e/vectors completos
```

La cabecera siguiente vuelve a deflacionar. No hace falta un segundo scan al
pie: la validación defensiva sí ocurre allí y la única decisión de
convergencia permanece en la cabecera. Deflation y success preceden siempre
al cap. Por ello un estado inicialmente convergido tiene éxito con
`maxSweeps==0`, mientras que un estado activo falla; y el último sweep
permitido puede converger en la cabecera siguiente.

`usedSweeps` es global a toda la fase. Un split, un bloque terminado o el paso
al bloque superior no lo reinicia. El entry productivo usa exclusivamente
`checkedMultiply(64,n)`; un overflow estructural conserva el trap checked y
no se traduce a convergencia.

## 13. Finitud y precedencia de fallos

Se reutilizan `isFiniteInternal(x)=((x-x)==+0)` y
`requireFiniteInternal`. Todo no finito generado internamente lanza
`NumericalConvergenceException`.

Los checks obligatorios son:

- en deflation: `a/b/scale`, y, si corresponde, ambos ratios,
  `normalizedSum` y `threshold`;
- en shift: todos los valores enumerados en §6;
- en el primer par: `t`, cocientes, producto del shift y `f/g`;
- en cada Givens: `r/c/s`;
- en cada step: `localScale`, normalizados, `cc/ss/cs`, cada suma, resta y
  producto del árbol, resultados reescalados, `nextBulge/nextZ`;
- en cada fila de `vectors`: ambos resultados antes de stores;
- después del sweep: cada `d[i]`, cada `e[i]` y cada
  `vectors[i,j]`, con traversals lógicos crecientes.

Las entradas legítimas ya son finitas, por lo que no se agrega un scan inicial
que recertifique la fase anterior. Los checks durante deflation evitan que un
no finito producido y no detectado por una refactorización se convierta en una
decisión de split.

La precedencia observable es:

1. shape guards;
2. deflation y selección;
3. success si no queda bloque;
4. budget failure si queda bloque sin unidad;
5. shift/Givens/chase/acumulación con checks inmediatos;
6. incremento del contador y scan defensivo.

Un no finito durante un sweep ya autorizado gana sobre el agotamiento de la
siguiente cabecera. Un estado convergido gana sobre el cap. Nunca se publica
un aggregate parcial.

## 14. Casos normativos

| caso | conducta |
|---|---|
| `n=0` | éxito inmediato; `d/e` vacíos y `vectors` `0x0` intacta |
| `n=1` | éxito inmediato; `d[1]` y la única columna intactas |
| `n=2` activo | un único step por sweep, sin leer `e[2]` ni crear bulge saliente |
| `e==0` | primer scan canonicaliza signed zeros y retorna sin sweep |
| Matrix cero | representación diagonal; éxito inmediato y zeros `+0` en `e` |
| un `2x2` activo | Wilkinson trailing y similaridad local ordinaria |
| múltiples bloques | siempre el bloque no singleton de mayor `hi`; budget compartido |
| repeated | multiplicidad permitida; base del eigenspace no canónica |
| clustered | no se fusiona; deflation sólo por el threshold local |
| spectrum indefinido | signos de `d` ordinarios; no hay branch de definitud |
| valores normalizados extremos | shift y update local escalados; breakdown no finito explícito |

La fase no promete signo de columnas, orden de eigenvalues ni identidad de una
base particular en multiplicidades.

## 15. Reutilización y refactor mínimo

`stableHypot<T>` se reutiliza literalmente. También son reutilizables
literalmente `isFiniteInternal` y `requireFiniteInternal`.

El source actual contiene lógica general bajo nombres históricos SVD:

```text
BidiagonalGivens<T>
bidiagonalGivens(f,g)
rotateBidiagonalColumns(M,p,q,c,s)
BidiagonalActiveBlock
deflateBidiagonal(d,e,eps)
selectBidiagonalBlock(d,e)
```

El vertical V1 hará el refactor privado mínimo:

```text
GivensRotation<T>
givensRotation(f,g)
rotateColumnsByGivens(M,p,q,c,s)
TrailingActiveBlock
deflateAdjacentOffDiagonal(d,e,eps)
selectTrailingActiveBlock(d,e)
```

y actualizará las callsites y qualification SVD existentes. Los helpers de
deflation y selección ya reciben exactamente `d/e`, ejecutan el árbol y los
scans requeridos aquí y no dependen de orientación ni de fórmulas de SVD; se
reutilizan literalmente después del rename. Tipos, fields, firmas escalares,
árbol aritmético, checks, signos y traversals no cambian. La rotación de filas
se renombra simétricamente a `rotateRowsByGivens` para mantener el par
coherente, aunque este eigensolver sólo necesita columnas.

No se duplican constructor, rotación de columnas, deflation ni selección de
bloque. En cambio, no se reutilizan `BidiagonalShift` ni
`chaseBidiagonalBulge`: el centro bidiagonal alterna rotaciones izquierdas y
derechas y su shift pertenece a `B^T B`; el centro simétrico exige una sola
similaridad. Compartir esos kernels sería semánticamente incorrecto. El
refactor común no agrega abstracción asignadora ni cambia el comportamiento
calificado de SVD.

## 16. Allocations, storage y complejidad

La fase no realiza heap allocations. Reutiliza los owners existentes:

```text
d       : n
e       : n-1
vectors : n x n
```

Bloque, shift, Givens, escalas y bulge son scalars o aggregates fixed-size. No
hay Matrix `T`, Matrix `G`, Vector temporal, active-block list, historial de
rotaciones ni allocation por sweep/rotación.

Un sweep sobre un bloque de longitud a lo sumo `n` realiza a lo sumo `n-1`
rotaciones. Con `maxSweeps=64*n`:

```text
rotaciones <= 64*n*(n-1) = O(n^2)
```

Cada rotación toca `O(1)` scalars tridiagonales y `n` filas de `vectors`.
Por tanto el centro y scans quedan en `O(n^2)` y la acumulación queda acotada
por `O(n^3)` scalar updates. El estado compacto `d/e` usa `O(n)` y el scratch
adicional del kernel es `O(1)`; en particular satisface el límite de
`O(n)` storage adicional y agrega cero matrices.

Una política de `O(n^2)` sweeps permitiría `O(n^3)` rotaciones y `O(n^4)`
updates de eigenvectors. Queda prohibida, igual que reiniciar el budget por
bloque.

## 17. Qualification V1

`LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1` agregará qualification white-box
para float32/float64 en O0/O2. El fixture será una copia test-only del módulo
o el mecanismo privado ya usado por los verticales SVD; no publicará hooks.

### 17.1 Deflation, splitting y signed zero

Se construirán thresholds con aritmética del tipo productivo y se probarán:

- `e` claramente menor y mayor;
- igualdad exacta, que debe deflacionar;
- predecessor y successor representables del threshold;
- `scale==0`, escalas very small/large y underflow del threshold;
- `e=+0/-0`, verificando `+0` por el signo del recíproco;
- traversal creciente y múltiples separadores;
- selección del bloque de mayor `hi`, singletons trailing y `e` inicialmente
  íntegramente cero.

### 17.2 Shift, Givens y step local

El shift se comparará con una fórmula host de mayor precisión que reconstruye
los eigenvalues del trailing `2x2`, sin copiar los mismos intermedios. Cubrirá
`delta<0`, `delta>0`, `delta==+0/-0`, signos de `b`, escala uniforme extrema,
`b` subnormal y la imposibilidad de `sigma/denominator==0` en bloque activo.

Givens comprobará `c^2+s^2≈1`, la componente anulada, ambos zeros signed y
pares de escalas muy distintas. El step local se contrastará con multiplicar
en host `G^T*T*G`; verificará `a'/b'/c'`, `bulge`, `z'`, el caso
`localScale==0` y ausencia de acceso a `z` en el último step.

### 17.3 Sweep, convergencia y vectors

Habrá fixtures `2x2`, `3x3` y bloques interiores que comparen un sweep
completo con un dense host independiente. El `2x2` cerrado comparará también
los dos eigenvalues analíticos y la rotación con el resultado del único step,
antes de ejecutar la deflation siguiente. Cubrirán repeated/clustered spectra,
indefinite, cero, un bloque activo, múltiples bloques y escalas normalizadas
extremas.

El hook de cap probará:

- estado activo con `maxSweeps=0` falla;
- estado ya convergido con cap cero tiene éxito;
- para un fixture determinista que necesita `m` sweeps, `m-1` falla y `m`
  converge, partiendo cada vez de un seed fresco;
- un split no reinicia el contador;
- un no finito producido en shift, update o acumulación gana inmediatamente y
  no entrega seed.

Se comprobará que cada rotación preserva columnas no participantes, que lee
ambas columnas antes de store, y que `vectors` permanece ortogonal cuando
`Q0` lo era.

## 18. Oracle independiente

Para un fixture controlado, el host conserva `d0/e0/Q0` y reconstruye:

```text
T0 = tridiagonal(d0,e0)
D  = diag(dFinal)
Q  = vectorsFinal
```

Si `Q0=I`, comprueba directamente:

```text
Q^T * T0 * Q ~= D
Q^T * Q ~= I
```

Si `Q0!=I`, la rotación tridiagonal neta es `Z=Q0^T*Q`; entonces comprueba
cualquiera de las dos identidades equivalentes:

```text
Z^T * T0 * Z ~= D

A0 = Q0 * T0 * Q0^T
Q^T * A0 * Q ~= D
```

Esto evita aplicar por error el `Qh` inicial dos veces. También se comprueba
la reconstrucción `A0 ~= Q*D*Q^T` y ortogonalidad con acumulación host
escalada.

`numpy.linalg.eigh/eigvalsh` se usa sólo en el host. Como este vertical no
ordena productivamente, se comparan multisets mediante copias host ordenadas.
No se comparan columnas individualmente para multiplicidades o clusters; se
usan residual, reconstrucción y, cuando corresponda, projectors de subespacio.

Los márgenes numéricos serán relativos a tipo, dimensión y escala, expresados
como constantes documentadas por `n*epsilon(T)`. No son tolerancias
productivas. Zero y casos exactos tendrán assertions específicas.

## 19. Gates source, recursos e IR

La qualification demostrará:

- `SymmetricTridiagonalSeed`, entries y helpers QR inaccesibles por import;
- ninguna función QR/eigen nueva pública;
- cero allocations/frees adicionales durante la fase, en al menos dos
  tamaños y tanto O0 como O2;
- ausencia de Matrix `T`, Matrix `G`, transpose owner, Vector temporal,
  lista de bloques e historial de rotaciones;
- ausencia de call al QR dense público y de reuse del chase/shift QR
  bidiagonal;
- ausencia de LAPACK/BLAS, FFI, opcode, intrinsic o runtime especial;
- calls o lowering equivalente del único `stableHypot` y del único constructor
  general de Givens;
- monomorfización float32/float64;
- ausencia posterior de `GenericParam`, witness, vtable, boxing, `TypeId` y
  call numérica indirecta;
- ningún constructor allocador dentro del loop exterior, sweep, chase o
  rotación;
- `git diff --check`.

El source scan distinguirá el refactor general de helpers de una duplicación:
debe quedar una sola autoridad productiva para construir Givens, una para
postrotar columnas, una para la deflation adyacente y una para seleccionar el
bloque trailing.

## 20. Milestone y fuera de scope

El siguiente milestone implementable es:

```text
LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-QR-V1
```

Debe implementar exactamente este kernel, wrappers, refactor privado y
qualification. Cualquier cambio de dirección, convención de signos, shift,
árbol local, deflation o budget reabre esta arquitectura.

Quedan fuera: API `symmetricEigen`, validación pública, escala inicial,
tridiagonalización Householder, rescale final, sort y permutación de columnas,
canonicalización de signos/bases, eigenvalues-only, QL o dirección adaptativa,
dense QR, LAPACK/BLAS, Complex y cambios de compiler/runtime.
