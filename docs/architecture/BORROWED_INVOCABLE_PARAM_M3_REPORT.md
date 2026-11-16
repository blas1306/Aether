# Aether — BORROWED-INVOCABLE-PARAM-V1 — M3 Final Qualification Report

Fecha: 2026-11-15.

## Estado

**M3: CLOSED. BORROWED-INVOCABLE-PARAM-V1: CLOSED.**

M0, M1 y M2 permanecen CLOSED. La qualification final no encontró un defecto
productivo nuevo: las correcciones de M3 se limitaron a los fixtures y a esta
trazabilidad. Los contratos CLOSED de Function, Closure, Invocable, Borrow
Ergonomics y Exceptions no cambiaron.

## Preflight y criterio de coverage

El preflight encontró M0–M2 como cambios locales sin commit y dos ejemplos
personales no rastreados. Se preservaron todos esos cambios y no se modificaron
`examples/indices.ae`, `examples/svd.ae`, Plots ni linearAlgebra.

La qualification distinguió tres clases de evidencia:

- **directa BorrowedPlace**: los tests M0/M1/M2 y el nuevo
  `borrowed_invocable_param_m3.rs` atraviesan `ref C`, especialización concreta,
  carrier dereferenciado, MIR, SSA, LLVM y ejecución;
- **reutilizada Owning Closures**: construcción/publicación Copy/Alias/Move,
  cleanup transaccional, corrupción del protocolo Closure y lifecycle intrínseco;
- **reutilizada Borrow Ergonomics/Exceptions**: borrow exterior de call,
  temporaries, invalidación por argumentos posteriores, cleanup normal/unwind,
  `ExceptionEventId`, catch/rethrow/finally/`ResumeUnwind`.

Un test by-value u `OwnedLocal` no fue contado como prueba de la ruta
`BorrowedPlace`; sólo aporta evidencia de los contratos compartidos indicados.

## Matriz normativa

| Requisito | Test/evidencia | Clase | Resultado/gap |
|---|---|---|---|
| Function top-level lvalue | M2 runtime y matriz M3 | directa | PASS O0/O2 |
| Function fresh/lambda sin captura | `fire(()=>noop())` en matriz M3; Anonymous Functions V1 | directa + reutilizada | PASS O0/O2 |
| Closure lvalue Copy/Alias/Move | matriz M3 y `invocable_capability_m3` | directa | PASS O0/O2; owner reutilizado |
| Closure fresh Copy/Alias/Move | matriz M3 | directa | PASS O0/O2 |
| Cero/una/múltiples invocaciones | `repeat(...,0/2/3)`, `choose`, M2 `twice` | directa | PASS |
| Branch/loop/early return | `choose`, `repeat`; Borrow Ergonomics | directa + reutilizada | PASS |
| Aridad 0/1/múltiple y void | `fire`, `choose`, `invoke3` | directa | PASS O0/O2 |
| `Invocable<(P),P>` generic | `generic` y provider importado | directa | PASS |
| Dos binders F/G independientes | `combine` | directa | cuatro instancias exactas |
| FF/FC/CF/CC | matriz M3 | directa | cuatro combinaciones PASS O0/O2 |
| Forwarding de `ref C` | `forward` local y provider importado | directa | PASS O0/O2 |
| Generic import entre módulos | fixture `tests/modules/borrowed_invocable_param_m3` | directa | PASS O0/O2 |
| Owner después de la call | Copy/Alias/Move, coste borrowed y consumer numérico | directa | PASS |
| Borrow nesting y no-owner | test MIR/SSA M3 y M2 | directa | PASS |
| Captures y publicación transactional | Owning Closures Read V1 | reutilizada | 25 PASS focales |
| Argumento posterior/unwind/finally | M2 + Borrow Ergonomics + Exceptions V1–V4 | directa + reutilizada | PASS |
| Consumer de integración midpoint | `NUMERIC_INTEGRATION` M3 | directa | PASS O0/O2 |
| Coste direct/by-value/borrowed | contador runtime M3 | directa | PASS O0/O2 |
| Diagnósticos negativos | frontend M0/M1 y negativos M3 | directa | PASS |
| MIR/SSA corruption matrix | M2 + Owning Closures + Borrow Ergonomics + Exceptions | directa + reutilizada por autoridad | PASS |

No quedó un gap esencial abierto.

## Qualification funcional O0/O2

La nueva suite ejecuta una única matriz observable que combina:

- Function top-level, lambda sin captura, Closure lvalue y Closure fresh;
- captures Copy, Alias y Move;
- cero, una y múltiples invocaciones;
- branches, loop, retorno antes de invocar y retorno del resultado invocado;
- firmas de cero, uno y tres parámetros y retorno `void`;
- firma parametrizada `Invocable<(P),P>`;
- F/G independientes y FF/FC/CF/CC;
- forwarding local y transitivo entre módulos;
- uso posterior de cada owner lvalue.

HIR contiene cuatro instancias distintas de `combine`, con tipos concretos
Function/Function, Function/Closure, Closure/Function y Closure/Closure. LLVM
no contiene `BorrowedCapabilityInvoke`, `CapabilityInvoke` ni adapter thunk.

## Ownership, borrows y temporaries

La inspección directa MIR/SSA de la instancia Closure borrowed demuestra:

1. el parámetro es `ref Closure<S>` shared;
2. cada `ClosureBorrow`, `ClosureCall` y `EndClosureBorrow` usa exactamente el
   mismo `Dereference(parameter)`;
3. dos invocaciones producen dos regiones interiores independientes;
4. no aparece `ClosureAlias`, owner load, retain ni Drop del parámetro;
5. el owner lvalue sigue invocable al retornar;
6. el owner fresh se publica antes del borrow exterior y se destruye después
   de su `EndBorrow`.

M2 y las suites Borrow Ergonomics/Owning Closures verifican además que el
borrow exterior cubre toda la call, que el interior cubre argumentos y
`ClosureCall`, que el interior termina primero en success/unwind, y que Move,
Replace, Store, Drop o invalidación del root durante cualquiera de las regiones
se rechazan. Cleanup es exactamente una vez en retorno normal, early return y
unwind.

## Exceptions y unwind

La ruta BorrowedPlace se ejecutó directamente con:

- throw desde Function borrowed;
- throw durante argumentos interiores después de `ClosureBorrow`;
- catch dentro del callee y segunda invocation;
- catch exterior, rethrow y finally.

Owning Closures y Exceptions V1–V4 aportan la evidence compartida para
construcción incompleta, throw desde Closure, argumentos exteriores posteriores
al borrow, cleanup exactamente una vez, `ForwardUnwind` y `ResumeUnwind`.
Los verificadores MIR/SSA adulteran y rechazan evento, landing pad, resultado
en exceptional edge y metadatos de finally.

El orden efectivo permanece:

```text
EndClosureBorrow interior
cleanup del frame borrowed
EndBorrow exterior del caller
Drop del temporary caller, si existe
catch, rethrow, finally o ResumeUnwind del mismo evento
```

No se crea otro `CallSiteId` ni `ExceptionEventId` para la adaptación.

## Corruption matrix MIR/SSA

La cobertura se construye o muta directamente en la representación cuya
autoridad debe rechazar; no depende sólo de una fase anterior.

| Corrupción | Evidencia independiente |
|---|---|
| Evidence/binder/ordinal/provenance falsos | frontend `borrowed_invocable_m0_corruptions_fail_closed` |
| Reference mutable, capa/tipo/pointee incorrectos | frontend M0/M1 + M2 MIR/SSA |
| Carrier de otro parámetro/root | frontend M1; verificadores MIR/SSA de provenance |
| Firma/args/result adulterados | frontend M0/M1 y verificadores Closure |
| Missing/duplicate/premature ClosureBorrow/End | Owning Closures MIR/SSA corruption tests, aplicables al carrier Place |
| Token intercambiado/cerrado temprano/phi escape | Owning Closures MIR/SSA + verificador BorrowedPlace M2 |
| End ausente en unwind | Owning Closures unwind y Exceptions corruption tests |
| EndBorrow exterior prematuro/temporary Drop temprano | Borrow Ergonomics MIR/SSA corruption test |
| Move/Replace/Store/Drop durante borrow | Owning Closures + Borrow Ergonomics; M2 reconstruye el carrier dereferenciado |
| Owner load/ClosureAlias/ARC inventado | frontend M1 y verificadores MIR/SSA borrowed |
| Drop del parámetro `ref C` | frontend M1 y ledgers MIR/SSA |
| Event adulterado/resultado exceptional | Exceptions V1–V4 MIR/SSA |
| Generic/evidence residual | frontend M1 y fronteras MIR/SSA |

La nueva prueba M3 vuelve a comprobar sobre `BorrowedPlace` real que MIR y SSA
conservan el mismo parámetro dereferenciado y no contienen `ClosureAlias` ni
Drop del parámetro. M2 conserva la corrupción directa de mutabilidad en MIR y
SSA. La semántica común de tokens y CFG no discrimina `OwnedLocal` contra
`BorrowedPlace`; recibe el `Place` real y se volvió a ejecutar dentro del gate.

## Comparación de costes instrumentada

Se midieron tres programas equivalentes, cada uno con una Closure capturante,
dos invocaciones y resultado observable 42. Los contadores se leen después del
cleanup de `main`.

| Escenario | Retain | Release | Destroy | Heap alloc | Heap free | Invocaciones | Adapter/thunk extra |
|---|---:|---:|---:|---:|---:|---:|---:|
| Closure lvalue directa | 0 | 1 | 1 | 1 | 1 | 2 | 0 |
| Generic by-value Invocable | 1 | 2 | 1 | 1 | 1 | 2 | 0 |
| Generic borrowed `ref C` | 0 | 1 | 1 | 1 | 1 | 2 | 0 |

Los mismos valores pasaron bajo O0 y O2. La allocation, el destroy y el release
final pertenecen a crear y destruir la Closure intrínseca. El único delta de
frontera by-value es adquirir/liberar un owner adicional. El delta de frontera
borrowed lvalue es **0 retain, 0 release, 0 allocation/free** y cada invocation
agrega **0 ARC**. Esto es una conclusión limitada a los consumers medidos y al
contrato estructural verificado; no se declara zero-cost universal.

## Consumer numérico

El fixture implementa exactamente:

```aether
float64 integrate<C:Invocable<(float64),float64>>(
    ref C f, float64 a, float64 b, usize n
)
```

Se ejecutó con Function lvalue, Closure capturante lvalue y Closure capturante
fresh, con `n = 100`. La regla de punto medio para `x²` en `[0,1]` se calculó
independientemente como `1/3 - 1/(12*n²) = 0.333325`; la tolerancia `1e-12`
supera holgadamente el error de redondeo observado y es muy inferior al error
de discretización. El consumer lineal esperado es exactamente `1.0`.

Cada llamada realiza exactamente `n` evaluaciones porque el loop inicia en
cero, incrementa una vez por iteración y su condición es `i < n`; MIR/SSA
conservan una única `ClosureCall` dinámica dentro del loop. La lvalue se invoca
otra vez después del consumer. Los contadores para las dos Closures son:
`0 retain, 2 release, 2 destroy, 2 alloc, 2 free`; no hay coste de adaptación.

## Diagnósticos negativos

La suite directa y el frontend M0/M1 rechazan:

- non-callable y firma incompatible;
- `ref mut C`, referencia de capa adicional y carrier/pointee incorrecto;
- satisfaction falsa de `ref Function`/`ref Closure`;
- retorno, captura o storage de `ref C`;
- owner C fabricado desde `*f`;
- assignment/replacement, Move, Drop, Alias o retain del pointee;
- invalidación por argumento posterior;
- operaciones genéricas sólo legales para Function Copy o Closure Alias.

La capability sigue perteneciendo a C; `ref C` es sólo el acceso borrowed.

## Regresiones y gates

Entorno canónico: `CARGO_INCREMENTAL=0`,
`TMPDIR=/tmp/aether-borrowed-invocable-m3`, creado y comprobado escribible.

| Comando | Exit | Resultado |
|---|---:|---|
| frontend borrowed focal | 0 | 5 passed |
| M2 | 0 | 4 passed |
| M3 | 0 | 6 passed |
| focales Invocable, Function, Anonymous, Closures, inference, Borrow y Exceptions | 0 | 92 passed adicionales; 107 focales totales |
| `cargo check --workspace` | 0 | PASS |
| `cargo test --workspace -j 1` | 0 | 1035 tests PASS; doc-tests PASS |
| `cargo fmt --all --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets -j 1` | 0 | PASS; warnings históricos no promovidos a error |
| `git diff --check` | 0 | PASS |

`linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó normalmente
en **1037.33 s**. No se usó timeout ni se interpretó el silencio como bloqueo.

## Archivos M3

- `compiler-next/crates/aether-driver/tests/borrowed_invocable_param_m3.rs`;
- `compiler-next/tests/modules/borrowed_invocable_param_m3/provider.ae`;
- `compiler-next/tests/modules/borrowed_invocable_param_m3/main.ae`;
- `docs/architecture/BORROWED_INVOCABLE_PARAM_M3_REPORT.md`;
- actualizaciones de estado en la arquitectura y reportes M0–M2.

Los archivos productivos visibles en el worktree corresponden a M0–M2. M3 no
los alteró y no modificó ejemplos personales.

## Defectos y límites

No se reprodujo ningún defecto productivo de Borrowed Invocable durante M3.
Los ajustes realizados fueron exclusivamente de fixtures de qualification.

Quedan fuera de scope Callable owning, CallableRef, type erasure, `ref mut C`,
auto-deref general, generic lambdas, closures mutables/consuming, nuevas
capabilities/ABIs/helpers, storage heterogéneo y migraciones de Plots o
linearAlgebra.

## Cierre

Toda la matriz normativa esencial, O0/O2, ownership, temporaries, exceptions,
corruption, costes instrumentados, imports/forwarding, consumer numérico y
gates canónicos quedó demostrada.

**BORROWED-INVOCABLE-PARAM-V1 CLOSED.**
