# Aether — LEGACY-TOOLS-FUTURE-AUDIT-V1

Estado: **AUDIT CLOSED — MIGRATION NOT YET AUTHORIZED**

Fecha: 2026-11-25

Checkout auditado: `main` @ `eec746d53520a161bdec27497f6789a632eb73f9`

Reporte de evidencia:
[LEGACY_TOOLS_FUTURE_AUDIT_V1_REPORT.md](LEGACY_TOOLS_FUTURE_AUDIT_V1_REPORT.md)

## 1. Alcance, autoridad y conclusión

Esta auditoría cubre el LSP Python, el intérprete AST, `AetherSession`, el REPL
de `aether-legacy`, sus consumidores IDE y su packaging. No implementa una
migración, no promueve semántica legacy y no autoriza eliminaciones.

La autoridad está fijada por [COMPILER_AUTHORITY.md](COMPILER_AUTHORITY.md):
`compiler-next` es el único compilador oficial. El frontend, typechecker,
runtime y comportamiento del stack Python son evidencia histórica aunque una
herramienta todavía los exponga. La aceptación del parser, typechecker o
intérprete Python no constituye soporte del lenguaje actual.

La conclusión es concreta:

1. **LSP:** conservar la función de producto, no su motor semántico Python. El
   destino recomendado es un LSP Rust sobre servicios editoriales de
   `compiler-next` (**LSP-C**). Un bridge Python → `compiler-next` (**LSP-B**)
   puede ser una transición acotada para diagnósticos, no la arquitectura
   final.
2. **Intérprete AST:** congelarlo como herramienta histórica no normativa. No
   portar sus capacidades por paridad y no anunciarlo como backend soportado
   del producto. Preservar corpus y casos que expresen contratos vigentes.
3. **REPL:** su UX persistente tiene valor independiente, pero su semántica hoy
   es inseparable del frontend/intérprete legacy. No construir un reemplazo
   hasta confirmar prioridad de producto. Si se aprueba, debe usar
   `compiler-next` y AOT/procesos primero; no necesita JIT.
4. **Packaging:** separar cualquier herramienta Python retenida del pin
   obligatorio `aether-compiler-core`; no perpetuar el wheel monolítico para
   sostener LSP o REPL. El split es una migración futura, no parte de esta fase.
5. **IDEs:** mantener el contrato externo `aether` + `aether-lsp`; migrar ambos
   clientes al mismo protocolo y corregir por separado la gramática CLI legacy
   que todavía emite IntelliJ.
6. **`compiler-rs`:** su retiro sigue condicionado por
   [LEGACY_COMPILER_RETIREMENT_AUDIT_V1.md](LEGACY_COMPILER_RETIREMENT_AUDIT_V1.md).
   LSP/AST/REPL no importan su binding en la ruta normal, pero el package que
   los distribuye sí lo exige durante instalación y build.

Para un proyecto mantenido principalmente por una persona, sostener dos
frontends semánticos, dos modelos de módulos y dos contratos de ownership es
un coste mayor que reimplementar la capa protocolar del LSP. Por eso
**LSP-A no es un destino sostenible** y **REPL-A sólo es aceptable como
herramienta histórica explícita**.

## 2. Método y significado de la evidencia

Se distinguieron cuatro niveles:

- **implementado y probado:** existe handler/código y pasó un test focal en el
  checkout auditado;
- **implementado con qualification insuficiente:** existe código, pero sólo
  lectura, tests indirectos o cobertura parcial;
- **anunciado:** aparece en capabilities o documentación;
- **ausente:** no hay capability, handler ni implementación localizada.

Una declaración LSP no se consideró implementación por sí sola. Tampoco se
consideró una característica del intérprete compatible con el lenguaje actual
por el solo hecho de tener tests legacy.

## 3. Inventario del LSP

### 3.1 Arquitectura real

`src/aether_lsp/server.py` implementa directamente JSON-RPC 2.0 sobre stdio,
con framing `Content-Length`. Mantiene texto y versión por URI en memoria. El
servidor no usa una biblioteca LSP, no crea un workspace index y no negocia
capacidades del cliente.

El análisis se reparte entre:

```text
aether-lsp
  -> src/aether_lsp/server.py
     -> aether.language_service.analyze_source
        -> lexer Python
        -> Parser.parse_with_recovery()
        -> TypeChecker.check_collecting_errors()
     -> autocomplete_engine.py + command_catalog.py
     -> document_symbols.py
     -> source_formatter.py
```

Los helpers de completion, hover, símbolos y navegación mezclan AST Python,
estado del typechecker y extracción léxica/regex. No consumen HIR ni identidades
semánticas de `compiler-next`.

### 3.2 Capabilities, handlers, tests y destino

| Capacidad | Estado comprobado | Código y qualification | Uso IDE | Dependencia semántica | Alternativa en `compiler-next` | Importancia |
| --- | --- | --- | --- | --- | --- | --- |
| Initialize/shutdown/exit | **Implementado y probado** en flujo básico | `_handle_message`, `_initialize_result`; smoke subprocess en `test_aether_lsp_server.py` | VS Code `LanguageClient` e IntelliJ LSP platform | versión legacy; capabilities estáticas | shell LSP nuevo; no requiere compiler API | necesaria |
| Negociación LSP | **Parcial** | ignora `initialize.params`, `initialized`, workspace folders y client capabilities | clientes toleran el mínimo | protocolo propio | biblioteca/protocolo LSP Rust | necesaria para robustez, no bloquea edición mínima |
| Sync open/close/save/change | **Implementado y probado** | `_did_open/_change/_save/_close`; versiones y limpieza probadas | ambos clientes | mapas de texto Python | document store con overlays | necesaria |
| Sync incremental | **Ausente** | anuncia `change: 1`; reemplaza el documento completo | clientes envían full sync | n/a | edits incrementales sobre overlays | útil, no primer gate |
| Diagnósticos léxicos | **Implementados y probados indirectamente** | `analyze_source -> lex`; rangos y múltiples errores probados | ambos | lexer legacy | `aether_frontend::lex`, `Diagnostic`, `Span` | necesaria |
| Diagnósticos sintácticos y recovery | **Implementados y probados** | `parse_with_recovery`; múltiples errores y catch malformado | ambos | parser/AST legacy | `parse_source` hoy es batch/fail; requiere recovery/editor API | necesaria |
| Diagnósticos semánticos | **Implementados y probados** para Python | `TypeChecker.check_collecting_errors`; errores múltiples e imports | ambos | typechecker legacy no normativo | análisis HIR de `compiler-next`; estructurar API para resultados parciales | crítica |
| Debounce/errores internos | **Implementado y probado parcialmente** | timer de 350 ms; descarta source/version obsoletos; ICE se convierte en warning | ambos | threading Python | scheduler cancelable + snapshots | útil |
| Completion | **Implementado y probado**, qualification acotada | snippets, keywords, builtins, símbolos anteriores, funciones del archivo, miembros nativos/stdlib; helpers regex | ambos por capability estándar | catálogos y símbolos legacy; no HIR oficial | symbol/type query sobre frontend oficial | necesaria en uso cotidiano |
| Hover | **Implementado y probado**, document-local | símbolos, builtins, imports y algunos miembros | ambos | regex/document symbols + tablas legacy | resolved symbol/type/signature service | necesaria |
| Go to Definition | **Implementado y probado**, document-local | `_definition_result` devuelve siempre el mismo URI | ambos | `symbol_visible_at_offset` | source map + resolved symbol cross-file | necesaria |
| Find References | **Implementado y probado**, lexical/document-local | regex por nombre; sólo limita específicamente catch binder | ambos | coincidencia textual, no identidad semántica | symbol identity + reference index | útil, alto riesgo de falsos positivos hoy |
| Rename | **Ausente y no anunciado** | sin provider/handler/test | ninguno | n/a | reference index + edits validados | útil, no prioritario antes de identidad semántica |
| Document Symbols | **Implementado y probado**, parcial | imports, funciones, variables, catch binders; extracción propia | ambos; outline | parser/regex legacy | AST/HIR declarations con spans | necesaria |
| Formatting | **Implementado y probado** para casos acotados | full-document edit; control flow, función abreviada y exceptions idempotentes | ambos | formatter Python, no compiler-next | formatter separado o AST oficial con trivia | útil pero no debe bloquear semántica |
| Signature Help | **Ausente y no anunciado** | sin código | ninguno | n/a | callable resolution HIR | útil, posterior a hover/completion |
| Inlay Hints | **Implementado y probado** | anunciado; nombres de parámetros de funciones, constructors y methods; cache por source | clientes compatibles lo consumen | parse/typecheck legacy completo | call resolution HIR | útil, no esencial |
| Code Actions | **Ausente y no anunciado** | sin código | ninguno | n/a | diagnostics con `FixIt` ya existe en frontend Rust | útil cuando spans/fix-its sean editor-safe |
| Semantic Tokens | **Ausente y no anunciado** | los IDEs resaltan lexicalmente por separado | no | n/a | token/AST/HIR clasificación | útil, no prioritario |
| Imports/módulos en diagnostics | **Implementado y probado** | resuelve desde directorio del URI | ambos | loader legacy lee filesystem | `CompilationSession::discover` descubre grafo transitivo | crítica |
| Navegación/completion cross-file | **Ausente** | no hay index; documentos abiertos son mapas independientes | ninguno más allá de diagnostics | n/a | catálogo de módulos + symbol index | necesaria para proyectos reales |
| Cancelación | **Ausente** | no maneja `$/cancelRequest`; handlers síncronos; timers sólo para diagnostics | ninguno | n/a | request tokens/cancel-safe queries | necesaria antes de análisis costoso |
| Performance incremental | **No calificada** | full lex/parse/typecheck por cambio; sólo cache semántica de inlay por source exacto | ambos | frontend batch Python | parse/cache/query db o invalidación por módulo | necesaria al crecer proyectos |

No se encontró una capability anunciada sin handler. Sí se encontró una brecha
entre “handler existente” y “servicio semántico”: definition y references no
son navegación de workspace, y completion/hover no prueban fidelidad con el
lenguaje oficial.

### 3.3 Multi-file, recuperación y concurrencia

- Diagnostics puede leer imports desde el filesystem relativo al documento.
- El texto abierto de otro URI no se usa como overlay para esos imports; un
  cambio no guardado en un módulo importado no forma parte del análisis.
- No hay índice persistente, invalidación transitiva ni watch handling en el
  servidor. VS Code crea un file watcher, pero el servidor no implementa
  `workspace/didChangeWatchedFiles`.
- Recovery pertenece al parser Python. Si el análisis lanza inesperadamente,
  se publica un diagnostic interno saneado y el proceso continúa.
- El lock cubre writes; los handlers no tienen aislamiento por snapshot. El
  timer de diagnostics comprueba texto y versión para evitar publicar trabajo
  obsoleto, pero no cancela cómputo ya iniciado.

### 3.4 Consumidores

**VS Code** ejecuta el comando configurable `aether-lsp --stdio` mediante
`vscode-languageclient`, registra documentos `file` y `untitled` y un watcher
`**/*.ae`. Usa las capabilities estándar que anuncie el servidor. Su CLI sí
usa la gramática oficial `aether run/check ... --emit <fase>`.

**IntelliJ** inicia el mismo `aether-lsp --stdio` como servidor project-wide
para `.ae`. La documentación enumera diagnostics, completion, hover, outline y
formatting; la plataforma puede consumir además las capabilities anunciadas de
navigation/inlay hints.

Se detectó una incompatibilidad independiente: `AetherCommandLine.kt` resuelve
el ejecutable oficial `aether`, pero construye comandos legacy (`FILE`,
`--backend=ast FILE`, `--check FILE`, `--emit-ir`, `--emit-ssa`, `--emit-llvm`).
La CLI oficial usa `aether run/build/check FILE` y `--emit ast|hir|mir|ssa|llvm`.
Esto no cambia el resultado del LSP, pero debe ser gate de integración IDE.

## 4. Inventario del intérprete AST

### 4.1 Arquitectura de evaluación

La ruta es:

```text
source
  -> lexer Python
  -> parser Python
  -> TypeChecker Python
  -> normalize_entry_point
  -> ASTBackend
  -> Interpreter sobre Environment/Scope Python
```

`Interpreter.interpret` carga imports, registra/ejecuta statements y luego
invoca el entry point. El evaluator despacha por clases del AST. Control flow
no local usa excepciones internas (`_ReturnSignal`, `_BreakSignal`,
`_ContinueSignal`, `_ThrownExceptionSignal`). `Function` captura un
`Environment` y snapshots de tablas de imports/tipos para llamadas posteriores.

### 4.2 Capacidades observadas

| Área | Capacidad real | Qualification/limitación | Clasificación |
| --- | --- | --- | --- |
| Escalares | `int` legacy checked-i32, `float`, `double`, `complex`, `boolean`, `string`, null/nullable y void interno | suite Python amplia; semántica no normativa | histórica; varias diferencias incompatibles |
| Variables/scopes | declarations con inferencia o tipo, const, assignment, scopes anidados y no-shadowing | tests de scope y session | útil como referencia, no oracle |
| Control flow | if/else, while, for-in, range, break/continue, return, short circuit | tests amplios en suite legacy | reemplazable por compiler-next |
| Funciones | block y forma abreviada; parámetros, retornos, recursion/calls; valores de función tipados para superficie acotada | `Function` captura environment; no equivale a closures oficiales modernas | histórica/experimental |
| Closures | existe captura léxica interna de `Environment` | no hay lambda node en este AST ni qualification focal de first-class closures actuales | qualification insuficiente |
| Colecciones | Array, List, Tuple, Range, Vector, Matrix, transpose, slicing/indexing y métodos nativos | Python objects y reglas legacy; SciPy/NumPy para álgebra | útil como corpus, no portar implementación |
| Structs | fields, construction, methods, copy/equality, field/index assignment | soportado por interpreter y tests legacy | histórica |
| Enums | identidad nominal por módulo, variants y valores | superficie anterior; compiler-next admite payloads/match bajo contratos actuales | divergente |
| Classes/interfaces | `ClassInstance`, constructors, methods, interface carrier/calls en superficie legacy | ownership/dispatch difiere del ARC/witness/receiver contract oficial | incompatible como autoridad |
| Referencias/borrowing | tracking local de valores owned y préstamo de variable de iteración; handles de class/interface | no implementa el borrow model, places, views ni invalidación de `compiler-next` | obsoleta como modelo semántico |
| Excepciones | throw, bare rethrow, múltiples catch, matching por Error/interface y `message()` | implementation AST completa para su modelo; contrato actual vive en compiler-next | histórica útil para casos observables |
| Imports/módulos | modules de archivo, packages, aliases, visibility, cache por interpreter e imports transitivos | lee filesystem; no package manager oficial | histórica; loader no reutilizable |
| Builtins | print/println, conversiones, math, strings, collections, process args, text IO | registry Python; parte de API difiere | seleccionar tests, no código |
| IO | stdout streaming, typed `input`, UTF-8 text/persistence helpers | input y errores probados en suite; filesystem host | experimental/histórica |
| Matemática | escalares, operadores Vector/Matrix, solve/eig/SVD/LU y otras rutinas | imports eager NumPy/SciPy; comportamiento host | experimental, reemplazable por libraries oficiales |
| Gráficos | figures, plot/bar/histogram, styles, SVG/PNG/document/interactive modes | `PlotBackend`; tests de sesiones/figures | valor independiente posible, no semántica core |
| Estado | `Environment` global; `AetherSession` reutiliza checker e interpreter | persiste vars/functions; imports/tipos parcialmente snapshot | útil para UX REPL |
| Memoria | refcount explícito para `StringValue`/`CollectionObject`, ownership sets, copy/destroy de aggregates; Python GC para hosts | no representa lifecycle/ARC/MIR oficial | incompatible |
| Errores | errores tipados con source location; typecheck antes de ejecutar; rollback de session | rollback usa deepcopy y coverage focal limitada | útil como patrón UX |

### 4.3 Persistencia y transacciones de `AetherSession`

Cada `run(source)` toma un `deepcopy` de parte del typechecker y del runtime,
ejecuta el pipeline y restaura el snapshot ante cualquier excepción. Está
probado que:

- variables y funciones sobreviven entre entradas;
- una entrada fallida no destruye estado anterior ni compromete una variable
  nueva;
- scopes de bloque no escapan;
- dos sesiones son independientes;
- `run_aether` crea una sesión fresca;
- estado de figures se aísla por sesión.

La transacción no está calificada para toda la superficie. El snapshot no
incluye, entre otros, interfaces del checker/runtime, methods/constructors del
runtime, `module_bindings`, exports cualificados, cache de módulos cargados,
identidades nominales de enum ni estado completo de plots. Por tanto no se debe
afirmar rollback total de imports, OOP, enums o gráficos sin tests nuevos.

### 4.4 Diferencias semánticas relevantes

Las diferencias no son bugs que esta auditoría autorice reparar:

- `int` Python es checked i32; el contrato actual de `compiler-next` define
  `int` como alias de `int64` y agrega familias fixed-width/unsigned.
- Literal typing, coerciones, generics y capacidades actuales se resuelven en
  el frontend Rust, no existen con el mismo modelo en Python.
- Ownership oficial se expresa en HIR/MIR/SSA con moves, drops, borrows,
  views, lifetimes y verificación por fase. Los sets/refcounts del interpreter
  son una simulación distinta.
- Classes/interfaces oficiales usan contracts de handles ARC, receivers,
  witnesses, inheritance y dispatch que no deben inferirse desde
  `ClassInstance`/`StructInstance` Python.
- El loader oficial usa `CompilationSession`, package identities, locks,
  registry y catálogo transitivo; el intérprete resuelve paths locales.
- `compiler-next` posee features actuales —por ejemplo generics, payload enums,
  match, references y closures— que el AST/evaluator histórico no modela de
  forma equivalente.
- NumPy/SciPy/Matplotlib son implementaciones host de herramientas científicas,
  no definición normativa de operaciones Aether.

## 5. Inventario del REPL

El REPL vive en `aether.cli.run_repl`, no es un producto separado. Crea una
`AetherSession`, lee una línea con `readline`, hace `strip()` y llama
`session.run(source)`.

| Función | Estado |
| --- | --- |
| Persistencia de variables | **implementada y probada** |
| Persistencia de funciones | **implementada y probada** en `AetherSession` |
| Imports | el estado de imports se conserva en objetos de sesión, pero no tiene qualification focal suficiente ni rollback completo probado |
| Evaluación | ejecuta un fragmento fuente; no imprime automáticamente el valor de una expresión |
| Comandos | sólo `\exit` y `\quit` |
| Multiline | **ausente**; una línea física es una compilación |
| Recovery de error de lenguaje | continúa y restaura el snapshot probado para casos básicos |
| ICE | termina el REPL porque el estado puede no ser seguro |
| Ejecución parcial | no hay cell graph; una entrada se typecheckea y ejecuta como unidad, aunque efectos host externos no son transaccionales |
| Historial/editing | **ausente**; no readline library ni archivo de history |
| Interrupción/cancelación | `KeyboardInterrupt` termina con 130; no cancela una entrada y conserva la sesión |
| Plotting | comparte `PlotBackend` persistente por sesión; probado para aislamiento/figures |
| Compiler dependency | usa exclusivamente frontend/typechecker/interpreter Python; no `compiler-next` |

El valor independiente es el loop interactivo, el workspace persistente, el
rollback visible y la exploración matemática/plotting. El parser/typechecker y
la semántica del evaluator no tienen valor independiente que justifique
mantenerlos como segundo lenguaje.

## 6. Grafo de dependencias y packaging

### 6.1 Grafo actual

```text
VS Code / IntelliJ
  -> aether-lsp (entry point de aether-language)
     -> aether_lsp.server
        -> aether package __init__
           -> language_service -> runner -> session
              -> pipeline -> interpreter
                 -> plot_backend -> NumPy (eager), Matplotlib (lazy)
                 -> stdlib.math.linear_algebra -> NumPy + SciPy (eager)
        -> autocomplete_engine / command_catalog / document_symbols

aether-legacy --repl
  -> AetherSession -> Python frontend + AST Interpreter

instalación/build de aether-language
  -> aether-compiler-core == 1.0.0rc4 (obligatorio en pyproject)
  -> source local compiler-rs/distributions/aether-compiler-core
  -> setup.py lee compiler-rs/Cargo.toml
  -> wheel Maturin/PyO3 + companions legacy
```

No existe edge runtime directo desde `aether_lsp.server`, `Interpreter` o
`AetherSession` a `aether_compiler_core`. Los imports del core viven en rutas
legacy IR/SSA y son lazy. El acoplamiento que bloquea instalación independiente
es de distribución/build.

### 6.2 Clasificación de dependencias

| Clase | Dependencias encontradas |
| --- | --- |
| A. Instalación obligatoria | `aether-compiler-core`, NumPy, SciPy, SymPy, Matplotlib, PyQt6; todas declaradas sin extras |
| B. Runtime obligatorio por imports actuales | Python stdlib; módulos `aether`; NumPy y SciPy llegan eager al importar interpreter; helpers top-level de LSP |
| C. Lazy/opcional en ejecución | Matplotlib se importa al usar plotting; modos GUI dependen de backend/entorno; core Rust se importa sólo en rutas IR/SSA legacy |
| D. Sólo tests/dev | pytest; Node/TypeScript/vscode-languageclient para extensión; Gradle/IntelliJ SDK para plugin |
| E. Históricas no usadas observadas | SymPy y PyQt6 no tienen imports en `src`; PyQt6 puede ser dependencia indirecta del backend Qt de Matplotlib, pero no uso directo |
| F. Externas/no verificadas integralmente | consumidores privados, wheels publicados, entornos GUI, IDE hosts y comportamiento cross-platform |

`requirements.txt` sólo lista NumPy/SciPy/SymPy/Matplotlib y no refleja
`aether-compiler-core` ni PyQt6; `pyproject.toml` es la fuente de instalación.

### 6.3 ¿Pueden instalarse separados del core Rust legacy?

**No con el packaging soportado actual.** `pip install aether-language` exige
el core y el build hook exige `compiler-rs/Cargo.toml`. `--no-deps` es un bypass
de desarrollo documentado por VS Code, no una distribución independiente ni
una prueba de dependencias completas.

**Sí es técnicamente viable extraerlos**, porque la ruta AST/LSP normal no llama
al binding. Pero el LSP actual importa el package público completo y arrastra
session/interpreter/NumPy/SciPy. Un split correcto requiere primero definir
imports estrechos y dependencias por herramienta; no basta con borrar el pin.

## 7. Alternativas de arquitectura

### 7.1 LSP

| Alternativa | Reutilización/dependencias | Fidelidad | Complejidad y mantenimiento | Riesgos/requisitos | Milestones posibles |
| --- | --- | --- | --- | --- | --- |
| **LSP-A: conservar Python y desacoplar package** | reutiliza server, completion, formatter y tests; extrae subset Python | baja/media y decreciente: sigue lexer/parser/typechecker legacy | split inicial medio, mantenimiento alto por semántica duplicada | false positives, lenguaje nuevo ausente, perpetuar scientific stack; requiere dependency audit fino | package mínimo; imports estrechos; marcar features legacy; EOL posterior |
| **LSP-B: Python protocol, compiler-next engine** | conserva loop/clients y parte UX; necesita API Rust accesible por subprocess/protocolo o binding | alta para diagnostics si todo análisis viene de Rust; mixta mientras navigation siga Python | coste medio; dos runtimes/protocolos | overlays no guardados, recovery parcial, process latency, schema/versioning; no se recomienda PyO3 sólo por compatibilidad | diagnostics JSON/IPC; overlay contract; route diagnostics; luego symbols/queries; retirar analyzers Python |
| **LSP-C: LSP Rust sobre compiler-next** | reutiliza `SourceFile`, spans, diagnostics, AST/HIR, module graph; agrega document store/index/protocol | máxima y una sola autoridad | coste inicial alto, mantenimiento total menor | frontend batch no tiene recovery incremental/query API; requiere separación de analysis session y estabilidad de IDs | editor-analysis crate; diagnostics; sync/cancel; symbols/navigation; completion/hover; optimization incremental |

Un frontend batch no es todavía un language server. `CompilationSession` parsea
una vez el catálogo desde disco y el driver retorna dumps/diagnostics; no ofrece
overlays, resultados parciales, query de símbolo, invalidación ni cancelación.
Sin esas APIs, envolver `aether check` sólo da diagnostics de archivos guardados.

### 7.2 REPL

| Alternativa | Reutilización/dependencias | Fidelidad | Complejidad/mantenimiento | Riesgos/requisitos | Milestones posibles |
| --- | --- | --- | --- | --- | --- |
| **REPL-A: mantener Python** | máxima reutilización inmediata; requiere frontend/interpreter y stack científico | baja respecto al lenguaje oficial | bajo hoy, alto acumulado | usuarios confunden aceptación AST con soporte; packaging pesado | etiquetar experimental; aislar package; congelar; EOL |
| **REPL-B: compiler-next** | reutiliza parser/HIR/MIR/SSA/backend/CLI oficiales | alta | media/alta; persistencia es el problema, no el prompt | fragment grammar, declarations, values y side effects entre procesos; necesita session contract | runner de fragmento no persistente; declarations acumuladas; process AOT; estado explícito; JIT sólo futuro |
| **REPL-C: UI Python + compiler-next** | conserva prompt Python; delega compile/run | alta sólo en parte delegada | añade IPC y package para una UI pequeña | complejidad sin ventaja clara; persistir valores sigue sin resolverse | bridge subprocess temporal; retirar UI Python al existir CLI Rust |

Un REPL AOT puede compilar fragmentos y ejecutar procesos. No requiere JIT. Sin
embargo, concatenar el transcript y reejecutarlo repite IO/plots/side effects;
serializar valores pierde identidad/owners; mantener código in-process requiere
una ABI/runtime session. Esas decisiones deben ser explícitas antes de prometer
persistencia equivalente a `AetherSession`.

## 8. Costes, riesgos y prioridades

### 8.1 Prioridad de capacidades

| Categoría | Capacidades |
| --- | --- |
| Necesarias cotidianamente | diagnostics autoritativos, sync robusto, imports/multi-file, completion básica, hover, document symbols, definition cross-file, formatting estable |
| Útiles no prioritarias | references semánticas, rename, signature help, inlay hints, code actions, semantic tokens, performance incremental avanzada |
| Experimentales | REPL persistente, plotting interactivo, scientific host builtins, AST execution |
| Históricas | Python compiler pipeline, IR/SSA legacy bridges, i32 `int`, loader Python, ownership simulator |
| Reemplazables | protocol loop Python, regex symbols/navigation, formatter Python si se define alternativa |
| Obsoletas como autoridad | TypeChecker/Interpreter Python, `--backend=ast` presentado como backend oficial, semantic parity con legacy |

### 8.2 Riesgos priorizados

| Prioridad | Riesgo | Estado |
| --- | --- | --- |
| P0 | LSP publica diagnostics de semántica no autoritativa | comprobado |
| P0 | package de tooling obliga instalar/build `compiler-rs` | comprobado |
| P1 | navegación lexical se interpreta como semántica | comprobado |
| P1 | IntelliJ emite gramática CLI legacy contra `aether` oficial | comprobado |
| P1 | reemplazo LSP batch ignora buffers no guardados/import overlays | requisito no resuelto |
| P1 | REPL hace parecer soportadas features sólo AST | comprobado en documentación histórica |
| P1 | borrar `compiler-rs` rompe el wheel antes del split | comprobado por auditoría anterior |
| P2 | split apresurado conserva imports NumPy/SciPy en LSP | comprobado |
| P2 | transcript REPL repite side effects | riesgo arquitectónico |
| P2 | consumidores externos del wheel/LSP | **UNRESOLVED** |

## 9. Recomendación arquitectónica por componente

### 9.1 LSP

Destino: **LSP-C**, un servidor Rust que use servicios de `compiler-next`.

Transición permitida: **LSP-B exclusivamente para sustituir diagnostics
semánticos primero**, usando un contrato machine-readable y overlays. Completion,
hover y navegación Python pueden sobrevivir brevemente con labeling/test gates,
pero no se deben expandir con nuevas reglas de lenguaje.

No se recomienda LSP-A como estado estable. Separar su wheel sin reemplazar el
motor sólo reduce el acoplamiento de instalación y consolida la divergencia.

### 9.2 Intérprete AST

- congelar features;
- marcarlo `LEGACY/EXPERIMENTAL/NON-NORMATIVE` en cualquier superficie que se
  retenga;
- preservar tests que describan output/errores aún deseables como corpus de
  `compiler-next`, reescribiendo expectations según contratos actuales;
- no portar NumPy/SciPy/plotting al core del compilador;
- retirar la implementación cuando no la consuman REPL, tests o distribución.

### 9.3 REPL

No iniciar todavía un REPL oficial nuevo. Primero decidir si el producto
necesita: (a) runner de fragmentos, (b) declarations persistentes, (c) valores
persistentes, (d) IO/plots persistentes. Son productos de coste distinto.

Si se aprueba, elegir **REPL-B** integrado en la CLI Rust, comenzando por
compilación AOT por proceso y fragments sin prometer persistencia de valores.
REPL-C no aporta suficiente valor para justificar Python/IPC permanentes.

### 9.4 Packaging Python

- no publicar LSP/AST/REPL nuevos dentro del wheel monolítico actual;
- si se necesita una ventana de compatibilidad, crear una distribución legacy
  explícita con extras científicos opcionales y sin core Rust cuando la ruta no
  lo usa;
- distribuir el LSP Rust junto a la toolchain oficial o como artefacto propio,
  sin importar `aether-language`;
- eliminar `aether-compiler-core` del package retenido sólo después de probar
  wheel/sdist/install limpio y búsquedas negativas.

### 9.5 IDEs

- conservar `aether-lsp --stdio` como contrato para permitir reemplazo interno;
- calificar VS Code e IntelliJ contra el mismo fixture protocolar;
- exigir buffers no guardados e imports con overlays en diagnostics;
- alinear IntelliJ con `run/build/check --emit` antes de llamarlo cliente de la
  CLI oficial;
- no duplicar completion/semantics dentro de plugins.

### 9.6 Retiro de `compiler-rs`

Esta auditoría no cambia el gate anterior. El orden correcto es: reemplazar o
separar LSP/REPL/AST, retirar dependency/build hook del package Python, aislar
qualification legacy y recién entonces autorizar el borrado físico. No portar
PyO3/schema-v1/schema-v2 para sostener estas herramientas.

### 9.7 Condiciones que cambiarían la recomendación

- Si el LSP deja de ser producto soportado y los IDEs aceptan sólo syntax
  highlighting + CLI, puede retirarse en vez de reconstruirse.
- Si aparece un equipo dedicado a tooling Python, LSP-B podría durar más, pero
  no debe definir semántica.
- Si mediciones muestran que batch Rust satisface latencia en proyectos reales,
  incremental parsing puede posponerse.
- Si usuarios demuestran uso fuerte de REPL científico persistente, se justifica
  diseñar un runtime session oficial; sin esa evidencia, no.

## 10. Plan de transición incremental

### M0 — decisión de producto

- confirmar LSP como superficie soportada;
- decidir si REPL será retirado, histórico descargable u objetivo oficial;
- fijar plazo/EOL de `aether-language` y `aether-compiler-core`.

**Gate:** owner y estado público para LSP, AST y REPL; ninguna implementación.

### M1 — editor analysis contract en `compiler-next` (primer milestone recomendado)

Diseñar y calificar una API Rust que acepte un entry URI/path y overlays de
texto versionados, construya el grafo de módulos y devuelva diagnostics
estructurados con source identity, span, code, severity y phase. Debe admitir
cancelación segura o límites de request y no requerir LLVM/clang.

**Por qué primero:** toda capacidad semántica posterior depende de source IDs,
spans, overlays y módulo graph. Empezar por completion o por el protocol loop
crearía otra capa sobre APIs batch insuficientes.

**Gate:** tests single/multi-file, buffers no guardados, recovery definido,
stale-version suppression, no dependencia legacy y latencia medida.

### M2 — diagnostics autoritativos en el LSP existente

Conectar sólo diagnostics al contrato M1. Mantener el resto estable y marcar
su origen legacy. No agregar features al analyzer Python.

**Gate:** corpus de diagnostics oficial, ambos IDEs, cancelación, versionado y
fallback fail-closed; ningún fallo Python decide aceptación.

### M3 — symbol services

Exponer declarations, resolved identities, types, signatures y references en
compiler-next; migrar document symbols, hover, definition y completion básica.

**Gate:** cross-file/import aliases, shadowing, overload/generics, stale edits y
ausencia de regex como fuente de identidad.

### M4 — servidor Rust

Mover document store, scheduler y handlers a Rust conservando el executable
`aether-lsp`. Portar formatting sólo con contrato explícito. Añadir performance
incremental donde las mediciones lo exijan.

**Gate:** protocol fixtures, VS Code, IntelliJ, shutdown/cancel, malformed
messages, memory/latency y parity funcional seleccionada, no parity semántica
legacy.

### M5 — packaging y IDE closure

Distribuir el nuevo LSP, alinear comandos IntelliJ, separar/retirar entry point
Python y demostrar instalaciones limpias sin `aether-compiler-core`.

**Gate:** wheel/sdist Rust/Python elegidos, PATH discovery cross-platform,
búsquedas negativas y smoke de ambos IDEs.

### M6 — decisión REPL/AST

- si REPL no es prioritario: deprecación y retiro con snapshot histórico;
- si lo es: diseño separado REPL-B con gates de fragments, state y side effects;
- retirar interpreter Python cuando no queden consumers ejecutables.

**Gate:** decisión explícita; no unir este milestone con el LSP ni con el
borrado de `compiler-rs`.

### M7 — retiro legacy coordinado

Ejecutar los gates de `LEGACY_COMPILER_RETIREMENT_AUDIT_V1`, preservar historia,
retirar workflows/scripts/tests/packages legacy y hacer el retiro físico en un
cambio dedicado.

## 11. Gates obligatorios para futuras migraciones

1. `compiler-next` es la única fuente de diagnostics/identidades semánticas.
2. Overlays no guardados participan en análisis multi-file.
3. Cada capability anunciada tiene handler, test protocolar y consumer smoke.
4. Resultados parciales/recovery nunca se presentan como compile success.
5. Cancelación y respuestas obsoletas no publican estado incorrecto.
6. VS Code e IntelliJ usan la CLI oficial y el mismo LSP.
7. Tooling retenido se instala sin `compiler-rs` ni `aether-compiler-core`.
8. Dependencias científicas son extras del producto que realmente las usa.
9. Corpus migrado prueba contratos actuales, no igualdad con Python.
10. REPL declara exactamente qué estado persiste y qué side effects no pueden
    revertirse.
11. No hay commit/push/tag automático ni retiro físico dentro de una auditoría.

## 12. Cierre

Se identificaron capabilities, handlers, tests, consumidores, dependencias y
brechas de fidelity. Se distinguió LSP anunciado de soporte real, se compararon
alternativas, se emitió una recomendación concreta y se definió una transición
con gates. No se modificó código productivo ni se eliminó trabajo del usuario.

Por tanto, **AUDIT CLOSED**.

La migración, deprecación y eliminación quedan **NOT YET AUTHORIZED**.
