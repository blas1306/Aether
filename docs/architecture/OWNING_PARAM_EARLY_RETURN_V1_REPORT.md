# OWNING-PARAM-EARLY-RETURN-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-23.

Autoridad normativa:

- [OWNING-PARAM-EARLY-RETURN-ARCH-1](OWNING_PARAM_EARLY_RETURN_ARCH_1.md)
- [OWNING-PARAM-EARLY-RETURN-ARCH-1 — reporte](OWNING_PARAM_EARLY_RETURN_ARCH_1_REPORT.md)

## Resultado

Los parámetros owning por valor pueden permanecer `Owned` hasta cualquier
return alcanzable. HIR sintetiza el cleanup después de evaluar la expresión de
retorno; MIR conserva sus `Move`, `Drop`, flags y ladders existentes; SSA ya no
acepta o rechaza ownership mediante la existencia global de algún consume.

El shape original de Expense Tracker compila por valor en una fixture dedicada:

```aether
int runList(Array<string> arguments, LedgerDecodeResult loaded) {
    if (length(arguments) != 2) {
        println("invalid arguments: <ledger.alpt> list");
        return 2;
    }
    printTransactions(loaded.ledger);
    return 0;
}
```

El port principal conserva por ahora sus firmas `ref`, tal como permitía la
decisión de arquitectura.

## Implementación

### HIR

`verify_hir` reconstruye el análisis de ownership sobre una copia del body y
compara el plan resultante con el HIR recibido. Esto convierte `drops` y
`exit_drops` en evidencia verificada: omisiones, duplicados, orden incorrecto o
modo unconditional/conditional incorrecto se rechazan antes de MIR.

No se agregaron nodos ni estados. La síntesis existente sigue procesando primero
la expresión del return y excluyendo paths terminantes de joins continuantes.

### MIR

No fue necesario agregar otro lowering. El dataflow MIR existente ya inicia
parámetros non-Copy como `Owned`, transfiere el resultado antes del cleanup,
mantiene flags root-level y verifica que `Return` no conserve owners vivos. Las
suites completas confirman los ladders normales, condicionales y de unwind.

### SSA

La prueba existencial global de string ownership fue reemplazada por un ledger
por obligación y CFG. Para cada root ordinario o string-compuesto registra
`Unborn`, `Live` o `Discharged` y recorre:

- parámetros, definiciones, phis y backedges;
- `Move`, `Drop`, calls, aggregates, enums y containers;
- transfer del operand de retorno;
- edges normal/unwind, donde el resultado de una call sólo nace en normal;
- `ResumeUnwind`;
- branches de conditional cleanup correlacionados con el drop flag del mismo
  root.

Un exit normal o excepcional con estado `Live`, una segunda descarga o una
redefinición que pisa una obligación viva se rechaza. Los payloads proyectados
de enum y owners algebraicos/clases continúan bajo sus verificadores SSA
especializados y el Drop recursivo de su root compuesto.

## Qualification

Se agregó una fixture estructural de Expense Tracker y una vertical O0/O2 que
cubre:

- parámetro nunca movido con early return y return final;
- varios owners y cleanup en orden inverso;
- `return x` en un path y Drop en el sibling;
- branches anidados y varios early returns;
- return desde `while`, `for range` y collection loop;
- call con edge de unwind;
- `Array<string>`, `List<string>` y structs owning;
- balance final de allocations/frees de heap y string.

También se agregó corrupción específica que elimina sólo el Drop de uno de dos
exits. El sibling conserva otro Drop, por lo que el antiguo chequeo existencial
la habría aceptado; el ledger path-sensitive la rechaza. HIR tiene cobertura
equivalente para un early return sin cleanup. La matriz previa del repositorio
continúa cubriendo flags, phis, double Drop, unwind, finally, calls consumidoras,
containers, nullable, enums, clases y owners algebraicos.

## Validación

Ejecutado satisfactoriamente:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

La suite completa terminó con 219/219 tests de la vertical principal, 64/64 de
frontend, 29/29 de middle y todas las integraciones, incluidas las nuevas
pruebas O0/O2. El differential runner comprobó 21 casos con cero fallos.
