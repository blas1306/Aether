# LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1 — solve reutilizable desde Cholesky

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-29.

Este milestone es exclusivamente documental. No modifica
`linearAlgebra/src/lib.ae`, consumer, tests, compiler, runtime ni standard
library. La implementación y calificación pertenecen a un milestone posterior.

Autoridad relacionada:

- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-V1](LINEAR_ALGEBRA_CHOLESKY_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-SOLVE-V1](LINEAR_ALGEBRA_GENERIC_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1.md);
- [LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_V1_REPORT.md).

## 1. Decisión resumida

Se agregarán exactamente estos dos overloads públicos y genéricos:

```aether
Vector<T,Column> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref Cholesky<T> factor,
    ref Matrix<T> B);
```

Ambos resuelven el sistema representado por `A = L L^T` en dos etapas:

```text
L y   = rhs
L^T x = y
```

El factor y el RHS son préstamos shared. El resultado es un owner nuevo e
independiente que sirve también como único workspace: primero contiene `y` y
después `x`. No se consume ni copia `Cholesky`, no se materializa `L^T` y no
se crea un Vector por columna para el RHS matricial.

El solve valida únicamente las relaciones estructurales de extents. No vuelve
a demostrar que `L` sea un factor Cholesky canónico ni inspecciona por separado
su diagonal. Un `Cholesky<T>` legítimo producido por `cholesky` ya garantiza
square shape, lower triangularidad materializada, upper cero y diagonal finita
estrictamente positiva. La semántica de aggregates forjados manualmente queda
cerrada en §6.

## 2. Superficie, overloads e inferencia

Los overloads coexisten con las rutas actuales desde `ref Matrix<T>` y
`ref LU<T>`. El primer argumento nominal distingue `Cholesky<T>`, `LU<T>` y
`Matrix<T>`; el segundo distingue Vector column y Matrix. No se selecciona un
algoritmo por shape runtime, flag, enum ni tipo de retorno.

`ref` forma parte de ambas declaraciones. BORROW-ERGONOMICS permite calls
ordinarias sobre owners sin escribir `&`:

```aether
var ch = cholesky(A);
var x1 = solve(ch, b1);
var x2 = solve(ch, b2);
println(ch.L);
println(x1);
println(x2);
```

Las formas `solve(&ch,&b1)` y `solve(&ch,&B)` son equivalentes. La resolución
debe inferir `T` desde los tipos exactos de los argumentos antes de materializar
los préstamos, igual que las APIs preserving vigentes. El argumento explícito
`solve<float32>(ch,b)` también es válido. No hay wrappers `float32`/`float64`,
default de precisión, alias `cholSolve` ni variantes `InPlace`: consultar un
factor no ofrece storage de entrada que convenga consumir.

La API admite únicamente `Vector<T,Column>` como RHS vectorial. No se agrega
un overload para `Vector<T,Row>`, `MatrixView`, `MatrixViewMut` ni precisión
mixta.

## 3. Semántica matemática

Para un factor legítimo:

```text
factor.L = L : n×n
A = L L^T
diag(L) finita y estrictamente positiva
```

el overload vectorial devuelve `x : n` tal que, sujeto al redondeo concreto,
`A x = b`. El overload matricial recibe `B : n×q` y devuelve `X : n×q`; cada
columna `c` resuelve `A X[:,c] = B[:,c]`.

La operación nunca reconstruye `A`. Forward substitution lee `L[i,j]` y
backward substitution lee la transpose sólo mediante índices invertidos
`L[j,i]`. El upper almacenado de `L` no participa en ninguna operación.

El resultado del overload Matrix coincide columna por columna con el algoritmo
vectorial bajo el mismo orden escalar de §8, pero no se implementa invocando
`solve` una vez por columna. Esto conserva un único owner resultante, evita
allocations por RHS y deja explícito el layout `n×q`.

## 4. Guards y precedencia

El overload vectorial ejecuta exactamente estos guards, en este orden:

```text
1. shapeGuard(rows(factor.L) == columns(factor.L));
2. shapeGuard(dimension(b) == rows(factor.L));
```

El overload matricial ejecuta exactamente:

```text
1. shapeGuard(rows(factor.L) == columns(factor.L));
2. shapeGuard(rows(B) == rows(factor.L));
```

Todos ocurren antes de allocation, acceso elemental o aritmética. El primer
guard falso produce el trap abortivo `ShapeMismatch`; no se convierte en una
Exception capturable. Después de ambos guards se fija
`n = rows(factor.L)` y, para Matrix, `q = columns(B)`.

No se agregan guards sobre triangularidad, upper cero, finitud o signo de la
diagonal. Tampoco se compara una shape guardada con metadata externa, porque
`Cholesky<T>` sólo contiene `L`.

Esta frontera sigue el criterio de los overloads desde LU: se protegen siempre
las inconsistencias de extents que podrían causar accesos fuera de dominio,
pero no se recorre el aggregate para volver a probar todos los invariantes
semánticos de su productor. Cholesky permite una decisión aún más estrecha
sobre la diagonal porque, a diferencia de `lu`, su productor checked no puede
devolver legítimamente un factor singular.

## 5. Invariante legítima frente a aggregate representacional

`Cholesky<T>` conserva el diseño representacional vigente:

```aether
struct Cholesky<T: Storable> {
    Matrix<T> L;
}
```

La constraint del aggregate permite almacenarlo y moverlo; no prueba que una
Matrix arbitraria sea el resultado de `cholesky`. El contrato semántico de
`solve` exige que, además de pasar los guards, el argumento represente un
factor legítimo producido conforme a CHOLESKY-V1. Ésta es una precondición del
caller, no un estado que `solve` certifique nuevamente.

Revalidar toda la propiedad sería incorrectamente costoso e incompleto: mirar
la diagonal no prueba triangularidad ni que exista una entrada original SPD;
mirar toda `L` agregaría un pase `O(n²)`, nuevas comparaciones y una segunda
autoridad sobre el formato. La operación `cholesky` ya es el entry point checked
que rechaza no finitud, asimetría y pivots no positivos antes de publicar el
factor.

## 6. Política para factores construidos manualmente

Un aggregate manual que pasa los guards de shape pero viola la invariante de
§5 no dispara una validación nominal de `solve`. Su ejecución queda definida
por los mismos loops y operaciones IEEE de §7–§8:

- una diagonal `+0` o `-0` participa en `Div`; puede producir infinito o NaN
  según el numerador concreto, sin `SingularMatrixException`;
- una diagonal negativa finita participa normalmente en ambas divisiones;
- NaN o infinito se propagan o combinan conforme a `Mul`, `Sub` y `Div` IEEE;
- celdas no cero del upper se ignoran por completo;
- valores lower finitos pero incompatibles con algún Cholesky se usan como los
  coeficientes del sistema triangular indicado por esa Matrix;
- ningún caso anterior lanza `NotPositiveDefiniteException` desde `solve`.

Fuera de la precondición legítima no se promete residual respecto de una
Matrix original, positividad, finitud ni una clase especial de resultado. Sí se
prometen los guards, el orden de evaluación, la ausencia de lecturas del upper
y el ownership normales de esta arquitectura.

No se usa `SingularMatrixException`: esa excepción es necesaria en LU porque
`lu` publica factores de matrices singulares y `solve(ref LU,...)` debe decidir
si puede resolverlos. `cholesky`, en cambio, nunca publica con éxito una
diagonal cero. Reclasificar un aggregate forjado como matriz singular mezclaría
la validez de la representación con la singularidad de una entrada que el
factor no conserva.

Tampoco se reutiliza `NotPositiveDefiniteException`: `solve` no recibe la
Matrix `A` ni ejecuta el test de positive definiteness. Una diagonal negativa,
por ejemplo, viola la forma canónica elegida aunque una `L` triangular
invertible todavía define `L L^T` positive definite. Lanzar esa excepción
afirmaría una propiedad que el solve no puede diagnosticar.

No se crea `InvalidCholeskyFactorException` en este milestone. Si una futura
API necesita aceptar factores no confiables, deberá diseñar un constructor
checked o un validador explícito, con su propio costo y contrato; no cambiará
silenciosamente esta ruta reusable.

Para `B : n×0` no se recorren filas aritméticas ni diagonales. Un factor manual
inválido pero square devuelve por ello `n×0`, mientras que una LU singular con
el mismo RHS sigue lanzando según su contrato histórico. La diferencia es
deliberada: LU admite factores singulares producidos legítimamente; Cholesky
no, y esta operación no es su validador.

## 7. Algoritmo vectorial normativo

Después de los guards se crea un único `Vector<T,Column> w` de longitud `n`,
inicializado con el cero concreto. `w` es a la vez `y` y el resultado `x`.

Forward substitution, con índices públicos 1-based:

```text
for i = 1..n:
    value = b[i]
    for j = 1..i-1:
        value = value - L[i,j] * w[j]
    w[i] = value / L[i,i]
```

Al terminar la fila `i`, `w[1..i]` contiene el prefijo resuelto de `y`.

Backward substitution sobrescribe el mismo backing:

```text
for i = n..1:
    value = w[i]
    for j = i+1..n:
        value = value - L[j,i] * w[j]
    w[i] = value / L[i,i]
```

Cuando se procesa `i`, las posiciones `w[j]` con `j>i` ya contienen `x[j]` y
las posiciones menores aún pueden contener `y`; no hay interferencia. El loop
descendente debe representarse con el patrón seguro vigente para `usize`, con
salida explícita en `i == 1`, y quedar vacío cuando `n == 0`.

No se separan `y` y `x`, no se copia `b`, no se crea `L^T` y no se delega a un
kernel triangular que altere el orden o agregue storage.

## 8. Algoritmo Matrix normativo

Después de los guards se crea una única `Matrix<T> W` de shape `n×q`,
inicializada con el cero concreto. No hay gather ni permutación.

Forward substitution recorre filas, luego columnas RHS y finalmente el dot
product de cada celda:

```text
for i = 1..n:
    for c = 1..q:
        value = B[i,c]
        for j = 1..i-1:
            value = value - L[i,j] * W[j,c]
        W[i,c] = value / L[i,i]
```

Backward substitution conserva columnas ascendentes y `j` ascendente:

```text
for i = n..1:
    for c = 1..q:
        value = W[i,c]
        for j = i+1..n:
            value = value - L[j,i] * W[j,c]
        W[i,c] = value / L[i,i]
```

El orden exacto es por tanto `i/c/j`, no `i/j/c`. Cada acumulador local empieza
en el elemento RHS actual, ejecuta su dot product completo y se divide una sola
vez al final de la fila lógica de ese RHS. Esta elección hace idéntico el orden
escalar de una columna Matrix y el overload Vector, sin crear ese Vector.

La diagonal puede cargarse en un escalar una vez por fila o leerse para cada
columna siempre que no cambie el orden aritmético observable ni se introduzca
validación. No se permite convertir el algoritmo en updates `i/j/c`, reductions
vectoriales o un kernel BLAS que reasocie las restas.

## 9. Shapes con cero

Las reglas exactas son:

| `L` | RHS | resultado |
|---|---|---|
| `0×0` | Vector length `0` | Vector length `0` |
| `0×0` | Matrix `0×q` | Matrix `0×q`, preserva `q` |
| `n×n`, `n>0` | Matrix `n×0` | Matrix `n×0`, preserva `n` |
| cualquier square | RHS con dimensión/filas incompatibles | `ShapeMismatch` |
| `m×n`, `m!=n` | cualquier RHS | `ShapeMismatch` por el primer guard |

`0×q` y `n×0` conservan ambos extents y tienen backing null porque el producto
es cero. Los loops aritméticos son vacíos donde corresponda. `0×0` es el factor
legítimo vacío ya aceptado por Cholesky V1.

## 10. Ownership, alias y lifetime

`factor` y el RHS se prestan shared durante toda la call:

- no se mueve, consume, clona ni muta `factor`;
- no se mueve, consume ni muta `factor.L` a través de una proyección;
- no se mueve, consume, clona ni muta `b`/`B`;
- ningún préstamo escapa en el resultado;
- el resultado es owning e independiente de todos los inputs;
- no existe alias de backing entre resultado, `factor.L` y RHS.

Una misma factorización puede resolver secuencialmente cualquier combinación
de RHS Vector y Matrix compatibles. Después del retorno normal, y también
después de cualquier fallo que haga unwind en infraestructura ajena al kernel,
el factor y RHS permanecen vivos. Los traps de `shapeGuard` conservan su
semántica abortiva general y no prometen unwind.

Aunque el lenguaje permita construir un RHS y el factor a partir de valores
relacionados, owners distintos no pueden compartir de forma escondida el mismo
backing. El nuevo workspace elimina además cualquier necesidad de tratar alias
entre lectura y escritura.

## 11. Allocations y coste

Para el overload Vector:

- tiempo: `O(n²)`;
- storage resultante: `n` elementos;
- exactamente una allocation de backing si y sólo si `n > 0`;
- cero allocations de backing si `n == 0`.

Para el overload Matrix:

- tiempo: `O(n² q)`;
- storage resultante: `n*q` elementos;
- exactamente una allocation de backing si y sólo si `n*q > 0`;
- cero allocations de backing si `n*q == 0`.

Estos conteos son propios de una ruta válida después de guards exitosos. Un
fallo de shape sucede antes de allocation. No se asignan Matrix/Vector
auxiliares, transpose, copia del factor, copia del RHS, owner por columna,
tabla de pivots ni objeto Exception del solve.

Los escalares `value`, índices y una carga opcional de diagonal son `O(1)` y no
son owners numéricos. La Matrix resultado puede inicializarse con
`matrixFilled<T>(n,q,0)` y el Vector con `vectorFilled<T,Column>(n,0)`; su pase
de fill no autoriza un segundo backing.

## 12. Capabilities y frontera genérica

Los cuerpos usan exactamente estas familias escalares sobre `T`:

| capability | uso |
|---|---|
| `Zero` | inicialización del único workspace/result |
| `Mul` | producto de coeficiente triangular por solución previa |
| `Sub` | acumulación ordenada desde el RHS |
| `Div` | división final por `L[i,i]` |

No necesitan `Equal`, `Order`, `Sqrt`, `Abs`, `One`, `Add` ni `Negate`. La
ausencia de `Equal`/`Order` es consecuencia directa de no validar nuevamente la
diagonal.

La superficie pública permanece `T: IEEEFloat`, no una lista explícita de
capabilities ni un constraint más amplio. `IEEEFloat` sigue sellando las
instancias admitidas a `float32` y `float64`; no se agrega Complex.

## 13. Orden numérico IEEE

El orden de §§7–8 es contractual para cada celda:

1. `value` recibe el RHS actual (`b[i]`, `B[i,c]` o el `y` ya almacenado);
2. `j` crece estrictamente en forward y también en backward;
3. cada iteración evalúa primero `L[...] * workspace[...]` y luego resta ese
   producto de `value`;
4. la división por la diagonal ocurre exactamente una vez, después de todas
   las restas de esa celda;
5. el resultado concreto se almacena antes de avanzar.

No hay fast-math, reassociation, reducción paralela, FMA contractual,
acumulador promovido, tolerancia ni refinamiento iterativo. Overflow,
underflow, signed zero, subnormales, NaN e infinitos siguen las operaciones
IEEE del tipo concreto. Una optimización sólo es válida si preserva este orden
observable y el presupuesto de storage.

## 14. Relación con LU solve

No se modifica ninguna declaración, guard, excepción, loop, allocation ni
semántica de `solve(ref LU<T>,...)` o de las rutas desde Matrix. En particular,
LU conserva permutation gather, diagonal unitaria de `L`, pivots de `U`,
`SingularMatrixException` y su política para `q=0`.

Los overloads Cholesky tendrán bodies ordinarios separados. Un helper source
privado sólo sería admisible si no cambia orden, capabilities, guards,
allocations ni ownership; el primer vertical no necesita introducirlo. Unificar
artificialmente LU y Cholesky detrás de una abstracción triangular agregaría
flags/permutaciones o haría menos verificable la ausencia de transpose.

## 15. HIR, MIR, SSA y backend

La implementación futura vive exclusivamente en
`linearAlgebra/src/lib.ae`. No se agregan:

- opcode HIR/MIR/SSA de solve Cholesky;
- intrinsic, builtin o runtime helper especializado;
- reconocimiento del nombre `Cholesky` o del package;
- allowlist, ABI, witness, vtable o dispatch numérico;
- operación transpose ni materialización backend de `L^T`.

HIR debe mostrar préstamos shared de factor/RHS, los dos `shapeGuard`, una
única construcción del resultado, loops/indexing ordinarios y sólo las
capabilities de §12. Los préstamos terminan antes del retorno y el owner nuevo
se mueve al caller.

La monomorphization sustituye `T` antes de MIR. MIR y SSA contienen sólo
`float32` o `float64` concretos, `Mul/Sub/Div` concretos, branches e indexación;
no contienen parámetros genéricos, nodos capability residuales, `TypeId`,
boxing ni calls indirectas.

## 16. Qualification del milestone futuro

### Vector

La calificación cubrirá, para `float32` y `float64`:

- factor `0×0` y RHS length cero;
- `1×1`;
- diagonal SPD;
- SPD dense con solución conocida;
- comparación de residual `A*x ≈ b`;
- comparación contra `solve(ref LU, b)` cuando ambas rutas aplican;
- dos o más RHS secuenciales sobre el mismo factor;
- factor, `factor.L` y cada RHS intactos después de las calls;
- resultado owning sin alias;
- una allocation para `n>0`, cero para `n==0`.

### Matrix

Para ambas precisiones se cubrirán:

- `q=0`, incluido `n>0`;
- `q=1`, comparado elemento a elemento con el overload Vector;
- `q>1` y solución conocida;
- `n=0` con varios valores de `q`;
- SPD dense y residual `A*X ≈ B`;
- comparación contra `solve(ref LU, B)`;
- reutilización del factor con Matrix y Vector RHS mezclados;
- inputs intactos, independencia del resultado y conteos exactos de backing.

Las tolerancias serán explícitas por precisión y caso. No forman parte del
algoritmo ni de sus guards.

### Shapes inválidas

Se calificará la precedencia exacta con aggregates construidos para tests:

- `L` rectangular falla antes de mirar el RHS;
- Vector de longitud incompatible falla después de pasar square shape;
- Matrix con filas incompatibles falla después de pasar square shape;
- todos fallan antes de allocation y de cualquier acceso elemental.

### Aggregates manuales no canónicos

Los tests fijarán la política de §6, no una validación accidental:

- diagonal cero: no se lanza `SingularMatrixException` ni
  `NotPositiveDefiniteException`; se observa el resultado IEEE del caso;
- diagonal negativa finita: los loops se ejecutan sin excepción nominal;
- diagonal NaN e infinita: propagación IEEE, sin excepción nominal del solve;
- upper no cero: mismo resultado bitwise que con ese upper en cero;
- lower finito no canónico: se resuelve el par triangular `L,L^T` indicado,
  sin afirmar que provenga de `cholesky`;
- `n×0` con factor manual no canónico: éxito con shape preservada y sin leer
  diagonal.

La qualification source/IR comprobará además que no aparezcan comparaciones de
diagonal, scans de finitud, transpose, clone del factor ni Vector temporal por
columna.

### Consumer y regresión

El consumer independiente agregará dogfood equivalente a:

```aether
var ch = cholesky(A);
var x = solve(ch, b);
var x2 = solve(ch, b2);
println(ch.L);
println(x);
println(x2);
```

Se ejecutará en O0/O2 y se mantendrán verdes constructors, LU, determinant,
solve LU, QR, Cholesky y ownership ergonomics.

## 17. Determinant futuro

Se reserva, sin diseñar su algoritmo ni política numérica:

```aether
T det<T: IEEEFloat>(ref Cholesky<T> factor);
```

Este solve no agrega metadata pensando en determinant, no fija orden del
producto, overflow, validación de factors manuales ni tratamiento de `0×0` para
esa futura operación. `factor.L` ya contiene la información necesaria.

## 18. Alternativas rechazadas

| alternativa | razón de rechazo |
|---|---|
| consumir `Cholesky` | impide reutilización y no ahorra el workspace resultado |
| copiar `factor.L` | agrega `O(n²)` storage y contradice el préstamo shared |
| materializar `L^T` | allocation y tráfico innecesarios; basta indexación invertida |
| Vector separado para `y` y `x` | duplica storage sin dependencia que lo exija |
| un Vector por columna de `B` | agrega hasta `q` owners/allocations y pierde shape directa |
| revalidar SPD/factor completo | duplica autoridad y costo sin disponer de `A` |
| validar sólo diagonal | chequeo incompleto que amplía capabilities y no certifica el factor |
| `SingularMatrixException` para diagonal cero | singular LU es estado legítimo; Cholesky cero sólo puede ser aggregate forjado |
| `NotPositiveDefiniteException` desde solve | solve no comprueba positive definiteness de una entrada `A` |
| nueva excepción de factor inválido | agranda API para un constructor manual fuera de precondición |
| compartir a la fuerza el kernel LU | permutation, diagonal unitaria y `U` cambian guards y orden |
| ruta Cholesky automática desde Matrix | requiere selector/overload con política distinta y está fuera de scope |

## 19. Fuera de scope

Este milestone no implementa código. También quedan fuera:

- `solve(Matrix A,RHS)` que seleccione o ejecute Cholesky automáticamente;
- selector LU/Cholesky;
- inverse, determinant Cholesky y log-determinant;
- `Complex`, Hermitian solve y conjugate transpose;
- packed triangular storage, sparse, BLAS/LAPACK y GPU;
- iterative refinement, condición y tolerancias;
- RHS views o solve que sobrescriba el RHS;
- constructor/validador checked para un `Cholesky` manual.

## 20. Criterio de cierre

La arquitectura queda cerrada por este documento y
[LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1-REPORT](LINEAR_ALGEBRA_CHOLESKY_SOLVE_ARCH_1_REPORT.md).
El próximo milestone puede implementar exactamente los dos overloads sin
decisiones pendientes sobre guards, factors manuales, loops, zero shapes,
allocations, ownership, capabilities o lowering.
