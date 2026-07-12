# List Backend Audit

## Alcance

Auditoria de la implementacion actual de `List<T>` y estado de la migracion al
backend. La fase 1 ya implementa un subconjunto compilable.

Areas revisadas:

- parser y AST
- typechecker
- interprete AST
- runtime/builtins
- miembros nativos y soporte de lenguaje/LSP
- IR, SSA, optimizadores y LLVM
- tests y documentacion

## Resumen Ejecutivo

`List<T>` es una feature completa en el frontend/interprete. En IR/SSA/LLVM ya
tiene soporte de fases 1, 2, 3a, 3b (`indexOf`), 4a (`clear`), 4b (`push`/growth), 4c (`pop`) y 4d (`insert`) para literales con tipo esperado, `.length`,
`.is_empty`, `for x in xs` / `for T x in xs`, lectura `xs[i]` y escritura
`xs[i] = value`, `copy`, `contains`, `indexOf`, `reverse`, `clear`, `push`, `pop` e `insert`. El resto de la API de listas
sigue pendiente de backend.

La migracion no deberia reutilizar directamente las instrucciones de `Array<T>`.
`Array<T>` hoy baja como agregado contiguo fijo con header `{ length, data* }`.
`List<T>` necesita capacidad, crecimiento y operaciones mutantes que cambian
longitud, por lo que la representacion recomendada es:

```text
struct List<T> {
    i64 length
    i64 capacity
    ptr data
}
```

El mayor riesgo no es el literal ni `length`; es preservar la semantica de
copia/aliasing. La contradiccion detectada entre la documentacion de diseno y
el interprete AST quedo resuelta en el frontend/runtime: `List<T>` aliasa por
asignacion, por paso de parametros y por return cuando no hay conversion de
elementos. El backend preserva esa semantica para `ListSet`: todos esos caminos
conservan el mismo header y buffer de datos.

## Implementacion Actual

### Parser y AST

- `List<T>` se parsea como anotacion generica junto con `Array<T>`.
  Si se omite `<T>`, el elemento por defecto es `double`.
- Los literales con llaves producen `ast.ListLiteral`.
- `{}` es sintacticamente valido, pero requiere tipo esperado para ser tipado.
- Los elementos de lista requieren comas; `{1 2}` es error.
- `ast.IndexExpression` cubre `xs[i]` y slices explicitos.
- La sintaxis de metodo nativo existe via `ast.MethodCall` y tambien por
  llamadas punteadas desazucaradas, por ejemplo `xs.copy()`.

### Tipos y Generics

- `ListType(element_type)` es inmutable y solo guarda el tipo de elemento.
  No guarda longitud ni capacidad.
- `List<T>` acepta elementos primitivos, listas, arrays y tipos estructurados
  compatibles.
- La inferencia exige homogeneidad por grupo: no mezcla primitivos con listas,
  arrays u otros tipos estructurados.
- Los primitivos numericos se promocionan a un tipo comun.
- `List<int>` y `List<double>` son compatibles por conversion implicita de
  elemento si cada elemento puede convertirse.
- `Array<T>` y `List<T>` son tipos distintos; no hay conversion implicita entre
  ellos.

### Interpreter y Runtime Actual

La representacion interna del interprete es:

```text
AetherValue(
    type_name = ListType(T),
    value = list[AetherValue]
)
```

Operaciones:

- `length(xs)` y `xs.length` retornan `int`.
- `is_empty(xs)` y `xs.is_empty` retornan `boolean`; no existe metodo nativo
  `xs.isEmpty()`.
- `copy(xs)` y `xs.copy()` retornan una nueva lista Python con los mismos
  elementos.
- `push`, `pop`, `insert`, `remove_at`, `contains`, `clear`, `reverse` y
  `sort` existen como builtins globales.
- `push`, `pop`, `insert`, `removeAt`, `contains`, `clear`, `size`, `copy`,
  `reverse` y `sort` existen como metodos nativos.
- `removeAt` es el nombre de metodo; internamente baja a `remove_at`.
- `size()` como metodo de lista baja a `length(xs)`. El builtin global
  `size(value)` sigue teniendo semantica de shape vector, no de longitud de
  lista.
- `sort` acepta `List` y `Array` con elementos `int`, `double` o `string` y
  comparte la misma semantica estable para ambos contenedores.

### Indexing y Slices

- Las listas usan indices 0-based.
- `xs[i]` lee un elemento.
- `xs[i] = value` muta el contenedor.
- `xs[start:end]` y `xs[start:step:end]` existen para listas.
- Los bounds de slices son inclusivos.
- Slices negativos no estan permitidos como indices; un `step` negativo si esta
  permitido.
- El resultado de slice es un nuevo contenedor `List<T>` con los elementos
  seleccionados.
- Slice assignment no esta soportado.

### Mutabilidad, Const y Aliasing

Mutaciones bloqueadas por `const`:

- index assignment: `const List<int> xs = {1}; xs[0] = 2;`
- builtins mutantes: `push`, `pop`, `insert`, `remove_at`, `clear`,
  `reverse`, `sort`
- metodos mutantes equivalentes, incluyendo `removeAt`

Operaciones permitidas con `const`:

- `length(xs)`, `xs.length`
- `is_empty(xs)`, `xs.is_empty`
- `contains(xs, value)`
- `xs.indexOf(value)`
- `copy(xs)`, `xs.copy()`
- `xs.size()`

Estado actual de copia/aliasing:

- `coerce_list_value` devuelve la misma instancia runtime cuando el tipo fuente
  ya coincide con `List<T>` destino y sus elementos ya estan materializados con
  el tipo esperado.
- Las conversiones que cambian el tipo de elemento, por ejemplo
  `List<int>` -> `List<double>`, crean un nuevo contenedor con elementos
  coaccionados; no pueden compartir storage tipado sin romper invariantes.
- La asignacion local, el binding de parametros y el return de `List<T>` copian
  la referencia, no el contenedor.
- `copy_value` preserva referencias de agregados mutables. Los structs siguen
  copiandose por valor, pero un campo `List<T>` dentro de un struct copia la
  referencia a la lista.
- `copy(xs)` hace copia superficial del contenedor con `list(xs.value)`.
- `copy(xs)`, `xs.copy()` y los slices producen un contenedor externo
  independiente, pero sus elementos reference-type siguen compartidos.
- `const` bloquea mutacion a traves de esa referencia; no congela el objeto si
  existe otro alias no-const.

### Interaccion con `for`

Frontend/interprete:

- `for` sobre `List<T>` esta soportado por `_iterable_values`.
- El interprete itera sobre `list(value.value)`, es decir, una fotografia
  superficial de los elementos al entrar al loop.
- El typechecker infiere el tipo del loop variable como `T`.

IR/backend:

- El lowering de `for` soporta rangos `int`, arrays, vectores y listas.
- Para listas usa `IRListLength` y `IRListGet` con un indice local.
- La lectura por indice explicita `xs[i]` fuera del lowering de `for` no forma
  parte de la fase 1.

## Backend Fase 1 Implementado

La representacion LLVM temporal de `List<T>` es:

```llvm
%AetherList = type { i64, i64, ptr }
; fields:
; 0 length
; 1 capacity
; 2 data
```

Propiedades de esta fase:

- `IRListNew` / `SSAListNew` construyen un contenedor heap y un buffer contiguo.
- `length == capacity` al construir el literal.
- Asignacion, parametros y return transportan el `ptr` del contenedor; no copian
  header ni buffer.
- `.length` baja a `IRListLength` / `SSAListLength` y lee el campo `length`.
- `.is_empty` baja a `IRListIsEmpty` / `SSAListIsEmpty` y compara `length == 0`.
- `for x in xs` y `for T x in xs` bajan con `ListLength` + `ListGet`.
- `ListGet` valida `0 <= index < length` antes de cargar `data` o calcular el
  GEP del elemento.

Fuera de alcance en fase 1:

- indexing explicito `xs[i]`/`xs[i] = value` como feature de superficie.
- `copy`, `contains`, `indexOf`, `reverse`, `sort`.
- `push`, `pop`, `insert`, `removeAt`, `clear`.
- crecimiento de capacidad, `realloc`, ownership, `free` o GC.

## Cobertura Por Operacion

`Frontend` significa parser/typechecker/interprete AST. `IR` y `SSA` cuentan
solo soporte operacional, no la existencia nominal del tipo.

| Operacion | Frontend | IR | SSA | LLVM | Dificultad estimada |
| --- | --- | --- | --- | --- | --- |
| Tipo `List<T>` nominal | Si | Si | Si | Si, como ptr | Baja |
| Literal `{...}` como `List<T>` | Si | Si | Si | Si | Media |
| Literal `{}` con tipo esperado | Si | Si | Si | Si | Media |
| `length(xs)` | Si | No | No | No | Baja |
| `xs.length` | Si | Si | Si | Si | Baja |
| `xs.is_empty` | Si | Si | Si | Si | Baja |
| `is_empty(xs)` | Si | No | No | No | Baja |
| `xs.isEmpty()` | No | No | No | No | Nueva feature |
| `xs.size()` | Si | No | No | No | Baja |
| `xs[i]` | Si | Si | Si | Si | Implementado fase 2 |
| `xs[i] = value` | Si | Si | Si | Si | Implementado fase 2 |
| Slice `xs[start:end]` | Si | No | No | No | Alta |
| Slice assignment | No | No | No | No | Nueva feature |
| `copy(xs)` / `xs.copy()` | Si | Si | Si | Si | Implementado fase 3a |
| `contains(xs, value)` / `xs.contains(value)` | Si | Si | Si | Si | Implementado fase 3a |
| `xs.indexOf(value)` | Si | Si | Si | Si | Implementado fase 3b |
| `reverse(xs)` / `xs.reverse()` | Si | Si | Si | Si | Implementado fase 3a |
| `sort(xs)` / `xs.sort()` | Si | Si | Si | Si | Implementado; comparte `IRSequenceSort` y runtime con Array |
| `push(xs, value)` / `xs.push(value)` | Si | Si | Si | Si | Implementado fase 4b |
| `pop(xs)` / `xs.pop()` | Si | Si | Si | Si | Implementado fase 4c |
| `insert(xs, i, value)` / `xs.insert(i, value)` | Si | Si | Si | Si | Implementado fase 4d |
| `remove_at(xs, i)` / `xs.removeAt(i)` | Si | No | No | No | Alta |
| `clear(xs)` / `xs.clear()` | Si | Si | Si | Si | Implementado fase 4a |
| Equality `xs == ys` | Si | No | No | No | Alta |
| `for x in xs` / `for T x in xs` | Si | Si | Si | Si | Implementado fase 1 |

## Representacion Recomendada Para LLVM

### Opcion Recomendada

```llvm
%AetherList = type { i64, i64, ptr }
; fields:
; 0 length
; 1 capacity
; 2 data
```

Ventajas:

- Se adapta a crecimiento amortizado para `push` e `insert`.
- `length` e `is_empty` son cargas simples.
- Reutiliza el patron actual de arrays: header heap + data heap + punteros
  opacos en valores LLVM.
- Permite que `clear` sea O(1) para elementos sin destructores.
- Permite `copy` con nueva cabecera y nuevo buffer.

Costos:

- Necesita helpers runtime nuevos para crecimiento y copia.
- El backend actual no tiene ownership, destructores ni `free`; inicialmente
  tendra las mismas fugas toleradas que arrays.
- `sort` y `contains` usan comparacion especializada por tipo de elemento.

### Alternativas Rechazadas

`{ length, data* }`:

- Es suficiente para `Array<T>` fijo, pero no para `push`, `insert` o
  crecimiento eficiente.

Incluir `element_size` en cada lista:

- Simplifica helpers genericos, pero duplica metadata que el compiler ya conoce
  estaticamente en cada llamada. Conviene pasar `element_size` al helper.

Inline small-vector optimization:

- No encaja con la simplicidad del backend actual y complicaria aliasing,
  copies y llamadas runtime. No es apropiada para la primera migracion.

Refcount/GC en header:

- Puede ser futuro, pero meterlo ahora mezclaria `List<T>` con una decision
  global de ownership que arrays, strings y matrices todavia no resuelven.

## Runtime LLVM

Los helpers de crecimiento implementados y los contratos aun pendientes son:

Helpers base:

- `aether_checked_mul_i64(left, right) -> i64` usa
  `llvm.umul.with.overflow.i64` y deriva al panic de tamano;
- `aether_checked_allocation_bytes(length, element_size) -> i64` valida
  operandos no negativos y reutiliza la multiplicacion checked;
- `aether_alloc(size) -> ptr` admite cero como buffer nulo, comprueba el
  resultado de `malloc` para requests no vacios y usa el panic de OOM;
- `aether_list_length_to_int` y `aether_list_index_to_int` implementan la
  frontera checked `i64 -> i32` sin cambiar los tipos publicos.

- `aether_list_new(element_size: i64, length: i64, capacity: i64) -> ptr`
- `aether_list_new_from_values(element_size: i64, length: i64, values: ptr) -> ptr`
  o, alternativamente, emitir `new` + stores desde LLVM sin helper variadico.
- `aether_list_length(list: ptr) -> i64`
- `aether_list_capacity(list: ptr) -> i64`
- `aether_list_data(list: ptr) -> ptr`
- `aether_list_reserve(list: ptr, required: i64, element_size: i64) -> void` (interno, implementado)

Lectura/escritura:

- `aether_list_element_ptr(list: ptr, element_size: i64, index: i64) -> ptr`
- `aether_list_check_index(list: ptr, index: i64) -> void` (implementado para
  get/set; carga length y deriva a un panic `noreturn`)
- `aether_list_insert_bounds_check(index: i64, length: i64) -> void`

Mutacion:

- `push` se emite desde `SSAListPush`: prepara/reserva, recarga `data`, almacena
  el valor tipado y actualiza `length` al final.
- `pop` se emite desde `SSAListPop`: valida lista no vacia mediante
  `aether_list_prepare_pop`, carga `data[new_length]`, actualiza `length` y
  devuelve el valor tipado. No cambia header, `capacity` ni `data`.
- `aether_list_insert(list: ptr, element_size: i64, index: i64, value_ptr: ptr) -> void`
- `aether_list_remove_at(list: ptr, element_size: i64, index: i64, out_ptr: ptr) -> void`
- `clear` se emite inline como GEP al campo `length` y `store i64 0`; no usa
  helper runtime.
- `aether_list_reverse(list: ptr, element_size: i64) -> void`

Copia y busqueda:

- `aether_list_copy(list: ptr, element_size: i64) -> ptr`
- `aether_list_contains_*` especializado por elemento, o loop generado en LLVM.
- `aether_list_index_of_*` especializado por elemento y compartido por
  `indexOf`/`contains` para la busqueda lineal.

Sort:

- La implementacion expone `aether_sort_i32`, `aether_sort_f64` y
  `aether_sort_string`, todos con ABI `(data, length)` y reutilizados por List
  y Array.
- Los helpers implementan merge sort bottom-up estable, con tiempo
  `O(n log n)` y buffer temporal `O(n)`.
- La semantica comun de `List<T>` y `Array<T>`, incluida estabilidad, strings
  y NaN, esta definida en
  [`AETHER_SEQUENCE_SORT_DESIGN.md`](../aether/AETHER_SEQUENCE_SORT_DESIGN.md).

Errores:

- Helper de panic/runtime error para out-of-bounds.
- Helper de panic para `pop`/`remove_at` sobre lista vacia.
- Si se mantiene sin `free`, documentar que el runtime de backend todavia no
  gestiona liberacion.

## Impacto En IR y SSA

Instrucciones minimas recomendadas:

- `IRListNew(result, elements)`
- `IRListLength(result, list)`
- `IRListIsEmpty(result, list)`
- `IRListGet(result, list, index)`
- `IRListSet(list, index, value)`
- `IRListCopy(result, list)`
- `IRListContains(result, list, value)`
- `IRListIndexOf(result, list, value)`
- `IRListReverse(list)`
- `IRSequenceSort(sequence)`, compartida con Array
- `IRListPush(list, value)`
- `IRListPop(result, list)`
- `IRListInsert(list, index, value)`
- `IRListRemoveAt(result, list, index)`
- `IRListClear(list)`

`IRListIndexOf(result, list, value)` retorna `int`: el primer indice desde cero
o `-1` cuando no encuentra el valor.

Las instrucciones mutantes deben ser side-effecting aunque no produzcan valor.
`IRListSet`, `Push`, `Insert`, `Clear`, `Reverse` y `Sort` no pueden eliminarse
solo porque no tengan resultado usado.

## Roadmap Recomendado

### Fase 1: literal, length, isEmpty

Mantener esta fase, con dos ajustes:

- Implementar primero `length(xs)` y `xs.length`.
- Mapear `is_empty(xs)`; no existe `xs.isEmpty()` hoy, asi que agregar
  `isEmpty` seria una feature nueva y deberia decidirse aparte.

Justificacion:

- Valida representacion y allocation sin mutacion compleja.
- Habilita `for` sobre listas en una extension pequena posterior.
- Es el conjunto de menor riesgo para LLVM.

### Fase 2: index, assignment

Implementada.

Justificacion:

- `xs[i]` y `xs[i] = value` prueban data pointer, stores y mutabilidad.
- Tambien fuerza a decidir si los indices se quedan en `i32` fuente con
  extension a `i64` runtime o si el IR normaliza indices a `i64`.

La implementacion conserva `IRListSet` / `SSAListSet` como instrucciones con
efectos y reescribe sus tres operandos sin eliminarlas. `ListGet` es una
lectura de memoria `may_trap`: DCE IR y SSA la conservan aunque el resultado no
se use, y no se pliega ni se reutiliza a traves de un `ListSet`.

LLVM extiende el indice fuente a `i64`, llama a
`aether_list_check_index(list, index)` y solo despues carga `header.data`,
calcula `data[index]` y emite `load` o `store`. Un indice negativo, igual a
length o mayor termina con codigo 1 y el mensaje
`Aether panic: List index out of bounds`; el store no ocurre si el check falla.

### Fase 3: copy, contains, indexOf, reverse, sort

Recomiendo partirla internamente:

- Fase 3a: `copy`, `contains`, `reverse`.
- Fase 3b: `indexOf` y `sort`.

Fase 3a y fase 3b implementadas para las operaciones sin cambio de longitud:

- `IRListCopy` / `SSAListCopy` son allocations observables y se conservan. LLVM
  valida `length * element_size`, crea header y buffer independientes y solo
  entonces copia las representaciones de elemento; los elementos
  reference-type mantienen sus punteros, por lo que la copia es superficial.
- `IRListContains` / `SSAListContains` son lecturas lineales. LLVM especializa
  igualdad para `int`, `double`, `boolean`, `string` y referencias; no se
  introduce `Comparable`.
- `IRListIndexOf` / `SSAListIndexOf` reutilizan una busqueda interna `i64`,
  producen el primer indice o `-1`, y convierten a `i32` con check. Un indice
  mayor que `INT32_MAX` termina con
  `Aether panic: List index does not fit in int`.
- `contains` compara directamente el resultado `i64` de esa busqueda con `-1`;
  no puede disparar el panic de narrowing solo para producir un booleano.
- `IRListReverse` / `SSAListReverse` mutan el buffer mediante swaps in-place,
  no producen resultado y nunca se eliminan.
- `IRSequenceSort` / `SSASequenceSort` son comunes a List y Array, mutan el
  mismo buffer, no producen resultado y nunca se eliminan. LLVM extrae
  `data`/`length` y llama al mismo helper especializado para ambos headers.
- No se implementaron `lastIndexOf`, operaciones que cambian longitud,
  crecimiento, capacidad, `realloc`, GC ni ownership.

Justificacion:

- `copy` es esencial para estabilizar semantica de aliasing.
- `contains` se puede emitir como loop simple con igualdad.
- `reverse` es mutante pero local y no cambia capacidad.
- `indexOf` ya existe en frontend, IR/SSA, interpretes, optimizadores y LLVM.
- `sort` centraliza comparacion por tipo, orden UTF-8 y politica de NaN en los
  helpers compartidos.

### Fase 4: push, pop, insert, removeAt, clear

El contrato detallado de invariantes, crecimiento, allocation, shifting,
ownership y optimizacion para esta fase esta en
[`AETHER_LIST_GROWTH_DESIGN.md`](../aether/AETHER_LIST_GROWTH_DESIGN.md). Es un
contrato implementado para 4a/4b/4c y previo para las operaciones pendientes. La
Fase 4a (`clear`) no cambia `capacity` ni `data`; la Fase 4b (`push`) usa un
reserve interno con crecimiento geometrico, checks de overflow y OOM. La Fase
4c (`pop`) carga antes de reducir `length`, no hace shrinking y produce `T`.

`clear`, `push` y `pop` son los tres primeros incrementos implementados de Fase 4.

Justificacion:

- `clear` solo cambia `length`; no requiere crecimiento ni memmove.
- `insert` y `removeAt` requieren contratos adicionales de capacidad,
  shifting y errores runtime.
- `insert` y `removeAt` son los mas sensibles a off-by-one y memmove.

Orden sugerido dentro de Fase 4:

1. `clear` (implementado, Fase 4a)
2. `push` (implementado, Fase 4b)
3. `pop` (implementado, Fase 4c)
4. `insert`
5. `removeAt`

## Optimizadores

### SCCP

Impacto:

- `ListNew` con elementos constantes no debe convertir toda la lista en una
  constante escalar salvo que se agregue una lattice de agregados inmutables.
- `ListLength` puede plegarse si proviene directamente de un literal no mutado
  y no hay alias o stores intermedios. Sin alias analysis, debe ser
  conservador.
- Mutaciones de lista deben marcarse como efectos. SCCP no debe reemplazar
  lecturas despues de `set/push/pop/insert/removeAt/clear/reverse/sort` usando
  hechos anteriores.

Recomendacion:

- En la primera version, tratar todas las operaciones mutantes y llamadas
  runtime de listas como desconocidas/efectivas.
- Solo plegar `is_empty(ListNew(...))` y `length(ListNew(...))` si el valor no
  escapa y no hay mutacion visible.

### DCE

Impacto:

- Puede eliminar `ListIsEmpty` y `ListContains` si su resultado no se usa.
  Conserva `ListGet`, `ListLength` y `ListIndexOf` porque pueden hacer trap;
  `ListCopy` se conserva como allocation observable.
- No puede eliminar `ListSet`, `Push`, `Pop`, `Insert`, `RemoveAt`, `Clear`,
  `Reverse` ni `Sort`.
- `Pop` y `RemoveAt` tienen side effect aunque el resultado no se use.

Recomendacion:

- Agregar listas mutantes al conjunto de instrucciones side-effecting desde el
  primer commit de IR.

### Constant Folding

Impacto:

- `length` e `is_empty` de literal directo son candidatos simples.
- `xs[i]` de literal directo con indice constante solo es seguro si no hubo
  mutacion ni alias.
- `contains` sobre literal directo podria plegarse para elementos escalares,
  pero no es necesario en la primera migracion.
- `sort` y `reverse` no deben plegarse como si fueran puras porque mutan.

Recomendacion:

- Fase inicial: plegar solo `length`/`is_empty` en patrones directos y dejar el
  resto sin folding hasta tener metadata de escape/alias.

## Reutilizacion Posible

Frontend reutilizable:

- Parser de `List<T>` y `ListLiteral`.
- Typechecker de literales, conversiones y miembros nativos.
- Reglas de `const` para mutacion.
- Validacion de aridad/tipos de builtins.
- Tests existentes del interprete como especificacion observable.

Backend reutilizable:

- Patron de `Array<T>` para header heap + data heap.
- `IRArrayLength`, `IRArrayGet`, `IRArraySet` como modelo conceptual, pero no
  como instrucciones compartidas.
- Helpers LLVM de calculo de element pointer y allocation contigua, adaptados a
  header con capacidad.
- Lowering de `for` indexable sobre array/vector: una vez existan
  `ListLength` y `ListGet`, el mismo esquema puede admitir listas.

No reutilizar sin cambios:

- `IRArrayNew` para literales de lista: array es fijo y list necesita capacidad.
- Optimizadores de array si asumen ausencia de cambios de longitud.
- Cualquier lowering que copie contenedores en asignacion, parametros o return.

## Riesgos

- El backend preserva referencia mutable para el subconjunto de listas que
  soporta; ownership y tipos de objeto completos siguen pendientes.
- Falta de ownership/free/GC en LLVM.
- `const` es por referencia de acceso, no congelamiento profundo; el backend
  debe preservar esa regla si hay aliases.
- `sort` para strings opera sobre la representacion UTF-8 terminada en cero y
  usa `strcmp`, cuyo orden de bytes unsigned coincide con el contrato.
- `indexOf` usa igualdad escalar/string por valor e igualdad de referencia para
  agregados, sin comparacion profunda.
- Nested lists y listas de structs/classes deben posponerse o fallar claramente
  mientras esos tipos no tengan backend completo.
- Builtins globales vs metodos nativos deben converger en el mismo lowering.
- `for` sobre listas debe definir si la longitud se captura al inicio o se lee
  dinamicamente cada iteracion. El interprete actual itera sobre una fotografia
  superficial.

## Documentacion y Matriz

`docs/compiler/FEATURE_MATRIX.md` refleja el estado actual:

- `List<T>` existe como tipo frontend y tipo IR/SSA nominal.
- `clear` es la unica operacion que cambia longitud con backend; `sort` esta
  implementado para List y Array. Las demas mutaciones de longitud siguen
  pendientes.
- `indexOf` aparece implementado en todo el pipeline.
- `isEmpty / is_empty` esta marcado parcial en parser porque solo existe
  `is_empty` como builtin global; no hay metodo `isEmpty`.

La matriz se actualiza junto con cada fase del backend.
