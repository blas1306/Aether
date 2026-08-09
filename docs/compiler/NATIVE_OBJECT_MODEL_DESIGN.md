# Modelo nativo de objetos por referencia

> Clasificación: **Current reference / Design — implementación Phase 5.4C**.
> Actualizado: **28 de julio de 2026**. Referencias, payload, fields,
> constructores, métodos concretos y ARC class están implementados en native.
> Interfaces incluyen witness dispatch para carrier class y boxing owned de
> structs, con lifecycle, nullable y colecciones.

## 1. Alcance y fuentes de verdad

El objetivo es fijar una representación común y composable para `class`,
interfaces, referencias, `null`, `T?`, dispatch y lifetime antes de implementar
cualquiera de esas capacidades en native.

El diseño conserva estas fuentes de verdad:

- la semántica frontend/AST histórica de classes, interfaces y nullable descrita
  por [AETHER_V0_SPEC.md](../aether/AETHER_V0_SPEC.md);
- la exclusión explícita de esas features del perfil estable en
  [AETHER_LANGUAGE_SPEC_V1.md](../aether/AETHER_LANGUAGE_SPEC_V1.md) y
  [AETHER_NATIVE_PROFILE_V1.md](../aether/AETHER_NATIVE_PROFILE_V1.md);
- el diagnóstico por etapas y el grafo de dependencias de
  [BACKEND_FEATURE_PARITY.md](../aether/BACKEND_FEATURE_PARITY.md);
- el ABI descriptivo actual de
  [AETHER_NATIVE_ABI.md](AETHER_NATIVE_ABI.md);
- las operaciones canónicas de
  [VALUE_LIFECYCLE_DESIGN.md](VALUE_LIFECYCLE_DESIGN.md);
- el objeto string no nulo y su ARC oculto de
  [STRING_RUNTIME_DESIGN.md](../aether/STRING_RUNTIME_DESIGN.md).

Este RFC no convierte el comportamiento histórico de v0 en parte de Aether
1.0. Tampoco relaja el capability gate. Una fase posterior deberá promover cada
feature explícitamente después de completar su camino E2E.

## 2. Decisiones resumidas

| Tema | Decisión |
| --- | --- |
| Identidad de class | Una instancia es una allocation lógica única y estable durante su vida. Copiar una referencia no crea otra instancia. |
| Referencia de class | Handle opaco, no nulo, de una palabra target: `ptr` en LLVM. |
| Objeto class | Header administrado seguido por fields en orden fuente. El layout es interno y target-dependent. |
| Dispatch de class | Directo/estático mientras no exista inheritance u override. No se agrega una vtable por objeto. |
| Valor interface | Existential de dos palabras: `{carrier, witness_table}`. No es un solo puntero. |
| Dispatch de interface | Indirecto por witness table inmutable, una por par `(tipo concreto, interface)`. |
| Struct en interface | Se guarda en una caja owned. Copiar el interface clona lógicamente el struct para conservar value semantics. |
| Class en interface | El carrier es la misma instancia class. Copiar el interface retiene y conserva aliasing. |
| `null` | No es un objeto ni un puntero genérico. Sólo construye el estado ausente de un `T?`. |
| `T?` | Tagged value canónico `{present: i1, payload: T}` para todo `T` representable. |
| Nullable de referencia | También usa tag; no roba el valor `ptr null`. Un `T` no nullable mantiene su invariante no nulo. |
| Uniformidad | Classes y handles runtime directos son una palabra; interfaces y nullable no. La uniformidad aprobada es de lifecycle/ownership, no de cantidad de palabras. |
| Ownership inicial | ARC fuerte, intrusivo, no atómico y oculto para classes; compatible con el contrato ya usado por strings y Array/List. |
| GC futuro | Debe consumir descriptors y trazado tipado sin cambiar la semántica. La primera opción compatible es un collector no moving por proceso/build. |
| `const` | Califica el acceso/binding, no el objeto. No forma parte del handle, header ni witness table. |
| ABI pública | Ninguna. Todo el diseño es ABI interna del módulo combinado hasta que exista runtime versionado. |

## 3. Objetivos e invariantes del modelo

### 3.1 Identidad

Cada construcción exitosa de una class crea una identidad distinta, incluso si
todos sus fields tienen el mismo contenido que otra instancia. La identidad:

- comienza al publicar la instancia construida;
- se conserva a través de assignment, parámetros, returns e interfaces;
- no cambia al mutar fields;
- termina cuando el runtime reclama la instancia;
- puede reutilizar una dirección sólo después de terminada esa vida.

La dirección estable se usa para retain/release, self-assignment e identidad.
Phase 5.3A fijó `Eq(ClassRefType(C))` en el subset IR native: `==`/`!=`
comparan los handles de dos valores del mismo `C`, nunca sus fields. El
lowering posterior de constructores y métodos promovió la superficie class;
no se agrega igualdad definida por usuario.

### 3.2 Semántica de referencia, mutabilidad y aliasing

Un valor de class denota una instancia; no contiene una copia inline de sus
fields. Para `b = a`, ambos handles designan la misma instancia y cada owning
slot mantiene su propia participación de ownership. Una mutación mediante `b`
puede observarse mediante `a`.

Esta regla también se conserva al convertir una class a interface. En cambio,
un struct sigue siendo un value type. La conversión de un struct a interface
crea un snapshot owned del valor y una copia posterior del interface crea otro
snapshot lógico. No se permite que el type erasure convierta accidentalmente un
struct en un objeto con aliasing observable.

El optimizador debe suponer aliasing entre referencias de class mientras no
exista un análisis que pruebe lo contrario. Reads y writes de fields, calls
mutantes e indirect calls son efectos de memoria; no pueden eliminarse o
reordenarse como operaciones puras.

### 3.3 `const`

`const` sigue siendo una restricción estática sobre un binding o access path:

- impide rebind del local;
- impide escribir fields o llamar métodos mutantes a través de ese path;
- no congela globalmente el objeto;
- no impide mutación mediante otro alias mutable;
- deja de propagarse al atravesar una referencia class contenida, de acuerdo
  con el typechecker actual;
- en interfaces controla si el receiver puede usar un método mutante, pero no
  selecciona otra witness table.

No existen handles `const`, bits de const en el header ni variantes de vtable.
Codificar const en runtime duplicaría representaciones sin aportar una
garantía que el lenguaje no ofrece.

### 3.4 Compatibilidad y seguridad

El modelo debe:

- preservar el ABI y value semantics actuales de structs;
- admitir fields con lifecycle no trivial, incluidos string, Array/List,
  structs y referencias class;
- no confundir null con string vacío, colección vacía o un objeto destruido;
- mantener nombres nominales independientes de paths locales e import aliases;
- usar tamaño, alineación y padding calculados por LLVM para el target;
- conservar retain/release, dispatch y allocation como efectos visibles para
  verificadores y optimizadores;
- permitir instrumentación de leaks, overflow/underflow de RC y use-after-free;
- dejar trazado suficiente para un collector futuro.

## 4. Taxonomía: semántica frente a representación

No todo valor representado internamente por `ptr` tiene semántica de class.

| Familia | Semántica source | Representación propuesta/actual | Identidad source |
| --- | --- | --- | --- |
| class | referencia mutable | `ptr` no nulo a objeto class | sí, aunque sin operador público |
| Array/List | referencia mutable | `ptr` no nulo a objeto runtime | aliasing observable; sin operador público |
| string | value inmutable con storage compartible | `ptr` no nulo a objeto string | no |
| callable top-level | valor de código sin capture | `ptr` a función | no Eq |
| interface | type erasure que preserva la semántica del concreto | `{ptr carrier, ptr witness}` | la del concreto |
| struct | value type | agregado LLVM inline | no identidad de objeto |
| `T?` | suma `None | Some(T)` | `{i1, T}` | la del payload sólo cuando está presente |

La uniformidad útil es el protocolo `copy_init/move_init/assign/destroy`, no
forzar a todos los tipos a ser una palabra ni compartir un único header.

## 5. Representación de class y referencias

### 5.1 Handle

`ClassRefType(C)` se representa como `ptr` opaco de una palabra target. Un
valor class válido es siempre no nulo. No existe un valor default universal de
tipo class: si se necesita ausencia debe usarse `C?`.

En pseudotipo LLVM:

```llvm
; Forma conceptual, no definición que deba emitirse en esta fase.
%class.<canonical-id> = type {
    %AetherObjectHeader,
    <field-0>,
    <field-1>,
    ...
}
```

El handle apunta al inicio de la allocation. Los fields mantienen orden fuente;
LLVM decide offsets, padding y alineación. No se hardcodea ancho de puntero ni
tamaño de header en Python.

### 5.2 Header y descriptor

El header lógico de una class contiene:

```text
descriptor      # tipo nominal, destroy y trace
strong_count    # ARC inicial
flags           # immortal/debug/management; reserva interna
reserved        # cero o uso versionado futuro
```

El descriptor inmutable por tipo contiene al menos:

```text
canonical_type_id
object_size / object_alignment
destroy_fields(object)
trace_references(object, visitor)
management/version flags
```

Éste es un contrato lógico, no un layout C público. Compiler y runtime pueden
materializarlo como globals LLVM privadas. Field access de código generado usa
el layout nominal completo de la class; retain/release, validación y
destrucción deben centralizarse en helpers para no duplicar offsets de header.

### 5.2.1 Layout materializado en Phase 5.3A/5.3B

```llvm
%AetherObjectHeader = type { ptr, i64, i32, i32 }
%AetherClassDescriptor = type {
    ptr, ; canonical_type_id UTF-8/NUL
    i64, ; object_size
    i64, ; object_alignment
    ptr, ; destroy_fields(object)
    ptr, ; trace_references(object, visitor)
    i32, ; management flags
    i32  ; descriptor version (= 1)
}
%class.<readable>.<digest> = type {
    %AetherObjectHeader,
    <field-0>,
    <field-1>,
    ...
}
```

Los índices del header son descriptor, `strong_count`, flags y reserved. Desde
5.3B los fields siguen al header en orden fuente y LLVM decide padding,
offsets y alineación. Cada tipo nominal recibe símbolos deterministas basados
en su ID completo y un digest.

`class_new` calcula size/alignment del objeto completo con expresiones LLVM/DataLayout, usa el
allocator checked, zero-inicializa el bloque y publica descriptor y strong
count 1. El último release llama `destroy_fields` por descriptor antes de
liberar el bloque. `destroy_fields` destruye el payload en orden fuente inverso;
`trace` permanece reservado para un collector futuro.

Strings no se migran a este header. Su layout actual comienza por
`byte_length` y tiene invariantes propios. Array/List también conservan sus
headers. Comparten lifecycle y convenciones de ownership, no una representación
física obligatoria.

### 5.3 Identidad nominal

Class, interface, descriptor, witness table y símbolo de método deben usar un
ID canónico basado en módulo/package semántico más declaración, nunca el path
absoluto, el alias de import ni sólo el spelling corto. Esto extiende el
principio ya usado por enums y mangling de módulos.

La identidad nominal debe resolverse antes de construir layouts. Dos classes
homónimas de módulos distintos nunca comparten descriptor, layout o witness.

### 5.4 Construcción

La construcción segura sigue esta secuencia lógica:

1. comprobar tamaños y reservar una allocation alineada;
2. inicializar header en estado no publicado con un owner inicial;
3. inicializar cada field con el lifecycle de su tipo;
4. ejecutar el constructor con `this` borrowed;
5. publicar un handle owned sólo cuando la instancia sea válida.

Una falla antes de la publicación destruye en orden inverso exactamente los
fields ya vivos y libera la allocation. El panic native actual es abortivo y
no hace unwind, pero conservar el estado de inicialización evita cerrar la
puerta a errores recuperables.

No se interpreta un bloque de ceros como una class válida. En particular, un
field class no nullable requiere inicialización real; `ptr null` sólo puede
existir como bytes inactivos dentro de un nullable ausente o durante
construcción interna no publicada.

### 5.5 Definite initialization y defaults

Un constructor explícito no recibe defaults implícitos: todos sus fields,
incluidos scalar, string, nullable, struct, class, Array y List, deben
inicializarse en cada path exitoso. Se rechazan reads previos, returns
incompletos, exposición de `this` incompleto y asignaciones sólo probables
después de merges. Un loop no prueba inicialización porque puede ejecutar cero
veces. La gramática actual no admite initializers en la declaración del field;
los ceros de la allocation son sólo una medida de seguridad interna.

Una class sin constructor explícito conserva el constructor posicional: recibe
exactamente un argumento por field en orden fuente. El fallback AST `None` para
fields class no nullable queda inaccesible para programas typechecked.

## 6. `null` y nullable

### 6.1 Regla semántica

`null` no tiene representación standalone. Es un literal contextual que sólo
puede crear el caso ausente del tipo esperado `T?`. No pertenece a toda
referencia y no cambia la nulabilidad de class, string, interface o colección.

El frontend actual prohíbe nested nullable y `void?`; el backend conserva esas
reglas y sólo admite `T?` cuando `T` tiene layout y lifecycle native completos.

### 6.2 Layout canónico

Para todo `T` representable:

```llvm
%nullable.<T> = type { i1, <llvm-type-of-T> }
; field 0: present
; field 1: payload
```

Invariantes:

- `present == false`: el valor es `null`; el payload no es un valor Aether
  vivo y nunca se copia, lee, compara ni destruye;
- `present == true`: el payload contiene exactamente un `T` vivo;
- el caso ausente usa `zeroinitializer` en el payload al cruzar storage/ABI,
  para evitar `undef`, poison y bytes indeterminados;
- esos ceros son bytes inactivos, no un valor válido de `T`;
- padding y tamaño pertenecen al DataLayout del target.

Se rechaza usar `ptr null` como niche ABI para nullable de referencia. El tag
uniforme:

- soporta `int?`, structs?, interface? y cualquier `T` sized;
- mantiene no nulos todos los handles no nullable;
- conserva la distinción entre `null`, `""` y una colección vacía;
- evita que una optimización de representación cambie firmas entre tipos.

Una optimización local futura puede usar un niche si demuestra equivalencia y
reconstruye la forma canónica en storage, calls, returns y phis. No forma parte
del ABI inicial.

### 6.3 Lifecycle de `T?`

Las operaciones se sintetizan recursivamente:

| Operación | Caso ausente | Caso presente |
| --- | --- | --- |
| `init_default` | `{false, zeroinitializer}` | — |
| `copy_init` | copia el tag y canonicaliza payload | `copy_init(T)` |
| `move_init` | mueve la forma ausente | transfiere `T`, deja source ausente |
| `assign` | adquiere primero el nuevo estado y destruye payload anterior si existía | usa `assign/copy_init(T)` con commit seguro |
| `destroy` | no-op | `destroy(T)` |
| `relocate` | move bitwise del agregado, source deja de estar vivo | igual, sin duplicar owner |

`T?` es trivialmente copiable sólo si `T` lo es, siempre es sized si `T` lo
es, y necesita destroy/retain exactamente cuando el caso presente de `T` lo
necesita.

### 6.4 Comparación

El test interno de null sólo lee el tag. La igualdad de dos nullable:

1. dos ausentes son iguales;
2. ausente y presente son distintos;
3. dos presentes delegan en `Eq(T)`.

Esto no amplía `Eq`: si `T` no tiene igualdad, `T?` tampoco la obtiene. Por
ello el layout permite comprobar el tag, pero la disponibilidad de un operador
source sigue siendo decisión del typechecker actual. La Fase 5.3A define
`Eq(Class)` por identidad del objeto, así que `Class?` hereda esa igualdad;
`Interface?` continúa sin `Eq`: Phase 5.4A incorpora representación y witness
identity, pero no define igualdad source ni dispatch.

## 7. Representación de interfaces

### 7.1 Existential fat value

Una interface no se representa con un puntero a una vtable dentro de cada
objeto. El valor erased es:

```llvm
%interface.<canonical-id> = type {
    ptr, ; carrier owned/borrowed según posición
    ptr  ; witness table inmutable y no nula
}
```

Para una interface no nullable ambos punteros son válidos y no nulos. Un
interface nullable envuelve el agregado completo en el tag de la sección 6.
El agregado mide dos palabras target y su alineación es la alineación de `ptr`;
LLVM decide padding/DataLayout. Se pasa y retorna por valor según la ABI de
agregados del target. En storage, IR y SSA siempre es un único valor tipado, no
dos SSA values independientes.

La witness table es metadata inmortal y una global privada por par
`(tipo concreto, interface nominal)`. Phase 5.4A materializa exactamente:

```text
header:
    interface_id: ptr
    concrete_type_id: ptr
    abi_version: i32
    method_slot_count: i32
    copy_owned: ptr
    drop_owned: ptr
method_slots[N]:
    index: i32
    method_id: ptr
    dispatch_thunk: ptr
```

Los slots siguen el orden de declaración de la interface. Como no existe
interface inheritance, defaults ni overloads, no se necesita resolución
adicional. El orden es ABI interna y debe regenerarse conjuntamente; no es una
FFI estable. El símbolo se deriva únicamente de los IDs UTF-8 canónicos,
longitudes, bytes hex y un digest estable; no depende del path ni del orden de
recorrido. Las tablas se imprimen ordenadas por `(interface_id,
concrete_type_id, symbol)`.

En IR, `interface_construct result, carrier, witness` conserva el par y lleva
la metadata completa por DTO. `interface_call receiver, slot, args` conserva
la firma borrada y baja exclusivamente a witness→slot→thunk. En SSA el par
sigue siendo un único valor agregado nominal; parámetros, returns y phis lo
transportan sin separar ni reconstruir sus componentes. Optimización puede
eliminar una construcción sólo cuando todo el valor está muerto; las calls
indirectas conservan efectos de memoria, ARC y panic.

### 7.2 Carrier de class

Cuando una class implementa la interface:

- `carrier` es el mismo handle a la instancia class;
- construir un interface consume un owner temporal o retiene un carrier
  borrowed;
- copiar/retener el interface retiene solamente el carrier;
- destruir/liberar el interface libera solamente el carrier;
- el witness no se retiene ni libera: es metadata inmutable e inmortal;
- los method thunks y calls indirectas todavía no existen en 5.4A.

No se reserva una caja adicional en esta conversión. La identidad de la class
no cambia ni se introduce una segunda capa de objeto.

### 7.3 Carrier de struct (Phase 5.4C)

Un puntero a un struct temporal o de stack no escapa dentro de una interface.
Phase 5.4C implementa el carrier como puntero a una caja existential privada,
sin cambiar el layout público `{carrier,witness}`:

```text
struct-interface box:
    i64 payload_size
    i32 payload_alignment
    i32 payload_offset
    padding hasta payload_offset
    concrete struct payload
```

El header ocupa 16 bytes. `payload_offset = align_up(16,
payload_alignment)`; size/alignment se validan mediante el contrato LP64 del
DTO y LLVM vuelve a calcular el tamaño total con DataLayout. Ownership es
`owned_value`; descriptor, adapters y layout permanecen internos al backend.
La caja contiene una copia lógica viva del struct. Sus operaciones son:

- `copy_owned`: reserva otra caja y ejecuta `copy_init` del payload;
- `drop_owned`: destruye el payload en orden correcto y libera la caja;
- method thunk read-only: invoca el método sobre el payload;
- method thunk mutante: actualiza el payload contenido en esa caja.

Así, copiar o retornar un interface cuyo concreto es struct mantiene value
semantics. Compartir la misma caja por retain sería incorrecto: dos variables
interface podrían observar mutaciones cruzadas que no existen al copiar el
struct directamente.

Una optimización puede evitar la caja para un interface estrictamente borrowed,
no escapable y con lifetime probado, pero la forma owned canónica siempre es la
caja. La optimización no puede cambiar aliasing, dispatch ni cleanup.

### 7.4 Lifecycle dinámico (Phase 5.4C)

El tipo estático interface no conoce si el concreto es class o struct. El
contrato implementado es:

```text
copy_init(dst, src):
    new_carrier = src.witness.copy_owned(src.carrier)
    dst = {new_carrier, src.witness}

move_init(dst, src):
    transferir las dos palabras; source deja de estar vivo

assign(dst, src):
    adquirir new_carrier primero
    guardar el nuevo par
    old.witness.drop_owned(old.carrier)

destroy(value):
    value.witness.drop_owned(value.carrier)
```

La adquisición anterior al drop hace segura la autoasignación, incluso cuando
source y destination contienen el mismo carrier. `copy_owned` puede asignar y
fallar para structs; el destino anterior no cambia antes del commit.

## 8. ABI interna

### 8.1 Regla general de calls

Se conserva la convención de lifecycle actual:

- parámetros normales son borrowed durante la call;
- el callee adquiere ownership si almacena o retorna el valor;
- resultados no triviales son owned por el caller;
- un move/return puede transferir un owner sin retain;
- fields, locals owning, globals futuros y elementos owning se destruyen una
  vez;
- receivers de métodos son borrowed durante la call.

Borrowed/owned es metadata semántica/verificable, no un bit dentro del valor.

### 8.2 Matriz ABI

| Tipo/posición | Parámetro | Return | Copy | Move | Destroy |
| --- | --- | --- | --- | --- | --- |
| `struct S` | ABI por valor existente; lifecycle source preserva copia lógica | por valor/aggregate existente | fields recursivos | relocation de valor | fields en orden inverso |
| `class C` | `ptr` borrowed | `ptr` owned | retain | transferir palabra | release |
| `interface I` | `{ptr,ptr}` borrowed por valor | `{ptr,ptr}` owned | witness `copy_owned` | transferir dos palabras | witness `drop_owned` |
| `T?` | `{i1,T}` borrowed recursivo | `{i1,T}` owned si presente | condicionado por tag | transferir agregado | payload sólo si presente |
| `null` | no existe posición sin tipo esperado | construye `T?` ausente | — | — | — |

El paso de agregados sigue la calling convention LLVM/Clang del target, como
los structs actuales. No se promete que `{ptr,ptr}` o `{i1,T}` tenga la misma
ABI C en todos los targets. Al separar el runtime deberán definirse firmas C
estrechas con handles opacos o out parameters.

### 8.3 ABI de métodos

Los métodos de class no reutilizan `MethodResultType` de struct:

```text
class method:    R C.method(ptr borrowed_this, P1, ...)
struct method:   {S [, R]} S.method(S receiver, P1, ...)  # ABI actual
```

Una class se muta en su objeto compartido y no necesita devolver un receiver
actualizado. Mantener separados ambos ABIs evita copiar el objeto o confundir
identidad con value reconstruction.

El slot erased de interface usa conceptualmente:

```text
R thunk(ptr carrier, P1, ...)
```

Para class, el thunk llama al método class. Para struct, adapta el payload de
la caja al ABI existente de método struct y, si corresponde, guarda el receiver
actualizado que retorna dicho ABI. De este modo interface dispatch no obliga a
cambiar el contrato actual de structs.

### 8.4 Assignment y fields

Assignment nunca es sólo un store para un valor owning:

```text
class dst = src:
    retain(src)
    old = dst
    dst = src
    release(old)
```

Interface y nullable siguen las variantes de sus secciones. Un field get que
produce un valor owned copia/retiene; un borrow temporal puede evitarlo sólo si
no escapa. Un field set usa `assign` del tipo del field y conserva
self-assignment, aliasing indirecto y strong exception safety.

### 8.5 Comparación ABI

- `ClassRefType` compara identidad con `icmp eq/ne ptr` en IR/SSA/LLVM;
- el gate de capability todavía impide que sintaxis source de classes llegue al
  lowering native hasta implementar constructores, fields y métodos;
- interfaces no tienen compare source;
- pointer equality de colecciones sólo puede ser un fast path no observable;
- null test inspecciona el tag del nullable;
- igualdad nullable delega en `Eq(T)` cuando esa capability existe;
- witness/descriptor pointers no son valores comparables del lenguaje.

### 8.6 Ownership observable

El usuario puede observar aliasing y mutaciones, pero no:

- el valor del strong count;
- el número exacto de retains/releases;
- si una optimización hizo move o elidió ARC;
- la dirección del objeto;
- el momento exacto de reclamación en ausencia de un destructor/API de
  identidad;
- la clase concreta almacenada en una interface mediante reflection, porque no
  existe tal API.

Allocation failure, panic de overflow de RC y agotamiento de memoria siguen
siendo efectos runtime. Este RFC no agrega destructores de usuario, weak
references, finalizers ni reflection.

## 9. Dispatch

### 9.1 Despacho estático

Se usa para:

- funciones libres;
- métodos de struct con tipo concreto;
- constructores;
- métodos de class con tipo concreto.

Classes no tienen inheritance, override ni overload. Una vtable de class no
aportaría semántica y aumentaría todos los objetos. El descriptor de tipo no se
consulta para una call concreta.

Coste esperado: una call directa, más las operaciones de lifecycle de
argumentos/resultados que realmente correspondan.

### 9.2 Despacho dinámico

Se usa exclusivamente cuando el tipo estático del receiver es interface:

1. cargar el function pointer del slot conocido de la witness table;
2. pasar el carrier como receiver erased;
3. ejecutar una call indirecta con la firma estática de la interface.

Coste esperado en steady state:

- una carga del slot;
- una indirect call;
- posiblemente un thunk corto;
- ninguna allocation por call.

La conversión a interface sí puede tener coste:

- class a interface owned: retain, sin allocation;
- struct a interface owned: allocation y copia lógica;
- interface copy: retain o clone decidido dinámicamente por witness.

Calls indirectas deben marcarse conservadoramente como reads/writes, may-trap y
posible allocation según la firma/efectos del método hasta disponer de effect
summaries verificadas.

### 9.3 Devirtualización futura

SSA puede reemplazar una interface call por call concreta sólo si prueba la
witness exacta y conserva:

- el thunk necesario para struct/class;
- ownership de argumentos/return;
- efectos y panics;
- mutación del carrier correcto;
- lifetime de una caja struct.

La devirtualización no autoriza eliminar la conversión/caja si el interface
escapa o si hacerlo cambia value semantics.

## 10. Lifetime y administración de memoria

### 10.1 Owners y borrows

Son owners:

- el resultado inicial de una construcción/allocation;
- cada local owning;
- fields owning de class/struct;
- elementos owning de collections;
- un interface owned respecto de su carrier;
- el payload presente de un nullable owned;
- un resultado no trivial entregado al caller;
- globals futuros.

Son borrows:

- parámetros normales durante la call;
- `this`/receiver durante un método;
- reads temporales marcados no escapables;
- iteración borrowed existente;
- referencias utilizadas sólo para una operación runtime acotada.

Cada alias class owned cuenta como un strong owner. Un borrow no incrementa RC,
no se destruye y no puede sobrevivir al owner que garantiza su vida.

### 10.2 ARC inicial

Classes adoptan ARC fuerte, intrusivo y no atómico:

- una instancia dinámica publicada comienza con strong count 1;
- copy/escape owned hace retain;
- destroy hace release;
- retain valida overflow antes de incrementar;
- release valida underflow;
- la transición `1 -> 0` destruye fields en orden inverso y libera el objeto;
- cleanup normal no lanza una excepción recuperable.

Esto coincide con el régimen actual de string y Array/List sin obligarlos a
compartir header. Los helpers permanecen type-directed: liberar una class
necesita su descriptor; liberar string o collection usa su runtime existente.

La política no atómica sólo es válida mientras Aether no permita compartir
objetos entre threads native. Concurrencia exige una decisión previa entre RC
atómico, transferencia comprobada o GC.

### 10.3 Ciclos

Classes pueden formar ciclos mediante fields de referencia. ARC fuerte por sí
solo no reclama un ciclo que conserva counts positivos. La primera
implementación debe ser memory-safe —nunca use-after-free— pero no puede
prometer reclamación de ciclos sin una de estas extensiones:

1. cycle collector sobre el grafo de objetos;
2. tracing GC;
3. weak references con semántica source nueva.

Este RFC reserva `trace_references` en descriptors y recomienda un cycle
collector/tracing no moving antes de calificar programas cíclicos de larga vida
como libres de leaks. Weak references no se introducen porque cambiarían la
superficie del lenguaje.

El límite debe documentarse y medirse con leak tests; no debe ocultarse
liberando arbitrariamente un objeto con strong owners.

### 10.4 GC opcional futuro

El contrato semántico de lifecycle permanece aunque cambie el proveedor:

- `copy_init`, `assign`, `move`, `destroy` y ownership siguen en IR;
- un lowering ARC los convierte en retain/release;
- un lowering GC puede convertirlos en root updates, write barriers o no-ops
  probados;
- descriptors de class y cajas struct enumeran referencias transitivas;
- collections deben exponer trazado de elementos, no sólo liberar buffers;
- fields string/recursos no GC siguen necesitando cleanup o integración con el
  collector.

La primera estrategia GC compatible debe ser no moving y seleccionada para el
proceso/build completo. Así los handles `ptr`, carriers de interface y borrows
mantienen dirección estable. Un collector moving requiere stack maps, update
de roots, pinning/handles para ABI y revisión de field access; no queda
prometido por este RFC.

Un modo híbrido por tipo sólo es válido si el collector recorre todas las
aristas entre classes, cajas, collections y objetos ARC. Simplemente convertir
retain/release en no-op produciría roots perdidos y no es una migración válida.

### 10.5 Fin de vida y panic

Un objeto puede destruirse cuando desaparece el último strong owner y no
existe un borrow válido fuera de esos owners. Bajo ARC esto ocurre de forma
determinista en la transición a cero; bajo GC futuro puede ocurrir después de
ser inalcanzable.

El panic native actual termina el proceso y no ejecuta unwind de frames. Los
exits estructurados normales (`return`, fin de scope, `break`, `continue`)
mantienen cleanup. Si se implementan excepciones recuperables, cada punto
fallable necesitará una arista excepcional con el conjunto exacto de objetos y
payloads parcialmente vivos.

## 11. Integración con LLVM y capas actuales

### 11.1 LLVM

El diseño usa exclusivamente formas que LLVM ya representa:

- opaque `ptr` para class/carriers/descriptors/functions;
- named structs para objetos, interfaces y nullable;
- globals constantes para descriptors y witness tables;
- indirect calls con firma estática conocida;
- GEP sobre layouts nominales;
- helpers effectful de allocation/retain/release/drop/trace.

No requiere punteros tipados, cálculo host de padding ni un target fijo. Antes
de emitir objetos reutilizables debe fijarse triple/DataLayout o continuar con
la política actual de módulo combinado compilado por Clang host.

### 11.2 Initial IR y SSA

El IR y SSA admiten `ClassRefType`, `InterfaceType` y `NullableType`. Phase
5.4A define para interfaces:

- tipo nominal `InterfaceType`;
- `IRInterfaceConstruct`/`SSAInterfaceConstruct`;
- witness metadata versionada y determinista en DTO Python/Rust;
- conversión class→interface;
- lifecycle de carrier class en locals, parameters, returns, phis, nullable,
  Array y List;
- representación LLVM nominal `{ptr carrier, ptr witness}` y globals
  constantes.

Las calls por slot, function pointers no nulos, boxing y adapters siguen
ausentes y se diagnostican explícitamente.

Lifecycle se expande después de verificar Initial IR y antes de SSA. SSA
conserva tipos nominales, dominancia y phis, pero un phi owned no crea owners
implícitos. Los verificadores Python y Rust importan y validan el mismo schema
DTO v1, incluida la identidad y el orden de slots del witness.

### 11.3 Structs

Nada cambia en el layout o ABI de struct:

- fields inline en orden fuente;
- copy y destroy recursivos;
- paso/return por valor target-dependent;
- `MethodResultType` para receiver actualizado;
- ciclos by-value siguen prohibidos;
- un field class es sólo un handle de una palabra y por eso no crea ciclo de
  layout.

La caja de interface es un adaptador externo al valor struct. No cambia el
layout de `S` ni hace que un `S` ordinario tenga header.

### 11.4 Runtime string y collections

String conserva:

- handle no nulo de una palabra;
- header propio con byte length;
- UTF-8 y NUL trailing;
- ARC no atómico, literales/vacío inmortales;
- value semantics por contenido.

Array/List conservan sus headers, buffers, aliasing y RC. El modelo nuevo
reutiliza su clasificación de handle no trivialmente copiable y trivialmente
relocatable. Cuando puedan contener class/interface/nullable, sus hooks de
elemento deben delegar en el lifecycle completo del elemento.

## 12. Orden de implementación recomendado

La auditoría del repositorio no respalda una dependencia lineal
`nullable -> class -> interface`. Nullable es una raíz composable; interfaces
sí dependen del ABI erased y de receivers con lifecycle válido.

```text
IDs nominales + TypeLayout + lifecycle/ownership verificable
                  |
          +-------+------------------+
          |                          |
          v                          v
  Nullable tagged genérico     Class object/reference ABI
          |                          |
          |                          v
          |                 construcción + fields +
          |                 métodos directos + ARC
          |                          |
          +-------------+------------+
                        v
              Interface carrier/witness
              /                    \
      caja para struct       carrier de class
                        |
                        v
          dispatch + lifecycle dinámico
                        |
                        v
        hardening de ciclos / GC opcional /
        optimización ARC y devirtualización
```

Lifecycle no es una fase final: es criterio de entrada y salida en cada bloque.
No debe habilitarse construcción de class, nullable no trivial o boxing de
interface con cleanup pendiente.

### 12.1 Fase siguiente A — fundamentos

1. congelar IDs nominales cross-module;
2. extender la descripción de TypeLayout sin emitir código nuevo;
3. fijar traits de class/interface/nullable;
4. diseñar schema/opcodes y reglas de verifier Python/Rust;
5. definir helpers runtime privados y matriz de efectos;
6. preparar tests negativos de gate y wire format.

### 12.2 Fase B — nullable (implementada en Fase 5.2)

1. tag, constructores absent/present y extracción comprobada;
2. lifecycle recursivo y phis;
3. null comparison/print sólo según reglas existentes;
4. structs/collections con nullable cuando `T` sea representable;
5. paridad AST/IR/SSA/LLVM y capability promotion explícita.

Esta rama se implementó antes de classes. El registry genérico acepta
`ClassRefType` e `InterfaceType` con sus layouts/lifecycle actuales, sin
rediseñar nullable.

### 12.3 Classes — estado tras 5.3C

Fase 5.3A completa descriptor/header, runtime ARC, layout nominal, allocation
checked, transporte por parámetros/returns/phis, containment, aliasing,
self-assignment e igualdad por identidad en el subset IR/SSA/LLVM interno.

Fase 5.3B completa layout de payload, `class_get`, `class_set`, constructor
posicional/explicit, `this.field`, field implícito, definite initialization,
ownership de reemplazo y destructor recursivo. `this` se pasa borrowed y una
construcción exitosa entrega exactamente el owner de la allocation.

`IRClassNew` conserva el estado privado de inicialización del payload y cada
`class_set initialize=true` publica el bit del field sólo después del store.
Tanto el intérprete IR como el destructor descriptor-driven de LLVM liberan
únicamente los fields publicados. Por eso un constructor que propaga una
excepción puede devolver el owner de la allocation al cleanup del caller sin
leer fields todavía nulos ni destruir dos veces los ya inicializados.

Fase 5.3C completa el ABI directo de métodos, `this` fuera de constructores,
calls estáticas, recursión e imports de métodos. Cada método baja como
`R C.method(ptr borrowed_this, P1, ...)`: el receiver no crea un owner ni un
slot local, las mutaciones usan `class_set` sobre el objeto compartido y los
resultados owning se transfieren al caller. No reutiliza `MethodResultType`,
reservado a value receivers struct. Las calls ordinarias conservan efectos de
memoria y lifecycle a través de IR, SSA, optimizadores y LLVM.

### 12.4 Interfaces

**Phase 5.4A–5.4C completadas:** ABI `{carrier,witness}`, witness tables
deterministas, carrier class sin box, box owned para struct,
IR/SSA/DTO/verifiers Python y Rust, LLVM, lifecycle dinámico, nullable y
colecciones.

**Phase 5.4B completada:** slots poblados con thunks
`R(ptr borrowed_carrier, args...)`, opcode `interface_call`, carga
witness→slot→thunk y call indirecta LLVM. Python y Rust validan orden,
cantidad, firma borrada, ownership y compatibilidad con el método class.
Mutación conserva aliasing y el call no introduce ARC adicional. Incluye
parámetros, returns, temporales, recursión, colecciones e imports; no incluye
boxing, devirtualización ni inlining.

**Phase 5.4C pendiente:** caja struct, clone/drop adapters y lifecycle
dinámico decidido por witness, sin cambiar las dos palabras del valor.

### 12.5 Fase siguiente E — lifetime avanzado

1. instrumentación RC/leaks y sanitizers;
2. política de ciclos para workloads de larga vida;
3. descriptors de trace para todo objeto/container;
4. prototipo GC no moving detrás de la misma semántica;
5. ARC optimization y devirtualización sólo con pruebas de equivalencia;
6. decisión separada de threading y RC atómico.

## 13. Riesgos y decisiones que provocarían refactor

| Decisión prematura | Refactor/riesgo posterior | Mitigación aprobada |
| --- | --- | --- |
| Usar `ptr null` para `Class?`/`string?` | ABI nullable distinta por tipo; no soporta `int?`/struct?; rompe el invariante no nulo | tag uniforme `{i1,T}` |
| Hacer todos los reference-like values de una palabra | obliga a heap-box de interface y nullable, agrega allocations y confunde semántica | aceptar fat/tagged values |
| Un header universal idéntico a string | migración del runtime textual y offsets duplicados | compartir protocolo, no bytes |
| Meter vtable en cada class | coste permanente sin inheritance; ABI difícil de cambiar | dispatch class directo, witness externa |
| Retener una caja struct al copiar interface | convierte value semantics en aliasing | witness clone para struct |
| Guardar puntero a struct stack en interface owned | dangling al escapar/retornar | caja owned canónica |
| Boxear class al convertir a interface | segunda identidad/lifetime y allocation innecesaria | carrier apunta a instancia original |
| Reutilizar `MethodResultType` para class | copia/reconstrucción falsa del receiver | ABI class por `ptr this` |
| Hacer release antes de retain en assignment | use-after-free en self/indirect alias | acquire-before-commit-before-drop |
| Codificar `const` en handles/vtables | explosión de variantes y falsa inmutabilidad global | const exclusivamente estático |
| Tratar interface call como pura | DCE/reordering rompe mutación, allocation y panic | efectos conservadores |
| Exponer offsets/header/vtable como FFI | bloquea evolución de ARC/GC/layout | ABI privada y helpers opacos |
| IDs nominales por spelling corto | colisiones cross-module y witness incorrecta | ID canónico module+declaration |
| Adoptar GC moving sin roots/stack maps | pointers/carriers/borrows dangling | GC inicial no moving; decisión posterior |
| Convertir retain/release en no-op para “usar GC” | objetos no rooted y aristas invisibles | lowering de roots/barriers + trace tipado |
| Ignorar ciclos ARC | leaks no acotados en grafos class | instrumentar y añadir cycle collector/GC |
| RC no atómico después de threads | races, UAF y corrupción de counts | decisión de concurrencia antes de threads |
| Promover una feature por admitir su IR type nominal | gaps de lowering/verifier/runtime | capability gate E2E por operación |
| Copiar el fallback AST `None` a un field class no nullable | null implícito, contradicción con `T?` y posibles traps tardíos | caracterizar/decidir initialization antes de promover class |

## 14. Validación arquitectónica

| Restricción del repositorio | Comprobación |
| --- | --- |
| Backend LLVM actual | Usa opaque pointers, named aggregates, target layout e indirect calls ya compatibles. No exige cambio inmediato. |
| IR existente | `InterfaceType`, `interface_construct` e `interface_call` conservan carrier+witness, slot y firma borrada. |
| SSA/verifiers | Lifecycle antes de SSA, phis agregados y verificación coordinada Python/Rust implementados para construcción y dispatch class-carrier. |
| Structs | No cambia layout, paso/return, copy recursivo ni MethodResultType. La caja interface vive fuera del struct. |
| String ARC | Mantiene handle no nulo, header propio y retain/release. `string?` usa wrapper/tag independiente como requería su RFC. |
| Array/List | Mantiene aliasing, headers y RC. Nuevos elementos usarán hooks type-directed. |
| Paridad | Sigue el grafo auditado: reference layout/lifecycle antes de class; erased ABI antes de interface; nullable como rama independiente. |
| Const | Reproduce la restricción por access path y el corte al atravesar class que aplica el frontend actual. |
| Igualdad | Phase 5.3A agrega Eq por identidad al tipo IR class; interfaces y equality definida por usuario siguen fuera. |
| Perfil native | Profile 24: nullable, classes, interfaces class/struct y excepciones son E2E; `interfaces` y `error-handling` son capacidades granulares COMPLETE. |

## 15. Criterios de entrada para implementación

Antes de comenzar código de una de las ramas debe aprobarse:

- el ID nominal y mangling cross-module;
- la forma exacta del IR y DTO versionado;
- los traits de lifecycle y reglas de verifier;
- la tabla de efectos de cada opcode/helper;
- el boundary compiler/runtime y política de allocation failure;
- tests de semántica AST que caractericen aliasing de class y copia de struct a
  través de interface, incluidos métodos mutantes;
- tests de nullable para cada familia de layout;
- criterio explícito de capability promotion y rollback.

`NullableType` tiene soporte native E2E. `ClassRefType` tiene layout, payload,
construcción source, métodos directos, lifecycle y transporte ejecutables
desde 5.3C. `InterfaceType` tiene layout, construcción class/struct, dispatch,
lifecycle, DTO, SSA, LLVM y verificación coordinada Python/Rust.

## 16. Fuera de alcance

No se diseñan ni habilitan:

- inheritance, `extends`, `super` u override de class;
- interface inheritance, default methods o generic interfaces;
- destructores/finalizers de usuario;
- weak/unowned references;
- reflection, downcast o type tests públicos;
- igualdad definida por usuario o equality de interfaces;
- concurrency o sharing cross-thread;
- exceptions/unwind;
- FFI estable, runtime separado versionado o linking de objetos Aether de
  releases distintas;
- generics de usuario, closures o bound methods;
- GC moving.

Cada una de esas features requiere un RFC separado. El descriptor y los thunks
de este diseño dejan puntos de extensión, pero no anticipan semántica que el
lenguaje actual no posee.

## 17. Estado y frontera tras Phase 5.4C

Completado: handle nominal; allocation de objeto completo; layout determinista
de fields; DTO y verificación Python/Rust; constructor posicional y explícito;
`this.field` y acceso implícito; reads/writes con aliasing; definite
initialization; ARC de fields; destrucción recursiva por descriptor; classes en
nullable, structs, Array y List; métodos directos con parámetros, returns,
recursión, calls anidadas, `this` explícito/implícito y alias-visible mutation;
LLVM válido en O0/O1/O2.

La superficie native admite classes concretas con fields, constructores y
métodos de dispatch estático, y convierte classes o structs a valores
interface `{carrier,witness}`. Las llamadas de interface hacen dispatch
witness-driven; los structs usan cajas owned con copy/drop dinámico.
Inheritance/default methods, destructores de usuario, exceptions/unwind, weak
refs, GC y cycle collection siguen posteriores. ARC fuerte no recolecta
ciclos.
