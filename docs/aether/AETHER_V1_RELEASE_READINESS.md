# Aether v1 — auditoría de preparación para Release Candidate

> Clasificación: **Audit**. Es una auditoría fechada, no una especificación.
> Los contratos vigentes están en [la spec v1](AETHER_LANGUAGE_SPEC_V1.md) y
> [el perfil native v1](AETHER_NATIVE_PROFILE_V1.md).

> Auditoría relacionada posterior al corte: [control de flujo e
> iteración](CONTROL_FLOW_AND_ITERATION_AUDIT.md). Ese documento caracteriza la
> implementación rc.1 y diseña la transición rc.2; no modifica este dictamen ni
> la spec congelada.

Fecha de corte: **16 de julio de 2026**

Repositorio auditado: commit `634a404`

Perfil de capacidades auditado: `22`

Resultado actualizado tras P0.3: **READY TO BEGIN RC; NOT READY FOR v1 FINAL**

## 1. Dictamen ejecutivo

Aether está preparado para **comenzar** una Release Candidate de v1 dentro del
contrato y del perfil publicados, pero no para declarar v1 final ni congelar su
ABI interno. El cierre P0.3 añadió contrato, identidad y artefactos sin ampliar
features ni el subset native. Los hallazgos P1, P2 y P3 de esta auditoría
permanecen abiertos con su prioridad original.

Los tres bloqueos P0 están cerrados sobre el mismo alcance: P0.1 delimita
tempranamente profile 22, P0.2 asegura paridad observable dentro de lo aceptado
y P0.3 identifica y verifica `Aether 1.0.0-rc.1`.

El gate native ya no promete `float` ni otras formas sin camino completo:
rechaza esas construcciones después del typechecker y antes del lowering con un
diagnóstico `AE-BACKEND-*` tipado y localizado. Todo programa del corpus que el
perfil 22 acepta alcanzó LLVM y clang O0/O1/O2 sin errores internos.

Una suite verde demuestra una base de ingeniería considerable. No demuestra
por sí sola paridad semántica, seguridad de ownership, portabilidad ni un
contrato de release. La RC congela sólo la spec y el perfil publicados; no
convierte los P1 ni las fronteras excluidas en compatibilidad prometida.

## 2. Alcance, método y criterio

Esta auditoría inspeccionó el estado actual del código, documentación, tests y
ejemplos. Las auditorías previas se usaron sólo como lista de hipótesis; sus
afirmaciones se contrastaron contra implementación y ejecución.

Estados usados:

| Estado | Criterio |
| --- | --- |
| **COMPLETE** | Camino coherente dentro de un alcance explícito, con implementación y evidencia ejecutable suficiente. |
| **PARTIAL** | Existe un subconjunto útil, pero hay combinaciones, plataformas o capas sin cerrar. |
| **UNSUPPORTED** | La capacidad se rechaza deliberadamente en esa capa. |
| **BROKEN** | Una ruta prometida o aceptada diverge, falla tarde o viola su contrato observable. |
| **DESIGN ISSUE** | La frontera, semántica o fuente de verdad no está suficientemente resuelta para congelarse. |

La clasificación de prioridad es estricta: P0 bloquea una RC; P1 puede cerrarse
durante la RC pero bloquea v1 final; P2 es deuda importante; P3 es trabajo
post-v1. Una feature explícitamente fuera del alcance no se eleva a P0 sólo por
no existir.

## 3. Validación realizada

| Validación | Resultado | Lectura crítica |
| --- | --- | --- |
| `pytest` completo | **3058 passed, 1 skipped**, 148.76 s | Base amplia; el único skip es Newton system experimental. No hay medición de cobertura. |
| `scripts/ci.py --skip-tests` | **PASS**, 8.69 s | Pasaron whitespace, 3 benchmarks, 7 emisiones LLVM y 7 builds native. Es un pipeline local pequeño, no una matriz CI. |
| Regression general SSA del repositorio | 112 programas; 84 bajaron a IR; 60 comparables; 28 no comparables | La comparación es estructural. Las excepciones de programas no comparables no prueban equivalencia de ejecución. |
| Build de wheel | **PASS**: `aether_language-0-py3-none-any.whl` | El artefacto sigue versionado `0`; no valida una distribución v1. |
| Instalación aislada del wheel con `--no-deps` | El comando `aether --version` falla por import de `numpy` | Las dependencias están declaradas, pero el comando mínimo carga de forma eager el runtime científico. Revela acoplamiento de packaging, no una dependencia omitida. |
| IntelliJ `gradle test` | **INCONCLUSO** | Falló antes de los tests por corrupción/modificación del immutable workspace cache local de Gradle. El pipeline del repositorio tampoco ejecuta Gradle. |
| Sondeo de `%` sobre parámetros `double` | **PASS**: `AE-BACKEND-ARITHMETIC` antes del lowering | El subset native declara únicamente remainder entero. |
| Sondeo de cast `boolean(1)` | **PASS**: `AE-BACKEND-PRIMITIVE_TYPES` antes del lowering | Los casts native estables son `int↔double`. |
| Sondeo de local inferido `x = 1` | **PASS**: `AE-BACKEND-VARIABLES_AND_CONST` antes del lowering | La declaración por asignación sigue siendo válida en AST, no en native. |
| Sondeo `float(16777217)` pasado a función | **PASS**: `AE-BACKEND-PRIMITIVE_TYPES` antes del lowering | `float` queda fuera del subset native estable. |
| Corpus de ejemplos aceptado por native | **PASS**: 84/84 emitieron LLVM; 84/84 compilaron con clang en O0/O1/O2 | Ningún programa aceptado llegó a un fallo de lowering, verifier, printer o clang. |
| Corpus diferencial profile 22 | **PASS**: 12 programas; 36 comparaciones AST/native; clang O0/O1/O2 | stdout/stderr por bytes, exit code y archivos finales idénticos en sandbox controlado. |
| `println(1500.0)` | AST/native: `1500.0` | El formato público conserva `.0`; ALPT1 mantiene su codec canónico separado. |
| `println(Array<string>{"a", "b"})` | AST/native: `{"a", "b"}` | Quotes y escapes públicos unificados, con escritura native length-aware. |

El cierre P0.1 modificó únicamente el gate, la frontera de build y sus tests;
no agregó sintaxis, tipos, stdlib ni features. La prueba de leaks con LeakSanitizer no
pudo considerarse válida en este entorno; una ejecución ASan sin detección de
leaks no encontró errores de dirección en el ejemplo `particles`, pero eso no
sustituye una matriz sanitizer automatizada.

## 4. Estado por área

| Área | Estado | Evidencia y límite determinante |
| --- | --- | --- |
| Core language | **PARTIAL / DESIGN ISSUE** | El núcleo AST es amplio, pero v0 sigue siendo la especificación normativa y la frontera v1 no coincide con native. |
| Tipos | **PARTIAL** | `int/double/boolean/string` tienen camino native fuerte; `float`, `complex` y nullable son frontend-only y reciben diagnóstico temprano. El `int` aceptado usa checked i32 en AST/IR/native. |
| Structs | **PARTIAL** | Value semantics, métodos, nesting, equality y colecciones cruzan native para un subset real. Faltan layouts de otros tipos y ABI documentada/estable. |
| Classes | **UNSUPPORTED native / DESIGN ISSUE** | AST/typechecker/intérprete sí; no IR/SSA/LLVM. Lifecycle, layout y dispatch de referencia siguen abiertos. |
| Interfaces | **UNSUPPORTED native / DESIGN ISSUE** | Conformidad y dispatch AST; sin representación ni lowering native. |
| Enums | **COMPLETE para enums sin payload** | Nominales y cross-module funcionan en el perfil actual; payloads no son parte del alcance implementado. |
| Arrays | **PARTIAL** | Subset native profundo, RC, slicing, copy, Eq y sort. Composición con todos los tipos, sanitizers y contratos de panic no están cerrados. |
| Lists | **PARTIAL** | Growth, operaciones, copy, slicing, Eq y RC están bien cubiertos. Persisten los mismos límites de elemento/lifecycle y plataforma. |
| Strings | **PARTIAL** | Handle length-aware, ARC, UTF-8 bytes, concat, trim, split, parsing, files y argv existen. Formato, documentación, threading, ABI pública y composición general no están cerrados. |
| Callables | **PARTIAL** | Referencias a funciones top-level sin captura cruzan imports/native. No closures, bound methods, builtins como valor ni retorno callable general. |
| Ownership | **PARTIAL / DESIGN ISSUE** | Coordinado para string y Array/List, no para classes ni storage de Vector/Matrix; no hay unwind ni evidencia leak-sanitizer de release. |
| Lifecycle | **PARTIAL / DESIGN ISSUE** | IR explícito y verifiers fuertes para el subset RC. Panic abortivo evita rollback observable, pero no resuelve cleanup general. |
| Equality | **PARTIAL** | Eq estructural amplio en el subset native; no hay contrato completo para clases, callables, nullable y combinaciones restantes. |
| Modules | **PARTIAL** | Funciones, structs, enums y callables soportados cruzan archivos. No globals/constantes con storage ni inicialización single-execution native. |
| Imports | **PARTIAL** | Resolución semántica, alias y visibilidad son reales. README/tests README aún afirman que native los rechaza. |
| Parser | **COMPLETE para la gramática implementada / DESIGN ISSUE para v1** | Parser amplio con recuperación; no hay especificación v1 canónica sincronizada que determine qué superficie se congelaría. |
| Typechecker | **PARTIAL** | Resolución multifase y diagnósticos múltiples son fuertes. El detector posterior consume tipos chequeados y bindings léxicos para delimitar native. |
| Interpreter AST | **COMPLETE como referencia de la superficie AST, no como definición v1** | Es el backend más amplio; usa tipos/semántica host en números y formatting, de modo que no garantiza paridad native. |
| IR | **PARTIAL** | Modelo y verifier extensos para el subset native. Formas conocidas sin lowering, incluido `float`, quedan detenidas por el perfil 22. |
| Intérprete IR | **PARTIAL** | Útil para el subset y tests; no cubre toda la superficie AST ni sustituye la comparación native. |
| SSA | **PARTIAL** | General builder, dominancia, phis, verifier y optimizadores son sustanciales. No hay ejecución SSA y 28/112 programas del corpus no fueron comparables. |
| LLVM/native | **PARTIAL** | El subset aceptado por el perfil 22 llega a clang sin fallos conocidos. Sigue sin target matrix y conserva dependencias libc/POSIX. |
| Optimizer | **PARTIAL** | Verificación tras passes y modelado conservador de efectos son positivos. `O2` equivale a `O1`; CLI/native no expone política coherente y float folding usa semántica host. |
| CLI | **PARTIAL** | Run/build/emit/bench funcionan; reporta v0, opciones de optimización son inconsistentes entre emit/native y errores internos pueden escapar del contrato de diagnóstico. |
| REPL | **PARTIAL** | Persistente, rollback y AST-only. No tiene entrada multilinea y hace `deepcopy` del estado completo antes y después de rollback. |
| LSP | **PARTIAL** | Diagnostics usan lexer/parser/typechecker; completion/symbols/definition/references dependen en buena parte de regex y sólo resuelven el documento actual. Sin rename/format/semantic tokens. |
| IntelliJ | **PARTIAL / BROKEN en fidelidad léxica** | Plugin básico real. Resalta `'hola'` como string aunque el lexer del lenguaje sólo admite strings con comillas dobles y usa `'` como operador. Validación Gradle actual inconclusa. |
| Error messages | **PARTIAL** | Las limitaciones native conocidas usan diagnóstico `AE-BACKEND-*`, capability, detalle tipado y ubicación. Quedan otros contratos de diagnóstico fuera de este P0. |
| Diagnostics | **PARTIAL** | Recuperación y publicación LSP son útiles. `_read_source` captura `OSError` pero no `UnicodeDecodeError`, por lo que una fuente inválida puede filtrar error host. |
| Capability profile | **COMPLETE como gate native / deuda de trazabilidad** | El perfil 22 delimita el subset por tipos y formas soportadas antes del lowering. El registro E2E aún es manual y no sustituye una matriz generada capability→test. |
| Documentation | **BROKEN / DESIGN ISSUE** | Hay contradicciones activas, estados históricos mezclados con presentes, dos parity reports y especificación v0 aún normativa. |
| Dogfooding | **PARTIAL** | Tres ejemplos valiosos cubren subsets complementarios, pero no ejercitan las abstracciones y fronteras que v1 scope aún exige. |
| Testing | **PARTIAL** | Volumen y pruebas E2E destacables; sin coverage, fuzz/property testing, sanitizers, CI de plataformas ni trazabilidad real del perfil. |
| Build | **PARTIAL** | Linux local y clang pasan. No hay CI hospedada visible, matriz Windows/macOS, sanitizer ni Gradle integrado. |
| Packaging | **BROKEN para una v1** | Wheel construible, pero versión `0`, sin tags, core import acoplado a NumPy/SciPy/plots y sin release pipeline reproducible. |

## 5. Hallazgos P0 — bloquean una Release Candidate

### P0.1 — CERRADO: el perfil de capacidades native es una frontera sound

El perfil 22 corrige la frontera sin ampliar el lenguaje ni el backend. El
detector deriva los requisitos de tipos chequeados, bindings léxicos, firmas,
conversiones, operadores, builtins, layouts y plataforma. Los cuatro sondeos
originales son ahora regresiones negativas que sustituyen el fallo tardío por
un diagnóstico temprano:

- `% double` se rechaza como `AE-BACKEND-ARITHMETIC` usando tipos de operandos;
- `boolean(1)` y otras conversiones fuera de `int↔double` se rechazan como
  `AE-BACKEND-PRIMITIVE_TYPES`;
- la declaración inferida/implícita se rechaza como
  `AE-BACKEND-VARIABLES_AND_CONST`;
- todo uso de `float` se rechaza como `AE-BACKEND-PRIMITIVE_TYPES`, por lo que
  no puede volver a producir LLVM f32 inválido.

La auditoría extendida añadió las mismas garantías para conversiones implícitas,
operadores sin lowering, tuples/destructuring, builtins AST-only, impresión de
layouts no representables, pérdida de shape Vector/Matrix, rango con paso cero,
Exception values y restricciones de argv/files por plataforma. La emisión de
módulos de librería ya no inventa un wrapper hacia `main`; `build` valida perfil
y entry point antes del lowering.

**Evidencia de cierre:** todas las regresiones negativas espían el lowerer y
comprueban que no se invoca; todos los casos positivos atraviesan el pipeline.
Los 84 ejemplos aceptados por el perfil emitieron LLVM y compilaron con clang
O0/O1/O2. No queda un caso conocido que impida considerar sound el gate native.

### P0.2 — CERRADO: paridad observable dentro del perfil aceptado

El perfil 22 conserva su frontera; no se añadió ninguna capability. El contrato
público de `print/println(double)` usa 15 dígitos significativos, locale C,
`NaN`, `Infinity`/`-Infinity`, conserva `-0.0` y agrega `.0` cuando una salida
finita no contiene punto ni exponente. El codec ALPT1 continúa separado y usa
su representación canónica `%.17g`.

La impresión native de strings dentro de agregados ahora conserva comillas y
escapa `\\`, `\"`, newline y tab como AST, sin tratar NUL como terminador. La
negación double baja a `fneg`, preservando signed zero. Los panics de bounds,
overflow, división, split y métodos List del corpus tienen el mismo prefijo,
mensaje, stdout y exit 1. La CLI AST imprime panic público sin traceback host.

El runner `scripts/differential_parity.py` descubre el corpus aceptado, valida
el capability gate antes del lowering, ejecuta AST y compila el mismo LLVM con
clang O0/O1/O2. Cada ejecución usa locale, timezone y hash seed controlados;
compara stdout/stderr como bytes, exit code y snapshot de archivos. Los 12
programas producen 36 comparaciones exactas e incluyen escalares, doubles IEEE,
UTF-8/NUL, strings escapados, Array/List, structs/enums, copia/aliasing, argv,
archivos y panics. El runner forma parte de `scripts/ci.py` como gate repetible.

Durante el cierre también se corrigió un owner pendiente de strings de
`System.args()`, que podía causar double-release y traceback Python al copiar
`args[i]` a un local. No quedan divergencias conocidas dentro de este corpus.

### P0.3 — CERRADO: contrato y artefacto identificable como v1 RC

- `AETHER_LANGUAGE_SPEC_V1.md` es la especificación normativa y separa
  semántica de lenguaje de disponibilidad por backend.
- `AETHER_NATIVE_PROFILE_V1.md` es normativo y su tabla se genera/verifica
  directamente contra capability profile 22.
- `src/aether/version.py` contiene la única identidad mantenida:
  `1.0.0rc1` PEP 440, derivada públicamente como `1.0.0-rc.1`. Alimenta
  setuptools, wheel/sdist, CLI, REPL, LSP, plugin, tests y manifest.
- `aether --version` informa `Aether 1.0.0-rc.1` y
  `Native capability profile 22` desde un wheel, sin depender del checkout.
- Wheel y sdist incluyen licencia, stdlib, runtime LLVM generado y documentos
  esenciales; el wheel se instala con dependencias en un venv limpio.
- `scripts/release.py --version 1.0.0-rc.1` comprueba limpieza salvo
  `--allow-dirty`, ejecuta `scripts/ci.py`, construye, inspecciona, instala y
  prueba los artefactos, y genera manifest más `SHA256SUMS` sin publicar.
- Los smokes externos al checkout cubren version, AST/native, módulo/import,
  string, colección, argv, archivo y rechazo `AE-BACKEND-*`.
- El manifest distingue language version, package version y capability profile;
  registra commit, timestamp policy, Python/plataforma, dirty flag, resumen de
  gates, artefactos y SHA-256. Declara explícitamente que no se demostró
  reproducibilidad bit por bit.
- El gate completo pasó con 3065 tests, documentación, compileall, dogfoods,
  corpus diferencial (12 programas, 36 comparaciones, clang O0/O1/O2),
  benchmarks, emisiones LLVM, builds native y `git diff --check`.

El soporte declarado es AST validado en Linux y native **Linux x86_64 con
clang**. No se declara Windows, macOS, POSIX genérico, ABI estable ni clang
empaquetado. Los artefactos producidos con `--allow-dirty` son sólo evidencia
local y no se deben publicar; un candidato publicable debe regenerarse desde
un commit limpio. Este cierre no cambia ni cierra ningún hallazgo P1.

## 6. Hallazgos P1 — bloquean v1 final

### P1.1 — La abstracción de referencia/dispatch prometida por el scope no existe en native

Classes e interfaces son capacidades reales de parser, typechecker e intérprete
AST, pero no cruzan IR. El scope mínimo pide “al menos una abstracción por
referencia o dispatch” (`AETHER_V1_SCOPE.md:126`), y luego reconoce que continúa
abierta. No es razonable vender la superficie sintáctica como v1 estable sin
decidir si esa promesa entra o sale formalmente del release.

### P1.2 — Ownership y lifecycle sólo están cerrados para un subconjunto

String y Array/List tienen RC/ARC coordinado, hooks recursivos y cleanup normal.
Es trabajo valioso, pero `VALUE_LIFECYCLE_DESIGN.md:152-158` deja por definir
classes y buffers Vector/Matrix. No existe unwind; el panic native aborta, por
lo que rollback y cleanup excepcional no están demostrados. Tampoco hay una
etapa ASan/LSan obligatoria.

Riesgos concretos de release:

- aliasing y destrucción al introducir class handles;
- copiar Vector/Matrix dentro de agregados sin owner de storage definido;
- leaks o double-free en combinaciones no presentes en los E2E actuales;
- cambios incompatibles futuros del header/ABI interno.

### P1.3 — El modelo de errores native no está delimitado

Bounds y varios errores de runtime hacen panic controlado, pero
`throw`/`try`/`catch` son AST-only, no hay unwind, `input` es AST-only y algunos
errores del compilador filtran excepciones internas. Para v1 final debe existir
un contrato pequeño pero completo: qué es diagnóstico de compilación, resultado
nominal, panic abortivo y excepción —o qué sintaxis se declara no v1.

### P1.4 — Módulos native no tienen storage ni inicialización

La resolución cross-file para funciones, structs, enums y callables funciona.
No funcionan globals/constantes ni statements top-level importados con
inicialización single-execution. Es una frontera semántica, no un detalle de
linker. Debe cerrarse o excluirse normativamente antes de v1 final.

### P1.5 — La stdlib base no existe como producto congelable

`BUILTINS_AND_STDLIB_DESIGN.md` diseña una separación razonable, pero no hay una
stdlib `.ae` distribuida. El registro Python mezcla builtins del compilador,
IO/text, plotting y NumPy/SciPy. `src/aether/stdlib/registry.py:197` importa todas
las familias para consultar el registro; linear algebra importa NumPy y SciPy
en carga de módulo. Incluso `aether --version` atraviesa imports del runtime por
el `__init__` público.

Faltan como producto coherente el módulo mínimo `testing`, una frontera clara
core/optional y política de compatibilidad de nombres. La persistencia ALPT1 es
un codec manual dentro de un ejemplo, no una API general de stdlib.

### P1.6 — Portabilidad de v1 no está validada

Sólo se validó Linux en esta auditoría. El builder rechaza explícitamente
System.args y text-file IO en Windows (`src/aether/backend/llvm/build.py:61-77`)
y text IO en POSIX no Linux. El runtime usa `newlocale`, `strtod_l`, libc,
`fsync` y `rename`. El LLVM emitido no fija `target triple` ni `datalayout`; se
delega el target a clang sin matriz cross-platform.

UTF-8 por bytes está bien definido dentro del string runtime y ALPT1 evita
problemas de endianness al ser textual. La frontera filesystem/path/locale no
está cerrada fuera de Linux.

### P1.7 — Falta un release gate reproducible

No se encontró workflow CI hospedado. `scripts/ci.py` es útil, pero no incluye
IntelliJ/Gradle, wheel/sdist instalado, Windows, sanitizers, coverage ni corpus
de paridad completo. Si clang falta, omite native con warning. Antes de v1 final
debe existir un gate que no pueda declarar verde sin probar las fronteras del
release.

## 7. Hallazgos P2 — importantes

### P2.1 — Trazabilidad de tests insuficiente pese al volumen

Los 3058 tests son una fortaleza. Los huecos son de calidad de evidencia:

- no hay umbral ni informe de coverage;
- no hay property-based/fuzzing para parser, codecs, UTF-8, RC o verificadores;
- no hay sanitizer gate;
- `E2E_TESTED_CAPABILITIES` es un conjunto manual. El test en
  `tests/aether/test_backend_capabilities.py:100` sólo verifica que cada
  capability COMPLETE esté incluida en ese conjunto, no que apunte a una prueba
  ejecutada;
- el regression SSA atrapa excepciones para clasificar no comparables;
- 28 de 112 programas descubiertos no llegaron a comparación y sólo 60
  compararon builders;
- no hay matriz sistemática tipo × operación × backend × optimización.

### P2.2 — Concentración y duplicación arquitectónica

Los archivos `typechecker.py` (4445 líneas), `interpreter.py` (3430),
`ir/lowering.py` (3418), `ir/verifier.py` (2513), `ssa/verifier.py` (2253) y
`backend/llvm/printer.py` (4062) concentran decisiones repetidas de tipos,
efectos, layout, lifecycle y diagnóstico. Agregar una feature exige coordinar
muchos switches manuales; el bug ya cerrado del capability gate demuestra el
riesgo de futuras omisiones.

El runtime LLVM se construye como grandes fragmentos textuales dentro del
compiler y se inyecta en cada módulo. No hay una biblioteca runtime versionada
ni frontera ABI comprobable. Helpers internos de texto, creados para el codec
ALPT1, aumentan el privilegio del runtime y el acoplamiento ejemplo-compilador.

### P2.3 — Tooling semánticamente más débil que el compilador

El LSP publica buenos diagnostics del frontend, pero symbols/completion se
reconstruyen con regex (`src/aether/language_service.py:46-69` y
`src/document_symbols.py`). References busca ocurrencias textuales en un solo
documento (`src/aether_lsp/server.py:355-384`), por lo que shadowing, comentarios
y strings pueden dar falsos positivos. Definition tampoco resuelve
cross-module. El catálogo de members está duplicado y puede divergir.

El plugin IntelliJ tiene una divergencia concreta: su lexer trata comillas
simples como string salvo que parezcan apóstrofe postfix, y el test lo consagra.
El lenguaje real no ofrece ese literal. No bloquea el compilador, pero no debe
llamarse tooling v1 fiel.

### P2.4 — CLI y REPL exponen políticas accidentales

- `-O` sólo controla ciertas emisiones; native siempre pasa por el pipeline SSA.
- `O2` es alias efectivo de `O1`, no un nivel distinto.
- el REPL sólo admite una línea por lectura y AST.
- para rollback, `AetherSession` hace `deepcopy` de todos los símbolos, funciones,
  tipos y valores (`src/aether/session.py:110-159`), costo O(tamaño de sesión)
  por input y fuente de problemas de identidad futuros.
- `_read_source` captura `OSError`, no errores de decodificación UTF-8.

### P2.5 — Riesgos de rendimiento previsibles

No se propone optimizarlos antes de corregir contratos, pero deben registrarse:

- concatenaciones encadenadas materializan intermediarios y pueden copiar bytes
  de forma cuadrática; `concatFragments` evita esto sólo en rutas privilegiadas;
- el runtime textual y helpers usados se recompilan dentro de cada ejecutable;
- consultas repetidas al registro importan/construyen catálogos de builtins;
- el rollback del REPL copia el estado completo;
- LSP symbols/references recorre texto con múltiples regex;
- operaciones de colecciones y sort asignan buffers temporales sin estrategia
  de allocator/reserve pública.

No se encontró un algoritmo claramente explosivo en los tres dogfoods actuales,
pero su escala es pequeña y los benchmarks no cubren lifecycle/string/files.

### P2.6 — Seguridad y robustez necesitan evidencia adicional

- RC no atómico es correcto sólo mientras no exista concurrencia native; la
  prohibición debe ser contractual.
- No hay hardening sanitizer continuo para retain/release, aliasing y cleanup.
- Panic abortivo hace inconsistente la expectativa de liberación ante fallos.
- Escritura atómica POSIX es durable, pero cambia el modo del destino a 0600,
  reemplaza symlinks, no bloquea concurrent writers y conserva ventanas TOCTOU;
  el propio diseño documenta estos límites.
- Paths no son una frontera de seguridad/sandbox. Eso puede ser non-goal, pero
  debe decirse en la documentación de release.
- Fuente UTF-8 inválida puede escapar como `UnicodeDecodeError` host.

### P2.7 — Higiene documental deficiente

Hay documentos honestos y técnicamente detallados, pero no forman una fuente
de verdad consistente:

- `README.md:301` y `tests/README.md:25` dicen que native rechaza imports; hoy
  funciones, structs, enums y callables importados sí se compilan.
- `BACKEND_FEATURE_PARITY.md:292` conserva como hallazgo actual que
  Array/List&lt;Struct&gt; falla en LLVM, aunque commits y tests posteriores lo
  implementaron. Su encabezado dice revisión 15 de julio mientras incorpora
  cambios del 16.
- `docs/compiler/BACKEND_FEATURE_PARITY.md` está bien marcado como histórico,
  pero `docs/compiler/README.md` aún afirma que optimizer/LLVM no están
  conectados al CLI.
- `STRING_RUNTIME_DESIGN.md:84`, `:230`, `:1044` y `:1160` mezclan inventario
  pre-ARC y fases futuras con un encabezado que declara concat, parsing, trim,
  split, files y argv implementados.
- `VALUE_LIFECYCLE_DESIGN.md:414-431` afirma que concat, parsing, split/trim,
  files y argv siguen aplazados; ya existen.
- `COLLECTION_RUNTIME_DESIGN.md:3` y `:865` dicen que las seis fases están
  implementadas; `:882` concluye que todavía no describe una implementación
  completada.
- `PERSISTENCE_FORMAT_DESIGN.md` declara implementación actual, pero sus fases
  1–3 y parte del scope siguen redactadas como futuras. El “formato oficial” se
  implementa manualmente en `examples/expense_tracker/Persistence.ae`.
- `docs/EVOLUTION.md:153-155` y sus “Open Design Questions” todavía ponen
  concat/parsing/files/argv como ausentes, junto con preguntas que sí siguen
  abiertas.
- `EXPENSE_TRACKER_DOGFOOD_REPORT.md` conserva etapas históricas que niegan CLI
  o persistencia sin un corte claro entre estado viejo y actual.
- `examples/README.md` marca directorios enteros como “tested”, mientras el
  smoke no garantiza ejecución exhaustiva de cada ejemplo.

## 8. Hallazgos P3 — post-v1

Estos puntos no deberían retrasar v1 si el alcance los excluye con claridad:

- closures, lambdas, bound methods y callable environments;
- enum payloads, user generics, maps/sets y destructuring native completo;
- concurrencia, RC atómico, GC, weak references y custom allocators;
- grapheme clusters, normalización Unicode, case folding y regex;
- SSO, interning, ropes, views y builders públicos;
- optimizaciones O2 reales, GVN, LICM y vectorización;
- package manager, stable C ABI/FFI completo y runtime dynamic linking;
- reflection y serialización genérica;
- locks, backups, migrations y transacciones multiarchivo para persistencia.

La condición es que ninguna de estas capacidades aparezca implícitamente
prometida por la sintaxis o documentación v1.

## 9. Backend parity: discrepancias verificadas independientemente

La ruta real es:

```text
source -> lexer/parser -> typechecker -> capability profile
       -> AST interpreter
       -> IR lowering/verifier -> general SSA/verifier/optimizer
       -> textual LLVM/runtime -> clang -> native process
```

| Superficie | AST | IR/SSA | Native | Evaluación |
| --- | --- | --- | --- | --- |
| `int`, `double`, bool, control, funciones | Amplio | Amplio subset | Amplio subset | **Paridad observable cerrada para profile 22**; la superficie global sigue parcial. |
| `% double` | Ejecuta | No entra al pipeline native | Rechazo temprano `AE-BACKEND-ARITHMETIC` | **AST-only declarado**. |
| `float` | Coerción host | No entra al pipeline native | Rechazo temprano `AE-BACKEND-PRIMITIVE_TYPES` | **AST-only declarado**. |
| Casts | Amplios | int↔double efectivo | int↔double; resto rechazado temprano | **PARTIAL delimitado**. |
| Local inferido | Ejecuta | No entra al pipeline native | Rechazo temprano `AE-BACKEND-VARIABLES_AND_CONST` | **AST-only declarado**. |
| Structs | Amplios | Subset nominal/value | Subset real incl. Array/List | **PARTIAL**, no “AST-only”. |
| Classes/interfaces | Ejecutan | No | No | **UNSUPPORTED native**. |
| Enums sin payload | Ejecutan | Sí | Sí, también imports | **COMPLETE** en el alcance. |
| Strings | Superficie amplia | Lifecycle y ops dedicadas | Subset grande | **PARTIAL** por formato/composición/plataforma. |
| Array/List | Superficie amplia | RC y ops amplias | Subset amplio | **PARTIAL**, fuerte pero no universal. |
| Modules/imports | Incluye init top-level | Decl. soportadas combinadas | Funciones/structs/enums/callables | **PARTIAL**, no globals/init. |
| Exceptions/input | Ejecutan | No | No | **UNSUPPORTED native**. |
| Vector/Matrix | Amplios vía host | Subset | Subset | **PARTIAL**, ownership storage abierto. |

La auditoría histórica de paridad no se usa como gate: contiene tanto
limitaciones ya resueltas como divergencias todavía abiertas. El perfil 22 es
la frontera programática; tampoco sustituye pruebas diferenciales de ejecución.

## 10. Dogfooding

### Numerical Methods — PARTIAL

Ejercita de verdad imports multiarchivo, funciones/callables top-level, structs,
enums nominales, control de flujo, matemática escalar y resultados de error por
status. Las dieciocho validaciones coinciden AST/native.

No ejercita Array/List ownership, strings dinámicas, files/argv, clases,
interfaces, input/excepciones, globals/init, Vector/Matrix storage, stdlib
instalada ni testing. Los algoritmos son escalares y los errores evitan la
ausencia de exceptions mediante enums. Es buen dogfood de funciones numéricas,
no del lenguaje v1 completo.

### Expense Tracker — PARTIAL, el más representativo

Ejercita módulos, structs/enums, `List<Transaction>`, strings ARC, concat, trim,
split, parsing nominal, argumentos, IO UTF-8, escritura atómica y codec ALPT1
fail-closed. Fuerza growth y lifecycle recursivo de strings dentro de structs y
colecciones. Es el mejor stress funcional actual.

Huecos: clases/interfaces, native error handling, `input`, globals/init,
float/complex/nullable, Vector/Matrix, testing/stdlib distribuida, concurrencia,
Windows y metadata/locking del filesystem. El codec es application-specific y
usa helpers internos; no prueba una API general de persistencia. Tolera las
divergencias conocidas de formatting.

### Aggregate Collections — PARTIAL

`examples/aggregate_collections/particles.ae` ejerce un caso importante:
Array&lt;Particle&gt;, structs anidados, get/set, copia, slice, Eq y `for-in` borrowed,
con output exacto AST/native.

Huecos: List, growth, strings o referencias dentro del elemento, imports,
files/errors, failure paths, classes/interfaces y Vector/Matrix fields. Un único
happy path no basta para validar todo el lifecycle de agregados.

### Cobertura combinada

Los tres ejemplos son complementarios y útiles. Juntos aún no cubren:

- ninguna abstracción reference/dispatch native;
- module globals/init;
- input o error/unwind native;
- portabilidad no Linux;
- ciclo completo de una stdlib instalada y módulo testing;
- sanitizer/leak behavior;
- todas las combinaciones owner/borrow/copy/return/panic;
- límites numéricos, NaN/Inf/-0, i32 overflow y f32 rounding;
- diagnósticos negativos del perfil como producto final.

Por ello el dogfood actual prueba que varios subsistemas funcionan; no prueba
que el núcleo v1 esté listo para congelarse.

## 11. Decisiones de congelamiento

| Frontera | ¿Congelar hoy? | Motivo |
| --- | --- | --- |
| Núcleo sintáctico | **NO** | No hay spec v1 normativa sincronizada y existen formas válidas cuyo estatus native/diagnóstico es accidental. Probablemente requiere delimitación más que rediseño masivo, pero aún no freeze. |
| ABI interno | **NO** | Runtime textual, layouts parciales y lifecycle de classes/Vector/Matrix siguen abiertos; tampoco hay target matrix. |
| IR | **NO** | El capability gate ya está cerrado y `float` excluido, pero globals/init, error edges y lifecycle general obligarán a revisar tipos/opcodes/efectos. |
| SSA | **NO** | La infraestructura es fuerte, pero hereda un IR no cerrado, no tiene ejecución propia y mantiene builder pattern/fallback y corpus incompleto. |
| Stdlib base | **NO** | No existe aún como distribución Aether separada y estable; el registro actual mezcla core y dependencias host pesadas. |
| Runtime string | **NO** | El contrato semántico central está cerca, pero formatting, docs, sanitizers, plataforma y frontera ABI/threading no permiten congelar el runtime interno. |
| Modelo de ownership | **NO** | Sólo está coordinado para string y Array/List; las restantes referencias y buffers no tienen contrato completo. |

## 12. Condiciones mínimas para volver a auditar RC

Sin prescribir features nuevas, una reauditoría debería exigir:

1. cero P0: mantener el gate temprano sound ya cerrado, cerrar la paridad
   observable del subset y versionar el contrato v1;
2. decisión explícita de inclusión/exclusión para classes/interfaces, errors,
   input, globals/init, float/nullable/complex;
3. matriz capability→test ejecutable, no sólo registro manual;
4. build/install/run del artefacto release en entornos limpios;
5. CI obligatoria con native, sanitizer y las plataformas prometidas;
6. documentación canónica sin contradicciones de estado;
7. dogfood diferencial AST/native con outputs y fallos exactos;
8. auditoría de lifecycle sobre cada tipo que pueda poseer referencias.

## 13. Inventario documental inspeccionado

Documentos obligatorios, leídos y contrastados:

- `README.md`
- `CHANGELOG.md`
- `docs/EVOLUTION.md`
- `docs/aether/AETHER_V1_SCOPE.md`
- `docs/aether/BACKEND_FEATURE_PARITY.md`
- `docs/compiler/BACKEND_FEATURE_PARITY.md` (copia histórica, inspeccionada por
  existir el mismo título)
- `docs/aether/BACKEND_CAPABILITY_PROFILES.md`
- `docs/aether/BUILTINS_AND_STDLIB_DESIGN.md`
- `docs/aether/COLLECTION_RUNTIME_DESIGN.md`
- `docs/aether/STRING_RUNTIME_DESIGN.md`
- `docs/compiler/VALUE_LIFECYCLE_DESIGN.md`
- `docs/aether/TEXT_FILE_IO_DESIGN.md`
- `docs/aether/PERSISTENCE_FORMAT_DESIGN.md`
- `docs/aether/NUMERICAL_METHODS_DOGFOOD_REPORT.md`
- `docs/aether/EXPENSE_TRACKER_DOGFOOD_REPORT.md`

Documentación adicional contrastada: `docs/aether/AETHER_V0_SPEC.md`,
`docs/compiler/README.md`, `tests/README.md`, `examples/README.md`, READMEs de
Numerical Methods y Expense Tracker, diseños de arrays/collections/vector-matrix,
SSA/control flow/LLVM, y documentación del plugin IntelliJ.

Implementación inspeccionada: AST, lexer/parser, typechecker, intérprete AST,
model/lowering/verifier/interpreter IR, CFG y análisis, builders/verifier/passes
SSA, layouts/printer/build/runtime LLVM, capability detector/profile, CLI,
session/REPL, language service, LSP, plugin IntelliJ, registry/builtins/stdlib,
text IO, tests y ejemplos.

## 14. Decisión final

**A, para comenzar RC; B, para v1 final.**

**"Aether puede comenzar una Release Candidate `1.0.0-rc.1` dentro de la spec
v1 y native profile 22, pero todavía debe cerrar los P1 antes de v1 final."**

P0.1, P0.2 y P0.3 están cerrados. Ownership general, errores, módulos con
storage/init, stdlib futura, portabilidad, sanitizers y los demás hallazgos P1
siguen abiertos; este dictamen no los rebaja ni los declara resueltos.
