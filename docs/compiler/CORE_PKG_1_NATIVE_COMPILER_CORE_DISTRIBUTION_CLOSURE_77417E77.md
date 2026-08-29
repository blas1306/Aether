# CORE-PKG-1 — cierre formal de distribución nativa

Fecha: 2026-08-28

## Decisión

`CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED`

El cierre consume exclusivamente metadata, jobs, logs y los 14 artifacts
oficiales del GitHub Actions run `33216160463`. GitHub fija ese run al workflow
`core-native-packaging`, evento `workflow_dispatch`, rama `main`, revisión exacta
`77417e7751482fc5a88a7d4207e99d67692da043` y conclusión `success`.

El resultado califica la distribución conjunta de binding y companion para la
matriz probada. No promueve el transporte in-process, no hace de PyO3 el default,
no autoriza retirar el companion y no extrapola corrección fuera de esas
plataformas o versiones de CPython.

## Jobs obligatorios

Los 14 jobs reales terminaron `completed/success`; no se aceptó ningún job
missing, skipped, neutral, cancelled ni con otra revisión.

| Job | ID | Resultado |
|---|---:|---|
| package-contract | 99000115209 | success |
| companion-installed-rollback | 99000114903 | success |
| source-development-install | 99000115138 | success |
| failure-campaign | 99000115208 | success |
| binding-installed-smoke | 99000115397 | success |
| aggregate-fail-closed | 99001462219 | success |
| clean-install-platform (linux-x86_64, ubuntu-latest) | 99000115347 | success |
| clean-install-platform (windows-x86_64, windows-latest) | 99000115116 | success |
| clean-install-platform (macos-x86_64, macos-15-intel) | 99000115159 | success |
| clean-install-platform (macos-arm64, macos-15) | 99000115358 | success |
| python-compatibility (3.11) | 99000115194 | success |
| python-compatibility (3.12) | 99000115225 | success |
| python-compatibility (3.13) | 99000115384 | success |
| python-compatibility (3.14) | 99000115341 | success |

## Integridad de artifacts

GitHub publicó exactamente 14 artifacts. Cada ZIP fue descargado por artifact
ID a un directorio temporal separado. Los 14 SHA-256 calculados coinciden con
los 14 digests `sha256:` publicados por GitHub. Se extrajeron 16 archivos JSON;
todos fueron parseados y hasheados. El manifest completo, incluidos tamaños de
archive, filenames y SHA-256 de cada archivo extraído, está en el JSON
machine-readable del cierre.

| Artifact | ID | Bytes | Job fuente | Digest del ZIP |
|---|---:|---:|---|---|
| core-pkg-1-aggregate | 9703572314 | 1234 | aggregate-fail-closed | `a92971fc…d12c6` |
| core-pkg-1-platform-macos-x86_64 | 9703566500 | 1569 | clean-install macOS x86_64 | `0f513c11…0143d` |
| core-pkg-1-contract | 9703547555 | 220 | package-contract | `df70a059…fbfb97` |
| core-pkg-1-platform-windows-x86_64 | 9703523966 | 1587 | clean-install Windows x86_64 | `23c8bb54…0f042` |
| core-pkg-1-platform-macos-arm64 | 9703484287 | 1567 | clean-install macOS arm64 | `49e4aa9f…84270` |
| core-pkg-1-python-3.14 | 9703471366 | 1487 | python-compatibility 3.14 | `92610936…70014` |
| core-pkg-1-python-3.13 | 9703470254 | 1490 | python-compatibility 3.13 | `af7e929e…b8c6e` |
| core-pkg-1-binding | 9703468423 | 2741 | binding-installed-smoke | `160e9447…e38ad` |
| core-pkg-1-python-3.11 | 9703467588 | 1489 | python-compatibility 3.11 | `be4494f2…0385e` |
| core-pkg-1-python-3.12 | 9703465913 | 1488 | python-compatibility 3.12 | `56fa5890…81063` |
| core-pkg-1-source | 9703458937 | 223 | source-development-install | `55f743fd…fbeb3` |
| core-pkg-1-companion | 9703458761 | 227 | companion-installed-rollback | `1169c900…3c767` |
| core-pkg-1-platform-linux-x86_64 | 9703456798 | 1499 | clean-install Linux x86_64 | `5c246fbf…2fb8f` |
| core-pkg-1-failures | 9703424671 | 226 | failure-campaign | `7e4020f4…1ffd8e` |

Los artifacts `contract`, `companion`, `source` y `failures` son marcadores
machine-readable `PASS`; no se les atribuyen campos que no contienen. Sus
detalles se trazan a los jobs/logs oficiales y, para el protocolo y rollback del
companion, a los cuatro artifacts detallados de clean consumer.

## Aggregate oficial y reproducción

El artifact `core-pkg-1-aggregate` declara
`CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED`, revisión
`77417e7751482fc5a88a7d4207e99d67692da043`, run `33216160463` y `errors=[]`.

Se ejecutó el checker real
`scripts/check_core_pkg_1_native_distribution.py` sobre los 13 artifacts de
entrada descargados. El resultado volvió a ser `QUALIFIED`. Al recomponer el
layout `merge-multiple` usado por Actions, el aggregate recomputado resultó
byte-identical al oficial. Ambos tienen SHA-256
`d59339b4705091df3ffbce72fc2c99b390a44433d449525ed7bb0fb0ef07a0f6`.

## Contrato de packages e identidad de CompilerCore

Los artifacts de wheels prueban el contrato exacto:

`aether-language==1.0.0rc4` requiere
`aether-compiler-core==1.0.0rc4`.

La distribución nativa contiene el wrapper estable `aether_compiler_core`, el
binding PyO3, `aether-ssa-shadow[.exe]` y `native-core-manifest.json`. El job de
contract ejecutó 19 tests (19 passed). `aether-core-qualification==0.1.0`
permanece separado y qualification-only; no se convirtió evidencia histórica de
CORE-1.0A en un producto nuevo.

Binding, manifest nativo y companion reportan package `1.0.0rc4`, producto
nativo `0.1.0`, CompilerCore API `1`, protocolo `1`, input schema `[1]`, output
schema `[2]` y build identity
`77417e7751482fc5a88a7d4207e99d67692da043`. Además producen la misma salida
ordinaria en los probes. Esa es la identidad demostrada; no se afirma una
equivalencia semántica universal no cubierta por los artifacts.

## Clean consumers por plataforma

| Plataforma | Python | Native wheel/tag | Instalación, import, wrapper y rollback |
|---|---|---|---|
| Linux x86_64 | 3.13.15 | `aether_compiler_core-1.0.0rc4-cp313-cp313-linux_x86_64.whl` | PASS |
| Windows x86_64 | 3.13.15 | `aether_compiler_core-1.0.0rc4-cp313-cp313-win_amd64.whl` | PASS |
| macOS x86_64 | 3.13.15 | `aether_compiler_core-1.0.0rc4-cp313-cp313-macosx_10_12_x86_64.whl` | PASS |
| macOS arm64 | 3.13.14 | `aether_compiler_core-1.0.0rc4-cp313-cp313-macosx_11_0_arm64.whl` | PASS |

En los cuatro casos pip resolvió el native package desde el wheel de language.
Pasaron `_aether_core`, el wrapper estable, creación y uso de `CompilerCore`,
descubrimiento del companion instalado, metadata/version identity, operación
ordinaria, error protocol-v1, recovery, reuse persistente (un proceso, tres
requests) y shutdown. El transporte productivo siguió siendo
`ProductionRustSSALoweringClient` y la respuesta coincidió.

Los consumers ejecutaron sin Cargo ni rustc en PATH. El cwd temporal no hizo
importable el repositorio y los módulos importados no provinieron del checkout.
El Rust toolchain sólo fue necesario en el entorno de build del wheel.

## Compatibilidad CPython en Linux x86_64

| Minor | Patch exacto | Native wheel | Resultado |
|---|---|---|---|
| 3.11 | 3.11.16 | `aether_compiler_core-1.0.0rc4-cp311-cp311-linux_x86_64.whl` | PASS |
| 3.12 | 3.12.14 | `aether_compiler_core-1.0.0rc4-cp312-cp312-linux_x86_64.whl` | PASS |
| 3.13 | 3.13.15 | `aether_compiler_core-1.0.0rc4-cp313-cp313-linux_x86_64.whl` | PASS |
| 3.14 | 3.14.7 | `aether_compiler_core-1.0.0rc4-cp314-cp314-linux_x86_64.whl` | PASS |

Cada lane pasó instalación, import, wrapper, companion, smoke, recovery y
version contract sin Rust/Cargo para el consumer. No se extrapola fuera de
CPython 3.11–3.14 ni se combinan estas lanes Linux con otras plataformas.

## Binding, companion y desarrollo

El binding instalado importó por `_aether_core` y
`aether_compiler_core._aether_core`, declaró `QUALIFICATION_ONLY=false`, creó
`CompilerCore` y reportó protocolo 1. La lane CORE-1.0A productiva pasó, su
checker devolvió `CORE_IN_PROCESS_PRODUCTION_GUARD_QUALIFIED`, y la proyección
registró nueve regression gates y cuatro shared-core guards. La evidencia
upstream sigue marcada `CORE-1.0A` y `qualification_only=true`.

Los steps `Replay CORE-1.0A regression lanes without promoting in-process`,
`Validate exact CORE-1.0A production evidence` y
`Project checked production guard into CORE-PKG-1 evidence` se ejecutaron y
terminaron individualmente en `success`; no se infieren sólo del color del job.

El job dedicado de companion, en Ubuntu con CPython 3.13.15, instaló el wheel
nativo, descubrió el binario por `aether_compiler_core.companion_path`, comprobó
su existencia y verificó que arrancar sin una request válida falla. El protocolo,
rollback/recovery, reuse y shutdown completos están probados adicionalmente por
los cuatro clean consumers.

El job de desarrollo probó exactamente Ubuntu, CPython 3.13.15 y Rust 1.85:
instalación nativa desde
`compiler-rs/distributions/aether-compiler-core`, instalación editable de
`aether-language` con `--no-deps`, import del binding y descubrimiento del
companion instalado. No se califican otros workflows de desarrollo.

## Alcance CLI e IDE

CORE-PKG-1 no ejecutó el entry point CLI end-to-end como lane independiente.
Los clean consumers sí importaron `aether` desde el wheel instalado y
ejercitaron `ProductionRustSSALoweringClient`, comprobando que el transporte
productivo resolvía y usaba el companion del mismo entorno. Ése es el alcance
CLI demostrado: instalación y camino productivo subyacente, no una
calificación de comandos de usuario.

VS Code e IntelliJ fueron auditados, no ejecutados en la matriz cross-platform.
Ambos delegan en los entry points `aether`/`aether-lsp` del ejecutable
configurado, `.venv` de proyecto o PATH; ninguno descubre directamente el
binding o el companion ni selecciona el transporte. La auditoría concluyó que
no hacía falta cambiar los plugins o sus launch schemas, pero este cierre no
afirma una calificación de ejecución de los IDEs.

## Failure campaign

El job oficial terminó `13 passed, 14 deselected`. Cubre ausencia del package
nativo, mismatch de versión nativa y de language/native, manifest ausente,
malformado o incompatible, shadowing del checkout, binding ausente o shadow,
checksum RECORD incorrecto, companion ausente, companion no ejecutable en
POSIX, cero o múltiples wheels candidatas y wheel incompatible con CPython.
No se inventan casos fuera de ese selector.

## Arquitectura productiva y blocker de CORE-1.0B

El transporte productivo sigue siendo el companion. PyO3 está disponible en la
distribución productiva, pero disponibilidad no equivale a selección default.
No apareció fallback automático y el companion sigue siendo producción y
rollback. Los regression/shared-core guards preservan protocol-v1, authority,
lifecycle, refinement, schemas y semántica de CompilerCore.

CORE-PKG-1 nació porque `_aether_core` no formaba parte de instalaciones
normales de `aether-language`. Los clean consumers prueban que el dependency
contract instala ahora binding y companion juntos. Por tanto, el blocker de
distribución que detuvo CORE-1.0B queda resuelto para la matriz calificada.

CORE-1.0B remains unpromoted. CORE-1.1 was not implemented.

## Historia preservada

El primer run `33188797944`, revisión
`b219d60d1afe38bea560495536401e9997a4ea5a`, permanece `FAILED` y su aggregate
permanece `CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED`. El job
`binding-installed-smoke` falló la reproducción productiva CORE-1.0A; por ello
no se publicó `core_pkg_1_binding_smoke`, y `aggregate-fail-closed` bloqueó por
esa ausencia. El run exitoso es evidencia posterior e independiente; no
sobrescribe ni reinterpreta el histórico.

## Límites y cambios

GitHub emitió en los 14 jobs el warning de que `actions/checkout@v4`,
`actions/setup-python@v5`, `actions/download-artifact@v4` y
`actions/upload-artifact@v4` todavía targetean Node.js 20 y fueron forzadas a
ejecutarse bajo Node.js 24. Se clasifica como **CI maintenance warning**, no
como fallo CORE-PKG-1: los jobs y gates siguieron en `success` y no hay evidencia
contraria en el run.

No hay caracterización de performance en estos artifacts y performance no es un
gate. Este cierre crea sólo documento, manifest, checker y tests separados. No
modifica packaging productivo, workflow, CompilerCore, SSA, refinement,
lifecycle, authority ni schemas. No crea commit.

El checker fail-closed
`scripts/check_core_pkg_1_native_distribution_closure_77417e77.py` fija run,
revisión, jobs, artifact IDs/digests/hashes, aggregate, contrato, identidad,
matrices, smoke/rollback/source/failures y el guard companion-default. También
puede recibir los directorios de ZIPs y evidencia oficial para reverificar los
payloads descargados y la reproducción byte-identical. El snapshot de fuentes
se verifica contra la revisión histórica exacta, no contra un worktree posterior.
