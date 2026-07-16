# Expense tracker dogfood example

Este ejemplo modular prueba el núcleo generalista de Aether con un dominio no
matemático. Modela ingresos y gastos, valida montos, mantiene una
`List<Transaction>`, resume, filtra y lista transacciones. No pretende ser
todavía una aplicación financiera persistente.

## Estructura

- `Transaction.ae`: enum y struct nominal del dominio; la fecha es `string`.
- `Ledger.ae`: alta validada en `List<Transaction>`.
- `Reports.ae`: resumen, filtro e impresión mediante `for-in`.
- `Main.ae`: CLI mínima y demostración completa en memoria con validaciones de
  dominio, collections y strings dinámicas.

## AST y native

Desde la raíz del repositorio:

```bash
aether run examples/expense_tracker/Main.ae
aether run examples/expense_tracker/Main.ae -- add expense 3 19.95 food "Lunch with friends"
aether run examples/expense_tracker/Main.ae -- add income 4 100.0 work "Side project"
aether run examples/expense_tracker/Main.ae -- list
aether run examples/expense_tracker/Main.ae -- summary
```

Sin argumentos se ejecuta el dogfood histórico completo. Con argumentos,
`System.args()` entrega el comando y sus operandos como un snapshot
`Array<string>`; `--` pertenece al CLI de Aether y no llega al programa. El
shell conserva una descripción entre comillas como un único argumento.

El mismo programa completo funciona en AST y native. LLVM almacena cada
`Transaction` por valor en un buffer contiguo, obtiene su tamaño del layout del
target y conserva los handles de sus valores `string` durante get/set,
crecimiento y filtrado mediante los hooks ARC de elemento. Ya no hace falta un
`NativeSubset.ae` separado.

El formateo nativo existente de doubles usa `%g`, por lo que el listado muestra
`1500`/`250` donde AST muestra `1500.0`/`250.0`; las validaciones y toda la
lógica coinciden. `transactionLabel` construye una etiqueta owned mediante
`category + ": " + description`, y `Main.ae` valida su `byteLength`.
`Main.ae` también obtiene el identificador `2` desde `" 2 "` y el monto
`250.0` desde `"\t250.0\n"` aplicando `.trim()` antes de los parsers; sólo
consume `value` tras comprobar `ParseStatus.Success`. Una llamada directa sin
trim sigue produciendo `InvalidFormat`, y descripción/categoría se recortan
antes de construir la transacción. Split y formatting siguen fuera del
ejemplo.

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

Cada proceso parte de una lista nueva. `add` demuestra validación y construcción
de la transacción, pero no persiste el alta; `list` y `summary` operan sobre dos
transacciones de demostración creadas en esa ejecución.

## Límites deliberados

- `main` continúa siendo `int main()`; los argumentos se consultan con
  `System.args()`.
- No hay archivos, CSV ni `split`.
- No hay conversiones implícitas ni otras APIs generales de texto.
- Las fechas no se validan ni se ordenan.
- No se agregaron excepciones, GC ni destructores.

El estado y la estrategia de layout están documentados en
[`EXPENSE_TRACKER_DOGFOOD_REPORT.md`](../../docs/aether/EXPENSE_TRACKER_DOGFOOD_REPORT.md).
La baseline de ownership está en
[`COLLECTION_MIGRATION_BASELINE.md`](../../docs/aether/COLLECTION_MIGRATION_BASELINE.md).
