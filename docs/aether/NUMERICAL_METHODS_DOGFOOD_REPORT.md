# Informe de fricciones: métodos numéricos

Revisión: 15 de julio de 2026. Programa observado:
[`examples/numerical_methods/`](../../examples/numerical_methods/README.md).

El programa implementa bisección, Newton-Raphson, secante, trapecios y Simpson
en cinco módulos Aether. Se ejecutó correctamente con el intérprete AST y todas
sus validaciones imprimieron `true`. La resolución multi-módulo native ya
atraviesa los imports; el diagnóstico temprano actual enumera los bloqueos
reales siguientes: interfaces, manejo de errores y comparación de strings.
La matemática escalar consolidada ya no aparece como bloqueo.

Escala de severidad: **crítica** impide el objetivo central; **alta** bloquea un
programa v1 razonable; **media** obliga a boilerplate o reduce calidad; **baja**
es local o cosmética.

## F01 — No existen funciones de primera clase

- **Clasificación:** Feature ausente.
- **Descripción:** una función top-level no tiene un tipo utilizable en
  variables, parámetros o retornos. Las expression functions tampoco son
  valores. `Plots` obtiene referencias mediante un caso especial del
  intérprete, no mediante semántica general.
- **Ejemplo mínimo:** `RootResult solve(double function(double) f, ...);` no es
  sintaxis Aether aceptada.
- **Backend afectado:** frontend, AST, IR, SSA y native.
- **Severidad:** crítica para `math.numerics` reutilizable.
- **Solución recomendada:** diseñar un tipo función estático sin exigir
  closures capturantes en la primera fase; soportar referencias a funciones
  top-level y llamadas indirectas, y agregar closures solo en una fase
  posterior si se deciden.
- **¿Bloquea Aether v1?:** sí, si “funciones como parámetros” permanece en el
  perfil v1; en caso contrario debe declararse explícitamente diferido.
- **¿Requiere cambio de sintaxis?:** probablemente sí, pero la decisión debe
  justificarse como capacidad ausente, no como estética.
- **¿Puede resolverse en stdlib?:** no.
- **¿Requiere runtime/backend?:** sí; representación callable, typechecker,
  IR, llamada indirecta y ABI LLVM.

## F02 — La alternativa con interfaces es solo AST

- **Clasificación:** Feature parcial.
- **Descripción:** `ScalarFunction.evaluate(x)` produce una API reusable con la
  sintaxis actual, pero interfaces e interface dispatch no bajan a IR.
- **Ejemplo mínimo:**
  `double apply(ScalarFunction f, double x) { return f.evaluate(x); }`.
- **Backend afectado:** IR lowering, SSA, LLVM/native.
- **Severidad:** alta.
- **Solución recomendada:** bajar interfaces después de fijar layout/dispatch
  y preservar la diferencia entre structs por valor y classes por referencia.
- **¿Bloquea Aether v1?:** sí para el perfil generalista anunciado.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** no.
- **¿Requiere runtime/backend?:** sí, principalmente ABI y dispatch.

## F03 — Imports native implementados para declaraciones, inicialización pendiente

- **Clasificación:** Feature parcial, bloqueo principal resuelto.
- **Descripción:** funciones y structs cross-module, aliases, visibilidad,
  transitividad y ciclos llegan a LLVM/native mediante IR combinado. Globals,
  constantes y statements top-level importados todavía requieren storage e
  inicialización explícitos.
- **Ejemplo mínimo:** `from Roots import bisection;`.
- **Backend afectado:** IR, SSA, LLVM/native y linker/build.
- **Severidad:** crítica para programas medianos.
- **Solución recomendada:** extender IR con globals y fijar inicialización/orden
  una sola vez sobre el `CheckedProgram` ya existente.
- **¿Bloquea Aether v1?:** sí.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** no.
- **¿Requiere runtime/backend?:** compiler/linker; runtime para inicializadores
  y globals según el diseño final.

## F04 — El backend predeterminado no ejecuta la superficie amplia

- **Clasificación:** Problema de ergonomía.
- **Descripción:** `aether file.ae` selecciona LLVM, pero interfaces,
  excepciones y muchos builtins publicados son solo AST. Un programa válido
  necesita conocer y pedir `--backend=ast`.
- **Ejemplo mínimo:** `aether examples/numerical_methods/main.ae` informa ahora
  `interfaces`, `error-handling` y strings parciales, no imports ni matemática
  escalar.
- **Backend afectado:** CLI y native.
- **Severidad:** alta.
- **Solución recomendada:** cerrar el perfil nativo v1 o hacer que la ayuda y
  diagnósticos distingan claramente perfiles; no hacer fallback silencioso.
- **¿Bloquea Aether v1?:** sí para una CLI coherente.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** no.
- **¿Requiere runtime/backend?:** CLI y compilador.

## F05 — Matemática escalar bajada (resuelto para el núcleo real)

- **Clasificación:** Resuelto; capacidad native parcial por el subconjunto
  complejo experimental.
- **Descripción:** `abs`, `sqrt`, `sin`, `cos`, `tan`, `exp`, `ln`, `log`,
  `Math.floor`, `Math.ceil`, `Math.mod`, `Math.factorial` y `Math.pi` atraviesan
  IR, SSA y LLVM/native para `int`/`double`. Los algoritmos del ejemplo ya no
  son rechazados por sus usos de `abs`.
- **Ejemplo mínimo:**
  `int main() { println(abs(-1.0)); return 0; }`.
- **Backend afectado:** soporte implementado en IR, SSA y LLVM/native.
- **Severidad:** cerrada para el núcleo real; `complex` continúa fuera del
  perfil native.
- **Solución aplicada:** call común con identidad builtin, intrinsics LLVM,
  `libm` y helpers checked de runtime.
- **¿Bloquea Aether v1?:** no para el núcleo escalar seleccionado.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** parcialmente; las composiciones sí, las
  primitivas eficientes necesitan backend/runtime.
- **¿Requiere runtime/backend?:** implementado; queda pendiente un ABI complejo.

## F06 — `try`/`catch` y `throw` son solo AST

- **Clasificación:** Feature parcial.
- **Descripción:** Simpson puede rechazar un número impar de intervalos con una
  excepción clara, pero esa API deja de ser compilable.
- **Ejemplo mínimo:**
  `if intervals % 2 != 0 { throw "even interval count required"; }`.
- **Backend afectado:** IR, SSA y LLVM/native.
- **Severidad:** alta.
- **Solución recomendada:** decidir para v1 entre excepciones compiladas
  mínimas o resultados explícitos; si se conservan excepciones, definir unwind
  o un mecanismo runtime controlado antes de emitir código.
- **¿Bloquea Aether v1?:** sí para la feature de errores tal como está
  especificada; los panics de safety por sí solos no la reemplazan.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** un tipo `Result` podría cubrir APIs, pero
  requiere genéricos/ergonomía y no implementa la sintaxis existente.
- **¿Requiere runtime/backend?:** sí.

## F07 — Falta una librería de testing Aether

- **Clasificación:** Problema de librería estándar.
- **Descripción:** no existe `assert` ni runner de tests del lenguaje. El
  ejemplo imprime booleanos y un test Python compara el output.
- **Ejemplo mínimo:** la intención sería `assert(approx(root.value, sqrt(2)))`,
  pero no existe una API oficial.
- **Backend afectado:** todos como superficie de usuario; la validación actual
  vive fuera de Aether.
- **Severidad:** media.
- **Solución recomendada:** módulo `testing` pequeño con assert booleano,
  igualdad, aproximación numérica, mensajes y exit code; runner CLI después.
- **¿Bloquea Aether v1?:** sí para afirmar tests coherentes del ecosistema, no
  para ejecutar los algoritmos.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** mayormente sí.
- **¿Requiere runtime/backend?:** solo panic/exit y, opcionalmente, ubicación.

## F08 — No hay argumentos nombrados ni valores por defecto en funciones

- **Clasificación:** Problema de ergonomía.
- **Descripción:** llamadas numéricas con varios `double` e `int` dependen del
  orden posicional y repiten tolerancia/máximo de iteraciones.
- **Ejemplo mínimo:**
  `newton(target, derivative, 1.0, 1e-10, 100)` no puede escribirse con
  `tolerance:` ni omitir defaults.
- **Backend afectado:** parser/typechecker; por consecuencia todos.
- **Severidad:** media.
- **Solución recomendada:** no cambiar v1 por este dogfood aislado. Primero
  evaluar structs de opciones en programas reales; después diseñar named/default
  arguments como bloque separado.
- **¿Bloquea Aether v1?:** no.
- **¿Requiere cambio de sintaxis?:** sí si se implementa directamente.
- **¿Puede resolverse en stdlib?:** parcialmente con un options struct.
- **¿Requiere runtime/backend?:** lowering de defaults/calls; no runtime
  especial.

## F09 — `RootResult` no puede expresar la razón del fallo cómodamente

- **Clasificación:** Problema de ergonomía.
- **Descripción:** `converged=false` agrupa bracket inválido, derivada casi
  nula, denominador casi nulo y agotamiento de iteraciones. Un enum resolvería
  la API en AST, pero enums aún son AST-only.
- **Ejemplo mínimo:** `RootResult(value, iterations, false)`.
- **Backend afectado:** API en todos; enum status solo AST.
- **Severidad:** media.
- **Solución recomendada:** agregar un `RootStatus` enum cuando enums lleguen a
  native; no añadir códigos mágicos ni strings como parche.
- **¿Bloquea Aether v1?:** no para el algoritmo; enums compilados sí son un
  objetivo v1 independiente.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** sí una vez disponible enum en el backend.
- **¿Requiere runtime/backend?:** bajar enums; no runtime complejo.

## F10 — Diagnóstico de identificador reservado poco localizado

- **Clasificación:** Problema de mensajes de error.
- **Descripción:** usar `function` como nombre de variable en el primer borrador
  produjo “Expected ';' after expression” en vez de indicar que el token es una
  palabra reservada/no es un identificador válido.
- **Ejemplo mínimo:** `QuadraticMinusTwo function = QuadraticMinusTwo();`.
- **Backend afectado:** parser y herramientas frontend.
- **Severidad:** baja.
- **Solución recomendada:** cuando una declaración tipada encuentra un keyword
  donde espera nombre, emitir un error específico con ubicación. No fue
  necesario cambiar la gramática; el ejemplo usa `target`.
- **¿Bloquea Aether v1?:** no.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** no.
- **¿Requiere runtime/backend?:** no; solo parser/diagnóstico.

## F11 — El hint de “supported IR subset” está desactualizado

- **Clasificación:** Falta de documentación.
- **Descripción:** varios errores de lowering/builtins enumeran solo funciones,
  locales, literales escalares, aritmética, comparaciones, control y calls. No
  menciona structs, Array/List, for, short-circuit ni Vector/Matrix ya
  soportados.
- **Ejemplo mínimo:** compilar el ejemplo sin `--backend=ast`.
- **Backend afectado:** diagnósticos IR/CLI.
- **Severidad:** media.
- **Solución recomendada:** generar el hint desde un perfil versionado o
  mantenerlo junto a la matriz de capacidades; evitar una lista manual extensa.
- **¿Bloquea Aether v1?:** no por sí solo, pero perjudica la CLI coherente.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** no.
- **¿Requiere runtime/backend?:** diagnóstico del compilador.

## F12 — No hay un módulo `math.numerics` escribible/instalable todavía

- **Clasificación:** Limitación deliberada.
- **Descripción:** los algoritmos deben vivir como ejemplo y sus imports se
  resuelven desde el directorio del entry file. No existe layout/instalación de
  stdlib Aether para promoverlos sin copiar archivos.
- **Ejemplo mínimo:** `from Roots import newton;` es local, no
  `from math.numerics import newton;`.
- **Backend afectado:** módulos, distribución, CLI y native.
- **Severidad:** media.
- **Solución recomendada:** definir primero búsqueda de stdlib y callables;
  promover después el código dogfood con tests de compatibilidad.
- **¿Bloquea Aether v1?:** no para consolidación; sí para publicar esa API.
- **¿Requiere cambio de sintaxis?:** no.
- **¿Puede resolverse en stdlib?:** sí, tras resolver callables y búsqueda/instalación de stdlib.
- **¿Requiere runtime/backend?:** resolución/link de módulos.

## Resultado de la prueba

No fue necesario corregir semántica del compilador para ejecutar el ejemplo.
Se adaptó el diseño a capacidades existentes mediante una interfaz y se cambió
el identificador local reservado `function` por `target`. El test automatizado
valida:

- convergencia y precisión de los tres métodos de raíces;
- bracket inválido;
- derivada y denominador de secante casi nulos;
- precisión de trapecios y Simpson;
- excepción por subdivisiones inválidas de Simpson.

La matemática escalar ya no bloquea native. El ejemplo completo todavía no
compila por interfaces, `throw`/`try-catch` y comparación general de strings.
La próxima mejora de mayor retorno es un callable tipado mínimo para funciones
top-level; después conviene decidir el modelo de errores compilado. Globals e
inicialización de módulos siguen siendo deuda general, pero no son el bloqueo
que reporta este ejemplo declarativo.
