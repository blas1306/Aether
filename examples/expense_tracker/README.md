# Expense tracker dogfood example

Este ejemplo modular prueba el núcleo generalista de Aether con un dominio no
matemático. Modela ingresos y gastos, valida montos, mantiene una
`List<Transaction>`, resume, filtra y lista transacciones. No pretende ser
todavía una aplicación financiera persistente.

## Estructura

- `Transaction.ae`: enum y struct nominal del dominio; la fecha es `string`.
- `Ledger.ae`: alta validada en `List<Transaction>`.
- `Reports.ae`: resumen, filtro e impresión mediante `for-in`.
- `Main.ae`: demostración completa en memoria y sus validaciones de dominio,
  collections y strings dinámicas.

## AST y native

Desde la raíz del repositorio:

```bash
aether --backend=ast examples/expense_tracker/Main.ae
aether --backend=native examples/expense_tracker/Main.ae
```

El mismo programa completo funciona en ambos backends. LLVM almacena cada
`Transaction` por valor en un buffer contiguo, obtiene su tamaño del layout del
target y conserva los handles de sus valores `string` durante get/set,
crecimiento y filtrado mediante los hooks ARC de elemento. Ya no hace falta un
`NativeSubset.ae` separado.

El formateo nativo existente de doubles usa `%g`, por lo que el listado muestra
`1500`/`250` donde AST muestra `1500.0`/`250.0`; las validaciones y toda la
lógica coinciden. `transactionLabel` construye una etiqueta owned mediante
`category + ": " + description`, y `Main.ae` valida su `byteLength`.
`Main.ae` también obtiene el identificador `2` con `parseInt("2")` y el monto
`250.0` con `parseDouble("250.0")`; sólo consume `value` tras comprobar
`ParseStatus.Success` y demuestra el manejo de un monto con whitespace como
`InvalidFormat`. Split/trim y formatting siguen fuera del ejemplo.

La Fase 2 confirma además que `List<Transaction>` conserva aliasing en
assignment/parámetros/returns, que `copy()` crea un objeto y buffer exteriores
independientes y que strings/structs siguen su lifecycle. El objeto List tiene
strong RC y destrucción final.

La Fase 3 añade un slice `transactions[0:1]`: el resultado conserva strings y
structs mediante `copy_init`, pero reemplazar su `Transaction` no cambia el
slot correspondiente de la lista original.

Las Fases 4–5 hacen `const` read-only por alias y convierten los recorridos de
`Reports.ae` en borrows por elemento. Resumen y listado no copian cada
`Transaction`; `matches.push(transaction)` es la adquisición owning normal que
copia el struct y retiene sus strings.

## Límites deliberados

- No hay argumentos de proceso ni `main(args)`.
- No hay archivos, CSV, `split` o `trim`.
- No hay conversiones implícitas ni otras APIs generales de texto.
- Las fechas no se validan ni se ordenan.
- No se agregaron excepciones, GC ni destructores.

El estado y la estrategia de layout están documentados en
[`EXPENSE_TRACKER_DOGFOOD_REPORT.md`](../../docs/aether/EXPENSE_TRACKER_DOGFOOD_REPORT.md).
La baseline de ownership está en
[`COLLECTION_MIGRATION_BASELINE.md`](../../docs/aether/COLLECTION_MIGRATION_BASELINE.md).
