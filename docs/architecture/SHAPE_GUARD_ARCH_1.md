# SHAPE-GUARD-ARCH-1 — guard dinámico general de shape

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este milestone es exclusivamente documental. No modifica el lenguaje, el
compilador, el runtime, `linearAlgebra` ni los tests. Define el prerequisito
general identificado por:

- [LINEAR-ALGEBRA-SOLVE-ARCH-1](LINEAR_ALGEBRA_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-SOLVE-ARCH-1-REPORT](LINEAR_ALGEBRA_SOLVE_ARCH_1_REPORT.md).

También preserva los contratos existentes de traps, HIR/MIR/SSA y shapes de
Matrix/Vector, en particular
[DYNAMIC-SHAPES-AND-SLICES-ARCH-1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md),
[MATRIX-ADD-V1](MATRIX_ADD_V1_REPORT.md),
[SLICE-ASSIGNMENT-V1](SLICE_ASSIGNMENT_V1_REPORT.md) y el modelo de error de
[ERROR-MODEL-ARCH-1](ERROR_MODEL_ARCH_1.md).

## 1. Decisión resumida

La superficie V1 es una primitiva global intrínseca, disponible en cualquier
source y package ordinario:

```aether
shapeGuard(condition);
```

Es una forma statement-only, con exactamente un argumento `bool` y sin
argumentos de tipo, resultado, mensaje ni trap seleccionable. Si la evaluación
del argumento termina en `true`, la ejecución continúa. Si termina en `false`,
la primitiva produce exactamente el `TrapKind::ShapeMismatch` estructurado ya
existente.

La condición es una expresión booleana ordinaria. La primitiva no conoce
containers, ejes ni extents y no infiere relaciones:

```aether
shapeGuard(rows(A) == columns(A));
shapeGuard(dimension(v) == rows(A));
shapeGuard(columns(B) == rows(A));
```

Estas tres expresiones no tienen tratamiento especial. Son comparaciones
`bool` construidas explícitamente por la library.

## 2. Auditoría y elección de superficie

### 2.1 Convenciones actuales

El lenguaje ya reserva primitivas globales para operaciones fundamentales que
deben estar disponibles uniformemente, entre ellas `rows`, `columns`,
`dimension`, `vectorFilled` y `matrixFilled`. Los nombres compuestos de esta
familia source usan camelCase. Además, los effect statements ya distinguen
operaciones intrínsecas de una call declarada ordinaria.

Por eso se fija el spelling exacto `shapeGuard`, sin import ni calificación.
Es un símbolo reservado: una declaración local o de package no lo reemplaza ni
cambia su semántica. No es un valor de función y `pkg.shapeGuard(...)` no
designa esta primitiva.

### 2.2 Alternativas descartadas

| alternativa | decisión | razón |
|---|---|---|
| primitiva global `shapeGuard(bool);` | elegida | disponibilidad uniforme y lowering estructurado desde el frontend |
| función ordinaria en core/std | rechazada | una call opaca no conserva por sí sola el contrato ni el fail edge; además introduce resolución/import/versionado innecesarios |
| `assert(condition)` general | rechazada | mezcla invariant failure, debugging, mensajes y políticas de release que no pertenecen a shape |
| `guard(condition, TrapKind)` | rechazada | expone una taxonomía interna y equivale a custom/user-selectable traps |
| contracts/preconditions declarativos | diferida | requerirían propagación interprocedural, reglas de call-site y diagnóstico estático que V1 no necesita |
| intrinsic de `solve`, Matrix o Vector | prohibida | la capacidad debe ser general y no privilegiar una library o familia de containers |

La operación es estrecha en la clase de fallo, pero general en quién puede
usarla y qué relación runtime puede expresar. No se diseña un sistema general
de contratos.

## 3. Tipado y admisión source

La gramática reutiliza el statement de call terminado en `;`; no se agrega una
keyword. El chequeo semántico reconoce sólo:

```text
shapeGuard(<exactamente un bool>);
```

Reglas cerradas:

- el argumento debe tener exactamente tipo `bool`;
- no hay truthiness, conversión numérica ni coerción nullable;
- no se aceptan argumentos de tipo;
- no hay overloads, variantes calificadas ni forma método;
- no puede usarse como initializer, argumento, return ni valor de función;
- aridad, type arguments o tipo incorrectos producen un diagnóstico estático
  normal de aridad/tipo en el span de la invocación o del operando;
- una condición constante `false` es código válido que trapea; no se convierte
  en un diagnóstico de shape.

V1 no promete que el frontend entienda que `rows(A) == columns(A)` describe
una matriz square, ni que emita `E0345` aunque los extents sean conocidos. La
primitiva sólo exige un `bool`.

## 4. Semántica dinámica exacta

Para una ejecución de `shapeGuard(e);`:

1. se evalúa `e` exactamente una vez según las reglas ordinarias del lenguaje;
2. si esa evaluación completa con `true`, se toma el edge de continuación;
3. si completa con `false`, se toma el edge de fallo y termina mediante
   `ShapeMismatch`;
4. no existe un tercer resultado, payload o mensaje dinámico.

El guard mismo no asigna memoria, no lee ni inspecciona containers, no muta
estado, no crea owners y no deja préstamos vivos. Los efectos y traps propios
de `e` siguen siendo los de `e`. En particular, si evaluar `e` divide por cero,
indexa fuera de rango, asigna o llama una función con efectos, esa conducta
ocurre antes de que el guard pueda decidir. Ninguno de esos traps se captura o
se convierte en `ShapeMismatch`.

`false` produce exactamente el mismo `TrapKind::ShapeMismatch` que las
operaciones matemáticas y de assignment actuales. Es abortivo, no es una
Exception, no hace unwind, no entra en `catch` y no ejecuta cleanup de trap. No
se crea `LibraryShapeMismatch`, un código específico de package ni un nuevo
símbolo de runtime.

La afirmación “`true` no tiene efectos” significa que, después de evaluar la
condición, la operación guard no agrega allocation, mutation, retain/release,
borrow o call. No afirma que una condición escrita con efectos sea pura.

## 5. Evaluación, préstamos y ordering

Los statements de un bloque se ejecutan en orden source. Un guard no puede ser
adelantado sobre expresiones previas ni retrasado sobre expresiones posteriores.
El lowering debe completar la evaluación de la condición —incluidos sus
suboperandos de izquierda a derecha, calls y finales de préstamos temporales—
antes de ramificar. La continuación domina todo statement posterior.

Por tanto una library puede escribir:

```aether
shapeGuard(rows(A) == columns(A));
shapeGuard(dimension(b) == rows(A));
Vector<float64,Column> workspace = vectorFilled<float64,Column>(rows(A), 0.0);
```

y obtener que ambos guards completan antes de la allocation. La misma regla
permite ubicarlos antes de indexing, division, mutation o calls costosas. El
compilador no inserta speculative execution de operaciones posteriores ni
mueve automáticamente el guard buscando una posición “mejor”.

El fail-before-effects prometido llega sólo hasta donde lo escribió la library:
los efectos anteriores y los necesarios para calcular la condición ya
ocurrieron. Entre guards consecutivos, el primero que evalúa a `false` gana.

## 6. HIR

HIR incorpora un statement explícito, no una `Call`:

```text
HirStmtKind::ShapeGuard {
    condition: HirExpr,          // TypeId::BOOL
    trap: HirTrapKind::ShapeMismatch,
}
// HirStmt.span conserva la ubicación source completa.
```

`HirTrapKind` es vocabulario cerrado del frontend; no es un tipo source. En V1
la única combinación admitida por esta operación es `ShapeMismatch`.

El verificador HIR recalcula y exige:

- statement proveniente del símbolo intrínseco global exacto;
- un único operando de tipo canónico `bool`;
- resultado no utilizable y ausencia de type arguments;
- trap exactamente `ShapeMismatch`;
- span source válido;
- ownership y préstamos de la condición balanceados por las reglas HIR
  ordinarias, sin obligación residual atribuible al guard.

Una mutación que cambie tipo, trap, categoría statement, cantidad de operandos
o contrato se rechaza antes de MIR. No se rebaja a una declaración llamada
`shapeGuard`.

El `MathStep::ShapeGuard` existente dentro de recipes cerradas de algebra
elementwise/product no se vuelve programable ni se reutiliza como sustituto de
este statement. Ambos comparten la clase de trap, pero el nuevo nodo admite un
`bool` arbitrario y control flow de una función ordinaria.

## 7. MIR

MIR evalúa `condition` una vez hasta un `Operand` booleano y termina el bloque
actual con control flow explícito:

```text
Terminator::ShapeGuard {
    condition: Operand,          // bool
    success: BlockId,
    failure: BlockId,
    trap: TrapKind::ShapeMismatch,
    span: Span,
}

failure:
    Terminator::Trap(TrapKind::ShapeMismatch)
```

Los statements posteriores se bajan exclusivamente en `success`. `failure` es
un bloque abortivo sin instrucciones, unwind edge ni sucesor. Mantener el tag
del terminator, el edge y el bloque Trap hace visible la intención y permite
validarla; una pareja genérica `Branch`/`Trap` no basta para reconstruir que el
source autorizó emitir `ShapeMismatch`.

El verificador MIR exige operand type `bool`, destinos distintos y válidos,
trap idéntico en terminator y bloque de fallo, bloque de fallo vacío y abortivo,
span conservado y ninguna unwind/exception edge. También exige que la
continuación sea el único edge hacia las operaciones source posteriores y que
los protocolos ordinarios de borrow/ownership estén cerrados antes del
terminator. Cualquier corrupción falla cerrada.

## 8. SSA

La construcción SSA preserva la misma operación como terminator:

```text
SsaTerminator::ShapeGuard {
    condition: SsaOperand,       // bool
    success: BlockId,
    failure: BlockId,
    trap: TrapKind::ShapeMismatch,
    span: Span,
}
```

El bloque `failure` termina en `SsaTerminator::Trap(ShapeMismatch)` y el bloque
`success` domina toda instrucción posterior. No se representa como call, como
comparación de descriptors ni como metadata informativa.

El verifier SSA comprueba independientemente tipo, definición y dominance del
operando; identidad del trap en ambos sitios; targets, predecessors y
terminación exactos; ausencia de unwind; span; y ausencia de instrucciones o
phis ejecutables en el fail block. No confía en que MIR ya lo haya validado.
Una corrupción a otro `TrapKind`, a un entero, a edges invertidos/aliased o a
un fail block continuante se rechaza.

## 9. Backend y relación exacta con `ShapeMismatch`

El backend sólo recibe SSA verificado. Emite una rama condicional al bloque de
continuación o a la misma ruta `trap_shape_mismatch` que ya materializa
`SsaTerminator::Trap(TrapKind::ShapeMismatch)` mediante `llvm.trap` y
`unreachable`.

No hay helper `aether_shape_guard`, ABI nueva, allocation, string, formatting,
excepción o dispatch según package. Si la implementación comparte físicamente
la etiqueta final entre varios guards, eso no fusiona su evaluación ni altera
sus spans en IR/dumps.

## 10. Optimización

`ShapeGuard` es control flow potencialmente abortivo y no es una operación
pura eliminable por defecto. Son transformaciones permitidas:

- condición probada constante `true` y libre de efectos/traps: reemplazar el
  guard por su edge `success`;
- condición probada constante `false` y libre de efectos/traps previos:
  reemplazarlo por un trap directo `ShapeMismatch`;
- constant propagation o CSE de la expresión booleana sólo con las reglas
  ordinarias de aliasing, calls, traps y memoria;
- compartir el bloque final de `ShapeMismatch` sin compartir ni reordenar las
  condiciones.

No está permitido eliminar la evaluación de una condición con efectos, evaluar
la condición dos veces, hoist/sink a través de efectos observables, ejecutar el
success speculativamente, convertir otro trap ni usar conocimiento
interprocedural de shapes no demostrado. V1 no requiere análisis
interprocedural ni que compiler-next agregue un optimizer general. Las pruebas
de folding se vuelven obligatorias sólo cuando una capa optimizadora declare
implementar esas transformaciones; O0 conserva la forma explícita.

## 11. Generalidad, packages y abuso

Cualquier package puede emitir deliberadamente `ShapeMismatch` mediante
`shapeGuard(false);`. Esto es parte del contrato elegido. No entrega raw
access, memoria uninitialized, selección de un trap arbitrario ni capacidad de
recuperación privilegiada; sólo permite terminar de forma segura con una clase
de fallo que el lenguaje ya expone por comportamiento.

La disponibilidad no depende de ser OAL, `linearAlgebra`, std, aplicación raíz
o dependencia. Un cuerpo de library se chequea y serializa con el mismo nodo
HIR, y una compilación consumer preserva el mismo MIR/SSA/trap. No se consulta
el nombre del package.

La auditoría actual confirma que `ShapeMismatch` no pertenece a solve:

- productos algebraicos y operaciones elementwise lo usan para extents
  runtime incompatibles;
- `Matrix.add` lo usa antes de allocation, relocation o escritura;
- slice assignment lo usa para length/rows/columns incompatibles antes de los
  stores;
- el backend ya posee una ruta estructurada común para ese `TrapKind`.

El guard extiende la expresabilidad de source ordinario; no reemplaza los
checks especializados ni hace programable el recipe IR de esos kernels.

## 12. Diagnósticos y compatibilidad

Un operando no booleano, aridad distinta, type arguments o uso en posición de
valor producen un diagnóstico frontend normal. El código exacto podrá
asignarse en el vertical de implementación junto con las pruebas de estabilidad;
esta arquitectura no reutiliza engañosamente `E0345`, reservado para mismatches
de shape conocidos por operaciones que sí analizan shapes.

Agregar `shapeGuard` reserva un nuevo nombre global. Éste es el único impacto
source deliberado. No cambia el significado de `if`, `throw`, `assert` (que no
se introduce), Matrix/Vector, exceptions o traps existentes.

## 13. Calificación del futuro vertical

La implementación deberá cubrir como mínimo:

- `shapeGuard(true)` continúa y `shapeGuard(false)` termina por
  `ShapeMismatch`;
- operando no bool, aridad, type arguments, uso como valor, calificación y
  shadowing se rechazan conforme a la superficie cerrada;
- una condición con contador/call se evalúa exactamente una vez;
- orden observable frente a efectos antes, dentro y después del guard;
- guard escrito antes de allocation, indexing, division y call costosa, con
  instrumentación que demuestre que lo posterior no ocurrió al fallar;
- un trap producido al evaluar la condición conserva su clase y no se convierte;
- finalización de préstamos temporales y ausencia de borrow residual en el edge
  `success`;
- condiciones arbitrarias sobre `rows`, `columns` y `dimension`, incluidos
  extents cero, sin introspección automática;
- definición en un package ordinario e invocación desde un consumer separado;
- mismo resultado y ordering en O0 y O2;
- dumps HIR/MIR/SSA con operación, bool, span, edges y trap explícitos;
- corrupciones HIR/MIR/SSA de operand type, trap, targets, fail block, span y
  unwind rechazadas independientemente;
- constante true/false cuando el optimizer correspondiente exista;
- búsqueda estructural que descarte paths por nombre de `linearAlgebra`, OAL,
  `solve`, Matrix o Vector;
- suite existente de operaciones matemáticas, Matrix.add y slice assignment
  verde, demostrando reutilización del mismo backend/trap.

## 14. Orden del futuro vertical de implementación

1. Reservar y diagnosticar `shapeGuard` en la superficie global statement-only.
2. Agregar `HirStmtKind::ShapeGuard` y su verificación/corrupciones.
3. Agregar el terminator MIR, lowering con dos edges y verifier fail-closed.
4. Preservar el terminator en SSA y agregar verificación independiente.
5. Bajar SSA verificado a la ruta `ShapeMismatch` existente, sin ABI nueva.
6. Agregar tests source, package consumer, ordering, borrow y traps en O0/O2.
7. Agregar folding sólo si existe una capa apropiada y sus pruebas de efectos;
   no bloquear V1 por esa optimización opcional.
8. Ejecutar la suite completa y publicar un reporte de implementación separado.
9. Recién después desbloquear el vertical de implementación de solve.

## 15. Fuera de scope

No forman parte de SHAPE-GUARD-ARCH-1:

- implementar el guard o `solve`;
- contracts/preconditions declarativos;
- dependent/refinement types o inferencia estática de shapes;
- mensajes, payloads o user-defined/custom traps;
- exceptions, catch o unwind para `ShapeMismatch`;
- una primitiva general `assert` o selección source de `TrapKind`;
- inspección automática de containers;
- compiler magic de Matrix, Vector, `linearAlgebra` o solve;
- movimiento automático de guards o análisis interprocedural de shapes.

No quedan decisiones arquitectónicas abiertas dentro de este alcance.
