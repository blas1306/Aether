# Auditoría de control de flujo e iteración de Aether

> Clasificación: **Audit**. Este documento describe el comportamiento observado;
> no modifica la especificación normativa ni promete capacidades nuevas.

Fecha de corte: **17 de julio de 2026**  
Repositorio auditado: commit `bee88b8`  
Versión de lenguaje al corte: **1.0.0-rc.1**

> Estado posterior a la auditoría: los P0 de control-flow identificados aquí
> quedaron implementados para rc.2. El parser exige headers parentizados,
> `else if` usa nesting AST, existe formatter/migrador token-aware y el LSP
> publica formatting/snippets canónicos. Paso dinámico cero y extremos
> `INT_MAX`/`INT_MIN` tienen paridad AST/IR/native. Las descripciones de rc.1
> que siguen se conservan como evidencia histórica del hallazgo, no como
> gramática vigente. Véase [la guía de migración](RC2_CONTROL_FLOW_MIGRATION.md).

## 1. Resumen ejecutivo

La sintaxis implementada hoy es la sintaxis sin paréntesis de rc.1. `if` y
`while` aceptan accidentalmente una condición entre paréntesis porque `(...)`
ya es una expresión agrupada; los paréntesis no forman parte de sus
producciones y desaparecen del AST. `for (...)` no parsea. `else if` tampoco es
una producción: la alternativa actual exige que `else` vaya seguido
inmediatamente de `{`. La forma equivalente disponible es `else { if ... }`.

La implementación tiene buen soporte end-to-end para:

- `if`/`else`, `while`, `break`, `continue` y retorno desde loops;
- rangos enteros inclusivos, ascendentes y descendentes, con paso explícito;
- `for-in` inferido o con anotación exacta sobre `Range<int>`, `Array<T>`,
  `List<T>` y `Vector<T>`;
- elementos struct en colecciones en AST y native;
- scopes por bloque y cleanup explícito de IR en salidas normales,
  `break`, `continue` y `return`.

No hay soporte actual para rangos flotantes. La restricción no está localizada
en una sola capa: aparece en `RangeType`, typechecker, intérprete AST y lowering
de IR. IR ni siquiera tiene un valor `Range` materializado; reconoce el
`RangeExpression` directamente dentro de `for` y genera el CFG del loop.

La auditoría congeló dos divergencias relevantes entre AST y native:

1. Un paso cero dinámico lanza `Range step cannot be zero` al comenzar la
   iteración AST, pero IR/native lo consideran un rango vacío. Un paso cero
   estático llega a AST y falla en runtime, mientras que el perfil native y el
   lowerer lo rechazan antes de ejecutar.
2. En `2147483647:2147483647`, AST ejecuta el único elemento y termina. IR y
   native intentan incrementar el iterador después del cuerpo y hacen panic por
   overflow entero.

Para rc.2 se recomienda introducir producciones explícitas con `(` y `)` y
diagnósticos dedicados antes de migrar corpus y tooling. Para rangos generales
se recomienda conservar un tipo nominal genérico restringido `Range<T>`, al
principio con `T = int | float | double`, valores perezosos y cálculo del valor
por índice. La primera implementación native debería habilitar `Range<double>`
sin diseñar todavía una API pública completa de `Iterator<T>`.

## 2. Método y alcance

Se inspeccionaron parser, tokens, AST, typechecker, intérprete AST, lowering,
modelo/verifier/intérprete/printer IR, construcción SSA, optimizadores, printer
LLVM, capability gate, LSP, editores, plugin IntelliJ, ejemplos y documentos.
Las afirmaciones se contrastaron con tests ejecutables. No se cambió sintaxis,
semántica, verifier ni perfil de capacidades.

Los tests nuevos están en
`tests/aether/test_control_flow_iteration_characterization.py`: 24 casos que
registran el comportamiento vigente, incluidas las limitaciones anteriores.

## 3. Gramática real del parser

La siguiente EBNF es descriptiva de `src/aether/parser.py`, no normativa:

```ebnf
statement       ::= "if" expression block ("else" block)?
                  | "while" expression block
                  | "for" forBinding "in" expression block
                  | "break" ";"
                  | "continue" ";"
                  | "return" expression? ";"
                  | ...

forBinding      ::= IDENTIFIER
                  | typeAnnotation IDENTIFIER

block           ::= "{" statement* "}"

expression      ::= rangeExpression
rangeExpression ::= logicalOr
                  | logicalOr ":" logicalOr
                  | logicalOr ":" logicalOr ":" logicalOr
```

`rangeExpression` tiene la precedencia más baja. En `start:step:end`, el AST
reordena los operandos a `RangeExpression(start, end, step)`. No se aceptan más
de dos `:` en una expresión de rango.

### 3.1 Tokens consumidos

| Forma | Consumo real |
| --- | --- |
| `if e { b }` | `IF`, una expresión completa, `LEFT_BRACE`, statements, `RIGHT_BRACE`; opcionalmente `ELSE` y otro bloque. |
| `while e { b }` | `WHILE`, una expresión completa y un bloque. |
| `for x in e { b }` | `FOR`, `IDENTIFIER`, `IN`, expresión y bloque. |
| `for T x in e { b }` | `FOR`, type annotation, `IDENTIFIER`, `IN`, expresión y bloque. |
| `a:b` | expresión lógica, `COLON`, expresión lógica. |
| `a:s:b` | lo anterior, segundo `COLON`, tercera expresión lógica. |
| `break;` / `continue;` | keyword y `SEMICOLON`. |

Lexer y parser comparten `TokenType.IF`, `ELSE`, `WHILE`, `FOR`, `IN`,
`BREAK`, `CONTINUE` y `COLON`. Los literales con punto o exponente son
`FLOAT_LITERAL`, pero el parser les asigna el tipo de lenguaje `double`.

### 3.2 Ambigüedades y lookahead

El encabezado tipado de `for` se decide con lookahead, no mediante backtracking.
`_type_annotation_end_cursor` debe encontrar una anotación válida seguida por
`IDENTIFIER IN`. Sólo entonces el parser consume un tipo. Esto permite tipos
genéricos y nominales (`List<int>`, alias, `User`) sin confundir siempre el
primer identificador con la variable inferida.

La consecuencia diagnóstica es que un header casi tipado puede caer en la rama
inferida. Por ejemplo, `for int i 1:3` informa `Expected loop variable after
'for'. near 'int'.`, no “Expected 'in'”. Es correcto respecto del algoritmo
actual, pero no es un diagnóstico orientado al usuario.

El `:` también se usa en slicing. `_index_component` reconoce primero un `:`
solo como `FullSlice`; de otro modo llama a la misma expresión de rango. Esta
decisión permite `values[start:end]`, pero no cambia la semántica de rango del
`for`: las slices de colecciones son semiabiertas y los rangos iterados son
inclusivos.

### 3.3 Paréntesis actuales

| Fuente | Resultado actual | Causa |
| --- | --- | --- |
| `if (condition) {}` | Aceptada | `(...)` es una primary expression agrupada. |
| `while (condition) {}` | Aceptada | Igual que `if`. |
| `for (i in values) {}` | Rechazada | Después de `FOR` se espera binding, no `LEFT_PAREN`. |
| `for (int i in 1:10) {}` | Rechazada | Igual que la forma inferida. |
| `else if condition {}` | Rechazada | Después de `ELSE`, `_block()` exige `{`. |

El AST no conserva paréntesis de agrupación. Por tanto, después de parsear no
se puede distinguir `if e` de `if (e)`. La migración debe diagnosticarse y/o
reescribirse desde tokens o texto fuente, no desde el AST actual.

### 3.4 Diagnósticos actuales de headers mal formados

| Entrada | Diagnóstico observado |
| --- | --- |
| `for in 1:3 {}` | `Expected loop variable after 'for'.` |
| `for i 1:3 {}` | `Expected 'in' after loop variable.` |
| `for int i 1:3 {}` | `Expected loop variable after 'for'.` |
| `for int i in` | termina intentando formar la expresión/bloque; no hay diagnóstico específico del header. |
| `for (i in 1:3) {}` | `Expected loop variable after 'for'. near '('.` |
| `else if ...` | `Expected '{' before block. near 'if'.` |

Hacer obligatorios los paréntesis requiere separar el parseo de la condición
del parseo de expresión general: consumir `LEFT_PAREN`, parsear exactamente una
expresión, consumir `RIGHT_PAREN` y recién entonces el bloque. En `for`, los
paréntesis deben envolver binding, `in` e iterable; el lookahead tipado se
ejecutará dentro de ellos.

## 4. AST e intérprete AST

### 4.1 Nodos

| Construcción | Nodo y campos |
| --- | --- |
| `if` / `else` | `IfStatement(condition: Expression, body: list[Statement], else_body: list[Statement] | None, line, column)`. |
| `while` | `WhileStatement(condition, body, line, column)`. |
| `for-in` | `ForInStatement(variable: str, iterable: Expression, body, line, column, variable_type: AetherType | None)`. |
| rango | `RangeExpression(start, end, step: Expression | None)`. No guarda ubicación propia. |
| `break` | `BreakStatement(line, column)`. |
| `continue` | `ContinueStatement(line, column)`. |
| `return` | `ReturnStatement(expression | None, line, column)`. |

No existe un nodo `ElseIfStatement`; el anidamiento dentro de `else_body` es la
única representación posible hoy.

### 4.2 Evaluación, scopes y señales

`if` y `while` evalúan su condición y exigen un valor de tipo `boolean`; no hay
truthiness. Cada cuerpo ejecutado recibe un `Environment(parent=env)`. `if`
crea un environment para la rama elegida. `while` crea uno nuevo en cada
iteración.

`break`, `continue` y `return` se implementan como señales internas de Python.
`while` y `for` capturan sólo las dos primeras; `return` atraviesa el loop hasta
el marco de función. `_execute_block` siempre ejecuta `Environment.cleanup()`
en `finally`, también cuando sale una señal o excepción. Para retornos con
valores propietarios protege/transfiere los owners necesarios antes del
cleanup local.

La variable de `for`:

- vive en un environment nuevo por iteración;
- es `const`, no owning y está marcada como borrowed iteration;
- no puede sombrear bindings visibles;
- deja de ser válida y sale de scope al finalizar la iteración;
- no escapa del loop.

La expresión iterable se evalúa una sola vez. Array, List y Vector producen una
lista host superficial para recorrer; cada `AetherValue` elemento se vincula
como préstamo, no como copia propietaria. El typechecker prohíbe reasignar la
variable iteradora y controla mutaciones incompatibles del elemento o de la
colección activa.

Además de las formas solicitadas, AST acepta una Matrix vector-like. IR/native
no la incluye en `_lower_indexable_iterable`, por lo que no debe confundirse
con soporte native de Matrix general.

### 4.3 Semántica actual de `RangeExpression`

| Aspecto | Comportamiento AST actual |
| --- | --- |
| Tipo | Sólo `Range<int>`. |
| Evaluación | `start`, luego `end`, luego `step`; cada operando una vez. El paso omitido es `1`. |
| Extremo | Inclusivo: positivo usa `current <= end`, negativo `current >= end`. |
| Dirección | Paso positivo con `start > end` y paso negativo con `start < end` producen rango vacío. El paso por defecto no infiere descenso. |
| Paso cero | Aceptado por parser/typechecker; `AetherRange.__iter__` lanza `AetherTypeError` al comenzar a iterar. |
| Materialización | Perezosa: `AetherRange.__iter__` es generador. |
| Avance | Suma acumulativa `current += step`, no cálculo por índice. |
| Overflow | El contador usa `int` host sin límite; no aplica checked i32 al avance del rango. |

Las restricciones `int` están en:

1. `types.RangeType.__post_init__`, que rechaza cualquier element type distinto
   de `int`;
2. `typechecker.TypeChecker._range_type`, que exige `int` para start/end/step;
3. `interpreter.Interpreter._evaluate_range`, que repite el chequeo dinámico;
4. los campos tipados `int` y el valor emitido por `AetherRange`;
5. el lowering de IR descrito más adelante.

## 5. Typechecker y matriz de compatibilidad

El typechecker calcula primero el tipo del iterable. `_iterable_element_type`
admite `RangeType`, `ArrayType`, `ListType`, `VectorType` y Matrix vector-like.
Si el header tiene tipo explícito, exige igualdad exacta con el elemento. No
aplica conversiones implícitas en el header. Con header inferido, el símbolo de
loop recibe directamente el element type.

Tomadas literalmente con la sintaxis rc.2 propuesta, todas las filas pedidas
se detienen en la misma frontera actual:

| Fuente exacta | Parse | Typecheck / tipo inferido | AST ejecutable | IR/native |
| --- | --- | --- | --- | --- |
| `for (int i in 1:10) {}` | No: `Expected loop variable after 'for'.` | No alcanza TC | No | No |
| `for (i in 1:10) {}` | No: mismo diagnóstico | No alcanza TC | No | No |
| `for (double i in 1:10) {}` | No: mismo diagnóstico | No alcanza TC | No | No |
| `for (double i in 1:0.1:10) {}` | No: mismo diagnóstico | No alcanza TC | No | No |
| `for (i in 1:0.1:10) {}` | No: mismo diagnóstico | No alcanza TC | No | No |
| `for (int i in 1:0.1:10) {}` | No: mismo diagnóstico | No alcanza TC | No | No |
| `for (string s in strings) {}` | No: mismo diagnóstico | No alcanza TC | No | No |
| `for (User u in users) {}` | No: mismo diagnóstico | No alcanza TC | No | No |
| `for (u in users) {}` | No: mismo diagnóstico | No alcanza TC | No | No |

Para distinguir esa limitación puramente sintáctica de las capacidades de las
capas posteriores, la matriz siguiente retira solamente los paréntesis y usa
la gramática rc.1 implementada:

| Caso | Parse | Typecheck / inferencia | Conversión y diagnóstico | AST | IR/native |
| --- | --- | --- | --- | --- | --- |
| `for int i in 1:10 {}` | Sí | Sí; `i: int`. | Ninguna. | Sí | Sí |
| `for i in 1:10 {}` | Sí | Sí; infiere `i: int`. | Ninguna. | Sí | Sí |
| `for double i in 1:10 {}` | Sí | **No**. | No promueve el elemento: `expected 'double', got 'int'`. | Nodo sí, ejecución chequeada no | No |
| `for double i in 1:0.1:10 {}` | Sí | **No**. | El rango falla antes: `Range bounds and step must be int, got 'double'.` | Nodo sí | No |
| `for i in 1:0.1:10 {}` | Sí | **No**. | Mismo diagnóstico de rango; no se infiere `double`. | Nodo sí | No |
| `for int i in 1:0.1:10 {}` | Sí | **No**. | Mismo diagnóstico de rango. | Nodo sí | No |
| `for string s in strings {}` con colección string | Sí | Sí; `s: string`. | Coincidencia exacta. | Sí | Sí dentro del perfil. |
| `for User u in users {}` con struct | Sí | Sí; `u: User`. | Coincidencia nominal exacta. | Sí | Sí para structs representables. |
| `for u in users {}` | Sí | Sí; infiere el element type nominal. | Ninguna. | Sí | Sí para structs; class sigue AST-only. |

Un `List<User>` donde `User` es class itera correctamente en AST, tanto con
header explícito como inferido, pero el capability gate native rechaza classes
antes del lowering. No es una divergencia silenciosa.

## 6. Matriz de soporte por capa

| Capacidad | Parser/AST | Typechecker | AST runtime | IR/IR interpreter | SSA/LLVM native |
| --- | --- | --- | --- | --- | --- |
| `if` | Sí | condición bool | Sí | Sí | Sí |
| `else if` directo | **No** | — | — | — | — |
| `else` | Sí | Sí | Sí | Sí | Sí |
| `while` | Sí | condición bool | Sí | Sí | Sí |
| rango int | Sí | `Range<int>` | Sí, lazy/inclusivo | lowering directo | Sí, i32 |
| rango float/double | Sí como AST sintáctico | **Rechazado** | No tras TC | **Rechazado** | **Rechazado** |
| Array | Sí | Sí | préstamo | indexable | Sí |
| List | Sí | Sí | préstamo | indexable | Sí |
| Vector | Sí | Sí | préstamo | indexable | Sí |
| Matrix vector-like | Sí | Sí | Sí | **No** | **No** |
| iterador explícito | Sí | igualdad exacta | Sí | usa element type chequeado | Sí |
| iterador inferido | Sí | element type | Sí | usa element type chequeado | Sí |
| `break` | Sí | sólo dentro de loop | señal | jump + cleanup | Sí |
| `continue` | Sí | sólo dentro de loop | señal | jump + cleanup | Sí |
| retorno en loop | Sí | reglas de función | atraviesa loop + cleanup | return + cleanup | Sí |
| scopes por iteración | Sí | Scope hijo | Environment hijo | scopes/lifetimes explícitos | Sí |

## 7. Lowering y modelo IR

### 7.1 `if`

El lowerer genera `thenN`, opcional `elseN` y `mergeN`. La condición baja a un
valor IR y `_emit_branch` exige `BoolType`. Las ramas abiertas saltan al merge;
si ambas terminan, no se inventa un merge alcanzable. El IR no conserva la
sintaxis fuente de paréntesis.

### 7.2 `while`

El CFG es:

```text
preheader -> condN --true--> bodyN -> condN
                    \false------------> exitN
```

`continue` salta a `condN`; `break` a `exitN`. La condición se recalcula en
cada vuelta.

### 7.3 Rango entero

IR no representa un objeto Range ni una instrucción de rango. `_lower_for_in`
reconoce que el iterable AST es exactamente `RangeExpression` y usa un camino
especial:

```text
preheader -> for.condN -> for.bodyN -> for.incN -> for.condN
                     \---------------------------> for.exitN
```

Start, end y step se evalúan una vez en el preheader. El paso omitido es una
constante `IntType(1)`. Los tres operandos deben ser `IntType`; la variable de
loop es storage `IntType`. El incremento es `IRBinaryOp(add)` y `IRAssign`.

Para paso constante, la condición es `le` si es positivo y `ge` si es
negativo. Un cero constante hace fallar el lowerer. Para paso dinámico se
generan `for.posN`, `for.negN` y `for.neg.boundN`: `step > 0` elige `<=`,
`step < 0` elige `>=`, y cero va directamente a exit. Ésta es la causa de la
divergencia con AST.

Toda esta ruta está estructuralmente fijada a `IntType`, no sólo limitada por
el typechecker. Para `Range<double>` habrá que parametrizar storage,
constantes, comparaciones, incremento y política de cero.

### 7.4 Array/List/Vector

El iterable se evalúa una vez y se obtiene su longitud. El lowerer crea un
índice interno `IntType` y un binding de elemento no propietario:

| Contenedor | Inicio | Condición | Lectura |
| --- | --- | --- | --- |
| Array | 0 | `index < length` | `IRArrayGet(..., borrowed=True)` |
| List | 0 | `index < length` | `IRListGet(..., borrowed=True)` |
| Vector | 1 | `index <= length` | `IRVectorGet` |

El índice de Vector refleja la indexación pública one-based del contenedor.
Los índices de Array/List son zero-based. La anotación explícita ya fue
validada por el typechecker; el lowerer usa el element type real.

### 7.5 Break, continue y lifecycle

`_LoopTargets` guarda targets y la profundidad de scope al entrar al loop.
Antes de un salto anticipado, `_emit_cleanup` destruye en orden inverso todos
los storages creados en scopes más internos:

- `break`: cleanup del cuerpo y jump al exit; el exit completa cleanup del
  storage iterador y temporales del loop;
- `continue`: cleanup del cuerpo y jump a condición (`while`) o incremento
  (`for`);
- `return`: transfiere/protege el valor retornado, limpia todos los scopes
  vivos y emite `IRReturn`;
- salida normal: el context manager de scope emite los `IRDestroy` pendientes.

Los elementos de colecciones se leen como préstamos y no se copian/destruyen
como owners en cada iteración. El contenedor o temporal iterable conserva su
lifetime alrededor del loop. `LifecycleTypeRegistry` trata Array/List/string y
structs que los contienen como valores que necesitan destroy; los escalares y
Vector del modelo actual son triviales.

### 7.6 Modelo, verifier, intérprete y printer

El verifier no tiene reglas “de rango”: verifica las instrucciones genéricas,
tipos homogéneos, terminadores, CFG y estados de lifecycle. `IRCompareOp`
admite orden para int o double, y `IRBinaryOp` ya conoce aritmética numérica;
por eso parte de la infraestructura futura existe, aunque el lowerer de rango
la bloquee.

El intérprete IR ejecuta el mismo CFG. La suma int usa aritmética i32 chequeada
y puede hacer panic. El printer sólo serializa bloques e instrucciones; no
reconstruye sintaxis Aether ni materializa Range.

## 8. SSA y optimizadores

La ruta predeterminada expande primero lifecycle y luego construye SSA con el
algoritmo general:

1. construye CFG desde branches/jumps;
2. calcula dominadores e immediate dominators;
3. calcula dominance frontiers;
4. coloca phis por storage con poda de liveness/initialized-in;
5. renombra por DFS del dominator tree;
6. verifica predecesores exactos, tipos y dominancia de cada incoming.

Una variable externa modificada dentro de un loop recibe un phi loop-carried
en el header si está viva. El storage de la variable iteradora de rango también
recibe phi entre preheader e incremento. El índice de colección sigue el mismo
modelo. Un `break` añade un predecesor al exit; cualquier phi allí debe tener un
incoming por cada predecesor real. Un `continue` añade la arista al header de
`while` o al bloque de incremento de `for`, por lo que el valor correcto llega
al siguiente ciclo.

El builder antiguo basado en patrones todavía existe como compatibilidad, pero
el pipeline usa `GeneralSSABuilder`; la auditoría y los tests caracterizan esta
ruta general.

Los pipelines IR y SSA incluyen constant folding, propagación, simplificación,
DCE y, en SSA, SCCP y eliminación de phis. Sus evaluadores distinguen int
chequeado de float/double y las comparaciones ya son genéricas. DCE consulta los
efectos: una suma int que puede hacer overflow no es eliminable como operación
puramente inocua.

No se encontró un supuesto exclusivo de rango int dentro de dominancia, phis,
DCE o SCCP. Los supuestos duros están antes, en lowering. Antes de habilitar
rangos flotantes deben auditarse de nuevo:

- folding/SCCP frente a NaN, infinito y signed zero;
- simplificaciones algebraicas que no sean válidas bajo IEEE-754;
- preservación de la evaluación única y del orden start/end/step;
- eliminación de branches de signo y cero sólo con constantes válidas;
- paridad exacta de redondeo entre Python, IR interpreter y LLVM.

## 9. LLVM/native

`IntType` baja estructuralmente a `i32`. Por eso tanto el valor del rango como
el índice interno de colección son hoy i32. No hay un “tipo índice de rango”
separado. Array/List/Vector son handles `ptr`; sus operaciones de length/get se
expresan mediante instrucciones SSA y helpers/runtime del contenedor.

Las comparaciones enteras usan `icmp slt/sle/sgt/sge`: son signed. Las futuras
comparaciones float/double ya tienen camino `fcmp` con predicados ordered
(`olt`, `ole`, `ogt`, `oge`), pero el rango no lo usa todavía.

El incremento entero llama al helper de aritmética chequeada, no a un `add`
LLVM silenciosamente wrapping. Esto preserva el contrato general i32, pero el
CFG siempre incrementa tras el cuerpo, incluso si el valor actual ya es el
extremo final. Así aparece el panic en `INT_MAX:INT_MAX` y su equivalente
descendente en el borde inferior.

| Caso native actual | Resultado |
| --- | --- |
| paso positivo/negativo constante | comparación inclusiva signed correcta; dirección incompatible vacía. |
| paso dinámico positivo/negativo | branch por signo y comparación correspondiente. |
| paso dinámico cero | rango vacío, sin panic. |
| paso constante cero | capability gate/lowering lo rechazan. |
| overflow del incremento | panic entero chequeado. |
| Array/List | índice i32 zero-based; elemento borrowed. |
| Vector | índice i32 one-based; elemento no propietario. |

El uso de i32 es doble: para Range proviene directamente de `Range<int>`, pero
para colecciones es también una decisión estructural actual del backend y de la
API pública de índices/length. `Range<double>` no obliga a cambiar el índice de
colección; sí obliga a separar claramente “ordinal interno de iteración” del
“valor numérico iterado”.

## 10. Tooling, ejemplos y documentación

### 10.1 Formatter

No existe un source formatter de Aether. `src/aether/formatting.py` formatea
valores en runtime, incluido `AetherRange`, pero no reescribe código. LSP no
publica `documentFormattingProvider`. Por tanto, rc.2 necesita un formatter
nuevo o una migración textual separada; no se puede delegar el cambio a una
infraestructura inexistente.

### 10.2 LSP

Los diagnostics del LSP llaman al lexer/parser/typechecker reales, así que el
cambio del parser se reflejará automáticamente. Completion, symbols y otras
features tienen lógica adicional y algunos componentes regex. El servidor no
ofrece formatting ni semantic tokens. Sus tests de initialize confirman sólo
completion, symbols, hover, definition y references.

La migración rc.2 debe actualizar completions/snippets en
`src/autocomplete_engine.py`, que hoy publican `for x in iterable`,
`while condition` e `if condition` sin paréntesis.

### 10.3 Herramientas oficiales

El IDE Qt y su editor web embebido fueron retirados después de esta auditoría.
La migración de completions y snippets corresponde ahora al servicio compartido
y a sus clientes oficiales de VS Code e IntelliJ; no existe una obligación de
paridad adicional para un editor de escritorio propio.

### 10.4 IntelliJ

El plugin usa un highlighter léxico propio con keywords y puntuación; no tiene
parser de control-flow ni formatter. El LSP embebido aporta diagnostics. Su
typing support ya empareja `()` y `{}`, pero no inserta paréntesis después de
keywords ni migra headers. Deben actualizarse snippets/documentación/tests del
plugin y verificar que el LSP incluido corresponda a rc.2.

### 10.5 Corpus y documentos

La spec v1 vigente documenta explícitamente las formas sin paréntesis. No se
modificó en esta auditoría. Ejemplos, tests, docs de diseño y autocomplete usan
ampliamente esa sintaxis; una búsqueda inicial encuentra decenas de archivos,
por lo que el cambio no debe hacerse como edición manual parcial.

El release de rc.2 debe migrar de forma atómica:

- ejemplos `.ae`;
- tests unitarios, corpus de paridad y strings fuente embebidos;
- spec normativa sólo en la tarea que implementa el cambio;
- native profile si muestra sintaxis;
- README, tutoriales, changelog y migration note;
- snippets/autocomplete de Studio, LSP/servicio y plugin;
- futura extensión VS Code, tomando LSP como fuente de diagnostics.

## 11. Tests de caracterización añadidos

El archivo nuevo cubre:

- paréntesis accidentales en `if`/`while` y rechazo en `for`;
- rechazo actual de `else if` y equivalente con nesting braced;
- diagnostics de headers mal formados;
- rangos inclusivos ascendentes/descendentes, pasos positivo/negativo y
  direcciones incompatibles;
- paso cero constante y dinámico en AST, IR y native;
- headers explícitos e inferidos y la matriz de rangos flotantes rechazada;
- Array, List, Vector, string, struct y class AST-only;
- diagnóstico de tipo iterador incompatible, sin conversión implícita;
- `break`, `continue`, mutación externa, scopes y retorno dentro del loop;
- cleanup IR antes de continue, break y return;
- paridad AST/IR/native en casos soportados;
- divergencia de overflow en el extremo i32.

Estos tests no corrigen las divergencias: las hacen visibles y deliberadas para
que la tarea de implementación posterior pueda cambiar expectativas con una
decisión de diseño explícita.

## 12. Divergencias y riesgos

| Prioridad | Hallazgo | Riesgo |
| --- | --- | --- |
| P0 rc.2 | `if`/`while` aceptan ambas formas y el AST no conserva paréntesis. | Sin parseo dedicado no puede emitirse el diagnóstico de migración requerido. |
| P0 rc.2 | `for (...)` no es aceptado hoy. | La migración no puede adelantarse antes del cambio de parser. |
| P0 Range | cero dinámico AST vs native. | Un mismo programa válido por TC observa error o rango vacío. |
| P0 Range | overflow posterior al último elemento en IR/native. | Rango singleton en el borde i32 diverge de AST. |
| P1 | `else if` no existe aunque el diseño rc.2 lo muestra. | Hace falta decidir nodo dedicado vs desugaring a `else_body=[If]`. |
| P1 | Range es valor AST pero sólo construcción directa de `for` en IR. | `r = 1:10; for i in r` no tiene camino native. |
| P1 | Matrix vector-like itera en AST pero no IR. | La matriz de soporte debe seguir separando backends. |
| P1 | múltiples listas de keywords/snippets no derivadas de tokens. | Drift de Studio/IntelliJ/docs durante la transición. |
| P2 | `RangeExpression` no tiene location propia. | Diagnostics de rango suelen caer en ubicación del statement o sin columna precisa. |
| P2 | no hay formatter de fuente. | Migración y estilo canónico requieren herramienta nueva o rewriter aislado. |

## 13. Plan exacto para paréntesis obligatorios en rc.2

### Fase 1 — parser y diagnostics

1. Introducir helpers dedicados, por ejemplo
   `_parenthesized_control_expression(keyword)` y `_for_header()`.
2. Después de `IF`/`WHILE`/`FOR`, exigir `LEFT_PAREN` antes de consumir la
   expresión o binding.
3. Consumir `RIGHT_PAREN` con mensajes específicos por constructo.
4. Reconocer deliberadamente la forma antigua antes de caer en `_expression`
   y emitir dos líneas conceptuales:

   ```text
   Expected '(' after 'if'.
   Control-flow conditions require parentheses in Aether 1.0.
   ```

   El error debe conservar line/column en el primer token posterior al keyword
   y usar `hint`/`kind` del sistema de diagnostics, no concatenar un error
   genérico de expresión.
5. Para `else if`, consumir `ELSE` y, si sigue `IF`, parsear recursivamente un
   `IfStatement` como único elemento de `else_body`. No hace falta nodo nuevo;
   esta representación ya coincide con el nesting existente y con lowering.
6. Añadir errores dedicados para `Expected ')' after if condition`, `while
   condition` y `for header`, incluidos paréntesis vacíos y desbalanceados.

### Fase 2 — formatter/migrador

No hay formatter actual. La opción de menor riesgo es un comando aislado de
migración token-aware que:

- inserte `(` inmediatamente tras el keyword y `)` antes del brace que termina
  el header;
- preserve comentarios y whitespace;
- transforme `else { if (...) { ... } }` sólo si se decide canonizarlo, no como
  requisito semántico;
- sea idempotente y tenga modo `--check`;
- no toque `if`/`for` dentro de strings o comentarios.

No se recomienda un reemplazo regex global: condiciones multilínea, llamadas,
rangos, comentarios y braces anidados lo vuelven inseguro. El rewriter es
pequeño y aislable, pero no se implementó en esta auditoría.

### Fase 3 — tooling y corpus

1. Actualizar autocomplete/snippets de Studio y cualquier snippet LSP.
2. Añadir formatting provider sólo si se decide crear un formatter real; el
   migrador no necesita fingir ser formatter.
3. Actualizar IntelliJ README/fixtures y verificar auto-pairs.
4. Preparar la futura extensión VS Code para consumir el mismo LSP rc.2.
5. Ejecutar el migrador sobre ejemplos, tests, parity corpus y docs activas.
6. Actualizar spec v1, native profile, changelog y una migration note con
   ejemplos antes/después.

### Fase 4 — release gates

- tests positivos sólo con sintaxis nueva;
- tests negativos que aseguren diagnostics dedicados para sintaxis antigua;
- tests LSP sobre message/range/hint;
- smoke de todos los ejemplos;
- corpus diferencial AST/native;
- búsqueda gate que impida headers antiguos fuera de fixtures negativas;
- CI completo, release-doc checker, IntelliJ tests y build de artefactos.

## 14. Alternativas para rangos numéricos generales

### A. `Range<int>` y `Range<double>` nominales separados

Ventaja: implementación directa y reglas explícitas por tipo. Desventajas:
duplica lógica, complica `float`, promociones y el futuro `Iterable<T>`, y no
encaja con el `RangeType(element_type)` que ya existe internamente.

### B. `Range<T>` genérico restringido a numéricos

Ventaja: una sola abstracción, element type visible al typechecker, inferencia
natural del iterador y futuro encaje con `Iterable<T>`. Requiere restricciones
genéricas internas aunque Aether todavía no exponga un sistema completo de
traits. Es la opción recomendada.

### C. Construcción especial sin tipo visible

Ventaja: mínimo diseño público inicial. Desventajas: el rango ya es un valor en
AST, typechecker y formatter; ocultar su tipo empeora diagnostics e impide
asignarlo, pasarlo o conectarlo después con iterables.

### D. Lowering directo sólo dentro de `for`

Es exactamente la estrategia native actual. Es eficiente y puede conservarse
como optimización, pero no debe ser el único modelo semántico: diverge cuando
el rango se guarda en una variable y dispersa las reglas entre frontend y CFG.

## 15. Diseño recomendado para `Range<T>`

### 15.1 Tipo e inferencia

Mantener `Range<T>` nominal genérico con una restricción interna
`T in {int, float, double}`. No es necesario exponer todavía sintaxis pública de
constraints ni una jerarquía numérica completa.

El tipo común de start, step y end se calcula con widening únicamente:

```text
int + int                         -> int
int/float sin double             -> float
cualquier combinación con double -> double
```

`int -> float`, `int -> double` y `float -> double` son promociones válidas.
No se admiten narrowing implícitos. Como los literales reales actuales son
`double`, `1:0.1:10` resulta `Range<double>`; un `Range<float>` requiere un
operando float explícito o contexto futuro bien definido.

La variable inferida recibe exactamente `T`. La variable explícita también
debe ser exactamente `T`; no se recomienda conversión en el header. Así se
preserva la regla actual y se evita que `for float x in Range<double>` esconda
pérdida por iteración. Una conversión deseada debe expresarse en los operandos
del rango.

### 15.2 Semántica

- extremo inclusivo, por compatibilidad;
- paso omitido `T(1)`;
- no inferir automáticamente un paso negativo;
- dirección incompatible produce rango vacío;
- paso cero constante: error de typecheck dedicado;
- paso cero dinámico: panic/runtime error idéntico en AST, IR y native;
- NaN en cualquier operando: runtime error antes de la primera iteración;
- infinito en cualquier operando: runtime error; restringir a valores finitos
  evita rangos no terminantes y simplifica paridad;
- rango vacío no evalúa el cuerpo, pero sí evalúa start/step/end una vez;
- overflow entero no debe ocurrir sólo por intentar avanzar después del último
  valor. Si el próximo valor necesario no cabe en int, panic consistente;
- signed zero float es cero para validar el paso.

### 15.3 Cálculo por índice

Para float/double se recomienda no usar suma acumulativa. En la iteración `k`,
calcular `candidate = start + T(k) * step` con operaciones del tipo T y comparar
ese candidate con el extremo. Esto limita drift acumulativo y hace la paridad
más controlable. No debe introducirse FMA en un backend si los otros hacen
multiply y add separados.

El ordinal `k` es interno y no cambia el sistema público de tipos; puede usar
una representación backend suficientemente amplia. Antes de ejecutar el
cuerpo debe comprobarse progreso representable: si `candidate` coincide con el
anterior pese a `step != 0`, terminar con un error dedicado para evitar loops
prácticamente infinitos por resolución flotante.

Para int puede usarse la misma abstracción ordinal, con cálculo chequeado, o un
avance que primero determine si ya se alcanzó/pasó el extremo y sólo sume si
habrá otra iteración. Cualquiera de las dos elimina el overflow espurio del
último elemento.

No se recomienda una tolerancia epsilon implícita para decidir inclusión: hace
el resultado dependiente de escala y sorprende al usuario. La inclusión se
decide comparando el candidate representable con end bajo IEEE ordered
comparison.

### 15.4 Materialización y protocolo futuro

Range debe seguir siendo perezoso y evaluar sus tres operandos una sola vez.
Semánticamente debe existir un pequeño `RangeValue<T> {start, step, end}` aunque
el compilador optimice un `for` directo a CFG sin materializarlo.

La primera etapa puede usar un protocolo interno equivalente a:

```text
iter_init(range) -> state
iter_next(state) -> (has_value, T)
```

Array/List/Vector pueden continuar con su lowering indexable especializado. En
una etapa posterior, `Range<T>` implementará el mismo contrato que
`Iterable<T>`/`Iterator<T>` sin obligar a exponer hoy interfaces públicas,
allocations de iterador ni dynamic dispatch.

### 15.5 Cambios necesarios por capa

1. Relajar `RangeType` a numeric element types y mejorar ubicación de
   `RangeExpression`.
2. Implementar common numeric type y promociones en typechecker.
3. Reemplazar `AetherRange` int-only por valor genérico con reglas finitas,
   cero y cálculo por índice.
4. Parametrizar `_lower_for_range` por IR numeric type y unificar cero/overflow.
5. Decidir representación IR de range values no directos; mantener direct
   lowering como optimización.
6. Añadir `float/double` al capability gate sólo cuando el camino completo sea
   válido; no relajar el gate anticipadamente.
7. Verificar SSA optimizations con corpus IEEE y paridad O0/O1/O2.
8. Añadir tests de NaN, infinito, signed zero, resolución, extremos, overflow,
   promoción y rango guardado en variable.

El backend ya soporta operaciones y comparaciones double genéricas, de modo que
no hay un bloqueo fundamental en LLVM. El bloqueo arquitectónico es la
duplicación de semántica de rango y el lowering especial int-only, no la falta
de `double` en el IR escalar.

## 16. Trabajo futuro priorizado

### P0 — implementación rc.2

- parser con paréntesis obligatorios y `else if` deliberado;
- diagnostics específicos e invariantes LSP;
- migración atómica de corpus, ejemplos, snippets y docs normativas;
- tests negativos de sintaxis antigua y release gate de búsqueda;
- resolver y unificar paso cero y overflow de rango antes de ampliar tipos.

### P1 — `Range<double>`

- aprobar las reglas de la sección 15;
- hacer genérico el modelo AST/typechecker/runtime;
- parametrizar lowering y añadir range value IR o normalización equivalente;
- corpus diferencial AST/IR/native para float/double y optimizaciones;
- documentar explícitamente finitud, NaN, precisión y errores.

### P2 — iteración general

- cerrar Matrix vector-like native o excluirla explícitamente;
- permitir ranges almacenados y pasados sin depender de AST shape;
- definir el protocolo interno Iterable/Iterator reutilizable;
- derivar metadata de tooling desde tokens/gramática para reducir drift.

### P3 — herramientas

- source formatter canónico;
- migrador reutilizable e idempotente;
- semantic tokens y formatting LSP;
- integración equivalente en IntelliJ y futura extensión VS Code.

## 17. Conclusión

El control-flow básico y la iteración de colecciones tienen una base sólida y
un lifecycle native explícito. La transición de sintaxis es localizada en el
parser pero amplia en corpus/tooling. `Range<double>` es viable sobre el IR
numérico existente, aunque no debe implementarse como una simple relajación del
typechecker: primero hay que unificar cero, overflow, finitud, precisión y la
representación semántica de Range entre AST y native.

## 18. Validación final

Validación ejecutada sobre el worktree de esta auditoría:

| Comando/gate | Resultado |
| --- | --- |
| `PYTHONPATH=src .venv/bin/pytest` | **3088 passed, 1 skipped**, 3089 tests recolectados, 148.14 s. |
| Suite focalizada de control-flow/lifecycle/backend | **92 passed**, 1.80 s. |
| `scripts/check_release_docs.py` | **PASS**. |
| `scripts/ci.py --skip-tests` | **PASS**, 16.16 s: whitespace, documentación, compileall, benchmarks, LLVM, paridad diferencial y native. |
| `git diff --check` | **PASS**. |

El skip preexistente pertenece al smoke experimental del ejemplo Newton; no
está relacionado con control-flow ni con los cambios documentales de esta
auditoría.
