# Lifecycle de valores de Aether

Estado: **contrato, ARC string y RC de objetos Array/List implementados para
Aether v1**, 15 de julio de 2026. El lowering AST→IR emite lifecycle y cleanup
estructural, el verifier comprueba el estado antes de SSA y la expansión genera
retain/release effectful para strings, colecciones y structs que los contienen.
Los handles LLVM siguen ocupando una palabra.
La caracterización previa a RC de Array/List y su superficie de migración está
en [`COLLECTION_MIGRATION_BASELINE.md`](../aether/COLLECTION_MIGRATION_BASELINE.md).

## 1. Vocabulario e invariantes

Una ubicación está **viva** desde que termina una inicialización exitosa hasta
que es destruida o usada como fuente de una relocation. Una ubicación no
inicializada no contiene un valor Aether y no se puede leer ni destruir.
Un *owning slot* mantiene las referencias owned transitivas de su valor; un
borrow permite leer durante una región acotada y no se destruye.

El compilador modelará, directa o sintéticamente, estas operaciones:

```text
init_default(destination)
copy_init(destination, source)
move_init(destination, source)
assign(destination, source)
destroy(value)
relocate(destination, source, count)
```

`copy` crea otro valor vivo; `move` y `relocate` transfieren un valor y ponen
fin a la vida en el origen. Por ello una copia lógica nunca se reemplaza por
`memcpy` solo porque la representación tenga tamaño fijo.

## 2. Contrato de las operaciones

### `init_default(destination)`

- Pre: `destination` es storage válido, alineado, sized y no inicializado.
- Post: contiene el valor default del tipo y está vivo; no existe fuente.
- Aliasing/self: no aplica. El storage no puede solapar otro valor vivo.
- Panic: si puede fallar, la ubicación queda no inicializada. Quien llama
  conserva la responsabilidad por los valores anteriores ya inicializados.
- Bytes: `memset(0)` solo es válido si el layout declara explícitamente que el
  patrón cero es su default. No es válido para el string futuro, cuyo default
  es el singleton vacío no nulo.

### `copy_init(destination, source)`

- Pre: `destination` está no inicializado; `source` está vivo y es legible.
- Post: ambos contienen valores lógicamente iguales e independientes respecto
  a mutaciones permitidas; pueden compartir almacenamiento inmutable.
- Fuente: sigue viva y conserva todo su ownership.
- Aliasing: el storage no puede solaparse. Un borrow que designa el mismo valor
  lógico no cambia el contrato.
- Self: `copy_init(&x, &x)` es inválido porque `destination` no estaría sin
  inicializar.
- Panic: ante fallo no nace un valor completo en `destination`. Un hook
  compuesto revierte los campos que sí llegó a inicializar, en orden inverso.
- Bytes: `memcpy` es una implementación válida solo para tipos
  `is_trivially_copyable`. En cualquier otro tipo debe ejecutarse el hook.

### `move_init(destination, source)`

- Pre: `destination` está no inicializado y `source` está vivo.
- Post: `destination` recibe el valor y su ownership sin retain; `source` queda
  en el estado moved-from definido por el tipo. Para string queda vivo con el
  singleton vacío; para un tipo interno puede quedar no inicializado si su
  contrato lo declara y el verificador impide leerlo o destruirlo.
- Fuente: no conserva el valor original.
- Aliasing/self: storage solapado o idéntico no es válido para `move_init`.
- Panic: la transferencia de una representación sized no debe fallar. Si un
  tipo requiere trabajo que puede fallar, debe completar primero la parte
  fallable sin consumir la fuente o definir rollback explícito.
- Bytes: una carga/store, `memcpy` o `memmove` puede mover un tipo
  `is_trivially_relocatable`, pero debe aplicarse después el estado moved-from
  exigido si la fuente sigue siendo una ubicación viva.

### `assign(destination, source)`

- Pre: ambos están vivos y los tipos son asignables.
- Post: `destination` contiene una copia lógica del valor observado en
  `source`; `source` sigue vivo.
- Aliasing: debe preservar aliasing indirecto. Se adquiere primero el nuevo
  ownership, luego se reemplaza el destino y por último se destruye el valor
  anterior.
- Self: es válida y no cambia el valor ni su lifetime.
- Panic: si adquirir la copia falla, `destination` conserva el valor anterior.
  Una vez hecho el commit, un destructor no debe producir un panic recuperable;
  una violación interna aborta el proceso.
- Bytes: equivale a store/memcpy solo para tipos trivialmente copiables. En
  general no equivale a `destroy` seguido de `copy_init`, porque ese orden
  rompe self-assignment y aliasing.

### `destroy(value)`

- Pre: `value` está vivo y es owned por esa ubicación.
- Post: libera sus recursos transitivos exactamente una vez y la ubicación
  queda no inicializada. Destruirla de nuevo es inválido.
- Fuente/self: no hay fuente. Los borrows no se destruyen y no pueden sobrevivir
  al owner del que dependen.
- Panic: cleanup normal no produce un panic recuperable. Underflow, double
  destroy o un descriptor corrupto son fallos internos/traps. Durante unwind
  futuro, un segundo panic termina el proceso.
- Bytes: es no-op solo cuando `needs_destroy == false`; borrar bytes no ejecuta
  destrucción.

### `relocate(destination, source, count)`

- Pre: los `count` destinos están sin inicializar; los `count` orígenes están
  vivos, forman rangos válidos del mismo tipo y la operación conoce si se
  solapan.
- Post: cada destino contiene el valor y ownership correspondiente; las
  ubicaciones fuente dejan de contener objetos vivos, aunque sus bytes
  permanezcan. No se destruyen después.
- Fuente: se consume. Relocation **no** es copy.
- Aliasing: rangos idénticos son no-op. Con solapamiento parcial se respeta la
  dirección de `memmove`; nunca puede haber dos ubicaciones vivas para el mismo
  elemento como resultado intermedio observable.
- Self: un rango idéntico conserva sus elementos vivos y cuenta como no-op.
- Panic: una relocation bitwise no falla. Una implementación por hooks mueve
  en un orden seguro y debe llevar el prefijo/sufijo ya consumido para cleanup
  preciso ante un fallo excepcional.
- Bytes: `memmove` es válido solo para tipos `is_trivially_relocatable` y solo
  si la vida del rango fuente termina. `memcpy` exige además ausencia de
  solapamiento. Ninguno representa una copia lógica de un tipo no trivial.

## 3. Clasificación canónica de tipos

Las propiedades conceptuales son:

- `is_sized`: tiene tamaño/alineación conocidos para el target;
- `is_trivially_copyable`: copiar bytes crea un segundo valor vivo válido;
- `is_trivially_relocatable`: mover bytes es válido si muere el origen;
- `needs_destroy`: abandonar un valor vivo requiere un hook;
- `contains_references`: la representación contiene referencias/descriptores,
  aunque hoy sean inmortales o tengan aliasing deliberado;
- `needs_retain`: una copia lógica debe adquirir ownership transitivo.

`LLVMTypeLayouts` conserva estos hechos separados. La clasificación aprobada de
string ya está activa y se propaga recursivamente a structs y operaciones de
elementos de colección.

| Tipo | Sized | Copy trivial actual | Relocate trivial | Destroy actual | References | Retain actual | Contrato futuro relevante |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `int`, `boolean`, `double` | sí | sí | sí | no | no | no | sin cambio |
| `float` | frontend sí; native no | no definido native | no definido | no | no | no | fijar ABI antes de almacenarlo |
| enum sin payload | sí | sí | sí | no | no | no | sin cambio |
| callable top-level | una palabra donde está soportado | sí para transporte directo | sí | no | sí, a código | no | closures requerirán otro layout/lifecycle |
| class reference | una palabra conceptual; fuera del subset native | no prometido | sí si el modelo conserva handle | por definir | sí | por definir | coordinar con ownership general de objetos |
| string actual | sí, handle de una palabra | **no** | sí | **sí** | sí | **sí** | objeto UTF-8 ARC; default vacío; copy retain; destroy release |
| struct | si todos los campos lo son y no hay ciclo by-value | `all(fields)` | `all(fields)` | `any(fields)` | `any(fields)` | `any(fields)` | síntesis recursiva nominal |
| nested struct | misma regla recursiva | misma regla recursiva | misma regla recursiva | misma regla recursiva | misma regla recursiva | misma regla recursiva | los nombres no cortan el análisis |
| `Array<T>` | handle `ptr` sized | **no** | sí | **sí** | sí | **sí** | reference type: copy retain y destroy release |
| `List<T>` | handle `ptr` sized | **no** | sí | **sí** | sí | **sí** | igual; growth relocaliza T dentro del objeto compartido |
| `Vector<T>` / `Matrix<T>` | descriptor sized en subset native | sí en ABI actual | sí | no hoy | sí | no hoy | definir owner/alias de storage antes de hooks |

Un tipo de colección no se declara migrado solo porque su descriptor sea
copiable. Su operación `copy` también depende recursivamente del lifecycle de
`T`. Hasta que existan hooks, el subset native solo admite representaciones
para las que las operaciones actuales están demostradas. Los hooks de elemento
string/struct y el handle RC del contenedor están activos.

### 3.1 Lifecycle implementado de Array/List

La decisión v1 de
[`COLLECTION_RUNTIME_DESIGN.md`](../aether/COLLECTION_RUNTIME_DESIGN.md) trata
Array/List como handles reference type a un objeto contenedor con strong RC no
atómico. Para el **handle**, `copy_init` retiene y comparte, `move_init`
transfiere, `assign` hace retain-before-release, `destroy` libera y `relocate`
mueve bits invalidando la fuente. El último release destruye el rango vivo de
elementos, el buffer y el objeto exactamente una vez.

Esto no es el método público `copy()`: ese método reserva otro descriptor y
buffer y ejecuta la copia lógica de cada `T`. Slicing usa la misma copia lógica
sobre un rango. La implementación clasifica el handle como no trivial y cubre
coordinadamente assignment, parámetros, returns, fields, nesting y cleanup.

## 4. Lifecycle aprobado de string

```text
init_default(dst):
    dst = empty_singleton

copy_init(dst, src):
    retain(src.handle)
    dst.handle = src.handle

move_init(dst, src):
    dst.handle = src.handle
    src.handle = empty_singleton

assign(dst, src):
    retain(src.handle)
    old = dst.handle
    dst.handle = src.handle
    release(old)

destroy(value):
    release(value.handle)

relocate(dst, src, count):
    transferir los handles sin retain/release
    terminar la vida de las ubicaciones fuente
```

El vacío y los literales son inmortales, por lo que retain/release son no-op
para ellos. Todo handle Aether publicado es no nulo. `retain` comprueba overflow
de `strong_count` antes de incrementar y hace panic; `assign` aún conserva el
destino si falla ese retain. Relocation no deja una copia y nunca incrementa el
contador.

## 5. Síntesis para structs

Para:

```aether
struct Person {
    string name;
    int age;
}
```

se sintetizan hooks por campo:

```text
init_default(Person dst): init_default(dst.name); init_default(dst.age)
copy_init(Person dst, Person src): copy_init(dst.name, src.name); copy_init(dst.age, src.age)
move_init(Person dst, Person src): move_init(dst.name, src.name); move_init(dst.age, src.age)
assign(Person dst, Person src): assign(dst.name, src.name); assign(dst.age, src.age)
destroy(Person value): destroy(value.age); destroy(value.name)
```

Inicialización/copia avanza en orden de declaración; destrucción y rollback
usan el orden inverso. Si copiar el campo `k` hace panic, se destruyen
exactamente los campos `[0, k)` ya inicializados y el struct destino nunca se
publica como vivo. Para el primer ARC, `retain` solo falla por overflow, que es
un panic checked. La política sigue exigiendo rollback si el runtime soporta
unwind; si el panic aborta el proceso no se observa leak, pero el IR debe
conservar metadata de inicialización parcial para no cerrar esa posibilidad.

`assign` de structs no puede hacerse campo a campo ingenuamente si source y
destination se solapan. El hook debe tratar self-assignment como no-op o
adquirir primero todas las referencias que podrían perderse antes del commit.

## 6. Array y List

### Array

- Un literal/default inicializa elementos uno por uno y lleva un contador de
  prefijo vivo para rollback.
- `get` por valor ejecuta `copy_init`; un borrow efímero solo es válido si el
  análisis prueba que no escapa.
- `set`/overwrite ejecuta `assign`, incluyendo self-aliasing.
- Copia y slice crean storage nuevo y hacen `copy_init` por elemento.
- Destrucción recorre exactamente los elementos vivos y después libera storage.
- Arrays de structs usan el hook sintetizado del struct, no búsqueda ad hoc de
  fields string.

### List

- `push`/`insert` hacen `copy_init`, o `move_init` únicamente desde un temporal
  consumible probado.
- `pop` mueve el último elemento al resultado y reduce el rango vivo sin
  destruir el valor transferido.
- `removeAt` mueve el eliminado al resultado cuando existe; los restantes se
  desplazan por relocation y ninguna ubicación fantasma se destruye.
- `set` usa `assign`; `clear` destruye `[0, length)` una sola vez y pone length
  en cero antes de exponer el estado final.
- Growth reserva un buffer y relocaliza `[0, length)`. El buffer anterior se
  libera sin destruir sus bytes ya consumidos.
- Destrucción hace `clear` y luego libera el buffer. Capacity nunca determina
  cuántos elementos están vivos.

Para tipos no triviales, `memcpy` no es copy. `memmove` solo es relocation si
la fuente deja de estar viva. Insert/remove con solapamiento debe elegir el
orden correcto; ninguna operación destruye dos veces ni destruye un elemento
que fue transferido como resultado.

## 7. Convención de llamadas

- Parámetros string y, por composición, parámetros aggregate se reciben
  borrowed durante la call. Guardarlos o retornarlos exige adquirir ownership.
- Returns transfieren un valor owned al caller.
- Un temporal owned es responsabilidad de su expresión/scope hasta que se
  mueve a un slot, argumento owned futuro o return; un temporal borrowed nunca
  se destruye.
- Calls directas, indirectas, métodos, constructors, imports cross-module,
  builtins y runtime calls usan la misma convención declarada en la firma
  semántica. La indirección no puede borrar los efectos de lifecycle.
- Constructors inicializan `this`/resultado como storage parcial y solo
  publican el valor al completar todos los campos.
- Builtins/runtime deben declarar por parámetro `borrowed`, `consuming` o
  `owned` y si el resultado es owned. En ausencia de declaración se asumen
  efectos conservadores y no se eliden operaciones.

Casos normativos:

```aether
string identity(string value) { return value; }
```

`value` es borrowed; el return hace retain y entrega una referencia owned.

```aether
string literal() { return "hello"; }
```

El resultado es owned por convención, pero el retain efectivo del literal
inmortal es no-op.

```aether
string build() {
    string result = futureConcat(...);
    return result;
}
```

El resultado owned del concat se mueve al local y luego al caller. El lowering
puede transferirlo sin retain/release redundante si prueba que no existe otro
uso ni cleanup posterior del local.

## 8. Cleanup y control de flujo

La estrategia aprobada es preservar scopes léxicos durante AST→IR y emitir
operaciones de lifecycle explícitas **antes de SSA**. El lowerer mantiene una
pila de owning slots e inserta cleanup en fin de scope, `return`, `break`,
`continue` y cada arista que abandona una región. Ramas se unen solo después de
reconciliar qué valores están inicializados/movidos.

Un pase de ownership sobre IR previo a SSA puede complementar y verificar la
emisión si IR conserva scope ids, estado de inicialización y ownership. No se
recomienda que sea la única fuente de verdad. Un pase posterior a SSA es más
difícil: los slots y scopes léxicos ya se repartieron entre valores y phis,
returns/branches comparten aristas, y dominancia/liveness no expresan por sí
solas qué uso consume ownership ni cómo hacer rollback parcial.

Panic abortivo ejecuta la terminación segura del runtime. Si se incorpora
unwind, cada punto que puede hacer panic necesitará una arista excepcional con
cleanup del conjunto exacto de valores vivos.

## 9. Forma implementada en IR y verificación

La IR semántica implementa operaciones genéricas tipadas:

```text
init_default dst: T
copy_init dst: T, src
move_init dst: T, src
assign dst: T, src
destroy value: T
relocate dst: T, src, count
```

`retain`/`release` quedan como primitivas de lowering/runtime, no como API de
usuario. Las operaciones genéricas sobreviven hasta que el tipo y control de
flujo estén verificados; antes de LLVM se expanden a no-op, load/store,
memcpy/memmove o calls/hooks recursivos. Solo retain/release/runtime calls y
movimientos concretos necesitan llegar a LLVM.

El verificador exige tipo sized, destination no inicializado donde corresponda,
un único destroy/consume por vida, source viva, convenciones de calls/returns,
dominancia y estado coherente en phis. Un phi de un valor owned representa un
owner en el bloque destino y cada arista transfiere exactamente uno; no crea
owners implícitos. Lifecycle y calls con panic son efectos observables para
DCE. Ningún optimizador puede borrarlos, duplicarlos o moverlos a través de un
panic/call sin prueba de equivalencia.

`IRStorage` distingue ubicaciones addressable owned de `IRValue`. Cada opcode
puede conservar `IRSourceLocation`; la nominalidad viene del `IRType` completo.
`LifecycleTypeRegistry` sintetiza planes de structs en orden fuente y orden
inverso para destrucción/rollback. String y structs que lo contienen son no
triviales; Array/List son handles no trivialmente copiados, con destroy, pero
siguen siendo trivialmente relocatables.

La decisión aplicada es expandir lifecycle **después de `IRVerifier` y antes
de SSA**. `LifecycleExpander` convierte el lifecycle string/struct en
retain/release effectful y conserva load/store/default/no-op para tipos
triviales. En IR, los opcodes declaran efectos obligatorios y DCE no puede
eliminarlos.

Optimizaciones futuras, no implementadas en esta fase: pairing general probado
de retain/release, ARC global e inlining/devirtualización de hooks. La expansión
ya consume temporales owned obvios y mueve locals al return. Todas
requieren una demostración sobre aliasing, aristas de control y panics; la
adyacencia textual no basta.

## 10. Auditoría preventiva de la representación actual

Hoy string native es un handle a `AetherStringObject` con ARC. Copia,
asignación, returns, structs y elementos Array/List invocan retain/release en
los recorridos implementados. Igualdad por contenido y print length-aware están
activos; concat, interpolación, parsing, split/trim, archivos, argv e input
native continúan rechazados o sin API.

Los recorridos de `List` usan hooks de copy/destroy para elementos; growth usa
relocation y `clear` destruye el rango vivo. El objeto posee ahora contador,
buffer y release final coordinado con aliases, calls, returns y fields.

## 11. Detalles aplazados no bloqueantes

- metadata para inicialización parcial con unwind (la forma normal de IR ya
  está fijada);
- lifecycle general de classes y ownership de buffers Vector/Matrix;
- optimización ARC, RVO y política de concurrencia posterior;
- `StringView`, substring y APIs públicas de texto.

El bloque RC coordinado de colecciones está implementado. La optimización ARC y
nuevas APIs string pueden seguir después;
concat, parsing, split/trim, files y argv permanecen aplazados.
