# Aether — CLOSURE-CAPTURE-ANALYSIS-V1 — Report

## Resultado

Estado: **CLOSED (semantic foundation); productive closure lowering remains out
of scope**.

La pérdida del scope ocurría en `analyze_bodies_for_target`: el parser anexaba
cada lambda como declaración sintética de módulo y la inferencia analizaba esa
declaración antes que la función creadora. Por eso un nombre exterior llegaba
al lookup con un scope nuevo y terminaba convertido en `E0359`.

La corrección introduce una fase entre collection de declaraciones y análisis
de bodies. Recorre la función creadora con scopes léxicos, resuelve cada uso
libre antes de analizar la declaración sintética y conserva identidad estable
`BindingId { function, ordinal }`. No hace lookup por nombre en backend, no
crea globals y no guarda snapshots sin identidad.

## Metadata

`ClosureEnvironmentInfo` conserva `LambdaId`, creador, target sintético, firma
`Closure` y capturas canónicas. Cada `ClosureCaptureInfo` contiene:

- `BindingId`, nombre sólo diagnóstico y carácter explicit/implicit;
- `CaptureMode`, source/capture `TypeId`;
- spans de declaración, primer uso y entrada explícita;
- índice de orden canónico.

Las capturas explícitas aparecen primero en orden source. Las implícitas se
ordenan por primer uso léxico y span de declaración. Una captura explícita no
usada permanece en metadata y produce `ClosureCaptureWarning W0369` con los
spans de adquisición y declaración.

## Política semántica

- `Copy + Storable`: Copy automático;
- owner con Alias intrínseco (`string`, class/interface handle o `Closure`):
  Alias automático;
- owner Move-only: sólo `capture(move name)`;
- references, views y non-Storable: rechazo `E0369`;
- Copy/Alias/Move explícitos se validan contra el binding concreto;
- acceso mutable capturado, captura inexistente o sombreada: rechazo source
  spanned.

El análisis distingue bindings homónimos, excluye funciones top-level, conserva
shadowing, procesa lambdas anidadas y propaga capturas transitivas. Una lambda
sin environment continúa como `Function`/`FunctionRef` sin allocation ni ARC.

## Frontera productiva

Una lambda capturante llega ahora hasta metadata y clasificación `Closure`. El
pipeline se detiene después con `E0376`: el lowering productivo de Closure no
está implementado. Nunca se degrada a `FunctionRef`, no genera LLVM inválido y
no afirma que existan `ClosureCreate`, boxes o thunks.

## Qualification

Gates dedicados ejecutados el 2 de noviembre de 2026:

- `owning_closures_read_v1`: **13/13 PASS**;
- `anonymous_functions_v1`: **5/5 PASS**;
- `function_values_v1`: **8/8 PASS**;
- ambos reproducers avanzan de `E0359` a la frontera explícita `E0376`.

La suite dedicada cubre Copy/Alias automático, Move explícito, cláusula
parcial, captura explícita no usada, orden, identidad, shadowing, bindings
homónimos, referencias/views, Move implícito, mutable capture, captura
inexistente, nesting/transitividad, `Function` versus `Closure` y spans.

Qualification global:

- `TMPDIR=/home/blasm/tmp CARGO_INCREMENTAL=0 cargo test --workspace -j 1`:
  **PASS completo**; el test final de registry pasó 5/5 y el caso largo
  `linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó en 987.34 s;
- `cargo fmt --all --check`: **PASS**;
- `cargo clippy --workspace --all-targets -j 1`: **código 0**; se corrigieron
  los warnings atribuibles al subvertical y permanecen warnings preexistentes;
- `git diff --check`: **PASS**.

## Alcance preservado

No se implementaron operaciones HIR/MIR/SSA productivas, allocation LLVM,
invoke/destroy thunks, runtime nuevo, Callable general, adapters,
BorrowedClosure, storage en aggregates ni compilación separada. Plots,
Graphics, bibliotecas numéricas y ejemplos personales no fueron modificados.

