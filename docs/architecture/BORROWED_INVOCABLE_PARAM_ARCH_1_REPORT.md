# Aether — BORROWED-INVOCABLE-PARAM-V1 — Architecture & Feasibility Report

Fecha: 2026-11-09.

Estado: **ARCHITECTURE CLOSED; IMPLEMENTATION CLOSED**, 2026-11-15.

M0–M3 quedaron cerrados. La matriz final, costes instrumentados, consumer
numérico y gates reproducibles constan en
`BORROWED_INVOCABLE_PARAM_M3_REPORT.md`.

Documento normativo:
[BORROWED_INVOCABLE_PARAM_ARCH_1.md](BORROWED_INVOCABLE_PARAM_ARCH_1.md).

No se implementó código productivo, no se modificaron tests/runtime/libraries y
no se hizo commit ni push.

## Resultado

La extensión es viable sin reabrir `INVOCABLE-CAPABILITY-V1` y sin modificar
Function ABI, ClosureABI-v1, exception ABI o runtime.

La superficie cerrada es:

```aether
R apply<P, R, C: Invocable<(P), R>>(ref C f, P x) {
    return f(x);
}
```

La capability pertenece exclusivamente a C. `ref C` es un acceso shared,
non-owning y no-escape al carrier. La entrada no copia Function, no hace
`ClosureAlias`, no retiene Closure, no transfiere C y no crea cleanup del
parámetro.

`ref Function` y `ref Closure` no se convierten en satisfiers de Invocable. La
inferencia retira exactamente la capa shared del patrón `ref C`, infiere el
pointee C y valida el requirement cerrado sobre ese C.

## Hallazgo de factibilidad

El pipeline contiene casi todas las piezas necesarias:

- borrow ergonomics ya materializa Places y fresh temporaries con cleanup
  normal/unwind;
- generic inference ya puede obtener U de un owner frente a `ref U`;
- Invocable V1 ya conserva requirement/evidence, firma y CallSiteId hasta la
  especialización;
- Function ya usa `IndirectCall` may-unwind;
- Closure ya usa `ClosureBorrow` / `ClosureCall` / `EndClosureBorrow` y MIR/SSA
  representan el carrier como Place;
- exception lowering ya preserva un evento por cleanup/catch/rethrow/finally.

La incompatibilidad concreta está en HIR: `ClosureCall` sólo acepta hoy un
carrier local owning. Cargar `*f` como Closure sería incorrecto porque
fabricaría un owner sin Alias/Transfer. La arquitectura resuelve la brecha con
un carrier discriminado `OwnedLocal | BorrowedPlace`; la ruta borrowed llega a
MIR como el Place dereferenciado que el protocolo existente ya puede expresar.
No es un bloqueo de ABI ni runtime.

## Ownership y lifetime cerrados

Hay dos borrows diferentes:

1. el caller presta el Function/Closure para toda la llamada a `apply`;
2. una especialización Closure abre además el borrow interno requerido por su
   invocation, desde antes de sus argumentos hasta success/unwind.

Para Function, la especialización carga el code pointer Copy desde el Place y
emite `IndirectCall`. Para Closure, conserva el Place y emite el protocolo
Closure existente. Ninguna ruta crea ARC por invocation.

Un Closure lvalue cruza la frontera con delta cero de retain/release. Un fresh
se transfiere a un temporary owner del caller, se presta y se destruye después
de cerrar el borrow; la allocation/release intrínsecos del fresh no son coste
de adaptación.

El borrow comienza al evaluar/materializar el argumento y cubre todos los
argumentos posteriores. Move, replacement, Drop o invalidación del root durante
ese intervalo se rechazan. Dentro del body también se rechazan owner load,
Move, Drop, assignment, return C, Alias, retain y storage desde `*f`.

El parámetro no genera `GenericOwnerObligation`: el caller conserva ownership y
ejecuta todo cleanup normal, early-return o excepcional que corresponda.

## Exceptions

Function y Closure permanecen may-unwind. Throws durante argumentos exteriores
cierran el borrow de frontera y limpian sólo temporaries ya publicados. Throws
durante argumentos de Closure o durante `ClosureCall` cierran primero el borrow
interior. Al salir de `apply`, el caller cierra el borrow exterior y después
destruye su temporary.

El `CallSiteId` de la call exterior y el de `f(...)` son distintos. Cada frame
conserva el `ExceptionEventId` de su landing pad/handler; al propagar entre
frames se transporta el mismo record excepcional y ningún cleanup crea,
sustituye o duplica un evento. No existe un evento de adaptación.

## IR y verificación

HIR generic agrega `BorrowedCapabilityInvoke`, con:

- carrier Place de tipo C bajo una dereference shared `ref C`;
- evidence y satisfaction ligadas a C;
- firma exacta, `RepeatableRead`, `MayUnwind` y CallSiteId.

Se mantiene separado del `CapabilityInvoke` by-value CLOSED. Especialización:

```text
ref Function<S> -> load Copy del Place -> IndirectCall
ref Closure<S>  -> ClosureCall(BorrowedPlace) -> protocolo Closure existente
```

MIR y SSA rechazan residuos generic/evidence, owner inventado, ARC/Drop del
parámetro, escape del reference, carrier invalidado, tokens faltantes o
duplicados y eventos alterados. Cada verifier reconstruye el contrato sin
confiar en la fase anterior.

## Qualification requerida

La implementación no puede cerrarse sin O0/O2, dumps y corruption tests para:

- Function/Closure lvalue y fresh;
- invocation repetida, branches, loops y early return;
- cero ARC adicional en frontera y por invocation;
- cero allocation o adapter thunk de adaptación;
- lifetime y cleanup de temporaries;
- throws en argumentos exteriores/interiores y en invocation;
- catch interno/externo, rethrow y finally;
- generic imports y forwarding;
- ausencia de residuos en MIR/SSA/LLVM;
- rechazo de escape, storage, Move, Drop, replacement, ref mut y satisfaction
  falsa de reference types.

El consumer normativo es una integración por rectángulos pequeña que recibe
`ref C`, ejecutada con Function y Closure lvalue/fresh, con tolerancia numérica,
conteo de invocaciones y contadores ARC/allocation.

## Riesgos

Los principales riesgos son confundir la capability de C con una de `ref C`,
cargar Closure como owner, fusionar los dos borrows, acortar la lifetime de un
fresh, agregar retain defensivo y perder el evento al recorrer dos regiones de
cleanup. El documento normativo asigna un verifier y corruption test específico
a cada riesgo.

## Milestones

1. M0: typing, inference y `BorrowedCapabilityInvoke` generic verificado;
2. M1: especialización Function/Closure y HIR concreto;
3. M2: MIR/SSA, lifecycle, temporaries y exceptions;
4. M3: qualification O0/O2, coste, imports, consumer y workspace.

## Fronteras preservadas

Permanecen fuera callable owning/erased, CallableRef, `ref mut`, mutable o
consuming closures, generic lambdas, trait system general, storage heterogéneo,
migración de Plots, ABI nuevo y helpers runtime nuevos.

Veredicto: no existe incompatibilidad arquitectónica bloqueante. Los contratos
de ownership, lifetime y excepciones están completos, por lo que corresponde
**ARCHITECTURE CLOSED; IMPLEMENTATION CLOSED;
BORROWED-INVOCABLE-PARAM-V1 CLOSED**. La trazabilidad histórica de la propuesta
y de M0–M2 se conserva; M3 aporta la qualification final.
