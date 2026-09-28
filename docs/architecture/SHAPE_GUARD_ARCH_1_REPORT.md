# SHAPE-GUARD-ARCH-1 — reporte de arquitectura

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Autoridad normativa:
[SHAPE-GUARD-ARCH-1](SHAPE_GUARD_ARCH_1.md).

Este reporte cierra únicamente el milestone documental. No se modificaron el
lenguaje, compiler-next, runtime, std, `linearAlgebra`, OAL ni tests.

## Resultado

Se fija una única superficie source global y general:

```aether
shapeGuard(condition);
```

Es una primitiva intrínseca statement-only, reservada y disponible para todo
package sin import ni privilegio. Admite exactamente un `bool`, sin type
arguments, resultado, mensaje o trap seleccionable. El camelCase sigue las
primitivas compuestas `vectorFilled` y `matrixFilled`.

Si la condición completa con `true`, continúa. Si completa con `false`, emite
exactamente el `ShapeMismatch` estructurado existente. La condición se evalúa
una sola vez. El guard no inspecciona Matrix/Vector ni infiere shapes: relaciones
como `rows(A) == columns(A)` o `dimension(v) == rows(A)` son expresiones
booleanas ordinarias escritas por la library.

## Alternativas cerradas

No se eligió una función ordinaria core/std porque una call opaca no preserva
el contrato y fail edge exigidos. Tampoco se agregó `assert`, un sistema de
contracts ni `guard(condition, TrapKind)`: esas opciones mezclan mensajes,
políticas de assertions, propagación interprocedural o custom traps fuera del
problema.

La primitiva es general por condición y por package, pero deliberadamente fija
la clase de fallo. No existe intrinsic de solve, álgebra lineal, Matrix o
Vector.

## Semántica y orden

La expresión booleana conserva todos sus efectos y traps ordinarios y se
evalúa antes de decidir. Un bounds trap o división por cero surgido dentro de
la condición no se convierte a `ShapeMismatch`. En el camino `true`, el guard
en sí no asigna, muta, retiene, libera ni deja un borrow residual.

Los statements posteriores sólo son alcanzables por el success edge. Por ello
una library obtiene fail-before-allocation/access/division/call cuando coloca el
guard antes de esas operaciones. No hay hoisting, sinking ni ejecución
especulativa implícitos. El primer guard falso en orden source gana.

`ShapeMismatch` continúa siendo abortivo y no capturable: no es Exception, no
hace unwind, no exige cleanup ni lleva mensaje dinámico.

## HIR, MIR y SSA

HIR incorpora `HirStmtKind::ShapeGuard` con operando `bool`, trap frontend
cerrado `ShapeMismatch` y el span del statement. No se transforma en una call.

MIR y SSA incorporan cada uno un terminator `ShapeGuard` con:

- operando booleano;
- edge `success`;
- edge `failure`;
- `TrapKind::ShapeMismatch`;
- source span.

El fail block es vacío y termina exactamente en `Trap(ShapeMismatch)`; no tiene
unwind ni continuación. Las operaciones source posteriores viven sólo bajo el
success edge.

Los verificadores de las tres capas recalculan el contrato y fallan cerrados
ante tipo no bool, trap distinto, edges inválidos, fail block continuante,
unwind o span corrupto. SSA comprueba además definición/dominance y no confía en
la admisión MIR. El `MathStep::ShapeGuard` existente dentro de recipes
matemáticas cerradas permanece separado y no se vuelve una API programable.

## Backend, optimizer y generalidad

El backend dirige el fail edge a la ruta `trap_shape_mismatch` existente, que
usa `llvm.trap`/`unreachable`. No aparece helper, ABI, excepción, payload ni
runtime específico de libraries.

Una optimización puede borrar un guard probado `true` o convertir uno probado
`false` en trap directo sólo si también prueba que no elimina efectos o traps
de la condición. CSE/propagación debe preservar memoria, aliasing, orden y
número de evaluaciones. V1 no requiere análisis interprocedural de shapes ni un
nuevo optimizer general.

Cualquier package, incluida una dependencia ordinaria, puede escribir
`shapeGuard(false);`. Se acepta deliberadamente: permite terminación segura,
pero no raw access, memoria uninitialized ni elección arbitraria de traps. La
auditoría confirma que `ShapeMismatch` ya es compartido por productos y
operaciones elementwise, `Matrix.add` y slice assignment; no pertenece a
`linearAlgebra`.

## Calificación futura

El vertical de implementación deberá cubrir true/false, type errors,
evaluación única, ordering frente a side effects, guards anteriores a
allocation/access/division/calls, preservación de otros traps, préstamos sin
residuo, relaciones arbitrarias de extents, package consumer, O0/O2 y
corrupciones HIR/MIR/SSA.

Las pruebas de folding constante serán obligatorias sólo cuando exista el pass
que lo implemente. También deberá comprobarse estructuralmente la ausencia de
special cases por nombre de `linearAlgebra`, OAL, `solve`, Matrix o Vector.

## Orden de implementación acordado

1. Superficie y diagnostics de `shapeGuard`.
2. Nodo y verifier HIR.
3. CFG/terminator y verifier MIR.
4. Preservación y verifier SSA.
5. Lowering a `ShapeMismatch` existente.
6. Tests source/package/ordering/O0/O2/corrupción.
7. Folding opcional si hay un pass apropiado.
8. Suite completa y reporte de implementación.
9. Implementación posterior de LINEAR-ALGEBRA-SOLVE.

Quedan fuera solve, design-by-contract, shape inference, dependent/refinement
types, custom traps, assertion messages, exceptions y compiler magic de
álgebra lineal. No quedan decisiones arquitectónicas abiertas dentro del
milestone.
