# Evolución de Aether

Este documento explica por qué Aether tomó su forma actual. No define la
gramática, no reemplaza la especificación y no promete que una capacidad de
diseño esté disponible en todos los backends. Para el estado detallado
prevalecen el código, los tests y los
[perfiles de capacidades](aether/BACKEND_CAPABILITY_PROFILES.md); la
[auditoría de paridad](aether/BACKEND_FEATURE_PARITY.md) conserva además
snapshots históricos identificados como tales.

## ¿Por qué existe Aether?

Aether nació dentro de un proyecto centrado en cálculo, escritura técnica y
experimentación matemática. Los primeros casos de uso estaban ligados a
métodos numéricos, álgebra lineal, plotting y a la posibilidad de ejecutar
cálculos cerca de los documentos que los explicaban. Esa procedencia todavía
se ve en los literales matemáticos, en Vector y Matrix, en el REPL y en la
atención prestada a funciones escalares y algoritmos numéricos.

La experiencia también mostró un límite: una exploración matemática deja de
ser pequeña en cuanto necesita varios módulos, tipos de dominio, validación de
errores, colecciones, IO o un ejecutable reproducible. Resolver cada una de
esas necesidades como excepción habría producido un lenguaje científico con
un núcleo débil. Por eso Aether se separó del runtime histórico de MathLab y
empezó a consolidarse como un lenguaje propio, con frontend, semántica y
herramientas independientes.

El resultado buscado es un lenguaje de propósito general con una ergonomía
especialmente buena para matemática y computación científica. El ejemplo de
Numerical Methods conserva el origen; Expense Tracker comprueba que las mismas
decisiones sirven fuera de ese dominio. Ninguno de los dos ejemplos define por
sí solo el lenguaje.

## Filosofía

### Propósito general, especialización deliberada

El núcleo debe poder expresar programas que no sean científicos: funciones,
módulos, control de flujo, tipos definidos por el usuario, errores, colecciones
e IO no pueden ser añadidos improvisados. La orientación matemática aparece en
la comodidad de los tipos y bibliotecas, no en una segunda semántica separada.

Aether nunca tuvo como objetivo reemplazar todos los lenguajes existentes. No
pretende ganar a Python, Julia, C++, Rust, Java o C# en cada escenario. Su
objetivo más concreto es permitir que una exploración numérica crezca hasta un
programa nativo coherente sin obligar a cambiar de lenguaje por falta de
fundamentos generales.

### Núcleo pequeño, biblioteca amplia

La dirección de diseño reserva al compilador solo aquello que necesita conocer
para tipar, representar o optimizar correctamente un programa. Bounds checks,
layout de tipos privilegiados y ciertas primitivas matemáticas pueden requerir
soporte del backend. Algoritmos de colecciones, estadística, métodos numéricos
y texto pertenecen preferentemente a módulos escribibles en Aether.

Esto no describe todavía una stdlib distribuida y terminada. El registro actual
incluye builtins y módulos prototipo, varios de ellos implementados en Python
para el intérprete AST. La separación es una dirección arquitectónica: evitar
que cada API útil se convierta en sintaxis o en un opcode permanente.

### Tipado fuerte y semántica visible

Los tipos no son sugerencias para el backend. Firmas, mutabilidad, identidad
nominal, copia, aliasing y fallos checked deben conservarse desde el
typechecker hasta la ejecución. Cuando el backend native todavía no puede
mantener una regla, el perfil debe rechazar el programa de forma explícita en
lugar de ejecutar una aproximación silenciosa.

### Backend moderno y verificable

El backend se construyó por capas: AST chequeado, IR, lifecycle, SSA,
optimizaciones, LLVM y clang. Cada frontera existe para hacer explícita una
clase distinta de invariantes. La arquitectura no persigue complejidad por sí
misma; permite inspeccionar el programa, verificarlo antes de generar código y
mantener separadas la semántica fuente y las decisiones del target.

### Ergonomía matemática sin un lenguaje paralelo

Vector y Matrix son tipos matemáticos con shape, orientación e índices públicos
1-based. Array y List son colecciones de programación con índices 0-based. La
distinción evita convertir una lista dinámica en un vector algebraico o una
matriz en un array anidado irregular. Ambos dominios comparten el sistema de
tipos, las funciones y los módulos; no comparten automáticamente todas sus
operaciones.

## Cómo cambió el proyecto

El primer núcleo ejecutable se apoyó en un AST y un intérprete escritos en
Python. Esa etapa permitió estabilizar sintaxis, scopes, tipos y diagnósticos,
y sigue siendo la superficie con mayor cobertura. Sobre ella aparecieron
módulos, structs, classes, interfaces, enums, Arrays y Lists. También se separó
el producto activo de los formatos y runtimes históricos conservados bajo
`legacy/`.

El paso siguiente fue dejar de identificar «funciona en el intérprete» con
«está implementado en el lenguaje compilado». La IR introdujo una frontera
tipada y verificable; SSA hizo explícito el flujo de valores entre ramas y
loops; los optimizadores adquirieron un modelo común de efectos; LLVM permitió
producir ejecutables nativos con clang. Los perfiles de capacidades surgieron
después para describir honestamente la diferencia entre la superficie AST y la
native.

Los hitos más recientes se guiaron por programas completos. Numerical Methods
forzó una respuesta mínima y reusable para callables, módulos y resultados de
error. Expense Tracker expuso los límites de layout para colecciones de structs
y, más tarde, los de ownership para strings dentro de esos structs. Esa
secuencia convirtió problemas observados en decisiones de arquitectura, sin
ampliar la gramática más de lo necesario.

## Decisiones importantes

### Structs

Los structs son value types porque representan datos compuestos sin identidad
de objeto propia. Asignarlos, pasarlos como argumento o retornarlos produce un
valor independiente; mutar los campos de una copia no modifica el struct del
que salió. Esto hace predecibles los resultados numéricos, coordenadas, estados
y pequeños objetos de dominio, y permite un ABI directo para el subconjunto
native.

La copia de un struct respeta la semántica de cada campo. Un struct anidado se
copia por valor, mientras que un campo que ya es reference-like conserva el
aliasing definido por ese tipo. Por tanto, «struct por valor» no significa
«deep copy recursiva de todo objeto alcanzable».

### Classes

Las classes son reference types porque modelan identidad y estado compartido.
La asignación copia la referencia; dos aliases observan las mutaciones del
mismo objeto. `const` restringe la mutación a través de un binding, pero no
congela un objeto al que puede existir otro alias mutable.

Esta semántica funciona en el frontend y el intérprete AST. Layout, dispatch y
ownership de classes todavía no cruzan el backend native. Mantener esa frontera
visible es preferible a compilar una class como si fuera accidentalmente un
struct.

### Strings

`string` es un valor inmutable, no nulo y con igualdad por contenido. Su
representación interna usa UTF-8 válido sin normalización Unicode implícita.
La longitud almacenada, no un byte nulo, determina el contenido; un terminador
adicional existe solo como conveniencia interna.

En native, un string es un handle de una palabra hacia un objeto Aether. El
vacío y los literales son inmortales. Los objetos dinámicos tienen ownership
interno mediante ARC no atómico: una copia lógica retiene, una transferencia
mueve y la destrucción libera. Parámetros son borrowed y retornos owned. Estas
reglas se modelan antes de SSA para que cleanup y optimizaciones no dependan de
convenciones implícitas del emisor LLVM.

El runtime de representación y lifecycle ya existe, pero no equivale a una API
de texto completa. Concatenación pública native, parsing, `split`, `trim`,
substring, archivos y argumentos de proceso siguen fuera del alcance actual.
El contrato detallado está en
[`aether/STRING_RUNTIME_DESIGN.md`](aether/STRING_RUNTIME_DESIGN.md).

### Arrays

`Array<T>` tiene longitud fija: después de construirlo se pueden reemplazar
elementos, pero no agregar ni retirar posiciones. Su storage es contiguo en el
subconjunto native y los accesos tienen bounds checks.

Para v1 se aprobó como reference type mutable. Asignar un Array copia la
referencia y produce aliasing; `copy()` y slicing crean otro contenedor y otro
buffer mediante copia lógica superficial de los elementos. La implementación
actual ya exhibe gran parte del aliasing, pero todavía no completa retain,
release y destrucción final del objeto contenedor. El contrato y la migración
pendiente están en
[`aether/COLLECTION_RUNTIME_DESIGN.md`](aether/COLLECTION_RUNTIME_DESIGN.md).

### Lists

`List<T>` representa una secuencia mutable de longitud dinámica. Su header
estable mantiene longitud, capacidad y puntero al buffer; crecer puede reemplazar
el buffer, pero no la identidad que comparten los aliases. Las operaciones de
crecimiento validan overflow y allocation, y no hay shrinking automático.

Para v1 se aprobó que assignment, parámetros y returns copien o transfieran la
referencia al mismo objeto. `copy()` es la operación explícita que crea header y
buffer independientes; no hace deep copy de referencias anidadas. También se
aprobó un handle de una palabra a objeto heap con strong RC no atómico como
representación principal. Falta migrar el lifecycle completo del contenedor y
unificar const, slicing, for-in e igualdad. Capacity de `List.copy()`,
`reserve`, `shrinkToFit`, views y un GC futuro siguen como detalles separados.

### Runtime

Aether tiene runtime propio porque varias garantías del lenguaje no pueden
delegarse sin más a libc o al host Python. El runtime implementa checks de
overflow y allocation, panics de seguridad, IO básico native, layouts y
operaciones esenciales de Array/List/Vector/Matrix, matemática escalar y el
lifecycle de strings.

La intención es mantenerlo pequeño. Una operación pertenece al runtime cuando
necesita conocer representación, ABI, allocation o seguridad de bajo nivel.
Los algoritmos que pueden escribirse con esas primitivas deben tender a la
stdlib. Usar `malloc`, `fwrite`, `libm` o intrinsics detrás del runtime no los
convierte en APIs públicas de Aether ni define una FFI estable.

### Backend

El intérprete AST conserva el papel de referencia práctica para la superficie
más amplia. La IR no lo reemplaza: ofrece una forma tipada más cercana a la
ejecución, con control de flujo, operaciones de memoria, efectos y lifecycle
explícitos. Su verifier impide que un programa mal formado avance solo porque
un backend particular lo tolera.

SSA se deriva de esa IR para que cada definición y cada merge de control sean
explícitos. Dominadores, fronteras de dominancia y phis permiten optimización
global, pero introducen invariantes que el verificador comprueba antes y
después de los pases. LLVM es el target actual para generación nativa; clang
realiza la compilación final. No es la fuente de la semántica de Aether.

Los optimizadores son conservadores con traps, calls, allocation, mutaciones y
lifecycle. Constant folding, DCE o SCCP solo son mejoras si preservan panics,
ownership y efectos observables. Una optimización más agresiva no tiene valor
si vuelve menos verificable el backend.

### Modules

Los módulos separan resolución semántica de generación de código. El frontend
resuelve imports completos o selectivos, aliases, visibilidad, ciclos e
identidad de símbolos; el backend native consume ese programa chequeado y no
reconstruye dependencias desde strings.

Funciones y tipos soportados ya cruzan módulos en native. Globals, constantes
con storage y statements ejecutables importados requieren todavía un modelo de
inicialización que garantice orden y ejecución única. Por eso el soporte se
declara parcial.

### Typed callables

El primer callable general es deliberadamente pequeño: una referencia a una
función top-level del usuario, sin captura y con firma estructural exacta
`R(P1, ...)`. Es suficiente para pasar una función a un solver numérico y tiene
una representación native directa como puntero a función.

Esta decisión cerró un caso real sin anticipar closures. Lambdas, captura,
métodos enlazados, builtins como valores y retorno de callables necesitarían
decidir representación y ownership de un entorno; no se consideran una
consecuencia automática del soporte actual.

### Enums

Los enums actuales son nominales y no tienen payload. Se eligieron para
representar estados finitos sin recurrir a enteros o booleanos ambiguos, como
los resultados de convergencia y de integración. La identidad incluye la
declaración y el módulo; el discriminante sigue el orden fuente. LLVM los
representa internamente como `i32`, detalle que no constituye una ABI pública.

Payloads, ADTs y pattern matching no se infieren de esta base. Añadirlos sería
una decisión de lenguaje distinta.

### Standard Library

El diseño distingue tres responsabilidades:

1. Un **builtin** es una operación que el compilador reconoce porque participa
   directamente en typing, control, layout o lowering.
2. El **runtime** contiene primitivas de representación, ABI, allocation,
   safety e interacción mínima con el sistema.
3. La **stdlib** ofrece módulos y algoritmos estables, preferentemente escritos
   en Aether sobre las dos capas anteriores.

Esta separación permite que Array y List sigan siendo tipos privilegiados sin
convertir `map`, `filter` o cada búsqueda en un opcode; también permite que
métodos numéricos evolucionen como biblioteca en lugar de gramática. El estado
actual aún mezcla prototipos AST en Python con primitivas native, por lo que la
frontera es un criterio de migración y no una afirmación de distribución
terminada. La propuesta completa está en
[`aether/BUILTINS_AND_STDLIB_DESIGN.md`](aether/BUILTINS_AND_STDLIB_DESIGN.md).

## Principios

- Coherencia antes que cantidad de features.
- Semántica explícita para copia, aliasing, mutabilidad, errores y ownership.
- Una feature no está completa porque exista su nodo AST, tipo IR u opcode.
- Backend verificable en cada frontera relevante.
- Optimizaciones correctas antes que agresivas.
- Rechazo temprano y localizado cuando un backend no cubre una feature válida.
- Runtime pequeño, centrado en representación y seguridad.
- Stdlib modular y escribible en Aether siempre que sea razonable.
- Ergonomía matemática integrada con el núcleo general, no superpuesta a él.
- Dogfooding con programas completos antes de ampliar la gramática.

## Open Design Questions

Las siguientes áreas permanecen abiertas. La lista registra trabajo de diseño,
no un roadmap ni una decisión implícita:

- ownership y liberación definitivos de headers y buffers de List, y su
  relación con otros contenedores y classes;
- lifecycle general de classes, interfaces, Vector y Matrix en native;
- concatenación, interpolación, parsing y algoritmos públicos de texto;
- runtime de contenedores a largo plazo, incluidos iteración durante mutación,
  `reserve`, `shrinkToFit` y contenedores anidados;
- modelo native de errores, panics, excepciones y eventual unwinding;
- archivos, entrada native, argumentos de proceso y APIs de sistema;
- forma y distribución de la stdlib, incluido `testing`, `collections`,
  `math`, `math.linalg` y `math.numerics`;
- inicialización y storage de globals/constantes a través de módulos;
- coherencia final de la CLI, perfiles de optimización y contratos de formato;
- política de paquetes, resolución de dependencias y posible package manager o
  registry;
- threading, atomics y seguridad del ARC si se introduce concurrencia;
- necesidad de GC —si alguna vez se implementa— y su convivencia con el
  ownership explícito ya modelado.

Mientras estas preguntas sigan abiertas, los documentos de diseño pueden
explorar alternativas, pero no deben presentarlas como semántica disponible.
