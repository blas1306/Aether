# Auditoría final del perfil Aether 1.0

Fecha de corte: **2026-07-18**. Release observada: **1.0.0-rc.2**. Perfil
native observado: **22**. Plataforma native validada: **Linux x86_64 + clang**.

Este documento es la matriz autoritativa de cierre. A diferencia de las
matrices históricas, el estado final nunca usa `PARTIAL`: cada subconjunto
concreto es `SUPPORTED`, `OUTSIDE_V1`, `BROKEN` o `UNDECIDED`. El perfil
estable recomendado es deliberadamente menor que toda la superficie que el
parser y el intérprete AST pueden reconocer.

## 1. Resultado ejecutivo

La auditoría inventaría **123 features concretas**: **75 `SUPPORTED`**, **46
`OUTSIDE_V1`**, **2 `BROKEN`** y **0 `UNDECIDED`**. No se encontró un P0. Se
encontraron **2 P1, 6 P2 y 3 P3**. Los dos estados `BROKEN` son superficies de
producto —coherencia documental y catálogo de ejemplos—, no construcciones
que el gate native acepte y luego miscompile.

> Seguimiento: esta tabla conserva el snapshot del 2026-07-18 que abrió B12 y
> B13. Los planes R1/F02 y R2/F01 se cerraron después mediante gates dedicados.
> Tras la reconciliación del 2026-07-28, el catálogo actual tiene 88
> `V1_NATIVE`, 17 `AST_ONLY_EXPERIMENTAL` y cero `BROKEN`; véase
> `AETHER_EXAMPLES_CATALOG_AUDIT.md`.

La evidencia ejecutada en este corte fue:

- 103 archivos en `examples/`: 78 `V1_NATIVE`, 21
  `AST_ONLY_EXPERIMENTAL`, 4 `BROKEN`, 0 `OUTDATED`;
- los 78 archivos native pasaron parse, typecheck, capability gate y emisión
  LLVM; 68 tenían entry point y compilaron/ejecutaron con el exit code y los
  hashes registrados; 10 son módulos y emitieron LLVM sin inventar un `main`;
- corpus diferencial: 14 programas y 42 comparaciones AST/native en clang
  O0/O1/O2; el caso `language_core` también coincide con el IR interpreter;
- no existe fallback silencioso de native a AST en el CLI;
- `float`, `complex`, classes, interfaces, tuples, rangos almacenados,
  interpolación, input y excepciones se detienen antes del lowering native.

El manifiesto ejecutable y reproducible está en
`examples/v1_examples_manifest.json`; su regresión está en
`tests/aether/test_v1_profile_audit.py`.

## 2. Contrato de backends

| Backend | Rol de Aether 1.0 | Contrato |
| --- | --- | --- |
| Native | Backend principal y única frontera de ejecución estable del perfil v1. | Todo programa `SUPPORTED` debe pasar frontend, gate, IR verifier, SSA verifier, LLVM, clang y ejecución. No hay fallback. |
| AST | Intérprete auxiliar, backend del REPL y referencia semántica para pruebas diferenciales. | Puede ejecutar features `OUTSIDE_V1`; eso no las incorpora a v1. No es una segunda frontera estable que amplíe el lenguaje 1.0. |
| IR interpreter | Infraestructura interna de caracterización y depuración. | No forma parte del contrato público. Puede cubrir menos que native y nunca define disponibilidad v1. |
| SSA | Representación/verificación interna, no backend ejecutable público. | Toda emisión native pasa por SSA verificado y por optimizadores con verificación posterior. |

`aether archivo.ae` y `aether run archivo.ae` seleccionan LLVM/native por
defecto. `--backend=ast` y `--backend=ir` son elecciones explícitas. El REPL es
AST-only y lo declara; no hay fallback automático al fallar native.

## 3. Leyenda y fuentes de evidencia

- `Sí`: la etapa implementa el subconjunto exacto de la fila.
- `Gate`: el frontend lo reconoce, pero native lo rechaza antes de IR.
- `No`: no existe esa representación o ejecución.
- `—`: no aplica a esa feature.
- `Fmt/LSP/IJ`: formatter, language server y plugin IntelliJ.

Componentes principales: `lexer.py`, `parser.py`, `ast.py`, `types.py`,
`typechecker.py`, `interpreter.py`, `capabilities.py`, `ir/`, `ssa/`,
`backend/llvm/`, `cli.py`, `source_formatter.py`, `aether_lsp/` y
`tools/intellij-aether/`. Las pruebas citadas usan el nombre de archivo bajo
`tests/aether/` salvo que se indique otra ruta.

## 4. Matriz autoritativa

### 4.1 Sintaxis, declaraciones y control de flujo

| ID | Feature | Parser | Typechecker | AST | IR | SSA | Native | Tooling | Docs | Estado v1 | Implementación / tests / ejemplos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C01 | Variable local tipada con inicializador | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §5 | SUPPORTED | parser/typechecker/lowering; `test_ir_lowering.py`; `examples/llvm/*` |
| C02 | Declaración local inferida por asignación | Sí | Sí | Sí | Gate | No | No | Fmt/LSP | Spec §5 | OUTSIDE_V1 | capability `VARIABLES_AND_CONST`; `test_backend_capabilities.py`; `probandoNR.ae` |
| C03 | `const T name = value` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §5 | SUPPORTED | `scope.py`; `test_const_collection_borrowed_for.py`; `ir/local_const.ae` |
| C04 | Asignación simple | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §5 | SUPPORTED | AST `Assignment`; lowering/store; `language_core.ae` |
| C05 | Asignación compuesta `+=` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §6 | SUPPORTED | token `PLUS_EQUAL`; control-flow tests; `language_core.ae` |
| C06 | Otras compuestas (`-=`, `*=`, `/=`) | No | No | No | No | No | No | IJ sólo puntúa | No canónica | OUTSIDE_V1 | No hay tokens/nodos; diagnóstico syntax esperado |
| C07 | Bloques, scopes y no-shadowing | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP | Spec §5 | SUPPORTED | `scope.py`; `test_control_flow_regression.py` |
| C08 | `if (condition)` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §7 | SUPPORTED | `test_control_flow_iteration_characterization.py` |
| C09 | `else if` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §7 | SUPPORTED | desazucar a `IfStatement`; test de lazy branch |
| C10 | `else` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §7 | SUPPORTED | IR branches/phis; corpus `language_core` |
| C11 | `while (condition)` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §7 | SUPPORTED | `test_for_backend.py`; corpus `language_core` |
| C12 | `for` sobre rango int literal, inclusivo | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Native profile §4 | SUPPORTED | `range_safety.py`; `test_control_flow_iteration_characterization.py` |
| C13 | Rango almacenado y luego iterado | Sí | Sí | Sí | Gate | No | No | Fmt/LSP | Perfil exacto | OUTSIDE_V1 | `AE-BACKEND-FOR_IN`; regresión `test_v1_profile_audit.py` |
| C14 | `for-in` Array/List/Vector soportado | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §7 | SUPPORTED | borrowed elements; `test_const_collection_borrowed_for.py` |
| C15 | `for-in` Matrix o string | Sí | Sí | AST según tipo | Gate | No | No | Fmt/LSP | Auditorías | OUTSIDE_V1 | Matrix iteration sigue fuera del lowering estable |
| C16 | `break` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §7 | SUPPORTED | loop contexts; `for_break_continue.ae` |
| C17 | `continue` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §7 | SUPPORTED | loop contexts; `for_break_continue.ae` |
| C18 | `return`, incluido retorno temprano | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §8 | SUPPORTED | verifier terminators; corpus `language_core` |
| C19 | Función normal tipada | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §8 | SUPPORTED | forward signatures; `test_declaration_order.py` |
| C20 | Función abreviada con retorno explícito | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §8 | SUPPORTED | `ExpressionFunctionDeclaration`; NR2/NR3 |
| C21 | Función abreviada con retorno inferido | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §8 | SUPPORTED | desazucar antes de backend; `test_expression_functions_and_math.py` |
| C22 | `int main()` y main sintético top-level | Sí | Sí | Sí | Sí | Sí | Sí | CLI/LSP/IJ | Spec §3.3 | SUPPORTED | `entry_point.py`; `test_entry_point.py` |
| C23 | Llamadas adelantadas, recursión y recursión mutua | Sí | Sí | Sí | Sí | Sí | Sí | LSP parcial | Spec §5/8 | SUPPORTED | multifase; `test_declaration_order.py`; corpus `language_core` |
| C24 | Funciones anidadas | Sí | Sí | Sí | No | No | No | Parser/LSP | No v1 | OUTSIDE_V1 | lowering `FunctionDeclaration` unsupported; parity characterization |
| C25 | Imports de funciones/structs/enums/callables soportados | Sí | Sí | Sí | Sí | Sí | Sí | LSP parcial | Spec §3.2 | SUPPORTED | `modules.py`; `test_native_modules.py`; numerical methods |
| C26 | Globals/const y statements inicializadores importados | Sí | Sí | Sí | Gate | No | No | LSP parcial | Perfil §4 | OUTSIDE_V1 | `AE-BACKEND-MODULES`; no storage/init single-execution native |

### 4.2 Tipos

| ID | Feature | Parser | Typechecker | AST | IR | SSA | Native | Tooling | Docs | Estado v1 | Implementación / tests / ejemplos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T01 | `int` checked i32 | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §2/4 | SUPPORTED | `integer_arithmetic.py`; safety tests |
| T02 | `float` binary32 distinto de double | Sí | Sí | Sí | Nominal | Nominal | Gate | Fmt/LSP/IJ | Spec §4 | OUTSIDE_V1 | `AE-BACKEND-PRIMITIVE_TYPES`; decisión: reservar fuera de v1 |
| T03 | `double` IEEE binary64 | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §4 | SUPPORTED | numeric parity, scalar math, NR examples |
| T04 | `boolean` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §4 | SUPPORTED | short-circuit/equality tests |
| T05 | `string` inmutable UTF-8 | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §10 | SUPPORTED | length-aware ARC runtime; string corpus |
| T06 | `void` | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §4/8 | SUPPORTED | `test_void_functions.py` |
| T07 | Enum nominal sin payload | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §4 | SUPPORTED | `test_enum_native.py`; expense tracker |
| T08 | Struct por valor con campos soportados | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §4/9 | SUPPORTED | lifecycle/Eq; struct parity tests |
| T09 | Class por referencia | Sí | Sí | Sí | No | No | Gate | LSP/IJ | Frontend annex | OUTSIDE_V1 | `AE-BACKEND-CLASSES`; ejemplos `classes/` experimentales |
| T10 | Interface y dispatch | Sí | Sí | Sí | No | No | Gate | LSP/IJ | Frontend annex | OUTSIDE_V1 | `AE-BACKEND-INTERFACES`; `test_interfaces.py` |
| T11 | Tuple y destructuring | Sí | Sí | Sí | Parcial histórico | No estable | Gate | LSP parcial | Spec §4.3 | OUTSIDE_V1 | `AE-BACKEND-PRIMITIVE_TYPES`; tuple return tests AST |
| T12 | `null` y `T?` | Sí | Sí | Sí | Nominal | No estable | Gate | LSP/IJ | Spec §4 | OUTSIDE_V1 | no narrowing/layout native |
| T13 | `Any` | No | No | No | No | No | No | No | No | OUTSIDE_V1 | No forma parte del lenguaje implementado |
| T14 | Tipo callable top-level sin captura | Sí | Sí | Sí | Sí | Sí | Sí | LSP parcial | Perfil §4 | SUPPORTED | `test_typed_callables.py` |
| T15 | Lambda o closure | No | No | No | No | No | No | No | Fuera | OUTSIDE_V1 | explícitamente no implementar |
| T16 | `Range<int>` efímero de loop | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP | Perfil §4 | SUPPORTED | inclusive/directional/zero-step tests |
| T17 | `Range<int>` como variable/parámetro/retorno | Sólo inferido | Sí parcial | Sí | Gate | No | No | LSP parcial | Perfil exacto | OUTSIDE_V1 | no sintaxis fuente `Range<T>`; `AE-BACKEND-FOR_IN` |
| T18 | `Range<double>` | Parser expresión | Rechaza | No | No | No | No | Syntax/type diag | Fuera | OUTSIDE_V1 | rango sólo int; diagnóstico type temprano |
| T19 | `Array<T>` para scalar/string/struct soportado | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §4/10 | SUPPORTED | array safety/RC/slicing/Eq tests |
| T20 | Array anidado o con class/layout no soportado | Sí | Sí | AST | Gate | No | No | LSP parcial | Perfil §4 | OUTSIDE_V1 | `AE-BACKEND-AGGREGATE_COLLECTION_ELEMENTS` |
| T21 | `List<T>` para scalar/string/struct soportado | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §4/10 | SUPPORTED | list backend/growth/RC tests |
| T22 | List anidada o con class/layout no soportado | Sí | Sí | AST | Gate | No | No | LSP parcial | Perfil §4 | OUTSIDE_V1 | gate por element layout/lifecycle |
| T23 | `Vector<int/double>` core con shape local | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Perfil §4 | SUPPORTED | LLVM vector examples; semantic parity tests |
| T24 | Vector avanzado o shape cruzando ABI no representable | Sí | Sí | Sí | Gate | No | No | LSP parcial | Perfil §4 | OUTSIDE_V1 | `AE-BACKEND-VECTOR`; advanced algebra AST-only |
| T25 | `Matrix<int/double>` core con shape local | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Perfil §4 | SUPPORTED | LLVM matrix examples; parity tests |
| T26 | Matrix iteration/ABI avanzada/álgebra avanzada | Sí | Sí | Sí | Gate/subset | No estable | No | LSP parcial | Perfil §4 | OUTSIDE_V1 | `AE-BACKEND-MATRIX`; `basic_operations.ae` experimental |
| T27 | `complex` y literal `im` | Sí | Sí | Sí | Nominal | Nominal | Gate | LSP/IJ | Frontend annex | OUTSIDE_V1 | `AE-BACKEND-PRIMITIVE_TYPES`; sin ABI/native ops |
| T28 | Unions y genéricos definidos por usuario | No | No | No | No | No | Gate/no | LSP parcial | Fuera | OUTSIDE_V1 | `AE-BACKEND-GENERICS`; privileged collections no implican generics |
| T29 | Tipos bootstrap Parse/File Result y ALPT1 structs | Sí | Sí | Sí | Sí | Sí | Sí | LSP parcial | Spec §4.4/13 | SUPPORTED | parsing/file/persistence tests; expense tracker |

### 4.3 Expresiones y operadores

| ID | Feature | Parser | Typechecker | AST | IR | SSA | Native | Tooling | Docs | Estado v1 | Implementación / tests / ejemplos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E01 | Literales int/double/bool/string | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §2 | SUPPORTED | lexer/parser; parity scalars/strings |
| E02 | Literal imaginario/complex | Sí | Sí | Sí | Nominal | Nominal | Gate | LSP/IJ | Spec §2 | OUTSIDE_V1 | mismo gate que T27 |
| E03 | Aritmética int/double `+ - * / %` aplicable | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §6 | SUPPORTED | numeric/modulo/safety tests |
| E04 | Promoción segura y aritmética mixta int→double | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §6 | SUPPORTED | `test_numeric_backend_parity.py`; NR examples |
| E05 | Potencia `^`, incluida checked int | Sí | Sí | Sí | Sí | Sí | Sí | IJ operator | Spec §6 | SUPPORTED | numeric parity; FormulaNumerosPrimos |
| E06 | División, módulo, NaN, infinity y signed zero | Sí | Sí | Sí | Sí | Sí | Sí | — | Spec §6/10 | SUPPORTED | differential scalars/panics |
| E07 | Comparaciones ordenadas | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §6 | SUPPORTED | double/int comparison examples |
| E08 | `&&`, `||`, `!` con short-circuit | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §6 | SUPPORTED | logical short-circuit tests |
| E09 | Igualdad scalar/string/enum | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §9 | SUPPORTED | equality/string/enum tests |
| E10 | Igualdad estructural struct/Array/List soportado | Sí | Sí | Sí | Sí | Sí | Sí | LSP parcial | Spec §9 | SUPPORTED | Eq contract/structural equality tests |
| E11 | Cast explícito e identidad `int↔double` | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §6 | SUPPORTED | numeric parity; LLVM cast examples |
| E12 | Casts boolean/string/float/complex generales | Sí | Frontend subset | AST subset | Gate | No | No | LSP parcial | Perfil §4 | OUTSIDE_V1 | `AE-BACKEND-PRIMITIVE_TYPES` |
| E13 | Llamada directa | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §8 | SUPPORTED | call/recursion tests |
| E14 | Llamada indirecta a función top-level sin captura | Sí | Sí | Sí | Sí | Sí | Sí | LSP parcial | Perfil §4 | SUPPORTED | `IRFunctionRef`/`SSACallIndirect`; typed callables |
| E15 | Callable retornado, builtin como valor o método enlazado | Parser/type diag | Rechaza | No | No | No | No | LSP parcial | Fuera | OUTSIDE_V1 | diagnósticos type específicos |
| E16 | Acceso y mutación de campos struct | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §4/9 | SUPPORTED | struct native/value semantics tests |
| E17 | Acceso y mutación de campos class | Sí | Sí | Sí | No | No | Gate | LSP/IJ | Frontend annex | OUTSIDE_V1 | depende de T09 |
| E18 | Métodos struct y `this` | Sí | Sí | Sí | Sí | Sí | Sí | LSP parcial | Spec §4 | SUPPORTED | `test_struct_methods.py` |
| E19 | Métodos class y dispatch interface | Sí | Sí | Sí | No | No | Gate | LSP parcial | Frontend annex | OUTSIDE_V1 | `AE-BACKEND-CLASS_METHODS/INTERFACES` |
| E20 | Constructor struct automático/explícito | Sí | Sí | Sí | Sí | Sí | Sí | LSP/IJ | Spec §4 | SUPPORTED | struct constructor/equality example |
| E21 | Constructor class | Sí | Sí | Sí | No | No | Gate | LSP/IJ | Frontend annex | OUTSIDE_V1 | `AE-BACKEND-CLASS_CONSTRUCTORS` |
| E22 | Indexación Array/List zero-based | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §10 | SUPPORTED | bounds/list/array backend tests |
| E23 | Indexación Vector/Matrix one-based | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §4.3 | SUPPORTED | vector/matrix indexing parity |
| E24 | Slicing semiabierto Array/List y copia | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §10 | SUPPORTED | collection slicing/copy tests |
| E25 | Slicing Vector/Matrix | Sí | Sí | AST | Gate | No | No | Fmt/LSP | Perfil §4 | OUTSIDE_V1 | `AE-BACKEND-VECTOR/MATRIX` |
| E26 | Concatenación string | Sí | Sí | Sí | Sí | Sí | Sí | Fmt/LSP/IJ | Spec §10 | SUPPORTED | ARC concat and byte-length tests |
| E27 | Interpolación string | Sí (`$expr$`) | Sí | Sí | Gate | No | No | Fmt/LSP | Spec dice `${expr}` | OUTSIDE_V1 | `AE-BACKEND-STRINGS`; discrepancia documental F02 |
| E28 | Operadores elementwise y solve `\` avanzados | Sí | AST subset | Sí | Gate/subset | No estable | No | IJ operator | v0/design | OUTSIDE_V1 | advanced LinearAlgebra; ejemplos experimentales |
| E29 | Transposición `'` avanzada | Sí | AST subset | Sí | Gate/subset | No estable | No | IJ corregido | v0/design | OUTSIDE_V1 | fuera del core Vector/Matrix native congelado |

### 4.4 Runtime y biblioteca visible

| ID | Feature | Parser | Typechecker | AST | IR | SSA | Native | Tooling | Docs | Estado v1 | Implementación / tests / ejemplos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | `print`/`println` de layouts soportados | Sí | Sí | Sí | Sí | Sí | Sí | completion/LSP | Spec §10 | SUPPORTED | printer/runtime; differential corpus |
| R02 | Print de layouts no representables | Sí | Sí | AST | Gate | No | No | LSP parcial | Perfil §4 | OUTSIDE_V1 | gate inspecciona layout transitivo |
| R03 | `input` tipado | Sí | Sí | Sí | No | No | Gate | completion/LSP | Frontend annex | OUTSIDE_V1 | `AE-BACKEND-INPUT`; interactive examples |
| R04 | `System.args()` y forwarding `--` | Sí | Sí | Sí | Sí | Sí | Sí Linux | CLI/LSP | Spec §13 | SUPPORTED | arguments parity and CLI tests |
| R05 | Matemática scalar consolidada | Sí | Sí | Sí | Sí | Sí | Sí | completion/LSP | Perfil §4 | SUPPORTED | sin/cos/tan/exp/ln/log/sqrt/abs/floor/ceil/pi |
| R06 | `Math.factorial` y `Math.mod` | Sí | Sí | Sí | Sí | Sí | Sí | completion/LSP | Perfil §4 | SUPPORTED | scalar math native tests |
| R07 | Álgebra lineal avanzada (solve/eig/SVD/LU/...) | Sí | Sí | Sí host | Gate | No | No | completion parcial | Design audits | OUTSIDE_V1 | NumPy/SciPy AST; no ABI native estable |
| R08 | `byteLength`, `trim`, `split`, parseInt/parseDouble | Sí | Sí | Sí | Sí | Sí | Sí | completion/LSP | Spec §10/13 | SUPPORTED | string parsing/split/trim tests |
| R09 | Formatting/conversión string genérica | Sí parcial | AST parcial | Sí parcial | Gate | No | No | LSP parcial | No congelado | OUTSIDE_V1 | no contrato format universal native |
| R10 | API Array/List copy/search/mutation/sort/reverse | Sí | Sí | Sí | Sí | Sí | Sí | completion/LSP | Spec §10 | SUPPORTED | collection subsystem tests/examples |
| R11 | Archivos de texto UTF-8 read/write/append/atomic | Sí | Sí | Sí | Sí | Sí | Sí Linux | completion/LSP | Spec §13 | SUPPORTED | file corpus, text IO tests |
| R12 | IO binario, streams, dirs, locks, procesos | No | No | No general | No | No | No | No | Fuera | OUTSIDE_V1 | no lenguaje visible implementado |
| R13 | Persistencia ALPT1 del Expense Tracker | Sí | Sí | Sí | Sí | Sí | Sí Linux | ejemplo/docs | Design | SUPPORTED | codec explícito, load/save/atomic dogfood |
| R14 | Persistencia/bases de datos genérica | No | No | No | No | No | No | No | Fuera | OUTSIDE_V1 | ALPT1 no implica ORM/DB/serialization general |
| R15 | Plotting | Sí builtin | Sí | Sí host | No | No | Gate | completion/LSP | Experimental | OUTSIDE_V1 | Plots y ejemplos científicos AST-only |
| R16 | Panics checked: overflow/div0/bounds/step zero | Sí | Sí | Sí | Sí | Sí | Sí | CLI diag | Spec §11 | SUPPORTED | safety tests and panic differential corpus |
| R17 | `throw`/`try`/`catch` | Sí | Sí | Sí | No | No | Gate | Fmt/LSP/IJ | Frontend annex | OUTSIDE_V1 | `AE-BACKEND-ERROR_HANDLING` |
| R18 | GC | — | — | Host Python | No | No | No | — | Fuera | OUTSIDE_V1 | no implementar en esta tarea/v1 |
| R19 | ARC/lifecycle string, Array y List | — | Sí tipos | Host + hooks | Sí | Sí | Sí | — | Lifecycle docs | SUPPORTED | retain/release/destroy verificados; RC tests |
| R20 | Ownership/cleanup de class | — | Frontend | Host refs | No | No | No | — | Abierto | OUTSIDE_V1 | no layout, ARC ni ABI class |
| R21 | Cleanup normal de recursos soportados | — | — | Host | Sí | Sí | Sí | — | Lifecycle docs | SUPPORTED | lifecycle expansion/verifier tests |
| R22 | Unwind/cleanup durante panic o excepción | — | — | Host exceptions | No | No | Abort | — | Perfil | OUTSIDE_V1 | panic native abortivo; no unwind |
| R23 | NaN/infinity/signed zero y formato público | Sí | Sí | Sí | Sí | Sí | Sí | CLI | Spec §10 | SUPPORTED | differential scalar corpus O0/O1/O2 |
| R24 | Recursion/stack overflow como panic controlado | Sí | Sí | Recursión host | No guard | No guard | Stack host | — | No contrato | OUTSIDE_V1 | recursión funciona; overflow de stack no está controlado |

### 4.5 Pipeline, CLI y tooling

| ID | Feature | Parser | Typechecker | AST | IR | SSA | Native | Tooling | Docs | Estado v1 | Implementación / tests / ejemplos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B01 | Native como backend por defecto | — | Sí | — | Sí | Sí | Sí | CLI | Spec/Profile | SUPPORTED | `cli.py`; CLI/release contract tests |
| B02 | AST como referencia auxiliar/REPL | Sí | Sí | Sí | — | — | — | CLI/REPL | Este audit | SUPPORTED | `session.py`; REPL tests; no amplía v1 |
| B03 | IR interpreter interno | — | — | — | Sí | — | — | `--backend=ir` experimental | Este audit | SUPPORTED | `ir/interpreter.py`; IR parity tests |
| B04 | IR y SSA verifiers obligatorios en native | — | — | — | Sí | Sí | Sí | emit tools | Compiler docs | SUPPORTED | verifier tests; LLVMBuilder pipeline |
| B05 | Optimización O0/O1 con verify-after-pass | — | — | — | Sí | Sí | Sí | emit/CI | Compiler docs | SUPPORTED | optimizer and SCCP tests |
| B06 | O2 distinto de O1 y política pública uniforme | — | — | — | Alias O1 | Alias O1 | Alias O1 | CLI sólo emit-ir | Perfil lo declara | OUTSIDE_V1 | no prometer fuerza distinta en 1.0 |
| B07 | Selección explícita `llvm|ast|ir` | — | — | — | — | — | — | CLI | README/spec | SUPPORTED | `test_aether_cli.py` |
| B08 | Ausencia de fallback silencioso native→AST | — | — | — | — | — | Sí | CLI | Spec §1 | SUPPORTED | errores devuelven 1; backend cambia sólo por flag |
| B09 | Formatter de sintaxis estable | Sí | — | — | — | — | — | formatter/LSP | Spec | SUPPORTED | `test_source_formatter.py`; headers parentizados |
| B10 | LSP diagnostics lexer/parser/typechecker | Sí | Sí | — | — | — | — | LSP | README | SUPPORTED | `test_aether_lsp_server.py`; capabilities no son lint native por defecto |
| B11 | IntelliJ lexer/highlighter fiel a strings/apostrophe | Léxico espejo | — | — | — | — | — | IntelliJ | Plugin README | SUPPORTED | corrección rc.2 + Gradle regression |
| B12 | Documentación canónica coherente y sin estados históricos activos | — | — | — | — | — | — | Docs | Contradicciones | BROKEN | spec interpolation, IR design backend, README/tests v0; hallazgo F02 |
| B13 | Catálogo de ejemplos totalmente alineado al perfil declarado | Sí/No | Sí/No | Mixto | Mixto | Mixto | Mixto | README/manifest | README inexacto | BROKEN | 78 native, 21 AST-only, 4 no typecheck; hallazgo F01 |
| B14 | Packaging/ejecución native Windows/macOS | — | — | — | — | — | No validado | release tooling | Perfil Linux | OUTSIDE_V1 | soporte declarado sólo Linux x86_64 + clang |
| B15 | `long`, do-while, match, lambdas, closures | No | No | No | No | No | No | keywords parciales/no | Roadmap | OUTSIDE_V1 | explícitamente post-1.0 |

## 5. Diagnóstico requerido para lo que queda fuera

| Familia | Diagnóstico esperado | Momento |
| --- | --- | --- |
| `float`, `complex`, nullable, tuples | `AE-BACKEND-PRIMITIVE_TYPES` con tipo/forma concreta | Después de typecheck, antes de IR |
| Classes/constructors/methods | `AE-BACKEND-CLASSES`, `CLASS_CONSTRUCTORS` o `CLASS_METHODS` | Antes de IR |
| Interfaces | `AE-BACKEND-INTERFACES` | Antes de IR |
| Input | `AE-BACKEND-INPUT` | Antes de IR |
| Exceptions | `AE-BACKEND-ERROR_HANDLING` | Antes de IR |
| Interpolación | `AE-BACKEND-STRINGS`, detalle `interpolated string` | Antes de IR |
| Rango almacenado | `AE-BACKEND-FOR_IN`, detalle `iteration over Range<int>` | Antes de IR |
| Layout de colección no soportado | `AE-BACKEND-AGGREGATE_COLLECTION_ELEMENTS` o capability del tipo | Antes de IR |
| Shape Vector/Matrix no representable | `AE-BACKEND-VECTOR`/`MATRIX` con contexto ABI | Antes de IR |
| Inicialización de módulo importado | `AE-BACKEND-MODULES` | Antes de IR |
| Sintaxis no existente (`-=`, lambda, match, etc.) | `AetherSyntaxError` | Parser |

Los errores internos verdaderos no se convierten en capability errors. Los
verifiers producen categoría `ir`/`ssa`, LLVM produce `llvm`, y el runtime
produce panic público. La taxonomía de nombres todavía no coincide literalmente
con `verification`/`internal compiler error`; se registra como F05.

## 6. Superficies sospechosas: decisión y divergencia

| Superficie | Decisión | Evidencia y divergencia |
| --- | --- | --- |
| `float` | **OUTSIDE_V1 / reservar** | Es distinto en frontend/AST, pero no tiene ABI native estable. Todo uso se gatea. No eliminar la palabra hasta decidir compatibilidad post-1.0. |
| `complex` | **OUTSIDE_V1** | Literal `im`, casts y operaciones heredadas viven en AST. No hay representación native estable ni ejemplos oficiales v1. |
| Classes | **OUTSIDE_V1** | Construcción, aliasing, const path, visibilidad y métodos tienen tests AST. Faltan layout, ABI, ownership, cleanup, igualdad y lowering completos. |
| Interfaces | **OUTSIDE_V1** | Conformidad/dispatch AST; no vtable/fat pointer ni dispatch IR/SSA/native para struct o class. |
| Function values | **SUPPORTED sólo para funciones top-level sin captura y firma exacta** | `IRFunctionRef`, indirect call y SSA phi existen. Retornos callable, builtins como valor, bound methods, lambdas y closures quedan fuera. Una función abreviada es declaración, no function value. |
| Vector | **SUPPORTED core local int/double** | Literales, shape, index, set, add/sub/scale/dot y combinaciones registradas llegan a native. APIs avanzadas y pérdida de shape en ABI quedan fuera. |
| Matrix | **SUPPORTED core local int/double** | Literales, rows/columns, index/set, add/sub/scale/matmul y multiplicaciones registradas llegan a native. Iteración y álgebra host avanzada quedan fuera. |
| Rangos | **SUPPORTED sólo como expresión directa de `for` int** | Inclusivos, pasos positivos/negativos/dinámicos; cero estático es type error y cero dinámico panic. Almacenamiento/parámetros/retornos quedan fuera. |
| Array/List | **SUPPORTED para layouts registrados** | Semántica de referencia, `copy`/slice independientes, bounds, const path, borrowed for-in, RC y Eq. Colecciones anidadas y classes se excluyen. |
| Strings | **SUPPORTED en superficie cerrada** | UTF-8 length-aware, ARC, copy/params/return/fields/collections, concat/Eq/print/trim/split/parsing/files. Interpolación y formatting general quedan fuera; panic abortivo no hace unwind. |

## 7. Hallazgos

### F01 — P1 — El directorio de ejemplos no es todavía un catálogo v1 honesto

**Resolución posterior: CERRADO en R2/B13 (2026-07-18).** Se preserva debajo la
observación original como evidencia histórica; el manifiesto schema 2 y el gate
actual ya no contienen entradas `BROKEN`.

- **Feature/backend:** ejemplos / frontend y native.
- **Reproducción:** ejecutar `tests/aether/test_v1_profile_audit.py` o leer el
  manifiesto.
- **Esperado:** todo ejemplo presentado como oficial v1 es `V1_NATIVE`.
- **Real:** 78/103 son native, 21 son AST-only y 4 fallan en frontend:
  `linear_algebra/primes_advanced.ae`,
  `minimos_cuadrados/MinimosCuadrados.ae`,
  `minimos_cuadrados/interactive.ae` y `pruebaListas.ae`.
- **Archivos/tests:** `examples/README.md`, manifest, profile audit test.
- **Recomendación:** separar físicamente o rotular los experimentales y mover
  los cuatro rotos a migration fixtures o corregirlos con una decisión explícita.

### F02 — P1 — El contrato normativo mezcla lenguaje AST y perfil estable native

- **Feature/backend:** especificación / todos.
- **Reproducción:** comparar `AETHER_LANGUAGE_SPEC_V1.md` §§1, 2.3 y 4 con el
  parser y `AETHER_NATIVE_PROFILE_V1.md`.
- **Esperado:** “Aether 1.0” denota una frontera única y coherente.
- **Real:** la spec declara features AST como lenguaje v1 aunque no sean parte
  del backend estable; además documenta `${expression}` cuando el parser usa
  `$expression$`. `AETHER_IR_DESIGN.md` aún llama AST al backend por defecto.
- **Recomendación:** hacer normativa la decisión de este audit y trasladar la
  superficie AST-only a un anexo experimental no-v1.

### F03 — P2 — Tooling IntelliJ divergía en comillas simples (corregido)

- **Real previo:** `'hola'` era un string para IntelliJ y una secuencia de
  operadores/identificador para el lexer Aether.
- **Corrección:** sólo `"` inicia string; `'` siempre es operador. Se actualizó
  el test Gradle.

### F04 — P2 — UTF-8 inválido filtraba una excepción host (corregido)

- **Real previo:** el CLI, runner LSP e import loader capturaban `OSError` pero
  no `UnicodeDecodeError`.
- **Corrección:** diagnóstico de lectura/import específico, exit 2 para fuente
  raíz y error de lenguaje para import, sin traceback.

### F05 — P2 — Categorías internas no están normalizadas al vocabulario de release

IR/SSA/LLVM usan `kind=ir|ssa|llvm`; el contrato solicitado distingue
`verification` e `internal compiler error`. Los fallos conocidos de capability
sí se gatean temprano, pero falta una envoltura explícita para ICE inesperado
sin ocultarlo como error de usuario.

### F06 — P2 — No hay sanitizer/fuzz/platform gate obligatorio

Hay cobertura de ownership, overflow y bounds, pero no ASan/LSan/UBSan en CI,
fuzzing de parser/verifiers ni matriz Windows/macOS. El perfil Linux limita el
claim, pero este hueco bloquea 1.0 final, no necesariamente un RC interno.

### F07 — P2 — Recursión y allocation failure dependen del host

La recursión correcta funciona, pero stack overflow y fallo de allocation no
son panics Aether controlados. No se observó miscompilación; debe documentarse
como límite y someterse a stress/sanitizers.

### F08 — P2 — Trazabilidad de capability completa sigue siendo manual

`E2E_TESTED_CAPABILITIES` comprueba pertenencia a un conjunto, no un enlace
ejecutable capability→test. La nueva matriz y el manifest mejoran evidencia,
pero no reemplazan un registro generado.

### F09 — P3 — `O2` es alias de `O1`

Está declarado, por lo que no es divergencia silenciosa. No debe venderse como
nivel distinto ni bloquear el perfil semántico.

### F10 — P3 — Documentos históricos activos conservan lenguaje v0/rc.1

`tests/README.md`, `docs/guia_de_uso.md` y auditorías históricas pueden inducir
a error. Deben rotularse como legacy o enlazar la spec v1.

### F11 — P3 — El LSP no publica capability diagnostics native por defecto

Publica syntax/type diagnostics y el run action usa el CLI. Es aceptable para
v1 pequeño, pero una acción “validate native profile” mejoraría feedback.

## 8. Auditoría de robustez

| Riesgo | Estado observado | Prioridad |
| --- | --- | --- |
| Overflow i32, división/módulo por cero, `INT_MIN / -1` | Checked en AST/IR/native, con corpus de panic | Cerrado para v1 |
| Potencia int | Checked; double usa semántica IEEE/libm | Cerrado para v1 |
| Bounds Array/List/Vector/Matrix y slicing | Checks antes de acceso; regresiones P0 históricas presentes | Cerrado para layouts soportados |
| Step de rango cero | Rechazo estático o panic dinámico equivalente | Cerrado |
| Tamaños/capacidades List | Guards de overflow y stress tests | Cerrado en corpus actual |
| ARC/double-free strings y Array/List | Lifecycle explícito + tests; sin sanitizer obligatorio | P2 residual |
| Cleanup en panic | Panic aborta; no unwind | Fuera de v1 |
| Temporales/clang | TemporaryDirectory y errores específicos; clang externo requerido | Aceptable Linux |
| UTF-8 fuente malformada | Corregido en raíz, runner LSP e imports | Cerrado en esta tarea |
| Recursion/stack | Sin guard Aether | P2/F07 |

## 9. Auditoría de especificación y plan de `AETHER_V1_SPEC.md`

La spec v1 ya existe como `AETHER_LANGUAGE_SPEC_V1.md`; no conviene crear una
segunda especificación competidora. Debe evolucionar o renombrarse de manera
atómica con esta estructura:

1. Conformance: Aether v1 estable = perfil native cerrado; AST experimental.
2. Léxico y gramática exacta, generados/probados contra tokens y parser.
3. Entry point, módulos e inicialización excluida.
4. Tipos soportados; anexo no normativo para frontend experimental.
5. Conversiones, promociones y operadores por matriz de tipos.
6. Control de flujo y rangos efímeros.
7. Funciones normales/abreviadas/callables top-level.
8. Structs/enums y semántica de valor.
9. Strings/Array/List y ownership observable.
10. Vector/Matrix core exacto.
11. Builtins, math, argv, texto y persistencia acotada.
12. Panic/diagnostics y códigos de salida.
13. Plataforma/toolchain y no-promesas de ABI.
14. Tabla de exclusiones con `AE-BACKEND-*` esperado.

Cambios obligatorios: corregir interpolación, quitar classes/interfaces/float/
complex/tuples/exceptions del cuerpo normativo estable, declarar rangos sólo
efímeros, congelar el subset Vector/Matrix, enlazar este inventario, rotular v0
como histórico y sincronizar README, LSP, IntelliJ y ejemplos.

## 10. Marcadores y deuda inspeccionada

La búsqueda de `TODO`, `FIXME`, `partial`, `unsupported`, `not implemented`,
`AST-only`, `native-only`, `capability`, `fallback`, `legacy` y `temporary`
confirma que la deuda principal está concentrada en lowerers, builders de SSA,
documentos históricos, benchmark/tooling experimental y features excluidas.
No se usó esa búsqueda como prueba de soporte: cada decisión de esta matriz se
contrastó con gate, lowering, tests o ejecución.
