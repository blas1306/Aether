# CLASS-HANDLE-REFERENCES-ARCH-1 — shared borrows de class handles

Estado: **CLOSED COMO ARQUITECTURA; NO IMPLEMENTADO**, 2026-10-20.

Este milestone cierra exclusivamente la semántica de `ref C` cuando `C` es
una class. No modifica todavía parser, resolución, HIR, MIR, SSA, LLVM,
runtime, std, graphics ni tests ejecutables. Ningún programa nuevo queda
admitido hasta completar y calificar **CLASS-HANDLE-REFERENCES-V1**.

La decisión reutiliza:

- las referencias non-owning y no-escape de NEXT-VERTICAL-9;
- las regiones de call, temporales y `EndBorrow` de
  [BORROW-ERGONOMICS-V1](BORROW_ERGONOMICS_V1_REPORT.md);
- class identity, `Alias`/Transfer, ARC y receivers de
  [OOP-V1](OOP_V1_REPORT.md);
- interfaces e inheritance de [OOP-V2](OOP_V2_REPORT.md) y
  [OOP-V3](OOP_V3_REPORT.md);
- nullability de [NULLABLE-V1](NULLABLE_V1_REPORT.md);
- unwind de EXCEPTION-V1..V4; y
- la exclusión de interior borrows fijada por
  [CLASS-BUFFER-FIELDS-ARCH-1](CLASS_BUFFER_FIELDS_ARCH_1.md).

La motivación inmediata es permitir APIs generales como:

```aether
public string render(ref Scene scene);
```

pero la feature no conoce `graphics`, `Scene`, SVG ni ningún package concreto.

## 1. Decisión resumida

Para una class concreta `C`:

```aether
void inspect(ref C value) { ... }

C owner = C(...);
inspect(owner);       // borrow implícito call-scoped vigente
inspect(&owner);      // forma explícita equivalente
```

`ref C` es un **shared borrow del valor class handle** almacenado en un Place.
El borrow concede una vista non-owning y read-capable de la misma identidad
dinámica. No es un owner, un `Alias`, una copia del objeto ni un préstamo del
payload interior.

Durante la región:

- el caller conserva exactamente su obligación strong original;
- el source handle no se mueve, reemplaza ni destruye;
- el objeto permanece vivo por esa obligación original;
- formar, pasar y terminar el borrow agrega exactamente cero retain/release;
- el callee no puede convertir la vista en ownership;
- un receiver derivado del borrow sólo puede usar métodos read;
- el borrow no puede almacenarse, retornarse ni escapar según V9; y
- finalizar el borrow no ejecuta Drop sobre `C`.

La representación semántica conserva Place, provenance y owner anchor. La
representación física preferida pasa el mismo object pointer del class handle,
sin pointer wrapper, heap box ni ARC adicional.

## 2. Distinción normativa: handle borrow versus interior borrow

Estas operaciones son distintas:

```aether
ref Scene scene_ref = &scene;
ref Buffer<Command> commands_ref = &scene.commands;
```

La primera presta el **handle value** de `scene`. Conceptualmente, el Place
source contiene un slot owning y una obligación que mantiene viva la identidad
alcanzada. El callee recibe capacidad read sobre esa identidad, no acceso
writable al slot.

La segunda intenta prestar storage dentro del payload heap. Continúa fuera.
Aunque el objeto se mantuviera vivo, otro `Alias` podría reemplazar
`commands`, destruir su backing anterior y dejar un interior reference o View
colgante. Un keepalive del objeto no es un pin del field ni de su backing.

Por tanto este milestone admite únicamente la frontera:

```text
owning handle Place --shared borrow/owner anchor--> borrowed handle view
```

y no admite:

```text
object pointer --field/index projection--> interior source-visible reference
```

La dirección del object pointer puede ser estable durante la vida del objeto;
eso no vuelve estables sus fields reemplazables. No se agrega pinning, backing
refcount, exclusividad, freeze profundo ni disciplina de reallocation.

## 3. Superficie source y regla exacta

### 3.1 Formas admitidas

CLASS-HANDLE-REFERENCES-V1 debe admitir `ref C` shared cuando el pointee
canónico es exactamente una class handle concreta, incluido un alias de tipo
transparente que canonicaliza a esa misma class.

Los orígenes V1 son:

- un local owning inicializado `C`;
- un parámetro owning `C` dentro de su callee;
- un temporary owner materializado por BORROW-ERGONOMICS-V1 durante una call;
- una dereference/reborrow shared ya válida cuya provenance termina en uno de
  esos roots; y
- las composiciones nullable cerradas en la sección 8.

Class fields que almacenen handles, globals/statics, captures y otros storage
kinds no admitidos por OOP vigente no se habilitan lateralmente.

La sintaxis permanece la general:

```aether
ref C r = &owner;
f(&owner);
f(owner);             // sólo adaptación shared exacta de call ya existente
f(r);                 // forwarding del reference existente
(*r).readMethod();    // dereference explícito; no se agrega auto-deref
```

No se agrega keyword, borrow operator, class-specific parameter mode ni
receiver spelling nuevo.

### 3.2 Predicado de admisión

El gate actual `contains_class(pointee) -> E0406` es demasiado amplio. El
vertical debe reemplazarlo por una clasificación positiva, no por quitar el
check globalmente:

| Pointee canónico | `ref` shared V1 | Motivo |
|---|---:|---|
| `C` class concreta | sí | objetivo del milestone |
| `C?` | sí, con sección 8 | storage nullable de un class handle |
| interface `I` | no | carrier/lifetime distinto; sección 10 |
| struct/enum/container que contiene class | no | no es un class-handle slot directo |
| token interno de constructor/receiver/keepalive | no | no es source type |
| field o element proyectado desde object payload | no | interior borrow |

El hecho de que `contains_class(T)` sea verdadero no basta para admitir T. El
predicado debe distinguir class handle directo, nullable directo e inclusión
transitiva.

### 3.3 `ref mut`

`ref mut C` y `ref mut C?` quedan explícitamente fuera de V1. Admitirlos
permitiría reemplazar el handle slot y reabre invariance, assignment ordering,
ARC del valor anterior/nuevo, overlap con shared refs y source-place mutation.
Nada en este documento permite inferirlos a partir de `ref C`.

El diagnóstico debe decir que sólo shared class-handle references están
admitidas; no debe sugerir que `&mut` funcionará en este vertical.

## 4. Semántica de valor borrowed y no-escape

Una expresión obtenida al dereferenciar `ref C` tiene tipo nominal observado
`C`, pero su **use category es BorrowedHandle**, no owning `C`.

Esto es esencial porque el `TypeId` nominal por sí solo no autoriza ownership.
Los usos permitidos consumen la vista borrowed directamente. No se materializa
primero un owner `C`.

Son válidos:

```aether
(*r).readMethod();
int n = (*r).publicCopyField;
bool same = *r == other;
forward(r);                 // forward espera ref C
```

si cada operación ya existe para C, respeta visibility y requiere sólo
capacidad read.

Son inválidos:

```aether
C x = *r;                   // produciría owner sin Alias/retain
consumeByValue(*r);         // idem
return *r;                  // ownership o borrow escapado
return r;
store.refField = r;
(*r).mutMethod();
(*r).owningField;           // extracción de owner
&(*r).field;
&(*r).bufferField[0];
move(*r);
```

Un public field Copy puede leerse por valor mediante el `FieldRead` existente.
Un field owning no puede extraerse. Formar `HirPlaceBase::ClassField` para un
borrow source-visible continúa rechazado aun si el root llegó por `ref C`.

References conservan la política V9: son Copy como descriptores non-owning,
pero copiar/forwardear el descriptor no copia ownership ni prolonga la región
de su root. Un forwarding `ref C -> ref C` preserva provenance y owner anchor;
no crea ARC ni necesita un owner nuevo.

## 5. Place, provenance y owner anchor

### 5.1 El source sigue siendo un Place

`&owner` y el ajuste implícito de `owner` resuelven primero un `HirPlace` de
tipo exacto `C` o `C?`. Ese Place identifica:

- root local/parámetro/temporary;
- slot lógico que contiene el handle;
- TypeId nominal exacto;
- estado initialized/Owned;
- región de borrow; y
- la obligación owning que actúa como anchor.

Para `ref C`, el borrow carga o proyecta el **valor non-null del handle** una
vez al comenzar la región, pero no consume el slot. Mientras la región está
activa el root anchor no puede moverse, reemplazarse, dropearse ni quedar
MaybeMoved. Esta estabilidad permite que LLVM pase directamente el object
pointer sin conservar un `C**`. `ref C?` conserva en cambio la dirección
non-null de su slot nullable por la razón de representación de la sección 14.

Esta especialización física no borra el Place semántico. HIR/MIR/SSA deben
seguir pudiendo demostrar qué owner mantiene vivo el objeto. Un pointer sin
provenance y una anotación optimista de lifetime no son una implementación
válida.

### 5.2 Owner/root anchor

El anchor de `ref C` es una obligación **prestada**, no una strong obligation
adicional:

```text
OwnerToken(owner_slot, object)
  + BeginBorrow(owner_slot)
  -> BorrowAnchor(borrow_id, owner_token, object)
```

`BorrowAnchor`:

- no incrementa ni decrementa strong count;
- no puede separarse del reference ni entrar en un aggregate;
- impide consumir/reemplazar el owner token source durante la región;
- prueba que el pointer corresponde al objeto mantenido vivo por ese token;
- puede respaldar reborrows/nested calls dentro de la región; y
- termina con `EndBorrow`, sin Drop de C.

Para `ref C?`, el anchor primario es el root/storage inicializado del container
nullable. Si está present, incluye además su obligación owning condicional; si
está null, no inventa un owner/object token y sólo inmoviliza el slot hasta
`EndBorrow`. Ambos casos usan el mismo `BorrowId` y cero ARC.

Para un temporary call-scoped, el temporary recibe por Transfer la única
obligación owning; `EndBorrow` ocurre antes de su Drop normal o excepcional.
No hay Alias intermedio.

### 5.3 Dos borrows y aliases externos

Dos shared borrows simultáneos al mismo slot son válidos. El ledger puede
tener varios `BorrowId` anclados al mismo owner token; ninguno altera ARC.

Un borrow desde dos owning aliases distintos también es válido. Cada borrow se
ancla al owner exacto que fue su source, aunque ambos pointers identifiquen el
mismo objeto.

La class puede tener otros aliases strong que muten el objeto. `ref C` no hace
al objeto profundamente immutable y no demuestra ausencia de mutación externa.
Sólo prohíbe escribir mediante esa capability y protege su owner source contra
operaciones que invalidarían el anchor. Rebind/drop de otro alias no invalida
el borrow mientras el owner source permanezca vivo.

## 6. ARC y costos normativos

La decisión es **cero ARC adicional** por class-handle borrow.

Para:

```aether
void f(ref C value) {
    (*value).readMethod();
}

C c = C(...);
f(c);
```

el schedule lógico es:

```text
construct c                 owner count = 1
BeginBorrow(c)              owner count = 1
enter f                     owner count = 1
BorrowedReceiver(*value)    owner count = 1
read method call            owner count = 1
leave f                     owner count = 1
EndBorrow(c)                owner count = 1
later Drop(c)               owner count = 0; destroy
```

En particular no aparecen `HandleAlias`, `ReceiverKeepalive` owning,
retain/release ni Drop del borrowed value. Esta regla es normativa en O0 y O2;
no basta emitir el par en O0 y confiar en que O2 lo elimine.

El receiver keepalive conservador vigente existe porque una call ordinaria
desde un handle owning puede evaluar argumentos que reemplacen el slot antes
de invocar. Un receiver derivado de `ref C` usa en cambio el `BorrowAnchor`
activo: el source owner está probado estable por toda la región exterior. Por
eso debe bajar como **BorrowedReceiver**, no como `ReceiverKeepalive` con
retain/release.

ARC que una operación distinta requiera sigue siendo observable. Por ejemplo,
crear deliberadamente `C alias = owner`, pasar otro argumento owning por valor
o retornar un owning handle conserva sus `Alias`/retain normales. La
qualification debe aislar el delta atribuible al borrow.

## 7. Receiver operations y dispatch

### 7.1 Adaptación a receiver

`(*r).method(args)` evalúa `r` una vez y crea un token interno
`BorrowedReceiver` read-only enlazado al `BorrowId`. No crea un source-visible
handle ni una strong obligation.

Después de esa adaptación se reutiliza exactamente el pipeline OOP vigente:

- resolución nominal/visibility ordinaria;
- `DirectMethodCall` para método non-virtual;
- `VirtualCall` y `VirtualSlotId` para método open;
- misma firma de argumentos/result ownership;
- misma evaluación izquierda→derecha; y
- mismo target directo/devirtualizado sólo con las pruebas ya existentes.

No existe un segundo protocolo de lookup/dispatch para borrows. El único hecho
nuevo es el modo de lifetime del receiver operand.

### 7.2 Capability

El token es siempre read. Un método declarado `mut` falla antes de lowering.
Un método read no es pure: puede lanzar, asignar a storage no derivado del
receiver o observar mutaciones hechas por otros aliases según las reglas
vigentes. No se infieren `readonly`, `readnone`, `noalias` ni memoization.

El `BorrowedReceiver` es válido durante la call de método y está dominado por
el borrow exterior. No puede guardarse, retornarse, entrar en phi arbitrario ni
usarse después de `EndBorrow`.

### 7.3 Fields, igualdad y consultas

`FieldRead` acepta el receiver borrowed sólo para fields Copy y con visibility
ordinaria. `IdentityEq` puede comparar una vista borrowed con otra vista o con
un handle owning compatible sin crear Alias. Compara object identity, nunca el
slot, refcount, descriptor o payload.

No se exponen dirección, strong count, descriptor ni metadata adicional.

## 8. Nullability

Classes actuales son non-null por defecto y `C?` existe como nullable distinto
con null-pointer niche. El milestone no cambia esas reglas.

### 8.1 `ref C`

Es un reference non-null a un class handle non-null. Comenzar el borrow prueba
un owner `C` inicializado y un object pointer válido. No hay null check nuevo.

### 8.2 `ref C?`

Es un reference non-null a un **valor nullable class handle**. Puede formarse
desde un Place `C?` bajo las reglas ordinarias:

```aether
C? maybe = ...;
ref C? slot = &maybe;
```

El borrow no prueba que el payload esté presente. Si es null no hay object
owner que invocar; si está presente, el owner condicional del container actúa
como anchor y no se retiene. Se permiten únicamente operaciones nullable ya
tipables, por ejemplo observar/comparar `*slot` con `null` y forwardear `slot`
a otro `ref C?`.

NULLABLE-V1 no mantiene un refinement persistente para `*slot`, porque es una
projection potencialmente aliased. Este milestone no agrega uno, no introduce
force unwrap/safe navigation y no permite llamar un método de C sin obtener C
por una regla nullable independiente ya admitida.

### 8.3 Otras composiciones

`(ref C)?` conserva, si se usa, la composición general ya definida por
NULLABLE-V1: ausencia del reference versus reference presente con su provenance.
No recibe operaciones especiales ni lifetime extension. Su valor presente
debe seguir anclado a un owner vivo y no puede escapar.

`ref mut C?` y `(ref mut C)?` permanecen fuera por la exclusión de `ref mut`.
No se agregan nullable nested, coercions nuevas ni cambios de layout.

## 9. Inheritance

Un `ref Derived` conserva la identidad dinámica del mismo complete object.

- `(*derived_ref).baseReadMethod()` usa el lookup efectivo vigente y dispatch
  directo/virtual ordinario.
- Un open method declarado en Base conserva virtual dispatch y alcanza el
  override de la clase dinámica.
- `base.method` mantiene su significado especial sólo dentro de method bodies;
  un class reference no crea una nueva forma de base call.

Se admite una conversión estrecha **BorrowedClassUpcast**:

```text
ref Derived -> ref Base
```

sólo si existe la relación owning `Derived -> Base`, es accesible y el path
nominal ya es válido. Conserva pointer, identidad dinámica, `BorrowId`, anchor y
capability shared; no hace Alias, retain, slicing, field copy ni allocation.

Esto no es variance general de `ref T`. Sólo aplica a class handles shared. No
aplica a `ref mut`, aggregates, interfaces ni types de igual layout. Los
verificadores reconstruyen el base path exacto.

BORROW-ERGONOMICS-V1 continúa prohibiendo conversion+borrow en un solo ajuste:
un argumento owning `Derived` no se convierte implícitamente a `Base` para
luego formar `ref Base`. Primero debe existir un `ref Derived` válido y la
adaptación ref-to-ref se representa explícitamente en HIR, o el API debe pedir
el tipo exacto. Este milestone no cambia ranking ni inference.

## 10. Interfaces

`ref InterfaceHandle` queda **fuera de CLASS-HANDLE-REFERENCES-V1**.

Una class handle concreta es un pointer. El carrier interface vigente es el
par owning `{object pointer, witness pointer}` y posee una strong obligation.
Prestarlo exige cerrar simultáneamente:

- si se presta el carrier slot o una snapshot de ambos words;
- cómo se ancla object y witness a través de rebind/unwind;
- ABI de reference al carrier frente a pointer pair by value;
- nullable tagged interface layout;
- interface-to-parent borrowed adaptation; y
- ReceiverBorrow para `InterfaceCall` sin retain.

Nada de eso es necesario para class refs ni debe forzarlas a usar un fat
pointer. `ref I`, `ref I?` y class-to-`ref I` fallan con diagnóstico explícito
de feature no admitida, no con una afirmación falsa sobre class handles.

El futuro milestone de interface borrows podrá reutilizar `BorrowAnchor`, pero
deberá calificar su carrier y witness por separado.

## 11. HIR

HIR debe conservar el `TypeId` source `ref C`/`ref C?` real y el Place exacto.
La forma existente de `Borrow`/`CallScopedSharedBorrow` se extiende con una
clasificación de anchor; no se representa como `HandleAlias`, `Coerce`,
`ClassUpcast` owning ni bool backend-only.

Forma conceptual:

```text
ClassHandleBorrow {
    borrow_id: BorrowId,
    place: HirPlace<C | C?>,
    reference_type: ref C | ref C?,
    anchor: OwnerPlace(root, owner_state)
          | NullableSlot(root, presence_state),
    region: LexicalScope | CallSite(call_site, argument_index),
    origin: Explicit | Implicit,
}
```

No es obligatorio agregar un enum separado si `Borrow` expresa todos esos
facts de manera tipada. Sí es obligatorio que el verificador pueda distinguir
un class-handle borrow de un interior class-field borrow.

La observación de `*r` en contexto OOP usa una operación conceptual:

```text
BorrowedHandleView(reference, class, borrow_id)
BorrowedReceiver(view, capability=Read, borrow_id)
```

`BorrowedReceiver` alimenta los `DirectMethodCall`/`VirtualCall` existentes.
Puede reutilizar `ClassTokenKind::Receiver { mutable:false,
initializing:false }` sólo si el op conserva `BorrowId` y los verificadores
distinguen inequívocamente este origen de `this`. No debe disfrazarse de
`ClassTokenKind::Keepalive`, porque ese token vigente es owning.

El verificador HIR reconstruye independientemente:

- pointee directo C/C? permitido y reference shared canónico;
- source Place initialized y su owner state;
- ausencia de ClassField/index payload en provenance;
- region/CallSiteId/argument index correctos;
- no Move/Alias/Transfer al formar el borrow;
- usos de la vista sólo en contextos borrowed autorizados;
- receiver read y mismo ClassId o base relation válida;
- no owning result desde dereference;
- no escape/store/return/capture; y
- cleanup synthesis sin Drop para el reference ni para la vista.

## 12. MIR

MIR conserva operaciones y región explícitas. Para un lvalue:

```text
borrowed:ref C = BeginBorrowSharedClassHandle(
    place=owner,
    anchor=owner_token,
    borrow_id,
    region)
...
EndBorrow(borrow_id, borrowed)
```

El nombre concreto puede seguir siendo `Borrow`; la semántica anterior es
normativa. El operand físico aún no se decide en MIR.

Para un temporary:

```text
tmp:C = Transfer(<fresh owner>)
borrowed:ref C = BeginBorrowSharedClassHandle(tmp, tmp_owner, id, call)
invoke f(borrowed) normal/unwind
normal: EndBorrow(id); Drop(tmp)
unwind: EndBorrow(id); Drop(tmp); propagate same event
```

MIR debe impedir mientras el borrow esté vivo:

- Move/Transfer/Drop/replacement del anchor source;
- reuse de un owner token como si el borrow lo hubiera consumido;
- `HandleAlias` atribuido a la formación del borrow;
- método mut o field write mediante la vista;
- materialización owning desde dereference;
- interior class-field Place como borrow root; y
- cualquier use después de `EndBorrow`.

Calls anidadas pueden crear child borrows o forwardear el descriptor existente.
En ambos casos el owner anchor exterior domina toda la nested call. Los
`EndBorrow` se ordenan interior→exterior.

## 13. SSA y verificación de ownership

SSA conserva `BorrowId`, provenance, exact class TypeId, anchor y región. Un
class borrow participa en dos ledgers relacionados pero distintos:

1. el ledger owning conserva exactamente el owner token original para C o el
   owner condicional presente de C?; y
2. el ledger borrow registra que ese token/Place, o el slot C? null sin token,
   está inmovilizado hasta `EndBorrow`.

`BeginBorrow` no produce owner token. `EndBorrow` no consume ni libera uno.
Phis de raw pointers no pueden reconstruir un borrow: un join de references
sólo es válido bajo las reglas generales existentes y debe preservar un anchor
demostrable en cada incoming edge.

El verificador SSA rechaza independientemente:

- `ref C` sin owner vivo/dominante, incluso si el pointer no es null;
- `ref C?` sin root nullable initialized/dominante, o present sin su owner
  condicional vivo;
- owner movido, reemplazado o liberado antes de `EndBorrow`;
- pointer/object distinto del token anchor;
- owner/retain/release inventado para el borrowed value;
- Drop de `ref C`, BorrowedHandleView o BorrowedReceiver;
- escape por Return, Store, aggregate, phi no autorizado o call by-value;
- mutable receiver/field access desde capability read;
- upcast path/class metadata adulterados;
- `EndBorrow` ausente, duplicado, fuera de orden o sólo en un successor; y
- cleanup excepcional que libera el owner source antes de cerrar el borrow.

Las optimizaciones ARC pueden usar el anchor como prueba, pero no eliminar el
owner que lo sustenta ni convertir el borrow en ownership. Después de cualquier
rewrite se ejecuta la verificación SSA completa.

## 14. LLVM y ABI

La representación V1 elegida para `ref C` es el **mismo object pointer de C**
pasado como valor borrowed. No es `C**` en la call ABI.

Esta elección es segura porque BeginBorrow fija el valor del handle y prohíbe
reemplazar/dropear su owner anchor hasta EndBorrow. El Place/slot sigue en IR
semántico para la prueba de lifetime, pero no necesita viajar al callee. Dentro
del callee, `*r` es una operación semántica de observación; LLVM ya posee el
object pointer y no carga/retiene un owner.

`ref C?` no puede usar directamente el nullable object pointer como descriptor:
si el pointee fuese null, se confundiría “reference presente a un C? null” con
un `(ref C?)?` ausente y se rompería el contrato non-null de references. Por
eso conserva el ABI general de refs y pasa un pointer non-null al slot `C?`;
el callee carga desde allí el nullable class handle. El slot ya existe o es el
temporary estable de la call, no es wrapper, box ni allocation adicional.

Así, `ref C` usa el object pointer optimizado y `ref C?` usa pointer-to-slot.
Ambos son one-word en Linux x86-64, preservan sus TypeIds distintos y agregan
cero ARC. `(ref C)?` puede usar null como ausencia del reference porque un
`ref C` válido contiene siempre un object pointer non-null; `(ref C?)?` puede
usar null como ausencia porque el descriptor `ref C?` es la dirección non-null
del slot, no el valor nullable almacenado.

Quedan prohibidos:

- wrapper heap o stack ABI obligatorio;
- nuevo fat pointer para classes;
- runtime borrow object o borrow counter;
- vtable/witness/reflection adicional;
- retain/release en formación, forwarding, receiver read o finalización;
- boxing y payload copy;
- atributos LLVM `noalias`, `readonly` o `nonnull` no justificados (`ref C` sí
  puede usar non-null sólo si el backend ya lo deriva del contrato C); y
- inferir lifetime desde un raw pointer después de perder `BorrowId`.

Direct/virtual calls reciben el mismo receiver pointer ABI que hoy. El backend
sólo selecciona ese pointer desde un BorrowedReceiver verificado en lugar de
un owning keepalive.

## 15. Exceptions, unwind y nested calls

Caso central:

```aether
string render(ref Scene scene) {
    inspect(scene);
    throw GraphicsTextException();
}
```

Si el caller invoca `render(owner)`, su owner permanece vivo y no se transfiere.
El callee no registra Drop para el parámetro `ref Scene`. En throw:

1. se limpian sólo locals owning inicializados dentro de `render`;
2. se propaga el mismo `ExceptionEvent`;
3. el exceptional edge del caller termina los borrows call-scoped activos en
   orden interior→exterior;
4. si el root era un temporary, se lo dropea después de `EndBorrow`;
5. si era un owner del caller, no se lo dropea por causa del borrow; y
6. catch/finally recibe el mismo evento y el caller puede seguir usando owner.

`EndBorrow` es cleanup semántico sin runtime ARC. Debe existir en normal y
unwind aunque LLVM no emita una instrucción física.

Una nested call que recibe el mismo `ref C` conserva el anchor exterior. Si la
nested call lanza, cierra su región antes de abandonar la región exterior. Un
catch dentro del callee puede continuar usando el parámetro mientras su función
siga activa; un catch en el caller se ejecuta después del `EndBorrow` de la
call que lanzó.

Traps continúan abortivos y sin cleanup garantizado. Este milestone no los
convierte en exceptions.

## 16. Aliasing e incompatibilidades

Shared no significa exclusive. Se permiten:

- dos o más `ref C` al mismo owner;
- borrows desde handles Alias del mismo object;
- identidad/lecturas concurrentes en el orden secuencial del lenguaje; y
- mutación del object mediante otro owning alias si las reglas OOP ordinarias
  la permiten.

El borrow controla el **handle source y la capability de su path**, no todos
los aliases del object. Por ello no se puede optimizar una lectura suponiendo
que ningún alias mutará fields.

Sí son incompatibles, para el Place anchor exacto mientras viva el borrow:

- Move/Transfer/Drop;
- assignment/rebind/replacement;
- `ref mut C` (además no admitido en V1);
- cleanup temprano o owner-state join que pierda la obligación; y
- una call/effect cuya metadata vigente pruebe que puede reemplazar ese mismo
  slot.

Cuando alias/provenance no permite demostrar estabilidad, el checker falla
cerrado. No se agrega runtime pointer comparison ni borrow checker exclusivo.

## 17. Diagnósticos

La implementación debe mantener E0406 para features realmente fuera, pero no
usar el mensaje histórico “class handle slot references require separate
qualification” para un caso ahora válido.

Familias requeridas:

| Causa | Mensaje/nota requerida |
|---|---|
| `ref C` shared válido | ningún diagnóstico; dump identifica class-handle borrow |
| `ref mut C` | mutable class-handle references no admitidas en V1 |
| `ref I` | interface-handle references requieren qualification separada |
| aggregate que contiene C | no es un class-handle slot directo admitido |
| interior field/index | interior class storage cannot be borrowed; nombrar proyección |
| move/rebind/drop activo | señalar borrow/anchor y operación invalidante |
| método mut | receiver shared borrowed sólo concede read capability |
| owning extraction | no se puede producir owner/Alias desde `ref C` |
| escape/store/return | borrow non-escaping y límite de región |
| upcast inválido | relación nominal/path ausente o ref kind no shared |
| nullable misuse | conservar diagnóstico NULLABLE existente, sin auto-unwrap |

No se debe sugerir Clone, retain manual, pinning ni copiar el objeto.

## 18. Qualification futura: `class_handle_references_v1.rs`

CLASS-HANDLE-REFERENCES-V1 debe crear:

```text
compiler-next/crates/aether-driver/tests/class_handle_references_v1.rs
```

y fixtures source/malformed IR auxiliares sólo cuando el vertical se
implemente. La suite corre en O0 y O2.

### 18.1 Positivos

1. class simple prestada explícita e implícitamente;
2. método read directo desde `(*r)`;
3. método open/virtual que preserva identidad dinámica;
4. public Copy field read sin owner extraction;
5. nested forwarding `ref C -> ref C`;
6. dos borrows simultáneos del mismo slot;
7. borrows desde dos `Alias` del mismo object;
8. owner del caller usable después de cada call;
9. `ref Derived` llamando método declarado en Base;
10. `ref Derived -> ref Base` con relación válida y dispatch del override;
11. identity equality borrowed/borrowed y borrowed/owning;
12. `ref C?` null/present, test de null y forwarding sin auto-unwrap;
13. `(ref C)?` sólo bajo la composición NULLABLE ya vigente;
14. temporary C call-scoped: Transfer a root, EndBorrow y un único Drop;
15. excepción dentro del callee y catch en caller;
16. nested call que lanza y cleanup interior→exterior;
17. caller continúa usando el owner después del catch; y
18. mismo resultado/ownership lógico en O0/O2.

### 18.2 ARC y allocation

Los probes deben medir counters, no sólo inspeccionar source:

- `f(ref c)` agrega exactamente `retain=0`, `release=0`;
- un method read mediante `ref C` tampoco agrega receiver keepalive ARC;
- dos borrows simultáneos agregan 0/0;
- forwarding/nested calls agregan 0/0;
- Derived→Base borrowed agrega 0/0;
- unwind de lvalue agrega 0/0 y no destruye el owner caller;
- temporary fresh conserva sólo su release/drop ordinario post-borrow; y
- alloc/free no incluye wrapper, box ni runtime borrow object.

HIR/MIR/SSA dumps no deben contener `HandleAlias` o owning
`ReceiverKeepalive` atribuible a esas operaciones. LLVM inspection debe probar
pointer ABI y ausencia de calls ARC dentro del intervalo aislado.

### 18.3 Negativos source

- move, Drop o replacement del owner mientras está borrowed;
- método `mut`, field write y wrong receiver capability;
- `C x = *r`, by-value argument, return o move-out desde `*r`;
- return/store/capture del reference;
- `ref mut C` y `ref mut C?`;
- `ref Interface` y class-to-ref-interface;
- unrelated/cross-module inaccessible base conversion;
- borrow+upcast combinado desde owning Derived a `ref Base`;
- `&object.bufferField` y `&(*r).bufferField`;
- `&object.bufferField[i]` y `&(*r).bufferField[i]`;
- `ref mut object.someOwner`;
- View/ViewMut sobre backing reemplazable de class;
- nullable method call sin presencia utilizable; y
- borrow sin owner initialized/live.

### 18.4 Corrupciones HIR/MIR/SSA

Cada frontera debe rechazar, sin confiar en la anterior:

- pointee/reference TypeId o ClassId incorrecto;
- mutable bit escalado;
- Place cambiado por ClassField/interior projection;
- owner anchor ausente, moved, wrong-object o non-dominating;
- BorrowId/CallSiteId/argument index duplicado o adulterado;
- BorrowedHandleView usado como owner;
- BorrowedReceiver cambiado a mut;
- direct/virtual target o VirtualSlotId corrupto;
- borrowed base-upcast path corrupto;
- retain/owner token inventado;
- Drop del borrowed value;
- EndBorrow ausente/duplicado/antes de call/sólo en normal;
- escape mediante Store/Return/aggregate/phi/call by-value; y
- owner cleanup anterior a EndBorrow en unwind.

### 18.5 Metadata y LLVM

Corromper class relation, method capability, field ownership, descriptor/slot y
dynamic target debe continuar fallando en los verificadores OOP existentes.
LLVM debe mostrar:

- un pointer argument para `ref C`, no wrapper/fat pointer;
- pointer-to-slot non-null para `ref C?`, sin confundir pointee null con
  reference nullable ausente;
- direct/virtual dispatch idéntico al owning receiver salvo lifetime mode;
- ninguna vtable extra, reflection o borrow runtime;
- ningún `noalias` injustificado; y
- landing pads que terminan la región semántica antes del cleanup del root.

## 19. Regressions obligatorias

El gate de cierre ejecutará al menos:

- OOP-V1, V2, V3, OOP-OPT y OOP-POLISH;
- lifecycle/ARC de classes y dynamic destruction;
- references/views NEXT-VERTICAL-9;
- BORROW-ERGONOMICS-V1 y generic ref inference;
- NULLABLE-V1;
- EXCEPTION-V1..V4, unwind, catch y finally;
- CLASS-BUFFER-FIELDS-V1 y negativos de interior borrow;
- GRAPHICS-FOUNDATION-V1;
- graphics workspace existente sin privilegios compiler-side;
- `cargo test --workspace`;
- `cargo fmt --all -- --check`;
- `cargo clippy --workspace --all-targets -- -D warnings`;
- `git diff --check`; y
- differential vigente.

Un fixture graphics puede actuar como dogfood, pero la suite autoritativa usa
classes mínimas generales y no importa `graphics`.

## 20. Fuera de alcance

- `ref mut C`/`ref mut C?` y reemplazo mediante reference;
- `ref Interface` y borrowed interface adaptation;
- interior refs/views a cualquier class field o element;
- pinning, regions heap, backing refcounts o runtime borrow tracking;
- profundamente immutable/frozen objects;
- owning read-only handle nuevo;
- extraer/retornar/almacenar owners desde un borrow;
- stored/returned/captured references y named lifetimes;
- general reference covariance o variance de generics;
- conversion+borrow implícito y cambios de overload ranking;
- class graph fields, generic classes o nuevos storage kinds;
- boxing, reflection, RTTI/downcasts, FFI y ABI pública estable; y
- privilegios para Scene, graphics o packages concretos.

## 21. Plan del vertical y criterio de cierre

El futuro **CLASS-HANDLE-REFERENCES-V1** debe, en orden:

1. sustituir el E0406 amplio por el predicado positivo de sección 3;
2. hacer que Places directos C/C? formen shared borrows con owner anchor;
3. representar BorrowedHandleView/BorrowedReceiver sin owning token;
4. extender calls/fields/equality OOP existentes a capability read borrowed;
5. implementar el borrowed class upcast limitado;
6. conservar regiones/EndBorrow en normal y unwind;
7. bajar `ref C` al object pointer existente;
8. agregar verificaciones/corrupciones independientes y counters; y
9. completar toda la qualification de secciones 18–19.

El vertical sólo podrá declararse admitido si O0 y O2 demuestran cero ARC
adicional incluso al invocar un método read a través del borrow. Si la
implementación vigente obligara a un receiver retain/release, debe cambiar el
modo del receiver para usar `BorrowAnchor`; no puede redefinir el contrato de
este ARCH ni esconder el tráfico con una optimización opcional.

## 22. Resultado arquitectónico

La feature es implementable con los layouts y protocolos actuales:

- C ya es un object pointer con owner token explícito;
- refs ya son non-owning/no-escape y poseen Place/provenance;
- call borrows ya tienen regiones normal/unwind;
- OOP ya separa Alias, Transfer, receiver capability y dispatch; y
- SSA ya verifica owners y cleanup por path.

La pieza nueva es una relación verificada entre el borrow y el owner token que
lo ancla, más un receiver borrowed que reutiliza dispatch sin adquirir ownership.
No requiere runtime, layout de objeto ni protocolo ARC nuevo.

**Estado final: CLOSED.**

Siguiente milestone autorizado: **CLASS-HANDLE-REFERENCES-V1**.
