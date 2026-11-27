# TEST-QUALIFICATION-V1 — informe de implementación

Estado: **CLOSED**
Fecha: 2026-11-27

## 1. Resultado

Se implementó qualification reproducible para `compiler-next` con cuatro
perfiles: `core`, `conformance`, `oal` y `full`. El inventario falla cerrado
ante nuevos binaries de integración y el perfil Full conserva como autoridad
el comando literal, sin filtros:

```bash
cargo test --workspace -j 1 --no-fail-fast
```

El cierre se limita a los gates propios de TEST-QUALIFICATION-V1: tests del
runner, ejecución de Core y Conformance, y validación de los planes OAL y Full.
OAL y Full completos no fueron ejecutados, de acuerdo con el alcance autorizado.

## 2. Archivos y comandos

El manifiesto está en `compiler-next/tests/qualification.toml`. El punto de
entrada es:

```bash
tests/qualify.sh core
tests/qualify.sh conformance
tests/qualify.sh oal
tests/qualify.sh full
```

`--list` valida el manifiesto y muestra el plan sin ejecutar. `--json PATH`
escribe planificación o resultados en JSON. Sin `--json`, cada run deja un
`results.json` y un log por suite bajo `qualification-results/`; ese directorio
se ignora en Git.

## 3. Inventario clasificado

El manifiesto contiene 122 suites/gates, incluidas 113 suites de integración:

| Crate | Binaries inventariados |
| --- | ---: |
| `aether-driver` | 106 |
| `aether-package` | 3 |
| `aether-cli` | 1 |
| `aether-frontend` | 1 |
| `aether-lsp` | 1 |
| `aether-registry` | 1 |

Las pertenencias no son exclusivas: 10 binaries pertenecen a Core, 71 a
Conformance, 38 a OAL y los 113 están documentados como cubiertos por Full.
Full no los reejecuta individualmente: Cargo descubre y ejecuta el workspace
completo. Conformance ejecuta primero las 14 entradas de Core y luego sus
entradas adicionales.

El inventario incluye los 26 binaries `linear_algebra_*`, dos `graphics_*`,
cinco `plots_*`, package/registry, consumidores, CLI y LSP. Los 96 casos de
`differential.tsv` permanecen bajo autoridad exclusiva de
`run-differential.sh`; el manifiesto registra el script, no duplica casos ni
expectativas.

## 4. Validación cerrada

Antes de planificar o ejecutar se rechazan:

- TOML inválido, versión desconocida, IDs duplicados o perfiles inválidos;
- comandos vacíos o incompatibles con su target Cargo;
- scripts inexistentes, timeouts no positivos, owners o responsabilidades
  ausentes y metadata de plataforma/optimización incompleta;
- binaries de integración nuevos sin clasificación y referencias a binaries
  inexistentes;
- pérdida de los gates mínimos fijados por la arquitectura para Core o
  Conformance;
- alteración u omisión del comando literal del workspace en Full.

La ejecución es secuencial y determinista. Cada suite produce PASS, FAIL o
BLOCKED; un timeout, comando ausente o requisito de plataforma incumplido es
BLOCKED. FAIL y BLOCKED obligatorios producen exit status distinto de cero. El
timeout termina el grupo de procesos con TERM y, si es necesario, KILL.

En Linux, el JSON registra fase, duración, CPU observada y RSS máxima observada
del grupo de procesos. CPU/RSS son telemetría muestreada y por tanto una cota
observada, no contabilidad de precisión de todos los procesos muy breves.

## 5. Tests del runner

Se agregaron 13 tests independientes que no ejecutan el workspace. Cubren:

- parseo y validación del manifiesto;
- selección, orden y pertenencia múltiple de perfiles;
- perfil desconocido y referencia a suite inexistente;
- binary nuevo sin clasificación;
- protección ante la exclusión de una suite anteriormente obligatoria;
- propagación de FAIL y comando inexistente como BLOCKED;
- timeout y terminación de un hijo persistente;
- JSON válido;
- Full literal y sin exclusiones derivadas del manifiesto;
- exit status no cero ante FAIL/BLOCKED.

Resultado final: **13/13 PASS** en 2,15 s.

## 6. Qualification ejecutada

| Evidencia | Plan | Ejecutado | Resultado | Duración acumulada de suites |
| --- | ---: | ---: | --- | ---: |
| Runner independiente | 13 tests | 13 | PASS | 2,15 s |
| Compiler Core | 14 suites | 14 | **14 PASS** | 15,51 s |
| Language Conformance | 77 suites | 77 | **77 PASS** | 207,25 s |
| OAL Integration | 39 entradas | 0 | plan validado | no ejecutado |
| Full Ecosystem | 6 gates | 0 | plan validado | no ejecutado |

El plan Full contiene: tests del runner, autotest diferencial, diferencial
oficial, workspace literal, Clippy y rustfmt. El plan OAL contiene todas las
suites de linearAlgebra/graphics/plots, materialización, package y registry.

En Conformance, `vertical` fue la suite dominante (87,10 s). El diferencial
oficial completó sus 96 casos en 8,15 s. La suite BITWISE no commiteada fue
descubierta por el inventario y pasó, pero no se presenta como baseline del
repositorio ni se modificó su estado normativo.

Los JSON y logs finales quedaron en:

- `compiler-next/qualification-results/test-qualification-v1-core-final/`;
- `compiler-next/qualification-results/test-qualification-v1-conformance-final/`.

## 7. Timeouts y caso QR

No se usa un timeout global de 300 s. Los tests OAL tienen 1200 s y la suite
registry que contiene
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` tiene 1500 s. Full
dispone de 2400 s. El silencio no se interpreta como deadlock y cualquier
interrupción conserva estado BLOCKED.

El test QR no fue ejecutado en este milestone. Se preserva la evidencia
histórica de finalización normal en aproximadamente 699–1094 s; no se modificó
ni optimizó el test.

## 8. Riesgos residuales y política de cierre

- OAL y Full están planificados y validados, pero su estado de ejecución es
  desconocido en este cierre; no se declara que esos perfiles hayan pasado.
- La telemetría por muestreo puede omitir picos muy breves.
- Suites Cargo mixtas siguen teniendo una responsabilidad primaria aproximada;
  separarlas exige un milestone posterior y no debe eliminar assertions.
- Un cambio futuro que agregue un binary requiere clasificarlo antes de que
  cualquier perfil pueda arrancar.

TEST-QUALIFICATION-V1 se declara CLOSED porque todos sus gates de implementación
y qualification requeridos pasaron. La política no convierte fallos, timeouts,
omisiones ni runs interrumpidos en PASS.

## 9. Archivos modificados

- `compiler-next/.gitignore`;
- `compiler-next/tests/qualification.toml`;
- `compiler-next/tests/qualify.sh`;
- `compiler-next/tests/qualification_runner.py`;
- `compiler-next/tests/qualification_runner_test.py`;
- `compiler-next/tests/__init__.py`;
- `docs/architecture/TEST_QUALIFICATION_V1_REPORT.md`.

No se modificaron código productivo, tests semánticos, manifests Cargo, OAL,
registry ni los documentos normativos de BITWISE-OPERATORS-V1. Tampoco se
ejecutaron commit, push, reset, clean o stash.

Commit sugerido:

```text
test: add reproducible compiler qualification profiles
```
