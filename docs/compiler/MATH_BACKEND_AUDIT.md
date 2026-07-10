# Math Backend Audit

## Alcance

Auditoria de mantenimiento sobre las instrucciones matematicas de vector y
matriz en IR, SSA y el printer LLVM:

- `IRVectorAdd`, `IRVectorSub`, `IRVectorScale`, `IRVectorDot`.
- `IRMatrixAdd`, `IRMatrixSub`, `IRMatrixScale`, `IRMatrixMatMul`.
- `IRMatrixVectorMul`, `IRVectorMatrixMul`, `IROuterProduct`.
- Instrucciones SSA equivalentes.
- `src/aether/backend/llvm/printer.py`.

Este documento nacio como auditoria. La fase 1 de refactorizacion interna del
backend LLVM ya fue aplicada sin cambios de comportamiento.

## Estado de Refactorizacion

- Fase 1 completada: helpers privados del printer LLVM para creacion de
  agregados, labels/checks de loops, recorrido elemento a elemento, recorrido
  doble de matrices, load/store de elementos y seleccion de `add/sub/mul`
  contra `fadd/fsub/fmul`.
- Sin features nuevas, sin instrucciones nuevas y sin cambios intencionales en
  el LLVM generado.

## Resumen Ejecutivo

El backend matematico ya tiene algunos buenos puntos de reutilizacion:

- El interprete IR comparte add/sub de vectores y matrices mediante helpers
  binarios.
- El printer LLVM comparte la emision lineal de add/sub/scale con helpers para
  agregados contiguos.
- Las instrucciones IR y SSA mantienen nombres, campos y contratos faciles de
  comparar.

La deuda principal no esta en una operacion aislada, sino en que cada nueva
instruccion matematica debe agregarse manualmente en muchos sitios:

- Modelo IR y modelo SSA.
- Exports de paquetes.
- Printer textual IR y SSA.
- Verifier IR y SSA.
- Builder SSA y renaming.
- Optimizadores que preguntan por pureza, resultado u operandos.
- LLVM dispatch, validacion, allocation, loops y shape checks.

Eso hace que el costo marginal de agregar una operacion sea alto y que sea
facil olvidar un sitio. Las mejores oportunidades de abstraccion estan en
helpers pequenos de metadata y de loops, no en reemplazar todo el modelo de
instrucciones por una jerarquia generica.

## IR

### Modelo

`src/aether/ir/model.py:97` a `src/aether/ir/model.py:200` define una
dataclass por operacion. La forma es clara, pero hay grupos repetidos:

- Binarias elemento a elemento:
  - vector: `result`, `left`, `right`, `length`, `orientation`.
  - matriz: `result`, `left`, `right`, `rows`, `cols`.
- Escalares sobre agregados:
  - vector: `result`, `vector`, `scalar`, `length`, `orientation`.
  - matriz: `result`, `matrix`, `scalar`, `rows`, `cols`.
- Productos:
  - `IRVectorDot`, `IROuterProduct`, `IRMatrixMatMul`,
    `IRMatrixVectorMul`, `IRVectorMatrixMul`.

Esta duplicacion es en buena parte aceptable: las dataclasses explicitas hacen
que pattern matching, type checking y printers sean legibles. La abstraccion
mas util aqui no seria una clase base compleja, sino metadata auxiliar externa:

- `math_instruction_result(instruction)`.
- `math_instruction_operands(instruction)`.
- `math_instruction_shape(instruction)`.
- `math_instruction_kind(instruction)` para distinguir `elementwise_binary`,
  `scale`, `dot`, `outer`, `matmul`, `matvec`, `vecmat`.

Eso permitiria compartir logica en optimizadores sin esconder la semantica de
cada instruccion.

### Lowering

`src/aether/ir/lowering.py:820` a `src/aether/ir/lowering.py:1098` contiene
la seleccion de operaciones agregadas.

Duplicacion observada:

- Vector add/sub y matrix add/sub repiten el mismo flujo:
  - verificar tipos de agregados.
  - verificar elemento compatible.
  - buscar longitud/dimensiones.
  - verificar igualdad de shape.
  - crear temporal.
  - registrar shape.
  - emitir instruccion.
- `Vector<Row> * Vector<Column>`, `Vector<Column> * Vector<Row>`,
  `Matrix * Matrix`, `Matrix * Vector<Column>` y `Vector<Row> * Matrix`
  repiten el patron de:
  - filtrar orientacion/tipos.
  - buscar shape.
  - validar compatibilidad.
  - calcular tipo de resultado.
  - crear temporal y registrar shape.
  - emitir instruccion.
- `IRVectorScale` e `IRMatrixScale` comparten casi toda la estructura salvo el
  origen del shape y el constructor final.

Oportunidad de mantenimiento:

- Extraer helpers de shape:
  - `_known_vector_length(value, context, message, expression)`.
  - `_known_matrix_dimensions(value, context, message, expression)`.
  - `_record_result_shape(result, shape, context)`.
- Extraer una pequena tabla de multiplicacion agregada que describa:
  - tipos/orientaciones aceptadas.
  - shape resultante.
  - constructor IR.
  - shape registry destino.

No conviene abstraer prematuramente todos los mensajes de error: esos mensajes
son especificos y ayudan al usuario.

### Interpreter

`src/aether/ir/interpreter.py:185` a `src/aether/ir/interpreter.py:227`
despacha cada instruccion de forma explicita. Los helpers actuales son buenos:

- `_execute_vector_binary` cubre `IRVectorAdd` y `IRVectorSub`
  (`src/aether/ir/interpreter.py:314`).
- `_execute_matrix_binary` cubre `IRMatrixAdd` y `IRMatrixSub`
  (`src/aether/ir/interpreter.py:381`).
- `_execute_vector_scale` y `_execute_matrix_scale` son equivalentes salvo
  shape y nombre de campo (`src/aether/ir/interpreter.py:331` y
  `src/aether/ir/interpreter.py:399`).

Duplicacion y oportunidades:

- `_execute_vector_dot`, `_execute_matrix_matmul`,
  `_execute_matrix_vector_mul` y `_execute_vector_matrix_mul` repiten un
  kernel de acumulacion `sum(lhs * rhs)` con inicializacion `0`/`0.0`
  (`src/aether/ir/interpreter.py:347`, `src/aether/ir/interpreter.py:416`,
  `src/aether/ir/interpreter.py:441`, `src/aether/ir/interpreter.py:465`).
- `IROuterProduct` comparte la parte de producto elemento a elemento, pero no
  la reduccion (`src/aether/ir/interpreter.py:363`).
- Hay varios checks de "ambos son list" y "longitud/dimensiones coinciden" que
  podrian pasar por helpers pequenos.

Una abstraccion razonable seria:

- `_zero_for_result(type_)`.
- `_checked_list(value, operation_name)`.
- `_execute_dot_kernel(left, right, result_type)`.
- `_execute_linear_product(rows, cols, inner, lhs_at, rhs_at, result_type)`.

Eso permitiria implementar `dot`, `matmul`, `matrix_vector` y
`vector_matrix` con el mismo acumulador sin perder claridad.

### Verifier IR

`src/aether/ir/verifier.py:375` a `src/aether/ir/verifier.py:417` tiene
dispatch manual para cada instruccion. La verificacion especifica esta en
`src/aether/ir/verifier.py:585` a `src/aether/ir/verifier.py:869`.

Puntos ya compartidos:

- `_verify_vector_binary` cubre add/sub.
- `_verify_matrix_binary` cubre add/sub.

Duplicacion restante:

- `IRVectorScale` y `IRMatrixScale` tienen la misma estructura: definido,
  result type, aggregate operand type, shape positivo, result type igual al
  agregado, scalar type igual al elemento.
- `IRVectorDot`, `IROuterProduct`, `IRMatrixMatMul`,
  `IRMatrixVectorMul` e `IRVectorMatrixMul` repiten:
  - definir operandos.
  - verificar tipos aggregate.
  - verificar orientacion cuando aplica.
  - verificar dimensiones positivas.
  - calcular `_numeric_binary_result_type`.
  - comparar elemento o resultado.
- La misma logica existe casi linea por linea en el verifier SSA.

Oportunidad:

- Crear helpers de verificacion matematica puros que no dependan de IR vs SSA,
  por ejemplo:
  - `_require_vector_type(value, operation)`.
  - `_require_matrix_type(value, operation)`.
  - `_require_orientation(vector_type, expected, operation)`.
  - `_require_positive_shape(operation, rows=None, cols=None, inner=None)`.
  - `_require_numeric_result_element(left_element, right_element, result)`.

El unico detalle a adaptar entre IR y SSA es como se valida "definido":
despues de eso, la verificacion de tipos es identica.

## SSA

### Modelo SSA

`src/aether/ssa/model.py:85` a `src/aether/ssa/model.py:188` replica la
familia IR con `SSAValue` en lugar de `IRValue`.

Esto es duplicacion deliberada y razonable mientras IR y SSA sean capas
distintas. La oportunidad no esta tanto en mezclar modelos, sino en evitar que
cada consumidor vuelva a codificar la misma tabla de instrucciones
matematicas.

### Builder y Renaming

`src/aether/ssa/builder.py:549` a `src/aether/ssa/builder.py:620` convierte
IR matematico a SSA. `src/aether/ssa/renaming.py:282` a
`src/aether/ssa/renaming.py:364` hace una conversion muy parecida.

Duplicacion observada:

- Cada rama define un resultado, resuelve operandos y construye la instruccion
  SSA equivalente.
- `builder.py` usa `state.value_map`; `renaming.py` usa el estado interno y
  ademas llama `_bind_value`.
- La tabla IR->SSA esta duplicada en ambos archivos.

Oportunidad:

- Crear un helper local de conversion basado en descriptors:
  - clase IR.
  - clase SSA.
  - campos operandos a resolver.
  - campos metadata a copiar.
- Mantener el paso "define/bind result" separado, porque difiere entre builder
  y renaming.

Ejemplo conceptual:

```text
IRVectorAdd -> SSAVectorAdd
operands: left, right
metadata: length, orientation
```

Esto reduciria el riesgo de que una nueva operacion se agregue al builder pero
no al renaming, o viceversa.

### Printer SSA

`src/aether/ssa/printer.py:109` a `src/aether/ssa/printer.py:177` es casi
identico a `src/aether/ir/printer.py:113` a `src/aether/ir/printer.py:181`,
cambiando clases `IR*` por `SSA*`.

Oportunidad:

- Compartir formateadores por "shape de instruccion":
  - vector binary.
  - vector scale.
  - vector dot.
  - outer product.
  - matrix binary.
  - matrix scale.
  - matrix/matrix, matrix/vector, vector/matrix.
- Mantener printers separados si se prefiere, pero usar helpers con argumentos
  `typed_value`, `value` y nombres de campos.

Esto es deuda liviana: no afecta semantica, pero aumenta churn al agregar
instrucciones.

### Optimizers SSA

Patrones repetidos aparecen en:

- `src/aether/ssa/optimizer/algebraic_simplification.py:294` a
  `src/aether/ssa/optimizer/algebraic_simplification.py:391`.
- `src/aether/ssa/optimizer/trivial_phi.py:260` a
  `src/aether/ssa/optimizer/trivial_phi.py:433`.
- `src/aether/ssa/optimizer/dead_phi.py:152` a
  `src/aether/ssa/optimizer/dead_phi.py:179`.
- `src/aether/ssa/optimizer/sccp.py:420` a
  `src/aether/ssa/optimizer/sccp.py:430`.

La repeticion central es "cuales son los operandos de esta instruccion" y
"como reconstruyo la instruccion con operandos reescritos".

Oportunidad:

- Un helper `ssa_instruction_operands(instruction)` compartido.
- Un helper `ssa_rewrite_instruction_operands(instruction, rewrite_value)`.
- Una tupla comun `SSA_PURE_VALUE_INSTRUCTIONS`.

Esto tambien aplica a IR:

- `src/aether/ir/optimizer/dead_code.py:51` a
  `src/aether/ir/optimizer/dead_code.py:75`.
- `src/aether/ir/optimizer/dead_code.py:192` a
  `src/aether/ir/optimizer/dead_code.py:223`.

## LLVM Printer

### Dispatch y Resultado

`src/aether/backend/llvm/printer.py:183` a
`src/aether/backend/llvm/printer.py:204` despacha cada operacion matematica.
`src/aether/backend/llvm/printer.py:240` a
`src/aether/backend/llvm/printer.py:266` repite la lista para detectar
instrucciones con resultado.

Oportunidad:

- Un registro privado de handlers:

```text
SSAVectorAdd -> _print_vector_add
SSAVectorSub -> _print_vector_sub
...
```

- Un set comun de instrucciones con resultado, o mejor un helper compartido
  desde SSA si se decide centralizar metadata.

Esto evitaria listas largas que deben actualizarse en paralelo.

### Helpers Contiguos Existentes

El printer LLVM ya tiene buenos helpers:

- `_print_contiguous_new` para array/vector/matrix literals
  (`src/aether/backend/llvm/printer.py:1222`).
- `_print_contiguous_binary` para vector/matrix add/sub
  (`src/aether/backend/llvm/printer.py:1250`).
- `_print_contiguous_scale` para vector/matrix scale
  (`src/aether/backend/llvm/printer.py:1302`).
- `_array_data_pointer`, `_array_element_pointer` y
  `_matrix_element_pointer` para acceso a almacenamiento contiguo
  (`src/aether/backend/llvm/printer.py:1487` a
  `src/aether/backend/llvm/printer.py:1535`).

Estos helpers ya reducen bastante la duplicacion de operaciones
elementwise. Conviene preservarlos.

### Loops de Productos

La mayor oportunidad esta en los productos:

- `_print_vector_dot` emite un loop con indice, acumulador y dos loads
  (`src/aether/backend/llvm/printer.py:531` a
  `src/aether/backend/llvm/printer.py:612`).
- `_print_outer_product` emite loops anidados, loads, coerciones, producto y
  store (`src/aether/backend/llvm/printer.py:628` a
  `src/aether/backend/llvm/printer.py:746`).
- `_print_matrix_vector_mul` y `_print_vector_matrix_mul` son casi imagenes
  espejo: ambos allocan resultado, extraen data pointers, hacen loop externo,
  loop interno, acumulador, coerciones, producto, suma y store final
  (`src/aether/backend/llvm/printer.py:924` a
  `src/aether/backend/llvm/printer.py:1202`).
- `_print_matrix_matmul` hace el mismo producto acumulado, pero lo desenrolla
  en Python con `for row/col/inner` y genera LLVM lineal
  (`src/aether/backend/llvm/printer.py:835` a
  `src/aether/backend/llvm/printer.py:908`).

Problemas de mantenimiento:

- Hay dos estrategias de codegen para productos: loops LLVM runtime para
  dot/matvec/vecmat/outer y unroll estatico para matmul.
- El patron de acumulador `zero`, `mul`, `add`, `coerce`, `store` esta
  repetido en varias funciones.
- Los nombres de labels y temporales son manuales en cada funcion.
- `matrix_vector` y `vector_matrix` duplican casi todo con indices invertidos.

Oportunidades de abstraccion:

- Helper para crear un "loop simple" LLVM:
  - indice alloca.
  - label loop/body/exit.
  - condicion `icmp slt`.
  - incremento.
- Helper para "loop doble":
  - indice externo.
  - indice interno.
  - reset de indice interno.
  - labels consistentes.
- Helper para "reduction product":
  - inicializar acumulador.
  - cargar operandos.
  - coerce a tipo resultado.
  - multiplicar.
  - sumar a acumulador.
- Helper para cargar data pointers de varios agregados:
  - `left_data`, `right_data`, `result_data`.
- Un descriptor de producto lineal:
  - longitud de salida.
  - longitud de reduccion.
  - formula de indice A.
  - formula de indice B.
  - formula de indice resultado.
  - orientacion/nombre para labels.

Con ese descriptor, `matrix_vector` y `vector_matrix` podrian ser el mismo
generador con formulas distintas. `matrix_matmul` tambien podria usarlo si se
elige emitir loops LLVM en lugar de unroll.

### Validaciones LLVM

Las validaciones LLVM repiten checks de tipo numerico y orientacion:

- `_validate_vector_dot` (`src/aether/backend/llvm/printer.py:614`).
- `_validate_outer_product` (`src/aether/backend/llvm/printer.py:748`).
- `_validate_matrix_matmul` (`src/aether/backend/llvm/printer.py:910`).
- `_validate_matrix_vector_mul` (`src/aether/backend/llvm/printer.py:1055`).
- `_validate_vector_matrix_mul` (`src/aether/backend/llvm/printer.py:1204`).

Oportunidad:

- `_require_numeric_element(type_, operation, role)`.
- `_require_vector_orientation(value, orientation, operation, role)`.
- `_require_matrix_value(value, operation, role)`.
- `_require_positive_dims(operation, *dims)`.

Esto mantendria mensajes especificos y bajaria el ruido.

## Problemas de Mantenimiento

### 1. Tabla de instrucciones matematica dispersa

La misma familia de instrucciones aparece manualmente en muchos archivos:

- dispatch de interprete.
- verifier IR.
- model/export IR.
- printer IR.
- builder SSA.
- renaming SSA.
- model/export SSA.
- printer SSA.
- verifier SSA.
- optimizers IR/SSA.
- printer LLVM.

Riesgo: agregar una nueva operacion o cambiar un campo exige recordar todos
los sitios. Este es el riesgo de mantenimiento mas alto.

### 2. Verificacion IR y SSA duplicada

Los verifiers IR y SSA repiten casi la misma logica de tipos para vector/matrix
ops. La diferencia principal es el tracking de definido. Extraer helpers
type-only reduciria divergencias.

### 3. Reescritura de operandos duplicada

Optimizadores y renaming vuelven a construir instrucciones con operandos
reescritos una por una. Esto escala mal con cada nueva instruccion.

### 4. Loops LLVM hechos a mano

Los loops LLVM de productos tienen mucha superficie manual:

- labels.
- allocas de indices.
- loads/stores de indices.
- offsets row-major.
- coerciones.
- acumuladores.

Este tipo de codigo es propenso a errores pequenos de indice, especialmente
en operaciones espejo como `Matrix * Vector` y `Vector * Matrix`.

### 5. Estrategia inconsistente en `matrix_matmul`

`matrix_matmul` genera codigo desenrollado segun dimensiones conocidas,
mientras otros productos generan loops LLVM. El unroll puede ser aceptable para
ejemplos pequenos, pero puede inflar el LLVM para matrices grandes y deja dos
formas de mantener el mismo concepto de producto acumulado.

## Oportunidades Recomendadas

### Alta prioridad

1. Crear metadata compartida de instrucciones matematicas.

   Debe responder al menos:

   - resultado.
   - operandos.
   - si es pura.
   - shape/logical kind.
   - constructor equivalente IR->SSA cuando aplique.

2. Compartir helpers de verificacion type-only entre IR y SSA.

   Mantener wrappers IR/SSA para `_require_defined`, pero centralizar las
   reglas de vector/matrix.

3. Extraer helpers de loops LLVM para productos acumulados.

   Empezar por `matrix_vector` y `vector_matrix`, porque son los mas
   parecidos y por eso tienen mejor relacion beneficio/riesgo.

### Prioridad media

4. Unificar reescritura de operandos en SSA optimizers.

   Un helper de reconstruccion reducira bastante codigo en
   `trivial_phi`, `algebraic_simplification`, `dead_phi`, `dead_code` y
   `sccp`.

5. Reducir duplicacion en printers textuales IR/SSA.

   Esto baja churn, aunque no es una fuente fuerte de bugs.

6. Considerar loops LLVM para `matrix_matmul`.

   Si se mantiene el unroll por ahora, documentar que es una decision
   intencional para dimensiones estaticas pequenas.

### Baja prioridad

7. Unificar modelos IR/SSA con clases base.

   No parece urgente. Las dataclasses explicitas son legibles y sirven como
   contrato. Una abstraccion demasiado agresiva podria empeorar el codigo.

## Que No Abstraeria Todavia

- No reemplazaria todas las instrucciones matematicas por una unica
  `AggregateOp`.
- No esconderia orientaciones de vector detras de strings genericos sin tests
  muy claros.
- No fusionaria IR y SSA en el modelo de datos.
- No generalizaria todos los mensajes de error; varios mensajes actuales son
  valiosos por ser especificos.

## Checklist de Regresion Para Futuras Refactors

Antes de cambiar estas abstracciones, conviene cubrir:

- `Vector<Row> + Vector<Row>`, `Vector<Column> + Vector<Column>`.
- `Vector<Row> - Vector<Row>`, `Vector<Column> - Vector<Column>`.
- `scalar * vector`, `vector * scalar`.
- `Vector<Row> * Vector<Column>` como dot.
- `Vector<Column> * Vector<Row>` como outer product.
- `Matrix + Matrix`, `Matrix - Matrix`, `scalar * Matrix`, `Matrix * scalar`.
- `Matrix * Matrix`.
- `Matrix * Vector<Column>`.
- `Vector<Row> * Matrix`.
- Casos invalidos de orientacion.
- Casos invalidos de dimensiones.
- Promocion `int` a `double` en productos LLVM.
- Paridad entre IR interpreter y LLVM para ejemplos pequenos.

## Conclusión

La implementacion actual es entendible y ya comparte parte del trabajo en las
operaciones elementwise. La deuda mas importante es la dispersion: cada
operacion matematica existe como una lista de casos sincronizados a mano en
muchos componentes.

La ruta de menor riesgo es introducir metadata y helpers pequenos alrededor de
las instrucciones existentes. Primero conviene atacar operandos/resultados,
verificacion type-only y loops LLVM de productos. Eso reduce el costo de
mantenimiento sin perder la claridad de tener instrucciones IR/SSA explicitas.
