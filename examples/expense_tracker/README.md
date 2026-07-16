# Expense tracker dogfood example

Este ejemplo modular prueba el núcleo generalista de Aether con un dominio no
matemático. Modela ingresos y gastos, valida montos, mantiene una
`List<Transaction>`, resume, filtra, lista y persiste transacciones mediante el
formato versionado ALPT1.

## Estructura

- `Transaction.ae`: enum y struct nominal del dominio; la fecha es `string`.
- `Ledger.ae`: alta validada en `List<Transaction>`.
- `Reports.ae`: resumen, filtro e impresión mediante `for-in`.
- `Persistence.ae`: codec ALPT1 puro y wrappers explícitos de load/save.
- `Main.ae`: CLI mínima y demostración completa en memoria con validaciones de
  dominio, collections y strings dinámicas.

## AST y native

Desde la raíz del repositorio:

```bash
aether run examples/expense_tracker/Main.ae
aether run examples/expense_tracker/Main.ae -- expenses.alpt add expense 3 19.95 food "Lunch with friends" 2026-07-16
aether run examples/expense_tracker/Main.ae -- expenses.alpt add income 4 100.0 work "Side project" 2026-07-17
aether run examples/expense_tracker/Main.ae -- expenses.alpt list
aether run examples/expense_tracker/Main.ae -- expenses.alpt summary
aether run examples/expense_tracker/Main.ae -- persist-check /tmp/aether-summary.txt
aether run examples/expense_tracker/Main.ae -- split-check , "food,,work"
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
antes de construir la transacción. `split-check <separator> <text>` ejercita
la primitiva byte-based preservando campos vacíos; es sólo una inspección de
texto simple, no un parser CSV ni un formato persistente.

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

El primer argumento de la CLI persistente es siempre el path. Un archivo
inexistente se trata como ledger vacío; `add` guarda sólo después de una carga
completa válida. `list` y `summary` sobre un path inexistente muestran el
estado vacío. Un archivo corrupto o de versión incompatible nunca se
sobrescribe automáticamente. Exit codes: `2` uso/dominio, `3` carga/formato y
`4` guardado; éxito usa `0`.

ALPT1 incluye los seis fields (`id`, `type`, `amount`, `category`,
`description`, `date`), usa payloads length-prefixed en bytes UTF-8 y nombres
estables de enum. El writer es canónico. El parser es fail-closed, acepta fields
aditivos desconocidos según la RFC y rechaza duplicados, faltantes, tipos,
versiones, framing y trailing data inválidos.

`persist-check <path>` se conserva como dogfood aislado de archivos de texto:
escribe un resumen fijo, lo relee y hace append de `verified\n`. Ese archivo
auxiliar no es el ledger ni CSV; la CLI `add|list|summary` usa ALPT1 y no intenta
parsearlo mediante `split`.

## Límites deliberados

- `main` continúa siendo `int main()`; los argumentos se consultan con
  `System.args()`.
- No hay archivos binarios, JSON, CSV, reflection ni codecs automáticos.
- El guardado actual usa `io.writeText`: puede truncar ante un fallo y no se
  anuncia como atómico.
- No hay conversiones implícitas ni otras APIs generales de texto.
- Las fechas no se validan ni se ordenan.
- No se agregaron excepciones, GC ni destructores.

El estado y la estrategia de layout están documentados en
[`EXPENSE_TRACKER_DOGFOOD_REPORT.md`](../../docs/aether/EXPENSE_TRACKER_DOGFOOD_REPORT.md).
La baseline de ownership está en
[`COLLECTION_MIGRATION_BASELINE.md`](../../docs/aether/COLLECTION_MIGRATION_BASELINE.md).
