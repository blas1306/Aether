# Informe de dogfooding generalista: expense tracker

Actualización 15-07-2026: el ejemplo completo conserva paridad AST/native tras
la migración de string. `List<Transaction>` atraviesa múltiples `push`, growth,
filtros, returns, módulos, enum fields, igualdad e impresión con hooks
recursivos para los tres fields string. Se mantienen diez validaciones
funcionales, una validación de slice, más el listado final; no se añadieron CLI
real ni persistencia.

Actualización const/borrow: los tres recorridos de `List<Transaction>` en
`Reports.ae` usan ahora el binding borrowed read-only sin copia automática por
vuelta. El filtro adquiere ownership únicamente al ejecutar `push(transaction)`;
summary y print leen directamente. Un test negativo del dogfood confirma que
`transaction.amount = 0.0` se rechaza. El ejemplo de partículas suma masa con
`for Particle particle in particles`; cuando necesita modificar conserva la
copia local explícita y el set indexado posterior.

Revisión: 15 de julio de 2026. Programa:
[`examples/expense_tracker/`](../../examples/expense_tracker/README.md).

## Resultado ejecutivo

`Main.ae` funciona completo en AST y LLVM/native con el mismo modelo modular:
`List<Transaction>`, enum nominal, strings literales transportadas, alta con
validación, dos reallocations o más, resumen, filtro, lista vacía, `for-in` e
impresión. Las once validaciones, incluidas la independencia de una copia
explícita y de `transactions[0:1]`, producen `true` en ambos backends.

El bloqueo anterior era exclusivamente de layout: IR y SSA conservaban
`StructType`, y los GEP/load/store ya estaban tipados, pero el emisor calculaba
tamaños con una tabla escalar y fallaba en `_sizeof(StructType)`. No se cambió
la semántica por valor ni se sustituyeron structs por punteros.

## Implementación native

- `LLVMTypeLayouts` es la fuente canónica de layout almacenable del módulo.
- El tamaño de un struct es la expresión constante LLVM
  `ptrtoint(getelementptr(%struct.T, null, 1))`; LLVM/DataLayout decide padding,
  anidamiento y ancho de puntero.
- Los buffers de Array/List siguen siendo contiguos y el GEP usa `%struct.T`.
- Get/pop/remove cargan el aggregate por valor; set/push/insert lo almacenan
  por valor.
- `copy()` usa un helper tipado que aplica copy-init por elemento; reserve usa
  relocation y los movimientos solapados usan `memmove`.
- Sólo llegan a esas copias elementos sized con un lifecycle representable. Los
  structs aceptados se verifican recursivamente.
- La clasificación distingue relocation trivial, `needs_destroy`, referencias
  contenidas y `needs_retain`. String y structs que lo contienen usan ARC y
  cleanup; los handles Array/List tienen strong RC y destrucción final.
- Los tipos nominales se emiten antes que los helpers que los usan.

## Subconjunto de campos admitido

Se admiten primitivas nativas (`int`, `boolean`, `double`), enums sin payload,
structs acíclicos anidados, strings y descriptores/referencias de colecciones ya
representables. Un field string es un handle a `AetherStringObject`: copy y
destroy retienen/liberan recursivamente. Las APIs públicas de concat, parsing y
producción dinámica general siguen fuera del subset.

Se rechazan antes de LLVM structs incompletos/recursivos por valor y, para
elementos de colección, class/interface, nullable, float,
complex u otros tipos sin ABI native. El diagnóstico incluye Array/List, tipo
elemento, backend, motivo y ubicación fuente. `sort` no inventa orden para
structs; `contains/indexOf` estructural permanece fuera del subconjunto.

## Evidencia

- E2E del tracker completo con imports y clang real.
- Array de struct con padding, enum, string y struct anidado.
- List de struct con push, varias reallocations, insert, get/set, copy,
  removeAt, pop, reverse, clear, impresión y for-in.
- Slicing independiente de Array/List y copia por valor del elemento.
- Verificadores IR/SSA para identidad nominal, layout conocido y ciclos.
- Ejemplo preliminar de simulación en
  [`particles.ae`](../../examples/aggregate_collections/particles.ae), usando
  `Vec2` porque guardar `Vector<double>` dentro de un struct sólo copiaría hoy
  su descriptor/referencia y no ofrece ownership profundo.

La diferencia principal de presentación es el formateo preexistente de double:
native `%g` imprime `1500`, AST imprime `1500.0`. La baseline también registra
que strings dentro de colecciones se imprimen con comillas en AST/IR y sin ellas
en native. No afecta cálculos ni validaciones del tracker.

## Límites restantes y próxima tarea

Siguen fuera de alcance argumentos, archivos, parsing, split/trim, excepciones
y GC. El tracker es una demostración directa desde
`main`, no una CLI persistente.

El contrato mínimo de string native queda aprobado en
[`STRING_RUNTIME_DESIGN.md`](STRING_RUNTIME_DESIGN.md), y las reglas de copy,
move, assign, destroy, colecciones, calls y cleanup en
[`VALUE_LIFECYCLE_DESIGN.md`](../compiler/VALUE_LIFECYCLE_DESIGN.md). El tracker
usa strings ARC y cleanup de elementos. El último owner de una List libera sus
Transaction vivos, buffer y objeto. `copy()` crea storage exterior distinto y
conserva los strings mediante lifecycle recursivo.

La próxima fase recomendada es igualdad estructural E2E y `Eq(T)` compartido
por `contains/indexOf`; archivos, argv, concat, parsing y split/trim siguen
aplazados.
