# Auditoría de cierre del catálogo de ejemplos para RC3

> Classification: **Audit**. Fecha: **2026-07-18**. Esta decisión no amplía
> el perfil normativo Aether 1.0 ni implementa features nuevas.

El catálogo ejecutable autoritativo es
[`../../examples/v1_examples_manifest.json`](../../examples/v1_examples_manifest.json).
La auditoría inicial contenía 78 `V1_NATIVE`, 21 `AST_ONLY_EXPERIMENTAL` y
cuatro `BROKEN`. Su cierre dejó 78 `V1_NATIVE`, 23
`AST_ONLY_EXPERIMENTAL`, un `INVALID_FIXTURE`, un archivo `REMOVED` y cero
`BROKEN` dentro de 101 ejemplos públicos.

El mantenimiento del 2026-07-28 incorporó cuatro ejemplos públicos añadidos
después de ese cierre, promovió `Sorts/Main.ae` y `Sorts/Sortings.ae` de acuerdo
con el soporte native observado, y preservó las promociones de clases ya
registradas por el manifiesto. El catálogo actual contiene 105 rutas: 88
`V1_NATIVE`, 17 `AST_ONLY_EXPERIMENTAL` y cero `BROKEN`. De los 17
experimentales, nueve tienen ejecución AST automatizada con exit code y hashes
de stdout/stderr; los ocho restantes son entradas frontend, interactivas, de
plotting o módulos auxiliares. Todos pasan frontend y declaran el conjunto
exacto de capabilities que native rechaza antes de IR.

## Reconciliación de mantenimiento del 2026-07-28

Los SHA-256 de archivo de esta tabla se calcularon sobre los bytes crudos del
checkout y son evidencia de auditoría, no campos del manifiesto. Los hashes que
sí forman parte del manifiesto corresponden a observaciones stdout/stderr
normalizadas como documenta `examples/README.md`.

| Fallo original | Entrada anterior / archivo SHA-256 | Comportamiento observado | Causa y resolución |
| --- | --- | --- | --- |
| Inventario autoritativo | Sin entrada: `LeetCode/isPalindrome.ae` (`edafdae8966f606c7834075443386952cc3629681868662df5a052ed45c88fb5`), `LeetCode/twoSum.ae` (`1b64daeaa15a92fcd91cf2f37c297084899b9e152472dcf89069ac418137ee28`), `SNL.ae` (`9070d715e8448f7ebec91dff49641e4d01dd35d9b9845851cd6af7b7fb240504`) y `nonlinear_systems/nr2.ae` (`18b58084c7600a3342aa844e5b11e96dcb86c45c9cac026d71382dbd2cec1a7c`). | Los dos LeetCode pasan gate, IR, SSA, LLVM y ejecución native. `SNL` es AST-only por `ARITHMETIC`, `MATRIX` y `VECTOR`; `nr2` por `MATRIX` y `VECTOR`; ambos ejecutan con exit 0. | Inventario faltante. Se añadieron cuatro entradas explícitas en orden determinista. |
| Clasificación de `Sorts/Main.ae` | `AST_ONLY_EXPERIMENTAL`; archivo `d3d8bf37281b38bb96402f1eec9fddd34ce77dc5df6d9b431d5aa47975597838`. | Sin rechazos de capability; pasa IR, SSA, LLVM y ejecución native con exit 0. | Clasificación obsoleta. Se promovió a `V1_NATIVE`. |
| Clasificación de `Sorts/Sortings.ae` | `AST_ONLY_EXPERIMENTAL`; archivo `4b208cb588b35cccad6ddc20f024c877669f131f01561f422b5bfe3009024acc`. | Sin rechazos de capability; emite como módulo native y no declara entry point. | Clasificación obsoleta. Se promovió a `V1_NATIVE` con `native_module_emission`. |
| Capabilities de `nonlinear_systems/newton_system.ae` | Faltaban `FUNCTION_VALUES` y `MODULES`; archivo `308c89b86dce3b6c9b7999a15dd5605ec7eb58530e2ced6b585036eedf4e2305`. | Sigue siendo AST-only; el gate reporta exactamente seis códigos, antes de IR. | Metadatos de clasificación obsoletos. Se sincronizó `outside_v1_features`. |
| Hash native de `nose.ae` | stdout `8060aa…7cc3`; archivo `7a82fe147bdae21eaec574d5a9a0182477ae174cde41e9a970cf1e68fd057396`. | Exit 0, stdout `10000000\n`, SHA-256 `de6aeb89…4bbf0`, stderr vacío. | Observación obsoleta tras cambiar el ejemplo. Se actualizó el hash. |
| Hash de `Sorts/Main.ae` | stdout AST `0fa8c62f…1502`; mismo archivo auditado arriba. | La salida actual tiene SHA-256 `b82b299c…8714b` y coincide con native. | Observación obsoleta y backend obsoleto. Se registró la observación native canónica. |
| Hash AST de `nonlinear_systems/newton_system.ae` | stdout `aea58ea9…f51f`; mismo archivo auditado arriba. | Exit 0, stdout SHA-256 `3ac3e5b9…76e33`, stderr vacío. | Observación obsoleta. Se actualizó el hash sin modificar el ejemplo. |

## Decisión sobre los cuatro archivos rotos

| Ruta auditada | Propósito e historia inferida | Sintaxis y feature que fallaba | Backend y fase | Referencias y valor conservado | Decisión |
| --- | --- | --- | --- | --- | --- |
| `examples/linear_algebra/primes_advanced.ae` | Ajuste de la sucesión de primos mediante mínimos cuadrados y plot. Nació el 2026-05-24 (`09cf6c3`) y fue movido desde `src/aether/prueba3.ae` el 2026-05-29. | Vectores columna inferidos, solve `A \ p`, producto `A*z`, índices históricos desde cero y función abreviada usada por `Plots.plot!`. El fallo auditado era `Matrix * Vector<Row>` en el typechecker. | AST y native, typecheck, antes de capability/IR. | Enlazado por README, manifiesto, auditorías de álgebra/perfil y `CLEANUP_REPORT.md`. Conserva valor como demostración experimental de álgebra host y plotting. | `AST_ONLY_EXPERIMENTAL`; orientación/tipos/índices actualizados, typecheck válido y rechazo native temprano por capabilities declaradas. |
| `examples/minimos_cuadrados/MinimosCuadrados.ae` | Ajuste general de mínimos cuadrados con función base y plot. Proviene de `src/aether/MinimosCuadrados.ae`, reorganizado el 2026-05-29. | Vectores fila usados como RHS, pérdida de orientación en `A*z`, índices históricos desde cero y función top-level usada como valor. El fallo auditado era `Matrix * Vector<Row>`. | AST y native, typecheck, antes de capability/IR. | Enlazado por README, manifiesto, auditoría de perfil y `CLEANUP_REPORT.md`. Es la variante completa que justifica conservar el tema. | `AST_ONLY_EXPERIMENTAL`; orientación/tipos/índices y residual actualizados, typecheck válido y rechazo native temprano por capabilities declaradas. |
| `examples/minimos_cuadrados/interactive.ae` | Variante interactiva incompleta, movida desde `src/aether/prueba8.ae` el 2026-05-29. Leía dos vectores pero nunca llenaba la matriz de diseño. | `input`, plotting y una función abreviada anidada que capturaba la variable local `z`; las closures/funciones anidadas están fuera de v1. El fallo era `Undefined variable 'z'`. | AST y native, typecheck del frontend. | Sólo tenía comprobación de existencia, README, manifiesto, auditoría y reporte histórico. Duplicaba la demostración no interactiva y no era un fixture de migración porque no existe migración normativa de closures. | `REMOVED`; no aporta cobertura válida ni una transformación mecánica verificable. |
| `examples/pruebaListas.ae` | Experimento mínimo añadido el 2026-06-07 (`1c252aa`) junto con trabajo inicial de Lists. | `List<int>` y asignación escalar a slice `xs[0:3] = 0`; la asignación a slices no está soportada. | AST y native, typecheck, con diagnóstico en 2:9. | Enlazado sólo por README, manifiesto y auditoría de perfil. Conserva valor como frontera negativa estable del typechecker. | `INVALID_FIXTURE`; movido a `tests/fixtures/invalid/list_slice_assignment.ae` con expectativa JSON estructurada. |

No se creó ningún `MIGRATION_FIXTURE`: ninguno de los cuatro casos dispone de
una transformación soportada por `migrate_control_flow_rc2.py`. Reclasificar la
función anidada o la asignación a slices como migrables habría prometido una
feature/migración inexistente.

## Evidencia de separación

- Todos los `.ae` que permanecen bajo `examples/` tienen exactamente una
  entrada de manifiesto y sólo una de las dos clasificaciones públicas.
- El fixture inválido vive bajo `tests/fixtures/invalid/`, declara categoría,
  tipo de diagnóstico, línea, columna, fragmento y exit code, y tiene regresión
  propia.
- Los dos ejemplos de álgebra corregidos no se presentan como v1: el manifiesto
  enumera cada código `AE-BACKEND-*` que los excluye de native.
- El archivo removido no aparece en el catálogo, packaging ni smoke tests.

Por tanto, `BROKEN examples = 0` y el hallazgo F01/R2/B13 puede cerrarse sin
incorporar álgebra host, plotting, input, closures o slice assignment al perfil
normativo.
