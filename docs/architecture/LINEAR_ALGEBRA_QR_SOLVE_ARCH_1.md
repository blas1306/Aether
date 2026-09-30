# LINEAR-ALGEBRA-QR-SOLVE-ARCH-1 — solve reutilizable desde QR

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-30.

Este milestone es exclusivamente documental. No modifica
`linearAlgebra/src/lib.ae`, consumer, tests, compiler, runtime ni standard
library. La implementación y calificación pertenecen a un milestone posterior.

Autoridad relacionada:

- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-SOLVE-V1](LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_V1_REPORT.md).

## 1. Decisión resumida

Se agregarán exactamente estos dos overloads públicos y genéricos:

```aether
Vector<T,Column> solve<T: IEEEFloat>(
    ref QR<T> factor,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref QR<T> factor,
    ref Matrix<T> B);
```

Para `Q : m×m`, `R : m×n` y un factor legítimo `A = Q R`, la operación admite
solamente `m >= n` y rango columna completo. Si `m == n`, resuelve `A x = b`.
Si `m > n`, devuelve la solución única de mínimos cuadrados. En ambos casos el
resultado tiene dimensión lógica `n`; para `B : m×q`, devuelve `X : n×q`.

La operación calcula únicamente las primeras `n` componentes o filas de
`Q^T rhs` y resuelve el sistema triangular efectivo
`R1 x = (Q^T rhs)[1:n]`, donde `R1 = R[1:n,1:n]`. No materializa `Q^T`, no
reconstruye `A`, no calcula ecuaciones normales y no produce un residual.

Factor y RHS son préstamos shared. El resultado owning es también el único
workspace. Antes de crearlo, después de todos los guards estructurales, se
recorre la diagonal de `R1` en orden creciente. Un pivot exactamente cero
lanza `RankDeficientMatrixException`.

## 2. Superficie pública y nombre

El nombre normativo es `solve`, no `leastSquares`. El tipo nominal del primer
argumento distingue las rutas desde `QR<T>`, `LU<T>`, `Cholesky<T>` y
`Matrix<T>`; el segundo argumento distingue Vector column y Matrix. No se
agrega selector, enum de método, flag de shape ni dispatch por tipo de retorno.

Usar `solve` también cuando `m > n` es deliberado. Un factor QR rectangular
tall determina naturalmente el problema full-column-rank cuya solución única
es la de mínimos cuadrados. El contrato y la documentación de este overload
explicitan esa interpretación; un segundo alias `leastSquares` sólo duplicaría
la superficie y dejaría dos nombres para la misma operación. No se ofrece ese
alias en V1.

`ref` forma parte de ambas firmas. BORROW-ERGONOMICS permite calls ordinarias
sobre owners:

```aether
var factor = qr(A);
var x1 = solve(factor, b1);
var x2 = solve(factor, b2);
var X = solve(factor, B);
println(factor.Q);
println(factor.R);
```

Las formas explícitas con `&` son equivalentes. La inferencia de `T` sigue la
política vigente para parámetros shared genéricos; también se admite el
argumento explícito `solve<float32>(factor,b)`. No hay wrappers por precisión,
default de precisión ni variantes `InPlace`: consumir un factor consultado no
evita el workspace de resultado ni ofrece un backing útil para reciclar.

La API vectorial acepta únicamente `Vector<T,Column>`. No se agregan overloads
para `Vector<T,Row>`, views, precisiones mixtas ni tipos complejos.

## 3. Dominio y semántica matemática

Para un factor legítimo:

```text
Q : m×m
R : m×n
A = Q R
Q^T Q = I
m >= n
R1 = R[1:n,1:n] triangular superior e invertible
```

la ruta Vector recibe `b : m` y devuelve `x : n`.

- Si `m == n`, `x` es la solución del sistema square `A x = b`, sujeto al
  redondeo del algoritmo concreto.
- Si `m > n`, `x` es la solución única
  `argmin_x ||A x - b||_2`.

La ruta Matrix recibe `B : m×q` y devuelve `X : n×q`. Cada columna `X[:,c]`
es, de manera independiente, la solución square o least-squares determinada
por `B[:,c]`.

Para el caso tall, escribir `Q^T b = [g; h]` con `g : n` da
`||A x-b||_2 = ||R1 x-g||_2` combinado con un término independiente de `x`.
Resolver `R1 x=g` produce por ello el minimizador único. Esta justificación no
autoriza materializar `Q^T`, calcular `h`, el residual, `A^T A` ni `A^T b`.

El dominio V1 excluye `m < n`. No se intenta elegir variables libres ni
producir una solución minimum-norm. Ese caso falla por `shapeGuard` como una
violación estructural del dominio del overload, antes de cualquier scan o
allocation.

## 4. Guards estructurales y precedencia

El overload Vector ejecuta exactamente estos guards, en este orden:

```text
1. shapeGuard(rows(factor.Q) == columns(factor.Q));
2. shapeGuard(rows(factor.R) == rows(factor.Q));
3. shapeGuard(rows(factor.R) >= columns(factor.R));
4. shapeGuard(dimension(b) == rows(factor.Q));
```

El overload Matrix ejecuta exactamente:

```text
1. shapeGuard(rows(factor.Q) == columns(factor.Q));
2. shapeGuard(rows(factor.R) == rows(factor.Q));
3. shapeGuard(rows(factor.R) >= columns(factor.R));
4. shapeGuard(rows(B) == rows(factor.Q));
```

Las consultas de extents necesarias para evaluar esos guards son las únicas
observaciones previas permitidas. Los cuatro guards ocurren antes de:

- allocation o construcción del resultado;
- indexación elemental de `Q`, `R` o RHS;
- aritmética escalar;
- scan de rango sobre la diagonal.

Un guard falso produce el trap abortivo `ShapeMismatch`, de acuerdo con la
semántica general de `shapeGuard`; no se convierte en una Exception capturable.
La primera relación falsa en el orden anterior determina la precedencia.

No hacen falta otras relaciones de extents. Los guards 1 y 2 establecen que el
número de columnas de `Q` coincide con las filas de `R`; el guard 3 garantiza
que existen las primeras `n = columns(R)` filas y entradas diagonales de `R`,
y el guard 4 hace válidas todas las lecturas del RHS. El tipo `QR<T>` ya fija
el mismo `T` para ambas matrices.

Sólo después de los cuatro guards se fijan `m = rows(factor.Q)`,
`n = columns(factor.R)` y, para Matrix, `q = columns(B)` para el resto del
algoritmo.

## 5. Rango columna y excepción nominal

Se agrega exactamente esta excepción pública al package:

```aether
public class RankDeficientMatrixException : Exception {
    public init() {}
}
```

Representa que el factor QR no tiene el rango columna completo necesario para
producir la solución única prometida por estos overloads. El spelling incluye
`Matrix` y conserva la familia nominal vigente
`SingularMatrixException`, `NotSymmetricMatrixException` y
`NotPositiveDefiniteException`.

No se reutiliza `SingularMatrixException`. Una Matrix tall no es singular en
el sentido square usual; puede ser rank-deficient y carecer de una solución
least-squares única. Reutilizarla haría que el significado dependiera de que
`A` fuese square aunque el mismo overload admite `m > n`.

`RankDeficientException` se rechaza porque omite la entidad diagnosticada y no
sigue el spelling de las excepciones numéricas del package.
`InvalidQRFactorException` también se rechaza: el solve no valida en general
la canonicidad del aggregate y un pivot cero puede provenir legítimamente de
`qr(A)` para una entrada rank-deficient. El diagnóstico es insuficiencia de
rango para esta operación, no procedencia inválida.

No se cambian la declaración ni los sitios de throw de
`SingularMatrixException`; la ruta LU conserva su excepción histórica.

## 6. Política exact-zero y orden del scan

Después de que pasen todos los guards y antes de crear el resultado se ejecuta
exactamente:

```text
zero = 0
for i = 1..n creciente:
    if R[i,i] == zero:
        throw RankDeficientMatrixException()
```

La comparación es igualdad IEEE exacta. `+0` y `-0` comparan igual a cero y
lanzan. No hay epsilon oculto, tolerancia, `rcond`, norma, escala relativa,
heurística de rango ni pivoting. Un valor subnormal no cero se acepta. NaN no
compara igual a cero; `+Inf`, `-Inf` y cualquier valor finito no cero también
pasan el scan y participan luego en la aritmética IEEE normal.

El primer pivot cero en orden creciente produce el throw. No se indexa ningún
otro dato del factor o RHS antes de este scan; las únicas lecturas elementales
son `R[i,i]`. En particular, no se empieza a calcular `Q^T rhs` hasta haber
comprobado toda la diagonal efectiva.

Esta política diagnostica invertibilidad triangular concreta por pivots
exactos, no rango numérico aproximado. Un factor matemáticamente mal
condicionado o cuyo rank deficiency se haya redondeado a pivots pequeños pero
no cero continúa por el algoritmo. V1 no promete rank revelation.

El scan se ejecuta aunque el RHS matricial tenga `q == 0`. Por tanto un factor
con pivot cero y `B : m×0` lanza `RankDeficientMatrixException`; la
solvabilidad del factor se comprueba independientemente de cuántas columnas
RHS existan. El throw precede toda allocation de backing de resultado.

## 7. Aggregate representacional y factor manual

`QR<T>` mantiene su forma representacional vigente:

```aether
struct QR<T: Storable> {
    Matrix<T> Q;
    Matrix<T> R;
}
```

Pasar los guards y el scan exact-zero no certifica un QR canónico. La
legitimidad matemática `A = Q R`, ortogonalidad de `Q`, triangularidad de `R`
y procedencia Householder son precondiciones del caller cuando se espera la
semántica de §3. `solve` no revalida:

- `Q^T Q == I`;
- triangularidad o ceros bajo la diagonal de `R`;
- existencia de una Matrix `A` tal que el aggregate provenga de `qr(A)`;
- finitud de `Q` o `R`;
- signos, escalas o forma Householder;
- reconstrucción `A == Q R`.

Después de shapes y scan, un factor manual ejecuta literalmente los algoritmos
de §§8–9:

- una `Q` arbitraria participa mediante `Q[k,i]` para `k=1..m` e `i=1..n`;
- sólo el triángulo superior `R[i,j]` con `1<=i<=j<=n` es leído por la
  sustitución; celdas bajo diagonal y filas `n+1..m` se ignoran;
- off-diagonales superiores arbitrarias participan tal cual;
- NaN e infinitos de `Q` o del triángulo leído se propagan conforme a IEEE;
- una diagonal NaN o infinita no es cero para el scan y participa en `Div`;
- una diagonal `+0` o `-0` siempre lanza antes de usar `Q` o el RHS.

No se crea ni lanza `InvalidQRFactorException`. Fuera de la precondición
legítima no se promete residual respecto de una entrada original, optimalidad
least-squares, ortogonalidad ni finitud; sí se prometen guards, exact-zero,
orden operacional, allocations y ownership de esta arquitectura.

El scan de pivots no contradice esta política estrecha: dividir por un pivot
exactamente cero impide la sustitución que define la operación, mientras que
revalidar las demás propiedades sería una certificación distinta, costosa e
incompleta.

## 8. Algoritmo Vector normativo

Después de guards y scan se crea exactamente un `Vector<T,Column> w` de
longitud `n`, inicializado con el cero concreto. Es a la vez el único workspace
y el resultado.

La primera etapa calcula sólo las primeras `n` componentes de `Q^T b`:

```text
for i = 1..n:
    value = 0
    for k = 1..m:
        product = Q[k,i] * b[k]
        value = value + product
    w[i] = value
```

No se calcula ninguna componente `i>n` y no se materializa `Q^T`.

La sustitución hacia atrás sobre `R1` sobrescribe el mismo backing:

```text
for i = n..1:
    value = w[i]
    for j = i+1..n:
        product = R[i,j] * w[j]
        value = value - product
    w[i] = value / R[i,i]
```

Cuando se procesa `i`, las posiciones `w[j]` con `j>i` ya contienen `x[j]`.
El loop descendente debe usar el patrón seguro vigente para `usize`, con salida
explícita en `i == 1`, y debe quedar vacío para `n == 0`.

No se crea un segundo Vector, no se copia el RHS, no se copia `R` y no se
delega a un helper dot-product o triangular que cambie el orden contractual.

## 9. Algoritmo Matrix normativo

Después de guards y scan se crea exactamente una `Matrix<T> W` de shape
`n×q`, inicializada con el cero concreto. No se crea un Vector por columna.

La etapa parcial `Q^T B` usa exactamente el orden `i/c/k`:

```text
for i = 1..n:
    for c = 1..q:
        value = 0
        for k = 1..m:
            product = Q[k,i] * B[k,c]
            value = value + product
        W[i,c] = value
```

La sustitución usa exactamente el orden `i/c/j`, con `i` descendente, `c`
creciente y `j` creciente:

```text
for i = n..1:
    for c = 1..q:
        value = W[i,c]
        for j = i+1..n:
            product = R[i,j] * W[j,c]
            value = value - product
        W[i,c] = value / R[i,i]
```

Cada celda completa su acumulación y división antes de avanzar a la próxima
columna. No se admite transformar los loops a `i/k/c` o `i/j/c`, aunque otra
organización pudiera mejorar locality. El orden elegido coincide por columna
con el algoritmo Vector sin invocarlo `q` veces.

## 10. Orden numérico IEEE

Para cada componente de `Q^T rhs`, el orden contractual es:

1. inicializar `value` con el cero concreto;
2. recorrer `k=1..m` estrictamente creciente;
3. evaluar primero `Q[k,i] * rhs[k]`;
4. evaluar después `value + product`;
5. almacenar una sola vez al terminar la componente.

Para cada componente de la sustitución:

1. cargar el valor actual del workspace;
2. recorrer `j=i+1..n` estrictamente creciente;
3. evaluar primero `R[i,j] * workspace[j]`;
4. evaluar después `value - product`;
5. dividir exactamente una vez por `R[i,i]` después de todas las restas;
6. almacenar antes de avanzar.

No hay reassociation, fast-math, FMA contractual, reduction tree, acumulador
promovido, compensación, vector reduction ni paralelización que altere este
orden. Overflow, underflow, signed zero, subnormales, NaN e infinitos siguen
las operaciones IEEE del tipo concreto.

## 11. Shapes cero

Las reglas exactas son:

| `Q` | `R` | RHS | resultado |
|---|---|---|---|
| `m×m` | `m×0` | Vector length `m` | Vector length `0` |
| `m×m` | `m×0` | Matrix `m×q` | Matrix `0×q`, preserva `q` |
| `0×0` | `0×0` | Vector length `0` | Vector length `0` |
| `0×0` | `0×0` | Matrix `0×q` | Matrix `0×q`, preserva `q` |
| `m×m` | `m×n`, `n>0` | Matrix `m×0` | Matrix `n×0`, preserva `n` |
| shapes incompatibles | cualquiera | cualquiera | `ShapeMismatch` por precedencia de §4 |

`n == 0` es full column rank por vacuidad. El scan no tiene pivots, los loops
de `i` quedan vacíos, no hay aritmética de `Q^T rhs` y el resultado no tiene
backing. Esto vale también para `m == n == 0`.

Con `q == 0` y `n>0`, el scan de los `n` pivots sí se ejecuta. Si todos son no
cero, los loops por columnas no hacen aritmética y se devuelve `n×0` sin
backing. Si alguno es cero, se lanza la excepción nominal antes de construir el
resultado. Los dos extents lógicos se preservan aun cuando el backing sea null.

## 12. Ownership, alias y lifetime

`factor` y RHS se prestan shared durante toda la call:

- no se mueve, consume, clona ni muta `factor`;
- no se mueve, consume, clona ni muta `factor.Q` o `factor.R`;
- no se mueve, consume, clona ni muta `b` o `B`;
- ningún préstamo escapa en el resultado;
- el resultado es owning e independiente;
- no existe alias de backing entre resultado, matrices del factor y RHS.

El mismo factor puede resolver secuencialmente cualquier combinación de RHS
Vector y Matrix compatibles. Después de retorno normal o de la Exception
capturable de rango, factor y RHS permanecen utilizables. Los traps de
`shapeGuard` conservan su semántica abortiva general y no prometen unwind.

No hay variante `InPlace`: ni `Q`, ni `R`, ni el RHS pueden alojar directamente
un resultado de shape `n`/`n×q` sin destruir inputs compartidos o cambiar la
promesa de reutilización.

## 13. Allocations y coste

Para Vector:

- tiempo: `O(m*n + n²)`;
- storage resultante: `n` elementos;
- exactamente un backing si y sólo si `n > 0`;
- cero backings si `n == 0`.

Para Matrix:

- tiempo: `O(m*n*q + n²*q)` más el scan `O(n)`;
- storage resultante: `n*q` elementos;
- exactamente un backing si y sólo si `n*q > 0`;
- cero backings si `n*q == 0`.

El scan `O(n)` también forma parte de la ruta Vector; se menciona
separadamente en Matrix para destacar que no desaparece con `q==0`.

Todo fallo estructural o de rango ocurre antes de crear el workspace y por
tanto crea cero backings de resultado. El objeto Exception sigue la semántica
normal de exceptions y no cuenta como backing numérico.

No se asignan transpose de `Q`, copia de `R`, copia del factor, copia del RHS,
residual, Matrix auxiliar, segundo Vector, Vector por columna, normal equations
ni tabla de pivots. Los acumuladores e índices son escalares `O(1)`. El fill
inicial del único resultado no autoriza un segundo backing.

## 14. Capabilities y frontera genérica

Los bodies usan exactamente estas familias escalares sobre `T`:

| capability | uso |
|---|---|
| `Zero` | cero del scan e inicialización/acumulación del resultado |
| `Equal` | comparación exacta de `R[i,i]` con cero |
| `Add` | acumulación ordenada de `Q^T rhs` |
| `Mul` | productos de `Q`/RHS y `R`/solución previa |
| `Sub` | acumulación de sustitución hacia atrás |
| `Div` | división final por pivot de `R1` |

No necesitan `One`, `Order`, `Sqrt`, `Abs` ni `Negate`. La frontera pública
permanece `T: IEEEFloat`, no una lista explícita de capabilities ni un dominio
numérico más amplio. `IEEEFloat` mantiene selladas las instancias a `float32`
y `float64`.

## 15. Relación con otros solve

No se modifica ningún overload desde `Matrix<T>`, `LU<T>` o `Cholesky<T>`.
Tampoco cambia `SingularMatrixException`. Los tipos nominales hacen coexistir
las cuatro familias sin selector:

```text
solve(ref Matrix<T>,    ref RHS)
solve(ref LU<T>,        ref RHS)
solve(ref Cholesky<T>,  ref RHS)
solve(ref QR<T>,        ref RHS)
```

Para `m==n` y una Matrix invertible, QR solve debe producir una solución
compatible dentro de tolerancia con LU solve y con `A*x≈b`; no se exige
igualdad bitwise entre algoritmos porque factorización y orden aritmético
difieren.

No se agrega una ruta automática desde Matrix que seleccione QR. El caller
elige explícitamente al crear/pasar el factor nominal y puede amortizarlo entre
varios RHS.

## 16. HIR, MIR, SSA y backend

La implementación futura vive enteramente como source ordinario de
`linearAlgebra`. No se agregan:

- opcode HIR/MIR/SSA de QR solve;
- intrinsic de transpose, dot product o triangular solve;
- builtin o runtime helper especializado;
- reconocimiento nominal de `QR` o del package;
- dispatch por `TypeId`, witness, vtable, boxing o llamada numérica indirecta.

HIR debe mostrar shared borrows de factor/RHS, los cuatro guards en orden, el
scan `Equal`, una única construcción de resultado, loops/indexing ordinarios y
las capabilities de §14. La construcción sucede después del scan. Los
préstamos terminan antes del retorno y el owner nuevo se mueve al caller.

La monomorphization sustituye `T` antes de MIR. MIR y SSA contienen sólo tipos
y operaciones concretas `float32` o `float64`, control flow e indexación, sin
parámetros genéricos ni nodos capability residuales. La implementación no
materializa una operación transpose aunque lea matemáticamente `Q^T`.

## 17. Qualification del milestone futuro

### Square Vector y Matrix

Para `float32` y `float64` se cubrirán:

- `0×0`;
- `1×1`;
- diagonal invertible;
- square dense invertible;
- comparación con `solve(ref LU, rhs)` dentro de tolerancia;
- residual `A*x≈b` y `A*X≈B`;
- Matrix RHS con `q=1` y `q>1`;
- correspondencia por columna entre Matrix `q=1` y Vector;
- reutilización secuencial del factor con Vector y Matrix;
- `Q`, `R` y RHS intactos después de las calls;
- independencia/ausencia de alias del resultado;
- conteos exactos de backing en O0 y O2.

No se exigirá igualdad bitwise contra LU.

### Tall least-squares

Para ambas precisiones se usarán casos `m>n` full-column-rank con solución
conocida:

- sistema overdetermined consistente y residual cero dentro de tolerancia;
- sistema inconsistente con residual no cero;
- Vector RHS y Matrix RHS con varias columnas;
- solución conocida no trivial;
- comprobación independiente de optimalidad
  `A^T(Ax-b)≈0` sólo en tests;
- shape de salida `n` o `n×q` y conservación de `q`.

Los tests pueden formar residual y normal-equation residual como oráculos; el
kernel no incorpora ninguna de esas operaciones.

### Rank deficiency y precedencia

Se cubrirán square y tall:

- pivot `+0`;
- pivot `-0`;
- Matrix rank-deficient factorizada con `qr` cuyo caso elegido produzca pivot
  exacto cero;
- `QR` manual con diagonal cero;
- Vector y Matrix RHS;
- `B : m×0`, que igualmente debe lanzar;
- catch nominal exacto de `RankDeficientMatrixException`;
- cero allocations/backings de resultado antes del throw.

También se fijará que todos los guards estructurales preceden al scan: un
aggregate con shapes inválidas y diagonal observable cero falla primero con
`ShapeMismatch`, sin indexación diagonal. Entre guards, vence la primera
relación falsa de §4.

### Shapes cero

Se cubrirán `m×0`, `0×0`, `0×q` y `n×0`, comprobando ambos extents, ausencia de
backing y ausencia de aritmética RHS. Para `n×0`, se distinguirá éxito con
diagonal no cero de throw con diagonal cero.

### Aggregates manuales no canónicos

Los tests fijarán la ausencia de validación accidental:

- `Q` no ortogonal, cuyo valor se usa literalmente;
- lower de `R` no cero, sin efecto sobre el resultado;
- filas `n+1..m` de `R` arbitrarias, sin efecto;
- off-diagonal superior arbitraria, que sí participa;
- NaN e infinitos en `Q`;
- diagonal NaN, `+Inf` y `-Inf`, que no disparan el scan exact-zero;
- combinaciones manuales cuya propagación IEEE confirme el orden de §§8–10.

La qualification source/IR comprobará que no aparezcan scan de finitud,
ortogonalidad, triangularidad, transpose, copia de factores, helper dot-product
que cambie el orden ni Vector temporal por columna.

### Consumer

El consumer independiente agregará dogfood equivalente a:

```aether
// Square.
var squareFactor = qr(A);
var x = solve(squareFactor, b);

// Tall full-column-rank.
var tallFactor = qr(tallA);
var xls = solve(tallFactor, tallB);
var Xls = solve(tallFactor, tallRhsMatrix);

println(tallFactor.Q);
println(tallFactor.R);
println(xls);
println(Xls);
```

Se ejecutará en O0/O2 y mantendrá verdes constructors, LU, determinant, solve
LU, QR, Cholesky solve y ownership ergonomics.

## 18. Alternativas rechazadas

| alternativa | razón de rechazo |
|---|---|
| `leastSquares(ref QR,...)` | duplica la operación; `solve` documenta square y tall sin dos superficies |
| ofrecer ambos nombres | crea aliases y decisiones de uso sin diferencia semántica |
| admitir `m<n` | requiere política minimum-norm/free variables no disponible en QR de `A` |
| `SingularMatrixException` | no describe correctamente una Matrix tall rank-deficient |
| `RankDeficientException` | no sigue el naming centrado en Matrix del package |
| `InvalidQRFactorException` | el productor QR puede publicar legítimamente rank deficiency y no se valida el factor completo |
| tolerancia/epsilon/rcond | introduce una heurística oculta y decisiones de escala fuera de V1 |
| omitir scan para `q==0` | hace depender la solvabilidad declarada del número de RHS y diverge de LU |
| consumir `QR` | impide reutilización sin ahorrar el workspace resultado |
| materializar `Q^T` | agrega `m²` storage y trabajo innecesario |
| calcular todo `Q^T rhs` | las componentes `n+1..m` no intervienen en la solución |
| segundo workspace para `x` | `Q^T rhs` puede sobrescribirse con backward substitution |
| Vector por columna | agrega owners/allocations y no respeta el kernel Matrix directo |
| normal equations | empeora la formulación numérica y reconstruye trabajo que QR ya resolvió |
| revalidar QR canónico | agrega costo, otra autoridad e invariantes que el aggregate no certifica por tipo |
| selector automático desde Matrix | mezcla elección de algoritmo con este overload nominal reusable |

## 19. Trabajo futuro reservado

Quedan reservados, sin diseñarlos en este milestone:

- minimum-norm para `m<n` mediante una factorización apropiada;
- LQ o QR de `A^T`;
- QR pivoted y rank-revealing;
- tolerancia, `rcond` o política de rango numérico;
- pseudoinverse;
- API que también devuelva residual o su norma;
- representación economy de `Q`;
- representación Householder implícita/packed.

Estas reservas no agregan variantes, metadata ni puntos de extensión a V1.

## 20. Fuera de scope

Este milestone no implementa código. También quedan fuera:

- selección automática LU/Cholesky/QR desde Matrix;
- normal-equations solver;
- underdetermined solve y política de variables libres;
- SVD, pseudoinverse y minimum-norm;
- pivoted QR o rank revelation;
- tolerancias de rango;
- `Complex`;
- BLAS/LAPACK, sparse, GPU o kernels packed;
- solve que sobrescriba factor o RHS.

## 21. Criterio de cierre

La arquitectura queda cerrada por este documento y
[LINEAR-ALGEBRA-QR-SOLVE-ARCH-1-REPORT](LINEAR_ALGEBRA_QR_SOLVE_ARCH_1_REPORT.md).
El próximo milestone puede implementar exactamente los dos overloads y la
excepción nominal sin decisiones pendientes sobre naming, dominio, guards,
rango, loops, zero shapes, allocations, ownership, factors manuales, orden
numérico, lowering o qualification.
