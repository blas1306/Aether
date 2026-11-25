# Aether — LEGACY-COMPILER-RETIREMENT-AUDIT-V1

Estado: **AUDIT CLOSED — RETIREMENT NOT YET AUTHORIZED**

Fecha: 2026-11-25

Checkout auditado: `main` @ `35e1a8197dc7a48d6f7218b27a44f458c98c25c4`

## 1. Decisión arquitectónica

`compiler-next` es la implementación oficial y autoritativa del compilador de
Aether. La CLI pública `aether`, el frontend, HIR, MIR, SSA, verificadores,
ownership, backend LLVM, driver, package manager y registry vigentes viven en
ese workspace.

`compiler-rs` pertenece al pipeline histórico reconstruido antes de
`compiler-next`. No es un segundo frontend completo: recibe Initial IR producido
por Python, lo importa a representaciones Rust, verifica y transforma ese IR y
lo expone mediante binarios y un binding PyO3. Su nombre de directorio no le
confiere autoridad sobre el lenguaje actual.

La jerarquía de autoridad para cualquier conflicto es:

1. contratos `CLOSED` aplicables a `compiler-next`;
2. implementación y qualification de `compiler-next`;
3. documentos vigentes que describen esa implementación;
4. `compiler-rs`, el compilador Python y sus documentos como evidencia
   histórica o herramientas transitorias, nunca como autoridad normativa.

No existe obligación de paridad integral con `compiler-rs` ni con el compilador
Python. Un fallo exclusivo del workspace histórico no bloquea la qualification
de `compiler-next`. Tampoco se debe portar una capacidad sólo porque exista en
el diseño anterior.

La auditoría encontró, sin embargo, consumidores internos reales de
`compiler-rs`. Por eso la decisión de autoridad está cerrada, pero borrar o
mover hoy el directorio rompería packaging, la CLI Python, tests, scripts y CI.
Esos consumidores deben migrarse, archivarse o retirarse explícitamente antes
del retiro físico.

## 2. Alcance y método

Se inspeccionaron:

- estado Git local y remoto, tracked/untracked, diff y diff cached;
- ambos workspaces Cargo y todos sus manifests;
- manifests Python, locks, hooks de build y distribución Maturin;
- código productivo Python que descubre o importa el core Rust histórico;
- workflows, scripts, tests, fixtures, ejemplos y configuración de IDE;
- documentación pública, arquitectura, migraciones y evidencia histórica;
- el diferencial `compiler-next` ↔ CLI Python legado;
- integridad de los paths relevantes y metadata Cargo sin compilar.

Las apariciones textuales se clasificaron por función. Un documento de
migración fechado no se trató como consumidor ejecutable, y un nombre de
producto como `aether-ir-verifier` sí se siguió hasta su manifest, builder,
distribución y caller.

## 3. Inventario de implementaciones y componentes

### 3.1 Matriz principal

| Componente | Ubicación / lenguaje | Responsabilidad y mantenimiento observable | Dependencias entrantes / salientes | Relación con `compiler-next` | Clasificación propuesta |
|---|---|---|---|---|---|
| Compilador oficial | `compiler-next/`, Rust | Source → HIR → MIR → SSA verificado → LLVM; actividad reciente y CLI pública | IDEs, ejemplos, packages y tests → crates internos, `clang`, OS | Implementación autoritativa; no importa `compiler-rs` ni Python | **ACTIVE** |
| CLI y driver oficiales | `compiler-next/crates/aether-cli`, `aether-driver`, Rust | `aether check/build/run/init/sync/update/add/remove/publish`; toolchain y ejecución | VS Code/IntelliJ/usuario → frontend, middle, backend, package | Superficie pública vigente | **ACTIVE** |
| Frontend y middle-end vigentes | `aether-frontend`, `aether-middle`, Rust | Lexer/parser, semántica, HIR/MIR/SSA, ownership y verificación actuales | driver/backend → `aether-package` y crates entre sí | Contratos actuales, incompatibles por diseño con el IR histórico | **ACTIVE** |
| Backend y runtime emitido vigentes | `aether-backend-llvm`, Rust | Lowering LLVM y soporte runtime del compilador oficial | driver → frontend/middle; salida a `clang` | Reemplazo autoritativo del backend Python | **ACTIVE** |
| Package manager y registry | `aether-package`, `aether-registry`, Rust | Proyectos, locks, cache, transport HTTPS, publicación y registry | CLI/driver/packages → filesystem, red, serde/toml | Infraestructura oficial independiente de `compiler-rs` | **ACTIVE** |
| Workspace histórico | `compiler-rs/`, Rust | Contenedor de IR, verificadores, lowering SSA, bridges y distribución del pipeline Python | paquete Python, 10 workflows, scripts y tests → Cargo/PyO3/serde | No es frontend completo ni autoridad de `compiler-next` | **MIGRATION-REQUIRED** como conjunto; clasificar por crate antes de retirar |
| IR histórico | `compiler-rs/crates/aether-ir`, Rust | Import de schema-v1, IR owned, wire DTO v1/v2, lifecycle normalization y SSA lowering | verifier, executable, binding y tools → serde | Sólo entiende contratos/representaciones del pipeline anterior | **MIGRATION-REQUIRED**, luego **LEGACY-REFERENCE** |
| Verificadores históricos | `compiler-rs/crates/aether-verifier`, Rust | Verificación de Initial IR, CFG/dominance/SSA/lifecycle/borrow/return; `CompilerCore`; `aether-ssa-shadow` | binding, verifier executable, CI y qualification → `aether-ir` | Sus ideas/corpus pueden informar tests; sus resultados no gobiernan `compiler-next` | **MIGRATION-REQUIRED**, luego **LEGACY-REFERENCE** |
| Verificador subprocess | `compiler-rs/crates/aether-ir-verifier`, Rust | Protocolo v1 stdin/stdout para admisión de Initial IR | Python runtime, package, scripts, tests, CI → `aether-ir`, `aether-verifier` | Sin consumidor en el pipeline oficial | **MIGRATION-REQUIRED** |
| Binding PyO3 | `compiler-rs/crates/aether-python`, Rust/PyO3 | `CompilerCore`, `CompilationSession`, import schema-v1 y export schema-v2 | distribución Maturin y Python legado → IR/verifier/PyO3 | Bridge exclusivo del pipeline anterior | **MIGRATION-REQUIRED** |
| Distribución nativa histórica | `compiler-rs/distributions/aether-compiler-core`, Python/Rust packaging | Wheel `aether-compiler-core`, wrapper, binding y dos binarios validados por RECORD | `aether-language`, uv, release/CI → Maturin y crates legacy | No la usa `aether` oficial | **MIGRATION-REQUIRED** |
| Compilador Python original | `src/aether/`, Python | Lexer/parser/typechecker, Initial IR, SSA, optimizers, LLVM printer/runtime, CLI `aether-legacy` | wheel, tests, LSP, scripts → core Rust legacy, clang y libs Python | Implementación histórica, explícitamente congelada | Dividir: **LEGACY-REFERENCE**, **MIGRATION-REQUIRED** y **RETIRE-CANDIDATE** según función |
| Intérprete AST y REPL | `src/aether/interpreter.py`, `session.py`, `pipeline.py`, Python | Mayor cobertura histórica, REPL y caracterización semántica | `aether-legacy`, LSP/tests → frontend y builtins Python | No es compilador oficial; puede conservar valor como herramienta | **MIGRATION-REQUIRED** para desacoplar packaging; después decidir **LEGACY-REFERENCE** o herramienta activa explícita |
| Intérprete IR histórico | `src/aether/ir/interpreter.py`, Python | Ejecuta subconjunto del Initial IR histórico | CLI/tests → IR Python | Sin equivalente requerido por contrato actual | **LEGACY-REFERENCE**; posible **RETIRE-CANDIDATE** tras inventariar usuarios externos |
| Backend LLVM Python | `src/aether/backend/llvm`, Python | Emisión textual, runtime helpers, build/run del pipeline legacy | `aether-legacy` y tests → Initial IR/SSA, clang | Sustituido funcionalmente por el backend Rust con contratos distintos | **RETIRE-CANDIDATE** cuando deje de ofrecerse el native legacy |
| LSP Python | `src/aether_lsp/`, Python | Servidor compartido por editores; usa frontend/language service Python | VS Code/IntelliJ → `src/aether` | Servicio todavía expuesto, no dependencia directa de `compiler-rs` | **MIGRATION-REQUIRED** para separar del wheel/core legacy o reemplazarlo |
| IDEs | `vscode-extension/`, TypeScript; `tools/intellij-aether/`, Kotlin | Clientes de `aether` y `aether-lsp` externos | usuario → CLI oficial y LSP Python | CLI ya apunta a `aether`; LSP conserva dependencia indirecta del paquete Python | **ACTIVE**, con migración del LSP pendiente |
| Scripts de desarrollo | `scripts/`, Python | CI local, release, qualification, packaging, medición y migraciones históricas | personas/workflows/tests → ambos stacks según script | 63 archivos referencian productos legacy; otros sirven a tareas generales | Granular: **MIGRATION-REQUIRED**, **LEGACY-REFERENCE** o **ACTIVE** |
| Tests y corpus | `tests/`, `compiler-next/tests/`, varios | Qualification actual, legacy, packaging y diferenciales | CI/desarrolladores → ambos stacks | Los tests de `compiler-next` son autoridad sólo sobre contratos actuales | Granular: **ACTIVE**, **MIGRATION-REQUIRED** o **LEGACY-REFERENCE** |
| Bibliotecas Aether | `graphics/`, `plots/`, `linearAlgebra/`, Aether | Packages/dogfood del lenguaje vigente | ejemplos/package manager → CLI oficial | Consumers de `compiler-next`, no infraestructura legacy | **ACTIVE** |

### 3.2 Observaciones que evitan clasificaciones incorrectas

- `compiler-rs` no contiene lexer, parser, typechecker ni backend LLVM completo.
  Es una parte nativa del compilador híbrido Python histórico.
- El intérprete AST, el LSP, scripts genéricos y los packages Aether no deben
  eliminarse automáticamente junto con `compiler-rs`.
- La ausencia de referencias desde `compiler-next/Cargo.toml` y sus crates
  prueba independencia interna del workspace, no independencia total de su
  qualification: `compiler-next/tests/run-differential.sh` aún ejecuta
  `python -m aether.cli`.
- Los binarios y bindings encontrados bajo `compiler-rs/target/` y dentro del
  source tree de la distribución están ignorados, no tracked. Deben protegerse
  como trabajo local durante cualquier retiro, no asumirse recreables.

## 4. Mapa de dependencias

### 4.1 Pipeline oficial

```text
usuario / IDE
  -> aether (aether-cli)
  -> aether-driver
  -> aether-frontend + aether-middle
  -> aether-backend-llvm
  -> clang / ejecutable

aether-cli / aether-driver
  -> aether-package
  -> cache / registry / packages Aether
```

No hay edge de este grafo a `compiler-rs`.

### 4.2 Pipeline histórico todavía instalable

```text
pyproject.toml: aether-language
  -> aether-compiler-core == 1.0.0rc4
     -> wrapper aether_compiler_core
        -> PyO3 aether-python -> aether-verifier -> aether-ir
        -> aether-ssa-shadow  -> aether-verifier -> aether-ir
        -> aether-ir-verifier -> aether-verifier -> aether-ir

aether-legacy / Python Initial IR
  -> initial_ir_verifier_path() -> aether-ir-verifier
  -> binding() o companion_path() -> lowering/verificación SSA Rust
  -> Python optimizer/backend LLVM/clang
```

### 4.3 Dependencias de qualification y desarrollo

```text
10 GitHub workflows ─┐
63 scripts           ├─> compiler-rs / aether-compiler-core / binarios
32 test files        ┤
setup.py + uv.lock   ┘

compiler-next/tests/run-differential.sh
  -> Python aether.cli
  -> pipeline legacy y su instalación/core nativo
```

## 5. Clasificación de referencias

### A. Dependencias ejecutables reales

- `pyproject.toml:13-23` fija `aether-compiler-core==1.0.0rc4` y lo resuelve
  desde `compiler-rs/distributions/aether-compiler-core` en desarrollo.
- `src/aether/ir/shadow_verifier.py:1056-1083` descubre el
  `aether-ir-verifier` instalado y lo usa como gate del Initial IR legacy.
- `src/aether/ssa/in_process.py:11-105` usa `CompilerCore`/`CompilationSession`
  mediante PyO3.
- `src/aether/ssa/shadow.py:386-466` selecciona binding in-process o el
  subprocess `aether-ssa-shadow` desde el wrapper estable.
- `compiler-next/tests/run-differential.sh:30-47` ejecuta la CLI Python y hace
  que su resultado contribuya al exit status del diferencial.
- `examples/pNR/ejecutar.sh:3-7` compara manualmente `aether` con
  `aether-legacy`; no es una dependencia del producto, pero sí un consumidor
  ejecutable versionado.

### B. Dependencias de build o test

- `setup.py:12-29` lee `compiler-rs/Cargo.toml` para generar metadata del
  verificador; `MANIFEST.in:10` incluye ese manifest en el sdist.
- `uv.lock:5-36` conserva la dependencia de directorio y la dependencia runtime
  del paquete Python.
- Diez workflows construyen crates/binarios o wheels de `compiler-rs`; tres
  corren en cada pull request, `rust-ssa-shadow.yml` corre en pull request y
  schedule semanal, dos tienen path gates de pull request y cuatro son manuales.
- 63 scripts y 32 archivos de tests fuera de `compiler-rs` referencian al
  workspace, sus crates, productos o wrapper.
- Los tests internos de los cuatro crates son consumidores locales legítimos
  mientras el workspace exista; dejan de ser gates del producto oficial al
  archivar el workspace.

### C. Referencias documentales vigentes

- `README.md:133-163` declara `compiler-next`/`aether` como interfaz oficial y
  `aether-legacy` como superficie histórica temporal.
- `README.md:295-378` separa el pipeline oficial de los backends históricos.
- `compiler-next/README.md:31-36` identifica `aether` como CLI oficial y el
  Python CLI como transición congelada.
- Documentos de packaging y protocolos bajo `docs/compiler/` describen
  contratos todavía materializados por el wheel histórico. Son vigentes para
  mantener o retirar ese artefacto, pero no para definir el lenguaje actual.

### D. Referencias históricas legítimas

- Diseños, promotion reports, evidence JSON y snapshots de platform bajo
  `docs/compiler/` registran por qué y cómo se promovieron verificadores dentro
  del pipeline anterior.
- `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md:740-787` ya distingue
  activos reutilizables de transportes transitorios y recomienda reconstrucción
  sin compatibilidad de IR.
- Los reportes `NEXT_VERTICAL_*` que dicen que no modificaron `compiler-rs` son
  evidencia de preservación, no dependencias.

Estas referencias deben conservarse con una cabecera o índice que las marque
como históricas, y no reescribirse para fingir que siempre describieron
`compiler-next`.

### E. Referencias obsoletas

- `compiler-rs/README.md` todavía afirma que el compilador productivo permanece
  enteramente en Python y que `aether-python` no integra PyO3; el source actual
  tiene binding y distribución productiva.
- `docs/architecture/IMPLEMENTATION_LANGUAGE_OWNERSHIP.md:44-61` conserva una
  foto intermedia que llama vacío al seam `aether-python`; contradice el código
  posterior y la distribución Maturin.
- `src/aether/cli.py` conserva un selector temporal `--compiler=next` dentro de
  `aether-legacy`, aunque `aether` ya es la CLI oficial. El bridge no es
  necesario para preservar el intérprete AST.
- La wording de workflows de “authority promotion” puede hacer parecer que
  esas autoridades gobiernan `compiler-next`. Hoy sólo califican el pipeline
  histórico y deben renombrarse, aislarse o archivarse.

## 6. Capacidades únicas y decisión de preservación

| Capacidad legacy | Uso actual comprobado | Alternativa en `compiler-next` | Decisión propuesta |
|---|---|---|---|
| Import schema-v1 y wire DTO v1/v2 | Python legacy, tests, package y CI | HIR/MIR/SSA owned internos, sin ese wire contract | No portar. Conservar fixtures/protocolo como referencia hasta retirar consumers |
| Verificador Initial IR protocol-v1 | Gate productivo del pipeline Python | Verificadores propios sobre HIR/MIR/SSA actual | No usar como oracle normativo. Retirar con el native legacy; migrar sólo invariantes que un contrato CLOSED actual requiera y que falten |
| Lifecycle normalization y SSA lowering histórico | Binding y companion del legacy | Middle-end Rust vigente | No migrar por paridad; archivar implementación tras retirar consumers |
| Verificador de refinamiento Initial IR → SSA | Qualification legacy | Verificación por fase y corrupción de IR actual | Preservar estrategia/corpus adversarial reutilizable; no el contrato wire antiguo |
| `CompilerCore` PyO3 in-process | Dependencia real de `aether-language` | Driver Rust directo, sin Python | Retirar junto con el pipeline native Python; no introducir PyO3 en `compiler-next` sólo por compatibilidad |
| Companion persistente y protocolo framed | Rollback/qualification legacy | Llamadas in-process entre crates | Archivar; reutilizar únicamente ideas de fail-closed si aparece un boundary real |
| Wheel nativo cross-platform con RECORD/provenance | Packaging del Python legacy | Distribución oficial Rust aún usa otro modelo | Evaluar sus tests de integridad como requisitos generales; no conservar el wheel como dependencia del compilador oficial |
| AST interpreter y REPL Python | Superficie explícita aún no migrada | No hay reemplazo integral | Decisión separada: conservar como herramienta histórica empaquetada sin core Rust o retirar con anuncio; no confundir con `compiler-rs` |
| IR interpreter Python | Caracterización y tests legacy | Ninguna obligación de equivalente | LEGACY-REFERENCE; no migrar salvo necesidad actual demostrada |
| LSP Python | Consumido por los dos IDEs | CLI/compiler Rust no expone aún LSP equivalente | Mantener la función, pero separar packaging del core legacy o planear reemplazo explícito |
| Qualification/differential harnesses | Amplio uso en CI histórico; un diferencial vive en `compiler-next` | Tests y mutation checks actuales | Migrar patrones, casos fuente y checks relevantes. El legacy no debe ser gate ni oracle de aceptación de `compiler-next` |

La capacidad verdaderamente necesaria no es “que `compiler-rs` compile”, sino
mantener las superficies actuales elegidas conscientemente: CLI oficial, LSP si
sigue publicado, quizá AST/REPL, corpus útil y qualification independiente.

## 7. Clasificación consolidada

| Elemento | Clasificación ahora | Estado objetivo antes de borrar `compiler-rs` |
|---|---|---|
| `compiler-next/**` | **ACTIVE** | **ACTIVE** |
| `compiler-rs` como path operativo | **MIGRATION-REQUIRED** | Sin consumers; snapshot/tag histórico |
| crates IR/verifier y fixtures | **MIGRATION-REQUIRED** | **LEGACY-REFERENCE** en tag/archive, o retirados del branch activo |
| binding, companions y distribución | **MIGRATION-REQUIRED** | **RETIRE-CANDIDATE** |
| Python AST/REPL | **MIGRATION-REQUIRED** por acoplamiento de paquete | **LEGACY-REFERENCE** o herramienta explícitamente mantenida, según decisión de producto |
| Python frontend/IR/SSA/LLVM native | **LEGACY-REFERENCE** con consumers aún activos | **RETIRE-CANDIDATE** después de EOL del native legacy |
| LSP Python | **MIGRATION-REQUIRED** | **ACTIVE** desacoplado o reemplazado |
| IDEs | **ACTIVE** | **ACTIVE** |
| CI/scripts/tests que construyen legacy | **MIGRATION-REQUIRED** | Archivados o eliminados del gate activo |
| corpus y evidencia histórica | **LEGACY-REFERENCE** | **LEGACY-REFERENCE** con labeling claro |
| packages `graphics`, `plots`, `linearAlgebra` | **ACTIVE** | **ACTIVE** |
| consumidores externos no visibles | **UNRESOLVED** | Inventariados o cubiertos por anuncio/EOL antes del retiro |

## 8. Política mínima de autoridad propuesta

Texto normativo propuesto:

> `compiler-next` y la CLI `aether` son la única implementación oficial del
> compilador Aether. Los contratos `CLOSED` aplicables a `compiler-next`
> gobiernan sintaxis, semántica, ownership, IR y comportamiento observable.
> `compiler-rs` y el compilador Python son implementaciones históricas no
> normativas; pueden usarse para estudiar algoritmos, casos y regresiones, pero
> no como oracle de aceptación ni como fuente de requisitos de compatibilidad.
> Una divergencia legacy no bloquea `compiler-next`. Todo código nuevo debe
> partir de contratos actuales y tests de `compiler-next`, y cualquier
> reutilización legacy debe declarar el contrato vigente que satisface.

Publicación mínima recomendada, en una fase posterior:

1. resumen breve y enlace en `README.md`, junto a “Instalación y primer uso”;
2. sección normativa en `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` o un
   documento corto `COMPILER_AUTHORITY.md` enlazado desde allí;
3. instrucciones raíz para desarrolladores/asistentes sólo si el repositorio
   adopta ese mecanismo. Hoy no existe `AGENTS.md`, `CONTRIBUTING` ni archivo de
   instrucciones equivalente; no conviene crear varios canales divergentes.

Reglas operativas para tooling y asistentes:

- no consultar `compiler-rs` para decidir semántica vigente sin una solicitud
  explícita de arqueología;
- buscar primero contratos `CLOSED` y tests de `compiler-next`;
- no añadir nuevos edges desde `compiler-next` a Python, schema-v1/v2,
  `aether-compiler-core` o binarios legacy;
- no convertir diferencias legacy en blockers del workspace oficial;
- etiquetar snippets/comandos legacy y no publicarlos como onboarding actual;
- exigir una justificación vinculada a un contrato vigente al migrar un
  algoritmo o caso.

## 9. Estrategia de retiro segura

### Etapa 0 — congelar autoridad y alcance

1. Publicar la política anterior.
2. Marcar `compiler-rs`, `aether-compiler-core` y workflows asociados como
   legacy, sin intentar reparar F4 sólo para mantenerlos verdes.
3. Prohibir nuevos consumers y registrar owners/decisiones para AST/REPL y LSP.

Gate: ningún documento o gate presenta al stack legacy como autoridad de
`compiler-next`.

### Etapa 1 — preservar historia verificable

1. Elegir el último commit histórico coherente, no asumir que el HEAD actual es
   compilable.
2. Crear, con aprobación separada, una etiqueta anotada como
   `compiler-rs-last-historical-v1` que incluya commit, estado conocido y enlace
   al reporte de retiro.
3. Preservar fixtures, manifests de qualification y documentación útil en el
   tag; no versionar `target/`, `.so`, `.pyc` ni `_native/` locales.

La etiqueta es conveniente: el workspace contiene unas 40 mil líneas Rust/Python
de source/tests y abundante evidencia que perdería navegabilidad si sólo queda
en commits no identificados. La etiqueta no debe llamarse “release oficial” ni
prometer build verde.

### Etapa 2 — desacoplar qualification de `compiler-next`

1. Cambiar `compiler-next/tests/run-differential.sh` para que la qualification
   autoritativa use expectativas propias de contratos CLOSED.
2. Mover la ejecución legacy a una tarea histórica/informativa, o congelar sus
   observaciones como evidencia no normativa.
3. Confirmar que fallos, ausencia de Python o ausencia de
   `aether-compiler-core` no cambian el resultado de gates oficiales.

Gate: `compiler-next` puede calificarse desde checkout limpio sin Python ni
`compiler-rs` (salvo tests que explícitamente se declaren arqueología opt-in).

### Etapa 3 — resolver superficies Python que aún importan

1. Decidir AST/REPL: mantener un paquete histórico liviano sin dependencia
   nativa, o anunciar EOL y retirarlo.
2. Decidir LSP: separar su instalación del `aether-language` monolítico o
   reemplazarlo por un servicio sobre `compiler-next`.
3. Retirar del package metadata el pin a `aether-compiler-core`, el source uv,
   el hook `setup.py` y el manifest Cargo sólo cuando ningún entry point
   retenido los necesite.
4. Retirar los cuatro adapters runtime legacy después de eliminar sus callers.

Gate: instalar y ejecutar cada herramienta Python retenida sin
`compiler-rs`, Maturin ni binarios nativos legacy.

### Etapa 4 — archivar CI, scripts y tests

1. Clasificar los 10 workflows y 63 scripts por `keep/adapt/archive/delete`.
2. Portar sólo harnesses/corpus que prueben necesidades actuales.
3. Quitar gates de pull request/schedule legacy y preservar evidence con índice
   histórico.
4. Retirar los 32 test files de integración legacy del conjunto activo o
   moverlos al snapshot histórico.

Gate: búsquedas de paths/productos legacy sólo devuelven documentos y
referencias históricas deliberadas.

### Etapa 5 — alinear documentación y consumidores secundarios

1. Actualizar README, arquitectura, release/packaging, IDE docs y ejemplos.
2. Retirar el selector `--compiler=next` del CLI legacy si ese CLI sobrevive;
   conservar sólo las funciones explícitamente mantenidas.
3. Actualizar `examples/pNR/ejecutar.sh` o archivarlo.
4. Añadir cabeceras históricas a documentos que describen promotion de
   `compiler-rs`.

Gate: onboarding, build, CI e IDE config no ofrecen el compilador histórico
como alternativa vigente.

### Etapa 6 — retiro físico y qualification final

1. Repetir inventario en un checkout limpio y auditar consumidores externos.
2. Retirar `compiler-rs` y sus consumers obsoletos en un cambio dedicado y
   revisable, nunca junto con cambios semánticos de `compiler-next`.
3. Calificar Cargo metadata/check/fmt/clippy/test de `compiler-next`, CLI,
   packages, IDE commands y toda herramienta Python retenida.
4. Ejecutar `git diff --check`, link/path checks y búsquedas negativas.

Gate final: ningún producto/gate vigente necesita el tag histórico; todas las
referencias restantes son explícitamente documentales.

## 10. Riesgos y mitigaciones

| Riesgo | Evidencia | Mitigación |
|---|---|---|
| Borrado prematuro rompe instalaciones Python | pin runtime, uv source, setup hook y distribución Maturin | Desacoplar packaging antes del path |
| CI oculta sigue construyendo legacy | 10 de 11 workflows lo referencian; algunos son PR/scheduled | Inventario por trigger, no sólo por nombre; retirar gates explícitamente |
| Tests usan legacy como blocker | diferencial de `compiler-next` suma fallos legacy | Hacer autoridad independiente y legacy informativo |
| Herramientas importan módulos/binarios | cuatro módulos runtime y numerosos scripts | búsqueda por package/API/producto, no sólo por texto `compiler-rs` |
| Documentos mezclan épocas | README actual convive con ADRs/snapshots obsoletos | política central + labeling histórico |
| Se pierde AST/REPL o LSP útil | ambos viven en el paquete Python monolítico | decisión de producto y split antes del retiro |
| Se porta semántica vieja por accidente | IR/ownership/schema difieren | exigir contrato CLOSED vigente por toda migración |
| Se amplía accidentalmente a MathTeX/Python completo | el retiro apunta al core legacy, no a todo Python ni a archivos archivados | lista explícita de paths y cambios dedicados |
| Consumers externos no visibles | una búsqueda local no detecta scripts privados o wheels instalados | anuncio/EOL, búsqueda en releases y telemetría disponible; **UNRESOLVED** hasta entonces |
| Pérdida de archivos no versionados | targets, bindings y binarios ignorados; worktree ya contiene trabajo local | snapshot/tag de tracked; inventario y backup separado de untracked; nunca `clean/reset` |
| Tag engañoso | HEAD legacy tiene F4 documentado | tag anotado al último estado elegido, con defectos conocidos; no llamarlo release |

## 11. Qualification futura obligatoria

La eliminación sólo podrá aprobarse cuando:

- no haya imports, paths, manifests, locks, workflows o tests ejecutables que
  requieran `compiler-rs`;
- `compiler-next` se califique sin ejecutar el compilador histórico;
- los IDEs resuelvan `aether` y un LSP deliberadamente soportado;
- cada herramienta Python retenida se instale sin `aether-compiler-core`;
- corpus reutilizados prueben contratos actuales y no igualdad de IR legacy;
- las búsquedas negativas cubran nombres de path, crates, packages, módulos y
  binarios;
- un checkout limpio pase los gates oficiales y `git diff --check`;
- el plan de preservación de historia y de archivos locales esté ejecutado.

## 12. Cierre de diseño

Se identificaron los consumidores internos relevantes, se separaron
dependencias ejecutables de referencias históricas, se evaluaron capacidades
únicas y se definió una secuencia verificable. La política es coherente con la
autoridad de `compiler-next` y esta fase no modifica código productivo.

Por tanto, **LEGACY-COMPILER-RETIREMENT-AUDIT-V1 queda AUDIT CLOSED**.

El cierre no autoriza borrar, mover, reparar ni retirar automáticamente
`compiler-rs`. La recomendación actual es **RETIREMENT NOT YET AUTHORIZED** hasta
completar las etapas 0–5 y resolver los consumers externos **UNRESOLVED**.
