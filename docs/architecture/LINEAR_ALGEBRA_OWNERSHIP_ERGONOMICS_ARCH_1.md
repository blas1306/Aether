# LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1 — preserving defaults

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-29.

Este milestone redefine la ergonomía de ownership de las operaciones densas
principales del package ordinario `linearAlgebra`. La API cotidiana presta y
preserva la Matrix de entrada; la variante cuyo nombre termina en `InPlace`
consume el owner y puede reutilizar su backing. Este documento sólo fija el
contrato y el próximo vertical. No modifica source, compiler, runtime ni tests.

Autoridad relacionada:

- [BORROW-ERGONOMICS-V1](BORROW_ERGONOMICS_V1_REPORT.md);
- [MATRIX-DYNAMIC-DESCRIPTOR-V1](MATRIX_DYNAMIC_DESCRIPTOR_V1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-QR-V1](LINEAR_ALGEBRA_GENERIC_QR_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-V1](LINEAR_ALGEBRA_CHOLESKY_V1_REPORT.md);
- [LINEAR-ALGEBRA-SOLVE-MATRIX-V1](LINEAR_ALGEBRA_SOLVE_MATRIX_V1_REPORT.md).

Donde este documento cambia el ownership público de aquellas APIs, esta
decisión más reciente prevalece. Sus contratos matemáticos, shapes, orden
numérico, excepciones y representación de factores permanecen vigentes.

## 1. Decisión resumida

El principio cerrado es **cómodo por defecto, explícito cuando importa**:

- `lu`, `qr` y `cholesky` reciben un préstamo shared y preservan completamente
  la Matrix fuente;
- `luInPlace`, `qrInPlace` y `choleskyInPlace` reciben ownership, conservan los
  kernels actuales y reutilizan el backing recibido;
- `det` y los dos overloads `solve` que reciben una Matrix siguen la misma
  política, con variantes `detInPlace` y `solveInPlace`;
- los overloads que reciben `ref LU<T>` no cambian;
- no hay overload elegido por ownership, copy-on-write, alias owning, clone
  implícito, GC, reference counting ni reconocimiento especial del compiler.

La superficie normativa es:

```aether
LU<T> lu<T: IEEEFloat>(ref Matrix<T> A);
LU<T> luInPlace<T: IEEEFloat>(Matrix<T> A);

QR<T> qr<T: IEEEFloat>(ref Matrix<T> A);
QR<T> qrInPlace<T: IEEEFloat>(Matrix<T> A);

Cholesky<T> cholesky<T: IEEEFloat>(ref Matrix<T> A);
Cholesky<T> choleskyInPlace<T: IEEEFloat>(Matrix<T> A);

T det<T: IEEEFloat>(ref Matrix<T> A);
T detInPlace<T: IEEEFloat>(Matrix<T> A);
T det<T: IEEEFloat>(ref LU<T> factor);              // sin cambio

Vector<T,Column> solve<T: IEEEFloat>(
    ref Matrix<T> A,
    ref Vector<T,Column> b);
Vector<T,Column> solveInPlace<T: IEEEFloat>(
    Matrix<T> A,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(
    ref Matrix<T> A,
    ref Matrix<T> B);
Matrix<T> solveInPlace<T: IEEEFloat>(
    Matrix<T> A,
    ref Matrix<T> B);

Vector<T,Column> solve<T: IEEEFloat>(
    ref LU<T> factor,
    ref Vector<T,Column> b);                         // sin cambio
Matrix<T> solve<T: IEEEFloat>(
    ref LU<T> factor,
    ref Matrix<T> B);                               // sin cambio
```

`ref` forma parte de las declaraciones preserving. En calls ordinarias se
escribe `lu(A)`, no `lu(&A)`, porque BORROW-ERGONOMICS-V1 adapta exactamente un
argumento `Matrix<T>` al parámetro `ref Matrix<T>` después de resolver la firma.
La forma explícita `lu(&A)` sigue siendo equivalente. Esa adaptación no se
aplica a los parámetros owning de las variantes `InPlace` y jamás decide cuál
de los dos nombres invocar.

Todas estas declaraciones conservan la visibilidad pública ordinaria del
package. En particular, las variantes `InPlace` no son kernels privados: son
la vía pública y explícita para quien prioriza memoria y bandwidth.

## 2. Naming

Se cierran exactamente los pares:

```text
lu        / luInPlace
qr        / qrInPlace
cholesky  / choleskyInPlace
det       / detInPlace
solve     / solveInPlace
```

El sufijo `InPlace` se asocia de manera uniforme con consumo y reutilización
del storage de la primera Matrix. Lee naturalmente en call sites y coincide con
el vocabulario numérico habitual. Se descartan `Owned`, `Consume` y `Move`
porque describen el mecanismo de transferencia pero no la intención de
reutilizar storage; `inPlaceLu` rompe la familia y ordena peor la búsqueda por
algoritmo.

`InPlace` no significa que el resultado sea la misma Matrix nominal ni que
todas las partes del factor compartan un único buffer. Significa que la Matrix
de entrada se consume y uno de los owners del resultado reutiliza su backing
según el contrato del algoritmo.

## 3. Contrato preserving

Para `lu(A)`, `qr(A)`, `cholesky(A)`, `det(A)` y `solve(A,rhs)`:

1. `A` se presta shared durante la call y no se mueve.
2. Ningún byte de su reserva, incluidos elementos lógicos y padding privado,
   puede escribirse.
3. Después del retorno normal o de una excepción recuperable, el caller
   conserva el mismo owner `A`, shape, capacities, stride, valores lógicos y
   backing.
4. Todo factor retornado posee storage independiente de `A`. Ninguna Matrix del
   factor puede aliasar su backing.
5. `rhs`, los overloads desde factor y sus reglas shared permanecen sin cambio.

“Completamente observable” incluye cualquier observación válida futura de
capacity o instrumentación de lifecycle. No basta restaurar valores al final:
la implementación no puede mutar temporalmente `A`, aunque el resultado final
coincida. Tampoco puede retener un view o referencia a `A` dentro del factor.

Un rvalue también puede adaptarse a `ref Matrix<T>` mediante el temporary
call-scoped vigente. Por tanto `lu(makeMatrix())` es legal, pero crea primero
ese owner temporal y después la copia preserving. Cuando el caller ya ofrece
un owner descartable debe preferir `luInPlace(makeMatrix())` para evitar la
copia. No se agrega una optimización contextual que cambie semántica según la
vida restante del argumento.

## 4. Contrato InPlace

Para cada variante `InPlace`:

- el primer parámetro es `Matrix<T>` owning y la call lo mueve;
- cualquier uso source posterior del binding original es un error estático de
  use-after-move;
- el kernel conserva su orden, aritmética, shape y errores actuales;
- el backing recibido se reutiliza de acuerdo con el contrato siguiente;
- no se promete recuperar el owner original si la call lanza: el unwind limpia
  el workspace consumido exactamente una vez.

Reutilización concreta:

| API | owner que recibe el backing de entrada |
|---|---|
| `luInPlace` con `m <= n` | `LU.U` |
| `luInPlace` con `m > n` | `LU.L` |
| `qrInPlace` | `QR.R` |
| `choleskyInPlace` | `Cholesky.L` |
| `detInPlace` / `solveInPlace` | el factor LU temporal correspondiente |

LU sigue asignando el otro factor económico y la permutación; QR sigue
asignando `Q`; Cholesky continúa sin allocations Matrix internas. La identidad
del backing reutilizado debe calificarse, aunque no se convierta en raw pointer
de API pública.

## 5. Una sola implementación numérica

Los cuerpos numéricos actuales se renombran a sus spellings `InPlace`. Las
versiones preserving son wrappers ordinarios conceptualmente equivalentes a:

```aether
LU<T> lu<T: IEEEFloat>(ref Matrix<T> A) {
    Matrix<T> workspace = copyMatrixForFactorization<T>(A);
    return luInPlace(workspace);
}
```

QR y Cholesky aplican exactamente el mismo patrón. No se duplica eliminación,
Householder, validación Cholesky ni cálculo de pivots. `det` y `solve` delegan
de esta forma:

```text
det(A)                 -> det(lu(A))
detInPlace(A)          -> det(luInPlace(A))
solve(A,rhs)           -> solve(lu(A),rhs)
solveInPlace(A,rhs)    -> solve(luInPlace(A),rhs)
```

Los guards propios de `det`/`solve` sobre square shape y compatibilidad del RHS
se conservan antes de factorizar y en el mismo orden actual. Cada ruta hace una
sola LU. Las preserving hacen una sola copia de `A`; las `InPlace`, ninguna.

No se introduce un kernel que a veces tome prestado y a veces consuma, un
booleano `preserve`, overload por ownership ni optimización que robe el backing
de un préstamo porque parezca ser su último uso.

## 6. Copia mínima de Matrix

La auditoría no encontró una operación general existente que copie un owner
`Matrix<T>`. Assignment mueve una Matrix non-Copy, `matrix_view` no posee
storage y `matrixFilled` construye storage nuevo pero no copia una fuente.

Este milestone diseña únicamente un helper source ordinario, privado de
`linearAlgebra`, conceptualmente:

```aether
Matrix<T> copyMatrixForFactorization<T: IEEEFloat>(ref Matrix<T> source);
```

El futuro vertical puede escoger otro nombre privado. Su contrato, no su
spelling, es normativo:

- lee `rows(*source)` y `columns(*source)`;
- crea una Matrix de shape lógico exactamente `m×n` mediante infraestructura
  pública ordinaria, inicialmente con el cero de `T`;
- copia una vez cada elemento lógico, en orden de filas, usando indexación
  Matrix y por tanto el stride real de la fuente;
- produce `rowCapacity == m` y `columnCapacity == n`;
- no lee, copia, inicializa desde ni expone el padding de la fuente;
- para `m*n > 0` crea exactamente un backing independiente; para cualquier
  shape con un eje cero conserva ambos extents y no crea backing;
- sólo se instancia para `IEEEFloat`, cuyos elementos son `Storable + Copy`.

Con la infraestructura actual, `matrixFilled` realiza un pase de inicialización
con cero y el helper realiza después el pase que copia la fuente. Son dos pases
lineales de escritura sobre el único backing nuevo, no dos copias ni dos
allocations. Un futuro constructor general de copia podría evitar el zero-fill,
pero no es requisito ni licencia para publicar storage sin inicializar.

No se usa `memcpy`: una fuente puede tener padding y `columnCapacity` distinto
de `columns`, y el contrato sólo incluye el rectángulo lógico. El loop elemento
a elemento es correcto para layout padded y no presupone bytes copiables más
allá de las capabilities declaradas.

No se publica todavía `copy(Matrix)`, `clone`, copy constructor ni una operación
general para toda collection. Una API pública futura deberá diseñarse de forma
independiente para `T: Storable + Copy`, shapes vacíos, inicialización sin un
valor semilla, exceptions y otras collections. Los wrappers no justifican
agrandar este vertical ni crear un intrinsic.

## 7. Layout rectangular y padding

La copia preserving normaliza capacidad, no layout lógico:

```text
source: {ptr, m, n, rowCapacity >= m, columnCapacity >= n}
copy:   {newPtr, m, n, m, n}
```

Cada lectura fuente usa `row * source.columnCapacity + column`; cada escritura
destino usa stride `n`. Sólo se visitan `m*n` elementos lógicos. Así, dos
matrices con valores/shape iguales pero distinto padding producen factores
contractualmente equivalentes y el padding privado nunca adquiere semántica.

Los casos `0×0`, `m×0` y `0×n` conservan sus shapes exactos. Una fuente vacía
con reserva positiva, construible en calificación de IR, genera una copia de
capacidad exacta con backing null; el factor nunca comparte aquella reserva.

## 8. Orden de errores

La copia y su posible allocation ocurren antes de entrar al kernel `InPlace`.
Después de una copia exitosa, la clase y el orden relativo de los guards,
excepciones y decisiones IEEE del kernel son idénticos a los actuales.

Para LU y QR no se agrega validación de dominio. Un fallo de allocation o size
durante la copia puede preceder al trabajo numérico; de otro modo se ejecuta el
mismo kernel y se obtiene el mismo factor que con `InPlace` sobre una copia
equivalente.

Para Cholesky se cierra explícitamente:

```text
cholesky(A): copy logical A -> choleskyInPlace(copy)
```

No se valida `A` antes de copiar. En consecuencia:

- una Matrix rectangular o con defecto de dominio puede pagar la copia antes
  del `ShapeMismatch`, `NotPositiveDefiniteException` o
  `NotSymmetricMatrixException`;
- un fallo de allocation/copy puede observarse antes de esos errores;
- una vez iniciada la validación Cholesky, se conserva exactamente la
  precedencia shape → no finito → asimetría → pivot no positivo;
- el owner original permanece intacto en todas las excepciones recuperables;
  el workspace copiado se limpia durante unwind.

Se acepta ese costo para mantener una sola autoridad de validación y una sola
implementación numérica. Prevalidar y luego llamar a `choleskyInPlace`
duplicaría el pase `O(n²)` y su error ordering; saltar la validación interna
exigiría dos entry points o un protocolo “validated” nuevo. Ninguna de esas
complejidades compensa evitar una allocation sólo en inputs inválidos. El
caller sensible a ese costo puede usar `choleskyInPlace`, que conserva shape y
validación de dominio antes de la primera escritura, como hoy.

En `det` y `solve`, los guards externos existentes sí permanecen antes de la
copia: una `A` no square, o un RHS incompatible después de pasar square shape,
falla sin factorizar ni copiar. Esto preserva el orden público ya cerrado para
esas operaciones y evita trabajo que sus propios contratos pueden descartar.

## 9. Cost model

Para una entrada `m×n`, toda API preserving de factorización agrega:

```text
tiempo adicional      O(m*n) (zero-fill más copia lógica en la estrategia actual)
storage adicional     m*n elementos de T
backing allocations   exactamente 1 si m*n > 0; 0 si m*n == 0
```

Ese workspace pasa por move al kernel y después al factor; no existe una
segunda copia ni una Matrix packed residual. La memoria pico aumenta en el
tamaño lógico de `A`, aunque el resultado conserve ese workspace como uno de
sus factores. En matrices square el término `O(n²)` no cambia el tiempo
asintótico `O(n³)`, pero sí agrega `O(n²)` de memoria pico y bandwidth, lo cual
puede dominar matrices pequeñas, cache behavior o batches grandes.

Por algoritmo:

| operación | preserving | `InPlace` |
|---|---|---|
| LU `m×n` | copia `m*n`, luego allocation actual de factor `r*r` y permutación `m` | factor `r*r` + permutación; recicla `A` |
| QR `m×n` | copia `m*n`, luego `Q` de `m*m`; copia queda como `R` | `Q` de `m*m`; `A` queda como `R` |
| Cholesky `n×n` | una copia `n*n`; copia queda como `L` | cero allocations del kernel; `A` queda como `L` |
| `det/solve` desde Matrix | el costo preserving de LU una vez, más resultado/workspace propio de solve | costo LU actual una vez, más resultado/workspace propio de solve |

`r = min(m,n)`. La tabla cuenta owners numéricos principales; las excepciones
nominales y el backing null de shapes vacíos conservan sus contratos propios.
No se promete que un optimizador elimine la copia preserving y no se permite
hacerlo si pudiera aliasar o modificar `A`.

## 10. `det` y `solve` desde Matrix

Se elige la opción consistente: los overloads cotidianos desde Matrix también
preservan `A`, y se agregan variantes públicas `InPlace`. Mantenerlos consuming
habría creado esta sorpresa:

```aether
lu(A);       // preserva A
det(A);      // consume A
```

Además, conservar la firma owning de `det/solve` pero hacerla llamar al nuevo
`lu(ref Matrix)` consumiría un owner sólo para copiarlo y destruirlo después,
el peor resultado de ergonomía y costo. Las dos familias explícitas evitan esa
incoherencia.

Sólo `A` cambia de política. Los RHS de `solve` ya son `ref` shared, permanecen
usables y no reciben variantes destructivas. Los overloads `det(ref LU<T>)` y
`solve(ref LU<T>, ref RHS)` siguen siendo preserving, reutilizables y sin copia
de factores. Las futuras APIs:

```aether
solve(ref Cholesky<T> factor, ref RHS)
det(ref Cholesky<T> factor)
```

deben seguir el mismo contrato borrowed y no requieren variantes `InPlace`,
porque consultar un factor no necesita consumirlo.

## 11. Compatibilidad y migración

Éste es un cambio semántico deliberado y aceptable antes de estabilizar la API
pública V1. La mayoría de calls `lu(A)`, `qr(A)`, `cholesky(A)`, `det(A)` y
`solve(A,rhs)` sigue compilando y conserva resultados matemáticos, pero ahora
`A` continúa usable y aparece una allocation/copia adicional.

Impactos que el vertical debe tratar explícitamente:

- tests de use-after-move del nombre base pasan a ser positivos y deben migrar
  a `*InPlace`;
- tests de allocation exacta y backing reuse deben dividirse por familia;
- forwarding functions tipadas con parámetro owning cambian de firma si
  prometen preserving, o deben llamar `*InPlace` si siguen consumiendo;
- valores de función o expectativas ABI con `Matrix<T>` no son compatibles con
  la nueva firma `ref Matrix<T>`;
- callers que sólo usaban la call como último uso siguen compilando pero pagan
  una copia hasta migrar a `*InPlace`;
- source que antes esperaba intencionalmente que el binding quedara moved ya no
  obtiene esa prueba salvo que use el spelling explícito.

No se mantiene simultáneamente un overload legacy `lu(Matrix<T>)`: overloads
que sólo difieren por ownership harían que la selección/adaptación fuese parte
de la semántica de performance y contradirían este diseño.

El alias deprecated `qrFloat32(Matrix<float32>)` conserva su firma consuming y
debe delegar a `qrInPlace(A)`. Así no introduce una copia nueva escondida y su
contrato histórico permanece hasta su retiro. No se agregan aliases
`luOwned`, `qrOwned` ni equivalentes.

## 12. Compiler e IR

Todo se resuelve en package source ordinario:

```text
call preserving
  -> CallScopedSharedBorrow de A
  -> allocation Matrix ordinaria + loops de copia
  -> call owning al InPlace
  -> EndBorrow

call InPlace
  -> Move de A
  -> kernel existente
  -> backing transferido al factor
```

HIR debe mostrar `ref Matrix<T>` y borrow scoped en el wrapper/caller; MIR y SSA
deben conservar Borrow/EndBorrow, el owner independiente y el Move al kernel.
Las variantes `InPlace` muestran el consumo actual. Los verificadores deben
rechazar tanto un wrapper preserving que mueva/escriba la raíz prestada como
una variante `InPlace` que duplique o deje vivo el owner original.

No se agrega opcode de copia Matrix, recipe de factorización, intrinsic LU/QR/
Cholesky, allowlist de package, COW, metadata de “último uso” ni excepción al
borrow checker. `linearAlgebra` no recibe privilegios sobre otras libraries.

## 13. UX canónica

Uso cotidiano:

```aether
Matrix<float64> A = ...;

var luFactor = linearAlgebra.lu(A);
var qrFactor = linearAlgebra.qr(A);

// A sigue disponible y no comparte backing con los factores.
println(A);
```

Uso sensible a memoria:

```aether
Matrix<float64> A = ...;
var factor = linearAlgebra.luInPlace(A);

// A fue consumida; usarla aquí es un error estático.
```

La guía debe recomendar el nombre base cuando claridad, reuso de la entrada o
seguridad frente a decisiones anticipadas importe; `InPlace` cuando el caller
sabe que termina la vida de `A` y desea evitar una copia `O(mn)`.

## 14. Qualification del futuro vertical

### 14.1 Preservación y equivalencia

Para LU, QR y Cholesky, en `float32` y `float64`, shapes válidos incluidos los
vacíos y rectangulares admitidos:

1. construir `before` mediante una copia explícita independiente;
2. invocar el nombre preserving;
3. comprobar shape, capacities observables disponibles, valores y usabilidad
   posterior de `A`;
4. comprobar que ninguna escritura alcanzó el backing de `A`;
5. comparar el factor con `*InPlace` aplicado a otra copia idéntica;
6. comprobar backing distinto para toda Matrix retornada que pudiera contener
   el workspace.

La igualdad numérica usa los oráculos/tolerancias existentes; shapes,
permutación, ceros estructurales y preservación de bytes se comprueban de forma
exacta. Una fixture padded con canarios confirma que sólo se leen elementos
lógicos y que el resultado tiene capacidad exacta.

### 14.2 Ownership negativo

Cada `*InPlace(A)` debe producir error compile-time al usar `A` después. Cada
nombre preserving debe permitir `rows(A)`, indexación, formatting y una segunda
factorización después de la call. Se cubren argumento implícitamente prestado,
`&A` explícito, rvalue temporal y forwarding genérico.

HIR/MIR/SSA deben demostrar borrow sin Move para preserving y Move sin clone
para `InPlace`. Corrupciones independientes deben rechazar alias de backing,
escritura a shared ref, borrow que escapa, owner duplicado, EndBorrow omitido y
Drop doble.

### 14.3 Allocations y errores

Con counters en O0 y O2 se exige:

- exactamente un backing adicional para cada copia preserving no vacía y cero
  para shapes de producto cero;
- presupuesto actual sin copia en cada `InPlace`;
- identidad de backing reciclado conforme a la tabla de §4;
- cleanup balanceado en éxito y unwind;
- Cholesky inválido preserving: copia antes de shape/domain, misma clase y
  precedencia del kernel cuando la copia tiene éxito;
- Cholesky inválido `InPlace`: validación actual antes de primera escritura;
- `det/solve` incompatibles: guards externos antes de la copia;
- singularidad de solve y demás errores actuales sin reclasificación.

La auditoría source/IR exige un único body numérico por algoritmo, wrappers con
una copia exacta, ninguna copia dentro de loops numéricos y ausencia de
intrinsics o reconocimiento por nombre.

### 14.4 Regresión y consumer

El consumer publicado debe exhibir ambas familias y migrar calls donde el costo
histórico consuming sea intencional. Se ejecutan package check, consumer O0/O2,
suites dedicadas de LU/QR/Cholesky/det/solve, workspace completo, formatting,
clippy y differential suite conforme a las prácticas vigentes.

## 15. Primer vertical recomendado

**LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1** debe ser un solo vertical coherente:

1. renombrar los tres cuerpos numéricos actuales a `*InPlace`;
2. agregar el helper privado de copia lógica exact-capacity;
3. agregar los tres wrappers preserving;
4. migrar las rutas Matrix de `det/solve` y agregar sus variantes `InPlace`;
5. mantener sin cambios los overloads desde `LU`;
6. dirigir `qrFloat32` a `qrInPlace`;
7. actualizar documentación, consumer y qualification de ownership,
   allocations, padding, errores e IR.

Separar sólo el rename de kernels de los wrappers dejaría una API pública
transitoriamente incoherente. El vertical puede organizar commits internos,
pero se declara completo únicamente con todos los pares y pruebas anteriores.

## 16. Fuera de scope

Este milestone no diseña ni implementa:

- copy-on-write, ARC nuevo, GC o reference counting de Matrix;
- copy constructors, assignment por copia o conversión owner-a-copia;
- una API pública general `copy`/`clone` para collections;
- cambios al borrow checker o a BORROW-ERGONOMICS-V1;
- factors compactos, views de entrada como sustituto de Matrix owner o aliasing
  entre fuente y resultado;
- solve/det por Cholesky, inverse, SVD, eigenvalues, sparse o GPU;
- BLAS/LAPACK, block algorithms o eliminación de copia por análisis de último
  uso;
- cambios numéricos a LU, QR o Cholesky.

No quedan decisiones abiertas que bloqueen el vertical. En particular quedan
cerrados firmas, naming, visibilidad, ownership, copia y padding, costos,
`det/solve`, orden Cholesky, compatibilidad y qualification.
