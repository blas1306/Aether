# Aether — LSP-DOCUMENT-SYMBOLS-REFRESH-INVESTIGATION-V1

Fecha: 2026-11-26
Estado: **INVESTIGATION CLOSED — recuperación verificada; causa histórica no identificada.**

## 1. Alcance y conclusión

Se auditó el ciclo completo de `textDocument/documentSymbol` desde `didOpen` y `didChange`
hasta `AnalysisScheduler`, `RequestCompletion`, adaptación JSON-RPC y el cliente oficial de VS
Code. También se agregaron reproducciones contra el binario real `aether-lsp --stdio`.

La secuencia servidor válida → inválida → válida recupera los símbolos sin reiniciar. Lo mismo
ocurre al insertar sólo líneas en blanco, agregar un enum válido, enviar varias ediciones rápidas
y cancelar una request anterior mientras se agenda una nueva. El archivo manual final compila y
ejecuta con la CLI oficial.

Una verificación manual posterior observó además que Outline se recuperó automáticamente después
de restaurar un error sintáctico transitorio, sin ejecutar `Developer: Reload Window`. Por tanto,
la recuperación manual observada y las reproducciones stdio son **PASS**. Sin embargo, **no se
confirmó un defecto productivo del servidor, frontend o cliente**, no se hizo una corrección
especulativa y la causa raíz del fallo histórico permanece **NO IDENTIFICADA**. La recuperación
posterior verifica el comportamiento actual, pero no explica definitivamente la sesión original.

## 2. Preflight y preservación

El preflight de cierre encontró `main` en `f6929c4ab819a1805fa8f57a678eeeb11c74eeb9`,
cuatro commits por delante de `origin/main` (`961427e6fb71ac5aad94c4e4a8658a0c248d93bd`),
sin cambios staged, y cambios personales en:

- `examples/ProbandoNR/probandoNR2.ae`: enum `Color` con `Rojo`, `Verde` y `Azul`.
- `examples/ProbandoNR/probandoNR4.ae`: helper `derivada` y ajuste de la fórmula iterativa.

También se preservaron `probandoNR3.ae`, `.aether-package.lock`, ejecutables generados, el archivo C,
`scrap/`, el VSIX instalado localmente, `node_modules/`, `out/`, targets, builds y el resto de locks,
binarios y temporales ignorados. No se ejecutaron `reset`, `clean` ni `stash`, y no se hizo push.

## 3. Evidencia manual recibida

La sesión manual reportó:

1. Outline mostró inicialmente `NewtonResultado`, sus campos y las funciones.
2. Tras insertar líneas en blanco y agregar un enum, Outline quedó vacío.
3. El canal Aether registró `textDocument/documentSymbol` fallidas con
   `RequestFailed (-32803)` y estado `Partial / Parse / FrontendStopped`.
4. `aether run examples/ProbandoNR/probandoNR2.ae` compiló y ejecutó correctamente.
5. `Developer: Reload Window` recuperó `NewtonResultado`, `Color`, sus miembros y las funciones.

Esta evidencia demuestra una divergencia observable entre la UI y el archivo final en disco, pero
no conserva la secuencia de `didChange`, versiones, IDs de request y respuestas necesaria para
atribuirla a un componente concreto.

### 3.1 Evidencia manual posterior — 26 de noviembre de 2026

En una segunda verificación manual se observaron estos hechos:

1. VS Code ejecutaba el servidor Rust.
2. `textDocument/documentSymbol` funcionaba inicialmente.
3. Se eliminó temporalmente la coma después de `Verde` dentro de `enum Color`.
4. El parser informó `expected ',' after enum variant`.
5. Outline dejó de mostrar símbolos durante el error sintáctico.
6. Se restauró la coma.
7. El diagnóstico sintáctico desapareció.
8. Outline recuperó automáticamente `NewtonResultado`, sus campos, `Color`, sus variantes y las
   funciones.
9. No se ejecutó `Developer: Reload Window` durante esta recuperación.
10. La traza verbose estaba activa, pero las capturas no conservan el intercambio completo de
    requests y respuestas.

Clasificación de cierre:

- Recuperación manual observada: **PASS**.
- Tests stdio de recuperación: **PASS**.
- Causa raíz del fallo histórico: **NO IDENTIFICADA**.
- Corrección productiva: **NO REALIZADA**, porque no se demostró un defecto.

Esta recuperación posterior no constituye una explicación definitiva del fallo original: sin la
traza completa no permite reconstruir las versiones, requests, respuestas ni decisiones de
invalidación de aquella sesión.

## 4. Auditoría del ciclo

### 4.1 Sincronización y versiones

`initialize` anuncia full document sync (`textDocumentSync.change = 1`). `didOpen` crea un overlay
con el texto y versión del cliente. `didChange` acepta exactamente un reemplazo completo, llama a
`EditorWorkspace::change`, incrementa el `DocumentVersion` interno y conserva la versión del
cliente. Las versiones regresivas se rechazan; versiones iguales no retroceden el estado.

Cada cambio aceptado llama a `schedule_all`, que agenda diagnósticos sobre
`AnalysisTarget::Document`. Las requests de símbolos capturan un snapshot nuevo mediante
`AnalysisTarget::Path`; resuelven el `DocumentId` del overlay solicitado y sólo publican si el
snapshot sigue siendo corriente.

### 4.2 Scheduler, snapshots y publicación

`AnalysisScheduler` es serial, asigna `RequestId` monotónico, elimina trabajo obsoleto del mismo
target y cancela el request en ejecución del mismo target. Antes de publicar, consulta
`may_publish_analysis`; los resultados stale, documentos cerrados, fuentes externas cambiadas o
cancelaciones no alcanzan un resultado de símbolos.

`RequestCompletion::document_symbols` exige simultáneamente:

- terminal `Published`;
- análisis `Complete + Valid`;
- snapshot semántico con el mismo `SnapshotStamp`;
- `SourceId` editable y perteneciente a ese snapshot.

No existe fallback a símbolos históricos. Un documento válido sin declaraciones produce
`Available([])`; un documento inválido produce `Unavailable`, nunca un éxito vacío.

### 4.3 JSON-RPC y cancelación

El servidor conserva cada ID JSON-RPC junto con su `RequestId` y `CancellationToken`. La respuesta
se emite una sola vez si ese par continúa pendiente. Los códigos observados y auditados son:

| Condición | Código |
| --- | ---: |
| cancelación solicitada por el cliente | `RequestCancelled (-32800)` |
| snapshot stale, documento cerrado o fuente cambiada | `ContentModified (-32801)` |
| análisis corriente incompleto o inválido | `RequestFailed (-32803)` |
| fallo interno | `InternalError (-32603)` |
| resultado válido, incluso vacío | respuesta `result` |

La especificación LSP define `RequestFailed` para una request sintácticamente válida que no puede
completarse y reserva `ServerCancelled` para requests que declaran explícitamente cancelación del
servidor. También aclara que un `null` exitoso no pide al cliente reenviar la request. Véase la
[especificación LSP 3.17](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)
y su [fuente normativa](https://github.com/microsoft/language-server-protocol/blob/gh-pages/_specifications/lsp/3.17/specification.md).

Para un parseo inválido **corriente**, `-32803` es semánticamente más honesto que `[]`: no hay un
conjunto vacío validado. Tampoco corresponde usar automáticamente `-32801`, porque el contenido no
necesariamente cambió, ni `-32802`, porque no se confirmó una cancelación iniciada por el servidor
compatible con ese contrato. No se cambió esta política.

### 4.4 Cliente VS Code y Outline

La extensión usa `vscode-languageclient` 9.0.1 y registra el provider LSP estándar; no implementa
un Outline paralelo. La librería:

- convierte una respuesta de símbolos a `DocumentSymbol[]`;
- devuelve `null` para cancelaciones iniciadas por VS Code;
- convierte ciertas cancelaciones de servidor en `CancellationError`;
- registra y propaga `RequestFailed (-32803)` como error del provider.

La API oficial `DocumentSymbolProvider` sólo expone `provideDocumentSymbols`; no ofrece un evento
`onDidChangeDocumentSymbols`, a diferencia de APIs que sí definen refresh explícito. Véase la
[referencia oficial de VS Code](https://code.visualstudio.com/api/references/vscode-api). LSP
3.17/3.18 tampoco define `workspace/documentSymbol/refresh`. Por ello no se inventó una
notificación, no se agregó polling y no se usó `vscode.executeDocumentSymbolProvider` como supuesto
refresh del Outline: ese comando consulta providers, pero no constituye un contrato de invalidación
de la UI.

## 5. Hipótesis investigadas

| Hipótesis | Evidencia | Estado |
| --- | --- | --- |
| Un parseo inválido envenena el scheduler o el overlay | inválido → válido recupera por el mismo proceso stdio | no reproducida |
| Líneas en blanco rompen versión, rangos o snapshot | respuesta válida tras edición exclusiva de líneas en blanco | no reproducida |
| Un enum válido mantiene el análisis parcial | enum y variantes aparecen jerárquicamente | no reproducida |
| Varias ediciones rápidas dejan la revisión anterior activa | versiones 5, 6 y 7 enviadas sin esperas; request final devuelve versión lógica final | no reproducida |
| Cancelar una request anterior cancela también la nueva | request vieja `-32800`; sucesora devuelve `Color` y `main` | no reproducida |
| El servidor devuelve símbolos históricos o `[]` ante parseo inválido | tests y gates fail-closed devuelven `-32803` | descartada |
| VS Code no vuelve a consultar después del error | la evidencia manual no registra el tráfico posterior a la edición final | abierta |
| La request final llegó antes del último `didChange` o con otro texto | no hay traza de versiones/payloads de la sesión manual | abierta |
| La UI descartó una respuesta válida posterior | no hay captura del Extension Host/Outline | abierta |

## 6. Reproducción determinista agregada

`compiler-next/crates/aether-lsp/tests/protocol.rs` ahora ejecuta dos casos nuevos sobre el binario
real, con framing LSP por stdio y sin sleeps:

### `document_symbols_recover_after_invalid_blank_line_enum_and_rapid_edits`

1. abre un documento válido en versión 1;
2. consulta y verifica `NewtonResultado`, tres campos y `main`;
3. cambia a sintaxis inválida en versión 2 y verifica `-32803`;
4. vuelve a código válido con sólo líneas en blanco adicionales en versión 3;
5. agrega `Color` válido en versión 4 y verifica tres variantes;
6. envía versiones 5 inválida, 6 válida y 7 válida sin esperar análisis intermedio;
7. consulta y verifica que la versión lógica final contiene `NewtonResultado`, `Color` y `main`.

### `cancelling_an_older_document_symbol_request_does_not_cancel_its_successor`

1. inicia una request costosa;
2. envía `$/cancelRequest` para su ID;
3. envía un `didChange` válido y una nueva request sin esperar la respuesta anterior;
4. verifica `-32800` para la vieja y símbolos válidos para la nueva.

Los tests preexistentes siguen cubriendo jerarquía, rangos UTF-16, overlay/disco, clases,
interfaces, stale por edición, cierre, shutdown y proyecto no disponible.

Los tests demuestran que **si el cliente envía una request nueva después de la edición válida, el
servidor la responde correctamente**. No demuestran que VS Code haya enviado esa request en la
sesión manual; ese es un hecho del cliente que sólo puede decidir una traza real.

## 7. Correcciones realizadas

No se modificó código productivo. No se confirmó un defecto que autorizara cambiar lifecycle,
cancelación, frontend, semántica, respuesta de errores o integración VS Code.

Se corrigió únicamente el déficit comprobado de qualification: faltaban regresiones stdio para
inválido → válido sin restart, líneas en blanco, enum, ráfagas y cancelación con sucesor.

La instrumentación temporal usada para la última observación se retiró antes de consolidar: se
eliminaron exclusivamente la importación de `Trace` y `await client.setTrace(Trace.Verbose)` de
`vscode-extension/src/lsp.ts`. No se cambiaron defaults, configuración personal ni soporte LSP de
producción. El VSIX instalado localmente puede seguir conteniendo ese tracing hasta que sea
reconstruido y reinstalado; no se eliminó ni modificó manualmente la extensión instalada.

## 8. Procedimiento para capturar una sesión real

1. En settings JSON temporales, configurar
   `"aetherLanguageServer.trace.server": "verbose"`. Éste es el ID actual del `LanguageClient`.
2. Abrir el canal de salida del Aether Language Server y empezar con el documento válido.
3. Reproducir inválido → válido, anotando cuál es la última versión visible del documento.
4. Conservar, para el URI afectado, cada `textDocument/didChange` con su `version`, cada
   `textDocument/documentSymbol` con su ID, cada `$/cancelRequest` y cada respuesta.
5. Comprobar primero si existe una request cuyo envío sea posterior al `didChange` final válido.
6. Si no existe, el problema queda en la invalidación/reconsulta del cliente o VS Code.
7. Si existe, comparar el payload del último `didChange` con el buffer visible y clasificar la
   respuesta: éxito, stale/cancelada o `-32803`.
8. Sólo si una request posterior al texto válido vuelve a producir `-32803`, agregar temporalmente
   a stderr del servidor `URI`, versión cliente, `DocumentVersion`, `SnapshotStamp`, `RequestId`,
   estado y código; retirar esa instrumentación después de la captura.

La traza verbose puede contener texto fuente y rutas locales; debe compartirse recortada al único
documento afectado y eliminarse al terminar.

## 9. Qualification

Reejecutada sobre el árbol final del cierre:

| Comando | Resultado |
| --- | --- |
| `cargo test -p aether-analysis` | PASS, 49/49 |
| `cargo test -p aether-lsp` | PASS, 4 unitarios + 10 stdio |
| `npm test` en `vscode-extension` | PASS, 4/4 |
| `npm run compile` en `vscode-extension` | PASS |
| `cargo check --workspace` | PASS |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS con warnings preexistentes fuera de este cambio |
| `bash tests/test-differential-harness.sh` desde `compiler-next` | PASS |
| `bash tests/run-differential.sh` desde `compiler-next` | PASS, `mode=official checked=96 failures=0` |
| `git diff --check` | PASS |

El primer intento de invocar el harness como `tests/test-differential-harness.sh` desde la raíz del
repositorio falló porque esa ruta no existe allí; se corrigió el directorio de trabajo a
`compiler-next` y el gate real pasó.

Se conserva como qualification histórica del reporte de investigación, sin reejecutarla en este
cierre:

| Comando | Resultado histórico |
| --- | --- |
| `aether check examples/ProbandoNR/probandoNR2.ae` | PASS |
| `aether run examples/ProbandoNR/probandoNR2.ae` | PASS; raíz `0.567143290409784`, residual `2.220446049250313e-16`, 5 iteraciones |
| `cargo test --workspace -j 1` | PASS completo; test OAL final 715,27 s |

No se repitió el workspace completo porque el cierre no contiene cambios productivos Rust y el PASS
completo ya estaba registrado. Los crates afectados, los tests stdio, la extensión, `cargo check`,
formato, Clippy y ambos diferenciales sí se reejecutaron.

## 10. Limitaciones

- No se automatizó VS Code/Electron ni se inspeccionó estado interno de Outline.
- No se dispone de la traza completa de la sesión manual original.
- La reproducción stdio controla explícitamente cuándo consulta símbolos; por diseño no prueba la
  decisión autónoma de VS Code de reconsultar.
- `Developer: Reload Window` prueba que una sesión nueva puede reconstruir la jerarquía, pero no
  identifica qué estado de la sesión anterior quedó atascado.
- No se inició ningún servicio LSP ajeno; sólo procesos `aether-lsp --stdio` efímeros creados por
  los tests solicitados.

## 11. Archivos modificados

- `compiler-next/crates/aether-lsp/tests/protocol.rs`: dos regresiones stdio nuevas.
- `docs/architecture/LSP_DOCUMENT_SYMBOLS_REFRESH_INVESTIGATION_V1_REPORT.md`: este informe.
- `examples/ProbandoNR/probandoNR2.ae`: cambio personal preexistente, preservado sin edición por
  esta investigación.
- `examples/ProbandoNR/probandoNR4.ae`: cambio personal preexistente, preservado sin edición por
  esta investigación.

## 12. Consolidación Git

```text
test(lsp): qualify document symbol recovery after transient parse failures
```

El commit de cierre incluye exclusivamente:

- `compiler-next/crates/aether-lsp/tests/protocol.rs`;
- `docs/architecture/LSP_DOCUMENT_SYMBOLS_REFRESH_INVESTIGATION_V1_REPORT.md`.

`vscode-extension/src/lsp.ts` volvió a su contenido funcional anterior y por ello no forma parte del
commit. Tampoco forman parte los cambios personales ni los artefactos ignorados. No se hizo push.
El estado final esperado conserva únicamente como modificaciones visibles los dos archivos
personales de `examples/ProbandoNR`, además de todos los archivos ignorados ya enumerados; el cierre
queda un commit adicional por delante de `origin/main`.
