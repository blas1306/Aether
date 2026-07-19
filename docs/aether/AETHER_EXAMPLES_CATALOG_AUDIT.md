# Auditoría de cierre del catálogo de ejemplos para RC3

> Classification: **Audit**. Fecha: **2026-07-18**. Esta decisión no amplía
> el perfil normativo Aether 1.0 ni implementa features nuevas.

El catálogo ejecutable autoritativo es
[`../../examples/v1_examples_manifest.json`](../../examples/v1_examples_manifest.json).
La auditoría inicial contenía 78 `V1_NATIVE`, 21 `AST_ONLY_EXPERIMENTAL` y
cuatro `BROKEN`. El resultado es 78 `V1_NATIVE`, 23
`AST_ONLY_EXPERIMENTAL`, un `INVALID_FIXTURE`, un archivo `REMOVED` y cero
`BROKEN` dentro de 101 ejemplos públicos.

De los 23 experimentales, 14 tienen ejecución AST automatizada con exit code y
hashes de stdout/stderr; los nueve restantes son cuatro programas interactivos,
tres sesiones de plotting y dos módulos auxiliares. Todos pasan frontend y
declaran el conjunto exacto de capabilities que native rechaza antes de IR.

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
