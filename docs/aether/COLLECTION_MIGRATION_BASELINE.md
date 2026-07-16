# Baseline de migración de `Array<T>` y `List<T>`

Estado: **baseline histórica de Fase 0; Fases 1–5 completadas el 15 de julio de 2026**.

> Actualización Fase 2: las tablas históricas siguientes conservan el punto de
> partida. El estado vigente implementa `Array.copy()` y `List.copy()` en
> AST/IR/SSA/LLVM/native. Ambos crean objeto y buffer exteriores nuevos,
> ejecutan `copy_init(T)` elemento a elemento y retornan ownership. List
> normaliza `capacity = size`; nesting conserva handles interiores compartidos.
> El diagnóstico transitorio de `Array.copy()` fue retirado en el perfil 10.
>
> Actualización Fases 4–5: `const` sigue caminos de value types y colecciones
> anidadas, pero se detiene en una referencia class. `for-in` de Array/List usa
> un elemento borrowed no-owning; una copia a local/field/return adquiere
> ownership mediante `copy_init`. Se detecta mutación del iterable directo y
> mediante aliases locales simples.

Este documento registra lo que hace el repositorio antes de migrar los
contenedores a objetos con reference counting. La semántica aprobada está en
[`COLLECTION_RUNTIME_DESIGN.md`](COLLECTION_RUNTIME_DESIGN.md). Cuando esta
baseline dice “actual” describe implementación, no una promesa normativa.

La inspección y las pruebas separan tres recorridos:

- **AST**: `runner.py`, `interpreter.py` y valores Python de `types.py`;
- **IR**: lowering verificado e `IRInterpreter`, sin pasar por SSA;
- **native**: AST chequeado → IR → SSA → LLVM → runtime y `clang`.

Los estados de la tabla son: **coincide** (conducta observable ya alineada),
**seguro histórico** (funciona porque los contenedores no se destruyen),
**gap** (conducta distinta de la RFC) y **diagnosticado** (el camino se corta
antes de un lowering que no puede garantizar el contrato).

## Matriz ejecutiva

| Caso | Semántica aprobada | AST actual | IR actual | Native actual | Estado |
| --- | --- | --- | --- | --- | --- |
| `List b = a` | copia de handle, alias | mismo `AetherValue`/lista Python | mismo objeto lista | mismo `ptr` a header y buffer | coincide; ownership pendiente |
| `Array b = a` | copia de handle, alias | igual a List | mismo objeto lista | mismo `ptr` a `%AetherArray` | coincide; ownership pendiente |
| `b[0] = x` | visible por todos los aliases | visible | visible | visible | coincide |
| parámetro | recibe misma referencia | misma referencia | mismo objeto | mismo `ptr` | coincide; sin retain |
| reasignar parámetro | cambia solo binding local | sí | sí | sí | coincide |
| return de local/parámetro/field | referencia owned, sin deep copy | comparte referencia | comparte objeto | devuelve el `ptr` | seguro histórico; no owned real |
| struct con field colección | copiar struct copia el handle | struct nuevo, field alias | valor struct, field alias | bytes del struct, mismo `ptr` | coincide superficialmente |
| class con field colección | class y field por referencia | soportado, conserva identidad | no soportado | diagnóstico de classes | diagnosticado |
| `List.copy()` | objeto/buffer exterior nuevos | lista Python exterior nueva | lista exterior nueva | header y buffer nuevos | coincide superficialmente |
| `Array.copy()` | objeto/buffer exterior nuevos | lista Python exterior nueva | sin operación E2E | diagnóstico temprano native | diagnosticado |
| `const List view = mutable` | const por alias | binding restringido | chequeado antes de IR | chequeado antes de native | coincide |
| slice Array | copia `[start,end)` | semiabierto | semiabierto | semiabierto | coincide |
| slice List | copia `[start,end)` | semiabierto | semiabierto | semiabierto | coincide desde Fase 3 |
| `for-in` | borrow read-only por iteración | binding borrowed no-owning | `borrow_element`, índice y length | load de slot sin retain | coincide para Array/List |
| mutar iterable/binding en `for-in` | prohibido | diagnóstico tipado | verifier + diagnóstico | verifier + diagnóstico | directo y aliases locales simples |
| `Array/List ==` | contenido ordenado | estructural recursivo | no general | diagnóstico temprano | gap diagnosticado |
| `contains/indexOf` primitivo/string | `Eq(T)` | contenido | contenido | contenido | coincide en subset |
| búsqueda de referencias anidadas | `Eq(T)` estructural | identidad | identidad | identidad | gap caracterizado |
| búsqueda de struct | `Eq(T)` estructural | estructural Python | no E2E general | diagnóstico temprano específico | gap diagnosticado |
| destrucción de contenedor | release y destroy al último owner | GC Python, sin modelo Aether | ninguna | ninguna | gap: leak deliberado |
| lifecycle de elementos string | retain/release exacto | referencias Python | modelado por hooks | ARC en operaciones implementadas | parcial; container final leak |
| print anidado/string | presentación uniforme | braces internos; strings con comillas | listas anidadas con `[]`; strings con comillas | braces internos; strings sin comillas | gap de presentación |

## Assignment, aliases y parámetros

`AetherValue` contiene `type_name` y un `value` que para Array/List es la misma
lista Python mutable. La asignación ordinaria no llama a `copy_value` para el
contenedor. IR usa el mismo valor host y LLVM almacena un handle `ptr`; ninguno
duplica header o buffer. Por eso assignment es O(1) y una escritura por índice,
`push`, `clear`, `reverse` o `sort` es visible a través de otros aliases.

El parámetro recibe ese mismo handle. Mutarlo cambia el objeto del caller;
reasignar el nombre del parámetro cambia sólo el slot local. No hay retain al
entrar ni release al salir. Hoy esto no deja un dangling porque tampoco existe
destrucción final del contenedor, pero agregar solamente un `free` convertiría
returns y aliases en use-after-free/double-free.

`Array` tiene longitud fija del objeto, no del binding: un binding puede
reasignarse a otro Array. `List` mantiene length/capacity en su header.

## Returns

| Origen del return | AST | IR/native actual | Riesgo para Fase 1 |
| --- | --- | --- | --- |
| local | entrega el mismo handle | retorna el `ptr`; el lowering de lifecycle puede mover el slot | debe transferir exactamente un ownership |
| parámetro | mismo handle | copia lógica de parámetro en lifecycle, expandida hoy a store trivial | debe retener para el caller |
| field de struct | field alias | carga/copia el handle del struct | debe retener antes de morir el aggregate |
| literal | nuevo valor Python | header/buffer heap nuevos | ownership inicial debe pasar al caller |
| temporal (`copy`, slice) | valor temporal | sólo operaciones E2E existentes | el temporal debe moverse, no retener/liberar dos veces |
| función importada | misma semántica AST | módulos se combinan y el `ptr` cruza la firma | igual que una función local; globals importados siguen rechazados |

Los módulos native soportan funciones importadas combinadas, no storage ni
inicialización de colecciones globales importadas. Esa limitación ya pertenece
al perfil parcial de modules/imports.

## Structs, classes, nesting y strings

Un struct se copia por valor. Sus fields primitivos se copian; un field
Array/List conserva el mismo handle, por lo que dos copias del struct alcanzan
el mismo contenedor. El `TypeLayout` recorre structs y sabe que strings
requieren retain/destroy, pero aún clasifica los handles Array/List como
triviales y sin destroy propio.

Classes son referencias en AST: copiar la class no copia el objeto y un field
List conserva el alias. IR/native todavía rechaza classes antes del lowering.

En `List<List<T>>` y `Array<List<T>>`, assignment y copia del struct exterior
copian handles interiores. `copy()` y slicing crean sólo el contenedor exterior:
los contenedores interiores, instances de class y otras referencias siguen
compartidos. Los structs elemento se copian por valor y sus fields referencia
siguen siendo superficiales.

Strings tienen ARC native activo. Literales, get/set, push/insert, pop/remove,
copy, slice, clear y operaciones de structs invocan los hooks de elemento que
corresponden. Crecimiento de List relocaliza los bits vivos y libera el buffer
viejo sin destruirlos, que es la semántica correcta de relocate. Sin embargo,
como el objeto List nunca se destruye, sus elementos todavía vivos tampoco
reciben el release final. `clear()` sí destruye los elementos vivos.

Para `List<Transaction>`, cada Transaction se mueve/copia por valor y su fecha
string participa del lifecycle recursivo. El header y buffer de la List quedan
filtrados al final; no hay double free actual porque no se intenta liberarlos.

## `copy()` en la baseline histórica

| Propiedad | AST Array/List | IR List | Native List | Native Array |
| --- | --- | --- | --- | --- |
| objeto exterior | nuevo `AetherValue` | nueva lista host | nuevo header | no hay camino E2E |
| buffer | nueva lista Python | nueva lista | nueva allocation | diagnosticado |
| length | preservada | preservada | preservada | — |
| capacity | no observable | no modelada | se fija a `length` | — |
| profundidad | superficial | superficial | superficial con copy hooks de elementos | — |
| strings/structs | referencias/copia lógica host | valores host | retain/copy-init recursivo | — |
| nested/class refs | compartidas | compartidas | handles compartidos | — |

Las formas globales `copy(xs)` y de método `xs.copy()` convergen en la misma
operación semántica. La detección de capability conserva la forma desazucarada
tipada del receiver; no inspecciona texto. Array.copy se rechaza en native
antes de IR mientras no exista un camino completo de lifecycle.

La Fase 2 reemplaza ese estado: `array_copy` y `list_copy` son operaciones IR
tipadas distintas de `copy_init`; ambas sobreviven SSA y llegan a helpers LLVM
especializados por elemento. El intérprete implementa rollback del prefijo ante
errores recoverables. Native conserva panic abortivo sin unwind.

## `const`

`const` es constness del binding, no inmutabilidad transitiva del objeto.

- `xs = other`, `xs[0] = value` y métodos mutantes por `xs` se rechazan;
- push/pop/insert/removeAt/clear/reverse/sort usan el chequeo común;
- una mutación encadenada cuyo root es const se rechaza por el análisis de
  lvalue existente, incluidos fields/indexes que ese análisis representa;
- un alias mutable preexistente puede seguir cambiando el mismo objeto, y el
  cambio es visible desde el alias const;
- esto aplica también a nested collections, classes y strings elemento según
  el tipo de la ruta, sin congelar globalmente los valores alcanzables.

No se rediseñó el sistema general de const en esta fase.

## Slicing

### Array

AST, IR y native usan índices 0-based y límites `[start,end)`. El resultado es
un contenedor exterior independiente. `[0:0]` y `start == end` dan vacío;
`[0:length]` copia todo; `[1:3]` copia índices 1 y 2; `start > end`, negativos o
end mayor que length producen el error de bounds correspondiente. Los hooks de
copy de elemento retienen strings y referencias contenidas en structs.

### List: Fase 3

AST, IR, SSA y native ejecutan slicing semiabierto `[start,end)`. `[0:0]` y
`[length:length]` producen List vacía; `[0:length]` copia toda la lista. El
resultado tiene objeto, buffer y capacity propios, con `size == capacity ==
end-start`. Negativos, `start > end` o límites mayores que length producen
panic sin clamping. Los handles de elementos anidados se retienen: sólo el
contenedor exterior es independiente.

## `for-in`

AST obtiene un snapshot de la lista exterior al comenzar (`list(value.value)`).
IR/native capturan length una vez y hacen get por valor en cada iteración. Por
eso modificar length durante el loop produciría reglas distintas: AST seguiría
el snapshot, mientras native podría leer según el length original sobre un
buffer mutado. El typechecker ahora rechaza la mutación estructural directa del
iterable (`push/pop/insert/removeAt/clear/reverse/sort`).

El binding de loop no se puede asignar ni mutar directamente. Para structs, el
get produce la copia por valor existente; modificar el struct local no escribe
el slot de colección. Para una colección anidada, el elemento es un handle y
por ello sería un alias: su mutación directa se rechaza como borrow read-only.

Este patrón sí es válido y conserva la semántica normal de referencia:

```aether
for List<int> inner in nestedLists {
    List<int> saved = inner;
    saved.push(1);
}
```

No existe todavía borrow IR. La comprobación de Fase 0 cubre rutas lvalue
directas tipadas y su scope resuelto. No intenta demostrar aliases indirectos,
escape general, llamadas que capturen el handle ni rutas calculadas.

## Igualdad, búsqueda y orden

| Elemento/operación | AST | IR/native | Baseline |
| --- | --- | --- | --- |
| Array/List `==`, `!=` | contenido ordenado y recursivo | no general | diagnóstico native |
| int/bool/enum search | valor | valor | coincide |
| double search | valor IEEE; NaN no se encuentra | igual | coincide |
| string search | contenido | contenido length-aware | coincide |
| nested Array/List search | identidad del handle | identidad del handle | gap frente a Eq estructural |
| class search | identidad | classes no soportadas | gap/diagnosticado por class |
| struct search | igualdad estructural host | no Eq(T) general | diagnóstico específico |
| sort | int/double/string, estable e in-place | mismo subset | fuera del gap de igualdad |

`contains` e `indexOf` comparten su noción de igualdad por tipo, pero no la
igualdad estructural general de contenedores. No existe aún una infraestructura
`Eq(T)` reutilizable end-to-end, por lo que Fase 0 no cambió esa conducta.

## Ownership histórico y allocations

Native usa actualmente:

```text
%AetherArray = { i64 length, ptr data }
%AetherList  = { i64 length, i64 capacity, ptr data }
```

Los literals/defaults construyen header y buffer heap; incluso el vacío es un
handle válido. Array conserva su buffer. List puede realocarlo al crecer y
libera el buffer anterior después de relocate. No hay refcount en el header,
retain/release de handle, destrucción final, ni free final de header/buffer.

`clear()` destruye los elementos vivos y pone length en cero, pero conserva
capacidad y buffer. `pop`/`removeAt` transfieren el elemento removido; set
destruye el anterior después de preparar el nuevo. copy/slice inicializan
elementos nuevos. La ausencia de destrucción final causa leaks deliberados y
evita hoy double-free. Returns, aliases y nesting son memory-safe sólo bajo esa
decisión histórica.

No hay hooks de debug públicos de destrucción, así que los tests observan
supervivencia y clear, no contadores internos inexistentes.

## ABI actual y forma conceptual futura

No se cambió representación ni se fija una ABI C pública. La migración deberá
reemplazar conceptualmente cada header por objetos como:

```text
AetherArrayObject<T> = header de ownership + length + buffer owned
AetherListObject<T>  = header de ownership + length + capacity + buffer owned
```

El handle de lenguaje seguirá siendo un `ptr` de una palabra. Literals,
constructors, locals, parámetros, returns, fields de struct/class, nested
collections, modules, print, igualdad y un FFI futuro deberán pasar por el
mismo lifecycle. El layout concreto y nombres de helpers siguen privados.

## Invariantes verificables para Fase 1

1. Todo handle Aether observable es válido y nunca null; el vacío es un objeto válido.
2. `strong_count > 0` para objetos alcanzables, salvo inmortales documentados.
3. El objeto posee exactamente su buffer; `size <= capacity`.
4. Array conserva length fija; List sólo tiene elementos vivos en `[0,size)`.
5. Cada elemento vivo se destruye exactamente una vez.
6. `copy_init` de handle retiene; move transfiere y deja estado moved-from válido.
7. Assign hace retain-before-release y self-assignment es seguro.
8. El último release destruye elementos, buffer y objeto, en ese orden lógico.
9. `copy()` crea objeto y buffer exteriores distintos; nesting sigue superficial.
10. Slicing crea objeto nuevo y usa `[start,end)` para ambos tipos.
11. Ningún return, field, alias o nested handle queda dangling.
12. Nested containers retienen sus handles y los strings conservan ARC exacto.

## Superficie exacta estimada para Fase 1

### AST runtime

- `src/aether/types.py`: clasificación explícita de handles y semántica de copia.
- `src/aether/interpreter.py`: locals, args, returns, fields, for-in y temporales.
- `src/aether/stdlib/core.py`: constructors, copy, slice y operaciones mutantes.

### Frontend y perfiles

- `src/aether/typechecker.py`: ownership/borrow estático sólo donde el diseño lo exija.
- `src/aether/capabilities.py`: retirar diagnósticos cuando el recorrido sea E2E;
  dividir capabilities amplias sólo si hay una necesidad de producto real.

### IR y expansión de lifecycle

- `src/aether/ir/types.py`, `model.py` y `lifecycle.py`: declarar Array/List no
  triviales y sus operaciones copy/move/destroy.
- `src/aether/ir/lowering.py`: slots owning, retain de params/fields, moves de
  returns/temporales y cleanup en todas las salidas.
- `src/aether/ir/interpreter.py`: ejecutar el contrato y mantener paridad.

### SSA, verificadores y optimizers

- `src/aether/ssa/model.py`, builders, printer y verifier: preservar las nuevas
  operaciones y tipos de efecto.
- `src/aether/ir/optimizer.py` y `src/aether/ssa/optimizer.py`: no eliminar,
  duplicar ni reordenar retain/release; respetar unwind/returns.

### LLVM y runtime

- `src/aether/backend/llvm/layout.py` y `types.py`: object header y TypeLayout.
- `src/aether/backend/llvm/printer.py`: expansión de lifecycle, calls, returns,
  fields, nested layouts y cleanup.
- `src/aether/backend/llvm/array_runtime.py`, `list_runtime.py` y
  `runtime_common.py`: alloc/retain/release/final destroy, copy y slice.
- `src/aether/backend/llvm/string_runtime.py`: integración recursiva, sin cambiar
  el contrato ARC de string.

### Producto y evidencia

- `tests/aether/`: unitarios de lifecycle/IR/SSA/layout y E2E AST/native para
  aliases, self-assignment, returns, fields, nesting, strings y último owner.
- `docs/aether/`, `docs/compiler/`: actualizar RFC, paridad, lifecycle y ABI.
- `examples/expense_tracker`, `examples/aggregate_collections/particles.ae` y
  `examples/numerical_methods`: dogfood sin introducir una semántica paralela.

Los nombres exactos de módulos LLVM pueden variar durante la implementación;
la evidencia anterior corresponde a las responsabilidades actuales, no obliga
a mantener una partición interna accidental.

## Riesgos concretos

- agregar destroy sin retains coordinados crea dangling pointers y double-free;
- retener params pero no mover returns filtra o destruye prematuramente;
- copiar bytes de structs con handles sin hooks duplica ownership sin retain;
- liberar buffers durante growth como destroy, en vez de relocate, libera
  elementos todavía vivos;
- self-assignment con release-before-retain puede destruir el objeto fuente;
- cleanup omitido en break/continue/return produce leaks dependientes de CFG;
- `copy()` o slice parcial puede retener strings pero no nested containers;
- optimizers que consideren lifecycle puro pueden eliminar operaciones necesarias;
- cambiar simultáneamente slicing y ABI habría dificultado aislar regresiones;
- el formato de print ya diverge y no debe confundirse con ownership.

## Dogfooding de Fase 0

- **Expense Tracker**: `List<Transaction>` conserva aliasing; `copy()` y el
  slice `[0:1]` independizan el exterior y preservan los fields string.
- **Partículas**: el slice `Array<Particle>[0:1]` copia el struct por valor y
  permite reemplazarlo sin modificar el slot original.
- **Numerical Methods**: no depende del futuro RC de contenedores y sirve como
  guardia de regresiones indirectas de frontend, IR y ejecución.

## Siguiente fase recomendada

Tras RC, copia explícita y slicing copying, la siguiente fase debe unificar
`const` y `for-in` borrowed. Igualdad estructural E2E puede abordarse después,
sin mezclarla con views o cambios de ABI.

`ARRAY`, `LIST` y especialmente `ARRAY_SLICING` son capabilities más amplias
que algunas operaciones aquí diagnosticadas. El perfil 8 usa detalles
semánticos tipados dentro de esas capabilities y no promueve ni degrada estados.
Una división futura sólo se justifica si esos subcontratos se publican o
negocian de forma independiente.
