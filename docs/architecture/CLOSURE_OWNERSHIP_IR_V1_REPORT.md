# Aether — CLOSURE-OWNERSHIP-IR-V1 — Implementation & Qualification Report

Fecha: 2 de noviembre de 2026.

Estado: **CLOSED para el subvertical HIR/MIR/SSA; el milestone
`OWNING-CLOSURES-READ-V1` permanece PARTIAL**.

## Resultado ejecutivo

Las closures capturantes ya atraviesan HIR, MIR y SSA como operaciones
semánticas owning explícitas, con identidad de environment, `BindingId`, tipo,
modo y orden de cada captura. Cada IR reconstruye y verifica su propio contrato;
la validez de una fase anterior no actúa como autoridad para la siguiente.

El rechazo `E0376` se trasladó desde el análisis temprano a la frontera posterior
a `VerifiedSsa`. De este modo se califica la representación completa sin fingir
un backend productivo: LLVM todavía no asigna `ClosureBox`, no materializa el
payload ni emite invoke/destroy thunks o `ClosureCall` ejecutable.

Las lambdas sin captura conservan la ruta existente `FunctionRef` /
`IndirectCall` y el ABI de `Function` no cambió.

## Contrato implementado

### HIR

- `ClosureRecipe` identifica environment, firma, invoke/destroy y recipe de
  destrucción `nounwind`.
- `HirClosureCapture` conserva `BindingId`, source local, tipo y modo
  `Copy`/`Alias`/`Move` en orden canónico.
- `ClosureCreate`, `ClosureAlias` y `ClosureCall` permanecen como operaciones
  tipadas; no se degradan a punteros crudos.
- Los slots sintéticos del body read-only conservan el `BindingId` original.
  Después del análisis de capturas no se reconstruye identidad por spelling.
- El ledger aplica snapshot para `Copy`, adquisición owning independiente para
  `Alias` y transferencia con invalidación del source para `Move`. No existe
  `Move` implícito.
- El verificador rechaza environments, firmas, orden, identidad, tipos, modes,
  sources, references/views, slots o recipes incompatibles.

### MIR

- `MirFunction` expone capture slots read-only y `FlowMir` publica la tabla de
  environments independientemente del HIR.
- `ClosureCreate` representa el prefijo de inicialización antes/después de cada
  adquisición y el estado de publicación. Un box incompleto no cuenta como
  publicado.
- `ClosureAlias`, transferencias, replacement, argumento, return y cleanup se
  integran con el ledger owning existente.
- La invocación usa `ClosureBorrow`, evaluación de argumentos, `ClosureCall` y
  `EndClosureBorrow`. El end existe tanto en el edge normal como en el unwind.
- El análisis path-sensitive rechaza joins incoherentes, fin ausente/duplicado y
  move, drop, replacement o invalidación del carrier mientras está protegido.
- `ClosureCall` es conservadoramente may-unwind y mantiene la identidad del
  `ExceptionEvent`; `finally` no gana una nueva clase de llamada de usuario.

### SSA

- `SsaIr` conserva environments, capture slots, provenance, modes, owner
  transfers, borrow tokens y edges normal/unwind hasta `VerifiedSsa`.
- `ClosureCreate`, `ClosureAlias`, `ClosureBorrow`, `ClosureCall` y
  `EndClosureBorrow` siguen siendo operaciones semánticas.
- El verificador SSA reconstruye types/recipes/orden/identidades, verifica el
  ledger owning y prohíbe escapes por phi, duplicación de obligación, consumo o
  invalidación antes de `EndClosureBorrow`.

## Frontera productiva

El driver detiene cualquier programa capturante después de verificar SSA con:

```text
E0376: capturing Closure reached VerifiedSsa, but productive LLVM Closure lowering is not implemented
```

El backend también contiene una guarda fail-closed si se lo invoca directamente
con esas operaciones. No se genera un binario parcial ni se omite silenciosamente
el lifecycle owning.

Por tanto no se declaran implementados ni calificados:

- allocation y publicación LLVM de `ClosureBox`;
- layout productivo del payload;
- invoke/destroy thunks y su reachability;
- codegen de `ClosureCall`;
- ejecución real O0/O2 de closures capturantes;
- adapters generales `Function`/`Closure` o callable general.

## Qualification

Cobertura focal agregada o extendida:

- `owning_closures_read_v1`: **21/21 PASS**;
- `anonymous_functions_v1`: **5/5 PASS**;
- `function_values_v1`: **8/8 PASS**;
- unit tests frontend: **78/78 PASS**;
- unit tests middle: **29/29 PASS**.

La suite cubre `Copy`/`Alias`/`Move` en las tres IR, capturas parciales y
transitivas, lambdas anidadas, return, paso por argumento, alias y
self-replacement, use-after-move, borrow normal/unwind y determinismo. Las
corrupciones independientes incluyen capture faltante/reordenada, modo,
`BindingId`, tipo, prefijo de inicialización, recipe de destroy, fin de borrow y
drop ausente/duplicado.

Gates de repositorio:

- `CARGO_INCREMENTAL=0 TMPDIR=/tmp/aether-closure-ir-v1 cargo test --workspace -j 1`:
  **PASS completo, código 0**; incluye la prueba final de registry
  `linear_algebra_oal_publishes_and_runs_real_qr_consumer` (**5/5**, 951,74 s)
  y todos los doc-tests;
- `cargo fmt --all --check`: **PASS**;
- `cargo clippy --workspace --all-targets -j 1`: **código 0**, con warnings
  preexistentes;
- `git diff --check`: **PASS**.

No se modificaron Graphics, Plots, bibliotecas numéricas ni ejemplos
personales.

## Estado del milestone principal

`CLOSURE-OWNERSHIP-IR-V1` cierra la representación y qualification de ownership
hasta `VerifiedSsa`. `OWNING-CLOSURES-READ-V1` permanece **PARTIAL** porque sus
gates productivos requieren boxes, thunks, lowering LLVM y ejecución O0/O2
reales. Este reporte no reclasifica interoperabilidad entre compilaciones
independientes, que continúa fuera del alcance del milestone actual.
