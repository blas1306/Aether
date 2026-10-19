# CLASS-BUFFER-FIELDS-ARCH-1 — `Buffer<T>` privado en classes

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Este documento elimina como decisión semántica el privilegio accidental de
`Buffer<int>` en fields de class. No implementa el cambio, no admite programs
nuevos todavía y no agrega una excepción para graphics.

Autoridades:

- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md), en particular
  ownership estructural, `Buffer<T>`, `Storable`, OOP-V1 y constructor unwind;
- [OOP-ARCH-1](OOP_ARCH_1.md),
  [OOP-V1](OOP_V1_REPORT.md) y los verticales de lifecycle vigentes;
- la arquitectura e implementación actuales de `Buffer<T>`;
- [GRAPHICS-FOUNDATION-V1-REPORT](GRAPHICS_FOUNDATION_V1_REPORT.md), sólo como
  reproducer del gap y no como autoridad para privilegiar tipos o packages.

## 1. Resultado normativo

Para una class concreta `C`, el field:

```aether
class C {
    Buffer<E> values;
}
```

es admisible en este perfil si y sólo si se cumplen todas estas condiciones:

1. el field es `private`, explícita o implícitamente;
2. `Buffer<E>` ya es un tipo válido bajo la única regla ordinaria de
   `Buffer` de la sesión;
3. `E` es concreto y tiene layout finito disponible para el target;
4. `E` satisface el predicado central vigente
   `is_admitted_buffer_element(E)`;
5. no viola una prohibición ortogonal vigente para todo class field, como el
   almacenamiento de function values en FUNCTION-VALUES-V1.

No se vuelve a expresar la condición como una lista de `TypeId`, nombres
nominales o packages. Resolver source y verificar metadata deben consultar la
misma autoridad de admisión. En particular, ninguna capa puede preguntar si
`E == int`.

La propiedad de paridad queda fijada así:

> Si el frontend ordinario admite el tipo concreto `Buffer<E>` y `E` satisface
> las restricciones ortogonales vigentes de class storage, un field privado no
> puede rechazarlo por el spelling, identidad nominal o package de `E`.

Este milestone no generaliza el conjunto de elementos de `Buffer`. Cuando un
vertical futuro amplíe correctamente el predicado central, class fields
heredarán esa ampliación sólo después de que layout, drop y verificadores sigan
siendo válidos; este documento no anticipa esa admisión.

## 2. Auditoría de la implementación vigente

La restricción a `int` aparece dos veces y ambas deben cambiar juntas:

| Capa | Estado actual | Decisión de esta arquitectura |
|---|---|---|
| resolución HIR, `hir.rs` | `narrow_buffer` exige literalmente `buffer_element(ty) == int` y field no público | reemplazar por la consulta central de admisión de class field |
| verificación de metadata, `oop.rs` | reconstruye la misma excepción literal a `int` | verificar de nuevo el mismo predicado general, sin confiar en HIR |
| propiedades de tipos, `types.rs` | todo `Buffer<E>` es non-Copy, Relocatable, needs-drop y Storable si `E` lo es | ya es genérico; no especializar |
| layout frontend | todo `Buffer<E>` ocupa el descriptor pointer + length | ya es genérico; usar su layout canónico |
| HIR class | `FieldWrite` conserva `FieldId`, tipo exacto e initialize/replace | ya es genérico para init/replacement |
| MIR | materializa ownership y verifica estado de construcción por field | ya usa tipo/`needs_drop`, no `int` |
| SSA class ledger | rastrea cualquier tipo para el que `buffer_element` existe | ya es genérico; el comentario “narrowly admitted” queda obsoleto |
| LLVM field write | carga el owner anterior, instala el nuevo y llama drop glue tipado | ya mangla el `Buffer<E>` concreto; no `int` |
| LLVM final release | recorre la receta tipada de fields y llama `aether_drop_*` | ya es genérico para cualquier `Buffer<E>` concreto |
| drop de `Buffer` | libera backing con size/alignment de `E`; no recorre elements | correcto sólo porque el predicado actual exige `E` no-drop |

Por tanto, layout, replacement, final release y constructor unwind ya transportan
un `TypeId` concreto y no dependen de que el element sea scalar. Quitar sólo el
`if` de HIR no basta: dejaría en desacuerdo al verificador independiente y no
resolvería el acceso por Place descrito en la sección 9.

El contador privado `aether_object_buffer_drop_count` es instrumentation de
qualification, no semántica ni ABI. Su nombre no autoriza una clasificación por
`E`. Los conteos normativos son owners adquiridos/destruidos y heap
allocations/frees; ningún branch de producción se agrega para un element kind.

## 3. Regla de element type

`Storable` por sí solo **no** es suficiente en el lenguaje actual. `string`,
class handles, `Array<T>`, `List<T>` y el propio `Buffer<T>` son Storable y
needs-drop, pero el drop de `Buffer<E>` vigente sólo libera el backing: no
destruye elements. Admitirlos aquí produciría leaks o lifecycle incompleto.

La regla efectiva actual para `E` es:

```text
valid(E)
and concrete(E)
and finite_layout(E)
and Copy(E)
and not needs_drop(E)
and not contains_reference(E)
and not contains_view(E)
and not contains_owning(E)
```

Se implementará consultando `is_admitted_buffer_element`, no duplicando esta
fórmula en class code. Todos los tipos admitidos son persistentemente
almacenables, pero `Storable` no reemplaza las condiciones adicionales de la
implementación actual de Buffer.

| `E` | Field `Buffer<E>` V1 | Motivo |
|---|:---:|---|
| `int`, demás integers, `uint8`, `float32`, `float64`, `bool`, `char` | sí | concrete Copy/no-drop scalar |
| struct nominal simple | sí | si todos sus fields derivan la regla central |
| struct Copy anidado | sí | derivación estructural, sin límite por nombre |
| enum sin payload | sí | Copy/no-drop y layout concreto |
| enum con payload | sí | si todos los payloads de todas las variants satisfacen la regla |
| instancia concreta de struct/enum genérico | sí | después de sustitución, si tiene propiedades/layout concretos |
| `T: Storable` simbólico | no | Storable no prueba Copy/no-drop ni concreción |
| `T: Copy` simbólico | no | `Buffer<T>` simbólico sigue fuera del perfil ordinario vigente |
| tipo con Drop, incluido aggregate que lo contiene | no | Buffer no tiene element drop glue vigente |
| `Buffer<U>`, `Array<U>`, `List<U>`, Vector/Matrix owner | no | owning substructure y needs-drop |
| `string`, class handle, interface handle | no | owner non-Copy/needs-drop |
| `ref U`, `ref mut U`, View/ViewMut y aggregates que los contienen | no | storage borrowed no persistible |
| function value o aggregate que lo contiene | no en este perfil | prohibición ortogonal de FUNCTION-VALUES-V1 para class fields |

La aceptación de un enum con payload no depende de que el payload “parezca
scalar”; depende sólo de sus propiedades estructurales y layout concreto. Esto
cubre directamente los payload enums Copy requeridos por graphics.

## 4. Visibility y encapsulación

`Buffer<E>` permanece permitido únicamente como field privado:

- `Buffer<E> values;`: privado por default y potencialmente admisible;
- `private Buffer<E> values;`: equivalente;
- `public Buffer<E> values;`: rechazado;
- `protected` e `internal` para members no existen en la gramática vigente y no
  se introducen aquí.

La razón no es el element kind. Un Buffer es un owner único y el acceso público
directo abriría extracción, replacement e interior borrows fuera del protocolo
de receiver de class. Los métodos públicos pueden exponer operaciones Copy o
comportamiento validado, no el descriptor owner.

Private se evalúa respecto de la class que declara el field. Una subclass no
obtiene acceso directo a un field privado del base. Herencia y orden de drop
existentes no cambian.

## 5. Inicialización definida

Un field `Buffer<E>` participa en el mismo análisis por `FieldId` que el actual
`Buffer<int>`:

- una class no vacía requiere `init`;
- bytes reservados por `ObjectAlloc` no cuentan como valor inicializado;
- cada path normal de `init` debe inicializar el field exactamente una vez antes
  de publicación;
- una lectura, indexación o replacement antes de esa primera escritura falla;
- joins deben concordar en el estado owning; un loop no puede ser el único que
  establezca la inicialización;
- el owner RHS se mueve al field; no se duplica el descriptor;
- la class sólo se publica después de completar todos los fields/base.

`Buffer<E>(0, fill)` es un Buffer ordinario válido y cuenta como field
inicializado. El fill conserva la evaluación y validación ordinarias de su
constructor aunque length sea cero. Length cero no es un sentinel de
“uninitialized” y su drop sigue ejecutándose exactamente una vez.

## 6. Replacement

Después de inicializado, dentro de un método `mut`:

```aether
values = newBuffer;
```

tiene este orden semántico:

1. evaluar completamente el RHS y obtener una obligación owning nueva;
2. conservar intacto el field si esa evaluación lanza;
3. mover el owner anterior a un cleanup temporal interno;
4. instalar el descriptor nuevo en el field;
5. marcar consumida la obligación del RHS;
6. destruir el owner anterior exactamente una vez.

La instalación precede al drop anterior, como en OOP-V1. No existe un hueco
observable, no hay deep copy, retain de Buffer ni runtime dependiente de `E`.
El drop de Buffer vigente es no-throwing y libera un backing usando el layout
concreto de `E`.

Dos owners Buffer legales no aliasan el mismo backing. `values = values` no se
convierte en un caso runtime: leer owning el field está prohibido. Un local ya
movido al field tampoco puede reutilizarse. HIR/MIR/SSA deben rechazar cualquier
IR que fabrique dos obligaciones para el mismo descriptor; el backend no agrega
comparación de pointers para encubrir IR inválido.

Si un futuro milestone admite extracción owning de fields, deberá rediseñar
self-assignment y partial moves antes de reutilizar esta secuencia.

## 7. Drop de class y exception safety

La última release del handle ejecuta la receta vigente:

1. fields propios que necesitan drop, en orden inverso de declaración;
2. fields del base según la receta de herencia vigente, derived antes que base;
3. un único free de la allocation completa del objeto.

Cada `Buffer<E>` llama al mismo drop glue tipado que usaría un owner local. En
este perfil sus elements son no-drop, por lo que se libera exactamente un
backing y no se recorren elements. La frase “semántica ordinaria de Buffer” es
deliberada: si Buffer obtiene elements con Drop en otro milestone, class no
inventará un segundo protocolo.

Ante una language exception durante `init`, `ConstructorUnwindPlan` y el estado
`initialized_fields` seleccionan sólo la subsecuencia ya inicializada de la
receta canónica. Esos fields se destruyen en orden inverso y la allocation no
publicada se libera. No se agrega bitmap runtime. Si el RHS inicial de un field
lanza, el field aún no está inicializado y no se toca. Si una operación posterior
lanza, el field ya instalado sí pertenece al rollback.

En replacement, una excepción durante el RHS deja vivo el owner anterior. Tras
el commit no hay operación throwing entre store y drop. Los traps abortivos
conservan la política global vigente; este milestone no promete unwind para
traps.

## 8. Representación y layout

Un field usa exactamente la representación canónica de un Buffer local:

```text
{ data: pointer, length: usize }
```

En Linux x86-64 ocupa 16 bytes, alignment 8. El object layout alinea el offset
del field con el alignment del descriptor, no con el de `E`. El backing sí usa
`size_of(E)` y `align_of(E)` para allocation/free e indexing.

No hay boxing del descriptor, allocation por field, vtable de element,
reflection, type tag runtime ni descriptor gráfico. El descriptor vive inline
en la única allocation del objeto. Un Buffer de length no cero mantiene, como
antes, una allocation separada sólo para su backing.

## 9. Acceso, indexing y borrowing

La auditoría encontró que el HIR Place vigente sólo proyecta fields de structs;
los class fields pasan por `ClassOp::FieldRead/FieldWrite`, y `FieldRead` rechaza
todo field non-Copy. Por eso generalizar admisión sin cerrar acceso dejaría un
owner almacenable pero no utilizable para copiar sus elements.

### 9.1 Acceso indexado inmediato admitido

Este V1 incluye una proyección de storage de class acotada a acceso inmediato:

```aether
class C {
    Buffer<Point> points;

    public int read(usize i) {
        return int(points[i].x);       // Copy read
    }

    public mut int write(usize i, Point p) {
        points[i] = p;                 // Copy write
        return 0;
    }
}
```

La raíz semántica conserva receiver + `FieldId`; luego reutiliza las
proyecciones ordinarias `Index` y `Field` y el bounds check ordinario de
`Buffer<E>`. Un read receiver permite sólo observación Copy. Escribir un element
o reemplazar el Buffer exige receiver `mut`. Durante `init`, sólo puede
indexarse después de la inicialización definida del field.

No se emite `ClassOp::FieldRead` de tipo `Buffer<E>` para esta operación. HIR
representa un `ClassFieldStoragePlace` (nombre ilustrativo) que no es un valor
owning. MIR lo baja a receiver/offset/projections preservando el tipo exacto;
SSA verifica que no aparezca un token owner adicional. LLVM obtiene la dirección
del slot, lee pointer/length sólo para el bounds check y el element address, y
completa load/store antes de abandonar la operación.

Todos los suboperands source (selector y valor Copy a escribir) se evalúan una
vez conforme al orden ordinario antes de la sección final sin calls que observa
descriptor y backing. El receiver tiene el keepalive normal de la llamada. Como
el target es single-threaded y la operación no produce una referencia, ningún
alias de clase puede intercalar un replacement entre obtener el backing y
completar el acceso.

Esto permite copiar prefijos entre un field y un Buffer local, implementar
growth por allocation/copy/replacement y retornar accessors Copy. No permite
pasar el Buffer field a una función consuming ni producir una View.

### 9.2 Borrows que siguen fuera

Continúan rechazados:

```aether
ref Buffer<Point> a = &points;
ref mut Buffer<Point> b = &mut points;
ref Point p = &points[i];
View<Point> v = view(points);
ViewMut<Point> w = view_mut(points);
```

Las classes tienen aliases ARC mutables y un método `mut` no es unique/noalias.
Un alias podría reemplazar el backing mientras una referencia o View escapara
de la operación, dejando provenance o storage inválidos. El keepalive del
objeto no mantiene vivo un backing reemplazado. Resolver esto requiere una
arquitectura general de interior borrows de class, no copiar el descriptor ni
agregar pinning/refcount por Buffer.

Por ello `ref field` y `ref mut field` no se “implementan” cargando `{ptr,len}`.
Conservan el diagnóstico de interior reference/owning field vigente. Cuando
exista una solución general deberá reutilizar Place/provenance, invalidar ante
replacement a través de aliases y no cambiar la representación aquí fijada.

## 10. Move y partial moves

Este milestone admite:

- mover un Buffer local o resultado fresco al field durante init;
- mover un Buffer local o resultado fresco para reemplazar el field;
- leer/escribir values Copy por indexing inmediato;
- reemplazar por un zero-length Buffer ordinario para vaciar storage.

No admite:

- lectura owning del field;
- mover el field a un local o return;
- mover directamente de un field a otro;
- dejar un field moved/uninitialized después de publicar la class;
- partial moves de class;
- destructuring owning del objeto.

Así, los methods son la única superficie de mutation/replacement y la class
permanece siempre completamente inicializada una vez publicada.

## 11. Generic classes

La gramática vigente no admite `class Holder<T>`. Por tanto:

```aether
class Holder<T> { Buffer<T> values; }
```

queda fuera de CLASS-BUFFER-FIELDS-V1. No se agrega monomorphization de class,
metadata paramétrica ni layout simbólico.

Sí debe funcionar:

```aether
struct Point { float64 x; float64 y; }

class Concrete {
    Buffer<Point> points;
    // ... init y methods ...
}
```

También entra `Buffer<Pair<int>>` u otra instancia concreta de struct/enum
genérico ya monomorphizada que satisfaga el predicado ordinario. Antes de MIR
el field y su element tienen `TypeId` y layout concretos.

## 12. Contrato HIR, MIR, SSA y LLVM

### HIR

- una consulta central devuelve admisión o motivo para todo class field;
- source resolution y `verify_class_metadata` recalculan esa decisión;
- `ClassOp::FieldWrite { initialize }` sigue siendo la única escritura del
  descriptor completo;
- `ClassFieldStoragePlace` conserva receiver, `FieldId`, tipo/projections,
  access mode y estado de init para indexing inmediato;
- nunca aparece `Load/FieldRead` owning de `Buffer<E>` para indexar;
- ownership synthesis consume el RHS una vez y conserva cleanup tipado.

### MIR

- preserva initialize contra replace y el constructor unwind plan;
- baja el place indexado sin crear un local owner para el descriptor;
- valida tipo exacto, receiver read/mut, privacidad, estado inicializado,
  projections y ausencia de borrow escape;
- replacement conserva evaluate/acquire, install, drop-old.

### SSA

- el ledger existente rastrea cualquier `Buffer<E>`, no sólo int;
- una escritura completa consume exactamente un token owner;
- un acceso indexado es observacional/Copy y no crea ni consume owner;
- joins, unwind y corruption tests demuestran ausencia de duplicate/drop/leak;
- metadata no confiable se vuelve a comparar con el `TypeId` concreto.

### LLVM

- recibe sólo tipos concretos post-monomorphization;
- usa `{ptr,i64}` y el offset/alignment verificados;
- llama el drop glue mangled de `Buffer<E>` en replacement, rollback y final
  release;
- acceso indexado calcula element address con layout de `E` y bounds ordinario;
- no decide capabilities, visibility, initialization ni ownership.

Quedan prohibidos allowlists por type/package, boxing, vtable, reflection,
runtime por `E`, opcode graphics y cualquier nombre especial de Point/Command.

## 13. Compatibility

Todo program actual con `Buffer<int>` conserva:

- el mismo TypeId estructural y descriptor físico;
- el mismo move/drop/replacement observable;
- los mismos offsets salvo cambios derivados únicamente de otros fields de su
  propia class;
- el mismo número de object/backing allocations y frees;
- la misma privacidad y prohibición de extracción/borrow;
- el mismo código genérico de Buffer después de monomorphization.

No cambian reglas de Array/List, Matrix/Vector, aggregates owning, class ARC,
interfaces, inheritance, exceptions, generic storage ni drop. Los tests
vigentes de esos subsistemas son gates, no ejemplos opcionales.

## 14. Qualification de implementación futura

El vertical de implementación agregará un fixture dedicado, preferentemente:

```text
compiler-next/crates/aether-driver/tests/class_buffer_fields_v1.rs
```

### Positivos mínimos

- `Buffer<int>`, `Buffer<uint8>`, `Buffer<float64>`;
- `Buffer<simple struct>` y `Buffer<nested Copy struct>`;
- enum sin payload y payload enum Copy;
- instancia concreta de aggregate genérico;
- length cero, init desde local y desde resultado fresco;
- read/write indexado inmediato y nested Copy field projection;
- replacement único y múltiple;
- class alias, releases intermedias y última release;
- init que lanza antes y después de inicializar el field;
- RHS de replacement que lanza, demostrando que el owner anterior sobrevive;
- herencia con fields Buffer en base/derived y drop order canónico;
- O0 y O2 con el mismo resultado y los mismos conteos lifecycle.

### Negativos mínimos

- field Buffer público;
- element needs-drop/owning, class/interface handle, string, ref/view y
  aggregates que los contengan;
- `T: Storable` y `T: Copy` simbólicos donde Buffer ordinario siga sin admitirlos;
- function-containing element bajo la frontera vigente;
- class genérica;
- field sin inicializar, lectura antes de init y estado divergente/loop;
- use-after-move del local transferido;
- extracción owning, return owning, field-to-field move y partial move;
- `ref field`, `ref mut field`, element ref, `view` y `view_mut`;
- indexed write desde read receiver y acceso privado externo.

### Lifecycle e IR

Los escenarios deben cerrar exactamente object alloc/destroy, backing
alloc/free y drops para init normal, partial unwind, replacement, scope exit,
alias + final release y múltiples replacements. Length cero no se usa para
ocultar un owner no inicializado.

Los dumps/corruptions de HIR, MIR y SSA deben probar:

- field metadata con element/type/offset alterado se rechaza;
- drop recipe omitida, duplicada o reordenada se rechaza;
- initialize convertido en replace y viceversa se rechaza;
- descriptor owning copiado para indexar se rechaza;
- token RHS duplicado o no consumido se rechaza;
- cleanup de unwind incorrecto se rechaza;
- access place con receiver, visibility, mutability o projection falsa se
  rechaza.

LLVM se inspecciona para descriptor inline, alignment correcto, drop glue
tipado, ausencia de heap object por field y ausencia de símbolos/branches
especiales por `E` o graphics.

### Gates de regresión

Además del fixture dedicado deben pasar los suites de Buffer, V11 aggregates,
V15–V17 capabilities/storage, Array/List, Matrix/Vector, OOP-V1/V2/V3,
OOP-OPT, exceptions y el contrato global. `Buffer<int>` se compara
explícitamente antes/después en O0/O2.

GRAPHICS-FOUNDATION-V1 sólo podrá retomarse después de cerrar esta
qualification. Sus tipos sirven como dogfood adicional, nunca como condición
de admisión.

## 15. Orden de implementación acordado

1. centralizar admisión/reason diagnostics de class fields y eliminar ambas
   comparaciones a `int`;
2. agregar positivos/negativos de tipos antes de tocar lowering;
3. representar y verificar el class-field storage place indexado, manteniendo
   prohibidos los borrows escapables;
4. preservar la proyección en MIR/SSA y extender corruptions independientes;
5. reutilizar layout, replacement, drop y unwind genéricos existentes;
6. verificar LLVM, counters y O0/O2 sin runtime nuevo;
7. ejecutar gates globales y actualizar contrato/README/reportes de
   implementación sólo entonces.

Hasta completar esos pasos, el estado de lenguaje sigue siendo el documentado
por OOP-V1: sólo `Buffer<int>` privado está admitido de hecho.
