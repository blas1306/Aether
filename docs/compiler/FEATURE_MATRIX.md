# Matriz de cobertura del compilador

Ultima revision: 2026-07-10.

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
| List | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| Array | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ parcialmente documentada | Parcial backend |
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
- `List<T>` existe como tipo fuente y como tipo IR/SSA nominal, pero no tiene
  lowering real de literales/metodos/operaciones de lista.
- `Array<T>` tiene backend para literales con tipo esperado, indexing,
  assignment y length; no tiene API completa de colecciones.

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
  por IR/LLVM, como arrays y vectores.
- `break` y `continue` no agregan sintaxis ni opcodes especiales: se materializan
  como saltos IR/SSA a los destinos activos del loop.

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
| List.length / length | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.isEmpty / is_empty | ⚠️ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.copy | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.contains | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.indexOf | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| List.push | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.pop | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.insert | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.removeAt / remove_at | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.clear | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.reverse | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |
| List.sort | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ documentada | Frontend solamente |

### Array

| Feature | Parser | Typechecker | AST Interpreter | IR | SSA | Optimizer | LLVM | Tests | Spec | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Array.length / length | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ⚠️ parcialmente documentada | Completa con optimizer parcial |
| Array.isEmpty | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.copy | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ⚠️ parcialmente documentada | Frontend solamente |
| Array.contains | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.indexOf | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.swap | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.reverse | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |
| Array.sort | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ no documentada | No implementado |

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
4. Bajar `List<T>` real al backend: literales, propiedades, metodos mutantes y
   no mutantes.
5. Agregar `NullableType`/`null` al IR, SSA, optimizadores y LLVM, incluyendo
   comparaciones con `null`.
6. Implementar `for`, `break` y `continue` en IR/SSA/LLVM.
7. Migrar structs, classes, interfaces y enums al backend o definir
   explicitamente que son solo del interprete AST.
8. Alinear la spec con el estado real de operadores de algebra lineal,
   especialmente `*`, outer product y matrix multiplication.
9. Bajar `transpose`/`conjtranspose` y demas builtins de algebra lineal que hoy
   dependen del interprete AST.
10. Agregar tests dedicados de recursividad en IR/SSA/LLVM.
11. Completar o descartar formalmente APIs faltantes de colecciones:
    `indexOf`, `Array.isEmpty`, `Array.contains`, `Array.swap`,
    `Array.reverse` y `Array.sort`.

## Revisar manualmente

- Ninguna fila queda en `?` tras esta revision.
- Mantener esta matriz sincronizada con cambios en `docs/aether/` y con las
  pruebas de backend; varias filas son parciales por disonancia entre spec,
  frontend y subconjunto LLVM.
