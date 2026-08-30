# CORE-1.0B — cierre formal del transporte productivo in-process

Fecha: 2026-08-30

## Decisión

`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTED`

El cierre consume exclusivamente el run oficial nuevo `33293548667`, lanzado
por `workflow_dispatch` sobre `main` y fijado a la revisión exacta
`a9d0df6eeec081cc8baf881450e5e3a30db9d020`. El workflow
`core-in-process-production-transport-promotion` terminó `completed/success`.
El run anterior `33293069494` y los históricos `33264243543` y `33265815894`
permanecen `FAILED/BLOCKED`; ninguno se reutiliza como evidencia positiva.

La promoción hace `in_process` el transporte productivo por defecto. El
companion instalado continúa disponible como rollback explícito mediante
`AETHER_RUST_CORE_TRANSPORT=companion`; no existe fallback automático y
protocol-v1 permanece soportado.

## Jobs obligatorios

Los 20 jobs reales terminaron `completed/success` sobre el mismo head SHA. No
se aceptó ningún job missing, skipped, cancelled, neutral ni con otra revisión.

| Job | ID |
|---|---:|
| affected-rust-4-5 | 99209237775 |
| differential-both-transports | 99209237798 |
| production-default-in-process | 99209237814 |
| sessions-concurrency | 99209237824 |
| blocker-resolution | 99209237827 |
| no-fallback | 99209237836 |
| explicit-companion-rollback | 99209237853 |
| python-compatibility (3.13) | 99209237860 |
| transport-parity | 99209237871 |
| source-development-install | 99209237875 |
| clean-install-platform (macos-arm64, macos-15) | 99209237878 |
| clean-install-platform (macos-x86_64, macos-15-intel) | 99209237880 |
| packaged-clean-consumer | 99209237896 |
| python-compatibility (3.11) | 99209237943 |
| python-compatibility (3.14) | 99209237946 |
| clean-install-platform (windows-x86_64, windows-latest) | 99209237954 |
| clean-install-platform (linux-x86_64, ubuntu-latest) | 99209237970 |
| python-compatibility (3.12) | 99209237992 |
| production-pipeline | 99209493921 |
| aggregate-fail-closed | 99209748688 |

## Artifacts e integridad

GitHub publicó 13 artifacts. Cada ZIP se descargó por artifact ID a un
directorio temporal separado. Los 13 SHA-256 descargados coinciden con los
digests `sha256:` de GitHub; se extrajeron y hashearon 31 JSON. El manifest
machine-readable conserva artifact ID, nombre, tamaño, job fuente, job ID,
digest del ZIP y hash de cada record extraído.

| Artifact | ID | Bytes | Digest ZIP |
|---|---:|---:|---|
| core-1-0b-aggregate | 9726749933 | 822 | `0de046fd…87c0` |
| core-1-0b-platform-macos-x86_64 | 9726742173 | 4812 | `50ef5ac1…dfc0` |
| core-1-0b-platform-windows-x86_64 | 9726741419 | 4825 | `a43a422f…c9e72` |
| core-1-0b-functional | 9726722333 | 4318 | `8d10012e…521ab` |
| core-1-0b-python-3.14 | 9726720570 | 4747 | `56736d6e…51cfd` |
| core-1-0b-platform-linux-x86_64 | 9726720304 | 4748 | `477c2378…6dc09` |
| core-1-0b-python-3.13 | 9726720110 | 4744 | `53066d20…bf9c3` |
| core-1-0b-development-install | 9726719670 | 3026 | `e431dc49…6b702` |
| core-1-0b-python-3.11 | 9726719635 | 4735 | `7c9f8678…de705` |
| core-1-0b-packaged-consumer | 9726717779 | 3946 | `e0e02fb6…4ed9b` |
| core-1-0b-python-3.12 | 9726716078 | 4737 | `7f8e23f3…632a1` |
| core-1-0b-platform-macos-arm64 | 9726714595 | 4791 | `557e1cc1…1abcc` |
| core-1-0b-blocker-resolution | 9726696549 | 698 | `1363606b…eb0ed` |

## CORE-PKG-1 y aggregate

`blocker-resolution` recomputó el cierre exacto de CORE-PKG-1:
`CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED`, run `33216160463`, revisión
`77417e7751482fc5a88a7d4207e99d67692da043`. Se preserva el contrato
`aether-language==1.0.0rc4` → `aether-compiler-core==1.0.0rc4`, wrapper estable,
binding PyO3 productivo, companion instalado, manifest versionado y
`QUALIFICATION_ONLY == false`.

El artifact oficial `core-1-0b-aggregate` declara exactamente
`CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTED`, `errors=[]`, las cuatro
plataformas, CPython 3.11–3.14 y todos los prerequisites obligatorios en `true`.
El checker real se volvió a ejecutar sobre los 12 artifacts de entrada
descargados. La recomposición volvió a declarar `PROMOTED` y resultó idéntica en
bytes al aggregate oficial. Ambos tienen SHA-256
`4a0f7ab6ea6967fa0d5190f9a0f75f47e23b4170b45d944e550c360c7cb6baaa`.

## Default, rollback y no-fallback

Sin `AETHER_RUST_CORE_TRANSPORT`, requested/observed fueron
`in_process/in_process`; el selector explícito `in_process` produjo el mismo
resultado. Con `AETHER_RUST_CORE_TRANSPORT=companion`, requested/observed fueron
`companion/companion`. El rollback descubrió y arrancó el companion desde
`aether_compiler_core` instalado, utilizó protocol-v1, reutilizó el proceso,
manejó failure/recovery y no ejecutó el binding PyO3 por debajo.

Las pruebas dedicadas confirman que fallar in-process no intenta companion,
fallar companion no intenta in-process, un transport mismatch falla antes de
ejecutar una request y una selección inválida falla cerrada.

## Packaged clean consumer

El artifact dedicado del job `packaged-clean-consumer` contiene exactamente:

- `core-1.0b-packaged-install.json`, kind
  `core_1_0b_clean_consumer_install`;
- `core-1.0b-packaged-default.json` y
  `core-1.0b-packaged-companion.json`, kind
  `core_1_0b_packaged_clean_consumer`, role `packaged_clean_consumer`.

Los records de matrices usan el kind redundante
`core_1_0b_packaged_consumer` y no pueden sustituir estos records dedicados.
El install manifest registra los wheels exactos y sus hashes:

- `aether-language==1.0.0rc4`:
  `1207a8cee7b125bf7fdbc0ce987b3a4ec2eb7f898c1104e41dd837e38a0b4ff2`;
- `aether-compiler-core==1.0.0rc4`:
  `928657961c9228785aa0bbab37818b8f3897d8ef144a3813b769189accad2ae7`.

Las dependencias runtime se derivaron de METADATA y se instalaron primero:
`matplotlib==3.10.8`, `numpy==2.4.2`, `scipy==1.17.1` y `sympy==1.14.0`.
Los Aether wheels se instalaron luego con `--no-deps`, sin permitir resolver
otro Aether desde índice; `pip check` pasó.

El consumer ejecutó fuera del checkout, sin checkout importable y sin
Cargo/rustc en PATH. In-process no arrancó companion; companion arrancó una vez
y no llamó PyO3. Cada lane hizo tres requests: compilación representativa,
failure manejado y recovery con el mismo cliente. Ambos transportes produjeron
dos funciones y el mismo output SHA-256
`2522a8877eaac3b97be8dc43413396514a8a5ac5ae0637da4da5c770b7bcf5b2`.

## Funcional, sesiones y failures

La lane funcional ejecutó 116/116 casos históricos y 116/116 pipelines `.ae`
por ambos transportes. Pasaron CFG de profundidades 993, 1000, 5000 y 10000;
differential match; divergence/corruption fail-closed; authority modes
existentes; los gates Rust afectados; y el job separado production-pipeline.

Se reutilizó un CompilerCore in-process y se ejecutaron 32 requests
concurrentes con sesiones Rust-owned independientes, accounting y aislamiento
de error sin observar cross-session state leak. Esta afirmación queda limitada
al workload probado.

La campaña estructurada usó los mismos seis inputs en ambos transportes:
malformed JSON, non-object, schema no soportado, campo root desconocido, target
CFG inválido y función duplicada. Comparó accept/reject, categoría, phase y
source location. No se eleva igualdad textual a requisito universal.

## Plataformas, Python y desarrollo

| Plataforma | Patch Python | Default | Rollback |
|---|---|---|---|
| Linux x86_64 | 3.13.15 | in_process | companion |
| Windows x86_64 | 3.13.15 | in_process | companion |
| macOS x86_64 | 3.13.15 | in_process | companion |
| macOS arm64 | 3.13.14 | in_process | companion |

| CPython Linux x86_64 | Patch | Resultado |
|---|---|---|
| 3.11 | 3.11.16 | PASS |
| 3.12 | 3.12.14 | PASS |
| 3.13 | 3.13.15 | PASS |
| 3.14 | 3.14.7 | PASS |

Cada matrix lane instaló wheels productivos, ejecutó fuera del checkout sin
toolchain de consumer, observó default y rollback, comprobó proveniencia,
operación representativa y build identity. No se extrapola a otras plataformas,
PyPy ni otras versiones de Python.

La lane de desarrollo probó checkout fuente, build/install nativo, instalación
editable de language, discovery de binding y companion, default in-process y
rollback companion. No califica cualquier entorno de desarrollo imaginable.

## Performance

Performance fue caracterizada con cinco muestras warm para `ordinary`,
`deep_cfg_1000`, `historical_116` y `real_ae_expense_tracker`, separando
conversion, Rust core, IPC/protocol y result conversion. En la operación
ordinary las medianas fueron 0.000971748 s in-process y 0.001100808 s companion.
Estos números no son un gate de corrección ni sostienen superioridad universal.

## Historia preservada

- `33264243543`: FAILED/BLOCKED, sin promoción retrospectiva.
- `33265815894`: FAILED/BLOCKED; `packaged-clean-consumer` y
  `aggregate-fail-closed` fallaron. El aggregate que decía `PROMOTED` era
  internamente inconsistente e inválido para closure.
- `33293069494`: FAILED/BLOCKED. Todos los gates productivos pasaron, pero el
  aggregate bloqueó porque el harness creó `core-1-0b-packaged-install.json` y
  exigió/subió `core-1.0b-packaged-install.json`. El defecto se corrigió en el
  commit estrictamente necesario `a9d0df6`; ese run no se reinterpreta.

## Alcance y límites

Este cierre no modifica CompilerCore, SSA/refinement/lifecycle, authority modes,
schemas ni protocol-v1. No elimina companion, no introduce fallback automático
y no autoriza CORE-1.1. Tampoco afirma soporte universal de plataforma/Python,
corrección semántica universal, thread-safety universal ni superioridad de
performance universal.

El único cambio posterior al run fallido fue la corrección del nombre del
manifest en el harness y su test de regresión; no cambió semántica productiva.
El cierre agrega sólo documento, manifest, checker y pruebas, sin crear otro
commit.
