# CORE-1.0A — cierre formal del boundary in-process

Fecha: 2026-08-28

## Decisión

`CORE_IN_PROCESS_BOUNDARY_QUALIFIED`

El cierre usa exclusivamente metadata y artifacts oficiales descargados con
`gh` del run `33144738758`, workflow
`core-1.0a-in-process-qualification`, sobre la revisión exacta
`6f6851dfd353bb716eeffc05a701b6bc4dab5132`. El run terminó `success`; los 12
jobs obligatorios terminaron `success`, sin aceptar estados skipped, cancelled
o neutral.

Esta decisión califica operacionalmente el boundary in-process contra el
companion persistente y el corpus probado. No es una promoción productiva, una
afirmación de corrección universal ni autorización para consolidar semántica.

## Gates del run

| Job | ID | Conclusión |
|---|---:|---|
| semantic-historical-failures-deep | 98763185488 | success |
| rust-owned-sessions-gil-memory | 98763185574 | success |
| affected-rust-4.5-production-gates | 98763185664 | success |
| clean-install-linux-x86_64 | 98763185667 | success |
| clean-install-windows-x86_64 | 98763185605 | success |
| clean-install-macos-x86_64 | 98763185642 | success |
| clean-install-macos-arm64 | 98763185660 | success |
| cpython-3.11-linux-x86_64 | 98763185661 | success |
| cpython-3.12-linux-x86_64 | 98763185662 | success |
| cpython-3.13-linux-x86_64 | 98763185693 | success |
| cpython-3.14-linux-x86_64 | 98763185624 | success |
| aggregate-fail-closed-decision | 98763793041 | success |

GitHub publicó exactamente 12 artifacts. Para cada uno se registraron ID,
nombre, job fuente, digest SHA-256 de GitHub, SHA-256 del ZIP oficial descargado,
archivo extraído y SHA-256 del archivo. Los 12 digests de los ZIP descargados
coinciden con GitHub. Los 12 archivos machine-readable declaran la revisión
esperada cuando su contrato contiene revisión; las 11 evidencias de entrada
declaran además `worktree_clean=true`.

El aggregate oficial, artifact `9675384624`, declara
`CORE_IN_PROCESS_BOUNDARY_QUALIFIED` sin errores. El checker existente
`scripts/check_core_1_0a_in_process.py`, ejecutado sobre los 11 inputs oficiales,
recompuso el mismo archivo byte por byte. El SHA-256 del aggregate es
`8e70eb181f9b5adc4749cb1fd2baf68ad21a386f7ff5956762bb0a6fc868bf8f`.

## Calificación semántica

- Histórico companion: 116/116; histórico in-process: 116/116; equivalencia de
  transporte, semántica y diagnóstico/downstream: 116/116.
- Casos ordinarios: 5/5.
- Initial IR y binding failures: 8/8. Cubre documento/JSON malformado, schema,
  CFG, duplicación de función, return/value flow y lifecycle; la paridad de
  diagnóstico y source location se conserva donde corresponde.
- Mutaciones SSA/refinement RUST-4.x: 13/13. Cubre phi inválido, refinement e
  imported SSA malformado, sin divergencias ocultas.
- Deep CFG: 993, 1000, 5000 y 10000, todos PASS con paridad companion/in-process.

No se reconstruyó evidencia faltante por inferencia: estos valores se leyeron
del artifact oficial `core-1.0a-semantic` y fueron revalidados por el checker.

## Sesiones, GIL y memoria

Todos los gates de creación, uso repetido, interleaving, aislamiento, fallo
seguido de reuse, fallos concurrentes, cleanup, ausencia de handles stale y
serialización same-session pasaron. La misma sesión se serializa mediante
`Mutex<CompilationSession>`; sesiones independientes conservan su contrato.

Durante Rust, el ticker Python avanzó 4.008.208 iteraciones. El soak realizó 500
sesiones; RSS creció 0 bytes, el crecimiento Python trazado fue 32 bytes y el
artifact declara `unbounded_growth_observed=false`. El gate aprobado usa este
criterio de crecimiento acotado; no exige literalmente memoria igual a cero.
`CompilerCore` y `CompilationSession` conservan `Send + Sync`, y no se declara
`unsafe`.

## Regresión productiva RUST-4.5

La lane oficial ejecutó 51 tests afectados (51 passed, 34 deselected) y pasó
protocol-v1, companion persistente, lifecycle, output Rust SSA,
verification/refinement, diagnóstico estructurado, modo diferencial Python
shadow, rollback y política default RUST-4.5. También pasaron los cuatro guards
que mantienen `CompilerCore` compartido sin acoplarlo a PyO3 ni introducir el
cliente in-process en el selector default.

El companion sigue siendo producción y rollback; in-process sigue siendo no-default
y `qualification_only`. No cambió la authority policy.

## Clean install por plataforma

| Plataforma | Python | Wheel | Tag | Import/probe |
|---|---|---|---|---|
| Linux x86_64 | 3.13.15 | `aether_core_qualification-0.1.0-cp313-cp313-manylinux_2_34_x86_64.whl` | `cp313-cp313-manylinux_2_34_x86_64` | PASS |
| Windows x86_64 | 3.13.15 | `aether_core_qualification-0.1.0-cp313-cp313-win_amd64.whl` | `cp313-cp313-win_amd64` | PASS |
| macOS x86_64 | 3.13.15 | `aether_core_qualification-0.1.0-cp313-cp313-macosx_10_12_x86_64.whl` | `cp313-cp313-macosx_10_12_x86_64` | PASS |
| macOS arm64 | 3.13.14 | `aether_core_qualification-0.1.0-cp313-cp313-macosx_11_0_arm64.whl` | `cp313-cp313-macosx_11_0_arm64` | PASS |

En las cuatro plataformas pasaron import, ordinary operation, structured
failure, repeated session use y disponibilidad protocol-v1 del companion. El
consumidor limpio instaló wheels preconstruidos con only-binary y sin Rust ni
Cargo disponibles en su PATH de instalación.

La afirmación de packaging queda limitada a lo demostrado: qualified wheels
can be installed and used by the tested clean consumer environments without
Rust/Cargo being available to the consumer.

## Compatibilidad Python en Linux x86_64

| Minor | Versión exacta | Wheel tag | Import/smoke/consumer |
|---|---|---|---|
| CPython 3.11 | 3.11.16 | `cp311-cp311-manylinux_2_34_x86_64` | PASS |
| CPython 3.12 | 3.12.14 | `cp312-cp312-manylinux_2_34_x86_64` | PASS |
| CPython 3.13 | 3.13.15 | `cp313-cp313-manylinux_2_34_x86_64` | PASS |
| CPython 3.14 | 3.14.7 | `cp314-cp314-manylinux_2_34_x86_64` | PASS |

No se extrapola compatibilidad a otras versiones o combinaciones de plataforma.

## Performance oficial

Dos warmups y cinco muestras por workload; las cifras son medianas. Performance
no es gate de corrección.

| Workload | Companion persistente | In-process |
|---|---:|---:|
| ordinary | 0,266 ms | 0,130 ms |
| historical batch (116) | 407,046 ms | 393,820 ms |
| deep CFG | 229,094 ms | 231,793 ms |
| repository real | 3,485 ms | 3,314 ms |

La ligera lentitud in-process del caso deep CFG no bloquea: no existe un umbral
de performance previo y el artifact marca explícitamente `correction_gate=false`.

## Evidencia histórica preservada

El run `33143156047` sobre
`2401ab8d56c13d7837aab245735105764e65ade0` permanece `FAILED` y
`CORE_IN_PROCESS_BOUNDARY_QUALIFICATION_BLOCKED`. Sus causas fueron ejecutar
`maturin develop` fuera de un virtualenv y un selector que asumía exactamente
un wheel. Este cierre no sobrescribe, elimina ni reinterpreta ese documento: el
run `33144738758` es una qualification independiente sobre otra revisión.

## Límites del cierre

`CompilerCore`, SSA, refinement y lifecycle no fueron modificados por este
cierre. CORE-1.1 no fue implementado. El binding no fue promovido a default, el
companion no fue eliminado y no se alteraron modos de rollback ni authority.
El workflow de qualification tampoco fue modificado.

El manifest machine-readable asociado contiene 12 entradas de artifacts y es
validado fail-closed por
`scripts/check_core_1_0a_in_process_closure_6f6851df.py`.
