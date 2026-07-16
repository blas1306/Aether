# Frontera entre builtins, stdlib y paquetes oficiales

Estado: diseño para consolidación de v1, 14 de julio de 2026. Este documento
clasifica responsabilidades; no migra masivamente la librería
actual.

## Principio rector

Aether tendrá tres niveles:

1. **Builtins e intrínsecos**: operaciones que el compilador o runtime debe
   conocer por representación, semántica, seguridad u optimización esencial.
2. **Librería estándar**: APIs disponibles con la distribución, versionadas
   con el lenguaje y, siempre que sea posible, escritas en Aether sobre un
   núcleo pequeño.
3. **Paquetes oficiales**: capacidades mantenidas por el proyecto pero con
   ciclo, dependencias y peso separados del lenguaje y la stdlib.

La regla para añadir un intrínseco es:

> Una operación solo debe ser intrínseca cuando requiera acceso directo a la
> representación, semántica especial, garantías de seguridad, optimización
> esencial o no pueda expresarse eficientemente en Aether.

Que una operación se sienta builtin no obliga a crear un nodo AST, opcode o
helper de runtime específico. Una llamada conocida puede resolverse a stdlib,
un LLVM intrinsic, `libm` o runtime durante lowering.

La aplicación concreta de esta frontera a strings se decide en
[`STRING_RUNTIME_DESIGN.md`](STRING_RUNTIME_DESIGN.md), con lifecycle en
[`VALUE_LIFECYCLE_DESIGN.md`](../compiler/VALUE_LIFECYCLE_DESIGN.md). El diseño
está aprobado. Las primitivas internas de objeto UTF-8, ARC, igualdad e
impresión length-aware ya están implementadas; todavía no declara implementado el módulo
`text` descritos allí.

El núcleo público implementado añade dos operaciones que requieren conocer la
representación: `string + string` y la property `s.byteLength`. `+` nunca
convierte números, booleanos ni valores nominales; puede asignar y hacer panic.
`byteLength` es O(1) y cuenta bytes UTF-8, no code points ni graphemes.

El perfil 15 añade `parseInt(string)` y `parseDouble(string)` como builtins
globales explícitos. Esta ubicación coincide con los builtins globales actuales
y evita fingir un método estático que el lenguaje todavía no soporta. Devuelven
`IntParseResult`/`DoubleParseResult` con `ParseStatus`; su gramática byte-aware,
defaults y política IEEE están en
[`STRING_PARSING_DESIGN.md`](STRING_PARSING_DESIGN.md). Son intrínsecos porque
native necesita acceso length-aware al objeto string y control explícito del
locale, no porque exista una conversión implícita.

## Nivel 1: builtins e intrínsecos

### Candidatos legítimos

- tipos primitivos y sus operadores;
- conversiones primitivas checked;
- `panic` y terminación anormal segura;
- representación, allocation y bounds checks de `Array<T>`;
- primitivas de representación dinámica de `List<T>`;
- representación contigua, shape e índices de `Vector<T>` y `Matrix<T>`;
- impresión/entrada mínimas necesarias para bootstrap;
- funciones escalares fundamentales cuando mapearlas a LLVM/`libm` evite una
  implementación incorrecta o ineficiente;
- constantes plegables seleccionadas como `PI` y `E`.

### Lo que no debe ser intrínseco por defecto

- `contains`, `map`, `filter`, `reduce`, estadísticas o algoritmos de búsqueda;
- factorizaciones, eig, SVD o solvers de alto nivel;
- plotting;
- una instrucción IR por cada nombre de método público;
- nombres de proveedor como `dgemm` en el IR semántico.

El IR debe expresar, cuando sea útil, una operación semántica como
`matrix_matmul`. El backend puede seleccionar BLAS/LAPACK por tipo, tamaño y
plataforma sin acoplar el lenguaje a un símbolo concreto.

## Nivel 2: estructura propuesta de stdlib

No todos los módulos son requisito de v1. La tabla distingue el mínimo de
salida del crecimiento posterior.

| Módulo | Responsabilidad | Dependencias | Mínimo v1 | Puede esperar | Escribible en Aether | Necesita runtime/intrínseco |
| --- | --- | --- | --- | --- | --- | --- |
| `io` | consola, streams y archivos básicos | `text`, `system` mínimo | print/println, input tipado, archivo texto básico y errores | buffering avanzado, codecs extensibles | wrappers, lectura por líneas, helpers | stdin/stdout/stderr, handles, bytes, close |
| `text` | strings, búsqueda, split/join y conversión | runtime string | encoding definido, `byteLength`, concat e igualdad | substring, slicing/views, regex, normalización Unicode completa | algoritmos sobre iteración de code units/points | representación, allocation, decoding/encoding |
| `collections` | colecciones generales | generics, equality; hashing para Map/Set | APIs derivadas de Array/List que se seleccionen | Map, Set, Queue, Stack si hashing/generics no están listos | la mayoría de algoritmos y estructuras | allocation y primitivas Array/List |
| `time` | reloj monotónico, fecha/duración mínima | `system` | reloj monotónico para medición | zonas horarias, calendarios | Duration y formato parcial | clocks del SO |
| `system` | proceso, args, entorno, exit, plataforma | runtime/ABI C | argumentos, código de salida, variables de entorno seleccionadas | procesos hijos completos | wrappers y validación | llamadas del SO/libc |
| `testing` | asserts, suites y resultados | `io`, errores | `assert`, comparación y runner reproducible | property testing, mocks | casi todo | exit code/stack mínimo opcional |
| `math` | escalares, constantes y utilidades numéricas | LLVM/`libm` | núcleo escalar y `PI`; decidir `E` | funciones especiales | composición y wrappers | intrinsics/`libm` para primitivas |
| `math.linalg` | álgebra lineal de Vector/Matrix | math, storage contiguo, BLAS/LAPACK opcional | operaciones básicas y un contrato de shapes | eig/SVD/factorizaciones amplias | validación, algoritmos pequeños, dispatch | kernels, FFI y allocations eficientes |
| `math.statistics` | estadística descriptiva | collections/iterables, math | no requerida en esta tarea; candidata posterior | distribuciones e inferencia | sí, tras decidir tipos/iterables | no salvo kernels opcionales |
| `math.numerics` | raíces, integración, interpolación, ODE | math, callables, testing | puede comenzar con bisección/Newton/secante/trapecios/Simpson cuando haya callable estable | solvers avanzados y adaptativos | sí | solo primitivas escalares |
| `math.complex` | complejo como abstracción de biblioteca | generics, operadores | no requerido para v1 si bloquea el núcleo | funciones complejas avanzadas | idealmente sí | posiblemente intrinsics/ABI para rendimiento |
| `math.random` | RNG y distribuciones básicas | system entropy, math | semilla explícita y generador reproducible si entra en v1 | catálogo amplio/crypto RNG | algoritmos PRNG | entropy del sistema; no para cada sample |

Los nombres públicos nuevos deben usar minúsculas. Los namespaces actuales
`Math`, `Math.LinearAlgebra` y `Plots` se conservan mientras se define una
migración compatible; no se renombran en este bloque.

## Nivel 3: paquetes oficiales

Fuera de stdlib deben vivir capacidades con dependencias pesadas, ritmo propio
o dominio especializado:

- plotting y visualización (`plot`, `visualization` o `aether.plot`);
- data tooling y formatos externos;
- integraciones con sistemas de terceros;
- scientific avanzado;
- wrappers de alto nivel de BLAS/LAPACK si no forman el backend interno de
  `math.linalg`.

`Plot` no pertenece conceptualmente a `Math`. El repositorio ya registra
plotting como namespace `Plots` y lo implementa en `src/aether/stdlib/plots.py`;
esa separación conceptual es correcta, aunque el archivo siga bajo el paquete
Python llamado `stdlib` por razones históricas. No se migra ahora.

Un paquete oficial puede usar ABI C y dependencias opcionales. La instalación
del compilador y el runtime mínimo no debe depender obligatoriamente de Python,
NumPy, SciPy o un stack gráfico.

## Decisiones por tipo y familia

### `Array<T>`

Debe seguir siendo builtin o un tipo privilegiado porque su layout, allocation,
bounds checks, slicing y paso por ABI afectan al compilador.

Su semántica v1 es la de un reference type mutable de longitud fija. Assignment
copia la referencia; `copy()` y slicing crean otro descriptor y buffer. El
contrato de ownership, const, iteración e igualdad se define en
[`COLLECTION_RUNTIME_DESIGN.md`](COLLECTION_RUNTIME_DESIGN.md).

Primitivas esenciales:

- allocation/literal target-typed;
- `get`, `set`, `length`;
- bounds y overflow checks;
- acceso contiguo para backend/FFI;
- creación de una copia/slice cuando el contrato lo exija.

Métodos derivados para stdlib:

- `contains`, `indexOf`, `reverse`, `map`, `filter`, `reduce`, `find`;
- algoritmos de orden superior y búsquedas no dependientes del layout.

`sort` puede seguir como primitiva optimizable mientras la comparación, el
buffer temporal y los traps estén centralizados; su API pública no obliga a
que siempre sea intrínseca.

### `List<T>`

Puede seguir privilegiada por su header dinámico `{length, capacity, data}` y
por la seguridad del crecimiento.

También es un reference type mutable. Sus aliases comparten header y observan
growth y mutaciones; `copy()` crea un contenedor independiente sin copiar
profundamente referencias anidadas. El runtime debe tratar el handle con el
lifecycle RC aprobado, separado de la copia lógica de elementos.

Primitivas:

- construcción/literal (`new` conceptual, aunque la sintaxis actual use un
  literal target-typed);
- `get`, `set`, `push`, `pop`, `insert`, `removeAt`;
- `length`/`size`, `capacity`, `clear`;
- reserve/growth interno checked.

Derivables en stdlib:

- `contains`, `reverse`, `map`, `filter`, `reduce`, `find`, `indexOf` y
  algoritmos similares.

Hoy varias operaciones derivadas ya poseen opcodes y helpers LLVM. No se
refactorizan en esta tarea: primero se estabiliza el contrato y luego se mide
si expresarlas en Aether conserva seguridad y rendimiento.

### `Vector<T>`

Es un vector matemático orientado, no una colección dinámica equivalente a
`std::vector`. No debe heredar automáticamente la API completa de `List`.
Longitud, orientación, dot/outer product y reglas de shape son parte de su
semántica.

### `Matrix<T>`

Debe conservar storage contiguo (o una representación de igual calidad para
álgebra lineal), dimensiones explícitas y bounds por coordenada. No se modela
conceptualmente como `Array<Array<T>>`, porque eso pierde layout, rectangularidad
y oportunidades de FFI/optimización.

### `Map`, `Set`, `Queue`, `Stack`

Son candidatos a `collections`, preferiblemente implementados en Aether.
`Queue` y `Stack` pueden construirse sobre primitivas existentes antes que
`Map`/`Set`. Estos últimos requieren primero:

- genéricos de usuario suficientemente estables;
- igualdad y hashing con contrato explícito;
- política de mutabilidad e invalidación de iteradores;
- representación y crecimiento seguros.

No son obligatorios para esta consolidación de v1.

### Funciones matemáticas escalares

El inventario actual consolidado es `sin`, `cos`, `tan`, `sqrt`, `exp`, `ln`,
`log`, `abs`, `Math.mod`, `Math.factorial`, `Math.floor` y `Math.ceil`.
`round` y las demás operaciones de `libm` son propuestas futuras, no API
existente. La superficie preferida a futuro es `math.x`
con imports selectivos; mantener aliases globales actuales es una decisión de
compatibilidad separada.

El backend puede elegir:

- LLVM intrinsics;
- `libm` mediante ABI C;
- helpers del runtime;
- calls conocidas con folding seguro.

No se crean nodos AST especiales para cada función. Los errores de dominio,
NaN, infinito y tipos de retorno deben tener un contrato común antes de marcar
el módulo estable.

### `PI` y `E`

El estado actual expone `Math.pi`; no existe una constante `E` registrada y
`PI` no es global. Para no romper compatibilidad:

- v1 debe mantener `Math.pi` y permitir import selectivo;
- la stdlib futura debe normalizar a `math.PI`/`math.E` o a la convención de
  casing que adopte la spec;
- no deben importarse implícitamente nuevas constantes globales;
- el compilador puede plegarlas como constantes conocidas sin convertirlas en
  sintaxis especial.

### `Complex<T>`

El diseño objetivo es un struct genérico de `math.complex`, no un nuevo
primitivo. Sin embargo, el repositorio actual ya contiene un tipo primitivo
experimental `complex`, literales `im` y builtins AST. Retirarlo ahora rompería
compatibilidad y los genéricos/overloads de usuario todavía no permiten
reexpresarlo fielmente como `Complex<T>`.

Decisión de consolidación:

1. no ampliar el primitivo actual ni llevarlo automáticamente al perfil v1;
2. conservarlo como experimental por compatibilidad;
3. diseñar después el struct y las reglas de operadores/conversiones;
4. migrar solo con una ruta de compatibilidad y tests.

### `Statistics`

`math.statistics` es el siguiente módulo matemático candidato, pero no se
implementa en esta tarea. Antes hay que decidir:

- tipos numéricos aceptados y resultado para entradas enteras;
- si consume Array/List, Vector, una interfaz iterable o overloads limitados;
- comportamiento de colecciones vacías;
- varianza poblacional frente a muestral;
- algoritmos numéricamente estables (por ejemplo, actualización online);
- propagación/ignorancia configurable de NaN;
- mutabilidad, allocation y precisión del acumulador.

La ausencia actual de iterables genéricos y funciones de orden superior hace
prematuro fijar una API amplia.

### `math.numerics`

Este es el nombre reservado para métodos numéricos. Evita confundir el dominio
con una interfaz llamada `Numeric`. Su primera API puede evolucionar desde
`examples/numerical_methods/` cuando exista un callable tipado estable. Los
algoritmos son stdlib escribible en Aether; callbacks, tolerancias comunes y
resultados estructurados son el bloqueo de diseño, no una necesidad de nuevos
opcodes.

## Criterio de migración

Mover una operación existente desde builtin hacia stdlib requiere:

1. contrato semántico y de complejidad documentado;
2. implementación Aether equivalente con tests AST/native;
3. medición de rendimiento y tamaño;
4. conservación de panics y efectos frente a optimizadores;
5. compatibilidad de nombre o deprecación explícita.

Hasta cumplirlos, la ubicación Python actual describe implementación, no la
arquitectura pública definitiva.

## Capacidad interna `Eq(T)`

`contains` e `indexOf` son algoritmos derivados de la capacidad semántica
interna `Eq(T)` y tienen costo `O(n · eq(T))`. No definen reglas especiales por
tipo ni consumen el argumento. La misma capacidad gobierna `==`, `!=`, structs
y Array/List anidados. Por ahora no es una interface pública: no hay custom
comparators, hashing, Map/Set ni igualdad de classes/callables. Una interface
pública futura puede reutilizar el concepto, pero no queda prometida por esta
fase.
