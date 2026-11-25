# Aether — Application Maturity Assessment V1

Estado: **ASSESSMENT COMPLETE**

Fecha: 2026-11-22

Checkout evaluado: `main` @ `3c5c451854cbddb2d5296ed1873ae837a5e03908`

## 1. Resumen ejecutivo

Las tres aplicaciones fueron escritas, compiladas y ejecutadas como consumidores
Aether reales en O0 y O2. Ninguna quedó bloqueada.

- El solver numérico es el caso más maduro: LU y QR resuelven el mismo sistema,
  las operaciones matriciales permiten calcular el residuo directamente y las
  excepciones de singularidad son nominales y recuperables.
- IO, argumentos de proceso, parsing numérico y escritura de texto alcanzan para
  aplicaciones de datos y CLI pequeñas, con errores nominales útiles.
- Las principales fricciones están en ownership de strings/colecciones y en el
  paso SSA al mutar una colección owning guardada dentro de un struct.
- El diagnóstico de contratos de forma en runtime no es accionable desde la CLI:
  una dimensión incompatible termina sólo como `program terminated without a
  representable exit status`.
- El Expense Tracker histórico sí funciona hoy en procesos separados y en O0/O2,
  pero su codec robusto ocupa 526 líneas. La falta de un formato estructurado en
  std/OAL desplaza mucho código incidental a la aplicación.
- La documentación de IO en el README raíz está desactualizada respecto de la
  superficie y garantías realmente implementadas.

El objetivo de lenguaje general con ergonomía científica está demostrado para
programas numéricos densos pequeños. Para aplicaciones generales, las
capacidades base existen, pero ownership, codecs y algunos diagnósticos aún
imponen boilerplate desproporcionado.

## 2. Preflight

### Checkout y cambios

- Rama: `main`.
- HEAD: `3c5c4518 refactor(examples): simplify scientific curve fitting`.
- `git status --short` estaba vacío antes del assessment.
- No se modificó compiler, runtime, std, OAL ni ejemplos existentes.
- Los únicos sources nuevos están bajo `examples/assessment/`; el único documento
  nuevo es este reporte.

### CLI y packages

La CLI vigente es el binario Rust `aether` de `compiler-next/crates/aether-cli`.
Se usó directamente desde el checkout:

```text
compiler-next/target/debug/aether
```

Superficie observada: `run`, `build`, `check`, `init`, `sync`, `update`, `add`,
`remove`, `publish`, `env`, `install` y `uninstall`; perfiles `-O0` y `-O2`.
Los targets directory exigen `aether.toml`, usan `src/main.ae` por defecto y
generan `aether.lock`. Los tres proyectos del assessment siguen esa estructura.

No hay `Cargo.toml` en la raíz. Existen dos workspaces Rust independientes:
`compiler-next/` y `compiler-rs/`.

### std, OAL y ejemplos relevantes

Superficie ejecutada:

- `std.Process.args()`;
- `std.File.readText`, `writeText` y `writeTextAtomic`;
- `std.IO.IOException`, `InvalidTextEncodingException` y excepciones nominales
  de archivo;
- `std.Text.lines`, `split`, `trim`, `contains`, `parseInt` y `parseDouble`;
- `Array<T>`, `List<T>`, `push`, `remove`, iteración e indexación;
- matrices, vectores columna, producto matriz-vector y resta;
- `linearAlgebra.solve`, `lu`, `qr`, `dot`, `leastSquares` y `svd`.

OAL oficiales instaladas en el checkout:

| Package | Manifest | Dependencias |
|---|---|---|
| `linearAlgebra` | `linearAlgebra/aether.toml` | ninguna |
| `graphics` | `graphics/aether.toml` | ninguna |
| `plots` | `plots/aether.toml` | `graphics` por path |

Se inspeccionaron y usaron como evidencia adicional:

- `examples/scientific-curve-fitting`;
- `examples/expense_tracker`;
- `examples/word_stats`;
- reportes CLOSED de Linear Algebra, IO, Text, Process args, File atomic write,
  ownership y Expense Tracker bajo `docs/architecture/`.

La documentación y los tests históricos sólo orientaron el trabajo. Las
conclusiones funcionales de este reporte se basan en ejecuciones nuevas.

## 3. Matriz de capacidades

| Capacidad | Numerical Solver | Data Processor | Expense Tracker | Estado observado |
|---|---:|---:|---:|---|
| Package directory + dependencia path | sí | sí | sí | funciona en O0/O2 |
| Argumentos CLI | modos de error | input/output | help/add/list/total | funciona; array owning explícito |
| IO de archivo real | — | read/write | read/atomic write | funciona; errores nominales |
| Strings y parsing numérico | output | int/double | double | funciona, con fricción de ownership |
| Colecciones | vectores | `List<double>` | `List<Expense>` | funciona para locals; field owning expone E0400 |
| Persistencia entre procesos | — | output nuevo | sí | funciona en O0/O2 |
| Álgebra matricial | LU y QR | — | — | madura para el caso evaluado |
| SVD/least squares | evidencia complementaria | — | — | curve fitting ejecutado en O0/O2 |
| Errores recuperables | singular/rank deficient | IO/input | IO/input/corrupción | nominales salvo shape traps |
| Diagnóstico de dimensiones | trap | — | — | insuficiente desde CLI |
| Output verificable | números | archivo exacto | archivo + total | coincide con oráculos externos |

## 4. Aplicación A — Numerical Solver

### Requisitos y diseño

El programa usa:

```text
A = [[3, 1], [1, 2]]
b = [5, 5]
x esperado = [1, 2]
```

Resuelve el sistema con dos APIs públicas independientes:

1. `la.solve(A, b)`, que usa la ruta LU preservando inputs;
2. `la.qr(A)` seguido de `la.solve(factor, b)`.

Para ambas calcula `r = A * x - b` y
`sqrt(la.dot(r, r))`. El vector se declara explícitamente como
`Vector<float64,Column>` y la indexación pública observada es 1-based.

Source: `examples/assessment/numerical-solver/src/main.ae`, 71 líneas:
aproximadamente 24 de solve/residuo/output, 29 de casos negativos y 12 de CLI.

### Compilación y ejecución

Comandos reales:

```text
compiler-next/target/debug/aether check examples/assessment/numerical-solver -O0
compiler-next/target/debug/aether run examples/assessment/numerical-solver -O0 -- normal
compiler-next/target/debug/aether run examples/assessment/numerical-solver -O2 -- normal
```

Output observado, idéntico en O0/O2:

```text
LU x = [1, 2]
LU residual norm = 0
QR x = [1.0000000000000002, 1.9999999999999998]
QR residual norm = 8.881784197001252e-16
```

El oráculo Python independiente produjo `x=(1,2)` y norma `0.0`. El residuo QR
observado es consistente con redondeo IEEE y está muy por debajo de `1e-12`.

### Casos límite e inválidos

| Caso | O0 | O2 | Resultado observado |
|---|---:|---:|---|
| matriz singular, LU | exit 0 | exit 0 | se captura `SingularMatrixException` |
| matriz rank-deficient, QR | exit 0 | exit 0 | se captura `RankDeficientMatrixException` |
| `b` de dimensión 1 para A 2x2 | exit 1 CLI | exit 1 CLI | trap sin diagnóstico de dimensiones |
| vector RHS con orientación `Row` | check exit 1 | no aplica | E0460 lista sólo overloads `Column`/Matrix |

El caso de dimensión incompatible imprime únicamente:

```text
aether: error: program terminated without a representable exit status
```

La orientación incompatible sí se rechaza estáticamente y el diagnóstico enumera
las ocho familias de overloads disponibles.

### SVD y aplicación científica existente

Se ejecutó el consumer oficial `examples/scientific-curve-fitting` desde un
directorio temporal, no sólo sus tests o documentación:

```text
/home/blasm/proyectos/Aether/compiler-next/target/debug/aether run \
  /home/blasm/proyectos/Aether/examples/scientific-curve-fitting -O0
/home/blasm/proyectos/Aether/compiler-next/target/debug/aether run \
  /home/blasm/proyectos/Aether/examples/scientific-curve-fitting -O2
```

Ambas ejecuciones observaron:

```text
fit: y = 1.0000000000000002 + 1.9999999999999996x
SSE: 4
SVG: curve_fit.svg
```

El SVG tuvo 10 016 bytes en ambos perfiles. Esto demuestra en ejecución la ruta
SVD de `leastSquares`, producto matriz-vector, residuo, `dot` e integración con
Plots/Graphics.

### Coste y limitaciones

El happy path es legible y compacto. Los inputs preservados permiten reutilizar
`A` y `b` sin copias explícitas. Las limitaciones observadas son el índice 1-based
—correcto pero fácil de omitir sin documentación cercana— y el trap opaco para
shapes dinámicos inválidos.

Estado funcional: **PASS**.

## 5. Aplicación B — Data Processor

### Requisitos y parser

El programa recibe `<input.csv> <output.txt>`, lee UTF-8 real, valida el header,
procesa múltiples filas, usa `parseInt`/`parseDouble`, acumula los valores en
`List<double>`, calcula cantidad/suma/promedio y escribe un archivo nuevo.

El parser es deliberadamente mínimo. Sólo admite exactamente dos campos por
línea separados por una coma. No admite comillas, comas escapadas, CR/LF dentro
de campos ni dialectos CSV. Por tanto este assessment **no** declara soporte CSV
general.

Source: `examples/assessment/data-processor/src/main.ae`, 88 líneas:
aproximadamente 23 de CLI/IO, 44 de validación/parsing y 21 de agregación/output.

### Compilación y caso válido

```text
compiler-next/target/debug/aether check examples/assessment/data-processor -O0
compiler-next/target/debug/aether run examples/assessment/data-processor -O0 -- \
  /tmp/.../valid.csv /tmp/.../result-O0.txt
compiler-next/target/debug/aether run examples/assessment/data-processor -O2 -- \
  /tmp/.../valid.csv /tmp/.../result-O2.txt
```

Output de proceso y archivo, idéntico en O0/O2:

```text
count=4
sum=70
average=17.5
```

El oráculo Python independiente produjo cantidad `4`, suma `70.0` y promedio
`17.5`.

### Casos inválidos realmente ejecutados

Todos se ejecutaron con archivos bajo `/tmp/aether-assessment-data-*`:

| Entrada | Exit | Output observado |
|---|---:|---|
| archivo vacío | 2 | `error: empty input` |
| header `identifier,value` | 2 | `error: expected header id,value` |
| valor `nope` | 2 | `error: invalid value` |
| fila con sólo `1` | 2 | `error: row must contain exactly two fields` |
| archivo inexistente | 2 | `error: input file not found` |
| output apunta a un directorio | 2 | `error: could not write output file` |

También se validan IDs positivos, overflow/underflow, valores no finitos, filas
vacías y suma no finita; esos branches existen pero no se declaran como
ejecutados en esta ronda salvo donde la tabla lo indica.

### Coste y limitaciones

Las APIs de IO y parsing son claras. El coste incidental está en extraer strings
owning de `List<string>`: `std.Text.trim(*lines[0])` falla con E0293, por lo que
el programa consume las listas con `remove(lines, 0)` y `remove(fields, 0)`.
Esto añade mutación y puede convertir un scan en O(n²) al remover repetidamente
el primer elemento. Un iterador funciona para scans homogéneos, pero el header
especial hace visible la carencia de una lectura/clone ergonómica del elemento.

Estado funcional: **PASS**, con parser local restringido.

## 6. Aplicación C — Expense Tracker CLI

### Reutilización del consumer histórico

Se localizó `examples/expense_tracker`, con 785 líneas de aplicación:

- CLI/model/ledger/reportes: 259 líneas;
- `Persistence.ae`: 526 líneas de codec ALPT1 robusto.

No se asumió que su presencia implicara funcionamiento. Se ejecutó de nuevo en
O0 y O2 sobre archivos temporales, en procesos separados:

```text
compiler-next/target/debug/aether run examples/expense_tracker/main.ae -O0 -- \
  /tmp/.../historical.alpt add expense 1 19.95 food lunch 2026-07-16
compiler-next/target/debug/aether run examples/expense_tracker/main.ae -O0 -- \
  /tmp/.../historical.alpt list
compiler-next/target/debug/aether run examples/expense_tracker/main.ae -O0 -- \
  /tmp/.../historical.alpt summary
```

O0 y O2 produjeron `transaction added: food: lunch`, luego la transacción
persistida y finalmente `expenses: 19.95`, `balance: -19.95`.

Para mantener mínimo el entregable aislado no se duplicó el codec ALPT1. La
aplicación del assessment conserva del consumer histórico su frontera CLI,
parsing nominal, modelo de carga fail-closed, procesos independientes y escritura
atómica. Usa un formato local lineal `amount<TAB>description<LF>` con rechazo de
tabs/newlines en la descripción. No es ALPT1 ni un formato general.

Source: `examples/assessment/expense-tracker/src/main.ae`, 168 líneas:
aproximadamente 16 de modelo/status, 45 de carga/parsing, 20 de persistencia y
87 de ayuda/comandos/validación/reportes.

### Ejecución normal O0/O2

En cada perfil se ejecutaron cuatro procesos sobre el mismo archivo:

```text
... run examples/assessment/expense-tracker -O0 -- /tmp/.../ledger.txt add 12.5 lunch
... run examples/assessment/expense-tracker -O0 -- /tmp/.../ledger.txt add 7.25 taxi
... run examples/assessment/expense-tracker -O0 -- /tmp/.../ledger.txt list
... run examples/assessment/expense-tracker -O0 -- /tmp/.../ledger.txt total
```

Output observado en O0 y O2:

```text
#1 | lunch | 12.5
#2 | taxi | 7.25
total: 19.75
```

Archivo persistido:

```text
12.5<TAB>lunch
7.25<TAB>taxi
```

El oráculo Python independiente produjo `19.75`.

### Ayuda y errores ejecutados

| Caso | Exit | Output observado |
|---|---:|---|
| `help` | 0 | uso de `add`, `list`, `total` |
| monto `nope` | 2 | `error: invalid amount` |
| monto `-1` | 2 | monto debe ser finito y positivo |
| comando desconocido | 2 | error + uso |
| archivo persistido corrupto | 3 | `error: invalid expense file` |
| parent de escritura inexistente | 4 | `error: could not save expenses` |

### Ownership y modularidad

El diseño natural `LoadResult { List<Expense> expenses, LoadStatus status }`
compiló hasta SSA pero falló con E0400 al mutar el field. El programa final usa
`loadExpenses(path, ref mut List<Expense>)` y mantiene status separado. Es un
workaround pequeño, pero obliga a deformar la API de carga. La separación en
funciones de load/save/usage se conserva; dividir el programa mínimo en más
módulos no aportaba evidencia adicional.

Estado funcional: **PASS**, con formato local restringido y workaround SSA.

## 7. Hallazgos clasificados

### F1 — Mutar un `List<T>` owning dentro de un struct falla en SSA

- Tipo: **Compiler / Ownership**.
- Severidad: **MAJOR**.
- Reproducer mínimo ejecutado:

```aether
struct Item { string name; }
enum Status { Ok, Bad }
struct Result { List<Item> items; Status status; }
int main() {
    Result result = Result({}, Status.Ok);
    push(result.items, Item("x"));
    return 0;
}
```

- Esperado: compila y agrega un elemento al list almacenado.
- Observado: `error[E0400] (ssa): SSA owner ValueId(6) remains live at normal
  return`. En el consumer mayor también se observó `SSA memory store
  type/ownership contract invalid` sobre el field.
- Causa: hipótesis explícita; la adaptación/mutación del field atraviesa frontend
  pero el lowering o ledger de owners SSA no representa consistentemente la
  obligación del owner agregado.
- Workaround: mantener el `List<T>` como local root y pasarlo por `ref mut`, con
  el status en otro local.
- Impacto: impide modelar resultados idiomáticos que combinan payload owning y
  status; afecta parsers, loaders y builders, no sólo este tracker.
- Prioridad: **P0**.

### F2 — Observación Text de un string indexado dispara E0293

- Tipo: **Ergonomía / Ownership**.
- Severidad: **MINOR**.
- Reproducer mínimo ejecutado:

```aether
import std.Text;
int main() {
    List<string> lines = std.Text.lines("x");
    string value = std.Text.trim(*lines[0]);
    println(value);
    return 0;
}
```

- Esperado: `trim(ref string)` observa el elemento sin transferirlo.
- Observado: E0293, `partial move of non-Copy field string is unsupported`, en
  la expresión indexada.
- Causa: la adaptación call-scoped a shared borrow no cubre esta combinación de
  indexación/dereference sobre `List<string>`.
- Workaround: iterar por referencia cuando todas las filas son homogéneas o
  consumir el elemento con `remove` para obtener un owner local.
- Impacto: parsers simples ganan mutación/boilerplate y `remove(0)` repetido puede
  degradar complejidad.
- Prioridad: **P1**.

### F3 — Shape guards dinámicos no producen diagnóstico accionable

- Tipo: **OAL / Runtime / Package-CLI**.
- Severidad: **MAJOR**.
- Reproducer: `la.solve` con matriz 2x2 y vector columna de longitud 1, modo
  `dimension-mismatch` del solver.
- Esperado: excepción o error que identifique dimensiones incompatibles.
- Observado: el proceso aborta y la CLI sólo informa `program terminated without
  a representable exit status`, tanto en O0 como en O2.
- Causa: `shapeGuard` es un trap abortivo y la CLI no traduce su status/señal a un
  diagnóstico de contrato.
- Workaround: validar manualmente `dimension(b) == rows(A)` antes de llamar.
- Impacto: errores comunes de usuario en ciencia son difíciles de localizar y
  obligan a duplicar precondiciones públicas de la OAL.
- Prioridad: **P0**.

### F4 — El workspace `compiler-rs` no pasa `cargo check --workspace`

- Tipo: **Compiler**.
- Severidad: **MAJOR**.
- Reproducer ejecutado:

```text
cd compiler-rs
cargo check --workspace
```

- Esperado: workspace consistente.
- Observado: E0004 en `crates/aether-python/src/lib.rs:57`; faltan arms para
  `CompilerPhase::InitialIrImport` y `InitialIrVerification`.
- Causa identificada: el enum del verifier fue ampliado sin actualizar el mapping
  exhaustivo del binding Python.
- Workaround: usar la CLI oficial `compiler-next`, cuyo workspace sí pasa check.
- Impacto: rompe el gate global del checkout y cualquier build del binding
  Python legacy, aunque no bloquea las tres aplicaciones evaluadas.
- Prioridad: **P1**.

### F5 — README raíz describe una API y durabilidad de IO obsoletas

- Tipo: **Documentación**.
- Severidad: **MAJOR**.
- Reproducer: seguir `README.md` líneas cercanas a la sección de API mínima de
  archivos.
- Esperado: ejemplos alineados con la CLI/std promovidas.
- Observado: usa `import io`, `FileReadResult`, `FileStatus`, `appendText`, path
  `examples/expense_tracker/Main.ae` y afirma `fsync` de archivo/directorio. La
  superficie ejecutada usa `std.File`, retorna `string`/`void`, el archivo real es
  `main.ae`, y `FILE_ATOMIC_WRITE_V1_REPORT.md`/tests afirman y comprueban ausencia
  de `fsync`.
- Causa: sección no migrada después de la promoción de compiler-next/std.File.
- Workaround: consultar los reportes CLOSED recientes y el README local del
  Expense Tracker.
- Impacto: el onboarding propone código que no compila y promete una garantía de
  durabilidad inexistente.
- Prioridad: **P0 documental**.

### F6 — No hay codec/tabular general en std u OAL

- Tipo: **Standard Library / OAL / Ergonomía**.
- Severidad: **OPTIONAL**.
- Evidencia: Data Processor requiere parser local restringido; el Expense Tracker
  histórico dedica 526 líneas a ALPT1.
- Esperado: no se exige CSV/JSON en V1; por tanto esto es ausencia, no defecto.
- Observado: Text aporta primitivas suficientes, pero la validación, escaping y
  esquema quedan íntegramente en el consumer.
- Causa: capability fuera de la superficie actual.
- Workaround: parsers locales mínimos o codec de dominio como ALPT1.
- Impacto: aplicaciones generales reales tienen mucho más código incidental que
  el solver científico.
- Prioridad: **P2**.

### F7 — La CLI no ofrece `--help`/`--version` globales

- Tipo: **Package/CLI**.
- Severidad: **MINOR**.
- Reproducer ejecutado: `aether --help` y `aether --version`.
- Esperado: ayuda/version exit 0 en una CLI distribuible.
- Observado: ambas opciones son desconocidas; se imprime usage y se retorna error.
- Causa: superficie CLI no implementada.
- Workaround: provocar usage o consultar README/reportes.
- Impacto: fricción de descubrimiento; no bloquea build/run/check.
- Prioridad: **P2**.

## 8. Análisis transversal

### Capacidades maduras

- El pipeline oficial compila y ejecuta packages y dependencies path de forma
  consistente en O0/O2.
- Linear Algebra ofrece una superficie coherente, genérica y preserving. LU, QR,
  SVD/least-squares, productos y orientación de vectores funcionaron en consumers
  reales.
- Los errores de singularidad/rank deficiency son nominales y catchables.
- `std.Process.args` preserva argumentos entre la CLI y el programa.
- IO de texto UTF-8, parsing numérico y excepciones nominales cubren los casos
  básicos de aplicaciones generales.
- `writeTextAtomic` ofrece publicación atómica de nombre y preserva old/new ante
  fallos pre-publish; no debe confundirse con durabilidad.

### Fricciones recurrentes

- Ownership es la fricción transversal dominante: strings dentro de colecciones,
  fields owning y mutación de aggregates obligan a reorganizar APIs.
- Los consumers deben conocer qué expresiones serán adaptadas a borrow contextual
  y cuáles se interpretarán como partial move.
- Los diagnósticos estáticos de overload/orientación son buenos; los traps de
  forma dinámicos son opacos.
- Las aplicaciones de datos repiten validación/formato porque Text es de bajo
  nivel y no existe un codec oficial.
- La documentación raíz mezcla superficies legacy y actuales.

### Generalidad y ergonomía científica

Aether ya expresa el núcleo del solver con una densidad cercana al dominio:
literales matriciales, tipos de orientación, operadores y solve reutilizable.
Ésa es evidencia fuerte de ergonomía científica, no sólo cantidad de features.

En Data Processor y Expense Tracker, las mismas bases permiten terminar el
trabajo, pero el código de plumbing domina: 88 y 168 líneas respectivamente,
frente a unas 24 líneas de happy path numérico. La diferencia proviene menos de
la ausencia de control flow/IO que de ownership proyectado y falta de codecs.

## 9. Priorización de mejoras

Máximo de cinco mejoras propuestas:

| Prioridad | Mejora | Evidencia | Impacto | Coste | Riesgo | Dependencias |
|---:|---|---|---|---|---|---|
| 1 | Cerrar ownership de fields owning y observación indexada | F1, F2; dos apps | elimina fallos SSA y APIs deformadas | alto | alto: ledger/drop/borrow SSA | contrato HIR/MIR/SSA y tests lifecycle |
| 2 | Diagnósticos nominales de shape/contratos | F3 | errores científicos accionables | medio | medio: ABI de error/traps | linearAlgebra + runtime + CLI |
| 3 | Corregir documentación promovida de IO/Expense | F5 | onboarding correcto y sin promesas falsas | bajo | bajo | ninguna implementación |
| 4 | Reparar exhaustividad de `aether-python` | F4 | restaura gate de compiler-rs | bajo | bajo | decidir soporte del workspace legacy |
| 5 | Diseñar un codec estructurado pequeño, no necesariamente CSV completo | F6 | reduce cientos de líneas en apps generales | medio/alto | medio: formato/versionado/errores | Text, File y política de packages |

### Próximo milestone recomendado

**OWNING-COLLECTION-FIELDS-V1**: cerrar una única semántica verificada para
observar elementos non-Copy por índice y mutar colecciones owning almacenadas en
fields, con lifecycle y unwind correctos en HIR/MIR/SSA/LLVM.

Es la única recomendación seleccionada porque tiene dos fallos ejecutados,
afecta dos dominios del assessment y hoy obliga tanto a consumo destructivo de
strings como a cambiar la forma pública de resultados de carga. El milestone no
debe ampliar sintaxis ni introducir clone implícito: primero debe fijar el
contrato de borrow/mutación existente y calificar los reproducers F1/F2 en O0/O2.

No se inicia ese milestone como parte de este assessment.

## 10. Gates y tests focales

### Gates

| Comando | Resultado |
|---|---|
| `cd compiler-next && cargo check --workspace` | PASS |
| `cd compiler-rs && cargo check --workspace` | **FAIL preexistente**, F4 |
| `git diff --check` | PASS al cierre |

No se ejecutó `cargo test --workspace` global porque no se modificó código
productivo. Sí se ejecutaron suites focales proporcionales a los comportamientos
evaluados.

### Tests focales

| Suite | Resultado |
|---|---:|
| `linear_algebra_solve_v1` | 9 pass |
| `linear_algebra_qr_solve_v1` | 6 pass |
| `linear_algebra_ownership_ergonomics_v1` | 6 pass |
| `text_v1` | 8 pass |
| `io_v1` | 12 pass |
| `expense_tracker_next_port_complete` | 3 pass |
| `process_args_v1` | 9 pass |

Total focal: **53 pass, 0 fail**.

## 11. Limitaciones del assessment

- Plataforma evaluada: Linux x86_64/POSIX del checkout actual; no se evaluó
  Windows ni otros targets.
- Los datasets son pequeños; no se midió performance ni memoria a escala.
- No se probó concurrencia de writers, locking ni crash/power-loss.
- El parser CSV local no pretende cubrir RFC 4180.
- El formato del tracker de assessment no es ALPT1; el consumer histórico ALPT1
  se ejecutó por separado para no perder esa evidencia.
- No se ejecutó cada branch defensivo escrito; las tablas distinguen casos
  observados de validaciones sólo presentes en source.
- No se evaluaron networking, GUI, async, FFI, packaging remoto ni publicación.
- El fallo de `compiler-rs` se registró, pero no se corrigió por estar fuera del
  alcance y de la prohibición de modificar compiler/runtime.

## 12. Inventario de entregables

```text
examples/assessment/
  numerical-solver/
    aether.toml
    aether.lock
    src/main.ae
  data-processor/
    aether.toml
    aether.lock
    src/main.ae
  expense-tracker/
    aether.toml
    aether.lock
    src/main.ae
docs/reports/APPLICATION_MATURITY_ASSESSMENT_V1.md
```

Los inputs, outputs, ledgers, SVG y reproducers temporales se colocaron bajo
`/tmp/aether-assessment-*`; no se mezclaron con los sources.
