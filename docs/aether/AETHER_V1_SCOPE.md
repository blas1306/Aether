# Alcance formal de Aether v1

Estado del documento: propuesta normativa de alcance, revisada contra el
repositorio el 15 de julio de 2026. Describe qué debe significar **v1**; no
declara que el estado actual ya sea v1.

## Identidad

Aether es:

> Un lenguaje de programación estático y compilado de propósito general, con
> una ergonomía especialmente orientada a matemática, métodos numéricos y
> simulaciones.

La idea central es:

> 100 % núcleo general y 130 % ergonomía matemática.

El núcleo general no es un apéndice: tipos, funciones, control de flujo,
módulos, datos definidos por el usuario, errores, IO y herramientas deben ser
coherentes aunque el programa no sea científico. El énfasis matemático agrega
literales, tipos y APIs cómodas; no reemplaza esos fundamentos.

Aether no intenta ser “el lenguaje definitivo”, reemplazar a todos los demás
lenguajes ni superar a Python, Julia, C++, Rust, Java o C# en cada eje. Busca
que una exploración matemática o numérica pueda evolucionar hasta un programa
nativo completo sin cambiar de lenguaje y sin descubrir que las capacidades
generales eran pobres o improvisadas.

## Estados usados

- **Estable para el alcance actual**: existe un camino funcional probado en
  todas las etapas que corresponden a la feature.
- **Parcial**: existe un subconjunto útil, pero falta una etapa, semántica o
  cobertura requerida para v1.
- **Solo AST**: parser, typechecker e intérprete AST lo ejecutan, pero no llega
  al backend compilado.
- **No implementado**: no hay un camino funcional de lenguaje.
- **Planeado para v1**: es requisito de salida, no una afirmación de soporte
  actual.

La fuente de detalle por etapa es
[`BACKEND_FEATURE_PARITY.md`](BACKEND_FEATURE_PARITY.md).

## Objetivos verificables de Aether v1

| Objetivo v1 | Estado actual | Criterio de salida de v1 |
| --- | --- | --- |
| Tipado estático | Parcial | Todo programa aceptado por el camino compilado debe estar chequeado; no debe depender de tipos dinámicos ocultos. Las funciones de expresión con parámetros desconocidos deben quedar delimitadas o tipadas formalmente. |
| Compilación nativa | Parcial | El CLI debe compilar y ejecutar el conjunto v1 mediante LLVM/clang con diagnósticos claros y sin fallback silencioso a AST. |
| Funciones tipadas, `void`, retorno y recursión | Estable para tipos backend | Llamadas, argumentos, retornos y recursión deben mantener paridad AST/native. |
| Funciones como parámetros o valores | Parcial: top-level tipadas sin captura | Mantener `R(P1, ...)` con compatibilidad exacta y paridad AST/native; closures, lambdas, captura, métodos enlazados, builtins como valores y retorno de callables quedan fuera hasta un diseño posterior. |
| Control de flujo (`if`, `while`, `for`, `for-in`, `break`, `continue`) | Estable en el subconjunto compilable | Mantener short-circuit, alcance y saltos idénticos en AST, IR y native. |
| Módulos e imports | Parcial native | Funciones y structs soportados compilan con imports completos/selectivos, aliases, transitividad, privacidad y ciclos. Falta storage/inicialización native para globals, constantes y statements top-level importados. |
| Structs por valor | Estable en el núcleo | Mantener construcción, métodos, copia, parámetros, retorno, igualdad e impresión para campos soportados; documentar el ABI. |
| Classes por referencia | Solo AST | Bajar layout, construcción, aliasing, visibilidad, métodos y ownership al backend sin convertirlas accidentalmente en valores. |
| Interfaces | Solo AST | Bajar representación y dispatch para structs y classes, preservando semántica de valor/referencia. |
| Enums sin payload | Estable AST/native | Mantener identidad nominal, discriminantes deterministas, igualdad, impresión y uso en structs/funciones/colecciones compatibles. Payloads, ADTs y pattern matching nuevo no son requisito v1. |
| Strings | Parcial | Literales, variables, parámetros, retorno, impresión, concatenación, igualdad e interpolación deben tener contrato de encoding y ownership coherente en native. |
| `Array<T>` | Parcial para tipos de elemento backend | Mantener literal, get/set, length, slicing, sort y bounds/overflow checks; soportar o rechazar temprano elementos struct y definir qué métodos derivados quedan en stdlib. |
| `List<T>` | Parcial para tipos de elemento backend | Mantener get/set, growth, mutaciones, copy, búsqueda, reverse y sort; completar layout/copia de structs y cerrar ownership/liberación sin introducir GC híbrido. |
| `Vector<T>` y `Matrix<T>` | Parcial | Mantener literales, storage contiguo, índices 1-based, shape, operaciones básicas y checks; llevar el subconjunto matemático v1 seleccionado a native. |
| Manejo básico de errores | Parcial | Panics de seguridad y `throw`/`try`/`catch` deben tener una semántica delimitada y coherente. Excepciones avanzadas no son requisito. |
| Salida | Parcial | `print`/`println` deben cubrir valores v1 con formato documentado y consistente. |
| Entrada | Solo AST | `input` tipado debe funcionar en ejecución nativa o quedar reemplazado por una API v1 equivalente explícita. |
| Archivos | No implementado | Proveer una API mínima y testeada para abrir/cerrar, leer y escribir texto/binario, con errores definidos. |
| Argumentos del proceso | No implementado | Exponer argumentos y código de salida mediante una API `system` o equivalente; `main` seguirá sin parámetros mientras no cambie la especificación. |
| Matemática escalar | Parcial, mayormente AST | Seleccionar y llevar a native al menos `sin`, `cos`, `tan`, `sqrt`, `exp`, `log`/`ln`, `abs`, `floor`, `ceil` y constantes acordadas. |
| Módulos matemáticos | Parcial, AST | Formalizar `math` y un núcleo de `math.linalg`; `math.numerics` puede comenzar como código Aether. No todo el catálogo actual es requisito v1. |
| Tests del lenguaje | Parcial pero amplio | Cada feature v1 debe tener pruebas positivas, negativas, safety y paridad; los skips deben depender solo de herramientas opcionales conocidas. |
| CLI coherente | Parcial | `run`, build, selección de backend, inspección y niveles de optimización deben describir exactamente qué hacen. El backend por defecto no debe rechazar silenciosamente gran parte de la superficie promocionada. |
| Paridad semántica AST/native | Parcial y bloqueante | Un programa dentro del perfil v1 debe producir los mismos valores, efectos, panics y errores observables en AST y native. |
| Interoperabilidad futura por ABI C | No implementado | v1 debe documentar una frontera FFI/ABI C viable y no cerrar el diseño; no es necesario prometer estabilidad binaria completa ni wrappers extensos en v1. |
| Programas medianos | Parcial, solo AST para la superficie amplia | Mantener al menos varios programas modulares no triviales con validaciones automatizadas; hoy existen `examples/numerical_methods/` y `examples/expense_tracker/`. Al menos uno debe compilar nativamente usando el perfil v1. |

El estado compilable publicado se modela en los perfiles versionados descritos
en [`BACKEND_CAPABILITY_PROFILES.md`](BACKEND_CAPABILITY_PROFILES.md). Estos
perfiles no reducen la validez general de Aether: hacen que `run`, `build` y la
emisión LLVM rechacen temprano, con ubicación, una feature válida que aún no
pertenece al subconjunto del backend elegido.

El contrato propuesto de semántica, representación, ABI y ownership de strings
está en [`STRING_RUNTIME_DESIGN.md`](STRING_RUNTIME_DESIGN.md). Es una RFC en
revisión: no modifica todavía este alcance ni el estado de capacidades.

Una feature puede excluir una etapa solo por una razón explícita. Por ejemplo,
el lexer no “implementa” bounds checks, y una declaración de tipo no necesita
ejecución propia; esa no aplicabilidad debe documentarse, no contarse como una
celda verde automática.

## No objetivos de Aether v1

Quedan fuera de v1:

- `Any` y un escape dinámico universal;
- un sistema híbrido complejo de GC y liberación manual;
- LINQ, ORM, framework web o GUI del lenguaje;
- GPU y un JIT sofisticado;
- metaprogramación avanzada y macros complejas;
- async completo;
- un package registry público;
- una implementación propia de machine learning;
- reemplazos caseros de NumPy, SciPy, BLAS o LAPACK;
- una implementación propia de BLAS/LAPACK;
- genéricos de usuario avanzados, overloads y enum payloads, salvo que un
  bloqueo del núcleo demuestre que un subconjunto mínimo es imprescindible.

Plotting, visualización, data tooling, wrappers científicos e integraciones
pueden existir como paquetes oficiales, pero no definen la estabilidad del
núcleo. Estas ideas pueden evaluarse después de v1 y no deben retrasar su
salida.

## Perfil mínimo de programas v1

Para afirmar que Aether v1 permite programas medianos, el repositorio debe
mantener ejemplos automatizados que combinen, no solo aíslen:

1. varios archivos y visibilidad pública/privada;
2. structs y al menos una abstracción por referencia o dispatch;
3. colecciones mutables con manejo de errores;
4. IO de consola y archivos;
5. lógica de dominio con funciones y control de flujo no triviales;
6. build nativo reproducible;
7. resultados equivalentes en AST y native dentro del perfil declarado.

El ejemplo de métodos numéricos satisface 1, 5, 6 y 7 para su perfil. El expense
tracker satisface 1, 3 y 5 en AST, y revela que archivos, argumentos, strings
dinámicos y colecciones de structs aún impiden cubrir 4, 6 y 7 para un programa
generalista completo.

## Criterios de estabilidad

Una característica se considera realmente implementada solo cuando cumple los
criterios aplicables de esta lista:

1. **Lexer/parser**: reconoce únicamente las formas documentadas, conserva
   ubicación y produce errores claros para formas inválidas.
2. **AST**: representa toda la información semántica necesaria sin depender de
   texto fuente reconstruido.
3. **Typechecker**: valida tipos, mutabilidad, alcance, visibilidad, control de
   flujo y restricciones de uso; no delega errores previsibles al host.
4. **Intérprete AST**: ejecuta la semántica de referencia cuando corresponda y
   reporta errores Aether, no excepciones accidentales de Python.
5. **Modelo IR**: posee tipos e instrucciones con efectos, traps, memoria y
   ownership explícitos suficientes para la feature.
6. **Lowering IR**: cubre todas las formas aceptadas dentro del perfil y falla
   con un diagnóstico público preciso fuera de él.
7. **Verificador IR**: rechaza tipos, CFG, operands y metadatos inválidos.
8. **Intérprete IR**: cuando corresponda, ejecuta el mismo contrato observable
   y sirve como oráculo intermedio.
9. **SSA**: la construcción cubre el CFG producido y conserva efectos,
   definición-uso, tipos y phis.
10. **Verificador SSA**: comprueba dominancia de usos, phis contra
    predecesores, tipos, terminadores y estructura completa.
11. **Optimizaciones**: ninguna pasada elimina o mueve panics, allocations,
    IO, mutaciones o calls observables; existen regresiones para el caso.
12. **LLVM/native**: emite IR válido, enlaza, ejecuta y mantiene layout,
    overflow, bounds, formato y códigos de salida definidos.
13. **Runtime**: especifica representación, seguridad, ownership, errores y
    dependencias externas; no filtra detalles accidentales del host.
14. **Tests**: incluye casos válidos, inválidos, límites y paridad. Un test de
    existencia de nodo no basta como prueba end-to-end.
15. **Documentación**: sintaxis, semántica, límites y backend soportado aparecen
    en la especificación, guía y matrices sin contradicciones conocidas.
16. **Coherencia entre backends**: los resultados, efectos y fallos observables
    coinciden, o la diferencia queda fuera del perfil estable y se rechaza de
    forma explícita.

Una feature sin tests es “implementada pero sin tests”; una feature sin
contrato publicado es “implementada pero sin documentación”. Ninguna de esas
dos categorías puede ser estable en v1.

## Regla de congelamiento de sintaxis

La sintaxis actual queda temporalmente congelada durante la consolidación de
v1. Solo debe cambiar si aparece al menos una de estas condiciones:

- una ambigüedad grave;
- una inconsistencia semántica;
- una imposibilidad de evolución futura;
- un problema importante de ergonomía demostrado por programas reales;
- una incompatibilidad seria entre frontend y backend.

No se cambia sintaxis por preferencia estética. Toda excepción al congelamiento
debe incluir un programa mínimo, impacto de compatibilidad, alternativa sin
cambio sintáctico, actualización de spec y tests de migración o rechazo.
