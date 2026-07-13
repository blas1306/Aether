# Matriz de cobertura del compilador

Ultima revision: 2026-07-11.

Esta matriz es la referencia oficial del estado visible de implementacion del
compilador de Aether. Resume la cobertura por etapa del pipeline actual:
parser, typechecker, interprete AST, IR, SSA, optimizadores IR/SSA y backend
LLVM.

Alcance y criterios:

- `AST Interpreter` es el interprete de la superficie completa del lenguaje.
- `LLVM` es el backend compilado y cubre un subconjunto de la superficie.
- `Optimizer` indica si los optimizadores IR/SSA conocen correctamente la
  representacion de la feature. Si una feature no baja a IR/SSA, se marca como
  no implementada para optimizer.
- `Tests` indica cobertura observable en tests o ejemplos automatizados.
- `Spec` indica documentacion oficial de lenguaje en
  `docs/aether/AETHER_V0_SPEC.md` y documentos de lenguaje relacionados.
- `phi` no es una feature de superficie: aparece como infraestructura interna
  de SSA/LLVM.

Leyenda:

- ✅ implementado/cubierto
- ⚠️ parcial o limitado a un subconjunto
- ❌ no implementado/no cubierto
- ? evidencia insuficiente
- N/A no aplica a esa etapa

Leyenda de `Spec`:

- ✅ documentada
- ⚠️ parcialmente documentada
- ❌ no documentada

## Tipos

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| int | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| double | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| bool/boolean | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| string | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| List | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend fase 4e |
| Array | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ sin bounds/narrowing checked | ✅ | ⚠️ parcialmente documentada | Inconsistente entre AST/IR y LLVM |
| Vector<Row> | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| Vector<Column> | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| Matrix | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| Optional/Nullable (`T?`) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Pendiente IR |
| Class | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| Struct | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| Interface | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| Enum | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |

Notas:

- `string` baja como valor/literal/call/return/phi, pero LLVM no soporta
  operaciones string (`+`, comparaciones, impresion, length, indexing, runtime).
- `List<T>` tiene backend fases 1, 2, 3a, `indexOf` de fase 3b, `clear` de fase 4a, `push`/growth de fase 4b, `pop` de fase 4c, `insert` de fase 4d y `removeAt` de fase 4e para literal con tipo esperado,
  `.length`, `.is_empty`, `for x in xs` / `for T x in xs`, lectura indexada y
  asignacion indexada, `copy()`, `contains()`, `indexOf()`, `reverse()` y
  `clear()`, `push()`, `pop()`, `insert()` y `removeAt()`. No incluye shrinking,
  reserva publica, ownership general ni runtime dinamico completo. El backend
  agrega bounds checks propios para `ListGet`/`ListSet` antes de acceder a
  `data`; las mutaciones de longitud validan sus indices antes de modificar la
  lista.
- `ListNew`, `ListCopy` y el buffer temporal de `List/Array.sort` validan
  multiplicaciones i64 antes de reservar o copiar. `List.length` e `indexOf`
  rechazan resultados fuera de i32; `contains` consume la busqueda i64 sin
  narrowing.
- En el frontend/interprete, los agregados mutables (`List`, `Array`,
  `Vector`, `Matrix`) aliasan por asignacion, parametros y return cuando no hay
  conversion de elementos; `copy()` crea el contenedor independiente explicito.
- `Array<T>` tiene backend para literales con tipo esperado, indexing,
  assignment y length; no tiene API completa de colecciones. LLVM no valida
  bounds de get/set, ArrayNew no comprueba overflow de bytes y `.length` trunca
  i64 a i32 sin check. El detalle y roadmap estan en
  [`ARRAY_SUBSYSTEM_AUDIT.md`](ARRAY_SUBSYSTEM_AUDIT.md).

## Expresiones

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unary `-` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ⚠️ parcialmente documentada | Parcial backend |
| `!` factorial postfix | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ no documentada | Frontend solamente |
| `+` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| `-` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| `*` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ⚠️ parcialmente documentada | Parcial backend |
| `/` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| `%` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ documentada | Pendiente LLVM |
| `==` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| `!=` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| `<` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| `<=` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| `>` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| `>=` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| `&&` | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ no documentada | Pendiente IR |
| <code>&#124;&#124;</code> | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ no documentada | Pendiente IR |
| ternario | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |

Notas:

- `!` esta implementado como operador postfix de factorial. No se encontro
  negacion booleana prefija `!expr` en el parser.
- `&&` y `||` tienen short-circuit en el interprete AST, pero no bajan a IR.
- `%` baja como `rem`; los optimizadores IR/SSA conocen `mod`/`rem`. LLVM solo
  tiene `srem` para enteros en el backend actual.
- `==`/`!=` estan muy cubiertos en frontend; IR/SSA cubren escalares
  seleccionados y string, pero LLVM no soporta comparaciones string.
- `*` esta parcialmente documentado porque la spec aun conserva restricciones
  de matrix/vector `*` que no describen todo el backend actual.

## Control de flujo

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| if | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| while | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| for | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| break | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| continue | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |
| return | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Completa |

Notas:

- `for` baja a CFG explicito con bloques de condicion, cuerpo, incremento y
  salida. El backend cubre rangos `int` y colecciones indexables ya soportadas
  por IR/LLVM: arrays, vectores y listas fase 1.
- `break` y `continue` no agregan sintaxis ni opcodes especiales: se materializan
  como saltos IR/SSA a los destinos activos del loop.
- Auditoria tecnica relacionada:
  [CONTROL_FLOW_AUDIT.md](CONTROL_FLOW_AUDIT.md).

## Funciones

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llamadas | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| parametros | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| recursion | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ parcialmente documentada | Pendiente tests |

Notas:

- Recursion: el frontend y el interprete AST tienen tests. Por inspeccion
  ejecutable local, una funcion recursiva simple baja a IR, ejecuta en el IR
  interpreter, construye SSA, pasa por el optimizer SSA y emite una llamada
  LLVM recursiva. Falta un test dedicado de backend.
- Los optimizadores conservan llamadas de forma conservadora; no hacen analisis
  interprocedural.

## Colecciones

### List

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| List literal `{...}` con tipo esperado | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Parcial backend fase 1 |
| List.length / length | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ may-trap | ✅ checked i64→i32 | ✅ | ✅ documentada | `.length` segura; builtin global aun no baja a IR |
| List.is_empty / is_empty | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Parcial backend fase 1 |
| for sobre List | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Parcial backend fase 1 |
| List index read (`xs[i]`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ may-trap | ✅ bounds + panic | ✅ | ✅ documentada | Seguro: `0 <= i < length` en AST/IR/native |
| List index assignment (`xs[i] = value`) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ side-effect | ✅ bounds + panic | ✅ | ✅ documentada | Seguro: check antes del store |
| List.copy | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ checked bytes/OOM | ✅ | ✅ documentada | Orden seguro antes de allocation/memcpy |
| List.contains | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ búsqueda i64 | ✅ | ✅ documentada | No depende del narrowing de indexOf |
| List.indexOf | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ may-trap | ✅ checked i64→i32 | ✅ | ✅ documentada | `-1` ausente; panic si índice > INT32_MAX |
| List.push | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Implementado fase 4b con growth interno |
| List.pop | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Implementado fase 4c |
| List.insert | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Implementado fase 4d |
| List.removeAt / remove_at | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Implementado fase 4e sin shrinking |
| List.clear | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Implementado fase 4a |
| List.reverse | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ documentada | Implementado fase 3a |
| List.sort | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ checked temp/offsets | ✅ | ✅ documentada | `IRSequenceSort` estable compartido, sin wraparound |

### Array

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Array literal `{...}` con tipo esperado | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ allocation conservadora | ⚠️ OOM checked, bytes sin overflow check | ✅ | ✅ documentada | Funcional con riesgo de allocation |
| Array.length / length | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ lectura eliminable | ⚠️ trunc i64→i32 sin check | ✅ caminos normales | ⚠️ parcialmente documentada | Narrowing nativo inseguro |
| for sobre Array | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ hereda ArrayGet | ⚠️ loop acotado, get sin check propio | ⚠️ | ⚠️ parcialmente documentada | Funcional, safety parcial |
| Array index read (`a[i]`) | ✅ | ✅ | ✅ bounds | ✅ bounds en interpreter | ✅ | ❌ DCE elimina get may-trap | ❌ sin bounds ni panic | ⚠️ AST/validos native | ⚠️ parcialmente documentada | Inseguro en LLVM |
| Array index assignment (`a[i] = value`) | ✅ | ✅ | ✅ bounds | ✅ bounds en interpreter | ✅ | ✅ side-effect | ❌ sin bounds; store directo | ⚠️ AST/validos native | ⚠️ parcialmente documentada | Inseguro en LLVM |
| Array.isEmpty | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.copy | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ⚠️ parcialmente documentada | Frontend solamente |
| Array.contains | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.indexOf | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.swap | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.reverse | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.sort | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ checked temp/offsets | ✅ | ✅ documentada | Mismo helper estable y seguro que List.sort |

La semantica unica implementada de `List.sort` y `Array.sort` esta en
[`AETHER_SEQUENCE_SORT_DESIGN.md`](../aether/AETHER_SEQUENCE_SORT_DESIGN.md).
Ambos contenedores comparten IR, politica de comparacion y helpers LLVM; solo
difieren al extraer el puntero de datos y la longitud de sus cabeceras.

El crecimiento y las mutaciones de longitud de `List<T>` tienen su
contrato de implementacion en
[`AETHER_LIST_GROWTH_DESIGN.md`](../aether/AETHER_LIST_GROWTH_DESIGN.md). Las
filas `insert` y `removeAt` permanecen sin backend. `clear` y `pop` conservan
capacidad y buffer; `push` implementa reserve/growth interno y preserva header.

## Algebra lineal

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Vector literal | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| Matrix literal | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| vector index | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| matrix index | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| vector assignment | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ parcialmente documentada | Completa con optimizer parcial |
| matrix assignment | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ parcialmente documentada | Completa con optimizer parcial |
| vector add | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| vector sub | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| vector scale | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| matrix add | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| matrix sub | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| matrix scale | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| dot product | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| outer product | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ parcialmente documentada | Completa con optimizer parcial |
| matrix multiplication | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ parcialmente documentada | Completa con optimizer parcial |
| matrix-column multiplication | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| row-matrix multiplication | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| transpose builtin | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Pendiente IR |

Notas:

- Los optimizadores IR/SSA preservan operaciones de algebra lineal y reescriben
  usos cuando corresponde, pero no aplican optimizaciones algebraicas
  especificas para agregados.
- La spec documenta `Math.LinearAlgebra.matmul(...)`; la documentacion de
  operadores `*` para todos los casos de algebra lineal esta desalineada con el
  backend actual y por eso algunas filas quedan parcialmente documentadas.

## Backend LLVM e infraestructura interna

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| build | N/A | N/A | N/A | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ no documentada | Completa |
| run | N/A | N/A | N/A | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ no documentada | Completa |
| emit-llvm | N/A | N/A | N/A | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ no documentada | Completa |
| phi | N/A | N/A | N/A | N/A | ✅ | ✅ | ✅ | ✅ | ❌ no documentada | Infraestructura backend |
| call | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ documentada | Completa con optimizer parcial |
| casts | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ documentada | Parcial backend |
| string globals | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ parcialmente documentada | Parcial optimizer |

Notas:

- `phi` esta implementado y probado en SSA/LLVM. No corresponde a parser,
  typechecker ni interprete AST porque no es sintaxis Aether.
- `casts` estan documentados como `int`, `float`, `double`, `complex`,
  `string`, `boolean`, pero IR/LLVM solo soportan de forma efectiva casts
  numericos seleccionados, especialmente `int <-> double`.
- `string globals` cubre literales string como valores LLVM `ptr`; no implica
  runtime string completo.

## Prioridades recomendadas

1. Bajar `&&` y `||` a IR/SSA/LLVM preservando short-circuit.
2. Completar `%` en LLVM para `double` o limitar explicitamente el subconjunto
   compilable.
3. Completar strings en backend: concatenacion, comparaciones, impresion,
   length/indexing y runtime/ownership.
4. Completar `List<T>` con las mutaciones de longitud restantes, crecimiento,
   `realloc` y ownership; `clear` y `sort` ya estan implementados.
5. Agregar `NullableType`/`null` al IR, SSA, optimizadores y LLVM, incluyendo
   comparaciones con `null`.
6. Migrar structs, classes, interfaces y enums al backend o definir
   explicitamente que son solo del interprete AST.
7. Alinear la spec con el estado real de operadores de algebra lineal,
   especialmente `*`, outer product y matrix multiplication.
8. Bajar `transpose`/`conjtranspose` y demas builtins de algebra lineal que hoy
   dependen del interprete AST.
9. Agregar tests dedicados de recursividad en IR/SSA/LLVM.
10. Completar o descartar formalmente APIs faltantes de colecciones:
    `Array.isEmpty`, `Array.contains`, `Array.swap` y `Array.reverse`;
    `Array.sort` ya esta implementado.

## Revisar manualmente

- Ninguna fila queda en `?` tras esta revision.
- Mantener esta matriz sincronizada con cambios en `docs/aether/` y con las
  pruebas de backend; varias filas son parciales por disonancia entre spec,
  frontend y subconjunto LLVM.
