# Expense Tracker para `compiler-next`

Aplicación modular que registra ingresos y gastos en un ledger ALPT1 persistente.
Los comandos `add`, `list` y `summary` son procesos independientes: cada
invocación carga el archivo completo, lo valida de forma fail-closed y, cuando
corresponde, publica una nueva versión mediante reemplazo atómico.

## Estructura

- `main.ae`: CLI y validación de argumentos.
- `Transaction.ae`: `TransactionType`, `Transaction` y `Ledger`.
- `Ledger.ae`: alta validada de transacciones.
- `Reports.ae`: listado y resumen.
- `Persistence.ae`: codec ALPT1, carga y guardado atómico.

## Uso

Desde la raíz del repositorio:

```bash
aether examples/expense_tracker/main.ae --compiler next -- expenses.alpt add expense 3 19.95 food "Lunch with friends" 2026-07-16
aether examples/expense_tracker/main.ae --compiler next -- expenses.alpt add income 4 100.0 work "Side project" 2026-07-17
aether examples/expense_tracker/main.ae --compiler next -- expenses.alpt list
aether examples/expense_tracker/main.ae --compiler next -- expenses.alpt summary
```

El separador `--` termina las opciones del compilador; todo lo posterior llega
al programa mediante `std.Process.args()`. Para O2:

```bash
aether examples/expense_tracker/main.ae --compiler next -O2 -- expenses.alpt summary
```

La forma nativa explícita también está disponible:

```bash
compiler-next/target/debug/aether-next build examples/expense_tracker/main.ae -O2 -o expense
./expense expenses.alpt summary
```

`add` requiere exactamente:

```text
<ledger.alpt> add <expense|income> <id> <amount> <category> <description> <date>
```

El ID debe ser un `int` válido. El monto debe ser un `double` finito y mayor que
cero. Categoría, descripción y fecha son strings; espacios, UTF-8, `:` y saltos
de línea se conservan si el shell los entrega dentro de un único argumento.

## Persistencia y errores

Un archivo inexistente representa un ledger vacío. `list` y `summary` no lo
crean; `add` lo crea al publicar la primera transacción. Un ALPT1 corrupto,
incompatible o con trailing data se rechaza entero y nunca se transforma en un
estado parcial ni se sobrescribe automáticamente.

Exit codes:

- `0`: éxito;
- `2`: uso o dato de dominio inválido;
- `3`: fallo de carga o formato;
- `4`: fallo de guardado.

El writer emite ALPT1 revision 1 canónico con payloads length-prefixed en bytes
UTF-8. `std.File.writeTextAtomic` garantiza que observers vean el archivo
anterior o el nuevo completo y que un fallo anterior al publish preserve el
anterior. Reemplazo atómico no significa durabilidad ante power loss: no se
hace `fsync`, no hay locking y writers concurrentes usan
last-successful-rename-wins.

El demo histórico sin argumentos, `split-check` y `persist-check` no forman
parte de esta CLI. Eran checks de dogfood; `persist-check` dependía de
`appendText`, innecesario para la persistencia ALPT1 real.
