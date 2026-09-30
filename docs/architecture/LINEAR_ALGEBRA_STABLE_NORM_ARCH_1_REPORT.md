# LINEAR-ALGEBRA-STABLE-NORM-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-30.

Documento normativo:
[LINEAR-ALGEBRA-STABLE-NORM-ARCH-1](LINEAR_ALGEBRA_STABLE_NORM_ARCH_1.md).

## Resultado

Se diseñaron, sin implementar, helpers source privados para norma euclídea e
hipotenusa escaladas de `linearAlgebra`. La norma conserva una única
recurrencia `scale + scaledSquares`; la hipotenusa ordena dos magnitudes y
divide `low/high`. Ninguna forma usa `sqrt(sum(x*x))`, epsilon, libm `hypot`,
intrinsic, runtime especial, SIMD o dispatch por tipo.

La interfaz de norma recibe una `VectorView<T,Column>` y extremos inclusivos.
Columnas Matrix entran mediante `column`, filas mediante `row` más
`transpose_view` y owners Vector mediante `vector_view`; todas son adaptaciones
O(1) sin materialización. El rango vacío canónico `1..0` retorna `+0`.

## Compatibilidad QR

La auditoría detectó que QR no ramifica sobre la norma final sino sobre
`normScale`. Por eso la autoridad de acumulación devuelve un aggregate privado
con `scale` y `scaledSquares`; QR conserva literalmente
`if (state.scale != zero)` y sólo dentro calcula
`state.scale * sqrt(state.scaledSquares)` mediante la finalización común.

Quedan fijos el traversal creciente, `abs`, comparisons, divisiones,
multiplicaciones, sumas, `sqrt` final y todos sus árboles source. No se permite
reassociation, FMA contractual, fast-math, reducción oculta ni acumulador
promovido. La axis view añade sólo descriptor/validación ordinaria, no
operaciones floating-point ni allocations.

La qualification V1 comparará el QR extraído contra un fixture congelado del
loop anterior en float32/float64 y O0/O2, incluidos cero, signed zero,
subnormales, escalas extremas y las rutas IEEE vigentes. Mantendrá budgets de
allocations, backing reuse, APIs, branches Householder y golden checks; no se
relajarán tolerancias para aceptar un cambio introducido por el refactor.

## Ceros y no finitos

Vacío, todos ceros y mezclas `+0/-0` retornan exactamente `+0`, sin división por
cero ni `sqrt`. No hay exceptions ni validación interna de finitud: SVD seguirá
rechazando no finitos antes del kernel, pero QR conserva su comportamiento.

La política no intenta imitar un `norm`/`hypot` público: un infinito aislado en
la norma produce infinito, dos infinitos producen NaN, y sólo NaN más ceros
deja escala cero y retorna `+0`, exactamente como la rama QR vigente. En
`stableHypot`, NaN produce NaN, infinito con finito produce infinito e
`(Inf,Inf)` produce NaN. Estas consecuencias proceden del orden IEEE fijado, no
de detección especial.

## Capabilities, lowering y coste

Ambas operaciones quedan bajo `T: IEEEFloat` y usan exactamente `Zero`, `One`,
`Add`, `Mul`, `Div`, `Equal`, `Order`, `Abs` y `Sqrt`; no requieren `Sub`,
`Negate` ni `epsilon`. Tras monomorphization sólo quedan float32/float64 y
operaciones Core concretas, sin residue genérico, witnesses o calls indirectas.

La norma cuesta O(n) tiempo/O(1) storage y la hipotenusa O(1)/O(1). Ambas
asignan cero veces y no crean Matrix, Vector o slice owner. Se promete evitar
overflow/underflow prematuro evitable por scaling, no correctly-rounded ni una
cota universal en ULP. V1 usará oráculos independientes y tolerancias separadas
por precisión.

## Visibilidad y secuencia

Los helpers y su aggregate omiten `public`; no forman parte de la API de
`linearAlgebra`. Las pruebas directas serán white-box dentro de una unidad de
qualification, acompañadas por un consumer negativo que no pueda resolverlos.
No se publicará un wrapper sólo para tests.

La extracción cabe en un único `LINEAR-ALGEBRA-STABLE-NORM-V1`. Si el pipeline
activo aún expone provisionalmente todas las funciones top-level, el cierre de
visibilidad module-private es un gate previo y acotado; no se aceptará exposición
pública como workaround. Después, bidiagonalización reutilizará la norma y el
QR bidiagonal/Givens reutilizará la hipotenusa, sin implementar esos consumers
en este milestone.

## Alcance de este cierre

Se crearon únicamente este reporte y el documento normativo. No se modificó
`linearAlgebra`, QR, SVD, compiler, runtime, tests, consumer, manifests ni
capabilities.
