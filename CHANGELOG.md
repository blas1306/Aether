# Aether Changelog

Este documento registra hitos de Aether, no commits individuales ni una lista
exhaustiva de features. Los estados describen lo que existía al cerrar cada
etapa; cuando el intérprete AST y el backend LLVM/native tienen coberturas
distintas, esa diferencia se indica de forma explícita.

Aether sigue siendo un prototipo en desarrollo y todavía no tiene una release
estable. La especificación v0 conserva valor histórico y sintáctico, mientras
que el alcance v1 y los perfiles de capacidades describen la consolidación en
curso.

## Unreleased

### Added

- Codec manual ALPT1 revision 1 para `Transaction`/`List<Transaction>`, con
  resultados nominales, parser byte-aware fail-closed, formatting binary64
  round-trip y wrappers `loadLedger`/`saveLedger`.
- Expense Tracker persistente entre procesos con path explícito, rechazo de
  archivos corruptos sin overwrite y dogfood AST/IR/SSA/LLVM/native.

- `string.split(string) -> Array<string>` end-to-end en AST, IR, SSA y
  LLVM/native: matching byte-based no solapado, campos vacíos, UTF-8/NUL,
  separator vacío con panic y fragments owned con rollback en intérpretes.
- Completions/signature LSP y comando dogfood `split-check` en Expense Tracker;
  no declara CSV, regex, views, escaping ni segmentación Unicode.
- Documentación histórica de los hitos del lenguaje y de las decisiones que
  llevaron desde el prototipo matemático hasta el diseño generalista actual.
- Referencias `const` de Array/List con read-only por camino de acceso y
  `for-in` con borrow no-owning por elemento en AST, IR, SSA y LLVM/native.
- `string.trim()` end-to-end con whitespace ASCII exacto, fast paths ARC,
  preservación de UTF-8/NUL y paridad AST/IR/SSA/LLVM en O0/O1/O2.
- `System.args()` end-to-end con snapshots owned `Array<string>`, forwarding
  después de `--`, inyección AST/IR y wrapper native `main(argc, argv)` POSIX.
- `io.readText`, `io.writeText` e `io.appendText` para archivos de texto UTF-8,
  con resultados nominales, bytes/NUL exactos, errores portables y paridad
  AST/IR/SSA/LLVM en Linux y clang O0/O1/O2.

### Changed

- Los mutadores de colecciones se clasifican mediante metadata semántica; la
  mutación del iterable se rechaza también para aliases locales simples.
- El perfil de capacidades 12 separa `const-collection-references` y
  `borrowed-for-in-elements`.
- El perfil de capacidades 16 agrega `string-trim`; parsing numérico conserva
  su gramática estricta y requiere trim explícito.
- El perfil 17 agrega `process-arguments` y `cli-argument-forwarding`; Expense
  Tracker consume comandos reales sin cambiar la firma pública de `main`.
- El perfil 18 agrega `text-file-read`, `text-file-write` y `text-file-append`;
  Expense Tracker dogfoodea persistencia de un resumen textual no-CSV.
- El perfil 19 agrega la capacidad granular completa `string-split`.
- El perfil 20 agrega `alpt1-encode`, `alpt1-decode`,
  `expense-ledger-load` y `expense-ledger-save`; no declara atomicidad.

### Notes

- No se declara una versión estable ni se congela una API con esta entrada.
- Las diferencias vigentes entre backends continúan registradas en la
  [auditoría de paridad](docs/aether/BACKEND_FEATURE_PARITY.md) y en los
  [perfiles de capacidades](docs/aether/BACKEND_CAPABILITY_PROFILES.md).

## Runtime and Ownership — July 2026

### Added

- Operaciones estructurales de lifecycle en IR (`init_default`, `copy_init`,
  `move_init`, `assign` y `destroy`), verificación de su uso y cleanup por
  scope antes de la conversión a SSA.
- Objetos string nativos inmutables en UTF-8. Los literales y el string vacío
  son objetos inmortales; los objetos dinámicos usan ARC no atómico con
  `retain`/`release` comprobados.
- Hooks recursivos de lifecycle para structs y para elementos de Array/List,
  incluidos copy, slice, get/set, crecimiento y operaciones que transfieren un
  elemento.

### Changed

- El handle native de `string` dejó de representar un `char *`: apunta a un
  objeto Aether con longitud, flags, contador de referencias y bytes inline.
- Parámetros string se tratan como borrowed y los retornos como owned; el
  lowering conserva esa distinción al mover o retener valores.

### Improved

- Igualdad e impresión de strings usan longitud explícita y no dependen de
  `strcmp` o de terminación nula para definir el valor.
- Los efectos de lifecycle llegan a SSA como operaciones effectful, por lo que
  DCE y SCCP no pueden borrar retains, releases o cleanup observables.

### Notes

- Concatenación native pública, parsing, `split`/`trim`, archivos y argumentos
  de proceso permanecen fuera de este hito.
- ARC resuelve el ownership interno de strings, no el lifetime general de
  classes ni de los headers de contenedores.

## Dogfooding — July 2026

### Added

- `examples/numerical_methods/`: bisección, Newton-Raphson, secante, trapecios
  y Simpson organizados en módulos, con callables tipados y resultados de
  estado mediante structs y enums.
- `examples/expense_tracker/`: dominio no matemático con módulos,
  `List<Transaction>`, enums, strings y operaciones de consulta y resumen.

### Improved

- Numerical Methods ejecuta las mismas dieciocho validaciones en AST y
  LLVM/native sin la interfaz provisional usada antes para representar una
  función escalar.
- Expense Tracker ejecuta sus nueve validaciones y el listado final en ambos
  backends; además ejercita crecimiento de listas y lifecycle recursivo de
  strings dentro de structs.
- El dogfooding detectó regresiones reales en el uso de phis, layout agregado y
  ownership de strings, que se corrigieron en las capas correspondientes.

### Notes

- Expense Tracker continúa siendo una demostración en memoria: no implica que
  existan archivos, parsing, argumentos de proceso ni una CLI de aplicación.
- Numerical Methods no convierte todavía esos algoritmos en una stdlib
  distribuible ni añade un módulo `testing`.

## Aggregate Collections — July 2026

### Added

- Soporte LLVM/native para elementos struct nominales, acíclicos y con layout
  conocido dentro de `Array<T>` y `List<T>`.
- Cálculo de tamaño y alineación delegado al layout del target LLVM, con
  storage contiguo y operaciones get/set por valor para los elementos.
- Diagnósticos previos al lowering para combinaciones de campos cuyo layout o
  lifecycle native todavía no está definido.

### Changed

- Las copias, slices y realocaciones de colecciones dejaron de asumir que todo
  elemento tenía tamaño escalar. El camino actual distingue copia lógica,
  relocation y destrucción.

### Improved

- `List<T>` conserva un header estable `{length, capacity, data}` durante el
  crecimiento checked, de modo que todos sus aliases observan la misma lista.
- `Array<T>` mantiene longitud fija, bounds checks y slices con almacenamiento
  independiente.

### Notes

- Array y List son agregados mutables con aliasing por asignación; que un
  elemento struct se almacene y cargue por valor no convierte al contenedor en
  un value type.
- La existencia de Array/List/Vector/Matrix parametrizados no constituye
  soporte para genéricos definidos por el usuario.

## Enums — July 2026

### Added

- Enums nominales sin payload a través de AST, typechecker, IR, SSA y
  LLVM/native.
- Identidad por declaración y módulo, discriminantes deterministas, igualdad,
  impresión y uso en firmas, structs y colecciones compatibles.

### Notes

- LLVM usa `i32` como representación interna; no se declara una ABI pública.
- Payloads, ADTs, bit flags, casts implícitos y pattern matching nuevo no forman
  parte del soporte actual.

## Typed Callables — July 2026

### Added

- Valores callable estructurales con sintaxis `R(P1, ...)` para referencias a
  funciones top-level definidas por el usuario.
- Llamadas indirectas tipadas en AST, IR, SSA y LLVM, incluidas referencias
  importadas, aliases, phis y firmas compatibles con structs por valor.

### Improved

- Los algoritmos numéricos pueden recibir una función sin depender de
  interfaces AST-only ni de un hook específico de plotting.
- Los optimizadores consideran conservadores los efectos de una llamada
  indirecta y preservan sus usos a través del control de flujo.

### Notes

- Las firmas requieren compatibilidad exacta y no incluyen captura.
- Closures, lambdas, métodos enlazados, builtins como valores, retorno de
  callables y funciones genéricas no especializadas siguen fuera del alcance.

## Scalar Math — July 2026

### Added

- Lowering native de la matemática escalar real consolidada para `int` y
  `double`, usando intrinsics LLVM, `libm` o helpers checked según la operación.
- Soporte compilado para `Math.pi` como constante inmediata sin inicialización
  global de módulo.

### Improved

- Firmas canónicas y efectos conocidos para que typechecker, IR, SSA,
  intérpretes y optimizadores compartan la identidad de cada builtin.
- Paridad probada para el subconjunto native de `sin`, `cos`, `tan`, `sqrt`,
  `exp`, `ln`/`log`, `abs`, `floor`, `ceil`, `Math.mod` y
  `Math.factorial`.

### Notes

- El perfil continúa siendo parcial: `float`, `complex`, el catálogo avanzado
  de álgebra lineal y algunos contratos de dominio no tienen paridad native
  completa.
- No existen una constante global `PI` ni una constante `E` públicas.

## Native Modules — July 2026

### Added

- Compilación native multiarchivo desde un programa ya resuelto y chequeado.
- Imports completos y selectivos, aliases, transitividad, privacidad, ciclos y
  mangling basado en identidad semántica para funciones y tipos soportados.

### Changed

- El backend consume la resolución de módulos producida por el frontend; no
  vuelve a interpretar nombres o rutas desde el texto fuente.

### Notes

- Globals, constantes con storage e instrucciones ejecutables de módulos
  importados aún no tienen un modelo completo de inicialización native y se
  rechazan antes del lowering.

## Backend Validation — July 2026

### Added

- Perfiles versionados de capacidades para separar lenguaje válido de
  superficie ejecutable por AST o LLVM/native.
- Verificación SSA de dominancia, orden de usos, estructura de CFG e incoming
  exactos de phis, incluidos backedges y bloques inalcanzables.
- Verificación obligatoria después de construir SSA, durante los pases de
  optimización en desarrollo/tests y antes de emitir LLVM.

### Improved

- Los diagnósticos de features válidas pero no compilables se producen antes
  del lowering LLVM y conservan ubicación fuente.
- La tabla común de efectos marca traps, memoria, allocation y mutaciones para
  impedir que los optimizadores eliminen panics o cambios observables.

### Notes

- Los perfiles describen cobertura; no sustituyen al typechecker ni a los
  verificadores de IR/SSA.
- `-O2` existe como nombre reservado para emisión IR, pero actualmente es un
  alias de `-O1`; esas flags no configuran el pipeline SSA del build native.

## Compiler Pipeline — June–July 2026

### Added

- IR tipada con lowering desde el AST chequeado, verifier, printer e intérprete
  experimental.
- CFG, dominadores, fronteras de dominancia y una forma SSA con colocación de
  phis y renaming por árbol de dominadores.
- Optimizadores IR y SSA: constant folding y propagation, simplificación
  algebraica, eliminación de código/stores/phis muertos y SCCP.
- Backend textual LLVM, emisión `.ll`, build con clang y ejecución de binarios
  temporales desde la CLI.

### Changed

- `GeneralSSABuilder` pasó a ser el constructor SSA predeterminado; el builder
  por patrones quedó como comparación limitada.
- La ruta native se consolidó como AST chequeado → IR verificada → SSA
  verificada y optimizada → LLVM → clang.

### Notes

- El intérprete AST continúa siendo la referencia con mayor superficie. La
  existencia de un tipo u opcode en IR no implica por sí sola soporte native.

## Language Foundation — May–June 2026

### Added

- Núcleo aislado de Aether con lexer, parser, AST, typechecker, intérprete,
  sesiones persistentes y REPL.
- Funciones tipadas, `void`, control de flujo, módulos, imports, visibilidad,
  aliases y diagnósticos con ubicación.
- Structs como value types y classes como reference types, ambos con
  constructores y métodos en el backend AST; interfaces mínimas y enums
  nominales sin payload.
- Separación entre `List<T>`, `Array<T>` y los tipos matemáticos Vector/Matrix;
  Lists dinámicas, Arrays de longitud fija y una primera API de colecciones.
- Builtins matemáticos y una base de álgebra lineal para experimentación
  numérica.

### Changed

- Aether pasó a ser el lenguaje activo del proyecto; MathLab/MathTeX quedó
  aislado en `legacy/` como material histórico.
- El foco dejó de ser únicamente un entorno de cálculo y documentos
  ejecutables: el núcleo se orientó a programas de propósito general sin
  abandonar la ergonomía matemática.

### Notes

- Classes, interfaces, excepciones, input y parte de la computación científica
  siguen disponibles solo mediante el intérprete AST.
