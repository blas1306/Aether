# Aether — LLVM-LOCAL-NAME-UNIQUENESS-V1 — Reporte

Estado: **CLOSED — CAUSA RAÍZ CORREGIDA Y QUALIFICATION COMPLETA EN VERDE**

Fecha: 2026-11-25

Checkout investigado: `main` @
`35e1a8197dc7a48d6f7218b27a44f458c98c25c4`.

El cambio se limita al lowering de interpolación de strings del backend LLVM y
a su prueba de regresión. No modifica frontend, HIR, MIR, SSA, ownership,
Iteration V3, ABI ni runtime. Se preservaron los cambios locales anteriores de
documentación, qualification y `examples/ProbandoNR`; no se hizo commit, push
ni tag.

## 1. Reproducer exacto

Fuente:

`compiler-next/tests/programs/iteration_v3_smoke.ae`

Comandos ejecutados desde la raíz, antes de la corrección:

```bash
compiler-next/target/debug/aether build \
  compiler-next/tests/programs/iteration_v3_smoke.ae \
  -O0 -o /tmp/aether-llvm-local-name-o0

compiler-next/target/debug/aether build \
  compiler-next/tests/programs/iteration_v3_smoke.ae \
  -O2 -o /tmp/aether-llvm-local-name-o2
```

Ambos comandos terminaron con status `1` y el mismo diagnóstico sustantivo:

```text
error[E0601] (toolchain): clang rejected generated LLVM: ...ll:1650:3: error: multiple definition of local value named 'fmt_observed18_0'
 1650 |   %fmt_observed18_0 = load ptr, ptr %v17
      |   ^
1 error generated.
```

El harness oficial previo observaba el mismo rechazo mediante su driver y lo
registraba como fallo de infraestructura/compilación con status `2`; no había
una diferencia semántica entre ambos diagnósticos.

## 2. LLVM IR inválido conservado

La invocación oficial de la CLI se ejecutó con un wrapper de captura de `clang`
que copió el archivo temporal antes de que el driver lo eliminara. La evidencia
quedó fuera del worktree productivo:

- `/tmp/aether-llvm-local-name-O0-invalid.ll`
- `/tmp/aether-llvm-local-name-O2-invalid.ll`
- `/tmp/aether-llvm-local-name-o0.stderr`
- `/tmp/aether-llvm-local-name-o2.stderr`

Los dos LLVM IR tienen 62.496 bytes y son idénticos en la región afectada. El
fragmento inválido es:

```llvm
bb5:
  %v17 = getelementptr inbounds i8, ptr %v16, i64 0
  %fmt_observed18_0 = load ptr, ptr %v17
  %fmt_len18_0 = call i64 @aether_string_length(ptr %fmt_observed18_0)
  %fmt_total18_0 = add i64 0, 0
  %fmt_sum18_0 = call { i64, i1 } @llvm.uadd.with.overflow.i64(i64 %fmt_total18_0, i64 %fmt_len18_0)
  %fmt_total18_1 = extractvalue { i64, i1 } %fmt_sum18_0, 0
  %fmt_overflow18_0 = extractvalue { i64, i1 } %fmt_sum18_0, 1
  br i1 %fmt_overflow18_0, label %fmt_trap18, label %fmt_size_ok18_0
fmt_size_ok18_0:
  %v18 = call ptr @aether_string_allocate(i64 %fmt_total18_1)
  %fmt_build18 = call ptr @aether_string_data(ptr %v18)
  %fmt_offset18_0 = add i64 0, 0
  %fmt_observed18_0 = load ptr, ptr %v17
  %fmt_src18_0 = call ptr @aether_string_data(ptr %fmt_observed18_0)
```

## 3. Función, bloques y productores

La función afectada era:

```text
@__aether_v2_m18_iteration_5fv3_5fsmoke_f4_main
```

Las dos definiciones eran:

| Definición | Bloque | Instrucción | Operación source |
|---|---|---|---|
| primera | `bb5` | `load ptr, ptr %v17` | observación compartida de `*word` para medir `${*word}` con `aether_string_length` |
| segunda | `fmt_size_ok18_0` | `load ptr, ptr %v17` | nueva observación del mismo `${*word}` antes de obtener sus bytes con `aether_string_data` |

El rastreo HIR/MIR/SSA confirmó que no era un temporal de F3 ni un reporter. El
productor real era `ValueId(18)`, `String::Interpolate`, con un único hole de
tipo `string`, `access: SharedObservation`, `conversion: StringBorrow`,
originado por `println("${*word}")`.

## 4. Causa raíz

`emit_interpolation` tiene dos fases necesarias:

1. observar cada hole y calcular el tamaño exacto;
2. reservar el string final y copiar cada fragmento.

Para un hole `string` prestado, las dos fases llamaban independientemente a
`observed_value`. Ese helper genera el nombre determinista
`%fmt_observed{result}_{index}` y emite inmediatamente su definición. Por eso
las dos llamadas dentro de una misma instrucción `String::Interpolate`
reemitían el mismo nombre.

El `result` no se reiniciaba por bloque y no había duplicación de SSA, colisión
con un nombre source-facing ni conflicto entre helpers distintos. `result` es
el `ValueId` único de la instrucción dentro de la función y `index` identifica
el fragmento. El defecto era más localizado: el helper de observación se usaba
dos veces para una sola pareja `(result, index)`.

La primera carga en `bb5` domina `fmt_size_ok18_0`; por lo tanto, la segunda
carga no sólo era inválida por nombre, sino también innecesaria.

## 5. Corrección implementada

Durante la fase de sizing, `emit_interpolation` conserva el operando LLVM ya
observado para cada fragmento `string`. La fase de escritura reutiliza ese
operando en `aether_string_data` en vez de volver a invocar `observed_value`.

La corrección:

- elimina la segunda definición;
- conserva el mismo valor, orden de evaluación y lifetime;
- es determinista;
- no crea globales ni cambia mangling;
- no cambia ABI ni runtime;
- sólo usa memoria del proceso compilador durante codegen y no añade overhead
  al ejecutable generado.

No se introdujo un generador paralelo de nombres porque el namespace existente
`(ValueId, fragment_index)` ya era suficiente. Renombrar la segunda carga habría
ocultado la doble emisión sin aprovechar la dominancia ni resolver su causa.

## 6. Modelo de unicidad por función

Los resultados SSA `%v{result}` y los temporales derivados de una operación
usan el `ValueId` de la instrucción, que es único dentro de cada función. Los
índices de fragmento separan múltiples holes de una misma interpolación. Cada
función LLVM comienza un namespace local nuevo, por lo que repetir el mismo
nombre en dos funciones diferentes es válido.

La regresión recorre cada cuerpo LLVM con un conjunto nuevo por función y
rechaza toda segunda definición de un mismo LHS `%...`. `clang` valida además
el namespace LLVM completo, incluidos argumentos y labels. No se reutiliza un
identificador al cambiar de basic block.

## 7. Compatibilidad O0/O2

Después de la corrección se ejecutaron:

```bash
compiler-next/target/debug/aether build \
  compiler-next/tests/programs/iteration_v3_smoke.ae \
  -O0 -o /tmp/aether-llvm-local-name-fixed-o0
/tmp/aether-llvm-local-name-fixed-o0

compiler-next/target/debug/aether build \
  compiler-next/tests/programs/iteration_v3_smoke.ae \
  -O2 -o /tmp/aether-llvm-local-name-fixed-o2
/tmp/aether-llvm-local-name-fixed-o2
```

Ambas compilaciones y ejecuciones terminaron con status `0` y bytes de salida:

```text
A\0B\n
hé\n
```

La validez del IR no depende del nivel de optimización.

## 8. Tests de regresión

Se añadió
`borrowed_string_interpolation_names_are_unique_in_o0_o2` a `format_v1.rs`.
La prueba cubre:

- el reproducer original por `include_str!`, sin duplicarlo ni cambiarlo;
- O0 y O2;
- aceptación del LLVM por `clang` y ejecución nativa;
- salida exacta, incluyendo NUL y UTF-8;
- varias operaciones de formatting en una función;
- interpolaciones en ramas y loops anidados;
- holes prestados múltiples en una misma interpolación;
- funciones diferentes con namespaces locales independientes;
- convivencia de los helpers `%fmt_observed...` de interpolación y
  `%format_buffer...` de `str` en la misma función;
- detección explícita de definiciones locales LLVM repetidas por función.

Resultado focal del test nuevo: `1 passed; 0 failed`. Resultado de la suite
completa de formatting: `11 passed; 0 failed`.

## 9. Qualification focal y gates generales

| Gate | Resultado |
|---|---|
| CLI oficial, reproducer O0 | PASS, status 0 y salida exacta |
| CLI oficial, reproducer O2 | PASS, status 0 y salida exacta |
| `cargo test -p aether-driver --test iteration_v3` | PASS, 6/6 |
| `cargo test -p aether-driver --test format_v1` | PASS, 11/11 |
| `cargo test -p aether-driver --test shape_contract_diagnostics_v1` | PASS, 4/4 |
| `cargo test -p aether-driver --test uncaught_exception_diagnostics_v1` | PASS, 5/5 |
| `cargo test -p aether-backend-llvm` | PASS, 8/8 + doc-tests |
| `cargo test -p aether-cli` | PASS, 31/31 + doc-tests |
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | PASS; todas las suites y doc-tests |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS, exit 0; advertencias preexistentes fuera del cambio |
| `git diff --check` desde la raíz | PASS |

Shape Contract Diagnostics y Uncaught Exception Diagnostics conservan sus
salidas y contratos. No se cambiaron reporter names ni helpers de diagnóstico.

## 10. Qualification oficial de 96 casos

Comandos ejecutados desde la raíz:

```bash
bash compiler-next/tests/test-differential-harness.sh
bash compiler-next/tests/run-differential.sh
```

Resultados:

```text
differential harness tests: PASS
array_list_borrowed_for_in: PASS compiler-next=0 [V1_CONTRACT]
qualification: mode=official checked=96 failures=0
```

El harness negativo confirmó que expectativas incorrectas y compiladores rotos
siguen produciendo salida no exitosa. El gate oficial no invocó Python legacy ni
dependió de `compiler-rs`. `differential.tsv`, su cobertura de 96 casos y la
expectativa normativa `accept:0` no fueron modificados por este milestone.
