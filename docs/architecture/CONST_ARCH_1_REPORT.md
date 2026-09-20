# CONST-ARCH-1 — design report

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-20.

Documento normativo: [CONST_ARCH_1.md](CONST_ARCH_1.md).

Sólo se agregaron documentos. No se modificó lexer, parser, AST, HIR, MIR, SSA,
backend, runtime, tests ni la superficie source admitida.

## Resultado

Se aprobó `const` como propiedad del binding para locals y parámetros:

```aether
const int n = computeN();
void inspect(const ref Node node) { ... }
```

Un local const se inicializa obligatoriamente en su declaración y luego no
puede reemplazarse. El initializer puede ser runtime, tener efectos y lanzar;
no se introduce constant evaluation, `constexpr`, storage estático ni folding
obligatorio.

Const no forma `Const<T>`. El valor conserva exactamente el mismo `TypeId`,
layout, ABI, InstanceId, mangling, calling convention y capacidades que T. En
parámetros es sólo una restricción verificada dentro del body; el caller y el
tipo `Function` no cambian.

## Mutación shallow y referencias

La protección cubre el root y fields inline de aggregates por valor. Así,
`p.x = 3` se rechaza para un `const Point p`. Termina al cruzar una frontera de
indirection o handle writable: una mutación admitida a través de `ref mut`, un
class handle, List u otra collection/view conserva sus reglas ordinarias.

`const ref T` y `const ref mut T` son válidos. En ambos casos se prohíbe rebind
del descriptor. El primero sigue siendo shared/read y el segundo conserva write
capability al pointee; const nunca degrada `ref mut T` a `ref T`. Por ello los
diagnósticos distinguen “binding is const” de “pointee is not writable”.

Una List const puede hacer push/reserve o escribir elementos si la API y los
borrows ordinarios lo permiten, pero no puede reemplazarse con otra List. Los
Stores internos del descriptor sólo son válidos como parte de un protocolo
tipado verificado; no abren una excepción general para asignar al root.

## Ownership y cleanup

Un owner const puede moverse, consumirse, retornarse by ownership o transferirse
a un aggregate. Move termina el lifetime del valor completo en lugar de
reemplazarlo, por lo que usa la transición ordinaria `Owned -> Moved`. Todo uso
posterior falla por use-after-move y const continúa prohibiendo reinicializar o
reasignar el binding. No se inserta Clone, Alias o ARC.

Un Move parcial desde un field inline sigue rechazado porque dejaría vivo el
aggregate const con storage parcial; mover el root completo sí es legal. Esta
frontera conserva la distinción normativa entre Write/redefinition y Move
terminal.

El Drop automático normal o excepcional se ejecuta sólo si el valor continúa
Owned. Un initializer que lanza antes de publicar el binding no genera Drop; un
path que ya transfirió el owner tampoco. Unwind, drop flags y joins MaybeMoved
siguen las reglas ordinarias y garantizan exactamente una terminación por path.

## IR y verificabilidad

AST, HIR y signatures conservarán `BindingMutability::{Mutable, Const}` como
metadata de declaración, nunca en `AstType` o `TypeData`. HIR centralizará la
clasificación Read/Borrow/Write/Move/CleanupDrop, rechazará Write o borrow
mutable del storage inline y admitirá Move del root completo.

MIR mantendrá la marca en locals/parámetros y verificará inicialización única,
ausencia de Store/reinicialización/borrow mutable, Move terminal único, rechazo
de Move parcial, use-after-move, protocolos handle y cleanup sólo del owner que
permanece Owned. SSA conservará una tabla mínima de bindings source incluso tras
promoción para repetir esas pruebas y soportar corruption tests. La marca sólo
puede borrarse después de SSA verificada; LLVM no deducirá readonly/noalias/
invariant del simple hecho de que el binding sea const.

## Scope y diagnósticos

CONST-V1 incluye locals y parámetros, también genéricos y combinaciones con
`ref`/`ref mut`. Fields, globals/statics, pattern/catch/iteration bindings,
captures y temporales compiler-owned quedan fuera. El parser debe emitir un
diagnóstico específico para contextos reservados.

Los mensajes cubren initializer ausente, reassignment, escritura inline,
mutable borrow, Move parcial y uso fuera de V1. Un uso posterior a Move conserva
el diagnóstico ordinario de moved value; una reasignación posterior sigue
diciendo que el binding es const. Los errores de capability del pointee
permanecen separados de los del binding.

## Primer vertical recomendado

**CONST-V1 — immutable local and parameter bindings** debe recorrer todo el
pipeline de una vez. La qualification combina runtime initializers, Copy y
owners, struct fields, references, class/List handles, generics, parámetros,
defaults, Move/return/consume de roots completos, use-after-move, rechazo de
reinicialización y Move parcial, cleanup normal/excepcional condicionado al
estado Owned, O0/O2, corrupción HIR/MIR/SSA y equivalencia de TypeId/layout/ABI/
mangling frente a bindings mutables.

La implementación debe permanecer fail-closed hasta que ownership, unwind,
backend y verificadores estén completos. No debe incluir fields/globals,
inicialización tardía, deep const, compile-time evaluation, readonly placement
ni overloads basados en const.

## Validación del milestone

- Se crearon únicamente el documento normativo y este reporte.
- Se preservaron los cambios preexistentes del working tree.
- Quedaron cerrados sintaxis, semántica del binding, inicialización runtime,
  ownership/Move, mutación shallow, referencias, collections, parámetros,
  generics, representación IR, diagnósticos, ABI/layout y el primer vertical.
- No queda una decisión abierta dentro del alcance V1.
- No se declara implementada ninguna conducta source nueva.
