# Expense tracker dogfood example

Este ejemplo modular prueba el núcleo generalista de Aether con un dominio no
matemático. Modela ingresos y gastos, valida montos, mantiene una
`List<Transaction>`, resume, filtra y lista transacciones. No pretende ser
todavía una aplicación financiera persistente.

## Estructura

- `Transaction.ae`: enum y struct nominal del dominio; la fecha es `string`.
- `Ledger.ae`: alta validada en `List<Transaction>`.
- `Reports.ae`: resumen, filtro e impresión mediante `for-in`.
- `Main.ae`: demostración completa en memoria y sus once validaciones.

## AST y native

Desde la raíz del repositorio:

```bash
aether --backend=ast examples/expense_tracker/Main.ae
aether --backend=native examples/expense_tracker/Main.ae
```

El mismo programa completo funciona en ambos backends. LLVM almacena cada
`Transaction` por valor en un buffer contiguo, obtiene su tamaño del layout del
target y conserva los punteros de sus literales `string` durante get/set,
crecimiento y filtrado mediante los hooks ARC de elemento. Ya no hace falta un
`NativeSubset.ae` separado.

El formateo nativo existente de doubles usa `%g`, por lo que el listado muestra
`1500`/`250` donde AST muestra `1500.0`/`250.0`; las once validaciones y toda la
lógica coinciden. Los strings son handles a objetos ARC; concat, parsing y las
otras APIs públicas de producción dinámica siguen fuera del ejemplo.

La Fase 2 confirma además que `List<Transaction>` conserva aliasing en
assignment/parámetros/returns, que `copy()` crea un objeto y buffer exteriores
independientes y que strings/structs siguen su lifecycle. El objeto List tiene
strong RC y destrucción final.

La Fase 3 añade un slice `transactions[0:1]`: el resultado conserva strings y
structs mediante `copy_init`, pero reemplazar su `Transaction` no cambia el
slot correspondiente de la lista original.

## Límites deliberados

- No hay argumentos de proceso ni `main(args)`.
- No hay archivos, CSV, parsing numérico, `split` o `trim`.
- No hay concat ni APIs generales de parsing/construcción dinámica de strings.
- Las fechas no se validan ni se ordenan.
- No se agregaron excepciones, GC ni destructores.

El estado y la estrategia de layout están documentados en
[`EXPENSE_TRACKER_DOGFOOD_REPORT.md`](../../docs/aether/EXPENSE_TRACKER_DOGFOOD_REPORT.md).
La baseline de ownership está en
[`COLLECTION_MIGRATION_BASELINE.md`](../../docs/aether/COLLECTION_MIGRATION_BASELINE.md).
