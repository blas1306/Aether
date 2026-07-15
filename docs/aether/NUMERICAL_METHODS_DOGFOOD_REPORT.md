# Informe de fricciones: métodos numéricos

Revisión: 15 de julio de 2026. Programa observado:
[`examples/numerical_methods/`](../../examples/numerical_methods/README.md).

El programa implementa bisección, Newton-Raphson, secante, trapecios y Simpson
en módulos Aether. La versión actual se ejecuta tanto en el intérprete AST como
en LLVM/native y ambos producen las mismas doce validaciones `true`. Usa
funciones importadas como valores y ya no depende de una interfaz
`ScalarFunction`.

## Cambios comprobados

### F01 — Callables top-level tipados: resuelto para el alcance mínimo

- **Estado:** implementado E2E y registrado como `FUNCTION_VALUES = PARTIAL`.
- **Sintaxis:** `ReturnType(ParameterType, ...)`; el alias del ejemplo es
  `double(double)`.
- **Semántica:** firma estructural exacta, referencia explícita a una función
  block top-level visible, sin entorno ni captura.
- **Recorrido:** typechecker, intérprete AST, `function_ref`/`call_indirect` en
  IR, SSA con dominancia y `phi`, y puntero/call indirecta LLVM.
- **Módulos:** funcionan imports completos/selectivos, aliases y mangling por
  identidad semántica, incluso con nombres homónimos.
- **ABI:** conserva el ABI directo existente; soporta `void`, primitivas y
  structs por valor ya compatibles. No asigna heap.
- **Límites:** sin closures, lambdas, captura, métodos enlazados, builtins o
  expression functions como valores, callables variádicos, genéricos no
  especializados ni retorno de callables.

La inspección previa confirmó que no existía una producción callable parcial
reutilizable: solo había funciones block/expresión y el hook ad hoc de
`Plots`. El cambio de gramática imprescindible fue el sufijo mínimo
`ReturnType(ParameterType, ...)`, coherente con la sintaxis de declaraciones y
sin introducir una segunda forma `function(...)`.

No existen overloads de funciones en Aether: los nombres duplicados ya son un
error. Por eso esta fase no añade resolución contextual de overload sets ni un
diagnóstico de ambigüedad que hoy sería inalcanzable.

### F02 — Workaround mediante interfaces: eliminado

`Roots.ae` e `Integration.ae` reciben `ScalarCallable` y llaman `target(x)`
directamente. Las interfaces continúan siendo una capacidad AST válida para
otros diseños, pero ya no bloquean este programa ni se usan como
representación oculta del callable native.

### F03 — Imports declarativos y mangling: comprobados

El entry file pasa referencias importadas desde `Problems.ae` hacia funciones
de `Roots.ae` e `Integration.ae`. El backend consume la resolución semántica
del `CheckedProgram` y emite el símbolo mangled correspondiente; no vuelve a
resolver imports por texto. Globals e inicialización ejecutable de módulos
siguen siendo deuda independiente y el ejemplo no los requiere.

### F04 — Matemática escalar: comprobada

`abs` y las operaciones `int`/`double` atraviesan AST, IR, SSA y native. Los
builtins no se pueden pasar directamente como callables en esta versión; una
función top-level wrapper es la política explícita cuando haga falta.

### F05 — Optimizadores y una regresión encontrada

Las calls indirectas tienen efectos conservadores: DCE no puede eliminarlas
solo porque su resultado no se use. Renaming, simplificación, SCCP y reemplazo
de phis conocen el operando callable. El dogfood además descubrió que
`DeadPhiPass` no contaba usos desde instrucciones de structs/method-results;
se corrigió para no eliminar un `phi` de loop todavía usado al construir
`RootResult`.

## Fricciones que permanecen

### Manejo de errores native

`throw`/`try-catch` sigue siendo solo AST. Para conservar una única variante
de calidad comparable entre backends, los root solvers usan
`RootResult` con un `RootStatus` explícito y Simpson devuelve `0.0` ante un
conteo inválido. Este
último valor es un sentinel de dogfood, no el contrato recomendado para una
futura `math.numerics`; un `Result` o excepciones compiladas debe resolverlo.

### Resultado de convergencia: resuelto con enum nominal

`RootResult.status` usa `RootStatus` con `Converged`, `MaxIterations`,
`InvalidInterval` y `ZeroDerivative`. Los tres algoritmos ya no esconden causas
esperables tras un booleano. El enum atraviesa imports selectivos, campo de
struct, returns, comparaciones, IR, SSA y LLVM/native con output idéntico al
intérprete AST.

### Testing y distribución

No existe todavía un módulo `testing` ni una ubicación de stdlib instalable.
El ejemplo imprime booleanos y pytest compara exactamente AST/native. Debe
seguir en `examples/` hasta que existan búsqueda de stdlib y una API de tests.

### Ergonomía

Los argumentos siguen siendo posicionales y no hay valores por defecto. Un
options struct es preferible a ampliar la gramática solo por este ejemplo.

## Resultado de la prueba

La suite automatizada cubre convergencia y precisión de los tres métodos de
raíces, bracket inválido, derivada y denominador casi nulos, precisión de
trapecios/Simpson y subdivisiones inválidas. El mismo source multi-módulo pasa
AST y clang real con output idéntico, incluyendo el enum de estado. El bloqueo
crítico original —pasar una
función matemática reutilizable sin interfaz AST-only— queda cerrado dentro
del alcance deliberadamente `PARTIAL` de callables top-level sin captura.
