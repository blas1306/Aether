# Aether — LEGACY-COMPILER-RETIREMENT-AUDIT-V1 — Reporte

Estado: **AUDIT CLOSED — RETIREMENT NOT YET AUTHORIZED**

Fecha: 2026-11-25

Checkout auditado: `main` @ `35e1a8197dc7a48d6f7218b27a44f458c98c25c4`

Documento de decisión:
[LEGACY_COMPILER_RETIREMENT_AUDIT_V1.md](LEGACY_COMPILER_RETIREMENT_AUDIT_V1.md)

## 1. Resultado ejecutivo

La autoridad ya está resuelta: `compiler-next` es el compilador oficial y
`compiler-rs` no gobierna semántica, compatibilidad ni qualification del
lenguaje vigente.

El retiro físico no está listo. `compiler-next` no tiene dependencias Cargo ni
imports directos hacia `compiler-rs`, pero el stack Python histórico mantiene
dependencias productivas y de build, y la infraestructura del repositorio lo
construye extensamente. Se comprobaron:

- un pin runtime y source override de `aether-compiler-core`;
- cuatro módulos Python productivos que descubren o usan el core/verificadores;
- un hook de build y un sdist manifest dependientes del Cargo manifest legacy;
- 10 workflows, 63 scripts y 32 archivos de tests con referencias operativas;
- un diferencial dentro de `compiler-next` que ejecuta la CLI Python legacy y
  suma sus fallos al resultado;
- un ejemplo Bash versionado que compara ambas implementaciones.

La recomendación es retirar por capas: primero desacoplar qualification oficial,
luego decidir AST/REPL y LSP, separar packaging, archivar CI/scripts/tests y
recién entonces retirar el path. No se recomienda reparar `compiler-rs` para
prolongar su vida ni portar sus contratos por paridad.

## 2. Preflight y preservación

### 2.1 Git

| Dato | Evidencia |
|---|---|
| Rama | `main` |
| HEAD | `35e1a8197dc7a48d6f7218b27a44f458c98c25c4` |
| Upstream remoto verificado | `origin/main` = `6ca7813cde4df61761ffc20a87bd2553aa24f1eb` |
| Relación | HEAD está 1 commit ahead, 0 behind |
| Tracked | 2.368 archivos |
| Untracked no ignorados | 7 archivos |
| Diff cached | vacío |
| Diff tracked previo | 2 archivos, 24 inserciones y 16 eliminaciones |

`git ls-remote --heads origin main` confirmó el mismo hash que el remote-tracking
ref local sin ejecutar `fetch` ni modificar refs.

### 2.2 Trabajo previo preservado

Cambios tracked preexistentes:

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

Además se observaron artefactos ignorados dentro de `compiler-rs`: `target/`,
`__pycache__/`, un binding `.so` y `_native/` con binarios. No se tocaron.

No se ejecutaron `clean`, `reset`, `stash`, commit, push, tag ni operaciones
destructivas. Los únicos archivos creados por esta fase son los dos entregables
documentales.

## 3. Evidencia de independencia de `compiler-next`

1. `compiler-next/Cargo.toml` declara siete crates propios y ninguno apunta
   fuera del workspace al stack legacy.
2. Los manifests de `aether-frontend`, `aether-middle`,
   `aether-backend-llvm`, `aether-driver`, `aether-cli`, `aether-package` y
   `aether-registry` sólo enlazan crates del workspace y crates.io.
3. La búsqueda por `compiler-rs`, nombres de crates legacy, módulos Python y
   binarios no devolvió matches dentro de source/manifests de `compiler-next`.
4. Cargo pudo resolver offline la metadata de `compiler-next` sin
   `compiler-rs`.

Límite: `compiler-next/tests/run-differential.sh:6-47` ejecuta indirectamente la
CLI Python. No es un edge del producto compilado, pero sí una dependencia de
qualification. El script valida por separado expectativas next y legacy, y
cualquier desviación legacy incrementa `failures`; eso contradice la política
de que un fallo histórico no bloquee `compiler-next`.

## 4. Evidencia de dependencias activas de `compiler-rs`

### 4.1 Producto y packaging Python

| Ruta | Líneas | Dependencia comprobada |
|---|---:|---|
| `pyproject.toml` | 13-23 | pin `aether-compiler-core==1.0.0rc4` y source local bajo `compiler-rs` |
| `pyproject.toml` | 31-35 | publica `aether-legacy`, LSP y probes SSA en el mismo paquete |
| `uv.lock` | 5-36 | resuelve y exige la distribución legacy |
| `setup.py` | 12-29 | lee versión desde `compiler-rs/Cargo.toml` y genera metadata |
| `MANIFEST.in` | 10 | incluye el Cargo manifest en el sdist |
| distribución `pyproject.toml` | 17-29 | Maturin construye PyO3 y empaqueta `aether-ssa-shadow` y `aether-ir-verifier` |

Esto es una dependencia real de instalación/build, no documentación. Retirar el
directorio hoy rompe source installs, lock resolution y builds de wheel/sdist.

### 4.2 Código Python productivo

| Ruta | Líneas | Función |
|---|---:|---|
| `src/aether/ir/rust_verifier.py` | 60-83, 690-719 | toma versión del Cargo manifest y descubre binario en `compiler-rs/target` |
| `src/aether/ir/shadow_verifier.py` | 1056-1111 | descubre `initial_ir_verifier_path()` y crea el gate productivo |
| `src/aether/ssa/in_process.py` | 11-105 | importa el binding y llama `CompilerCore`/`CompilationSession` |
| `src/aether/ssa/shadow.py` | 386-466 | selecciona transporte binding o `aether-ssa-shadow` |

Los imports son lazy, pero el paquete declara el core como dependencia
obligatoria. El backend AST puede no ejecutar esos módulos en una sesión dada;
eso no elimina el acoplamiento de distribución.

### 4.3 Workspace y capacidades

`compiler-rs/Cargo.toml:1-7` contiene cuatro crates:

- `aether-ir`: modelo Initial IR/wire, importer, lifecycle y SSA;
- `aether-verifier`: verificadores y `CompilerCore`, además del binario
  `aether-ssa-shadow`;
- `aether-ir-verifier`: protocolo/executable de verificación Initial IR;
- `aether-python`: cdylib PyO3 sobre IR/verifier.

El source y tests Rust/Python relevantes suman aproximadamente 40.196 líneas.
No es un stub ni un frontend alternativo: es un subsystem sustancial del
pipeline híbrido anterior.

El binding expone `CompilationSession.lower_ssa`, export schema-v2 y
`CompilerCore.accept_initial_ir_schema_v1` en
`compiler-rs/crates/aether-python/src/lib.rs:137-239`. La distribución lo
declara “Productive native CompilerCore interfaces for Aether” y empaqueta los
dos companions. Esta evidencia invalida textos antiguos que lo describen como
seam vacío.

### 4.4 CI

De 11 workflows presentes, 10 tienen dependencias legacy:

| Workflow | Trigger observado | Rol legacy |
|---|---|---|
| `core-in-process-promotion.yml` | PR + manual | instala/construye distribución y transportes |
| `core-in-process.yml` | PR + manual | construye verifier, companion y PyO3 |
| `core-native-packaging.yml` | PR + manual | wheels y clean-install multi-platform |
| `rust-ir-authority-promotion.yml` | manual | promoción/evidencia Initial IR antigua |
| `rust-ir-pre-lifecycle-shadow-qualification.yml` | manual | workspace, verifier, wheels y diferencial |
| `rust-refine-authority-promotion.yml` | manual | verifier/refinement y distribución |
| `rust-refine-shadow-qualification.yml` | manual | shadow/refinement y packaging |
| `rust-ssa-shadow.yml` | PR + semanal + manual | build legacy y full Python suite |
| `rust-verifier-cross-platform.yml` | PR por paths + manual | artefactos del verifier |
| `rust-verifier-operational.yml` | PR por paths + manual | build/readiness/canary |

El único workflow sin referencia es `vscode-extension.yml`.

La existencia de `pull_request` o `schedule` demuestra que no todos son simples
archivos históricos. No se ejecutaron workflows; no se afirma que estén verdes.

### 4.5 Scripts y tests

La búsqueda agrupada encontró referencias en 210 archivos fuera de
`compiler-rs`:

| Área | Archivos |
|---|---:|
| `docs/` | 96 |
| `scripts/` | 63 |
| `tests/` | 32 |
| `.github/` | 10 |
| `src/` | 4 |
| manifests/locks/hooks (`pyproject.toml`, `setup.py`, `MANIFEST.in`, `uv.lock`) | 4 |
| `examples/` | 1 |

Los 63 scripts incluyen build de artefactos, packaging, qualification,
performance, promotion, product probes y soak. Los 32 tests incluyen paths
directos a source/fixtures, builds Cargo, contracts de distribución,
transportes, platform packaging y provenance. No todos merecen migración:
primero deben separarse los harnesses/corpus reutilizables de gates que sólo
demuestran el pipeline retirado.

## 5. Documentación: vigente, histórica y obsoleta

### Vigente

- `README.md:135-163` presenta `aether`/`compiler-next` como interfaz oficial.
- `README.md:276-328` etiqueta al Python como histórico y separa pipelines.
- `compiler-next/README.md:31-36` declara la CLI oficial Rust y congela la
  transición Python.

### Histórica legítima

- Los documentos de migración, protocolos, qualification y promotion bajo
  `docs/compiler/` explican contratos del pipeline anterior.
- Evidence JSON, hashes y platform reports son trazabilidad, no autoridad
  semántica actual.
- `NEXT_VERTICAL_*` documenta que el nuevo compilador se desarrolló sin
  modificar legacy.

### Obsoleta o ambigua

- `compiler-rs/README.md` describe estados anteriores a PyO3/productive wheel.
- `IMPLEMENTATION_LANGUAGE_OWNERSHIP.md:44-61` contiene el mismo snapshot
  desactualizado, aunque su política general de una autoridad por
  responsabilidad sigue siendo útil.
- Nombres de workflows y documentos con “authority” carecen de una advertencia
  visible de que la autoridad se limita al pipeline histórico.
- `README.md:473-486` llama “actuales” a partes de `src/aether`; el contexto
  posterior distingue legacy, pero la lista puede confundir a tooling que lea
  sólo ese fragmento.

## 6. Capacidades únicas encontradas

Se encontraron capacidades no duplicadas literalmente en `compiler-next`:

1. import y validación de schema-v1 Initial IR;
2. export y verificación de schema-v2 SSA;
3. protocolo persistente `aether-ssa-shadow`;
4. executable protocol-v1 `aether-ir-verifier`;
5. binding PyO3 `CompilerCore` con sesiones Rust-owned;
6. distribución Maturin con wrapper/RECORD/provenance y dos binarios;
7. campañas diferenciales y de promotion específicas de esos contratos;
8. AST interpreter/REPL y LSP Python en el paquete que depende del core.

Las primeras siete pertenecen al diseño anterior o a su frontera de migración.
`compiler-next` posee alternativas conceptuales internas —IR owned,
verificadores, SSA, driver in-process y packaging Rust— pero no compatibilidad
wire. No se recomienda recrearla.

AST/REPL y LSP sí representan funciones todavía expuestas. No son capacidades
de `compiler-rs`, pero su empaquetado monolítico las ata a él. Son el principal
motivo para una decisión granular en vez de borrar todo Python.

## 7. Hallazgos

### H1 — autoridad oficial correctamente promovida

README, CLI Rust y manifests coinciden en que `compiler-next` es oficial. No se
halló edge directo del workspace oficial al workspace histórico.

### H2 — `compiler-rs` no puede borrarse hoy

El pin, wrapper, adapters, workflows, scripts y tests son consumers comprobados.
Clasificación: **MIGRATION-REQUIRED**, no **RETIRE-CANDIDATE** global.

### H3 — qualification oficial conserva un blocker legacy indirecto

`compiler-next/tests/run-differential.sh` falla también si el resultado legacy
se desvía. Debe ser el primer desacoplamiento porque contradice expresamente la
decisión arquitectónica.

### H4 — el paquete Python mezcla funciones con destinos distintos

Frontend/compiler/backend legacy, AST/REPL, LSP, release tooling y bridge Rust
comparten distribución. Retirar el core sin split elimina funciones que podrían
seguir siendo útiles; conservar todo sólo por AST/LSP perpetúa una dependencia
innecesaria.

### H5 — el valor reusable es principalmente evidencia y técnica

Invariantes, corpus adversarial, fail-closed boundaries, provenance y mutation
tests son activos útiles. Los schemas, APIs y outputs concretos no son contratos
que `compiler-next` deba reproducir.

### H6 — existe deuda observable, pero no debe repararse en esta fase

`APPLICATION_MATURITY_ASSESSMENT_V1.md:432-450` registra F4: el workspace
legacy falla `cargo check --workspace` por arms faltantes en el binding PyO3.
La consolidación posterior dejó F4 fuera de alcance. Esta auditoría no repitió
ni corrigió el check: un build roto legacy no invalida el compilador oficial y
arreglarlo sólo para mantenerlo verde contradice el objetivo.

### H7 — el riesgo de consumers externos permanece

El repositorio no puede probar que scripts privados, instalaciones locales o
artefactos publicados no consumen `aether-compiler-core`. Este riesgo queda
**UNRESOLVED** y exige EOL/comunicación antes del borrado, pero no impide cerrar
el inventario interno.

## 8. Incertidumbres y pruebas no realizadas

- No se inspeccionaron repositorios privados, package indexes, releases
  instaladas ni scripts de usuarios externos.
- No se ejecutaron workflows remotos; se inspeccionaron sus triggers y comandos.
- No se ejecutó `cargo check/test` de `compiler-rs`; F4 conocido está fuera de
  alcance y no bloquea esta auditoría.
- No se ejecutó el workspace completo de `compiler-next`; no hubo cambio de
  producto y la auditoría no necesita recompilarlo.
- No se probó cada uno de los 63 scripts ni los 32 tests; su función se
  estableció por source/manifests/call sites.
- Los artefactos ignorados locales no se validaron ni borraron.
- No se determinó todavía si AST/REPL y LSP tendrán soporte futuro: esa es una
  decisión de producto posterior, no una incertidumbre sobre sus dependencies.

## 9. Riesgos priorizados

| Prioridad | Riesgo | Estado |
|---|---|---|
| P0 | Eliminar `compiler-rs` rompe build/install del wheel Python | comprobado |
| P0 | Un fallo legacy bloquea el diferencial de `compiler-next` | comprobado |
| P1 | Workflows PR/scheduled quedan rotos o confusos | comprobado |
| P1 | Retiro arrastra AST/REPL o LSP sin decisión | comprobado |
| P1 | Documentos de authority antigua inducen contratos legacy | comprobado |
| P1 | Consumers externos no inventariados | **UNRESOLVED** |
| P2 | Se pierde corpus/técnica útil al borrar en bloque | mitigable con tag y selección |
| P2 | Se pierden artefactos no versionados locales | mitigable con inventario/backup separado |
| P2 | El retiro se expande a packages Aether, MathTeX o Python general | mitigable con alcance/path allowlist |

## 10. Recomendación de retiro

Recomendación: **aprobar la dirección de retiro, no la eliminación inmediata**.

Orden obligatorio:

1. publicar la política de autoridad;
2. hacer independiente la qualification de `compiler-next`;
3. decidir y desacoplar AST/REPL y LSP;
4. retirar pin, source override, setup hook y adapters;
5. archivar workflows/scripts/tests legacy preservando corpus útil;
6. alinear docs, IDEs y ejemplos;
7. crear una etiqueta histórica anotada sobre un commit deliberadamente
   elegido;
8. repetir auditoría de consumers y qualification;
9. retirar físicamente en un cambio dedicado.

No se recomienda:

- portar schema-v1/v2 o PyO3 a `compiler-next` por compatibilidad;
- arreglar F4 sólo para que el workspace histórico compile;
- usar `compiler-rs` como oracle de aceptación;
- borrar toda implementación Python junto con el core Rust;
- etiquetar el HEAD actual como release sin declarar su estado conocido.

## 11. Qualification de esta auditoría

| Gate | Resultado |
|---|---:|
| branch/HEAD/status/diffs inspeccionados | PASS |
| `origin/main` consultado en remoto | PASS |
| tracked/untracked e ignored legacy inventariados | PASS |
| manifests Cargo/Python/Maturin inspeccionados | PASS |
| búsqueda de path/crates/package/module/binarios | PASS |
| referencias separadas por función | PASS |
| metadata Cargo offline de `compiler-next` | PASS |
| metadata Cargo offline de `compiler-rs` | PASS |
| paths relevantes y dangling symlinks | PASS, cero symlinks colgantes |
| `git diff --check` y whitespace directo de entregables nuevos | PASS |
| código productivo modificado | PASS, ninguno |
| `compiler-rs` borrado/movido/reparado | PASS, no |
| commit/push/tag | PASS, no realizados |
| workspace completo | NOT RUN, fuera de alcance |

Antes de crear los entregables, `git diff --check` pasó sobre el diff previo.
Después de crearlos se volvió a comprobar whitespace y el diff de esta fase; el
resultado final queda registrado en la sección siguiente.

## 12. Estado final

Se cumplieron las condiciones de cierre:

- consumers internos relevantes identificados;
- referencias históricas separadas de dependencies ejecutables;
- capacidades únicas evaluadas sin asumir que deban portarse;
- estrategia verificable y gates definidos;
- política coherente con `compiler-next` propuesta;
- código productivo y trabajo local preservados.

Por tanto, **AUDIT CLOSED**.

La eliminación queda **NOT YET AUTHORIZED**. `compiler-rs`, su distribución y
los componentes marcados **MIGRATION-REQUIRED** deben permanecer hasta ejecutar
el plan. Los posibles consumers externos siguen **UNRESOLVED** y requieren una
verificación/EOL previa al retiro físico.

No se hizo commit ni push y no se inició automáticamente el retiro.
