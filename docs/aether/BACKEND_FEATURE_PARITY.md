# Auditoría completa de paridad de backends

> Clasificación: **Audit**. La matriz conserva evidencia y deuda por etapa; no
> reemplaza [la spec v1](AETHER_LANGUAGE_SPEC_V1.md) ni
> [el perfil native normativo](AETHER_NATIVE_PROFILE_V1.md).

Actualización Fase 5.2 (27-07-2026): nullable es E2E para todo payload con
layout native representable. Parser/typechecker/AST, IR y DTO, verificadores
Python/Rust, intérprete IR, SSA/optimizadores y LLVM/native conservan el mismo
valor `{ i1 has_value, T value }`. `null` es absent canonical; present,
igualdad, print y lifecycle son type-directed y sólo acceden al payload con tag
activo. No hay `ptr null`, boxing ni allocation nullable. El typechecker
mantiene soundness rechazando `T? -> T`; smart casts/flow narrowing siguen
como trabajo futuro.

Reconciliación Fase 5.0 (25-07-2026, revisión `0ff3d3b`): el perfil de
capacidades continúa en la versión 22 y no cambió la frontera de lenguaje
native cerrada el 18-07-2026: las 75 filas `SUPPORTED` de
[`AETHER_V1_PROFILE_AUDIT.md`](AETHER_V1_PROFILE_AUDIT.md) conservan su
clasificación, todo programa admitido conserva camino E2E y las 46 filas
`OUTSIDE_V1` siguen rechazadas antes del lowering. El
trabajo Rust posterior no añadió features de lenguaje: completó el import de
IR v1, el verificador combinado, el protocolo/subprocess, shadow validation,
alineación de IRV-024, packaging operativo y un canary explícito con Rust como
autoridad. La compilación ordinaria sin pipeline inyectado continúa usando
`IRVerifier` Python; el pipeline dual configurado usa Python como autoridad y
Rust como shadow, y sólo el entorno canary invierte esos roles sin fallback.

Actualización perfil 7 (15-07-2026): native completó transporte de handles al
objeto UTF-8, igualdad por contenido, literales/vacío inmortales, ARC oculto,
impresión length-aware y hooks de elementos string/struct para Array/List. Las
filas históricas que describen `char *`, `%s`, `strcmp` o copia trivial son el
snapshot previo a esta actualización. En ese perfil parsing, split/trim, files
y argv continuaban no implementados; parsing numérico se completa en el perfil
15 documentado más abajo.

Actualización perfil 8 (15-07-2026): la Fase 0 de colecciones añadió detección
semántica tipada y diagnósticos previos al lowering para igualdad Array/List,
`Array.copy()`, el antiguo gap de slicing List y búsqueda estructural de structs.
La Fase 1 implementó RC (perfil 9), Fase 2 completó `Array/List.copy()` E2E
(perfil 10) y Fase 3 completó slicing semiabierto E2E (perfil 11). La matriz exhaustiva por backend
está en [`COLLECTION_MIGRATION_BASELINE.md`](COLLECTION_MIGRATION_BASELINE.md).

Actualización perfil 13 (15-07-2026): `Eq(T)` unifica `==`, `!=`, structs,
Array/List y `contains/indexOf`. AST, IR, SSA y LLVM/native comparan contenido
recursivo; interfaces/callables se diagnostican. La fundación IR 5.3A añadió
posteriormente identidad para `ClassRefType`, aún detrás del gate source de
classes.
LLVM reutiliza helpers tipados deterministas y conserva IEEE-754, incluido
`NaN != NaN`.

Actualización perfil 14 (15-07-2026): concat string y `s.byteLength` son E2E
en AST/IR/SSA/LLVM. Concat produce ownership, asigna una sola vez por helper y
conserva efectos de panic/allocation; interpolación y formatting siguen fuera.

Actualización perfil 15 (15-07-2026): `parseInt`/`parseDouble` y los resultados
nominales con `ParseStatus` son E2E en AST/IR/SSA/LLVM, incluidos bytes NUL/UTF-8,
locale C, structs/colecciones y clang O0/O1/O2. NaN/infinito se rechazan y
underflow double sigue IEEE-754.

Actualización perfil 16 (15-07-2026): `string.trim()` es E2E en
AST/IR/SSA/LLVM, recorta exactamente seis whitespace ASCII, conserva NUL,
UTF-8 y espacios no ASCII, y mantiene fast paths/ownership en O0/O1/O2. Parsing
sigue estricto y sólo acepta whitespace tras un `trim()` explícito.

Actualización perfil 17 (15-07-2026): `System.args()` y el forwarding posterior
a `--` son E2E en AST/IR/SSA/LLVM/native POSIX. El wrapper nativo valida todo
`argv` como UTF-8 antes del `main()` Aether interno; cada call produce un
`Array<string>` owned e independiente. Windows/UTF-16 queda pendiente.

Actualización perfil 18 (16-07-2026): `io.readText`, `io.writeText` e
`io.appendText` son E2E en AST y native Linux/POSIX. Preservan NUL/newlines,
validan UTF-8 al leer, normalizan errores y sobreviven O0/O1/O2. Windows y
otras fronteras POSIX native permanecen diagnosticadas explícitamente.

Actualización perfil 21 (16-07-2026): `io.writeTextAtomic` publica mediante
temporal seguro en el mismo directorio, `fsync` de archivo, rename y `fsync` de
directorio. AST y native Linux preservan bytes/NUL y limpian fallos normales
previos al rename; `saveLedger` ya la usa. No hay locking, metadata cloning,
rollback posterior al rename ni soporte Windows simulado.

Actualización perfil 19 (16-07-2026): `string.split(string)` es E2E en
AST/IR/SSA/LLVM. Hace matching exacto por bytes, no solapado, conserva campos
vacíos y NUL/UTF-8, rechaza separator vacío y devuelve un `Array<string>` con
fragments owned. La call conserva efectos de lectura/allocation/panic y
sobrevive clang O0/O1/O2.

Actualización perfil 20 (16-07-2026): el codec manual ALPT1 de
`Transaction`/`List<Transaction>` es E2E en AST, IR, SSA y LLVM/native. El
cursor consume bytes UTF-8 exactos, el encoder concatena fragmentos en una
asignación final, los doubles usan `%.17g` bajo locale C y el parser staged
rechaza corrupción sin publicar resultados parciales. `loadLedger`/`saveLedger`
envuelven `io.readText` y, desde perfil 21, `io.writeTextAtomic`.

Actualización perfil 22 (16-07-2026): el capability gate native pasa a ser la
frontera exhaustiva previa al lowering. Los tipos chequeados, conversions,
bindings, firmas, operadores, builtins, layouts y límites de plataforma
delimitan el subset; `float` queda excluido y `for` pasa a `PARTIAL` por el caso
de paso cero. Las formas fuera del subset terminan en diagnósticos
`AE-BACKEND-*` con ubicación, nunca en lowering/verifier/LLVM/clang. Los módulos
sin `main` pueden emitirse como LLVM de librería; sólo `build` exige entry point.
El corpus aceptado por native compila con clang en O0/O1/O2.

Cierre de paridad observable P0.2 sobre perfil 22 (16-07-2026): un runner
diferencial compara stdout/stderr bytes, exit code y archivos finales entre AST
y clang O0/O1/O2. `print/println(double)` usa un formatter público común de 15
dígitos, conserva `.0`/signed zero y normaliza no finitos; ALPT1 conserva
`%.17g` como codec canónico separado. Strings en agregados mantienen quotes y
escapes length-aware. Panics públicos del corpus coinciden en mensaje/canal/code.
Catorce programas y 42 comparaciones quedan integrados al gate local de CI.
El corpus incluye ahora control de flujo, recursión, llamadas adelantadas,
structs, métodos, colecciones, math scalar e imports de módulos, además de los
casos anteriores de strings, archivos, argumentos y panics.

Última revisión: 25 de julio de 2026, incluyendo el cierre del perfil v1 y la
reconciliación del verificador Initial IR Python/Rust. Este documento reemplaza como
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
lexer -> parser -> typechecker -> native capability gate
      -> EntryPointNormalizer -> IR lowering
      -> Initial IR verifier -> GeneralSSABuilder -> SSA verifier
      -> SSAOptimizerPipeline -> LLVM printer/runtime -> clang
```

No existe intérprete SSA. AST e IR interpreter son backends alternativos. La
CLI usa LLVM por defecto; REPL e integración IntelliJ ejecutan AST.

La autoridad Initial IR de producción sigue siendo Python. `IRBackend()` sin
configuración adicional invoca sólo `IRVerifier`. La infraestructura dual es
opt-in e inyectada: su configuración normal ejecuta Python-authority/Rust-shadow
y su canary explícito ejecuta Rust-authority/Python-shadow. Ambos verificadores
cubren el IR v1 transportable; el selector Rust no interviene en SSA, LLVM ni
en el capability gate.

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
de callables. Strings/native sigue `PARTIAL` porque interpolación, formatting y
otras APIs de texto quedan fuera; transporte, igualdad, concat, `byteLength` y
`trim` son E2E. El detector consulta tipos de operandos registrados por el
typechecker.

La decisión aprobada para reemplazar en fases el transporte `char*` por un
modelo con UTF-8, longitud y ownership explícitos está en
[`STRING_RUNTIME_DESIGN.md`](STRING_RUNTIME_DESIGN.md), y el contrato de
lifecycle en
[`VALUE_LIFECYCLE_DESIGN.md`](../compiler/VALUE_LIFECYCLE_DESIGN.md). La
representación y lifecycle ya están activos en esta matriz.

## Tipos, declaraciones y operadores

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `int` i32 | C | C | C | C | C | C | C | C | C | C | C | C | C | paridad E2E | C | Completo | Semántica checked i32 y límites de literal están fijados por la spec v1. |
| `double` | C | C | C | C | C | C | C | C | C | C | C | C | C | E2E | C | Completo | División sigue IEEE-754, incluidos inf/NaN. |
| `boolean` | C | C | C | C | C | C | C | C | C | C | C | C | C | E2E | C | Completo | `bool` no es spelling público; se usa `boolean`. |
| `float` | C | C | C | C por coerción | C nominal | P | P | P | P | P | P | N: gate temprano | N | frontend+gate | P | Solo AST | El perfil 22 lo excluye explícitamente del subset native estable. |
| `complex` / literal `im` | C | C | C | C | C nominal | N desde fuente | P nominal | N | P nominal | P nominal | N | N | AST Python | AST | C v0 | Solo AST | Ya existe como primitivo experimental, en tensión con el diseño futuro de stdlib. |
| `null` y `T?` | C | C | C assignability/Eq, sin narrowing | C tagged | C `NullableType` + null const/cast/compare | C params/locals/returns/collections | C incluido nested/void inválidos | C tagged | C casts/phis | C | C conservador | C named `{i1,T}` | sin runtime nuevo; ARC condicional | parser/type/IR/SSA/ABI/E2E | C v0 + diseño native | Completo para `T` representable | Sin smart casts; `T? -> T` continúa diagnosticado. |
| Variables locales tipadas mutables | C | C | C | C | C | C | C | C | C | C | C | C | — | E2E | C | Completo | Requieren inicializador. |
| `const` local | C | C | C binding+paths | C | metadata AST para borrow | C, restricciones resueltas antes de IR | C | C | C | C | C | C | — | frontend+backend | C | Completo | Array/List propagan read-only por value/nested paths, se detienen en class y no congelan aliases mutables. |
| Inferencia `x = expr` | C | C | C | C | N para global implícito | N | N | N | N | N | N | N | AST | frontend | C | Solo AST | El compilador exige locales que ya estén declarados. |
| Alias de tipo | C | C | C | C | se resuelve | P: top-level alias aceptado solo como metadata | C | C | C | C | C | C para usos soportados, incluidos aliases importados | — | AST+struct backend | C | Parcial | El alias conserva identidad semántica separada del nombre interno. |
| Operadores `+ - * /` escalares | C | C | C | C | C | C int/double | C | C | C | C | C checked | C int/double | C | E2E+safety | P | Parcial | `float`, `complex`, string y agregados amplían la superficie AST. |
| Overflow entero y negación mínima | — | — | permite runtime | C: panic i32 | C `may_trap` | C | C | C | C | C | C preserva traps | C intrinsics checked | C | E2E AST/IR/native | C | Completo | Contrato implementado y normativo en v1. |
| División por cero | — | — | permite runtime | C | C | C | C | C | C | C | C | C | C | E2E | C | Completo | Int hace panic; double usa IEEE-754 en los tres backends. |
| `%` truncante | C | C | C | C int/double | C `rem` | C, con promoción explícita | C homogéneo | C int/double | C | C | C | C `srem`/`frem` | P | AST/IR/native | C | Completo para int/double | Los operandos mixtos se homogeneizan en IR; divisor cero int conserva panic. |
| Potencia `^` | C | C | C tabla int/double | C checked/IEEE | C `pow` | C, con casts explícitos | C homogéneo | C | C | C | C folding checked/SCCP/GCP | C helper i32/libm `pow` | helper checked + libm | E2E+límites+IEEE | C | Completo para int/double | `int^int` exige exponente no negativo y overflow i32 checked; cualquier double produce double. |
| `Math.mod` floor-mod | llamada normal | C | C | C | C call builtin | C | C | C | C | C | C checked | C helper tipado | runtime mínimo | AST/IR/native | C | Completo int/double | Es builtin de namespace, no operador. |
| Comparaciones ordenadas | C | C | C | C | C | C int/double | C | C | C | C | C | C int/double | — | E2E | C | Parcial | Otros numéricos/agregados tienen cobertura distinta. |
| Igualdad escalar | C | C | C | C | C | C | C | C | C | C | C | C Eq tipado | `aether_string_equal`/helpers Eq | amplia | C | Completa para tipos Eq | Primitivas, string, enums, structs y Array/List; `ClassRefType` interno usa identidad; interfaces/callables siguen sin Eq. |
| Igualdad agregada | C | C | C | C | C subset tipado | C Struct/Array/List/Vector/Matrix representables | C subset | C subset | C subset | C subset | C preserva lecturas | C subset | helpers Eq tipados | amplia por tipo | C para perfil v1 | Parcial | `Eq(T)` es E2E para layouts admitidos, incluidos Array/List recursivos y referencias de clase por identidad; interfaces, callables y layouts rechazados siguen fuera. |
| `&&` / <code>&#124;&#124;</code> short-circuit | C | C | C boolean | C | CFG | C por branches/merge | C | C | C con phi | C | C SCCP | C | — | E2E | C | Completo | La spec v1 ya fija short-circuit; `docs/compiler/FEATURE_MATRIX.md` conserva el snapshot AST-only obsoleto. |
| `!` prefijo | C | C | C boolean | C | C | C | C | C | C | C | C | C `xor` | — | E2E | C | Completo | No existe factorial postfix. |
| Casts explícitos | C | C | C amplio | C amplio | P | C int↔double e identidad | C subset + identidad | C subset + identidad | C subset | C subset + identidad | C elimina identidad | C int↔double e identidad; resto rechazado por gate | P | frontend+par+gate | C | Parcial | `string`, `boolean`, `float` y `complex` quedan fuera del subset native declarado. |

## Funciones y control de flujo

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Funciones tipadas y parámetros | C | C | C | C | C | C para tipos backend | C | C | C | C | C conservador | C | stack nativo | E2E | C | Parcial | La fila es parcial por tipos de parámetros que solo existen en AST. |
| Funciones `void` | C | C | C | C | C | C | C | C | C | C | C | C | — | E2E | C | Completo | Calls void solo como statement. |
| Funciones como parámetros/valores | C `R(P...)` | C `FunctionType` | C exacto, símbolos/imports | C valor explícito sin entorno | C `FunctionType`/`function_ref`/`call_indirect` | C local e imports | C firma/símbolo/void | C | C refs/calls/phi | C tipos/dominancia | C conservador, calls con efectos | C `ptr` y call indirecta | sin heap/environment | E2E AST/IR/SSA/clang | C | Parcial | Solo funciones block top-level de usuario sin captura; no closures, lambdas, bound methods, builtins/expresión como valor ni retorno callable. |
| Funciones abreviadas `f(double x)=...` | C desazucarado | `FunctionDeclaration` + `return` | C retorno inferido o explícito | C | sin cambio | C como función normal | C | C | C | C | C | C subset de tipos | normal | E2E frontend/backend | C | Completo para firmas backend | No introduce lambdas ni un nodo/IR nuevo. |
| Calls directas y recursión | C | C | C; firmas multifase | C | C | C | C | C | C | C | C conservador | C | — | E2E directa/mutua | C | Completo | La spec v1 y los tests cubren calls adelantadas, recursión y recursión mutua. |
| `return` | C | C | C paths/tipo | C | C | C | C | C | C | C | C | C | exit `main` | E2E | C | Completo | `main` retorna int y no recibe parámetros. |
| `if` / `else` | C | C | C boolean | C | CFG | C | C | C | C/phi | C | C | C | — | E2E | C | Completo | Incluye ramas con retorno. |
| `while` | C | C | C boolean | C | CFG | C | C | C | C loop phi | C | C | C | — | E2E | C | Completo | Control anidado cubierto. |
| `for` sobre rango | C | C | C | C | CFG | C pasos +/-/dinámicos | C | C | C | C | C | C | — | E2E | C | Completo | Rango es inclusivo según spec actual. |
| `for-in` sobre colección | C | C | C borrow read-only | C amplio, borrow no-owning | CFG/`borrow_element`/length | C Array/List; Vector previo | C scope/mutación/escape | C subset | C metadata borrow | C scope/phi/mutación | C preserva borrow | C load sin retain | bounds helpers | E2E Array/List/struct/nesting | C | Parcial | Array/List tienen semántica borrowed completa; Matrix y otras colecciones no comparten iterable general. |
| `break` / `continue` | C | C | C solo loop | C | jumps | C | C | C | C | C | C | C | — | E2E nested | C | Completo | Se bajan a targets del loop activo. |
| Entry point y top-level script | C | C | C | C | función `main` | C tras normalización | C | C | C | C | C | C | exit code | E2E | C | Completo en raíz | Solo `main` del módulo raíz conserva ABI; un `main` importado se manglea. Statements top-level importados aún requieren inicialización. |
| Tuples y destructuring | C | C | C | C | N | N | N | N | N | N | N | N | AST | AST | C | Solo AST | Incluye retornos múltiples en AST. |

## Strings, IO y proceso

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| String literal/variable/arg/return | C | C | C | C | C handle | C | C | C | C | C | C lifecycle | C | `AetherStringObject` ARC | E2E | C | Completo | UTF-8 explícito, vacío/literales inmortales y dinámicos owned. |
| Concat e igualdad string | C | C | C tipos exactos | C bytes | C binary tipado / compare | C | C efectos/tipos | C `StringValue` | C | C | C effect-aware | C | `aether_string_concat`/`equal` | E2E+O0/O1/O2 | C | Completo | Solo `string + string`; sin conversiones implícitas. |
| `string.byteLength` | C property | C | C `int` | C O(1) | call tipada | C | C | C | C | C | C | C checked i64→i32 | header explícito | E2E UTF-8/NUL | C | Completo | Cuenta bytes, no code points ni graphemes. |
| `string.trim()` | C método | C | C read-only, cero args, owned | C bytes | call builtin tipada+loc | C | C firma/efectos | C `StringValue` | C | C | C effect-aware | C | `aether_string_trim` | E2E+O0/O1/O2 | C | Completo | Sólo whitespace ASCII `20 09 0A 0D 0C 0B`; conserva NUL/UTF-8/no-ASCII. |
| `string.split(string)` | C método | C | C read-only, un arg, `Array<string>` owned | C bytes | call builtin tipada+loc | C | C firma/efectos | C `StringValue`+Array | C | C | C effect-aware | C lifecycle Array/string | `aether_string_split` dos pasadas | E2E+O0/O1/O2 | C | Completo | Matching exacto no solapado; conserva vacíos/NUL/UTF-8; separator vacío hace panic. |
| `parseInt` / `parseDouble` | C llamada | C | C resultados nominales | C bytes compartidos | C calls tipadas+loc | C | C firma/layout | C | C | C | C effect-aware | C ABI struct | parser i32 + DFA/`strtod_l` locale C | E2E+O0/O1/O2 | C | Completo | Sin trim/locale implícito; defaults 0 no son sentinels; NaN/infinito rechazados. |
| Interpolación/formatting string | C | C | C | C | N | N | N | N | N | N | N | N | N | AST | C | Solo AST | No se habilitó conversión ni formatting native. |
| `print` / `println` escalares | llamada | C | C variádico | C | C `IRPrint` | C | C | C | C | C | C efecto | C | helper público double + IO length-aware | diferencial O0/O1/O2 | C | Completo | Double público: 15 dígitos, `.0` visible, signed zero y `NaN`/`Infinity`; no reutiliza el codec ALPT1. |
| Print Array/List | llamada | C | C | C | C subset tipado | C subset | C | C | C | C | C | C subset | helpers tipados | diferencial+E2E | P | Parcial | Strings se quotean/escapan igual en AST/IR/native; layouts fuera del subset siguen rechazados por profile 22. |
| Print Struct/Vector/Matrix | llamada | C | C | C | C subset | C subset | C | C | C | C | C | C subset | helpers | E2E | P | Parcial | Shape/tipos de campos limitan el subconjunto struct. |
| `input` tipado | C nodo dedicado | C | C por contexto | C | N | N | N | N | N | N | N | N | AST stdin | AST | C | Solo AST | No existe input native. |
| Argumentos del proceso (`System.args`) | — | C call | C `Array<string>`/arity | C inyectable | C builtin tipado | C | C | C | C | C | C efectos alloc/read/panic | C POSIX | contexto + wrapper `argc/argv` | E2E | C | Completo POSIX | `main` sigue sin parámetros; snapshot nuevo O(argc), UTF-8 estricto y Windows UTF-16 pendiente. |
| Archivos texto (`io.readText`/`writeText`/`writeTextAtomic`/`appendText`) | — | C calls | C firmas/resultados nominales | C binario explícito | C builtin+loc | C | C firma/layout | C bytes | C | C | C efectos IO/alloc | C Linux | helpers incremental/exact-write/atomic durable | E2E+faults+O0/O1/O2 | C | Completo AST, parcial native | Atomic usa temp+fsync+rename+dir-fsync; UTF-8/NUL exactos; sin locking/streams/binarios. |

## Módulos y tipos definidos por usuario

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Packages, módulos e imports | C | C | C aliases/selectivos/ciclos | C carga/cache | C programa chequeado; IR combinado | C declaraciones soportadas | C | C | C | C | C | C subset | sin runtime nuevo | unit+IR+native E2E | C subset | Parcial | Un package mapea a un archivo. Faltan globals/constantes y statements top-level importados, diagnosticados antes del lowering. |
| Visibilidad top-level | C | C | C en imports | C | identidad/export metadata | C consume referencias resueltas | C | C | C | C | C | C subset | — | semantic+native | C | Parcial native | Privacidad se valida semánticamente; dentro del mismo archivo no restringe acceso. |
| Struct fields/constructores | C | C | C nominal | C | C definiciones/new/get/set | C subset | C | C | C | C | C | C subset | helpers print/equality | E2E dedicado | C para perfil v1 | Parcial | El subset v1 de layouts acíclicos representables es E2E; fields fuera del layout/lifecycle admitido se rechazan por el gate. |
| Métodos de struct y `this` | C | C | C mutabilidad | C | C funciones + method result | C | C | C | C | C | C | C | — | E2E | P | Completo | Para tipos de firma soportados por backend. |
| Semántica por valor de struct | — | C | C const | C copia | C reconstrucción | C | C | C | C | C | C | C by-value | — | E2E copia/arg/return | C | Completo | Campos reference mantienen copia shallow deliberada. |
| Igualdad/print de struct | C | C | C comparabilidad | C | C recursivo subset | C | C | C | C | C | C | C subset | helpers | E2E | P | Parcial | Enum y nullable representable ya están soportados como fields; Vector/Matrix conservan límites. |
| Classes por referencia | C | C | C visibilidad/alias/definite init | C | C new/get/set | C fields/constructores | C nominal/fields | C aliasing | C refs/phis | C | C preserva writes/ARC | C payload/header/ARC | descriptor destroy | AST+IR+SSA+clang O0/O1/O2 | C | State native | 5.3B completa fields, constructors y containment; ciclos ARC no se recolectan. |
| Constructores/`this` de class | C | C | C | C | C | C | C | C | C | C | C | C | ARC | E2E | C | Completo subset | `this` sólo dentro del constructor; parámetros borrowed, resultado owned. |
| Métodos de class | C | C | C | C | N | N | N | N | N | N | N | N | AST | amplia AST | C | Solo AST | Phase 5.3C; diagnóstico `AE-BACKEND-CLASS_METHODS`. |
| Native Interface ABI | C | C | C conformidad | C class→interface | C tipo/instrucción/witness DTO | C valor/phi | C | C preserva carrier+witness | C | C `{ptr,ptr}`/tablas | C carrier-only | C Python/Rust | AST + construcción native | ABI/ownership/DTO/LLVM | C | Completa 5.4A | Dispatch y boxing separados. |
| Interface dispatch/boxing | C | C | C | C AST | diagnóstico 5.4B/5.4C | N | N | N | N | slots null | N | rechaza | AST | negativos | C | Solo AST | No calls, virtual dispatch ni boxing native. |
| Enums sin payload | C | C | C identidad módulo/declaración | C valor nominal+discriminante | C `enum Name` + constante nominal | C | C miembros/discriminantes/tipos | C | C phis/tipos | C nominal/dominancia | C folding preserva tipo | C `i32` ABI interno | metadata de impresión | AST+IR+SSA+clang O0/O1/O2 | C | Completo | Sin payload, ADT, casts implícitos, bit flags ni pattern matching nuevo. Imports, aliases, homónimos, structs, arrays/list compatibles y callables funcionan. |
| Genéricos de usuario | P: se reconocen para rechazo | P | N | N | N | N | N | N | N | N | N | N | N | negativos | C como no soportado | No implementado | Array/List/Vector/Matrix son genéricos privilegiados, no evidencia de generics generales. |

## Array, List, Vector y Matrix

| Feature | Lexer/parser | AST | Typechecker | AST interpreter | IR model | IR lowering | IR verifier | IR interpreter | SSA | SSA verifier | Optimizers | LLVM/native | Runtime | Tests | Spec/docs | Estado global | Observaciones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Array<T>` literal | C target-typed | C | C | C | C | C | C | C | C | C | C allocation | C layout tipado incluido Struct soportado | C RC y destroy final | E2E escalares/enum/Struct | C | Parcial | Structs acíclicos sized, nested y strings usan TypeLayout y hooks; otros layouts se diagnostican temprano. |
| Bounds checks Array | — | — | índice int | C | efectos `may_trap` | C | C | C | C | C | C preserva | C | C | safety E2E | C | Completo | `FEATURE_MATRIX.md` y el cuerpo histórico de `ARRAY_SUBSYSTEM_AUDIT.md` aún describen el estado inseguro ya corregido. |
| Array get/set/length | C | C | C | C | C | C | C | C | C | C | C | C | C narrowing | E2E | C | Completo | Índices 0-based. |
| Array sort | método/global | C | C tipos | C estable in-place | C sequence sort | C | C | C | C | C | C efecto | C | C temp checked | E2E | C | Completo | int/double/string. |
| Array slicing | C `a[s:e]` | C | C | C copy | C | C | C | C | C | C | C | C | C bounds | E2E | C | Completo | 0-based, half-open, dos límites explícitos. |
| Array copy/equality | C | C | C | C | C | C | C | C | C | C | C | C | RC + helper Eq tipado | E2E | C | Completa | `copy` crea storage exterior nuevo; igualdad compara contenido mediante Eq(T). |
| `List<T>` literal/new/get/set | C target-typed | C | C | C | C | C | C | C | C | C | C | C layout tipado incluido Struct soportado | C RC y destroy final | E2E escalares/enum/Struct + expense tracker | C | Parcial | No hay keyword `new`; layouts no representables se rechazan antes de LLVM. |
| List length/capacity/core mutation | métodos | C | C | C | C salvo capacity pública | C | C | C | C | C | C | C | C checked growth | E2E | P | Parcial | `capacity` se usa internamente pero no es API pública completa. |
| List push/pop/insert/removeAt/clear | métodos/global | C | C | C | C | C | C | C | C | C | C efecto/trap | C para layouts soportados | C hooks de elemento y release final | E2E+safety escalares/Struct/string | C | Parcial | No shrinking es deliberado; `clear` destruye elementos vivos y el último owner destruye buffer y objeto. |
| List contains/indexOf/reverse/copy/sort | métodos/global | C | C | C | C | C | C | C | C | C | C | C Eq search | helpers Eq compartidos | E2E + baseline | C salvo sort general | Completa para búsqueda Eq | Copy exterior superficial; búsqueda estructural; sort sigue limitado a int/double/string. |
| List slicing/equality | C | C | C | C | C | C | C | C | C | C | C | C | RC + copy_init + Eq | E2E | C | Completa | Slice `[start,end)` independiente; igualdad ignora capacity e identidad. |
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
| CLI run/build/inspect/bench | — | — | usa frontend | AST seleccionable | usa IR | C subset | C | C subset | export/build | C | perfiles parciales | default/build C subset con gate previo | clang | tests CLI | P desactualizada | Parcial | La superficie native es menor que AST, pero el perfil 22 la delimita antes del lowering. |
| REPL persistente | C por entrada | C | C incremental | C rollback | N | N | N | N | N | N | N | N | AST session | tests | C | Solo AST | `--backend=ast` obligatorio. |
| LSP | lexer/parser | AST | C diagnósticos frontend | — | N | N | N | N | N | N | N | N | proceso LSP | tests | P | Parcial | Completion/hover/symbols parciales y formatting canónico de control-flow; sin rename semántico completo. |
| Optimización `-O0` | — | — | — | — | C | C | C | — | no usada por emit-ir | — | sin pases | — | — | CLI/optimizer | C | Completo | Solo `--emit-ir`; no controla build native. |
| Optimización `-O1` | — | — | — | — | C | C | C post-pass | — | SSA native tiene pipeline propio | C | C fixed point IR | native no usa flag | — | amplia | C | Parcial | El nombre de perfil solo conecta a emisión IR. |
| Optimización `-O2` | — | — | — | — | C | C | C | — | igual | C | alias de O1 | native no usa flag | — | CLI | C como alias | Parcial | No es un nivel más fuerte; debe seguir marcado experimental. |
| ABI C / FFI | N | N | N | N | N | N | N | N | N | N | N | N | usa libc internamente | N | diseño futuro | No implementado | Usar `printf`/malloc internamente no constituye una FFI pública. |

## Resultado de la reconciliación Fase 5.0

Hay dos perímetros distintos y no deben mezclarse:

1. **Perfil estable Aether 1.0:** paridad completa para las 75 filas admitidas.
   Cada programa aceptado por las filas de lenguaje del perfil 22 alcanza IR
   verificado, SSA verificado, optimización, LLVM, clang y tests native; el
   corpus diferencial mantiene el contrato observable. No se encontró un gap
   P0 ni una feature v1 aceptada que falle después del gate.
2. **Superficie experimental del frontend/AST:** paridad incompleta. Las 46
   filas `OUTSIDE_V1` no son promesas de la release, pero varias ya parsean,
   typecheckean y ejecutan en AST. Alcanzar paridad con toda esa superficie
   requiere el trabajo listado abajo.

El trabajo Rust cambia el estado del **subsistema de verificación**, no la
matriz de lenguaje. El importador owned IR v1 y el verificador Rust cubren el
IR transportable, IRV-024 quedó semánticamente alineado y existe un canary
Rust-authority fail-closed. La compilación de producto todavía usa el
verificador Python directo salvo inyección explícita; Rust no verifica SSA ni
añade lowering, runtime o codegen de features.

La deuda anterior del **SSA verifier** permanece cerrada: comprueba dominancia
y orden de usos, operandos `phi` sobre su arista, un incoming exacto por
predecesor y la política de inalcanzables. Se ejecuta después de construcción,
en tests después de cada pase y obligatoriamente antes de LLVM/native. No
existe un intérprete SSA; esa celda es `—`, no un gap.

## Matriz resumida reconciliada

La matriz exhaustiva anterior conserva las celdas por etapa. Este resumen
agrupa el resultado actual sin convertir un nodo/opcode nominal en soporte:

| Área | Frontend + AST interpreter | IR model/lowering/verifier/interpreter | SSA/verifier/optimizers | LLVM/runtime/native tests | Resultado |
| --- | --- | --- | --- | --- | --- |
| Core v1: int/double/boolean, funciones, control-flow | C | C | C | C + diferencial | Completo |
| Strings v1: transporte, Eq, concat, byteLength, trim, split, parsing | C | C | C | C + lifecycle/O0/O1/O2 | Completo |
| Structs/enums y métodos representables | C | C para layout v1 | C | C + E2E | Completo para perfil v1 |
| Array/List representables: RC, copy, slice, Eq, búsqueda, sort y mutación registrada | C | C | C | C + safety/E2E | Completo para perfil v1 |
| Vector/Matrix core tipado y shaped | C | C subset | C subset | C subset + parity | Completo para perfil v1 |
| Módulos/imports de declaraciones soportadas | C | C | C | C + multiarchivo | Completo para perfil v1 |
| Args y archivos de texto | C | C | C | C en Linux; gate de plataforma | Completo en plataforma v1 |
| Initial IR verifier Rust | — | C para schema/IR v1 transportable; opt-in/canary | — | No cambia codegen | Subsistema completo hasta canary; no autoridad de producto |
| Superficie `OUTSIDE_V1` detallada abajo | C/P según feature | N o nominal sin E2E | N | gate temprano | Sin paridad |

## Backend restante antes de paridad con todo el frontend

| Feature | Evidencia frontend/AST | Primera frontera incompleta | Estado native comprobado |
| --- | --- | --- | --- |
| Local inferida `x = expr` | Parser, checker y AST C | No crea storage local compilable | Gate / Solo AST |
| Funciones anidadas | Parser, checker y AST C | Lowering de declaración anidada N | Solo AST |
| Globals/const y statements importados | Módulos/checker/AST C | Falta storage IR e inicialización single-execution | Gate `AE-BACKEND-MODULES` |
| `float` | Parser/checker/AST C | IR sólo nominal/parcial; sin ABI native estable | Gate `AE-BACKEND-PRIMITIVE_TYPES` |
| `complex` / `im` | Parser/checker/AST C | Sin lowering fuente ni ABI/runtime native | Gate |
| `null` y `T?` | Parser/checker/AST C | Sin narrowing, layout/lifecycle ni lowering | Gate |
| Tuples/destructuring | Parser/checker/AST C | Sin modelo/lowering IR estable | Gate |
| Classes | Parser/checker/AST + IR/SSA/LLVM 5.3B | Métodos generales, interfaces y dispatch pendientes | Gate `AE-BACKEND-CLASS_METHODS` por métodos |
| Native Interface ABI | Construcción class→interface, IR/SSA/DTO/verifiers/LLVM C | Sin dispatch ni boxing | ABI habilitada; gate `AE-BACKEND-INTERFACES` sólo para 5.4B/5.4C |
| Métodos enlazados, callable retornado, builtin como valor | Subsets reconocidos; callable top-level ya C | Sin environment/ABI/lowering para esas formas | Rechazo de tipo/gate |
| Interpolación y formatting general | Parser/checker/AST C para el experimento | Sin IR/lowering/runtime native | Gate `AE-BACKEND-STRINGS` |
| `input` tipado | Nodo/checker/AST C | Sin opcode/runtime native | Gate `AE-BACKEND-INPUT` |
| `throw` / `try-catch` | Parser/checker/AST C | Sin IR, cleanup excepcional ni runtime native | Gate `AE-BACKEND-ERROR_HANDLING` |
| Slicing Vector/Matrix y Matrix `for-in` | Frontend/AST C en los subsets registrados | Sin lowering estable | Gate Vector/Matrix |
| Álgebra lineal avanzada | Checker/AST host con NumPy/SciPy y tests | La mayoría no tiene IR ni ABI/runtime native | Solo AST |
| `Range` almacenado | AST tiene `Range<int>` | Native baja sólo `RangeExpression` dentro de `for` | Gate `AE-BACKEND-FOR_IN` |
| Protocolo genérico Iterator/Iterable | Sólo propuesta en la auditoría de iteración | No existe API/nodos/tipos implementados | No implementado |
| Reflection/serialización genérica | ALPT1 es codec manual, no reflection | No existe superficie de lenguaje o backend | No implementado |
| Genéricos de usuario | Parser reconoce formas para rechazo | Checker y todas las etapas posteriores N | No implementado |

Slicing de **Array/List no es un gap**: es E2E, copying, 0-based y semiabierto.
Tampoco lo son Eq/búsqueda de `Array/List<Struct>`, lifecycle final de List,
`%` double, short-circuit, bounds de Array, enums o structs del perfil v1.

## Dependencias comprobadas

Las aristas siguientes aparecen en los contratos/auditorías existentes; no
establecen dependencia entre raíces independientes:

```text
IR global storage + política single-execution
    -> globals/const importados
    -> statements inicializadores importados

TypeLayout + lifecycle de referencias
    -> layout/ownership de class native

TypeLayout/lifecycle de valor borrado + carrier/witness (5.4A completado)
    -> witness slots/thunks + dynamic dispatch native (5.4B)
    -> boxing y adapters struct (5.4C)

Range value IR (fuera del lowering especial de for)
    -> Range almacenado/pasado
    -> protocolo interno Iterable/Iterator
    -> iterables no indexables adicionales

Contrato de shape/orientación por operación avanzada
    -> opcode/ABI de runtime de álgebra lineal
    -> lowering LLVM + tests native

Paridad IRV + protocolo/package + IRV-024 alineado (completados)
    -> canary Rust-authority sostenido
    -> decisión separada de autoridad Initial IR de producto
```

No hay evidencia de que nullable sea requisito de classes, ni de que classes
sean requisito técnico único de interfaces; por eso no se inventa la cadena
`nullable -> class -> interface`. Nullable necesita su propio layout y
lifecycle. Interface necesita una representación borrada/dispatch compatible
con los receivers admitidos. Reflection tampoco entra en el grafo: no existe
implementación ni contrato aprobado que permita ordenar ese trabajo.

## Prioridad

### P0 — corrección crítica

**Ninguno abierto encontrado.** El gate evita lowering de las formas excluidas;
los P0 históricos de i32, rangos, bounds, lifecycle, paridad observable e
IRV-024 están cerrados y tienen regresión.

### P1 — feature visible pero backend incompleto

Para el objetivo amplio de paridad con el frontend: estado importado de
módulos; classes; interfaces/dispatch; tuples; `float`/`complex`;
funciones anidadas y callables avanzados; interpolación/formatting; input;
excepciones; extensiones Vector/Matrix; y álgebra lineal avanzada. Son
experimentos explícitamente `OUTSIDE_V1`, no defectos de conformidad del perfil
estable. Cada uno debe permanecer detrás del gate hasta completar todas las
etapas y tests de su fila.

### P2 — feature estable, subsystema incompleto

- decisión de promoción o retención de la autoridad Rust después del canary;
- `-O2`, que continúa como alias de `-O1` y no selecciona optimización native;
- portabilidad fuera de Linux, no prometida por el perfil v1;
- consolidación de matrices/documentos históricos duplicados.

Ninguno impide ejecutar correctamente una feature admitida en Linux con la
autoridad Python actual.

### P3 — expansión futura

Genéricos de usuario, protocolo público Iterator/Iterable, reflection,
Map/Set/Queue/Stack, FFI pública, binary/stream/process IO general y
closures/lambdas sin superficie implementada. No son trabajo necesario para
cerrar el perfil native actual y no se les asigna semántica nueva en esta
auditoría.

## Reconciliación documental

- `BACKEND_CAPABILITY_PROFILES.md` es coherente con profile 22 y explica la
  evolución del gate. Duplica historia de perfiles de esta auditoría y contiene
  una línea repetida de igualdad string. También conserva el conteo “81 filas”
  aunque esta matriz por etapas tiene hoy 84 filas, y el snapshot diferencial
  de 12 programas/36 ejecuciones frente al corpus actual de 14/42. El
  inventario de release de 123 filas usa otra granularidad y no debe mezclarse
  con ninguno de esos conteos. Conviene conservar allí sólo política y
  evolución del dato generado.
- `AETHER_V1_PROFILE_AUDIT.md` y `AETHER_NATIVE_PROFILE_V1.md` son coherentes
  para el perímetro v1: 75 `SUPPORTED`, 46 `OUTSIDE_V1`, gate 22 y Linux. El
  primero es cierre de release; esta auditoría sigue siendo la matriz de
  backend más amplia, no un segundo inventario normativo.
- `LINEAR_ALGEBRA_AUDIT.md` acierta en que álgebra avanzada sigue AST-only,
  pero su “Phase 5 LLVM/Runtime Integration” quedó obsoleta para el core
  Vector/Matrix que ya baja E2E. Debe etiquetar esa fase como histórica y
  limitar el pendiente a operaciones avanzadas.
- `CONTROL_FLOW_AND_ITERATION_AUDIT.md` tiene un encabezado correcto que marca
  cerrado el P0 rc.2, pero el resumen, matrices y prioridades posteriores
  conservan el snapshot rc.1. Debe tratarse como evidencia histórica; sus
  propuestas de `Range<T>`/Iterator no son estado implementado ni roadmap
  aprobado.
- `docs/compiler/BACKEND_FEATURE_PARITY.md` ya está marcado como ubicación
  histórica y enlaza esta auditoría: no debe actualizarse como segunda matriz.
- `docs/compiler/FEATURE_MATRIX.md`, el cuerpo histórico de
  `ARRAY_SUBSYSTEM_AUDIT.md` y partes de `LLVM_BACKEND.md` todavía afirman
  short-circuit ausente, Array inseguro, structs/List/string/println/imports
  ausentes o LLVM desconectado. Son contradictorios con código, tests y perfil.
  Deben recibir banner de snapshot/superseded o perder las tablas duplicadas.
- `AETHER_IR_DESIGN.md` mezcla infraestructura actual con una lista
  “Current limitations” anterior a for, structs, SSA, builtins y optimizer.
  Debe separar diseño inicial histórico de contrato implementado.
- `IR_BACKEND_SUPPORTED_SUBSET` en `src/aether/errors.py` sigue siendo un hint
  manual obsoleto. La fuente reutilizable actual es el detector/profile; no se
  debe crear otra matriz manual.
- `BACKEND_RUST_MIGRATION.md` abre todavía con “Phase 3 ... parity audit is
  next”, aunque el mismo documento agrega resultados 4.x al final. Los
  documentos `INITIAL_IR_*`, `PYTHON_RUST_VERIFIER_ADAPTER.md`,
  `RUST_VERIFIER_OPERATIONAL_READINESS.md` y `RUST_VERIFIER_CANARY.md` son la
  evidencia vigente. Al consolidar, debe distinguirse “producción directa
  Python” de “configuración dual por defecto Python-authority/Rust-shadow”.

## Roadmap recomendado para Fase 5.x

1. **5.1 — Autoridad documental y baseline:** eliminar o marcar como snapshot
   las matrices duplicadas anteriores y hacer que resúmenes generables consuman
   `capabilities.py`. Mantener esta auditoría para evidencia por etapa y el
   perfil v1 para el contrato de release.
2. **5.2 — Cierre de autoridad Initial IR:** evaluar los criterios de salida
   ya definidos del canary. Promover Rust o conservar Python debe ser una
   decisión separada, fail-closed y sin cambiar features, SSA o LLVM.
3. **5.3 — Estado de módulos native:** implementar en una fase futura, no en
   esta auditoría, storage IR y política single-execution antes de admitir
   globals/const/statements importados.
4. **5.3A — Referencias native:** TypeLayout/lifecycle/ABI, allocation interna,
   ARC, identidad y containment completos; mantener gated construcción,
   fields y métodos source.
5. **5.3B — Payload class:** definite initialization, constructor lowering,
   cleanup parcial, fields y destructor recursivo.
6. **5.3C — Métodos class:** ABI directo, `this` borrowed y calls estáticas
   completados.
7. **5.4A — Native Interface ABI:** `{carrier,witness}`, construcción
   class-only, DTO/SSA/verifiers/LLVM y lifecycle completados.
8. **5.4B — Dispatch:** poblar witnesses y añadir dispatch sólo
   después de que sus receivers y ABI callable tengan lifecycle verificable.

Nullable, tuples, `float`/`complex`, excepciones, strings adicionales,
iteración general y álgebra avanzada son raíces o ramas independientes. No
deben agruparse artificialmente con 5.3–5.5 ni habilitarse por relajar el gate:
cada promoción exige su propio camino parser→tests y actualización explícita
del perfil.

## Validación de la reconciliación

| Check | Resultado |
| --- | --- |
| `scripts/check_release_docs.py` | PASS |
| `scripts/render_native_profile.py --check` | PASS; profile 22 sincronizado |
| Corpus diferencial | PASS; 14 programas, 42 comparaciones O0/O1/O2 |
| Capabilities/parity/Eq/short-circuit/RC/numeric/Vector-Matrix | 127 passed |
| IR/SSA verifier, optimizers y regresión de repositorio | 230 passed |
| Shadow/authority/canary/operational/IRV-024 | 79 passed, 3 skipped opt-in |
| `cargo test --workspace --all-targets` | PASS |
| `git diff --check` | PASS |

La suite focalizada que incluye `test_v1_profile_audit.py` produjo 317 passed
y 7 failures exclusivamente en el catálogo de ejemplos: el manifest no incluye
archivos trackeados posteriores (`SNL.ae` y dos ejemplos LeetCode), existe
`nonlinear_systems/nr2.ae` sin trackear y el worktree ya contenía cambios en
`Sorts/Main.ae`, `Sorts/Sortings.ae` y `nose.ae` que alteran clasificación o
hashes. Esta auditoría no modificó esos ejemplos ni el manifest. El hallazgo es
documental/catalogación y no contradice las pruebas backend focalizadas ni el
corpus diferencial versionado.
