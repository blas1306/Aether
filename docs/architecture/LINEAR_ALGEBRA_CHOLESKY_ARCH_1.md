# LINEAR-ALGEBRA-CHOLESKY-ARCH-1 — factorización de Cholesky real

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este milestone es exclusivamente documental. No modifica
`linearAlgebra/src/lib.ae`, tests, compiler, runtime ni standard library. La
implementación y calificación pertenecen a un milestone posterior.

Autoridad relacionada:

- [NUMERIC-CAPABILITIES-ARCH-1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [NUMERIC-GENERIC-MIGRATION-CLOSURE-1](NUMERIC_GENERIC_MIGRATION_CLOSURE_1_REPORT.md);
- [LINEAR-ALGEBRA-LU-ARCH-1](LINEAR_ALGEBRA_LU_ARCH_1.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [LINEAR-ALGEBRA-OAL-V1-QR](LINEAR_ALGEBRA_OAL_V1_QR_REPORT.md).

## 1. Decisión resumida

Cholesky V1 acepta una `Matrix<T>` owning, square, finita, exactamente
simétrica y definida positiva, para `T: IEEEFloat`. Devuelve el factor inferior
materializado que satisface, sujeto al redondeo IEEE del algoritmo:

```text
A = L L^T
```

La superficie pública cerrada es:

```aether
struct Cholesky<T: Storable> {
    Matrix<T> L;
}

public class NotSymmetricMatrixException : Exception {
    public init() {}
}

public class NotPositiveDefiniteException : Exception {
    public init() {}
}

Cholesky<T> cholesky<T: IEEEFloat>(Matrix<T> A);
```

`T` se infiere desde `Matrix<T>`. No hay overloads por precisión, default
`float64`, wrapper `choleskyFloat32`, selector lower/upper ni tolerancia
implícita. `float32` y `float64` son las únicas instancias admitidas por el
marker sellado `IEEEFloat`.

`A` se consume y su backing se transforma en `L`. El triángulo superior se
escribe con ceros del tipo concreto antes del retorno. El kernel no asigna otra
Matrix ni otro buffer proporcional a `n²`.

## 2. Auditoría de convenciones vigentes

`linearAlgebra` ya fija las convenciones relevantes:

- los objetos de factorización son aggregates nominales representacionales:
  `LU<T: Storable>` y `QR<T: Storable>`;
- los kernels toman la Matrix por valor y consumen su owner: `lu(Matrix<T>)` y
  `qr(Matrix<T>)`;
- los kernels numéricos nuevos tienen una sola implementación source con
  `T: IEEEFloat` y dejan que el argumento infiera `T`;
- los fields matemáticos usan mayúscula convencional (`L`, `U`, `Q`, `R`);
- una precondición dinámica de shape usa `shapeGuard`, cuyo fallo es el trap
  abortivo `ShapeMismatch`, no una Exception capturable;
- los fallos matemáticos capturables usan clases nominales ordinarias, como
  `SingularMatrixException`;
- los shapes con producto de extents cero conservan metadata y no asignan
  backing;
- `LU<T>` y `QR<T>` restringen el aggregate sólo por representación; la
  operación productora expresa el dominio numérico.

Se adopta por ello `Cholesky<T>` y no una `Matrix<T>` desnuda. Aunque V1 sólo
contiene `L`, el tipo nominal conserva qué relación matemática representa la
matriz, evita confundirla con un triangular arbitrario y ofrece el receptor
natural para futuros `solve` y `det` especializados. No se justifica un field
adicional, metadata de pivots ni copia de la entrada.

## 3. Dominio matemático V1

El dominio aceptado es el de matrices reales finitas:

```text
A : n×n
A = A^T exactamente según la comparación definida en §5
x^T A x > 0 para todo vector real no nulo x
```

La factorización calculada es la Cholesky sin pivoting. Para una entrada dentro
del dominio y una ejecución que no pierde la positividad por redondeo,
`L` es `n×n`, triangular inferior y tiene diagonal estrictamente positiva.

V1 no acepta matrices rectangulares, semidefinidas positivas, indefinidas,
singulares, no finitas ni aproximadamente simétricas. Tampoco promete decidir
la propiedad matemática sobre reales exactos independientemente del redondeo:
la decisión se hace con los valores intermedios concretos del algoritmo V1.

El caso `0×0` es la única excepción vacía al enunciado usual “para todo vector
no nulo”: se acepta como factorización válida por vacuidad y produce `L` de
shape `0×0`.

## 4. Representación canónica lower

V1 publica sólo:

```text
A = L L^T
```

con `L` lower. No publica simultáneamente `R` para `A = R^T R` ni un enum que
seleccione orientación.

La elección lower tiene cuatro ventajas concretas:

1. el algoritmo row-oriented descrito en §9 escribe naturalmente el triángulo
   inferior sin transpose ni workspace;
2. el backing de la entrada puede reciclarse directamente;
3. el futuro solve ejecuta primero forward substitution con `L` y después
   backward substitution con `L^T`, conservando un solo factor;
4. coincide con el nombre y significado del field `L` ya familiar en `LU`, sin
   exponer un detalle de storage packed.

Upper tendría el mismo coste asintótico, pero ofrecer ambas formas duplicaría
superficie, tests y decisiones de consumo sin aportar capacidad matemática.
Una variante upper futura, si existe una necesidad medida, será una API
explícita y no cambiará el significado de `Cholesky.L`.

## 5. Contrato exacto de simetría

La simetría de V1 se comprueba explícitamente y antes de la primera escritura
sobre `A`. Para cada par `1 <= j < i <= n` se exige:

```text
A[i,j] == A[j,i]
```

La igualdad es la comparación IEEE ordinaria del tipo concreto. No es igualdad
bitwise:

- `+0 == -0` es `true`, por lo que signos de cero opuestos son simétricos;
- dos valores finitos deben comparar exactamente iguales;
- NaN no compara igual ni siquiera consigo mismo y no puede pertenecer al
  dominio;
- no hay epsilon absoluto, relativo, ULP ni escalado escondido.

Antes de comparar cada celda, el mismo pase valida que sea finita. Para un
valor `x: T`, V1 puede expresar la prueba sin capability nueva como:

```text
(x - x) == 0
```

Esto es `true` para todo valor IEEE finito, incluidos ambos ceros y
subnormales, y `false` para NaN y ambos infinitos. La implementación futura
debe leer y validar cada diagonal una vez y, para cada par fuera de diagonal,
validar ambos valores antes de compararlos. Un no finito produce
`NotPositiveDefiniteException`; una pareja finita desigual produce
`NotSymmetricMatrixException`.

El orden público de validación es:

1. `shapeGuard(rows(A) == columns(A));`
2. pase completo de finitud y simetría, sin mutación;
3. factorización y chequeo de cada diagonal calculada.

Dentro del pase 2 el recorrido normativo es por filas crecientes y, en cada
fila, columnas crecientes: diagonal `i,i` y luego pares de esa fila con
`j < i`. Para un input que tenga más de un defecto, gana el primer defecto
observado por ese recorrido. La clasificación de no finito antes que igualdad
evita que un NaN sea diagnosticado accidentalmente como mera asimetría.

El pase cuesta `O(n²)` tiempo, no asigna y no queda oculto detrás de un nombre
“unchecked”. El costo es intencional: `cholesky` es la entrada checked y
fail-fast. Una futura API trusted/unchecked o una variante con tolerancia debe
tener nombre y contrato separados; no forma parte de V1.

### Simetría producida por floating point

Una matriz matemáticamente simétrica construida por dos rutas flotantes
distintas puede contener `A[i,j] != A[j,i]` por redondeo. V1 la rechaza. El
caller debe construir un solo triángulo y reflejarlo exactamente, o
simetrizar/materializar explícitamente según la política numérica de su
aplicación. La library no puede escoger una tolerancia universal sin conocer
escala, unidades y error esperado.

## 6. Detección de positive definiteness

Para cada diagonal `i`, después de restar los productos en el orden de §9, se
obtiene el pivot calculado `d`. Se acepta sólo si ambas condiciones son ciertas:

```text
(d - d) == 0
d > 0
```

La primera exige finitud y la segunda positividad estricta bajo comparación
IEEE. La implementación debe comprobarlas antes de invocar `sqrt(d)`. Si
cualquiera falla, lanza `NotPositiveDefiniteException`.

La tabla normativa es:

| `d` calculado | resultado |
|---|---|
| finito y `d > +0` | aceptar y evaluar `sqrt(d)` |
| `+0` o `-0` | `NotPositiveDefiniteException` |
| finito negativo | `NotPositiveDefiniteException` |
| NaN | `NotPositiveDefiniteException` |
| `+Inf` o `-Inf` | `NotPositiveDefiniteException` |
| subnormal positivo | aceptar; `sqrt` conserva semántica concreta |
| subnormal negativo | `NotPositiveDefiniteException` |

Así `sqrt` nunca es el detector accidental de un pivot inválido. El chequeo
también captura NaN o infinito producido por overflow, underflow o cancelación
en la acumulación, aunque todos los elementos de entrada fueran finitos.

Los valores off-diagonal se calculan mediante división IEEE. No hay un check
finite separado después de cada división: si una operación genera no finito,
éste participa en la diagonal de la misma fila y el chequeo obligatorio de `d`
falla antes de completar esa fila. No se devuelve jamás un factor con un
elemento no finito producido silenciosamente.

## 7. Modelo de errores

Los tres fallos tienen identidades distintas:

| condición | mecanismo |
|---|---|
| `rows(A) != columns(A)` | `shapeGuard` → trap `ShapeMismatch` |
| entrada finita pero no simétrica exacta | `NotSymmetricMatrixException` |
| valor no finito o pivot calculado no finito/no positivo | `NotPositiveDefiniteException` |

`SingularMatrixException` no se reutiliza: una matriz semidefinida singular es
sólo un subconjunto de los rechazos, y una matriz indefinida no es
necesariamente singular. Separar no-simetría de no-positive-definiteness da un
diagnóstico accionable sin introducir payload, `Option` ni `Result`, que no son
la convención vigente del package.

Ambas clases nuevas son públicas, nominales, sin fields y con constructor
vacío, igual que `SingularMatrixException`. Son excepciones ordinarias: hacen
unwind y pueden capturarse. `ShapeMismatch` conserva su semántica abortiva y no
se transforma en Exception.

Los checks se ejecutan antes de indexar fuera del dominio o llamar `sqrt` sobre
un valor rechazado. En cualquier throw, el owner consumido `A` y su backing se
liberan exactamente una vez por unwind; no se publica el workspace parcial.

## 8. Zero shape

`cholesky(Matrix<T> 0×0)` tiene éxito. Devuelve exactamente:

```text
Cholesky<T> { L: Matrix<T> 0×0 }
```

La metadata `0×0` se conserva, los pases y loops son vacíos, y el owner vacío
de entrada se mueve al field `L`. No se asigna backing, no se lanza excepción y
no se sintetiza una matriz identidad distinta. La reconstrucción vacía y la
triangularidad son válidas por vacuidad.

No existen otros zero shapes admisibles para esta API square: `0×n` y `m×0`
con el otro extent no cero fallan en el primer `shapeGuard`.

## 9. Algoritmo normativo V1

Se elige Cholesky clásico lower, unblocked, row-oriented en forma dot-product,
usando `A` como workspace `L`. Con índices públicos 1-based:

```text
for i = 1..n:
    for j = 1..i:
        value = A[i,j]
        for k = 1..j-1:
            value = value - A[i,k] * A[j,k]

        if i == j:
            require finite(value) and value > 0
            A[i,i] = sqrt(value)
        else:
            A[i,j] = value / A[j,j]

for i = 1..n:
    for j = i+1..n:
        A[i,j] = 0
```

En el loop interno, `A[i,k]` y `A[j,k]` ya pertenecen a columnas calculadas de
`L`. El valor original `A[i,j]` todavía no fue sobrescrito. El triángulo upper
permanece intacto durante el cálculo y se limpia sólo tras completar con éxito.

La forma dot-product se elige por claridad, determinismo del orden de suma y
uso directo de un solo workspace. Una forma outer-product también podría
reciclar la matriz, pero mutaría una trailing submatrix completa y hace menos
local la correspondencia entre pivot rechazado y entrada. Un algoritmo blocked
puede aprovechar BLAS-3, pero exige kernels y tuning inexistentes y no mejora
el contrato V1. Una optimización blocked futura puede conservar exactamente la
API y materializar el mismo `L`.

No se usa pivoting. Pivoted Cholesky y `LDL^T` tienen dominios, resultados y
aplicaciones diferentes.

## 10. Ownership, storage y aggregate

`cholesky(Matrix<T> A)` consume `A`. El caller que necesite preservar la matriz
debe entregar explícitamente otra Matrix owning; V1 no acepta `MatrixView` ni
hace una copia escondida.

Durante la factorización:

- el lower triangle y la diagonal del backing se reemplazan por `L`;
- el upper triangle conserva temporalmente el input sólo porque ya pasó el
  chequeo de simetría;
- al éxito, cada celda upper se escribe como `T zero = 0`.

El resultado público es por tanto una Matrix triangular ordinaria y completa:
fuera del triángulo inferior contiene ceros observables, no bytes privados,
valores indeterminados ni una copia sorprendente del input.

El aggregate mantiene constraint representacional:

```aether
struct Cholesky<T: Storable> {
    Matrix<T> L;
}
```

No se cambia a `T: IEEEFloat`: igual que `LU<T>` y `QR<T>`, almacenar/mover el
factor sólo necesita `Storable`; las operaciones que lo construyan o consuman
declararán su dominio. Esta separación también deja espacio a una futura
`Cholesky<Complex<R>>` sin afirmar que `Complex<R>` satisface `IEEEFloat`.

## 11. API, inferencia y naming

La única función nueva es:

```aether
Cholesky<T> cholesky<T: IEEEFloat>(Matrix<T> A);
```

Ejemplos admitidos conceptualmente:

```aether
Cholesky<float64> f64 = linearAlgebra.cholesky(A64);
var f32 = linearAlgebra.cholesky(A32);
var explicit = linearAlgebra.cholesky<float32>(A32);
```

El argumento determina `T` antes de borrow adaptation, igual que `lu` y `qr`.
No se requiere expected-result inference y no existe ambigüedad por precisión.

Los spellings cerrados son `cholesky`, `Cholesky<T>` y `L`. No se exponen
abreviaturas como `chol`, nombres de algoritmo ni sufijos de precisión.

## 12. Capabilities escalares

El kernel real usa exactamente estas familias:

| capability | uso |
|---|---|
| `Zero` | cero tipado, finitud y limpieza upper |
| `Sub` | `value - product` y `x - x` para finitud |
| `Mul` | productos dot |
| `Div` | entradas lower fuera de diagonal |
| `Equal` | finitud e igualdad simétrica exacta |
| `Order` | `d > zero` |
| `Sqrt` | diagonal positiva |

No necesita `One`, `Add`, `Negate` ni `Abs` con la formulación normativa. La
API, sin embargo, declara sólo `T: IEEEFloat`, como LU, solve, det y QR. No
publica la expansión de capabilities ni una conjunción accidental que admita
tipos fuera del dominio IEEE cerrado.

## 13. Semántica numérica IEEE

La implementación futura debe preservar literalmente el orden de §9:

- `value` comienza en `A[i,j]`;
- `k` aumenta de `1` a `j-1`;
- cada paso evalúa un producto y una resta en orden source;
- no se permite reassociation, reducción paralela, fast-math, FMA contractual
  ni acumulador promovido a otra precisión;
- `sqrt(T)` es el Core genérico que monomorfiza a la operación concreta de
  `float32` o `float64` y devuelve el mismo tipo.

Signed zero sigue las operaciones IEEE. En el input, `+0` y `-0` comparan
iguales para simetría. Como pivot calculado, ambos fallan `d > +0`. Los ceros
escritos en el upper son el literal algebraico `0`, es decir `+0` concreto.

NaN e infinitos de entrada se rechazan en el pase previo. Un NaN o infinito
intermedio se rechaza en el check diagonal. Un subnormal finito conserva su
valor y puede aceptarse si es positivo; no se habilita flush-to-zero. Overflow,
underflow y redondeo son los del tipo concreto. Por ello una matriz SPD en
aritmética real puede ser rechazada si el algoritmo concreto obtiene un pivot
cero, negativo o no finito; V1 no promete exactitud simbólica ni estabilidad
perfecta.

Para inputs SPD razonablemente condicionados, Cholesky sin pivoting es el
algoritmo estándar y debe producir un residual pequeño. La API no publica una
tolerancia universal para definir “pequeño”; las pruebas usan tolerancias
explícitas por precisión y caso.

## 14. Evolución a Complex

V1 no modifica `IEEEFloat`, `RealOps` ni `Order`, y no inventa orden para
`Complex`. Una extensión compleja necesitará un diseño separado con:

- `A = L L^H`, donde `H` es transpose conjugada;
- chequeo de simetría Hermitian, no igualdad transpose simple;
- conjugación en cada producto dot;
- diagonal de `A` real y diagonal de `L` real estrictamente positiva;
- relación explícita entre `Complex<R>` y su tipo real asociado `R` para
  magnitud, comparación y `sqrt` de la diagonal;
- política propia de exactitud/tolerancia Hermitian y valores no finitos.

El aggregate con un solo `Matrix<T> L` ya es suficiente para esa representación,
pero esta reserva no fija todavía la firma ni capabilities complejas.

## 15. Evolución a solve

Guardar sólo `L` es suficiente para resolver sin reconstruir `A`:

```aether
Vector<T,Column> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Matrix<T> B);
```

El algoritmo futuro hará `L y = b` por forward substitution y
`L^T x = y` por backward substitution. `L^T` se lee por índices invertidos; no
se materializa una transpose. Los overloads validarán que `L` sea square y que
el RHS tenga filas/dimensión compatible. Recibirán el factor por `ref` shared,
permitiendo reutilizarlo. No se implementan en este milestone.

No hace falta guardar `A`, `L^T`, permutation ni signo: SPD no requiere
pivoting y la diagonal positiva fija el factor de manera única en aritmética
exacta.

## 16. Evolución a determinant

Un overload futuro puede calcular:

```text
det(A) = product(diag(L))^2
```

leyendo `ref Cholesky<T>` sin allocation. Para reducir overflow evitable podría
evaluar el producto y cuadrarlo o acumular productos de `L[i,i] * L[i,i]`; esa
decisión numérica requiere su propio milestone. El factor actual contiene toda
la información necesaria y el caso `0×0` debe conservar el producto vacío
igual a uno. No se agrega `det` ahora.

## 17. Lowering HIR, MIR y SSA

Cholesky será source ordinario dentro del package `linearAlgebra`. No se agregan:

- HIR operations o recipes específicas de Cholesky;
- compiler intrinsics, allowlists o reconocimiento por nombre del package;
- MIR/SSA opcodes;
- helpers backend, runtime numeric dispatch o ABI nuevo.

El source usa `rows`, `columns`, indexing/assignment de Matrix, `shapeGuard`,
exceptions nominales, control flow ordinario, literals algebraicos y `sqrt`
Core genérico. El HIR paramétrico contiene las operations capability de §12.
Monomorphization sustituye `T` y reifica `sqrt`; MIR y SSA ven sólo operaciones
concretas `float32` o `float64`. LLVM debe emitir instancias y calls directas a
la operación sqrt concreta, sin `TypeId`, witnesses, vtables, boxing ni calls
indirectas.

## 18. Cost model normativo

Para `A : n×n`:

- factorización: `n(n+1)(n-1)/6` productos y restas en los dot products,
  `n(n-1)/2` divisiones y `n` square roots; tiempo `O(n³)`;
- validación de finitud/simetría: `O(n²)` reads/comparaciones;
- limpieza upper: `n(n-1)/2` stores, `O(n²)`;
- memoria auxiliar escalar: `O(1)`;
- Matrix/Vector auxiliares: cero;
- ruta de éxito: exactamente cero allocations propias de Matrix, Vector,
  backing o cualquier otro owner auxiliar, tanto para `n > 0` como para
  `n == 0`;
- owner resultante: el mismo backing que entró en `A`; una Matrix no vacía fue
  asignada por quien construyó la entrada, no por `cholesky`;
- éxito: el backing sale una vez dentro de `Cholesky.L`;
- excepción nominal: se construye exactamente un owner ordinario de la clase
  Exception lanzada, sin payload ni backing numérico; unwind libera una vez
  tanto ese objeto al terminar su manejo como el owner Matrix consumido;
- shape trap: conserva el modelo abortivo general de `shapeGuard`, sin promesa
  de cleanup por unwind.

No se crea transpose, copia simétrica, vector temporal ni Matrix packed
adicional. Los conteos de operaciones describen el kernel clásico; checks y
branches agregan `O(n²)` sin cambiar la clase cúbica.

## 19. Qualification del milestone de implementación futuro

### Casos válidos

- `0×0`, con shape preservado y cero allocations;
- `1×1` positiva;
- identidad y diagonal positiva;
- SPD dense conocida con factor esperado;
- SPD dense reconstruida mediante `L * transpose_view(L)`;
- SPD ill-conditioned razonable que conserve pivots concretos positivos;
- `float32` y `float64`, con inferencia y type argument explícito.

Se comprobarán shape `n×n`, upper exactamente `+0`, diagonal positiva y finita,
y `A ≈ L*L^T` con tolerancias publicadas por precisión/caso. Cuando exista un
factor conocido, se comparará también `L` respetando su diagonal positiva.

### Casos inválidos

- rectangular `m×n`, incluidos `0×n`/`m×0`: `ShapeMismatch` antes de mutar;
- simétrica semidefinida, singular PSD e indefinida;
- diagonal negativa, `+0` y `-0` relevantes;
- finita no simétrica, incluida diferencia de un ULP;
- off-diagonal `+0/-0`, que sí debe pasar simetría;
- NaN en diagonal o fuera de diagonal;
- `+Inf` y `-Inf` en diagonal o fuera de diagonal;
- overflow/underflow intermedio que invalide un pivot;
- subnormales positivos válidos y subnormales negativos inválidos.

Se verificará la clase exacta de fallo y la precedencia shape → no finito →
asimetría → pivot no positivo.

### Estructura, ownership e IR

La calificación incluirá:

- consumo de la entrada y reutilización del mismo backing como `L`;
- cero allocations internas y ausencia de clones/owners temporales;
- cleanup de la entrada en cada throw instrumentado;
- ejecución O0 y O2 con los mismos resultados/errores contractuales;
- una sola declaración y body genéricos, sin kernels por precisión;
- HIR paramétrico con sólo las capabilities de §12;
- instancias HIR concretas y MIR/SSA sin nodos capability residuales;
- símbolos/código concreto separado para `float32`/`float64`, calls directas a
  `sqrtf`/`sqrt` y ausencia de dispatch runtime;
- consumo desde el package publicado y consumer independiente;
- regresión completa de LU, det, solve, QR y constructors.

## 20. Alternativas rechazadas

| alternativa | razón de rechazo V1 |
|---|---|
| devolver `Matrix<T>` | pierde identidad de factor y receptor futuro de solve/det |
| devolver `{L, LT}` | duplica storage y puede leerse transpuesto sin materializar |
| packed privado con upper indeterminado | sorprendente si se expone Matrix públicamente |
| producir upper o selector lower/upper | superficie y qualification duplicadas |
| asumir simetría | puede aceptar/ignorar silenciosamente medio input |
| tolerancia fija | depende de escala y es un contrato numérico arbitrario |
| API trusted en V1 | agrega superficie antes de medir necesidad/performance |
| `SingularMatrixException` | no representa matrices indefinidas o no finitas |
| una excepción SPD única | oculta el diagnóstico distinto de asimetría finita |
| `Option`/`Result` | diverge del error model actual sin ventaja compensatoria |
| outer-product | mutación global menos local para el primer vertical |
| blocked/BLAS | infraestructura y tuning fuera de scope |
| copiar `A` | contradice el contrato owning y agrega una Matrix `O(n²)` |

## 21. Fuera de scope

Este milestone no implementa Cholesky ni modifica código. También quedan fuera:

- `Complex`, Hermitian Cholesky y nuevas capabilities;
- pivoted o incomplete Cholesky;
- `LDL^T`, sparse y blocked BLAS/LAPACK;
- solve Vector/Matrix por Cholesky;
- determinant, inverse y log-determinant por Cholesky;
- rank-one update/downdate;
- API upper, tolerante, configurable, trusted o unchecked;
- estimación de condición, rank o recuperación numérica.

## 22. Criterio de cierre

La arquitectura queda cerrada por este documento y
[LINEAR-ALGEBRA-CHOLESKY-ARCH-1-REPORT](LINEAR_ALGEBRA_CHOLESKY_ARCH_1_REPORT.md).
El próximo milestone puede implementar exactamente esta superficie sin cambios
al compilador ni decisiones pendientes sobre dominio, storage o errores.
