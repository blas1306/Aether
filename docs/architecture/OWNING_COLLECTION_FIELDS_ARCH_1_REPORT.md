# Aether — OWNING-COLLECTION-FIELDS-ARCH-1 — Reporte

Estado: **ARCHITECTURE CLOSED; FASE DOCUMENTAL COMPLETADA**, 2026-11-22.

Documento normativo:
[OWNING_COLLECTION_FIELDS_ARCH_1.md](OWNING_COLLECTION_FIELDS_ARCH_1.md).

## 1. Resultado

La investigación cerró F1 y F2 sin implementar cambios.

- F1 es un defecto SSA de continuidad de owners en commits de descriptor. La
  operación source ya es válida y HIR/MIR la representan correctamente. La
  corrección debe quedar en SSA y reutilizar `ListPush/ListReserve`,
  `InsertField`, `StoreProvenance::DescriptorCommit` y el ledger existentes.
- F2 fue reclasificado: `*lines[0]` no pide un borrow; intenta dereferenciar un
  `string`. Debe seguir rechazado, pero con E0271 en lugar del E0293 producido
  por un load prematuro. `trim(lines[0])` y `trim(&lines[0])` ya implementan la
  observación shared requerida.

No se modificaron compiler, runtime, STD, OAL, ejemplos ni APIs. No se inició
implementación, no se hizo commit ni push y no se ejecutó un workspace global.

## 2. Evidencia de reproducción

Checkout inspeccionado:

```text
3c5c451854cbddb2d5296ed1873ae837a5e03908
```

CLI:

```text
compiler-next/target/debug/aether
```

### F1

| Comando | O0 | O2 |
|---|---|---|
| `aether check <F1>` | E0400 owner `ValueId(6)` live | mismo |
| `aether build <F1> -o <tmp>` | mismo E0400 | mismo |
| local `List<Item{string}>` + push | E0400 | mismo |
| `reserve(List<string>)` | E0400 | mismo |
| Copy-element field análogo | PASS/runtime 0 | PASS/runtime 0 |
| address-taken aggregate field | E0400 projected owning Store | mismo |
| mutation por `ref mut Result` | PASS/runtime 0 | PASS/runtime 0 |

El dump del caso Copy análogo demuestra la secuencia SSA
`ListPush -> InsertField -> Drop(new aggregate)`. La inspección de
`verify_ownership_ledger` demuestra que `InsertField` consume hoy sólo su
aggregate operand, no el descriptor owning insertado. El ID reportado por el
reproducer es precisamente el resultado de `ListPush`.

Al materializar el root, SSA cambia a
`ListPush -> Store DescriptorCommit(ListPush)`. El verifier de provenance puede
demostrar el par, pero el chequeo genérico de Store rechaza primero un target
drop-needing `MemoryLocal + Field*`. El camino `Dereference + Field*` usado por
`ref mut` pasa, confirmando la bifurcación.

### F2

| Forma | O0 | O2 |
|---|---|---|
| `trim(*lines[0])` | E0293 actual | E0293 actual |
| `trim(lines[0])` | PASS, imprime `x` | PASS, imprime `x` |
| `trim(&lines[0])` | PASS, imprime `x` | PASS, imprime `x` |

Se ejecutó además un probe conjunto con local string, field string,
`Array<string>`, `List<string>`, `List<int>` a `ref int` e iteración
`ref string`; todas las formas correctas pasaron check y runtime O0/O2.

HIR/MIR/SSA de `trim(lines[0])` muestran `CallScopedSharedBorrow`, `Borrow` y
`EndBorrow` sobre el Place indexado. No hay Move, Clone ni Alias del elemento.

## 3. Consumers inspeccionados

### `examples/assessment/data-processor`

Usa `remove(lines, 0)` y `remove(fields, 0)` para obtener owners string. Ese
workaround nació de F2, pero no es necesario para observación: el header puede
observarse con `trim(lines[0])`. Consumir/remover continúa siendo correcto
cuando la aplicación realmente necesita extraer ownership.

### `examples/assessment/expense-tracker`

Mantiene `List<Expense>` como local root y lo pasa por
`ref mut List<Expense>` a `loadExpenses`; status queda separado. Es el
workaround exacto de la rama SSA promovida de F1.

### `examples/expense_tracker`

El consumer histórico ya demuestra ambos contratos correctos:

- `addTransaction(ref mut Ledger)` ejecuta
  `push((*ledger).transactions, Transaction(...))`, que usa el camino
  DescriptorCommit por dereference y pasa;
- `std.Text.trim((*arguments)[3])` y `[4]` observan directamente elementos
  indexados de `Array<string>` sin escribir `*` delante del index.

Los tres consumers pasan `aether check` O0/O2 en el checkout preservado.

## 4. Separación de causas

| Dimensión | F1 | F2 |
|---|---|---|
| primera etapa problemática | SSA | frontend diagnóstico |
| source válido | sí | no, por el `*` |
| capacidad semántica nueva | no | no |
| contrato reutilizado | descriptor commit + aggregate ownership | exact shared call borrow |
| cambio mínimo | owner transitions + projected commit verification | E0271 sin load owning |
| runtime/STD/OAL | sin cambios | sin cambios |
| milestone | owning collection fields | index dereference diagnostic |

No comparten un defecto de representación y no deben resolverse con un cambio
global de ownership.

## 5. Arquitectura recomendada

### F1

- completar consumos de source root para mutadores SSA directos;
- hacer que owning `InsertField` consuma aggregate y inserted value;
- verificar producer/path/source/single-use para el par mutador + InsertField;
- exceptuar del rechazo genérico de projected Store sólo un
  `DescriptorCommit` que el verifier reconstruya y valide;
- conservar lowering LLVM y demostrar lifecycle O0/O2 por identidad.

### F2

- inspeccionar el tipo de un Place operand de dereference sin cargarlo;
- emitir E0271 si no es reference;
- mantener E0293 para una lectura/move parcial real;
- conservar las formas válidas y la ausencia de auto-deref/implicit clone.

## 6. Qualification y riesgos

El documento normativo contiene matrices separadas. Los gates decisivos son:

- reproducers O0/O2 en check/build y runtime cuando corresponda;
- tres formas SSA de descriptor continuity;
- `List<T>` Copy y owning, nested fields, roots address-taken y `ref mut`;
- growth/reallocation, aliases, return, throw/catch y cleanup;
- lifecycle sin double-drop, leak, use-after-free ni Clone implícito;
- borrows indexados implícitos/explícitos, Array/List/field/iteration;
- rechazo de growth con borrow vivo y de partial moves reales;
- corruption tests independientes HIR/MIR/SSA y verificación LLVM.

El riesgo principal de F1 es confundir continuidad de descriptor con
replacement. La arquitectura lo evita exigiendo un producer tipado exacto y
prohibiendo que `InsertField`/Store owning ordinarios suplan `ReplaceOwned`.
El riesgo principal de F2 es silenciar E0293 legítimos; el cambio se limita al
outer dereference cuyo operand Place tiene tipo non-reference probado.

## 7. Bloqueos y estado

No quedan bloqueos de arquitectura ni decisiones de lenguaje abiertas. Quedan
trabajos de implementación y qualification:

1. implementar/corromper/calificar la continuidad SSA de F1;
2. implementar y probar el diagnóstico E0271 de F2;
3. ejecutar los gates focalizados y nativos de las matrices antes de declarar
   los milestones de implementación CLOSED.

La imposibilidad de obtener un dump raw del F1 desde la CLI —el driver verifica
SSA antes de imprimirlo— no deja la causa indeterminada: la forma se confirmó
con el caso Copy análogo, ambos modos de materialización, el caso `ref mut`
positivo y la inspección directa de builder y verifier. Un test de implementación
debe usar `build_ssa` antes de `verify_ssa` para fijar esa evidencia.

## 8. Archivos de esta fase

- `docs/architecture/OWNING_COLLECTION_FIELDS_ARCH_1.md`;
- `docs/architecture/OWNING_COLLECTION_FIELDS_ARCH_1_REPORT.md`.

Los probes temporales de reproducción no forman parte del entregable.
