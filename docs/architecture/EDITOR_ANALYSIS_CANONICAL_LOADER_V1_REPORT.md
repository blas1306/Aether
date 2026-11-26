# EDITOR-ANALYSIS-CANONICAL-LOADER-V1 — reporte

Estado: **CLOSED; IMPLEMENTADO Y QUALIFIED**, 2026-11-25.

Checkout de implementación: `main` @ `eec746d53520`. Se preservaron los
cambios locales preexistentes y no se ejecutaron reset, clean, stash, commit ni
push.

## 1. Arquitectura antes y después

Antes, `aether-driver` era dueño de `CompilationSession`, enumeraba y leía el
filesystem directamente, construía el catálogo, asignaba identidades densas y
resolvía imports. Esto obligaba a cualquier consumidor editorial a depender del
driver completo o a duplicar el loader.

Después, `aether-analysis` es la única autoridad de discovery, catálogo,
`ProjectPlan`, identidades e imports. `aether-driver` depende de esta capa,
reexporta temporalmente `CompilationSession`, `SessionModule`, `ProjectPlan` y
`StandaloneFile`, y conserva únicamente el pipeline batch posterior.

```text
aether-package
      ↓
aether-frontend
      ↓
aether-analysis  (provider + catálogo + imports + sesión)
      ↓
aether-driver    (HIR → MIR → SSA → LLVM/toolchain)
```

No existe una segunda implementación del loader.

## 2. Archivos movidos o adaptados

- `compiler-next/crates/aether-analysis/src/lib.rs`: implementación canónica
  extraída del driver, frontera de sources y tests focales.
- `compiler-next/crates/aether-analysis/Cargo.toml`: crate interno nuevo.
- `compiler-next/crates/aether-driver/src/lib.rs`: eliminación del loader local,
  consumo/reexports de `aether-analysis` y adaptación de timings.
- manifests y lock del workspace: miembro y dependencia nuevos.

No se modificaron frontend, middle, backend LLVM, Python, `compiler-rs`, IDEs ni
OAL.

## 3. Grafo de dependencias

La dependencia directa del crate es:

- `aether-frontend`;
- `aether-package`, para `PackageInstanceKey`, metadata, clases de proyecto y
  nodos resueltos;
- `sha2`, para el fingerprint del contenido efectivamente leído.

`aether-analysis` no depende de driver, middle, backend LLVM, LLVM, clang,
Python ni código legacy. `cargo tree -p aether-analysis --depth 2` confirma el
grafo; `aether-frontend` también depende de `aether-package`.

## 4. Contrato `SourceProvider`

`SourceProvider::enumerate` entrega descriptors ordenables dentro de un
`SourceScope`; `SourceProvider::read` entrega `SourceContent` owned con texto,
`ContentFingerprint` y `SourceProvenance`. El provider no interpreta imports,
no asigna `SourceId`/`ModuleId`, no decide package identity y no modifica
manifest/lock ni accede a red.

`DiskSourceProvider` conserva la recursión `.ae`, el rechazo de symlinks y los
mensajes de IO del loader batch. La construcción canónica normaliza el orden
antes de asignar IDs. `discover_catalog_with_provider` es la frontera preparada
para sustituir el origen del contenido sin duplicar las reglas semánticas.

## 5. Identidades preservadas

Se conserva la construcción existente de `PackageKey`, `SourceUnitKey`,
`PackageInstanceKey`, `PackageId`, `ModuleId` y `SourceId`. Los aliases siguen
siendo bindings locales; `ResolvedImport.target` conserva la identidad
canónica. Las sources de toolchain, grants, visibilidad, roots de packages y
orden de módulos usan el mismo código extraído sin cambios semánticos.

## 6. Consistencia de lectura

Cada lectura exitosa devuelve texto owned e inmutable (`Arc<str>`) y SHA-256 de
exactamente ese texto. La procedencia registra el path y el mismo fingerprint.
El provider compara metadata inmediatamente antes y después de leer y reporta
una inconsistencia observable si cambian longitud o tiempo de modificación.

Esto no es un snapshot transaccional del filesystem: un cambio concurrente que
no altere esas señales puede no detectarse y distintas lecturas pueden observar
instantes distintos. Los errores de enumeración, metadata, UTF-8 o lectura son
fallos explícitos. No se agregaron locks globales. Un futuro snapshot editorial
podrá congelar los `SourceContent` exactos que entregue su provider.

## 7. Tests de equivalencia

Los tests nuevos cubren discovery standalone, imports directos/transitivos,
alias, orden de enumeración invertido con identidades densas/lógicas iguales,
fingerprint/provenance, errores de lectura, entrada inexistente, source de
toolchain y ausencia de escrituras de manifest/lock. Las suites existentes del
driver continúan consumiendo la API reexportada, por lo que ejercitan el mismo
loader desde batch.

## 8. Qualification

Resultados registrados hasta ahora:

- `cargo check --workspace`: PASS.
- `cargo test --workspace -j 1`: PASS; todas las suites y doc-tests terminaron.
- `cargo fmt --all --check`: PASS.
- `cargo clippy --workspace --all-targets -j 1`: PASS; conserva warnings
  preexistentes fuera del cambio y no reporta warnings en `aether-analysis`.
- `git diff --check`: PASS.
- `bash compiler-next/tests/run-differential.sh`: PASS,
  `mode=official checked=96 failures=0`.
- tests focales de `aether-analysis`: 6 PASS.
- `cargo tree -p aether-analysis --depth 2`: PASS; sin middle/backend/legacy.

Todos los comandos concluyeron; no se contabilizaron procesos parciales como
PASS.

## 9. Riesgos

- El filesystem no ofrece atomicidad entre sources; el contrato lo expone en
  vez de prometer coherencia inexistente.
- El reexport del driver preserva compatibilidad interna pero no pretende ser
  una API pública estable.
- La API del provider es deliberadamente mínima; overlays y document store no
  forman parte de este milestone.

## 10. Limitaciones

No se implementaron overlays, document store, versiones documentales,
`AnalysisSnapshot`, mapping UTF-16, recovery nuevo, cancelación, scheduler,
LSP, completion, hover, rename ni REPL. Tampoco se introdujo resolución nueva
de packages ni carga editorial read-only de locks.

## 11. Archivos modificados

- `compiler-next/Cargo.toml`
- `compiler-next/Cargo.lock`
- `compiler-next/crates/aether-analysis/Cargo.toml`
- `compiler-next/crates/aether-analysis/src/lib.rs`
- `compiler-next/crates/aether-driver/Cargo.toml`
- `compiler-next/crates/aether-driver/src/lib.rs`
- `docs/architecture/EDITOR_ANALYSIS_CANONICAL_LOADER_V1_REPORT.md`

## 12. Mensaje de commit sugerido

`refactor(analysis): extract canonical source catalog from driver`
