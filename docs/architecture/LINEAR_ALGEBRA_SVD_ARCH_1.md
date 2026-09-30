# LINEAR-ALGEBRA-SVD-ARCH-1 — descomposición singular real thin

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-30.

Este milestone es exclusivamente documental. No modifica
`linearAlgebra/src/lib.ae`, consumer, tests, compiler, runtime, standard library
ni capabilities numéricas. La infraestructura, implementación y calificación
se dividen en milestones posteriores (§24).

Autoridad relacionada:

- [AETHER-V1-LANGUAGE-CHARTER](AETHER_V1_LANGUAGE_CHARTER.md);
- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md);
- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [LINEAR-ALGEBRA-QR-SOLVE-ARCH-1](LINEAR_ALGEBRA_QR_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-QR-SOLVE-V1](LINEAR_ALGEBRA_QR_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md).

## 1. Decisión resumida

V1 ofrecerá la SVD real reducida, económica o **thin**:

```aether
struct SVD<T: Storable> {
    Matrix<T> U;
    Vector<T,Column> S;
    Matrix<T> Vt;
}

public class NonFiniteMatrixException : Exception {
    public init() {}
}

public class NumericalConvergenceException : Exception {
    public init() {}
}

SVD<T> svd<T: IEEEFloat>(ref Matrix<T> A);
```

Para `A : m×n` y `k=min(m,n)`, un retorno legítimo tiene exactamente:

```text
U  : m×k
S  : Vector<T,Column> de dimensión k
Vt : k×n

A ≈ U diag(S) Vt
U^T U ≈ I_k
Vt Vt^T ≈ I_k
S[1] >= ... >= S[k] >= +0
```

Las aproximaciones están sujetas al redondeo IEEE del tipo concreto. La API
admite matrices square, tall, wide, vacías, cero y rank-deficient. Preserva la
entrada mediante préstamo shared. No se agrega `svdInPlace` en V1.

El objetivo productivo es Golub–Kahan/Reinsch: reducción Householder a
bidiagonal, seguida por iteración QR implícita shifted con deflation, y
acumulación de vectores singulares. Formar `A^T A` o `A A^T` queda prohibido
como implementación productiva.

Antes de cualquier iteración se rechaza toda entrada con NaN o infinito
mediante `NonFiniteMatrixException`. Toda iteración tiene límite interno; no
alcanzar convergencia finita lanza `NumericalConvergenceException`. Nunca se
permite un loop no acotado.

## 2. Representación: thin frente a full

Se elige **thin** como representación normativa. Full habría producido
`U:m×m`, `S:k`, `Vt:n×n`. Esa forma agrega `m-k` o `n-k` vectores de un
complemento ortogonal que no participan en la reconstrucción y cuya elección
no es única. En matrices muy rectangulares, su coste `O(m²+n²)` puede dominar
innecesariamente entrada y cálculo.

Thin conserva todos los `k` triplets singulares, no una aproximación truncada.
Por tanto:

- reconstruye cualquier `A:m×n` en aritmética exacta;
- representa los ceros singulares y matrices rank-deficient;
- basta para pseudoinverse y solves minimum-norm futuros;
- permite rank, condición y truncación desde `S`;
- hace directa la aproximación rank-`r` con los primeros `r` triplets;
- evita completar el subespacio nulo izquierdo cuando `m>n` y el derecho
  cuando `m<n`.

No se elige una representación de reflectors, bidiagonal más transforms ni un
factor lazy. Éstas serían útiles como artefactos internos, pero expondrían el
algoritmo, dificultarían impresión/consumo y obligarían a futuras operaciones a
reconstruir vectores. Tampoco se almacena `Sigma` como Matrix dense: tendría
`k²` celdas para sólo `k` valores útiles.

La decisión thin no bloquea una futura `svdFull(A)`. Esa operación deberá tener
nombre explícito, retornar un tipo o contrato que declare las shapes full y
construir los complementos ortogonales. No cambiará el significado de `svd` ni
de `SVD<T>` V1. No se reserva hoy una firma concreta.

## 3. Tipo público e identidad matemática

Los nombres normativos de fields son exactamente `U`, `S` y `Vt`. La notación
es breve, convencional y coherente con `QR.Q`, `QR.R`, `LU.L` y `LU.U`.
`singularValues` sería descriptivo pero rompería la familia matemática sin
resolver ninguna ambigüedad: el tipo nominal ya identifica `S`.

`S` es `Vector<T,Column>`. Su orientación permite imprimirlo y procesarlo con
la infraestructura Vector vigente, pero no significa que `S` sea una Matrix
columna dentro de la identidad: `diag(S)` es sólo notación matemática. La API
no materializa ni publica esa Matrix.

Para cada `i=1..k`, la columna `U[:,i]`, el escalar `S[i]` y la fila
`Vt[i,:]` forman un triplet correspondiente. Equivalentemente, si
`v_i = transpose(Vt[i,:])`:

```text
A v_i = S[i] u_i
A^T u_i = S[i] v_i
A = sum(i=1..k, S[i] u_i v_i^T)
```

Para `m>n`, `k=n`: las `n` columnas de `U` son ortonormales y `Vt` es square
ortogonal. No se entrega el complemento izquierdo de dimensión `m-n`.

Para `m<n`, `k=m`: `U` es square ortogonal y las `m` filas de `Vt` son
ortonormales. No se entrega el complemento derecho de dimensión `n-m`.

Para `m==n`, ambos factores son square. En todos los casos la ortogonalidad es
de las columnas de `U` y filas de `Vt`, no una promesa de que `U U^T` o
`Vt^T Vt` sean identidad cuando el factor correspondiente es rectangular.

## 4. Contrato exacto de shapes y casos vacíos

`svd` admite cualquier Matrix rectangular sin `shapeGuard`: los dos extents de
una Matrix válida bastan para definir el dominio. Sea siempre
`k=min(rows(A),columns(A))`.

| entrada `A` | `U` | `S` | `Vt` |
|---|---:|---:|---:|
| `m×n`, `m,n>0` | `m×k` | `k` | `k×n` |
| `5×0` | `5×0` | `0` | `0×0` |
| `0×7` | `0×0` | `0` | `0×7` |
| `0×0` | `0×0` | `0` | `0×0` |

Los extents lógicos se conservan incluso cuando no existe backing. En toda
entrada con `k==0`, el chequeo de finitud y los kernels son recorridos vacíos;
la operación retorna las tres shapes de la tabla, no lanza y no fabrica una
identidad full. Las identidades de reconstrucción y ortogonalidad valen por
vacuidad.

Una matriz cero no vacía sí produce `k` triplets: `S` contiene `k` ceros
positivos y `U`/`Vt` contienen bases ortonormales deterministas según el
algoritmo, aunque matemáticamente no sean únicas.

## 5. Ordering, signos y multiplicidades

Para todo retorno normal, `S` contiene sólo valores finitos, normalizados no
negativos y en orden no creciente bajo el `Order` IEEE ordinario:

```text
S[1] >= S[2] >= ... >= S[k] >= +0
```

Como los no finitos de entrada se rechazan y ningún retorno puede contener un
`S` no finito, no hace falta definir un orden total artificial para NaN. Esta
garantía es sobre los valores representables producidos por una ejecución
legítima, no sobre los valores singulares reales exactos antes de redondear.

Después de converger, cada valor diagonal `d_i` se transforma en `abs(d_i)`.
Si `d_i < 0`, se niega la fila correspondiente `Vt[i,:]`; `U` permanece sin
cambio. Usar `abs` normaliza también `-0` a `+0`. Esta elección preserva la
reconstrucción y fija dónde ocurre la corrección, pero no canonicaliza los
signos generales de los vectores.

Luego se ordenan los triplets por `S` descendente. Cada intercambio de
`S[i]`/`S[j]` intercambia también las columnas `i`/`j` de `U` y las filas
`i`/`j` de `Vt`. El sort es estable respecto del orden producido por el kernel:
valores que comparan iguales no se intercambian. Esto da reproducibilidad para
una misma implementación y orden de operaciones, no una base matemática
canónica.

V1 no promete un signo concreto. El cambio simultáneo
`u_i -> -u_i`, `v_i -> -v_i` es observable en los fields pero igualmente
válido. No se agrega un pase costoso de canonicalización. Tests y consumers no
deben exigir signos elemento a elemento.

Si hay valores singulares repetidos —incluidos múltiples ceros— cualquier base
ortonormal del subespacio correspondiente es legítima. Ni el sort estable ni
el determinismo del kernel hacen normativa esa base. Qualification debe medir
reconstrucción, ortogonalidad y, cuando compare vectores, proyectores o
subespacios; nunca debe comparar `U`/`Vt` elemento a elemento con un oráculo.

## 6. Rank deficiency y futuros conceptos de rango

Rank deficiency es parte ordinaria del dominio. Dependencia de filas o
columnas y valores singulares cero no lanzan excepción. El kernel debe
completar `U` y `Vt` con vectores ortonormales para conservar las shapes thin y
las identidades de §3.

V1 no define rango numérico. En floating point no es correcto usar simplemente
`count(S != 0)`: perturbaciones y redondeo convierten ceros matemáticos en
valores pequeños. Una futura `rank(factor,tolerance)` deberá fijar una política
explícita dependiente de escala, dimensión y precisión; no reinterpretará los
valores almacenados por SVD.

El orden descendente permite que una futura aproximación Eckart–Young rank-`r`
use directamente los primeros `r` triplets. Thin también permite
`A^+ = V diag(S^+) U^T` sin full `U` o `V`, y una futura condición espectral a
partir de extremos de `S` bajo una política explícita para ceros/rango. Ninguna
de esas APIs forma parte de este milestone.

## 7. Ownership y superficie de entrada

`svd(ref Matrix<T> A)` es preserving. La adaptación de borrow vigente permite
la call cotidiana `svd(A)`; durante la call `A` no se mueve ni se escribe y,
después de retorno normal o excepción capturada, el owner original sigue
disponible con descriptor, backing y valores intactos.

El resultado es owning e independiente: `U`, `S` y `Vt` no aliasan `A` ni
entre sí. La implementación hará una copia lógica inicial de `A` y usará ese
workspace para la reducción. Como en las factorizaciones vigentes, no se
promete que el optimizador elimine esa copia.

No se agrega `svdInPlace(Matrix<T> A)` en V1. Aunque una implementación futura
podría reciclar el rectángulo de entrada como `U` en el caso tall o `Vt` en el
wide, el beneficio y la secuencia segura dependen de la representación real de
reflectors y del ensamblado. Publicar hoy la variante obligaría a un contrato
de reutilización antes de medirlo. El nombre queda conceptualmente reservado
y sólo podrá incorporarse con arquitectura y qualification propias; `svd`
seguirá siendo preserving.

## 8. Política de NaN e infinito

Antes de bidiagonalizar, la copia de trabajo se recorre completamente por filas
y columnas crecientes. Cada valor `x:T` es finito exactamente cuando:

```text
(x - x) == 0
```

La prueba acepta finitos normales, subnormales y ambos ceros, y rechaza NaN y
ambos infinitos con `NonFiniteMatrixException`. No se deja la política a la
propagación IEEE: NaN puede impedir deflation y un infinito vuelve inútiles las
rotaciones y normas. Rechazar antes de iterar hace el fallo determinista y
evita usar el cap como detector accidental del input.

`NonFiniteMatrixException` es pública, nominal, sin payload y reusable por
futuras descomposiciones que adopten el mismo dominio. No se reutiliza
`NotPositiveDefiniteException`: finitud de una Matrix general no tiene relación
con simetría o positive definiteness. Tampoco es un `ShapeMismatch`, porque
toda shape rectangular es válida.

La ruta preserving crea y llena su copia antes de que el kernel la valide,
siguiendo la ergonomía vigente. Si se lanza, unwind destruye el workspace y
preserva la fuente. El orden observable entre múltiples no finitos es el primer
elemento del recorrido row-major lógico, aunque todos producen la misma clase
sin payload.

## 9. Convergencia y error numérico

Se agrega `NumericalConvergenceException`, pública, nominal y sin payload. Es
general para algoritmos numéricos iterativos —por ejemplo eigen QR futuro— y
no menciona SVD en el nombre.

La iteración bidiagonal mantiene un contador acotado de pasos QR. Su límite es
una constante de política interna, documentada y dependiente de `k`; no es un
argumento público, tolerancia ni resultado observable en ejecuciones que
convergen. El sub-milestone de iteración fijará el multiplicador exacto junto
con la fórmula concreta de shift, pero no puede cambiar estas reglas:

- el bound total es finito y `O(k²)`, con aritmética de extents checked;
- cada paso consume presupuesto aunque no reduzca el bloque activo;
- deflation reduce el estado activo y no reinicia presupuesto ilimitadamente;
- agotar el presupuesto lanza `NumericalConvergenceException`;
- un estado iterativo o resultado singular no finito también lanza esa
  excepción antes de ordenar o publicar un factor;
- nunca se devuelve un aggregate parcial ni existe loop sin cap.

Esto deja abierta una constante de implementación deliberadamente local, no
una decisión de API. Cambiarla puede alterar cuándo un caso patológico falla,
pero no autoriza menor calidad ni loops no acotados. La qualification debe
incluir una vía controlada o hook de test para demostrar el failure path sin
depender de encontrar casualmente una matriz adversarial.

## 10. Algoritmo productivo

La familia normativa es Golub–Kahan/Reinsch:

1. orientar el problema para trabajar sobre una forma tall/square; para una
   entrada wide se aplica el mismo kernel conceptualmente a `A^T` y al final se
   intercambian los roles de los vectores izquierdos/derechos, sin cambiar el
   contrato público;
2. reducir por reflectors Householder izquierdos y derechos a bidiagonal real;
3. iterar sobre diagonal y superdiagonal mediante QR implícito shifted,
   deflation y splitting de bloques;
4. acumular las transformaciones ortogonales en las matrices thin;
5. normalizar signos, verificar finitud y ordenar triplets.

### Alternativas evaluadas

**Eigendecomposition de `A^T A` o `A A^T`: rechazada.** Es tentadora por
reutilización futura de eigen, pero cuadra el condition number y pierde
precisión relativa en valores singulares pequeños. También forma una Matrix
dense adicional, suma productos con riesgo de overflow/underflow y perjudica
rank/pseudoinverse, precisamente los consumers estratégicos de SVD.

**One-sided Jacobi: no elegida para V1.** Puede ofrecer excelente precisión
relativa y paralelismo, pero requiere sweeps globales, una política distinta de
convergencia y más trabajo sobre matrices muy rectangulares. Es una alternativa
futura válida o un oráculo independiente de qualification, no el kernel V1.

**Bidiagonal divide-and-conquer u otras variantes:** se reservan para tamaños
grandes o backends optimizados. Incrementan mucho la complejidad de workspace y
deflation secular sin mejorar la primera frontera pública.

Golub–Kahan evita ecuaciones normales, tiene coste dense estándar, trata tall y
wide simétricamente y permite reutilizar el patrón Householder y la norma
escalada ya calificados en QR. Esa reutilización es de técnica/helper source,
no delegación a `qr(A)` ni dependencia de su `Q:m×m`, que derrotaría thin.

## 11. Reducción bidiagonal y acumulación

La copia `m×n` almacena temporalmente la bidiagonal y las colas de reflectors
Householder compactos. No se materializa una Matrix por reflector ni una
secuencia de `H`/`G` dense. La diagonal `d:k` y la off-diagonal `e:max(k-1,0)`
se extraen a Vectors/work arrays lineales.

Los reflectors se almacenan durante la reducción y se aplican/materializan en
orden apropiado al ensamblar `U:m×k` y `Vt:k×n`. No se acumulan desde el primer
paso en factors full `m×m`/`n×n`. La implementación puede materializar primero
el factor que no reutiliza el workspace y después sobrescribir el workspace
con el otro factor thin, siempre que preserve las colas hasta su último uso.

Para `m>=n`, la bidiagonal es upper `k×k`. Para `m<n`, el kernel tall sobre la
orientación transpuesta produce la misma forma y el ensamblado intercambia sus
factores, de modo que el resultado público sigue siendo `U:m×m`, `Vt:m×n`.
Una transpose view puede gobernar accesos; no se permite materializar una copia
adicional de `A^T` sólo por conveniencia.

Las bases asociadas a ceros deben completarse mediante los mismos products
ortogonales, no dividiendo por el singular value. Así rank deficiency y matriz
cero no son casos excepcionales.

## 12. Iteración bidiagonal, deflation y estado

El estado iterativo esencial son `d`, `e`, los límites de bloques activos y las
dos colecciones de vectores singulares acumulados. La iteración usa pasos QR
implícitos bulge-chasing con shifts estables derivados del bloque bidiagonal;
las rotaciones de Givens se aplican inmediatamente a las columnas de `U` y
filas de `Vt` correspondientes.

Una entrada off-diagonal se deflaciona cuando es despreciable a escala local,
conceptualmente:

```text
abs(e[i]) <= epsilon(T) * (abs(d[i]) + abs(d[i+1]))
```

La fórmula final debe incluir tratamiento escalado para evitar overflow en la
suma y una regla segura cuando la escala local es cero. No se usa una
tolerancia absoluta global ni una constante decimal por precisión. Splits y
ceros diagonales se tratan dentro del algoritmo bidiagonal sin declarar rank
failure.

No se fija en este documento cada fórmula del shift o cada dirección de chase:
eso pertenece a `SVD-BIDIAGONAL-QR-ARCH-1`. Sí quedan fijadas la familia
implicit shifted QR, la escala local, la acumulación vectorial, deflation,
normalización final, sort correlacionado y convergencia acotada. Ese
sub-milestone no puede sustituir eigen de ecuaciones normales ni Jacobi bajo el
mismo nombre sin reabrir esta arquitectura.

## 13. Tolerancia y gap de machine epsilon

La tolerancia debe derivarse del machine epsilon de `T` y magnitudes locales.
No puede reutilizar los exact-zero contracts de LU/QR solve ni introducir
`1e-6`/`1e-12` dispersos.

Hoy `NUMERIC-CAPABILITIES-V1` ofrece `Zero`, `One`, aritmética, comparación,
`Abs`, `Sqrt` y el marker sellado `IEEEFloat`, pero no una operación genérica
para machine epsilon. Éste es un **gap bloqueante de infraestructura** para la
implementación genérica y debe cerrarse antes del kernel iterativo.

El milestone `IEEE-FLOAT-CONSTANTS-ARCH-1/V1` deberá proveer una única operación
estándar equivalente a:

```aether
T epsilon<T: IEEEFloat>();
```

con `epsilon<float32> = 2^-23` y `epsilon<float64> = 2^-52`, entendidos como la
distancia entre `1` y el siguiente valor representable. Debe ser usable desde
source genérico, monomorfizar a una constante concreta, no hacer dispatch
runtime y tener una sola autoridad. El diseño de ese milestone decidirá si se
expresa como capability atómica o primitive estándar; este documento no
modifica retrospectivamente `NUMERIC-CAPABILITIES-V1`.

`copysign` no es requisito: selección de signo mediante `Order` conserva el
patrón QR vigente. `hypot` tampoco es requisito público: normas y rotaciones
pueden usar un helper interno de sum-of-squares/hipotenusa escalado construido
con `Abs`, `Order`, `Div`, `Mul` y `Sqrt`. Si el sub-milestone demuestra que una
primitive adicional mejora semántica o lowering, deberá diseñarla aparte.

## 14. Autoridad de normas estables

Queda prohibido calcular una norma como `sqrt(sum(x_i*x_i))`. La autoridad
source será un único helper privado de norma escalada compartido por QR y SVD,
extraído sin cambiar el orden contractual ni los resultados calificados del QR
vigente. El estado conceptual es `scale` más `scaledSquares`; sólo se forman
ratios de magnitudes comparables antes de `sqrt`.

El helper de hipotenusa para Givens seguirá el mismo principio de scaling. No
habrá copias independientes de constantes o fórmulas de tolerancia en
bidiagonalización, iteración y qualification. Extraer el helper y demostrar que
QR no cambia pertenece al milestone de infraestructura, no a este documento.

## 15. Capabilities y tipos admitidos

La frontera pública permanece exactamente `T: IEEEFloat`, que en V1 admite
sólo `float32` y `float64`. No admite integers, aggregates numéricos de usuario
ni Complex.

El kernel requiere las guarantees ya implicadas por `IEEEFloat`:
`Zero`, `One`, `Add`, `Sub`, `Mul`, `Div`, `Negate`, `Equal`, `Order`, `Abs`,
`Sqrt`, además de `Copy`, `Relocatable` y `Storable`. La única necesidad no
cubierta es machine epsilon (§13). No se agrega una mega-lista de capabilities
a la firma.

La SVD compleja futura necesitará conjugate transpose, magnitud real asociada,
phases en lugar de signos y posiblemente `S` sobre un tipo real distinto de
los elementos de `U`/`Vt`. Por eso no se generaliza prematuramente este
aggregate real.

## 16. Complejidad y allocations

El objetivo de tiempo dense es `O(m*n*k)`, con `k=min(m,n)`, más el trabajo
iterativo bidiagonal `O(k²)` por la secuencia convergente y la aplicación de
rotaciones a los factors. No se promete un conteo exacto de FLOPs ni un orden
bitwise entre versiones.

El storage owning del resultado es inevitable:

```text
U:  m*k elementos
S:  k elementos
Vt: k*n elementos
```

Se permiten además, de manera explícita y acotada:

- una copia/workspace `m*n` de la entrada preserving, reutilizable como uno de
  los outputs cuando el ensamblado concreto lo demuestre seguro;
- `O(k)` para diagonal, off-diagonal, rotations/scalars y bookkeeping de
  bloques;
- como máximo `O(m*k + k*n)` storage transitorio para materializar/acumular
  vectores si el primer kernel no puede reutilizar el workspace sin perder
  reflectors.

No se exige artificialmente una sola allocation. Sí se exige que el número de
owners/workspaces sea finito, independiente del número de iteraciones y
documentado por branch tall/wide/empty. Está prohibido asignar dentro de cada
paso QR, conservar el historial de iteraciones, crear un factor full, construir
`diag(S)`, `A^T A`, `A A^T` o una Matrix transpuesta adicional.

Para `k==0`, cada output conserva sus extents y no tiene backing; la copia
preserving tampoco asigna backing. La qualification futura fijará conteos
concretos una vez exista el ensamblado, en lugar de inventarlos antes del
kernel.

## 17. Reconstruction y qualification matemática

Los tests no necesitan una Matrix `diag(S)`. Un helper de test calcula por
celda, con acumulación independiente:

```text
reconstructed[i,j] = sum(r=1..k, U[i,r] * S[r] * Vt[r,j])
```

o escala columnas de una copia test-only de `U`. Ese helper no se vuelve API
pública. El residual se mide con norma escalada y umbral dependiente de
`epsilon(T)`, dimensiones y una escala como `||A||`; no se exige igualdad
bitwise ni un decimal universal.

La ortogonalidad se comprueba por separado:

```text
||U^T U - I_k||
||Vt Vt^T - I_k||
```

con tolerancias dimensionadas para `float32`/`float64`. Deben existir checks de
shapes, finitud, no negatividad, orden descendente y correspondencia de
triplets además del residual.

La matriz de calidad incluye:

- square, tall y wide dense deterministas;
- diagonal y rectangular diagonal;
- rank-deficient por filas/columnas dependientes;
- cero, identidad y `0×0`, `m×0`, `0×n`;
- valores singulares repetidos;
- casos controlados ill-conditioned con valores conocidos;
- escalas muy grandes y pequeñas que distingan norma escalada de suma ingenua;
- ambas precisiones, O0 y O2;
- rechazo de NaN/Inf en distintas posiciones y failure de convergencia;
- input intacto/reusable, cleanup y presupuestos de allocation.

Los singular values se comparan, cuando sea viable, contra un oráculo
independiente de alta calidad (por ejemplo LAPACK sólo en el harness o valores
analíticos precomputados), no contra ecuaciones normales ni contra el mismo
kernel. Para multiplicidades se comparan proyectores/subespacios y no bases.
Las tolerancias del oráculo se versionan y justifican por precisión, escala y
dimensión.

## 18. HIR, MIR, SSA y backends futuros

SVD será source ordinario del package `linearAlgebra`. No se agrega opcode SVD,
intrinsic de descomposición, reconocimiento del nombre del package, lowering
oculto a LAPACK ni dispatch por `TypeId`.

HIR paramétrico contendrá borrows, exceptions, constructors, loops y
operaciones capability ordinarias. Tras monomorphization, MIR y SSA contendrán
sólo operaciones concretas float32/float64; no sobrevivirán parámetros
genéricos, witnesses, capabilities, boxing o vtables. La futura operación de
epsilon deberá bajar por su autoridad estándar propia, no por reconocimiento
de `svd`.

Una implementación LAPACK futura podrá ofrecerse como backend/package
optimizado siempre que preserve exactamente shapes thin, ordering, signos no
canónicos, política de no finitos, excepciones y ownership. No forma parte de
V1 y el kernel productivo propio no dependerá de LAPACK.

## 19. Consumer futuro

El consumer debe usar el nombre preserving y demostrar la reutilización:

```aether
Matrix<float64> A = /* tall, wide o rank-deficient */;
var factor = svd(A);

println(factor.U);
println(factor.S);
println(factor.Vt);
println(A); // A sigue viva e intacta
```

También debe cubrir `float32` por inferencia y la forma explícita
`svd<float32>(A)`. No se agregan wrappers por precisión, default `float64`,
selector full/thin, tolerancia pública ni opción de algoritmo.

## 20. Compatibilidad con APIs futuras

La representación y ordering dejan disponibles, sin prometer firmas todavía:

- pseudoinverse mediante los triplets cuyo `S[i]` supere una política futura;
- least-squares rank-deficient y minimum-norm sin full factors;
- rank numérico bajo tolerancia explícita;
- `cond2` a partir de extremos relevantes de `S`;
- aproximación low-rank/PCA tomando prefijos contiguos;
- métodos espectrales que consuman `U`, `S` o `Vt` directamente.

Ninguna API futura debe asumir que un singular value matemáticamente cero se
almacena bitwise como cero, ni que signos/bases repetidas son canónicos. Debe
validar las shapes del aggregate si acepta un `SVD<T>` construido manualmente;
este milestone sólo define el productor `svd` y no agrega consumers de factor.

## 21. Precedencia de fallos y publicación

La secuencia conceptual de `svd` es:

1. leer extents y crear la copia lógica preserving;
2. validar finitud completa de la copia;
3. construir todos los workspaces acotados necesarios;
4. bidiagonalizar y ensamblar factors;
5. iterar con cap y deflation;
6. normalizar signos, comprobar finitud y ordenar;
7. publicar el único `SVD<T>` completo.

Allocation failure y overflow de tamaño conservan los traps generales del
lenguaje. Un no finito de entrada encontrado después de copiar lanza
`NonFiniteMatrixException`. Tras pasar esa validación, agotamiento o estado no
finito del algoritmo lanza `NumericalConvergenceException`. En toda exception,
unwind libera exactamente una vez cada owner inicializado y no deja escapar
outputs parciales. Los traps abortivos mantienen la semántica general sin
promesa de cleanup.

## 22. Decisiones rechazadas

| alternativa | motivo de rechazo en V1 |
|---|---|
| full SVD por defecto | storage y complementos ortogonales innecesarios |
| `singularValues` field | verbosidad sin ambigüedad dentro de `SVD` |
| `Sigma: Matrix<T>` | `O(k²)` storage para `k` datos y API de test artificial |
| consumir `A` en `svd` | contradice preserving-by-default vigente |
| `svdInPlace` inmediato | reutilización aún no demostrada por el ensamblado |
| propagar NaN/Inf | puede impedir deflation y producir resultados inútiles |
| trap por no finito/convergencia | son fallos numéricos recuperables, no shapes |
| excepción `SVDConvergenceException` | concepto reutilizable por eigen y otros métodos |
| lanzar por rank deficiency | ceros singulares son resultado normal |
| canonicalizar signos/bases | trabajo extra sin identidad matemática única |
| ordenar `S` sin vectors | rompe los triplets y la reconstrucción |
| formar ecuaciones normales | cuadra condición y degrada valores pequeños |
| tolerancia decimal hardcoded | no escala con tipo, magnitud o dimensión |
| loops hasta converger | no garantiza terminación |

## 23. Fuera de scope

No se implementan ni diseñan por completo en este milestone:

- pseudoinverse, rank, condition number o low-rank approximation;
- PCA, least-squares vía SVD o minimum-norm solve;
- SVD full, truncada, sparse o randomized;
- Complex SVD;
- GPU, SIMD/blocked tuning, BLAS/LAPACK o FFI;
- valores/vectores singulares parciales;
- API pública de tolerancia, iteration cap o selección de algoritmo;
- actualización incremental de una SVD.

## 24. Secuencia de implementación

El cierre se descompone en verticales verificables:

1. **IEEE-FLOAT-CONSTANTS-ARCH-1/V1**: machine epsilon genérico y lowering
   concreto, sin tocar SVD.
2. **LINEAR-ALGEBRA-STABLE-NORM-V1**: extraer/calificar la norma e hipotenusa
   escaladas compartidas, demostrando no regresión bitwise/contractual de QR.
3. **LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1/V1**: reducción compacta tall y wide,
   shapes cero, reflectors y ensamblado thin, todavía con oráculos internos.
4. **LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1/V1**: fórmulas exactas de shift,
   chase, deflation, cap, acumulación y failure path.
5. **LINEAR-ALGEBRA-SVD-ASSEMBLY-V1**: API pública, excepciones, preserving,
   signos, sort correlacionado y consumer.
6. **LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1**: oráculo independiente,
   calidad extrema, ownership/allocations, O0/O2 e IR.

Cada vertical puede refinar orden interno y constantes privadas, pero no puede
cambiar representación, shapes, algoritmo productivo, políticas públicas ni
excepciones cerradas aquí sin reabrir `LINEAR-ALGEBRA-SVD-ARCH-1`.
