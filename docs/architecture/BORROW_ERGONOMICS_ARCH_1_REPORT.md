# BORROW-ERGONOMICS-1 — design report

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-15.

Documento normativo:
[BORROW_ERGONOMICS_ARCH_1.md](BORROW_ERGONOMICS_ARCH_1.md).

Sólo se agregaron documentos. No se modificó parser, resolver, HIR, MIR, SSA,
backend, runtime, Core, STD, tests ni la superficie soportada.

## Resultado

Se aprobó una adaptación única para posiciones de argumento. Si la firma
concreta espera `ref T` shared y el argumento produce exactamente el mismo
`TypeId` T, el compiler puede insertar un Borrow shared limitado a esa call:

```aether
string path = "input.txt";

std.File.readText(path);
std.File.readText("input.txt");
std.Text.contains(text, "Aether");
```

`f(value)` queda semánticamente alineado con `f(&value)`. No es una conversión
`T -> ref T`, no crea Alias/Move/Clone/ARC y no introduce auto-deref. `ref mut`
requiere siempre `&mut place` explícito.

## Lvalues y rvalues

Un lvalue presta su Place existente, preserva provenance y bloquea Move,
replacement, Drop o invalidación estructural incompatible desde su evaluación
hasta que termina la call. El borrow shared no es exclusivo: mantiene la
política actual de aliases y no autoriza `noalias`.

Un rvalue se evalúa una vez y se transfiere a un root oculto address-taken. El
compiler lo presta durante la call y lo destruye después, sin duplicar su
obligación owning. Un literal string inmortal puede usar storage estático o una
materialización eliminable, con cero heap y cero ARC físico, pero el Borrow
sigue visible en IR.

Los argumentos se evalúan de izquierda a derecha. Un borrow anterior permanece
activo mientras se evalúan argumentos posteriores y durante la invocación.
Varios temporales se limpian en orden inverso.

## Unwind y traps

En una call `may_unwind`, el caller conserva ownership de los temporales
prestados. El exceptional edge termina los borrows, destruye cada temporary
inicializado y propaga el mismo `ExceptionEvent` hacia catch/finally/unwind. Un
initializer que lanza antes de publicar su temporary no genera Drop.

Los traps continúan siendo abortivos y sin cleanup garantizado. El milestone no
los convierte en exceptions ni agrega rollback.

## Resolución e inferencia

La adaptación se intenta después de resolver el callable, sustituir generics y
obtener el parámetro concreto. La prioridad futura por argumento es:

1. match exacto sin ajuste;
2. match exacto mediante implicit shared borrow;
3. conversión ordinaria existente.

La comparación entre candidatos es por dominancia componente a componente; un
empate o candidatos incomparables producen ambigüedad, nunca selección por
orden de declaración. Por ello `f(T)` vence a `f(ref T)` para `f(value)`.

El compiler actual conserva nombres únicos y familias cerradas; no se implementa
un sistema general de overloads. Cada familia selecciona primero su firma
canónica y aplica después la misma adaptación.

Generics tampoco usan el borrow como inferencia: `ref U` contra un argumento U
owning no determina U. Una aplicación explícita, o U inferido por otro
parámetro, sí puede recibir el ajuste después de la sustitución. No se confunden
`U` y `ref U`, y la adaptación no cambia InstanceId, mangling ni constraints.

## IR y verificación

HIR representa `CallScopedSharedBorrow` con `CallSiteId`, argument index, tipos
exactos y source Place o Temporary. MIR materializa roots ocultos, Borrow,
call/invoke, `EndBorrow` y cleanup normal/excepcional. SSA conserva la misma
región y rechaza cualquier phi, Store, Return o uso que haga escapar el
reference.

Cada verificador reconstruye por separado tipo, provenance, dominancia, orden,
scope, ausencia de invalidación y Drop único. LLVM sólo traduce SSA verificada
al pointer ABI existente; puede eliminar storage con prueba, pero no puede
inventar ARC, `noalias` ni lifetime extension.

## Diagnósticos y costos

Los errores distinguirán tipo diferente, `ref mut`, source no addressable ni
materializable, escape, ambigüedad e invalidación por otro argumento. Un caso
legal no se describirá como conversión implícita de `string` a `ref string`.

Los costos quedan cerrados:

- lvalue: cero allocation/copy owning/Alias/ARC;
- literal string inmortal: cero heap/ARC físico;
- temporary owning: sólo construcción y Drop ya propios de T;
- adaptación: cero retain/release, Clone o owner adicional;
- unwind: cleanup exacto del temporary, sin excepción sustituta.

No se promete heap materialization; stack/static/elisión dependen de storage y
pruebas del backend.

## Primer vertical recomendado

**BORROW-ERGONOMICS-V1 — exact shared call borrows** debe cubrir direct calls,
`std.File` y `std.Text`, lvalues/literals/temporales, un T Copy, `&` explícito,
múltiples argumentos, generics ya determinados, invalidaciones, success/unwind/
finally y traps. Debe agregar dumps y corrupciones HIR/MIR/SSA, instrumentación
de lifecycle y ejecución O0/O2.

La implementación debe reemplazar la ergonomía string-specific que hoy obtiene
operands borrowed mediante `string_borrow_operand` por una adaptación común que
mantenga `ref T` explícito en todos los IR. No debe agregar overloads generales,
auto-deref, `ref mut` automático ni borrows fuera de calls.

## Alcance conservado

Siguen fuera assignments/returns/fields/captures de references, stored borrows,
escaping lifetimes, conversión seguida de borrow, Alias/Clone/ARC implícito,
method receiver sugar, closures, smart pointers y typing dinámico. Toda la
feature continúa fail-closed hasta que el vertical nativo complete frontend,
MIR, SSA, LLVM, unwind, diagnósticos y qualification.

## Validación del milestone

- Se crearon únicamente este reporte y el documento normativo.
- Se preservaron los cambios preexistentes del working tree.
- La decisión cierra regla exacta, lvalues, rvalues/literals, lifetime,
  ownership/provenance, unwind/traps, resolución, generics, IR, diagnósticos,
  costos y primer vertical.
- No se declara implementada ninguna conducta source nueva.
