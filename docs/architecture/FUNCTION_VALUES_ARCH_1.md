# FUNCTION-VALUES-ARCH-1 — valores de función no capturantes

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-15.

Este milestone define valores de función no capturantes para `compiler-next`.
No modifica parser, AST, HIR, MIR, SSA, backend, runtime, tests ni la fila de
features soportadas. La implementación pertenece a verticales posteriores.

La decisión se apoya en el `TypeArena` canónico actual, la separación verificada
AST → HIR → MIR → SSA → LLVM, el ABI bootstrap Linux x86-64, las reglas de
ownership/capabilities y el modelo de excepciones unchecked ya admitido.

## 1. Decisiones resumidas

- La única sintaxis es `Function<(P1, P2, ...), R>`; los paréntesis de la lista
  de parámetros son obligatorios incluso con cero o un parámetro.
- `Function<(P...), R>` es un tipo estructural canónico. Su identidad contiene
  los `TypeId` ordenados de los parámetros y el `TypeId` de retorno; no contiene
  nombre, `FunctionId`, módulo, origen, span ni spelling de aliases.
- Dos function types son iguales sólo cuando tienen igual aridad y cada
  `TypeId`, incluido el retorno, coincide exactamente. V1 es invariante y no
  introduce conversiones entre firmas.
- El valor runtime es un único puntero no nulo a una función Aether con el ABI
  exacto de la firma. No hay environment pointer, heap, ARC, drop ni descriptor.
- Todo function value es `Copy`, `Relocatable` y `Storable`, no necesita drop y
  ocupa un word en el target actualmente admitido.
- Una función top-level no genérica visible tiene un tipo de función inferible
  cuando su nombre aparece en posición de valor. No necesita contexto esperado.
- `f(args)` sigue siendo una llamada directa cuando `f` resuelve a una
  declaración libre conocida. Una variable/parámetro/expresión de tipo
  `Function` produce una llamada indirecta.
- HIR, MIR y SSA conservan `FunctionRef` e `IndirectCall` explícitos. `Call`
  directo no cambia.
- Los verificadores reconstruyen la firma desde el `TypeId` canónico y la
  comparan con la instancia concreta referenciada, sus argumentos y resultado.
- Una llamada indirecta se considera capaz de unwind. Usa el mismo cleanup,
  landing-pad e `invoke` que una llamada directa desconocida, salvo prueba
  interna válida de `nounwind`.
- Se admiten paso, retorno, locales, fields y elementos de `Array`/`List` porque
  el valor es Copy/Storable y no porta una lifetime. El primer vertical no tiene
  que calificar toda esa superficie a la vez.
- `Function<(T), T>` es válido dentro de código genérico y se sustituye al
  monomorfizar. Una declaración de función genérica no puede tomarse como valor
  en V1 porque no existe una sintaxis de referencia a una instancia concreta.
- Closures, lambdas, métodos enlazados, virtual/interface method references,
  builtins como valores y FFI function pointers quedan fuera de scope.

## 2. Superficie fuente y gramática

La gramática normativa es:

```text
type                    := reference_type
                         | function_type
                         | named_type

function_type           := "Function" "<" function_parameter_tuple
                           "," type ">"
function_parameter_tuple := "(" function_parameter_types? ")"
function_parameter_types := type ("," type)*
```

Ejemplos válidos:

```aether
Function<(), int>
Function<(double), double>
Function<(int, bool), void>
Function<(List<int>, Function<(), bool>), Array<double>>
Function<(T), T>
```

La lista entre paréntesis es sintaxis propia de la firma, no un tipo tuple de
Aether. En particular `()` sólo significa cero parámetros dentro del primer
argumento de `Function`; no crea un `Unit` fuente almacenable.

Son inválidos:

```aether
Function<double, double>          // falta la lista `(double)`
Function<((double)), double>      // no existe un tipo tuple/paréntesis general
Function<(double,), double>       // trailing comma no admitida en V1
Function<(void), int>             // void no es tipo de parámetro
Function<(int), void, bool>       // hay exactamente dos componentes
function(double) -> double        // sintaxis alternativa
fn(double): double                // sintaxis alternativa
```

`Function` es una forma intrínseca sólo sin qualification. `pkg.Function<...>`
se resuelve como un nombre nominal qualified ordinario y no como function type.
El nombre unqualified `Function` queda reservado en el namespace de tipos y no
puede redeclararse como alias o nominal. No se reserva una segunda forma
histórica. Un alias transparente con otro nombre sí puede nombrar el tipo
canónico:

```aether
public alias Unary = Function<(double), double>;
```

### 2.1 Parsing exacto

Al ver el identifier no qualified `Function` seguido de `<`, el parser entra en
la producción dedicada. Después de `<` exige `(`, parsea cero o más `type`
separados por comas, exige `)`, una coma, exactamente un `type` de retorno y
`>`. El cierre de tipos nested usa la misma tokenización de `>` que el resto de
generic applications.

Los errores se anclan en el primer token que hace imposible continuar:

- ausencia de `(` después de `Function<`;
- ausencia de tipo después de `(` o `,`;
- ausencia de `)` antes del separador de retorno;
- ausencia de la coma entre tuple y retorno;
- ausencia del retorno;
- argumentos adicionales o falta de `>`.

El AST debe dejar de representar toda forma de tipo como un nombre con una lista
homogénea de argumentos. La forma conceptual cerrada es:

```text
AstType {
    kind: Named { module, name, arguments }
        | Reference { pointee, mutable }
        | Function { parameters, result },
    span
}
```

Esto evita codificar la parameter tuple como un nombre falso, impide estados
como `reference + Function` simultáneos y conserva spans de cada componente.
Los consumidores actuales de `AstType.module/name/arguments/reference` deberán
migrar al discriminante; no debe usarse un sentinel como `Tuple` o `()`.

### 2.2 Legalidad de `void`

`void` continúa siendo ausencia de resultado y no un valor almacenable. Se
permite como `result` de `Function`, incluso nested:

```aether
Function<(), void>
Function<(Function<(), void>), int>
```

Se rechaza en parámetros, incluso oculto por un alias, y en toda posición que
las reglas actuales ya prohíben: local, field, element, generic argument de una
colección o retorno dentro de un aggregate. La restricción se valida después de
canonicalizar aliases, no por spelling.

Una llamada cuyo callable retorna `void` sólo es legal en las posiciones donde
una llamada directa `void` ya es legal. No convierte `void` en un valor fuente.

## 3. Tipo canónico e identidad

`TypeData` incorpora una variante estructural:

```text
TypeData::Function {
    parameters: TypeArgsId,
    result: TypeId,
}
```

`TypeArgsId` reutiliza la lista ordenada canónica del arena. No representa la
parameter tuple como otro `TypeId`; por tanto no aparece un tipo tuple incidental
en layout, diagnostics ni mangling.

`TypeArena::intern_function(parameters, result)`:

1. exige que todos los `TypeId` existan en el mismo arena;
2. exige que ningún parámetro sea `void`;
3. acepta `void` como resultado;
4. interna primero la lista ordenada de parámetros;
5. retorna el único `TypeId` asociado a `{parameters, result}`.

La igualdad es igualdad del `TypeData` ya internado. Los aliases desaparecen al
resolver, de modo que alias y target producen el mismo `TypeId`. Los nominales
continúan siendo nominales: dos structs de igual layout dentro de una firma no
son intercambiables.

Ejemplos:

```text
Function<(int32), int64> != Function<(int64), int64>
Function<(ref T), R>     != Function<(T), R>
Function<(ref T), R>     != Function<(ref mut T), R>
Function<(A, B), R>      != Function<(B, A), R>
Function<(), void>       == el mismo TypeId tras cualquier alias transparente
```

El `TypeId` sigue siendo session-local y no es identidad ABI persistente. Dumps,
diagnostics y mangling formatean recursivamente la forma fuente canónica
`Function<(P1, ...), R>`.

### 3.1 Invariancia y conversiones

Parámetros y retorno son invariantes en V1. No hay contravariancia,
covariancia, widening de firmas, adaptación de ownership, conversión de
`ref mut` a `ref`, wrapper implícito ni reinterpretación de punteros.

La ausencia de conversión entre function types no cambia el typing de una
llamada. Cada argumento de una llamada indirecta pasa por las mismas
conversiones ordinarias que una llamada directa. HIR inserta las coerciones
permitidas antes de `IndirectCall`; MIR/SSA reciben operandos cuyo `TypeId` ya
coincide exactamente con cada parámetro.

El tipo de una referencia debe coincidir exactamente con la firma ya resuelta de
la función. No se usa el expected type para fabricar un thunk:

```aether
int64 wide(int32 x) { ... }
Function<(int64), int64> bad = wide; // incompatible, aunque una call directa
                                     // pudiera admitir algún widening de args
```

### 3.2 Nullability e igualdad

Un function value válido nunca es null. V1 no tiene literal null para Function,
default zero initialization, optional callable ni sentinel. Definite
initialization impide observar un slot sin inicializar. Un null encontrado
después de HIR sería corrupción/invariant failure, no un valor Aether.

`==`, ordering, hashing y reflection de function values no se admiten en este
milestone. La representación de un word no convierte igualdad de direcciones en
semántica fuente; optimización, thunks futuros y linking podrían cambiarla.

## 4. Ownership, capabilities y storage

Para todo `TypeData::Function`, independientemente de los tipos mencionados en
su firma:

| Propiedad | V1 |
| --- | --- |
| `is_known` | `true`, incluso si la firma contiene generic parameters |
| `Copy` | `true` |
| `Relocatable` | `true` |
| `Storable` | `true` |
| `needs_drop` | `false` |
| ownership del target | no-owning; el código vive al menos todo el proceso |
| tamaño/alineación Linux x86-64 | 8/8 bytes |

La propiedad no se deriva de los parámetros ni del retorno. Un callable que
acepta un owner no posee ese owner mientras está almacenado; sólo la ejecución
de la llamada aplica el contrato normal del parámetro.

Copiar, asignar, pasar y retornar un function value copia un word. No hay
retain/release, drop flag, cleanup, allocation ni runtime helper. Puede ser:

- parámetro o retorno por valor;
- local y valor de un merge/phi;
- field de struct o payload de enum;
- elemento de `Array<Function<...>>`;
- elemento de `List<Function<...>>`.

Las colecciones continúan realizando sus allocations normales; el elemento
Function por sí mismo no asigna. List puede relocalizarlo mediante la ruta Copy/
Relocatable existente y el drop de un aggregate no genera acción para ese field.

Una firma puede mencionar referencias según las reglas actuales de parámetros.
Eso no vuelve borrowed al function value. Los retornos borrowed que el lenguaje
ya prohíbe continúan prohibidos; Function no abre una vía de escape.

## 5. Declaraciones y referencias a funciones

Son targets V1 únicamente funciones block top-level de usuario, visibles y con
una firma concreta. No hay overload sets en `compiler-next`, por lo que cada
nombre visible resuelve a lo sumo a una declaración.

Una expresión de nombre que no resuelve primero a local/parámetro y sí resuelve
a una función elegible produce:

```text
HirExprKind::FunctionRef {
    target: HirCallTarget,
    function_type: TypeId,
}
```

El tipo se infiere directamente de la firma; un expected type no es necesario.
Si existe, se compara después por igualdad canónica exacta. Esto permite:

```aether
double square(double x) { return x * x; }

Function<(double), double> a = square;
var b = square; // sólo si la inferencia local `var` ya está admitida;
                // este milestone no introduce `var`
```

El shadowing conserva la regla lexical ordinaria: un local/parámetro `f` oculta
una función libre `f`. Un nombre oculto no puede recuperarse por expected type.
Una función importada puede referenciarse mediante las mismas formas full,
selective y alias que ya le dan visibilidad; `module.f` en posición de valor se
resuelve por identidad de módulo y `FunctionId`, nunca por texto en backend.

La referencia no ejecuta el cuerpo ni evalúa argumentos. Materializa la
dirección de la instancia concreta y mantiene esa instancia alcanzable para
codegen aunque no exista ninguna call directa hacia ella.

### 5.1 Targets excluidos

V1 rechaza como function value:

- Core calls, intrinsics, `abs`, `exp`, `println` y otros builtins especiales;
- métodos de instancia, `obj.method` y `this.method`;
- métodos virtuales o requirements de interface;
- constructors/initializers;
- una declaración genérica abierta;
- una class/static method aunque en el futuro pueda usar un ABI similar.

Un wrapper top-level de usuario es la adaptación explícita para un builtin.
Methods static/free podrán admitirse en otro milestone sólo después de probar
que tienen identidad de instancia, visibilidad y ABI equivalentes; no se
presupone aquí.

### 5.2 Funciones genéricas

Una función no genérica tiene una instancia concreta y es referenciable. Una
función genérica abierta no tiene una dirección única:

```aether
T identity<T>(T x) { return x; }
Function<(int), int> f = identity; // error V1
```

El expected type no infiere silenciosamente los type arguments y `identity<int>`
no se agrega como expresión en este milestone. Las instancias creadas por calls
directas continúan existiendo, pero no son nombrables como valores por accidente.
Una futura sintaxis explícita de referencia instanciada puede producir el mismo
`FunctionRef` a un `InstanceId`; no requiere cambiar representación ni ABI.

Esto es distinto de tipos genéricos dentro de una firma:

```aether
T apply<T>(Function<(T), T> f, T x) { return f(x); }
```

En HIR paramétrico el function `TypeId` contiene el `GenericParamId` exacto. La
substitución recorre parámetros y retorno, interna un function type concreto y
debe concluir antes de MIR. `Function<(Wrapper<T>), List<T>>` funciona del mismo
modo para un struct generic `Wrapper` ya declarado. MIR/SSA rechazan todo
function type que todavía contenga generic parameters.

## 6. Resolución de calls

La sintaxis de call debe permitir conceptualmente un callee expression, aunque
el AST actual optimice nombres simples:

```text
call_expression := postfix_expression "(" arguments? ")"
```

Semantic resolution distingue dos casos antes de construir HIR.

### 6.1 Call directa

Si el callee, ignorando paréntesis transparentes, es un nombre que resuelve a
una función libre concreta y no a un value binding, se emite el `HirExprKind::Call`
directo actual con su `HirCallTarget`. Ejemplos:

```aether
f(x)
module.f(x)
(f)(x) // los paréntesis no fuerzan indirección
```

Tomar `f` como valor en otro punto no degrada estas calls. El grafo de calls,
mangling y optimizaciones directas siguen viendo la identidad concreta.

### 6.2 Call indirecta

Si el callee resuelve a un expression value cuyo `TypeId` es Function, se emite:

```text
HirExprKind::IndirectCall {
    call_site: CallSiteId,
    callee: HirExpr,
    args: Vec<HirExpr>,
    signature: TypeId,
}
```

Esto cubre parámetros, locales, fields/projections, loads, resultados y phis:

```aether
Function<(double), double> g = f;
double y = g(x);                  // indirecta
Function<(double), double> h = choose(flag);
double z = h(x);                  // indirecta
```

El callee se evalúa exactamente una vez y antes de los argumentos. Los
argumentos se evalúan una vez, de izquierda a derecha, igual que en una call
directa. Una excepción durante callee/argumentos observa únicamente efectos y
cleanups previos.

Aridad y resultado vienen exclusivamente del `TypeData::Function`. Un value no
Function no es callable. Para retorno `void`, la call sólo puede aparecer como
statement según la regla existente.

## 7. HIR y verificación

Se agregan dos operaciones conceptuales, sin reutilizar `ClassOp` ni calls
virtuales:

```text
FunctionRef {
    target: HirCallTarget,       // Declaration en HIR paramétrico,
                                 // Instance en HIR concreto
    function_type: TypeId,
}

IndirectCall {
    call_site: CallSiteId,
    callee: HirExpr,
    args: Vec<HirExpr>,
    signature: TypeId,
}
```

El `HirExpr.ty` de `FunctionRef` coincide con `function_type`. El de
`IndirectCall` coincide con el result extraído de `signature`. No se copian
vectors de tipos como segunda autoridad.

El verificador HIR reconstruye y exige:

1. `function_type/signature` existe y es `TypeData::Function`;
2. un `FunctionRef` concreto apunta a un `FunctionInstanceInfo` existente;
3. parameters y return de esa instancia coinciden exactamente con el tipo;
4. un ref paramétrico apunta a la declaración correcta y su firma sustituible
   coincide bajo los mismos binders;
5. el callee de `IndirectCall` tiene exactamente `signature`;
6. la aridad coincide;
7. cada argumento, después de coerciones HIR explícitas, tiene el `TypeId` del
   parámetro correspondiente;
8. `HirExpr.ty` es el retorno exacto;
9. ningún target excluido se encubre como `FunctionRef`.

La monomorphization sustituye también `function_type/signature` y reifica todo
target permitido a `InstanceId`. HIR concreto que llegue a MIR no contiene un
`HirCallTarget::Declaration` en `FunctionRef`, del mismo modo que una call
directa concreta no lo contiene.

## 8. MIR

MIR conserva operaciones distintas:

```text
Rvalue::FunctionRef {
    target: InstanceId,
    signature: TypeId,
}

Rvalue::IndirectCall {
    call_site: CallSiteId,
    callee: Operand,
    args: Vec<Operand>,
    signature: TypeId,
}
```

`Rvalue::Call { callee: InstanceId, ... }` permanece exclusivamente directo.
No se baja una referencia a entero, no se usa `ClassOp::VirtualCall` y no se
añade environment operand.

`FunctionRef` es una computación Copy no trapping y sin unwind edge.
`IndirectCall` es un efecto ordenado potencialmente throwing. Lowering evalúa y
materializa callee antes de arguments, usa el protocolo existente de borrows/
owners para arguments y termina call-scoped borrows en el mismo punto que una
call directa.

El verificador MIR repite las obligaciones HIR con la tabla concreta de
`FunctionInstanceInfo`, valida todos los operands/locals y además exige:

- destination de `FunctionRef` igual a `signature`;
- firma exacta de `target`;
- operand callee de `IndirectCall` igual a `signature`;
- destination igual al retorno de la firma;
- arguments exactos, sin coerciones implícitas residuales;
- ningún generic parameter en signature;
- el unwind edge requerido por la política de la sección 10.

Al ser Copy, un function local no genera move state ni drop flags. Un MIR
corrupto que lo marque como `Move` puede tratarlo como copy sólo mediante el
lowering general ya autorizado para tipos Copy; nunca introduce una obligación
lineal especial.

## 9. SSA

SSA preserva:

```text
SsaOp::FunctionRef {
    target: InstanceId,
    signature: TypeId,
}

SsaOp::IndirectCall {
    call_site: CallSiteId,
    callee: SsaOperand,
    args: Vec<SsaOperand>,
    signature: TypeId,
}
```

`FunctionRef` define un valor de tipo `signature`. `IndirectCall` usa ese valor
como operand ordinario, define el result/unit de la firma y retiene su normal y
eventual exceptional edge. Function values participan normalmente en phis,
loads/stores, aggregate insert/extract y argument passing.

El verificador SSA reconstruye las mismas firmas y, adicionalmente, valida
single definition, dominance del callee y argumentos, phi types exactos,
alcanzabilidad, predecessors y exceptional-edge dominance. Un phi sólo puede
mezclar valores con el mismo function `TypeId`; no crea una firma unión.

`IndirectCall` nunca es pure: DCE no puede eliminarla sólo porque su resultado
no se use. SCCP o devirtualización pueden convertirla en `Call` directa sólo si
prueban un único `FunctionRef` target y vuelven a verificar firma, effects y
unwind. O0 y O2 deben ser semánticamente equivalentes.

El análisis de reachability de codegen incluye todo `target` nombrado por
`FunctionRef`. Una función usada sólo como valor no puede ser eliminada como
inaccesible.

## 10. Unwind y efectos

Según EXCEPTION-ARCH-2, posibilidad de unwind no forma parte de la identidad de
un function type. Las exceptions Aether son unchecked y una función puede
adquirir o perder internamente un path throwing sin cambiar su tipo fuente.

Por tanto toda `IndirectCall` es conservadoramente `may_unwind = true`. En una
función con eventos/cleanups excepcionales, MIR y SSA exigen el mismo unwind
edge que para `Call`, `VirtualCall` o `InterfaceCall`; el landing pad ejecuta
los drops de owners vivos y conserva el `ExceptionEvent` normal. Sin un cleanup
local necesario, la excepción puede propagarse por el mismo mecanismo ABI que
en una call directa.

El backend emite `invoke` cuando la instruction lleva exceptional successor y
`call` cuando no lo lleva. No adjunta `nounwind` a una indirect call por el mero
hecho de que sus targets observados hoy no lancen. Una optimización interna
puede probar un conjunto cerrado de targets todos `nounwind`, pero la prueba es
revocable, no cambia `TypeId` y debe mantener cleanup correctness.

Traps continúan siendo fail-fast y no recorren el edge de unwind. Closures
futuras no pueden reutilizar esta sección para esconder cleanup de environment.

## 11. Representación y ABI LLVM

En el target admitido, un function value tiene layout:

```text
FunctionValue = address of exact Aether function instance // one pointer word
```

No hay `{code, env}`, tag, descriptor, refcount, vtable, type metadata ni null.
La dirección pertenece al address space ordinario del módulo. El código tiene
lifetime de proceso y no es liberable.

LLVM actual usa opaque pointers, por lo que el storage type físico es `ptr` y no
codifica la firma. La autoridad sigue siendo `TypeId::Function`; backend y
verificadores construyen el prototype exacto antes de emitir LLVM. Opaque
pointer no autoriza a olvidar o reinterpretar una firma.

### 11.1 Referencia

`FunctionRef(target)` baja a la constante `ptr @mangled_target`. Como LLVM no
necesita una instrucción para materializar esa constante, el backend puede
mapear el `ValueId` SSA a ese operand durante emission. La operación permanece
explícita en SSA/dumps y no se fabrica un `bitcast`, `ptrtoint`, global mutable
ni runtime lookup.

El símbolo usa el mangling actual de la `FunctionInstanceInfo` concreta. Su
definición se emite aunque sólo sea alcanzable por referencia.

### 11.2 Call indirecta

Para firma `Function<(P1, ..., Pn), R>`:

```llvm
; sin handler/cleanup local
%r = call <llvm-R> %callee(<llvm-P1> %a1, ..., <llvm-Pn> %an)

; con exceptional edge
%r = invoke <llvm-R> %callee(<llvm-P1> %a1, ..., <llvm-Pn> %an)
       to label %normal unwind label %cleanup
```

Se usa la calling convention Aether bootstrap actual (la default que hoy usan
las calls directas), los mismos tipos físicos, ownership argument protocol y
return ABI. No se permite varargs ni un cast para hacer coincidir prototypes.
Una discrepancia es error del verificador/backend antes de producir LLVM.

`void` fuente conserva en este V1 la representación interna existente de
`compiler-next`: `TypeId::VOID`/unit baja a `i1` y la función/call transporta el
token unit. Esto mantiene ABI idéntico entre call directa e indirecta y encaja
con el modelo SSA donde toda expression tiene tipo. Si un milestone futuro
migra globalmente el ABI de `void` a LLVM `void`, deberá cambiar ambas clases de
call juntas; nunca puede darles ABIs diferentes.

El LLVM generado debe pasar `llvm-as`/`opt -verify` (o la verificación
equivalente disponible), y la qualification inspecciona que:

- la referencia es el símbolo exacto, sin cast;
- la call usa el operand `%callee`, no `@target`;
- parameter/return types son exactos;
- `invoke` conserva normal/unwind successors;
- O0/O2 no introducen allocation, ARC ni drop para Function.

## 12. Paso, retorno y aggregates

El ABI por valor de un function parameter o return es `ptr`. Esto admite:

```aether
Function<(double), double> choose(
    bool first,
    Function<(double), double> a,
    Function<(double), double> b
) {
    if (first) { return a; }
    return b;
}
```

Los returns copian el pointer y un merge usa phi `ptr`. No hay sret, hidden
environment ni ownership transfer. El retorno de callable se admite en la
arquitectura V1 aunque la especificación/bootstrap legacy anterior lo hubiera
diferido; el modelo actual de `compiler-next` ya puede expresarlo limpiamente
porque Function es Copy y no borrowed.

Un field/enum payload usa el layout normal de un pointer. Array/List calculan
stride/alignment desde `TypeArena::layout` y no contienen una excepción por
tipo. Las reglas de definite initialization siguen impidiendo null slots. Una
API que quiera representar “sin callback” necesita un futuro Optional/Nullable
explícito; no usa zero pointer.

## 13. Diagnostics

Se reserva la familia siguiente para el vertical. Los códigos, category, phase
y span forman parte de esta decisión.

| Caso | Diagnóstico propuesto | Fase |
| --- | --- | --- |
| forma `Function` incompleta/no canónica | `E0110 invalid Function type syntax; expected Function<(P1, ...), R>` | parse |
| `void` en un parámetro | `E0350 Function parameter type cannot be void` | semantic/type |
| ref/declaración con firma distinta | `E0351 function reference has type X, expected Y` | semantic/type |
| call indirecta con aridad incorrecta | `E0352 function value expects N arguments, found M` | semantic/type |
| argumento o retorno incompatible | `E0353 indirect call argument/result is incompatible with signature` | semantic/type |
| value no callable usado como callee | diagnóstico callable existente, mostrando su tipo canónico | semantic/type |
| método/bound method | `E0354 bound and method function values are not supported` | semantic/type |
| función genérica abierta | `E0355 generic function must be explicitly instantiated before use as a value` | semantic/type |
| builtin/intrinsic como valor | `E0356 builtin functions are not values; use a top-level wrapper` | semantic/type |
| null/default callable | diagnóstico de null/definite initialization existente | semantic/type |

El parser no debe convertir `Function<T, R>` en un generic nominal desconocido:
reconoce la intención y ofrece la forma canónica. Diagnostics de mismatch
imprimen ambas firmas mediante `format_type`, no raw `TypeId` ni LLVM types.

Un error de return significa que el `HirExpr.ty` del call fue corrompido; en
source normal el result se deriva de la firma y el uso posterior recibe el
diagnóstico ordinario de tipo esperado. Los verificadores de HIR/MIR/SSA emiten
errores de verification internos, no reciclan diagnostics source.

## 14. Qualification

La suite completa de FUNCTION-VALUES V1 debe cubrir:

### 14.1 Parsing y typing

- cero, uno y varios parámetros;
- retorno value y `void`;
- nested `Function`, containers y generic types dentro de la firma;
- aliases transparentes y nominales distintos;
- todas las formas no canónicas y delimitadores faltantes;
- `void` sólo en retorno;
- igualdad/invariancia y ausencia de widening de firmas.

### 14.2 Flujo de valores

- ref local, parámetro, return y phi/select por control flow;
- field de struct, enum payload, `Array` y `List`;
- Copy repetido sin move/use-after-move;
- función imported mediante full/selective import y alias;
- shadowing local sobre nombre de función;
- function target usado únicamente por referencia sigue emitido;
- ninguna allocation, retain, release o drop atribuible al function value.

### 14.3 Calls e IR

- `f(x)` conocido conserva `Call` directo en HIR/MIR/SSA/LLVM;
- `g(x)` con local/parámetro conserva `IndirectCall` en las tres IR;
- aridad, argumentos y return exactos;
- coerciones ordinarias de argumentos ocurren antes de MIR;
- corrupción de target/signature/callee/argument/result rechazada
  independientemente en HIR, MIR y SSA;
- phi dominance y DCE conservan callees indirectos;
- devirtualización opcional vuelve a verificar el `Call` directo.

### 14.4 ABI y unwind

- inspection de address, call e invoke sin bitcasts;
- tipos scalar, struct/value ABI ya admitidos y unit/`void`;
- call indirecta dentro y fuera de `try`, con owners vivos y `finally`;
- exception propagada, capturada y no capturada;
- trap no se convierte en unwind;
- O0/O2 equivalentes y LLVM verifier limpio;
- un word de layout en Linux x86-64.

### 14.5 Generics y rechazos

- `Function<(T), T>` se sustituye en una instancia generic concreta;
- generic types nested quedan concretos antes de MIR;
- generic function abierta se rechaza incluso con expected type;
- métodos, virtual/interface refs, constructors y builtins se rechazan con el
  diagnóstico específico;
- null y sintaxis alternativas se rechazan.

### 14.6 Newton obligatorio

`examples/newton/main.ae` es el caso E2E obligatorio. Debe demostrar:

- parsing de dos parámetros `Function<(double), double>`;
- refs directas `newton(f, df, ...)` sin convertir las calls externas a
  indirectas;
- calls `f(x)` y `df(x)` indirectas dentro de `newton`;
- calls directas a `newton`, `exp`, `abs` y output según sus rutas existentes;
- resultado numérico y residual correctos en O0/O2;
- dumps e LLVM que hagan visible la distinción direct/indirect.

## 15. Primer vertical de implementación

El primer vertical recomendado es **FUNCTION-VALUES-V1 — Newton callable
spine** y debe llegar E2E a Linux x86-64 O0/O2:

1. agregar `AstType::Function` y parsing exacto de la forma canónica;
2. agregar `TypeData::Function`, interning, formatting, layout y properties;
3. resolver referencias top-level no genéricas en posición de valor;
4. admitir parámetros y locales Function Copy;
5. distinguir call directa por declaración de call indirecta por value;
6. preservar `FunctionRef`/`IndirectCall` y verificarlos en HIR/MIR/SSA;
7. bajar address y call/invoke indirectos sin casts;
8. actualizar reachability para targets address-taken;
9. ejecutar Newton y una matriz negativa de firma/arity/syntax/unwind;
10. inspeccionar LLVM y demostrar cero lifecycle/runtime propio.

Este vertical debe incluir cero/uno/múltiples parámetros y `void` aunque Newton
sólo use unary/value return. Puede dejar tras feature gates cerrados, para
verticales inmediatos, retorno de Function y storage en aggregates/Array/List;
la arquitectura y ABI de esas formas ya quedan decididos y no requieren otro
diseño.

## 16. Decisiones diferidas, no bloqueantes

No quedan decisiones abiertas que bloqueen FUNCTION-VALUES-V1. Se difieren:

- sintaxis para referenciar una monomorphization genérica concreta;
- Optional/Nullable function values;
- igualdad, hashing o reflection de callables;
- stable/public ABI y FFI function pointers;
- static methods que prueben equivalencia con funciones libres;
- callable error contracts si un futuro modelo checked vuelve a incorporarlos
  a firmas; las exceptions unchecked actuales no forman parte del TypeId;
- `nounwind` interprocedural y devirtualización como optimizaciones;
- closures/lambdas, capture layout y su ABI `{code, environment}` eventual.

Ninguna de estas deudas permite agregar environment, null, casts de firma o
subtyping al V1 por accidente.

## 17. Fuera de scope

- closures, lambdas y funciones anidadas capturantes;
- environment pointers, heap boxes y capture ownership;
- bound/static/virtual/interface method values;
- builtins, intrinsics y constructors como valores;
- partial application, currying y variadics;
- overload sets;
- variance/subtyping de funciones y conversion thunks implícitos;
- generic function templates abiertos;
- dynamic typing, reflection y callable equality;
- C/foreign function pointers o calling conventions configurables.
