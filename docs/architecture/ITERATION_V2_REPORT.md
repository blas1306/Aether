# ITERATION-V2 — Array/List Copy `for-in`

Estado: **IMPLEMENTADO** en `compiler-next`, perfil nativo Linux x86-64,
2026-09-15.

Documento normativo: [ITERATION_ARCH_1.md](ITERATION_ARCH_1.md).

## Superficie cerrada

ITERATION-V2 admite `for (x in values)` y `for (T x in values)` cuando el tipo
exacto del iterable es `Array<T>` o `List<T>` y `T` garantiza `Copy`. El binding
inferido tiene TypeId `T`; la anotación explícita se resuelve antes de introducir
el nombre y debe ser exactamente `T`. No se inserta widening, cast, Alias, move
ni otra conversión por elemento.

Los elementos non-Copy continúan fallando cerrado con E0443, incluida una
anotación `ref T`: el binding `SharedElementBorrow` queda para un vertical
posterior. Range conserva sin cambios la superficie ITERATION-V1 de `int`.
No se admiten otros iterables, iteración mutable/consuming, generators,
comprehensions ni slicing.

## AST y HIR

El parser reutiliza `AstStmtKind::ForIn` y amplía `AstForBinding` para cualquier
tipo fuente ordinario, no sólo el token `int`. La distinción no es ambigua: un
identificador seguido inmediatamente por `in` es binding inferido; las demás
formas resuelven primero un tipo y después el nombre.

HIR agrega `ForCollection` con LoopId, TypeIds exactos de iterable/item/binding,
`IterationBindingCategory::CopyValue`, clasificación Array/List mediante el
TypeArena, `structural_borrow` para List y una fuente con provenance explícita:

- `Borrowed(HirPlace)` conserva el owner de un lvalue o `*reference`;
- `Temporary { root, initializer }` transfiere el resultado owning completo a
  un LocalId oculto address-taken cuyo lifetime abarca el loop.

La sustitución genérica conserva todos esos TypeIds y vuelve a comprobar `Copy`
en la instancia concreta. El verificador HIR rechaza discrepancias entre la
colección, el item, el binding, la categoría, el root temporal y el préstamo
estructural. No existe una marca opaca de “for verificado”.

## Ownership, mutación y cleanup

Un lvalue queda prestado durante el loop completo. Su owner no puede moverse,
reemplazarse ni destruirse. List añade un préstamo de toda la estructura, por
lo que push, reserve, pop, remove, swap_remove y llamadas por una referencia
escribible que pueda alcanzar el mismo root fallan estáticamente. La política
es conservadora ante provenance desconocida y no depende de spare capacity.

Las asignaciones de slots Copy siguen siendo mutación no estructural. Cada item
se carga al entrar en su vuelta: escribir un índice futuro cambia el valor que
se observará al alcanzarlo, mientras el binding actual conserva su copia.

El root oculto de un temporary participa en el análisis lineal ordinario. MIR
usa `CollectionOwnerCapture` para su única transferencia y el root se incorpora
a `active_owners`; los drop flags, return, landing pads, catch y finally
reutilizan exactamente el protocolo de ownership existente. La salida normal,
break o exhaustion destruye el root una vez; return y unwind lo limpian por la
ruta correspondiente. Un lvalue prestado nunca se destruye por el loop.

## MIR, SSA y LLVM

MIR baja cada colección a CFG explícito:

```text
preheader: capture owner; captured_length = length(owner); index = 0
header:    index < captured_length ? item : exit
item:      binding = CollectionBinding(owner, index, CopyValue)
body:      fallthrough/continue -> latch; break -> exit
latch:     index = checked(index + 1); goto header
exit:      end borrow; drop hidden owner when present
```

`CollectionLoop` conserva kind, iterable/item/binding TypeIds, category,
owner, captured length, index, LoopId, header/item/body/latch/exit, préstamo
estructural y root temporal. El verificador MIR reconstruye captura única de
length y cero, comparación estricta, carga tardía, provenance común, targets,
avance checked unitario y cardinalidad de `CollectionOwnerCapture`.

SSA preserva esa metadata, el phi exacto de index y las operaciones efectivas.
Su verificador vuelve a relacionar el valor inicial, phi/backedge, captured
length, source descriptor, `CollectionBinding` y latch sin confiar en
VerifiedMir. Los loops Range y Collection comparten una secuencia canónica de
LoopId, incluidos programas y nesting mixtos.

LLVM recibe sólo VerifiedSSA. Emite descriptor, comparación, phi, GEP y load
tipado directos. El bounds proof dominante autoriza el GEP sin helper por item.
No hay iterator object, `next`, vtable, allocator, heap helper ni allocation
adicional del loop. Las únicas allocations observadas son las propias de crear
la Array/List fuente.

## Control flow

`continue` apunta al latch y ejecuta un avance; `break` apunta al exit y no
carga ni avanza otro item. El item block sólo carga después del guard. Nested
Range/Array/List loops conservan targets lexicales. Los transfers que atraviesan
finally usan el mecanismo de acciones pendientes de EXCEPTION-V4; throw y
unwind conservan el ExceptionEvent y limpian el root temporal.

## Qualification

La suite `iteration_v2` cubre nativamente en O0 y O2:

- Array y List vacíos, singleton y múltiples;
- escalares Copy de tamaños distintos y aggregate Copy;
- inferencia, anotación exacta y mismatches sin conversión;
- lvalues, `*ref Array/List` y resultados temporales de funciones;
- evaluación única, una sola lectura de length y orden ascendente;
- mutación de slot futuro observable y copia estable del binding actual;
- rechazo de push/reserve/pop/remove/swap_remove, replacement, move y calls
  escribibles potencialmente estructurales;
- break, continue, nested loops y mezcla con Range;
- return, throw/catch, finally y cleanup del hidden root;
- corrupciones independientes de HIR, MIR y SSA;
- ausencia de iterator/helper y carga LLVM directa;
- equivalencia observable O0/O2.

`tests/programs/iteration_v2_smoke.ae` queda incorporado al corpus diferencial.
La qualification final ejecutó sin fallos `cargo test --workspace`,
`cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D
warnings`, `git diff --check` y `bash compiler-next/tests/run-differential.sh`
(21 comparaciones legacy, cero diferencias inesperadas).

## Límites conservados

Permanecen fuera elementos non-Copy y bindings `ref T`, ranges de otros
integers o float, mutable/consuming iteration, custom Iterable/Iterator,
generators, slicing y comprehensions. ITERATION-V2 tampoco publica una API de
iterator ni modifica runtime, ABI de colecciones o el compilador legacy.
