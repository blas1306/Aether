# ITERATION-V3 — borrowed non-Copy Array/List elements

Estado: **IMPLEMENTADO** en `compiler-next`, perfil nativo Linux x86-64,
2026-09-15.

Documento normativo: [ITERATION_ARCH_1.md](ITERATION_ARCH_1.md).

## Superficie cerrada

ITERATION-V3 implementa únicamente la fila `SharedElementBorrow` para
`Array<T>` y `List<T>` cuando el elemento exacto `T` no garantiza `Copy` y ya
es legal como storage según los gates vigentes. El binding inferido es
exactamente `ref T`; la anotación explícita debe ser el mismo TypeId. Por tanto
`for (word in words)` y `for (ref string word in words)` son válidos para
colecciones de string, mientras `for (string word in words)` y `ref mut string`
se rechazan.

La fila V2 de elementos Copy no cambia: conserva binding `T` por valor y
categoría `CopyValue`. Tampoco se modificó `collection_element_admission`, las
garantías `Storable`/`Relocatable`, el gate particular de Buffer ni la
composición OOP. Un aggregate owning, nested Array/List o parámetro genérico
con garantía suficiente hereda la nueva categoría sólo cuando su TypeId exacto
resulta non-Copy y su colección ya era admisible.

No existe auto-deref: la lectura continúa usando `*binding`, incluida la forma
`println("${*word}")`. Las lecturas string obtenidas desde ese Place son
préstamos para la operación de texto, no `StringOp::Alias` ni owners nuevos.

## HIR y provenance

`IterationBindingCategory` incorpora `SharedElementBorrow`. `ForCollection`
conserva iterable/item/binding TypeIds por separado, el binding `ref T`
canónico, la fuente `Borrowed(HirPlace)` o el root temporal, el owner derivado,
el préstamo estructural de List y el body que delimita el préstamo por item.
El verificador HIR reconstruye la relación exacta `ref item_type`, exige
capacidad shared y rechaza la categoría borrowed para un T Copy.

El análisis de ownership registra el owner de la colección como provenance del
binding y mantiene dos obligaciones distintas:

- el owner/descriptor de la colección queda prestado durante todo el loop;
- el slot posiblemente actual queda prestado durante el body de la vuelta.

Mientras vive el segundo préstamo se rechazan replacement de un slot non-Copy,
extraction, move y llamadas escribibles que puedan alcanzarlo. List conserva
además la prohibición total de push, reserve, pop, remove y swap_remove durante
la iteración. La comparación de roots permite que otra colección demostrablemente
disjunta siga siendo mutable; relaciones de índices o aliases no probadas
fallan cerrado. Las reglas existentes impiden almacenar, retornar o rebindear
el `ref T`.

## MIR, SSA y LLVM

MIR reutiliza el CFG explícito de V2 y materializa en el item block una
`CollectionBinding { category: SharedElementBorrow }`. Esa operación toma
`owner[index]` bajo el guard dominante y produce `ref T`; no carga T ni crea un
owner. `CollectionLoop` conserva owner, TypeIds, captured length, índice,
header/item/body/latch/exit, structural borrow y hidden root.

Los verificadores MIR y SSA relacionan de nuevo el collection kind, element
TypeId, pointee/reference TypeId, capacidad shared, source Place, índice y
LoopId. SSA reconstruye la región del body desde el CFG: ningún uso del valor
borrowed puede aparecer en latch, exit u otra región, y Store, ReplaceString,
Move, Take, Relocate o mutación List sobre el mismo root se rechazan mientras
el préstamo está vivo. Esto hace verificable el fin del préstamo antes del
latch sin una marca opaca de aprobación.

LLVM emite el descriptor, GEP comprobado por dominancia y el puntero al slot.
`CopyValue` conserva su load anterior; `SharedElementBorrow` devuelve la
dirección tipada del slot. No se emiten Alias, Move, Clone, Take, Relocate,
retain/release, deep copy, iterator object, vtable, `next` ni allocation por
item. Los únicos costos owning son la construcción y destrucción normal de la
colección/elementos.

## Temporales y control flow

Las colecciones temporales owning conservan el hidden root de V2. El préstamo
apunta siempre a un slot de ese root. Fallthrough y `continue` terminan todo uso
del binding antes del latch; `break` sale sin advance ni carga adicional.
Return, throw/unwind y `finally` reutilizan drop flags, landing pads y acciones
pendientes existentes, de modo que el root se limpia exactamente una vez.
Colecciones lvalue no son destruidas por el loop.

## Qualification

La suite `crates/aether-driver/tests/iteration_v3.rs`, el test HIR local y
`tests/programs/iteration_v3_smoke.ae` cubren en O0 y O2:

- Array/List, inferencia a `ref string` y anotación explícita exacta;
- rechazo de binding owning y `ref mut`;
- lectura explícita, interpolación, UTF-8 multibyte y U+0000;
- aggregate non-Copy, nesting y una instancia genérica Storable;
- cero ARC/relocation en el item block y ausencia de iterators/helpers;
- rechazo de mutación estructural, replacement, extraction, owner replacement
  y llamadas escribibles posiblemente invalidantes;
- mutación de un root demostrablemente disjunto;
- continue, break, nested loops, temporales, return, throw y finally;
- corrupciones HIR de item/reference/category, MIR de categoría, y SSA de
  pointee, lifetime y operación invalidante.

El smoke V3 participa también del corpus diferencial como contrato nativo sin
equivalente legacy.

La qualification de cierre ejecutó sin fallos `cargo test --workspace`,
`cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D
warnings`, `git diff --check` y `bash compiler-next/tests/run-differential.sh`.
El diferencial comparó 21 casos legacy y reportó cero fallos.

## Scope conservado

Permanecen fuera auto-deref, iteración `ref mut`, consuming/move iteration,
Alias/value iteration de owners, custom Iterable/Iterator, ranges de otros
integers o float, generators, slicing y comprehensions. ITERATION-V3 no cambia
runtime público, ABI de colecciones, representación string ni el compilador
legacy.
