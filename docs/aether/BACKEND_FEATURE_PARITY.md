# Auditoría completa de paridad de backends

Última revisión: 15 de julio de 2026, incluyendo enums native y los ejemplos
dogfood de métodos numéricos y expense tracker. Este documento reemplaza como
referencia canónica a la auditoría histórica de `docs/compiler/`.

## Criterio

Una clase, nodo, tipo u opcode aislado no cuenta como soporte. **Completo**
exige un camino funcional y pruebas relevantes en todas las etapas aplicables.
**Parcial** identifica un subconjunto o una etapa faltante. **Solo AST** exige
parser, AST, typechecker e intérprete AST funcionales, pero ningún camino
compilado. Los demás estados globales usados son **Solo native**, **No
implementado**, **Implementado pero sin tests**, **Implementado pero sin
documentación**, **Obsoleto** e **Inconsistente**.

Abreviaturas de las celdas por etapa:

- **C**: cobertura funcional comprobada para el alcance de la fila.
- **P**: cobertura parcial o limitada.
- **N**: no implementado/no existe camino.
- **—**: la etapa no aplica.
- **AST**: evidencia solo en frontend/intérprete AST.

“LLVM/native” significa emisión, link con clang y ejecución, no solo la
existencia de un printer. “Runtime” incluye helpers LLVM y runtime Python que
materializan la semántica. “Tests” distingue pruebas de capa de pruebas de
paridad end-to-end.

La ruta nativa real es:

```text
lexer -> parser -> typechecker -> EntryPointNormalizer -> IR lowering
      -> IR verifier -> GeneralSSABuilder -> SSA verifier
      -> SSAOptimizerPipeline -> LLVM printer/runtime -> clang
```

No existe intérprete SSA. AST e IR interpreter son backends alternativos. La
CLI usa LLVM por defecto; REPL e integración IntelliJ ejecutan AST.

## Perfil programático y validación temprana

La auditoría detallada se consolida para consumo del compilador mediante los
perfiles versionados de `src/aether/capabilities.py`; su contrato y política de
actualización están en
[`BACKEND_CAPABILITY_PROFILES.md`](BACKEND_CAPABILITY_PROFILES.md). El perfil
no reemplaza esta auditoría: agrupa capacidades observables por el usuario y la
auditoría conserva evidencia por etapa, arquitectura y deuda interna.

Después de parsing y typechecking, el detector recorre el AST chequeado y
valida el perfil AST o LLVM/native antes del lowering específico. Una
limitación native se reporta como incompatibilidad de backend con código
`AE-BACKEND-*`, ubicación y sugerencia de AST únicamente cuando el perfil AST
cubre ese uso. Los verificadores IR/SSA y los rechazos específicos de LLVM se
mantienen como defensa interna.

La reconciliación inicial confirmó el resumen de esta auditoría. Desde el
perfil 4, “funciones como valores” incluye un callable estructural tipado para
funciones top-level sin captura en AST y native; permanece `PARTIAL` porque no
incluye closures, lambdas, métodos enlazados, builtins como valores ni retorno
de callables. Strings/native sigue `PARTIAL` por transporte de
literales/parámetros/retornos, mientras concat, comparación general e
interpolación quedan fuera del subconjunto.

## Tipos, declaraciones y operadores

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `int` i32 | C | C | C | C | C | C | C | C | C | C | C | C | C | paridad E2E | P | Parcial | Semántica checked i32 ya coincide; la spec aún contiene pasajes históricos. |
| `double` | C | C | C | C | C | C | C | C | C | C | C | C | C | E2E | C | Completo | División sigue IEEE-754, incluidos inf/NaN. |
| `boolean` | C | C | C | C | C | C | C | C | C | C | C | C | C | E2E | C | Completo | `bool` no es spelling público; se usa `boolean`. |
| `float` | C | C | C | C por coerción | C nominal | P | P | P | P | P | P | N | N | frontend | P | Solo AST | Literales decimales nacen `double`; falta mapping LLVM estable. |
| `complex` / literal `im` | C | C | C | C | C nominal | N desde fuente | P nominal | N | P nominal | P nominal | N | N | AST Python | AST | C v0 | Solo AST | Ya existe como primitivo experimental, en tensión con el diseño futuro de stdlib. |
| `null` y `T?` | C | C | C | C | P nominal | N | P nominal | N | N | N | N | N | AST | frontend | C v0 | Solo AST | Sin narrowing ni backend. |
| Variables locales tipadas mutables | C | C | C | C | C | C | C | C | C | C | C | C | — | E2E | C | Completo | Requieren inicializador. |
| `const` local | C | C | C | C | sin opcode propio | C, se borra tras TC | C | C | C | C | C | C | — | frontend+backend | C | Completo | La garantía es estática; no necesita representación runtime distinta. |
| Inferencia `x = expr` | C | C | C | C | N para global implícito | N | N | N | N | N | N | N | AST | frontend | C | Solo AST | El compilador exige locales que ya estén declarados. |
| Alias de tipo | C | C | C | C | se resuelve | P: top-level alias aceptado solo como metadata | C | C | C | C | C | C para usos soportados, incluidos aliases importados | — | AST+struct backend | C | Parcial | El alias conserva identidad semántica separada del nombre interno. |
| Operadores `+ - * /` escalares | C | C | C | C | C | C int/double | C | C | C | C | C checked | C int/double | C | E2E+safety | P | Parcial | `float`, `complex`, string y agregados amplían la superficie AST. |
| Overflow entero y negación mínima | — | — | permite runtime | C: panic i32 | C `may_trap` | C | C | C | C | C | C preserva traps | C intrinsics checked | C | E2E AST/IR/native | P | Completo | Contrato implementado después de la auditoría histórica. |
| División por cero | — | — | permite runtime | C | C | C | C | C | C | C | C | C | C | E2E | P | Completo | Int hace panic; double usa IEEE-754 en los tres backends. |
| `%` truncante | C | C | C | C int/double | C `rem` | C | C | C int/double | C | C | C | P: solo int | P | AST+int native | C | Parcial | LLVM no emite `frem`; divisor cero double difiere en mensaje/camino. |
| `Math.mod` floor-mod | llamada normal | C | C | C | C call builtin | C | C | C | C | C | C checked | C helper tipado | runtime mínimo | AST/IR/native | C | Completo int/double | Es builtin de namespace, no operador. |
| Comparaciones ordenadas | C | C | C | C | C | C int/double | C | C | C | C | C | C int/double | — | E2E | C | Parcial | Otros numéricos/agregados tienen cobertura distinta. |
| Igualdad escalar | C | C | C | C | C | C | C | C | C | C | C | P | P string | amplia | P | Parcial | String native por contenido solo dentro de igualdad de struct; compare string general se rechaza. |
| Igualdad agregada | C | C | C | C | P | P Struct/Vector/Matrix | C subset | C subset | C subset | C subset | P | P | helpers | amplia por tipo | P | Parcial | Array/List generales son AST-only; structs tienen límites de tipos de campo. |
| `&&` / <code>&#124;&#124;</code> short-circuit | C | C | C boolean | C | CFG | C por branches/merge | C | C | C con phi | C | C SCCP | C | — | E2E | P desactualizada | Implementado pero sin documentación | Código y tests son completos; spec/matrices aún dicen AST-only. |
| `!` prefijo | C | C | C boolean | C | C | C | C | C | C | C | C | C `xor` | — | E2E | C | Completo | No existe factorial postfix. |
| Casts explícitos | C | C | C amplio | C amplio | P | P int↔double | C subset | C subset | C subset | C subset | P | P int↔double | P | frontend+par | C | Parcial | `string`, `boolean`, `float`, `complex` exceden backend. |

## Funciones y control de flujo

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Funciones tipadas y parámetros | C | C | C | C | C | C para tipos backend | C | C | C | C | C conservador | C | stack nativo | E2E | C | Parcial | La fila es parcial por tipos de parámetros que solo existen en AST. |
| Funciones `void` | C | C | C | C | C | C | C | C | C | C | C | C | — | E2E | C | Completo | Calls void solo como statement. |
| Funciones como parámetros/valores | C `R(P...)` | C `FunctionType` | C exacto, símbolos/imports | C valor explícito sin entorno | C `FunctionType`/`function_ref`/`call_indirect` | C local e imports | C firma/símbolo/void | C | C refs/calls/phi | C tipos/dominancia | C conservador, calls con efectos | C `ptr` y call indirecta | sin heap/environment | E2E AST/IR/SSA/clang | C | Parcial | Solo funciones block top-level de usuario sin captura; no closures, lambdas, bound methods, builtins/expresión como valor ni retorno callable. |
| Expression functions `f(x)=...` | C | C | P tipo `unknown` por callsite | C | N | N | N | N | N | N | N | N | AST | AST | C | Solo AST | Útiles para exploración, no para callbacks ni compilación. |
| Calls directas y recursión | C | C | C; firmas multifase | C | C | C | C | C | C | C | C conservador | C | — | E2E directa/mutua | P | Completo | Orden de declaración resuelto recientemente. |
| `return` | C | C | C paths/tipo | C | C | C | C | C | C | C | C | C | exit `main` | E2E | C | Completo | `main` retorna int y no recibe parámetros. |
| `if` / `else` | C | C | C boolean | C | CFG | C | C | C | C/phi | C | C | C | — | E2E | C | Completo | Incluye ramas con retorno. |
| `while` | C | C | C boolean | C | CFG | C | C | C | C loop phi | C | C | C | — | E2E | C | Completo | Control anidado cubierto. |
| `for` sobre rango | C | C | C | C | CFG | C pasos +/-/dinámicos | C | C | C | C | C | C | — | E2E | C | Completo | Rango es inclusivo según spec actual. |
| `for-in` sobre colección | C | C | C | C amplio | CFG/get/length | P Array/List/Vector | C subset | C subset | C subset | C subset | P | C subset | bounds helpers | E2E subset | P | Parcial | Matrix y otras colecciones no comparten iterable general. |
| `break` / `continue` | C | C | C solo loop | C | jumps | C | C | C | C | C | C | C | — | E2E nested | C | Completo | Se bajan a targets del loop activo. |
| Entry point y top-level script | C | C | C | C | función `main` | C tras normalización | C | C | C | C | C | C | exit code | E2E | C | Completo en raíz | Solo `main` del módulo raíz conserva ABI; un `main` importado se manglea. Statements top-level importados aún requieren inicialización. |
| Tuples y destructuring | C | C | C | C | N | N | N | N | N | N | N | N | AST | AST | C | Solo AST | Incluye retornos múltiples en AST. |

## Strings, IO y proceso

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| String literal/variable/arg/return | C | C | C | C | C ptr-like | C | C | C | C | C | P | C para transporte | P sin ownership | backend subset | C | Parcial | Falta modelo de encoding/heap/vida útil para strings no literales. |
| Concat, igualdad e interpolación string | C | C | C | C | P binary/compare | P | C nominal | P | P | P | P | N general | AST | AST+rechazos | C | Solo AST | Interpolación se resuelve en AST; LLVM rechaza binary string. |
| `print` / `println` escalares | llamada | C | C variádico | C | C `IRPrint` | C | C | C | C | C | C efecto | C | `printf`/helpers | E2E | C | Completo | Formato double general aún usa contratos host distintos en casos extremos. |
| Print Array/List | llamada | C | C | C | P tipos | N general | N | N | N | N | N | N | AST | AST | P | Solo AST | Struct con campos Array/List escalares tiene helper específico, no print general de la colección. |
| Print Struct/Vector/Matrix | llamada | C | C | C | C subset | C subset | C | C | C | C | C | C subset | helpers | E2E | P | Parcial | Shape/tipos de campos limitan el subconjunto struct. |
| `input` tipado | C nodo dedicado | C | C por contexto | C | N | N | N | N | N | N | N | N | AST stdin | AST | C | Solo AST | No existe input native. |
| Argumentos del proceso | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | No implementado | `main` con parámetros es error deliberado. |
| Archivos (API del lenguaje) | N | N | N | N | N | N | N | N | N | N | N | N | N | N | N | No implementado | La lectura de módulos fuente no es file IO para programas Aether. |

## Módulos y tipos definidos por usuario

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Packages, módulos e imports | C | C | C aliases/selectivos/ciclos | C carga/cache | C programa chequeado; IR combinado | C declaraciones soportadas | C | C | C | C | C | C subset | sin runtime nuevo | unit+IR+native E2E | C subset | Parcial | Un package mapea a un archivo. Faltan globals/constantes y statements top-level importados, diagnosticados antes del lowering. |
| Visibilidad top-level | C | C | C en imports | C | identidad/export metadata | C consume referencias resueltas | C | C | C | C | C | C subset | — | semantic+native | C | Parcial native | Privacidad se valida semánticamente; dentro del mismo archivo no restringe acceso. |
| Struct fields/constructores | C | C | C nominal | C | C definiciones/new/get/set | C subset | C | C | C | C | C | C subset | helpers print/equality | E2E dedicado | P obsoleta | Parcial | Core int/double/bool/string/nested y Array/List escalares; aún hay límites de campo. |
| Métodos de struct y `this` | C | C | C mutabilidad | C | C funciones + method result | C | C | C | C | C | C | C | — | E2E | P | Completo | Para tipos de firma soportados por backend. |
| Semántica por valor de struct | — | C | C const | C copia | C reconstrucción | C | C | C | C | C | C | C by-value | — | E2E copia/arg/return | C | Completo | Campos reference mantienen copia shallow deliberada. |
| Igualdad/print de struct | C | C | C comparabilidad | C | C recursivo subset | C | C | C | C | C | C | C subset | helpers | E2E | P | Parcial | Enum ya está soportado como campo; nullable/Vector/Matrix conservan límites. |
| Classes por referencia | C | C | C visibilidad/alias | C | P tipo nominal | N | P nominal | N | N | N | N | N | AST objects | amplia AST | C | Solo AST | Sin ownership/layout native. |
| Constructores/métodos/`this` de class | C | C | C | C | N | N | N | N | N | N | N | N | AST | amplia AST | C | Solo AST | Public/private funciona en frontend. |
| Interfaces y dispatch | C | C | C conformidad | C struct/class | P tipo nominal | N | P nominal | N | N | N | N | N | AST dispatch | amplia AST + dogfood | C | Solo AST | Bloquea callables por interfaz en el ejemplo numérico. |
| Enums sin payload | C | C | C identidad módulo/declaración | C valor nominal+discriminante | C `enum Name` + constante nominal | C | C miembros/discriminantes/tipos | C | C phis/tipos | C nominal/dominancia | C folding preserva tipo | C `i32` ABI interno | metadata de impresión | AST+IR+SSA+clang O0/O1/O2 | C | Completo | Sin payload, ADT, casts implícitos, bit flags ni pattern matching nuevo. Imports, aliases, homónimos, structs, arrays/list compatibles y callables funcionan. |
| Genéricos de usuario | P: se reconocen para rechazo | P | N | N | N | N | N | N | N | N | N | N | N | negativos | C como no soportado | No implementado | Array/List/Vector/Matrix son genéricos privilegiados, no evidencia de generics generales. |

## Array, List, Vector y Matrix

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Array<T>` literal | C target-typed | C | C | C | C | C | C | C | C | C | C allocation | P subconjunto escalar/enum; no Struct | P sin size/layout Struct | E2E escalares + dogfood Struct AST | C | Parcial | El frontend acepta `Array<Struct>`, pero LLVM falla tarde al calcular el tamaño del elemento. |
| Bounds checks Array | — | — | índice int | C | efectos `may_trap` | C | C | C | C | C | C preserva | C | C | safety E2E | P histórico | Completo | Auditorías antiguas aún describen el estado inseguro ya corregido. |
| Array get/set/length | C | C | C | C | C | C | C | C | C | C | C | C | C narrowing | E2E | P | Completo | Índices 0-based. |
| Array sort | método/global | C | C tipos | C estable in-place | C sequence sort | C | C | C | C | C | C efecto | C | C temp checked | E2E | C | Completo | int/double/string. |
| Array slicing | C `a[s:e]` | C | C | C copy | C | C | C | C | C | C | C | C | C bounds | E2E | C | Completo | 0-based, half-open, dos límites explícitos. |
| Array copy/equality | C | C | C | C | P | N general | N | N | N | N | N | N | AST | AST | P | Solo AST | `copy` shallow y equality estructural no bajan. |
| `List<T>` literal/new/get/set | C target-typed | C | C | C | C | C | C | C | C | C | C | P subconjunto escalar/enum; no Struct | P sin size/layout Struct | E2E escalares + expense tracker AST | C | Parcial | No hay keyword `new`; `List<Struct>` se acepta pero LLVM falla tarde al calcular tamaño. |
| List length/capacity/core mutation | métodos | C | C | C | C salvo capacity pública | C | C | C | C | C | C | C | C checked growth | E2E | P | Parcial | `capacity` se usa internamente pero no es API pública completa. |
| List push/pop/insert/removeAt/clear | métodos/global | C | C | C | C | C | C | C | C | C | C efecto/trap | P sin elementos Struct | P layout/copia/ownership agregados | E2E+safety escalares + push Struct AST | C | Parcial | No shrinking deliberado; falta diagnóstico temprano para elementos no soportados. |
| List contains/indexOf/reverse/copy/sort | métodos/global | C | C | C | C | C | C | C | C | C | C | C | C | E2E | C | Completo | Son derivables conceptualmente aunque hoy privilegiados. |
| List slicing/equality | C | C | C | C | N | N | N | N | N | N | N | N | AST | AST | P | Solo AST | Slicing tiene formas limitadas. |
| Vector literal/get/set/length | C | C | C shape/orientation | C 1-based | C | C | C | C | C | C | C traps | C | C | E2E+safety | C | Completo | Vector matemático, no colección dinámica. |
| Operaciones Vector | C operadores | C | C shapes | C | C add/sub/scale/dot/outer/mul | C subset int/double | C | C | C | C | P sin álgebra específica | C subset | C loops | E2E amplia | P | Parcial | Transpose y varios builtins siguen AST-only. |
| Matrix literal/get/set/rows/columns | C | C | C shape | C 1-based | C | C | C | C | C | C | C traps | C | C | E2E+safety | C | Completo | Storage contiguo; valida fila/columna antes del offset. |
| Operaciones Matrix | C operadores | C | C shapes | C | C add/sub/scale/matmul/mul vector | C subset | C | C | C | C | P | C subset | C loops | E2E amplia | P | Parcial | No toda la superficie `Math.LinearAlgebra` baja. |
| Álgebra lineal avanzada | calls/namespaces | C | C amplia | C SciPy/NumPy opcional host | N mayoría | N | N | N | N | N | N | N | AST Python | amplia AST | C | Solo AST | solve, eig, SVD, LU/LDU, subspaces, etc.; no deben obligar NumPy en runtime futuro. |
| Map/Set/Queue/Stack | N | N | N | N | N | N | N | N | N | N | N | N | N | N | diseño v1 | No implementado | Candidatos a `collections`, no builtins automáticos. |

## Matemática, errores y herramientas

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Matemática escalar (`sin`, `sqrt`, `abs`, etc.) | calls | C | C | C IEEE/checked + sqrt complejo heredado | C call con id builtin | C reales consolidados | C firmas | C registry AST | C preserva id | C firmas | C efectos/DCE | C int/double | intrinsics, `libm`, helpers checked | AST/IR/SSA/native | C + auditoría | Parcial | `float`, builtins complejos y la divergencia `sqrt(real negativo)` quedan fuera de la paridad completa. |
| `PI` y `E` | import/member | C | C para `Math.pi` | C para `Math.pi` | C const double | C directa | C | C | C | C | C | C inmediata | sin global/init | AST/IR/native | P | Parcial | Solo `Math.pi`; `PI` global y `E` no existen. |
| `throw` / `try-catch` | C | C | C | C | N | N | N | N | N | N | N | N | AST exceptions | AST | C | Solo AST | Sin finally, jerarquías ni stack traces. |
| Panics de safety | — | — | tipos preventivos | C | efectos/traps | C | C | C | C | C | C preserva | C | C `puts/exit` | E2E | P dispersa | Completo | Array/List/Vector/Matrix, overflow int y allocation. |
| CLI run/build/inspect/bench | — | — | usa frontend | AST seleccionable | usa IR | C subset | C | C subset | export/build | C | perfiles parciales | default/build C subset | clang | tests CLI | P desactualizada | Parcial | Perfil LLVM default es mucho menor que superficie aceptada. |
| REPL persistente | C por entrada | C | C incremental | C rollback | N | N | N | N | N | N | N | N | AST session | tests | C | Solo AST | `--backend=ast` obligatorio. |
| LSP | lexer/parser | AST | C diagnósticos frontend | — | N | N | N | N | N | N | N | N | proceso LSP | tests | P | Parcial | Completion/hover/symbols parciales; sin formatter/rename semántico completo. |
| Optimización `-O0` | — | — | — | — | C | C | C | — | no usada por emit-ir | — | sin pases | — | — | CLI/optimizer | C | Completo | Solo `--emit-ir`; no controla build native. |
| Optimización `-O1` | — | — | — | — | C | C | C post-pass | — | SSA native tiene pipeline propio | C | C fixed point IR | native no usa flag | — | amplia | C | Parcial | El nombre de perfil solo conecta a emisión IR. |
| Optimización `-O2` | — | — | — | — | C | C | C | — | igual | C | alias de O1 | native no usa flag | — | CLI | C como alias | Parcial | No es un nivel más fuerte; debe seguir marcado experimental. |
| ABI C / FFI | N | N | N | N | N | N | N | N | N | N | N | N | usa libc internamente | N | diseño futuro | No implementado | Usar `printf`/malloc internamente no constituye una FFI pública. |

## Bloqueadores reales para Aether v1

1. **Inicialización y globals de módulos:** declaraciones soportadas ya cruzan
   imports; falta storage e inicialización single-execution para el resto de la
   semántica AST.
2. **Classes e interfaces native:** la promesa generalista sigue partida;
   structs y enums simples ya no son el bloqueo principal.
3. **Strings completos:** falta concat/equality/interpolación general,
   representación, encoding y ownership.
4. **Colecciones de datos definidos por usuario:** `Array/List<Struct>` se
   aceptan en frontend pero fallan tarde en LLVM por falta de size/layout/copia.
5. **Callables avanzados:** el subconjunto top-level tipado ya permite una
   stdlib numérica reusable; closures, lambdas y métodos enlazados quedan para
   un diseño posterior y no bloquean ese caso.
6. **Errores básicos compilados:** decidir y completar `throw`/`try-catch` o un
   perfil alternativo explícito.
7. **IO de entrada, archivos y argumentos de proceso:** faltan capacidades
   generales mínimas.
8. **Paridad del perfil:** cerrar `%` double, casts, formato y combinaciones de
   agregados antes de llamar estable al subconjunto.

La deuda anterior del **SSA verifier** queda cerrada: el verificador comprueba
dominancia y orden de todos los usos, trata operandos `phi` sobre su arista,
exige un incoming exacto por predecesor, valida inalcanzables con la política
documentada y se ejecuta tras construcción, tras cada pase SSA en
desarrollo/tests y obligatoriamente antes del camino LLVM/native. Hay tests
positivos y negativos directos para diamonds, loops/backedges, loops anidados,
phis incompletos/sobrantes/duplicados, usos no dominados y productores que
dejan SSA inválido.

## Inconsistencias semánticas confirmadas

- `%` admite reales en frontend/IR interpreter, pero LLVM solo implementa
  remainder entero.
- `float` y `complex` son tipos aceptados en frontend sin representación native
  completa.
- String equality general funciona en AST, pero LLVM solo posee comparaciones
  especiales dentro de ciertos helpers de structs.
- `Array/List<Struct>` atraviesa frontend, IR y SSA, pero el emisor LLVM filtra
  un error interno al necesitar el tamaño del elemento, en vez de rechazarlo
  según el perfil antes del lowering.
- El CLI elige LLVM por defecto aunque la mayor parte de módulos, UDT de
  referencia, errores y builtins matemáticos sean AST-only.
- `Plots` conserva un hook AST legado, separado del callable tipado general;
  los builtins y funciones de expresión tampoco son valores callable.
- El runtime AST de álgebra avanzada usa NumPy/SciPy del host; esa es una
  implementación prototipo, no un contrato aceptable de runtime native.

## Features aparentemente implementadas pero incompletas

- Tipos nominales `ClassRefType`, `InterfaceType`, `EnumType`, `FloatType` y
  `ComplexType` en IR no tienen un camino fuente ejecutable completo.
- La existencia de genéricos privilegiados en Array/List/Vector/Matrix no
  implica genéricos de usuario.
- Strings como `ptr` LLVM permiten transportar literales, no un runtime string.
- La API List es amplia para elementos soportados, pero elementos struct,
  ownership/free y capacity pública no están cerrados.
- `-O2` existe como opción, pero es alias de `-O1` y no afecta native.
- Builtins de álgebra lineal tienen typechecker e intérprete AST extensos, pero
  la mayoría no tiene IR.
- El soporte de struct es real, aunque no cubre todavía todo tipo de campo que
  acepta el frontend.

## Documentación desactualizada

- `AETHER_V0_SPEC.md` todavía afirma que structs no bajan a IR/JIT y que aliases
  de imports/selective imports no existen; ambos hechos cambiaron.
- La misma spec y `FEATURE_MATRIX.md` describen `&&`/`||` como AST-only; ya
  tienen CFG, SSA, optimización y tests native.
- `FEATURE_MATRIX.md` y auditorías históricas conservan estados inseguros de
  Array ya corregidos y contradicciones sobre List insert/removeAt.
- `docs/compiler/README.md` afirma que LLVM no está conectado al CLI; hoy es el
  backend predeterminado.
- `AETHER_IR_DESIGN.md` conserva un subset anterior a for, colecciones,
  structs y álgebra lineal básica.
- El hint `IR_BACKEND_SUPPORTED_SUBSET` de `errors.py` omite short-circuit,
  structs, Array/List, for y Vector/Matrix ya soportados.
- El README anterior describía el backend native como si no tuviera runtime,
  println ni agregados; los tests actuales prueban lo contrario.

## Deuda técnica de alto riesgo

1. Varias matrices manuales duplican la misma verdad y se desactualizan tras
   cada bloque de backend.
2. El perfil compilable no está representado como dato único reutilizable por
   diagnósticos, docs y CLI.
3. Ownership de List/string/class y liberación no tiene contrato v1; añadir más
   referencias antes de fijarlo multiplica el riesgo.
4. El runtime matemático AST mezcla semántica de lenguaje con bibliotecas
   Python opcionales.
5. Formato numérico y ciertos mensajes de panic no provienen de un contrato
   único entre AST, IR y libc.

## Próximas acciones recomendadas

1. Generar un perfil de capacidades versionado y usarlo en diagnóstico, CLI y
   documentación; corregir inmediatamente docs contradictorias.
2. Extender el modelo IR con globals e inicialización explícita de módulos,
   reutilizando el `CheckedProgram` y los tests multiarchivo existentes.
3. Cerrar `%` double y las conversiones implícitas restantes; la matemática
   escalar real ya usa calls conocidas sin inflar el IR.
4. Mantener el ABI de callables top-level tipados y diseñar closures solo si
   casos de uso posteriores justifican una representación `{code, environment}`.
5. Diseñar interfaces/classes con layout, dispatch y ownership documentados.
6. Completar runtime string y luego IO de entrada/archivos/args.
7. Promover el ejemplo numérico a `math.numerics` solo después de callables,
   módulos native y un módulo `testing` mínimo.
