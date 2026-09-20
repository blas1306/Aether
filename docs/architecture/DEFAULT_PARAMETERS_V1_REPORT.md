# DEFAULT-PARAMETERS-V1 — parámetros trailing materializados en el caller

Estado: **IMPLEMENTADO Y CALIFICADO** en `compiler-next`, Linux x86-64,
2026-09-20.

Documento normativo:
[DEFAULT_PARAMETERS_ARCH_1](DEFAULT_PARAMETERS_ARCH_1.md).

## Resultado

El parser admite `T name = expression` en parámetros. Las funciones libres de
usuario, locales o importadas, exponen un rango de aridad directa entre el
primer default y la aridad física completa. Desde el primer default todos los
parámetros posteriores deben tener initializer; no se añadieron named
arguments, holes, overloads, variadics ni omisión intermedia.

Los defaults se conservan en `ParameterSignature` como templates de la
declaración, con posición y spans propios. Todos se validan paramétricamente al
analizar la declaración, incluso si ningún call site los omite. Self-reference
y forward-reference se resuelven contra la lista completa de parámetros y se
rechazan; los parámetros anteriores se ligan al binding concreto de la call.
La materialización cambia temporalmente al módulo y generic scope del proveedor,
por lo que una call importada no reinterpreta nombres en el caller.

## Aridad, generics y diagnostics

Una call directa valida primero `minimum_arity..physical_arity`. La inferencia
generic recorre exclusivamente argumentos explícitos. Después de determinar y
validar la instancia se sustituyen los tipos y se tipan/adaptan los defaults
omitidos. Un generic parameter que sólo podría determinarse desde una omisión
continúa produciendo el rechazo ordinario de inferencia.

Se implementó la familia cerrada:

- `E0360`: parámetro required posterior a un default;
- `E0361`: tipo inválido del initializer;
- `E0362` / `E0363`: muy pocos o demasiados argumentos directos;
- `E0364`: referencia al propio parámetro o a uno posterior;
- `E0365`: default que no puede tiparse, incluido contexto de instancia;
- `E0366`: call indirecta que omite argumentos;
- `E0367`: defaults todavía no admitidos en métodos, initializers o
  requirements de interface.

Los builtins/Core/std intrinsics sin una declaración Aether ordinaria no
adquieren metadata ni una ruta de defaults.

## HIR y orden de evaluación

`HirExprKind::Call` contiene siempre la aridad física completa. Cada
`HirCallArgument` posee un `LocalId` sintético call-scoped, initializer, tipo
concreto y provenance `Explicit` o `Defaulted`. El provenance defaulted conserva
declaración, índice físico, span del initializer y span de la call.

Los explícitos se materializan primero y los defaults omitidos después, todos
de izquierda a derecha. Un default que lee un parámetro anterior lee su binding,
no clona el AST ni reevalúa el argumento. La qualification ejecuta defaults
encadenados y efectos sobre un contador para comprobar orden y evaluación única.

El verificador HIR reconstruye firma, binding, tipo, unicidad, sufijo de
provenance y adaptación de borrow. La monomorfización sustituye initializer y
tipo del binding antes de MIR.

## Ownership, borrow y excepciones

HIR ownership trata cada binding como una inicialización local secuencial. Los
owners no-Copy quedan vivos mientras se materializan argumentos posteriores y
se consumen sólo al entrar en la call física. Un uso consumidor desde un
default anterior entra en las reglas normales de move y no recibe Clone o Alias
implícito.

MIR inicializa los bindings en orden mediante `Use`/`Move`. Mientras puede
lanzar un initializer posterior, los owners ya publicados están registrados en
el cleanup temporal; el landing pad los destruye en orden inverso y nunca toca
un binding aún no inicializado. Justo antes de la call se transfieren a
temporales ordinarios y se desarman sus drop flags. No se agregó una operación
MIR de default.

La adaptación exacta `T -> ref T` funciona tanto para argumentos explícitos
como defaulted. El borrow conserva `CallSiteId`, índice físico, source y origen;
permanece activo durante defaults posteriores y la call, y termina en retorno o
unwind mediante el protocolo existente.

## Function values, imports y ABI

`TypeData::Function`, `FunctionRef` e `IndirectCall` no contienen defaults. Una
referencia a una función con defaults conserva la firma física completa y toda
call indirecta exige esa aridad. No se generaron wrappers, thunks ni partial
applications.

Las calls calificadas y por alias a funciones importadas usan la identidad y el
scope del proveedor. V1 opera sobre el programa fuente conjunto; no define aún
serialización binaria de templates.

MIR, SSA y LLVM sólo ven inicializaciones ordinarias más una call de aridad
completa. Mangling, calling convention y prototype LLVM son idénticos con y sin
initializer; no existen masks, sentinels ni metadata runtime.

## Qualification

La suite `crates/aether-driver/tests/default_parameters_v1.rs` cubre:

- uno y varios defaults, omisión total/parcial y todos los argumentos
  explícitos;
- defaults encadenados que usan un parámetro anterior explícito o defaulted;
- side effects, orden estricto y evaluación única;
- aridad, trailing rule, mismatch, self/forward reference y gates OOP;
- borrow shared implícito explícito/defaulted;
- inferencia generic suficiente, type arguments explícitos y rechazo cuando
  el type parameter no se determina sin el default;
- throw durante un default posterior, cleanup de los owners inicializados y
  propagación por los unwind edges existentes;
- función importada mediante alias y scope del proveedor;
- `FunctionRef` con firma completa, rechazo de indirect call abreviada y
  ausencia de wrappers;
- provenance HIR, desaparición de defaults antes de MIR/SSA, mismo prototype
  LLVM y ejecución nativa O0/O2.

Los gates de cierre ejecutados fueron:

```text
cargo test --workspace                                      PASS
cargo fmt --all --check                                    PASS
cargo clippy --workspace --all-targets -- -D warnings      PASS
git diff --check                                           PASS
bash compiler-next/tests/run-differential.sh               PASS (21/21)
```

## Fuera de scope conservado

Siguen fuera overloads, named arguments, holes, omisión no trailing,
variadics, closures/lambdas, defaults en métodos/initializers/interfaces,
metadata runtime, thunks por aridad, cambios ABI y persistencia cross-package de
templates compilados.
