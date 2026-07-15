# Perfiles de capacidades de backend

Los perfiles de capacidades son la fuente programática que usa Aether para
distinguir una feature válida del lenguaje de una feature ejecutable por un
backend concreto. El catálogo, los estados y los perfiles versionados viven en
`src/aether/capabilities.py`.

El perfil **no** redefine la gramática ni el sistema de tipos, no negocia
features dinámicamente y no sustituye los verificadores de IR o SSA. El parser
y el typechecker siguen decidiendo si un programa es Aether válido. Después del
typechecking, un detector recorre el AST chequeado (nunca el texto fuente) y
consulta los tipos de expresión conservados por cada `TypeChecker`. Produce
requisitos deduplicados con ubicación. La validación del perfil ocurre antes
del lowering específico de backend.

## Modelo

Cada `BackendCapabilityProfile` tiene:

- una identidad tipada (`ast` o `native`);
- una versión de schema/perfil;
- exactamente una entrada para cada miembro del enum `Capability`;
- un estado `COMPLETE`, `PARTIAL` o `UNSUPPORTED`;
- descripción y código diagnóstico estable en el catálogo canónico.

`COMPLETE` significa que el alcance completo de esa capacidad, tal como lo
define el catálogo, tiene evidencia end-to-end para ese backend. `PARTIAL`
significa que existe un subconjunto funcional y que los casos identificables
fuera de él deben producir un diagnóstico específico. `UNSUPPORTED` significa
que un uso válido del lenguaje no entra todavía en ese backend.

El catálogo agrupa features observables por el usuario. No replica las 81 filas
de `BACKEND_FEATURE_PARITY.md`: opcodes, helpers de runtime, verificadores y
detalles de ownership permanecen en la auditoría porque son evidencia o
arquitectura, no capacidades solicitadas directamente por un programa.

## Perfiles actuales

La versión actual del perfil es `9`. La versión `2` promovió `modules` e
`imports` de `UNSUPPORTED` a `PARTIAL`; la versión `3` promovió `scalar-math`
de `UNSUPPORTED` a `PARTIAL` en LLVM/native; la versión `4` incorpora el
subconjunto de callables top-level tipados y sin captura en ambos backends. La
versión `5` promueve `enums` a `COMPLETE` en LLVM/native para la semántica
existente de enums nominales sin payload. La versión `6` agrega
`aggregate-collection-elements`: es `COMPLETE` en AST y `PARTIAL` en native.
El subconjunto native cubre structs nominales acíclicos con lifecycle
representable: primitivas, enums, structs anidados y strings/otros descriptores;
las combinaciones sin layout/copia definida se rechazan con
ubicación y motivo antes del lowering LLVM. La versión `7` separó transporte,
igualdad, objeto dinámico y lifecycle de string tras activar ARC. La versión
`8` agrega detección tipada de gaps de migración de colecciones sin promover ni
degradar ninguna capability.
La versión `9` agrega `collection-object-lifecycle`: es `COMPLETE` en native,
con evidencia de RC fuerte, aliases, parámetros/returns, fields, nesting y
destrucción final, y `PARTIAL` en AST mientras su instrumentación lógica no
pretende sustituir el cleanup abortivo del proceso host.

El perfil AST representa el intérprete de referencia. Incluye módulos,
imports, classes, interfaces, enums, input, errores y matemática escalar. Las
funciones como valores son `PARTIAL`: el tipo estructural `R(P1, P2, ...)`
cubre referencias a funciones top-level de usuario sin captura, variables,
parámetros, `phi` y llamadas indirectas con compatibilidad exacta. Las
funciones de expresión y el hook legado de `Plots` siguen siendo subconjuntos
solo AST y no se confunden con el callable tipado.

El perfil LLVM/native representa el recorrido completo
AST→IR→SSA→LLVM→clang. Módulos e imports están en `PARTIAL`: compilan funciones,
funciones `void`, structs, constructores, métodos y firmas cross-module mediante
imports completos/selectivos y aliases, con transitividad, privacidad y ciclos
resueltos por el frontend. Globals/constantes y statements ejecutables en un
módulo importado se rechazan temprano porque el IR aún no modela storage ni
inicialización de módulo. El núcleo matemático real consolidado (`int`/`double`)
y `Math.pi` compila; los builtins complejos experimentales se detectan y se
rechazan, por lo que `scalar-math` es `PARTIAL`. `function-values` también es
`PARTIAL`: referencias a funciones top-level definidas por el usuario se
bajan a punteros LLVM tipados y las llamadas indirectas conservan efectos
desconocidos. Funciona con imports, aliases, parámetros primitivos, `void` y
structs por valor compatibles con el ABI actual. No incluye closures, lambdas,
captura, métodos enlazados, builtins como valores, funciones de expresión,
retorno de callables ni funciones genéricas no especializadas. Los enums sin
payload son `COMPLETE`: conservan identidad módulo/declaración en frontend,
IR y SSA, usan discriminantes deterministas por orden fuente, cruzan firmas,
structs, colecciones compatibles, imports/aliases y se imprimen como
`EnumName.VariantName`; LLVM los representa como `i32`. Classes, interfaces,
input y errores siguen no soportados. Strings, primitivos,
arithmetic, structs y colecciones quedan parciales porque sus subconjuntos
compilables son reales pero no cubren toda la superficie AST.
Archivos y argumentos del proceso están no soportados en ambos perfiles porque
todavía no son APIs válidas del lenguaje.

Para `strings`, el subset native distingue la operación semántica concreta:

- transporte de literales, variables, parámetros, returns, fields y elementos
  bajo handles `AetherStringObject` ARC: aceptado;
- igualdad/desigualdad por contenido: aceptada;
- concatenación e interpolación: rechazadas temprano con el nodo operador
  tipado y su ubicación;
- productores dinámicos, parsing, split/trim, archivos y argumentos: no se
  infieren por la mera presencia de texto y siguen fuera de su capacidad
  propia o sin API de lenguaje.

Un literal aislado no solicita soporte completo. `a + b` y `a == b` se detectan
cuando ambos operandos son string, aunque no haya literales y aunque la
operación viva en un módulo importado.

## Actualización de perfil 7: runtime string

El perfil 7 separa `string-transport`, `string-equality`,
`dynamic-string-object`, `string-lifecycle`, `string-concatenation`,
`string-parsing` y `string-split-trim`. Native marca completos transporte,
igualdad y objeto dinámico interno; lifecycle permanece parcial mientras no
exista una API pública amplia de productores. Concatenación, parsing y
split/trim están explícitamente unsupported.

## Actualización de perfil 8: baseline de colecciones

El detector conserva la forma `MethodCall` tipada usada al desazucarar calls
dotted y distingue, sin regex ni inspección del source:

- `Array.copy()`, todavía sin camino IR/native end-to-end;
- slicing cuyo receiver es List, con semántica AST inclusiva legado;
- `==`/`!=` con operandos Array o List, estructural sólo en AST;
- `contains`/`indexOf` de `List<Struct>`, que requiere un `Eq(T)` estructural
  todavía ausente de IR/native.

Todos producen un diagnóstico ubicado antes del lowering. Assignment, aliases,
parámetros, returns, List.copy, Array slicing y el subset seguro existente no
se desactivan. `array`, `list` y `array-slicing` son capabilities deliberadamente
amplias; los gaps se expresan como detalles semánticos que requieren soporte
completo. Sólo deberían dividirse si esos subcontratos se vuelven capacidades
de producto independientes. La evidencia completa está en
[`COLLECTION_MIGRATION_BASELINE.md`](COLLECTION_MIGRATION_BASELINE.md).

## Actualización de perfil 9: lifecycle de objetos colección

`Array<T>` y `List<T>` se clasifican como handles no trivialmente copiables y
trivialmente relocatables. Native usa un contador fuerte no atómico en el
objeto privado, retain-before-release para assignment y destrucción recursiva
del rango vivo, buffer y objeto al último owner. Los parámetros conservan la
convención borrowed y los returns entregan ownership. El perfil AST usa
`CollectionObject` con identidad, contador lógico, estado alive/freed y
contadores de prueba; permanece parcial porque panic continúa sin unwind.

La CLI no añade por ahora un comando `capabilities`: ejecución AST valida el
perfil AST, y `--emit-llvm`, ejecución LLVM, `build` y los perfiles LLVM/native
de `bench` validan el perfil native. Los modos de inspección IR/SSA conservan
sus rechazos internos porque son backends de desarrollo con límites propios,
no perfiles de ejecución publicados.

## Política de actualización

Para añadir o cambiar una capacidad:

1. actualizar el enum y su única definición canónica;
2. actualizar ambos perfiles de forma explícita;
3. ampliar el detector solo con información del AST chequeado o del estado
   semántico existente;
4. conservar una validación interna si protege invariantes de IR/SSA/LLVM;
5. añadir tests de modelo, detección, ubicación, deduplicación, CLI y backend;
6. reconciliar el cambio con `BACKEND_FEATURE_PARITY.md` y el alcance v1.

> Una capacidad no puede marcarse `COMPLETE` en un perfil sin tests
> end-to-end registrados para ese backend.

`E2E_TESTED_CAPABILITIES` y su test de consistencia hacen ejecutable esta
política. El registro no reemplaza la revisión de la auditoría: antes de marcar
`COMPLETE` deben existir casos positivos, negativos y de límites, además de
paridad observable cuando ambos backends implementen la feature.
