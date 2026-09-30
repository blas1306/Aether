# LINEAR-ALGEBRA-STABLE-NORM-ARCH-1 — norma e hipotenusa escaladas privadas

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-30.

Autoridad relacionada:

- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md) y su
  [reporte](LINEAR_ALGEBRA_SVD_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-ARCH-1](IEEE_FLOAT_CONSTANTS_ARCH_1.md), su
  [reporte de arquitectura](IEEE_FLOAT_CONSTANTS_ARCH_1_REPORT.md) y su
  [reporte V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md).

## 1. Decisión y alcance

`linearAlgebra` tendrá una sola autoridad source privada para acumular una
norma euclídea mediante `scale + scaledSquares`, una finalización privada de
esa acumulación y una hipotenusa escalada privada. Son infraestructura de los
kernels, no API matemática pública.

Este milestone sólo fija la arquitectura. No modifica QR, no implementa SVD,
no agrega primitives, intrinsics, libm `hypot`, dispatch por `TypeId`, SIMD ni
fast-math, y no cambia capabilities globales. Los nombres mostrados son
normativos para explicar el diseño, pero el vertical V1 puede escoger nombres
privados equivalentes.

Quedan fuera una API pública `norm`, `hypot` o `frobeniusNorm`, compensated dot
products, BLAS/LAPACK, precisión arbitraria y cualquier forma de SVD,
bidiagonalización o rotación Givens.

## 2. Auditoría del QR vigente

`qrInPlace` recorre cada cola de columna `R[k:m,k]` en orden creciente y ejecuta
exactamente:

```aether
T normScale = zero;
T scaledSquares = one;
usize i = k;
while (i <= m) {
    T magnitude = abs(R[i,k]);
    if (magnitude != zero) {
        if (normScale < magnitude) {
            T ratio = normScale / magnitude;
            scaledSquares = one + scaledSquares * ratio * ratio;
            normScale = magnitude;
        }
        else {
            T ratio = magnitude / normScale;
            scaledSquares = scaledSquares + ratio * ratio;
        }
    }
    i = i + 1;
}

if (normScale != zero) {
    T norm = normScale * sqrt(scaledSquares);
    // formación del reflector vigente
}
```

Son contractuales el orden ascendente, el `abs` previo a las ramas, ambas
comparaciones, el orden textual de división/multiplicaciones/suma y que no se
evalúa `sqrt` para escala cero. En particular, QR ramifica sobre `normScale`, no
sobre la norma final. Una extracción que retornara sólo `norm` y reemplazara la
rama por `if (norm != zero)` no preservaría literalmente esa decisión y queda
rechazada.

La extracción no cambia selección de `alpha`, storage del reflector,
actualizaciones de `Q`/`R`, shapes, ownership, allocations ni tolerancias.

## 3. Representación interna

La autoridad de acumulación devuelve un aggregate source privado equivalente a:

```aether
struct StableScaledSquares<T: Storable> {
    T scale;
    T scaledSquares;
}
```

No es parte de la API importable. Retener ambos campos permite que QR conserve
la rama exacta `state.scale != zero` y que sólo entonces finalice la norma. Los
consumers que sólo requieren el escalar usan un wrapper privado de norma; no
reimplementan la fórmula final.

Las tres operaciones conceptuales son:

```aether
StableScaledSquares<T> stableScaledSquaresRange<T: IEEEFloat>(
    VectorView<T,Column> values,
    usize first,
    usize last);

T finishStableNormNonzero<T: IEEEFloat>(StableScaledSquares<T> state);

T stableNormRange<T: IEEEFloat>(
    VectorView<T,Column> values,
    usize first,
    usize last);

T stableHypot<T: IEEEFloat>(T a, T b);
```

`finishStableNormNonzero` tiene la precondición privada `state.scale != +0` y
ejecuta sólo `state.scale * sqrt(state.scaledSquares)`. `stableNormRange`
acumula y retorna `+0` si `state.scale == zero`; en otro caso delega en esa
finalización. Así hay una sola recurrencia y una sola fórmula final.

## 4. Rango y forma de acceso

Se elige una `VectorView<T,Column>` más extremos inclusivos one-based. Un rango
no vacío satisface `1 <= first <= last <= dimension(values)`. El rango vacío
canónico es `first = 1, last = 0`; no se indexa la view. Son precondiciones de
los callers privados, no una nueva familia pública de errores.

QR construirá en O(1) `column(R,k)` y pasará `first=k`, `last=m`. Esto conserva
el orden `k..m` y no crea un slice owning. Una fila futura se adapta con
`transpose_view(row(A,r))`; un Vector owner se adapta con `vector_view`. Las
views sólo copian descriptor y stride, no elementos ni backing.

Se rechazan:

- owner `Vector` como parámetro, porque no cubre Matrix sin materialización;
- helpers separados de fila y columna, porque duplicarían la recurrencia;
- índices más accessor/callback, porque introducirían callable indirecto o
  closure y ocultarían el costo;
- slices owning o matrices/vectores temporales;
- un hidden reduction o kernel especial de backend.

La construcción de la axis view valida una vez el eje y su indexación conserva
los bounds checks ordinarios de `VectorView`. Es O(1), sin allocation. Esta es
la única diferencia estructural respecto de escribir `R[i,k]` directamente;
no agrega operación floating-point, no reordena el recorrido y no modifica un
resultado numérico. Qualification debe inspeccionarla, no asumir que una view
es gratuita por definición.

## 5. Recurrencia exacta de norma

La acumulación normativa es, sin reassociation:

```aether
T zero = 0;
T one = 1;
T scale = zero;
T scaledSquares = one;
usize i = first;
while (i <= last) {
    T magnitude = abs(values[i]);
    if (magnitude != zero) {
        if (scale < magnitude) {
            T ratio = scale / magnitude;
            scaledSquares = one + scaledSquares * ratio * ratio;
            scale = magnitude;
        }
        else {
            T ratio = magnitude / scale;
            scaledSquares = scaledSquares + ratio * ratio;
        }
    }
    i = i + 1;
}
```

Cada expresión asociativa se evalúa conforme a su árbol source. En particular,
`scaledSquares * ratio * ratio` es `(scaledSquares * ratio) * ratio`, y
`ratio * ratio` se forma antes de la suma de la segunda rama. No se admite FMA
contractual, reassociation, vector reduction, acumulador promovido a otra
precisión ni fast-math.

La finalización escalar exacta es:

```aether
if (state.scale == zero) { return zero; }
return state.scale * sqrt(state.scaledSquares);
```

El guard evita división por cero durante la recurrencia y evita `sqrt` en el
caso cero, igual que QR. No se consulta `epsilon<T>()`.

## 6. Ceros y signed zero

El literal algebraico `zero` materializa `+0` del tipo concreto. `abs(+0)` y
`abs(-0)` son `+0`, `magnitude != zero` es falso y el estado inicial no cambia.
Por ello:

- rango vacío retorna `+0`;
- todos `+0`, todos `-0` o cualquier mezcla retorna `+0`;
- no se divide por cero;
- QR omite exactamente el reflector de una columna cero.

No se usa tolerancia: un valor subnormal distinto de cero sigue la recurrencia.

## 7. NaN e infinito de la norma

El helper no lanza exceptions ni agrega validación de finitud. Ejecuta las
operaciones IEEE ordinarias en el orden anterior. Ésta es una decisión de
compatibilidad: QR V1 no pre-valida finitud, mientras que SVD sí la rechazará
antes de entrar en sus kernels.

Las consecuencias, deliberadamente documentadas y no convertidas en una API
matemática pública, son:

- un único infinito produce infinito;
- dos infinitos alcanzan `Inf / Inf`, por lo que contaminan
  `scaledSquares` con NaN y la norma final es NaN;
- un NaN junto con al menos una magnitud finita no nula deja escala no nula y
  normalmente produce NaN;
- un rango compuesto sólo por NaN y ceros deja `scale == +0`; la finalización
  retorna `+0`, reproduciendo la rama observada de QR;
- el orden de NaN/Inf no se normaliza ni se define mediante un total order;
  gobiernan exactamente comparisons unordered y la recurrencia source.

Por tanto, “estable” promete scaling para datos finitos, no saneamiento de
datos no finitos. Los futuros callers que requieran un error de dominio deben
validar antes, como exige SVD. No se añade `isFinite`, `isNaN`, infinito
sentinel ni excepción al helper.

## 8. Hipotenusa escalada exacta

La hipotenusa ignora signos mediante dos llamadas a `abs` y usa esta secuencia:

```aether
T zero = 0;
T one = 1;
T high = abs(a);
T low = abs(b);
if (high < low) {
    T temporary = high;
    high = low;
    low = temporary;
}
if (high == zero) { return zero; }
T ratio = low / high;
return high * sqrt(one + ratio * ratio);
```

No se sustituye por `sqrt(a*a + b*b)`, `max/min`, libm `hypot`, FMA ni una
llamada a la norma de dos elementos. Mantenerla separada evita descriptor,
loop y view para una operación O(1), pero comparte el mismo principio y orden
de scaling.

Para finitos, `(+0,+0)`, cualquier combinación de signed zeros y sus variantes
de signo retornan `+0`; los signos de no ceros no afectan el resultado. Un
infinito con un finito produce infinito. NaN en cualquier posición produce NaN.
`(Inf,Inf)` produce NaN por `Inf/Inf`, coherente con no introducir detección
especial. No se promete la precedence de infinito sobre NaN de algunas
implementaciones públicas de `hypot`.

## 9. Capabilities y dominio de tipos

Las firmas privadas usan `T: IEEEFloat`. Es la frontera honesta: V1 admite sólo
`float32` y `float64`, y la semántica anterior depende de IEEE NaN, infinito,
subnormales y signed zero. No se presenta el helper como algoritmo para un
`RealOps` abierto.

El cierre algebraico exacto observado por ambos helpers es:

```text
Zero, One, Add, Mul, Div, Equal, Order, Abs, Sqrt
```

`Sub` y `Negate` no son necesarios. `Copy`, `Relocatable` y `Storable` llegan
por `IEEEFloat` y por los valores/views implicados, no amplían la aritmética.
No se modifica `IEEEFloat`, sus guarantees ni el catálogo global.

## 10. Lowering, optimización y reproducibilidad

Todo será source ordinario dentro de `linearAlgebra/src/lib.ae`. Tras
monomorphization existirán instancias concretas float32/float64; MIR y SSA no
retendrán type parameters, capability nodes, witnesses, vtables, boxing ni
dispatch indirecto. `abs`/`sqrt` seguirán el lowering Core ya calificado.

El contrato numérico presupone las reglas vigentes sin fast-math. Una
optimización puede inlinear helpers y eliminar copias de descriptors o del
aggregate interno, pero no reassociar, fusionar o cambiar ramas floating-point.
O0 y O2 deben producir el mismo comportamiento contractual; no se promete que
todo resultado aproximado sea bitwise idéntico entre targets con contratos de
floating-point diferentes.

## 11. Coste y allocations

Para `n = max(0,last-first+1)`, la norma cuesta O(n) tiempo y O(1) storage. La
hipotenusa cuesta O(1) tiempo y O(1) storage. Ambas realizan cero heap
allocations y no crean owner, backing, Matrix, Vector ni slice owning.

El aggregate `StableScaledSquares` y los descriptors de views son valores
fixed-size. Qualification debe comprobar que no escapen ni provoquen boxing o
allocation incluso en O0.

## 12. Estabilidad y precisión prometida

Para datos finitos, la recurrencia evita el overflow/underflow prematuro
evitable de cuadrar directamente cada entrada. Si la norma matemática
redondeada excede el máximo finito, el resultado puede ser infinito; scaling no
promete representar un resultado irrepresentable. Un cociente muy pequeño o
su cuadrado puede underflow a cero, perdiendo una contribución insignificante
respecto de la escala.

No se promete correctly-rounded, faithful rounding ni una cota universal en
ULP. Qualification exigirá estabilidad razonable y tolerancias distintas para
float32/float64, comparando con oráculos de mayor precisión o valores
analíticos, nunca con la misma fórmula source.

Los casos extremos deben incluir valores cerca de `sqrt(maxFinite)` sin que la
norma real desborde, huge + tiny, todos muy pequeños, subnormales y magnitudes
mixtas. Cada caso debe demostrar que la fórmula ingenua fallaría o sería menos
informativa cuando ése sea el propósito del test.

## 13. Extracción y compatibilidad QR

El vertical reemplazará sólo el bloque de acumulación por la autoridad privada:

```aether
StableScaledSquares<T> state =
    stableScaledSquaresRange<T>(column(R,k), k, m);
if (state.scale != zero) {
    T norm = finishStableNormNonzero<T>(state);
    // body vigente, literal y sin cambios
}
```

Esto preserva traversal, valores leídos, operaciones floating-point, rama de
escala, ausencia de `sqrt` para cero y el body Householder. La llamada, axis
view y retorno del aggregate pueden cambiar estructura de IR no numérica, pero
no capabilities, allocations, ownership ni bits de los operands/resultados.

V1 debe comparar contra una copia de referencia congelada del loop anterior en
un fixture de qualification, no conservar dos implementaciones productivas.
Para inputs donde el contrato vigente fija igualdad exacta se comparan bits de
cada elemento de `Q` y `R`; para NaN se compara además la clasificación y ruta,
sin inventar estabilidad de payload donde no existe promesa previa.

## 14. Qualification del helper

Los helpers siguen module-private. La prueba directa debe vivir en un fixture
white-box compilado como la misma unidad fuente de qualification o usar el
mecanismo interno equivalente disponible al implementar el vertical. Queda
prohibido añadir un wrapper público, export condicional de producción o API
“temporal” sólo para tests. También se agrega una prueba negativa desde un
consumer que confirme que los nombres privados no resuelven.

La matriz mínima directa, en float32 y float64 y en O0/O2, comprende:

- norma: vacío, un elemento positivo/negativo, `3,4 -> 5`, signed zeros,
  magnitudes huge/tiny mezcladas, todos muy pequeños y subnormales;
- norma IEEE operacional: NaN solo, NaN con finito, un infinito y dos
  infinitos, preservando exactamente §7;
- hipotenusa: `(3,4) -> 5`, ambos órdenes, ceros y signed zeros, signos no
  cero, huge/tiny, subnormales, NaN, un infinito y dos infinitos;
- conteo cero de allocations, shapes/descriptors intactos y ausencia de
  owners temporales;
- HIR paramétrico con las capabilities exactas y HIR/MIR/SSA concretos sin
  residuo genérico ni dispatch.

No se usan decimales comunes que desborden ya el resultado matemático salvo en
un test explícito de overflow final.

## 15. Qualification de no regresión QR

Además de toda la suite QR vigente, V1 agregará:

- expectativas source/IR de una sola recurrencia productiva y llamada desde
  `qrInPlace`;
- float32 y float64, O0 y O2;
- columnas cero y signed zero;
- colas Householder de magnitud muy grande, muy pequeña, subnormal y mixta;
- square, tall, wide, rank-deficient y varios reflectores;
- comparación before/after del resultado completo, bitwise donde el contrato
  previo lo exige, y los mismos oráculos/tolerancias donde sólo promete
  aproximación;
- rutas operacionales vigentes de NaN/Inf para demostrar que no apareció
  validación, excepción o rama nueva;
- budgets de allocations/frees idénticos y backing de `R` reutilizado;
- ausencia de cambio en sign choice de `alpha`, loops posteriores y APIs
  `qr`, `qrInPlace` y `qrFloat32`.

No se relajará una prueba existente ni se actualizará un golden para aceptar
un resultado distinto causado por la extracción.

## 16. Visibilidad

Las declaraciones nuevas omiten `public` y son module-private según el contrato
del lenguaje. Ni el aggregate ni los tres helpers aparecen en la API publicada
de `linearAlgebra`. Esta decisión evita congelar una forma orientada a kernels;
un `hypot` público podría pertenecer a Core/Math y una futura familia pública de
normas necesita contratos de shape, errores y precisión propios.

Si el pipeline usado por V1 todavía aplica una regla provisional que expone
todo top-level function, la prueba negativa de §14 es un gate: se debe cerrar
la visibilidad ordinaria o ejecutar antes su vertical mínimo. No se resuelve el
gap marcando los helpers como públicos ni confiando sólo en un nombre con
underscore.

## 17. Dependencia de SVD y evolución

La bidiagonalización futura usará `stableNormRange` sobre columnas y sobre
filas adaptadas mediante views; no copiará la recurrencia Householder. El QR
bidiagonal implícito usará `stableHypot` para parámetros de Givens. La
qualification de reconstrucción podrá reutilizar la misma autoridad mediante
views, sin convertirla por ello en API pública.

`epsilon<T>()` permanece reservado a convergence/deflation. Ni norma ni
hipotenusa lo llaman. Esta separación evita mezclar exact-zero/scaling con
criterios algorítmicos tolerantes.

Una futura API `norm(Vector)`, `norm(Matrix)` o `frobeniusNorm(Matrix)` puede
adaptar sus recorridos a views o reutilizar el estado `scale + scaledSquares`.
Deberá decidir aparte orientación, orden Matrix, no finitos y precisión; este
milestone no congela esas APIs.

## 18. Milestones

La extracción numérica y su qualification caben en un único
`LINEAR-ALGEBRA-STABLE-NORM-V1`: no hace falta un submilestone QR porque la
rama sobre `scale` y la recurrencia pueden conservarse literalmente mediante
el estado privado.

La única precondición de infraestructura es que module-private sea realmente
inaccesible desde consumers (§16). Si el gate falla, se antepone un vertical
acotado de visibilidad top-level; no se mezcla esa corrección con cambios
numéricos. Superado ese gate, la secuencia de SVD continúa con
bidiagonalización, QR bidiagonal y assembly según
`LINEAR-ALGEBRA-SVD-ARCH-1`.
