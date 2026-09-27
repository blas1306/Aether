# DYNAMIC-SHAPES-AND-SLICES-ARCH-1

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-27.

Este milestone fija el contrato conjunto de shapes runtime, crecimiento de
`Matrix`, slices cerrados y asignación de slices. No admite todavía ninguna
sintaxis nueva ni modifica compiler-next, compiler legacy, runtime, std,
`linearAlgebra` o tests.

La autoridad de implementación futura es compiler-next. El compilador legacy
posee slices owning semiabiertos de `Array`/`List`; se auditan en la sección 16,
pero no constituyen un segundo contrato V1.

## 1. Decisiones resumidas

- `Vector<T,O>` es un owner unidimensional de longitud runtime e inmutable,
  con orientación `O` estática. `Row` y `Column` son tipos distintos.
- `Matrix<T>` es un owner rectangular de rows y columns runtime. Conserva ambos
  valores aun cuando uno sea cero; por eso distingue `0×0`, `m×0` y `0×n`.
- El crecimiento se expresa sólo como `A.add(v)`. Una fila crece rows y una
  columna crece columns. El vector se consume y la operación exige elementos
  `Storable + Relocatable`.
- Matrix adopta reserva geométrica bidimensional. El descriptor owner necesita
  `rowCapacity` y `columnCapacity`; el stride físico de fila es
  `columnCapacity`, no necesariamente `columns`.
- `Array`/`List` siguen siendo 0-based. `Vector`/`Matrix` y todos sus views son
  1-based. Los diagnostics nombran el dominio del tipo real.
- Los únicos selectores slice son `a:b` y `:` dentro de brackets. `a:b` es
  cerrado. `a:`, `:b`, stride y reverse no existen en V1.
- Los slices de `Array`/`List` son owners nuevos del mismo tipo. Los slices
  matemáticos son views prestados y conservan orientación, shape y strides.
- La asignación de slice reemplaza contenido y nunca cambia length/shape.
  Exige extent/shape y orientación exactos, sin broadcasting.
- Toda asignación solapada observa un snapshot lógico del RHS anterior a la
  primera escritura. La optimización puede evitar el temporal si prueba no
  overlap, pero no puede cambiar el resultado.
- `zeros`/`ones` son API de `linearAlgebra`. Una capacidad fundamental,
  general y segura de filled initialization permite que ese package y cualquier
  otro construyan abstracciones runtime-shape sin exponer punteros, capacity ni
  memoria sin inicializar.
- La API deseada de `zeros`/`ones` requiere overload resolution contextual por
  result type, inferencia de `T` y orientación desde el expected type. Esa
  capacidad no existe hoy.

## 2. Modelo nominal y representación de Vector

La identidad canónica permanece:

```text
VectorType = Vector { element: TypeId, orientation: Row | Column }
VectorValue = { data: ptr, length: usize }
```

La orientación nunca es metadata runtime. La longitud sí lo es y puede ser
cualquier `usize`, incluido cero. Para longitud cero el valor canónico usa
`{null,0}` y no asigna backing. Para longitud positiva, `data` referencia
exactamente `length` elementos inicializados.

La longitud de un Vector no cambia después de construirlo. "Shape dinámica"
significa que no forma parte del TypeId y se conoce en ejecución; no convierte
Vector en una colección growable. No se agrega `Vector.add`, capacity ni resize.

Son invariantes normativos:

- `Vector<T,Row>` y `Vector<T,Column>` no son asignables entre sí;
- ninguno es nominalmente `Matrix<T>` de `1×n` o `n×1`;
- no hay conversión implícita Vector↔Matrix ni Row↔Column;
- `transpose`/`transpose_view` siguen siendo las operaciones explícitas que
  cambian orientación;
- los elementos lógicos son todo el intervalo físico `[0,length)`.

## 3. Modelo rectangular y representación de Matrix

El estado lógico es siempre el producto cartesiano rectangular
`[0,rows) × [0,columns)`. No existe una longitud por fila, una fila parcial ni
un sentinel de hueco.

La representación growable cerrada es:

```text
MatrixValue<T> = {
    data: ptr,
    rows: usize,
    columns: usize,
    rowCapacity: usize,
    columnCapacity: usize
}

rowCapacity    >= rows
columnCapacity >= columns
physicalOffset(r0,c0) = r0 * columnCapacity + c0
```

Sólo las celdas con `r0 < rows && c0 < columns` están inicializadas y forman
parte del valor. Las ranuras reservadas son metadata interna inaccesible: no se
leen, no se destruyen y nunca se exponen mediante índices, slices o views.
Esto no es una API general `uninit`.

Si `rowCapacity * columnCapacity > 0`, `data` posee esa reserva comprobada. Si
el producto es cero, no hay asignación y `data == null`. Los dos productos de
capacity y bytes se comprueban contra overflow antes de asignar.

Un Matrix owner deja de prometer packing lógico con stride `columns`. Al crear
`MatrixView`, el descriptor es
`{data,rows,columns,columnCapacity,1}`. Los algoritmos internos deben usar el
stride del owner o un `MatrixView`; no pueden reconstruirlo desde `columns`.
Los literales y resultados materializados pueden comenzar con capacities
exactas, por lo que inicialmente siguen siendo packed.

La rectangularidad se preserva porque una mutación estructural publica el nuevo
par `(rows,columns)` sólo después de inicializar la fila o columna completa. No
hay estado source-visible con una celda ausente. Un trap aborta el proceso y no
expone un estado intermedio, coherente con el modelo actual sin unwinding.

## 4. Shapes con ejes cero

Rows y columns son metadata independiente incluso con backing nulo:

| Shape | `rows` | `columns` | elementos | backing |
|---|---:|---:|---:|---|
| `0×0` | 0 | 0 | 0 | null |
| `m×0` | m | 0 | 0 | null |
| `0×n` | 0 | n | 0 | null |

`[]` bajo expected type `Matrix<T>` produce exclusivamente `0×0`. Las otras
formas provienen de constructores matemáticos (`zeros/ones`), outer products,
slices full-axis o `add`; no se inventa sintaxis de literal ragged/vacía.

La ausencia de backing no permite deducir shape. Move, return, fields, equality
futura, views, rows/columns y drop deben transportar ambos ejes. Drop recorre
sólo el rectángulo lógico; las tres formas vacías destruyen cero elementos y
liberan cero backings.

Para un `MatrixView`, una dimensión cero conserva la otra y sus strides. No se
requiere que un descriptor vacío tenga una única combinación de strides; su
procedencia verificada, shape y la imposibilidad de indexarlo son la autoridad.

## 5. `Matrix.add`

La única superficie source es:

```aether
A.add(rowVector);       // Vector<T,Row>
A.add(columnVector);    // Vector<T,Column>
```

No existen `addRow` ni `addColumn`. El receiver debe ser un Place Matrix
escribible y no puede tener referencias o views derivados vivos. La operación
es estructural y puede invalidar todas las direcciones del backing.

El argumento es exactamente un owner `Vector<T,O>` con el mismo `T`; no acepta
Matrix, Array/List ni view y no realiza conversiones ocultas. Se consume aun
cuando `T` sea Copy. Esto permite transferir cada elemento una sola vez y hace
explícito que el RHS deja de ser utilizable.

Consumir también para `T:Copy` es una decisión consciente, uniforme y
potencialmente sorprendente desde el punto de vista ergonómico. La vertical de
implementación debe calificarla con casos de uso y pruebas de llamadas reales,
incluido el costo de copias y la claridad de diagnostics. Sin evidencia
suficiente este documento no cambia la semántica. La alternativa que debe
compararse es una variante copy-preserving disponible sólo para `T:Copy` —por
ejemplo, una operación que tome el Vector por préstamo compartido y copie sus
elementos— que deje el argumento utilizable; no debe aparecer como copia
implícita accidental ni debilitar el camino consuming para otros T.

La expansión puede relocalizar elementos ya inicializados, por lo que `add`
requiere `T: Storable + Relocatable`. `Matrix<T>` en sí conserva admisión con
sólo `T:Storable`; para un T sin prueba Relocatable, la construcción fija,
indexing y views siguen disponibles pero `add` se diagnostica estáticamente.

Las reglas completas son:

| Shape antes | argumento | precondición | shape después |
|---|---|---|---|
| `m×n` | `Vector<T,Row>` de longitud `k` | `k == n` | `(m+1)×n` |
| `m×n` | `Vector<T,Column>` de longitud `k` | `k == m` | `m×(n+1)` |

Estas reglas también resuelven el primer vector y los ceros:

- `0×0 + Row(n)` produce `1×n`; si `n==0`, produce `1×0`;
- `0×0 + Column(m)` produce `m×1`; si `m==0`, produce `0×1`;
- `m×0 + Row(0)` produce `(m+1)×0`;
- `m×0 + Column(m)` produce `m×1`;
- `0×n + Column(0)` produce `0×(n+1)`;
- `0×n + Row(n)` produce `1×n`.

Una discrepancia se comprueba antes de asignar, relocalizar o escribir backing
y produce `ShapeMismatch`, indicando orientación, longitud recibida y extent
esperado. Nunca se rellena, trunca ni deja un hole.

### 5.1 Reserva y costo

Cada capacity crece geométricamente (factor dos, con mínimo uno) cuando el eje
correspondiente se agota. Un crecimiento de reserva asigna el rectángulo de
capacity nuevo, relocaliza exactamente las celdas lógicas en orden verificable,
inicializa el vector nuevo, desarma los owners fuente y libera los backings
viejos. Sin crecimiento de reserva, agregar una fila cuesta `O(columns)` y una
columna `O(rows)`.

Una realocación cuesta `O(rows*columns + vector.length)`. Con capacities
geométricas, una secuencia que construye una matriz mediante filas y/o columnas
tiene costo amortizado lineal en la cantidad final de celdas inicializadas; no
repite una multiplicación o copia completa por cada `add`. La reserva es
`O(rowCapacity*columnCapacity)` y queda acotada por un factor constante del
rectángulo lógico cuando ambos ejes son positivos. Los shapes con un eje cero
no asignan memoria.

No se promete estabilidad de puntero ni de capacity observable. Capacity no
tiene query pública V1 y no participa en TypeId, igualdad ni semántica
matemática.

### 5.2 Expresabilidad actual

La sintaxis de method call ya existe, pero hoy no hay methods intrínsecos de
value types, overloads por orientación, generic parameter de orientación ni un
efecto estructural Matrix equivalente a `ListPush`. El primer vertical debe
resolver `A.add(v)` como operación compiler-known, elegida por el TypeId
canónico de `v`, y conservarla explícita en HIR/MIR/SSA. No debe simularse con
dos funciones OAL ni borrando Row/Column a runtime.

## 6. Bases y dominios de índices

| Contenedor | dominio escalar de extent `n` | slice cerrado |
|---|---|---|
| `Array<T>`, `List<T>` | `0 .. n-1` | `0 <= a <= b < n` |
| `Vector<T,O>` y views | `1 .. n` | `1 <= a <= b <= n` |
| eje Matrix y views | `1 .. extent` | `1 <= a <= b <= extent` |

Los operandos se contextualizan como `usize`, igual que indexing vigente. Un
índice constante inválido se diagnostica estáticamente cuando el extent es
conocido; de otro modo se produce el trap estructurado correspondiente antes de
restar la base o calcular un offset.

Los diagnostics no hablan genéricamente de "array" para un Vector/Matrix. Deben
incluir tipo/eje, base y extent real, por ejemplo `Vector slice 1-based range`
o `Matrix column slice ... extent 0`.

## 7. Gramática de selectores slice

La gramática contextual dentro de brackets es:

```text
selector      := scalar-expression | closed-slice | full-slice
closed-slice  := expression ":" expression
full-slice    := ":"
subscript     := expression "[" selector ("," selector)* "]"
```

`closed-slice` incluye ambos extremos y su longitud, tras validar, es
`b - a + 1`. `a > b` es inválido; no representa un slice vacío ni reverso.
`a:`, `:b`, `a:s:b`, más de un colon y negative indices son errores de sintaxis
específicos.

`[:]` significa toda la dimensión y no se descompone en endpoints. Es válido
para extent cero y produce longitud cero. Por diseño, la única forma de obtener
un slice vacío de una dimensión vacía es `[:]`; un closed-slice nunca es vacío.

El AST debe representar:

```text
SubscriptSelector = Scalar(AstExpr)
                  | Closed { first: AstExpr, last: AstExpr }
                  | Full
```

No debe reutilizar `AstExprKind::Range`. Esa forma actual permite un tercer
operando y no puede representar `[:]` sin fabricar expresiones. HIR resuelve
cada selector después de conocer el tipo/base/axis del container.

## 8. Slices de Array y List

`Array<T>[a:b]` produce un `Array<T>` owner nuevo; `List<T>[a:b]` produce un
`List<T>` owner nuevo. `[:]` produce una copia owning completa del mismo tipo.
El source y el resultado no comparten container ni buffer exterior. Modificar
un slot del resultado no modifica el slot source.

V1 exige `T:Copy` para materializar estos slices. El source permanece usable y
no hay un `Clone` general ni una transferencia parcial implícita que justifique
duplicar un T no-Copy. Handles o agregados no-Copy no pueden copiarse mediante
bitcopy accidental. Un milestone posterior puede introducir copy-initialization
o Clone explícito sin cambiar bounds/result type.

Un resultado Array tiene longitud exacta `k`. Un resultado List tiene length y
capacity iniciales iguales a `k`; su crecimiento posterior sigue el contrato
List normal. Para `[:]` sobre un owner vacío ambos resultados son owners vacíos
canónicos, sin allocation.

La creación cuesta `O(k)` tiempo y storage y realiza a lo sumo una allocation
no vacía. No es un view y no toma un borrow que limite la vida del source.

## 9. Slices de Vector

Un slice rvalue de `Vector<T,O>`, `VectorView<T,O>` o
`VectorViewMut<T,O>` produce siempre `VectorView<T,O>` compartido:

```text
v[a:b] -> { ptr(first), b-a+1, source.stride }
v[:]   -> { source.ptr, source.length, source.stride }
```

La orientación `O` se conserva en el TypeId. No se materializa un Vector, no se
cambia Row por Column y no se expone un raw `View` 0-based. Sobre un owner el
stride es uno; sobre un view se conserva el stride existente.

Crear el slice cuesta `O(1)`, no asigna ni copia elementos. El resultado hereda
la procedencia y restricciones actuales de `VectorView`: es Copy/Relocatable,
no-Storable, no puede escapar ni sobrevivir al owner y bloquea sus mutaciones
estructurales/move mientras está vivo.

La sintaxis ordinaria produce un view compartido incluso si la fuente es
escribible. La forma `v[a:b]` funciona además como slice-place escribible sólo
cuando aparece directamente a la izquierda de una asignación y la fuente tiene
capacidad mutable. No introduce un `VectorViewMut` escapable implícito; los
constructores explícitos `_mut` existentes siguen siendo la superficie para
obtener uno.

## 10. Indexing y slicing de Matrix

Cada axis tiene un selector y el tipo resultante depende de su rank lógico:

| Expresión | Resultado rvalue |
|---|---|
| `A[i,j]` | elemento `T`/Place escalar existente |
| `A[i,:]` | `VectorView<T,Row>` |
| `A[:,j]` | `VectorView<T,Column>` |
| `A[a:b,c:d]` | `MatrixView<T>` |
| `A[:,:]` | `MatrixView<T>` |
| `A[a:b,:]` | `MatrixView<T>` |
| `A[:,c:d]` | `MatrixView<T>` |

No se hace rank collapse para closed-slices de longitud uno: `A[i,:]` es vector
porque el selector de fila es escalar, mientras `A[i:i,:]` es MatrixView 1×n.
Dos escalares son indexing escalar; un escalar y un slice producen un vector
orientado; dos slices producen una submatriz.

Para descriptor fuente `(ptr,R,C,RS,CS)`:

```text
A[i,:]       = { ptr+(i-1)RS, C, CS }
A[:,j]       = { ptr+(j-1)CS, R, RS }
A[a:b,c:d]   = { ptr+(a-1)RS+(c-1)CS, b-a+1, d-c+1, RS, CS }
```

Un selector `Full` preserva el extent sin calcular `first-1`. Esto hace
definidos `A[i,:]` sobre `m×0` cuando `i` es válido, `A[:,j]` sobre `0×n`
cuando `j` es válido y `A[:,:]` para los tres shapes vacíos. No hay fila
válida en `0×n` ni columna válida en `m×0`.

Todos los resultados vector/matrix son views compartidos O(1), sin allocation,
y preservan procedencia y strides, incluso sobre transpose/subviews. La forma
directa de slice puede actuar como place mutable en slice assignment si la
fuente es writable, con la misma política que Vector. No hay conversión owning
implícita; una materialización futura debe ser una operación explícita y cuesta
`O(rows*columns)`.

## 11. Slice assignment

Slice assignment modifica celdas existentes y no cambia length, rows, columns
ni orientación. El LHS debe ser un owner o view mutable; un view compartido se
rechaza.

V1 admite:

| LHS | RHS exigido | contrato |
|---|---|---|
| `Array<T>[slice]` | `Array<T>` | length exacta |
| `List<T>[slice]` | `List<T>` | length exacta |
| `Vector<T,O>[slice]` | Vector/VectorView `T,O` | length y orientación exactas |
| `A[i,:]` | Vector/VectorView `T,Row` | `dimension == columns(A)` |
| `A[:,j]` | Vector/VectorView `T,Column` | `dimension == rows(A)` |
| `A[rowSlice,columnSlice]` | Matrix/MatrixView `<T>` | shape exacta |

`[:]` en el LHS permite asignar un RHS vacío a una dimensión vacía. Los
closed-slices siguen requiriendo al menos un elemento.

El reemplazo conserva el RHS y puede necesitar capturarlo por overlap; por
ello V1 exige `T:Copy`. Esta es la misma frontera que el reemplazo parcial
escalar actual de owners matemáticos. No se destruyen/mueven subowners no-Copy
ni se introduce Clone implícito.

Primero se validan bounds, orientación y extent/shape completos; luego se
realizan escrituras. Una discrepancia produce `ShapeMismatch` sin escribir una
parte. No hay scalar broadcasting, row/column broadcasting, padding,
truncation, conversión de orientación ni resize estructural.

## 12. Aliasing y overlap

La semántica observable es **snapshot del RHS**:

```aether
v[1:3] = v[2:4];
A[1:3,:] = A[2:4,:];
```

produce el mismo resultado que si todos los elementos RHS se hubiesen leído en
orden lógico a un temporal independiente antes de la primera escritura LHS.
Esto incluye views copiados, transpuestos, strided y cadenas de subviews con el
mismo owner de procedencia.

La implementación conservadora usa un temporal de `k` elementos, o `r*c` para
Matrix, y cuesta O(tamaño) tiempo/storage. Puede usar `memmove`, elegir dirección
de traversal o escribir directo con O(1) extra sólo cuando prueba que preserva
exactamente el snapshot. La ausencia de igualdad de punteros no prueba por sí
sola no-overlap para vistas strided; debe usarse procedencia y rango de offsets.

## 13. Frontera de allocation e inicialización

La representación y allocation de owners son capacidades fundamentales, no
constructores matemáticos. Se agrega una capacidad general verificada de
**filled initialization**, conceptualmente:

```text
vectorFilled<T,O>(length, initializedValue) -> Vector<T,O>
matrixFilled<T>(rows, columns, initializedValue) -> Matrix<T>
```

Los nombres son conceptuales; la superficie concreta puede vivir en un módulo
`core`/low-level y no es la API matemática recomendada. Sin embargo, debe ser
source-accessible bajo reglas uniformes para **cualquier package** que cumpla
sus constraints. No existe allowlist de std/OAL, autorización por metadata,
compiler magic ligada a package identity ni capacidad privilegiada. Esto es
coherente con PACKAGE-MANAGER-ARCH-1: la condición OAL expresa ownership y
metadata de confianza, no permisos técnicos.

La primitiva exige `T:Storable+Copy` y un `initializedValue: T` obligatorio;
no hay overload que omita el valor. Comprueba length/rows/columns, todos los
productos de shape/capacity y el tamaño en bytes antes de asignar. Para un
shape no vacío reserva storage no observable, copy-inicializa cada celda lógica
y sólo entonces publica el owner terminado. Para `length == 0`, `0×0`, `m×0`
o `0×n` no asigna backing, pero conserva toda la metadata lógica de shape. La
capacity elegida queda encapsulada y no forma parte del resultado observable.

HIR/MIR/SSA deben llevar una operación distinta de Matrix/Vector literal con
shape runtime y prueba de inicialización completa. Los verificadores exigen:

- argumentos `usize`, T y orientación coherentes;
- productos sin overflow antes de allocation;
- exactamente `rows*columns` o `length` stores inicializantes antes de publicar
  o permitir el escape del owner;
- cleanup del prefijo inicializado en una salida interna fallida;
- ninguna lectura/drop de padding reservado.

La superficie general devuelve sólo el owner terminado: no expone raw pointer,
memoria uninitialized, capacity o mutación de capacity, constructor raw,
`assume_init` ni estado parcialmente inicializado. Tampoco introduce
`Matrix<T>(m,n)`, `Vector<T>(n)` sin valor ni `.fill` como API matemática. Si
una operación futura necesita inicialización por generador para T no-Copy,
debe diseñarla aparte; este milestone no abre memoria arbitrariamente no
inicializada.

## 14. `linearAlgebra.zeros` y `ones`

La superficie matemática es:

```aether
Matrix<float64> A = linearAlgebra.zeros(3, 2); // 3×2
Matrix<float64> B = linearAlgebra.zeros(3);    // 3×3
Vector<float64,Column> v = linearAlgebra.zeros(3);
Vector<float64,Row> w = linearAlgebra.ones(3);
```

Para Matrix, un argumento significa square y dos significan rows/columns. Para
Vector, un argumento significa length y el expected type decide orientación.
El expected type también decide T cuando no hay argumento elemental.

`linearAlgebra` implementa estas funciones como código de package ordinario:
selecciona el cero/uno matemático de T y llama la misma capacidad general de
filled initialization disponible para cualquier package. `identity(n)` puede
construir `zeros(n,n)` y escribir la diagonal; no necesita allocation sin
inicializar. Un package comunitario puede usar exactamente la misma primitiva
y constraints para construir sus propias abstracciones, sin hacerse pasar por
OAL. Los constructores hacen una allocation y O(cantidad de elementos) stores,
no productos, outer products ni repeated `add`.

Una llamada de un argumento sin expected type es ambigua y debe diagnosticarse;
no elige Matrix, Row ni Column por prioridad. Con dos argumentos sólo Matrix es
candidato, pero T aún debe venir de expected type o type arguments explícitos.

## 15. Capacidades de lenguaje faltantes

Compiler-next no puede expresar hoy la API anterior como una OAL ordinaria:

1. no admite overload sets source con el mismo nombre;
2. la resolución de llamadas no usa el expected result type para seleccionar
   candidato ni inferir type arguments que aparecen sólo en el retorno;
3. Row/Column son markers compiler-known, no generic parameters source;
4. no hay overload sólo por orientación/result type;
5. no existe una capacidad general source-accessible y segura de
   allocation+fill runtime de shape variable;
6. no existe un method intrinsic estructural Matrix ni su efecto de
   invalidación en HIR/MIR/SSA;
7. el AST de subscript no distingue selector escalar, closed y full;
8. los IR no representan slice views, assignment snapshot ni sus contratos de
   shape/overlap.

La solución general recomendada es resolución contextual de overloads: filtrar
por nombre/arity y argumentos, contrastar el result type con el expected type,
inferir T/markers, exigir un único candidato y recién entonces crear la
instancia. No se agregan casos por nombre `zeros` en el frontend ni funciones
duplicadas `zerosRow`/`zerosColumn` a la API pública.

`A.add(v)` sí puede entrar antes como intrinsic cerrado porque su receiver y
argumento determinan unívocamente operación, T y orientación; no necesita
expected result overload.

## 16. Auditoría de compatibilidad

### 16.1 Reutilizable en compiler-next

- `TypeData::Vector` ya incluye orientación estática y descriptor owner
  `{ptr,dimension}`.
- `TypeData::Matrix` ya conserva rows/columns y rectangularidad de literales.
- `IndexSemantics` ya separa zero-based, one-based y one-based-2D.
- `VectorView{Mut}` ya usa `{ptr,dimension,stride}` y conserva orientación.
- `MatrixView{Mut}` ya usa `{ptr,rows,columns,rowStride,columnStride}`.
- `row`/`column`, transpose views, procedencia, no-escape y borrow invalidation
  cubren la mayor parte del modelo de slices matemáticos.
- List ya posee capacity, reserva geométrica, mutación estructural y efectos
  explícitos que sirven como patrón, no como representación de Matrix.
- Literales y algebraic results ya inicializan owners completos sin exponer
  memoria uninitialized.

### 16.2 Cambios semánticos necesarios en compiler-next

- Matrix pasa de tres a cinco palabras owner y de stride implícito `columns` a
  `columnCapacity`; todos los accesos, drop, aritmética y view recipes deben
  dejar de asumir packing.
- El AST/parser de subscript necesita selectors; hoy parsea expresiones y usa
  el `Range` general, que también admite tres partes y no representa `[:]`.
- HIR/MIR/SSA/verificadores/backends necesitan operaciones distintas para slice
  view, owning collection slice, add, filled-init y slice assignment.
- El sistema de procedencia debe reconocer subviews y prohibir `add` con aliases
  vivos, igual que ya prohíbe move/replacement del owner.
- Shape facts deben transportar `0×n`/`m×0`; la suposición V23 de que todo Matrix
  vacío es `0×0` deja de ser válida.
- Los algoritmos algebraicos deben consumir strides del owner/view y sus
  verificadores deben rechazar reconstrucciones desde columns.

### 16.3 Compiler legacy

Legacy ya implementa `Array/List[start:end]` como copia owning, 0-based y
**semiabierta**, permite `start==end` y no admite `[:]` ni slice assignment.
Sus AST/IR/SSA (`SliceExpression`, `IRArraySlice`, `IRListSlice`) y helpers
runtime son reutilizables conceptualmente, pero no pueden conservar esos bounds
bajo el nombre V1 nuevo.

La migración debe cambiar validación a `0 <= a <= b < n`, longitud a
`b-a+1`, agregar un nodo Full real y actualizar optimizadores/proof rules que
hoy prueban `start <= end <= length`. Fixtures como `[0:0]` vacío pasan a
seleccionar un elemento; un slice vacío sólo se obtiene con `[:]` sobre un
container vacío. No se mantiene un modo silencioso por backend.

Legacy permite hoy copy-initialization más amplia de handles/structs. La
frontera normativa inicial de este documento es T:Copy para que compiler-next
no invente Clone. Ampliar ambos backends requiere primero una capacidad de
duplicación común y verificable.

## 17. Diagnostics y orden de evaluación

Los diagnostics estáticos y traps runtime distinguen al menos:

- `IndexOutOfBounds` escalar con base/extent;
- `SliceOrderError` para `a>b`;
- `SliceBoundsError` para endpoints fuera del dominio;
- `ShapeMismatch` para add/assignment;
- `OrientationMismatch` cuando Row/Column no coincide;
- falta de `Copy`, `Storable` o `Relocatable` en la operación concreta;
- source compartido usado como slice-place mutable;
- structural mutation con referencia/view viva;
- overflow de shape/capacity/allocation.

Base y selectors se evalúan una sola vez, de izquierda a derecha. En slice
assignment se capturan después el descriptor/shape RHS y sus valores lógicos
antes de la primera escritura. Los checks completos preceden las escrituras.
La implementación no reevalúa endpoints ni queries durante el loop.

## 18. Costos visibles

| Operación | tiempo | storage/alloc |
|---|---|---|
| slice Array/List de `k` | `O(k)` | owner+buffer `O(k)` |
| slice Vector view | `O(1)` | 0 alloc, descriptor 3 palabras |
| slice Matrix/axis view | `O(1)` | 0 alloc, descriptor 3/5 palabras |
| materialización explícita futura | `O(k)` | owner `O(k)` |
| slice assignment `k` | `O(k)` | worst-case snapshot `O(k)` |
| add sin capacity growth | `O(vector.length)` | 0 alloc |
| add con capacity growth | `O(rows*columns + vector.length)` | 1 alloc+free |
| secuencia de add geométrica | amortizado `O(celdas finales)` | factor constante |
| zeros/ones shape `m×n` | `O(m*n)` | una allocation no vacía |

Ninguna API normal crea shape mediante multiplicación artificial, repeated
full-matrix copies o repeated `add` de escalares. La implementación actual de
QR que obtiene `m×m` con `A * transpose(A)` queda identificada como workaround
a retirar cuando `linearAlgebra.zeros/identity` esté disponible.

## 19. Orden recomendado de implementación

1. **Shape/descriptor Matrix:** capacities 2D, zero shapes, strides de owner,
   overflow, drop y corrupciones de verificadores, sin nueva sintaxis.
2. **Filled-init general seguro:** Vector/Matrix runtime shape totalmente
   inicializado, acceso uniforme desde cualquier package y pruebas de
   seguridad/cleanup sin privilegios OAL.
3. **Matrix.add:** intrinsic method Row/Column, Relocatable, invalidación,
   growth geométrico, costs y zero-axis cases.
4. **Selector AST/parser:** Scalar/Closed/Full y diagnostics de formas parciales,
   sin reutilizar Range.
5. **Slices read-only:** primero views Vector/Matrix y luego copias Array/List;
   bounds, zero extents, provenance y tipos resultantes.
6. **Slice assignment:** places mutables, exact shape/orientation, snapshot y
   overlap optimizable con pruebas diferenciales.
7. **Overload contextual:** expected-result inference y orientation markers de
   forma general, no especial para linearAlgebra.
8. **zeros/ones/identity OAL:** reemplazar workarounds QR y medir allocations.
9. **Parity/migración legacy:** contrato cerrado, `[:]`, diagnostics y fixtures
   sin conservar semántica semiabierta oculta.

Cada vertical debe actualizar HIR, MIR, SSA y verificadores independientes
antes de LLVM, incluir corrupciones de metadata/strides/shapes y cubrir O0/O2.

## 20. Fuera de alcance confirmado

No se diseñan strides source, reverse, negative indices, broadcasting, ragged
matrices, sparse storage, static dimensions, equivalencia Vector/Matrix,
advanced indexing, general uninitialized memory ni resize por assignment.
Capacity es detalle interno y los views sólo nacen de owners/views verificados.
