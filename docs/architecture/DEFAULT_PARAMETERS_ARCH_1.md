# DEFAULT-PARAMETERS-ARCH-1 — parámetros con valor por defecto

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-20.

Este milestone define parámetros trailing con initializer por defecto para
`compiler-next`. No modifica parser, AST, HIR, MIR, SSA, backend, runtime,
tests ni la superficie actualmente admitida. La implementación pertenece a
verticales posteriores.

La decisión se integra con
[FUNCTION-VALUES-ARCH-1](FUNCTION_VALUES_ARCH_1.md), el modelo de excepciones
unchecked, los imports por identidad semántica, la monomorfización existente y
los borrows implícitos limitados a una call. Un default es metadata semántica de
una declaración y una receta de expansión en el caller; nunca forma parte del
tipo `Function`, del prototype físico ni del dispatch runtime.

## 1. Decisiones resumidas

- La sintaxis de parámetro pasa a ser `T name` o `T name = expression`.
- Desde el primer parámetro con default, todos los parámetros fuente siguientes
  deben tener default. No existen holes, argumentos named ni omisión intermedia.
- Para `n` parámetros y `k` defaults trailing, la aridad mínima es `n - k` y la
  máxima es `n`. Una call directa acepta cualquier aridad dentro de ese rango.
- El caller evalúa primero los argumentos explícitos y después cada default
  omitido, estrictamente de izquierda a derecha y exactamente una vez.
- Cada default se evalúa en cada call que lo omite. No se evalúa al declarar la
  función, no se memoiza y no existe storage estático para su resultado.
- Un default usa el scope de su declaración. Puede referir símbolos visibles,
  generic parameters y parámetros anteriores; no puede referir su propio
  parámetro ni parámetros posteriores. `hi = lo + 1.0` es legal.
- La inferencia generic usa únicamente argumentos explícitos, type arguments
  escritos y el expected result que ya admita el algoritmo normal. Un default
  no puede inventar type arguments. Después se sustituye la instancia concreta
  y se materializan/tipan sus defaults.
- HIR representa la lista física completa y conserva provenance
  `Explicit`/`Defaulted`. Bindings call-scoped hacen explícita la secuencia y
  permiten que un default use el valor ya evaluado de un parámetro anterior.
- MIR y SSA reciben una call ordinaria con todos sus operandos. No incorporan
  `DefaultArgument`, aridad variable ni reglas de expansión.
- Sólo una call cuyo target es una declaración conocida puede aplicar defaults.
  Una `IndirectCall` exige siempre la aridad completa de su `Function` type.
- Calls directas a métodos, incluidos virtual/interface dispatch, aplican la
  misma expansión en el caller antes del dispatch. El primer vertical queda
  acotado a funciones libres; métodos requieren un vertical posterior, no otro
  diseño.
- La firma LLVM, mangling y calling convention no cambian. No se generan
  overloads, wrappers, thunks ni dispatch por aridad.

## 2. Sintaxis y AST

La extensión normativa de la gramática es:

```text
parameter-list       := parameter ("," parameter)*
parameter            := type identifier default-initializer?
default-initializer  := "=" expression
```

Los defaults están permitidos únicamente en parámetros de declaraciones
callables que la arquitectura califique. No se extiende la gramática de call:
una call sigue siendo una lista positional contigua de expresiones.

```aether
double f(double x, double y = 0.0) {
    return x + y;
}

int range_sum(int first, int last = first + 10, int step = 1) {
    // ...
}
```

No se admiten:

```aether
int f(int a = 0, int b)       // required después de default
f(1, , 3)                     // hole
f(a = 1)                      // named argument
f(_, 3)                       // placeholder/omisión intermedia
```

`AstParameter` pasa conceptualmente a:

```text
AstParameter {
    ty: AstType,
    name: String,
    default: Option<AstExpr>,
    span: Span,
}
```

El `span` del parámetro cubre tipo, nombre e initializer cuando existe. El AST
conserva además el span propio de `=` y de la expresión para diagnostics. El
parser no intenta tipar ni expandir el default, pero sí puede reportar errores
sintácticos locales como una expresión ausente después de `=`.

## 3. Regla trailing y aridad

Sea una declaración con `n` parámetros fuente, indexados `0..n`. Sea `d` el
índice del primer parámetro con default, o `n` si ninguno tiene default. La
declaración es válida sólo si todos los índices `i >= d` tienen default.

```text
minimum_arity = d
maximum_arity = n
default_count = n - d
```

Para cero parámetros, mínimo y máximo son cero. Para una declaración sin
defaults, ambos son `n`. Estas cantidades se calculan una vez al recolectar la
declaración y se verifican de nuevo en las fronteras semánticas que deserialicen
metadata.

Una call directa con `m` argumentos es admisible por aridad si y sólo si:

```text
minimum_arity <= m <= maximum_arity
```

Los argumentos explícitos corresponden siempre a los primeros `m` parámetros.
Los parámetros `m..n` se materializan desde sus defaults en orden. Por tanto:

```aether
int f(int a, int b = 0, int c = 1, int d = 2) { ... }

f(10);             // (10, 0, 1, 2)
f(10, 20);         // (10, 20, 1, 2)
f(10, 20, 30);     // (10, 20, 30, 2)
f(10, 20, 30, 40); // todos explícitos
```

No existe una interpretación de `f(10, 40)` como `(a, d)`: siempre significa
`(a, b)`. Un call site con `m < minimum_arity` reporta los argumentos required
faltantes; uno con `m > maximum_arity` reporta exceso. La resolución de nombre
y target ocurre antes de usar este rango; no se crean candidatos por aridad ni
se introduce overload resolution.

## 4. Propiedad, identidad y API semántica

Los defaults pertenecen a `FunctionSignature`/declaración, no a `TypeData`:

```text
ParameterSignature {
    name: String,
    ty: TypeId,
    default: Option<DefaultArgumentTemplate>,
    span: Span,
}

DefaultArgumentTemplate {
    parameter_index: u32,
    bound_expression: BoundDefaultExpr,
    declaration_span: Span,
    dependencies: DefaultDependencies,
}
```

`BoundDefaultExpr` es una receta frontend con nombres ya ligados a identidades
semánticas y referencias a parámetros por índice. No es un valor runtime, no es
un `HirExpr` ligado a los `LocalId` del body del callee y no llega a MIR.

La firma física continúa formada sólo por tipos de parámetros y retorno:

```aether
double f(double x, double y = 0.0) { ... }
```

tiene exactamente `Function<(double, double), double>`. El default sí es parte
de la API fuente/semántica publicada: agregarlo, quitarlo o cambiar su expresión
puede cambiar qué clientes compilan o qué valor observan tras recompilar. No es
parte de identidad de tipo, symbol identity, mangling ni ABI.

## 5. Scope y resolución de nombres

El scope de un default es el de la declaración, nunca el del call site. Puede
usar:

- funciones, tipos, constantes y demás símbolos visibles desde la source unit
  que declara la función, respetando qualification, imports y visibility;
- generic parameters de la declaración;
- parámetros fuente con índice estrictamente menor al suyo.

No puede usar:

- locals o imports visibles sólo en el caller;
- el parámetro que está inicializando;
- parámetros posteriores, aunque éstos también tengan default;
- miembros de instancia mediante un `this` implícito mientras ese concepto no
  esté admitido como expresión ordinaria en el método.

Los nombres de todos los parámetros se reservan durante el binding del listado.
Así, una referencia que coincide con un parámetro propio o posterior produce el
diagnostic específico y no cae accidentalmente en un símbolo exterior homónimo.

```aether
double clamp(double x, double lo = 0.0, double hi = lo + 1.0) { ... }
// Legal: `hi` lee el valor concreto ya evaluado de `lo`.

int bad(int x = x) { ... }          // self-reference inválida
int bad2(int x = y, int y = 1) { ... } // forward reference inválida
```

Una cadena de defaults anteriores es legal. Con `f(a, b = makeB(a),
c = makeC(b))`, `f(makeA())` evalúa `makeA`, después `makeB` con ese resultado y
después `makeC` con el valor real de `b`.

El uso de un parámetro anterior obedece ownership y borrow checking normales.
Una lectura Copy es válida. Si un default consume un valor owning anterior, la
posterior entrega obligatoria de ese mismo argumento al callee constituye
use-after-move y se rechaza. No se agrega copia implícita para facilitar un
default.

## 6. Tiping, conversiones y generic functions

Un default debe producir un valor aceptable para el tipo declarado del
parámetro mediante exactamente las conversiones y la adaptación de argumento
que admitiría una expresión explícita en esa posición. No obtiene conversiones
especiales ni puede devolver `void` donde se requiere un valor.

El frontend procesa una declaración en dos niveles:

1. Al recolectarla, liga nombres, valida la regla trailing, dependencias hacia
   parámetros anteriores y que la expresión sea bien formada bajo los generic
   parameters y constraints declarados. Una función no generic debe quedar
   completamente tipada aquí.
2. Para una instancia generic concreta, sustituye todos los `TypeId`, vuelve a
   validar operaciones/conversiones dependientes de la instancia y materializa
   el HIR del default sólo cuando una call lo omite.

La resolución generic de una call mantiene este orden obligatorio:

1. resolver type arguments escritos;
2. tipar los argumentos explícitos permitidos y ejecutar la inferencia normal;
3. incorporar cualquier expected-result inference que ya esté admitida, sin
   añadir una regla nueva por defaults;
4. exigir que todo generic parameter esté determinado y validar constraints;
5. sustituir la firma concreta;
6. tipar/adaptar los argumentos explícitos contra ella;
7. materializar y tipar sólo los defaults omitidos, de izquierda a derecha.

Un default nunca participa en los pasos de inferencia. Por ejemplo, si `T` sólo
aparece en un parámetro omitido, la call debe escribir `T` explícitamente o
obtenerlo por otra fuente ya admitida; el initializer no puede elegirlo. Un
error dentro de un default generic se diagnostica con el span de la declaración
y una nota en el call site/instancia que lo hizo concreto.

Todos los defaults se validan al declarar aunque una call concreta siempre
suministre ese argumento. Esto evita esconder APIs inválidas detrás de call
sites afortunados. La validación por instancia no sustituye la validación
paramétrica; la complementa.

## 7. Expansión HIR y provenance

La expansión ocurre después de resolver la declaración y la instancia generic,
pero antes de MIR. HIR debe contener los `n` argumentos físicos y distinguir su
origen. La forma conceptual cerrada es:

```text
HirCallArgument {
    binding: LocalId,              // local sintético, inmutable y call-scoped
    initializer: HirExpr,
    ty: TypeId,                    // tipo concreto del parámetro
    origin: Explicit { source_span }
          | Defaulted {
                declaration: FunctionId,
                parameter_index: u32,
                default_span: Span,
                call_span: Span,
            },
}

HirExprKind::Call {
    call_site: CallSiteId,
    callee: HirCallTarget,
    type_arguments: Vec<TypeId>,
    args: Vec<HirCallArgument>,    // siempre la aridad física completa
}
```

El nombre `LocalId` es conceptual: la implementación puede usar una identidad
dedicada si conserva las mismas invariantes. Cada entry inicializa su binding
en orden. Una referencia desde un default al parámetro `i` se reescribe como
lectura del binding ya inicializado `i`. Los operandos de la call física son
esos bindings en el mismo orden.

Esta normalización da semántica de `let` secuencial:

```text
let $arg0 = adapt(makeA(), P0);                  // Explicit
let $arg1 = adapt(makeB($arg0), P1);             // Defaulted
let $arg2 = adapt(makeC($arg1), P2);             // Defaulted
call f(move-or-read $arg0, move-or-read $arg1, move-or-read $arg2)
```

No clona un `HirExpr`, no reevalúa un argumento y no sustituye texto fuente. La
provenance se conserva en dumps y diagnostics, pero no afecta igualdad de tipos
ni codegen.

El lowering HIR → MIR emite inicialización, temporales, borrows, drops y la call
ordinaria en ese orden. La `Rvalue::Call` resultante ya tiene `n` operands; MIR
y SSA no poseen una variante default ni consultan `FunctionSignature.default`.

## 8. Evaluación, efectos y orden

Para una call directa con `m` argumentos explícitos y `n - m` omitidos:

1. se evalúan y adaptan los explícitos `0..m`, de izquierda a derecha;
2. se evalúan y adaptan los defaults `m..n`, de izquierda a derecha;
3. se ejecuta la call física sólo si todos terminaron normalmente.

Cada initializer se ejecuta exactamente una vez. Los defaults no se adelantan,
no se ejecutan si el argumento es explícito y no se constant-foldéan de modo que
cambie comportamiento observable. Optimizaciones pueden eliminar trabajo sólo
bajo las mismas reglas de efectos que cualquier otra expresión.

```aether
void f(int a, int b = makeB(), int c = makeC()) { ... }
f(makeA());
```

El orden observable es `makeA()`, `makeB()`, `makeC()`, `f(...)`. Dos ejecuciones
de `f()` ejecutan dos veces cada default omitido. Recursión provocada por un
default es recursión runtime ordinaria; no hay evaluación de declaración ni
ciclo especial de metadata.

## 9. Ownership, borrows, temporales y unwind

Los bindings sintéticos son call-scoped y usan las reglas ordinarias de
definite initialization, move, drop y borrow. Después de inicializar cada uno,
su cleanup queda activo. Si un initializer posterior traps o lanza:

- la función target no se invoca;
- se destruyen en orden inverso sólo los owners ya inicializados;
- se terminan los borrows ya iniciados conforme al cleanup edge vigente;
- nunca se intenta destruir un binding todavía no inicializado;
- el exception payload y los cleanups siguen el protocolo existente, sin una
  ruta especial para defaults.

Una call potencialmente throwing dentro de un default recibe el mismo
`invoke`/unwind successor que la misma call escrita explícitamente. Una vez
evaluados todos los argumentos, un throw desde el callee limpia temporales no
transferidos y cierra borrows con la política normal de la call.

La adaptación implícita `T -> ref T` conserva su metadata `call_site` e índice
físico. El lifetime comienza cuando se evalúa ese argumento —explícito o
defaulted— y abarca los defaults posteriores y la call. Conflictos con una
mutación o borrow posterior se diagnostican normalmente. Un temporary owning
prestado por un default vive al menos hasta retorno normal o unwind de la call y
se destruye exactamente una vez.

Los traps siguen siendo abortivos según su contrato actual. El frontend debe
mantener el orden previo al trap; no promete cleanup recuperable donde el modelo
de trap no lo ofrece.

## 10. Imports, packages y artefactos

La resolución de una call imported produce la misma identidad `FunctionId`/
`SymbolKey` que una call local y consulta una sola `FunctionSignature`; no existe
una ruta de expansión por módulo. Los aliases de package cambian spelling, no
el owner del default ni su scope.

Como un default se ejecuta en el caller, una interfaz semántica compilada debe
publicar, para cada parámetro defaulted:

- su posición y tipo canónico/paramétrico;
- el template ligado y sus spans/provenance reproducible;
- identidades de símbolos y generic parameters referenciados;
- dependencias y visibility necesarias para materializarlo;
- un fingerprint que invalide callers cuando cambie.

No basta exportar el prototype LLVM. Un paquete binario que no incluya esta
metadata no puede ofrecer defaults a nuevos callers y debe requerir aridad
completa. La metadata no se refleja en runtime ni se pasa al linker como parte
del symbol type.

El scope sigue siendo el de la declaración: un nombre importado por la librería
se guarda ya ligado. El caller no necesita importar ese nombre ni puede
redireccionarlo con un alias local. Visibility se comprueba en el contexto de
la declaración y la interfaz sólo puede publicar templates cuyas dependencias
sean legalmente materializables por el modelo de artefactos.

## 11. Function values e indirect calls

`TypeData::Function`, `FunctionRef`, `IndirectCall` y el prototype LLVM retienen
únicamente la firma física completa. Por tanto:

```aether
double f(double x, double y = 0.0) { return x + y; }

Function<(double, double), double> ok = f;
Function<(double), double> bad = f; // tipos distintos; no hay thunk

ok(1.0, 2.0); // válido
ok(1.0);      // inválido: indirect call requiere aridad completa
```

La expresión `f` pierde la ergonomía declarativa al convertirse en valor; el
puntero no porta metadata. La distinción no depende de la sintaxis visual sino
del target resuelto: si shadowing hace que `f` sea un local `Function`, `f(x)` es
indirecta y no puede aplicar los defaults de una declaración homónima.

No se generan wrappers por aridad, partial applications ni coerciones entre
function types. Los verificadores HIR/MIR/SSA de `FunctionRef` e `IndirectCall`
continúan exigiendo coincidencia exacta de todos los parámetros.

## 12. Métodos, virtual dispatch e interfaces

La semántica general incluye cualquier call de método cuyo frontend conozca una
declaración estática: método directo, virtual o requisito de interface. El
receiver implícito no cuenta en la aridad fuente ni puede omitirse. El caller
materializa los argumentos completos antes de seleccionar/invocar el slot; la
vtable y witness table conservan una única firma física completa.

Los defaults pertenecen a la declaración seleccionada estáticamente:

- una call mediante tipo base usa los defaults escritos en el método base;
- una call mediante interface usa los defaults del requirement;
- una call resuelta directamente a un método de clase usa los de esa
  declaración;
- el body finalmente ejecutado por dispatch no reevalúa ni reemplaza valores.

Un override/implementation no hereda metadata al caller ni necesita repetir el
initializer para ser ABI-compatible. Puede declarar defaults propios para calls
que se resuelvan estáticamente a él; agregar, quitar o cambiar esos defaults no
cambia compatibilidad del slot. Se recomienda no divergir porque el valor
observado depende deliberadamente del tipo estático, como ocurre con toda
expansión caller-side.

Initializers, métodos directos, virtuales y requirements quedan admitidos por
esta arquitectura. El primer vertical implementa sólo funciones libres. Hasta
el vertical OOP correspondiente, cualquier `=` en parámetros de miembros debe
producir un diagnostic `unsupported`, nunca ignorarse ni cambiar ABI.

## 13. Diagnostics

El primer vertical reserva la familia `E0360..E0367`; si el catálogo central
reasigna números antes de implementar, los nombres y contenidos siguientes
siguen siendo normativos.

| Código | Situación y mensaje mínimo | Span primario / notas |
| --- | --- | --- |
| `E0360 required_parameter_after_default` | ``parameter `b` is required after a parameter with a default`` | nombre de `b`; nota en el primer default |
| `E0361 default_type_mismatch` | ``default for parameter `p` requires T: <cause>`` | expresión default; nota en tipo de `p` |
| `E0362 too_few_direct_arguments` | ``function `f` accepts N..M arguments, found K; missing required ...`` | call; nota en declaración |
| `E0363 too_many_direct_arguments` | ``function `f` accepts at most M arguments, found K`` | primer argumento excedente o call |
| `E0364 invalid_default_parameter_reference` | ``default for `p` cannot reference itself/later parameter `q` `` | referencia; notas en ambas declaraciones |
| `E0365 cannot_type_default` | ``cannot type default for `p` [for instance ...]: <cause>`` | expresión default; nota en call concreta si aplica |
| `E0366 indirect_call_omits_arguments` | ``function value requires M arguments; defaults are available only on direct declarations`` | indirect call; nota en `Function` type |
| `E0367 default_context_unsupported` | ``default parameters are not yet supported on <context>`` | `=`/initializer; nota del vertical habilitado |

Una expresión ausente tras `=` sigue siendo error de parsing. Un nombre externo
desconocido, visibility violation, move conflict, borrow conflict o throw
incorrecto usa el diagnostic ordinario y añade contexto “while checking default
for parameter ...”.

Para una función con rango degenerado `N..N`, los mensajes pueden decir
“expects exactly N”. Para `0..M`, no deben inventar parámetros required. Los
diagnostics distinguen aridad de tipo: primero se valida el rango; después cada
argumento/materialización en orden y se reporta su posición física y origen.

## 14. ABI y backend

Una declaración:

```aether
int f(int a, int b = 0) { ... }
```

se emite exactamente como `f(int, int) -> int` bajo el ABI ya vigente. Tanto
`f(1)` como `f(1, 2)` producen una call con dos operands después de HIR. El
backend no consulta defaults y el LLVM prototype, attributes, calling
convention, exception personality y symbol son idénticos a los de la misma
declaración sin initializer.

Queda prohibido:

- emitir overloads ocultos `f$arity1`, wrappers o thunks;
- pasar count masks, sentinels o metadata runtime;
- cambiar el layout de function values o vtables;
- seleccionar defaults dentro del callee;
- representar ausencia mediante zero/null;
- variar mangling por initializer o aridad mínima.

Los dumps frontend pueden mostrar `default` y provenance. Los dumps MIR/SSA y
LLVM deben mostrar únicamente evaluación ordinaria, cleanup y la call de aridad
completa.

## 15. Primer vertical — DEFAULT-PARAMETERS-V1

El primer vertical queda deliberadamente acotado a funciones libres de usuario,
locales o imported dentro del modelo de source packages que compila el programa
conjunto. Debe implementar:

1. parsing y `AstParameter.default`;
2. regla trailing y metadata en `FunctionSignature`;
3. binding/tiping de defaults, incluidos parámetros anteriores;
4. aridad directa mínima/máxima;
5. inferencia generic sólo desde inputs no-default;
6. bindings HIR call-scoped con provenance y lista completa;
7. lowering ordinario con ownership, implicit shared borrow y unwind;
8. diagnostics `E0360..E0367` aplicables;
9. dumps que prueben expansión antes de MIR;
10. ejecución y LLVM en O0/O2 sin cambio de prototype.

Quedan failure-gated en ese vertical:

- `=` en métodos, initializers e interface requirements: `E0367`;
- defaults en builtins/Core/stdlib intrinsics sin declaración Aether ordinaria:
  `E0367`;
- artefactos binarios externos que no transporten template semántico: exigir
  aridad completa, sin degradación silenciosa.

La matriz mínima de calificación incluye:

- uno y varios defaults; todos explícitos, todos omitidos y sufijo parcialmente
  omitido;
- required después de default, demasiados y muy pocos argumentos;
- mismatch y nombre propio/posterior inválido;
- default que referencia parámetro anterior explícito y anterior defaulted;
- side effects y orden estricto con contadores;
- default throwing y cleanup inverso de owners/temporales previos;
- borrow implícito call-scoped creado por argumento explícito y por default;
- generic con inferencia suficiente, type arguments explícitos e inferencia que
  fallaría si dependiera del default;
- función imported por nombre qualified/alias;
- `FunctionRef` conserva firma completa e indirect call abreviada falla;
- misma firma MIR/SSA/LLVM y mismo prototype con/sin default;
- ejecución y estructura en O0 y O2.

## 16. Fuera de scope y decisiones abiertas

Fuera de scope permanecen overloads, named arguments, holes, omisión
intermedia, variadics, partial application, lambdas/closures, reflection de
defaults, runtime metadata, adaptación automática de function values y ABI de
aridad variable.

No queda ninguna decisión abierta que bloquee `DEFAULT-PARAMETERS-V1`. Los
siguientes son milestones separados con una frontera ya definida:

- habilitar la misma normalización en métodos/initializers/interfaces;
- formato persistente exacto de `BoundDefaultExpr` y sus fingerprints para
  distribución binaria/incremental;
- política de compatibilidad de API/versionado al cambiar un initializer;
- defaults para builtins o APIs nativas que no posean declaración Aether;
- una futura semántica de `this` en defaults de métodos;
- named arguments u omisión no trailing, que requerirían nueva sintaxis y
  resolución pero no deben alterar el ABI completo aquí fijado.

