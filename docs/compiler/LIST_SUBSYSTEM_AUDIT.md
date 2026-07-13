# Auditoria tecnica del subsistema `List<T>`

## Alcance y metodo

Esta auditoria describe el estado del repositorio al 12 de julio de 2026. Es
una revision estatica de frontend, interpretes, IR, SSA, optimizadores, backend
LLVM, runtime LLVM emitido, tests, benchmarks y documentacion. No propone
nuevas features del lenguaje y no modifica implementacion ni tests.

La implementacion se reviso principalmente en:

- `src/aether/{ast.py,parser.py,typechecker.py,interpreter.py,native_members.py}`;
- `src/aether/stdlib/core.py`;
- `src/aether/ir/{model.py,lowering.py,interpreter.py,printer.py,verifier.py}` y
  `src/aether/ir/optimizer/`;
- `src/aether/ssa/`, incluidos ambos builders y todos los optimizadores;
- `src/aether/backend/llvm/{printer.py,runtime.py,build.py,run.py}`;
- `tests/aether/test_list_*.py`, `tests/aether/test_sequence_sort.py`, tests de
  IR/SSA/LLVM, `tests/test_llvm_integration.py`, ejemplos y CI;
- `benchmarks/` y la documentacion de colecciones.

No se ejecutaron tests ni benchmarks por restriccion del encargo. Las
afirmaciones sobre cobertura indican que existe codigo de test, no que se haya
revalidado su resultado durante esta auditoria.

Actualizacion del 12 de julio de 2026: el P0 de bounds de `ListGet`/`ListSet`
y su modelado `may_trap` en DCE fueron resueltos despues del relevamiento
original. Las secciones afectadas se actualizaron; los demas riesgos y el
alcance de la auditoria permanecen sin cambios.

Actualizacion P2: el runtime LLVM quedo separado en `list_runtime.py` para el
layout/capacity/growth List, `array_runtime.py` para Array y
`runtime_common.py` para allocation checked, declaraciones y sort. La salida
LLVM representativa se conserva byte a byte.

## Resumen ejecutivo

Clasificacion global: **aceptable**.

El subsistema es funcionalmente amplio y coherente en sus caminos normales:
los quince opcodes auditados atraviesan AST, IR, SSA y LLVM mediante al menos
una forma de sintaxis; el aliasing por header estable esta bien conservado; las mutaciones estan
modeladas como efectos; growth centraliza reserva; new/copy/sort validan sus
tamanos; y la cobertura funcional es considerable. Los P0 nativos relevados
(bounds get/set, overflow de allocation/copy/sort y conversiones List i64 a
`int`) estan resueltos. La clasificacion se conserva como snapshot hasta cerrar
las brechas de formas publicas y consolidacion que siguen fuera de este cambio.

Hallazgos adicionales:

- La completitud por opcode no implica completitud de todas las formas
  publicas. El frontend/AST acepta los builtins globales `length(xs)`,
  `is_empty(xs)` e `index_of(xs, value)`, pero `IRLowerer` solo reconoce
  `.length`, `.is_empty` y `.indexOf(value)`. `List.size()` tambien existe en
  frontend/AST y no tiene lowering IR. La spec presenta esas formas como
  equivalentes, por lo que el backend documentado no es completamente
  intercambiable.
- `ListGet` se modela conservadoramente como `may_trap`: DCE IR y SSA lo
  preservan aunque su resultado no tenga usos. `ListSet` permanece
  side-effecting.
- `length` e `indexOf` siguen siendo `int` (`i32`) aunque el header use `i64`.
  LLVM ahora comprueba `0..INT32_MAX`; `indexOf` conserva `-1`, y ambos hacen
  panic en vez de truncar si un resultado no es representable.
- El conocimiento de operandos, resultados y efectos de cada opcode List esta
  duplicado entre builders, renaming, printers, verifiers y optimizadores. Hoy
  las mutaciones se preservan, pero agregar o refactorizar un opcode exige
  actualizar muchas listas manuales.
- La spec, `LIST_BACKEND_AUDIT.md` y los resumenes de `FEATURE_MATRIX.md`
  contienen texto historico que contradice el backend actual.
- La gestion de lifetime final sigue incompleta: los headers y buffers finales
  no se liberan. El buffer reemplazado durante growth si se libera.

## 1. Arquitectura real

El diagrama pedido no es estrictamente lineal: el interprete AST y el
interprete IR son backends alternativos, no etapas por las que pase un binario
nativo. El flujo efectivo es:

```text
source
  -> lexer -> parser -> AST -> typechecker -> TypedProgram
       |                                  |
       |                                  +-> AST Interpreter -> Python runtime values
       |
       +-> IR lowering -> IR verifier
              |             |
              |             +-> IR optimizer -> IR Interpreter
              |
              +-> CFG/dominators/phi placement/renaming
                         -> SSA verifier -> SSA optimizer
                         -> LLVM printer + runtime LLVM emitido
                         -> clang -> executable native
```

El camino de `LLVMBuilder.emit_llvm` usa el builder SSA general por defecto,
verifica SSA, ejecuta `SSAOptimizerPipeline` y emite LLVM. No ejecuta el
interprete AST ni `OptimizerPipeline` de IR. El optimizador IR pertenece al
backend/benchmark IR; por tanto hay que conservar los contratos List en ambos
middle-ends aunque native use actualmente solo el de SSA.

### Frontend

- `parser.py` produce `ast.ListLiteral`, `ast.IndexExpression` y
  `ast.IndexAssignment`; `List<T>` se representa con `ListType`.
- `native_members.py` registra `length`, `is_empty`, `push`, `pop`, `insert`,
  `removeAt`, `contains`, `indexOf`, `clear`, `size`, `copy`, `reverse` y
  `sort`. Los metodos se vinculan a builtins globales.
- `typechecker.py` resuelve tipos, conversiones, aridad, `int` para indices y
  mutabilidad. `LIST_MUTATING_BUILTINS` incluye las siete mutaciones publicas.
- `stdlib/core.py` contiene firmas y semantica runtime de los builtins que usa
  el interprete AST. No todas esas formas globales tienen equivalente en
  `IRLowerer`.

### AST Interpreter

`Interpreter` representa una lista como `AetherValue(ListType(T), list)` de
Python. Literal, get, set y `for` se ejecutan directamente; los metodos/builtins
delegan en `stdlib/core.py`. Python administra capacidad y memoria, de modo que
esta capa modela longitud, contenido y aliasing, pero no expone ni valida el
layout LLVM.

### IR

`IRLowerer` emite opcodes nominales `IRList*`; `for` se convierte en CFG con
`IRListLength` e `IRListGet`. `IRInterpreter` implementa las operaciones sobre
la misma lista Python compartida. Model, lowering, printer y verifier poseen
ramas explicitas por opcode.

### SSA

El camino por defecto es `GeneralSSABuilder`: CFG, dominadores, frontera de
dominancia, placement de phi y `SSARenamer`. El builder pattern historico sigue
disponible. Ambos conocen los opcodes List por separado. SSA mantiene el
puntero/lista como valor SSA, mientras las mutaciones modifican almacenamiento
externamente observable y no producen una nueva version del objeto.

### Optimizer

Existen dos pipelines:

- IR: folding, propagacion local, simplificacion algebraica, DCE y dead store.
- SSA: folding, propagacion global, simplificacion algebraica, SCCP, trivial
  phi, dead phi y DCE.

No hay alias analysis, memory SSA, GVN ni movimiento de cargas. La politica
actual es deliberadamente conservadora respecto de mutaciones.

### LLVM, runtime LLVM y native

`LLVMPrinter` baja SSA a LLVM textual y registra las dependencias requeridas.
`list_runtime.py` emite `aether_list_new`, copy, search, reverse, reserve,
prepare helpers y panics List; `array_runtime.py` emite el runtime Array; y
`runtime_common.py` centraliza allocation, declaraciones y los helpers de
merge sort compartidos por List y Array. Se enlazan intrinsecos LLVM y libc
(`malloc`, `free`, `puts`, `exit`, `strcmp`) al compilar con clang.

## 2. Representacion e invariantes

El layout emitido es consistente con el diseno:

```llvm
%AetherList = type {
    i64 length,
    i64 capacity,
    ptr data
}
```

Un valor LLVM `List<T>` es `ptr` al header. Los campos son:

| Campo | Indice GEP | Significado |
| --- | ---: | --- |
| `length` | 0 | slots logicamente vivos en `[0, length)` |
| `capacity` | 1 | slots reservados en el buffer |
| `data` | 2 | buffer contiguo de representaciones ABI de `T` |

`aether_list_new` asigna 24 bytes al header en el target asumido, inicializa
`length == capacity`, y usa `data == null` para el literal vacio porque
`aether_alloc(0)` retorna null. `reserve` conserva el header, puede reemplazar
`data`, duplica capacidad (`0 -> 1`, luego `capacity * 2`) y garantiza
`new_capacity >= required_capacity`. `clear`, `pop` y `removeAt` no reducen
capacidad.

### Coherencia entre capas

| Superficie | Representacion | Evaluacion |
| --- | --- | --- |
| Docs de growth/backend | header `{i64, i64, ptr}` | Coincide con LLVM actual. |
| LLVM | dos allocations: header y buffer | Implementa identidad estable y growth. |
| AST Interpreter | `AetherValue` + `list` Python | Abstraccion semantica coherente; no modela capacidad. |
| IR Interpreter | `list` Python | Abstraccion semantica coherente; no modela capacidad. |

La ausencia de `capacity` en los interpretes no es por si sola una
contradiccion: capacidad no es API publica. Si produce diferencias observables
cuando hay overflow, OOM o bounds, si hay falta de paridad runtime.

Inconsistencias/deuda:

- El layout asume punteros de 8 bytes y `size_t == i64`; no hay data layout ni
  guardia de target que documente o fuerce esa ABI.
- No hay validacion runtime de `0 <= length <= capacity`, `element_size > 0` ni
  procedencia del header. `element_size` es una constante del compilador, lo
  cual reduce el riesgo pero no centraliza el invariante.
- No existe ownership final: header y ultimo buffer filtran al terminar su
  lifetime. `reserve` si libera el buffer anterior.
- Los interpretes reportan excepciones ricas; native imprime mensajes fijos y
  termina con codigo 1. Es una diferencia de mecanismo esperable, pero los
  casos cubiertos no son los mismos.

## 3. Auditoria por operacion

En la columna runtime, "AST" se refiere a `stdlib/core.py` o a la lista Python
del interprete, y "LLVM" a helpers emitidos por el backend.

| Operacion | Frontend / AST | IR | SSA y optimizer | LLVM / runtime | Tests existentes | Observaciones |
| --- | --- | --- | --- | --- | --- | --- |
| `ListNew` | `ListLiteral`; inferencia/target type; AST crea lista Python | `IRListNew` y ejecucion/printer/verifier | `SSAListNew`; ambos builders; se conserva como allocation | checked bytes; header+buffer; stores de elementos inline | literal, tipos, empty, for, helpers/LLVM/native | Valida longitud/producto antes de reservar header o buffer. |
| `ListGet` | `IndexExpression`; indice `int`; AST comprueba bounds | `IRListGet`; interprete comprueba bounds con mensaje List | `SSAListGet`; DCE lo preserva por `may_trap` | `aether_list_check_index` antes de cargar data, GEP y load | validos; negativo/igual/mayor/empty; AST/IR/native; DCE; orden LLVM | Semantica uniforme `0 <= i < length`; panic native controlado. |
| `ListSet` | `IndexAssignment`; tipo/const; AST comprueba bounds y muta alias | `IRListSet`, side-effecting; check antes de mutar | `SSAListSet`; preservado por todos los pases | `aether_list_check_index` antes de cargar data, GEP y store | validos; negativo/igual/mayor/empty; estado; native; orden LLVM | Un fallo no escribe el buffer ni publica una mutacion parcial. |
| `ListLength` | builtin/property/`size()`; AST usa `len` | `IRListLength` para `.length` y `for`; no baja `length(xs)` ni `xs.size()` | `SSAListLength`; DCE la conserva por `may_trap` | carga `i64`; conversion checked a `i32` | limites unitarios, LLVM, DCE y caminos normales | `> INT32_MAX` produce `Aether panic: List length does not fit in int`. |
| `ListIsEmpty` | builtin y propiedad `is_empty`; AST `len == 0` | `IRListIsEmpty` solo para `.is_empty`; no baja `is_empty(xs)` | `SSAListIsEmpty`; lectura eliminable | carga `length` y `icmp eq 0` | propiedad en backend; builtin en AST | Opcode coherente, superficie global incompleta y docs de miembros incompletas. |
| `ListCopy` | builtin/metodo; copia superficial del contenedor | `IRListCopy`; nueva lista Python externa | `SSAListCopy`; conservada como allocation | valida bytes -> new -> `memcpy` no vacio | shallow copy, helpers, orden LLVM/native | Nunca llama memcpy con un tamano envuelto; header y buffer independientes. |
| `ListContains` | builtin/metodo; igualdad valor o identidad segun `T` | `IRListContains`, reutiliza busqueda del interprete | `SSAListContains`; lectura | llama a busqueda especializada que retorna `i64` | escalares/referencias, mutaciones, LLVM/native | Compara el `i64` con `-1`; no pasa por la conversion checked de indexOf. |
| `ListIndexOf` | builtin `index_of` y metodo `indexOf`; primer match/-1 | `IRListIndexOf` solo para `indexOf`; no baja `index_of` | `SSAListIndexOf`; DCE lo conserva por `may_trap` | busqueda `i64` + wrapper checked `i32` | valido/-1/limite helper/DCE/LLVM/native | Encontrado `> INT32_MAX` hace panic; la forma global aun no alcanza backend. |
| `ListReverse` | builtin/metodo mutante; AST `reverse` | `IRListReverse`/swaps | `SSAListReverse`; efecto preservado | helper generico, swap byte a byte | vacia/pares/impares/tipos/aliases/optimizer/native | Multiplicaciones de offsets sin check; correctas solo si el objeto fue asignado con tamanos validados. |
| `SequenceSort` | `sort` en List/Array; tipos ordenables | un `IRSequenceSort` comun | un `SSASequenceSort`; efecto preservado | merge sort estable con bytes checked, compartido | int/double/string/NaN/alias/List+Array/native | Valida temporal antes de malloc; bounds y width evitan add/shift con wrap. |
| `ListClear` | builtin/metodo mutante; AST `clear` | `IRListClear` | `SSAListClear`; efecto preservado | store inline de cero a `length` | empty/nonempty/reuse/alias/optimizer/native | Correctamente O(1); conserva capacidad/data y slots residuales. |
| `ListPush` | tipo de valor, aridad y const; AST `append` | `IRListPush` | `SSAListPush`; efecto preservado | `prepare_push` + `reserve`; recarga data; store y length al final | zero/growth/reuse/tipos/refs/aliases/optimizer/native | Checks de `length+1`, doubling y bytes correctos; logica de commit esta repartida entre helper y emitter. |
| `ListPop` | vacio falla; retorna `T`; AST `pop` | `IRListPop`, efecto+resultado | `SSAListPop`; nunca puro aunque resultado muera | `prepare_pop`; load tipado; store length | tipos/refs/empty/clear/alias/unused/optimizer/native | Correcto sin shrinking; slot muerto no se limpia. |
| `ListInsert` | `0 <= i <= length`; valor/const; AST `insert` | `IRListInsert` | `SSAListInsert`; efecto preservado | prepare+bounds+reserve; `memmove`; store; length ultimo | inicio/medio/final/tipos/refs/errors/aliases/native | El helper valida bytes y length; emitter vuelve a calcular bytes sin overflow intrinseco, seguro solo por ese contrato. |
| `ListRemoveAt` | `0 <= i < length`; retorna `T`; AST `pop(i)` | `IRListRemoveAt`, efecto+resultado | `SSAListRemoveAt`; preservado con resultado muerto | prepare+bounds; load; `memmove`; length ultimo | posiciones/tipos/refs/errors/aliases/unused/native | Helper valida bytes; sin shrinking. `LIST_BACKEND_AUDIT.md` aun lo marca pendiente en secciones viejas. |

No se detecto un opcode de esta lista que falte completamente en una capa,
pero length/is_empty/indexOf tienen formas publicas que faltan en IR y capas
posteriores. La duplicacion encontrada es estructural, no duplicacion de opcodes publicos:
`contains` e `indexOf` reutilizan una busqueda interna `i64`, sort reutiliza un helper comun, y
push/insert reutilizan reserve.

## 4. Duplicacion y helpers concretos

### LLVM

La mayor concentracion esta en `backend/llvm/printer.py`:

- GEP de `length`, `capacity` y `data` y sus loads/stores aparecen tanto en
  helpers Python (`_list_data_pointer`, `_list_length64`) como escritos a mano
  dentro de strings del runtime emitido.
- push, pop, insert, removeAt y clear repiten la secuencia obtener campo de
  longitud / calcular nueva longitud / publicar longitud.
- insert y removeAt repiten sext del indice, GEP tipado, conteo de elementos,
  bytes de movimiento y `memmove`.
- `aether_checked_mul_i64` y `aether_checked_allocation_bytes` cubren new, copy
  y sort; reserve/prepares conservan sus checks de capacidad existentes.
- OOM, overflow, index-bounds, pop-empty, insert-bounds y removeAt-bounds repiten global de
  mensaje, `puts`, `exit` y `unreachable`.
- El printer mantiene muchos flags `_uses_list_*` y luego reconstruye
  dependencias de declaraciones manualmente.

Helpers recomendados, sin cambiar semantica:

1. Helpers Python de emision `_list_field_ptr(field)`, `_load_list_field` y
   `_store_list_field`, utilizables tambien al construir cuerpos runtime.
2. Un unico helper LLVM `aether_panic(ptr message) noreturn`; wrappers con
   nombre por diagnostico pueden quedar pequenos si los tests dependen de sus
   simbolos.
3. `aether_checked_byte_size(count, element_size) -> i64` o generador comun de
   `umul.with.overflow`, usado por new, copy, reserve, insert/removeAt y sort.
4. `aether_list_check_index(index, length, allow_end, message)` o dos wrappers
   get/set (`< length`) e insert (`<= length`) sobre un nucleo comun.
5. `_emit_list_data_reload` y `_emit_list_length_commit` para las operaciones
   inline tipadas.
6. Un descriptor de dependencias runtime por opcode en vez de flags y
   condicionales dispersos; por ejemplo allocation, memcpy, memmove, panic,
   growth, search y sort.
7. Mantener `reserve` como unico owner de la politica de crecimiento; no crear
   variantes por tipo.

### IR

Las mismas clases se enumeran por separado en lowering, interpreter, printer,
verifier, DCE, simplificacion y propagacion. El lowering de llamadas mutantes
sin resultado repite desazucarado de receiver, aridad y validacion para push,
insert, clear, sort y reverse; `_lower_call` repite otro esquema para copy,
contains, indexOf, pop y removeAt.

Helpers recomendados:

- `_normalize_native_call(call) -> (builtin, receiver+args)` compartido por
  statement y expression lowering;
- builders pequenos `emit_list_unary_effect`, `emit_list_indexed_effect` y
  `emit_list_value_result`, manteniendo errores especificos;
- metadata declarativa por instruccion: `result`, `operands`, `effect`,
  `may_trap`, tipos esperados y nombre de printer;
- utilidades comunes `instruction_result()` e `instruction_operands()` para
  optimizadores y verifier.

### SSA

Hay duplicacion directa entre el builder pattern (`builder.py`) y el renamer
del builder general (`renaming.py`). Printer, verifier, algebraic
simplification, SCCP, DCE, dead phi y trivial phi vuelven a enumerar casi las
mismas instrucciones y operandos.

Helpers recomendados:

- una traduccion IR->SSA compartida para instrucciones que no escriben slots;
  el builder solo aportaria la funcion que resuelve cada `IRValue`;
- un rewriter generico de operandos basado en la metadata del opcode;
- un registro unico de productores puros, productores con efecto y
  terminadores;
- generacion/validacion de printer y verifier desde esa metadata cuando la
  regla sea mecanica, dejando funciones especiales solo para invariantes de
  tipos complejos.

### Runtime

Ya existen buenas reutilizaciones: contains/indexOf delegan en la busqueda
interna i64, insert/push delegan en reserve y sort es comun a Array/List. Lo
repetido es la periferia:
panics, acceso a campos, multiplicacion de bytes y declaracion condicional de
intrinsecos/libc. Un modulo generador de runtime con secciones y dependencias
explicitas reduciria el tamano de `LLVMPrinter` y evitaria combinaciones de
flags invalidas.

## 5. Side effects y optimizadores

Operaciones mutantes auditadas:

| Operacion | IR DCE | SSA DCE | SCCP | Alg. simplification | Dead/trivial phi |
| --- | --- | --- | --- | --- | --- |
| `ListSet` | conservada | conservada | conservada; operandos registrados | reconstruye 3 operandos | reescribe 3 operandos |
| `ListReverse` | conservada | conservada | conservada | reescribe lista | reescribe lista |
| `SequenceSort` | conservada | conservada | conservada | reescribe secuencia | reescribe secuencia |
| `ListClear` | conservada | conservada | conservada | reescribe lista | reescribe lista |
| `ListPush` | conservada | conservada | conservada | reescribe lista/valor | reescribe lista/valor |
| `ListPop` | conservada aunque resultado muera | conservada aunque resultado muera | resultado `Overdefined`, operacion conservada | reescribe lista | reescribe lista |
| `ListInsert` | conservada | conservada | conservada | reescribe 3 operandos | reescribe 3 operandos |
| `ListRemoveAt` | conservada aunque resultado muera | conservada aunque resultado muera | resultado `Overdefined`, operacion conservada | reescribe lista/indice | reescribe lista/indice |

No se encontro una inconsistencia funcional actual entre esos cinco tipos de
pase. Detalles que merecen limpieza:

- En SCCP, `SSAListRemoveAt` figura tanto entre productores de resultado como
  en la tupla de mutaciones; la primera rama gana. Es redundante y facilita que
  futuras ediciones diverjan. `SSAListPop` solo figura como productor con
  resultado, aunque tambien muta; hoy el transformer preserva ambos, pero la
  metadata conceptual es asimetrica.
- Dead phi y trivial phi no deciden pureza, pero contienen grandes visitors de
  operand rewrite. La cobertura completa actual depende de que cada opcode se
  agregue manualmente.
- Los tests de List ejecutan pipelines completos y comprueban que las
  mutaciones sobreviven. No aislan todas las combinaciones
  opcode-pase, especialmente SCCP/dead phi/trivial phi para cada mutador.

Lecturas y allocations:

- `ListIsEmpty` y `ListContains` son productores puros eliminables por DCE.
- `ListLength` y `ListIndexOf` se conservan en DCE IR/SSA porque sus
  conversiones `i64 -> i32` pueden hacer panic aunque el resultado no se use.
- `ListNew` y `ListCopy` se conservan conservadoramente aunque el resultado
  muera, porque allocation/OOM se trata como observable.
- `ListGet` es una lectura `may_trap`: se excluye de los productores
  eliminables en DCE IR y SSA. No se introdujo metadata centralizada; la regla
  conservadora queda explicita en ambos pases.

## 6. Aliasing

El contrato coherente para tipos exactamente iguales es:

```text
assignment / parameter / return
        -> copia del handle al mismo objeto/header

copy()
        -> header nuevo + buffer externo nuevo
        -> elementos reference-type copiados superficialmente
```

### Por operacion

| Caso | AST / IR | LLVM | Coherencia |
| --- | --- | --- | --- |
| asignacion | comparte objeto/lista Python | copia `ptr` | Si |
| parametro | pasa el mismo objeto | pasa `ptr` | Si |
| return | retorna el mismo objeto | retorna `ptr` | Si |
| `copy()` | lista externa, elementos shallow | header+buffer nuevos, bytes/handles shallow | Si |
| `push()` | muta lista compartida | reserve conserva header y recarga data | Si |
| `pop()` | reduce lista compartida y retorna el elemento | reduce length, retorna la representacion almacenada | Si |
| `insert()` | muta lista compartida | reserve conserva header; memmove de representaciones | Si |
| `removeAt()` | compacta lista compartida y retorna elemento | carga antes de memmove; conserva header | Si |
| `clear()` | vacia lista compartida | pone length=0; conserva data/capacity | Si |

La igualdad de `contains/indexOf` tambien coincide: escalares/string por valor,
agregados reference-type por identidad de handle. Una lista anidada copiada
con `copy()` tiene contenedor externo independiente, pero sus listas internas
siguen aliased.

Riesgos/deuda:

- No hay alias analysis; esto es correcto pero limita optimizaciones.
- No hay lifetime/GC/refcount. Copiar y retornar handles es semanticamente
  correcto, pero filtra memoria y no define destruccion de elementos.
- Los slots muertos tras pop/removeAt/clear conservan handles. Hoy no son
  observables; con un GC conservador podrian prolongar lifetimes.
- Conversiones entre listas con distinto tipo de elemento no deben confundirse
  con aliasing exacto: una conversion que materializa elementos necesita un
  contenedor nuevo. La documentacion existente lo explica mejor que la
  metadata IR, que no tiene un opcode general de conversion List.

## 7. Bounds checks

Politica semantica observada: indices publicos son `int`, 0-based; get/set y
removeAt requieren `0 <= i < length`; insert permite `i == length`; pop exige
`length > 0`.

| Operacion | AST runtime | IR Interpreter | LLVM native |
| --- | --- | --- | --- |
| get | `_require_index`, si | `_check_list_index`, si | `aether_list_check_index`, antes de data/GEP/load |
| set | `_require_index`, si | `_check_list_index`, antes de mutar | `aether_list_check_index`, antes de data/GEP/store |
| `for` | iteracion segura sobre valores | indice generado + get comprobado | condicion del loop y check propio de cada get |
| insert | `0 <= i <= length` | mismo check | `prepare_insert`, mismo check antes de reserve/memmove |
| removeAt | `0 <= i < length` | mismo check | `prepare_remove_at`, mismo check antes de load/memmove |
| pop | no vacia | no vacia | `prepare_pop` antes del calculo/load |

AST e IR incluyen indice y longitud. LLVM usa el mensaje estatico
`Aether panic: List index out of bounds`, llama `exit(1)` y termina el bloque
con `unreachable`. El helper comprueba `index >= 0` e `index < length`; solo al
retornar se carga `data` y se calcula el GEP del elemento. Es reutilizable por
otras operaciones, aunque insert/removeAt conservan sus checks existentes en
esta tarea.

## 8. Overflow y representabilidad

| Calculo | Estado LLVM | Riesgo |
| --- | --- | --- |
| `length + 1` push | `uadd.with.overflow` en prepare | Cubierto |
| `length + 1` insert | `uadd.with.overflow` en prepare | Cubierto |
| `capacity * 2` | `umul.with.overflow` | Cubierto; panic si doubling desborda incluso si required podria caber |
| `new_capacity * element_size` | `umul.with.overflow` en reserve | Cubierto |
| `length * element_size` al copiar durante growth | `umul.with.overflow` | Cubierto |
| bytes a mover en insert | `umul.with.overflow` en prepare; `mul` repetido al emitir | Cubierto por precondicion, pero fragil por duplicacion |
| bytes a mover en removeAt | igual | Cubierto por precondicion, pero fragil por duplicacion |
| bytes de `ListNew` | `aether_checked_allocation_bytes` antes del header | Cubierto |
| bytes de `ListCopy` | checked antes de llamar new y antes de memcpy | Cubierto |
| bytes/bounds internos de sort | checked total/run; sumas acotadas; width con branches | Cubierto |
| offsets byte de reverse | `mul`/`add` | No cubierto; depende de invariantes previos |
| retorno de length/indexOf | helpers checked; `-1` admitido solo para indexOf | Cubierto; panic si excede `INT32_MAX` |
| tamano del header | constante 24 | Valido solo bajo ABI 64-bit asumida |

`aether_alloc` trata size cero como null y comprueba `malloc` null para sizes
no cero. No comprueba limites distintos de `i64` ni modela `size_t` en targets
de 32 bits. El contrato documental de growth exige mas: element size valido,
limite del allocator y ausencia de wrap en todos los caminos. La
implementacion satisface el contrato i64 en reserve/prepares y en
new/copy/sort; modelar un `size_t` de 32 bits sigue fuera del target actual.

## 9. Runtime LLVM

### Lo que esta bien centralizado

- `aether_alloc` unifica OOM para allocation List, Array y sort.
- `aether_list_reserve` es el unico lugar que decide growth y reemplaza buffer.
- contains e indexOf delegan en una busqueda `i64` deduplicada por ABI de T;
  solo indexOf llama al wrapper checked a `i32`.
- sort List/Array comparte exactamente los helpers especializados.
- `memcpy` se usa para buffers no solapados y `memmove` para shifts solapados.
- reserve publica `data/capacity` solo despues de allocation/copy y libera el
  buffer anterior; push/insert publican length despues del store/move.

### Oportunidades de simplificacion

- La extraccion del runtime List y la infraestructura comun ya estan
  completadas; las declaraciones se deduplican por modulo.
- Los mensajes y checks dependientes del layout permanecen especializados.
- Mover la totalidad de insert/removeAt a helpers storage-oriented con
  `value_ptr/out_ptr`, o mantener lowering inline pero compartir una primitiva
  de movimiento validado. La primera opcion reduce LLVM emitido; la segunda
  conserva loads/stores tipados. Ambas son refactors, no features.
- Representar dependencias runtime como grafo: `push -> prepare -> reserve ->
  alloc/memcpy/free/overflow`, en vez de condicionales booleanos.
- Compartir accesos al header entre helpers emitidos y emitter tipado.

## 10. Riesgos de optimizacion

No existen hoy pases que muevan instrucciones de memoria, CSE de cargas List
o folding de contenido. Por eso varios riesgos estan contenidos por ausencia
de optimizacion, no por un modelo formal de memoria.

Riesgos abiertos:

1. **Eliminar efectos/traps:** las mutaciones estan correctamente fuera de las
   listas de productores puros y `ListGet` tambien se conserva por `may_trap`.
2. **Mover/reutilizar lecturas:** cualquier futuro GVN, LICM o load forwarding
   debe tratar llamadas desconocidas y las ocho mutaciones como clobbers de
   longitud/contenido de todos los aliases posibles.
3. **Longitud constante:** solo es seguro plegar length/is_empty de un literal
   si no escapa, no tiene aliases y no hay mutacion alcanzable. El pipeline no
   hace actualmente ese plegado, lo cual es conservador.
4. **Contenido constante:** no plegar get/contains/indexOf a traves de set,
   reverse, sort, clear, push, pop, insert, removeAt o una llamada que pueda
   recibir el mismo header.
5. **Copy:** outer storage no aliasa, pero sus elementos reference-type si.
   Una futura alias analysis necesita distinguir ambos niveles.
6. **Calls:** los optimizadores actuales conservan calls; cualquier resumen de
   efectos interprocedural debe incluir mutaciones via parametros y returns.
7. **SCCP:** actualmente marca resultados List como overdefined y no aprende
   hechos de memoria. Si se agregan lattices de length/contenido, necesitaran
   invalidacion por alias.

La refactorizacion clave es separar tres propiedades en metadata:
`has_side_effects`, `reads_memory` y `may_trap`. Un unico booleano pure/impure
no alcanza para List.

## 11. Cobertura de tests

### Fortalezas

- `test_list_backend.py` recorre lowering, interprete IR, builders, verifiers,
  printers, pipelines, texto LLVM y clang para todas las operaciones.
- Hay tests de alias por asignacion, parametro y return para set/push/insert y
  varias mutaciones adicionales.
- copy shallow, referencias anidadas e igualdad valor/identidad estan
  cubiertos.
- insert/removeAt prueban extremos y panic native; pop prueba vacio y clear;
  clear prueba reuse; push prueba `capacity == 0` y varios crecimientos.
- sort tiene suite propia para estabilidad funcional, tipos, strings, NaN,
  aliases y reutilizacion List/Array.
- `tests/test_llvm_integration.py` compila y ejecuta todos los ejemplos LLVM,
  incluidos literal, for, get/set alias, copy, contains, indexOf, reverse,
  sort, clear, push, pop, insert y removeAt.

### Huecos

Prioridad alta:

- bounds nativos de get/set: **resuelto**, con casos negativo, igual a length,
  mayor, lista vacia, estado no modificado, orden LLVM y panic clang;
- paridad backend de las formas globales `length`, `is_empty`, `index_of` y
  del metodo documentado `size()`;
- overflow de new/copy/sort y limites `i64 -> i32`: **resuelto** con helpers
  unitarios y comprobaciones textuales LLVM sin allocations gigantes;
- fallo de allocation: **resuelto** mediante allocator inyectado; no se provoca
  OOM real.

Prioridad media:

- muchos aliases simultaneos atravesando varias realocaciones y funciones;
- secuencias nativas largas con varias decenas de growths;
- ciclos largos push/pop e insert/removeAt alternados, en inicio/medio/final;
- observacion interna de que pop/removeAt/clear conservan capacity/data y que
  clear reutiliza realmente el buffer, no solo el resultado;
- tests aislados por pase para SCCP, DCE, algebraic, dead phi y trivial phi en
  cada mutacion;
- stress LLVM para int/double/bool/string/ref durante growth y movimientos;
- paridad exacta de errores entre AST, IR optimizado y native.

Prioridad baja:

- combinaciones copy + muchos aliases + growth de original y copia;
- listas vacias repetidamente ordenadas/revertidas/limpiadas;
- inspeccion de deduplicacion de todos los helpers cuando muchas operaciones y
  tipos aparecen en un mismo modulo.

La suite `test_list_method_stress.py` es principalmente del runner AST y usa
secuencias pequenas; el nombre stress no equivale a stress de allocation
nativa.

### CI

`scripts/ci.py` ejecuta pytest, pero sus smoke lists explicitas son parciales:

- `LLVM_EXAMPLES` de CI incluye clear, insert, push y removeAt, pero omite
  literal, get/set, copy, contains, indexOf, reverse, sort y pop. Esos casos
  siguen cubiertos indirectamente por pytest/integration si clang esta
  disponible.
- La tupla `BENCHMARKS` de CI no incluye `list_for_sum.ae` ni `list_push.ae`,
  aunque ambos existen y estan documentados.

## 12. Benchmarks

Benchmarks List existentes:

- `list_for_sum.ae`: recorrido repetido de una lista de cinco elementos.
- `list_push.ae`: 256 pushes desde vacio y validacion de primer/ultimo valor.

Son utiles como smoke benchmarks, pero no caracterizan el subsistema completo.
Faltan, sin necesidad de convertirlos en features:

1. growth amortizado con tamanos crecientes y suficientes iteraciones para
   separar allocation/copy del ruido;
2. insert repetido al inicio y al medio;
3. removeAt repetido al inicio y al medio;
4. push/pop alternado para medir reuse de capacidad;
5. insert/removeAt alternado sin growth y con growth;
6. clear + refill para comprobar reutilizacion;
7. copy de listas grandes primitivas y de referencias;
8. contains/indexOf presente al inicio/final/ausente;
9. reverse grande;
10. sort grande para int/double/string, incluyendo inputs ordenado, inverso y
    con duplicados.

Ademas, los dos benchmarks List deberian entrar en la tupla de CI si se desea
que su mera ejecutabilidad sea una garantia continua. Esto es una mejora de
infraestructura, no una nueva operacion del lenguaje.

## 13. Documentacion y Feature Matrix

### `FEATURE_MATRIX.md`

La tabla detallada de colecciones refleja correctamente la existencia de
opcodes para literal, length, is_empty, for, get, set, copy, contains, indexOf,
push, pop, insert, removeAt, clear, reverse y sort hasta LLVM. Tambien documenta
los bounds checks propios de get/set native. No es correcta al agrupar
`List.length / length` y `List.is_empty / is_empty` como si
las formas property y builtin tuvieran la misma cobertura: las globales no
bajan. La fila `List.indexOf` es correcta solo para el metodo camelCase; no
registra el builtin global `index_of`, y `List.size()` no tiene fila propia.

Sin embargo, sus resumenes son historicos o ambiguos:

- la fila global de tipo `List` sigue marcando IR/SSA/optimizer/LLVM como
  parciales y estado "Parcial backend fase 4e";
- literal, length, is_empty y for marcan optimizer como parcial aun cuando los
  opcodes atraviesan el pipeline conservadoramente;
- el texto "backend fase 4e" comunica migracion incompleta pese a que todas las
  operaciones enumeradas estan implementadas. Seria mas preciso separar
  completitud funcional de robustez (bounds, ownership, overflow).

### Contradicciones documentales concretas

- `AETHER_V0_SPEC.md`, al inicio de Lists, dice que growth design solo marca
  clear/push/pop y que insert/removeAt son frontend-only. Ambas operaciones
  tienen IR, SSA, optimizer, LLVM y native.
- La misma spec llama al contrato sort "future" y al trabajo Array/backend
  "design-only", aunque `SequenceSort` esta implementado y probado.
- La lista de propiedades nativas soportadas omite `List<T>.is_empty`, aunque
  `native_members.py`, typechecker, AST, IR, SSA y LLVM la soportan.
- Las listas de builtins de la spec omiten `index_of`, aunque
  `stdlib/core.py` lo registra. El lowering acepta el metodo `indexOf`, no la
  forma global.
- `LIST_BACKEND_AUDIT.md` conserva en su resumen que el resto de la API esta
  pendiente, una tabla que marca removeAt sin backend y una conclusion que
  habla de mutaciones de longitud pendientes. Secciones posteriores del mismo
  archivo ya describen removeAt, por lo que el documento se contradice a si
  mismo.
- `AETHER_LIST_GROWTH_DESIGN.md` ya refleja el orden seguro y los helpers
  checked de new/copy; conserva como futuras las decisiones generales de
  ownership y limites del allocator.
- `MUTABLE_AGGREGATES.md` todavia llama "planned" a indexed mutation y futuras
  instrucciones de Vector/Matrix; su regla general de aliasing coincide, pero
  su estado historico reduce su valor como referencia actual.

La recomendacion no es agregar mas documentos paralelos, sino declarar esta
auditoria como snapshot y luego actualizar o retirar afirmaciones historicas
de los documentos normativos.

## 14. Roadmap tecnico recomendado

Solo pasos de robustez/refactor, sin nuevas features del lenguaje:

### P0 - correccion y seguridad nativa

1. **Completado:** centralizar y emitir bounds checks para `ListGet`/`ListSet`,
   alinear su semantica con AST/IR y modelar `may_trap` en DCE.
2. Completar el lowering de las formas publicas ya documentadas (`length`,
   `is_empty`, `index_of`, `size`) mediante los opcodes existentes.
3. **Completado:** aplicar checked byte-size a `aether_list_new`, copy y sort
   para el target i64 actual.
4. **Completado:** rechazar `List.length` e indices encontrados por `indexOf`
   que excedan `INT32_MAX`; `contains` permanece independiente del narrowing.

### P1 - consolidacion del runtime LLVM

5. **Completado:** extraer runtime List del printer de instrucciones y declarar
   dependencias entre helpers.
6. **Completado en el alcance compartible:** unificar infraestructura de panic,
   declaraciones, allocation, calculos checked y sort; los campos permanecen
   separados por layout.
7. Unificar prepare/move/commit de insert/removeAt sin duplicar calculos ya
   validados.
8. Registrar explicitamente ABI/target y alignment soportados.

### P2 - modelo de efectos del middle-end

9. Crear metadata unica de resultados, operandos, reads, writes y may-trap
   para IR/SSA.
10. Reutilizar esa metadata en builders, renaming, DCE, SCCP, phi rewriters,
   printers y verifiers.
11. Eliminar la asimetria SCCP de Pop/RemoveAt y agregar tests aislados por
    pase.

### P3 - cobertura y medicion

12. Cubrir bounds native, overflow/OOM inyectado, aliases con multiples
    reallocations y stress alternado.
13. Incorporar benchmarks List representativos y hacer que CI ejecute al menos
    los dos ya existentes.
14. Completar los smoke examples explicitos de CI o documentar que pytest es
    la unica lista exhaustiva.

### P4 - higiene y lifetime

15. Actualizar spec, feature matrix y auditorias historicas para eliminar
    contradicciones.
16. Definir e implementar una estrategia de lifetime/ownership para headers,
    buffers finales y slots reference-type; esto es deuda runtime, no una
    feature de coleccion.

## 15. Conclusion

`List<T>` tiene **todos los opcodes declarados**, con un pipeline uniforme y
buena cobertura de los caminos normales, pero no todas las formas publicas
documentadas alcanzan el backend.
La arquitectura de header estable, copy shallow, reserve central y efectos
conservadores es una base correcta.

El estado tecnico global del snapshot es **aceptable**: los P0 de bounds,
tamanos envueltos y narrowing silencioso estan cerrados. Persisten brechas de
superficie publica, ownership y consolidacion del runtime que quedaron
explicitamente fuera de esta tarea; no requieren cambiar `int`, el layout ni
la API de List.
