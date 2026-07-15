# Expense tracker dogfood example

Este ejemplo modular prueba el núcleo generalista de Aether con un dominio no
matemático. Modela ingresos y gastos, valida montos, mantiene una lista en
memoria, calcula un resumen, filtra por tipo y muestra transacciones legibles.
No pretende ser todavía una aplicación de finanzas utilizable.

## Estructura

- `Transaction.ae`: enum y struct del dominio. La fecha permanece como
  `string` porque Aether no tiene un tipo temporal.
- `Ledger.ae`: alta en una `List<Transaction>` con
  `AddTransactionStatus`, sin excepciones ni sentinels.
- `Reports.ae`: resumen, filtro por tipo e impresión.
- `Main.ae`: demostración completa en memoria y validaciones de ingreso, gasto,
  monto inválido, lista vacía y múltiples transacciones.
- `NativeSubset.ae`: subconjunto que prueba el modelo y la agregación sin
  `List<Transaction>`, para delimitar con precisión el soporte LLVM actual.

## Ejecución disponible

Desde la raíz del repositorio:

```bash
aether --backend=ast examples/expense_tracker/Main.ae
aether --backend=ast examples/expense_tracker/NativeSubset.ae
aether --backend=llvm examples/expense_tracker/NativeSubset.ae
```

`Main.ae` es funcional en AST: agrega un ingreso y un gasto, rechaza un monto
no positivo, lista ambos, calcula ingresos/gastos/balance y filtra gastos por
`TransactionType`.

`NativeSubset.ae` produce la misma salida en AST y LLVM. Demuestra que un enum
dentro de un struct, sus campos `string`, parámetros y retornos de structs y la
agregación escalar sí funcionan nativamente.

## Estado native del programa completo

`Main.ae` no compila completamente con LLVM. `List<Transaction>` atraviesa
frontend, IR y SSA, pero el emisor LLVM falla al calcular el tamaño del elemento
struct:

```text
LLVM backend does not know the size of struct ...Transaction
```

El error llega demasiado tarde y expone un detalle interno; debería ser un
diagnóstico temprano de capacidad hasta que exista layout/copia/ownership para
elementos struct. El ejemplo no reemplaza la lista por arrays paralelos porque
eso ocultaría la carencia que pretende revelar.

## CLI deseada y CLI real

La interfaz objetivo sería:

```bash
aether run Main.ae -- add expense 250.0 food 2026-07-15 Dinner
aether run Main.ae -- list
aether run Main.ae -- summary
```

No está implementada. Aether no expone argumentos del proceso y `main` no
acepta parámetros; además, el CLI del compilador no separa argumentos propios
de argumentos para el programa. `Main.ae` invoca las operaciones directamente
con datos de demostración y no afirma interpretar comandos.

## Persistencia deseada y persistencia real

No existe una API Aether para abrir, leer, escribir, anexar o cerrar archivos.
Por eso no hay `Storage.ae`: declarar estados y funciones que nunca acceden a
un archivo sería una API ficticia. CSV sigue siendo el formato recomendado
cuando exista IO textual mínimo, junto con un resultado nominal que distinga
éxito, archivo inexistente, datos inválidos y fallo de escritura.

## Otras limitaciones

- Las fechas son strings sin validación, orden temporal ni parsing.
- Igualdad, concatenación e interpolación de strings funcionan en AST, pero no
  pertenecen al subconjunto native general.
- No hay parsing de `int`/`double` desde string, `split` ni `trim`; esto también
  bloquea una futura carga CSV y el parsing de CLI.
- `input` tipado existe solo en AST y no sustituye archivos ni argumentos.
- `Map` no existe, pero no bloquea este ejemplo: resumen y filtro se expresan
  con loops y listas. Solo mejoraría reportes agrupados por categoría.
- No se implementaron JSON, excepciones native, fechas, argumentos, archivos o
  un runtime nuevo de strings para hacer pasar la demo.

El diseño objetivo y la auditoría por capacidad están en
[`EXPENSE_TRACKER_DOGFOOD_REPORT.md`](../../docs/aether/EXPENSE_TRACKER_DOGFOOD_REPORT.md).
