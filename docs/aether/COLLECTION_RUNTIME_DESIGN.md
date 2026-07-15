# RFC: semántica, ownership y lifecycle de `Array<T>` y `List<T>`

Estado: **decisión aprobada; Fases 1 (objeto RC) y 2 (copia explícita) implementadas para Aether v1**,
15 de julio de 2026.

La representación RC, el lifecycle del handle, los cleanups de IR, la
destrucción final native y `Array/List.copy()` están activos. Slicing List,
iteración borrowed e igualdad native general continúan fuera de este cambio.

Esta RFC congela la semántica pública de `Array<T>` y `List<T>` en las áreas
indicadas. Es documentación de diseño: no afirma que AST, IR, SSA, LLVM, ABI o
runtime ya hayan migrado, y no modifica todavía la especificación normativa.

Documentos relacionados: [diseño general de colecciones](AETHER_COLLECTIONS_DESIGN.md),
[crecimiento de List](AETHER_LIST_GROWTH_DESIGN.md),
[baseline de migración Fase 0](COLLECTION_MIGRATION_BASELINE.md),
[lifecycle de valores](../compiler/VALUE_LIFECYCLE_DESIGN.md),
[runtime de strings](STRING_RUNTIME_DESIGN.md),
[sort de secuencias](AETHER_SEQUENCE_SORT_DESIGN.md),
[Vector/Matrix](AETHER_VECTOR_MATRIX_DESIGN.md) y
[paridad de backends](BACKEND_FEATURE_PARITY.md).

La baseline de Fase 0 es la fuente descriptiva del comportamiento observado
por backend y de los diagnósticos transitorios. Esta RFC continúa siendo el
contrato aprobado; la baseline no afirma que RC, ABI, slicing List, borrow o
igualdad native ya estén implementados.

## 1. Decisiones aprobadas

| Tema | Decisión para Aether v1 |
| --- | --- |
| `Array<T>` | Reference type mutable, de longitud fija. |
| `List<T>` | Reference type mutable, de longitud dinámica. |
| Asignación | Copia la referencia en O(1); no copia descriptor, buffer ni elementos. El resultado es aliasing. |
| Copia explícita | `copy()` crea descriptor y buffer nuevos y copia lógicamente los elementos. Es una copia estructural superficial respecto de referencias anidadas. |
| Parámetros | El parámetro recibe la misma referencia. Mutar el contenedor es visible para el caller; reasignar el binding local no lo es. |
| Returns | Entregan una referencia owned válida para el caller. No hacen deep copy implícita. |
| `const` | Restringe las operaciones permitidas a través de esa referencia; no congela globalmente el objeto. |
| Slicing | Copia independiente, 0-based, con límites semiabiertos `[start,end)` para Array y List. |
| `for-in` | Acceso borrowed read-only al elemento durante cada iteración, sin copia automática. |
| Igualdad | Estructural y ordenada; no compara identidad del contenedor. |
| Ownership interno recomendado | Handle `ptr` de una palabra a objeto heap con strong RC no atómico. |
| COW/deep copy | No hay copy-on-write ni copia profunda recursiva implícita. |

La terminología normativa es:

- **copiar la referencia** describe assignment, binding de parámetro y otras
  operaciones de handle;
- **aliasing** describe el resultado: dos o más referencias alcanzan el mismo
  contenedor mutable;
- **copiar el contenido** se reserva para `copy()`, slicing u otra operación
  que crea otro contenedor.

## 2. Alcance y no objetivos

Esta RFC define reference semantics, assignment, aliasing, `copy()`, parámetros,
returns, `const`, slicing, `for-in`, igualdad, representación interna recomendada,
lifecycle y composición con structs y colecciones anidadas.

No diseña ni implementa:

- un operador público de identidad;
- sintaxis `ref`, `mut`, `borrow` o equivalente;
- `deepCopy()`;
- copy-on-write;
- weak references o concurrencia;
- `Slice<T>` ni views;
- allocators públicos, GC o una ABI C estable;
- ownership de `Vector<T>` o `Matrix<T>`;
- una API de iteración mutable.

## 3. Estado actual inspeccionado

Esta sección describe el repositorio al aprobar la RFC, no el contrato final.
Que una conducta actual coincida con la decisión no implica que su ownership
sea completo ni que quede estabilizada sin la migración prevista.

### 3.1 Superficie y frontend

- `{...}` infiere `List<T>` sin tipo esperado y es target-typed a `List<T>` o
  `Array<T>` cuando existe contexto. `{}` requiere contexto.
- Array y List son tipos diferentes, 0-based y con bounds checks. Array tiene
  longitud fija; List mantiene `length`, `capacity` y crecimiento geométrico.
- El intérprete representa los contenedores mediante un valor Aether que
  contiene una lista Python mutable. Assignment, parámetros y returns de igual
  tipo comparten ese valor; por tanto ya exhiben aliasing.
- `copy()` crea hoy otro contenedor exterior. Las colecciones anidadas siguen
  compartidas, coherente con la copia estructural superficial aprobada.
- Copiar un struct conserva actualmente el alias de sus fields Array/List.
  Las classes conservan identidad por referencia.
- `const` se comprueba por la raíz sintáctica y no queda como dato de runtime.

### 3.2 IR, SSA, LLVM y runtime

La IR dispone de operaciones específicas para construcción, acceso, longitud,
Array slice y mutaciones de List. `IRListCopy`/`SSAListCopy` existe; Array copy
general aún no cruza todo el pipeline. `for-in` se baja actualmente a length,
índice y get por valor, no al borrow read-only aprobado.

La representación native actual ya usa handles `ptr` a headers heap:

```text
%AetherArray = { i64 length, ptr data }
Array<T>     = ptr al header

%AetherList  = { i64 length, i64 capacity, ptr data }
List<T>      = ptr al header
```

Assignment, phi, parámetros y returns copian el puntero, y los aliases de List
ven un cambio de `data` tras growth porque el header permanece estable. Sin
embargo, el handle todavía se clasifica como trivial: no hay retain/release del
contenedor, last-owner ni destrucción final del header y buffer. Los hooks ARC
de elementos están más avanzados que el lifecycle del contenedor.

### 3.3 Coincidencias y divergencias relevantes

| Área | Estado actual | Decisión v1 | Trabajo pendiente |
| --- | --- | --- | --- |
| Assignment | Comparte handle | Copia la referencia | Completar RC/lifecycle sin cambiar el resultado observable. |
| Parámetros | Mismo handle; mutación visible | Misma referencia | Formalizar ownership del binding y reassignment local. |
| Returns | Mismo handle sin ownership final completo | Referencia owned | Retain/transfer seguro y cleanup. |
| `copy()` | Copia exterior; cobertura desigual | Descriptor+buffer nuevos, copia lógica de T | Paridad E2E y rollback/lifecycle. |
| `const` | Restricción por raíz, parcial | Read-only a través de la referencia | Unificar diagnósticos y paths encadenados. |
| Array slice | Copy `[start,end)` E2E | Igual | Completo en Fase 3. |
| List slice | Copy `[start,end)` E2E | Igual | Completo en Fase 3. |
| `for-in` | Snapshot AST o get por valor según backend | Borrow read-only por vuelta | Unificar y prohibir mutación estructural. |
| Igualdad | Estructural AST; cobertura desigual | Estructural E2E | Implementar backends y alinear búsqueda. |
| Destrucción | No finaliza contenedor | Release y finalización al último owner | Implementación coordinada obligatoria. |

No debe activarse `destroy` mientras assignment siga copiando raw pointers sin
retain: esa mezcla causaría use-after-free o double free. Tampoco debe
describirse la futura migración como un rediseño total, porque parte de la
semántica observable ya coincide accidentalmente.

## 4. Reference semantics, assignment y aliasing

`Array<T>` y `List<T>` son objetos contenedor mutables con identidad interna.
Una variable contiene una referencia al objeto, no el descriptor inline.
Assignment copia esa referencia y produce aliasing.

Ejemplo normativo para List:

```aether
List<int> a = {1, 2, 3};
List<int> b = a;

b[0] = 100;
```

Resultado:

```text
a == {100, 2, 3}
b == {100, 2, 3}
```

La misma regla se aplica a Array:

```aether
Array<int> a = {1, 2, 3};
Array<int> b = a;

b[0] = 100;
```

Ambos bindings observan `{100, 2, 3}`. Assignment es O(1), no inspecciona `T`
y no ejecuta `copy()`.

No hay ownership único después de copiar la referencia. Un optimizador puede
elidir retains/releases balanceados o transferir un handle muerto, pero no
puede eliminar aliasing observable ni convertir assignment en copia de
contenido.

## 5. Copia explícita `copy()`

```aether
Array<T> b = a.copy();
List<T> b = a.copy();
```

`copy()` debe:

1. crear un objeto/descriptor distinto;
2. crear un buffer distinto cuando la longitud no es cero;
3. copiar lógicamente cada elemento mediante la semántica normal de `T`;
4. preservar orden y longitud;
5. no compartir ni el contenedor ni su buffer con el original;
6. dejar el original sin cambios;
7. devolver una referencia owned al nuevo contenedor.

Ejemplo normativo:

```aether
List<int> a = {1, 2, 3};
List<int> b = a.copy();

b[0] = 100;
```

Resultado:

```text
a == {1, 2, 3}
b == {100, 2, 3}
```

Lo mismo aplica a Array.

### 5.1 Semántica de copia de los elementos

| `T` | Efecto al copiar un elemento |
| --- | --- |
| Primitiva | Copia por valor. |
| Enum | Copia del valor nominal. |
| `string` | Copia del handle y retain del objeto inmutable ARC. |
| Struct | Copia recursiva por valor, aplicando la semántica de cada field. |
| Class/interface | Copia de la referencia; conserva identidad del objeto. |
| Array/List | Copia de la referencia; la colección anidada continúa compartida. |
| Callable | Copia del handle; futuras closures aplican su lifecycle. |

Por eso `copy()` es una **copia estructural superficial respecto de tipos de
referencia anidados**. No recorre ni clona todo el grafo de objetos. Para
independizar una colección anidada, el programa debe invocar `copy()` sobre esa
colección explícitamente. `deepCopy()` no forma parte de v1.

### 5.2 Capacidad de `List.copy()`

La garantía semántica es `result.capacity >= result.length`; sólo los primeros
`length` slots contienen elementos vivos. Capacity no participa en igualdad ni
es identidad pública. Antes de implementar la migración debe congelarse una de
estas políticas internas para todos los backends:

- preservar exactamente la capacity de origen; o
- reducirla a `length` (y usar cero para la lista vacía).

Fase 2 congela la segunda política: `List.copy()` usa `capacity = size`, y la
lista vacía usa cero. AST guarda el mismo dato en el objeto privado, IR lo
preserva semánticamente y el helper native inicializa length y capacity con el
mismo valor.

### 5.3 Estado implementado y rollback

AST e IR interpreter reservan un objeto y buffer nuevos, hacen `copy_init` de
cada elemento y, ante un error recuperable, destruyen en orden inverso el
prefijo ya inicializado antes de liberar buffer y objeto. Los contadores de
debug verifican esta ruta sin exponer identidad al lenguaje.

IR usa los builtins tipados `array_copy` y `list_copy`, con tipo nominal del
receiver, ubicación fuente y resultado owned. SSA conserva ambas allocations
con efectos. LLVM genera un helper especializado por `T` que recorre el rango
vivo y aplica retain recursivo a strings, handles anidados y fields de struct;
no usa `memcpy` como sustituto de copia lógica. El panic native actual termina
el proceso y no hace unwind: por ello no se afirma rollback observable ni
exception safety native hasta que exista una política de unwind.

Esta elección de rendimiento permanece abierta. Cualquiera de las dos conserva
tamaño, orden, independencia del buffer y complejidad O(n · copy(T)); no puede
variar accidentalmente entre backends.

### 5.3 Fallos y rollback

Si allocation o la copia de un elemento falla, la operación debe destruir el
prefijo ya inicializado y liberar buffer y descriptor nuevos. El original no
cambia y nunca se publica un contenedor parcialmente inicializado.

## 6. Parámetros

Un parámetro Array/List recibe la misma referencia que el caller. No hay copia
implícita del contenido ni se necesita sintaxis de borrow para explicar la
semántica pública de v1.

```aether
void mutate(List<int> xs) {
    xs.push(4);
}
```

Después de `mutate(values)`, `values` contiene el elemento nuevo. Mutar el
contenedor, sus elementos o su orden mediante `xs` es visible desde todos los
aliases.

El binding del parámetro sigue siendo local:

```aether
void replace(List<int> xs, List<int> other) {
    xs = other;
}
```

La asignación cambia únicamente qué referencia guarda el binding local `xs`.
No reemplaza la variable del caller y no copia contenidos.

Internamente, una llamada puede prestar el handle mientras el caller garantiza
su vida o hacer retain/release alrededor de la llamada. Esa elección ABI es
invisible; si el parámetro se reasigna o escapa, el compilador debe mantener una
referencia owned válida. No se introducen parámetros `ref`, `mut` o `borrow` en
esta fase.

## 7. Returns

```aether
List<int> identity(List<int> xs) {
    return xs;
}
```

El caller recibe otra referencia al mismo contenedor. El return debe producir
una referencia owned válida según el lifecycle interno; puede retener el handle
o transferir una referencia ya owned, pero no copia elementos.

```aether
List<int> build() {
    List<int> xs = {1, 2, 3};
    return xs;
}
```

El resultado puede transferirse, moverse o construirse directamente en destino.
El cleanup del local no debe invalidar la referencia devuelta. RVO/NRVO y move
son optimizaciones de ownership, no cambios a la semántica de referencia.

No existe deep copy implícita en returns. `return xs.copy()` es la forma
explícita de retornar un contenedor independiente.

## 8. `const` sobre una referencia

```aether
const List<int> xs = values;
```

`const` restringe la referencia `xs`; no congela el objeto globalmente. A
través de `xs` se prohíbe:

- reasignar el binding;
- `push`, `pop`, `insert`, `removeAt`, `clear`, `reverse`, `sort` u otra
  mutación estructural;
- set o reemplazo de elementos;
- mutación encadenada de value types almacenados.

Otro alias mutable puede cambiar el mismo contenedor y `xs` observa el cambio:

```aether
List<int> a = {1, 2, 3};
const List<int> b = a;

a.push(4);
```

`b` observa `{1, 2, 3, 4}`.

### 8.1 Ejemplos por clase de elemento

Primitivas y enums no pueden reemplazarse a través de la referencia const:

```aether
const List<int> values = source;
values[0] = 9; // error
```

Un struct es value type. La proyección conserva la restricción y no permite
mutar el valor almacenado:

```aether
const List<Transaction> transactions = source;
transactions[0].amount = 0.0; // error
```

Un string es inmutable y tampoco puede reemplazarse:

```aether
const Array<string> names = source;
names[0] = "Ana"; // error
```

Una class conserva identidad propia. `const` impide reemplazar el elemento de
la colección, pero no congela transitivamente la instancia referenciada salvo
que la futura regla de const para classes lo establezca:

```aether
const List<Account> accounts = source;
accounts[0] = other; // error: reemplaza el slot
// La mutabilidad interna de accounts[0] depende del contrato de Account.
```

Para una colección anidada, el slot exterior no puede reemplazarse. Obtener la
referencia interior copia normalmente ese handle; el contenedor interior no se
congela globalmente:

```aether
const List<List<int>> outer = source;
List<int> inner = outer[0];
inner.push(4); // permitido; outer[0] observa el cambio
outer[0] = inner.copy(); // error: reemplaza un slot a través de outer
```

Una expresión cuyo receptor sea directamente `const List<int>` o
`const Array<int>` no puede invocar sus mutadores. La frontera const sigue las
semánticas de los tipos: se propaga por value types, pero no es un freeze
transitivo de objetos reference type alcanzables.

## 9. Slicing

Para Array y List, la forma de dos límites es 0-based y semiabierta:

```aether
a[start:end]
```

Selecciona exactamente los índices que cumplen `start <= i < end`. Los bounds
válidos son `0 <= start <= end <= length` y la longitud del resultado es
`end - start`.

```aether
Array<int> a = {10, 20, 30, 40, 50};
Array<int> s = a[1:4];
```

`s` es `{20, 30, 40}`. `a[2:2]` produce un Array vacío.

Slicing:

- crea otro descriptor y otro buffer;
- copia lógicamente los elementos como `copy()`;
- preserva orden;
- no comparte contenedor ni buffer con el original;
- permite mutar el resultado sin cambiar el original;
- devuelve el mismo tipo de colección que el receiver.

No existe `Slice<T>` público en v1 y una implementación no puede ocultar una
view bajo `Array<T>` o `List<T>`.

Desde la Fase 3, Array y List usan `[start,end)` en AST, IR y native. Ambos
crean un objeto y buffer exteriores independientes, ejecutan `copy_init` por
elemento y devuelven una referencia owned. Steps, índices negativos, límites
abiertos y slice assignment permanecen fuera del lenguaje.

## 10. Iteración `for-in`

La variable de iteración es un acceso **borrowed read-only** al elemento actual,
no una copia lógica automática:

```aether
for item in transactions {
    println(item);
}
```

Contrato:

- no se ejecuta copy/retain de `T` sólo por comenzar una iteración;
- `item` no puede usarse para reemplazar o mutar el elemento;
- el borrow no puede escapar, almacenarse ni retornarse;
- el borrow termina al final de esa iteración;
- asignar `item` a una variable normal copia según la semántica de `T`;
- toda mutación estructural del contenedor iterado está prohibida;
- cualquier reallocation durante el loop está prohibida.

```aether
for item in transactions {
    item.amount = 0.0;
}
```

Debe ser error: `item` es read-only. Para modificar elementos se usa hoy una
operación indexada permitida fuera de la región de iteración, o una futura API
de iteración mutable explícita que esta RFC no diseña.

El borrow implícito es semánticamente invisible salvo por la prohibición de
mutación/escape. Por ejemplo, `Transaction local = item` copia el struct por
valor; `List<int> local = item` copia una referencia si el elemento es una List;
`string local = item` retiene el string. No se agrega sintaxis nueva.

## 11. Igualdad

`a == b` para dos Array o dos List compatibles es igualdad estructural y
ordenada:

1. compara longitud;
2. compara los elementos en orden;
3. usa la igualdad semántica de `T` para cada par;
4. corta en la primera diferencia.

No compara dirección del descriptor, dirección del buffer, capacity, allocator
ni cantidad de aliases. Por tanto:

- dos contenedores diferentes con el mismo contenido son iguales;
- dos aliases son iguales;
- mutar mediante un alias cambia el valor que ambos observan;
- nested collections se comparan estructuralmente;
- strings comparan contenido;
- `NaN` conserva IEEE-754, incluido `NaN != NaN`;
- classes usan la igualdad que Aether defina para ellas;
- si `T` no soporta igualdad, la colección tampoco.

`contains` e `indexOf` deben usar la misma igualdad de `T`, no identidad
accidental. Esta RFC no expone un operador público de identidad del contenedor.

## 12. Representación y ownership internos recomendados

Dado que Array/List son reference types mutables, la representación principal
es un handle de una palabra a un objeto heap:

```text
ArrayObject<T> {
    strong_count
    length
    buffer
    element metadata/hooks
}

ListObject<T> {
    strong_count
    size
    capacity
    buffer
    element metadata/hooks
}
```

Los campos son conceptuales y no fijan una ABI pública. El compilador puede
monomorfizar hooks, separar metadata o empaquetar allocations si preserva:

- el valor público del handle es un `ptr` copiado por valor;
- strong RC es no atómico en v1;
- assignment, parámetros y returns copian o transfieren el handle;
- el buffer pertenece al objeto contenedor;
- todos los aliases observan el mismo descriptor y buffer actual;
- growth de List puede reemplazar el buffer dentro del objeto estable;
- el último release destruye elementos, buffer y objeto exactamente una vez;
- no hay COW ni owner único después de copiar la referencia.

Una implementación con header y buffer en allocations separadas es válida. Una
allocation combinada también lo es si growth, alineación y hooks conservan el
contrato. Identidad interna no participa en `==`.

### 12.1 Comparación con un GC futuro

Un GC puede reemplazar el strong RC y encargarse de la vida de descriptor y
buffer sin cambiar:

- assignment como copia de referencia;
- aliasing y mutación compartida;
- `copy()`/slicing como contenedores independientes;
- igualdad estructural;
- const por referencia;
- invalidación de borrows por mutación estructural.

El GC no convierte `copy()` en assignment, no introduce COW y no define por sí
solo finalización determinista de elementos/resources. Por eso el handle de una
palabra y la semántica pública pueden permanecer estables.

## 13. Lifecycle del handle de colección

Este lifecycle describe el handle reference type, no la copia de contenido:

### `init_default`

Crea o referencia un contenedor vacío válido. La estrategia exacta —singleton
vacío inmortal o allocation por instancia— permanece abierta, pero el valor
debe admitir todas las operaciones válidas del tipo.

### `copy_init`

Retiene el objeto contenedor y copia el handle. No copia elementos, descriptor
ni buffer.

### `move_init`

Transfiere el handle sin retain y deja la fuente en un estado vacío válido que
pueda destruirse de forma segura.

### `assign`

Retiene primero el handle nuevo, reemplaza el destino y libera después el
anterior. Debe ser segura ante self-assignment.

### `destroy`

Hace release. Cuando strong count llega a cero:

1. destruye exactamente una vez los elementos vivos;
2. libera el buffer;
3. libera el objeto contenedor.

Para List, `[0,size)` es el rango vivo; `[size,capacity)` no contiene valores
que deban destruirse.

### `relocate`

Mueve bitwise el handle, invalida la fuente y no hace retain/release. Sólo es
válido cuando termina la vida de la fuente.

La distinción central es:

```text
copy_init del handle de colección != método copy()
```

`copy_init` comparte el mismo contenedor y produce aliasing. `copy()` crea otro
contenedor y copia lógicamente sus elementos.

## 14. Structs con fields colección

Los structs continúan siendo value types, pero copiar un struct aplica la
semántica propia de cada field:

```aether
struct State {
    List<int> values;
}

State a = State({1, 2, 3});
State b = a;
b.values.push(4);
```

La copia de `State` copia la referencia del field `List<int>`. `a.values` y
`b.values` son aliases y ambos observan `{1, 2, 3, 4}`. Copiar un struct no hace
deep copy de los objetos referenciados.

Para independizar la lista interna se construye el destino con copia explícita,
usando la forma de construcción real disponible:

```aether
State b = State(a.values.copy());
```

Un field Array sigue la misma regla. `const State` propaga read-only por sus
fields value; el field reference conserva la semántica const aplicable a la
referencia obtenida a través de ese path.

## 15. Colecciones anidadas

Para `List<List<int>>` o `Array<List<int>>`, assignment comparte el contenedor
exterior. El `copy()` del exterior crea descriptor y buffer exteriores nuevos,
pero cada elemento `List<int>` se copia como referencia.

```aether
List<int> inner = {1, 2};
List<List<int>> a = {inner};
List<List<int>> b = a.copy();

b[0].push(3);
```

`a` y `b` son contenedores exteriores distintos, pero `a[0]` y `b[0]` apuntan
a la misma lista interior; ambos observan `{1, 2, 3}`. Para una copia profunda
específica, el programa debe copiar cada nivel intencionalmente.

El mismo principio se aplica a structs con fields class, callables y cualquier
otro reference type: los value types se copian por valor y los reference types
copian su referencia.

## 16. Array frente a List

Comparten reference semantics y lifecycle del handle, pero no son el mismo tipo
ni se convierten implícitamente.

### `Array<T>`

- longitud fija durante la vida del objeto;
- elementos reemplazables si la referencia no es const;
- sin `push`, `pop`, `insert` o `removeAt`;
- slicing copying;
- no expone capacity dinámica;
- permite optimizaciones futuras para storage matemático sin convertirse en
  `Vector<T>` o `Matrix<T>`.

“Longitud fija” no impide reasignar un binding mutable a otra referencia Array
de longitud diferente; impide cambiar la longitud del objeto Array existente.

### `List<T>`

- `size`/`length` dinámica y `capacity >= size`;
- `push`, `pop`, `insert`, `removeAt`, `clear` y growth;
- reallocation puede cambiar `buffer`, no el objeto que comparten los aliases;
- referencias/borrows de elementos se invalidan según la mutación estructural;
- `reserve`, `shrinkToFit` y capacity pública quedan para diseño posterior.

## 17. Complejidad

Sea `C(T)` el coste de copia lógica, `A(T)` el de assign, `D(T)` el de destroy,
`E(T)` el de igualdad y `k` la longitud de un slice.

| Operación | Array | List |
| --- | ---: | ---: |
| assignment / copia de referencia | O(1) | O(1) |
| `copy()` | O(n · C(T)) | O(n · C(T)) |
| igualdad | O(n · E(T)) worst-case | O(n · E(T)) worst-case |
| get borrowed interno | O(1) | O(1) |
| get a variable normal | O(C(T)) | O(C(T)) |
| set | O(A(T)) | O(A(T)) |
| slice | O(k · C(T)) | O(k · C(T)) |
| `push` | — | O(C(T)) amortizado; O(n) relocation worst-case |
| `pop` | — | O(move(T)) |
| `insert` | — | O(n) + lifecycle de T |
| `removeAt` | — | O(n) + lifecycle de T |
| `clear` | No es operación estructural de Array | O(n · D(T)) |
| destroy del último owner | O(n · D(T)) | O(n · D(T)) |
| `for-in` | O(n), sin copia automática de T | O(n), sin copia automática de T |

Retain/release de la referencia es O(1). La tabla distingue deliberadamente la
copia de referencia de la copia de contenido.

## 18. Impacto de implementación

| Capa | Coincidencia existente | Migración requerida |
| --- | --- | --- |
| Parser/sintaxis | Tipos, literales y operaciones ya existen. | Ninguna sintaxis nueva. |
| Typechecker | Const por raíz y aliasing básico ya aparecen. | Const consistente, borrow de loop, prohibición de escape/mutación e igualdad comparable. |
| Intérprete AST | `CollectionObject` modela RC, copy y slice semiabierto. | For-in sin snapshot divergente. |
| IR/SSA | `array_slice`/`list_slice` son allocations con lectura y posible panic. | Borrow read-only e igualdad. |
| LLVM/runtime | Header heap, buffer y aliasing ya existen. | Strong RC, final release, rollback y hooks de elemento completos. |
| ABI interna | `ptr` por valor ya coincide con el handle propuesto. | Convenciones owned/borrowed/transfer y cleanup; no se declara ABI pública. |
| Slicing | Array/List coinciden E2E con `[start,end)`. | Sin views, steps ni optimizaciones avanzadas. |
| Búsqueda/igualdad | Cobertura parcial y alguna identidad accidental. | Una sola semántica de Eq(T) en todos los backends. |
| Dogfood | Expense Tracker depende de mutación por parámetros y ya coincide. | Verificar lifetime y paridad sin cambiar su resultado. |

Los diagnósticos de migración deben distinguir dependencia válida del aliasing
aprobado de errores de const, escape de borrow o mutación durante iteración. No
se debe advertir que assignment comparte: ahora es el contrato, no una conducta
accidental a eliminar.

## 19. Alternativas rechazadas

- **Value semantics con copia implícita:** convierte assignment, fields y
  returns en operaciones O(n), contradice la identidad mutable aprobada y
  rompe código que comparte estado intencionalmente.
- **Ownership único sin aliasing:** no representa la decisión aprobada y
  requeriría moves/borrows observables en la sintaxis o diagnósticos.
- **Move-only:** empeora la ergonomía general y prohíbe la copia barata de una
  referencia válida.
- **Copy-on-write:** hace que una mutación pueda asignar y separar silenciosamente,
  añade uniqueness checks y cambia la visibilidad de mutaciones entre aliases.
- **Deep copy recursivo:** no preserva identidad de classes, requiere resolver
  ciclos/resources y tiene coste impredecible.
- **Views ocultas bajo Array/List:** hacen que slicing introduzca aliasing sin
  expresarlo y complican lifetime e invalidación.
- **Const global del objeto:** congelaría todos los aliases y exigiría tracking
  global/capabilities; v1 restringe cada referencia.
- **Copiar cada elemento en `for-in`:** añade `copy_init`/retain y coste no
  requerido para una lectura; el borrow read-only es suficiente.
- **Bounds inclusivos de slicing:** divergen del Array existente y hacen menos
  composable la longitud `end - start` y el slice vacío `[i:i)`.
- **Tratar assignment y `copy()` como equivalentes:** borra la distinción entre
  copia O(1) de referencia y copia O(n) de contenido.
- **Identidad como igualdad:** dos secuencias con el mismo contenido deben ser
  iguales aunque sus contenedores sean diferentes.

## 20. Detalles todavía abiertos

Estas decisiones no reabren la semántica aprobada:

- singleton vacío inmortal frente a objeto vacío asignado por instancia;
- preservar capacity exacta o reducirla a length en `List.copy()`;
- forma futura de iteración mutable;
- posible operador/API pública de identidad;
- weak references;
- strong RC atómico o estrategia de concurrencia futura;
- allocators y arenas;
- `reserve`, `shrinkToFit` y exposición de capacity;
- diseño de `Slice<T>` y views con lifetime/strides;
- ownership independiente de Vector/Matrix;
- sustitución futura de RC por GC;
- posible diseño futuro de step, sin compatibilidad implícita con la forma eliminada.

## 21. Extensiones futuras

Pueden diseñarse después, sin alterar la base v1:

- `Slice<T>` explícito y views strided;
- iteradores mutables con invalidación verificable;
- `deepCopy()` mediante protocolos explícitos por tipo, si existe una necesidad
  demostrada;
- weak references e identidad pública;
- RC thread-safe, ownership estático o GC;
- custom allocators/arenas;
- `reserve`, `shrinkToFit`, builders y algoritmos de stdlib;
- hashing, Map/Set y protocolos de igualdad;
- representaciones especializadas de Array para kernels, manteniendo la
  semántica pública.

## 22. Plan de implementación y estado

### Fase 0 — congelar y caracterizar

- congelar esta RFC y enlazarla desde el alcance v1;
- agregar después tests de caracterización de aliasing, copy, const, slices,
  loops y Eq(T);
- preparar diagnósticos de mutación/escape en `for-in` y caracterizar slicing List;
- auditar retains/releases actuales sin habilitar frees finales.

### Fase 1 — objeto RC y lifecycle del handle

- introducir strong count no atómico para Array/List;
- implementar `init_default`, `copy_init`, `move_init`, `assign`, `destroy` y
  `relocate` del handle;
- coordinar locals, fields, assignment, parámetros, returns y cleanup;
- validar self-assignment, empty, last-owner y paths de error.

### Fase 2 — copia explícita y composición

- llevar `copy()` de Array/List a todos los backends;
- copiar elementos con hooks de T y rollback;
- cubrir nested collections y structs con fields colección;
- congelar y probar la política de capacity de List copy.

### Fase 3 — slicing copying semiabierto (completa)

- conservar Array `[start,end)`;
- migrar List a `[start,end)` E2E;
- rechazar step, rangos abiertos e índices negativos;
- usar copia lógica y rollback de T.

### Fase 4 — const consistente

- aplicar read-only a través de la referencia en todos los paths;
- distinguir value paths de objetos reference type alcanzados;
- unificar diagnósticos AST/native.

### Fase 5 — `for-in` borrowed read-only

- bajar el acceso sin copia/retain automático;
- terminar el borrow por iteración;
- prohibir escape, mutación del elemento y mutación estructural/reallocation del
  iterable;
- dejar la iteración mutable para otra RFC.

### Fase 6 — igualdad y APIs derivadas

- implementar igualdad estructural ordenada E2E;
- hacer que `contains`/`indexOf` usen Eq(T);
- cubrir NaN, strings, structs, classes admitidas y nested collections.

El primer bloque recomendado es **Fase 0 seguida de Fase 1**. RC y destrucción
del contenedor deben activarse como un cambio coordinado: habilitar solamente
el release final sobre handles que todavía no retienen sería inseguro.

## 23. Resumen normativo

Array y List son reference types mutables. Assignment copia la referencia y
produce aliasing; `copy()` y slicing crean contenedores y buffers independientes
mediante copia lógica superficial de elementos. Parámetros reciben la misma
referencia, mientras returns entregan una referencia owned. `const` limita las
operaciones a través de un alias sin congelar el objeto globalmente. Slicing es
`[start,end)`. `for-in` presta cada elemento read-only sin copia automática.
Igualdad compara contenido en orden, nunca identidad.

La representación recomendada es un handle `ptr` a objeto heap con strong RC
no atómico. `copy_init` retiene ese objeto; el método `copy()` crea otro. Esta
distinción, junto con la destrucción exacta al último release, es la base de la
migración futura y no describe todavía una implementación completada.
