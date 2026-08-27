# Auditoría arquitectónica del compilador post-RUST-4.5

Fecha: 2026-08-27

Alcance: análisis y planificación; no migración, cambio productivo ni commit.

Baseline conceptual: `RUST_SSA_SHADOW_INDEPENDENT_PRODUCTION_PROMOTED`.

En este informe, **observado** significa seguido en llamadas o medido; **inferido**
significa consecuencia arquitectónica de esas llamadas; **recomendado** es una
decisión propuesta, no estado actual. El JSON compañero es
[`post_rust_4_5_compiler_architecture_audit.json`](post_rust_4_5_compiler_architecture_audit.json)
y la medición reproducible está en
[`audit_post_rust_4_5_pipeline.py`](../../scripts/audit_post_rust_4_5_pipeline.py).

## 1. Resumen ejecutivo

**Observado.** Una compilación native normal todavía es orquestada casi por
completo en Python. De 21 familias de etapas desde CLI hasta runtime, Python
participa en 18 (aproximadamente 86% por conteo de etapas, no por LOC ni por
tiempo). Rust es autoridad en el bloque Initial-IR schema-v1 → SSA schema-v2 y
verifica su `OwnedSsaModule`; `GeneralSSABuilder` no se instancia en el default.
Clang y el ejecutable final son los otros bloques no Python.

La deuda principal no es “falta migrar el lexer”. Es que no existe un límite
único de compiler core: un objeto Initial IR de Python se verifica repetidamente,
se normaliza en Python, cruza JSON hacia un companion persistente, vuelve como
schema v2 y atraviesa más verificación/refinement Python antes de un backend LLVM
también Python. En O0 se observaron **3 llamadas a `IRVerifier.verify` y 5 a
`SSAVerifier.verify` por build**.

Hay además dos discrepancias de autoridad:

- `implementation_language_ownership.json` dice que Initial IR verification es
  Rust/RP3, pero `LLVMBuilder.emit_llvm()` crea `IRBackend()` sin
  `VerifierAuthorityPipeline`; `IRBackend.verify()` ejecuta directamente el
  `IRVerifier` Python.
- El mismo registro todavía describe SSA construction/verification como
  Python/RP2, mientras el default de `SSALoweringAuthorityConfiguration` es
  `RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED` y la clausura RUST-4.5 está promovida.

**Performance observada.** No hay un único cuello de botella:

- cold y pequeño: importar `aether.cli` cuesta 447.2 ms de mediana, frente a
  12.7 ms de un proceso Python vacío; un build de `hello.ae` cuesta 530.1 ms;
- warm y pequeño: clang/link domina (39–41 ms sobre 42–54 ms);
- warm y grande: `expense_tracker/Main.ae` tarda 1.199 s y domina Python:
  verificación SSA, verificación Initial IR, refinement y materialización de IR
  son los mayores centros; el request Rust completo tarda 107.2 ms.

En la suma de las medianas de los siete workloads (1.779 s), las fases Python
nombradas, excluido clang, representan 66.0%; clang 16.9%; el request Rust con
transporte 7.4%; y coordinación/JSON no atribuida 9.7%. La selección incluye a
propósito el programa grande, por lo cual no es un promedio de uso real.

**Recomendación #1.** El próximo milestone debe ser
`CORE-1.0_IN_PROCESS_COMPILER_CORE_BOUNDARY`: activar `aether-python` como una
frontera Rust in-process que reproduzca primero el resultado del companion sin
cambiar semántica ni autoridad. No es una migración de frontend. Su propósito es
evitar que cada siguiente componente cree otro protocolo Python↔Rust y preparar
una sola importación del Initial IR para verification/lifecycle/SSA.

## 2. Pipeline productivo real

### 2.1 Entry points

El entry point instalado es `aether = aether.cli:main` (`pyproject.toml`). El
comando default `aether file.ae` termina en `cli._execute_file(...,
backend="llvm")`, `cli._run_native()`, `LLVMRunner.run()`. `aether build` usa
`cli._main_build()`, `cli._build_native()` y `LLVMBuilder.build()`. Ambos comparten
el pipeline de compilación; `run` agrega la ejecución del binario temporal.

La fuente se lee completa como UTF-8 en `cli._read_source`. Imports adicionales
se resuelven durante `TypeChecker._load_module()` mediante
`modules.resolve_file_module_path()` y vuelven a pasar por lexer/parser/checker.

### 2.2 Traza source → executable

| # | Etapa real y entry point | Lenguaje / autoridad | Entrada → salida | Frecuencia y frontera |
|---:|---|---|---|---|
| 1 | CLI/source: `cli.main`, `_main_build`, `_read_source` | Python / Python | argv+path → `str` | siempre; proceso Python |
| 2 | `lexer.lex`, `Lexer.scan_tokens` | Python / Python | source → `list[Token]` | siempre por módulo; in-process |
| 3 | `Parser.parse` + dataclasses en `ast.py` | Python / Python | tokens → `ast.Program` | siempre por módulo; in-process |
| 4 | `TypeChecker.check` | Python / Python | AST → tablas semánticas + AST aceptado | siempre; carga imports recursivos |
| 5 | `build_checked_program` | Python / Python | checker/module caches → `CheckedProgram` | siempre; IDs estables de módulo/símbolo |
| 6 | `normalize_entry_point` | Python / Python | AST raíz → AST con `main` explícito | siempre |
| 7 | `validate_backend_capabilities(..., NATIVE)` | Python / Python | `TypedProgram` → accept/error | siempre en native |
| 8 | `combine_checked_program`, `IRLowerer.lower_checked_program` | Python / Python | checked graph → Python `IRModule` | siempre; multi-module se combina y manglea |
| 9 | `IRBackend.verify` → `IRVerifier.verify` | **Python observado**; Rust declarado | `IRModule` → mismo módulo verificado | 3 veces en O0 observado |
| 10 | `expand_lifecycle` en `shadow_independent` | Python / Python observado | Initial IR → normalized IR | siempre antes del companion |
| 11 | `ir_module_to_dto`, `json.dumps` | Python / adapter | Python IR → schema-v1 bytes | seis materializaciones DTO observadas |
| 12 | `aether-ssa-shadow --persistent` | Rust / Rust | framed schema v1 → framed schema v2 | subprocess persistente por proceso Python |
| 13 | `ssa_module_from_dto` | Python / adapter | schema v2 → Python `SSAModule` | siempre |
| 14 | `SSAVerifier`, `verify_ssa_refinement` | Python / aceptación mandatory | normalized IR + SSA → SSA aceptado | 5 generic SSA verifies + 1 refinement |
| 15 | `build_optimizer_pipeline` | Python / Python | IR → IR | sólo O1/O2 |
| 16 | `build_ssa_optimizer_pipeline` | Python / Python | SSA → SSA | O0: sólo input verify; O1/O2: pases+verifies |
| 17 | `NativeBoundaryVerifier` + verify final en `LLVMBackend.emit` | Python / Python | SSA → backend input aceptado | siempre |
| 18 | `LLVMPrinter.print_module` y `*_runtime.py` | Python / Python | SSA → LLVM textual + runtime embebido | siempre; helpers según features |
| 19 | `LLVMBuilder._run_clang` | Python + clang externo | `.ll` → executable | siempre; subprocess y archivo temporal |
| 20 | `LLVMRunner._run_executable` | nativo | executable+argv → exit/stdout/stderr | sólo comando run/default, no build |
| 21 | helpers emitidos + libc/libm/OS | LLVM generado + C ABI externo | llamadas nativas → efectos runtime | según features/plataforma |

Evidencia primaria: `src/aether/cli.py`, `pipeline.py`, `modules.py`,
`ir/lowering.py`, `ir/module_lowering.py`, `ssa/shadow.py`,
`ssa/shadow_independent.py`, `backend/llvm/build.py`, `backend/llvm/backend.py` y
`backend/llvm/run.py`.

### 2.3 Qué significan semantic, resolution, constants y overloads aquí

No son subsistemas aislados con IR propio:

- declaración y resolución de nombres, imports/visibilidad, símbolos, alias,
  signatures, tipos, mutabilidad, ownership de colecciones, efectos de
  excepciones y conversiones implícitas viven entrelazados en `TypeChecker`;
- `build_checked_program()` materializa luego identidades estables
  `ModuleId`/`SymbolId`, pero consume decisiones del checker; no vuelve a resolver;
- no existe overload resolution general de funciones de usuario: `functions` es
  un mapa nombre→`FunctionSymbol`. Sí hay selección semántica por tipo para
  operadores numéricos, builtins, native members, constructores y métodos
  (`_call_type`, `_method_call_type`, `infer_builtin_type`, `promote_numeric`,
  `_can_convert_type`);
- constantes literales se crean en lexer/parser; restricciones y evaluación
  estática puntual (rangos i32, exponentes, dimensiones, builtin constants) viven
  en typechecker/module lowering; folding general es un pase IR/SSA de O1/O2.

Por eso migrar “name resolution” o “constant evaluation” solos partiría
`TypeChecker` por límites que hoy no existen.

### 2.4 Orden exacto dentro de RUST-4.5

`SSAPipeline.run(IRModule)` primero llama otra vez a `IRBackend().verify`. Luego
`lower_with_shadow_independent_rust_authority()` hace:

```text
Python IRVerifier
  → Python expand_lifecycle
  → Python schema-v1 DTO/snapshot + JSON
  → persistent Rust companion
       deserialize
       normalize_lifecycle_v1 (idempotente/no-op porque Python ya expandió)
       lower_verified_ir_to_ssa_v1
       verify_owned_ssa
       materialize schema v2
  → Python schema-v2 import
  → Python SSAVerifier
  → two same-input integrity checks
  → Python independent refinement verifier
  → Python SSAVerifier final
  → SSAPipeline.verify (Python)
  → O0 optimizer input verify (Python)
  → LLVMBackend final SSA verify (Python)
```

La traza medida confirma `python_general_ssa_builder_instantiated=false`,
`python_ssa_lowering_executed=false`, `rust_ssa_lowering_executed=true` y todas
las etapas de acceptance/refinement ejecutadas una vez. La observación “Python
SSA todavía corre” debe referirse a import/model/verifiers/refinement/optimizer,
no al `GeneralSSABuilder`.

## 3. Mapa de ownership por lenguaje

| Lenguaje | Ownership observado hoy | Allocation recomendada |
|---|---|---|
| Python | driver, frontend, semantics, AST/CheckedProgram/Initial IR, wiring/verificación real de Initial IR, lifecycle previo al companion, SSA import/refinement/generic verification, optimizer, LLVM emitter/runtime templates, tooling | Mantener tooling, qualification, oracles y scripts. Retirar gradualmente del core sólo donde el límite sea coherente. |
| Rust | owned Initial IR importer, lifecycle implementation, SSA lowering, owned SSA verifier; Initial IR verifier existe pero no está en el wiring normal | Compiler core, owned representations, verifiers, lifecycle/refinement, analyses/optimizer y native backend. |
| C | no runtime C versionado en el repo; el LLVM emitido llama ABI compatible con libc/OS | ABI estable del runtime y shims mínimos, no lenguaje general del compiler. |
| C++ | ninguno propio; clang/LLVM es toolchain externo | Sólo adapter si una integración LLVM sin API C/Rust lo justifica. |
| Aether | ejemplos, corpus y workloads; no compiler/stdlib canónico self-hosted | Tooling/stdlib de alto nivel primero; parser opcional mucho después. |

La división objetivo previa sigue siendo razonable. El ajuste es de secuencia:
antes de migrar más algoritmos, hay que crear el límite Rust in-process y una
fuente única de verdad para authority/acceptance.

## 4. Inventario Python del compiler

LOC es sólo tamaño aproximado (`wc -l`, incluye comentarios/blancos), nunca el
criterio de prioridad.

| Paquete/responsabilidad | LOC aprox. | ¿Critical path? | Representación/coupling | Estado y lenguaje plausible |
|---|---:|---|---|---|
| `cli.py` + `pipeline.py` | 1,430 | sí | fan-out a todas las capas | core driver Rust; project tooling puede ser Aether después |
| lexer/tokens/parser/AST | 2,473 | sí | dueño de Token/AST; formatter/LSP | Rust Stage0; parser Aether opcional futuro |
| typechecker/modules/symbols/scope/types/entry/capabilities | 9,137 | sí | AST, imports, stdlib, LSP, IR | bloque semántico Rust, no piezas aisladas |
| IR lowering/module lowering/model/types/DTO | 9,987 | sí | dueño Python Initial IR y schema v1 | Rust cuando exista typed input estable |
| `ir/verifier.py` | 3,964 | sí, 3 calls | Initial IR/lifecycle | ya existe Rust: arreglar wiring, conservar oracle |
| `ir/lifecycle.py` | 1,172 | sí | ownership Initial IR→SSA | ya existe Rust: promover coherentemente |
| SSA bridge/model/DTO/verifier/refinement | 7,010 | sí | ambos schemas + optimizer/backend | Rust core + binding fino |
| builders SSA Python/CFG/phi/rename | 3,001 | no default | oracle y rollback | mantener Python por ahora |
| optimizers IR+SSA | 4,006 | O0 verify; transforms O1/O2 | IR/SSA/verifiers | Rust |
| backend LLVM/runtime/toolchain | 12,437 | sí | SSA, ABI, plataforma, clang | Rust + runtime C ABI |
| AST runtime/session/language service/formatter | 4,643 | AST mode/tooling | AST, runtime values, plotting | Python reference/tooling; self-host selectivo |
| LSP/editor/plot tooling | 3,909 | no native path | source/AST/LSP | Python hasta tener semantic API incremental |

Estado mutable: `TypeChecker` y `IRLowerer` guardan tablas por instancia;
`AetherSession` conserva estado de REPL; `ssa.shadow` mantiene clients persistentes
process-global y un cache de clients qualification; LLVM printer conserva estado
por emisión. No se observó un global semántico compartido entre compilaciones que
habilite migrar una pieza sin definir ownership/invalidation.

Una deuda de startup independiente: importar el paquete `aether` importa
`language_service`→`runner`→`session`→`interpreter`→`plot_backend`, y éste importa
NumPy aun para `aether build`. Esto explica buena parte del cold cost. Es una
optimización válida de import graph, pero no reemplaza el trabajo arquitectónico.

## 5. Critical path, modos y código de referencia

### A. Mandatory production

IDs 1–14 y 16–19 de la tabla; id 20 para `run`. En default O0 no hay pases de
transformación, pero `SSAOptimizerPipeline.run()` verifica el input.

### B. Feature/profile-dependent

Imports multi-module; IR/SSA transforms O1/O2; helpers LLVM de strings,
collections, classes, exceptions, process args, math y file I/O; `-lm`; y ramas
de ABI Linux/Darwin/Windows.

### C. Diagnostic/development

`--tokens`, `--ast`, `--emit-ir`, `--emit-cfg`, `--emit-ssa`, `--emit-llvm`,
`--check`, `bench`, AST/IR execution backends y profiler LLVM opt-in.

### D. Qualification/test

`VerifierAuthorityPipeline`/canary de Initial IR Rust, differential Rust/Python
SSA, platform packaging, soak, mutation and deep-CFG qualification. Estos no se
contabilizan como dependencia productiva default.

### E. Rollback/reference

`GeneralSSABuilder`, el builder pattern y los modos
`python_ssa_only`, `python_ssa_authority_rust_shadow` y
`rust_ssa_authority_python_shadow`. El default fail-closed no cae automáticamente
a Python SSA.

### F. Dead/legacy

No se probó que una implementación compiler sea inalcanzable. El pattern builder
es accesible por `--emit-ssa --ssa-builder=pattern`; `GeneralSSABuilder` tiene
modos explícitos y qualification. `aether-python` es un seam vacío deliberado,
no código productivo muerto. Sí hay metadata de ownership obsoleta y debe
corregirse en el siguiente milestone de governance.

## 6. Medición reproducible

Comando ejecutado:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_post_rust_4_5_pipeline.py \
  --companion compiler-rs/target/release/aether-ssa-shadow \
  --output /tmp/post-rust-4-5-timing.json --rounds 7 --warmups 2
```

Linux x86_64, CPython 3.14.7, clang 22.1.8, companion release, O0 default. Cada
workload tuvo 2 warmups y 7 muestras. Se reporta mediana, MAD, mínimo y máximo.
Cold crea Python, companion y clang nuevos. Warm conserva Python y un companion
persistente. La instrumentación envuelve métodos desde el caller y usa sólo el
seam qualification; no modifica producción.

El checkout no tenía companion instalado en `/usr/libexec/aether/ssa-shadow`.
La campaña inyectó el release binary existente con el mecanismo qualification
oficial. Eso mide la ruta productiva lógica pero no afirma que este checkout sea
una instalación empaquetada completa.

### 6.1 Total cold vs warm

| Workload | Cobertura | Warm mediana ± MAD | Cold mediana ± MAD |
|---|---|---:|---:|
| `hello.ae` | tiny | 41.9 ± 0.4 ms | 530.1 ± 4.2 ms |
| `ir/sumTo.ae` | function/control/numeric | 47.0 ± 0.3 ms | 539.1 ± 6.5 ms |
| parity `strings.ae` | strings | 53.9 ± 0.9 ms | 550.8 ± 3.6 ms |
| `particles.ae` | collection/struct | 86.9 ± 1.4 ms | 591.5 ± 8.9 ms |
| `Sorts/Main.ae` | multi-module/collections/exceptions | 96.8 ± 0.3 ms | 588.1 ± 3.5 ms |
| `numerical_methods/main.ae` | multi-module/numeric/functions | 253.2 ± 2.4 ms | 749.0 ± 7.5 ms |
| `expense_tracker/Main.ae` | large/mixed | 1,199.1 ± 6.9 ms | 1,694.9 ± 4.7 ms |

Baseline de proceso: Python vacío 12.7 ± 0.8 ms; `import aether.cli` 447.2 ±
7.2 ms. La diferencia de 434.5 ms es import graph/dependencies, no trabajo del
programa Aether.

### 6.2 Breakdown warm agregado

Suma de medianas por workload: 1.7789 s. Esta suma pondera deliberadamente el
expense tracker; sirve para atribuir el corpus, no para predecir un usuario.

| Fase | s | share |
|---|---:|---:|
| clang/link externo | 0.3006 | 16.9% |
| Python SSA verification (5/build) | 0.2274 | 12.8% |
| Python Initial IR verification (3/build) | 0.1805 | 10.1% |
| Python IR DTO/integrity | 0.1645 | 9.2% |
| Python refinement | 0.1561 | 8.8% |
| Python semantics/typecheck/module load | 0.1501 | 8.4% |
| Python LLVM text emission | 0.0985 | 5.5% |
| Python schema-v2 import | 0.0691 | 3.9% |
| Python Initial IR construction | 0.0664 | 3.7% |
| Python lifecycle | 0.0401 | 2.3% |
| root parser + lexer | 0.0182 | 1.0% |
| otros Python nombrados | 0.0038 | 0.2% |
| request Rust completo (incluye transport) | 0.1309 | 7.4% |
| coordinación/JSON residual | 0.1727 | 9.7% |

Las fases Python nombradas excluyendo clang suman 66.0%. Para expense tracker,
el request companion tiene mediana 107.2 ms, de los cuales Rust reporta ~94.6 ms
de compute; el resto es transporte/encoding/decoding/coordinación. El Rust
intrínseco se concentra en SSA lowering (73.8 ms), no en lifecycle (1.2 ms).

### 6.3 Interpretación

- Python no es un bottleneck universal: clang domina los programas pequeños en
  proceso caliente.
- Python sí domina el programa grande y el cold startup.
- Migrar lexer+parser por performance atacaría ~1% warm del corpus.
- La motivación primaria del siguiente milestone es **arquitectura**, con un
  beneficio secundario grande al consolidar verificación/representaciones.
- O1/O2 tienen otro régimen: `POST_LIFECYCLE_INDEX_PERFORMANCE_REASSESSMENT.md`
  muestra optimizer como centro esperado, especialmente O2. No extrapolamos O0.

## 7. Grafo de dependencias y coste de fronteras

```text
source
  ↓
Token ───────────────→ parser/formatter/LSP
  ↓
AST
  ↓
TypeChecker mutable tables ─→ language service/AST interpreter
  ↓
CheckedProgram(ModuleId/SymbolId)
  ↓
combined/mangled AST
  ↓
Python Initial IR ─→ Python verifier/lifecycle/IR optimizer
  ↓ schema-v1 JSON (subprocess)
Rust owned IR → Rust SSA + Rust owned verifier
  ↓ schema-v2 JSON
Python SSA ─→ refinement/verifier/SSA optimizer
  ↓
Python LLVM emitter/runtime templates
  ↓ .ll file
clang/linker → executable → libc/OS
```

Consecuencias:

- lexer solo obliga a mantener Token Python o serializar tokens; no desbloquea
  semantics;
- parser solo obliga a duplicar/versionar AST y afecta formatter/LSP;
- name resolution separado de typechecker duplica symbols/types/diagnostics;
- Initial IR construction separado de semantics exige un typed-AST schema hoy
  inexistente;
- optimizer y backend ya tienen límites coherentes sobre IR/SSA, pero migrarlos
  con subprocesses nuevos multiplicaría transporte;
- lifecycle, SSA y verifiers pertenecen naturalmente al mismo owned core y ya
  tienen implementaciones Rust parciales/completas.

RUST-3/4 enseñó que companion startup se amortiza en proceso persistente, pero
JSON, materialización doble, imported verification y differential work no
desaparecen. Una segunda o tercera frontera persistente perpetuaría el problema.
La próxima frontera debe ser una librería in-process, no otro protocolo.

Opciones evaluadas:

| Opción | Evaluación |
|---|---|
| componentes individuales + companions | Rechazada: maximiza fronteras temporales |
| frontend completo ahora | Prematuro: typed representation inestable y gran riesgo semántico |
| Rust in-process core | Preferida: una importación, ownership y errores tipados; `aether-python` ya reserva el seam |
| conservar companion | Sí como rollback/qualification, no como patrón para nuevas migraciones |
| mover driver completo ya | Prematuro: sólo cambia quién orquesta representaciones todavía Python |
| optimizer/backend como bloque posterior | Coherente una vez que SSA permanece owned en Rust |

## 8. Matriz de candidatos

Escala 1=bajo, 5=alto. En complejidad, riesgo y fan-out, 5 es costo. Abreviaturas:
Crt criticality, Perf, Lev leverage, Py capacidad de sacar Python, Iso, Rep
stability, Cx, Risk, Tests, Or oracle, XPlat risk, Fan, SH self-hosting y Maint.

| Rank | Candidato | Crt | Perf | Lev | Py | Iso | Rep | Cx | Risk | Tests | Or | XPlat | Fan | SH | Maint |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | in-process compiler-core boundary | 5 | 4 | 5 | 2 | 5 | 5 | 3 | 3 | 5 | 5 | 4 | 4 | 1 | 5 |
| 2 | remaining SSA/refinement acceptance | 5 | 5 | 5 | 4 | 4 | 4 | 4 | 5 | 5 | 5 | 3 | 4 | 1 | 5 |
| 3 | lifecycle normalization | 5 | 3 | 4 | 2 | 5 | 5 | 2 | 5 | 5 | 5 | 3 | 3 | 1 | 4 |
| 4 | optimizer | 3 | 5 | 4 | 3 | 4 | 4 | 5 | 5 | 5 | 4 | 3 | 4 | 1 | 5 |
| 5 | LLVM/native backend orchestration | 5 | 4 | 5 | 4 | 4 | 3 | 5 | 5 | 5 | 4 | 5 | 5 | 1 | 5 |
| 6 | Initial IR construction | 5 | 3 | 5 | 3 | 3 | 3 | 5 | 5 | 5 | 4 | 3 | 5 | 2 | 5 |
| 7 | semantic/typechecker | 5 | 3 | 5 | 4 | 2 | 2 | 5 | 5 | 4 | 2 | 3 | 5 | 1 | 5 |
| 8 | name/symbol resolution | 5 | 2 | 4 | 3 | 2 | 2 | 4 | 5 | 4 | 2 | 2 | 5 | 2 | 4 |
| 9 | parser | 5 | 1 | 3 | 2 | 4 | 4 | 4 | 4 | 5 | 5 | 2 | 4 | 5 | 3 |
| 10 | lexer | 5 | 1 | 2 | 1 | 5 | 5 | 2 | 3 | 5 | 5 | 2 | 2 | 5 | 2 |
| 11 | whole compiler driver | 5 | 2 | 5 | 5 | 1 | 2 | 5 | 4 | 4 | 3 | 5 | 5 | 2 | 5 |

No se suman puntajes: rank 1 gana porque cambia la geometría de futuras
migraciones. Rank 2 tiene mayor upside directo, pero hacerlo antes de la frontera
obliga a crear o extender protocolos. Lifecycle es técnicamente más fácil porque
Rust ya lo implementa, pero promoverlo aislado todavía deja refinement Python y
dos representaciones. Optimizer/backend son buenos bloques posteriores. Frontend
queda detrás por coupling y falta de oracle semántico independiente.

Cobertura/oráculos relevantes:

- IR: `test_ir_verifier.py`, DTO completeness, critical differential corpus y
  tests Rust en `aether-verifier`;
- lifecycle: policy-v1 JSON/qualification y tests Python/Rust;
- SSA: RUST-4.x qualification, deep CFG, mutation, schema-v2, Python builder y
  refinement verifier independientes;
- optimizer: suites IR/SSA/O2 y Python como oracle de transformación;
- LLVM: backend/native/platform ABI, example manifest, clang acceptance y
  AST/native differential;
- frontend: mucha cobertura funcional, pero Python es la única semántica; los
  tests son golden/behavioral, no un segundo checker independiente.

## 9. Riesgo semántico

Orden aproximado de mayor riesgo:

1. semantics/type/conversions/call and method resolution/import visibility;
2. ownership/lifecycle, exception edges y refinement IR→SSA;
3. control-flow construction, phi/dominance y optimizer ARC/BCE/LICM;
4. LLVM object/layout/runtime ABI y diagnósticos de platform boundaries;
5. source diagnostics/parser recovery/interpolated strings;
6. lexer regular fuera de interpolation.

La cobertura alta no equivale a oracle independiente. Para frontend no existe
un checker alternativo; migrar requiere primero corpus golden tipado/diagnósticos
y differential execution. Para SSA/lifecycle sí existen Python/Rust lanes y
qualification madura. Para LLVM, clang valida estructura y el AST/native corpus
valida comportamiento, pero no prueba ABI/ownership por sí solo.

## 10. Self-hosting

Migrar ahora a Rust y self-hostear después son decisiones distintas.

- lexer/parser podrían llegar a Aether en SH3, con Rust Stage0 como bootstrap y
  oracle; su bajo costo actual hace innecesario anticiparlo;
- formatter, linter, package/build tooling y stdlib de alto nivel son mejores
  primeras superficies Aether porque no definen semántica core;
- typechecker, verifiers, optimizer, ownership y LLVM deben permanecer canónicos
  en Rust salvo ADR futuro con evidencia extraordinaria;
- el compiler driver de bajo nivel debe ser Rust; una capa de proyecto/paquetes
  podría ser Aether;
- runtime primitives deben estar detrás de C ABI estable, implementadas
  principalmente en Rust; algoritmos de alto nivel sí pueden ser Aether.

No conviene postergar el in-process core esperando self-hosting: ese límite será
también el Stage0 que un self-host futuro necesita.

## 11. Roadmap recomendado (máximo tres etapas)

### 1. `CORE-1.0_IN_PROCESS_COMPILER_CORE_BOUNDARY` — siguiente milestone

**Objetivo.** Convertir el crate vacío `aether-python` en binding in-process de
un único Rust core service. Primero debe reproducir exactamente la entrada
schema-v1 y salida schema-v2 actuales, sin cambiar semántica ni trust policy.

**Por qué primero.** Reduce el costo arquitectónico de toda migración siguiente,
permite ownership Rust duradero, evita más subprocess/JSON y tiene los mejores
oráculos existentes.

**Prerequisitos.** ADR de binding/packaging (PyO3 u otra API in-process), error
schema, ownership/threading/reentrancy, wheels por plataforma y definición de qué
DTO se importa una sola vez.

**Exit criteria.** Paridad exacta companion↔binding; clean-install wheels; una
importación Initial IR por request; cross-platform; no Python builder en default;
companion seleccionable como rollback; timings sólo observacionales.

**Rollback/oracle.** Companion actual como rollback. Python GeneralSSABuilder,
verifiers/refinement y modos differential como oráculos qualification.

### 2. `CORE-1.1_AUTHORITY_AND_ACCEPTANCE_CONSOLIDATION`

**Objetivo.** Corregir wiring de Initial IR authority, aceptar IR no normalizado
en Rust, ejecutar lifecycle Rust y retirar repeticiones Python del camino normal
sin debilitar invariantes. Implementar un refinement Rust independiente o
mantener temporalmente sólo el mínimo Python necesario, explícitamente medido.

**Exit criteria.** La traza normal invoca la autoridad declarada; cada familia de
invariantes tiene una verificación intencional, no accidentalmente repetida;
lifecycle Python sale del default; parity/mutation/rollback pasan.

**Rollback/oracle.** Switch configurado a la ruta Python anterior; verifier,
lifecycle, SSA verifier y refinement Python permanecen qualification/reference.

### 3. `CORE-2.0_OWNED_MIDDLE_AND_NATIVE_BACKEND`

**Objetivo.** Mantener SSA owned en Rust a través de optimizer y LLVM/native
lowering, y definir el C ABI del runtime antes de extraer helpers.

**Exit criteria.** Paridad O0/O1/O2, corpus LLVM/native diferencial, ABI y
packaging multiplataforma, Python backend seleccionable durante qualification.

No se propone aún una etapa frontend; debe reauditarse después de que el owned
core consuma/produzca representaciones estables sin roundtrip.

## 12. Qué NO migrar todavía

- lexer solo: <0.5% warm y agrega token boundary;
- parser solo: ~0.6% medido (lexer+parser ~1%) y agrega AST boundary;
- `GeneralSSABuilder`: está fuera del default y vale como oracle/rollback;
- Initial IR verifier “de nuevo”: Rust ya existe; falta wiring;
- driver entero de una vez: fan-out máximo con ownership todavía partido;
- C++ core: no existe dependencia que lo justifique;
- runtime C antes del ABI audit: no hay runtime C canónico hoy;
- LSP/editor: no reduce el critical path y exigiría API incremental prematura;
- release/benchmark/qualification Python: es asignación permanente apropiada;
- cleanup de imports como sustituto de arquitectura: vale como optimización
  pequeña e independiente, pero no resuelve fronteras ni authority.

## 13. Validación y límites de la auditoría

- No se modificó producción, tests productivos ni workflows.
- Sólo se agregó tooling de auditoría y estos dos artifacts.
- No se ejecutó una qualification multiplataforma nueva.
- La campaña fue Linux local; cross-platform risk se deriva de packaging/ABI
  existentes y debe validarse en CI cuando haya implementación.
- No se creó commit.
- Las cifras temporales son observacionales, no thresholds.
- `git diff --check`, validación JSON, smoke tests del script y tests focalizados
  se ejecutan como cierre de esta auditoría.
