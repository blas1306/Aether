# Aether — BORROWED-INVOCABLE-PARAM-V1 — M1 Concrete Specialization

Fecha: 2026-11-09.

Estado: **M1 CLOSED; BORROWED-INVOCABLE-PARAM-V1 permanece PARTIAL**.

Actualización 2026-11-15: M2/M3 quedaron CLOSED y la feature completa es
**BORROWED-INVOCABLE-PARAM-V1 CLOSED**. La línea anterior conserva el estado
histórico al cierre de M1; ver `BORROWED_INVOCABLE_PARAM_M3_REPORT.md`.

M0 permanece CLOSED. Este milestone no implementa M2 ni adelanta la
qualification integral de M3.

## Resultado

`BorrowedCapabilityInvoke` ya se especializa completamente en HIR concreto.
La selección se hace exclusivamente desde el `TypeData` concreto después de
sustituir y volver a validar binder, requirement, evidence, satisfaction y
firma canónica:

- `Function<S>` produce un `Load` Copy del code pointer desde el Place `*f` y
  un `IndirectCall` con el `CallSiteId` original;
- `Closure<S>` produce un `ClosureCall` cuyo carrier es el Place borrowed
  original, sin formar un owner.

No se modificaron Function ABI, Closure ABI, runtime, thunks ni libraries.

## Rewriting de Function

La especialización reconstruye el requirement `Invocable<S>` sobre `C`, no
sobre `ref C`, comprueba satisfacción exacta, sustituye argumentos y resultado,
y emite:

```text
IndirectCall {
    callee: Load(*f),
    signature: Function<S>,
    args,
    call_site: original,
}
```

`Function` conserva su semántica Copy. El Place se evalúa una vez; no aparece
owner, Drop, Alias, retain ni release. `BorrowedFunctionOrigin` conserva sólo
metadata concreta de integridad —parámetro canónico y site— para que el
verificador detecte provenance o evento adulterados. No transporta evidence
genérica a MIR.

## Rewriting de Closure

HIR concreto usa un carrier discriminado:

```text
ClosureCarrier =
    OwnedLocal(LocalId)
  | BorrowedPlace { place: HirPlace, parameter: LocalId, call_site: CallSiteId }
```

`OwnedLocal` preserva la semántica anterior de Owning Closures. La variante
borrowed conserva el Place dereferenciado de la referencia compartida, su
parámetro canónico y el site original. No emite `Load` owning,
`ClosureAlias`, retain, Move, Transfer, owner temporal ni Drop del parámetro.

Los recorridos de ownership y clases distinguen ambas variantes: el carrier
owned exige un local vivo; el borrowed sólo visita/verifica su Place.

## Provenance y verificación concreta

El monomorphizer ejecuta en orden:

1. valida binder y declaración dueña;
2. reconstruye requirement, evidence y satisfaction;
3. sustituye carrier, referencia, firma, argumentos y resultado;
4. comprueba `Invocable<S>` exactamente sobre el pointee concreto `C`;
5. selecciona Function o Closure desde `TypeData`;
6. reescribe conservando `CallSiteId` y semántica may-unwind inherente;
7. deja el HIR completo sujeto a `verify_hir`.

El verificador concreto exige para todo carrier borrowed:

- dereference compartido, sin projections;
- root que sea exactamente un parámetro source de la declaración;
- `ref Function<S>` o `ref Closure<S>` y pointee de firma exacta;
- identidad entre root y parámetro canónico retenido;
- identidad entre site de la call y site de origen;
- aridad, argumentos y resultado exactos;
- metadata de provenance presente en la ruta Function.

La verificación de completitud existente rechaza `GenericParam` residual y el
verificador paramétrico/concreto rechaza `BorrowedCapabilityInvoke` en HIR
concreto.

## Corruption tests

Los tests construyen o mutan IR directamente y cubren conjuntamente M0/M1:

- evidence de otra declaración o binder y requirement adulterado;
- firma, argumento, resultado, mode, `MayUnwind` y provenance genéricos;
- Function especializada como Closure y Closure especializada como Function;
- pointee o firma concreta incorrectos;
- mutable reference carrier;
- carrier cambiado a otro parámetro;
- parámetro/site de provenance adulterado o metadata Function eliminada;
- `Load` owning, `ClosureAlias`/retain semántico y Drop ficticios;
- `GenericParam` y `BorrowedCapabilityInvoke` residuales.

Los verificadores existentes siguen cubriendo site duplicado, cleanup y
ownership de Function Values, Owning Closures y calls may-unwind.

## Frontera M1/M2

Function puede bajar por el spine `IndirectCall` existente. La variante
`ClosureCarrier::BorrowedPlace` queda fail-closed en la frontera de lowering:
MIR sólo admite `OwnedLocal` hasta M2 y rechaza la variante borrowed antes de
crear `ClosureBorrow`.

M2 conserva íntegramente la responsabilidad de calificar e implementar el
Place dereferenciado en MIR/SSA, tokens `ClosureBorrow`/`EndClosureBorrow`,
two-level borrowing, temporaries, lifetime, excepciones y cleanup normal y
excepcional. M1 no declara ejecución productiva de Closure borrowed.

## Qualification

Entorno: `CARGO_INCREMENTAL=0`,
`TMPDIR=/tmp/aether-borrowed-invocable-m1`, directorio creado y escribible;
tests seriales cuando corresponde.

| Comando | Exit | Resultado |
|---|---:|---|
| `cargo test -p aether-frontend borrowed_invocable_m1 -j 1` | 0 | 2 passed |
| `cargo test -p aether-frontend -j 1` | 0 | 98 passed; doc-tests PASS |
| `cargo test -p aether-middle -j 1` | 0 | 29 passed; doc-tests PASS |
| suites focales Invocable M3/M4, Function Values, Owning Closures, inference, borrow, anonymous functions y Exceptions V1–V4 | 0 | todas PASS |
| `cargo check --workspace` | 0 | PASS |
| `cargo test --workspace -j 1` | 0 | corrida completa y doc-tests PASS |
| `cargo fmt --all --check` | 0 | sin diferencias |
| `cargo clippy --workspace --all-targets -j 1` | 0 | warnings preexistentes permitidos |
| `git diff --check` | 0 | limpio |

La corrida global dejó terminar normalmente
`linear_algebra_oal_publishes_and_runs_real_qr_consumer`: PASS en 960.04 s,
incluidos O0/O2. No se aplicó timeout artificial.

## Archivos modificados por M1

- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-frontend/src/hir/classes.rs`;
- `compiler-next/crates/aether-frontend/src/lib.rs`;
- `compiler-next/crates/aether-middle/src/mir.rs`;
- `docs/architecture/BORROWED_INVOCABLE_PARAM_M1_REPORT.md`.

Los documentos de arquitectura y el reporte M0 ya estaban presentes como
archivos untracked al iniciar M1 y se preservaron. No se hizo commit ni push.

## Cierre

Los contratos de especialización y verificación de HIR concreto de M1 están
completos y todos los gates ejecutados terminaron con exit 0. Por tanto,
**M1 queda CLOSED**. La feature **BORROWED-INVOCABLE-PARAM-V1 permanece
PARTIAL** hasta completar M2 y M3.
