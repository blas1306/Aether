# DEFAULT-PARAMETERS-ARCH-1 — reporte de diseño

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-20.

Documento normativo:
[DEFAULT_PARAMETERS_ARCH_1](DEFAULT_PARAMETERS_ARCH_1.md).

## Resultado

Se diseñaron parámetros trailing con default para `compiler-next` sin cambiar
código, tests, runtime ni superficie admitida. La forma fuente es
`T name = expression`; después del primer default todos los parámetros deben
tenerlo. Para `n` parámetros y un primer default en el índice `d`, la aridad
directa permitida es `d..n`. No existen holes, named arguments ni omisión
intermedia.

El initializer pertenece a `ParameterSignature` y a la API semántica de la
declaración. No pertenece a `TypeData::Function`, `FunctionRef`,
`IndirectCall`, mangling, vtables ni prototype LLVM. Una función con firma
física `(double, double) -> double` conserva exactamente ese tipo y ABI aunque
el segundo parámetro tenga default.

## Evaluación y HIR

Los argumentos explícitos se evalúan primero y luego los defaults omitidos,
siempre de izquierda a derecha y exactamente una vez. Cada omisión vuelve a
ejecutar el initializer; no hay evaluación al declarar ni memoization.

El scope es el de la declaración. Se permiten símbolos visibles, generic
parameters y parámetros anteriores, de modo que
`clamp(x, lo = 0.0, hi = lo + 1.0)` es legal. Self-reference y referencias a
parámetros posteriores son errores. Ownership y borrows siguen siendo
ordinarios: un default no obtiene una copia implícita de un owner anterior.

HIR materializa la aridad completa mediante bindings sintéticos call-scoped.
Cada binding conserva provenance `Explicit` o `Defaulted`, y un default que usa
un parámetro anterior lee el binding ya evaluado. HIR → MIR baja esos bindings
como inicializaciones, temporales, borrows, drops y una call normal. MIR, SSA y
backend nunca reciben una operación default ni una call abreviada.

Este modelo cierra conjuntamente:

- orden observable y evaluación única;
- referencias entre defaults sucesivos;
- temporales owning y moves;
- implicit shared argument borrows con el índice físico existente;
- cleanup de sólo los bindings inicializados cuando un default posterior
  lanza;
- ausencia total de cambios de ABI.

## Generics e imports

La inferencia generic se completa usando únicamente type arguments explícitos,
argumentos escritos y fuentes que el lenguaje ya admita. Los defaults no
inventan type arguments. Tras resolver la instancia concreta, el frontend
sustituye tipos, valida constraints y tipa/materializa los defaults omitidos.
La declaración también se valida paramétricamente para no esconder un default
inválido hasta una call eventual.

Una call imported usa la misma `FunctionSignature` e idéntica expansión que una
local. Para artefactos compilados, la interfaz semántica futura deberá exportar
el template ligado, sus dependencias y fingerprint; un prototype binario solo
no alcanza para ejecutar código en el caller. Los nombres quedan ligados en el
scope del proveedor y no se vuelven a resolver bajo imports del consumidor.

## Function values y OOP

Tomar una función como valor conserva sólo la firma completa. Por ello
`Function<(double, double), double> g = f` es válido, pero `g(1.0)` no: toda
indirect call exige aridad exacta y no porta metadata de defaults. No se generan
thunks, wrappers ni conversiones por aridad.

La arquitectura también cierra métodos. El caller materializa argumentos antes
de cualquier direct/virtual/interface dispatch; receiver y slot mantienen la
firma completa. Los defaults usados son los de la declaración seleccionada por
el tipo estático. Un override puede tener metadata distinta para calls resueltas
directamente a él sin alterar compatibilidad del slot.

El primer vertical se limita a funciones libres. Métodos, initializers e
interface requirements deben fallar explícitamente como no soportados hasta el
vertical OOP correspondiente; no requieren rediseñar evaluación, HIR o ABI.

## Diagnostics y primer vertical

Se reserva `E0360..E0367` para required-after-default, mismatch del initializer,
muy pocos/demasiados argumentos, referencia propia/posterior, default que no
puede tiparse, indirect call abreviada y contexto todavía no soportado. El
documento fija mensajes, spans y notas, además de cómo combinar contexto de
declaración y call en instancias generic.

`DEFAULT-PARAMETERS-V1` debe cubrir parser/AST, metadata de firma, trailing
rule, binding/tiping, aridad directa, generics, normalización HIR, lowering con
cleanup y borrow, imports del programa conjunto, diagnostics, dumps y pruebas
O0/O2. La matriz obliga a probar side effects, orden, throws, owners, defaults
encadenados, function values y que el LLVM prototype sea idéntico con y sin
initializer.

## Validación de este milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se implementó parser, AST, HIR, MIR, SSA, backend, runtime ni tests.
- Se preservaron los cambios preexistentes del worktree fuera de estos docs.
- La decisión reutiliza `FunctionSignature`, `CallSiteId`, la adaptación de
  borrow call-scoped, monomorfización, cleanup/unwind y calls de aridad completa
  existentes como fronteras de implementación.
- No quedan decisiones abiertas que bloqueen el primer vertical. Persistencia
  cross-package exacta, habilitación OOP, defaults nativos y named arguments son
  milestones posteriores con límites explícitos.
