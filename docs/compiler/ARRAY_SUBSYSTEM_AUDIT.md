# Auditoria tecnica del subsistema `Array<T>`

## Alcance y metodo

Esta auditoria describe el repositorio al 12 de julio de 2026. Es una revision
estatica de parser, AST, typechecker, interprete AST, IR, interprete IR, SSA,
optimizadores, backend/runtime LLVM, tests, ejemplos, spec y documentos de
diseno. No se modifico implementacion, tests ni ejemplos y, por restriccion del
encargo, no se ejecuto la suite. "Cubierto" significa que existe un test que
expresa el caso, no que se haya revalidado en esta auditoria.

Se revisaron principalmente:

- `src/aether/{ast.py,parser.py,typechecker.py,interpreter.py,types.py}`;
- `src/aether/{native_members.py,stdlib/core.py}`;
- `src/aether/ir/`, incluidos lowering, verifier, interpreter y optimizadores;
- `src/aether/ssa/`, ambos builders, verifier y todos los optimizadores;
- `src/aether/backend/llvm/{printer.py,list_runtime.py,runtime.py}`;
- `tests/aether/test_array_backend.py`,
  `test_collections_and_math_literals.py`, `test_sequence_sort.py`, tests de
  IR/SSA/LLVM y ejemplos Array;
- `docs/aether/` y la documentacion de `docs/compiler/` relacionada.

El interprete AST y el interprete IR son backends alternativos, no etapas del
ejecutable nativo. El camino nativo efectivo es AST tipado -> IR -> SSA
optimizado -> LLVM. El optimizador IR se usa en su propio pipeline; LLVM usa el
pipeline SSA.

## Resumen ejecutivo

Clasificacion global: **inconsistente**.

`Array<T>` es util y coherente en frontend y en ejecucion IR: es fijo, mutable,
0-based, reference-type y tiene aliasing observable. El backend nativo conserva
identidad mediante un header heap estable y `sort` esta especialmente bien
consolidado con `List`. Sin embargo, las garantias de seguridad cambian segun
el backend:

- AST e IR validan get/set; LLVM no valida ningun indice Array y calcula el GEP
  directamente.
- El header LLVM es `%AetherArray = type { i64 length, ptr data }`; no contiene
  capacity y no coincide con `%AetherList`.
- Array allocation comparte el allocator con List y detecta `malloc == null`,
  pero `length * element_size` es un `mul i64` sin overflow check.
- `Array.length` carga `i64` y hace `trunc i64 to i32` sin comprobar
  representabilidad.
- `copy` existe como builtin y metodo solo en frontend/interprete AST. No hay
  `IRArrayCopy` ni backend nativo.
- `IRArrayGet`/`SSAArrayGet` se clasifican como productores puros eliminables,
  aunque en el interprete IR son `may_trap`; DCE puede borrar un acceso invalido
  cuyo resultado este muerto.
- `sort` usa un unico `IRSequenceSort`/`SSASequenceSort` y los mismos helpers
  LLVM especializados que List, con allocation y bytes comprobados.
- El runtime Array sigue alojado en `list_runtime.py`; la logica de emision de
  campos, get/set/length permanece en `printer.py`.

La cantidad de features y tests felices no compensa las tres brechas P0:
bounds nativos, bytes de allocation sin check y narrowing silencioso. Por eso
la clasificacion no es "aceptable" ni "solido".

## 1. Representacion real

### AST Interpreter

Un Array es:

```text
AetherValue(ArrayType(T), list[AetherValue])
```

La lista Python contiene los elementos y su `len()` es la longitud. No hay
header, buffer separado ni capacity. `AetherValue` es frozen, pero su `value`
es una lista mutable. Asignacion, parametro y return de tipos exactamente
iguales conservan el mismo objeto lista. `copy` construye otra lista exterior
con `list(xs.value)` y conserva los mismos objetos elemento: es shallow.

### IR e IR Interpreter

`ArrayType(element)` es un tipo nominal del IR. Los opcodes reales son:

```text
IRArrayNew(result, elements)
IRArrayGet(result, array, index)
IRArraySet(array, index, value)
IRArrayLength(result, array)
IRSequenceSort(sequence)       # compartido con List
```

No hay un struct/header en el modelo IR. El interprete IR representa Array con
una lista Python plana. Por eso la longitud es `len(array)`, el objeto sirve de
handle compartido y no existe capacity. Parameters, stores/loads locales y
returns transmiten la misma referencia. No existe `IRArrayCopy`.

### SSA

SSA conserva exactamente los handles y opcodes correspondientes:
`SSAArrayNew`, `SSAArrayGet`, `SSAArraySet`, `SSAArrayLength` y
`SSASequenceSort`. Un set o sort muta almacenamiento alcanzable desde el
handle; no crea una nueva version SSA del contenido. No existe Memory SSA ni
alias analysis.

### LLVM

El layout emitido es:

```llvm
%AetherArray = type { i64, ptr }
; campo 0: length
; campo 1: data
```

Un `Array<T>` es un `ptr` al header de 16 bytes asumidos. `data` apunta a un
segundo allocation contiguo con representaciones ABI de T. Para un Array vacio
`aether_alloc(0)` retorna null, de modo que `data == null` y `length == 0`.

No existe capacity, ni publica ni accidental. `%AetherArray` tambien es la
representacion contigua reutilizada por Vector y Matrix; el nombre no implica
que esos tipos tengan semantica Array.

Comparacion explicita:

| Propiedad | `%AetherList` | `%AetherArray` |
| --- | --- | --- |
| Layout | `{ i64 length, i64 capacity, ptr data }` | `{ i64 length, ptr data }` |
| Header asumido | 24 bytes | 16 bytes |
| Length | campo 0, mutable | campo 0, fijo tras new |
| Capacity | campo 1 | no existe |
| Data | campo 2 | campo 1 |
| Identidad | `ptr` al header | `ptr` al header |
| Growth | puede cambiar data, conserva header | no existe |

El header Array es estable de facto dentro del backend actual: new lo crea una
vez; asignaciones, parametros, returns y phi copian el `ptr`; set/sort no lo
reemplazan. No es todavia un ABI normativo independiente: layout, 16 bytes,
punteros de 8 bytes y alineacion estan codificados en el emisor, sin data
layout/target guard ni documento de ownership.

### Aliasing entre capas

| Caso | AST Interpreter | IR Interpreter | LLVM | Estado |
| --- | --- | --- | --- | --- |
| asignacion `b = a` | misma lista Python | mismo objeto | copia de `ptr` | coherente |
| parametro | mismo objeto | mismo objeto | parametro `ptr` | coherente |
| return | mismo objeto | mismo objeto | return `ptr` | coherente |
| campo struct/class | conserva referencias dentro de valores struct copiados | no soportado | no soportado | frontend solamente |
| `copy(a)` | lista exterior nueva, elementos shallow | no hay opcode | no implementado | divergente |
| alias `const` | const bloquea mutacion por esa raiz; alias mutable puede mutar | const no llega al IR | igual que handle normal | frontend solamente |

La semantica pedida `b = a; b[0] = 9` esta implementada y probada en AST, y el
modelo pointer del backend la conserva. `b = a.copy()` aisla el contenedor solo
en AST. Arrays anidados copiados son shallow por implementacion, pero no hay un
test dedicado ni contraparte native.

## 2. Operaciones reales por capa

`Frontend` agrupa parser/typechecker/native members. `Optimizer` cubre ambos
pipelines. No se inventarian operaciones Array inexistentes.

| Operacion | Frontend | AST | IR | SSA | Optimizer | LLVM | Tests | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| literal `{...}` con target `Array<T>` | si; homogeneidad, widening, empty con target | lista Python | `IRArrayNew` | `SSAArrayNew` | allocation conservada; operands reescritos | header+buffer, stores inline | frontend/IR/SSA/native; empty y tipos | funcional, allocation bytes insegura |
| `length` / `.length` | builtin y propiedad tipados | `len`, sin check i32 | `IRArrayLength` solo para propiedad/for | `SSAArrayLength` | lectura eliminable, no se pliega | load i64 + trunc i32 | AST/IR/SSA/native normal | narrowing inseguro; builtin global no baja |
| index read `a[i]` | indice int, 0-based | check antes de read | `IRArrayGet`, check en interpreter | `SSAArrayGet` | DCE lo trata como puro | data load, sext, GEP, load | validos; AST igual a length | inseguro en native y mal clasificado |
| index write `a[i] = v` | indice/tipo/const validados | check antes de evaluar commit | `IRArraySet`, check antes de store | `SSAArraySet` | side-effect conservado | data load, sext, GEP, store | validos; AST igual a length | inseguro en native |
| asignacion/parametro/return | reference-type | alias | handle compartido | handle compartido | sin alias analysis | copia/paso/return de ptr | asignacion AST; parametro native; contexts frontend | semantica presente, cobertura incompleta |
| `copy(a)` / `a.copy()` | ambas formas aceptadas | shallow outer copy | no opcode; lowering rechaza Array | no | no | no | AST global/metodo | frontend solamente |
| `sort(a)` / `a.sort()` | tipos int/double/string | estable, in-place | `IRSequenceSort` | `SSASequenceSort` | efecto conservado y reescrito | helper comun checked | suite AST/IR/SSA/text/native | solido |
| `for x in a` | tipado | itera lista | length + get en CFG | opcodes correspondientes | hereda clasificacion de get | loop + get sin bounds | AST regression; no suite Array de safety | funcional, hereda riesgo native |

No se encontro slice Array, constructor `array(...)`, reserva, append/remove ni
otra API Array real. La aritmetica Array del interprete pertenece al area de
algebra lineal/frontend y no baja como una operacion de coleccion Array; no se
cuenta como API del subsistema fijo.

## 3. API prevista frente al estado real

La API acordada para esta comparacion es `length`, `isEmpty`, `copy`,
`contains`, `indexOf`, `swap`, `reverse`, `sort`. El codigo usa actualmente
`.length`, `.copy()` y `.sort()`; no se debe confundir `List.is_empty` con un
miembro Array.

| API | Estado real | Evidencia/diseno |
| --- | --- | --- |
| `length` | implementada hasta LLVM, con narrowing nativo inseguro; forma global solo AST | native member + `ArrayLength` |
| `isEmpty` | no implementada | mencionada solo como candidata futura comun en el diseno de sort |
| `copy` | parcial, frontend/AST solamente | builtin/metodo y shallow copy; sin IR opcode |
| `contains` | no implementada | solo candidata futura; helpers actuales son exclusivos de List |
| `indexOf` | no implementada | solo candidata futura; narrowing/helper exclusivos de List |
| `swap` | no implementada ni disenada como operacion nativa | ejemplos definen una funcion de usuario, no API |
| `reverse` | no implementada | candidata futura; `IRListReverse` no acepta Array |
| `sort` | implementada extremo a extremo | contrato y helper comun List/Array |

La spec general conserva texto historico que llama `sort` Array "design-only"
aunque el codigo y los tests ya lo implementan. `AETHER_COLLECTIONS_DESIGN.md`
define correctamente tamaño fijo, mutabilidad, aliasing y literal target-typed,
pero no fija la API completa. `AETHER_SEQUENCE_SORT_DESIGN.md` si define el
contrato compartido, aunque aun usa lenguaje futuro en algunas secciones.

## 4. Bounds checks

Contrato observado en AST e IR: `0 <= index < length`, con indices publicos
`int` y base cero.

| Caso | AST | IR Interpreter | LLVM |
| --- | --- | --- | --- |
| negativo | rechazado | rechazado | sext negativo + GEP fuera del buffer |
| `index == length` | rechazado | rechazado | GEP one-past; get carga/store escribe fuera |
| `index > length` | rechazado | rechazado | acceso fuera del buffer |
| Array vacio | rechazado | rechazado | GEP sobre `data == null` |
| get | check antes de indexar | check antes de indexar | no check ni panic |
| set | check y coercion antes de store | check antes de store | no check; store directo |

`_array_element_pointer` carga `data`, hace `sext i32 -> i64` y calcula GEP.
Nunca carga `length`. Por tanto no solo falta el panic: el GEP se calcula sin
haber decidido bounds. En set, un error de rango puede corromper memoria. No
hay escritura parcial de header, pero si puede haber escritura fuera del
buffer antes de cualquier fallo controlado.

List ya tiene `aether_list_check_index`, ejecutado antes de cargar data,
calcular GEP y load/store. No se puede reutilizar directamente porque lee un
`%AetherList`; si se comparte el nucleo, debe recibir `index,length` o tener un
wrapper Array que conozca su layout.

`for` genera una condicion `index < ArrayLength` y despues `ArrayGet`. Para el
indice generado por el compilador ese camino queda acotado, pero no convierte
`ArrayGet` en intrinsecamente seguro ni cubre accesos explicitos. Mutaciones en
el cuerpo no cambian length porque Array es fijo.

## 5. Overflow, allocation y offsets

### Construccion

`aether_array_new(element_size, length)` realiza:

1. `aether_alloc(16)` para el header;
2. store de `length`;
3. `%data_size = mul i64 %element_size, %length` sin check;
4. `aether_alloc(data_size)`;
5. store de data y return del header.

`aether_alloc` retorna null para size cero y, para size no cero, hace panic si
`malloc` retorna null. Por ello allocation failure de header/buffer esta
cubierto. El producto envuelto no lo esta: puede reservar un buffer pequeno y
los stores/GEP posteriores asumir el length grande.

Hoy `ArrayNew` solo nace de un literal y length es `len(elements)` calculado por
el compilador, sin constructor de longitud dinamica. Eso reduce la
alcanzabilidad desde fuente normal, pero no convierte el helper ni su ABI en
seguros; ademas la misma primitiva sirve a Vector/Matrix y resultados
contiguos.

### Copy

No existe copy LLVM Array, por tanto no hay actualmente memcpy/memmove Array
que auditar. La copia AST crea otra lista exterior y no modela overflow/OOM.
Agregar backend copy en el futuro deberia usar checked bytes antes de reservar
o copiar, como ListCopy; esta auditoria no agrega esa API.

### Sort

Array y List llaman exactamente a `aether_sort_i32`, `aether_sort_f64` o
`aether_sort_string(data, length)`. El helper:

- valida `length * element_size` con `aether_checked_allocation_bytes`;
- usa `aether_alloc` para el temporal;
- valida bytes de cada run antes de `memcpy`;
- acota `mid/right` mediante restas y selects;
- duplica width solo si hay espacio, o lo fija a length.

No se detecto un add/shift envolvente en el control de sort. Los GEP internos
dependen del length del header; si un Array fue creado con data_size envuelto,
sort no repara el buffer ya subasignado, aunque su temporal si se valida.

### Tabla de riesgos

| Calculo/recurso | Estado | Prioridad |
| --- | --- | --- |
| header Array 16 bytes | OOM checked; tamaño hardcoded para ABI asumida | P2 |
| `length * element_size` de new | `mul` sin overflow | P0 |
| buffer de new | OOM checked sobre tamaño ya calculado | P0 por producto |
| GEP get/set | sin bounds; indice sext i64 | P0 |
| length de literal | constante no negativa; no limite explicito i64/i32 | P0 por retorno i32 |
| copy | no existe native | P3 funcional |
| temporal/bytes sort | checked | cubierto |
| offsets sort | acotados por length | cubierto bajo header valido |

## 6. Truncamientos

El tipo fuente `int` y `IntType` LLVM son i32. Los indices entran como i32 y se
extienden con signo a i64, lo que preserva negativos para un futuro check.

La longitud interna del header es i64, pero `SSAArrayLength` produce `IntType`:

```llvm
%len64 = load i64, ptr %len_field
%result = trunc i64 %len64 to i32
```

No se comprueba `0 <= length <= INT32_MAX`. Si excede el rango, `.length` puede
devolver cero, negativo u otro valor truncado. List resolvio el mismo problema
con `aether_list_length_to_int`; Array no usa ese helper ni uno generico.

La forma global `length(a)` devuelve `int` correctamente en AST usando Python
`len`, pero `IRLowerer` no la reconoce: solo baja `.length` y el length interno
de `for`. El interprete IR devuelve un entero Python sin simular i32, creando
otra divergencia de representabilidad.

## 7. Sort compartido

La consolidacion de sort es la parte mas robusta del subsistema:

- frontend acepta solo `int`, `double` y `string` tanto para List como Array;
- AST usa sort estable; strings se ordenan por bytes UTF-8 y double coloca
  numeros en orden, luego NaN como clase equivalente;
- IR/SSA usan una sola instruccion `SequenceSort`, side-effecting;
- LLVM extrae data/length segun cada layout y llama al mismo helper por T;
- los helpers se deduplican por modulo aunque haya List y Array del mismo T;
- no cambia length, header ni identidad; todos los aliases ven el orden nuevo;
- int/double/string, infinidades, NaN, duplicados, alias y native estan
  cubiertos.

No se encontro logica residual de ordenamiento Array separada. La duplicacion
se limita a extraer campos de layouts distintos, lo cual es necesario.

## 8. Optimizadores y efectos

Clasificacion semantica recomendada de lo que existe hoy:

| Instruccion | Clasificacion real necesaria | Tratamiento actual | Evaluacion |
| --- | --- | --- | --- |
| `ArrayNew` | allocation observable/conservadora; may panic OOM | no esta en DCE pure | correcto y conservador |
| `ArrayGet` | read-only + `may_trap` | DCE IR/SSA la declara pure/removable | bug P1 (semanticamente visible en IR) |
| `ArraySet` | side-effecting + `may_trap` | nunca removible; SCCP la conserva | efecto preservado |
| `ArrayLength` | read-only; hoy no trap en objetos validos | pure/removable | aceptable hoy; debera ser may_trap si narrowing checked hace panic |
| `SequenceSort` | side-effecting + allocation/panic | nunca removible | correcto |

`constant_folding` no pliega contenido/length Array. Propagacion local/global y
SCCP marcan los resultados agregados como desconocidos/overdefined, sin
inventar hechos de memoria. Algebraic simplification, SCCP transformer,
dead/trivial phi y ambos builders reescriben los operandos Array y
`SequenceSort` explicitamente.

Inconsistencia principal: DCE puede eliminar `a[i]` muerto y con ello eliminar
el error que produce el interprete IR. En LLVM el get no tiene check, pero la
semantica del lenguaje sigue exigiendo el trap; la falta de backend no justifica
clasificarlo pure. `ArraySet` queda preservado aunque el backend carezca de
bounds.

No hay tests dedicados que pasen ArrayNew/Get/Set/Length por cada optimizador,
ni un test "ArrayGet muerto pero fuera de rango". La correccion depende de
listas manuales repetidas en DCE, SCCP, algebraic simplification, dead/trivial
phi, builders, printers y verifiers.

## 9. Duplicacion LLVM y runtime

### Duplicacion encontrada

- `_array_data_pointer` y `_array_length64` centralizan parte del acceso, pero
  `list_runtime.py` vuelve a escribir GEPs Array dentro de `aether_array_new`.
- get y set repiten data load, sext, GEP; no tienen helper comun de bounds.
- ArrayLength y sort vuelven a extraer length por caminos distintos del
  runtime textual.
- `aether_array_new`, tipos `%AetherArray/%AetherList`, allocator, panics,
  checked multiplication y helpers List viven todos en `list_runtime.py`.
- `LLVMPrinter` mantiene flags Array/List y arma manualmente las dependencias
  runtime.
- el descriptor de operandos/resultados/efectos esta duplicado extensamente en
  IR y SSA, no solo en LLVM.

### Que compartir con List

Reutilizable directamente:

- `aether_alloc` y allocation-failure panic;
- `aether_checked_mul_i64` y `aether_checked_allocation_bytes`;
- la infraestructura de panic (`puts`, `exit`, `unreachable`);
- los helpers especializados de sort;
- una primitiva de check que reciba `index` y `length`, sin conocer header.

Generalizable de forma segura:

- generacion/dependencias de secciones runtime;
- checked conversion de length i64 a Aether int con mensaje por contenedor o
  wrapper especifico;
- helpers Python para cargar campos y formar punteros de elemento despues del
  check;
- metadata `operands/result/reads/writes/may_trap/allocation` para IR/SSA.

No debe compartirse directamente:

- acceso por numero de campo: data es 1 en Array y 2 en List;
- layout/header y tamaño 16 vs 24;
- capacity/reserve/growth/commit de length, exclusivos de List;
- el check actual `aether_list_check_index(ptr list, ...)`, porque interpreta
  el header como List;
- copy List hasta que exista un opcode/contrato Array backend.

### Estrategia recomendada

Se recomienda **B: helpers comunes de secuencia + runtimes especificos**.

- Un nucleo pequeno `sequence_runtime.py` (o equivalente) debe poseer allocator,
  checked arithmetic, conversiones/panics comunes y sort storage-oriented.
- `array_runtime.py` debe poseer layout Array, new y wrappers Array de
  bounds/length.
- `list_runtime.py` debe conservar layout, capacity, growth y operaciones
  dinamicas List.

A mantiene aislamiento, pero deja duplicados precisamente los checks que ya
divergieron. C, generalizacion total, forzaria capacity/growth sobre un Array
que no los tiene o introduciria un layout comun artificial. B comparte solo
garantias independientes del layout y mantiene clara la semantica fija.

## 10. Panics y errores

| Situacion | AST | IR Interpreter | LLVM |
| --- | --- | --- | --- |
| bounds get/set | `Array index N out of bounds for length L (0-based)` | `IR array index N out of bounds for length L` | ausente |
| allocation overflow new | no modelado | no modelado | ausente |
| allocation failure | Python/runtime host | Python/runtime host | `Aether panic: memory allocation failed` |
| length fuera de int | ausente | ausente | trunc silencioso |
| tipo/indice invalido | `AetherTypeError` | verifier/`IRExecutionError` | verifier/`LLVMBackendError` antes de ejecutar |
| sort no soportado | error de tipo | verifier/interpreter error | backend rechaza tipo si llega invalido |
| overflow temporal sort | no modelado | no modelado | `Aether panic: allocation size overflow` |

Los mensajes AST e IR no son identicos, pero ambos son controlados. Native no
tiene mensajes Array de bounds, overflow ni length. Compartir el mensaje de OOM
y overflow de allocation con List es correcto; bounds y narrowing pueden usar
wrappers Array para conservar diagnostico claro.

## 11. Cobertura de tests y ejemplos

### Fortalezas

- `test_collections_and_math_literals.py` cubre literal, vacio, typing por
  declaration/param/return/field, read/write, length, alias por asignacion,
  copy global/metodo, const, tipo de elemento, Array/List distintos, nested
  Array, string/double y rechazo de slice.
- `test_array_backend.py` comprueba lowering IR, ejecucion IR, presencia SSA y
  clang para literal/get/set/length y parametro Array.
- `test_sequence_sort.py` comparte casos List/Array para tipos, estabilidad
  observable, NaN, strings, aliases, preservacion de length, opcodes,
  deduplicacion de helpers y ejecucion native.
- `test_control_flow_regression.py` recorre un Array; `array_sum.ae` y
  `array_sort.ae` sirven como ejemplos LLVM.
- tests de structs comprueban que Array puede ser campo, parametro/return de
  metodo y valor impreso en frontend.

### Huecos concretos

Prioridad P0/P1:

- get y set native con indice negativo, igual a length, mayor a length y Array
  vacio;
- comprobar que LLVM emite check antes de cargar data/GEP/store;
- comprobar que set fallido no altera header/buffer ni otra memoria;
- overflow de `length * element_size` con helper invocable o allocator
  inyectado, sin OOM real;
- `Array.length` i64 en `INT32_MAX` y `INT32_MAX+1` sin allocation gigante;
- DCE IR y SSA preservando un `ArrayGet` muerto que `may_trap`;
- ArrayNew conservado como allocation observable/OOM.

Prioridad media:

- aliasing Array por parametro y return con mutacion observada, en AST, IR y
  native (hoy solo hay assignment AST y parametro feliz native);
- aliasing a traves de fields cuando esas capas soporten structs/classes;
- copy shallow de `Array<Array<int>>` o elementos reference-type;
- copy + alias de original/copia y sort independiente;
- `for` sobre Array despues de set/sort y con aliases;
- paridad de errores AST/IR/native;
- tests aislados de rewriting Array en algebraic, SCCP, dead phi y trivial phi.

Prioridad baja/futura:

- fallo de header y buffer allocation con allocator controlado;
- Arrays grandes simulados mediante headers sinteticos, sin reservar memoria
  real;
- ownership/lifetime cuando exista una politica de destruccion.

Los tests actuales de bounds Array son solo del runner AST y solo usan
`index == length`; no cubren negativo, mayor, vacio, IR directo ni native.

## 12. Feature Matrix y documentacion

Antes de esta auditoria, `FEATURE_MATRIX.md` tenia inconsistencias claras:

- marcaba `Array.length` LLVM como implementado sin registrar el trunc i64->i32;
- no tenia filas Array para literal, for, get ni set, ocultando la ausencia de
  bounds native;
- llamaba a length "completa con optimizer parcial" pese al narrowing;
- la fila global de tipo Array era demasiado agregada para distinguir sort
  seguro de indexing inseguro.

Esta auditoria corrige solo esas afirmaciones y agrega un enlace al snapshot.
La fila `Array.copy` ya reflejaba correctamente que es frontend-only y las APIs
pendientes ya estaban marcadas como no implementadas.

Otros documentos historicos no se modifican aqui:

- `AETHER_V0_SPEC.md` llama sort Array design-only y tambien conserva estados
  List obsoletos;
- `AETHER_SEQUENCE_SORT_DESIGN.md` mezcla contrato implementado con redaccion
  futura, aunque sus reglas coinciden con el codigo;
- `LLVM_BACKEND.md` si reconoce expresamente que bounds generales de Array no
  estan incluidos;
- `MUTABLE_AGGREGATES.md` expresa correctamente el modelo reference-type, pero
  parte de su estado es prospectivo;
- `guia_de_uso.md` aun llama Array una coleccion futura pese a su frontend
  activo.

## 13. Comparacion de garantias Array vs List

| Garantia | List | Array | Brecha |
| --- | --- | --- | --- |
| bounds get/set AST | `0 <= i < length` | igual | ninguna |
| bounds get/set IR | check y error | check y error | ninguna |
| bounds get/set LLVM | helper antes de data/GEP | sin check | P0 |
| overflow new | checked bytes | `mul i64` sin check | P0 |
| allocation failure | header/buffer checked | header/buffer checked | ninguna para OOM |
| narrowing length | checked i64->i32 | trunc silencioso | P0 |
| aliasing assignment | handle/header compartido | handle/header compartido | ninguna |
| aliasing param/return | implementado y ampliamente probado | implementado, menos probado | cobertura |
| copy | shallow hasta LLVM | shallow solo AST | backend ausente |
| sort | helper comun estable/checked | mismo helper | ninguna |
| panic bounds | AST/IR/native | AST/IR solamente | P0 |
| `may_trap` get | preservado por DCE | removible por DCE | P1 |
| runtime separado | runtime List extraido | mezclado dentro de `list_runtime.py` y printer | P2 |
| ownership final | sin GC/free final | sin GC/free final | deuda comun P4 |
| tests safety | bounds/overflow/OOM/narrowing/native | principalmente caminos felices/AST | brecha alta |

Array no necesita capacity, growth, shrinking ni las mutaciones dinamicas de
List. No contar esas ausencias como defectos evita inflar artificialmente la
brecha; las diferencias de la tabla son garantias aplicables al tipo fijo.

## 14. Roadmap priorizado

### P0 - seguridad y paridad nativa

1. Agregar bounds nativos Array get/set con `0 <= index < length`, antes de
   cargar data/calcular GEP/load/store, y panic controlado.
2. Reemplazar el `mul i64` de `aether_array_new` por checked allocation bytes
   antes de reservar/publicar un Array utilizable.
3. Reemplazar el trunc de `Array.length` por conversion checked a Aether int.
4. Cubrir negativo/igual/mayor/vacio, orden del LLVM, overflow simulado y
   limites i32 sin allocations gigantes.

### P1 - modelo de efectos

5. Clasificar `ArrayGet` como read-only + `may_trap` y preservarlo en DCE IR y
   SSA aunque el resultado muera.
6. Definir metadata comun de result/operands/read/write/may_trap/allocation y
   usarla en DCE, SCCP y rewriters.
7. Agregar tests aislados por pase para New/Get/Set/Length/SequenceSort.

### P2 - consolidacion de runtime

8. Adoptar estrategia B: helpers comunes de secuencia/seguridad, runtime Array
   especifico y runtime List especifico.
9. Extraer `aether_array_new`, layout y wrappers de checks a
   `array_runtime.py`; dejar growth/capacity en `list_runtime.py`.
10. Centralizar allocator, checked arithmetic, panic y sort sin unificar los
    headers.
11. Documentar target ABI, alignment y tamaño de header soportados.

### P3 - API fija no estructural y cobertura

12. Completar `copy` hasta IR/SSA/LLVM respetando shallow elements y storage
    independiente.
13. Diseñar/implementar, en el orden que decida la spec, las APIs ya acordadas
    pero ausentes: `isEmpty`, `contains`, `indexOf`, `swap`, `reverse`.
14. Agregar aliasing por parametro/return, nested shallow copy, sort+copy+alias
    y `for` tras mutaciones.

P3 agrega superficie y por eso queda despues de corregir garantias de las
operaciones existentes. Esta auditoria no implementa ninguna de esas APIs.

### P4 - ownership y lifetime

15. Definir ownership/GC/refcount para headers, buffers y elementos reference.
16. Integrar fields/classes y destruccion sin romper aliasing ni shallow copy.
17. Decidir limpieza de slots/handles y estrategia de liberacion final.

## Conclusion

`Array<T>` tiene una base semantica clara y un layout nativo simple, fijo y
razonable, pero hoy no ofrece las mismas garantias en todos los backends. Su
mejor componente es sort compartido; sus debilidades no son APIs faltantes,
sino seguridad elemental de operaciones ya publicas. Hasta resolver bounds,
overflow de new, narrowing y `may_trap`, el estado tecnico objetivo es
**inconsistente**.
