# Aether

Aether es un lenguaje de programación estático y compilado de propósito
general, con una ergonomía especialmente orientada a matemática, métodos
numéricos y simulaciones.

La meta es **100 % núcleo general y 130 % ergonomía matemática**: permitir que
una exploración numérica crezca hasta un programa nativo completo sin cambiar
de lenguaje y sin relegar módulos, tipos, errores o IO a soluciones
improvisadas. Aether no intenta reemplazar a Python, Julia, C++, Rust, Java o
C# en todos los escenarios.

Aether está preparando **`1.0.0-rc.4`**. Es un candidato para validar el
contrato v1 y el perfil native 23, no una release final ni una declaración de
production-readiness. El frontend/intérprete AST cubre una superficie mayor
que el compilador native; la frontera aceptada está definida por la
[especificación normativa v1](docs/aether/AETHER_LANGUAGE_SPEC_V1.md) y el
[perfil native normativo](docs/aether/AETHER_NATIVE_PROFILE_V1.md).

La sintaxis de control vigente, introducida en `1.0.0-rc.2`, usa headers
parentizados: `if (condition)`, `while (condition)` y
`for (binding in iterable)`. El código escrito para rc.1 debe migrarse; las
formas sin paréntesis se rechazan con un diagnóstico dedicado. La
compatibilidad fuente con rc.1 no está garantizada; el migrador token-aware
actualiza fuentes sin alterar strings ni comentarios.

```aether
struct Point {
    double x;
    double y;

    double squaredNorm() {
        return x * x + y * y;
    }
}

int main() {
    Point point = Point(3.0, 4.0);
    println(point.squaredNorm());
    return 0;
}
```

Este programa pasa por typechecker, IR, SSA, optimizaciones, LLVM y clang, e
imprime `25`.

## Estado real

### Comprometido dentro del candidato actual

- lexer, parser, AST y typechecker con diagnósticos de ubicación;
- `int` checked de 32 bits, `double`, `boolean`, funciones tipadas y `void`;
- `if`, `while`, rangos, `for-in`, `break`, `continue` y short-circuit;
- entry point explícito `int main()` o script normalizado a `main`;
- argumentos de proceso mediante snapshots owned `System.args()` y forwarding
  del CLI después de `--`;
- archivos de texto UTF-8 con `io.readText`, `io.writeText`,
  `io.writeTextAtomic` e `io.appendText`,
  resultados nominales y bytes length-aware;
- persistencia ALPT1 manual del Expense Tracker en AST/native Linux, con
  payloads length-prefixed, rechazo fail-closed y save atómico/durable POSIX;
- structs por valor, constructores, métodos, `this`, copia, igualdad e
  impresión para el subconjunto de campos soportado por backend;
- nullable tagged, classes por referencia con ARC/fields/constructores/métodos
  e interfaces con witness dispatch, carriers class y boxing owned de structs;
- núcleo compilado de Array/List con bounds, overflow y allocation checks;
- literales y operaciones básicas compiladas de Vector/Matrix con índices
  públicos 1-based;
- `print`/`println` escalares y ejecución/build native con clang.

“Comprometido” aquí significa cubierto y coherente para el contrato RC; no
implica ABI estable, seguridad para producción ni v1 final terminada.

### Parcial

- strings: transporte UTF-8 owned, concatenación, igualdad, `byteLength`, `trim` y `split`
  y parsing están en AST/native; interpolación y formatting siguen parciales;
- Vector/Matrix: el núcleo es native, la mayor parte de `Math.LinearAlgebra`
  sigue en AST;
- numéricos: native cubre promoción contextual `int -> double`, operaciones
  mixtas `int`/`double`, casts identidad/int↔double, `%` real y potencia
  checked/IEEE; `float` y `complex` siguen fuera del perfil native estable;
- callables: AST/native cubren referencias a funciones top-level de usuario
  sin captura con firma exacta; faltan closures, lambdas, métodos enlazados,
  builtins como valores y retorno de callables;
- CLI/tooling: el CLI es funcional, pero el backend LLVM predeterminado cubre
  menos lenguaje que AST; LSP e IntelliJ son todavía incrementales;
- niveles `-O`: existen para `--emit-ir`; `-O2` actualmente equivale a `-O1`.

### Experimental o solo AST

- módulos de archivo, packages, imports/aliases y visibilidad son parciales en native;
- enums nominales sin payload son completos en AST/native (`i32` interno en LLVM);
- funciones abreviadas tipadas `f(double x) = ...`, tuples y destructuring;
- `input`, `throw`/`try`/`catch` y `complex`; las excepciones tienen lowering
  native interno de calificación, pero el perfil estable aún las rechaza;
- builtins matemáticos escalares y álgebra lineal avanzada;
- REPL persistente y plotting.

Estas capacidades son útiles para dogfood, pero no deben presentarse como
compilación nativa completa.

### Planeado

- globals/inicialización de módulos;
- input native, archivos binarios/streams/directorios y environment variables;
- módulo `testing` y una stdlib Aether distribuible;
- frontera futura de interoperabilidad por ABI C.

No son objetivos v1: `Any`, GC híbrido complejo, LINQ, ORM, web/GUI, GPU, JIT
sofisticado, macros avanzadas, async completo, registry público, ML propio ni
reimplementaciones de NumPy/SciPy/BLAS/LAPACK.

## Documentos de consolidación v1

- [Especificación normativa Aether v1](docs/aether/AETHER_LANGUAGE_SPEC_V1.md)
- [Perfil native normativo v1 / capability profile 23](docs/aether/AETHER_NATIVE_PROFILE_V1.md)
- [Índice y clasificación documental](docs/aether/README.md)
- [Alcance formal de Aether v1](docs/aether/AETHER_V1_SCOPE.md)
- [Auditoría completa de paridad](docs/aether/BACKEND_FEATURE_PARITY.md)
- [Diseño de builtins, stdlib y paquetes oficiales](docs/aether/BUILTINS_AND_STDLIB_DESIGN.md)
- [Ejemplo modular de métodos numéricos](examples/numerical_methods/README.md)
- [Informe de fricciones del ejemplo](docs/aether/NUMERICAL_METHODS_DOGFOOD_REPORT.md)
- [Especificación Aether v0](docs/aether/AETHER_V0_SPEC.md), conservada como
  documento histórico y no como contrato vigente

La sintaxis está temporalmente congelada durante esta consolidación. Los
cambios requieren una ambigüedad, inconsistencia, bloqueo evolutivo, problema
de ergonomía demostrado o incompatibilidad seria entre backends; no basta una
preferencia estética.

## Instalación y primer uso

Desde un wheel RC construido localmente (no se publica automáticamente):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install dist/aether_language-1.0.0rc4-py3-none-any.whl
.venv/bin/aether --version
```

El resultado esperado identifica por separado lenguaje y perfil:

```text
Aether 1.0.0-rc.4
Native capability profile 23
```

Para un checkout de desarrollo:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -e . --no-deps
```

Ejecutar un archivo con el backend predeterminado LLVM/native:

```bash
aether examples/llvm/gcd_iterative.ae
```

Pasar argumentos al programa (el shell ya resuelve quoting):

```bash
aether run program.ae -- add "Dinner with friends"
```

El programa consulta `System.args()` tras `import System;`. El array no incluye
el ejecutable, `run`, el archivo ni `--`. Sin separador se entregan cero
argumentos.

La API mínima de archivos requiere `import io;`. Es exclusivamente de texto
UTF-8: `FileReadResult loaded = io.readText(path)` y
`FileStatus status = io.writeText(path, content)`/`io.writeTextAtomic(...)`/
`io.appendText(...)`. No
normaliza newlines ni agrega terminadores; native está disponible por ahora en
Linux/POSIX.

El Expense Tracker demuestra persistencia estructurada sin JSON/reflection:

```bash
aether run examples/expense_tracker/Main.ae -- expenses.alpt add expense 1 19.95 food "Lunch" 2026-07-16
aether run examples/expense_tracker/Main.ae -- expenses.alpt list
```

El archivo usa ALPT1 revision 1. `saveLedger` publica mediante
`io.writeTextAtomic`: temporal seguro, fsync, rename y fsync del directorio en
POSIX; no añade locking ni backups.

Ejecutar la superficie más amplia con el intérprete AST:

```bash
aether --backend=ast examples/numerical_methods/main.ae
```

Producir un ejecutable permanente:

```bash
aether build examples/llvm/gcd_iterative.ae -o build/gcd
./build/gcd
```

El backend native y `build` están validados para **Linux x86_64** y requieren
`clang` en `PATH` (clang no se incluye en el wheel). Windows y POSIX genérico
no se declaran soportados. No existe fallback silencioso a AST: si una feature
válida solo en AST llega al compilador, el CLI falla con un diagnóstico.

## Backends y pipeline

### AST

`--backend=ast` usa:

```text
Lexer -> Parser -> TypeChecker -> EntryPointNormalizer -> AST Interpreter
```

Es el backend con mayor cobertura y el usado por el REPL. Incluye
inicialización de módulos, exceptions, input y builtins científicos fuera del
perfil estable. Las excepciones disponen de una ruta native interna, no pública,
que permanece detrás de `AE-BACKEND-ERROR_HANDLING`; classes, nullable e
interfaces sí compilan en native estable.

### IR interpreter

`--backend=ir` usa:

```text
Lexer -> Parser -> TypeChecker -> EntryPointNormalizer
      -> IR lowering -> IR verifier -> IR interpreter
```

Es una herramienta experimental para caracterizar el modelo IR. Requiere un
entry point normalizado y cubre exactamente lo que el lowering acepte; no
ejecuta módulos ni features AST-only.

### LLVM/native

El comando simple `aether file.ae` usa:

```text
Lexer -> Parser -> TypeChecker -> EntryPointNormalizer
      -> IR lowering -> IR verifier
      -> GeneralSSABuilder -> SSA verifier -> SSAOptimizerPipeline
      -> LLVM printer + runtime helpers -> clang -> proceso nativo
```

La ejecución temporal propaga stdout, stderr y exit code y elimina sus
artefactos. `aether build` conserva el ejecutable; `--keep-llvm` conserva
también el `.ll`.

El runtime LLVM actual aporta IO, contexto de argumentos y helpers checked para
aritmética entera, strings UTF-8, allocations, Array, List, Vector, Matrix,
sort, nullable, classes e interfaces. Classes usan ARC fuerte y las interfaces
ownership dinámico por witness; los ciclos no se recolectan y no hay FFI
pública.

## Herramientas del compilador

```bash
aether --tokens program.ae
aether --ast program.ae
aether --emit-ir program.ae
aether --emit-ir -O0 program.ae
aether --emit-ir -O1 --show-passes program.ae
aether --emit-ir -O2 program.ae
aether --emit-cfg program.ae
aether --emit-ssa program.ae
aether --emit-ssa --ssa-builder=pattern program.ae
aether --emit-ssa --ssa-builder=general program.ae
aether --emit-llvm program.ae
aether --check program.ae
aether --debug --emit-llvm program.ae
```

`GeneralSSABuilder` es el builder predeterminado. Usa CFG, dominadores y
fronteras de dominancia. El builder `pattern` se conserva como comparación
temporal y soporta menos formas. Los visitantes de operandos IR/SSA son
estructurales y la suite verifica que una instrucción nueva no quede fuera de
DCE, SCCP o las reescrituras de valores.

Los niveles del optimizer IR se conectan únicamente a `--emit-ir`:

- `-O0`: sin pases;
- `-O1`: folding, propagación local, simplificación algebraica, dead code y
  dead stores hasta punto fijo;
- `-O2`: alias actual de `-O1`, reservado para un nivel futuro más fuerte.

El pipeline native siempre ejecuta su pipeline SSA actual; esas flags no lo
configuran. Los efectos comunes de instrucciones (`may_trap`, reads/writes,
allocation y side effects) impiden que DCE/SCCP eliminen panics o mutaciones
observables. El verificador SSA todavía tiene deuda de dominancia/phis señalada
en la auditoría.

## Datos y matemática

### Array y List

`Array<T>` es contiguo y de longitud fija. Su núcleo native incluye literal,
get/set, length, slicing, sort y safety checked. `List<T>` usa un header
`{length, capacity, data}` y soporta crecimiento, push/pop, insert/removeAt,
clear, contains/indexOf, reverse, copy y sort.

Asignación, parámetros y retornos aliasan los contenedores mutables; `copy()`
crea el contenedor externo independiente. Structs son valores, pero sus campos
que ya son reference-like mantienen copia shallow.

### Vector y Matrix

`Vector<T, Row>`, `Vector<T, Column>` y `Matrix<T>` son tipos matemáticos, no
aliases de List ni `Array<Array<T>>`. Usan índices públicos 1-based y storage
interno contiguo/0-based. El backend cubre shape, get/set, igualdad, impresión y
operaciones básicas seleccionadas. Solvers, factorizaciones, eig/SVD y buena
parte de `Math.LinearAlgebra` son todavía AST-only.

### Métodos numéricos dogfood

[`examples/numerical_methods/`](examples/numerical_methods/) contiene
bisección, Newton-Raphson, secante, trapecios y Simpson con módulos,
`RootResult`, tolerancia, límites de iteración y validaciones. Usa el alias
callable `double(double)` y el mismo programa multi-módulo se valida en AST y
LLVM/native; no necesita ya la antigua interfaz `ScalarFunction`.

```bash
aether --backend=ast examples/numerical_methods/main.ae
```

## Módulos y imports

El frontend resuelve un módulo `A.B` como `A/B.ae` desde el directorio del
archivo de entrada. AST soporta inicialización de módulo y native profile 23
compila el subconjunto de declaraciones sin storage/import-time execution:

- `package A.B;`
- `import A.B;` e `import A.B as Alias;`
- `from A.B import name;` y alias selectivos;
- exports públicos, colisiones y detección de ciclos;
- inicialización de módulo una vez por sesión.

Native soporta funciones, structs, enums, métodos, callables y firmas
cross-module compatibles con el perfil. Rechaza globals, constantes que
requieren storage y statements ejecutables importados porque todavía no existe
inicialización compilada de módulos.

## REPL, LSP y editor

```bash
aether --repl
```

El REPL usa `AetherSession`, conserva variables/funciones y revierte una entrada
fallida sin destruir el estado confirmado. Solo admite AST.

El paquete `src/aether_lsp/` ofrece el servidor compartido de diagnósticos,
completion, hover y símbolos. El plugin IntelliJ vive en
`tools/intellij-aether/`. La extensión oficial de VS Code, todavía en
desarrollo y no publicada, vive en `vscode-extension/`; ambos editores usan el
mismo LSP y mantienen la semántica en Aether. La aplicación de escritorio
opcional se inicia con:

```bash
python3 src/main.py
```

MathTeX Studio y sus formatos `.mtx`, `.mtex`, `.mtn`, notebooks y PDF son
código histórico aislado bajo [`legacy/`](legacy/), no parte del runtime Aether
activo.

## Benchmarks

El harness de desarrollo separa preparación/compilación de ejecución:

```bash
aether bench benchmarks/sum_to.ae --backend ast
aether bench benchmarks/sum_to.ae --backend ir
aether bench benchmarks/sum_to.ae --backend all --iterations 20
```

Los perfiles incluyen AST, IR, SSA, LLVM emit, native build y native runtime.
Son mediciones aproximadas locales, no una suite científica de performance.
Véase [benchmarks/README.md](benchmarks/README.md).

## Historia y decisiones de diseño

- [Changelog de hitos](CHANGELOG.md)
- [Evolución de Aether](docs/EVOLUTION.md)

## Arquitectura del repositorio

- `src/aether/`: frontend, intérprete, IR, SSA, backend LLVM, runtime, CLI y
  builtins actuales.
- `src/aether_lsp/`: servidor de lenguaje.
- `vscode-extension/`: extensión oficial de VS Code en desarrollo, cliente del
  LSP y del CLI externos.
- `tools/intellij-aether/`: plugin IntelliJ, también cliente del LSP compartido.
- `src/`: aplicación/editor activos.
- `tests/`: tests del lenguaje, compiler, CLI, LSP y UI.
- `examples/`: programas Aether activos.
- `benchmarks/`: microbenchmarks del pipeline.
- `docs/aether/`: especificación, alcance y diseños de lenguaje.
- `docs/compiler/`: implementación y auditorías históricas del compilador.
- `legacy/`: MathTeX Studio aislado.

El empaquetado activo descubre código bajo `src/`, incluye stdlib, runtime LLVM
generado y los dos documentos normativos, y pytest recoge `tests/`.
`src/aether/` y el CLI no importan `legacy/`.

## Desarrollo y validación

Suite principal:

```bash
PYTHONPATH=src .venv/bin/pytest
git diff --check
```

Pipeline local completo:

```bash
.venv/bin/python scripts/ci.py
```

Incluye integridad documental, contrato público de diagnósticos/ICE, compileall,
whitespace, pytest, benchmarks,
corpus diferencial en clang O0/O1/O2, smoke LLVM y builds native. Los tests de
integración native se omiten cuando clang no está disponible. Detalle:
[docs/compiler/CI.md](docs/compiler/CI.md).

Los errores públicos se dividen en `syntax`, `type`, `capability`, `runtime`,
`toolchain` e `internal_compiler_error`. Los ICE no muestran traceback salvo
con `--debug`; códigos y exit codes están documentados en el
[contrato de diagnósticos](docs/aether/AETHER_DIAGNOSTICS.md).

El gate de release no publica ni crea tags:

```bash
.venv/bin/python scripts/release.py
```

Exige worktree limpio. Para validar cambios locales antes de commit se requiere
el flag explícito `--allow-dirty`; el manifest deja `dirty_worktree: true` y el
artefacto no debe publicarse. El comando construye wheel/sdist, instala el wheel
en un venv limpio, ejecuta smokes AST/native/imports/strings/collections/argv/
files/capability-gate y genera manifest más `SHA256SUMS` en `dist/`. No se
afirma reproducibilidad bit por bit.

Documentación técnica adicional:

- [IR design](docs/aether/AETHER_IR_DESIGN.md)
- [SSA construction](docs/compiler/SSA_CONSTRUCTION.md)
- [SSA builder](docs/compiler/SSA_BUILDER.md)
- [SCCP](docs/compiler/SCCP.md)
- [Array subsystem audit](docs/compiler/ARRAY_SUBSYSTEM_AUDIT.md)
- [List subsystem audit](docs/compiler/LIST_SUBSYSTEM_AUDIT.md)
- [Vector/Matrix design](docs/aether/AETHER_VECTOR_MATRIX_DESIGN.md)

Varias de estas notas conservan secciones históricas. Para cualquier afirmación
de soporte actual, prevalecen código, tests y la auditoría canónica de paridad.
