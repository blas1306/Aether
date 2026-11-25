# Aether — COMPILER-AUTHORITY-AND-QUALIFICATION-ISOLATION-V1 — Reporte

Estado actual: **CLOSED — QUALIFICATION OFICIAL POSTERIOR EN VERDE**

Estado al finalizar la ejecución original: **IMPLEMENTADO; QUALIFICATION
OFICIAL FAIL; NO CLOSED**

Fecha: 2026-11-25

Checkout: `main` @ `35e1a8197dc7a48d6f7218b27a44f458c98c25c4`

El aislamiento pedido está implementado: el gate oficial ya no descubre ni
ejecuta componentes legacy y el diferencial histórico quedó separado como una
tarea opt-in no normativa. El milestone no se declara `CLOSED` porque el gate
ampliado encontró un fallo real preexistente de `compiler-next` en
`iteration_v3_smoke.ae`. La restricción del milestone prohíbe corregir el
backend LLVM y también prohíbe alterar la expectativa para obtener PASS.

Los apartados 1 a 12 conservan los resultados y el estado de esa ejecución
original. El apartado 13 registra el seguimiento posterior que permite cerrar
el milestone sin reescribir aquel FAIL como PASS.

## 1. Política de autoridad publicada

Se creó la fuente normativa única
[`COMPILER_AUTHORITY.md`](../architecture/COMPILER_AUTHORITY.md). Establece:

- `compiler-next` como único compilador oficial;
- la CLI Rust `aether` como interfaz pública vigente;
- prioridad de los contratos `CLOSED` actuales;
- carácter histórico y no normativo de `compiler-rs` y del compilador Python;
- ausencia de obligación de compatibilidad o paridad;
- prohibición de nuevas dependencias legacy en el pipeline y los gates
  oficiales;
- uso de implementaciones históricas sólo como referencia o evidencia;
- independencia del resultado oficial respecto de cualquier resultado legacy.

La política no autoriza retirar físicamente ninguna implementación.

## 2. Cambios documentales

- `README.md` enlaza la política desde el índice de consolidación y desde la
  presentación de la CLI oficial.
- `AETHER_COMPILER_ARCHITECTURE.md` conserva intacto su contexto de auditoría
  fechado y remite a la política actual para interpretar sus descripciones
  históricas.
- `compiler-next/README.md` documenta la qualification oficial y el modo
  histórico opt-in, con sus autoridades y dependencias separadas.
- `differential.tsv` denomina explícitamente sus columnas
  `official_result` y `historical_legacy_result`; no se cambió ninguna
  expectativa.

No se reescribieron reportes históricos ni se creó una política paralela.

## 3. Mapa de callers del diferencial

| Consumer | Uso | Estado después del cambio |
|---|---|---|
| Ejecución manual documentada en `compiler-next/README.md` | Gate de qualification | Sigue invocando `tests/run-differential.sh`, ahora oficial y aislado |
| `aether-driver/tests/vertical.rs` | Lee `differential.tsv`; no invoca el shell | Conserva admisión frontend/diagnósticos de todos los casos |
| Reportes de arquitectura fechados | Registran ejecuciones pasadas del script | Evidencia histórica; no son callers ejecutables |
| `.github/` y `scripts/` | Búsqueda textual del nombre del script | No se encontraron callers actuales |

No hay un caller indirecto versionado que convierta el modo histórico nuevo en
gate oficial.

## 4. Comportamiento anterior

`tests/run-differential.sh`:

1. construía `aether-next`;
2. descartaba toda fila cuyo resultado legacy fuera `n/a`, por lo que sólo
   ejecutaba 21 de las 96 filas del manifiesto;
3. ejecutaba `aether-next run` y luego `.venv/bin/python -m aether.cli`;
4. sumaba en un único contador los fallos actuales y legacy;
5. exigía exit status exacto sólo para `accept`, pero para `reject` no validaba
   el diagnostic ID y para `trap` no verificaba ninguna condición;
6. terminaba con el número acumulado de fallos y mostraba ambos statuses por
   caso.

La ejecución pre-cambio observada fue `checked=21 failures=0`.

## 5. Comportamiento nuevo

`tests/run-differential.sh` ahora:

- ejecuta las 96 expectativas oficiales, sin filtrar por la columna legacy;
- valida el exit status exacto de `accept:N`;
- valida rechazo y diagnostic ID en `reject:EXXXX`;
- exige el status de trap que expone `aether-next` y no acepta como trap un
  fallo de compilación/driver;
- informa por separado errores de infraestructura;
- no contiene path, import, descubrimiento ni invocación de Python,
  `compiler-rs`, `aether-compiler-core`, PyO3 o Maturin;
- retorna éxito sólo cuando no existe ningún fallo de `compiler-next`.

`AETHER_NEXT_BIN` y `AETHER_QUALIFICATION_MANIFEST` son seams acotados del
harness para probar el control de resultados sin crear infraestructura general.

## 6. Separación normativa e histórica

Se conservó valor arqueológico en un script separado:
`tests/run-legacy-differential.sh`.

- sólo se ejecuta si una persona lo invoca explícitamente;
- se anuncia como `NON-NORMATIVE` al iniciar;
- inspecciona únicamente las 21 filas con observación legacy;
- reconoce como esperadas las diferencias `INTENTIONAL_CHANGE` codificadas en
  el manifiesto;
- un cambio de observación se describe expresamente sin imputar un defecto a
  `compiler-next`;
- Python ausente o un import imposible producen error de infraestructura;
- su resultado no es consumido por el script ni por los gates oficiales.

Separarlo fue más seguro que un flag: hace imposible activar accidentalmente
Python desde el entry point oficial y permite auditar dependencias por archivo.

## 7. Tests positivos y negativos

`tests/test-differential-harness.sh` cubre:

- expectativa oficial positiva, rechazo con diagnostic ID y trap;
- Python legacy disponible pero no invocado;
- Python legacy inexistente;
- ejecución desde un árbol mínimo donde `compiler-rs` no existe;
- escaneo del gate oficial contra nombres/dependencias legacy;
- expectativa normativa deliberadamente incorrecta, que produce FAIL;
- driver de `compiler-next` roto, que produce FAIL;
- divergencia legacy esperada, que queda informativa;
- observación legacy inesperada, que falla sólo el modo histórico y aclara que
  no implica un defecto actual;
- infraestructura histórica inexistente, que no se oculta.

Resultado: `differential harness tests: PASS`.

## 8. Pruebas sin dependencias legacy

El harness oficial pasó sus casos focales con un Python ejecutable, con un path
Python inexistente y desde un árbol temporal sin directorio `compiler-rs`.
Además, la ejecución real se lanzó con
`AETHER_LEGACY_PYTHON=/definitely/unavailable`; procesó las 96 filas, por lo que
la ausencia legacy no impidió construir ni ejecutar `compiler-next`.

La búsqueda de manifests de `compiler-next` tampoco encontró referencias a
`compiler-rs`, `aether-compiler-core`, PyO3 o Maturin.

## 9. Gates ejecutados

| Gate | Resultado |
|---|---|
| Baseline anterior `bash compiler-next/tests/run-differential.sh` | PASS, 21/21 |
| `bash -n` sobre los tres scripts del harness | PASS |
| `bash compiler-next/tests/test-differential-harness.sh` | PASS |
| `bash compiler-next/tests/run-legacy-differential.sh` | PASS, 21/21, no normativo |
| `cargo test --manifest-path compiler-next/Cargo.toml -p aether-driver --test vertical differential_manifest_admission_and_codes_are_current` | PASS, 1/1 |
| `cargo test --manifest-path compiler-next/Cargo.toml -p aether-cli` | PASS, 31 tests |
| `cargo check --manifest-path compiler-next/Cargo.toml --workspace` | PASS |
| Validación de existencia/permisos de paths y enlaces documentales locales | PASS |
| `git diff --check` y check equivalente para archivos nuevos no rastreados | PASS |
| Gate oficial real con Python legacy inaccesible | **FAIL**, 96 checked, 1 fallo real |

El fallo oficial es reproducible directamente:

```text
iteration_v3_smoke.ae -> status 2
error[E0601]: clang rejected generated LLVM
multiple definition of local value named 'fmt_observed18_0'
```

Las primeras 95 filas cumplieron su expectativa. La fila
`array_list_borrowed_for_in` esperaba `accept:0`; no se modificó.

## 10. Archivos modificados

- `docs/architecture/COMPILER_AUTHORITY.md` (nuevo)
- `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md`
- `docs/reports/COMPILER_AUTHORITY_AND_QUALIFICATION_ISOLATION_V1_REPORT.md`
  (nuevo)
- `README.md`
- `compiler-next/README.md`
- `compiler-next/tests/differential.tsv`
- `compiler-next/tests/run-differential.sh`
- `compiler-next/tests/run-legacy-differential.sh` (nuevo)
- `compiler-next/tests/test-differential-harness.sh` (nuevo)

No se modificó `compiler-rs`, el compilador Python, AST/REPL/LSP, packaging,
HIR/MIR/SSA, backend LLVM, semántica, OAL ni workflows.

Los cambios personales y artefactos que ya estaban presentes en el preflight
se preservaron. No se hizo commit, push ni tag.

## 11. Limitaciones y estado de cierre

La autoridad documental y el aislamiento de qualification están completos. Un
fallo legacy no puede bloquear el gate oficial y un fallo real de
`compiler-next` sí lo bloquea, como quedó demostrado.

El milestone permanece **NO CLOSED** porque la qualification oficial real no
está verde. Corregir la colisión de nombres LLVM pertenece a otro cambio con
autorización para tocar el backend; no se inició automáticamente esa etapa ni
ninguna etapa posterior del retiro legacy.

## 12. Mensaje de commit sugerido

```text
test(compiler-next): isolate official qualification from legacy compilers
```

## 13. Seguimiento: LLVM-LOCAL-NAME-UNIQUENESS-V1

El milestone posterior `LLVM-LOCAL-NAME-UNIQUENESS-V1` identificó la causa
raíz del `E0601`: el lowering de interpolación de strings observaba dos veces
el mismo hole prestado durante sizing y escritura, y por ello emitía dos
definiciones del mismo nombre local LLVM `%fmt_observed{result}_{index}`.

La corrección conserva durante sizing el operando observado y lo reutiliza en
la fase de escritura. No se alteró la expectativa normativa
`array_list_borrowed_for_in = accept:0`, no se ocultó el fallo del gate y no se
introdujeron dependencias hacia Python legacy, `compiler-rs`,
`aether-compiler-core`, PyO3 ni Maturin.

Después de esa corrección, el mismo gate oficial obtuvo:

```text
qualification: mode=official checked=96 failures=0
```

También pasaron los tests del harness, Format V1, Iteration V3, Shape Contract
Diagnostics, Uncaught Exception Diagnostics y el workspace completo, incluidos
`cargo check`, `cargo test`, `cargo fmt --check` y `cargo clippy`.

Por tanto, los requisitos originales quedan satisfechos: la qualification
oficial está aislada de implementaciones legacy, sigue detectando fallos reales
de `compiler-next` y, una vez corregida la causa raíz en su milestone propio,
queda completamente en verde. El estado final de
`COMPILER-AUTHORITY-AND-QUALIFICATION-ISOLATION-V1` es **CLOSED**.
