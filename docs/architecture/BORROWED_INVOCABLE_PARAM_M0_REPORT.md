# Aether — BORROWED-INVOCABLE-PARAM-V1 — M0 Report

Estado: **M0 CLOSED**, 2026-11-09.

Actualización 2026-11-15: M1–M3 también están CLOSED y la feature completa es
**BORROWED-INVOCABLE-PARAM-V1 CLOSED**. Este reporte conserva el estado
histórico observado al terminar M0; ver `BORROWED_INVOCABLE_PARAM_M3_REPORT.md`.

Estado de la feature completa: **BORROWED-INVOCABLE-PARAM-V1 PARTIAL**. M1,
M2 y M3 permanecen pendientes.

## 1. Alcance implementado

M0 admite exclusivamente invocation genérica a través de un parámetro de la
declaración actual cuyo tipo exacto sea shared `ref C` y cuyo binder pointee
posea evidence `C: Invocable<S>`:

```aether
R apply<P, R, C: Invocable<(P), R>>(ref C f, P x) {
    return f(x);
}
```

No se agregó satisfaction para tipos reference, autodereference general,
`ref mut C`, widening de firmas ni dispatch concreto borrowed.

## 2. Typing e inference

El analyzer reconoce `f(args)` como borrowed invocation sólo cuando:

- `f` resuelve a un source parameter de la función actual;
- el tipo declarado es exactamente una reference shared de una capa;
- el pointee es un `GenericParamId` perteneciente a la declaración;
- ese binder posee un único requirement `Invocable` parametrizado;
- aridad, argumentos y resultado coinciden exactamente, sin `Coerce`.

La evidence, el requirement y la satisfaction continúan perteneciendo a `C`,
no a `ref C`. La invocation se construye como `RepeatableRead` y
`MayUnwind`.

La inferencia reutiliza el mecanismo vigente para patrones `ref U`: un Place
owner o fresh owner de tipo Function/Closure infiere primero el pointee y la
firma, valida `Invocable` sobre ese pointee y sólo entonces materializa el
borrow de call. Los tests cubren Function lvalue, Closure lvalue, fresh Closure,
forwarding de un descriptor `ref C` y el rechazo de intentar satisfacer la
constraint con `ref Function`.

## 3. Generic HIR

Se agregó la variante boxed `BorrowedCapabilityInvoke`:

```text
BorrowedCapabilityInvoke {
    carrier: HirPlace,
    reference_type: TypeId,
    carrier_type: TypeId,
    arguments: Vec<HirExpr>,
    result_type: TypeId,
    requirement: GenericRequirementId,
    evidence: ConstraintEvidenceId,
    required_signature: CallableSignatureId,
    satisfaction: SatisfactionEvidence,
    mode: RepeatableRead,
    effect: MayUnwind,
    call_site: CallSiteId,
    provenance: Span,
}
```

`carrier` es el Place de tipo `C` formado por una única
`Dereference(Local(f), mutable=false)`. No contiene `Load`, Move, Alias,
Transfer, retain ni adquisición de owner. La variante está boxed para conservar
la indirection de los nodos recursivos de HIR.

El análisis de ownership visita el Place y los argumentos en orden, registra el
edge unwind por `CallSiteId` y no crea cleanup ni obligación owning para el
parámetro reference. Las invocaciones repetidas conservan el mismo descriptor
read-only.

## 4. Verificación independiente

`verify_hir` reconstruye y comprueba independientemente:

- que el root sea un parámetro source de la declaración actual;
- que su tipo declarado sea exactamente shared `ref C`;
- que el carrier tenga una única dereference, ninguna proyección y tipo `C`;
- que `C` sea el binder exacto y declaration-owned;
- que requirement, evidence y satisfaction pertenezcan a `C` y coincidan;
- que la firma, aridad, argumentos y resultado sean exactos;
- `RepeatableRead`, `MayUnwind`, provenance y `CallSiteId`;
- que el nodo exista sólo en HIR paramétrico.

Además, el verificador rechaza un `Load` owning o un nuevo `Borrow`/alias del
pointee de un parámetro borrowed Invocable. El ledger genérico reconstruido no
admite una `GenericOwnerObligation` para `f: ref C`; el sintetizador de
ownership detecta CallSite duplicado y divergencias de unwind/cleanup.

## 5. Ownership y negativos

Los tests de fuente rechazan:

- invocation through `ref mut C`;
- extracción de `C` mediante `*f`;
- assignment/replacement through shared `*f`;
- return/escape del descriptor reference;
- captura del reference por una Closure.

Los contratos existentes continúan rechazando storage, Drop, Move/Transfer,
partial move y adquisición owning desde una shared reference. No se agregó
`GenericOwnerObligation` para el parámetro borrowed.

## 6. Corruption tests

Se construye y muta HIR directamente para comprobar rechazo determinista de:

- evidence atribuida a otro binder;
- satisfaction de otro binder;
- requirement de otra declaración;
- dereference mutable;
- carrier rooted en otro parámetro;
- pointee/carrier type incorrecto;
- reference type incorrecto o con capa adicional;
- firma, aridad o resultado adulterados;
- modo consuming;
- eliminación de `MayUnwind`;
- provenance adulterada;
- `GenericOwnerObligation` inventada;
- owner load inventado;
- `CallSiteId` duplicado.

Los tests negativos de fuente cubren además Move/load, replacement, escape y
captura del reference.

## 7. Frontera M0/M1

La monomorfización rechaza explícitamente todo
`BorrowedCapabilityInvoke` con `E0476`:

```text
BORROWED-INVOCABLE-PARAM-V1 specialization requires M1;
BorrowedCapabilityInvoke cannot cross the M0 HIR boundary
```

MIR conserva una defensa residual `unreachable!`. M0 no emite `IndirectCall`,
`ClosureCall`, nuevos helpers, nuevos ABIs ni `ClosureCarrier::BorrowedPlace`.

## 8. Qualification

Entorno global:

- `TMPDIR=/tmp/aether-borrowed-invocable-m0`, verificado escribible: exit 0.
- `CARGO_BUILD_JOBS=1` en los gates de tests.

Resultados:

- `cargo test -p aether-frontend borrowed_invocable_m0 -- --nocapture`: exit 0,
  4 passed.
- `cargo test -p aether-frontend`: exit 0, 97 passed.
- suite focal driver de Invocable M3/M4, generic inference ref, borrow
  ergonomics, Function Values, Owning Closures, ownership y Exceptions V1–V4:
  exit 0, 84 passed.
- `cargo check --workspace`: exit 0.
- `cargo fmt --all -- --check`: exit 0.
- `git diff --check`: exit 0.
- `cargo clippy --workspace --all-targets`: exit 0. Clippy reportó warnings
  preexistentes del workspace; no se modificaron fuera del alcance.
- prueba adicional `cargo clippy ... -- -D warnings`: exit 101 por warnings del
  workspace ya presentes, incluido `assert_is_empty`, `large_enum_variant` y
  `needless_borrows_for_generic_args`; no es el gate Clippy canónico anterior.
- `TMPDIR=... CARGO_BUILD_JOBS=1 cargo test --workspace`: exit 0, corrida
  completa. No se canceló el test largo de registry;
  `linear_algebra_oal_publishes_and_runs_real_qr_consumer` pasó en 1018.61 s.

## 9. Archivos modificados por M0

- `compiler-next/crates/aether-frontend/src/hir.rs`
- `compiler-next/crates/aether-frontend/src/hir/classes.rs`
- `compiler-next/crates/aether-frontend/src/lib.rs`
- `compiler-next/crates/aether-middle/src/mir.rs`
- `docs/architecture/BORROWED_INVOCABLE_PARAM_M0_REPORT.md`

Los documentos `BORROWED_INVOCABLE_PARAM_ARCH_1.md` y
`BORROWED_INVOCABLE_PARAM_ARCH_1_REPORT.md` ya estaban presentes como archivos
untracked durante el preflight y no fueron modificados por M0.

## 10. Cierre

Todos los gates canónicos de M0 terminaron con exit 0. Por tanto, **M0 queda
CLOSED**. La feature **BORROWED-INVOCABLE-PARAM-V1 permanece PARTIAL** hasta
implementar y calificar M1–M3.
