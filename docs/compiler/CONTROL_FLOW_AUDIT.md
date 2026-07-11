# Auditoria tecnica de control de flujo

Ultima revision: 2026-07-10.

Alcance: auditoria documental de la implementacion actual de `if`, `while`,
`for`, `break`, `continue` y `return` a traves de IR lowering, CFG,
verificadores, dominadores, dominance frontier, colocacion de phis, renombrado
SSA, optimizadores IR/SSA y printer LLVM.

Esta auditoria no cambia parser, typechecker, interpreter, IR, SSA,
optimizadores, LLVM ni tests. Su objetivo es dejar un mapa tecnico antes de
empezar con `List<T>`.

## Resumen ejecutivo

El control de flujo ya atraviesa el pipeline compilador:

- `IRLowerer` baja `if`, `while`, `for`, `break`, `continue` y `return` a
  bloques explicitos con `IRBranch`, `IRJump` e `IRReturn`.
- `CFGBuilder` deriva edges desde terminadores de bloque.
- `IRVerifier` valida terminadores, targets, tipos, definicion de valores y
  stores visibles por todos los caminos alcanzables.
- `GeneralSSABuilder` es el builder SSA por defecto. Construye CFG,
  dominadores, dominance frontier, phis y renombrado general.
- `PhiPlacement` usa definition blocks, liveness y un analisis de
  inicializacion para evitar phis claramente innecesarios.
- `SSARenamer` elimina loads/stores promovibles y rellena incoming de phis por
  edges de CFG durante el DFS del arbol de dominadores.
- `SCCPPass` puede simplificar branches constantes, eliminar bloques no
  ejecutables y limpiar incoming de phis.
- `LLVMPrinter` emite labels, branches, jumps, returns y phis sobre SSA.

Las Fases 1 y 2 del plan de refactorizacion ya estan implementadas. El mayor
riesgo original no era que faltara una pieza principal, sino que la superficie
de control de flujo habia crecido con bastante duplicacion manual. Esa
duplicacion quedo reducida en el lowering: construccion de bloques,
terminadores, merges de `if`, targets de loops y restauracion de variables de
loop pasan ahora por helpers privados de `IRLowerer`.

## Arquitectura actual del lowering de control de flujo

`IRLowerer` mantiene la misma salida IR observable y los mismos nombres de
bloques principales, pero el protocolo interno quedo centralizado:

- `_new_block`, `_new_while_blocks` y `_new_for_blocks` crean bloques con
  nombres estables.
- `_append_block`, `_enter_block` y `_append_and_enter` registran y activan
  bloques sin duplicar mutaciones de `_FunctionContext`.
- `_emit_jump_if_open` y `_emit_current_jump_if_open` agregan jumps solo si el
  bloque no tiene terminador.
- `_emit_branch` valida condicion bool y emite `IRBranch`.
- `_finish_if_merge` decide si un `if` necesita merge, agrega jumps desde ramas
  abiertas y conserva el caso sin `else` donde el merge es target del camino
  falso.
- `_loop_context` encapsula targets de `break`/`continue` y, para `for`,
  binding/restauracion de la variable de loop mediante `finally`.
- `_lower_for_range_condition` aisla la sub-CFG especial de rangos con step
  dinamico.
- Los helpers de `for indexable` separan seleccion del iterable, inicializacion
  del indice, condicion, carga del elemento e incremento.

La semantica sigue igual: `continue` en `while` salta al bloque de condicion;
`continue` en `for` salta al bloque de incremento; `break` salta al bloque de
salida del loop activo; nested loops siguen usando el stack LIFO de targets.

## Archivos revisados

- `src/aether/ir/lowering.py`
- `src/aether/ir/model.py`
- `src/aether/analysis/cfg.py`
- `src/aether/ir/verifier.py`
- `src/aether/analysis/dominators.py`
- `src/aether/analysis/dominance_frontier.py`
- `src/aether/ssa/general_builder.py`
- `src/aether/ssa/phi_placement.py`
- `src/aether/ssa/renaming.py`
- `src/aether/ssa/verifier.py`
- `src/aether/ir/optimizer/*`
- `src/aether/ssa/optimizer/*`
- `src/aether/backend/llvm/printer.py`
- Tests de IR, CFG, dominadores, phi placement, SSA builder, SSA renaming,
  SSA verifier, optimizers, LLVM y `tests/aether/test_for_backend.py`.

## Estado por feature

### if

`if` baja a branch desde el bloque actual hacia `thenN` y `elseN` o `mergeN`.
Si no hay `else`, se crea un merge desde el principio. Si hay `else`, el merge
se crea solo si al menos una rama no termina. Las ramas no terminadas reciben
`IRJump(mergeN)`.

Observaciones:

- La forma aciclica esta bien soportada por CFG, IR verifier, SSA general,
  optimizadores y LLVM.
- `if` dentro de loops funciona porque `break` y `continue` usan el stack de
  targets activo en el contexto.
- `if` con `return` en ambas ramas evita crear merge innecesario.
- `if` con asignacion en ramas produce phis en SSA si el valor se lee despues.

Riesgos:

- La logica de merge y terminacion ya vive en `_finish_if_merge`; el riesgo
  principal restante es mantener cubiertos los casos de ramas completamente
  terminadas y `if` sin `else`, donde el merge sigue siendo target del camino
  falso.
- El lowerer falla si hay statements despues de un bloque terminado dentro del
  mismo cuerpo logico. Eso es correcto como restriccion actual del backend, pero
  conviene cubrirlo y decidir si sera error semantico, pruning de unreachable o
  soporte real de bloques inalcanzables de fuente.

### while

`while` baja a la forma:

```text
entry/current -> condN
condN -> bodyN | exitN
bodyN -> condN
exitN -> continuacion
```

`break` salta a `exitN`; `continue` salta a `condN`.

Observaciones:

- La forma canonical facilita CFG, dominadores, dominance frontier y phis de
  variables loop-carried.
- El body vacio queda como `bodyN: jump condN`.
- Nested loops funcionan por el stack LIFO de `_LoopTargets`.

Riesgos:

- La construccion de bloques, jumps y stack de targets ya esta compartida con
  `for` mediante helpers privados de `IRLowerer`.
- El destino de `continue` para `while` es el bloque de condicion, mientras que
  para `for` es el bloque de incremento. Esto sigue siendo correcto y ahora
  queda expresado en las llamadas a `_loop_context`.
- `return` dentro del loop termina el bloque actual, pero statements fuente
  posteriores dentro del mismo body provocan fallo de lowering, no creacion de
  unreachable IR.

### for

Hay dos lowerings:

- `for` sobre `RangeExpression`, con bloques `for.condN`, `for.bodyN`,
  `for.incN`, `for.exitN`.
- `for` sobre indexables soportados por IR, con indice interno
  `for.N.index`, length y `get` del elemento.

Para rangos con step dinamico se agregan `for.posN`, `for.negN` y
`for.neg.boundN` para elegir la comparacion correcta.

Observaciones:

- El loop variable se modela como slot local. Al salir del loop se restaura el
  binding anterior o se elimina si era nuevo.
- `continue` salta a `for.incN`; `break` salta a `for.exitN`.
- Rangos ascendentes/descendentes y step dinamico tienen cobertura de backend.
- La forma explicita es compatible con SSA general y LLVM.

Riesgos:

- `_lower_for_range` y `_lower_for_indexable` ya comparten nombres
  `cond/body/inc/exit`, targets de loop, jump final del body, bloque de salida
  y restauracion de locals. Todavia tienen logica propia para inicializacion,
  lectura de elemento e incremento, que corresponde a cada forma de iteracion.
- El step dinamico introduce una sub-CFG mas compleja, ahora aislada en
  `_lower_for_range_condition`.
- El loop variable se llama igual que la variable fuente; los slots internos de
  indice usan nombres con puntos. LLVM los escapa/estabiliza, pero un helper de
  nombres reduciria riesgo al agregar nuevos tipos de iteracion.

### break y continue

No existen opcodes especiales. En IR se materializan como `IRJump` al target
activo. En SSA se conservan como `SSAJump`.

Observaciones:

- El stack `context.loop_targets` permite nested loops y `break`/`continue`
  dentro de `if`.
- Para `for`, `continue` usa `for.incN`; para `while`, `continue` usa `condN`.
- Los verificadores solo ven jumps normales, lo cual mantiene simple el CFG.

Riesgos:

- La semantica de target de loop esta centralizada en `_loop_context`; si se
  agrega otro loop o forma de lowering, debe declarar explicitamente
  `break_target` y `continue_target`.
- Un `continue` como ultimo statement produce un jump explicito y no debe
  recibir un jump adicional al final del body. La logica actual lo evita con
  `_emit_jump_if_open` y ya tiene regresion dedicada en backend.

### return

`return` baja a `IRReturn`, con valor o vacio segun tipo de funcion. En SSA
se convierte a `SSAReturn` y LLVM emite `ret`.

Observaciones:

- `IRVerifier` valida tipo de retorno y que funciones no-void retornen en todos
  los caminos.
- `return` preserva la terminacion de bloque a traves de IR, SSA, optimizers y
  LLVM.

Riesgos:

- `return` dentro de loop esta soportado como terminador de bloque, pero falta
  una regresion source-to-LLVM especifica para `return` temprano dentro de
  `while`/`for`.
- Como no se generan bloques unreachable para statements posteriores, la
  politica actual es "fallar en lowering" si aparecen statements despues del
  terminador en el mismo cuerpo.

## Invariantes de CFG

Invariantes ya protegidos:

- Cada bloque debe tener terminador.
- Un terminador debe aparecer al final del bloque.
- `IRJump` y `IRBranch` deben apuntar a bloques existentes.
- `IRBranch`/`SSABranch` requieren condicion bool.
- Los CFG edges se derivan de terminadores finales.
- Los bloques inalcanzables no se rechazan por existir; se tratan de forma
  conservadora por dominadores y dominance frontier.

Invariantes parcialmente protegidos:

- `CFGBuilder` no valida estructura; asume IR/SSA verificado. Si se usa sobre
  IR no verificado, puede omitir edges de terminadores mal ubicados o bloques
  vacios.
- `IRVerifier` hace dataflow sobre bloques alcanzables e inspecciona bloques
  inalcanzables con un estado permisivo para detectar errores locales de tipo,
  nombres, llamadas y targets sin exigir stores visibles por caminos que no
  existen. No elimina unreachable.
- `DominatorAnalysis` deja bloques inalcanzables dominados solo por si mismos
  y con `idom = None`.
- `DominanceFrontierAnalysis` ignora bloques inalcanzables al calcular
  frontiers.

Riesgos:

- No hay pass IR de eliminacion de bloques inalcanzables. La primera limpieza
  real de unreachable aparece en SSA SCCP.
- El contrato "un solo terminador real y ultimo" esta duplicado entre IR y SSA
  verifier.
- Nested loops y `break`/`continue` dentro de `if` dependen mas de pruebas de
  integracion que de helpers con invariantes explicitos.

## SSA

### Phi placement

La ruta principal es `GeneralSSABuilder`, que ejecuta:

1. `CFGBuilder`
2. `DominatorAnalysis`
3. `DominanceFrontierAnalysis`
4. `PhiPlacement`
5. `SSARenamer`
6. `SSAVerifier`

`PhiPlacement` usa:

- bloques con `IRStore` como definitions;
- live-in por bloque, basado en loads antes de stores;
- inicializacion por todos los predecessors para evitar phis que no pueden
  tener valor visible.

Esto cubre los casos centrales:

- variables loop-carried;
- variables asignadas en ambos lados de un `if`;
- nested if;
- nested loops;
- multiples slots loop-carried;
- poda de phis no vivos.

### Renaming

`SSARenamer` recorre el arbol de dominadores:

- crea phis al inicio del bloque;
- convierte stores en push sobre stack de slot;
- convierte loads en el top visible del slot;
- al final de cada bloque agrega incoming a phis de sucesores usando el estado
  actual;
- no ensambla bloques no visitados.

Riesgos:

- El verificador SSA actual valida phis estructuralmente, pero no exige que un
  phi tenga exactamente un incoming por cada predecessor alcanzable. Si se
  construye SSA por fuera del builder, un phi con incoming faltante podria pasar
  algunas validaciones mientras sus tipos y predecessor names sean validos.
- El verificador SSA tampoco valida dominancia de cada uso no-phi. El builder
  general deberia producir SSA correcta, pero el verifier no cierra totalmente
  el contrato.
- Bloques inalcanzables se omiten al ensamblar SSA general. Esto es razonable,
  pero deberia quedar documentado como politica del builder y cubierto con
  tests source/IR mas directos.
- Variables inicializadas solo dentro de un loop y usadas despues deben fallar
  antes o durante verificacion IR/SSA. Hay tests manuales de verifier, pero
  faltan casos fuente dedicados en backend compilado.

## Optimizers

### IR optimizer

El optimizer IR actual es local/conservador:

- constant folding;
- local constant propagation;
- algebraic simplification;
- dead code;
- dead store.

Observaciones:

- Los terminadores no se eliminan.
- `DeadCodeEliminator` trata branch conditions y return values como usos vivos.
- `DeadStoreEliminator` conserva stores frente a branches, jumps y loops.
- No hay simplificacion IR de branches ni eliminacion IR de bloques
  inalcanzables.

Riesgos:

- Al no tener cleanup de CFG en IR, cualquier unreachable real via source o
  futuras transformaciones queda para etapas posteriores.
- La seguridad depende de que los passes sigan siendo locales. Si se agrega
  optimizacion global IR, debe compartir utilidades de CFG/verificacion.

### SSA optimizer

El pipeline SSA por defecto incluye:

- constant folder;
- global constant propagation;
- algebraic simplifier;
- SCCP;
- trivial phi elimination;
- dead phi elimination;
- dead code elimination.

Observaciones:

- SCCP es edge-sensitive: mantiene bloques y edges ejecutables.
- SCCP puede reemplazar branches bool constantes por jumps.
- SCCP elimina bloques no ejecutables y limpia incoming de phis desde bloques
  removidos.
- Hay checks para no dejar terminadores apuntando a bloques eliminados.
- Dead code conserva branches, jumps y returns.

Riesgos:

- La limpieza de SCCP asume que el conjunto de executable edges es consistente
  con los phis. Si futuros passes eliminan/reordenan bloques fuera de SCCP,
  haran falta helpers compartidos para reescribir phis y targets.
- Trivial/dead phi eliminan phis por usos, pero no hacen pruning semantico de
  phis redundantes mas alla de casos triviales.
- Falta una bateria source-to-optimized-SSA/LLVM para loops con `break`,
  `continue`, `return` y condiciones constantes.

## LLVM

`LLVMPrinter` emite:

- labels desde nombres de bloques SSA;
- `br i1` para `SSABranch`;
- `br label` para `SSAJump`;
- `ret` para `SSAReturn`;
- `phi` LLVM con incoming `[ value, %label ]`;
- nombres estables mediante reserva de temps y escaping de labels/values.

Observaciones:

- Los tests cubren jumps, branches, phis int/bool/string, orden de incoming y
  loops simples generados.
- La emision de control de flujo fuente (`for`) pasa por CLI y ejemplos LLVM.
- El printer tiene helpers para loops sinteticos de algebra lineal, separados
  del control-flow SSA de usuario.

Riesgos:

- Hay bastante helper para loops sinteticos internos, pero labels/branches/phis
  de SSA todavia estan repartidos en metodos pequenos sin un helper de
  "terminator/control-flow emission" compartido.
- La calidad de nombres depende de convenciones de lowering (`for.condN`,
  `condN`, `mergeN`) y de escaping posterior. Es estable hoy, pero podria
  degradarse al agregar nuevas formas de loops/listas si los nombres no se
  centralizan.
- Falta cobertura LLVM compilada para nested loops con `break`/`continue` en
  ambos niveles, `return` temprano dentro de loop y loops con branch constante.

## Cobertura de tests

### Bien cubierto

- `if` con returns en ambas ramas.
- `if` sin `else` con merge.
- `if`/`else` con asignacion y phi posterior.
- `while` simple, countdown y body vacio.
- CFG de `if` y `while`.
- Dominadores y dominance frontier para lineal, if/else, while e unreachable.
- Phi placement para if/else, while, sum-to, nested if y unreachable manual.
- SSA renaming para if/else, while, sum-to y nested if.
- SSA builder general con nested if, if-in-while, while-in-if, multiples
  loop-carried slots, sequential loops y nested while manual.
- IR verifier para target invalido, branch bool, load antes de store, stores
  visibles en merges/loops y retorno en todos los caminos.
- SSA verifier para phis basicos, incoming block inexistente, predecessor
  invalido, tipos, duplicados y phi vacio.
- SCCP para branches constantes, phis con incoming ejecutables, eliminacion de
  bloques inalcanzables y limpieza de incoming.
- LLVM printer para branch, jump, phi, orden de incoming y smoke tests con
  clang.
- `for` backend: range simple, nested ranges, dynamic step, break/continue
  dentro de if, while con break/continue, SSA con nested loop phis, optimizers,
  LLVM textual, CLI emit/build/run.
- Regresiones criticas de control de flujo en
  `tests/aether/test_control_flow_regression.py`: `for` vacio, `continue` como
  ultimo statement, `break` incondicional, `return` temprano en `for`/`while`,
  nested loops con `break`/`continue` internos, variables loop-carried
  modificadas desde loops internos, variables locales de loop con scope correcto,
  phis para variables inicializadas antes/modificadas dentro/usadas despues,
  SCCP con `while false`, `while true` con salida por `break`, `for` sobre
  `Array`/`Vector` con `break`/`continue` y rango con step dinamico negativo
  mas `continue`.

### Huecos recomendados

La parte critica de Fase 5 ya esta implementada. Quedan huecos utiles, pero no
bloqueantes para iniciar la refactorizacion:

- Mas combinaciones LLVM/clang de nested loops profundos, especialmente mezclas
  de `break`, `continue` y mutacion de varias variables loop-carried.
- Regresiones negativas explicitas para statements fuente despues de
  terminadores dentro del mismo body, documentando si la politica queda como
  error de lowering o si se agregara pruning de unreachable.
- Casos de optimizer con branches constantes dentro de loops anidados, no solo
  condiciones constantes del loop principal.
- Tests especificos de verificador SSA para incoming exacto por predecessor
  alcanzable y dominancia de usos, que pertenecen a Fase 3.

## Hallazgos principales

1. La implementacion es funcional y el lowering de control de flujo ya tiene
   helpers privados para las operaciones CFG repetidas.
2. `while`, `for range` y `for indexable` comparten el protocolo comun:
   crear bloques, saltar a condicion, bajar body, agregar jump final si no esta
   terminado, crear incremento/salida y restaurar contexto.
3. El stack de loop targets funciona y esta encapsulado como API privada de
   lowering de loops.
4. CFG y verificadores protegen las invariantes basicas; dominancia y
   frontiers ya modelan unreachable de forma conservadora.
5. La construccion SSA general esta bien ubicada como default y reemplaza la
   necesidad del builder pattern para control-flow real.
6. La verificacion SSA aun no expresa todo el contrato SSA: incoming exactos por
   predecessor alcanzable y dominancia de usos son los huecos mas importantes.
7. SCCP es el primer pass que cambia CFG de manera sustancial. Sus helpers de
   cleanup deberian volverse base comun si se agregan mas transforms de CFG.
8. LLVM emite bien control flow SSA, pero conviene separar helpers de terminador
   y phi para evitar duplicacion cuando crezca `List<T>`.

## Plan de refactorizacion propuesto

### Fase 1: helpers privados de lowering/CFG

Estado: implementada.

Objetivo: reducir duplicacion sin cambiar IR.

- Helpers internos agregados en `IRLowerer` para:
  - crear bloques con nombres estables;
  - emitir jump solo si el bloque actual no esta terminado;
  - emitir branch bool ya validada;
  - entrar/salir de bloque;
  - crear merge condicional de `if`;
  - construir la forma `cond/body/exit`.
- Mantener nombres actuales para no romper tests.
- No se agregaron tests nuevos en esta fase porque las regresiones criticas ya
  congelan nombres y comportamiento relevante.

### Fase 2: unificar stacks y destinos de loops

Estado: implementada.

Objetivo: hacer explicita la semantica de `break`/`continue`.

- Se creo `_loop_context`, un context manager privado para entrar a un loop con
  `break_target` y `continue_target`.
- Se unifico el patron de body:
  - bajar statements;
  - si body no termina, saltar al target natural;
  - restaurar loop target aunque haya error.
- La restauracion de loop variable en `for` queda dentro del mismo context
  manager.
- Queda documentado que `continue` de `for` apunta a `inc` y `continue` de
  `while` apunta a `cond`.

### Fase 3: simplificar/pruning de phis

Objetivo: fortalecer contrato SSA y reducir phis innecesarios.

- Extender `SSAVerifier` para:
  - exigir incoming exacto por predecessor alcanzable;
  - validar dominancia de usos no-phi;
  - validar que incoming phi este disponible sobre el edge correspondiente.
- Documentar politica de bloques inalcanzables en SSA general.
- Considerar pruning adicional despues de renaming, antes de optimizers:
  - phis no usados;
  - phis triviales;
  - phis insertados por inicializacion conservadora.

### Fase 4: helpers LLVM de control flow

Objetivo: estabilizar emision y nombres.

- Extraer helpers de printer para:
  - labels;
  - terminadores;
  - phi incoming;
  - validacion de targets si se decide hacer una pasada defensiva.
- Reusar convenciones de escaping en un solo punto.
- Mantener la emision textual actual para no cambiar fixtures.

### Fase 5: completar tests de regresion

Objetivo: cubrir la matriz de casos borde antes de `List<T>`.

- Estado: parte critica implementada en
  `tests/aether/test_control_flow_regression.py`.
- Agregar tests backend restantes para los huecos no bloqueantes listados
  arriba.
- Separar tests por capa cuando convenga:
  - lowering/IR exacto;
  - verifier/CFG;
  - SSA/phis;
  - optimizer/SCCP;
  - LLVM textual;
  - clang smoke solo para casos de alto valor.
- Ya hay regresiones para nested loops con `break` y con `continue`; ampliar a
  mas combinaciones solo si la refactorizacion toca esos targets.

## Recomendacion antes de `List<T>`

Antes de bajar `List<T>`, Fase 1, Fase 2 y la parte critica de Fase 5 ya
quedaron ejecutadas. `List<T>` probablemente agregue iteracion sobre
colecciones, mutacion, aliases y length dinamico; eso va a presionar targets de
loops, slots visibles, phis loop-carried y cleanup de CFG.

Fase 3 puede hacerse en paralelo o inmediatamente despues, porque no deberia
cambiar lowering. Fase 4 es menos urgente, pero ayuda a mantener calidad del
LLVM cuando aparezcan mas operaciones de colecciones.
