# Aether — POST-ASSESSMENT-GIT-CONSOLIDATION-V1

Estado: **CONSOLIDATION CLOSED**

Fecha de preflight y reconciliación documental: 2026-11-25.

## 1. Punto de partida verificado

```text
branch: main
HEAD: 3c5c451854cbddb2d5296ed1873ae837a5e03908
HEAD decoration: HEAD -> main, origin/main, origin/HEAD
index: vacío
tracked modificados antes de esta reconciliación: 16
untracked antes de esta reconciliación: 32 archivos
```

El preflight inspeccionó `git status --short`, `git diff`,
`git diff --cached`, la lista expandida de untracked, branch, HEAD y los 15
commits recientes. No se asumió el estado descrito por reportes anteriores.

No se ejecutaron `reset`, `clean`, `stash`, checkout destructivo, commit, push
ni modificación de `origin/main`. El staging continúa vacío. Los programas y
artefactos de `examples/ProbandoNR`, `probandoNR3C` y `tmp_lambda_test.ae` no se
modificaron.

## 2. Reconciliación documental

Se preservó el historial de qualification:

- AMENDMENT-1 mantiene como FAIL la ejecución original de
  `cargo test --workspace -j 1`, incluido su aislamiento al stack overflow
  posterior a las suites F2/Nullable;
- la ejecución posterior de `FRONTEND-STACK-USAGE-V1` se registra por separado:
  el mismo gate completó con PASS, sin `RUST_MIN_STACK`;
- AMENDMENT-1 queda CLOSED porque la única condición pendiente fue satisfecha
  por esa evidencia integrada posterior;
- F3 mantiene su excepción histórica y agrega una nota de seguimiento: la
  corrección F2/Nullable y la corrección de stack hicieron que dejara de
  bloquear el workspace.

No se declara retroactivamente PASS ningún comando que falló.

## 3. Inventario por propietario

### 3.1 Archivos exclusivos

| Milestone | Archivos exclusivos en el estado actual |
|---|---|
| APPLICATION-MATURITY-ASSESSMENT-V1 | `docs/reports/APPLICATION_MATURITY_ASSESSMENT_V1.md`; `examples/assessment/numerical-solver/{aether.toml,aether.lock,src/main.ae}`; manifests y locks versionables de `data-processor` y `expense-tracker` |
| OWNING-COLLECTION-FIELDS-ARCH-1 | `docs/architecture/OWNING_COLLECTION_FIELDS_ARCH_1.md`; `docs/architecture/OWNING_COLLECTION_FIELDS_ARCH_1_REPORT.md` |
| OWNING-COLLECTION-FIELDS-V1 | `compiler-next/crates/aether-driver/tests/owning_collection_fields_v1.rs`; `compiler-next/tests/programs/owning_collection_fields_expense_load.ae`; `docs/architecture/OWNING_COLLECTION_FIELDS_V1_REPORT.md` |
| INDEX-DEREFERENCE-DIAGNOSTIC-V1 + AMENDMENT-1 | `compiler-next/crates/aether-driver/tests/index_dereference_diagnostic_v1.rs`; `docs/architecture/INDEX_DEREFERENCE_DIAGNOSTIC_V1_REPORT.md` |
| APPLICATION-MATURITY-CONSOLIDATION-V1 | `docs/reports/APPLICATION_MATURITY_CONSOLIDATION_V1_REPORT.md` |
| SHAPE-CONTRACT-DIAGNOSTICS-ARCH-1 | `docs/architecture/SHAPE_CONTRACT_DIAGNOSTICS_ARCH_1.md`; `docs/architecture/SHAPE_CONTRACT_DIAGNOSTICS_ARCH_1_REPORT.md` |
| SHAPE-CONTRACT-DIAGNOSTICS-V1 | `compiler-next/crates/aether-frontend/src/{ast.rs,parser.rs,lib.rs}`; `compiler-next/crates/aether-frontend/src/hir/mathematical.rs`; `compiler-next/crates/aether-middle/src/algebraic.rs`; `compiler-next/crates/aether-backend-llvm/src/{algebraic.rs,lib.rs}`; `compiler-next/crates/aether-cli/src/lib.rs`; `compiler-next/crates/aether-cli/tests/bootstrap.rs`; `compiler-next/crates/aether-driver/tests/{language_parity.rs,shape_guard_v1.rs,shape_contract_diagnostics_v1.rs}` |
| FRONTEND-STACK-USAGE-V1 | `compiler-next/crates/aether-driver/tests/frontend_stack_usage_v1.rs`; `docs/architecture/FRONTEND_STACK_USAGE_V1_REPORT.md` |
| POST-ASSESSMENT-GIT-CONSOLIDATION-V1 | este reporte |

“Exclusivo” describe la propiedad del cambio pendiente, no que el archivo haya
sido creado originalmente por el milestone. Los archivos productivos listados
para F3 contienen sólo hunks de F3 en el diff actual.

### 3.2 Archivos compartidos y hunks

| Archivo | Propietarios | Separación verificable |
|---|---|---|
| `aether-frontend/src/hir.rs` | F2/AMENDMENT-1, F3, FRONTEND-STACK-USAGE-V1 | F2: rama `Dereference`, `flow_refined_place_type`, detección de Place y E0271. F3: metadata/site IDs, source provenance, guards/productos y verificadores. Stack: dispatcher `expression_non_logical`, `logical_binary`, `substitute_short_circuit` y eliminación de recursión lógica. Los grupos ocupan hunks distintos salvo que F2 original y su enmienda están entrelazados en un único hunk final. |
| `aether-middle/src/mir.rs` | F3, FRONTEND-STACK-USAGE-V1 | F3: metadata/observaciones de `ShapeGuard`, transporte algebraico y verificadores. Stack: dispatch y `lower_short_circuit` iterativo. Hunks distintos. |
| `aether-middle/src/ssa.rs` | F1, F3 | F1: `descriptor_mutation`, continuidad `InsertField`, ledger de owners y autorización `DescriptorCommit`. F3: metadata/observaciones de terminadores, provenance de sitios y diagnóstico algebraico. Hunks distintos. |
| `index_dereference_diagnostic_v1.rs` | F2 y AMENDMENT-1 | el archivo no rastreado contiene la suite final de 6 tests; reconstruir artificialmente la versión intermedia de 4 tests no aporta un estado técnico mejor. |
| `INDEX_DEREFERENCE_DIAGNOSTIC_V1_REPORT.md` | F2 y AMENDMENT-1 | el reporte base conserva el cierre original y enlaza la enmienda posterior. |
| `INDEX_DEREFERENCE_DIAGNOSTIC_V1_AMENDMENT_1_REPORT.md` | AMENDMENT-1 y esta reconciliación | conserva PARTIAL como hecho histórico y agrega el cierre posterior; se difiere al commit documental final. |
| `SHAPE_CONTRACT_DIAGNOSTICS_V1_REPORT.md` | F3 y esta reconciliación | conserva la excepción histórica y agrega sólo la nota de seguimiento; se difiere al commit documental final. |
| `examples/assessment/data-processor/src/main.ae` | Assessment + Application Consolidation | el archivo completo es untracked; el baseline previo sólo existe descrito en el reporte. No se propone reconstruirlo. |
| `examples/assessment/expense-tracker/src/main.ae` | Assessment + Application Consolidation | igual: el estado final depende de F1 y no se reconstruirá un baseline incompleto desde prosa. |

### 3.3 Archivos ajenos o personales — excluidos

| Archivo | Evidencia/clasificación |
|---|---|
| `examples/ProbandoNR/probandoNR2.ae` | cambio tracked personal, ya presente durante los milestones |
| `examples/ProbandoNR/probandoNR3.ae` | cambio tracked personal, ya presente durante los milestones |
| `tmp_lambda_test.ae` | scratch untracked citado como ajeno por los reportes |

No se incluirán en ninguna operación de staging.

### 3.4 Generados — excluidos

| Archivo | Tipo |
|---|---|
| `examples/ProbandoNR/.aether-package.lock` | lock efímero vacío |
| `examples/ProbandoNR/probandoNR2` | ELF x86-64 |
| `examples/ProbandoNR/probandoNR3` | ELF x86-64 |
| `probandoNR3C` | ELF x86-64 |
| `examples/assessment/data-processor/.aether-package.lock` | lock efímero vacío |
| `examples/assessment/expense-tracker/.aether-package.lock` | lock efímero vacío |

Los `aether.lock` no se clasifican aquí como outputs innecesarios: el
assessment los enumera expresamente como entregables versionables de los tres
packages.

### 3.5 Pertenencia indeterminada

No se encontró ningún archivo restante que deba incorporarse con pertenencia
indeterminada. `tmp_lambda_test.ae` y los artefactos NR están explícitamente
identificados como ajenos/generados por los preflights previos y por su tipo.
Si aparecieran archivos nuevos antes del staging, quedarán excluidos hasta una
nueva atribución explícita.

## 4. Secuencia de commits propuesta

La secuencia prioriza estados técnicos coherentes. No pretende reproducir como
commits snapshots locales que nunca existieron en Git.

### C1 — arquitectura de owning collection fields

Mensaje sugerido: `docs(compiler): define owning collection field continuity`

Archivos completos:

- `docs/architecture/OWNING_COLLECTION_FIELDS_ARCH_1.md`;
- `docs/architecture/OWNING_COLLECTION_FIELDS_ARCH_1_REPORT.md`.

### C2 — implementación F1

Mensaje sugerido: `fix(compiler): preserve owning collection field continuity`

Archivos/hunks:

- `compiler-next/crates/aether-middle/src/ssa.rs`: sólo `descriptor_mutation`,
  `verify_descriptor_insert_continuations`, integración del verifier,
  `DescriptorCommit`, consumos de `ListPush`/`ListReserve`/`MatrixAdd` e
  `InsertField`, y excepción verificada de projected Store;
- `compiler-next/crates/aether-driver/tests/owning_collection_fields_v1.rs`
  completo;
- `compiler-next/tests/programs/owning_collection_fields_expense_load.ae`
  completo;
- `docs/architecture/OWNING_COLLECTION_FIELDS_V1_REPORT.md` completo.

### C3 — F2 y su enmienda técnica final

Mensaje sugerido: `fix(frontend): preserve refined references in dereference diagnostics`

Archivos/hunks:

- `compiler-next/crates/aether-frontend/src/hir.rs`: exclusivamente el hunk de
  Dereference y los helpers `flow_refined_place_type`,
  `dereference_operand_is_place` e `invalid_dereference`;
- `compiler-next/crates/aether-driver/tests/index_dereference_diagnostic_v1.rs`
  completo;
- `docs/architecture/INDEX_DEREFERENCE_DIAGNOSTIC_V1_REPORT.md` completo.

F2 original y AMENDMENT-1 no se separan: su implementación final ocupa el mismo
hunk y una separación exigiría reconstruir temporalmente la regresión Nullable
ya conocida. El reporte formal de la enmienda se incorpora en C8, después de la
evidencia de stack que permite cerrarlo.

### C4 — aplicaciones de assessment y consolidation integradas

Mensaje sugerido: `feat(examples): add consolidated maturity assessment apps`

Archivos completos:

- `docs/reports/APPLICATION_MATURITY_ASSESSMENT_V1.md`;
- `docs/reports/APPLICATION_MATURITY_CONSOLIDATION_V1_REPORT.md`;
- `examples/assessment/numerical-solver/aether.toml`;
- `examples/assessment/numerical-solver/aether.lock`;
- `examples/assessment/numerical-solver/src/main.ae`;
- `examples/assessment/data-processor/aether.toml`;
- `examples/assessment/data-processor/aether.lock`;
- `examples/assessment/data-processor/src/main.ae`;
- `examples/assessment/expense-tracker/aether.toml`;
- `examples/assessment/expense-tracker/aether.lock`;
- `examples/assessment/expense-tracker/src/main.ae`.

Assessment y consolidation se agrupan porque `data-processor` y
`expense-tracker` son adiciones untracked cuyo baseline intermedio sólo está
documentado; el estado final de Expense Tracker además depende de C2 para
compilar. Los `.aether-package.lock` quedan fuera.

### C5 — arquitectura de diagnósticos de shape

Mensaje sugerido: `docs(compiler): define abortive shape contract diagnostics`

Archivos completos:

- `docs/architecture/SHAPE_CONTRACT_DIAGNOSTICS_ARCH_1.md`;
- `docs/architecture/SHAPE_CONTRACT_DIAGNOSTICS_ARCH_1_REPORT.md`.

### C6 — implementación F3

Mensaje sugerido: `feat(compiler): report shape contract failures by source site`

Archivos/hunks:

- completos: `compiler-next/crates/aether-frontend/src/ast.rs`,
  `compiler-next/crates/aether-frontend/src/parser.rs`,
  `compiler-next/crates/aether-frontend/src/lib.rs`,
  `compiler-next/crates/aether-frontend/src/hir/mathematical.rs`,
  `compiler-next/crates/aether-middle/src/algebraic.rs`,
  `compiler-next/crates/aether-backend-llvm/src/algebraic.rs`,
  `compiler-next/crates/aether-backend-llvm/src/lib.rs`,
  `compiler-next/crates/aether-cli/src/lib.rs`,
  `compiler-next/crates/aether-cli/tests/bootstrap.rs`,
  `compiler-next/crates/aether-driver/tests/language_parity.rs`,
  `compiler-next/crates/aether-driver/tests/shape_guard_v1.rs` y
  `compiler-next/crates/aether-driver/tests/shape_contract_diagnostics_v1.rs`;
- `compiler-next/crates/aether-frontend/src/hir.rs`: sólo metadata/site IDs,
  source provenance, transporte de
  `ShapeGuard`/`AlgebraicProduct`, captura de extents y verificadores/corruption;
- `compiler-next/crates/aether-middle/src/mir.rs`: sólo campos/observaciones de
  ShapeGuard, transporte algebraico y verificadores de sitio/operando;
- `compiler-next/crates/aether-middle/src/ssa.rs`: sólo terminador/renaming,
  verificación de identidad/observaciones y ownership del diagnóstico
  algebraico.

El reporte de implementación F3 se difiere a C8 para no crear primero una
versión artificial sin la nota de seguimiento posterior.

### C7 — corrección de uso de stack del frontend

Mensaje sugerido: `fix(frontend): flatten logical-expression traversal`

Archivos/hunks:

- `compiler-next/crates/aether-frontend/src/hir.rs`: dispatcher pequeño,
  `expression_non_logical`, `logical_binary` iterativo,
  `substitute_short_circuit` iterativo y retiro de las ramas recursivas
  correspondientes;
- `compiler-next/crates/aether-middle/src/mir.rs`: dispatch de short-circuit,
  `lower_short_circuit` iterativo y retiro de la rama recursiva;
- `compiler-next/crates/aether-driver/tests/frontend_stack_usage_v1.rs`
  completo;
- `docs/architecture/FRONTEND_STACK_USAGE_V1_REPORT.md` completo.

### C8 — cierre documental integrado

Mensaje sugerido: `docs(compiler): reconcile F2 F3 and stack qualification`

Archivos completos:

- `docs/architecture/INDEX_DEREFERENCE_DIAGNOSTIC_V1_AMENDMENT_1_REPORT.md`;
- `docs/architecture/SHAPE_CONTRACT_DIAGNOSTICS_V1_REPORT.md`.

Este commit conserva los FAIL históricos y agrega únicamente la evidencia
posterior que elimina el bloqueo. Depende de C7.

### C9 — reporte de consolidación Git

Mensaje sugerido: `docs(repo): record post-assessment git consolidation`

Archivo completo:
`docs/reports/POST_ASSESSMENT_GIT_CONSOLIDATION_V1_REPORT.md`, actualizado en la
fase de ejecución con hashes de commits, resultados de gates y cualquier
limitación real. Este commit sólo se propondrá después de revisar la división.

## 5. Riesgos de separación

1. `hir.rs`, `mir.rs` y `ssa.rs` requieren staging por patch/hunk y revisión del
   diff staged; `git add` por archivo mezclaría milestones.
2. Algunos hunks tienen contexto cercano después de aplicar los anteriores. Se
   debe regenerar el patch desde el diff restante después de cada commit, no
   reutilizar offsets antiguos a ciegas.
3. F2 original y AMENDMENT-1 no son separables de forma segura en código/test
   sin reconstruir una regresión conocida; se mantienen como una unidad técnica.
4. Las dos aplicaciones refactorizadas no conservan un baseline versionado. La
   reconstrucción desde snippets de reporte sería incompleta y arriesgaría
   formatos/errores; se usa un commit integrado y se declara explícitamente.
5. C6 puede pasar sus suites focales, pero el gate global histórico todavía
   encuentra el stack overflow independiente hasta C7. No se afirmará
   independencia global ni PASS del workspace para C6.
6. El reporte final debe actualizarse sólo con resultados realmente ejecutados;
   no se copiarán resultados históricos como si fueran de la secuencia nueva.

## 6. Protocolo de staging y qualification

Para cada commit lógico:

1. agregar sólo paths explícitos y, en compartidos, aplicar/stagear un patch
   revisado; nunca `git add .` ni `git add -A`;
2. comprobar `git diff --cached --check`;
3. inspeccionar `git diff --cached --stat`, `--name-status` y el diff staged
   completo relevante;
4. comparar la lista staged con este inventario y confirmar ausencia de
   `ProbandoNR`, scratch, binarios y locks efímeros;
5. para estados intermedios con Rust, construir una exportación acumulativa en
   `/tmp` desde HEAD más los patches de la secuencia, evitando alterar el
   worktree compartido;
6. ejecutar suites focales del milestone y `cargo check --workspace` cuando el
   estado sea técnicamente completo;
7. registrar explícitamente cualquier gate no viable o fallo esperado, sin
   convertirlo en PASS.

Qualification focal mínima propuesta:

| Commit | Qualification |
|---|---|
| C1, C5, C8, C9 | diff checks y revisión documental |
| C2 | `owning_collection_fields_v1`, `ssa_store_provenance_v1`, replacement owning y `cargo check --workspace` |
| C3 | `index_dereference_diagnostic_v1`, `nullable_v1`, borrow/iteration/text y `cargo check --workspace` |
| C4 | check y ejecución O0/O2 de los tres consumers; focales Text/IO/Process/Linear Algebra/F1/F2 |
| C6 | `shape_contract_diagnostics_v1`, `shape_guard_v1`, bootstrap, kernels, solve y exceptions; `cargo check --workspace` |
| C7 | test exacto antes bloqueado, `frontend_stack_usage_v1`, Numeric/Nullable/F1/F2/F3 y gates globales |

Al finalizar la secuencia propuesta, desde `compiler-next` y sin
`RUST_MIN_STACK`:

```text
cargo check --workspace
cargo test --workspace -j 1
cargo fmt --all --check
cargo clippy --workspace --all-targets -j 1
```

Y desde la raíz:

```text
git diff --check
```

## 7. Preflight de ejecución

La ejecución repitió el preflight antes de C1:

```text
branch: main
HEAD: 3c5c451854cbddb2d5296ed1873ae837a5e03908
index: vacío
tracking: main...origin/main, sin divergencia inicial
tracked modificados: 16
untracked: 32 archivos expandidos
```

El inventario coincidió con el plan: 14 sources Rust modificados, dos cambios
personales tracked en `examples/ProbandoNR`, cuatro tests nuevos, un fixture de
programa, los reportes previstos, tres packages de assessment y los artefactos
personales/generados ya clasificados. Ningún archivo relevante tenía mtime
posterior al reporte de planificación. No se detectó deriva que modificara
hunks atribuidos a un milestone y el index estaba vacío.

No se usó `git add .`, `git add -A`, `reset`, `clean`, `stash` ni checkout
destructivo. Los tres archivos compartidos se dividieron mediante patches
aplicados al index y regenerados después de cada commit propietario.

## 8. Commits creados

| ID | Hash | Mensaje | Archivos y propiedad |
|---|---|---|---|
| C1 | `57bc15ee918478862d586e83704411030c6d1ff1` | `docs(compiler): define owning collection field continuity` | 2 documentos F1 ARCH |
| C2 | `952363de6da5d020696ca80aa07d37be9bb58733` | `fix(compiler): preserve owning collection field continuity` | suite, fixture, reporte y sólo 5 grupos F1 de `ssa.rs`: integración del verifier, continuidad de descriptor, provenance, ledger y Store |
| C3 | `635debebd96fb8d0a430f101fd664249e0938606` | `fix(frontend): preserve refined references in dereference diagnostics` | suite/reporte F2 y sólo la rama Dereference más `flow_refined_place_type`, detección de Place y E0271 en `hir.rs` |
| C4 | `b2a0a4d9360d478e4085f8eb75c38263d66c4a48` | `feat(examples): add consolidated maturity assessment apps` | 2 reportes y 9 manifests/locks/sources versionables de los tres packages |
| C5 | `21074cad0934c55162784d147e66ad485f5e7f28` | `docs(compiler): define abortive shape contract diagnostics` | 2 documentos F3 ARCH |
| C6 | `8c720f9db9efb10271ed9bc069e8d9986287dca3` | `feat(compiler): report shape contract failures by source site` | 15 rutas productivas/tests F3 más el reporte histórico F3; `hir.rs`, `mir.rs` y `ssa.rs` contienen sólo metadata, sitio, observaciones, provenance y verificadores F3 |
| C7 | `b8ca58b5208526bfc73439ddc39aebad7fa9ba35` | `fix(frontend): flatten logical-expression traversal` | test/reporte Stack y sólo los dispatchers/recorridos iterativos de `hir.rs` y `mir.rs` |
| C8 | `cd4fe98327f916720ecb00c2cd19c27cf07f20d4` | `docs(compiler): reconcile F2 F3 and stack qualification` | reporte formal AMENDMENT-1 y nota posterior de reconciliación F3 |
| C9 | no se autorreferencia | `docs(repo): record post-assessment git consolidation` | este reporte final |

Dependencias preservadas: C1→C2; C2+C3→C4; C5→C6→C7→C8; C9 registra C1–C8.
F2 original y su enmienda técnica permanecen unidos en C3 porque comparten un
hunk final válido. Las aplicaciones permanecen integradas en C4 porque no
existe un baseline intermedio versionado seguro.

El ajuste documental solicitado sí fue aplicado sin reconstrucción riesgosa:
C6 contiene el reporte histórico F3 sin su nota posterior y conserva
explícitamente el FAIL original; C8 añade únicamente la reconciliación F3 y el
reporte final F2.

## 9. Qualification acumulativa real

| Commit | Evidencia ejecutada sobre exportación aislada del index | Resultado |
|---|---|---|
| C1 | `diff --cached --check` y revisión de los 2 documentos | PASS |
| C2 | `owning_collection_fields_v1` 6/6; `ssa_store_provenance_v1` 5/5; owning replacement 16/16; `cargo check --workspace` | PASS |
| C3 | frontend 98/98; F2 6/6; Nullable 10/10; Borrow 8/8; Iteration 6/6; Text 8/8; workspace check | PASS |
| C4 | `check` y ejecución de los 3 packages en O0/O2; comparación byte a byte; workspace check | PASS |
| C5 | `diff --cached --check` y revisión documental | PASS después de retirar una línea en blanco final rechazada por el gate |
| C6 | workspace check; F3 4/4; ShapeGuard 8/8; solve 9/9; MatrixAdd 6/6; Vertical 31/32/33 10/10, 12/12, 12/12; exceptions 34/34; bootstrap 1/1 | PASS focal |
| C6 limitación | test exacto `numeric_capabilities_v1::every_numeric_capability_and_alias_reifies_before_mir`, sin `RUST_MIN_STACK` | **FAIL esperado: stack overflow, SIGABRT**; depende de C7 |
| C7 | test exacto anterior; `frontend_stack_usage_v1` 3/3; gates globales; apps O0/O2 | PASS |
| C8 | diff check y revisión de sólo 2 cambios documentales; reutiliza C7 | PASS |
| C9 | diff check y revisión de este reporte | PASS requerido antes del commit |

Cada exportación se produjo desde el index acumulativo con
`git checkout-index --all --prefix=...`; el worktree completo nunca sustituyó
un estado intermedio.

En C4 y nuevamente después de C7:

- Numerical Solver produjo el mismo LU/QR en O0/O2;
- Data Processor produjo output byte-idéntico, SHA-256
  `6306fe4e7fef05e3e4c1b4bdf2dd62c74fbbfa26e7325dadffc2e8ac8de3da4b`;
- Expense Tracker persistió, listó y totalizó `19.75` en ambos perfiles, con
  ledger byte-idéntico y SHA-256
  `e0293676ec66be329261a9388b33ac287ecf09bb676e4f9e23805d8ebd754616`.

## 10. Gates finales después de C7

Ejecutados desde `compiler-next`, sobre la exportación exacta C7 y con
`RUST_MIN_STACK` ausente:

| Gate | Resultado real |
|---|---|
| test exacto antes bloqueado | PASS |
| `frontend_stack_usage_v1` | 3/3 PASS |
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | PASS completo; el test final largo terminó en 708,84 s |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS, exit 0, con warnings preexistentes/no relacionados |
| `git diff --check` desde la raíz | PASS |
| 3 consumers, `check` y ejecución O0/O2 | PASS |

Dos intentos iniciales del gate global no alcanzaron la fase de tests: el target
de Cargo llenó el tmpfs `/tmp` (7,5 GiB) y `ld` terminó con SIGBUS al enlazar
dos binaries distintos. No se clasificaron como fallos del código. Se retiraron
únicamente los temporales creados por esta ejecución y se repitió desde el mismo
source exportado con el target en disco; esa ejecución completó todos los gates.
Los targets/exportaciones temporales de qualification fueron eliminados al
final y no contenían trabajo fuente.

## 11. Exclusiones verificadas

Ningún commit incluye:

- `examples/ProbandoNR/probandoNR2.ae` ni `probandoNR3.ae`;
- `.aether-package.lock` de `ProbandoNR`, Data Processor o Expense Tracker;
- binarios `examples/ProbandoNR/probandoNR2`, `probandoNR3` o `probandoNR3C`;
- `tmp_lambda_test.ae`;
- cualquier archivo no identificado.

Los `aether.lock` versionables de los tres packages sí están en C4 conforme al
inventario aprobado. Los archivos personales fueron comprobados mediante
`git status`, `git diff --name-status` y la lista staged antes de cada commit.

## 12. Estado final y limitaciones

Después de C9, `main` queda nueve commits por delante de `origin/main`, sin
push. El index queda vacío. El worktree conserva únicamente cambios personales
y generados fuera de los milestones:

```text
 M examples/ProbandoNR/probandoNR2.ae
 M examples/ProbandoNR/probandoNR3.ae
?? examples/ProbandoNR/.aether-package.lock
?? examples/ProbandoNR/probandoNR2
?? examples/ProbandoNR/probandoNR3
?? examples/assessment/data-processor/.aether-package.lock
?? examples/assessment/expense-tracker/.aether-package.lock
?? probandoNR3C
?? tmp_lambda_test.ae
```

Limitaciones reales:

- el reporte no contiene el hash de C9 por diseño; C9 no se autorreferencia;
- los warnings Clippy existentes no fueron corregidos fuera de sus milestones;
- la qualification target-specific de señales continúa limitada al bootstrap
  Linux x86-64 documentado por F3;
- los baselines intermedios no versionados de las aplicaciones y F2 original
  no fueron reconstruidos artificialmente.

La secuencia es coherente, la propiedad de hunks fue verificada, no quedan
modificaciones productivas pendientes de los milestones, las aplicaciones y
gates finales pasan y los archivos personales permanecen fuera de los commits.
Por tanto se declara **CONSOLIDATION CLOSED**.
