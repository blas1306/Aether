# Aether

Aether es un lenguaje de programación estático y compilado de propósito
general, con una ergonomía especialmente orientada a matemática, métodos
numéricos y simulaciones.

La meta es **100 % núcleo general y 130 % ergonomía matemática**: permitir que
una exploración numérica crezca hasta un programa nativo completo sin cambiar
de lenguaje y sin relegar módulos, tipos, errores o IO a soluciones
improvisadas. Aether no intenta reemplazar a Python, Julia, C++, Rust, Java o
C# en todos los escenarios.

El proyecto está en desarrollo activo y **no está listo para producción**. El
frontend/intérprete AST cubre una superficie mayor que el compilador native;
las diferencias se documentan explícitamente en la
[auditoría de paridad](docs/aether/BACKEND_FEATURE_PARITY.md).

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

### Estable dentro del prototipo actual

- lexer, parser, AST y typechecker con diagnósticos de ubicación;
- `int` checked de 32 bits, `double`, `boolean`, funciones tipadas y `void`;
- `if`, `while`, rangos, `for-in`, `break`, `continue` y short-circuit;
- entry point explícito `int main()` o script normalizado a `main`;
- argumentos de proceso mediante snapshots owned `System.args()` y forwarding
  del CLI después de `--`;
- archivos de texto UTF-8 con `io.readText`, `io.writeText` e `io.appendText`,
  resultados nominales y bytes length-aware;
- structs por valor, constructores, métodos, `this`, copia, igualdad e
  impresión para el subconjunto de campos soportado por backend;
- núcleo compilado de Array/List con bounds, overflow y allocation checks;
- literales y operaciones básicas compiladas de Vector/Matrix con índices
  públicos 1-based;
- `print`/`println` escalares y ejecución/build native con clang.

“Estable” aquí significa cubierto y coherente para ese alcance; no implica API
congelada, seguridad para producción ni v1 terminada.

### Parcial

- strings: transporte UTF-8 owned, concatenación, igualdad, `byteLength`, `trim` y `split`
  y parsing están en AST/native; interpolación y formatting siguen parciales;
- Vector/Matrix: el núcleo es native, la mayor parte de `Math.LinearAlgebra`
  sigue en AST;
- casts y `%`: native cubre `int <-> double` y remainder entero, no toda la
  superficie aceptada por el frontend;
- callables: AST/native cubren referencias a funciones top-level de usuario
  sin captura con firma exacta; faltan closures, lambdas, métodos enlazados,
  builtins como valores y retorno de callables;
- CLI/tooling: el CLI es funcional, pero el backend LLVM predeterminado cubre
  menos lenguaje que AST; LSP e IntelliJ son todavía incrementales;
- niveles `-O`: existen para `--emit-ir`; `-O2` actualmente equivale a `-O1`.

### Experimental o solo AST

- módulos de archivo, packages, imports/aliases y visibilidad son parciales en native;
- classes por referencia e interfaces siguen solo AST;
- enums nominales sin payload son completos en AST/native (`i32` interno en LLVM);
- expression functions `f(x) = ...`, tuples y destructuring;
- `input`, `throw`/`try`/`catch`, nullable y `complex`;
- builtins matemáticos escalares y álgebra lineal avanzada;
- REPL persistente y plotting.

Estas capacidades son útiles para dogfood, pero no deben presentarse como
compilación nativa completa.

### Planeado

- globals/inicialización de módulos y tipos de referencia en native;
- input native, archivos binarios/streams/directorios y environment variables;
- módulo `testing` y una stdlib Aether distribuible;
- frontera futura de interoperabilidad por ABI C.

No son objetivos v1: `Any`, GC híbrido complejo, LINQ, ORM, web/GUI, GPU, JIT
sofisticado, macros avanzadas, async completo, registry público, ML propio ni
reimplementaciones de NumPy/SciPy/BLAS/LAPACK.

## Documentos de consolidación v1

- [Alcance formal de Aether v1](docs/aether/AETHER_V1_SCOPE.md)
- [Auditoría completa de paridad](docs/aether/BACKEND_FEATURE_PARITY.md)
- [Diseño de builtins, stdlib y paquetes oficiales](docs/aether/BUILTINS_AND_STDLIB_DESIGN.md)
- [Ejemplo modular de métodos numéricos](examples/numerical_methods/README.md)
- [Informe de fricciones del ejemplo](docs/aether/NUMERICAL_METHODS_DOGFOOD_REPORT.md)
- [Especificación Aether v0](docs/aether/AETHER_V0_SPEC.md), aún normativa para
  sintaxis pero con pasajes históricos identificados en la auditoría

La sintaxis está temporalmente congelada durante esta consolidación. Los
cambios requieren una ambigüedad, inconsistencia, bloqueo evolutivo, problema
de ergonomía demostrado o incompatibilidad seria entre backends; no basta una
preferencia estética.

## Instalación y primer uso

Desde un entorno Python de desarrollo:

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
`FileStatus status = io.writeText(path, content)`/`io.appendText(...)`. No
normaliza newlines ni agrega terminadores; native está disponible por ahora en
Linux/POSIX.

Ejecutar la superficie más amplia con el intérprete AST:

```bash
aether --backend=ast examples/numerical_methods/main.ae
```

Producir un ejecutable permanente:

```bash
aether build examples/llvm/gcd_iterative.ae -o build/gcd
./build/gcd
```

El backend native y `build` requieren `clang` en `PATH`. No existe fallback
silencioso a AST: si una feature válida solo en AST llega al compilador, el CLI
falla con un diagnóstico.

## Backends y pipeline

### AST

`--backend=ast` usa:

```text
Lexer -> Parser -> TypeChecker -> EntryPointNormalizer -> AST Interpreter
```

Es el backend con mayor cobertura y el usado por el REPL. Incluye módulos,
classes, interfaces, exceptions, input y builtins científicos que aún no
compilan.

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
sort y ciertos agregados. No tiene GC, ownership completo de classes ni FFI
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
```

`GeneralSSABuilder` es el builder predeterminado. Usa CFG, dominadores y
fronteras de dominancia. El builder `pattern` se conserva como comparación
temporal y soporta menos formas.

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

El backend AST resuelve un módulo `A.B` como `A/B.ae` desde el directorio del
archivo de entrada. Soporta:

- `package A.B;`
- `import A.B;` e `import A.B as Alias;`
- `from A.B import name;` y alias selectivos;
- exports públicos, colisiones y detección de ciclos;
- inicialización de módulo una vez por sesión.

El compilador native rechaza imports: todavía no existe unidad multi-módulo,
link ni contrato de inicialización compilada.

## REPL, LSP y editor

```bash
aether --repl
```

El REPL usa `AetherSession`, conserva variables/funciones y revierte una entrada
fallida sin destruir el estado confirmado. Solo admite AST.

El paquete `src/aether_lsp/` ofrece diagnósticos y soporte incremental de
completion, hover y símbolos. El plugin IntelliJ vive en
`tools/intellij-aether/`; la aplicación de escritorio opcional se inicia con:

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
- `src/`: aplicación/editor activos.
- `tests/`: tests del lenguaje, compiler, CLI, LSP y UI.
- `examples/`: programas Aether activos.
- `benchmarks/`: microbenchmarks del pipeline.
- `docs/aether/`: especificación, alcance y diseños de lenguaje.
- `docs/compiler/`: implementación y auditorías históricas del compilador.
- `legacy/`: MathTeX Studio aislado.

El empaquetado activo descubre código bajo `src/` y pytest recoge `tests/`.
`src/aether/` y el CLI no importan `legacy/`.

## Desarrollo y validación

Suite principal:

```bash
PYTHONPATH=src .venv/bin/pytest
git diff --check
```

Pipeline local completo:

```bash
python scripts/ci.py
```

Incluye whitespace, pytest, benchmarks rápidos, smoke LLVM y builds clang. Los
tests de integración native se omiten cuando clang no está disponible. Detalle:
[docs/compiler/CI.md](docs/compiler/CI.md).

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
