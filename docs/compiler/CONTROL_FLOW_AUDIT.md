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

El mayor riesgo no es que falte una pieza principal, sino que la superficie de
control de flujo crecio con bastante duplicacion manual. Eso vuelve fragiles
los cambios siguientes: cualquier ajuste para loops, scopes de variables,
targets de `break`/`continue`, pruning de phis o limpieza de CFG deberia tocar
varias formas parecidas.

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

- La logica de merge y terminacion vive directamente en `_lower_if`, no en un
  helper reusable.
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

- La construccion de bloques, jumps y stack de targets esta duplicada con
  `for`.
- El destino de `continue` para `while` es el bloque de condicion, mientras que
  para `for` es el bloque de incremento. Esto es correcto, pero hoy depende de
  llamadas manuales a `_LoopTargets` en cada lowerer.
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

- `_lower_for_range` y `_lower_for_indexable` duplican estructura casi completa:
  nombres, cond/body/inc/exit, push/pop de targets, jump final del body,
  incremento, bloque de salida y restauracion de locals.
- El step dinamico introduce una sub-CFG manual mas compleja que deberia quedar
  cubierta por helpers de condicion y targets.
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

- La semantica de target de loop no esta centralizada. Si se agrega otro loop o
  forma de lowering, hay que recordar manualmente ambos destinos.
- Un `continue` como ultimo statement produce un jump explicito y no debe
  recibir un jump adicional al final del body. La logica actual lo evita con
  `_is_terminated`, pero falta una regresion dedicada en backend para ese caso.

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
  inalcanzables con estado de entrada minimo para detectar errores locales.
  No elimina unreachable.
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

### Huecos recomendados

Los siguientes casos deberian agregarse como regresiones antes o durante la
refactorizacion:

- `for` vacio en backend IR/SSA/LLVM.
- `for` con body que termina siempre, por ejemplo body con `return` o `break`
  incondicional.
- `continue` en ultimo statement del body, verificando que no se duplica jump.
- `break` en nested loop via backend compilado, no solo frontend AST.
- `continue` en nested loop via backend compilado, no solo frontend AST.
- `return` dentro de `while` y `for`, con salida LLVM/clang si aplica.
- Variable declarada dentro del loop y usada solo dentro del loop.
- Variable declarada dentro del loop y usada despues del loop como error
  frontend/backend documentado.
- Variable asignada dentro del loop y usada despues del loop cuando tambien
  esta inicializada antes del loop.
- Loop con condicion constante `false` y `true` a traves de SSA optimizer/SCCP.
- Loop con bloques unreachable producidos por branch constante.
- `break` en inner loop y uso posterior de variable outer loop-carried.
- `continue` en inner loop y phis de variable outer/inner loop-carried.
- `for` sobre array/vector indexable con `break`/`continue`.
- `for` con step dinamico negativo y `continue`.
- Nested loops emitidos a LLVM y ejecutados con clang.

## Hallazgos principales

1. La implementacion es funcional, pero el lowering de control de flujo esta
   demasiado manual.
2. `while`, `for range` y `for indexable` repiten el mismo protocolo:
   crear bloques, saltar a condicion, bajar body, agregar jump final si no esta
   terminado, crear incremento/salida y restaurar contexto.
3. El stack de loop targets funciona, pero no esta encapsulado como API de
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

Objetivo: reducir duplicacion sin cambiar IR.

- Agregar helpers internos en `IRLowerer` para:
  - crear bloques con nombres estables;
  - emitir jump solo si el bloque actual no esta terminado;
  - emitir branch bool ya validada;
  - entrar/salir de bloque;
  - crear merge condicional de `if`;
  - construir la forma `cond/body/exit`.
- Mantener nombres actuales para no romper tests.
- Agregar tests de snapshot donde los nombres importen.

### Fase 2: unificar stacks y destinos de loops

Objetivo: hacer explicita la semantica de `break`/`continue`.

- Crear un helper/context manager privado para entrar a un loop con
  `break_target` y `continue_target`.
- Unificar el patron de body:
  - bajar statements;
  - si body no termina, saltar al target natural;
  - restaurar loop target aunque haya error.
- Compartir restauracion de loop variable en `for`.
- Dejar documentado que `continue` de `for` apunta a `inc` y `continue` de
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

- Agregar tests backend para todos los huecos listados arriba.
- Separar tests por capa cuando convenga:
  - lowering/IR exacto;
  - verifier/CFG;
  - SSA/phis;
  - optimizer/SCCP;
  - LLVM textual;
  - clang smoke solo para casos de alto valor.
- Agregar al menos un test end-to-end para nested loops con `break` y otro con
  `continue`.

## Recomendacion antes de `List<T>`

Antes de bajar `List<T>` conviene ejecutar al menos Fase 1, Fase 2 y la parte
critica de Fase 5. `List<T>` probablemente agregue iteracion sobre colecciones,
mutacion, aliases y length dinamico; eso va a presionar exactamente las zonas
que hoy estan duplicadas: targets de loops, slots visibles, phis loop-carried y
cleanup de CFG.

Fase 3 puede hacerse en paralelo o inmediatamente despues, porque no deberia
cambiar lowering. Fase 4 es menos urgente, pero ayuda a mantener calidad del
LLVM cuando aparezcan mas operaciones de colecciones.
