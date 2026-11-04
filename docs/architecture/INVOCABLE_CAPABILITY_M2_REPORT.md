# Aether — INVOCABLE-CAPABILITY-V1 — M2 Final Qualification

Fecha: 2026-11-04.

Estado: **M2 CLOSED; INVOCABLE-CAPABILITY-V1 PARTIAL**.

M0 y M1 permanecen CLOSED. M3 (rewriting Function/Closure) y M4 (ejecución
end-to-end) no se implementaron.

## Resultado

El frontend construye y verifica `CapabilityInvoke` proof-carrying en HIR
genérico antes de conocer una especialización. La operación conserva el
callee y su `TypeId` generic, argumentos y resultado exactos, requirement,
evidence declaration-owned, firma canónica, satisfaction simbólica,
`RepeatableRead`, `MayUnwind`, `CallSiteId` y provenance source.

El payload está boxed para que agregar la prueba no aumente el tamaño de cada
`HirExpr` recursivo. Esto mantiene estable la profundidad práctica de análisis
de bodies numéricos grandes; la qualification incluye el caso que detectaría
una regresión de stack.

El body genérico puede invocar un carrier cero o más veces. La invocation es
una observación y no una lectura by-value: no consume, copia ni crea alias del
carrier. Una lectura ordinaria conserva la semántica `Move` existente.

## Ownership simbólico

Cada root parameter by-value cuyo tipo aún contiene un generic no-Copy queda
registrado como `GenericOwnerObligation { root, ty, state, source }`. El ledger
ordinario existente sigue siendo la autoridad path-local:

- `Move` representa transfer e invalida el source;
- `HirDrop::{Unconditional, Conditional}` representa cleanup normal, return
  temprano, throw y demás transfers de control;
- `GenericUnwindObligation` asocia cada `CapabilityInvoke` may-unwind con los
  owners vivos, en orden inverso de adquisición.

`TypeProperties` desconocidas ya son conservadoras (`is_known=false`,
`needs_drop=true`); M2 no las reinterpreta como no-drop. Por ello un carrier no
usado conserva cleanup simbólico, un carrier retornado se transfiere sin drop,
y una invocation repetida mantiene el root vivo.

## Verificación independiente

`verify_hir` reconstruye y compara:

- declaration, binder, requirement, evidence y firma;
- callee type, aridad, argumentos y resultado exactos;
- satisfaction simbólica;
- `RepeatableRead`, `MayUnwind`, provenance y `CallSiteId` único;
- estado owning, moves, cleanup de exits y cleanup excepcional;
- ledger completo de roots genéricos.

La reconstrucción vuelve a ejecutar el transfer function sobre una copia del
body. HIR construido directamente no puede omitir, duplicar o cambiar el tipo
de cleanup, perder un root, invocar un moved root ni borrar una exceptional
edge.

Los corruption tests cubren evidence inexistente, evidence de otra
declaración y binder, requirement atómico, firma/callee/arity/argument/result
adulterados, mode y effect inválidos, provenance, site duplicado, moved root,
owner duplicado, transfer sin invalidación y cleanup perdido o inventado en
return, early return y unwind.

## Frontera productiva

Un generic no instanciado puede completar análisis y `verify_hir` conservando
`CapabilityInvoke`. Si monomorfización intenta sustituir ese nodo, devuelve
E0475: `verified generic CapabilityInvoke reached the M2/M3 specialization
boundary`. El verifier rechaza un nodo residual en HIR concreto y MIR contiene
además un guard exhaustivo imposible de atravesar desde `TypedHir` verificado.

No se creó `FunctionRef`, `IndirectCall`, `ClosureBorrow`, `ClosureCall`, drop
concreto, ABI, helper ni runtime nuevo para un carrier genérico.

## Casos de ownership calificados

- invocation repetida conserva el carrier y dos exceptional cleanups;
- parámetro no usado conserva root y cleanup hasta el return;
- `return f` emite `Move`, transfiere y no limpia el source;
- early return limpia todo root vivo;
- may-unwind conserva site y cleanup simbólico;
- una segunda transferencia o invocation después de move reporta E0291;
- `Invocable` solo no autoriza aritmética, equality, storage, duplicación ni
  invocation through `ref C`;
- la adaptación implícita por coerción no satisface una firma exacta.

## Qualification

Entorno: `CARGO_INCREMENTAL=0`, `TMPDIR=/tmp/aether-invocable-m2`, comprobado
escribible; Cargo serial (`-j 1`).

| Comando | Exit | Resultado |
|---|---:|---|
| `cargo test -p aether-frontend -j 1` | 0 | 92 passed; doc-tests 0 |
| suites focales driver (generic inference, Function Values, Anonymous Functions, Owning Closures, ownership y Exceptions V1–V4) | 0 | 82 passed |
| `cargo check --workspace` | 0 | workspace completo compila |
| `cargo test --workspace -j 1` | 0 | 1007 passed, 0 failed, 0 ignored; 111 grupos; doc-tests de 7 crates PASS |
| `cargo fmt --all --check` | 0 | sin diferencias |
| `cargo clippy --workspace --all-targets -j 1` | 0 | sólo warnings preexistentes permitidos |
| `git diff --check` | 0 | limpio |

El consumer final
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó PASS en
985.30 s, ejecutando sus rutas O0/O2. No se aplicó timeout artificial y su
salida numérica intermedia mostró progreso antes de terminar.

Durante qualification se detectó inicialmente un stack overflow reproducible
en `numeric_capabilities_v1`: el primer layout inline de la nueva variante
aumentaba el frame de visitors recursivos. Se corrigió boxeando el payload,
se reprodujo el test aislado 3/3 PASS y luego se reinició desde cero la corrida
global que figura arriba. La corrida fallida no se contabilizó como PASS.

Clippy conserva warnings preexistentes de `large_enum_variant`,
`needless_borrows_for_generic_args`, `match_same_arms`, `assert_is_empty`,
`too_many_lines`, `single_match_else` y `manual_let_else`. M2 no agrega una
categoría nueva.

## Archivos modificados

- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-frontend/src/hir/classes.rs`;
- `compiler-next/crates/aether-frontend/src/lib.rs`;
- `compiler-next/crates/aether-middle/src/mir.rs`;
- `docs/architecture/INVOCABLE_CAPABILITY_ARCH_1.md`;
- `docs/architecture/INVOCABLE_CAPABILITY_ARCH_1_REPORT.md`;
- `docs/architecture/INVOCABLE_CAPABILITY_M2_REPORT.md`.

No se modificaron libraries, runtime, ABI, ejemplos personales ni Plots. No se
hizo commit ni push.

Clasificación: **M2 CLOSED; INVOCABLE-CAPABILITY-V1 PARTIAL**.
