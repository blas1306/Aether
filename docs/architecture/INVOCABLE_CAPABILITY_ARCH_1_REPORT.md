# Aether — INVOCABLE-CAPABILITY-ARCH-1 — Report

Estado: **ARCHITECTURE CLOSED; IMPLEMENTATION NOT STARTED**, 2026-11-04.

Documento normativo:
[INVOCABLE_CAPABILITY_ARCH_1](INVOCABLE_CAPABILITY_ARCH_1.md).

## Resultado

Se convirtió la exploración de first-class callables en una arquitectura
normativa acotada para `INVOCABLE-CAPABILITY-V1`. No se modificaron compiler,
runtime, libraries, tests ni ejemplos.

La superficie cerrada es:

```aether
R apply<P, R, C: Invocable<(P), R>>(C f, P x) {
    return f(x);
}
```

`Invocable` es una constraint estructural, compiler-known y parametrizada por
firma exacta. No es un tipo de valor. V1 sólo admite `Function` y `Closure` de
la misma firma, con invocation read-only repetible.

## Decisiones cerradas

- spelling público `Invocable<(P...), R>`;
- uso exclusivo en generic constraints;
- firma canónica separada de `TypeData`;
- requirements parametrizados y evidence declaration-owned;
- aliases resueltos antes de canonicalización;
- equality invariante, sin conversions ni subtyping;
- inference exacta desde el carrier y sus argumentos;
- validación del body generic antes de monomorfización;
- `CapabilityInvoke` sólo en HIR generic;
- Function → `IndirectCall`;
- Closure → `ClosureBorrow` / `ClosureCall` / `EndClosureBorrow`;
- rechazo de todo residue antes de MIR;
- preservación de may-unwind y de identidad call/event;
- primer vertical by-value; `ref C` separado.

## Hallazgo técnico determinante

El modelo actual no puede representar correctamente `Invocable` como otro
valor del enum `Capability`: ese enum es atómico y `Copy`, mientras la nueva
constraint contiene `TypeId` sustituibles. El AST actual también conserva sólo
un nombre y `GenericParamInfo` usa `BTreeSet<Capability>`.

La arquitectura introduce conceptualmente:

```text
GenericRequirement = Atomic(Capability) | Invocable(CallableSignatureId)
```

con una tabla canónica de firmas y evidencia ligada a declaración, binder y
ordinal. No se agrega `TypeData::Invocable`, layout, ABI o runtime carrier.

## Ownership

La frontera by-value queda definida así:

| C concreto | Entrada | Invocation | Cleanup |
|---|---|---|---|
| Function | copia de pointer | `IndirectCall` | ninguno |
| Closure fresh | Transfer | borrow/call/end | release si sigue vivo |
| Closure lvalue | Alias/retain | borrow/call/end | release |
| Closure moved | Transfer | borrow/call/end | release |

`Invocable` no implica Copy, Alias, Storable o Relocatable. El body puede
invocar repetidamente, transferir el root y retornar `C`; no puede duplicarlo,
aliasarlo, almacenarlo ni operar aritméticamente sin constraints adicionales.

La diferencia de Drop entre Function y Closure se preserva mediante una
obligación root simbólica en HIR generic. La especialización elimina el drop de
Function o materializa el release exacto de Closure en success, early return y
unwind. Un tipo simbólico desconocido no puede tratarse como no-drop.

## Exceptions e IR

`CapabilityInvoke` conserva callee type, firma, requirement, evidence,
argumentos, resultado, `RepeatableRead`, `MayUnwind`, source span y
`CallSiteId`. La especialización mantiene el mismo site; MIR deriva un único
`ExceptionEventId` y preserva el evento por cleanup/catch/resume/finally.

Se exige una matriz de corruption que altere independientemente evidence,
binder, firma, argumentos, resultado, kind de dispatch, borrow token, cleanup y
evento excepcional. MIR/SSA/LLVM no pueden contener `CapabilityInvoke`,
evidence ni generic params residuales.

## Qualification

La matriz normativa exige O0/O2 para:

- Function top-level y lambda sin captura;
- closures con capturas Copy, Alias y Move;
- invocation repetida;
- cero, uno y varios parámetros; retorno void;
- firma generic con `T` y múltiples callables independientes;
- función generic importada;
- exceptions, early return y cleanup;
- retorno de `C` y use-after-move;
- operaciones no autorizadas y todos los signature mismatches;
- corrupción HIR/especialización/MIR/SSA;
- ausencia residual y conteos ARC/allocation.

El consumer pequeño propuesto es integración numérica por rectángulos dentro
de fixtures. `plots` no se migra en este vertical.

## Riesgos cerrados o acotados

- No se confunde invocabilidad con properties de storage.
- No hay evidence basada sólo en spelling.
- Dispatch se selecciona desde `TypeData` concreto, no desde metadata confiada.
- No se pierde cleanup de Closure en un body generic.
- No cambia Function ABI, ClosureABI-v1 ni el runtime.
- La promesa de coste se limita a cero adapter/allocation nuevos; no elimina
  allocation propia de Closure, ARC de boundary ni indirect dispatch.
- Code size por combinaciones de tipos se mide bajo los límites actuales de
  monomorfización.

## Milestones

1. parser y metadata parametrizada;
2. satisfaction, substitution e inference;
3. generic HIR, evidence y ownership simbólico;
4. rewriting y frontera pre-MIR;
5. qualification O0/O2 y report de implementación;
6. después de V1, `ref C` y sólo luego evaluar migraciones/erasure.

## Cambios realizados

Sólo se crearon:

- `docs/architecture/INVOCABLE_CAPABILITY_ARCH_1.md`;
- `docs/architecture/INVOCABLE_CAPABILITY_ARCH_1_REPORT.md`.

Se preservaron los documentos de exploración existentes y todos los cambios
ajenos. No se hizo commit ni push.

Clasificación: **ARCHITECTURE CLOSED; IMPLEMENTATION NOT STARTED**.
