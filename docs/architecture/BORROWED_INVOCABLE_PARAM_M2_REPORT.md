# Aether — BORROWED-INVOCABLE-PARAM-V1 — M2 Report

## Estado

**M2: CLOSED.**

Actualización 2026-11-15: M3 quedó CLOSED y la feature completa es
**BORROWED-INVOCABLE-PARAM-V1 CLOSED**. El párrafo siguiente conserva el estado
histórico al cierre de M2; ver `BORROWED_INVOCABLE_PARAM_M3_REPORT.md`.

`BORROWED-INVOCABLE-PARAM-V1` permanece **PARTIAL** hasta completar M3. M3 no
se inició en este trabajo.

## Preflight y frontera

El preflight confirmó que M0 y M1 estaban presentes como cambios locales sin
commit. Esos cambios y los archivos ajenos no se revirtieron ni sobrescribieron.

MIR ya podía representar el carrier requerido mediante
`PlaceBase::Dereference { reference, mutable: false }`; SSA conserva la misma
forma mediante `SsaPlaceBase::Dereference`. No fue necesario agregar ABI,
runtime helper, owner intermedio, thunk ni operación IR nueva.

El único rechazo productivo de M1 estaba en el lowering de
`ClosureCarrier::BorrowedPlace`. M2 lo reemplaza por `lower_place(place)` y
mantiene intacta la rama `OwnedLocal`.

## Lowering MIR/SSA

Una especialización Closure borrowed baja al protocolo Closure existente:

```text
ClosureBorrow(call_site, *parameter, Closure<S>)
arguments left-to-right
ClosureCall(call_site, *parameter, token, arguments, Closure<S>)
EndClosureBorrow(call_site, *parameter, token)
```

El mismo `Place` dereferenciado, `CallSiteId`, firma y token se conservan en
las tres operaciones. La evaluación del carrier ocurre una sola vez. El
landing pad existente enumera los borrows Closure activos y emite
`EndClosureBorrow` antes de limpiar owners del frame.

No se emite `ClosureAlias`, `Load` owning, `Move`, `Transfer`, `Drop` del
parámetro reference, retain/release de frontera ni owner temporal.

La ruta Function sigue siendo `Load(*f)` Copy seguido de `IndirectCall`; su
ABI de un code pointer no cambió.

## Borrow nesting, temporaries y ownership

Los dos niveles usan el ledger existente:

1. el caller abre el `CallScopedSharedBorrow` exterior sobre el argumento;
2. cada invocación Closure abre un `ClosureBorrow` interior independiente;
3. success y unwind cierran primero el token interior;
4. al salir del frame, el caller cierra el borrow exterior;
5. sólo entonces destruye el temporary owning, cuando existe.

Repeated invocation produce tokens interiores distintos. La prueba productiva
usa dos invocaciones dentro de la instancia borrowed y vuelve a usar el owner
Closure después del retorno. También cubre un Closure fresh: el root completo
se publica antes del borrow exterior y se destruye después de `EndBorrow`.

La calificación de Copy/Alias/Move captures continúa cubierta por
`owning_closures_read_v1` e `invocable_capability_m3`; M2 no altera la
construcción transaccional ni la publicación de closures.

## Excepciones

M2 reutiliza sin adaptación el `ExceptionEventId` y los landing pads
existentes. No crea un evento excepcional adicional. Se calificaron en O0 y
O2:

- throw desde Function borrowed;
- throw durante los argumentos de una `ClosureCall` después del borrow
  interior;
- catch en la función borrowed y segunda invocación;
- catch en el caller;
- rethrow;
- finally.

El orden observado/reconstruido es:

```text
EndClosureBorrow interior
cleanup del frame
EndBorrow exterior en el caller
cleanup del temporary del caller
handling o propagación del mismo evento
```

`ResumeUnwind`, `ForwardUnwind`, early return y nounwind de destroy/release
siguen cubiertos por las suites Exceptions V1–V4 y Owning Closures.

## Verificación MIR independiente

El verificador MIR ahora reconstruye para un carrier Closure dereferenciado:

- que la reference es exactamente un parámetro de la instancia;
- que es shared, sin proyecciones;
- que su pointee es exactamente la firma `Closure<S>`;
- que `ClosureBorrow`, `ClosureCall` y todos los `EndClosureBorrow` comparten
  carrier, site y token;
- que la call usa un token activo (no cerrado prematuramente);
- que load owning, `ClosureAlias`, Move, Drop y Replace no invalidan/fabrican
  ownership durante la región;
- que cada salida no abortiva cierra el token.

Para Function borrowed, MIR reconstruye el `Load` Copy desde un parámetro
`ref Function<S>` shared y exige que el code pointer tenga un único uso como
callee de un `IndirectCall` de firma exacta.

## Verificación SSA independiente

SSA repite la reconstrucción desde su propio CFG, definiciones, parámetros,
tipos y Places. No confía en metadata HIR/MIR para autorizar:

- provenance del parámetro shared y pointee exacto;
- token único, no escapado por phi y activo al ejecutar la call;
- ausencia de Store/Move/Replace/Drop/Load owning/ClosureAlias sobre el
  carrier protegido;
- terminación de todos los tokens antes de exits no abortivos;
- `Load(*f)` Function con un único uso `IndirectCall` exacto.

Los verificadores preexistentes mantienen dominancia, may-unwind,
`ExceptionEventId`, resultados sólo en success, cleanup de owners y ledger de
borrows exteriores.

## Corruption tests

`borrowed_invocable_param_m2.rs` construye MIR/SSA directamente, adultera la
capacidad del carrier borrowed a mutable y confirma rechazo independiente en
ambas fases. Las suites directas de Owning Closures y Borrow Ergonomics siguen
cubriendo missing/duplicate/premature begin/end, token incorrecto, escape por
phi, Move/Replace/Drop/Store, cleanup prematuro y corrupción de unwind/event.

Además, los verificadores añadidos rechazan estructuralmente carrier de otro
root, referencia no parámetro, pointee/firma incorrectos, owner load ficticio,
`ClosureAlias`, token cerrado antes de call y code pointer Function escapado.

## Qualification O0/O2 y costo

La suite M2 ejecuta en O0 y O2:

- Function borrowed lvalue;
- Closure borrowed lvalue;
- Closure fresh;
- repeated invocation;
- reutilización del owner después de la llamada;
- throws, catch, segunda invocation, rethrow y finally.

Resultados: 4/4 tests M2 PASS. El LLVM no contiene
`BorrowedCapabilityInvoke`, `CapabilityInvoke` ni adapter thunk.

El cruce `ref C` agrega **0 retain, 0 release y 0 allocations**: MIR/SSA no
contienen una operación capaz de producirlos en esa frontera. La creación y
destrucción del owner fresh permanece exactamente en el caller y conserva los
contadores cerrados de Owning Closures.

## Regresiones y gates

Entorno: `CARGO_INCREMENTAL=0`,
`TMPDIR=/tmp/aether-borrowed-invocable-m2`, directorio creado y escribible.

| Comando | Exit | Resultado |
|---|---:|---|
| `cargo test -p aether-frontend borrowed_invocable -j 1` | 0 | 5 passed |
| suites focales driver M2, Invocable M3/M4, Function Values, Anonymous Functions, Owning Closures, inference, Borrow Ergonomics y Exceptions V1–V4 | 0 | 104 passed |
| `cargo check --workspace` | 0 | PASS |
| `cargo test --workspace -j 1` | 0 | 1029 tests passed; doc-tests PASS |
| `cargo fmt --all --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets -j 1` | 0 | PASS; warnings históricos no promovidos a error |
| `git diff --check` | 0 | PASS |

El test largo
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó normalmente:
PASS en 1070.21 s. No se aplicó timeout.

## Archivos M2

- `compiler-next/crates/aether-middle/src/mir.rs`;
- `compiler-next/crates/aether-middle/src/ssa.rs`;
- `compiler-next/crates/aether-driver/tests/borrowed_invocable_param_m2.rs`;
- `docs/architecture/BORROWED_INVOCABLE_PARAM_M2_REPORT.md`.

Los cambios frontend visibles en el worktree pertenecen a M0/M1 y se
preservaron.

## Límites pendientes

M2 no agrega Callable owning, CallableRef, type erasure, `ref mut C`, generic
lambdas, closures mutables/consuming, auto-deref general, storage heterogéneo,
ABI/runtime helpers ni capabilities públicas. M3 permanece pendiente según el
contrato de `BORROWED-INVOCABLE-PARAM-V1`.
