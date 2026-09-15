# BORROW-ERGONOMICS-1 — implicit shared argument borrows

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-15.

Este milestone fija una única adaptación ergonómica en límites de call: cuando
un parámetro ya resuelto espera exactamente `ref T`, un argumento que produce
exactamente `T` puede convertirse en un préstamo shared limitado a esa call.
No modifica todavía parser, resolver, HIR, MIR, SSA, backend, runtime, Core ni
STD, y no admite ningún programa nuevo hasta un vertical nativo posterior.

La decisión conserva el modelo explícito de referencias de NEXT-VERTICAL-9,
el orden izquierda→derecha y el lifecycle del
[contrato semántico](AETHER_V1_SEMANTIC_CONTRACT.md), las fronteras tipadas de
la [arquitectura del compiler](AETHER_COMPILER_ARCHITECTURE.md), los owners
`string` de [GENERAL-V1](GENERAL_V1_STRING_REPORT.md), los argumentos borrowed
de [IO-V1](IO_V1_REPORT.md) y [TEXT-V1](TEXT_V1_REPORT.md), y el precedente de
temporales/provenance de [ITERATION-V3](ITERATION_V3_REPORT.md).

## 1. Decisión resumida

Para una posición de argumento cuyo parámetro concreto es `ref T`:

```aether
T value = makeT();

f(value);           // equivalente semántico a f(&value)
f(makeT());         // owner temporal, borrow durante f, cleanup después
f(literalOfT);      // materialización semántica equivalente
```

el compiler inserta un **implicit shared argument borrow** si, y sólo si:

1. la firma concreta del candidato ya fue determinada y la selección final de
   callable es única bajo las reglas de la sección 8;
2. el parámetro es exactamente el `TypeId` canónico `ref T` shared;
3. el argumento, después de contextualizar sólo construcciones/literales aún
   no tipados, tiene exactamente el mismo `TypeId` canónico `T`;
4. no existe entre ambos una coerción, cast, conversión user-defined, Alias,
   Clone, dereference ni otra adaptación;
5. el valor puede exponerse mediante un Place existente o un temporary Place
   seguro cuyo lifetime termine con la call;
6. el contrato vigente de `ref` garantiza no escape.

El resultado del ajuste tiene tipo exacto `ref T`. Es un Borrow real, no una
conversión de tipos ni una convención sólo del backend.

La regla no se aplica a `ref mut T`, a una asignación o initializer de tipo
`ref T`, a un return, field, payload, captura, valor generic almacenado ni a
ningún contexto que no sea una posición de argumento de una call resuelta.

## 2. Regla normativa exacta

Sea `P` el tipo canónico del parámetro seleccionado y `A` la expresión fuente.
La adaptación se decide con este algoritmo:

1. Resolver el nombre/familia de call, aridad y candidatos; resolver argumentos
   generic explícitos y toda inferencia generic permitida **sin** usar implicit
   borrow.
2. Sustituir los parámetros generic y obtener el tipo concreto `P` de cada
   candidato. En las familias cerradas actuales existe una sola firma; en un
   overload set futuro, la sección 8 selecciona una antes de insertar el nodo
   definitivo.
3. Si `A` ya tiene tipo exacto `P`, pasarla sin esta adaptación. Esto incluye
   una expresión explícita `&place : ref T`.
4. Si `P` no es `ref T` shared, no intentar la regla.
5. Analizar `A` con contexto de construcción `T`. El contexto puede tipar una
   literal o construcción neutral directamente como `T`; no puede insertar
   `Coerce(T1,T)`, cast ni conversión desde un valor ya tipado `T1`.
6. Si el tipo resultante no es exactamente `T`, la adaptación no es viable.
7. Si `A` resuelve a un Place de tipo `T`, crear un borrow shared de ese Place.
8. En otro caso, materializar el resultado completo de `A` en un temporary
   Place de tipo `T`, transferir allí su obligación owning cuando corresponda,
   y crear un borrow shared de ese Place.
9. Asociar borrow y temporary, si existe, a la región de la call concreta. La
   referencia no puede usarse fuera de esa posición ni sobrevivir a ninguna
   salida de la call.

La igualdad requerida es de `TypeId` después de expandir aliases transparentes.
No hay igualdad por layout, subtyping, widening, orientación compatible,
element type, clase base, interfaz, ni identidad de spelling.

### 2.1 Contexto directo no es conversión

Una literal contextual conserva las reglas existentes. Por ejemplo, si `T` es
`int8`, una literal exacta representable puede nacer como `int8`; no nace como
`int64` para convertirse luego. Una literal string nace como `string`. Una
construcción neutral como `{...}` puede resolverse directamente al `T` esperado
si su contrato propio lo permite.

En cambio, esto no es legal por BORROW-ERGONOMICS-1:

```aether
void takesWide(ref int64 value) { ... }
int32 narrow = 7;
takesWide(narrow); // no: int32 -> int64 seguido de borrow
```

El usuario debe producir un `int64` explícito en un paso visible y luego
prestarlo, o usar una expresión explícita cuyo resultado ya sea `int64`.

### 2.2 Referencias existentes y dereference

Una expresión `ref T` pasada a un parámetro `ref T` ya es match exacto y copia
solamente el descriptor no owning existente. No se crea `ref ref T`.

Una expresión `ref T` no se adapta a un parámetro `ref U`, ni a un parámetro
`T`; no existe auto-deref. Para prestar el pointee en una call distinta sigue
siendo necesario escribir `*reference` como Place fuente cuando corresponda.

## 3. Lvalues

Para un Place addressable `p : T`, `f(p)` con parámetro `ref T` crea el mismo
borrow shared que `f(&p)`:

- el borrow apunta al storage de `p` y conserva toda su provenance hasta el
  root owning existente;
- no crea un owner, Alias, retain/release, Clone, Move, load de `T` ni copia;
- no cambia la mutabilidad del binding ni promete inmutabilidad global;
- `ref` concede sólo capacidad read al callee y no implica exclusividad ni
  LLVM `noalias`;
- el Place/root no puede moverse, reemplazarse, destruirse o sufrir una
  invalidación estructural incompatible mientras la región está activa;
- efectos permitidos por otro alias bajo el modelo vigente siguen permitidos
  si no invalidan el Place/provenance. Esta feature no fortalece `ref` hasta
  convertirlo en un préstamo exclusivo estilo Rust.

Fields, índices y dereferences ya addressable pueden actuar como el Place del
argumento si sus reglas actuales permiten formar `&place`. Esta frase no
admite guardar el reference en un field: describe únicamente el origen del
borrow de call.

El análisis debe congelar la identidad del Place en su punto de evaluación.
Índices y bases se evalúan una sola vez, en el orden fuente, antes de evaluar
argumentos posteriores. Un efecto posterior no puede hacer que el borrow cambie
retroactivamente de slot.

## 4. Rvalues y temporales

Si `A : T` no es un Place addressable, la semántica es:

```text
evaluate A
  -> initialize hidden call temporary tmp:T
  -> begin shared Borrow(tmp) as ref T
  -> evaluate remaining arguments
  -> invoke selected callee
  -> capture its normal result, if any
  -> end call borrow
  -> destroy tmp if T needs_drop
  -> continue with the captured result
```

El temporary es un root compiler-owned, address-taken, no source-visible y de
una sola inicialización. Recibe por Transfer la obligación producida por `A`;
no crea una segunda obligación y no hace Alias. Si `T` es Copy, materializar el
valor en storage sigue siendo una copia física permitida por T, no un owner
lógico adicional. Si `T` necesita Drop, existe exactamente una obligación de
cleanup en el temporary.

Un rvalue sólo es admisible si las reglas existentes permiten construir un
valor completo `T` y conservar su provenance durante la call. Materializar un
descriptor borrowed no extiende el lifetime de su backing. Un valor parcial,
movido, MaybeMoved no usable, una operación cuyo resultado no puede almacenarse
ni un descriptor cuya provenance no alcance la call deben fallar cerrados.

Esta extensión de lifetime pertenece exclusivamente al **temporary owner o
valor inmediato producido como argumento**. No extiende el lifetime de roots
prestados de los que dependa T, no crea named lifetimes y no hace que el
temporary sea retornable, que sus referencias sean almacenables ni que resulte
visible después de la call.

### 4.1 Literales string

Para:

```aether
std.File.readText("input.txt");
```

la semántica sigue siendo un owner `string` lógico prestado durante la call.
En el perfil actual el literal tiene backing inmortal, por lo que una
implementación puede prestar una celda estática inmutable del handle o eliminar
el slot de stack si demuestra equivalencia. Esa optimización:

- no elimina el Borrow de HIR/MIR/SSA;
- no crea heap allocation;
- no ejecuta retain/release físico para el literal inmortal;
- no autoriza el mismo tratamiento para un string heap temporal.

Un string heap producido por `makeString()` se transfiere al root oculto y su
Drop ordinario ocurre después de la call o durante unwind.

## 5. Región de lifetime y orden de evaluación

Cada call posee una región `CallSiteId` conceptual. Los argumentos se evalúan
una vez, estrictamente de izquierda a derecha. Para cada argumento adaptado:

- su borrow comienza después de resolver/materializar su Place;
- permanece activo durante la evaluación de todos los argumentos posteriores;
- permanece activo durante la invocación;
- en éxito termina después de capturar el resultado y antes de continuar la
  expresión que contiene la call;
- en unwind termina en el exceptional edge antes del Drop de su temporary;
- en una salida producida mientras se evalúa un argumento posterior se cierra
  antes de limpiar el temporary y propagar esa misma salida.

Esto hace inválidos casos como:

```aether
void inspect(ref string first, string second) { ... }
string text = "A";
inspect(text, consume(text)); // el primer borrow bloquea el Move posterior
```

Para varios temporales, el cleanup sigue el orden inverso de materialización.
Los borrows se cierran antes de destruir sus roots; el orden físico entre
marcadores `EndBorrow` sin efecto runtime no es observable, pero los dumps y
verificadores usan orden inverso para mantener una forma canónica.

Una referencia explícita inline `f(&value)` recibe la misma región de call. Un
binding preexistente `ref T r = &value; f(r)` conserva en cambio el lifetime
léxico de `r`; la call sólo copia el descriptor reference.

## 6. Excepciones, unwind y traps

Una call `may_unwind` mantiene al caller como owner de todo temporary prestado.
Por ello el exceptional edge debe:

1. conservar el mismo `ExceptionEvent` producido por la call o por un argumento;
2. terminar los call borrows activos;
3. destruir en orden inverso cada temporary owning ya inicializado;
4. ejecutar después los demás cleanups de scopes abandonados;
5. entregar el mismo evento al handler, `finally` o `ResumeUnwind` existente.

El temporary no se considera transferido al callee. A diferencia de un
argumento owning by-value, debe limpiarlo el caller también cuando la invocación
ya comenzó y lanzó. Si la evaluación de `A` lanza antes de publicar `tmp`, no
existe obligación de Drop para ese argumento. Si un argumento posterior lanza,
se limpian solamente los temporales anteriores que sí quedaron inicializados.

Los traps de overflow, bounds, allocation o corrupción conservan la política
abortiva vigente. No toman exceptional edge, no son capturables y no prometen
Drop de temporales. Esta feature no convierte traps en exceptions ni agrega
rollback.

## 7. Ownership, provenance y efectos

`ImplicitSharedArgumentBorrow` se clasifica exactamente como Borrow:

| Propiedad | Resultado |
|---|---|
| ownership lógico del argumento | no cambia |
| capability entregada | shared/read `ref T` |
| Alias/retain/release | ninguno |
| Move/Transfer del lvalue | ninguno |
| temporary rvalue | una Transfer hacia root oculto, sin duplicación |
| Clone/deep copy | ninguno |
| provenance | Place/root original o root oculto exacto |
| exclusividad/noalias | ninguna |
| escape | prohibido |

La query existente de efectos de calls debe observar el borrow durante toda su
región. Moves, replacements, Drop y mutaciones estructurales que puedan
invalidar el root se rechazan con la misma autoridad usada por borrows
explícitos, views, argumentos anteriores e iteración. Relaciones no demostradas
siguen fallando cerradas; BORROW-ERGONOMICS-1 no introduce un solver de alias,
MemorySSA ni comparación runtime de punteros.

El cuerpo del callee se verifica bajo la política V9: un parámetro reference no
puede retornarse, almacenarse, capturarse ni convertirse en ownership. Por
tanto el no-escape es una propiedad estática del lenguaje, no una promesa
optimista anotada por la biblioteca.

## 8. Resolución de calls y overloads

El ajuste participa en viabilidad y ranking sólo después de conocer el tipo
concreto de cada parámetro. Para una futura familia con varios candidatos, el
costo por posición es:

| Rank | Match |
|---:|---|
| 0 | tipo exacto sin ajuste, incluido `ref T` explícito |
| 1 | tipo exacto mediante implicit shared argument borrow |
| 2 | conversión ordinaria ya admitida |

Un candidato A es mejor que B si no tiene peor rank en ninguna posición y
tiene mejor rank en al menos una. Debe existir un único candidato no dominado;
si dos candidatos son incomparables o empatan, la call es ambigua. No se suman
ranks ni se usa orden de declaración.

Así, si coexistieran:

```aether
void f(T value);
void f(ref T value);
```

`f(value)` elige `f(T)` porque el match por valor es rank 0 y el borrow es rank
1. `f(&value)` elige `f(ref T)` por match exacto; no hay auto-deref que haga
viable `f(T)`.

Una conversión no puede combinarse con borrow. Por tanto `U -> T -> ref T` no
es un candidato rank 2: es inviable. Rank 2 sólo describe candidatos cuyos
parámetros por valor ya aceptan una conversión ordinaria independiente.

El compiler actual no posee overloads user-defined generales. Sus nombres
únicos, familias Core cerradas, funciones toolchain, métodos e interfaces deben
seguir su selección actual. Cada mecanismo obtiene primero su única firma
canónica y ejecuta después la adaptación compartida por posición. Este
milestone no autoriza duplicar declaraciones, agregar un overload set ni
cambiar la selección cerrada de Core/Text/Math.

## 9. Generics

La inferencia generic termina antes del implicit borrow. En particular, una
correspondencia `ref U` contra un argumento owning `T` no infiere `U = T` por
esta feature:

```aether
void inspect<U>(ref U value) { ... }
Thing x = makeThing();

inspect(x);        // no basta para inferir U
inspect<Thing>(x); // U ya es concreto; luego se inserta el borrow
```

La call inferida sí puede usar el ajuste cuando `U` fue determinado de forma
independiente por otro parámetro exacto:

```aether
void pair<U>(U tag, ref U value) { ... }
pair(x, x); // el primer argumento determina U; el segundo puede prestarse
```

No se unifica `ref U` con `U`, ni `U` con `ref U`; no se eliminan reference
layers. Constraints se comprueban sobre los type arguments ya inferidos y la
sustitución concreta produce el `ref T` que habilita el paso posterior. La
adaptación no entra en `TypeId`, `InstanceId`, mangling, capabilities ni ABI y
no crea instancias alternativas.

Los cuerpos generic conservan su contrato exacto: un parámetro `ref U` sigue
siendo reference dentro del cuerpo y un forwarding call debe probar la firma
normalmente. No existe inferencia de lifetime ni constraint Borrowable.

## 10. Representación HIR

HIR debe mostrar el ajuste como expresión reference real. La forma normativa
es equivalente a:

```text
CallScopedSharedBorrow {
    call_site: CallSiteId,
    argument_index: u32,
    pointee_type: TypeId,
    reference_type: TypeId,       // exactamente ref pointee_type
    source: Place(HirPlace)
          | Temporary(HirExpr),
    origin: Implicit,
}
```

El nombre Rust concreto puede variar. No puede representarse como `Coerce`,
`Alias`, `Move`, un bool `borrowed` en el backend ni borrarse dejando un
argumento `T` contra un parámetro `ref T`.

La expresión enclosing tiene tipo `ref T`. El verificador HIR reconstruye:

- identidad y posición dentro de la call `CallSiteId`;
- parámetro concreto exactamente `ref T` shared;
- source exactamente `T` y sin nodo de conversión envolvente;
- Place válido o initializer temporal completo;
- referencia canónica shared y ausencia de escape;
- orden de argumentos y unicidad del ajuste por posición.

La forma sólo puede aparecer como descendiente directo del slot de argumento
correspondiente. Substitution generic reemplaza pointee/reference/source y
vuelve a comprobar la igualdad; nunca transforma el nodo en inferencia.

Un `&place` explícito puede conservar el `HirExprKind::Borrow` existente, pero
al usarse inline como argumento se asocia a la misma región `CallSiteId` para
obtener lifetime equivalente. Dumps distinguen `explicit` de `implicit` por
provenance diagnóstica, no por semántica de alias.

## 11. Representación MIR

MIR materializa toda decisión implícita. Para un lvalue:

```text
arg_ref = BorrowShared(place) [call_site, argument_index]
```

Para un rvalue owning:

```text
tmp:T = <lower initializer>
register cleanup(tmp)
arg_ref:ref T = BorrowShared(tmp) [call_site, argument_index]
```

La call recibe exclusivamente operands de sus tipos de parámetro; por tanto su
operand es `ref T`, nunca `T`. `CallBorrowRegion` (o metadata estructurada
equivalente) relaciona cada `Borrow`, root temporal, call/invoke, normal edge,
unwind edge y `EndBorrow`. No es suficiente confiar en la cercanía textual de
instructions.

El verificador MIR comprueba por su propio CFG:

- evaluación izquierda→derecha y una sola evaluación por argumento;
- borrow posterior a la inicialización/address resolution y dominante a la
  call;
- ausencia de Move/Replace/Drop/invalidation incompatible en la región;
- operand/reference TypeIds exactos y call signature exacta;
- captura del resultado normal antes de `EndBorrow`/cleanup;
- `EndBorrow` en toda salida no abortiva;
- Drop inverso de cada temporary owning en normal y unwind, exactamente una vez;
- ningún Drop en el caller para owners by-value ya transferidos al callee;
- el mismo exceptional event tras el cleanup.

Los roots ocultos reutilizan locals address-taken, drop flags, landing pads y
acciones `finally` existentes. No requieren un heap box ni una nueva categoría
de ownership.

## 12. Representación SSA y LLVM

SSA conserva:

- `Borrow` shared con Place/provenance y tipo `ref T`;
- `CallSiteId`/argument index y la región call-scoped;
- memory local o storage estable del temporary;
- call versus invoke, successors normal/unwind y resultado sólo normal;
- `EndBorrow` y Drop/cleanup en cada salida no abortiva.

El verificador SSA reconstruye dominancia y usos: el reference sólo puede
alcanzar el operand de su call; ningún phi, Store, Return, aggregate, nested
call no prevista ni uso posterior a `EndBorrow` puede transportarlo. Verifica
además que el temporary domina Borrow/call, permanece initialized hasta el fin
de la región y se destruye exactamente una vez cuando corresponde. No confía
en `VerifiedMir` ni en una marca opaque de aprobación.

LLVM recibe exclusivamente SSA verificada. Baja Borrow a la dirección estable
ya seleccionada y conserva el ABI pointer existente de `ref`. `EndBorrow` no
necesita instruction runtime. Puede eliminar allocas o usar storage estático
para literals cuando escape, alias y lifetime lo permitan, pero no puede:

- pasar por valor el pointee porque el ABI espera referencia;
- inventar retain/release;
- marcar el pointer `noalias`;
- prolongar el storage después de la call;
- omitir cleanup excepcional de un temporary heap-owning.

O0/O2 deben tener idéntico ownership lógico, excepciones, traps y valores.

## 13. Diagnósticos

La implementación debe producir diagnósticos estructurados por causa. Los IDs
exactos se estabilizarán al implementar el vertical; las categorías y mensajes
requeridos son:

| Causa | Diagnóstico requerido |
|---|---|
| `U` distinto de `T` | el parámetro espera `ref T`, el argumento es `U` y el borrow implícito exige `T` exacto |
| parámetro `ref mut T` | no existe implicit mutable borrow; sugerir `&mut place` sólo si el Place es writable |
| source no addressable ni materializable | explicar si es valor parcial, estado owning inválido, storage no materializable o provenance insuficiente |
| escape | indicar que el borrow implícito termina con la call y el contrato intentaría retornarlo/guardarlo/capturarlo |
| call ambigua | listar candidatos, ranks por argumento y dónde se insertaría el borrow |
| invalidación durante argumentos | señalar el borrow anterior, el Move/Replace/mutación conflictiva y la call que delimita la región |

Un caso legal nunca debe emitir `invalid implicit conversion from string to ref
string`: no hay una implicit conversion. Dumps y notas pueden decir `implicit
shared argument borrow`.

Un mismatch ordinario conserva el diagnóstico de argumento de la familia
actual, pero con el motivo exacto. No debe sugerirse `&value` si el tipo es
distinto, el parámetro es mutable, el valor ya fue movido o formar el borrow
seguiría siendo ilegal.

## 14. Costos observables

| Caso | Costo adicional exigido por la regla |
|---|---|
| lvalue `T` | cero allocation, copia owning, Alias y ARC; sólo dirección/ABI de ref |
| literal string inmortal | cero heap y cero ARC físico; slot estático o alloca eliminable |
| temporary owning | sólo los costos de producir T y su Drop ordinario; cero owner duplicado |
| temporary Copy | storage de call conceptualmente necesario, eliminable si ABI/alias lo permiten |
| unwind | cleanup ya requerido del temporary, sin exception nueva |

La decisión no promete heap materialization. Un backend debe preferir storage
existente, stack o static seguro y puede promover/eliminar storage con prueba.
Las allocation, Alias, retain/release y Clone count de la adaptación son
exactamente cero.

## 15. Primer vertical de implementación

Se recomienda **BORROW-ERGONOMICS-V1 — exact shared call borrows** en
`compiler-next`, Linux x86-64, O0/O2, con este alcance cerrado:

1. centralizar la adaptación de argumentos después de firma concreta;
2. admitir direct functions y llamadas toolchain ordinarias con `ref string`;
3. integrar `std.File.readText(path)`, `std.File.readText("input.txt")` y
   `std.File.writeText(path, value)`;
4. integrar `std.Text.contains(text, "Aether")` y el resto de posiciones
   `ref string` ya declaradas por TEXT-V1 sin cambiar sus operaciones;
5. cubrir un lvalue `string`, literal inmortal, concat/call string temporary y
   un T Copy addressable para demostrar que la regla no es string-only;
6. conservar `f(&value)` y probar equivalencia HIR/MIR/SSA/lifecycle salvo el
   marcador de origen;
7. probar múltiples argumentos, evaluación izquierda→derecha, invalidación por
   argumento posterior y roots demostrablemente disjuntos;
8. cubrir generic explícito y generic inferido por otro parámetro, rechazando
   inferencia basada sólo en `ref U` contra `U`;
9. cubrir success, throw durante argumento posterior, unwind desde callee,
   catch/finally/return exterior y traps abortivos;
10. agregar corrupciones independientes HIR/MIR/SSA de TypeId, source kind,
    call site, argument index, missing EndBorrow, escape y cleanup;
11. medir allocation/free y ARC para demostrar cero Alias/retain adicional y
    cleanup exacto de temporales;
12. mantener fail-closed `ref mut`, conversion+borrow, assignments/returns/
    fields, auto-deref, overloads generales y toda lifetime extension externa.

El primer vertical debe reutilizar una única función de adaptación para direct,
toolchain y Text. `string_borrow_operand` puede actuar como evidencia del
comportamiento deseado, pero no debe permanecer como una excepción que borra el
tipo `ref string`: las firmas y los IR deben ver el `ref T` real.

## 16. Qualification requerida

Antes de declarar soporte:

- tests positivos y negativos de frontend con spans/causas estables;
- HIR/MIR/SSA dumps deterministas que muestren Borrow y regiones;
- tests de corrupción en las tres fronteras;
- ejecución nativa O0/O2 y equivalencia con `&` explícito;
- instrumentación de alloc/free/retain/release/drop normal y excepcional;
- LLVM inspection para pointer ABI, ausencia de noalias/ARC/heap auxiliar y
  `invoke`/landing cleanup correcto;
- regresión completa de references/views, ownership, strings, IO, Text,
  exceptions/finally, generics, iteration y mathematical borrows;
- `cargo test --workspace`, fmt, clippy con warnings denied,
  `git diff --check` y differential vigente.

## 17. Fuera de alcance

- auto-deref o deref coercions;
- implicit borrow de `ref mut T`;
- borrows implícitos en initializer/assignment/return/field/payload;
- referencias almacenadas, retornadas, capturadas o con lifetime nombrado;
- general temporary lifetime extension;
- Alias, ARC, Clone/copy owning o smart pointers;
- conversión `T -> U` seguida de borrow;
- conversión/coerción entre tipos reference;
- method receiver sugar;
- closures, async, concurrencia o escape a callbacks;
- dynamic typing, reflection o dispatch runtime de borrows;
- resolución general de overloads.

Estas exclusiones son gates semánticos. Ninguna optimización, builtin cerrado o
API STD puede legalizarlas lateralmente.
