# Roadmap incremental del backend

> Estado: plan de consolidación, 18 de julio de 2026. No autoriza todavía una
> reescritura, una ABI pública ni la introducción de Rust/C/C++ en el árbol.

## 1. Decisión recomendada

Aether debe evolucionar por reemplazo de componentes detrás de contratos
medibles, no por una reescritura total.

Distribución de lenguajes recomendada:

| Área | Lenguaje | Motivo |
| --- | --- | --- |
| lexer/parser/AST/typechecker | Python | productividad, diagnósticos y tooling; no existe problema medido que justifique migrarlos |
| CLI, LSP, editor, formatter, release tooling | Python | integración y velocidad de cambio |
| AST interpreter | Python | oráculo semántico independiente; no eliminar |
| IR adapter/serializer inicial | Python | mínima perturbación y formato inspeccionable |
| verifier experimental | Rust | componente puro, acotado, sin LLVM/libc/ownership de objetos runtime |
| runtime separado | Rust `extern "C"` | memory safety, ownership explícito, tests/fuzz/Miri donde aplique |
| glue de sistema muy pequeño | C | sólo APIs/ABI de bajo nivel donde sea más directo que Rust |
| backend LLVM futuro | Rust + LLVM C API/bindings maduros | builders tipados y aislamiento de strings LLVM, sólo con evidencia |
| C++ | ninguno por defecto | no hay necesidad técnica concreta |

Primer componente recomendado para probar Rust: **verificador IR read-only**.
Primer componente de producción recomendado para separación: **runtime de
strings y lifecycle básico detrás de ABI C interna**, después de estabilizar
layout/ownership y de tener sanitizers.

## 2. Principios de migración

1. La semántica pública, no el código existente, es la autoridad.
2. AST interpreter e IR interpreter permanecen como oráculos independientes.
3. Todo backend recibe entrada validada y falla explícitamente; no hay fallback
   silencioso en producción.
4. La frontera portable es un contrato versionado, no objetos PyO3.
5. Runtime y compiler sólo comparten ABI/layout declarados.
6. Cada componente nuevo puede activarse/desactivarse y compararse.
7. Rollback significa cambiar selección/configuración y eliminar el artefacto
   nuevo, no revertir semántica ni formato source.
8. No se declara éxito por usar Rust: se exigen métricas, seguridad,
   mantenibilidad y packaging iguales o mejores.
9. C queda limitado al runtime pequeño o adaptación del sistema; C++ requiere
   una dependencia imposible o impráctica mediante C ABI.
10. Ninguna fase comienza si sus criterios de entrada no están cumplidos.

## 3. Baseline previo

Antes del primer commit Rust se debe guardar un baseline machine-readable por
commit, Python/Clang/OS/CPU y corpus. Casos mínimos:

- pequeños: arithmetic, calls, branches, panic integer/string/list;
- medianos: arrays/lists/structs/modules y benchmarks del repositorio;
- dogfoods: Numerical Methods y Expense Tracker admitidos por cada profile;
- corpus diferencial completo en O0/O1/O2.

Métricas obligatorias:

| Grupo | Métricas |
| --- | --- |
| frontend | lexer, parser y typecheck separados; módulos cargados; peak RSS |
| middle-end | IR lower, IR verify, lifecycle expand, optimización IR, SSA build, SSA verify, optimización SSA |
| codegen | LLVM emission, bytes LLVM, Clang/link, total build |
| CLI/package | startup cold/warm, tamaño wheel/sdist, tiempo import, dependencias, tiempo suite |
| artefacto | tamaño executable, símbolos/imports, reproducibilidad hash |
| runtime | wall/cpu, peak RSS, allocations, retains/releases, bytes allocated, output/exit |
| calidad | LOC/cyclomatic proxies, warnings, diagnostics parity, bugs, tiempo de cambio de opcode |

El harness actual de `aether bench` es un buen inicio, pero combina
parse+typecheck, SSA build+frontend y native build+Clang. Fase 0 debe agregar
timers alrededor de etapas ya existentes, salida JSON y medición RSS/tamaños
sin cambiar el comportamiento del compilador.

Criterios globales de éxito sugeridos:

- cero divergencias en el corpus diferencial;
- ningún diagnóstico pierde ID, ubicación o claridad;
- determinismo byte-for-byte bajo distintos `PYTHONHASHSEED` y paths
  equivalentes;
- runtime nuevo sin hallazgos ASan/UBSan/LSan en corpus y stress;
- memoria o tiempo no empeora más de 5% en medianas sin beneficio documentado;
- la métrica objetivo de la fase mejora al menos 10% o se obtiene una mejora de
  seguridad/mantenibilidad demostrable;
- wheel y startup no empeoran más de los budgets aprobados;
- rollback probado.

## 4. Fase 0 — Consolidación

### Objetivo

Eliminar ambigüedades antes de copiar implementación: arreglar el P0 de
literales i32 en una tarea semántica separada, documentar ABI, centralizar
contratos, establecer baselines, sanitizers y un IR experimental exportable.

### Dependencias y archivos

- docs de auditoría/ABI/roadmap;
- `lexer.py`, checker y tests de integer safety para BA-001, en un cambio
  independiente;
- `ir/model.py`, `ir/types.py`, `instruction_effects.py`, verifiers;
- `backend/llvm/layout.py`, runtime generators y printer;
- `benchmark.py`, `differential.py`, scripts CI;
- nuevo schema/fixtures bajo un namespace explícitamente experimental.

### Entregables incrementales

0A. Corregir/rechazar literales fuera de signed i32 antes de IR.

0B. Introducir `BuiltinContract`/opcode metadata canónica para firmas, efectos,
ownership y capability, consumida por IR/SSA sin cambiar output.

0C. Introducir `RuntimeRequirements` y un descriptor único de layout. El
printer aún puede generar el mismo LLVM, pero deja de inventar índices.

0D. Diseñar `aether-ir` JSON v0 experimental:

- envelope `{schema, version, module}`;
- types/opcodes con tags estables;
- constants sin objetos Python (`enum` con nominal ID/member/discriminant);
- CFG, structs, symbols, source file table/spans, ownership/effects;
- ordering canónico y reader que rechaza versiones desconocidas;
- no SSA ni formato binario inicialmente.

0E. Baseline de performance/determinismo/sanitizers.

### Riesgos y rollback

Riesgo: convertir metadata declarativa en un nuevo monolito o congelar v0
prematuramente. Rollback: mantener adapters paralelos y marcar schema
experimental; el pipeline productivo sigue consumiendo dataclasses.

### Pruebas

- bordes `INT_MIN/INT_MAX`, positivos/negativos fuera de rango y operaciones;
- roundtrip JSON y rechazo de schema/version/tag inválido;
- equivalencia printer antes/después del descriptor;
- verifier IR/SSA y capability negatives;
- LLVM byte-identical donde el refactor sea mecánico;
- determinismo por hash seed/path;
- corpus AST/native O0/O1/O2.

### Criterio de salida

- BA-001 cerrado;
- ABI actual y provisional documentada;
- runtime requirements/layout no duplicados en printer;
- IR JSON cubre todo el profile elegido y no contiene repr/IDs Python;
- baseline JSON versionado y sanitizer commands reproducibles;
- suite/CI completa verde.

Beneficio esperado: reducir riesgo y hacer medible cualquier migración, no
acelerar todavía la compilación.

## 5. Fase 1 — Runtime separado

### Objetivo

Compilar `aether_runtime` independientemente. El backend Python genera calls a
una ABI C interna y enlaza una library, sin conocer headers privados.

### Orden interno

1. panic/allocation y ABI version query;
2. string validate/length/retain/release/equal;
3. concat/trim/split/parse/format;
4. Array/List allocation/RC/bounds/copy/slice;
5. IO/process/files por provider de plataforma;
6. sort y helpers especializados, sólo si la ABI tipada está clara.

### Lenguaje

Rust estable con `#[repr(C)]`, `extern "C"`, handles opacos y tipos de ancho
fijo. C sólo para una adaptación pequeña de libc/OS que resulte más segura o
portable así. No C++.

### Archivos afectados

`backend/llvm/*_runtime.py`, `printer.py`, `build.py`, packaging/release, nuevos
headers/runtime sources y tests ABI. Los generators actuales se conservan
temporalmente como `runtime=inline` para desarrollo.

### Coexistencia

```text
aether ... --runtime inline    # oracle histórico, desarrollo
aether ... --runtime shared    # runtime separado
```

La selección debe ser explícita, reportada en diagnostics/build metadata y no
debe hacer fallback tras un fallo del runtime shared.

### Riesgos y rollback

- drift de ownership o layout;
- cambio de panic/streams/locale;
- packaging multi-platform más grande;
- calls ABI pueden reducir oportunidades de inline.

Rollback: seleccionar inline en desarrollo y en la release anterior; mantener
el mismo IR/backend. No mantener dual runtime indefinidamente: retirar inline
sólo tras dos ciclos verdes y baseline aprobado.

### Pruebas y métricas

- ABI size/alignment/symbol/version tests por target;
- diferencial inline/shared para stdout, stderr, exit, files y panic;
- contadores lifecycle y stress nested collections/strings;
- ASan/UBSan/LSan y fuzz de UTF-8/parse/retain-release;
- tamaño executable/wheel, link time, runtime performance y allocations.

### Criterio de salida

Compiler no usa GEP sobre headers runtime; ABI interna versionada; runtime se
compila/testea solo; corpus shared igual a inline; sanitizers sin hallazgos;
rollback demostrado.

## 6. Fase 2 — Piloto Rust acotado

### Objetivo

Validar toolchain, schema y coexistencia con un componente puro antes de
migrar codegen. Elección: verifier IR Rust.

### Por qué el verifier

- no posee objetos runtime ni llama LLVM/libc;
- consume exactamente la frontera que se necesita estabilizar;
- sus resultados pueden compararse con el verifier Python;
- fallo seguro: rechaza compilación, no genera un executable incorrecto;
- mide costo de distribución/startup y ergonomía de agregar opcodes.

### Interfaz

En desarrollo:

```text
aether --ir-verifier python
aether --ir-verifier rust
aether --ir-verifier both
```

`both` exige misma decisión y compara diagnostics por ID/span/categoría. El
payload canónico es IR JSON v0; un binding in-process puede agregarse después,
pero no sustituye el formato.

### Riesgos y rollback

Riesgo: duplicar toda la semántica sin metadata común o convertir el JSON en
API pública. Rollback: default Python y binary Rust opcional; schema permanece
experimental hasta cubrir corpus.

### Pruebas/métricas/criterio de salida

- todos los módulos válidos aceptados por ambos;
- corpus mutado de IR inválido rechazado por ambos;
- diagnostics equivalentes;
- fuzz parser/schema/verifier;
- tiempo/RSS/startup/package medidos;
- agregar un opcode de prueba requiere tocar metadata común, no switches
  divergentes no enumerados.

Finaliza cuando el verifier Rust puede ser default interno durante un ciclo sin
divergencia. Si no mejora seguridad, distribución o mantenimiento, se conserva
como experimento y no se migra el resto por inercia.

## 7. Fase 3 — Backend LLVM

### Entrada

Sólo si Fases 0-2 están cerradas y las métricas muestran que `LLVMPrinter`
limita performance/mantenimiento o que builders tipados reducen defectos.

### Objetivo

Implementar un emisor Rust que consume IR versionado (o construye su propia SSA
verificada), llama exclusivamente al runtime ABI y produce LLVM equivalente.

### Estrategia

- comenzar por scalars/control flow/calls;
- agregar strings y agregados sólo vía ABI runtime;
- implementar structs/layout mediante APIs LLVM target-aware;
- conservar backend Python como oráculo;
- comparar IR/LLVM normalizado, observables y objetos, no exigir texto idéntico
  cuando los builders cambien nombres legítimamente.

### Coexistencia

```text
aether --backend llvm-python
aether --backend llvm-rust
aether --backend llvm-both   # sólo CI/desarrollo
```

`llvm-both` compila ambos, ejecuta ambos en sandbox y compara stdout, stderr,
exit, files y panic. En producción se selecciona uno; nunca se reintenta el
otro tras error.

### Rollback, tests y salida

Rollback: `llvm-python` permanece seleccionable durante al menos un ciclo. Se
requieren corpus diferencial O0/O1/O2, LLVM verifier, sanitizers runtime,
determinismo, modules/mangling/layout goldens, compile time/RSS/package y
diagnostics. Sale cuando logra paridad completa del profile elegido y una
mejora medida; de lo contrario Python continúa como backend soportado.

## 8. Fase 4 — Optimizadores o SSA

No migrar antes del backend y formato estables.

Candidatos en orden:

1. análisis CFG/dominancia puro;
2. SCCP y passes SSA individuales;
3. SSA construction general;
4. optimizador IR completo.

Cada pass debe admitir `python`, `rust`, `both`; comparar IR/SSA normalizado,
efectos preservados, panics y resultados. El pattern SSA builder sigue como
oráculo hasta que el general tenga suficiente evidencia, luego se retira en
una tarea explícita.

Criterio adicional: ninguna optimización puede depender de layout runtime ni
reordenar operaciones que `InstructionEffects` marque trapping/owning.

## 9. Fase 5 — Frontend

Por defecto **no migrar** lexer, parser, AST, checker, module resolver, language
service, formatter, LSP ni diagnostics. Reabrir la decisión sólo con evidencia:

- frontend domina de forma sostenida el compile time;
- memoria/distribución Python incumplen budgets;
- bugs se concentran en invariantes que Rust resolvería;
- mantener tipos/diagnósticos Python cuesta más que una frontera estable.

Incluso si se migra una parte, conservar tests/goldens y AST interpreter Python
como implementación de referencia durante la transición.

## 10. Estrategia de comparación y fallback

Modos de desarrollo propuestos:

| Dimensión | Selecciones |
| --- | --- |
| verifier | `python`, `rust`, `both` |
| runtime | `inline`, `shared`, `both` en harness |
| LLVM backend | `llvm-python`, `llvm-rust`, `llvm-both` |
| optimización | profile + engine explícito |

El harness compara:

- IR canónico y verifier decision;
- SSA/LLVM normalizados cuando corresponda;
- stdout/stderr bytes;
- panic message/stream y exit code;
- archivos producidos;
- counters/trace de ownership sólo en builds instrumentados;
- timings, RSS, allocations y tamaños.

Regla de fallback: permitido sólo mediante flag explícito en desarrollo. Una
compilación de producción que elige Rust falla si Rust falla. Reintentar Python
ocultaría bugs y haría no reproducible el backend usado.

## 11. Sanitizers y seguridad

### Estado

LLVM/Clang, corpus y lifecycle tests existen. No hay gate ASan/UBSan/LSan,
Valgrind, fuzzing ni property suite general; Miri no aplica hasta introducir
Rust.

### Comandos reproducibles iniciales

Para un `.ll` conservado, en Linux/Clang:

```bash
PYTHONPATH=src .venv/bin/python -m aether build PROGRAM.ae \
  -o /tmp/aether-program --keep-llvm
clang -O1 -g -fno-omit-frame-pointer \
  -fsanitize=address,undefined /tmp/aether-program.ll \
  -o /tmp/aether-program-sanitized -lm
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  /tmp/aether-program-sanitized
```

LeakSanitizer separado cuando el target lo soporte:

```bash
clang -O1 -g -fsanitize=leak /tmp/aether-program.ll \
  -o /tmp/aether-program-lsan -lm
/tmp/aether-program-lsan
```

Valgrind es complementario, no gate primario:

```bash
valgrind --error-exitcode=99 --leak-check=full \
  --show-leak-kinds=all /tmp/aether-program
```

La automatización debe generar el LLVM en un directorio temporal, ejecutar
corpus normal y de panic, archivar logs y distinguir leaks deliberados de
objetos immortales. No se deben agregar flags sanitizer al build de release sin
un profile explícito.

Para Rust futuro:

```bash
cargo test --all-targets
cargo clippy --all-targets -- -D warnings
cargo miri test        # módulos compatibles; no FFI real bajo Miri
cargo fuzz run ir_parser
cargo fuzz run string_runtime
```

Property tests prioritarios: sequences aleatorias de retain/release/move,
rollback de copia parcial, nested structs/collections, UTF-8 válido/inválido,
parse numeric y verifier mutation testing.

## 12. Matriz de entrada/salida resumida

| Fase | Entrada obligatoria | Salida obligatoria |
| --- | --- | --- |
| 0 | backend actual verde | P0 cerrado, contracts/layout/schema/baseline/sanitizers preparados |
| 1 | ABI interna diseñada | runtime separado parity-safe y rollback inline |
| 2 | IR exportable y packaging Rust | verifier Rust comparable, fuzzed y medido |
| 3 | runtime/verifier estables + evidencia | LLVM Rust con paridad y beneficio |
| 4 | IR/SSA/LLVM estables | passes seleccionables y equivalentes |
| 5 | problema frontend medido | migración acotada o decisión explícita de no migrar |

## 13. Próxima tarea concreta

Crear un cambio pequeño y aislado para **cerrar BA-001**:

1. definir validación de literal signed i32 en el frontend;
2. aceptar `-2147483648` sin aceptar el literal positivo `2147483648` como un
   valor independiente;
3. rechazar otros literales fuera de rango con diagnostic ID/span;
4. agregar tests AST/typechecker/IR/native para ambos límites y fuera de rango;
5. ampliar el corpus diferencial;
6. ejecutar suite, CI y release checks.

Después, la siguiente tarea es diseñar únicamente el envelope y los tipos de
`aether-ir` JSON v0, sin implementar todavía Rust, FFI ni formato binario.
