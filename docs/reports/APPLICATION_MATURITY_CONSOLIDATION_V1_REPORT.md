# Aether — APPLICATION-MATURITY-CONSOLIDATION-V1

Estado: **CLOSED**

Fecha: 2026-11-23

Checkout evaluado: `main` @ `3c5c451854cbddb2d5296ed1873ae837a5e03908`

## 1. Resultado

Los tres consumers de `examples/assessment/` conservan sus resultados, errores,
códigos de salida y formatos en O0/O2. Dos programas mejoran de forma
comprobable:

- Expense Tracker vuelve a expresar la carga como un único `LoadResult` con el
  `List<Expense>` owning y su `LoadStatus`. El workaround `ref mut` + status
  separado ya no es necesario después de `OWNING-COLLECTION-FIELDS-V1`.
- Data Processor observa header, líneas y campos por índice. Ya no destruye
  listas con `remove(0)` para consultar strings, y su scan de líneas pasa de
  O(n²) a O(n).
- Expense Tracker aplica la misma observación indexada al scan del archivo. Sólo
  conserva `remove(fields, 1)` porque allí sí extrae el owner de la descripción
  para moverlo a `Expense`.
- Numerical Solver no necesitaba refactor. Sus resultados LU/QR y negativos se
  volvieron a ejecutar sin modificar la OAL.

No se modificaron compiler, frontend, SSA, runtime, STD, OAL, APIs públicas,
formatos persistidos ni ejemplos oficiales ajenos al assessment.

## 2. Preflight y preservación

El preflight observó:

- rama `main`, alineada con `origin/main`;
- HEAD `3c5c4518 refactor(examples): simplify scientific curve fitting`;
- staging vacío;
- cambios locales previos en `hir.rs`, `ssa.rs` y
  `examples/ProbandoNR/probandoNR2.ae`;
- suites, fixtures y reportes no versionados de F1/F2;
- `docs/reports/APPLICATION_MATURITY_ASSESSMENT_V1.md` y todo
  `examples/assessment/` todavía no versionados;
- otros artefactos ajenos no versionados, incluidos
  `examples/ProbandoNR/.aether-package.lock` y `tmp_lambda_test.ae`.

Todos esos cambios se preservaron. No se editó `examples/ProbandoNR` ni código
productivo. Una `.aether-package.lock` vacía creada por las ejecuciones bajo
`numerical-solver` fue detectada y eliminada antes del cierre.

Se inspeccionaron los reportes CLOSED de F1/F2, su arquitectura y fixtures, el
assessment original, los tres programs, `examples/expense_tracker` y
`examples/word_stats`. El tracker histórico confirma el patrón agregado
`LedgerDecodeResult`, mutación de `Ledger.transactions` y observación indexada de
argumentos; no fue reescrito.

## 3. Expense Tracker

### Antes

La carga deformaba su frontera para mantener separado el owner de la colección:

```aether
LoadStatus loadExpenses(ref string path, ref mut List<Expense> expenses) { ... }

List<Expense> expenses = {};
LoadStatus loadStatus = loadExpenses(arguments[0], &mut expenses);
```

Además consumía el frente de `lines` aun cuando sólo necesitaba observarlo.

### Después

```aether
struct LoadResult {
    List<Expense> expenses;
    LoadStatus status;
}

LoadResult loadExpenses(ref string path) {
    LoadResult result = LoadResult({}, LoadStatus.Success);
    // ...
    push(result.expenses, Expense(amount, description));
    return result;
}

LoadResult loaded = loadExpenses(arguments[0]);
```

`result` es el owner único durante la carga; el retorno transfiere el aggregate
completo y `main` conserva su único cleanup recursivo. Los retornos tempranos
después de haber cargado registros también retornan el aggregate, y el caller lo
destruye al salir por el status de error. No se introdujeron Clone, Alias,
retains ni reemplazos owning artificiales.

El `push(result.expenses, ...)` cubre el field owning y su growth; el segundo
`add`, en otro proceso, muta `loaded.expenses` después del retorno del aggregate.
La suite de F1 volvió a comprobar growth repetido, reserve, retorno, cleanup
normal/unwind, balance de heap/strings y ASan en O0/O2.

El scan usa un índice estable:

```aether
List<string> fields = std.Text.split(lines[lineIndex], "\t");
match (std.Text.parseDouble(fields[0])) { ... }
string description = remove(fields, 1);
```

Las dos primeras operaciones sólo observan. El último `remove` se conserva
porque transfiere el owner de `description` al nuevo `Expense`. En función del
número de líneas, el componente de recorrido de la carga pasa de O(n²), por
desplazar el frente de `lines`, a O(n). El codec y la concatenación de salida no
cambian.

El formato persistido continúa siendo exactamente:

```text
12.5<TAB>lunch<LF>
7.25<TAB>taxi<LF>
```

SHA-256: `e0293676ec66be329261a9388b33ac287ecf09bb676e4f9e23805d8ebd754616`.

## 4. Data Processor

### Antes

```aether
string headerLine = remove(lines, 0);
string header = std.Text.trim(headerLine);
while (length(lines) > 0) {
    string rawLine = remove(lines, 0);
    // ...
    string rawId = remove(fields, 0);
    string rawValue = remove(fields, 0);
}
```

Ninguno de esos owners se transfería a una estructura persistente; todos se
extraían sólo para consultar o producir el string nuevo de `trim`.

### Después

```aether
string header = std.Text.trim(lines[0]);
usize lineIndex = 1;
while (lineIndex < length(lines)) {
    string line = std.Text.trim(lines[lineIndex]);
    List<string> fields = std.Text.split(line, ",");
    string idToken = std.Text.trim(fields[0]);
    string valueToken = std.Text.trim(fields[1]);
    // ...
    lineIndex = lineIndex + 1;
}
```

El dataset válido sigue ejecutando exactamente cuatro iteraciones de registros:
el header se observa una vez y el cursor recorre los índices 1..4 en orden. No
se remueven ni reordenan filas. El scan de `lines` deja de hacer desplazamientos
lineales repetidos y pasa de O(n²) a O(n); cada fila conserva parsing y trabajo
O(1) respecto de sus dos campos, aparte del coste proporcional al texto de las
operaciones Text.

El archivo exacto sigue siendo:

```text
count=4
sum=70
average=17.5
```

con LF final y SHA-256
`6306fe4e7fef05e3e4c1b4bdf2dd62c74fbbfa26e7325dadffc2e8ac8de3da4b`.

## 5. Beneficios reales de F1 y F2

`OWNING-COLLECTION-FIELDS-V1` aporta una mejora semántica directa al consumer:
permite mutar, hacer crecer, retornar y finalmente destruir la colección owning
dentro de `LoadResult`. La API deja de exponer un parámetro `ref mut` incidental
y vuelve a reunir payload y estado.

`INDEX-DEREFERENCE-DIAGNOSTIC-V1` no habilitó programas nuevos. Su beneficio es
hacer causal el error: `*lines[0]` no crea un borrow y ahora informa E0271, en
vez del E0293 secundario. Las formas usadas por estos refactors,
`std.Text.trim(lines[0])` y el borrow explícito `&lines[0]`, ya representan
borrows compartidos call-scoped. La consolidation elimina el workaround
destructivo usando ese contrato correcto, sin atribuir a F2 una ampliación de
semántica.

## 6. Numerical Solver

No se cambió el source. O0 y O2 volvieron a producir:

```text
LU x = [1, 2]
LU residual norm = 0
QR x = [1.0000000000000002, 1.9999999999999998]
QR residual norm = 8.881784197001252e-16
```

`singular-lu` captura `SingularMatrixException` y `singular-qr` captura
`RankDeficientMatrixException`, ambos con exit 0 en ambos perfiles. El caso
`dimension-mismatch` conserva exit 1 y el diagnóstico pendiente:

```text
aether: error: program terminated without a representable exit status
```

F3 continúa abierto; no se modificó Linear Algebra, runtime ni CLI.

## 7. Qualification O0/O2

Se ejecutaron 36 procesos de aplicación, todos con el resultado esperado.

| Consumer | Caso | O0 | O2 | Comparación con assessment V1 |
|---|---|---:|---:|---|
| Numerical | normal LU/QR | exit 0 | exit 0 | output idéntico |
| Numerical | singular LU/QR | exit 0 | exit 0 | excepciones idénticas |
| Numerical | dimension mismatch | exit 1 | exit 1 | fallo opaco preservado |
| Data | 4 registros, suma 70, promedio 17.5 | exit 0 | exit 0 | stdout/archivo idénticos |
| Data | vacío/header/value/fila inválidos | exit 2 | exit 2 | mensajes idénticos |
| Data | read y write error | exit 2 | exit 2 | mensajes idénticos |
| Expense | add 12.5; add 7.25; list; total | exit 0 | exit 0 | procesos/output idénticos |
| Expense | archivo corrupto | exit 3 | exit 3 | mensaje idéntico |
| Expense | monto inválido | exit 2 | exit 2 | mensaje idéntico |
| Expense | error de escritura | exit 4 | exit 4 | mensaje idéntico |

Los archivos Data O0/O2 fueron byte a byte idénticos. Los ledgers Expense O0/O2
también fueron byte a byte idénticos. `list` mostró `lunch` y `taxi` en ese
orden; `total` imprimió `19.75`.

## 8. Tests focales y gates

Tests focales ejecutados:

| Suite | Resultado |
|---|---:|
| `owning_collection_fields_v1` | 6/6 PASS |
| `index_dereference_diagnostic_v1` | 4/4 PASS |
| List Vertical-14 | 7/7 PASS |
| owning collections Vertical-16 | 2/2 PASS |
| `text_v1` | 8/8 PASS |
| `io_v1` | 12/12 PASS |
| `process_args_v1` | 9/9 PASS |
| `linear_algebra_solve_v1` | 9/9 PASS |
| `linear_algebra_qr_solve_v1` | 6/6 PASS |
| `expense_tracker_next_port_complete` | 3/3 PASS |

Total focal: **66 pass, 0 fail**.

Gates:

| Gate | Resultado |
|---|---|
| consumers `check` O0/O2 (3 × 2) | PASS |
| qualification de aplicaciones O0/O2 | 36/36 PASS |
| `cd compiler-next && cargo check --workspace` | PASS |
| `cd compiler-next && cargo fmt --all --check` | PASS |
| `git diff --check` | PASS |

Se omitieron Clippy y `cargo test --workspace`: el cambio efectivo sólo toca dos
programas Aether y este reporte; no modifica Rust ni superficies compartidas, y
las suites focales cubren las capacidades ejercidas. Tampoco se repitió el
`cargo check` del workspace legacy `compiler-rs`; su F4 preexistente permanece
fuera de alcance, igual que en el assessment original.

## 9. Problemas pendientes

- F3: el mismatch dinámico de dimensiones sigue terminando sin diagnóstico
  representable.
- F4: el workspace legacy `compiler-rs` conserva el fallo exhaustivo documentado
  en el assessment original.
- F5–F7 del assessment original no cambian: documentación IO legacy, ausencia de
  codec estructurado general y opciones globales de CLI.
- Los formatos locales del assessment siguen siendo deliberadamente
  restringidos; no se declara CSV general ni ALPT1 para este tracker pequeño.

## 10. Archivos modificados por esta consolidation

- `examples/assessment/expense-tracker/src/main.ae`;
- `examples/assessment/data-processor/src/main.ae`;
- `docs/reports/APPLICATION_MATURITY_CONSOLIDATION_V1_REPORT.md`.

`examples/assessment/numerical-solver/src/main.ae` fue inspeccionado y
calificado, pero no modificado. No se hizo commit ni push.

## 11. Cierre

Los consumers preservan su funcionalidad observable en O0/O2, la persistencia
es byte-exacta, F1 elimina el workaround de la API de carga y la observación
indexada elimina scans destructivos sin introducir Clone/Alias ni O(n²).
Por tanto **APPLICATION-MATURITY-CONSOLIDATION-V1 queda CLOSED**.
