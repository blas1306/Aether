# Auditoría de paridad de features por backend (ubicación histórica)

La auditoría canónica, actualizada el 14 de julio de 2026 y desglosada por
lexer/parser, AST, typechecker, intérpretes, IR, SSA, optimizadores,
LLVM/native, runtime, tests y documentación, está en:

[`docs/aether/BACKEND_FEATURE_PARITY.md`](../aether/BACKEND_FEATURE_PARITY.md).

El contenido que sigue se conserva temporalmente como registro histórico de la
auditoría del 13 de julio. No debe usarse para decidir el estado actual: no
incluye correctamente los commits posteriores de short-circuit, resolución
multifase y backend de structs.

---

Última revisión: 2026-07-13.

## Alcance, criterio y resultado corto

Este documento registra el comportamiento actual; no es un roadmap ni una
declaración de intención. Se inspeccionaron lexer/parser, typechecker,
intérprete AST, lowering/verifier/intérprete IR, construcción/verificación y
optimización SSA, printer/runtime LLVM, CLI, REPL, servicio de lenguaje y el
plugin IntelliJ. Las afirmaciones ambiguas se contrastaron con los sondeos de
`tests/aether/test_backend_feature_parity.py`.

Una clase, opcode o tipo aislado no cuenta como soporte. `Implemented` requiere
que el camino indicado sea ejecutable y tenga evidencia. `Partial` identifica
el subconjunto. `AST-only` significa que parser, typechecker e intérprete AST
lo soportan, pero no baja al compilador. `Broken` indica una diferencia
semántica o de seguridad reproducible. `Parsed but rejected` es sintaxis que
el parser reconoce para producir un diagnóstico deliberado. `Unknown` se usa
cuando no hay evidencia suficiente.

La ruta nativa real es:

```text
lexer -> parser -> typechecker -> entry-point normalization -> IR lowering -> IR verifier
      -> GeneralSSABuilder -> SSA verifier -> SSA optimizer
      -> LLVM printer/runtime -> clang -> proceso nativo
```

El intérprete AST y el intérprete IR son backends alternativos. No existe un
intérprete SSA. El CLI usa LLVM por defecto; el REPL y la ejecución desde
IntelliJ usan AST.

Referencias centrales:

- nodos y sintaxis: `src/aether/ast.py:11`, `src/aether/parser.py:47`;
- reglas de tipos: `src/aether/typechecker.py:515`;
- ejecución de superficie: `src/aether/interpreter.py:274`;
- lowering: `src/aether/ir/lowering.py:180`;
- IR: `src/aether/ir/model.py:9`, `src/aether/ir/verifier.py:58`,
  `src/aether/ir/interpreter.py:79`;
- SSA: `src/aether/ssa/general_builder.py:37`,
  `src/aether/ssa/verifier.py:64`;
- LLVM: `src/aether/backend/llvm/printer.py:86` y los módulos `*_runtime.py`;
- selección de backend: `src/aether/cli.py:37`, `src/aether/cli.py:429`;
- REPL persistente: `src/aether/session.py:45`;
- IntelliJ/LSP: `tools/intellij-aether/src/main/resources/META-INF/plugin.xml:9`,
  `src/aether_lsp/server.py:91`.

## Estado de las etapas

| Etapa | Estado | Evidencia y límite principal |
| --- | --- | --- |
| Lexer | Implemented | Tokens, comentarios, literales, interpolación y recuperación inicial; `lexer.py`, tests de sintaxis. |
| Parser | Implemented | Superficie AST amplia; algunas formas se reconocen para rechazarlas. `parser.py:47-1395`. |
| Type checker | Implemented | Resolución multifase de tipos/miembros/firmas antes de cuerpos, scopes secuenciales para locales, módulos, UDT y recolección de múltiples diagnósticos. |
| AST interpreter | Implemented | Backend de superficie más completo; ejecuta el entry point normalizado y conserva sesiones persistentes. |
| IR lowering | Partial | Solo acepta programas formados por funciones top-level y un subconjunto de expresiones/tipos. |
| IR verifier | Implemented para el modelo IR | Valida CFG, definiciones y tipos de todos los opcodes actuales; no prueba equivalencia con la semántica AST. |
| IR interpreter | Partial | Ejecuta todos los opcodes IR actuales; Vector/Matrix ya coinciden con AST, pero persisten diferencias generales de representación/overflow numérico. |
| SSA builder | Implemented para IR verificable | `general` es el default; `pattern` queda como fallback limitado. |
| SSA verifier | Partial | Amplia validación por opcode; no cierra dominancia de todos los usos ni exige exactamente un incoming por predecessor para cada phi. Véase `CONTROL_FLOW_AUDIT.md`. |
| SSA optimizers | Partial | El modelo común de efectos conserva operaciones `may_trap`; DCE, SCCP, folding y simplificación mantienen los panics de Vector/Matrix. |
| LLVM printer | Partial | Cubre escalares seleccionados, control, Array/List y álgebra lineal contigua; no UDT, módulos, nullable, excepciones ni runtime string completo. |
| LLVM runtime | Partial | IO y safety de Array/List/Vector/Matrix; sin ownership/free/GC ni runtime string completo. |
| CLI | Implemented | LLVM default; selección `llvm|ast|ir`; inspección tokens/AST/IR/CFG/SSA/LLVM; build y bench. |
| IntelliJ | Partial | Highlighting, LSP, run config y typing helpers; sin formatter ni PSI semántico propio. |
| REPL | Implemented, AST-only | Estado persistente y rollback transaccional; solo acepta `--backend=ast`. |

## Matriz principal

Las celdas `IR` agrupan lowering, verifier e intérprete; `SSA` agrupa builder,
verifier y optimizadores. `Native` exige ejecución mediante clang, no solo
texto LLVM. `Tooling` se refiere al servicio de lenguaje/IntelliJ, no a que el
plugin ejecute ese backend.

### Lenguaje base y funciones

| Feature | Parser | Type checker | AST | IR | SSA | LLVM | Native | Tooling | Tests | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Variable local tipada con inicializador | Implemented | Implemented | Implemented | Implemented para tipos backend | Implemented | Implemented | Implemented | Símbolos/completion | AST+IR+native | Implemented |
| Declaración sin inicializador | Requiere `=` (`parser.py:666`) | N/A | N/A | N/A | N/A | N/A | N/A | No | sintaxis negativa indirecta | Not implemented |
| Inferencia local `x = expr` | Implemented | Implemented | Implemented | Assignment a nombre no local se rechaza | No | No | No | Símbolos heurísticos | frontend | AST-only |
| Assignment local | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented | Diagnósticos | E2E | Implemented |
| Assignment compuesto `+=` | Desazucarado a `+` (`parser.py:639`) | Implemented | Implemented | Según soporte de `+` | Según IR | Según LLVM | Según LLVM | Highlight | frontend/backend escalar | Partial |
| `const` local | Implemented | Reasignación rechazada | Implemented | Se borra tras typecheck | Igual que variable | Igual que variable | Igual que variable | Completion parcial | frontend+local IR | Partial |
| Alias de tipo | Implemented | Implemented, transitivo/ciclos | Implemented | Decl. top-level rechazada | No | No | No | Símbolos parciales | frontend/imports | AST-only |
| Aritmética `+ - * / %` | Implemented | Implemented | Tipos reales/complex/agregados | int/double y agregados seleccionados | Igual; folds escalares | int/double, `%` solo int | Igual | Highlight | amplia, no matriz total E2E | Partial |
| Comparaciones | Implemented | Implemented | escalares, null, agregados, structs/enums | int/double/bool/string seleccionados | Igual | int/double; string compare falla | Igual | Diagnósticos | escalar E2E | Partial |
| `&&` / `||` short-circuit | Implemented | boolean | Implemented con short-circuit (`interpreter.py:1642`) | Rechazado | No | No | No | Highlight/completion | AST | AST-only |
| Unario `-` | Implemented | Implemented | Implemented | int/double; se baja como `0-x` | Implemented | int/double | Implemented | Highlight | E2E parcial | Partial |
| Negación prefija `!boolean` | Implemented | boolean exacto | Implemented | `IRUnaryOp not`, puro | `SSAUnaryOp not`; folding, propagación, SCCP y DCE | `xor i1 ..., true` | Implemented | Highlight | frontend+IR+SSA+LLVM+CLI | Implemented |
| Factorial `factorial(...)` | Llamada normal | Implemented | Builtin Math | Rechazado como builtin | No | No | No | Completion | AST | AST-only |
| Cast explícito | Implemented como llamada de tipo | Amplio en frontend | int/float/double/complex/string/boolean con límites | solo int↔double efectivo | solo int↔double verificado | solo i32↔double | Implemented para ese par | Completion | frontend + par nativo | Partial |
| Conversión implícita | Implemented | widening de frontend | Implemented | muchos casos target-typed se rechazan | No adicional | solo casts ya emitidos | subconjunto | Diagnósticos | frontend; huecos backend | Partial |
| `if` / `else` | Implemented | bool | Implemented | CFG explícito | phi/CFG | Implemented | Implemented | Highlight/symbols | E2E | Implemented |
| `while` | Implemented | bool | Implemented | CFG explícito | loop phis | Implemented | Implemented | Highlight | E2E + sondeo | Implemented |
| `for` sobre rango | Implemented | int range | Implemented | pasos positivos/negativos/dinámicos | Implemented | Implemented | Implemented | Highlight | E2E | Implemented |
| `for` sobre colección | Implemented | Implemented | varias colecciones | Array/List/Vector | Implemented | Implemented para ese subconjunto | Implemented | Highlight | List/Vector; Array parcial | Partial |
| `break` / `continue` | Implemented | Solo en loop | Implemented | Saltos a targets activos | SSAJump | Implemented | Implemented | Highlight | nested E2E | Implemented |
| `return` | Implemented | Todos los caminos | Implemented | Implemented; unreachable posterior falla | Implemented | Implemented | Implemented | Diagnósticos | E2E | Implemented |
| Función `void` | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented | Símbolos/hover | E2E | Implemented |
| Función con retorno | Implemented | Implemented | Implemented | tipos backend | Implemented | tipos backend | tipos backend | Símbolos/hover | E2E | Partial |
| Llamada como expresión | Implemented | No acepta `void` | Implemented | Implemented para callee conocido | Implemented | Implemented | Implemented | Completion/hover | E2E | Implemented |
| Llamada como statement | Implemented | Implemented | Implemented | Solo `CallExpression`; expresión pura rechazada | Calls conservadas | Implemented | Implemented | Símbolos | E2E | Implemented |
| Argumentos posicionales | Implemented | Aridad/tipos exactos | Implemented | Implemented sin defaults | Implemented | Implemented | Implemented | Signature hover parcial | E2E | Implemented |
| Argumentos nombrados | Sintaxis implementada | Solo builtins que los declaran; user funcs rechazan | Plots/builtins seleccionados | Rechazado (`lowering.py:1187`) | No | No | No | Parser/LSP | Plots AST | AST-only |
| Parámetros por defecto | Sin nodo/campo de default | No | No | No | No | No | No | No | No | Not implemented |
| Recursión directa y mutua | Implemented | Firmas globales recolectadas antes de los bodies | Implemented | Implemented | Implemented | llamadas a símbolos emitidos en cualquier orden | Implemented | completion/hover/definition | `test_declaration_order.py` AST+IR+LLVM | Implemented |
| Overloads | Sintaxis repetible | Nombre duplicado rechazado (`typechecker.py:1319`) | No | No | No | No | No | No resolución overload | tests negativos UDT | Not implemented |
| Funciones anidadas | Parser las acepta en bloques | Se registran globalmente | Ejecutan; scope no es closure léxico | `FunctionDeclaration` en body rechazada | No | No | No | Símbolos incompletos | sondeo AST/IR | AST-only |

### Tipos primitivos e IO

| Feature | Parser | Type checker | AST | IR | SSA | LLVM | Native | Tooling | Tests | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `int` | Implemented | Implemented | Python int sin límite i32 | IntType | Implemented | i32 | wrap i32 | Completion/highlight | E2E | Partial — overflow difiere |
| `long` | No token/tipo | No | No | No | No | No | No | No | No | Not implemented |
| `float` | Tipo, literal decimal nace `double` | Implemented | Implemented por coerción | FloatType existe, literal/coerciones no integradas | Modelo parcial | Sin mapping LLVM | No | Completion | frontend | AST-only |
| `double` | Implemented | Implemented | Implemented | Implemented | Implemented | double | Implemented | Completion | E2E | Implemented |
| `boolean` | Implemented | Implemented | Implemented | BoolType | Implemented | i1 | Implemented | Completion | E2E | Implemented |
| `char` | No | No | No | No | No | No | No | strings single-quote se resaltan | No | Not implemented |
| `string` valores/literales | Implemented + interpolación | Implemented | runtime completo de superficie | literal/call/return/print | valor/phi | `ptr` a global; sin ownership | literales/print funcionan | Completion/hover | parcial E2E | Partial |
| `string` operaciones/interpolación | Implemented | Implemented | concat, equality, interpolation | concat/equality modeladas parcialmente | pasan SSA | printer rechaza binary/compare string | No | Diagnósticos | AST + rechazos CLI | AST-only |
| `complex` | literal `im` y tipo | Implemented | aritmética/builtins | tipos/opcodes nominales, literal rechazado | verifier conoce tipo | Sin mapping | No | Completion parcial | AST | AST-only |
| `void` | Solo retorno/firma | Implemented | Implemented | VoidType | Implemented | void | Implemented | Símbolos | E2E | Implemented |
| `null` / `T?` | Implemented | Implemented sin narrowing | Implemented | tipos nominales existen pero literal/lowering no | No camino fuente | Sin mapping | No | Diagnósticos | frontend | AST-only |
| `print` / `println` escalares | Implemented | variádico builtin | Todos los tipos formateables | int/bool/string/double | SSAPrint no eliminable | `printf` (`io_runtime.py:18`) | Implemented | Completion | sondeo+backend print | Implemented |
| Print de agregados/UDT | Implemented | Implemented | List/Array/Vector/Matrix/struct/etc. | Vector/Matrix con shape/orientación; otros agregados rechazados | preservado como efecto | helpers tipados | Vector/Matrix implementados | Completion | paridad E2E Vector/Matrix | Partial |
| Formato de números | N/A | N/A | `format_value` de Aether | Python `str` en intérprete IR | N/A | `%d` / `%.17g` | libc | N/A | casos simples | Partial — no contrato común total |
| `input` | Nodo dedicado | Contexto tipado requerido | int/float/string/bool/Vector/Matrix | Rechazado | No | No | No | Completion | AST | AST-only |

### Colecciones y álgebra lineal

| Feature | Parser | Type checker | AST | IR | SSA | LLVM | Native | Tooling | Tests | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Array<T>` literal | target-typed `{}` | Implemented | Implemented | IRArrayNew | SSAArrayNew | header+buffer checked | Implemented | members | E2E | Implemented |
| Array get/set | Implemented | tipos/const | bounds checked | bounds checked | conservados como may-trap/effect | bounds helper antes de acceso | panic controlado | Diagnostics | P0 AST+IR+native | Implemented |
| Array `.length` | Implemented | int | Implemented | checked i64→int | preservado may-trap | checked helper | panic overflow | Completion | P0 | Implemented |
| Array slicing `a[start:end]` | Implemented | solo Array/int | inclusive, copia nueva | IRArraySlice bounds | preservado | runtime checked | Implemented | sintaxis | AST+IR+native | Implemented |
| Array `sort` | método/global | int/double/string | estable in-place | IRSequenceSort | efecto conservado | helpers checked | Implemented | Completion | E2E | Implemented |
| Array `copy` | método/global | Implemented | shallow outer copy | Sin opcode; rechazado | No | No | No | Completion | AST | AST-only |
| Array igualdad | Implemented | estructural | Implemented | aggregate compare rechazado | No | No | No | Diagnósticos | AST | AST-only |
| Arrays anidados | Implemented hasta profundidad 2 | Implemented | Implemented | tipos recursivos posibles, sin E2E confiable | posible | punteros posibles | No prueba representativa | Completion genérica | frontend solamente | Unknown |
| `List<T>` literal/new | `{}`; no keyword `new` | target-typed | Implemented | IRListNew | SSAListNew | `{length,capacity,data}` | Implemented | members | E2E | Implemented |
| List get/set/length/is_empty | Implemented | tipos/const | bounds checked | opcodes dedicados | may-trap/effect preservados | helpers bounds/narrowing | panic controlado | Completion | E2E safety | Implemented |
| List slicing | `SliceExpression` | Implemented con límites | Implemented, varias formas limitadas | Solo ArraySlice; List rechazada | No | No | No | sintaxis | AST | AST-only |
| List `push` | método/global | Implemented | Implemented | IRListPush | efecto | growth checked | Implemented | Completion | E2E | Implemented |
| List `pop` | método/global | Implemented | Implemented | IRListPop | may-trap/effect | empty panic | Implemented | Completion | E2E | Implemented |
| List `insert` | método/global | Implemented | Implemented | IRListInsert | efecto/may-trap | bounds/growth checked | Implemented | Completion | E2E | Implemented |
| List `removeAt` | método + global `remove_at` | Implemented | Implemented | IRListRemoveAt | efecto/may-trap | checked | Implemented | Completion | E2E | Implemented |
| List `clear` | método/global | Implemented | Implemented | IRListClear | efecto | Implemented | Implemented | Completion | E2E | Implemented |
| List `contains` / `indexOf` | métodos + global snake_case | Implemented | value/reference policy | opcodes dedicados | contains puro; index may-trap narrowing | helpers | Implemented | Completion | E2E | Implemented |
| List `reverse` | método/global | Implemented | in-place | IRListReverse | efecto | Implemented | Implemented | Completion | E2E | Implemented |
| List `sort` | método/global | int/double/string | estable in-place | IRSequenceSort | efecto | checked temp/offsets | Implemented | Completion | E2E | Implemented |
| List `copy` | método/global | Implemented | shallow outer copy | IRListCopy | allocation conservada | checked allocation/memcpy | Implemented | Completion | E2E | Implemented |
| List igualdad | Implemented | estructural/ref recursiva | Implemented | aggregate compare rechazado | No | No | No | Diagnósticos | AST | AST-only |
| Vector literal/get/set/length | Implemented | orientación/shape | índices públicos 1-based | opcodes dedicados; checks y panic propios | DCE preserva get/set | `vector_runtime.py` valida y convierte offset | panic controlado | members | AST+IR+native, límites y writes | Implemented |
| Matrix literal/get/set/rows/columns | Implemented | shape | índices públicos 1-based | valida fila y columna antes del offset | DCE preserva get/set | `matrix_runtime.py` valida coordenadas | panic controlado | members | esquinas, límites y regresión offset plano | Implemented |
| Vector/Matrix aritmética básica | operadores +,-,* | shape/tipo | amplia | dimensiones estáticas/subconjunto int/double | preserva/optimiza usos | loops y allocations | happy paths | Completion | amplia E2E | Partial |
| Builtins de álgebra lineal | llamadas/namespaces | Amplio | transpose, solve, factorizaciones, eig/SVD, etc. | la mayoría sin lowering | No | No | No | Completion/hover importado | AST exhaustivo | AST-only |
| Vector/Matrix igualdad | Implemented | estructural | Implemented | compare estructural con shape | metadata preservada, no folding escalar | helpers tipados | Implemented | Diagnósticos | AST+IR+native | Implemented |
| Tuples y destructuring | literal/tipo/assignment | Implemented | retorno/destructuring | Sin tipos/opcodes de tuple en lowering | No | No | No | símbolos parciales | AST | AST-only |
| Maps/dictionaries | No | No | No | No | No | No | No | No | No | Not implemented |

### Tipos definidos por usuario y módulos

| Feature | Parser | Type checker | AST | IR | SSA | LLVM | Native | Tooling | Tests | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Struct fields/constructors | Implemented | nominal, aridad/tipos | Implemented | `IRStructDefinition/New/Get/Set`; constructor posicional y explícito | opcodes agregados puros | `%struct.Name = type { ... }`, orden fuente canónico | Implemented para tipos de campo ya soportados por backend | symbols/completion | paridad AST/IR/native dedicada | Implemented (core) |
| Struct methods/`this` | Implemented | mutabilidad inferida | Implemented | funciones `Name.method` con receptor/resultado explícitos | `MethodResultType` sin alias oculto | retorno agregado `{receiver, value}` | Implícito/explícito, llamadas mutadoras encadenadas | completion/symbols | métodos lectores/mutadores + constructor | Implemented (core) |
| Struct mutability/value semantics | Implemented | const root | copia por valor; agregados internos conservan refs | `struct_set` reconstruye el agregado | stores promovidos y phis de agregados | parámetros/retornos LLVM por valor | copia local/parámetro/retorno independiente | diagnostics | copia, parámetro, retorno y nesting | Implemented |
| Struct igualdad | Implemented | solo campos comparables | estructural recursiva | comparación nominal estructural | preservada por optimizadores | campo a campo; strings por contenido; Array/List escalares dinámicos | int/double/bool/string, nested Struct y Array/List escalares | diagnostics | igualdad nested/string/bool y List<int> | Partial: Enum/nullable y Vector/Matrix dentro de Struct esperan backend propio |
| Struct impresión | Implemented | N/A | `Name(field=value, ...)` | `IRPrint` acepta Struct | preservada por DCE | emisión recursiva del formato público | escalares, nested Struct y Array/List escalares | N/A | formato exacto AST/IR/native | Partial: Vector/Matrix como campos requieren shape runtime |
| Class fields/methods/constructors | Implemented | nominal/visibility | Implemented | declaración rechazada | No | No | No | symbols/completion | extensa AST | AST-only |
| Class reference semantics | Implemented | Implemented | alias por assignment/arg/return | No | No | No | No | N/A | dedicada | AST-only |
| Class `this` / visibility | Implemented | public/private | Implemented | No | No | No | No | completion filtra privados | tests | AST-only |
| Interfaces y dispatch | Implemented | conformidad nominal | dispatch struct/class | No | No | No | No | completion/symbols | tests | AST-only |
| Enums | variantes sin payload | nominal/equality | Implemented | declaración rechazada | No | No | No | variants completion | tests | AST-only |
| Enum payloads | Sin sintaxis | No | No | No | No | No | No | No | No | Not implemented |
| Genéricos de usuario | Formas genéricas se rechazan | No | No | No | No | No | No | No | interfaz negativa | Parsed but rejected |
| Nominal typing UDT | Implemented | Implemented | Implemented | clases IR nominales existen sin integración | No camino fuente | No | No | símbolos | AST | AST-only |
| Imports de archivo/módulo | `import A.B [as C]` | identidad canónica, bindings, ciclos/colisiones | namespace explícito, sin wildcard implícito | import statement rechazada honestamente | No | No | No | LSP/symbols/highlight parcial | suite dedicada AST | AST-only |
| Imports selectivos/alias/wildcard | `from A.B import x [as y]`; wildcard/listas rechazados | exports públicos y submódulos | binding directo conserva origen | rechazado como imports | No | No | No | completion/hover/symbols parcial | suite dedicada AST | AST-only |
| `package` / namespace | Implemented, uno por archivo | visibilidad de exports | Implemented | programa deja de ser solo funciones | No | No | No | symbols/hover | imports AST | AST-only |
| Resolución entre archivos | N/A | `source_root` + `.ae` | Implemented | No linker/lowering módulos | No | No | No | LSP recibe root | tests | AST-only |
| Visibilidad top-level | public/private | Implemented | Implemented | no módulos | No | No | No | completion parcial | tests | AST-only |
| Inicialización de módulo | Statements al importar | Typechecked | se ejecutan una vez por sesión | No | No | No | No | N/A | imports | AST-only |
| Statements top-level del módulo de entrada | Implemented | Implemented | `main` sintético normalizado | función `main` ordinaria tras normalización | Implemented | `@main` | exit del proceso | IntelliJ ejecuta AST | `test_entry_point.py` | Implemented para el módulo de entrada |
| `main` | `int main()` | retorno int, cero parámetros, único | se invoca; return 0 implícito | entry ordinario normalizado | compilado | `@main` | entry del proceso | CLI LLVM/AST/IR; IntelliJ AST | `test_entry_point.py` | Implemented |

### Errores, runtime y herramientas

| Feature | Parser | Type checker | AST | IR | SSA | LLVM | Native | Tooling | Tests | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Error de sintaxis | ubicación + recovery | N/A | no ejecuta | no alcanza | no alcanza | no alcanza | exit CLI 1 | LSP multi-diagnostic | tests | Implemented |
| Error de tipos | N/A | ubicación/hint/kind | no ejecuta | no alcanza | no alcanza | no alcanza | exit CLI 1 | LSP diagnostics | tests | Implemented |
| Bounds Array/List | N/A | índice int | checked | checked | DCE preserva | checked | panic + code 1 | diagnostics de tipo | safety E2E | Implemented |
| Bounds Vector/Matrix | N/A | índice int | checked, ambos 1-based | mismos checks; Matrix por coordenada | DCE preserva gets `may_trap` | helpers específicos antes del acceso | panic + code 1 | diagnostics de tipo | E2E reads/writes y regresiones | Implemented |
| División/módulo por cero | N/A | permitido runtime | AetherRuntimeError | IRExecutionError; folders no pliegan | SCCP conserva unknown | `fdiv` produce inf; no panic común | diverge | diagnostics solo estáticos | parcial | Broken |
| Overflow entero | N/A | sin regla | Python int no acotado | Python int no acotado | constantes Python | i32 wrap/LLVM flags ausentes | wrap | No | sin paridad E2E | Broken |
| Allocation overflow/OOM Array/List | N/A | N/A | host Python | checks lógicos seleccionados | instrucciones preservadas | helpers checked | panic | N/A | safety | Implemented |
| `throw` / `try-catch` | Implemented | string/Exception | Implemented | statements rechazados | No | No | No | keywords/diagnostics | AST | AST-only |
| Null dereference | nullable existe | no smart narrowing | operaciones restringidas | no nullable | No | No | No | diagnostics | frontend | AST-only |
| Exit codes | N/A | N/A | retorna el valor de `main` | retorna el valor de `main` | N/A | proceso retorna `main` | 0-255 POSIX | bridge AST recibe 0 normal/1 panic | AST+IR+CLI+native | Implemented para entry point |
| CLI backend predeterminado | N/A | N/A | explícito `--backend=ast` | explícito `ir` | export SSA | default `llvm` | default file run | N/A | CLI | Implemented |
| Selección explícita backend | N/A | N/A | `ast` | `ir` | no ejecución SSA | `llvm` | build/run | IntelliJ sin selector | CLI | Partial |
| REPL | Parser por línea | checker persistente | session + rollback | no | no | no | no | Studio/CLI | tests | AST-only |
| Formatter | N/A | N/A | solo formato de valores | N/A | N/A | N/A | N/A | no formatter/reformat | No | Not implemented |
| Syntax highlighting | N/A | N/A | N/A | N/A | N/A | N/A | N/A | lexer IntelliJ básico | Kotlin tests | Partial |
| Completions | N/A | TypeChecker no alimenta todas | N/A | N/A | N/A | N/A | N/A | keywords/builtins/símbolos y members, parte regex | Python/LSP | Partial |
| Symbols/outline/hover | N/A | N/A | N/A | N/A | N/A | N/A | N/A | LSP documentSymbol + hover; PSI es archivo plano | tests parciales | Partial |
| Diagnostics IntelliJ | Parser recovery | collector typechecker | no runtime live | no diagnósticos backend | no | no | no | LSP debounce/publicación | LSP tests | Implemented para frontend |
| Ejecutar desde IntelliJ | N/A | N/A | `aether_lsp.run_file` llama `run_source` AST | no | no | no | no | action/run config | Kotlin+bridge tests | AST-only |

## Programas de sondeo y resultados

Los programas viven como strings pequeños en
`tests/aether/test_backend_feature_parity.py` y
`tests/aether/test_entry_point.py`. Todos los backends consumen el mismo AST
normalizado y el mismo `main`, explícito o sintético.

| Sondeo | AST | IR interpreter | LLVM/native | Resultado |
| --- | --- | --- | --- | --- |
| Programa base con `main` | `ok\n`, return 0 | `ok\n`, return 0 | `ok\n`, exit 0 | paridad de entry |
| `while` 0..2 | `0\n1\n2\n` como script | mismo output | mismo output | paridad del core al adaptar entry |
| recursión factorial(5) | `120\n` | `120\n` | `120\n` | cobertura E2E antes ausente |
| Array set + slice | `9\n1\n` | mismo output | mismo output | Array core completo |
| List mutations + sort | `1\ntrue\n3\n` | mismo output | mismo output | List core completo |
| Struct y class mínimos | ejecutan | lowering rechaza | no alcanza | AST-only confirmado |
| nested function | ejecuta `2\n` | lowering rechaza `FunctionDeclaration` | no alcanza | AST-only y diagnóstico crudo |
| Vector get muerto fuera de rango | sin lectura top-level observable | IR optimizado conserva el get y trapea | SSA conserva el get; native hace panic controlado | paridad de efectos y safety |
| Matrix `[0,2]` sobre 2x2 | panic Matrix | mismo panic antes del offset | mismo panic, exit 1 | regresión cerrada |

## Modelo central de efectos de instrucciones

### Representación de `struct` en backend

Cada declaración fuente produce una sola `IRStructDefinition` nominal. Los
campos se conservan en orden fuente y LLVM emite exactamente un tipo identificado
`%struct.Name = type { ... }`; el layout no es `packed`, por lo que solo aplica
el padding natural decidido por LLVM. Construcción, lectura y actualización son
`struct_new`, `struct_get` y `struct_set`. La última es una operación funcional:
produce un agregado nuevo y nunca una referencia al almacenamiento anterior.

Asignaciones, argumentos y retornos transportan el agregado por valor. Un método
se baja a `Name.method(receiver, ...)` y retorna el par interno
`method_result<receiver, value>`. De ese par se extrae el receptor actualizado y,
si corresponde, el resultado público. En LLVM el ABI interno equivalente es
`{ %struct.Name, T }` (o `{ %struct.Name }` para `void`). Esta representación
mantiene visible la mutación en SSA, permite que los stores se promuevan a phis y
evita aliasing oculto. Los campos que ya son reference types (Array/List/etc.)
conservan la política shallow existente del AST.

Constant Folding, propagación local/global, SCCP, simplificación algebraica y
DCE tratan las operaciones de agregado como productores puros y conservan sus
dependencias. Las definiciones canónicas de layout se preservan al reconstruir
módulos optimizados.

Todas las instrucciones IR y SSA exponen `has_side_effects`, `may_trap`,
`reads_memory`, `writes_memory`, `allocates` y la propiedad derivada
`must_preserve`. Los descriptores y mixins viven en
`src/aether/instruction_effects.py`, por lo que instrucciones equivalentes de
IR y SSA comparten una sola definición semántica. DCE ya no mantiene tuplas de
tipos supuestamente puros: cualquier productor con resultado muerto se elimina
solo cuando `must_preserve` es falso.

La clasificación incluye IO y terminadores; calls conservadoras; stores y
mutaciones; accesos checked de Array/List/Vector/Matrix; conversiones y
aritmética checked; y todas las instrucciones que reservan almacenamiento.
Una lectura segura (`ListContains`, por ejemplo) declara `reads_memory` pero
puede eliminarse si su resultado está muerto. Los folders, propagación global y
SCCP conservan operaciones constantes inválidas en vez de convertir un panic en
una constante.

La regresión de `IRVectorGet`/`SSAVectorGet` y
`IRMatrixGet`/`SSAMatrixGet` muertos está corregida estructuralmente: son
lecturas `may_trap` y sobreviven DCE. AST, IR y LLVM reciben índices públicos
1-based. Vector valida `1 <= index <= length`; Matrix valida fila y columna por
separado y solo entonces calcula el offset 0-based interno. Los helpers
`aether_vector_check_index` y `aether_matrix_check_index` emiten panics propios,
sin reutilizar Array. Calls siguen clasificándose conservadoramente hasta que
exista análisis fiable de pureza/efectos interprocedural.

## Diferencias semánticas confirmadas

- Entry point: cerrado en P3. `EntryPointNormalizer`, ejecutado después del
  typechecker, envuelve el modo script en un `main` marcado `synthetic` y añade
  `return 0` solo si el flujo puede alcanzar el final. AST, IR y native propagan
  el mismo valor de retorno. El soporte nativo sigue limitado al módulo de
  entrada: imports e inicializadores de módulos continúan AST-only.
- Vector/Matrix: la especificación, AST, IR, SSA, ejemplos y LLVM usan índices
  públicos 1-based. Los offsets de storage siguen siendo 0-based y no forman
  parte de la API.
- Overflow: AST/IR usan enteros Python no acotados; native usa i32 y envuelve.
- División por cero double: AST e IR levantan error; LLVM `fdiv` imprime `inf`.
- Print: delimitadores, orientación y shape de Vector/Matrix coinciden entre
  AST/IR/native; List/Array y UDT continúan AST-only. El contrato general de
  formato double sigue parcial porque native usa `%.17g`.
- Strings: AST concatena/compara/interpola; LLVM solo transporta punteros de
  literales y puede imprimirlos.
- Exit: AST, IR y native retornan el valor de `main` (limitado por el proceso/OS
  para el ejecutable nativo); un panic conserva código 1.

## Diagnósticos y documentación desactualizados

No se corrigieron porque la consigna exige separarlos de cambios de
comportamiento.

1. `IR_BACKEND_SUPPORTED_SUBSET` en `src/aether/errors.py:73-83` omite double,
   void, print, for, break/continue, Array/List, slicing, sort, Vector y Matrix.
   Este hint acompaña hoy casi todos los rechazos IR.
2. `_feature_name` no mapea una función anidada y muestra el nombre interno
   `FunctionDeclaration`, confirmado por el sondeo.
3. `docs/compiler/README.md:84` dice que LLVM no está conectado al CLI; sí lo
   está y es el backend predeterminado (`cli.py:111-117`, `307-315`).
4. `docs/compiler/FEATURE_MATRIX.md` (2026-07-11) todavía marca Array native sin
   bounds/overflow/narrowing; `test_array_p0_safety.py` demuestra que los tres
   ya están implementados.
5. La misma matriz afirma primero que `List.insert/removeAt` están completos y
   más abajo que siguen pendientes; los ejemplos LLVM y tests E2E prueban el
   soporte.
6. `ARRAY_SUBSYSTEM_AUDIT.md` tiene una nota de actualización correcta, pero su
   resumen y tablas históricas aún describen get/set LLVM inseguros y DCE de
   ArrayGet. Leer solo esas secciones produce una conclusión falsa.
7. La auditoría anterior decía que Vector era 0-based; la especificación
   normativa y la guía establecen 1-based para Vector y Matrix. Implementación,
   ejemplos y tests ya fueron alineados con esa regla.
8. `AETHER_IR_DESIGN.md` conserva un “supported subset” anterior a colecciones,
   for y álgebra lineal.

Features documentadas sin cobertura E2E nativa: nullable/null, aliases,
imports/packages, exceptions, tuples, structs/classes/interfaces/enums,
operaciones string, List slicing, Array copy/equality y la mayor parte de los
builtins de álgebra lineal. A la inversa, Array safety P0, Array slicing,
List.insert/removeAt y varias operaciones Vector/Matrix ya tienen código/tests
backend que los documentos agregados no reflejan de forma consistente.

## Resumen ejecutivo

El frontend/AST constituye un lenguaje bastante más amplio que el compilador.
El núcleo escalar y de control, Array, y casi toda la API List llegan a native;
UDT, módulos, nullables, excepciones, tuples y numerosos builtins siguen siendo
AST-only. Vector/Matrix sí tienen ahora paridad real para literal, dimensiones,
get/set, bounds, igualdad, impresión y el subconjunto aritmético compilable.

Conteo de las 112 filas de features de la matriz (las 14 etapas de la tabla
inicial no entran en este conteo):

- 42 `Implemented` (incluye filas cuyo estado dice “Implemented para
  frontend” cuando ese era el alcance explícito de la feature tooling);
- 19 `Partial`;
- 37 `AST-only`;
- 3 `Broken`;
- 9 `Not implemented`;
- 1 `Parsed but rejected`;
- 1 `Unknown` (arrays anidados en el pipeline nativo).

El conteo es de capacidades, no una métrica de tamaño: aproximadamente 38% de
las filas auditadas tienen el alcance declarado completo, mientras 33% son
AST-only. Los principales bloqueos son UDT/módulos fuera del lowering, runtime
string incompleto y builtins de álgebra lineal que siguen fuera del lowering.

Features AST-only más relevantes: inferencia por assignment, aliases,
`&&`/`||`, la función factorial, named arguments, float/complex/nullable, input, print de
Array/List/UDT, Array copy/equality, List slicing/equality, builtins avanzados de
álgebra lineal, tuples, todos los UDT, imports/packages y excepciones.

## Prioridades y próximos bloques recomendados

### P0 — programas básicos o seguridad

Los bloques de índices/safety de Vector/Matrix y el modelo común de efectos ya
están cerrados por P2.

1. Definir y hacer coherente división/módulo por cero y overflow int entre
   AST, IR y native.

### P1 — paridad del núcleo

4. Bajar `&&`/`||` con short-circuit y completar conversiones implícitas y
   tipos float/string del core.
5. Actualizar los diagnósticos de backend y retirar matrices/documentos
   históricos contradictorios.

### P2 — colecciones y tipos definidos por usuario

7. Decidir Array copy/equality y List slicing/equality en backend antes de
   ampliar APIs.
8. Migrar por bloques separados: enums primero; structs value-type; classes e
   interfaces después, con ABI/ownership explícitos.
9. Caracterizar arrays anidados native y cerrar su estado `Unknown`.

### P3 — tooling

10. Hacer que IntelliJ permita elegir backend o indique claramente que Run usa
    AST mientras el CLI usa LLVM; agregar formatter solo como bloque separado.
11. Sustituir regex de completions/symbols por información del frontend donde
    sea viable y cubrir features nuevas del lexer IntelliJ.

### P4 — nuevas features y optimizaciones

12. Solo después de paridad/safety: defaults, overloads, genéricos de usuario,
    nuevos optimizadores y APIs de colección nuevas.

Cada número es deliberadamente una unidad separada. Ninguno se implementó en
esta auditoría.
