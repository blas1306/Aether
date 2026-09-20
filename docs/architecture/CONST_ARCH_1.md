# CONST-ARCH-1 — immutable bindings

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-20.

Este milestone define bindings que se inicializan una vez y no pueden ser
reemplazados. No modifica todavía lexer, parser, AST, HIR, MIR, SSA, backend,
runtime, tests ni la superficie actualmente admitida. La implementación
pertenece a un vertical nativo posterior.

`const` califica una declaración y su storage raíz, no el `TypeId` del valor ni
la mutabilidad transitiva de aquello que el valor referencia. Tampoco significa
evaluación en compile time. La decisión se integra con el ownership, los Places,
las referencias explícitas y los cleanups ya definidos por el
[contrato semántico](AETHER_V1_SEMANTIC_CONTRACT.md) y la
[arquitectura del compiler](AETHER_COMPILER_ARCHITECTURE.md).

## 1. Decisiones resumidas

- La sintaxis V1 es `const T name = expression;` para locals y
  `const T name` para parámetros.
- Todo local const requiere initializer en la misma declaración. No existe
  declaración const sin valor ni inicialización diferida.
- El initializer puede ejecutarse en runtime, tener efectos o lanzar. `const`
  no introduce `constexpr`, `consteval`, storage estático ni folding obligatorio.
- `const` prohíbe reemplazar el binding y modificar storage inline que forme
  parte de su valor. No prohíbe mover/consumir el valor completo: ese Move
  termina su lifetime en vez de reemplazarlo.
- Un valor Copy puede leerse y copiarse normalmente desde un binding const.
- El Drop automático normal o excepcional de un owner const sigue permitido y
  es obligatorio sólo en paths donde el valor no fue movido.
- `const` es shallow. No elimina capacidades de un reference, class handle,
  collection handle o view almacenado en el binding.
- `const ref T` y `const ref mut T` son válidos. El primero conserva capacidad
  shared/read; el segundo conserva capacidad de escritura al pointee. Ninguno
  puede ser rebindeado.
- Los parámetros const son una restricción local del body. No cambian el tipo
  `Function`, ABI, mangling, calling convention, overload identity ni caller.
- `const` nunca entra en `TypeData`, `TypeId`, `InstanceId`, substitution,
  constraints, layout u object representation.
- Fields, globals/statics, catch/pattern/iteration bindings y captures const
  quedan fuera de V1 y deben fallar de forma explícita si se usa la sintaxis en
  esos contextos.

## 2. Sintaxis y gramática

`const` es una keyword reservada y un modificador de binding:

```ebnf
local-declaration = [ "const" ], type, identifier, "=", expression, ";" ;
parameter         = [ "const" ], type, identifier, [ default ] ;
default           = "=", expression ;
```

Ejemplos V1:

```aether
const int x = 5;
const double pi = 3.141592653589793;
const int n = computeN();

void inspect(const int limit, const ref Node node,
             const ref mut Counter counter) {
    // ...
}
```

El modificador aparece antes del tipo completo. Por tanto, en
`const ref mut Counter counter`, `const` califica `counter` y `ref mut Counter`
es el tipo completo del valor almacenado. No se admiten spellings como
`ref const T`, `T const x` ni `const mut T`.

`const` no es un type constructor y no puede aparecer dentro de un type
spelling, generic argument o function type:

```aether
List<const int> xs;                  // error sintáctico/semántico
Function<(const int), void> f;       // error
ref const Person r;                  // error; escribir const ref Person r
```

El parser conserva el token y su `Span` en la declaración para diagnósticos. Un
uso delante de un field o declaración global se reconoce lo suficiente para
emitir “const fields/globals are not supported in CONST-V1”, no un error remoto
o una interpretación como identificador.

## 3. Modelo: mutabilidad del binding y capacidad del valor

Cada local o parámetro source tiene exactamente una propiedad:

```text
BindingMutability := Mutable | Const
```

Esta propiedad responde únicamente qué transiciones puede realizar el binding
y su storage inline. Es ortogonal a las propiedades del valor:

| Dimensión | Ejemplo | Qué controla |
|---|---|---|
| binding | `const T x` | replacement y escritura inline de `x` |
| reference capability | `ref T` / `ref mut T` | lectura/escritura del pointee |
| handle API | `List<T>`, class handle | operaciones admitidas sobre el objeto alcanzado |
| type ownership | Copy / owner / borrowed | copia, Transfer, Drop y provenance |

No existe propagación implícita de const. Al leer `x`, el resultado sigue
teniendo exactamente `T`; no se produce `Const<T>`, un borrow shared ni un tipo
readonly. Un alias o reference obtenido con las reglas ordinarias conserva
solamente las capacidades que su propio tipo expresa.

## 4. Inicialización y lectura

Un local const se publica exactamente una vez por su declaración:

```aether
const int x = expression;
```

La evaluación sigue las reglas ordinarias:

1. se evalúa `expression` exactamente una vez;
2. si termina normalmente con el `TypeId` requerido, se inicializa el root `x`;
3. a partir de esa publicación `x` puede leerse, pero no reinicializarse;
4. si el initializer lanza, `x` nunca queda inicializado y no se ejecuta su
   Drop; se limpian sólo las obligaciones anteriores ya publicadas;
5. un trap conserva la política abortiva vigente.

No es válido:

```aether
const int x;       // error: initializer obligatorio
x = 5;             // nunca constituye la inicialización de x
```

Esto es immutable binding, no “single assignment” con definite assignment
diferido. El initializer usa el mismo expected type, conversiones permitidas,
orden, ownership y provenance que el initializer de un local mutable.

Leer un valor Copy desde un const produce la copia ordinaria. Puede leerse
repetidas veces y pasarse by value:

```aether
const int n = computeN();
useInt(n);
useInt(n);          // legal: int es Copy
```

## 5. Runtime, compile time y optimización

Es legal que un initializer sea arbitrariamente runtime:

```aether
const int x = expensiveRuntimeCall();
```

Puede leer parámetros, asignar otros bindings, reservar memoria, realizar I/O
admitido o lanzar. Sólo debe producir el tipo esperado y satisfacer las reglas
normales de efectos/ownership.

CONST-V1 no agrega:

- interpretación o evaluación obligatoria en compile time;
- reglas de “constant expression”;
- `constexpr`, `consteval` ni globals estáticos;
- readonly data sections;
- propagación constante como garantía observable.

MIR/SSA/LLVM pueden plegar o eliminar una operación cuando las optimizaciones
ordinarias prueben equivalencia. El mismo programa debe conservar semántica en
O0 y O2, incluidas evaluación única, efectos, unwind y cleanup.

## 6. Reassignment, Places y frontera shallow

### 6.1 Replacement siempre prohibido; Move permitido

Para un root const `x`, se rechaza reemplazar o reinicializar su storage:

```aether
x = replacement;       // replacement directo
```

La decisión se toma antes de bajar la operación. No se evalúa el RHS de una
asignación inválida ni los otros argumentos de una call inválida: el programa
no pasa análisis semántico.

En cambio, un Move/Transfer del valor completo es legal. Termina el lifetime
del valor almacenado; no instala otro valor ni concede una segunda
inicialización:

```aether
const string s = makeString();
consume(s);             // legal: Move del root completo
use(s);                 // error ordinario: use after move
s = makeString();       // error const: no puede reinicializarse
```

Una operación que recibe un valor Copy by value no consume el binding, aunque
la IR use un load. Por ello `consumeInt(x)` puede repetirse si `int: Copy`. Para
un owner non-Copy se aplican las transiciones ordinarias `Owned -> Moved`, los
joins `MaybeMoved`, borrow conflicts y use-after-move.

### 6.2 Storage inline

Const bloquea Stores cuyo destino pertenece físicamente al valor inline del
root sin atravesar una frontera de indirection/handle. En particular:

```aether
struct Point { int x; int y; }

const Point p = Point(1, 2);
p.x = 3;                // error: mutación de storage const inline
```

La regla se expresa sobre Places. Para una escritura a `root.projection...`, el
análisis recorre desde el root:

- mientras sólo atraviese fields de aggregates por valor, permanece dentro de
  storage const y la escritura se rechaza;
- al atravesar un dereference writable o una operación de un handle/view con
  capacidad de mutación, termina la protección del binding; se aplican desde
  allí las reglas de capacidad, borrow y aliasing del valor;
- un dereference shared sigue rechazando la escritura por “pointee is not
  writable”, independientemente de const.

Esto también bloquea reemplazar un field owning de un struct const: no puede
usarse la asignación para consumir el field viejo e instalar otro. Un Move
parcial de ese field también se rechaza: no termina el lifetime del valor raíz,
sino que dejaría el aggregate const vivo con un hueco. Sí puede moverse el
aggregate raíz completo, lo que termina todos sus fields como una sola unidad.

### 6.3 Handles y mutación interior

Class handles y collection descriptors son handles semánticos. Const conserva
la identidad almacenada en el binding, no congela el objeto o backing storage:

```aether
const Person p = makePerson();
p.rename("Ada");        // legal si Person/API da capacidad de mutación

const List<int> xs = makeList();
xs.push(1);              // legal
xs[0] = 2;               // legal si la operación ordinaria es writable
xs = other;              // error: replacement del binding
```

Las operaciones de List pueden actualizar length/capacity/pointer del
descriptor físico durante lowering. Semánticamente son mutación a través del
handle y están permitidas; no son replacement source del binding. Los
verificadores deben reconocer las operaciones tipadas `ListPush`, `Reserve`,
`SetLength`, `Take`, relocation y equivalentes como protocolos internos de una
operación handle admitida, no como permiso general para emitir `Assign(xs, ...)`.

La misma regla aplica a Buffer, Array, Matrix, views y futuros handles según
las capacidades que ya exponga cada tipo. Const no concede una capacidad que el
tipo no tenía, no relaja borrows vivos y no convierte un handle shared en
writable. Para un aggregate puramente by-value no existe frontera de handle:
sus fields permanecen protegidos.

## 7. `ref` y `ref mut`

Ambas combinaciones se admiten:

```aether
Person a = makePerson();
Person b = makePerson();

const ref Person r = &a;
r = &b;                  // error: el binding r es const
// escritura a *r        // error distinto: ref Person es shared/read

const ref mut Person w = &mut a;
w = &mut b;              // error: el binding w es const
w.name = "Ada";          // legal: escribe a través de ref mut
```

Si la sintaxis vigente exige `(*w).name`, se usa ese spelling; CONST-V1 no
agrega auto-deref. La semántica es idéntica: el Store tiene base
`Dereference { mutable: true }`, no base local `w`.

Formar borrows desde un root const sigue estas reglas:

- `&x : ref T` es legal mientras T/Place sea borrowable;
- `&mut x : ref mut T` se rechaza cuando expondría el storage inline const;
- leer un `ref mut T` guardado en un binding const conserva el descriptor y su
  write capability; const no lo degrada a `ref T`;
- los lifetimes, provenance, no-escape e invalidación son los ordinarios.

Así se distingue “binding `w` is const” de “pointee is not writable”. Const no
promete exclusividad y no autoriza LLVM `noalias`.

## 8. Ownership, Move y cleanup

Un const owner sigue siendo un owner normal. Adquiere exactamente una
obligación al inicializarse. Esa obligación termina exactamente una vez por
Move/Transfer del root completo o por Drop al final del lifetime si el valor no
fue movido.

La política V1 separa explícitamente Write de Move:

```aether
const string s = makeString();
inspect(&s);             // legal: Borrow shared
consume(s);              // legal: transfiere ownership y deja s Moved

const string result = compute();
return result;           // legal: transfiere ownership al caller
```

Move no escribe el storage ni crea un valor de reemplazo: consume la obligación
owning existente y termina el lifetime del valor. Por tanto, const no lo
prohíbe. No se inserta Clone, Alias o retain; calls owning, returns, construcción
de aggregates/collections, payloads y otras operaciones consumidoras reciben
la misma Transfer que desde un binding mutable.

Después del Move, todo uso del valor falla por el análisis normal de estado
`Moved`/`MaybeMoved`. Además, aunque un modelo futuro permitiera reinicializar
un local mutable movido, const continúa prohibiendo `s = other`: la declaración
tiene una única inicialización y Move no vuelve a abrirla.

Se distinguen las operaciones:

| Operación | Desde const |
|---|---|
| Copy de un valor `Copy` | permitida |
| Borrow compatible | permitido |
| Move/Transfer/consume del root completo | permitido; deja el valor Moved |
| Move parcial de un field inline | prohibido; dejaría storage parcial |
| Write/replacement/reinitialization | prohibido |
| Drop automático del compiler | permitido sólo si el valor sigue Owned |

Drop no es una expresión source ni deja un binding usable: finaliza su lifetime
en una salida de scope. Se permite tanto en cleanup normal como en unwind,
`catch`/`finally` y drop flags. Una excepción durante el initializer no publica
el owner; una excepción posterior ejecuta su cleanup en el orden inverso
ordinario sólo en paths donde el root continúa Owned, sin double Drop ni
reemplazar el `ExceptionEvent` original. Los drop flags y estados de ownership
ordinarios distinguen paths Owned, Moved y MaybeMoved; const no crea un estado
nuevo.

Un borrow activo continúa bloqueando un Move incompatible hasta que termina.
Una operación handle que sólo muta el objeto alcanzado mantiene la obligación
owning en el root y se rige por la frontera shallow de la sección 6.

## 9. Parámetros

Los parámetros const se admiten en V1 porque expresan y verifican una propiedad
útil dentro del body:

```aether
void f(const int x) {
    x = 2;               // error
}
```

El caller sigue pasando exactamente `int`. Las firmas conservan el tipo
canónico `Function<(int), void>` y el prototype físico existente. Const se
conserva sólo como metadata de `ParameterSignature`/binding para analizar el
body; se excluye explícitamente de:

- lookup y overload identity;
- `Function` value compatibility;
- generic inference/substitution;
- symbol keys, mangling y dispatch;
- ABI, calling convention y parameter layout.

No pueden coexistir dos funciones diferenciadas sólo por const. Si el sistema
declarativo las considera el mismo símbolo, se diagnostica duplicate function.

Un parámetro owning const puede moverse, retornarse o consumirse desde el body.
Si permanece Owned, su cleanup físico conserva la convención ordinaria; si fue
movido, no se vuelve a destruir y cualquier uso posterior falla normalmente.
No puede reasignarse ni reinicializarse después del Move. Un parámetro Copy se
usa normalmente. En `const ref T x` y `const ref mut T x`, la regla de la
sección 7 permanece intacta.

Los defaults, si existen, pertenecen a la declaración/call y producen el mismo
tipo de parámetro; const no cambia dónde ni cuándo se evalúan, ni forma parte de
la receta del default.

## 10. Generics

Esto es válido sin constraints nuevos:

```aether
T keep<T>(T input) {
    const T value = input;
    // ...
}
```

La validez concreta de `input` como initializer sigue el ownership normal: si
la operación requiere mover `input`, éste debe ser movible. Después de la
inicialización, los usos de `value` dependen de las capacidades ya demostradas:

- con `T: Copy`, puede copiarse;
- siempre puede prestarse cuando la regla ordinary de borrow lo permita;
- puede consumirse si la instancia concreta es owning/non-Copy, tras lo cual
  queda Moved y no puede reinicializarse;
- sus APIs/handles conservan sus capacidades normales.

`BindingMutability` no participa en `Substitution` ni genera instancias
distintas. `const T` no es un type spelling, no añade un capability constraint
y no afecta `TypeId`, `InstanceId`, cache de monomorfización ni mangling.

## 11. Fields, globals y otros bindings

Fields const se reservan para un vertical posterior. Su contrato futuro queda
preparado, pero no admitido:

```aether
struct Config {
    const int version;   // no soportado en V1
    string name;
}
```

La futura regla será: inicialización obligatoria por literal/constructor antes
de publicar el aggregate, ningún replacement posterior, protección del storage
inline, Drop normal si aplica y layout/field type idénticos al field mutable.
Const será metadata de `FieldInfo`, no parte del `TypeId` del field ni del
layout. La construcción parcial, constructors y assignability necesitan su
propio vertical antes de habilitarla.

Globals y statics const también quedan fuera. No se reutilizará `const` como
sinónimo de compile-time constant, readonly segment o singleton. Requieren una
decisión separada sobre inicialización, orden entre módulos y teardown.

Catch bindings, match payload bindings, loop iteration bindings, implicit
`this`, temporales compiler-owned y captures no aceptan un modificador const en
V1. Sus reglas actuales no cambian. Una extensión futura deberá decidir cada
clase explícitamente; no heredará const por accidente.

## 12. Representación por fase

### 12.1 Lexer, AST y declaración semántica

El lexer agrega `KwConst`. AST agrega `mutability: BindingMutability` y el span
del modificador a `AstStmtKind::Local` y `AstParameter`; no modifica `AstType`.
El initializer local continúa siendo obligatorio en la forma AST.

HIR define un enum común, conceptualmente:

```rust
enum BindingMutability { Mutable, Const }
```

`HirLocal` y `HirParameter` lo conservan. `ParameterSignature` lo conserva para
el análisis del body, pero las claves de firma y los tipos de función lo ignoran.
El resolver centraliza una consulta `place_access(place)` que obtiene:

- root y mutabilidad del binding;
- si la proyección sigue en storage inline o cruzó una frontera writable;
- capacidad de reference/view/handle;
- modo requerido: Read, BorrowShared, BorrowMutable, Write, Move o CleanupDrop.

HIR rechaza Write y BorrowMutable sobre storage inline const, pero admite Move
del root completo y aplica la transición owning ordinaria. Rechaza Move de una
proyección inline que deje el aggregate parcialmente movido. Su verificador
repite por separado la regla de Write y la de Move sobre HIR ya tipada, incluida
la clasificación de operaciones handle y el initializer único.

### 12.2 MIR

`MirLocal` y `MirParameter` conservan `BindingMutability` y origen source versus
temporary compiler-owned. No se crea un `TypeData::Const<T>` ni una variante de
Rvalue const.

El verificador MIR exige para cada root source const:

- una única inicialización dominadora (o entrada de función para parámetro);
- ningún `Assign`/Store source posterior al root o proyección inline;
- ningún borrow mutable del storage inline;
- un `Move`/Transfer del root completo puede transicionar `Owned -> Moved` una
  vez por path, sin autorizar Store/reinicialización posterior;
- ningún Move parcial desde una proyección inline const;
- ningún uso posterior en estado Moved y las reglas ordinarias en MaybeMoved;
- operaciones handle sólo mediante opcodes/protocolos tipados permitidos;
- Drop sólo para paths donde el root continúa Owned, con flags y unwind
  ordinarios; nunca después de Transfer en el mismo path.

Stores auxiliares generados por un protocolo List permitido se enlazan a la
operación semántica mediante metadata existente/nueva; un Store desnudo al root
no puede justificarse por parecerse a su lowering.

### 12.3 SSA

SSA mantiene una tabla mínima de bindings source (`LocalId`, mutabilidad, tipo,
parámetro/local y root/provenance) incluso si mem2reg convierte el valor en SSA
puro. Para memory locals conserva la misma marca. La inicialización produce la
única versión source; Move puede consumir esa versión, pero no se modela una
segunda versión por reinicialización o reassignment.

El verificador SSA reconstruye:

- definición única y dominancia de la inicialización;
- ausencia de Store/redefinition sobre storage inline const;
- consumo como máximo una vez por path del owner const en calls, returns,
  aggregates u ops, con la misma validez que para un owner mutable;
- ausencia de uso posterior al consumo y tratamiento ordinario de joins
  `MaybeMoved`;
- ausencia de Move parcial desde fields inline const;
- distinción entre Write/redefinition, Move terminal y Drop final;
- legitimidad de mutaciones a través de dereference/handle y sus capacidades;
- cleanup normal/excepcional exactamente una vez sólo si el owner no fue
  transferido en ese path.

La metadata puede desaparecer sólo después de `verify_ssa` y antes/durante el
backend, nunca antes de los corruption tests. Optimización no puede usar const
como prueba de que el pointee, heap u objeto no cambia.

### 12.4 Backend

LLVM recibe los mismos tipos y layouts. Puede aprovechar SSA verificada para
eliminar slots o stores redundantes, pero no coloca automáticamente el valor en
memoria readonly, no añade `constant`, `readonly`, `noalias` ni `invariant.load`
y no cambia ARC/Drop. Esas propiedades requerirían pruebas independientes más
fuertes que immutable binding.

## 13. Diagnósticos

Los diagnósticos son estructurados, apuntan al uso inválido y añaden una nota a
la declaración const cuando ayude:

| Caso | Mensaje base requerido |
|---|---|
| local sin initializer | `const local 'x' requires an initializer` |
| reassignment | `cannot assign to const binding 'x'` |
| field inline | `cannot mutate storage of const binding 'p'` |
| borrow mutable inline | `cannot mutably borrow const storage 'x'` |
| Move parcial de field inline | `cannot partially move from const storage 'p'` |
| uso posterior a Move | diagnóstico ordinario `use of moved value 's'` |
| reassignment posterior a Move | `cannot assign to const binding 's'` |
| contexto fuera de V1 | `const fields/globals/... are not supported in CONST-V1` |
| spelling inválido | ``const` must precede the complete binding type` |

Un intento de escribir a través de `ref T` shared debe seguir diciendo que el
pointee/reference no es writable, aunque el binding reference también sea
const. Si se intenta reemplazar el descriptor reference, el mensaje dice que el
binding es const. Si ambos motivos son posibles, se diagnostica el primero que
corresponde a la operación source concreta, no una mezcla de ambos.

Los errores de tipo del initializer conservan su diagnóstico ordinario con una
nota del tipo esperado. Nunca se diagnostica que una call runtime “is not a
constant expression”, porque esa condición no existe.

## 14. ABI, layout e identidad

Para toda `T`, `const T x` y `T x` almacenan exactamente el mismo T:

| Propiedad | Efecto de const |
|---|---|
| `TypeId` / `TypeData` | ninguno |
| `InstanceId` / monomorfización | ninguno |
| tamaño, alineación, field offsets | ninguno |
| function type / overload identity | ninguno |
| symbol key / mangling | ninguno |
| ABI / calling convention | ninguno |
| object representation | ninguno |
| Drop glue | mismo glue y orden |
| pointee/handle capabilities | ninguno |

Los dumps deben mostrar const en metadata de bindings para auditabilidad, no
en el formato del tipo. Fixtures gemelos mutable/const deben demostrar el mismo
prototype LLVM y el mismo `size_of`/layout; diferencias de instrucciones por
optimización son aceptables si preservan efectos y cleanup.

## 15. Primer vertical: CONST-V1

El primer vertical debe implementar de extremo a extremo locals y parámetros:

1. `KwConst`, parsing y recuperación de errores;
2. metadata AST/HIR/signature sin contaminar tipos;
3. initializer obligatorio y runtime;
4. lectura/copia, reassignment y storage inline;
5. `const ref T` y `const ref mut T`;
6. owner const: Borrow y Move/consume permitidos, use-after-move ordinario y
   Drop sólo cuando permanece Owned;
7. class/collection handle mutation permitida versus replacement prohibido;
8. generics y monomorfización sin identidad nueva;
9. metadata/verificación HIR, MIR y SSA, incluidos corruption tests;
10. cleanup normal, return, throw, catch/finally y unwind;
11. ejecución O0/O2 y comparación de ABI/layout mutable versus const.

La qualification mínima incluye:

- local scalar, initializer literal y runtime, lecturas repetidas;
- initializer que lanza antes de publicación;
- reassignment y mutable borrow rechazados;
- struct value field mutation rechazada;
- Copy by-value permitido;
- string/Buffer/List/class owner const limpiado una vez si permanece Owned;
- consume/return/aggregate Move de root completo permitidos y sin double Drop;
- use-after-move y reassignment después del Move rechazados por motivos
  distintos;
- Move parcial de field inline const rechazado;
- borrow shared de owner const;
- ambas combinaciones const con ref/ref mut y mensajes diferenciados;
- mutación a través de `ref mut`, class handle y List permitida;
- List replacement rechazado, con push/index/reserve y borrow conflicts
  ordinarios preservados;
- parámetros const Copy, owning, `ref` y `ref mut`, incluidos defaults;
- `const T` generic con instancias Copy y owning;
- paths normales y excepcionales, drop flags, traps, O0/O2;
- dumps estables y corrupciones en cada frontera;
- mismo TypeId, InstanceId, layout, prototype y mangling.

La implementación debe ser fail-closed: ningún frontend parcial puede aceptar
source const hasta que HIR, MIR, SSA, backend, ownership, unwind, diagnósticos y
qualification estén completos.

## 16. Fuera de scope y decisiones abiertas

Quedan fuera de CONST-V1:

- fields const y su inicialización en constructors/literals;
- globals/statics y orden de inicialización/teardown;
- catch, match, iteration y capture bindings const;
- definite assignment tardío o declaración sin initializer;
- compile-time evaluation, constexpr y consteval;
- deep/transitive const, immutable object types y frozen collections;
- thread-safety, race freedom o exclusividad;
- readonly memory placement y constant propagation como semántica;
- overloads, mangling o TypeId basados en const;
- reglas nuevas de nullable, smart pointers o closures.

No queda ninguna decisión semántica abierta dentro del alcance de locals y
parámetros V1. Los verticales de fields y globals deberán conservar la
separación binding/value fijada aquí, pero decidirán sus mecanismos de
inicialización y lifecycle antes de habilitar sintaxis.
