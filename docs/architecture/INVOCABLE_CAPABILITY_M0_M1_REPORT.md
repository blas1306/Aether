# Aether — INVOCABLE-CAPABILITY-V1 — M0/M1 Final Qualification

Fecha: 2026-11-04.

Estado de milestones: **M0 CLOSED; M1 CLOSED**.

Estado del vertical completo: **INVOCABLE-CAPABILITY-V1 PARTIAL**. M2, M3 y
M4 no están implementados y no se comenzaron durante esta qualification.

Autoridad normativa:

- `INVOCABLE_CAPABILITY_ARCH_1.md`;
- `INVOCABLE_CAPABILITY_ARCH_1_REPORT.md`.

## Resultado

La implementación existente de M0/M1 quedó auditada contra la arquitectura,
completada únicamente con pruebas focales faltantes y calificada con el
workspace completo. No se agregó `CapabilityInvoke`, no se modificaron MIR,
SSA, LLVM, runtime ni libraries productivas.

El diff productivo permanece limitado a AST/parser, metadata y
canonicalización de tipos, requirements/evidence, satisfaction, sustitución,
forwarding, inferencia y diagnósticos del frontend. Las adiciones finales de
esta qualification dentro de esos archivos son pruebas de los gates M0/M1 y
la eliminación de un warning de Clippy en una aserción de prueba.

## Implementación verificada

- AST contextual con `AstInvocableSignature`; `Invocable` se acepta sólo como
  constraint de binder generic y no como tipo de valor.
- `CallableSignatureId` internado por parámetros ordenados y resultado,
  separado de `TypeData`; aliases transparentes se resuelven antes del
  interning.
- `GenericRequirement::Atomic` e `Invocable` conservan separadas la lattice
  atómica y la firma parametrizada.
- evidence declaration-owned ligada a owner, binder, requirement y ordinal;
  el verificador HIR reconstruye y contrasta cada identidad con las tablas de
  `TypeArena`.
- satisfaction exacta para `Function` y `Closure`; referencias, escalares y
  firmas de aridad, parámetro o resultado distintos son rechazados.
- sustitución recursiva de tipos dentro de parámetros y retorno, con
  reinterning canónico de la firma.
- forwarding simbólico exige un requirement `Invocable` equivalente en el
  binder remitido.
- inferencia descompone la firma del carrier, incluyendo parámetros que sólo
  aparecen en el requirement y el retorno, y rechaza conflictos de manera
  determinista.

## Matriz de gates M0/M1

| Gate | Evidencia | Estado |
|---|---|---|
| Constraints atómicas sin regresión | frontend completo, suites generic y workspace; `capabilities` y requirements atómicos conservados | PASS |
| `Invocable` sólo en constraints | parser focal rechaza variable, elemento de `Array` y retorno | PASS |
| Firma canónica y aliases | igualdad por `CallableSignatureId`; alias/directo duplicado rechazado | PASS |
| Cero, uno y múltiples parámetros | parser, satisfaction e integración focal | PASS |
| Resultado `void` | `Invocable<(),void>` y carrier `Function<(),void>` | PASS |
| Duplicados y contradicciones | duplicado directo, duplicado tras alias y firmas distintas | PASS |
| Evidence owner/binder/ordinal | metadata inspeccionada y corruption tests independientes | PASS |
| Evidence de otra declaración | mutación a `GenericOwner::Function(1)` rechazada por `verify_hir` | PASS |
| Function/Closure exactos | ambos carriers aceptados; aridad, parámetro y resultado incompatibles rechazados | PASS |
| No invocables | scalar y referencia a callable rechazados; diagnóstico distingue no-satisfaction | PASS |
| Sustitución recursiva | `Array<T>` y `Function<(T),T>` dentro de la firma se cierran a `float64` | PASS |
| Forwarding simbólico | `D: Invocable<(P),R>` remitido a otro binder equivalente | PASS |
| Inferencia desde parámetros y retorno | `P` y `R` inferidos desde la firma del carrier | PASS |
| Conflictos deterministas | fuente ordinaria `P=bool` contra firma `P=int` produce conflicto | PASS |
| Metadata corrupta independiente | owner, binder, ordinal, requirement ID y signature ID inválido rechazados directamente por el verifier | PASS |
| Frontera M0/M1 | invocación de carrier generic produce `E0475` antes de crear HIR productivo | PASS |

## Frontera fail-closed `E0475`

La rama de resolución de llamadas en `aether-frontend/src/hir.rs` reconoce un
local cuyo tipo es un binder con requirement `Invocable` y retorna `E0475`
inmediatamente. El retorno ocurre antes de obtener parámetros concretos y
antes de construir una expresión HIR de llamada. El análisis completo falla y
no puede alcanzar MIR, SSA o LLVM con una representación inventada.

La búsqueda del workspace encuentra `CapabilityInvoke` en código únicamente
en el texto de `E0475` y en su aserción de prueba. No existe variante
`CapabilityInvoke`, no existe `TypeData::Invocable` y no hay ruta de lowering o
codegen para dispatch generic. Por tanto la falta deliberada de M2 permanece
en la frontera correcta y no puede emitir código productivo incorrecto.

## Qualification focal

Todos los comandos se ejecutaron desde `compiler-next`, con Cargo serial y
`TMPDIR=/tmp/aether-invocable-m0-m1.hHVwan`, comprobado escribible.

| Comando | Exit | Resultado exacto |
|---|---:|---|
| `CARGO_INCREMENTAL=0 cargo test -p aether-frontend invocable -j 1` | 0 | 10 passed, 0 failed, 79 filtered |
| `CARGO_INCREMENTAL=0 cargo test -p aether-frontend generic_invocation_stops_at_the_m0_m1_boundary -j 1` | 0 | 1 passed, 0 failed, 88 filtered |
| `CARGO_INCREMENTAL=0 cargo test -p aether-frontend -j 1` | 0 | 89 passed, 0 failed; doc-tests 0 |
| `CARGO_INCREMENTAL=0 cargo test -p aether-driver --test generic_local_inference_v1 --test generic_inference_ref_argument_v1 --test function_values_v1 --test anonymous_functions_v1 --test owning_closures_read_v1 -j 1` | 0 | 8 + 5 + 8 + 5 + 25 = 51 passed, 0 failed |

Las suites Function Values y Anonymous Functions conservaron sus casos de
cero/uno/múltiples parámetros, `void`, aridad y firmas inválidas. Owning
Closures conservó validación HIR/MIR/SSA, lifecycle, exceptions, ARC y ASan.

## Workspace global y doc-tests

Comando:

```text
TMPDIR=/tmp/aether-invocable-m0-m1.hHVwan \
CARGO_INCREMENTAL=0 cargo test --workspace -j 1
```

Resultado: **exit 0**, 111 grupos de resultados, **1004 passed, 0 failed, 0
ignored**. Incluyó `vertical` 220/220, frontend 89/89, middle 29/29, registry
5/5 y los doc-tests de los siete crates del workspace (0 doctests, 0 fallos).

El último test,
`linear_algebra_oal_publishes_and_runs_real_qr_consumer`, terminó PASS en
**954.69 s** y ejecutó O0 y O2. El histórico revisado documenta 951.74 s,
1047.50 s, 1083.20 s y 1094.48 s para corridas equivalentes. El test usa la
ejecución síncrona normal y no contiene `timeout`, `Duration` ni `sleep`; no
existe un timeout artificial inferior a su duración habitual. La salida
numérica intermedia demostró progreso real, por lo que no fue detenido.

Log íntegro de la corrida: `/tmp/aether-invocable-m0-m1-workspace.log`.

## Gates estáticos

| Comando | Exit |
|---|---:|
| `cargo fmt --all --check` | 0 |
| `cargo clippy --workspace --all-targets -j 1` | 0 |
| `git diff --check` | 0 |

Clippy conserva warnings permitidos y preexistentes del workspace:
`large_enum_variant`, `needless_borrows_for_generic_args`, `match_same_arms`,
`assert_is_empty`, `single_match`, `too_many_lines` y `manual_let_else`. El
warning inicialmente observado en la aserción de parámetros vacíos de la
prueba M0 se corrigió; la qualification final no agrega una categoría nueva.

## Limitaciones pendientes

- M2: `CapabilityInvoke` proof-carrying, validación universal del body,
  obligations simbólicas y corruption matrix de generic HIR.
- M3: especialización a los spines Function/Closure, cleanup simbólico y
  rechazo residual pre-MIR.
- M4 y qualification completa: preservación de eventos/unwind, matrices O0/O2
  ejecutables de invocation generic, ausencia residual y contadores de coste.

Estas limitaciones impiden declarar cerrado `INVOCABLE-CAPABILITY-V1`, pero no
son gates de M0/M1. No se implementó ni inició ninguna de ellas.

## Archivos modificados

- `compiler-next/crates/aether-frontend/src/ast.rs`;
- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-frontend/src/lib.rs`;
- `compiler-next/crates/aether-frontend/src/parser.rs`;
- `compiler-next/crates/aether-frontend/src/types.rs`;
- `docs/architecture/INVOCABLE_CAPABILITY_M0_M1_REPORT.md`.

No se hizo commit ni push. No se comenzó M2.

Clasificación final: **M0/M1 CLOSED; INVOCABLE-CAPABILITY-V1 PARTIAL**.
