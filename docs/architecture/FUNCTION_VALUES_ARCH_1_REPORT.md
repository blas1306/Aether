# FUNCTION-VALUES-ARCH-1 — reporte de diseño

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-15.

Documento normativo:
[FUNCTION_VALUES_ARCH_1](FUNCTION_VALUES_ARCH_1.md).

## Resultado

Se diseñaron valores de función no capturantes para `compiler-next` sin cambiar
parser, AST, HIR, MIR, SSA, backend, runtime ni tests. La única sintaxis admitida
es `Function<(P1, P2, ...), R>`; los paréntesis de la lista son obligatorios
para cero, uno o varios parámetros y `void` sólo puede ocupar el retorno.

El tipo es estructural y canónico. `TypeData::Function` contiene una lista
canónica ordenada de parameter `TypeId` y el return `TypeId`. Aliases se borran
al resolver, nominales conservan identidad y firmas distintas no se convierten:
V1 es completamente invariante.

## Representación y ownership

El valor runtime es un único puntero no nulo a una instancia Aether concreta.
No contiene environment, descriptor, tag ni refcount. En Linux x86-64 ocupa
8 bytes con alineación 8 y siempre es Copy, Relocatable y Storable, con
`needs_drop = false`.

Por ello el diseño admite parámetros, locales, returns, phis, fields, enum
payloads y elementos de Array/List. Copiar o retornar el valor no asigna, no
retiene y no libera nada; las allocations propias de una colección siguen
siendo responsabilidad de la colección. Null/default callable e igualdad de
direcciones no forman parte del lenguaje.

## Referencias y calls

Una función block top-level no genérica visible puede aparecer como valor y su
tipo se infiere de la declaración, aun sin expected type. El shadowing lexical
da prioridad a locals/parámetros. Imports y aliases resuelven primero a
identidades semánticas; backend nunca vuelve a resolver nombres.

La distinción central queda preservada en todas las fases:

| Fuente | IR | LLVM |
| --- | --- | --- |
| `f(x)` donde `f` es declaración conocida | `Call` directo | `call/invoke ... @symbol(...)` |
| `Function<...> g = f` | `FunctionRef` | constante `ptr @symbol` |
| `g(x)` | `IndirectCall` | `call/invoke ... %callee(...)` |

Tomar la dirección de `f` no degrada otras calls directas. HIR, MIR y SSA
conservan `FunctionRef { target, function_type }` e
`IndirectCall { callee, args, signature }`; sus verificadores reconstruyen la
firma desde el TypeId y comprueban target, callee, aridad, arguments y return.
El análisis de reachability debe emitir una función aunque sólo se use mediante
su address.

## ABI y excepciones

LLVM usa `ptr` opaco como storage físico, pero eso no borra el prototype: la
firma canónica se verifica antes de codegen y la call se emite con parámetros y
retorno exactos, la calling convention bootstrap actual y ningún cast.
`FunctionRef` puede bajar como alias de operand constante sin fabricar una
instrucción, pero permanece operación explícita en SSA y dumps.

El `void` fuente conserva el ABI unit vigente de `compiler-next` (`i1`) tanto en
calls directas como indirectas. Una migración futura a LLVM `void` tendría que
ser global; no puede crear dos ABIs.

Toda call indirecta se considera capaz de unwind. Posibilidad de lanzar no es
parte del function TypeId bajo EXCEPTION-ARCH-2. MIR/SSA agregan el mismo edge
de cleanup/handler que para una call directa y LLVM usa `invoke` cuando existe
ese successor. Sólo una prueba interna cerrada de `nounwind` puede simplificarlo.

## Generics y límites

`Function<(T), T>` funciona dentro de HIR genérico: monomorphization sustituye
recursivamente parámetros y retorno, interna el tipo concreto y no deja generic
parameters llegar a MIR.

Una función genérica abierta no puede tomarse como valor en V1. El expected type
no instancia silenciosamente y todavía no se agrega una expresión
`identity<int>`. Una sintaxis explícita futura puede apuntar al `InstanceId`
concreto sin cambiar representación.

También quedan rechazados métodos bound/static/virtual/interface, constructors,
builtins/intrinsics como valores, closures, lambdas, variance, partial
application, overload sets y FFI pointers. Un wrapper top-level es la adaptación
explícita para un builtin.

## Primer vertical

**FUNCTION-VALUES-V1 — Newton callable spine** debe incorporar parsing y AST,
tipo canónico/properties/layout, refs top-level, parámetros/locales, calls
indirectas, verificación HIR/MIR/SSA, reachability y LLVM address/call/invoke.
Debe calificar cero/uno/múltiples parámetros, value/void, diagnostics negativos,
unwind, ausencia de lifecycle propio y O0/O2.

`examples/newton/main.ae` es obligatorio: `newton(f, df, ...)` conserva una call
directa a `newton` y referencias a `f`/`df`; dentro, `f(x)` y `df(x)` son calls
indirectas. Dumps e LLVM deben probar esa diferencia y la ejecución debe validar
raíz y residual.

Retorno de Function y storage en aggregate/Array/List quedan arquitectónicamente
admitidos, aunque pueden habilitarse en verticales posteriores con failure gates
cerrados. No requieren un segundo diseño de ownership o ABI.

## Validación de este milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se implementó código ni se cambió la superficie soportada.
- Se respetaron el TypeArena, unit ABI, capability lattice, monomorphization y
  protocolo EH reales de `compiler-next`.
- Se preservaron los cambios preexistentes en `examples/word_stats` y
  `examples/newton`.
- No quedan decisiones abiertas que bloqueen el primer vertical; generic refs,
  nullable/equality, stable ABI/FFI, checked error contracts y closures son
  milestones separados.
