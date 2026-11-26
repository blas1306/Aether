# AETHER-LSP-RUST-DIAGNOSTICS-V1 — reporte

Estado: **CLOSED; IMPLEMENTADO Y QUALIFIED**, 2026-11-26.

Checkout: `main` @ `678e26cfc472353137f07fe531ece57c41386fab`, inicialmente
un commit por delante de `origin/main`. Se preservaron los cambios personales y
no se ejecutó reset, clean, stash, commit ni push.

## 1. Arquitectura del servidor

Se agregó el crate interno `compiler-next/crates/aether-lsp` y el binario
`aether-lsp --stdio`. El proceso tiene un reader JSON-RPC en el thread principal,
el `AnalysisScheduler` serial oficial de `aether-analysis`, waiters livianos para
recoger resultados y un único writer propietario de stdout. Logs y fallos
internos van exclusivamente a stderr.

El crate depende sólo de `aether-analysis` y `serde_json`. No depende de driver,
middle, backend LLVM, Python ni `compiler-rs`. El pipeline de diagnostics termina
en HIR verificado mediante `CanonicalAnalyzer`; no construye MIR/SSA ni ejecuta
toolchain.

## 2. Biblioteca protocolar elegida

Se eligió una capa protocolar mínima sobre `serde_json`, dependencia ya presente
en el workspace, en lugar de un framework LSP/async. El alcance V1 contiene ocho
métodos simples y no requiere routing tipado, runtime async ni APIs de features.
La implementación local deja explícitos y testeables el framing, el writer único
y el orden atómico de publicación sin agregar dependencias transitivas.

## 3. Capabilities anunciadas

El initialize anuncia únicamente:

- `positionEncoding: "utf-16"`;
- `textDocumentSync.openClose: true`;
- `textDocumentSync.change: 1` (`Full`);
- `textDocumentSync.save.includeText: false`.

No anuncia completion, hover, formatting, definition, references, rename ni
ninguna feature fuera del milestone. Requests desconocidas reciben `-32601` y
notificaciones desconocidas se ignoran de forma segura.

## 4. Gestión de documentos

`didOpen`, `didChange`, `didSave` y `didClose` se traducen directamente a
`EditorWorkspace`. `DocumentId` permanece estable en el store,
`DocumentVersion` es monotónica y la versión del cliente se conserva en
`publishDiagnostics`. V1 usa full-text: exige exactamente un content change sin
`range`; un cambio incremental se rechaza y no modifica el overlay.

Save llama a `SavedDocument`: observa el disco pero no confía en el texto de la
notificación, no escribe y conserva el overlay. Close elimina el overlay,
invalida su época de publicación y limpia diagnostics.

Todos los documentos abiertos entran en cada `AnalysisSnapshot`; por eso un
módulo importado no guardado participa transitivamente sin archivos temporales.

## 5. Integración con `aether-analysis`

Cada edición agenda `AnalysisTarget::Document` mediante el único
`AnalysisScheduler` del workspace. Éste captura `AnalysisSnapshot`, ejecuta
`CanonicalAnalyzer`, usa `CancellationToken`, produce `SourceTable` y
`EditorDiagnostic`, y aplica `may_publish_analysis` antes de entregar un
resultado. `Partial + Invalid` se publica como diagnostics, nunca como éxito.

Para proyectos se agregó `aether_package::load_locked`, frontera estrictamente
read-only que valida un lock existente sin transaction lock, red, resolución
nueva ni escrituras. `ProjectPlan::load_read_only` adapta ese grafo usando la
autoridad existente. Sólo el entry validado recibe el plan; imports abiertos se
incorporan como overlays del mismo snapshot. Un proyecto que no puede validarse
así falla seguro en stderr y se analiza como archivo standalone cuando sea
posible.

## 6. Garantías de publicación

El scheduler primero descarta cancellation, snapshot stale, target cerrado y
sources de disco cambiadas. En la frontera de transporte existe una segunda
compuerta por `DocumentId` con época monotónica.

La comprobación de época/open y la inserción en la cola del writer ocurren bajo
el mismo mutex corto. El IO físico sucede después, en el writer, sin lock de
análisis. Por lo tanto una edición o close que adquiere después el mutex encola
su resultado/limpieza después de la publicación ya validada; y si adquiere antes,
la época vieja ya no valida. No se mantiene ningún lock durante stdout.

## 7. Cancelación y concurrencia

Cada edición vuelve a agendar todos los targets abiertos porque cualquier
overlay puede alterar topología/imports. El scheduler oficial cancela el request
running del mismo target, elimina queued obsoletos y conserva checkpoints entre
fases. No se promete preemption dentro de parser/typechecker.

Los waiters sólo esperan handles oficiales. Panic del frontend es recuperado por
el scheduler; errores internos se escriben en stderr y no se convierten en
errores sintácticos. Shutdown cancela la cola, solicita cancelación del trabajo
activo, hace join del worker y responde antes de esperar `exit`.

`$/cancelRequest` es aceptado. En V1 no hay requests LSP largos gestionados: los
análisis son trabajo interno provocado por notificaciones y su cancelación se
realiza por invalidación documental, no por ids JSON-RPC.

## 8. Diagnósticos multiarchivo

`SourceIdentity::Document` se resuelve con el registro estable de URI y
`SourceIdentity::Disk` con URI `file:` escapada. Rangos y related information se
copian desde `EditorDiagnostic`; severidad, code y message no se reinterpretan.
Sources toolchain sin URI editable no se atribuyen a un documento del usuario.

Cada target mantiene contribuciones por URI. Al completar un análisis se
reemplaza sólo la contribución de ese target y se publica la unión de las demás;
así un análisis multiarchivo no borra diagnostics vigentes de otro target. Close
retira esa URI de todas las contribuciones y publica una lista vacía.

## 9. Tests protocolarios

`crates/aether-lsp/tests/protocol.rs` ejecuta el binario real y cubre:

- initialize/initialized/shutdown/exit y capabilities mínimas;
- framing `Content-Length` y mensajes consecutivos;
- open/change/save/close, versiones y limpieza;
- overlay importado no guardado y publicación en su URI;
- diagnostics léxicos, sintácticos, semánticos y ownership (`E0291`);
- rango UTF-16 después de un emoji;
- ediciones rápidas, cancelación y observación exclusiva de la versión actual;
- request desconocida y recuperación después de JSON malformado.

Los tests de `aether-analysis` cubren además overlay transitivo, source changes,
panic recuperable, queue coalescing, stale suppression, cierre durante análisis
y shutdown determinista mediante observers/condvars, sin sleeps.

## 10. Qualification

Resultados confirmados:

- `cargo test -p aether-lsp`: PASS (2 unitarios, 2 end-to-end, doc-tests).
- `cargo test -p aether-analysis -j 1`: PASS (36).
- `cargo test -p aether-package -j 1`: PASS.
- `cargo check --workspace`: PASS.
- `cargo fmt --all --check`: PASS final.
- `cargo clippy -p aether-lsp --all-targets -j 1`: PASS sin warnings propios;
  se conserva un warning preexistente de `aether-frontend`.
- `cargo clippy --workspace --all-targets -j 1`: PASS con warnings
  preexistentes fuera del cambio.
- `cargo test --workspace -j 1`: PASS completo; el caso QR del registry
  concluyó en 710,79 s.
- `bash compiler-next/tests/test-differential-harness.sh`: PASS.
- `bash compiler-next/tests/run-differential.sh`: PASS,
  `mode=official checked=96 failures=0`.
- `npm test` en `vscode-extension`: PASS, 4/4.
- `./gradlew test --no-daemon`: PASS, incluyendo la integración IntelliJ.
- `git diff --check`: PASS.

`cargo tree -p aether-lsp` debe conservar únicamente
`aether-lsp → aether-analysis → aether-frontend/aether-package` más
`serde_json`; no aparece código legacy ni backend.

## 11. Limitaciones

V1 sólo acepta documentos `file:`. No implementa features de navegación o
edición, debounce, parsing incremental ni preemption dentro de una fase frontend.
Los packages de registry que no puedan validarse offline con la autoridad actual
fallan seguro; el servidor no sincroniza, actualiza, descarga ni materializa.
No se reemplazó el LSP Python instalado ni las configuraciones predeterminadas de
VS Code/IntelliJ. No se realizaron smoke tests GUI en este entorno sin IDE.

## 12. Archivos modificados

- `compiler-next/Cargo.toml`
- `compiler-next/Cargo.lock`
- `compiler-next/crates/aether-package/src/lib.rs`
- `compiler-next/crates/aether-analysis/src/lib.rs`
- `compiler-next/crates/aether-lsp/Cargo.toml`
- `compiler-next/crates/aether-lsp/src/lib.rs`
- `compiler-next/crates/aether-lsp/src/main.rs`
- `compiler-next/crates/aether-lsp/tests/protocol.rs`
- `docs/architecture/AETHER_LSP_RUST_DIAGNOSTICS_V1_REPORT.md`

## 13. Prueba manual temporal

Construir sin instalar ni reemplazar el Python:

```bash
cd compiler-next
cargo build -p aether-lsp
```

Ruta explícita:

```text
<checkout>/compiler-next/target/debug/aether-lsp
```

En VS Code configurar temporalmente `aether.lsp.executable` con esa ruta. En
IntelliJ, Settings → Languages & Frameworks → Aether → “Aether language server
executable”, usar la misma ruta. Ambos launchers ya agregan `--stdio`. Restaurar
la preferencia después de validar; no se cambió ningún default del repositorio.

## 14. Mensaje de commit sugerido

`feat(lsp): add native Rust diagnostics server`
