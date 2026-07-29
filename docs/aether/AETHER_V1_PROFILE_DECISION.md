# Decisión cerrada del perfil Aether 1.0

> Clasificación: **Audit / historical**. Registra la decisión de profile 22 del
> 18 de julio; no es la referencia vigente después de Phase 5.4/profile 23.

Fecha: **2026-07-18**. Esta decisión interpreta “Aether 1.0” como un perfil
estable único y verificable, no como la unión de todo lo que alguna capa puede
reconocer.

> Seguimiento de cierre: R1 quedó cerrado el **2026-07-18** con la publicación
> de la spec normativa limitada a las 75 filas `SUPPORTED`. R2/B13 quedó
> cerrado el mismo día con un catálogo de 78 ejemplos native, 23 experimentales
> AST-only y cero rotos. El siguiente bloqueador es R3: normalización pública de
> diagnostics de verification/ICE.

## Decisión normativa

El perfil estable de Aether 1.0 es el subconjunto aceptado por **native
capability profile 22** en **Linux x86_64 con clang**, refinado por las filas
`SUPPORTED` de `AETHER_V1_PROFILE_AUDIT.md`.

Native es el backend oficial. El intérprete AST es una referencia semántica,
backend del REPL y herramienta diferencial; sus capacidades adicionales son
experimentales y no amplían Aether 1.0. El IR interpreter es infraestructura
interna. Ningún frontend o backend puede hacer fallback silencioso a AST.

## Entra en Aether 1.0

La lista exacta es:

- declaraciones locales tipadas, `const` tipado, asignación simple y `+=`;
- bloques, scopes sin shadowing, `if`/`else if`/`else`, `while`, `break`,
  `continue`, retorno temprano;
- `for` sobre expresiones directas `Range<int>` inclusivas y `for-in` sobre
  Array/List/Vector soportados;
- funciones tipadas normales, funciones abreviadas con retorno explícito o
  inferido, llamadas adelantadas, recursión y `int main()`/main sintético;
- imports completos/selectivos/con alias de funciones, structs, enums y
  callables soportados, sin storage ni inicialización importada;
- `int` checked i32, `double`, `boolean`, `string`, `void`, enums sin payload y
  structs con layout soportado;
- function values exclusivamente para funciones top-level sin captura, firma
  estructural exacta y llamadas indirectas; una función abreviada sigue siendo
  declaración;
- Array/List de scalars, strings y structs registrados, con semántica de
  referencia, const access path, for-in prestado, RC, Eq, copy y slicing;
- Vector/Matrix local `int`/`double` sólo en las operaciones core que preservan
  shape en profile 22;
- literales core, aritmética int/double, promoción `int -> double`, potencia,
  comparaciones, short-circuit, igualdad y casts identidad/`int↔double`;
- acceso, mutación, métodos y constructores de structs; indexación y slicing
  de colecciones soportadas;
- strings: transporte UTF-8, ARC, concat, igualdad, print, `byteLength`,
  `trim`, `split`, `parseInt` y `parseDouble`;
- `print`/`println`, math scalar consolidada, `Math.mod`, `Math.factorial`,
  `Math.pi`, `System.args()` y forwarding del CLI;
- IO de texto UTF-8 read/write/append/atomic y el codec explícito ALPT1 del
  Expense Tracker, dentro de la plataforma declarada;
- panics checked de overflow, división/módulo, bounds y rango step cero;
- pipeline IR/SSA verificado, O0/O1 con verificación posterior, CLI native por
  defecto y selección explícita de backend;
- formatter, diagnostics syntax/type del LSP e IntelliJ lexer/highlighter para
  la sintaxis estable.

En términos de inventario, son exactamente las 75 filas `SUPPORTED`: C01,
C03–C05, C07–C12, C14, C16–C23, C25; T01, T03–T08, T14, T16, T19, T21, T23,
T25, T29; E01, E03–E11, E13–E14, E16, E18, E20, E22–E24, E26; R01, R04–R06,
R08, R10–R11, R13, R16, R19, R21, R23; B01–B05 y B07–B11.

## Queda fuera de Aether 1.0

La lista exacta y el resultado esperado es:

- inferencia local por asignación y otros compound assignments: syntax o
  `AE-BACKEND-VARIABLES_AND_CONST`;
- rango almacenado/parámetro/retorno, Range<double>, Matrix/string for-in:
  type error o `AE-BACKEND-FOR_IN`/`MATRIX`;
- funciones anidadas, lambdas, closures, retorno callable, builtins como valor
  y bound methods: type/capability error;
- globals/constantes y statements inicializadores importados:
  `AE-BACKEND-MODULES`;
- `float`, `complex`, tuple, nullable/null y sus casts/operaciones:
  `AE-BACKEND-PRIMITIVE_TYPES`;
- `Any`, unions y generics de usuario: syntax/type o `AE-BACKEND-GENERICS`;
- classes, sus constructores/métodos/campos y ownership:
  `AE-BACKEND-CLASSES`, `CLASS_CONSTRUCTORS` o `CLASS_METHODS`;
- interfaces y dispatch: `AE-BACKEND-INTERFACES`;
- Array/List anidados o con layout no registrado:
  `AE-BACKEND-AGGREGATE_COLLECTION_ELEMENTS` o capability del tipo;
- Vector/Matrix avanzado, slicing, iteración Matrix, pérdida de shape en ABI y
  algebra lineal host: `AE-BACKEND-VECTOR`/`MATRIX`;
- interpolación y formatting string general: `AE-BACKEND-STRINGS`;
- input: `AE-BACKEND-INPUT`;
- `throw`/`try`/`catch`: `AE-BACKEND-ERROR_HANDLING`;
- Plots, persistencia/DB genérica, IO binario, streams, procesos y GC: fuera de
  la gramática o capability específica;
- unwind/cleanup excepcional, panic controlado de stack overflow y ownership
  class: fuera del contrato;
- un O2 distinto, ABI estable y soporte native Windows/macOS: no prometidos;
- `long`, do-while, match, lambdas, closures y rangos genéricos: post-1.0.

En términos de inventario, son exactamente las 46 filas `OUTSIDE_V1`: C02,
C06, C13, C15, C24, C26; T02, T09–T13, T15, T17–T18, T20, T22, T24, T26–T28;
E02, E12, E15, E17, E19, E21, E25, E27–E29; R02–R03, R07, R09, R12, R14–R15,
R17–R18, R20, R22, R24; B06, B14–B15.

## Requiere trabajo antes de decidir

**Ninguna feature.** El grupo `UNDECIDED` queda vacío a propósito. Classes,
interfaces, float, complex, Vector/Matrix avanzado, rangos almacenados y
function values avanzados no necesitan una decisión ambigua: quedan fuera de
1.0 y pueden reabrirse después con un RFC y evidencia E2E.

El trabajo de coherencia identificado antes de RC3 no decide features nuevas:

1. **cerrado en R1:** hacer que la spec normativa exprese esta frontera;
2. **cerrado en R2:** separar/rotular los experimentales y resolver los cuatro
   ejemplos rotos sin ampliar v1;
3. normalizar diagnostics públicos de verification/ICE y ejecutar todos los
   gates finales.

## Cierres operativos posteriores a la auditoría

La tabla de `AETHER_V1_PROFILE_AUDIT.md` conserva B12/B13 como el snapshot que
originó R1/R2. Ambos hallazgos están cerrados por evidencia posterior y gates
dedicados; no se contaron como nuevas features `SUPPORTED`, por lo que el
inventario normativo permanece exactamente en 75. El catálogo no eliminó ni
debilitó el gate: todas sus rutas restantes tienen una clasificación
verificable.

## Recomendación de RC3

**Aether no está todavía lista para preparar una RC3 publicable.** F02/R1 y
F01/R2 están cerrados, pero falta R3: exponer `verification` de forma estable y
una frontera `internal compiler error` sin traceback para fallos inesperados.
Después deben repetirse los gates finales de R4 desde un commit limpio.
