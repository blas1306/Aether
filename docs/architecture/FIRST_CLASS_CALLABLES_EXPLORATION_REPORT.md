# Aether — FIRST-CLASS-CALLABLES — Exploration Report

Estado: **EXPLORATION COMPLETE; PROPOSED; NO IMPLEMENTADO**, 2026-11-04.

Documento principal:
[FIRST_CLASS_CALLABLES_EXPLORATION](FIRST_CLASS_CALLABLES_EXPLORATION.md).

## Resultado

Se completó la exploración arquitectónica de interoperabilidad entre
`Function<(Args),Return>` y `Closure<(Args),Return>` sin modificar compiler,
runtime, libraries, tests ni ejemplos.

La recomendación no hace de `Callable` un requisito inmediato. Propone:

1. una capability compiler-known, estructural y parametrizada por firma,
   provisionalmente `Invocable<(P...),R>`;
2. especialización antes de MIR a `IndirectCall` para Function o
   `ClosureCall` para Closure;
3. un `Callable` owning erased sólo como milestone posterior para storage o
   retorno heterogéneo, con adapters explícitos;
4. un posible `CallableRef` borrowed/no-escape si se necesita ABI uniforme sin
   monomorfización.

## Evidencia inspeccionada

Se revisaron los contratos y reportes de:

- Function Values y Anonymous Functions;
- First Class Closures, capture analysis, ownership IR y runtime LLVM;
- `OWNING-CLOSURES-READ-V1` y `ClosureABI-v1`;
- TypeArena, TypeData, TypeProperties, substitution y constraints generic;
- `FunctionRef`, `IndirectCall`, `ClosureAlias`, `ClosureBorrow`,
  `ClosureCall` y `EndClosureBorrow` en HIR/MIR/SSA/backend;
- borrow ergonomics y lifecycle de parámetros owning;
- `plots.plotFunction` y consumidores de Newton, derivación, métodos numéricos
  y mínimos cuadrados.

Hallazgos determinantes:

- Function y Closure ya son tipos estructurales hermanos, no subtipos.
- Function es un code pointer Copy/no-drop.
- Closure es un box pointer no-Copy con Alias ARC y Drop.
- Los carriers de un pointer no son ABI-intercambiables.
- Alias no es una capability generic pública.
- Storable no implica Alias, invocabilidad ni Copy.
- Las funciones generic se concretan antes de MIR, lo que permite resolver una
  operación de capability a los spines existentes sin runtime nuevo.
- Por firma, V1 sólo tiene dos tipos concretos de callable: Function y Closure;
  specialization no ocurre por lambda individual.

## Alternativas evaluadas

| Alternativa | Resultado |
|---|---|
| A. overloads Function/Closure | viable como puente; duplica APIs y crece combinatoriamente |
| B. Callable owning erased | necesario para heterogeneidad runtime; demasiado costoso como mecanismo universal |
| C. capability + specialization | mejor primer mecanismo; una fuente, sin adapter/runtime nuevo |
| D. híbrida | arquitectura objetivo recomendada; capability primero, erasure cuando exista caso real |
| E. CallableRef borrowed | alternativa útil para ABI invoke-only; no almacenable y no zero-cost |

## Ownership y rendimiento propuestos

Para una API generic by-value:

| Argumento | Frontera | Invocation |
|---|---|---|
| Function | copia de pointer | `IndirectCall` |
| Closure fresh | Transfer | borrow + `ClosureCall`, sin ARC por call |
| Closure lvalue | Alias/retain al entrar, release al salir | borrow + `ClosureCall`, sin ARC por call |

Una variante `ref C` puede evitar el retain/release de boundary y reutilizar la
región de shared call borrow, pero requiere qualification propia de invocation
a través de generic reference.

No se promete direct call, inline, eliminación del box ni zero-cost. La
capability evita allocation y thunk de **adaptación**; no elimina los costes
intrínsecos del kind concreto.

## Impacto IR

La propuesta mínima agrega una operación proof-carrying sólo en generic HIR,
provisionalmente `CapabilityInvoke`. La monomorfización debe validar firma y
modo repeatable-read, sustituir el tipo y reescribirla a operaciones concretas.
MIR debe rechazar cualquier capability call residual.

Un futuro Callable owning necesitaría su propia familia Create/Alias/Borrow/
Call/EndBorrow/Drop. Un futuro CallableRef necesitaría creación de descriptor,
call y cierre de región. Ninguna de esas familias se incorpora al primer
milestone.

## Riesgos principales

- confundir invocabilidad con Alias/Storable;
- presentar specialization como direct dispatch o zero-cost;
- code size por combinaciones de varios parámetros callable;
- evidencia de capability adulterada o residual generic en MIR;
- ocultar allocation/retain en conversiones a un owner erased;
- escape de un descriptor borrowed;
- perder cleanup o `ExceptionEvent` en thunks/unwind;
- confundir compatibilidad entre módulos fuente con ABI entre artefactos.

## Secuencia propuesta

1. revisión del spelling y contrato de `Invocable`;
2. `INVOCABLE-CAPABILITY-V1` by-value, sin migrar libraries;
3. `BORROWED-INVOCABLE-PARAM-V1` para `ref C`;
4. migración y qualification de `plots.plotFunction`;
5. adopción en Newton, integración, derivación y mínimos cuadrados;
6. medición de code size y un consumer real de storage;
7. implementar `CallableRef` o `Callable` owning sólo según esa evidencia;
8. storage en aggregates/containers y class fields como verticales separados.

## Decisiones pendientes de revisión

- spelling y grammar de la capability parametrizada;
- inclusión de `ref C` en el primer vertical;
- estrategia de compatibilidad para APIs Function existentes;
- spelling general de Move explícito para adapters;
- representación propia de Callable frente a adopción normativa de un header
  Closure-compatible;
- consumer que justifique storage heterogéneo;
- umbral medido para preferir CallableRef a monomorfización.

## Cambios realizados

Sólo se crearon:

- `docs/architecture/FIRST_CLASS_CALLABLES_EXPLORATION.md`;
- `docs/architecture/FIRST_CLASS_CALLABLES_EXPLORATION_REPORT.md`.

No se modificó código productivo, runtime, libraries, tests, reproducers ni
ejemplos. No se hizo commit ni push.
