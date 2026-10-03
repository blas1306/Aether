# LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1 — operaciones derivadas de SVD thin

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-03.

Este milestone es exclusivamente documental. No modifica
`linearAlgebra/src/lib.ae`, consumer, tests, compiler, runtime, standard
library ni capabilities. Las operaciones y qualifications descritas aquí se
dividen en verticales posteriores (§23).

Autoridad normativa:

- [AETHER-V1-LANGUAGE-CHARTER](AETHER_V1_LANGUAGE_CHARTER.md);
- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md);
- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1](LINEAR_ALGEBRA_SVD_QUALIFICATION_CLOSURE_1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md).

## 1. Decisión resumida

V1 agregará a `linearAlgebra` una familia source ordinaria sobre la SVD thin
ya pública. Habrá rutas preserving desde `Matrix<T>` y rutas reutilizables
desde `SVD<T>` para pseudoinversa numérica, mínimos cuadrados de norma mínima,
rango numérico, condición 2 y aproximación óptima de rango dado.

La política compartida retiene un singular value exactamente cuando supera el
cutoff; la igualdad pertenece al lado descartado. El overload sin cutoff usa
la convención relativa

```text
tau = max(m,n) * epsilon<T>() * sigmaMax
```

pero la clasificación se evalúa en forma normalizada, sin materializar `tau`:

```text
sigmaMax == 0       -> no se retiene ninguno
sigma > 0           y
sigma / sigmaMax > max(m,n) * epsilon<T>() -> retenido
```

Esto evita overflow o underflow prematuro en el producto con `sigmaMax`. Un
cutoff explícito es absoluto, finito y no negativo. `sigma <= cutoff` se
descarta. Cutoff negativo, NaN o infinito lanza la única excepción nueva:

```aether
public class InvalidSingularValueCutoffException : Exception {
    public init() {}
}
```

La pseudoinversa y least-squares V1 son deliberadamente **numéricos y
truncados**; no se publican aliases llamados `Exact`. `numericalRank` declara
la misma política en su nombre. En cambio, `condition2`, un `k` explícito de
Eckart–Young y sus errores no consultan cutoff alguno. Se agrega una consulta
estrecha, sólo sobre factores, para contar ceros representacionales exactos:
`nonzeroSingularValueCount`.

No se forma `Sigma`, pseudoinversa como paso de least-squares, transpose
owning, normal equations ni una segunda SVD. Los factores se prestan shared y
todos los resultados agregados son owners nuevos.

## 2. Superficie pública cerrada

Las firmas normativas son:

```aether
// Moore–Penrose numérica/truncada.
Matrix<T> pseudoInverse<T: IEEEFloat>(ref Matrix<T> A);
Matrix<T> pseudoInverse<T: IEEEFloat>(ref Matrix<T> A, T cutoff);
Matrix<T> pseudoInverse<T: IEEEFloat>(ref SVD<T> factor);
Matrix<T> pseudoInverse<T: IEEEFloat>(ref SVD<T> factor, T cutoff);

// argmin ||A x-b||2, eligiendo entre los minimizadores la norma mínima.
Vector<T,Column> leastSquares<T: IEEEFloat>(
    ref Matrix<T> A, ref Vector<T,Column> b);
Vector<T,Column> leastSquares<T: IEEEFloat>(
    ref Matrix<T> A, ref Vector<T,Column> b, T cutoff);
Vector<T,Column> leastSquares<T: IEEEFloat>(
    ref SVD<T> factor, ref Vector<T,Column> b);
Vector<T,Column> leastSquares<T: IEEEFloat>(
    ref SVD<T> factor, ref Vector<T,Column> b, T cutoff);

Matrix<T> leastSquares<T: IEEEFloat>(
    ref Matrix<T> A, ref Matrix<T> B);
Matrix<T> leastSquares<T: IEEEFloat>(
    ref Matrix<T> A, ref Matrix<T> B, T cutoff);
Matrix<T> leastSquares<T: IEEEFloat>(
    ref SVD<T> factor, ref Matrix<T> B);
Matrix<T> leastSquares<T: IEEEFloat>(
    ref SVD<T> factor, ref Matrix<T> B, T cutoff);

// Rango efectivo bajo la política común.
usize numericalRank<T: IEEEFloat>(ref Matrix<T> A);
usize numericalRank<T: IEEEFloat>(ref Matrix<T> A, T cutoff);
usize numericalRank<T: IEEEFloat>(ref SVD<T> factor);
usize numericalRank<T: IEEEFloat>(ref SVD<T> factor, T cutoff);

// Cuenta exacta sobre los bits almacenados; no afirma rango matemático de A.
usize nonzeroSingularValueCount<T: IEEEFloat>(ref SVD<T> factor);

// Condición espectral sin truncamiento numérico.
T condition2<T: IEEEFloat>(ref Matrix<T> A);
T condition2<T: IEEEFloat>(ref SVD<T> factor);

// Eckart–Young para presupuesto de rango dado.
Matrix<T> lowRankApproximation<T: IEEEFloat>(
    ref Matrix<T> A, usize rank);
Matrix<T> lowRankApproximation<T: IEEEFloat>(
    ref SVD<T> factor, usize rank);
T lowRankSpectralError<T: IEEEFloat>(ref Matrix<T> A, usize rank);
T lowRankSpectralError<T: IEEEFloat>(ref SVD<T> factor, usize rank);
T lowRankFrobeniusError<T: IEEEFloat>(ref Matrix<T> A, usize rank);
T lowRankFrobeniusError<T: IEEEFloat>(ref SVD<T> factor, usize rank);
```

`Matrix` y `SVD` nominales distinguen overloads; Vector column y Matrix
distinguen los RHS. No hay wrappers float32/float64, default de precisión,
flags, enum de algoritmo, methods, `Option`, `Result`, `Any` ni dispatch por
tipo de retorno.

Se elige `leastSquares`, no `solve`. Los overloads `solve` LU/Cholesky/QR
mantienen intactos sus dominios, exact-zero checks y excepciones. El nombre
nuevo hace visible que esta familia acepta square, tall, wide y rank-deficient
y que aplica truncamiento numérico.

## 3. Por qué overloads y no un objeto de política

V1 tiene una sola decisión configurable: cutoff absoluto. Un
`SVDTruncationOptions<T>`, una jerarquía de strategies o un enum default versus
absolute sólo envolvería un escalar, agregaría construcción y no tendría otro
consumer. Los overloads de aridad distinta conservan calls simples y hacen
visible cuándo el caller fija una escala absoluta.

El overload default no equivale a pasar un valor mágico. Usa dimensiones,
`epsilon<T>()` y `sigmaMax`; el overload explícito usa literalmente el cutoff
entregado. Una configuración nominal se reabrirá sólo cuando exista otra
opción pública real que deba combinarse con cutoff.

Tampoco se agrega un argumento `rcond`: suele significar un factor relativo,
pero compite en interpretación con cutoff absoluto y con el default
dimensionado. Quien necesite control relativo puede factorizar una vez,
consultar `factor.S[1]`, calcular su cutoff absoluto y reutilizar el factor.

## 4. Autoridad común de clasificación

Todos los consumers truncados deben delegar a un helper privado único. No
pueden copiar fórmulas locales. Para un factor legítimo se fijan:

```text
m = rows(factor.U)
n = columns(factor.Vt)
p = dimension(factor.S) = min(m,n)
sigmaMax = p == 0 ? 0 : factor.S[1]
```

La SVD pública garantiza `S[1] >= ... >= S[p] >= +0` y finitud. Bajo cutoff
explícito:

```text
retainExplicit(sigma, cutoff) := sigma > cutoff
```

Bajo default, si `p==0` o `sigmaMax==0`, el retained count es cero. En otro
caso:

```text
relativeCutoff = dimensionAsT(max(m,n)) * epsilon<T>()
retainDefault(sigma) := sigma > 0
                     && sigma / sigmaMax > relativeCutoff
```

Esta comparación normalizada es la definición operacional normativa; la
fórmula de `tau` es su interpretación matemática, no una exigencia de formar
el producto. Como `0 <= sigma <= sigmaMax`, el cociente no overflowea. Puede
underflowear a cero para una razón extrema, que queda correctamente del lado
descartado. `relativeCutoff` no underflowea cuando `p>0`: la dimensión es al
menos uno y epsilon es representable. Con extents `usize`, convertir la
dimensión tampoco puede overflowear float32/float64.

V1 no tiene cast genérico `usize -> T`. El helper privado `dimensionAsT` se
implementará con descomposición binaria del `usize`, `One` y `Add`, en
`O(log(max(m,n)))`, no mediante un loop lineal que dejaría de incrementar al
superar la precisión exacta de T. Esto es source ordinario y no agrega
capability, primitive ni compiler magic. Su rounding IEEE concreto forma parte
de la qualification.

La comparación es estricta del lado retenido en ambas rutas. Por tanto:

- cero exacto siempre se descarta;
- un valor exactamente igual al threshold se descarta;
- `cutoff==0` retiene exactamente los valores almacenados distintos de cero;
- un valor inmediatamente superior se retiene;
- un valor inmediatamente inferior se descarta.

Esta política clasifica el espectro **calculado**. No convierte
`epsilon<T>()` en tolerancia universal: epsilon sólo participa en este default
documentado; no altera condition number, Eckart–Young, solve LU/QR, la SVD ni
otros algoritmos.

## 5. Validación de cutoff y precedencia

Un cutoff explícito es válido exactamente si:

```text
(cutoff - cutoff) == 0 && cutoff >= 0
```

La primera parte rechaza NaN y ambos infinitos con las operaciones genéricas
ya disponibles; la segunda rechaza todo negativo y acepta `-0`, que compara
igual a cero. El helper normaliza conceptualmente ambos ceros al mismo caso.

`InvalidSingularValueCutoffException` es necesaria porque el lenguaje no tiene
un parameter guard recuperable y `shapeGuard` representa incompatibilidades
estructurales, no escalares inválidos. No se reutiliza
`NumericalConvergenceException`: todavía no comenzó cálculo iterativo. Tampoco
`NonFiniteMatrixException`: el dato inválido no es una Matrix.

La precedencia es:

1. guards de shapes del factor y del RHS, si existen;
2. guard `rank <= p` de low-rank, si existe;
3. validación del cutoff explícito, si existe;
4. SVD para rutas Matrix;
5. clasificación y cálculo.

Así una shape inválida vence a un cutoff inválido. En rutas Matrix sin RHS ni
rank (`pseudoInverse`, `numericalRank`) no hay guard estructural previo y un
cutoff inválido vence al scan de finitud ejecutado por `svd`. En least-squares
desde Matrix, la compatibilidad del RHS se comprueba antes de validar cutoff y
antes de factorizar.

## 6. Contrato de factores manuales

Todo overload sobre `SVD<T>` ejecuta, en este orden:

```text
shapeGuard(columns(factor.U) == dimension(factor.S));
shapeGuard(rows(factor.Vt) == dimension(factor.S));
```

Estas relaciones bastan para que todo acceso sea seguro y recuperan `m`, `p`
y `n`. No se exige `p==min(m,n)`: un aggregate manual con factors ya
truncados es estructuralmente operable, aunque no sea el retorno canónico de
`svd`. Para que tenga las garantías matemáticas documentadas, el caller debe
proveer `U`/filas de `Vt` ortonormales, triplets correspondientes y `S` finito,
no negativo y no creciente.

Como en QR solve, V1 no revalida ortogonalidad, reconstrucción, ordering,
signos ni finitud de un aggregate manual. Hacerlo sería una certificación
costosa e incompleta y requeriría una nueva excepción de factor inválido. Fuera
de la precondición legítima se prometen guards, ownership y ejecución literal,
no pseudoinversa, optimalidad ni finitud.

Los overloads Matrix llaman exactamente una vez a `svd(A)` y reciben siempre
un factor legítimo. Conservan por ello el rechazo de input no finito mediante
`NonFiniteMatrixException` y el failure iterativo mediante
`NumericalConvergenceException`, sin wrappers ni traducción.

## 7. Pseudoinversa numérica

Para `A:m×n`, el resultado es `n×m`. Si `R` es el prefijo de índices retenidos
—un prefijo por el ordering de S—, cada celda se calcula sin `Sigma` dense:

```text
Aplus[j,i] = sum(r in R, Vt[r,j] * U[i,r] / S[r])
```

La implementación puede escoger entre las dos parentizaciones escalares que
no creen un owner temporal, pero la vertical concreta fijará una sola y la
calificará en O0/O2. No se promete igualdad bitwise entre versiones de
arquitectura ni correctly-rounded. Si el resultado matemático o un intermedio
no es representable, la aritmética IEEE puede producir infinito; no se
silencia, satura ni convierte en excepción de convergencia.

Se asigna exactamente una Matrix resultado y se acumulan sólo triplets
retenidos. No se construyen `V`, `U^T`, `Sigma+`, columnas escaladas owning ni
listas de índices. Tiempo `O(n*m*r)` y storage adicional `O(1)`, donde `r` es
el retained count. El resultado owning no aliasa factor ni entrada.

No se publica `pseudoInverseExact`. Sobre una SVD calculada, “exacta” sólo
podría significar dividir por cada bit no cero del espectro aproximado, no la
pseudoinversa algebraica exacta de la Matrix matemática. Ese comportamiento
ya es expresable explícitamente con `cutoff==0`; darle el alias `Exact`
prometería más de lo que floating point puede establecer. El overload default
es siempre la pseudoinversa truncada numérica aquí definida.

## 8. Mínimos cuadrados de norma mínima

Para `A:m×n` y `b:m`, se devuelve `x:n`:

```text
x = sum(r in R, v_r * ((u_r^T b) / S[r]))
```

Para `B:m×q`, se devuelve `X:n×q` aplicando la misma identidad por columna. Es
el minimizador de norma mínima del problema truncado determinado por `R`. Con
cutoff cero y una factorización algebraicamente exacta coincide con la
solución Moore–Penrose; V1 no afirma esa exactitud sobre datos redondeados.

El kernel calcula cada proyección `u_r^T rhs` en un acumulador escalar, la
divide una vez por `S[r]` y acumula directamente en el resultado. No construye
`A+`, `U^T rhs`, una Matrix diagonal, un Vector por columna ni una copia del
RHS. Los budgets son:

| RHS | tiempo con `r` retenidos | owner nuevo |
|---|---:|---:|
| Vector | `O(r*(m+n))` | Vector `n` |
| Matrix `m×q` | `O(r*q*(m+n))` | Matrix `n×q` |

Factor y RHS son préstamos shared, incluso si aliasan storage mediante una
construcción externa admisible; el resultado se inicializa aparte antes de
escribir. No se agregan variantes `InPlace` porque las shapes pueden cambiar y
se destruiría la reutilización de RHS o factors sin eliminar el owner de
salida.

Esta familia no modifica `solve(ref QR,...)`: QR conserva full-column-rank,
square/tall y exact-zero. SVD least-squares añade wide, rank deficiency y
minimum norm bajo una política explícita, por lo que el nombre diferente evita
selección silenciosa de algoritmo.

## 9. Rango: tres conceptos separados

V1 distingue:

1. el rango matemático de una Matrix real, que floating point no puede
   certificar en general;
2. `numericalRank`, cantidad retenida por el cutoff default o explícito;
3. `nonzeroSingularValueCount`, cantidad de entradas de `factor.S` que
   comparan exactamente distintas de cero.

`numericalRank` nunca se documenta como rango exacto. Usa el mismo helper que
pseudoinverse y least-squares, de modo que para el mismo factor y cutoff las
tres operaciones concuerdan sobre `r`.

`nonzeroSingularValueCount` sólo acepta `SVD`, porque su significado es una
observación representacional del espectro almacenado. No se ofrece desde
Matrix: llamarla “exacta” después de una SVD numérica induciría a confundirla
con rango algebraico. No usa epsilon ni cutoff y considera `+0` y `-0` cero.

Ambas consultas retornan `usize`, asignan cero owners y recorren como máximo
`p` valores. Con un factor legítimo ordenado pueden terminar al primer
descartado; la implementación puede conservar un scan completo si simplifica
qualification sin cambiar el resultado.

## 10. Condición en norma 2

`condition2` no recibe ni consulta cutoff. Para `p>0` y un factor legítimo:

```text
sigmaMax = S[1]
sigmaMin = S[p]

sigmaMin == 0 -> +Infinity
otherwise     -> sigmaMax / sigmaMin
```

Esto usa los extremos de todo el espectro thin, tanto en matrices square como
rectangulares. Una Matrix rectangular de rango `p=min(m,n)` tiene condición
finita; cualquier rank deficiency representada por un cero exacto retorna
infinito. Una Matrix cero no vacía retorna infinito. Un valor diminuto no cero
puede producir una condición enorme o infinito por overflow del cociente; no
se reclasifica mediante la política numérica.

Para `p==0`, V1 define por contrato el valor extendido `+Infinity`: no existe
un singular value mínimo positivo y no se inventa una condición cero o uno.
Es una convención total para shapes `m×0`, `0×n` y `0×0`, expresamente no una
afirmación de que la razón vacía esté definida en análisis clásico. Se produce
con aritmética IEEE genérica `one/zero`; no requiere constante Infinity ni
nueva excepción.

No se agrega `effectiveCondition2` en V1. Elegir si un subespacio retenido
vacío tiene condición cero, uno o infinita exige otro contrato, y el caller ya
puede combinar `numericalRank` con el espectro. El nombre `condition2` queda
reservado a la definición sin truncamiento aquí cerrada.

## 11. Eckart–Young para rango dado

Sea `p=dimension(S)`. `rank` es válido exactamente en `0..p`; un valor mayor
falla mediante:

```text
shapeGuard(rank <= p)
```

El budget es una compatibilidad estructural con el número de triplets, no un
fallo de convergencia ni una ocasión para clamp silencioso. No se agrega una
excepción nominal: `shapeGuard` ya gobierna extents/rangos incompatibles y el
fallo es abortivo como otros contratos estructurales de álgebra lineal.

La aproximación materializada es:

```text
A_rank[i,j] = sum(r=1..rank, U[i,r] * S[r] * Vt[r,j])
```

y retorna una Matrix `m×n`. `rank==0` produce la Matrix cero de esa shape;
`rank==p` reconstruye el factor completo sujeto a rounding. No se confunde
`rank` con `numericalRank`: se usan exactamente los primeros `rank` triplets,
incluidos ceros si el budget los alcanza. Por tanto cutoff y epsilon no
participan.

No se retorna `SVD<T>` truncada: el contrato canónico de `SVD` tiene
`p=min(m,n)` y reutilizarlo para un prefijo cambiaría su invariante. Tampoco se
crea `LowRankFactor<T>` sin otro consumer concreto. La representación
factorizada ya existe como el factor original más el escalar `rank`, ambos
prestables sin allocation.

Materializar cuesta `O(m*n*rank)`, crea exactamente el owner resultado y usa
`O(1)` escalares adicionales. No crea slices owning de `U/S/Vt`.

## 12. Errores de aproximación sin reconstrucción

Los dos criterios públicos validan `rank<=p` y leen sólo `S`:

```text
lowRankSpectralError(rank) = rank < p ? S[rank+1] : 0

lowRankFrobeniusError(rank)
    = sqrt(sum(i=rank+1..p, S[i]^2))
```

Son las igualdades de Eckart–Young/Mirsky para un factor legítimo ordenado. No
construyen `A_rank`, residual, diagonal ni workspace. Spectral es `O(1)` tras
guards; Frobenius es `O(p-rank)` y usa la autoridad privada de suma de
cuadrados escalada ya calificada (`scale`, `scaledSquares`) para evitar
overflow/underflow prematuro.

Se retorna la norma Frobenius, no su cuadrado. Publicar el cuadrado obligaría a
overflowear en casos donde la norma aún es representable y no agrega un
consumer demostrado. Qualification sí puede comprobar la identidad cuadrada
en escalas seguras.

Para `rank==p`, ambos errores son `+0`. Para `p==0`, el único rank válido es
cero y ambos retornan `+0` sin allocation ni lectura elemental.

## 13. Shapes degeneradas

Sea `A:m×n`, `B:m×q` y `p=min(m,n)`:

| operación | shape/valor cuando `p==0` |
|---|---|
| `pseudoInverse(A)` | Matrix `n×m`, sin backing porque un eje es cero |
| `leastSquares(A,b)` | Vector `n` lleno de cero; backing sólo si `n>0` |
| `leastSquares(A,B)` | Matrix `n×q` cero; backing sólo si `n*q>0` |
| `numericalRank` / nonzero count | `0` |
| `condition2` | `+Infinity` |
| `lowRankApproximation(A,0)` | Matrix `m×n`, sin backing |
| ambos errores en rank cero | `+0` |

RHS Vector requiere siempre `dimension(b)==m`; RHS Matrix requiere
`rows(B)==m`, incluso con cero columnas. Para `A:0×n`, el problema sin
ecuaciones devuelve la solución de norma mínima cero de dimensión `n`. Para
`A:m×0`, devuelve el único Vector vacío o Matrix `0×q`.

Una Matrix RHS con `q==0` conserva el otro extent. Los guards y la validación
del cutoff se ejecutan igualmente; sólo los loops de columnas y la allocation
de backing quedan vacíos.

## 14. Ownership y ergonomía

Toda entrada es `ref` shared:

- ninguna Matrix, SVD, field de factor ni RHS se mueve, copia o muta;
- no se permite partial move de `U`, `S` o `Vt`;
- el mismo factor puede alimentar cualquier secuencia de operaciones;
- los overloads Matrix preservan `A` mediante el contrato vigente de `svd`;
- todo resultado Matrix/Vector es owning, independiente y no contiene borrows;
- los escalares `usize`/`T` retornan por valor.

BORROW-ERGONOMICS permite calls sobre owners sin escribir `&`. No se agregan
variantes consuming o `InPlace`: ninguna puede prometer reutilización general
de backing entre shapes `m×n`, `n×m`, `n`, `n×q` sin casos especiales y sin
impedir reuse de factores.

## 15. Finitud, reciprocales y estabilidad

Las rutas Matrix heredan el gate completo de finitud de `svd`. Las rutas SVD
confían en la precondición del factor legítimo (§6). Un cutoff explícito se
valida siempre aunque el espectro o RHS esté vacío.

La clasificación normalizada evita formar `max(m,n)*epsilon*sigmaMax`, pero no
promete precisión uniforme:

- factores mal condicionados amplifican error en reciprocales y products;
- un singular value retenido puede tener reciprocal infinito;
- proyecciones `U^T rhs` pueden sufrir cancelación;
- outputs matemáticos fuera del rango representable producen IEEE infinity;
- underflow de contribuciones diminutas es posible;
- multiplicidades cercanas al cutoff hacen el retained rank sensible al
  rounding legítimo de la SVD.

No se forman ecuaciones normales, que cuadrarían la condición. Las normas de
error Frobenius usan acumulación escalada. Las sumas dense fijarán un orden
determinista en su milestone, sin fast-math, reassociation contractual,
acumulación promovida ni requisito correctly-rounded.

## 16. Recursos y allocations

Para operaciones sobre factor precomputado:

| operación | SVD calls | owners nuevos | peak adicional |
|---|---:|---:|---:|
| pseudoinversa | 0 | una Matrix `n×m` si no vacía | output + `O(1)` |
| LS Vector | 0 | un Vector `n` si no vacío | output + `O(1)` |
| LS Matrix | 0 | una Matrix `n×q` si no vacía | output + `O(1)` |
| rangos / condición | 0 | 0 | `O(1)` |
| low-rank materializada | 0 | una Matrix `m×n` si no vacía | output + `O(1)` |
| errores low-rank | 0 | 0 | `O(1)` |

No se cuenta el objeto de una excepción como backing numérico. Los outputs se
inicializan con cero usando la infraestructura existente; no se permite un
segundo backing oculto durante fill.

Cada overload Matrix ejecuta exactamente una SVD y luego el kernel homólogo
sobre factor. Su tiempo suma `O(m*n*p)` de SVD y el coste indicado del
consumer. Su peak conserva temporalmente `U:m×p`, `S:p`, `Vt:p×n` mientras se
crea/calcula el resultado. No reconstruye `A` salvo que la operación pedida sea
precisamente `lowRankApproximation`.

## 17. Selección futura de rank por error

Este milestone reserva, pero no publica ni implementa, criterios para hallar
el mínimo `rank` que satisface:

- error espectral absoluto;
- error espectral relativo a `S[1]`;
- error Frobenius absoluto o relativo;
- fracción de energía retenida;
- presupuesto máximo de rank.

Ese problema es una búsqueda sobre el espectro y es distinto de construir la
mejor aproximación para un rank ya dado. Una futura arquitectura deberá fijar
unidades, dominio de tolerancias, casos `S[1]==0`, desigualdad en el boundary,
acumulación estable y precedencia de criterios. No habrá heurística universal
ni energía default escondida.

Los errores públicos de §12 son primitives suficientes para que un caller
explícito implemente hoy una búsqueda, sin obligar a materializar candidatos.

## 18. Excepciones, traps y publicación

La familia reutiliza:

- `NonFiniteMatrixException` desde `svd(Matrix)`;
- `NumericalConvergenceException` desde `svd(Matrix)`;
- `shapeGuard` para factor/RHS/rank estructuralmente incompatibles;
- `InvalidSingularValueCutoffException` sólo para el nuevo parámetro escalar.

No se agrega excepción para rank deficiency: es input ordinario. No se usa
convergence para shapes, rank fuera de rango o cutoff. Allocation-size
overflow, allocation failure, bounds y shape traps conservan la semántica
general del lenguaje.

Toda excepción capturable ocurre antes de publicar el owner resultado. Unwind
libera factores temporales y output parcialmente inicializado exactamente una
vez; las entradas shared continúan vivas. Un trap abortivo no promete cleanup.

## 19. Capabilities, monomorfización e IR

La frontera permanece `T: IEEEFloat`, exactamente float32/float64 V1. Se usan
las guarantees ya implicadas: `Zero`, `One`, arithmetic, `Equal`, `Order`,
`Abs`, `Sqrt`, `Copy`, `Relocatable`, `Storable`, más `epsilon<T>()`. No se
agrega capability ni lista expandida a las firmas.

Todo vive como source ordinario en `linearAlgebra`. No habrá opcode de
pseudoinversa/rank/condition/low-rank, intrinsic de SVD derivada, runtime
numérico, LAPACK/NumPy productivo, recognition del package, `TypeId` dispatch,
witness, vtable, boxing ni compiler magic.

HIR paramétrico conserva borrows, guards y operaciones capability. Después de
monomorphization, MIR/SSA/LLVM contienen sólo float32 o float64 concretos,
loops e indexing ordinarios. `epsilon<T>()` sigue su lowering ya calificado.

## 20. Qualification

Cada vertical tendrá tests independientes en float32/float64 y O0/O2.

**Cutoff:** cero, `-0`, negativo, NaN, ambos infinitos, igualdad exacta,
predecesor/sucesor representable del threshold, `sigmaMax==0`, espectros
subnormales y escalas cercanas a extremos. Se demostrará equivalencia del
default normalizado con un oráculo de alta precisión donde ambos sean
representables y ausencia del producto vulnerable.

**Pseudoinversa:** square/tall/wide, full rank, rank-deficient, cero y vacías;
las cuatro identidades Moore–Penrose dentro de tolerancia y comparación con
`numpy.linalg.pinv`/LAPACK usando exactamente el mismo cutoff. No se comparan
vectores singulares individualmente.

**Least-squares:** RHS Vector/Matrix, múltiples columnas, sistemas
consistentes/inconsistentes, over/underdetermined, rank-deficient y cero. Se
comprueban residual mínimo, ortogonalidad apropiada, norma mínima frente a
perturbaciones en nullspace y oráculo `lstsq` con cutoff alineado. Se prueba
reuse del factor sin construir pseudoinversa.

**Rango/condición:** espectros sintéticos controlados, discontinuidad del
cutoff, diferencia entre nonzero count y rango numérico, rectangulares full
rank, ceros exactos, tiny nonzero, overflow del cociente, Matrix cero y
extents vacíos bajo el contrato de infinito.

**Eckart–Young:** todos los ranks de espectros pequeños, `0`, `p` y fuera de
rango; residual espectral `S[rank+1]`, residual Frobenius estable, optimalidad
contra candidatos perturbados, escalas extremas y ausencia de construcción en
las consultas de error.

**Contratos estructurales:** factors manuales con cada shape inválida,
precedencia de guards/cutoff/SVD, RHS vacíos, extents preservados, input intacto,
no alias, cleanup y conteos exactos de backings. Multiplicidades se validan por
reconstrucción, proyectores o valores, nunca por bases/signos elemento a
elemento.

**IR:** monomorfización completa, shared borrows, una sola call SVD en rutas
Matrix, cero SVD en rutas factor, ausencia de `Sigma`, pseudoinversa dentro de
least-squares, normal equations, transpose owner, allocations auxiliares,
LAPACK productivo y opcodes especiales.

NumPy/LAPACK sólo será oráculo del harness host y nunca dependencia, import o
link productivo.

## 21. Alternativas rechazadas

| alternativa | razón |
|---|---|
| policy object/strategy hierarchy | un solo escalar configurable no justifica framework |
| `rcond` ambiguo | mezcla factor relativo con cutoff absoluto y default dimensionado |
| `pseudoInverseExact` | confunde nonzero bits calculados con álgebra exacta |
| default formando `tau` | puede underflowear/overflowear antes de comparar |
| comparación `sigma >= cutoff` | retendría cero con cutoff cero y dividiría por cero |
| cutoff negativo como cero | oculta error del caller |
| aceptar cutoff infinito | convierte silenciosamente toda Matrix en rango cero |
| epsilon universal | cada algoritmo requiere su propia política y escala |
| `solve` para esta familia | cambiaría/ocultaría contratos LU/QR existentes |
| construir `A+` en least-squares | agrega `n*m` trabajo/storage innecesario |
| normal equations | cuadran condición y duplican kernels |
| retornar SVD truncada | viola la shape canónica thin de `SVD<T>` |
| nuevo `LowRankFactor` | no tiene consumer que justifique otro aggregate |
| condition number bajo cutoff | cambia la definición matemática sin pedirlo |
| lanzar por rank deficiency | es el caso normal que estas operaciones resuelven |
| validar factor canónico completo | coste alto, certificación incompleta y nueva excepción |

## 22. Fuera de scope

No se implementan ni incorporan:

- eigen decomposition, Complex, sparse, randomized o partial SVD;
- PCA pública o selección automática de rank;
- GPU, SIMD, BLAS/LAPACK productivo;
- nuevos kernels o iteraciones SVD;
- condition estimators sin SVD;
- actualización incremental;
- nuevas capabilities, conversions o cambios al compilador;
- API in-place/consuming;
- garantías correctly-rounded o precisión uniforme mal condicionada.

## 23. Secuencia de implementación

1. **LINEAR-ALGEBRA-SVD-CUTOFF-V1**: excepción, validación, conversión binaria
   privada de dimensión, clasificación default/explícita, nonzero count y
   qualification extrema. No materializa resultados dense.
2. **LINEAR-ALGEBRA-SVD-PSEUDOINVERSE-V1**: cuatro overloads, un output,
   identidades Moore–Penrose, recursos e IR.
3. **LINEAR-ALGEBRA-SVD-LEAST-SQUARES-V1**: Vector/Matrix, Matrix/factor,
   minimum norm, reuse y prueba de que no se construye `A+`.
4. **LINEAR-ALGEBRA-SVD-RANK-CONDITION-V1**: numerical rank desde Matrix,
   condición sin cutoff, infinitos, vacíos y extremos.
5. **LINEAR-ALGEBRA-SVD-LOW-RANK-V1**: materialización de rank dado y errores
   spectral/Frobenius sin residual; selección automática sigue reservada.
6. **LINEAR-ALGEBRA-SVD-DERIVED-QUALIFICATION-CLOSURE-1**: oráculos externos,
   propiedades cruzadas, float32/float64, O0/O2, ownership, allocations,
   monomorfización, IR y regresión completa.

La infraestructura de cutoff es compartida porque pseudoinverse,
least-squares y numerical rank deben retener exactamente el mismo prefijo.
Condition2 y low-rank por `rank` no dependen de ella por diseño; sólo reutilizan
guards de factor y, para Frobenius, la norma escalada existente. Ningún
milestone puede introducir una segunda fórmula de cutoff ni cambiar el
significado de las APIs aquí cerradas sin reabrir esta arquitectura.
