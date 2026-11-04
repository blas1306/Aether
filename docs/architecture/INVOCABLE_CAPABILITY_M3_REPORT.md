# Aether — INVOCABLE-CAPABILITY-V1 — M3 Final Qualification

Fecha: 2026-11-04.

Estado: **M3 CLOSED; INVOCABLE-CAPABILITY-V1 PARTIAL**.

M0, M1 y M2 permanecen CLOSED. M4 (cierre end-to-end exhaustivo del vertical)
no se implementó.

## Resultado

La monomorfización ya reconstruye y valida cada `CapabilityInvoke` antes de
seleccionar dispatch desde el `TypeData` concreto:

- `Function<(P...), R>` se reescribe a `IndirectCall`;
- `Closure<(P...), R>` se reescribe a `ClosureCall`, que baja por el spine
  existente `ClosureBorrow` / `ClosureCall` / `EndClosureBorrow`;
- otros estados permanecen fail-closed mediante `E0475`.

La especialización vuelve a comprobar binder, declaración propietaria,
requirement, evidence, satisfaction, firma sustituida, callee, argumentos,
resultado, `RepeatableRead`, `MayUnwind`, provenance y `CallSiteId`. No confía
solamente en la evidence construida durante M2.

No se agregó dispatch, ABI, opcode, helper, runtime, adapter, vtable ni thunk.
`Function` continúa siendo indirecta y `Closure` reutiliza exactamente su
backend owning vigente.

## Ownership concreto

Después de sustituir locals, parámetros y body, el transfer function ordinario
de ownership reconstruye el cleanup con las propiedades concretas:

- un parámetro `Function` no genera `Drop`;
- un parámetro `Closure` vivo genera exactamente un cleanup owning;
- un carrier transferido o retornado queda invalidado en el source y no se
  limpia allí;
- early return, ramas, invocation repetida y unwind conservan el ledger
  path-local existente;
- la invocation de Closure no introduce retain/release por call.

El verifier concreto también considera ahora completa una firma `Closure`
solamente si todos sus parámetros y resultado están libres de generics. HIR
con `GenericParam` o `CapabilityInvoke` residual es rechazado antes de MIR.

## Exceptions

El rewriting conserva el `CallSiteId` original. MIR crea el único
`ExceptionEventId` correspondiente mediante el lowering vigente. Para Closure,
el landing pad contiene `EndClosureBorrow` antes del cleanup del carrier y
mantiene la excepción activa; no se crea un segundo evento de adaptación.

La qualification ejecutó O0/O2 con throw desde una Closure especializada y
catch en el caller. Ambos modos retornaron el resultado esperado y los
verificadores MIR/SSA aceptaron el spine normal y excepcional.

## Corruption tests

Además de las corrupciones proof-carrying de M2, M3 cubre independientemente:

- Function adulterada como `ClosureCall`;
- Closure adulterada como `IndirectCall`;
- Drop ficticio de Function;
- Drop omitido de Closure;
- `GenericParam` residual;
- `CapabilityInvoke` residual en HIR concreto.

Los verificadores existentes de Function Values y Owning Closures continúan
cubriendo firma, callee, resultado, aridad, borrow token, missing/duplicate
`EndClosureBorrow`, invalidación del carrier, unwind/event metadata y
corrupciones MIR/SSA.

## Qualification focal

El nuevo suite `invocable_capability_m3` cubre:

- Function top-level y lambda no capturante;
- Closure con captures Copy, Alias y Move;
- invocation repetida sin adquisición por invocation;
- parámetro ignorado y retorno/transferencia de `C`;
- una misma declaración con instancias Function y Closure;
- firma parametrizada por `P` y `R`;
- unwind, catch y `EndClosureBorrow` excepcional;
- HIR, MIR, SSA y ejecución real O0/O2.

Resultados focales:

| Comando | Resultado |
|---|---:|
| `cargo test -p aether-frontend -j 1` | 93 passed |
| suites Function Values, lambdas, Owning Closures, inferencia y Exceptions V1–V4 | 80 passed |
| `cargo test -p aether-driver --test invocable_capability_m3 -j 1` | 5 passed |

## Regresiones

Entorno: `CARGO_INCREMENTAL=0`, `TMPDIR=/tmp/aether-invocable-m3`, comprobado
escribible; Cargo serial (`-j 1`).

| Comando | Exit | Resultado |
|---|---:|---|
| `cargo test --workspace -j 1` | 0 | 1013 passed, 0 failed, 0 ignored; doc-tests PASS |
| `cargo fmt --all --check` | 0 | sin diferencias |
| `cargo clippy --workspace --all-targets -j 1` | 0 | sólo warnings preexistentes permitidos |
| `git diff --check` | 0 | limpio |

El consumer final
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó PASS en
1043.26 s y mostró progreso numérico intermedio. No se aplicó timeout.

## Archivos modificados

- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-driver/tests/invocable_capability_m3.rs`;
- `docs/architecture/INVOCABLE_CAPABILITY_M3_REPORT.md`.

No se modificaron ABI, runtime, Plots, LinearAlgebra, bibliotecas numéricas ni
ejemplos personales. No se hizo commit ni push.

Clasificación: **M3 CLOSED; INVOCABLE-CAPABILITY-V1 PARTIAL**.
