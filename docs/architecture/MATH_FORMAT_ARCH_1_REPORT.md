# MATH-FORMAT-ARCH-1 — architecture milestone report

Estado: **COMPLETADO COMO ARQUITECTURA; SIN IMPLEMENTACIÓN**, 2026-09-28.

Documento normativo:
[MATH_FORMAT_ARCH_1.md](MATH_FORMAT_ARCH_1.md).

## Resultado

Se cerró una extensión composicional del perfil FORMAT para los owners
`Vector<T,Row>`, `Vector<T,Column>` y `Matrix<T>` cuando el element type concreto
ya es interpolable y está admitido por la familia matemática. No se agregan
reflection, formatter protocol, dispatch runtime, API de conversión especial ni
casos en `println`, LU o `linearAlgebra`.

FORMAT de T permanece como única autoridad de cada elemento. Math formatting
sólo aporta delimiters, traversal y metadata para valores vacíos. El milestone
no modifica código, runtime, tests ni contratos de admisión.

## Sintaxis cerrada

| Valor | Forma normativa |
|---|---|
| Row no vacío | `[a, b, c]` |
| Column no vacío | `[a; b; c]` |
| Row vacío | `Row[]` |
| Column vacío | `Column[]` |
| Matrix con ambos ejes positivos | `[a, b; c, d]` |
| Matrix 0×0 | `Matrix(0,0)[]` |
| Matrix 0×n | `Matrix(0,n)[]` |
| Matrix m×0 | `Matrix(m,0)[]` |

Los singletons Row/Column producen ambos `[a]`; no existe un separator donde
mostrar orientación y FORMAT no pretende codificar el TypeId completo. En
cambio, vacíos llevan un tag compacto porque ningún elemento permite recuperar
orientación o shape.

La Matrix ordinaria tiene brackets exteriores únicos, `, ` entre columnas y
`; ` entre filas. No hay alineación, brackets por fila, trailing separators ni
layout adaptativo. La notación empty siempre conserva ambos extents y usa
decimal canónico de `usize`.

## Element type y round-trip

Integer, float, bool y char reutilizan exactamente FORMAT-V1. Esto conserva
shortest-round-trip float, `-0`, `NaN`, `Inf` y `-Inf`; no aparece precisión o
scientific policy matemática. No se materializa un owner string por elemento.

`char` está admitido como elemento y por ello se formatea sin quotes ni escapes.
Un char delimitador puede ser visualmente ambiguo y un newline puede producir
salida físicamente multilínea. Es una consecuencia deliberada de composición
exacta. `string` es interpolable pero continúa rechazado actualmente como
elemento Vector/Matrix; este milestone no ensancha esa admisión.

V1 no promete parsear la salida de vuelta. `Row[]`, `Column[]` y
`Matrix(m,n)[]` son presentación humana determinista, no nueva sintaxis source
ni serialización.

## Owners, views y traversal

V1 soportará sólo owners. `VectorView`, `VectorViewMut`, `MatrixView` y
`MatrixViewMut` conservan E0340 y no se materializan. Admitirlas queda como una
extensión posterior porque requiere cerrar provenance, keepalive y strides para
las dos pasadas, aunque su texto futuro pueda ser idéntico.

Vector recorre `i = 1..dimension`; Matrix recorre `i = 1..rows`, luego
`j = 1..columns`. Los extents son lógicos. El address físico Matrix usa el
stride verificado del descriptor actual, pero nunca se recorren capacity o
padding. No se crea transpose, slice, Vector por fila, segunda Matrix ni tabla
por elemento.

El costo es O(n) para Vector y O(m·n) para Matrix, con una pasada count y una
write. El único storage proporcional al resultado es el backing final string;
se permiten sólo buffers escalares acotados ya propios de FORMAT-V1.

## Ownership e integración con FORMAT-BORROW

MATH-FORMAT decide interpolabilidad y bytes; FORMAT-BORROW decide acceso. Al
estar ambos implementados, owner, `factor.L`, `ref Matrix<T>` y
`ref mut Matrix<T>` se observan mediante shared borrow sin Move, Clone, Alias,
copy, retain ni partial move. El borrow cubre count/write y termina antes de que
`Interpolation` publique el string.

Este milestone no redefine ownership ni habilita por sí solo el dogfood LU. La
implementación de FORMAT-BORROW es un gate explícito para demostrar que un
factor non-Copy sigue válido después del formatting.

## Representación por fases

HIR agregará una `MathematicalAggregateFormat` dentro del hole ordinario, con
kind owner, aggregate/element TypeIds, conversión FORMAT de T, traversal lógico
y política empty. No enumera elementos ni guarda extents duplicados.

MIR y SSA conservarán descriptor borrowed, zero-shape branch, loops lógicos,
separators y fases count/write. Sus verificadores reconstruirán kind, element
formatter, extents, layout/stride, checked size, publicación única y región de
borrow. El backend emitirá loops directos y reutilizará primitives FORMAT-V1;
no habrá call opaca con `Any`, TypeId, witness o callback.

Overflow/OOM, evaluación izquierda→derecha, cleanup y no publicación parcial
son exactamente los de FORMAT-V1. No existe excepción matemática nueva.

## Diagnostics

E0340 se mantiene para:

- Matrix/Vector cuyo T concreto no pertenezca al perfil FORMAT;
- `Matrix<T>`/`Vector<T,O>` dentro de un generic sin prueba estática de
  interpolabilidad (no existe todavía constraint pública `Format`);
- las cuatro views fuera de V1.

El mensaje nombra el agregado relevante y, cuando corresponda, el element type
que causa el rechazo. Una formación inválida del tipo matemático falla antes
con su diagnóstico ordinario. Borrow conflicts, uso tras move y E0293 fuera de
FORMAT no cambian.

## Qualification futura

El vertical deberá probar bytes exactos para Row/Column 0/1/n; Matrix 0×0,
0×n, m×0, 1×1, 1×n, m×1, rectangular y square; todos los scalar elements
admitidos; char adversarial; interpolation anidada/repetida; padding no leído;
overflow/OOM; E0340; views rechazadas; dumps/corruptions HIR-MIR-SSA;
reachability y equivalencia O0/O2.

Cuando FORMAT-BORROW esté calificado, el dogfood obligatorio será:

```aether
var factor = linearAlgebra.lu(A);
println("L = ${factor.L}");
println("U = ${factor.U}");
solve(factor, b);
det(factor);
```

Los overloads vigentes sobre `ref LU<T>` hacen legales ambos usos sobre el mismo
owner. La condición es probar Matrix interpolation, ausencia de
Move/Clone/partial move y que `factor` sigue válido para los dos calls.

## Orden de implementación acordado

1. consulta recursiva y estática de interpolabilidad;
2. conversión/verifier HIR para owners;
3. delimiters, empties y checked count;
4. traversal y count/write MIR sin owners intermedios;
5. loops, layout y regiones verificables en SSA;
6. codegen directo usando primitives FORMAT-V1;
7. integración con FORMAT-BORROW;
8. qualification negativa, estructural, O0/O2 y dogfood LU;
9. views sólo mediante milestone aditivo posterior.

No se modificó código en este milestone.
