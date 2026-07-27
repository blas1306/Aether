# ABI native de Aether

> Estado: **descriptivo y provisional**, 18 de julio de 2026. Documenta el
> contrato observado del profile native 22. No define una ABI pública, una FFI
> ni compatibilidad binaria entre releases.

## 1. Dominios de compatibilidad

Es necesario distinguir cuatro contratos:

| Dominio | Estado actual | Compatibilidad prometida |
| --- | --- | --- |
| semántica observable AST/native | normativa para programas admitidos por profile 22 | stdout/stderr, exit code, panic y archivos según la spec/profile |
| ABI interna del compilador | tipos, firmas y nombres dentro de un módulo LLVM combinado | ninguna entre versiones |
| ABI del runtime | helpers LLVM `private` generados dentro del módulo | no existe como ABI enlazable separada |
| FFI / objetos precompilados | no implementados | ninguna |

Un cambio de layout puede ser válido hoy si se actualizan compiler, runtime y
tests juntos y no cambia la semántica. Después de separar el runtime, todo
cambio de firma, ownership, discriminante, calling convention o layout de un
tipo cruzando la frontera requerirá una versión ABI.

## 2. Target y calling convention actuales

- El emisor no fija `target triple` ni `target datalayout`; Clang completa ambos
  para el host.
- Las funciones usan la calling convention LLVM por defecto, equivalente a la
  C del target para las firmas actuales, pero no se escribe `ccc` ni se prueba
  una matriz de targets.
- No se fijan atributos de visibilidad, `nounwind`, `nonnull`, `dereferenceable`,
  aliasing ni alineación de parámetros Aether.
- Los structs source y resultados agregados se pasan/retornan por valor según
  la ABI que LLVM/Clang elija para el target.
- Los handles se pasan como `ptr` opaco de una palabra target. No hay soporte
  prometido para punteros que no sean los del host donde se ejecuta Clang.
- No se emiten debug locations, object metadata ni versión ABI en el objeto.

Consecuencia: dos objetos generados por versiones distintas no deben enlazarse
entre sí, y una library Aether precompilada no es un producto soportado.

## 3. Entrada de proceso y símbolos

Cuando se crea un ejecutable, el `main` fuente se renombra internamente a
`__aether_program_main` (con sufijos para evitar colisión) y se genera:

```llvm
define i32 @main(i32 %argc, ptr %argv)
```

El wrapper valida que cada argumento sea UTF-8, publica un contexto de proceso
privado, invoca `i32 @__aether_program_main()`, destruye el contexto y devuelve
su resultado. Argumentos inválidos terminan con exit code 2; un panic del
lenguaje usa exit code 1.

El mangling de módulos usa componentes length-prefixed y es path-independent:

```text
__ae_m<module-components>__<kind>_<name-component>
```

Ejemplo conceptual: `A.Item` de kind `struct` produce un nombre que incluye
longitudes, módulo, kind y nombre. El algoritmo está caracterizado por tests,
pero sus nombres siguen siendo ABI interna.

Helpers `aether_*`, globals, runtime y métodos mangleados se emiten normalmente
con linkage `private`. Funciones source ordinarias pueden conservar external
linkage LLVM; eso es un detalle accidental, no una exportación FFI.

## 4. Matriz de representación

| Tipo | Representación LLVM | Tamaño/alineación | Paso/retorno | Estado |
| --- | --- | --- | --- | --- |
| `int` | `i32` signed | 4 bytes en `TypeLayout` | por valor | semántica estable; ABI interna |
| enum sin payload | `i32` | 4 bytes | por valor | discriminante provisional |
| `boolean` | `i1` | layout lógico 1 byte en storage registry | por valor | ABI interna; C `bool` no asumido |
| `float` | `float` en mapper | 4 bytes | profile 22 lo rechaza | no ABI native estable |
| `double` | `double` IEEE binary64 | 8 bytes | por valor | semántica estable; ABI target-dependent |
| `complex` | sin representación | — | — | AST/IR-only |
| `void` | `void` | unsized | retorno sin valor | interna |
| `string` | `ptr` | una palabra target | handle por valor | header y helpers privados |
| callable top-level | `ptr` | una palabra target | function pointer sin captures | provisional |
| `Array<T>` | `ptr` | una palabra target | handle por valor | runtime interno |
| `List<T>` | `ptr` | una palabra target | handle por valor | runtime interno |
| `Vector<T>` | `ptr` | una palabra target | handle por valor | provisional/shape incompleto |
| `Matrix<T>` | `ptr` | una palabra target | handle por valor | provisional/shape externo |
| struct | `%struct.Name = type { fields... }` | padding/alignment del target | por valor | layout source-order, no ABI pública |
| class | `ptr` no nulo a objeto nominal | una palabra target | handle por valor | fundación 5.3A; superficie gated |
| interface | sin LLVM ABI | — | — | unsupported native |
| nullable `T?` | `%nullable.<T> = type { i1, T }` | target-dependent, incluido padding | aggregate por valor | implementado para payload representable |
| tuple source | sin LLVM ABI general | — | — | unsupported native |
| method result | `{ %struct.Receiver [, Value] }` | target-dependent | por valor | detalle de lowering |
| parse/file result | struct nominal `{value,status}` | target-dependent | por valor | detalle runtime/compiler |

`LLVMTypeLayouts` usa expresiones `getelementptr`/`ptrtoint` para que LLVM
calcule tamaños de punteros y structs. No calcula padding de structs en Python.
Los tamaños fijos de int/enum/bool/float/double sí se registran en Python.

El primer field nullable es el tag `has_value`. `false` usa payload
`zeroinitializer` canonical e inactivo; ese payload no se lee, compara, copia
ni destruye. `true` activa el segundo field. Incluso `string?` y otros handles
usan este agregado: `ptr null` no es una representación nullable ni un niche
ABI. El nombre LLVM es determinista y el paso/retorno usa las reglas de
agregados del target, sin heap allocation.

Una constante `int` sólo puede llegar a esta ABI si está en
`[-2147483648, 2147483647]`. El frontend valida los literales antes del
lowering, incluidos argumentos, retornos, fields y elementos; los verificadores
IR/SSA y el printer LLVM rechazan además cualquier constante i32 interna fuera
de rango. LLVM nunca es responsable de truncar o normalizar un literal source.

## 5. String

El handle `string` es no nulo dentro del subset native y apunta al inicio de:

```llvm
%AetherStringObject = type {
    i64 byte_length,
    i64 strong_count,
    i32 flags,
    i32 reserved,
    [0 x i8] utf8_data
}
```

Hechos actuales:

- header fijo asumido por el runtime textual: 24 bytes;
- payload UTF-8 válido, length explícito y un NUL trailing de conveniencia;
- el NUL no participa en la longitud y los NUL embebidos son contenido;
- flags bit 0 = immortal, bit 1 = UTF8 valid;
- `reserved` debe ser cero;
- objeto dinámico inicia con strong count 1;
- objeto immortal no cambia su contador;
- empty string es un singleton private immortal;
- retain rechaza cero/negativo y `2^63-1`; release rechaza underflow;
- último release libera el bloque completo;
- argumentos son borrowed, una copia owned hace retain y un retorno entrega un
  owner válido según lifecycle lowering.

Ningún offset, flag o nombre `aether_string_*` es público. Un runtime separado
debe preferir handles opacos y accessors ABI antes que publicar este header.

## 6. Array y List

Layouts observados:

```llvm
%AetherArray = type {
    i64 length,
    ptr data,
    i64 strong_count
}

%AetherList = type {
    i64 length,
    i64 capacity,
    ptr data,
    i64 strong_count
}
```

Contrato interno actual:

- el handle es un puntero no nulo al header heap;
- `data` es null para una allocation de cero bytes y apunta a storage contiguo
  para longitudes positivas;
- length/capacity internos son i64, pero la superficie `length` retorna i32 y
  panica si no cabe;
- Array tiene longitud fija; List mantiene `capacity >= length` y puede cambiar
  `data` sin cambiar el header;
- strong count es i64 no atómico, inicia en 1 y tiene máximo `2^63-1`;
- assignment/copy de handle hace retain y conserva aliasing;
- `copy()`/slice crean header y buffer nuevos y hacen copia lógica de elementos;
- el último release destruye elementos vivos en orden inverso, libera buffer y
  luego header;
- capacity no participa en igualdad ni semántica observable;
- el lifecycle de T se especializa recursivamente para strings, handles y
  structs.

Los índices exactos de fields aparecen en los runtime generators y también en
`LLVMPrinter`; por eso estos layouts no deben cambiarse hasta introducir un
descriptor canónico o accessors ABI.

## 7. Vector y Matrix

Ambos se representan como `ptr` a storage compatible con `%AetherArray` en las
operaciones actuales. Vector transporta orientación en `IRType`; Matrix usa un
buffer plano row-major y varias instrucciones llevan `rows`, `cols` o shape
como metadata inmediata.

Esto es provisional:

- no hay header nominal separado;
- no hay contrato de ownership equivalente completo al de Array/List;
- dimensions no forman parte de un handle ABI autónomo;
- index source es 1-based para Vector/Matrix, a diferencia de Array/List;
- no se puede pasar un Matrix opaco a otro componente y recuperar su shape de
  manera general.

No debe exponerse Vector/Matrix por FFI ni cruzar un runtime separado hasta
definir descriptor, ownership y shape.

## 8. Structs, métodos y enums

### Structs

Los fields se emiten en orden de declaración. LLVM decide offsets, padding,
alineación y reglas de paso/retorno. Un struct debe ser acíclico por valor y
todos sus fields deben tener layout representable. La copia lógica recorre
fields en orden; destroy lo hace en orden inverso.

Un cambio de orden/tipo de field, representación de un field, target DataLayout
o algoritmo de mangling rompe compatibilidad binaria.

### Métodos

Los receivers struct tienen value semantics. Una llamada a método que puede
actualizar el receiver devuelve un agregado interno:

```text
method_result<Receiver, void> -> { Receiver }
method_result<Receiver, T>    -> { Receiver, T }
```

Lowering extrae el receiver actualizado y el resultado source. Este agregado
no forma parte del lenguaje ni de una futura FFI; puede cambiar al separar ABI
de métodos.

### Enums

Enums sin payload usan `i32`. El discriminante actual es el índice 0-based del
variant en orden fuente. `IREnumConstant` conserva nombre nominal, member ID y
discriminante hasta LLVM. Reordenar variants rompe objetos existentes, aunque
hoy esos objetos no se prometen compatibles.

## 9. Callables y funciones

Una callable soportada es una referencia a función top-level sin captures y se
transporta como `ptr`. La firma vive en `FunctionType`, no en el handle. La call
indirecta emite el tipo de argumentos/retorno desde SSA.

No están definidos:

- closures/environments;
- null callable;
- comparación/identidad callable;
- lifecycle de captures;
- validación runtime de signature;
- ABI FFI para callbacks.

La ABI futura debe usar un descriptor `{function, context, vtable/drop}` sólo
cuando closures sean un requisito; no debe anticiparse ahora.

## 10. Ownership en parámetros y retornos

Convención semántica implementada para valores no triviales:

| Posición | Convención |
| --- | --- |
| literal/allocation | produce un owner |
| local owning storage | consume/mantiene un owner y lo destruye al salir |
| argumento normal | borrowed durante la call; callee retiene si lo almacena |
| assignment/copy init | copia lógica; retain para handles |
| move/return transfer | transfiere ownership y deja source muerto |
| retorno no trivial | owned para caller |
| get de elemento | borrowed sólo cuando el opcode lo marca; en otro caso copy-init/retain |
| `for-in` collection element | borrowed read-only durante la iteración |

`IRStorage`, `IRCopyInit`, `IRMoveInit`, `IRAssign`, `IRDestroy`, `IRRelocate` y
`transferred_storage` expresan el contrato antes de SSA. `expand_lifecycle()`
lo baja a primitivas/calls ARC. Native panic termina el proceso y no hace
unwind; no existe cleanup de stack por panic recuperable.

Para `T?`, parámetros siguen borrowed y retornos siguen owned cuando el tag
está presente. Copy/destroy/retain/release inspeccionan primero el tag y
delegan a `T` únicamente para present; absent no ejecuta lifecycle del payload.

### 10.1 Class references (Phase 5.3A)

Una class cruza calls como el mismo `ptr` opaco; nunca se copia el payload.
Parámetros son borrowed durante la call. Un callee que almacena el handle hace
retain. Allocation produce un owner, copy/assignment agregan un owner, move y
return lo transfieren, y el owning local libera al salir.

El header privado es `{ptr descriptor, i64 strong_count, i32 flags, i32
reserved}`. El descriptor contiene ID nominal, size/alignment calculados por
LLVM, callbacks destroy/trace, flags y versión. `class_new` usa allocation
checked, zero-inicializa el objeto vacío, fija count 1 y publica un handle no
nulo. El último release llama destroy y `free`; retain/release validan
overflow, zero y underflow.

`==`/`!=` de `ClassRefType(C)` usan `icmp eq/ne ptr` sólo para el mismo tipo
nominal. `C?` sigue siendo `{i1, ptr}`; `ptr null` no es un valor `C` ni un
niche nullable. Esta ABI interna no habilita constructores, fields, métodos o
interfaces source.

## 11. Panic, IO y proceso

- Un panic público imprime el mensaje mediante helpers basados en `puts` y
  llama `exit(1)`; termina en `unreachable`.
- Startup con argv no UTF-8 escribe en stderr y devuelve 2.
- No hay excepción/unwind native ni error object ABI.
- Printing usa libc (`printf`, `fputs`, `fwrite`, `putchar`) y locale C temporal
  para doubles.
- File IO native usa llamadas POSIX/Linux y mapea errno a enums Aether; Windows
  y plataformas no Linux se rechazan para estas capacidades.
- `System.args()` crea un Array<string> owned desde `argv`.

Los valores exactos de status forman parte de la semántica de los enums
documentados, pero las firmas libc, flags POSIX y helpers privados no son ABI
Aether.

## 12. Dependencias externas

Según las features usadas, el módulo declara símbolos de:

- allocation/memory: `malloc`, `realloc`, `free`, LLVM memcpy/memmove;
- process/IO: `exit`, `puts`, `printf`, `fputs`, `fwrite`, `strlen` y streams;
- text/locale: `memcmp`, `strtod_l`, `newlocale`, `uselocale`, `freelocale`,
  `snprintf`;
- math: libc/libm y LLVM intrinsics;
- files POSIX: `open`, `read`, `write`, `close`, `fsync`, `mkstemp`, `rename`,
  `unlink`, `__errno_location`.

`LLVMBuilder` agrega `-lm` cuando detecta declaraciones matemáticas. No hay
manifest de imports runtime, son detectados a partir del LLVM textual.

## 13. Estabilidad y decisiones pendientes

| Área | Estable semánticamente | Provisional/interna | Pendiente antes de versionar |
| --- | --- | --- | --- |
| int | signed checked i32; literales fuera de rango rechazados en frontend | LLVM `i32` | target matrix |
| bool/double | valores públicos | reglas exactas de paso target | target matrix |
| strings | UTF-8, equality, ARC observable indirecto | header, flags, helper names | handle ABI/accessors/threading |
| Array/List | aliasing, copy/slice, Eq, lifecycle | headers, counters, helpers | ABI version + alloc/error policy |
| class ref | identidad, aliasing, ARC, transporte y Eq identidad | header/descriptor/helpers 5.3A | payload/constructores, ABI version, ciclos |
| structs/enums | orden de fields/variants y value semantics | concrete target ABI/mangling | object compatibility policy |
| callables/method results | comportamiento source subset | representación | closure/method ABI |
| panic | output/code según spec | `puts/exit`, no unwind | error ABI y threading |
| files/process | observables del profile | POSIX implementation | platform providers |

Decisiones que no deben tomarse implícitamente:

1. ABI por target versus ABI portable propia.
2. panic abort/exit versus unwind/result.
3. contadores atómicos versus runtime single-threaded.
4. allocator provisto por runtime versus inyectable.
5. headers públicos versus handles opacos.
6. versionado de object format y compatibilidad de mangling.
7. implementación y eventual versionado de la estrategia de
   nullable/classes/interfaces aprobada en
   [`NATIVE_OBJECT_MODEL_DESIGN.md`](NATIVE_OBJECT_MODEL_DESIGN.md), y la
   estrategia todavía separada de closures.

## 14. Forma recomendada de la ABI runtime futura

Sin implementarla todavía, la frontera debe ser una C ABI estrecha:

```c
/* nombres ilustrativos, no API aprobada */
uint32_t aether_runtime_abi_version(void);
void aether_string_retain(AetherString *value);
void aether_string_release(AetherString *value);
AetherStatus aether_string_concat(
    const AetherString *left,
    const AetherString *right,
    AetherString **out);
```

Principios:

- `extern "C"`, integer types de ancho fijo y structs C sólo donde sea seguro;
- handles opacos para objetos runtime;
- `out` parameters/result structs explícitos para operaciones fallibles;
- ownership escrito en cada parámetro/retorno;
- sin excepciones Rust/C++ cruzando la frontera;
- allocator y panic encapsulados;
- symbol prefix + versión ABI;
- header generado/comprobado contra Rust;
- tests de layout/size/alignment por target;
- backend llama ABI, nunca fields del header.

La primera versión debe ser **interna del runtime**, no una FFI pública. La FFI
requiere además estabilidad de nombres, tipos source, linking, panic y object
format que hoy no existen.

## 15. Cambios que rompen compatibilidad

Cuando exista runtime separado u objetos reutilizables, romperán ABI:

- cambiar tipo/orden de un field de header o struct exportado;
- cambiar i32/i64/pointer width esperado;
- cambiar discriminantes enum;
- cambiar calling convention o aggregate return;
- cambiar ownership borrowed/owned;
- renombrar/remover símbolos runtime;
- cambiar mangling;
- introducir null como handle válido;
- cambiar alignment/padding o target sin distinguir artefactos;
- cambiar panic/exception behavior cuando cruza la frontera.

Hasta entonces, estos cambios siguen siendo internos pero deben actualizar este
documento antes de modificar implementación y tests.
