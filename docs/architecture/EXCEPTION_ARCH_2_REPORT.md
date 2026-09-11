# EXCEPTION-ARCH-2 — reporte de decisión

Estado: **ARQUITECTURA DISEÑADA; SIN IMPLEMENTACIÓN**, 2026-09-10. El diseño
completo está en [EXCEPTION-ARCH-2](EXCEPTION_ARCH_2.md). No se modificaron
parser, HIR, MIR, SSA, LLVM ni runtime.

## Modelo recomendado

Aether adopta excepciones unchecked basadas en identidad nominal de clase. No
hay `throws`, `errors E`, obligación de manejar en call sites ni `Result`
obligatorio. La posibilidad de unwind no forma parte de function types,
overrides, interfaces o mangling fuente.

`Exception` es una clase open conocida por el core, no una interface ni un
`Object` universal. Solo `Exception` y sus subtipos nominales pueden lanzarse.
Las clases de excepción usan herencia simple, construcción, descriptor,
identidad, upcast, ARC y destrucción dinámica normales.

## Sintaxis

```aether
throw SomeException(...);

try {
    work();
}
catch (SomeException e) {
    recover(e);
}
catch (Exception e) {
    recoverAny(e);
}
```

`throw;` dentro de un catch relanza el evento activo sin crear otro payload ni
record. `throw e;` es un throw ordinario nuevo. El primer vertical requiere tipo
y binding en cada catch; no admite bare catch, filters, patterns o union catches.

## Throw eligibility y catch matching

- La expresión lanzada debe tener tipo estático de clase `C <: Exception`.
- Primitives, structs, enums, interfaces, borrows, valores parciales y clases
  no relacionadas no son lanzables.
- El catch compara el ClassId dinámico y su cadena nominal de bases con el
  ClassId canónico del clause; no compara strings ni shape.
- Los catches se prueban en orden fuente y gana el primer match.
- Un catch igual o más específico que uno anterior que ya lo cubre es
  inalcanzable y se rechaza.
- `catch (Exception e)` es el catch-all tipado y no captura traps o foreign EH.

## Propagación y ownership

Una excepción no manejada atraviesa implícitamente frames y scopes. El payload
es un objeto ARC normal; un record privado de unwinding posee un strong token
mientras está en vuelo. Throw de un owner fresco transfiere; throw de un lvalue
adquiere Alias antes del cleanup. El catch binding es un handle owning al mismo
objeto, sin slicing. Rethrow transfiere el mismo record.

La evaluación sigue izquierda-a-derecha. Solo locals/temporaries completamente
inicializados se limpian, en orden inverso. Un fallo de constructor limpia
exactamente los fields/base ya inicializados, no ejecuta `deinit` del objeto
parcial y libera una vez la allocation most-derived.

## Cleanup y estrategia de unwinding

La recomendación es híbrida por capas:

```text
HIR: try/catch/throw nominal + obligaciones de ownership
  -> MIR: normal/unwind edges + cleanup blocks explícitos
  -> SSA: result/event edge-only + owner lineal verificado
  -> LLVM: invoke/landing pads o funclets + unwinder nativo del target
```

MIR/SSA, no LLVM ni el runtime, son autoridad del orden y contenido del cleanup.
No se usa TLS/global `current_exception`. El primer target propuesto es Linux
x86-64; cada ABI/target adicional requiere qualification independiente. Un
event-out backend queda como alternativa futura, no como recomendación inicial.

El camino normal evita status results/branches en la firma ordinaria, pero paga
code size por invokes, cold pads y tablas EH. El camino excepcional paga
construcción/record, stack walk, matching O(profundidad inicial), cleanup y ARC.
No hay promesa zero-cost ni aptitud hard real-time.

## Traps

Arithmetic overflow, division/conversion failures, bounds/shape/size checks,
allocation failure, ARC invariant failures e ICE/runtime corruption siguen
siendo traps/fail-fast no capturables. No tienen handler edge ni garantía nueva
de cleanup. `catch (Exception e)` no los intercepta.

## Implicaciones de IR

- HIR conserva ClassIds, catches ordenados, Alias/Transfer, rethrow léxico y
  rollback de construcción.
- MIR usa calls con successors normal/unwind, `Throw`, `ResumeUnwind`, matching
  nominal y cleanup blocks con estados de inicialización/ownership.
- SSA modela result y `ExceptionEvent` exclusivamente en sus edges respectivos;
  exceptional edges participan en dominance, phis, loops y critical edges.
- Todos los IR rechazan evento duplicado/perdido, narrowing sin match dominante,
  cleanup inválido, result usado en unwind y traps conectados a catches.

## `finally`, FFI y destructores

`finally` forma parte del modelo, pero se difiere hasta después del spine y de
virtual/interface invokes. Debe ejecutarse una vez en salidas normales,
returns/control y excepciones, nunca como promesa frente a traps. Su primer
milestone debe prohibir control saliente y cerrar antes la política de un segundo
throw.

Las excepciones no cruzan C FFI. Imports usan contratos C explícitos; exports y
callbacks contienen en un catch-all root o traducen mediante adapters de
status/opaque handle. Foreign C++ EH se contiene en un shim `extern "C"`.

Los futuros `deinit` deben ser non-throwing. Se ejecutan por último release de
objetos completos incluso durante unwind; nunca sobre construcción parcial. Un
segundo unwind desde cleanup termina.

## Primer vertical acotado

**EXCEPTION-V1 — unchecked class exception spine**, Linux x86-64:

- `Exception`, subclases finales, throw fresh/lvalue, catches ordenados,
  exact/subtype/catch-all y bare rethrow;
- propagación por calls directos, nested scopes y root unhandled;
- cleanup exacto de Buffer/class owners y rollback base/derived parcial;
- HIR/MIR/SSA verificables y LLVM native EH;
- pruebas O0/O2, contadores, corruptions y sanitizers;
- evidencia de que arithmetic/bounds/ARC traps siguen fuera de catch.

Quedan fuera: `finally`, invokes virtual/interface/indirectos, generics, async,
threads, user destructors, public FFI adapters, messages/causes/stack traces y
cualquier trap-to-exception conversion.

## Decisiones abiertas

- API/prelude exactos de `Exception` y diagnostics de unhandled;
- personality/ABI concreto y ports Windows/Darwin/ARM64/WASI;
- identidad de descriptors con separate compilation/dynamic libraries;
- política de throw dentro de `finally`;
- adapters FFI recuperables;
- garantía non-throwing para `deinit`;
- generic constraints, async, threads y task roots;
- stack trace/provenance y comportamiento de emergencia ante OOM;
- alcance del análisis interno `nounwind`.
