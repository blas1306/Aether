# List Backend Audit

## Alcance

Auditoria de la implementacion actual de `List<T>` antes de empezar su
migracion al backend. No propone cambios de codigo ni implementa lowering.

Areas revisadas:

- parser y AST
- typechecker
- interprete AST
- runtime/builtins
- miembros nativos y soporte de lenguaje/LSP
- IR, SSA, optimizadores y LLVM
- tests y documentacion

## Resumen Ejecutivo

`List<T>` es una feature completa en el frontend/interprete, pero aun no tiene
representacion operativa en IR/SSA/LLVM. El tipo nominal existe en
`src/aether/types.py` y tambien se puede mapear a `src/aether/ir/types.py`, pero
el lowering rechaza o no reconoce sus operaciones.

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

El mayor riesgo no es el literal ni `length`; es decidir y preservar la
semantica de copia/aliasing. La documentacion de diseno dice que los agregados
mutables deberian aliasar por asignacion, pero el interprete actual copia el
contenedor al asignar/coaccionar listas. El backend debe elegir una semantica
compatible con la especificacion vigente o ajustar la especificacion antes de
exponer mutacion compilada.

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
- `is_empty(xs)` retorna `boolean`; no existe metodo nativo `xs.isEmpty()`.
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
- `sort` solo acepta `List<int>`, `List<double>` y `List<string>`.

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
- `is_empty(xs)`
- `contains(xs, value)`
- `copy(xs)`, `xs.copy()`
- `xs.size()`

Estado actual de copia/aliasing:

- `coerce_list_value` construye una lista Python nueva y coacciona cada
  elemento.
- `copy_value` hace copia recursiva para listas.
- `copy(xs)` hace copia superficial del contenedor con `list(xs.value)`.
- En la practica observable por tests, `copy(xs)` y slices producen
  contenedores independientes para mutaciones de elementos escalares.
- La documentacion de diseno en `MUTABLE_AGGREGATES.md` afirma una intencion
  futura distinta: asignar agregados deberia copiar referencias y observar
  aliases. Esta diferencia debe resolverse antes de mutacion LLVM completa.

### Interaccion con `for`

Frontend/interprete:

- `for` sobre `List<T>` esta soportado por `_iterable_values`.
- El interprete itera sobre `list(value.value)`, es decir, una fotografia
  superficial de los elementos al entrar al loop.
- El typechecker infiere el tipo del loop variable como `T`.

IR/backend:

- El lowering de `for` solo soporta rangos `int`, arrays y vectores.
- Para arrays/vectores usa `length` y `get` con un indice local.
- Listas no bajan a `for`; el mensaje indica que solo soporta rangos, arrays y
  vectores.

## Cobertura Por Operacion

`Frontend` significa parser/typechecker/interprete AST. `IR` y `SSA` cuentan
solo soporte operacional, no la existencia nominal del tipo.

| Operacion | Frontend | IR | SSA | LLVM | Dificultad estimada |
| --- | --- | --- | --- | --- | --- |
| Tipo `List<T>` nominal | Si | Parcial: tipo nominal | Parcial: via tipos IR | No | Baja |
| Literal `{...}` como `List<T>` | Si | No | No | No | Media |
| Literal `{}` con tipo esperado | Si | No | No | No | Media |
| `length(xs)` | Si | No | No | No | Baja |
| `xs.length` | Si | No | No | No | Baja |
| `is_empty(xs)` | Si | No | No | No | Baja |
| `xs.isEmpty()` | No | No | No | No | Nueva feature |
| `xs.size()` | Si | No | No | No | Baja |
| `xs[i]` | Si | No | No | No | Media |
| `xs[i] = value` | Si | No | No | No | Media/Alta |
| Slice `xs[start:end]` | Si | No | No | No | Alta |
| Slice assignment | No | No | No | No | Nueva feature |
| `copy(xs)` / `xs.copy()` | Si | No | No | No | Media |
| `contains(xs, value)` / `xs.contains(value)` | Si | No | No | No | Media |
| `indexOf` | No | No | No | No | Nueva feature |
| `reverse(xs)` / `xs.reverse()` | Si | No | No | No | Media |
| `sort(xs)` / `xs.sort()` | Si | No | No | No | Alta |
| `push(xs, value)` / `xs.push(value)` | Si | No | No | No | Alta |
| `pop(xs)` / `xs.pop()` | Si | No | No | No | Alta |
| `insert(xs, i, value)` / `xs.insert(i, value)` | Si | No | No | No | Alta |
| `remove_at(xs, i)` / `xs.removeAt(i)` | Si | No | No | No | Alta |
| `clear(xs)` / `xs.clear()` | Si | No | No | No | Media |
| Equality `xs == ys` | Si | No | No | No | Alta |
| `for x in xs` | Si | No | No | No | Media despues de get/length |

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
- Para `sort` y `contains` debe haber comparacion especializada por tipo de
  elemento o wrappers generados por el compiler.

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

## Runtime LLVM Necesario

No escribir estos helpers todavia; esta es la lista de contratos necesarios.

Helpers base:

- `aether_list_new(element_size: i64, length: i64, capacity: i64) -> ptr`
- `aether_list_new_from_values(element_size: i64, length: i64, values: ptr) -> ptr`
  o, alternativamente, emitir `new` + stores desde LLVM sin helper variadico.
- `aether_list_length(list: ptr) -> i64`
- `aether_list_capacity(list: ptr) -> i64`
- `aether_list_data(list: ptr) -> ptr`
- `aether_list_reserve(list: ptr, element_size: i64, required: i64) -> void`

Lectura/escritura:

- `aether_list_element_ptr(list: ptr, element_size: i64, index: i64) -> ptr`
- `aether_list_bounds_check(index: i64, length: i64) -> void`
- `aether_list_insert_bounds_check(index: i64, length: i64) -> void`

Mutacion:

- `aether_list_push(list: ptr, element_size: i64, value_ptr: ptr) -> void`
- `aether_list_pop(list: ptr, element_size: i64, out_ptr: ptr) -> void`
- `aether_list_insert(list: ptr, element_size: i64, index: i64, value_ptr: ptr) -> void`
- `aether_list_remove_at(list: ptr, element_size: i64, index: i64, out_ptr: ptr) -> void`
- `aether_list_clear(list: ptr) -> void`
- `aether_list_reverse(list: ptr, element_size: i64) -> void`

Copia y busqueda:

- `aether_list_copy(list: ptr, element_size: i64) -> ptr`
- `aether_list_contains_*` especializado por elemento, o loop generado en LLVM.
- `aether_list_index_of_*` si se agrega `indexOf`, especializado por elemento,
  o loop generado en LLVM.

Sort:

- Para fase inicial, conviene generar o exponer helpers especializados:
  `aether_list_sort_i32`, `aether_list_sort_f64`, `aether_list_sort_string`.
- Un helper generico con comparator function pointer es mas flexible, pero
  sube la complejidad de llamadas indirectas y ABI.

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
- `IRListReverse(list)`
- `IRListSort(list)`
- `IRListPush(list, value)`
- `IRListPop(result, list)`
- `IRListInsert(list, index, value)`
- `IRListRemoveAt(result, list, index)`
- `IRListClear(list)`

Si se agrega `indexOf`:

- `IRListIndexOf(result, list, value)` retornando `int`, con convencion a
  definir para "no encontrado". Recomendada: `-1`, por familiaridad y porque no
  requiere nullable.

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

Mantener.

Justificacion:

- `xs[i]` y `xs[i] = value` prueban data pointer, bounds, stores y mutabilidad.
- Tambien fuerza a decidir si los indices se quedan en `i32` fuente con
  extension a `i64` runtime o si el IR normaliza indices a `i64`.

### Fase 3: copy, contains, indexOf, reverse, sort

Recomiendo partirla internamente:

- Fase 3a: `copy`, `contains`, `reverse`.
- Fase 3b: `indexOf` y `sort`.

Justificacion:

- `copy` es esencial para estabilizar semantica de aliasing.
- `contains` se puede emitir como loop simple con igualdad.
- `reverse` es mutante pero local y no cambia capacidad.
- `indexOf` no existe en frontend; requiere spec, parser/member/builtin/tests
  antes de backend.
- `sort` requiere comparacion por tipo y politica para strings; es mas riesgosa
  que `reverse`.

### Fase 4: push, pop, insert, removeAt, clear

Recomiendo mover `clear` antes, a Fase 3a o al inicio de Fase 4.

Justificacion:

- `clear` solo cambia `length`; no requiere crecimiento ni memmove.
- `push`, `insert`, `pop` y `removeAt` requieren contratos de capacidad,
  shifting y errores runtime.
- `insert` y `removeAt` son los mas sensibles a off-by-one y memmove.

Orden sugerido dentro de Fase 4:

1. `clear`
2. `push`
3. `pop`
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

- Puede eliminar `ListLength`, `ListIsEmpty`, `ListGet`, `ListContains` y
  `ListCopy` solo si su resultado no se usa y si `ListCopy` no tiene efectos
  observables. Con runtime sin `free`, allocation no observable puede ser
  eliminable, pero conviene ser conservador al inicio.
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
- Semantica actual de `copy`/assignment sin resolver aliasing.

## Riesgos

- Semantica de aliasing contradictoria entre diseno y comportamiento actual.
- Falta de ownership/free/GC en LLVM.
- `const` es por referencia de acceso, no congelamiento profundo; el backend
  debe preservar esa regla si hay aliases.
- `sort` para strings depende de representacion/runtime de strings, que sigue
  parcial en LLVM.
- `indexOf` no existe aun en frontend ni spec como operacion implementada.
- Nested lists y listas de structs/classes deben posponerse o fallar claramente
  mientras esos tipos no tengan backend completo.
- Builtins globales vs metodos nativos deben converger en el mismo lowering.
- `for` sobre listas debe definir si la longitud se captura al inicio o se lee
  dinamicamente cada iteracion. El interprete actual itera sobre una fotografia
  superficial.

## Documentacion y Matriz

`docs/compiler/FEATURE_MATRIX.md` ya refleja correctamente el estado actual:

- `List<T>` existe como tipo frontend y tipo IR/SSA nominal.
- Las operaciones de lista son frontend-only.
- `indexOf` aparece como no implementado.
- `isEmpty / is_empty` esta marcado parcial en parser porque solo existe
  `is_empty` como builtin global; no hay metodo `isEmpty`.

No se actualizo `FEATURE_MATRIX.md` porque no se encontro una inconsistencia
real en esa matriz.
