# RFC: modelo de strings y runtime de texto de Aether

Estado: **propuesta en revisión**, 15 de julio de 2026. Este documento no es
normativo todavía y no declara implementado ningún cambio. La especificación
vigente, los perfiles de capacidades y el backend conservan su estado actual
hasta que esta RFC sea aprobada y ejecutada por fases.

## 1. Resumen de la recomendación

La recomendación para Aether v1 es:

| Dimensión | Decisión propuesta |
| --- | --- |
| Semántica | `string` es un valor inmutable, no nulo, con igualdad por contenido; copiar el valor puede compartir almacenamiento. |
| Encoding | UTF-8 válido y canónico como secuencia de bytes; sin normalización Unicode implícita. |
| Representación | Un handle de una palabra (`ptr`) a un `AetherStringObject` inmutable con longitud `i64`, refcount `i64`, flags y bytes inline. |
| Literales | Objetos estáticos read-only, `IMMORTAL`, deduplicables por módulo y terminados en cero. |
| Strings dinámicas | Objetos owned, inicialmente con reference counting no atómico y oculto al usuario. |
| Terminador | Un byte `0` adicional obligatorio por conveniencia de interoperabilidad; la longitud, nunca el terminador, es la autoridad. |
| ABI interna | El handle se pasa y retorna por valor; fields y elementos contienen el mismo handle. No se declara una ABI C pública estable. |
| Copia | Retain lógico al duplicar ownership; move bitwise al reubicar; release al sobrescribir o destruir. |
| Índices | No se propone `s[i]` en v1. No se confundirá byte, code point y grapheme. |
| Longitudes | `byteLength` O(1); `codePointCount` O(n); `graphemeCount` futuro. No se propone un `length` ambiguo para string. |
| Orden | `==`/`!=` por contenido. Los operadores `< <= > >=` no se proponen para string v1; sort y un compare interno usan bytes UTF-8 unsigned. |
| Substring | Fuera del primer runtime; la primera API segura debería copiar y usar límites de code points. Las views se aplazan. |
| División de APIs | Solo representación, validación, allocation, lifecycle y operaciones esenciales viven en runtime; algoritmos de texto viven en stdlib. |

Esta elección conserva la propiedad más útil del ABI actual —un string ocupa
una palabra en firmas, structs y colecciones— sin seguir confundiendo un valor
Aether con un `char*`. El coste es real: antes de producir strings dinámicas el
backend debe adquirir hooks de lifecycle y distinguir copia de reubicación.

## 2. Alcance y no objetivos

Esta RFC define el contrato que debe aprobarse antes de implementar el nuevo
runtime. No implementa concatenación, interpolación native, archivos, process
args, parsing, formatting, GC, reference counting, destructores ni cambios de
sintaxis. Tampoco decide la gestión de memoria general de classes y
colecciones.

Se distinguen cinco capas:

1. **Semántica visible:** lo que un programa Aether puede observar.
2. **Representación interna:** layout y invariantes que implementan esa
   semántica.
3. **ABI interna:** cómo circula el valor entre funciones, módulos y
   aggregates compilados juntos.
4. **Runtime:** primitivas que acceden a layout, allocation, seguridad y
   lifecycle.
5. **Stdlib:** APIs de texto expresables sobre esas primitivas.

Ningún nombre de helper incluido aquí es todavía API pública. Los nombres
`aether_string_*` son ilustrativos y pueden cambiar durante implementación.

## 3. Inventario del estado actual

### 3.1 Lexer, parser, literales y escapes

- `src/aether/lexer.py` escanea strings delimitadas por comillas dobles. Acepta
  strings multiline y decodifica `\"`, `\\`, `\$`, `\n`, `\t` y `\r` a un
  `str` de Python. Rechaza cualquier otro escape. No existe escape `\0`, `\xNN`
  ni `\u{...}` público.
- `src/aether/parser.py` vuelve a recorrer el lexeme crudo para distinguir `$`
  escapado de una interpolación `$expr$`. Un literal sin interpolación produce
  `ast.Literal(value, "string")`; uno interpolado produce
  `ast.InterpolatedString` con segmentos Python `str` y expresiones AST.
- Los archivos fuente raíz e importados se leen con `encoding="utf-8"` en
  `src/aether/cli.py`, `typechecker.py` e `interpreter.py`. Un archivo fuente
  inválido falla en el host al decodificar; todavía no hay un diagnóstico
  Aether dedicado para ese caso.
- El lexer y el parser operan sobre code points de Python. No existe validación
  explícita del valor contra la futura representación UTF-8, aunque todo
  literal proveniente de una fuente UTF-8 decodificada puede re-encodearse.

### 3.2 Typechecker y semántica AST

- `src/aether/typechecker.py` reconoce `string` como primitivo, permite
  asignación, parámetros, return, fields, colecciones, `+`, `==` y `!=` entre
  strings. Rechaza orden directo porque `< <= > >=` exigen numéricos reales.
- `string?` existe en el frontend y AST. `null` no pertenece a `string`; solo
  puede almacenarse en `string?`. Nullable no tiene representación native.
- Una interpolación siempre tiene tipo `string`; cada expresión embebida se
  typecheckea, pero no se exige una interfaz de formatting.
- `const` impide rebinding. No vuelve inmutable el contenido porque el string
  AST ya es un `str` inmutable de Python.
- No existen miembros nativos de string en `src/aether/native_members.py`.
  `length(...)` solo acepta List, Array y Vector.

El intérprete en `src/aether/interpreter.py` guarda el payload como `str` de
Python dentro de `AetherValue`. En consecuencia:

- asignar o pasar un string comparte el objeto host cuando Python lo decide;
- `+` usa concatenación Python;
- igualdad usa igualdad Python por contenido;
- interpolación usa `"".join` y `format_value`;
- `input()` recorta el fin de línea y produce un `str` host;
- `string(value)` usa el formateo del intérprete;
- structs se copian recursivamente, pero un field string termina compartiendo
  el payload inmutable;
- Array/List contienen `AetherValue` y sus copias son superficiales salvo la
  lógica especial de structs.

Este comportamiento es un prototipo útil, no un ABI ni una fuente válida de
tamaños, ownership o complejidad para native.

### 3.3 IR, SSA e intérprete IR

- `src/aether/ir/types.py` define un `StringType` nominal sin layout.
- Literales son `IRConst`/`SSAConst` cuyo valor sigue siendo `str` de Python.
- IR y SSA aceptan `add` de dos `StringType` y `eq`/`ne`; los verificadores
  validan tipos, no encoding, descriptor ni ownership.
- El intérprete IR usa `left + right` y operadores Python. Sort codifica cada
  string a UTF-8 y ordena esos bytes.
- IR lowering permite strings en variables, parámetros, return, structs,
  Array/List y print. Los valores por defecto de fields string son `""`.
- Los optimizadores SSA evitan deliberadamente plegar binary/compare de
  strings. No tienen modelo de allocation, identidad, retain/release ni
  lifetime.
- SSA no agrega una representación: conserva `StringType` y las mismas
  instrucciones. No existe intérprete SSA.

El tipo semántico de IR puede mantenerse; lo que debe cambiar es su contrato de
lowering y efectos. La igualdad no necesita convertirse en un opcode nuevo:
puede bajar a una call runtime conocida.

### 3.4 LLVM/native y ABI actual

El supuesto central actual está en `src/aether/backend/llvm/types.py`:

```text
StringType -> ptr
```

Ese `ptr` apunta hoy directamente al primer byte de un global C terminado en
cero:

```llvm
@.str.0 = private unnamed_addr constant [6 x i8] c"hello\00"
```

`src/aether/backend/llvm/printer.py`:

- codifica el `str` Python a UTF-8, agrega `\00` y escapa los bytes para LLVM;
- deduplica literales iguales dentro del módulo LLVM combinado;
- pasa y retorna el `ptr` por valor, incluso por `phi` y callables;
- imprime scalar string y fields/elements con `printf("%s", ptr)`;
- rechaza binary operations y comparaciones string generales;
- usa `strcmp` para igualdad dentro de structs y ciertas secuencias.

`runtime.py`, `runtime_common.py` y `list_runtime.py` también tratan cada string
como C string:

- `strcmp` implementa búsqueda, igualdad especializada y orden de sort;
- sort fija el tamaño del elemento string en 8 bytes, supuesto de puntero de
  64 bits;
- print de Array/List/Vector/Matrix pasa el elemento a `%s`;
- no hay `strlen` en el runtime porque la longitud no es una operación Aether,
  pero libc descubre el fin mediante el cero en print/compare.

`LLVMTypeLayouts` clasifica string como referencia sized, trivialmente copiable
y almacenable en colecciones. Array/List y structs copian el puntero con
load/store, `memcpy` o `memmove`. List reserve libera buffers de backing store,
pero no hay destrucción de elementos ni liberación de strings. Esto solo es
seguro para los literales estáticos actuales.

### 3.5 Structs, colecciones, módulos y callables

Hoy funcionan estos recorridos porque una string es un puntero inmortal:

- fields `string` dentro de structs por valor;
- structs con strings dentro de `Array` y `List`;
- get/set, push, insert, pop, removeAt, clear, reverse, sort, copy, slice y
  reallocation mediante copias bitwise;
- parámetros y returns, incluidos structs por valor;
- funciones top-level tipadas y calls indirectas sin captura;
- imports y firmas cross-module tras combinar el grafo en un módulo LLVM.

`examples/expense_tracker/` depende exactamente de este transporte. Cada
`Transaction` contiene tres fields string; `List<Transaction>` crece, filtra y
se copia por valor. Todos los textos provienen de literales, por lo que ningún
puntero vence y ninguna copia necesita ownership. El ejemplo no prueba strings
dinámicas, archivos, args, parsing ni liberación.

### 3.6 Builtins, perfiles, documentación y tests

- `src/aether/stdlib/core.py` registra `string(...)`, print/println e input AST,
  pero no una API de texto. `length` no acepta string.
- Sort de strings AST usa bytes UTF-8; native usa `strcmp`. Coinciden para UTF-8
  válido sin cero interno, pero `strcmp` trunca ante un cero embebido.
- El perfil native marca `strings` como `PARTIAL`. El detector rechaza
  interpolación y operaciones cuando encuentra un literal string. La función
  `_contains_string_literal` no detecta necesariamente `a + b` si ambos son
  parámetros o variables string; ese caso puede llegar al rechazo tardío del
  printer.
- Los verificadores permiten más operaciones string que LLVM. Los tests cubren
  esta divergencia y verifican el rechazo claro.
- Los tests LLVM fijan explícitamente `string -> ptr`, globales con `\00`,
  deduplicación, UTF-8, calls, returns y `phi`. Los tests de structs y
  colecciones fijan shallow pointer transport y `strcmp`.
- `AETHER_V0_SPEC.md` documenta concat e igualdad AST y declara que el orden
  string directo no está soportado. `AETHER_SEQUENCE_SORT_DESIGN.md` define el
  orden de sort por bytes UTF-8 unsigned. Las auditorías ya advierten que
  `ptr` no constituye un runtime string.
- No hay FFI pública. Usar `printf`, `strcmp`, `malloc` y `free` internamente no
  crea una ABI C del lenguaje.

### 3.7 Suposiciones que deben mantenerse o cambiar

| Suposición actual | Decisión |
| --- | --- |
| `string` es un tipo estático distinto | Mantener. |
| El valor cabe en una palabra en native | Mantener para v1 mediante un handle a objeto. |
| `string == ptr al primer byte` | Cambiar: el `ptr` apuntará al header del objeto. |
| Literal UTF-8 con cero final | Mantener los bytes y el cero final, agregando header y longitud. |
| Literales iguales se deduplican por módulo | Mantener como optimización no observable; no prometer interning global. |
| Asignación/return/field hacen copia lógica | Mantener, formalizando sharing y lifecycle. |
| Copy bitwise siempre duplica un string válidamente | Cambiar: bitwise sirve para move/relocation; copy requiere retain. |
| `strcmp` implementa toda igualdad/orden | Cambiar por length + `memcmp`; `strcmp` no tolera ceros internos. |
| `%s` imprime un string | Cambiar por escritura `data,length`; `%s` solo en adaptadores C comprobados. |
| Sort string ocupa exactamente 8 bytes | Cambiar a tamaño/alineación del handle según target; no hardcodear 8. |
| IR binary string es puro | Cambiar para concat: allocation y panic son efectos. Igualdad sigue sin allocation. |
| Python `str` define native | Rechazar. AST deberá emular el contrato Aether explícitamente. |
| El vacío puede ser `""`/global C | Cambiar a singleton `AetherStringObject` no nulo. |
| No hay null en `string` | Mantener. `string?` requiere wrapper/tag independiente en native. |
| Strings pueden viajar cross-module | Mantener con una única ABI interna por compilación. |
| Ownership es visible al usuario | Mantenerlo oculto. |

## 4. Semántica visible para el usuario

### 4.1 Valor inmutable y sharing

`string` es conceptualmente un **value type inmutable con representación
interna compartible**. Para:

```aether
string a = "hello";
string b = a;
```

`b` recibe una copia lógica del valor. La implementación puede compartir el
mismo objeto y debe hacerlo en v1; no copia los cinco bytes. El usuario no puede
observar identidad de almacenamiento. Dos strings son iguales si sus bytes
UTF-8 son iguales, aunque provengan de allocations diferentes.

No se modela como una class normal: no tiene dispatch, identidad pública ni
nullability implícita. Tampoco es una referencia mutable. Es una referencia
interna especial que implementa semántica de valor.

### 4.2 Asignación, parámetros, return y aggregates

- Asignación y paso por función preservan el contenido y pueden compartir el
  objeto.
- Return produce un valor válido independientemente de los locals del callee.
- Un field de struct participa en la copia lógica del struct. Copiar el struct
  no copia bytes de string, pero sí crea otra referencia propietaria interna.
- Array/List almacenan valores string, no direcciones prestadas a temporales.
- Guardar en una class usa el mismo contrato; la destrucción futura de la class
  debe liberar su field.
- `const string` impide reasignar el binding. No agrega inmutabilidad al
  contenido porque todo string ya es inmutable.

Los parámetros pueden implementarse como borrows durante la call, pero esa
elección ABI no cambia la semántica. Si un callee guarda o retorna el parámetro,
debe adquirir ownership antes de que termine el borrow.

### 4.3 Null, vacío y valores por defecto

- Un `string` válido nunca es null.
- `""` es el string vacío y usa un singleton estático no nulo de longitud cero.
- `string?` conserva la semántica frontend existente: null es distinto de
  vacío. Su ABI native se diseñará al implementar nullable; no se usará `ptr
  null` como representación informal antes de esa decisión.
- El valor por defecto interno de un field string es el singleton vacío.

### 4.4 Literales

Un literal se codifica como UTF-8 en compile time y vive durante todo el
proceso. Su objeto es read-only e inmortal. El compilador puede deduplicar
literales de bytes idénticos dentro del módulo combinado y el linker puede
fusionarlos, pero el programa no puede depender de ello.

El cero final no forma parte del contenido ni de `byteLength`. Los ceros
embebidos sí forman parte del contenido. El literal no se copia al heap al
asignarlo, pasarlo, retornarlo o guardarlo.

### 4.5 Igualdad

`a == b` y `a != b` comparan contenido:

1. si los handles son idénticos, son iguales;
2. si `byteLength` difiere, no son iguales;
3. si la longitud es cero, son iguales;
4. se comparan exactamente `byteLength` bytes con semántica de bytes unsigned.

No se aplica normalización Unicode, case folding ni locale. En particular,
formas Unicode visualmente equivalentes con secuencias UTF-8 diferentes no son
iguales. Una futura API explícita podrá normalizar o comparar ignorando case.

### 4.6 Orden

Los operadores `<`, `<=`, `>` y `>=` no se proponen para string v1. El
typechecker actual ya los rechaza y esa restricción evita fingir collation
humana.

El runtime sí necesita `compareBytes(a,b)` para sort y algoritmos internos. Su
orden es lexicográfico sobre bytes UTF-8 unsigned: primer byte distinto y luego
longitud si un string es prefijo. Es determinista, case-sensitive y sin locale,
coherente con
[`AETHER_SEQUENCE_SORT_DESIGN.md`](AETHER_SEQUENCE_SORT_DESIGN.md). Exponer
después un método `compareTo` es una decisión separada.

### 4.7 Índices y longitudes

No se propone `s[i]` en v1. Un índice sin unidad sería engañoso:

- byte: O(1), pero puede cortar UTF-8;
- code point: requiere scan O(n) sin índice auxiliar;
- grapheme cluster: requiere reglas Unicode extensas y versionadas.

Se proponen nombres explícitos:

- `s.byteLength -> int`: cantidad de bytes, O(1), con check al estrechar i64 a
  `int` si el tipo público sigue siendo i32;
- `s.codePointCount() -> int`: cantidad de Unicode scalar values, O(n);
- `s.graphemeCount()`: futura, fuera de v1 y probablemente dependiente de un
  módulo Unicode.

No se agrega `string.length` hasta aprobar qué unidad significaría. Internamente
el header siempre usa `i64 byte_length` aunque la API pública retorne `int`.

### 4.8 Substring y slicing

No son requisito del primer runtime. La primera API recomendada es una
`substring` que recibe índices de code points, valida límites y copia los bytes
seleccionados a un nuevo string. Será O(n) para ubicar límites y O(k) para
copiar.

Las views se aplazan porque añaden offset/owner al descriptor, complican FFI y
pueden retener un buffer enorme por una substring mínima. Una API por bytes
debe vivir en el futuro tipo `Bytes` o llevar un nombre explícitamente unsafe;
nunca debe construir UTF-8 inválido silenciosamente.

## 5. Encoding y frontera con bytes

UTF-8 válido es un invariante de todo valor `string` Aether.

- Literales se validan implícitamente al leer fuente UTF-8 y se codifican en
  compile time; el compilador debe convertir errores de decode/encode en
  diagnósticos Aether, no filtrar `UnicodeError` del host.
- Una primitiva `fromUtf8(bytes)` valida una vez antes de publicar el objeto.
- Entrada externa inválida produce un error estructurado; no reemplaza bytes
  automáticamente y no crea un string parcialmente válido.
- Una futura API explícita `fromUtf8Lossy` podrá reemplazar secuencias inválidas
  con U+FFFD. El nombre debe hacer visible la pérdida.
- Una ruta `unsafeFromUtf8` solo puede existir en runtime/FFI unsafe y debe
  documentar que violar el invariante es undefined behavior interno.
- Archivos binarios, buffers arbitrarios y datos que deban conservar UTF-8
  inválido pertenecen a `Bytes`, no a `string`.

Los ceros internos son bytes UTF-8 válidos (U+0000) y se conservan. Toda
operación Aether usa longitud explícita. Solo adaptadores de C pueden imponer la
restricción “sin cero interno”.

## 6. Alternativas de representación

| Alternativa | Ventajas | Problemas para Aether |
| --- | --- | --- |
| A. `char*` terminado en null | Una palabra; literales y libc simples | Sin longitud O(1), trunca ante cero interno, ownership/lifetime ausente, `strlen` repetido, no distingue borrowed/owned. |
| B. Descriptor `(data,length)` | Longitud explícita, spans y cero interno; simple | Dos palabras en cada field/element y ABI; no resuelve ownership; una view puede quedar dangling. |
| C. `(data,length,capacity,flags)` | Puede representar builder/ownership híbrido | Tres o cuatro palabras por valor; capacity no pertenece a un valor inmutable; tags se copian por todas las colecciones y siguen sin resolver sharing por sí solos. |
| D. Handle a objeto heap/static | Una palabra; header central; literales estáticos y objetos dinámicos comparten ABI; RC/GC posibles | Una indirección para longitud/data; requiere lifecycle; conversión a C necesita apuntar al payload. |
| E. Híbrido literal borrowed / dinámico owned en descriptor taggeado | Puede evitar headers de literales | Multiplica estados e invariantes en cada valor; más ancho o pointer tagging; complica ABI, alignment, FFI y GC. |

Se elige **D**. Es una representación híbrida a nivel de objetos —estático
inmortal o heap owned— pero no a nivel del handle: todo valor string tiene la
misma forma y apunta al mismo header lógico.

No se elige `(ptr,length)` aunque sea un buen string view porque Aether guarda
muchas strings en structs y buffers contiguos. Dos palabras duplicarían el
tamaño actual de cada field/element y todavía exigirían un owner adicional o
deep copy para resolver lifetime.

## 7. Representación elegida

### 7.1 Handle

Un valor `StringType` native es un puntero no nulo, de ancho y alineación de
puntero del target, al byte cero de un `AetherStringObject`. El handle no apunta
al primer byte de texto.

El ABI interno conceptual es:

```c
typedef struct AetherStringObject *AetherString;
```

### 7.2 Header y payload

El layout v1 propuesto es:

```text
offset  size  campo
0       8     i64 byte_length
8       8     i64 strong_count
16      4     i32 flags
20      4     i32 reserved
24      N+1   u8 data[N], u8 terminator
```

El header mide exactamente 24 bytes y se alinea a 8 bytes. Los enteros usan los
anchos indicados y la endianness del target; no dependen de tamaños Python. El
handle conserva tamaño/alineación de puntero. La implementación LLVM debe fijar
alignment 8 para el objeto aun en targets donde el ABI natural de `i64` sea
menor. Esta es una ABI **interna de la fase v1**, no una promesa binaria pública.

Flags iniciales:

```text
bit 0: IMMORTAL
bit 1: UTF8_VALID
bits 2..31: deben ser cero
```

`reserved` debe ser cero. Una revisión de esta RFC será necesaria antes de
dar significado a otros bits.

Invariantes:

- `byte_length` está en `0..INT64_MAX`;
- `data[0:byte_length]` es UTF-8 válido;
- `data[byte_length] == 0`;
- ceros dentro del rango son contenido válido;
- `UTF8_VALID` está siempre activo en un string publicado;
- si `IMMORTAL`, `strong_count == 0` y retain/release son no-op;
- si no `IMMORTAL`, `strong_count >= 1` mientras el objeto sea alcanzable por
  una referencia propietaria;
- flags desconocidos, reserved no cero, puntero null o longitud imposible
  constituyen descriptor malformado y deben atraparse en builds de runtime con
  checks, no procesarse como C string.

Una allocation dinámica necesita `24 + byte_length + 1` bytes. Runtime debe
comprobar por separado `byte_length <= INT64_MAX`, overflow de `length + 1`,
overflow de suma con 24, límites del allocator y fallo de allocation antes de
escribir. El máximo real es el menor entre `INT64_MAX`, `SIZE_MAX - 25` y la
política de recursos del runtime.

### 7.3 Vacío, literal y dinámico

- **Vacío:** singleton estático `{0, 0, IMMORTAL|UTF8_VALID, 0, [0]}`. Su
  handle nunca es null.
- **Literal:** global read-only con header de 24 bytes y `N+1` bytes inline.
  `IMMORTAL|UTF8_VALID`, refcount cero. No se copia al heap.
- **Dinámico:** una allocation contigua, flags `UTF8_VALID`, refcount inicial
  uno y payload terminado en cero. Después de publicarse no se modifica.

`capacity` no forma parte de `AetherStringObject`: un valor inmutable no la
necesita. Concatenación e interpolación usarán un builder runtime privado y
mutable con su propia `{data,length,capacity}`; finalizarlo produce el objeto
inmutable exacto.

## 8. Ownership y lifetime

### 8.1 Comparación de políticas

**Borrowed/owned tag en cada descriptor.** Evita retain para literales, pero
ensancha o taggea cada valor y obliga a propagar el estado por ABI. El objeto
elegido concentra esa decisión en `IMMORTAL`.

**Deep copy por asignación.** Evita sharing, pero vuelve O(n) cada parámetro,
field get, push y return; concat y structs con strings se vuelven
prohibitivamente caros. Se rechaza.

**Reference counting.** Da liberación determinista y encaja con strings
inmutables acíclicas. Cuesta retain/release en copias lógicas y necesita hooks
recursivos en aggregates. Los ciclos no son un problema del objeto string por
sí mismo porque no referencia otros objetos. Un builder tampoco debe formar
ciclos.

**GC.** Simplificaría copias y aggregates, pero Aether no tiene tracing,
roots, safepoints ni contrato de heap general. Adoptarlo solo por strings
resolvería una fracción del problema y condicionaría classes/List. Se deja
abierta la migración.

**Arenas.** Son útiles para parser/compiler, temporales de formatting o un
proceso batch, pero un string que escapa del arena requiere promoción/copia o
lifetime estático. No son la política general del valor público.

### 8.2 Política mínima v1 propuesta

Se propone **reference counting fuerte, no atómico e intrusivo**, solo para
`AetherStringObject` dinámico:

- literales y vacío son `IMMORTAL` y no modifican contador;
- un objeto dinámico nace con `strong_count = 1`;
- cada nueva referencia propietaria hace retain;
- abandonar una referencia propietaria hace release; al pasar de uno a cero se
  libera exactamente la allocation del objeto;
- retain/release no son API de usuario;
- Aether v1 no permite compartir objetos dinámicos entre threads. Antes de
  agregar threads se deberá elegir RC atómico, transferencia estática o GC.

No se propone copy-on-write: los strings son inmutables. Un builder mutable
nunca se comparte como string y no se expone al usuario.

### 8.3 Convención de ownership interna

- Variables locales, globals futuros, fields y elementos de colecciones son
  **owning slots**.
- Un parámetro string es un borrow válido durante la call. Guardarlo o
  retornarlo requiere retain.
- Un resultado string se entrega owned al caller. Una función que retorna un
  objeto nuevo transfiere su referencia inicial; una que retorna un parámetro o
  field retiene antes de transferir.
- Un temporal IR debe estar clasificado como borrowed u owned, o el lowering
  debe materializar una convención equivalente verificable. No basta inferirlo
  desde nombres SSA.
- Las optimizaciones de move pueden eliminar pares retain/release si preservan
  el mismo resultado ante self-assignment, branches, phis y panics.

Para `dst = src`, la secuencia segura conceptual es retain(src), cargar old,
store src, release(old). Retener primero hace segura la autoasignación.

Esta política evita:

- **leak permanente:** todo objeto owned tiene una referencia inicial y todo
  owning slot se destruye o transfiere;
- **double free:** solo el release que observa la transición 1→0 libera;
- **use-after-free:** un valor que escapa adquiere ownership antes de que el
  owner anterior se libere;
- **dangling en structs/List:** sus hooks recorren fields/elementos antes de
  destruir backing storage;
- **reallocation:** mueve representaciones sin destruir el source y sin crear
  ownership duplicado.

Si no se pueden implementar y verificar esos hooks, **strings dinámicas deben
seguir rechazadas**. Permitir allocations y aceptar leaks como contrato
transitorio no es una fase segura para programas reales.

## 9. Structs, Array y List

El handle es bitwise movable, pero el tipo `string` deja de ser trivialmente
copiable en el sentido de duplicación. `TypeLayout.trivially_copyable` mezcla
hoy dos conceptos que deben separarse.

El layout necesita al menos:

```text
size, alignment, contains_owned_references
copy_init(dst, src)     # construye copia; retiene transitivamente
move_init(dst, src)     # transfiere; source queda inválido o vacío
assign(dst, src)        # retain antes de release, seguro para alias
destroy(value)          # release transitivo
init_default(dst)       # singleton vacío para string
bitwise_relocatable     # sí para string y structs compatibles
```

`retain`/`release` pueden ser hooks escalares usados para generar los anteriores.
Los structs componen hooks en orden de fields. Las collections aplican hooks al
tipo elemento completo, no buscan strings ad hoc.

| Operación | Contrato para string o struct que contiene string |
| --- | --- |
| asignación / set | `assign`: retener nuevo, reemplazar, liberar anterior. |
| push / insert | `copy_init` del elemento salvo move comprobado de un temporal. |
| get | produce copia lógica owned si el resultado escapa; puede ser borrow efímero durante una expresión comprobada. |
| pop / removeAt | mueve el elemento al resultado, desplaza los restantes y no libera el valor retornado. |
| clear | destruye cada elemento vivo antes de poner length en cero. |
| Array copy / List copy / slice | nuevo backing store y `copy_init` por elemento; un `memcpy` solo no basta. |
| reallocation | bitwise relocation/move de los elementos; el buffer anterior se libera sin destruir copias fantasma. |
| reverse / sort | swaps/moves balanceados; no cambia el número total de owners. |
| return / parámetro | aplica la convención owned/borrowed de la sección anterior. |
| destrucción futura | recorre exactamente el rango de elementos inicializados y llama `destroy`. |

Los `memcpy` actuales siguen siendo válidos únicamente para **relocation** de
un buffer cuyo origen deja de contener elementos vivos. No son válidos para
`copy`, slice o cualquier operación donde origen y destino continúen vivos.

## 10. ABI interna

### 10.1 Política elegida

- Parámetro string: handle `ptr` por valor.
- Return string: handle `ptr` por valor; no `sret`.
- Field: un handle con alineación de puntero.
- Array/List: buffer contiguo de handles, tamaño obtenido del DataLayout; nunca
  hardcodeado a 8.
- Callable: `ptr` en la firma LLVM interna, con la convención de ownership
  documentada en metadata/verificador.
- Módulos: las firmas mangleadas usan la misma representación dentro del
  módulo combinado.
- Runtime: recibe handles para strings y `ptr + i64` para buffers externos.

Aunque el LLVM spelling siga siendo `ptr`, su pointee lógico cambia de byte de
texto a header. Todas las calls a `%s` y `strcmp` deberán migrar; conservar el
spelling no significa compatibilidad semántica con objetos compilados antes.

### 10.2 Alternativas ABI

- Pasar `(ptr,length)` por valor evita dereferencia para length pero duplica el
  ancho y no resuelve owner.
- Pasar puntero a descriptor introduce alias/lifetime de descriptor y una
  carga adicional sin reducir el objeto.
- `sret` es apropiado para aggregates grandes según target, no para un handle.
- Un par LLVM desestructurado acopla todas las firmas a esa representación.
- Un struct LLVM nominal de dos o más words es claro pero infla collections.

El handle de una palabra es eficiente y permite cambiar campos del objeto en
una versión futura. No promete estabilidad binaria: un cambio de runtime puede
requerir recompilar todos los módulos Aether.

## 11. Interoperabilidad con C

La frontera preferida con C es un span:

```c
const char *data;
uint64_t length;
```

Exportar ese span puede ser zero-copy y borrowed durante una call síncrona. El
callee no puede conservar `data` después sin copiar o recibir un owner explícito.

Para una API que exige solo `const char*`:

- el payload tiene cero final, por lo que no hace falta copiar si no hay cero
  interno;
- el adaptador debe buscar cero interno en los `length` bytes y rechazarlo con
  error; entregarlo silenciosamente truncaría contenido;
- el puntero correcto es `object + 24`, no el handle;
- el borrow dura como máximo la call C; el wrapper mantiene vivo el objeto;
- C recibe UTF-8, no locale encoding.

Importar `const char*` requiere scan acotado por una política de seguridad,
validación UTF-8 y copia a un objeto owned. Importar `const char* + length` es
preferible: valida exactamente el rango y admite ceros internos. Un borrow de
memoria externa no debe convertirse en string general salvo que un wrapper
FFI garantice lifetime; v1 copia.

No se declara todavía layout público del header ni funciones C estables.

## 12. Operaciones fundamentales y división de responsabilidades

Regla:

> Una operación solo debe ser intrínseca si necesita acceso directo a la
> representación, ownership, seguridad o una optimización esencial.

| Operación | Clasificación | Motivo |
| --- | --- | --- |
| materializar literal | compiler + objeto runtime estático | Conoce bytes y lifetime en compile time. |
| singleton vacío | runtime primitive | Invariante global y default init. |
| crear desde bytes UTF-8 | runtime primitive | Validación, overflow, allocation y ownership. |
| `byteLength` | builtin/accessor de representación | Carga checked del header; no necesita opcode nuevo. |
| igualdad | operador bajado a runtime call | Necesita header/data y `memcmp`; no instruction especial por backend. |
| concat | runtime primitive futura | Overflow, una allocation y lifecycle. |
| validate UTF-8 | runtime primitive | Frontera de seguridad compartida por IO/FFI. |
| retain/release | compiler-inserted runtime primitive | Lifecycle no visible al usuario. |
| acceso a byte | runtime primitive interna/futura | Bounds; la API pública preferida es `Bytes`. |
| compare por bytes | runtime primitive interna | Sort y búsqueda ordenada. |
| hashing | runtime primitive futura | Debe compartir bytes/seed con Map/Set. |
| decode siguiente code point | runtime primitive pequeña o iterator builtin | Validación y scan eficiente. |
| `trim`, `split`, `replace` | stdlib Aether | Algoritmos sobre iteración/builder. |
| `contains`, `startsWith`, `endsWith`, `find` | stdlib Aether | No requieren opcode; pueden usar bytes seguros. |
| case conversion | stdlib/módulo Unicode futuro | Tablas Unicode versionadas; no runtime mínimo. |
| parsing y formatting | stdlib sobre primitivas numéricas | Política de errores y formato, no layout string. |

Una call runtime conocida puede tener effects precisos en IR/SSA. No es
necesario crear `IRStringTrim`, `IRStringSplit`, etc.

## 13. Concatenación, interpolación y construcción

Se recomienda conservar `a + b` para strings porque ya es semántica visible
AST, pero implementarlo solo en la fase dinámica:

1. cargar longitudes;
2. comprobar `a.length + b.length`, header y terminador;
3. hacer exactamente una allocation;
4. copiar los dos rangos con longitud explícita;
5. escribir el cero final y publicar el objeto con refcount uno.

La operación es O(|a|+|b|), puede allocation-fail y no es pura a efectos del
optimizador. Los ceros internos se copian normalmente.

Para `a + b + c + d` y para interpolación, el compilador podrá reconocer una
cadena en un mismo expression tree y bajar segmentos a un builder interno o
calcular el tamaño total antes de una allocation. No se promete que cada `+`
aislado desaparezca ni se cambia associativity observable. Un builder mutable:

- es privado del runtime/stdlib;
- usa growth checked;
- no es un `string` hasta `finish`;
- queda thread-confined;
- se libera ante error/panic por la estrategia que se apruebe para cleanup.

Interpolación debe bajar a formatting de cada segmento y al mismo builder, no a
un opcode por tipo embebido.

## 14. Parsing y formatting

La API pública se decidirá con la stdlib. La frontera recomendada es
locale-independent y no usa sentinel ambiguo ni nullable para mezclar “valor
cero” con “error”. Aether aún no tiene enums con payload ni `Result<T,E>`, por
lo que una transición coherente usa enums y structs nominales ya existentes:

```aether
enum ParseErrorKind { None, Empty, InvalidDigit, Overflow, TrailingData }

struct IntParseResult {
    boolean ok;
    int value;
    ParseErrorKind error;
    int errorByte;
}
```

`value` solo es significativo cuando `ok`; `error` y `errorByte` cuando no. Es
menos expresivo que un Result con payload, pero no inventa una feature. Cuando
el lenguaje tenga un resultado estructurado mejor, la API podrá revisarse antes
de v1 estable. Excepciones no deben ser la única vía mientras native no las
soporte.

Si el modelo de miembros/namespace lo permite sin sintaxis especial, se
prefieren `int.parse(s)`, `double.parse(s)` y `boolean.parse(s)` como wrappers de
stdlib. `parseInt`/`parseDouble` serían aliases transitorios, no opcodes. La
elección de spelling puede aplazarse; la frontera runtime sigue siendo buffer
con longitud + resultado estructurado. Parsing numérico persistente ignora el
locale y parsing booleano debe enumerar explícitamente los spellings aceptados.

Formatting de primitivos produce strings dinámicas mediante runtime/builder.
El formato persistente es determinista, con punto decimal y sin locale
implícito. Formatos localizados deben pedir un locale explícito. La
interpolación reutiliza exactamente esas reglas.

## 15. Process args y archivos futuros

### 15.1 Argumentos

Una futura `system.args()` puede devolver `List<string>` owned:

- Unix: copiar los bytes de `argv`, validar UTF-8 y devolver error definido si
  no son válidos; una API de bytes puede preservar argumentos arbitrarios.
- Windows: obtener UTF-16 del sistema, convertir a UTF-8 con error ante datos
  inválidos y crear objetos owned.
- Aunque `argv` viva durante el proceso, copiar simplifica plataforma,
  terminación, validación y ownership. Una optimización borrowed sería interna
  y no cambiaría la API.
- `main` sigue sin parámetros hasta una decisión de sintaxis separada.

### 15.2 Archivos

- `readText` valida UTF-8 y devuelve un string owned o error estructurado.
- `readBytes` devuelve `Bytes` y nunca fuerza decode.
- Lectura por líneas puede reutilizar un buffer interno, pero cada string que
  escapa debe tener objeto owned independiente.
- Archivos grandes necesitan límites configurables y streaming; no toda API
  debe cargar a memoria.
- Escritura usa exactamente `byteLength`, por lo que conserva ceros internos.
- Handles, close y errores pertenecen a `io`; el objeto string no posee el
  archivo ni una mapping por defecto.

El expense tracker podrá añadir CSV solo después de estas fronteras, split,
trim, parsing y una política de errores; esta RFC no diseña CSV.

## 16. Evolución de gestión de memoria

| Estrategia futura | Interacción con el diseño |
| --- | --- |
| RC | Política inicial; header y hooks ya la soportan. Para threads podría hacerse atómico con recompilación. |
| GC tracing | El handle sigue apuntando a un objeto. `strong_count` y flags pueden convertirse en header GC; compiler elimina retain/release y registra roots. |
| Manual | Runtime puede conservar retain/release internos, pero no se recomienda exponer `free(string)` al usuario. |
| Arenas | Builders/temporales pueden usar arena y copiar/promover al escapar. Objetos inmortales siguen iguales. |
| Ownership estático | El análisis puede eliminar retains y probar moves sin cambiar sintaxis ni contenido del objeto. |
| Híbrido | Posible para distintos tipos, pero no debe crear dos representaciones públicas de string. |

Permanecen estables a nivel semántico: inmutabilidad, UTF-8 válido, igualdad
por bytes y sharing no observable. El handle de una palabra es la dirección
preferida, pero no una garantía binaria pública. Campos de header, RC y flags
pueden cambiar al recompilar programa y runtime juntos.

## 17. Classes, const e identidad

- `string` es value type semántico con referencia interna especial.
- No hereda de class, no tiene dispatch ni identidad comparable.
- `const string` solo congela el binding.
- Un field string en struct se retiene/libera con hooks de value copy.
- Un field string en class se retiene al asignar y se libera cuando exista
  destrucción de class; hasta entonces no debe habilitarse un productor
  dinámico que pueda almacenarse en una class native sin cleanup.
- Igualdad siempre es contenido. No existe operador público de identidad para
  string.

## 18. Hashing

`Map<string,T>`, `Set<string>`, symbol tables e interning necesitan que hash y
igualdad lean exactamente los mismos bytes. Recomendación:

- hash sobre los `byteLength` bytes UTF-8, incluidos ceros;
- seed aleatorio por proceso para containers expuestos a input adversarial;
- no prometer valores estables entre procesos ni usarlos para persistencia;
- un hash estable, si se necesita para archivos, debe ser una API separada con
  algoritmo/version explícitos;
- no cachear hash en el header v1. Medir primero; un cache futuro requiere
  revisar header y thread safety;
- interning de literales es una optimización. No internar obligatoriamente todo
  string dinámico porque retendría memoria y crea contención global.

## 19. Thread safety

Los bytes inmutables y los objetos `IMMORTAL` pueden leerse concurrentemente.
El RC no atómico propuesto no permite compartir una string dinámica entre
threads. Esto es aceptable solo mientras Aether no tenga concurrencia native.

Antes de agregarla se debe aprobar una de estas políticas: RC atómico para
objetos compartidos, transferencia/ownership estático que impida sharing, o
GC. Un cache de hash compartido necesitaría inicialización atómica o cálculo
repetible sin write. Builders son mutables y thread-confined.

## 20. Seguridad y lugar de verificación

| Riesgo | Verificación responsable |
| --- | --- |
| literal/source UTF-8 inválido | loader/lexer con diagnóstico fuente. |
| bytes externos UTF-8 inválidos | runtime en fromUtf8, IO y FFI boundary. |
| `length + 1`, header + payload, concat overflow | runtime antes de allocation; IR marca may-trap. |
| narrowing i64 a `int` público | runtime helper checked, como Array/List length. |
| out-of-bounds / corte dentro de code point | runtime primitive; typechecker evita `s[i]` no aprobado. |
| cero embebido | length-aware runtime; adaptador C rechaza APIs `char*` incompatibles. |
| use-after-free / double free | ownership verifier/lowering, retain-before-release y runtime debug checks. |
| overflow/underflow de refcount | retain checked antes de incrementar; release de cero es descriptor malformado y trap de runtime debug. |
| aliasing y self-assignment | hook `assign`; nunca release-before-retain. |
| descriptor malformado | IR verifier para constructores internos y runtime debug validation; FFI nunca acepta un header arbitrario como trusted. |
| reallocation | collection hooks distinguen relocation de copy y elementos inicializados. |
| string enorme / DoS | límites de runtime/IO, checked sizes y streaming. |
| hash flooding | hash seeded por proceso en Map/Set futuro. |
| formato C malicioso | nunca usar contenido como format string; formatos son constantes. |
| lifetime de span C | wrapper FFI retiene durante call o copia para storage externo. |

El typechecker protege unidades y APIs visibles; IR/SSA verifican ownership y
efectos; runtime protege datos/tamaños dinámicos; stdlib valida contratos de
alto nivel; FFI trata toda memoria externa como no confiable.

## 21. Compatibilidad y migración desde el repositorio actual

| Área | Estado actual | Diseño propuesto | Migración necesaria |
| --- | --- | --- | --- |
| Literal | global `[N+1 x i8]`, ptr al byte 0 | global header+payload inmortal | cambiar emisión y tests; conservar UTF-8/dedupe. |
| Parámetro | `ptr` C string por valor | `ptr` handle por valor, borrowed durante call | ABI spelling igual, significado/lifecycle nuevo. |
| Return | `ptr` por valor sin ownership | handle owned por valor | insertar retain/transfer y cleanup. |
| Struct field | raw `ptr`, shallow bit copy | handle, value-copy con hooks | separar copy de relocation; actualizar equality/print. |
| Array/List | buffer de ptrs; memcpy/memmove | buffer de handles con lifecycle | hooks en copy/slice/set/clear/remove/realloc. |
| Equality | Python; native general rechazada; `strcmp` en helpers | identidad+length+memcmp para todos | runtime call común; eliminar `strcmp` semántico. |
| Print | Python `str`; native `%s` | write de payload con longitud | helper length-aware para scalar/aggregate. |
| LLVM ABI | `StringType -> ptr` al payload | `StringType -> ptr` al objeto | cambiar pointee lógico y helpers, no necesariamente firmas. |
| AST runtime | Python `str` accidental | adaptador que emule bytes UTF-8/errores/complexidad | centralizar operaciones; no usar Python como contrato. |
| IR type | nominal sin layout | puede mantenerse nominal | agregar calls/effects/ownership metadata. |
| SSA type | nominal; optimizers evitan folding | puede mantenerse nominal | verificar ownership en phi/calls; efectos de concat. |
| Modules | combined module y globals dedupe | mismo ABI en el grafo | emitir objetos literales y lifecycle cross-module. |
| Callables | firma `ptr`, sin ownership | misma forma con convención | verifier y lowering de borrow/owned. |
| Builtins | print/cast/input AST; sin text API | núcleo pequeño + stdlib text | registrar solo APIs aprobadas por fase. |
| Capability profile | partial; detección basada parcialmente en literales | partial por operación/tipo chequeado | detector debe usar tipos, no heurística textual. |
| Expense tracker | strings literales inmortales transportadas | mismas salidas con objetos inmortales | test de migración; luego caso dinámico cuando fase 2. |

Código que asume directa o indirectamente `string == ptr al payload`:

- `backend/llvm/types.py`: mapping `StringType -> ptr` (el spelling se mantiene,
  cambia el significado);
- `backend/llvm/printer.py`: globales, `_literal`, print scalar/struct/secuencia,
  igualdad de struct y secuencias;
- `backend/llvm/layout.py`: trivial copy/reference classification;
- `backend/llvm/runtime.py`: tamaño fijo 8 y `strcmp` de sort;
- `backend/llvm/runtime_common.py`: equality/print de aggregates y declaración
  de `strcmp`;
- `backend/llvm/list_runtime.py`: contains/indexOf/search por `strcmp`;
- `backend/llvm/vector_runtime.py` y `matrix_runtime.py`: helpers comunes de
  igualdad/print string;
- Array/List lowering y runtime: memcpy/memmove, clear/copy/slice/reallocation
  sin element lifecycle;
- IR/SSA verifiers y optimizers: string binary/compare sin representación ni
  efectos de allocation;
- tests LLVM/native y documentación que fijan global C, `%s`, `strcmp`, una
  palabra y shallow copy.

## 22. Plan de implementación por fases

### Fase 0: contrato y diagnósticos

**Subsistemas:** esta RFC, capability profiles/detector, auditoría y errores
públicos.

**Invariantes:** no cambia representación; operaciones dinámicas siguen
rechazadas antes de lowering; el detector usa tipos chequeados y detecta
`a+b`/`a==b` aunque no haya literal.

**Tests:** diagnósticos por concat/comparison/interpolación con parámetros,
variables, imports y ubicación; perfil sigue `PARTIAL`.

**Riesgo:** confundir propuesta aprobada con capacidad implementada.

**Desbloquea:** migración controlada sin errores tardíos del printer.

### Fase 1: objeto, literales y operaciones sin allocation dinámica

**Subsistemas:** IR string contract, `LLVMTypeLayouts`, printer, nuevos helpers
runtime string, print/equality/sort/list search, structs/collections/callables,
AST adapter.

**Invariantes:** todo handle es no nulo y apunta a header válido; literales y
vacío son UTF-8, terminados e inmortales; print/equality nunca usan terminador
como longitud; no existe productor heap público.

**Tests:** layout exacto, vacío, ASCII/no ASCII, ceros internos construidos en
tests de IR, params/returns/phi/imports, structs y Array/List, igualdad por
contenido, sort bytewise, clang y sanitizers cuando estén disponibles.

**Riesgos:** cambiar el significado de cada `ptr`; helpers remanentes `%s` o
`strcmp`; hardcode de pointer size.

**Desbloquea:** ABI y longitud reales, igualdad native general y transporte
seguro de literales.

Esta fase debe introducir la interfaz de hooks aunque retain/release sean no-op
para objetos inmortales. No debe conservar `trivially_copyable=true` como
promesa para strings futuras.

### Fase 2: strings dinámicas y lifecycle

**Subsistemas:** allocator string, UTF-8 validator, RC, ownership lowering y
verifier, cleanup de scopes/branches/returns, hooks recursivos de TypeLayout,
Array/List y builder interno.

**Invariantes:** cada objeto owned tiene contador balanceado; concat hace una
allocation; copy vs move está definido en toda operación; ningún panic pierde
owners ya inicializados.

**Tests:** refcount debug, self-assignment, returns de params/locals, loops y
phi, overwrite, structs anidados, list growth/copy/slice/set/clear/pop/remove,
errores de allocation/overflow/UTF-8, ASan/LSan.

**Riesgos:** cleanup en control flow, ownership de temporales y destructores
parciales. Es el mayor bloque técnico.

**Desbloquea:** concat, formatting básico e interpolación native.

### Fase 3: stdlib `text` y parsing

**Subsistemas:** módulo stdlib Aether, iterador UTF-8, builder, structs/enums de
error y wrappers de primitivas numéricas.

**Invariantes:** unidad explícita; sin normalización/locale implícitos; toda
salida es UTF-8 válida.

**Tests:** trim/split/contains/find/replace/starts/ends con ASCII, multibyte,
combining marks, cero, vacío y strings grandes; parsing válido, inválido,
overflow y trailing data; paridad AST/native.

**Riesgo:** promover demasiados métodos a intrinsics o inventar Result antes de
resolverlo.

**Desbloquea:** lógica textual del expense tracker y formatos persistentes.

### Fase 4: system args y archivos

**Subsistemas:** módulos `system`/`io`, tipo Bytes, adaptadores Unix/Windows,
handles/error cleanup y APIs streaming.

**Invariantes:** decode explícito, lifetime owned, close seguro, límites de
recursos, writes length-aware.

**Tests:** argv Unicode/plataforma, inválidos cuando el SO los permite, empty
args, archivos UTF-8/invalid/binary/zero, líneas, errores, archivos grandes y
cleanup. Dogfood de expense tracker persistente.

**Riesgos:** diferencias de encoding del OS, errores parciales y archivos
grandes.

**Desbloquea:** CLI y persistencia reales.

### Fase 5: optimización

**Subsistemas:** builder fusionado, retain/release elimination, hashing,
interning opcional y profiling.

**Invariantes:** ninguna optimización cambia igualdad, orden, lifetime ni
panics observables.

**Tests:** property/differential, stress, benchmarks y adversarial hashing.

**Riesgos:** SSO o interning prematuros complican ABI/ownership. Solo se
consideran con mediciones.

**Desbloquea:** concatenaciones encadenadas y workloads de texto eficientes.

## 23. Alternativas rechazadas o aplazadas

- **`char*` puro:** rechazado por longitud, cero interno y ownership.
- **UTF-16:** rechazado como encoding canónico; no evita grapheme complexity,
  usa unidades variables y favorece solo ciertas APIs de plataforma.
- **UTF-32:** rechazado por 4x storage aproximado, peor cache/IO y porque
  graphemes siguen sin ser O(1).
- **Deep copy en cada asignación:** rechazado por complejidad y coste en
  funciones, structs y colecciones.
- **String principal mutable:** rechazado; hace observable el sharing, exige
  copy-on-write o aliasing complejo e invalida hashing.
- **Terminador como única longitud:** rechazado; el cero adicional es solo una
  facilidad de FFI.
- **Ownership visible al usuario en v1:** rechazado; no se agregan tipos
  `borrowed string`/`owned string` ni `free`.
- **SSO inmediato:** aplazado. Un handle estable y bytes inline en objeto son
  más simples; SSO ensancharía/taggearía cada valor y complica aggregates.
- **Interning obligatorio:** rechazado por memoria retenida, tabla global,
  contención y semántica accidental de identidad.
- **Python strings en native:** rechazado. Python puede implementar el backend
  AST, nunca definir el ABI ni ser dependencia del ejecutable.
- **Descriptor `(ptr,length)` público:** rechazado para v1 por tamaño y owner;
  sí se usa como span temporal en FFI.
- **Views de substring:** aplazadas por lifetime y retención de buffers.
- **ICU obligatorio:** rechazado para runtime mínimo; collation, graphemes y
  case Unicode completo pertenecen a una capa opcional/futura.

## 24. Preguntas abiertas para aprobación humana

### Bloqueantes antes de implementar

1. ¿Se aprueba el handle de una palabra a objeto, en lugar de `(ptr,length)`?
2. ¿Se aprueba exactamente el header de 24 bytes, sus flags iniciales y
   alignment 8?
3. ¿Se aprueba RC fuerte no atómico como política inicial para strings
   dinámicas, con strings cross-thread prohibidas hasta otra RFC?
4. ¿Se aprueba el cero final obligatorio aun cuando toda semántica use longitud?
5. ¿Se aprueba ABI interna por valor para el handle y resultados owned?
6. ¿Se aprueba que `TypeLayout` separe copy, move/relocation y destroy antes de
   habilitar cualquier productor dinámico?
7. ¿Se aprueba UTF-8 válido como invariante estricto y error —no replacement—
   por defecto en fronteras externas?
8. ¿Qué mecanismo de cleanup verificable usará IR ante branches, returns y
   panics: instrucciones retain/release explícitas, ownership SSA o un lowering
   posterior dedicado?

### Importantes pero aplazables

1. ¿Se confirma que no habrá `s[i]` ni `string.length` ambiguo en v1?
2. ¿La primera substring usa code points y copia, como recomienda esta RFC?
3. ¿Se aprueban `byteLength` y `codePointCount` como nombres públicos?
4. ¿Debe `compareBytes` quedar interno o exponerse como API explícita?
5. ¿Qué forma nominal exacta tendrán los resultados de parsing mientras no
   exista Result con payload?
6. ¿Cuál es el límite configurable para strings/lecturas completas además del
   límite del address space?

### Futuras

1. ¿RC atómico, ownership estático o GC cuando exista concurrencia?
2. ¿Cómo se migra el header a un GC tracing y qué roots requiere el ABI?
3. ¿Se justifica cache de hash, SSO o interning dinámico con benchmarks?
4. ¿Qué módulo/version de Unicode proveerá graphemes, normalización y case?
5. ¿Se expondrá alguna ABI C versionada o solo wrappers generados?
6. ¿Se admitirán substring views bajo un tipo distinto de `string`?

## 25. Recomendación final y primer bloque

Aether debería aprobar `string` como valor inmutable UTF-8, no nulo, con
igualdad por bytes y almacenamiento compartido. La representación recomendada
es un handle de una palabra a un objeto inline con longitud `i64`, refcount,
flags y terminador auxiliar. Literales son objetos inmortales; strings
dinámicas usan RC no atómico hasta que el lenguaje tenga una política general
de concurrencia o GC.

Esta opción preserva densidad en `Transaction`, `List<string>` y
`Array<Struct>`, mantiene calls/returns simples y permite evolucionar el header
sin cambiar sintaxis. La alternativa `(ptr,length)` hace más cara toda
colección y todavía deja ownership sin resolver; `char*` no satisface seguridad
ni complejidad.

El primer bloque recomendado, sin implementar aquí, es la **Fase 0**: aprobar
las ocho decisiones bloqueantes y corregir la detección temprana para todas las
operaciones string tipadas. El primer bloque de runtime posterior es la **Fase
1 completa** —objeto, literales, vacío, print, equality y transporte— junto con
la interfaz de lifecycle. No debe implementarse concat ni ningún productor heap
hasta que copy/move/destroy y cleanup estén verificados.
