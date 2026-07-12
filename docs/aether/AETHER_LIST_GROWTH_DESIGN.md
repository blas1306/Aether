# Aether List Growth Design

## Estado y alcance

Este documento define el contrato de crecimiento dinamico de `List<T>` y la
semantica de `push`, `pop`, `insert`, `removeAt`/`remove_at` y `clear`.
Las Fases 4a (`clear`), 4b (`push` y reserve/growth interno) y 4c (`pop`) estan
implementadas en frontend, interpretes, IR, SSA, optimizadores y LLVM.
`insert`, `removeAt`, shrinking, reserva publica y gestion general de memoria
permanecen como diseno futuro.

El contrato publico de listas ya definido en
[`AETHER_V0_SPEC.md`](AETHER_V0_SPEC.md), las reglas generales de aliasing de
[`MUTABLE_AGGREGATES.md`](../compiler/MUTABLE_AGGREGATES.md) y el layout LLVM
registrado en
[`LIST_BACKEND_AUDIT.md`](../compiler/LIST_BACKEND_AUDIT.md) siguen siendo
normativos. Este documento concreta como preservarlos cuando una mutacion
cambia la longitud o reemplaza el buffer.

## Layout e identidad

El layout LLVM de v0 permanece:

```llvm
%AetherList = type {
    i64 length,
    i64 capacity,
    ptr data
}
```

Un valor `List<T>` transporta un puntero al header, no el header por valor. El
header y el buffer son allocations conceptualmente distintas:

```text
alias a ----+
            +--> header { length, capacity, data } --> buffer de T
alias b ----+
```

La identidad observable de una lista es la direccion de su header. Esa
direccion es estable durante toda la vida de la lista. Una realocacion puede
cambiar `header.data`, pero nunca reemplaza el header ni actualiza solamente
uno de sus aliases.

```aether
List<int> a = {1, 2};
List<int> b = a;

b.push(3);

// a y b conservan el mismo header; ambos observan length == 3.
```

Asignacion, paso de parametros y return copian el puntero al mismo header
cuando no hace falta convertir el tipo de elemento. Reemplazar el header al
crecer dejaria aliases apuntando al objeto anterior y violaria esta semantica.
Una copia explicita con `copy()` si crea otro header y otro buffer.

## Invariantes

Para todo header valido se cumplen simultaneamente:

1. `0 <= length <= capacity`.
2. `data == null` si y solo si `capacity == 0` en la representacion canonica
   de v0. En particular, `capacity > 0` implica `data != null`.
3. Los elementos logicamente validos ocupan exactamente el rango
   `[0, length)`.
4. El rango `[length, capacity)` es capacidad disponible. Sus bytes pueden
   contener representaciones residuales, pero no son elementos logicos y no
   pueden leerse, recorrerse ni destruirse como tales.
5. Todos los aliases de una misma lista apuntan al mismo header.
6. La direccion del header no cambia. `data` puede cambiar solo mediante una
   operacion de reserva o crecimiento valida.
7. `capacity * element_size` debe ser representable por el tipo de tamano que
   consume el allocator. Ningun calculo de longitud, capacidad o bytes puede
   hacer wraparound.

Durante una operacion interna puede existir un buffer nuevo todavia no
publicado. Sin embargo, el header observable debe contener un estado valido
hasta el commit de la realocacion y volver a satisfacer todos los invariantes
al retornar o antes de reportar un error.

## Capacidad inicial

La representacion canonica de un literal vacio es:

```aether
List<int> empty = {};
```

```text
length = 0
capacity = 0
data = null
```

La representacion de un literal no vacio con `n` elementos es:

```aether
List<int> xs = {1, 2, 3};
```

```text
length = n
capacity = n
data = buffer con exactamente n slots
```

No se reserva una capacidad minima oculta para v0. Reservar, por ejemplo,
cuatro u ocho slots para `{}` ahorraria allocations en listas pequenas, pero
haría que todo literal vacio consumiera memoria, impediria la representacion
canonica `data = null` y agregaria una constante de ABI/politica sin evidencia
de workloads que la justifiquen. Empezar en cero mantiene literal y runtime
simples; la primera insercion reserva un slot. La politica puede ajustarse en
el futuro sin cambiar la semantica publica, siempre que no se exponga
`capacity` como garantia de lenguaje.

## Politica de crecimiento

Antes de una operacion que agregue elementos se calcula `required_length`. Si
`required_length <= capacity`, se conserva el buffer. Si hace falta crecer:

```text
growth_capacity = 1                  si capacity == 0
growth_capacity = capacity * 2       en otro caso

new_capacity = max(required_length, growth_capacity)
```

La formula admite futuras operaciones internas que reserven mas de un
elemento. Con esta politica, una secuencia de `push` tiene costo amortizado
`O(1)`; una operacion que crece copia `length` elementos y cuesta `O(n)`. La
capacidad reservada es `O(length)`.

### Overflow

El runtime debe rechazar, antes de llamar al allocator, cualquiera de estos
casos:

- `length + added_count` no es representable o excede el maximo admitido;
- `capacity * 2` no es representable;
- `new_capacity * element_size` no es representable por `i64` o por el
  `size_t` efectivo del target;
- `element_size` es cero o inconsistente con `T`; o
- el tamano solicitado excede un limite explicito del runtime/allocator.

No se permite saturar silenciosamente ni aceptar wraparound. Al duplicar, si
la multiplicacion no es representable pero `required_length` aun pudiera
serlo, una implementacion puede usar exactamente `required_length`; aun asi
debe validar el producto en bytes. Si el request final no es representable, el
runtime termina con un diagnostico claro de overflow de capacidad.

## Reserva y realocacion

`reserve(list, required_length, element_size)` es conceptualmente
transaccional:

1. Validar el header y `element_size` en builds que habiliten checks internos.
2. Calcular y validar `required_length` sin overflow.
3. Retornar sin cambios si `required_length <= capacity`.
4. Calcular `new_capacity` y el tamano del buffer, con todos los checks de
   overflow anteriores.
5. Reservar un buffer nuevo. Un resultado nulo para un request no nulo es un
   fallo fatal controlado, no un buffer valido.
6. Copiar superficialmente los `length` elementos validos al buffer nuevo.
7. Publicar `data = new_data` y `capacity = new_capacity` en el mismo header.
8. Liberar el buffer reemplazado cuando el runtime sea inequívocamente su
   owner. La implementacion debe ordenar publish/free de modo que ningun camino
   posterior use el buffer anterior.

El paso 7 es el commit: si allocation falla, el header conserva el buffer,
longitud y capacidad anteriores. `length` no cambia durante `reserve`.

`realloc` puede implementar el mismo contrato si preserva el buffer anterior
en caso de fallo, valida primero todos los tamanos y solo escribe el puntero
devuelto tras el exito. Una estrategia explicita `malloc + copy + free` es mas
facil de razonar inicialmente. En ambos casos, solo cambia el puntero `data`;
el header nunca se realoca.

Una mutacion que recibe `value` debe evaluarlo y copiar su representacion a un
temporal estable antes de llamar a `reserve` o desplazar slots. Esto cubre
casos donde el valor procede del buffer de la propia lista: crecer no debe
invalidar el origen antes de copiarlo.

La operacion publica actualiza `length` al final, una vez que reserva,
desplazamientos y escritura del nuevo elemento terminaron. Asi, un fallo antes
del commit de la mutacion no publica un slot parcialmente inicializado como
elemento valido.

## Fallos de memoria y errores runtime

La politica inicial del backend LLVM es un helper de panic del runtime que:

- emite un diagnostico determinista que distingue allocation, overflow,
  lista vacia e indice fuera de rango;
- termina el programa con estado no exitoso; y
- nunca retorna al codigo que asumiria que la operacion tuvo exito.

No se ignora un `malloc`/`realloc` nulo y no se deja un header parcialmente
actualizado. Excepciones recuperables de allocation o resultados especiales
quedan para una fase posterior, cuando exista un modelo general de excepciones
y unwinding para el backend.

## Ownership sin GC

Aether aun no tiene GC, conteo de referencias ni ownership completo en LLVM.
El diseno distingue tres capas:

- **Header:** representa la identidad compartida por los aliases. Su lifetime
  no puede deducirse liberando un alias individual.
- **Buffer:** allocation interna apuntada por un unico header. El runtime puede
  reemplazarla y liberar la anterior si conoce que ese header es su owner
  exclusivo.
- **Elementos reference-type:** son handles/punteros almacenados
  superficialmente. La lista no adquiere ownership recursivo de los objetos a
  los que apuntan.

Hasta contar con gestion de lifetime, headers y su ultimo buffer pueden fugar
al terminar su vida util. Es deuda tecnica aceptada solo para el backend
experimental y debe permanecer registrada. En cambio, una realocacion deberia
liberar el buffer sustituido si todos los buffers de lista tienen procedencia y
ownership runtime compatibles. Si hoy no se puede demostrar esa propiedad
para todos los constructores, es preferible filtrar temporalmente el buffer
viejo a introducir double-free o liberar memoria no poseida.

`pop`, `removeAt` y `clear` no liberan ni destruyen recursivamente elementos
reference-type. Un GC futuro debera decidir si limpia slots fuera de
`[0, length)` para evitar retencion conservadora; esa decision no cambia la
semantica logica de v0.

## Semantica de los metodos

Las formas de metodo y builtin global deben converger al mismo lowering y al
mismo contrato. Todos los indices son 0-based.

### `push(value) -> void`

Estado Fase 4b: implementado mediante `IRListPush` y `SSAListPush`, ambas sin
resultado y side-effecting. LLVM valida `length + 1`, llama al helper interno
`aether_list_reserve(list, required_capacity, element_size)`, vuelve a cargar
`data`, escribe el nuevo elemento y publica `length` al final. El helper usa
exactamente `0 -> 1` o duplicacion y `max(required, grown)`, valida overflow de
duplicacion y tamaños en bytes, y termina con panic claro ante overflow u OOM.
Tras reservar y copiar con exito libera el buffer anterior, actualiza `data` y
`capacity` en el mismo header y conserva shallow-copy para referencias.

1. Evaluar `value` y materializar una representacion estable asignable a `T`.
2. Validar `required_length = length + 1`.
3. Crecer si `required_length > capacity`.
4. Escribir `value` en el slot del antiguo `length`.
5. Publicar `length = required_length`.

Agrega al final, conserva la identidad del header y puede cambiar `data` y
`capacity`. Su costo es `O(1)` amortizado y `O(n)` worst-case cuando crece.

### `pop() -> T`

Estado Fase 4c: implementado mediante `IRListPop(result, list)` y
`SSAListPop(result, list)`, ambas side-effecting y con resultado `T`.
Requiere `length > 0`; una lista vacia produce error runtime. Captura el valor
de `data[length - 1]`, publica `length - 1` y devuelve el valor capturado. No
reduce capacidad ni libera el buffer. Su costo es `O(1)`.

El orden seguro es cargar `length`, comprobar cero, calcular `new_length`,
cargar `data[new_length]`, escribir `length = new_length` y devolver la carga.
La lectura ocurre antes de reducir la longitud y antes de cualquier posible
underflow. `capacity`, `data` y la identidad del header no cambian. El slot en
`data[new_length]` queda logicamente muerto fuera de `[0, length)` y no se
limpia mientras no exista una politica de GC. Para reference-types se devuelve
el mismo handle almacenado, sin deep copy ni destruccion recursiva.

La decision normativa es devolver `T`, consistente con el frontend y la spec
actuales y util para consumir el elemento retirado. Aunque el resultado no se
use, la mutacion sigue siendo observable.

### `insert(index, value) -> void`

Acepta exactamente `0 <= index <= length`; fuera de ese rango produce error
runtime. `index == length` es semanticamente equivalente a `push(value)`.

Tras evaluar y estabilizar `value`, valida `length + 1`, crece si hace falta,
desplaza el rango `[index, length)` un slot a la derecha, escribe el valor en
`index` y actualiza `length` al final. El desplazamiento debe tener semantica
de `memmove`, no `memcpy`, porque origen y destino se solapan. Cuesta `O(n)` en
el caso general y puede incluir una realocacion `O(n)`.

### `removeAt(index) -> T`

Requiere exactamente `0 <= index < length`; fuera de rango produce error
runtime. Captura `data[index]`, desplaza `[index + 1, length)` un slot a la
izquierda con semantica de `memmove`, publica `length - 1` y devuelve el valor
capturado. No reduce capacidad ni libera el buffer. Cuesta `O(n)`.

La decision normativa es devolver `T`, por consistencia con `pop()` y con el
frontend/spec existentes. El valor debe residir en un temporal independiente
antes del desplazamiento para no sobrescribirlo.

### `clear() -> void`

Publica `length = 0` y conserva `capacity`, `data`, header e identidad. No
libera el buffer, no mueve elementos y no destruye recursivamente referencias.
Todos los aliases observan inmediatamente la lista vacia y una insercion
posterior puede reutilizar la capacidad. Es `O(1)` bajo el modelo v0 sin
destructores.

Estado Fase 4a: implementado mediante `IRListClear` y `SSAListClear`, ambas
instrucciones sin resultado y con side effects. En LLVM baja directamente a
un acceso al campo 0 del header y `store i64 0`; no usa helper, allocator ni
`free`, y no accede a los campos `capacity` o `data`.

## Shrinking

V0 nunca reduce automaticamente capacidad en `pop`, `removeAt` ni `clear`.
Esto evita allocation thrashing en patrones de quitar/agregar y hace que esas
operaciones no fallen por allocation. No existe `shrinkToFit()` en v0.

Un futuro `shrinkToFit()` seria una operacion explicita, potencialmente
fallable, que preserva el header y podria establecer `capacity = length`; para
una lista vacia podria liberar el buffer y restaurar el estado canonico
`capacity = 0, data = null`. Requiere un diseno separado de errores y
ownership.

## Elementos reference-type y copia superficial

Reserva, crecimiento y desplazamientos copian la representacion almacenada de
`T`. Para strings, listas anidadas, arrays, clases u otros tipos representados
por handle/puntero, solo se mueve o copia ese handle. No hay deep copy:

```aether
List<int> inner = {1};
List<List<int>> xs = {inner};

xs.push(inner);
xs.insert(0, inner);
```

Los tres slots refieren al mismo objeto `inner`. Una realocacion de `xs` no
clona `inner`, no altera su header y no cambia igualdad de identidad. Los tipos
por valor se copian conforme a su representacion ABI, sin inventar semantica de
destructor en esta fase.

## `const` y aliases

`const` restringe la referencia usada para mutar; no congela el objeto ni se
propaga a otros aliases:

```aether
List<int> xs = {1, 2};
const c = xs;

c.push(3);  // error de compilacion
xs.push(3); // permitido; c tambien observa {1, 2, 3}
```

El typechecker debe rechazar `push`, `pop`, `insert`, `removeAt` y `clear`
cuando el receiver o primer argumento esta enraizado en un binding `const`.
Los checks de runtime no sustituyen esta regla estatica. La estabilidad del
header permite que el alias const observe mutaciones legales realizadas por
otro alias sin habilitar mutacion a traves de `c`.

## Estrategia de runtime LLVM

La separacion recomendada es un nucleo storage-oriented generico por tamano de
elemento y lowering tipado en el compilador. Los nombres exactos no son ABI
publica ni quedan fijados por este documento.

Helpers base candidatos:

```text
aether_list_reserve(list, element_size, required_length) -> void
aether_list_push(list, element_size, value_ptr) -> void
aether_list_prepare_pop(list) -> new_length
aether_list_insert(list, element_size, index, value_ptr) -> void
aether_list_remove_at(list, element_size, index, out_ptr) -> void
aether_list_clear(list) -> void
```

Tambien son compartibles los checks de overflow/bounds y el helper de panic.
`reserve`, `clear` y los movimientos de bytes no dependen semanticamente de
`T`; reciben `element_size` donde corresponde. La implementacion actual de
`pop` usa `aether_list_prepare_pop` solo para comprobar vacio y calcular el
indice; LLVM carga el valor tipado y despues publica la nueva longitud inline.
`push` e `insert` pueden usar un `value_ptr` estable, y `remove_at` un `out_ptr`, lo que permite una
implementacion generica con `memcpy` para un elemento y `memmove` para rangos
solapados.

El lowering conoce `T`, calcula su tamano ABI, crea temporales tipados para
input/output y convierte el `out_ptr` de `pop`/`removeAt` de vuelta a un valor
SSA de tipo `T`. Puede haber wrappers especializados como
`aether_list_push_i64` o `aether_list_pop_f64` si simplifican ABI o debugging,
pero deben delegar la politica de capacidad a un unico nucleo para evitar
divergencias. Solo operaciones que necesiten semantica propia de `T` --por
ejemplo, futuros destructores-- justifican especializacion real.

El runtime debe usar intrinsecos/funciones con semantica correcta:

- copia a un buffer nuevo: `memcpy`, porque las allocations no se solapan;
- shift dentro del mismo buffer: `memmove`;
- copia de un unico valor desde/hacia un temporal estable: `memcpy` o load/store
  tipado compatible con alignment.

## IR, SSA y optimizacion futura

Instrucciones propuestas:

| IR | SSA | Resultado | Efecto |
| --- | --- | --- | --- |
| `IRListPush(list, value)` | `SSAListPush(list, value)` | ninguno | muta lista |
| `IRListPop(result, list)` | `SSAListPop(result, list)` | `T` | muta lista |
| `IRListInsert(list, index, value)` | `SSAListInsert(list, index, value)` | ninguno | muta lista |
| `IRListRemoveAt(result, list, index)` | `SSAListRemoveAt(result, list, index)` | `T` | muta lista |
| `IRListClear(list)` | `SSAListClear(list)` | ninguno | muta lista |

`Push`, `Insert` y `Clear` son side-effecting sin resultado. `Pop` y
`RemoveAt` producen `T` y tambien son side-effecting: no se vuelven puras si
su resultado esta muerto.

Consecuencias conservadoras hasta tener alias analysis:

- **DCE:** nunca elimina estas cinco instrucciones por falta de usos. Puede
  eliminar el valor resultado muerto de `Pop`/`RemoveAt`, pero no la operacion.
- **SCCP/constant folding:** invalida hechos previos sobre length, is-empty,
  indices, orden y contenido de cualquier alias posible. No pliega una lectura
  a traves de una mutacion sin demostrar ausencia de alias.
- **Alias analysis:** debe modelar el header como identidad estable y `data`
  como storage interno reemplazable. Dos referencias al mismo header aliasan
  incluso si una reserva cambia `data`.
- **Orden de memoria:** estas instrucciones leen/escriben header y buffer y
  actuan como barreras para lecturas/escrituras de la misma lista o aliases.
  No pueden adelantarse, retrasarse ni reordenarse entre si o alrededor de una
  llamada que pueda recibir un alias sin prueba especifica.
- **Allocation:** `Push` e `Insert` pueden llamar al allocator y terminar el
  programa; ese efecto observable tambien impide tratarlas como stores
  triviales.

Este contrato no introduce concurrencia ni garantiza thread safety. "Orden de
memoria" aqui describe dependencias y reordenamiento del compilador en un
programa secuencial, no atomics ni sincronizacion entre threads.

## Orden de implementacion recomendado

La Fase 4 se divide asi:

1. **Fase 4a: `clear` (implementada).** Valida una mutacion de `length`, const,
   aliases y efectos IR sin allocation ni movimientos.
2. **Fase 4b: `reserve`/growth interno y `push` (implementada).** Establece overflow,
   allocation, commit del header y crecimiento amortizado con el caso de shift
   mas simple: ninguno.
3. **Fase 4c: `pop` (implementada).** Agrega error de lista vacia y resultado tipado sin
   requerir allocation ni memmove.
4. **Fase 4d: `insert`.** Reutiliza growth y agrega bounds inclusivos y shift a
   la derecha solapado.
5. **Fase 4e: `removeAt`.** Reutiliza el resultado tipado de `pop` y los checks
   de indice, y agrega shift a la izquierda solapado.

Este orden reduce variables nuevas por fase y deja `removeAt`, la combinacion
de retorno, bounds y memmove, para cuando esas piezas ya fueron probadas por
separado. No se mueve `clear` a la Fase 3 historica para no reetiquetar trabajo
ya cerrado; se lo implementa como primer incremento de Fase 4.

## Plan minimo de regresiones

La implementacion debera cubrir, con paridad entre interprete AST, interprete
IR y LLVM cuando cada superficie exista:

### Crecimiento y aliasing

- `push` sobre `capacity == 0` produce length/capacity validas y data no nulo;
- `push` con capacidad disponible no cambia `data` ni `capacity`;
- `push` que crece conserva todos los elementos y actualiza el mismo header;
- multiples crecimientos siguen la secuencia determinista de capacidad;
- un alias observa growth, nueva longitud y contenido;
- parametros y returns conservan el aliasing del header;
- `push(xs[0])` y `insert(i, xs[j])` siguen siendo correctos al realocar o
  desplazar;
- crecimiento con `int`, `double`, `string` y tipos reference-type.

### Operaciones

- `pop` normal devuelve el ultimo elemento; `pop` vacio falla claramente;
- `insert` al inicio, medio y final, incluido `index == length`;
- `insert` rechaza indices negativos y mayores que length;
- `removeAt` al inicio, medio y final devuelve el elemento correcto;
- `removeAt` rechaza lista vacia e indices fuera de rango;
- `clear` sobre lista vacia y no vacia es idempotente;
- `pop`, `removeAt` y `clear` preservan `capacity` y el buffer;
- reutilizar una lista tras `clear` no fuerza crecimiento si hay capacidad.

### Tipos, errores y compilador

- listas anidadas preservan identidad de los elementos y no hacen deep copy;
- cobertura de `int`, `double`, `string`, listas y otros reference-types
  soportados por backend;
- cada operacion mutante se rechaza a traves de `const` y funciona a traves de
  un alias mutable;
- overflow simulado de `length + 1`, doubling y bytes produce panic sin
  wraparound;
- allocation failure mockeado conserva el header previo antes de terminar;
- DCE conserva las cinco mutaciones, incluso con resultados sin uso;
- SCCP no reutiliza length/contenido anterior a traves de aliases mutados;
- verifier IR/SSA valida aridad, tipos de lista, indice y resultado;
- paridad de valores, errores y efectos entre AST Interpreter, IR y LLVM.

Los tests que necesiten observar capacidad o direccion de buffer deben usar
hooks internos de test, no convertir esos detalles en API publica de Aether.

## Riesgos y decisiones abiertas

Quedan deliberadamente abiertos para fases posteriores:

- lifetime final de headers y buffers sin GC/refcount/ownership;
- si todos los buffers actuales tienen procedencia compatible con `free` y,
  por tanto, cuando habilitar liberacion durante realloc;
- integracion del panic de allocation con futuras excepciones y unwinding;
- limpieza de slots retirados para un futuro GC preciso o conservador;
- alignment y ABI de tipos de elemento estructurados que aun no tengan backend
  completo;
- destructores o ownership de elementos por valor;
- semantica y necesidad de un futuro `reserve()` o `shrinkToFit()` publico;
- interaccion entre mutacion durante `for` y la politica de iteracion, que debe
  resolverse en su diseno especifico y no mediante la politica de capacidad.

No son decisiones abiertas en v0: estabilidad del header, aliasing por
asignacion, crecimiento geometrico `0 -> 1 -> 2 -> 4...`, retorno `T` de
`pop`/`removeAt`, ausencia de shrinking automatico, shallow movement de
referencias y error fatal controlado ante allocation/overflow en LLVM.
