# Aether — LEGACY-TOOLS-FUTURE-AUDIT-V1 — Reporte

Estado: **AUDIT CLOSED — MIGRATION NOT YET AUTHORIZED**

Fecha: 2026-11-25

Checkout auditado: `main` @ `eec746d53520a161bdec27497f6789a632eb73f9`

Documento principal:
[LEGACY_TOOLS_FUTURE_AUDIT_V1.md](LEGACY_TOOLS_FUTURE_AUDIT_V1.md)

## 1. Resultado ejecutivo

La auditoría comprobó que:

- el LSP Python es un servidor real y probado, no un stub: implementa sync,
  diagnostics, completion, formatting, document symbols, hover, inlay hints,
  definition y references;
- todas las capabilities que anuncia tienen handler, pero varias son
  document-local, lexicales o regex-assisted y no equivalen a un servicio
  semántico de workspace;
- rename, signature help, code actions, semantic tokens, cancel requests,
  incremental parsing e index de workspace están ausentes;
- diagnostics, completion, hover y navegación dependen del frontend Python
  histórico, no de `compiler-next`;
- el intérprete AST tiene una superficie amplia —scientific builtins, modules,
  OOP, exceptions, collections, IO y plots— pero implementa semántica legacy y
  un modelo de memoria incompatible con la autoridad actual;
- el REPL es un loop de una línea sobre `AetherSession`, con variables/functions
  persistentes y rollback básico, no un compilador interactivo completo;
- LSP/AST/REPL no importan el binding Rust en su ruta normal, pero el wheel que
  los instala obliga `aether-compiler-core` y su build hook lee
  `compiler-rs/Cargo.toml`;
- VS Code usa la CLI oficial, mientras IntelliJ todavía construye la gramática
  de flags legacy contra el executable `aether`.

La recomendación final es LSP Rust sobre `compiler-next`, AST congelado como
histórico y REPL oficial sólo si una decisión de producto justifica diseñar
persistencia sobre la compilación oficial.

## 2. Estado Git inicial y preservación

### 2.1 Preflight

| Dato | Evidencia |
| --- | --- |
| Rama | `main` |
| HEAD | `eec746d53520a161bdec27497f6789a632eb73f9` |
| `origin/main` local | mismo hash |
| `origin/main` remoto | mismo hash, confirmado con `git ls-remote --heads origin main` |
| Relación | 0 ahead, 0 behind |
| Staged | vacío |
| Tracked modificados previos | 2 archivos |
| Untracked previos | 7 archivos |

Commits recientes al inicio:

```text
eec746d5 fix(llvm): reuse borrowed string observations in interpolation
421ff0b3 test(compiler-next): isolate official qualification from legacy compilers
35e1a819 docs(io): align public IO and persistence contracts
6ca7813c docs(repo): record post-assessment git consolidation
cd4fe983 docs(compiler): reconcile F2 F3 and stack qualification
b8ca58b5 fix(frontend): flatten logical-expression traversal
8c720f9d feat(compiler): report shape contract failures by source site
21074cad docs(compiler): define abortive shape contract diagnostics
```

La primera consulta remota falló dentro del sandbox por DNS. Se repitió, con
autorización, únicamente `git ls-remote`; devolvió el HEAD auditado. No se hizo
`fetch` ni se modificaron refs.

### 2.2 Trabajo previo preservado

Tracked preexistentes:

- `examples/ProbandoNR/probandoNR2.ae`;
- `examples/ProbandoNR/probandoNR3.ae`.

Untracked preexistentes:

- `examples/ProbandoNR/.aether-package.lock`;
- `examples/ProbandoNR/probandoNR2`;
- `examples/ProbandoNR/probandoNR3`;
- `examples/assessment/data-processor/.aether-package.lock`;
- `examples/assessment/expense-tracker/.aether-package.lock`;
- `probandoNR3C`;
- `tmp_lambda_test.ae`.

El diff previo era 2 archivos, 24 inserciones y 16 eliminaciones. No se usó
reset, clean, stash, checkout, commit, push ni tag. No se ejecutaron binarios
untracked ni se editaron esos archivos.

## 3. Fuentes inspeccionadas

### 3.1 Autoridad y auditorías previas

- `docs/architecture/COMPILER_AUTHORITY.md`;
- `docs/architecture/LEGACY_COMPILER_RETIREMENT_AUDIT_V1.md`;
- `docs/architecture/LEGACY_COMPILER_RETIREMENT_AUDIT_V1_REPORT.md`;
- `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md`;
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`;
- `docs/compiler/EXCEPTION_TOOLING_QUALIFICATION.md`;
- `README.md` y `docs/aether/BACKEND_FEATURE_PARITY.md`.

### 3.2 LSP y helpers

- `src/aether_lsp/server.py`, `run_file.py`, `__init__.py`;
- `src/aether/language_service.py`, lexer, parser, typechecker y formatter;
- `src/autocomplete_engine.py`, `command_catalog.py`,
  `document_symbols.py`;
- `tests/test_aether_lsp_server.py`, `test_aether_lsp_run_file.py` y
  `tests/aether/test_language_service.py`.

El server tiene 1.076 líneas y su suite focal directa tiene 40 tests. El helper
`run_file` tiene cuatro tests adicionales; el language service, 22.

### 3.3 Interpreter/session/REPL

- `src/aether/interpreter.py` (3.602 líneas);
- `src/aether/session.py`, `pipeline.py`, `runner.py`, `cli.py`;
- `src/aether/ast.py`, `types.py`, `scope.py`, `modules.py`;
- stdlib core, IO, text, plots y linear algebra;
- `src/plot_backend.py`;
- tests de session, plots, pipeline, CLI y búsquedas de consumers en la suite.

### 3.4 Packaging y bridges

- `pyproject.toml`, `setup.py`, `requirements.txt`, `MANIFEST.in`, `uv.lock`;
- manifests de `compiler-rs` y distribución `aether-compiler-core`;
- imports/discovery de `aether_compiler_core` bajo `src/aether/ir` y
  `src/aether/ssa`;
- entry points y release scripts.

### 3.5 `compiler-next`

- workspace y manifests Cargo;
- `aether-frontend` lexer/parser/diagnostics/AST/HIR/types;
- `aether-driver::CompilationSession`, análisis/check/build/run;
- CLI oficial y su gramática pública;
- búsquedas de LSP, editor services, incremental/caches y dependencies LSP.

No se encontró implementation LSP ni dependency `lsp-types`/`tower-lsp` en
`compiler-next`. Sí existen `SourceFile`, `SourceId`, `Span`, diagnostics,
AST/HIR con identities y un module graph batch reutilizables.

### 3.6 IDEs

- sources, manifest, README y tests de `vscode-extension`;
- sources Kotlin, plugin XML, README, Gradle manifest y tests de
  `tools/intellij-aether`.

## 4. Evidencia comprobada

### E1 — capabilities reales del LSP

`_initialize_result` anuncia full-text sync, completion, formatting, document
symbols, hover, inlay hints, definition y references. `_handle_message` tiene un
branch y una función de resultado para cada una. No se encontraron providers
sin handler.

### E2 — ausencias verificadas

Las búsquedas por providers, methods y cancel request no devolvieron rename,
signature help, code actions, semantic tokens ni `$/cancelRequest`. El server
no procesa `workspace/didChangeWatchedFiles` y no tiene workspace index.

### E3 — navegación limitada

Definition siempre devuelve el URI actual. References ejecuta un regex por el
spelling en el source actual y sólo acota especialmente el scope de catch
binders. Document symbols/completion/hover usan extractores propios y tablas
legacy. Esto prueba existencia funcional, no precisión semántica cross-file.

### E4 — diagnostics multi-file parciales

El test abre un documento que importa un módulo en el mismo directorio y pasa.
El source root se deriva del URI. No existe overlay store compartido con el
loader de imports; sólo el documento request se toma de memoria.

### E5 — frontend de `compiler-next` reutilizable pero batch

El frontend publica `lex`, `parse_source`, diagnostics/spans, AST, HIR y
resolved identities. El driver descubre y parsea el catálogo transitivo una vez
en `CompilationSession`. No expone documentos versionados, overlays, recovery
parcial, symbol queries, invalidación ni cancelación.

### E6 — interpreter amplio y no normativo

El dispatch cubre variables, aliases, structs/classes/interfaces/enums,
assignments, loops, functions, returns, exceptions, calls, collections,
index/slice, field access, imports y interpolation. Builtins incluyen IO, math,
linear algebra y plots. La amplitud no resuelve las diferencias de tipos,
ownership, packages, OOP y generics con el compiler oficial.

### E7 — persistencia REPL acotada

`AetherSession` reutiliza checker/interpreter y hace snapshot/deepcopy antes de
cada entrada. Ocho tests prueban variables, funciones, rollback básico, scopes
y aislamiento. El snapshot omite tablas runtime/semantic relevantes; no se
consideró rollback total.

### E8 — dependency de core es packaging, no runtime AST/LSP

No hay import de `aether_compiler_core` en LSP, interpreter o session. El
`pyproject.toml` lo fija como dependency obligatoria y `setup.py` lee
`compiler-rs/Cargo.toml`. Por tanto no puede instalarse soportadamente separado
aunque la ruta normal no llame al binding.

### E9 — dependencias científicas llegan al LSP

`aether_lsp.server` importa el package público `aether`; `aether.__init__`
importa runner/session; interpreter importa `plot_backend` y linear algebra.
NumPy y SciPy se importan eager. Matplotlib es lazy al inicializar plotting.
SymPy/PyQt6 no tienen import directo localizado en `src`.

### E10 — divergencia de clientes IDE

VS Code genera `run`, `check` y `--emit fase`, coincidente con la CLI Rust.
IntelliJ genera flags legacy aunque resuelve `aether`. Esta evidencia se obtuvo
por comparación directa con `compiler-next/crates/aether-cli/src/lib.rs`.

## 5. Tests ejecutados

| Comando | Resultado |
| --- | --- |
| `python -m pytest ...` | **BLOCKED**: `/usr/bin/python` no tiene pytest |
| `.venv/bin/pytest -q tests/test_aether_lsp_server.py tests/test_aether_lsp_run_file.py tests/aether/test_language_service.py tests/aether/test_aether_session.py tests/aether/test_plots.py` | **PASS — 94 passed en 3.34 s** |
| `.venv/bin/pytest -q tests/test_aether_cli.py -k 'repl or backend_ast'` | **PASS — 4 passed, 149 deselected** |
| `npm test` en `vscode-extension/` | **PASS — compile TypeScript y 4/4 tests** |
| `./gradlew :tools:intellij-aether:test --offline` | **BLOCKED** antes de tests: wrapper intentó crear un `.lck` bajo `/home/blasm/.gradle`, read-only en sandbox |

Los 94 tests focales se descomponen en 40 de server LSP, 4 de LSP run-file, 22
de language service, 8 de session y 20 casos de plots (incluyendo
parametrización). El test subprocess verifica framing real, initialize,
diagnostics, completion, document symbols y shutdown.

La selección CLI ejercitó REPL y ejecución AST explícita. No se interpretó la
suite histórica completa como qualification del lenguaje oficial.

## 6. Tests omitidos o bloqueados

- No se ejecutó el workspace completo de `compiler-next`: no hubo cambios en
  código y la auditoría sólo necesitó inspeccionar APIs batch/editor.
- No se ejecutó `compiler-rs`: el defecto F4 y su retiro son objeto de la
  auditoría previa; no se autorizaron reparaciones legacy.
- No se ejecutó toda la suite Python: es extensa, mezcla compiladores/backends
  históricos y no aporta un gate proporcional a este cambio documental.
- IntelliJ quedó bloqueado por el directorio Gradle externo read-only. No se
  pidió descargar dependencias ni se reubicó/copió el cache para evitar ampliar
  la auditoría. Sus tests/source se inspeccionaron.
- No se hizo smoke manual dentro de VS Code o IntelliJ hosts.
- No se midió latencia/memoria en proyectos grandes; no existe corpus de
  performance LSP definido.
- No se probaron consumers externos, package indexes ni instalaciones privadas.

## 7. Dependencias identificadas

### 7.1 Obligación de distribución

`aether-language` requiere:

- `aether-compiler-core==1.0.0rc4`;
- NumPy 2.4.2;
- SciPy 1.17.1;
- SymPy 1.14.0;
- Matplotlib 3.10.8;
- PyQt6 6.8–6.x.

El package publica juntos `aether-legacy`, `aether-lsp` y probes SSA. El core se
resuelve localmente desde `compiler-rs` en uv, y el sdist incluye su manifest.

### 7.2 Runtime

- LSP: `aether`, autocomplete/command/document helper modules;
- diagnostics: lexer/parser/typechecker/modules Python;
- AST/REPL: interpreter, stdlib, text IO, plot backend, NumPy/SciPy;
- plotting: Matplotlib lazy y backend GUI dependiente del host;
- legacy IR/SSA: binding o companions `aether_compiler_core` lazy.

### 7.3 Desarrollo/consumidores

- pytest para Python;
- Node/TypeScript/vscode-languageclient para VS Code;
- Gradle + IntelliJ SDK para plugin;
- Rust/Cargo para compiler workspaces;
- VS Code e IntelliJ como consumers directos de `aether-lsp`.

## 8. Riesgos pendientes

1. Diagnostics LSP pueden contradecir al compilador oficial.
2. Navigation lexical puede modificar el símbolo equivocado si se agrega rename
   sin identities.
3. Un bridge batch sin overlays diagnosticaría fuentes guardadas, no el estado
   real del editor.
4. Full reparse síncrono sin cancelación puede degradar UX al crecer proyectos.
5. El split de wheel puede conservar accidentalmente NumPy/SciPy en un LSP que
   no los necesita conceptualmente.
6. El REPL puede duplicar side effects si se implementa como transcript AOT.
7. La documentation/acción AST puede hacer creer que hay dos autoridades.
8. IntelliJ no está alineado con la CLI oficial aunque su LSP sí apunta al entry
   point compartido.
9. Consumers externos de `aether-language`/`aether-compiler-core` siguen
   **UNRESOLVED**.
10. Retirar `compiler-rs` antes del split rompe build e instalación.

## 9. Limitaciones de la auditoría

- La clasificación de LSP se limita al protocolo/código/tests del repositorio;
  no asegura interoperabilidad completa con todas las versiones de clients.
- La suite amplia del interpreter contiene miles de tests indirectos. Se
  inspeccionaron categorías y tests focales, no se produjo una matriz por cada
  builtin.
- “Alternativa disponible en compiler-next” significa primitive/API interna
  reutilizable. No implica que exista un editor service listo.
- No se eligió una library LSP Rust ni un formato IPC concreto; eso pertenece
  al diseño de M1/M4.
- No se estimaron horas-persona porque no hay baseline de performance, release
  targets ni decisión REPL de producto.
- No se modificaron documentos históricos para corregir wording desactualizado;
  se registraron las contradicciones.

## 10. Archivos creados

- `docs/architecture/LEGACY_TOOLS_FUTURE_AUDIT_V1.md`;
- `docs/architecture/LEGACY_TOOLS_FUTURE_AUDIT_V1_REPORT.md`.

No se modificó código productivo, manifests, tests ni trabajo personal.

## 11. Qualification final

| Gate | Resultado |
| --- | ---: |
| branch/HEAD/upstream remoto verificados | PASS |
| tracked/staged/untracked inventariados | PASS |
| autoridad y auditoría previa inspeccionadas | PASS |
| capabilities comparadas con handlers | PASS |
| tests LSP/session/REPL focales | PASS |
| VS Code compile/tests | PASS |
| IntelliJ tests | BLOCKED por cache externo read-only; source/tests inspeccionados |
| manifests/dependencies/imports inspeccionados | PASS |
| frontend/driver `compiler-next` inspeccionados | PASS |
| `git diff --check` sobre tracked | PASS |
| whitespace de cada entregable nuevo con `git diff --no-index --check` | PASS, sin diagnostics de whitespace; status 1 esperado por contenido nuevo |
| código productivo modificado | PASS, ninguno |
| migración/retiro iniciado | PASS, no |
| commit/push/tag | PASS, no realizados |

## 12. Estado final

Se identificaron capacidades y consumidores, se distinguieron capabilities de
implementación y qualification, se localizaron los acoplamientos que impiden
retirar `compiler-rs`, se compararon LSP-A/B/C y REPL-A/B/C y se propuso una
secuencia incremental con gates.

La prueba IntelliJ bloqueada no impide la decisión arquitectónica: no hay
cambio Kotlin que calificar y la incompatibilidad CLI se demuestra por source.
Queda registrada como gate futuro, no como PASS.

El estado Git final conserva exactamente los dos tracked y siete untracked
personales del preflight y agrega únicamente los dos documentos de esta
auditoría como untracked. Rama, HEAD y upstream permanecen sin cambios.

Por tanto, **AUDIT CLOSED**.

No se autoriza todavía migración, deprecación, retiro físico de `compiler-rs`
ni eliminación del intérprete/REPL/LSP Python.
