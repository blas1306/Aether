# GENERAL-V2 — string structural composition

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-12, para el backend nativo
bootstrap Linux x86-64 de `compiler-next`. Este vertical elimina los gates de
almacenamiento correspondientes de GENERAL-V1 sin cambiar la representación,
el ownership directo ni las operaciones de contenido de `string`.

## Superficie admitida

Se admiten `string` como field de struct, payload de enum, elemento de
`Array<string>` y elemento de `List<string>`. La composición también alcanza
structs anidados, payloads aggregate y sustituciones genéricas que satisfagan
sus constraints reales. `Array<string>` se construye con literal; el constructor
fill que exige `T: Copy` continúa rechazado. List conserva sus operaciones ya
existentes de init, reserve, push, index replacement, remove y pop.

No se añadió sintaxis ni operación textual. GENERAL-V1 sigue siendo la autoridad
para literals, Alias directo, concat, igualdad, `byteLength`, output, UTF-8 y el
runtime ARC privado.

## Propiedades y límites de ownership

El fold estructural existente produce para cualquier aggregate que contiene
`string`: `Copy=false`, `Relocatable=true`, `Storable=true` y `needs_drop=true`.
Un parámetro `T: Copy` rechaza tanto `string` como un struct que lo contiene.
Storable no implica Copy, Clone ni Alias.

Un uso owning del aggregate completo es Move/Transfer y deja el source movido.
Un segundo uso se rechaza. No existe lectura owning parcial de `a.field` ni de
un índice que sintetice Alias; tampoco existe deep copy del aggregate. El Alias
intrínseco de GENERAL-V1 sólo aplica cuando la expresión fuente ya es un lvalue
cuyo tipo exacto es `string`, por ejemplo al construir una colección desde una
variable string viva.

## Construcción, replacement y Drop

Struct y enum consumen los owners de sus fields/payloads al construir el valor.
Array/List consumen cada elemento publicado en su prefijo inicializado. El Drop
recursivo existente destruye fields en orden inverso, sólo el payload activo del
enum y cada elemento vivo de la colección, liberando cada obligación string una
vez.

El replacement de un root `needs_drop` materializa primero el RHS, mueve el
owner anterior a un temporal, publica el nuevo valor y luego destruye el
anterior. Para un slot cuyo tipo exacto es `string`, MIR y SSA incorporan
`ReplaceString`: validan target escribible y operands exactos, almacenan el
nuevo handle y sólo después llaman a release sobre el anterior. Otros
replacements parciales de valores no-Copy continúan rechazados.

Returns normales, ramas y early returns descargan los owners vivos mediante los
cleanup lists existentes. Los landing pads de excepciones ejecutan el mismo
Drop recursivo para aggregates inicializados antes del throw.

## Array/List y relocalización

La admisión de elementos reutiliza la autoridad Storable/Relocatable de V17 y
el lifecycle de colecciones de V16-V20. La relocalización copia el handle string
de una palabra al slot destino, publica el destino e invalida el origen. No hace
retain ni release. El crecimiento de List y los desplazamientos de `remove`
mantienen el protocolo de prefijo inicializado/hueco; `remove` y `pop` transfieren
el owner extraído al resultado. El Drop final recorre únicamente elementos
todavía vivos.

El backend selecciona el runtime string por contención estructural en firmas y
tipos de resultados SSA. Así, incluso `Array<string>{}` o `List<string>{}` sin
literal ni operación textual dispone del glue de Drop necesario.

## Verificación independiente

HIR valida que el aggregate es no-Copy, que el Move invalida el source y que no
se introduce replacement parcial general. MIR verifica el ledger path-sensitive,
los Drops recursivos y el contrato exacto de `ReplaceString`. SSA extiende su
auditoría de owners a todo tipo que contiene string: parámetros, phis,
Aggregate/EnumConstruct, ArrayInit/ListInit, ListPush, Store/InsertField,
ReplaceString, ConsumeEnum, calls, returns, Move y Drop tienen consumos
explícitos y únicos por camino.

Las corrupciones de qualification comprueban rechazo de cleanup HIR duplicado,
operand no-string en `ReplaceString` MIR, result type incorrecto en SSA y
eliminación de los Drops recursivos SSA.

## Qualification ejecutable

La fixture `compiler-next/tests/programs/general_v2_string_composition.ae` y
`crates/aether-driver/tests/general_v2_string_composition.rs` cubren, en O0 y
O2:

- struct con un string, struct con varios strings y structs anidados;
- payload string y payload aggregate de enum, con match consuming;
- whole-value Move y rechazo de moved-from use y field-wise Alias;
- Array construction, replacement indexado y Drop;
- List init/reserve/push/replacement/remove/pop, relocalización y Drop;
- branch, early return, replacement de aggregate root y cleanup por excepción;
- rechazo de `T: Copy` para string y para un aggregate que lo contiene;
- selección de runtime para colecciones string vacías y corrupciones HIR/MIR/SSA.

La fixture conjunta observa exactamente `(alloc=2, free=2, retain=8,
release=10, concat=2, equal=0, literal_arc_noop=5)` y dos relocalizaciones tanto
en O0 como en O2. Esas dos relocalizaciones agregan cero eventos ARC. El caso de
branch/early return/root replacement observa `(4,4,0,4,4,0,8)`; el unwind de un
struct con dos heap strings observa `(2,2,0,2,2,0,4)`. Las colecciones vacías
observan cero en todos los contadores.

La calificación de cierre ejecutó sin fallos `cargo test --workspace` (incluye
219 pruebas verticales, 55 de frontend y 22 de middle-end), además de los seis
casos GENERAL-V2; `cargo fmt --all --check`; `cargo clippy --workspace
--all-targets -- -D warnings`; `git diff --check`; y el differential completo,
con `checked=21, failures=0`.

## Scope cerrado y deuda

Permanecen fuera: capability genérica Clone/Alias; ownership de graphs de
class/interface; fields class string; referencias string y `StringView`;
`Buffer<string>`, `Vector<string>` y `Matrix<string>`; indexing, slicing e
iteración textual; Text APIs, formatting/interpolation, Bytes, hashing, COW,
SSO y threads.

Deuda deliberada: generalizar en un vertical separado el replacement parcial
para cualquier tipo no-Copy con un protocolo de slot, si resulta necesario;
extraer/versionar el runtime privado; y calificar otros targets. Nada de esto se
infiere de Storable o Relocatable ni queda admitido por GENERAL-V2.
