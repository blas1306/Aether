# ITERATION-ARCH-1 — `for-in`, ranges e iteración de colecciones

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-14.

Este milestone define la primera semántica de iteración de Aether. No modifica
parser, AST, HIR, MIR, SSA, backend, runtime ni la fila de features soportadas.
La sintaxis y los nombres de operaciones internas descritos aquí son contratos
para verticales posteriores, no superficie actualmente admitida.

La decisión se apoya en el charter y contrato v1, en la separación tipada
AST → HIR → MIR → SSA → LLVM, en el modelo vigente de referencias y ownership,
en los contratos de `Array<T>`/`List<T>`, en el cleanup excepcional y en la
separación lenguaje/Core/STD fijada por MODULE-STD-ARCH-1.

## 1. Decisiones resumidas

- La forma fuente es `for (binding in iterable) { ... }`.
- V1 reconoce como iterables solamente `Range<T>`, `Array<T>` y `List<T>`.
- Un range se escribe `start:end` o `start:step:end`; ambos extremos son
  inclusivos cuando un valor generado coincide con el extremo.
- El step implícito es `+1` del tipo resuelto. Nunca se infiere `-1`.
- Una dirección incompatible produce una secuencia vacía. No es error ni trap.
- Step cero es inválido. Un cero demostrable se diagnostica estáticamente; un
  cero dinámico produce un trap no capturable antes de la primera iteración.
- Los tres operands se evalúan exactamente una vez, de izquierda a derecha.
- Ranges admiten los enteros signed/unsigned, `isize`/`usize`, `float32` y
  `float64`, usando únicamente typing y widening ordinarios.
- Los ranges float no usan epsilon y generan el candidato `k` desde el origen,
  no sumando repetidamente el step.
- `Range<T>` es un valor inline `Copy`, sin allocation, definido por el
  lenguaje. No pertenece a `std` y no introduce todavía una API general.
- Array y List se recorren en orden de índice ascendente, cero-based, observando
  una longitud capturada una sola vez. No se crea un iterator heap object.
- Un elemento `Copy` produce un binding `T` por valor. Un elemento no-Copy
  produce un binding explícitamente tipado `ref T`, sin Alias, retain/release,
  deep copy ni move desde la colección.
- El binding es semánticamente nuevo en cada iteración y sólo vive dentro del
  body. La reutilización física de un slot es una optimización.
- La estructura de un List no puede mutar durante su iteración. Array no posee
  mutación estructural. Un elemento prestado tampoco puede ser reemplazado por
  una operación que pueda invalidar ese préstamo.
- `break`, `continue`, `return` y unwind ejecutan los cleanups de los scopes que
  abandonan. Los traps conservan la política fail-fast sin unwind.
- No se introduce `Iterator<T>`, dispatch dinámico, generators ni iteración
  definida por usuarios.

## 2. Superficie fuente

La forma conceptual y gramatical es:

```text
for_statement := "for" "(" for_binding "in" expression ")" block
for_binding   := identifier | type identifier
```

`type` incluye los tipos de referencia ya existentes, por lo que un binding
owning explícito se escribe `ref T name`, no mediante una excepción gramatical:

```aether
for (i in 0:10) { ... }
for (int32 i in 0:2:10) { ... }
for (double x in 0.0:0.01:10.0) { ... }
for (x in values) { ... }
for (ref string value in strings) { ... }
```

No se admiten en esta decisión destructuring, múltiples bindings, índice
implícito, `else` de loop ni una cláusula distinta de `in`.

### 2.1 Expresión range

Las formas son:

```text
range_expression := expression_no_range ":" expression_no_range
                  | expression_no_range ":" expression_no_range
                    ":" expression_no_range
```

El nodo range es no asociativo. Un operand que sea a su vez un range exige
paréntesis y será rechazado por tipo en V1 porque `Range<T>` no es un scalar
numérico. El parser debe conservar ambos o tres operands, sus spans y su orden;
no debe fabricar el `+1` en AST.

La precedencia concreta se incorporará a la gramática junto a las expresiones
de control existentes, con estas obligaciones observables:

```aether
begin():limit()              // begin y limit son operands completos
0:step() + 1:end()           // el operand central incluye la suma
10:-2:0                      // -2 es unario, no un token especial de range
var r = 0:2:10;              // range es una expresión y un valor
```

No hay range abierto: falta de start, step o end es error sintáctico. Tampoco
se interpreta `:` según whitespace.

## 3. Evaluación y construcción

Para `start:step:end`:

1. se evalúa `start` exactamente una vez;
2. se evalúa `step` exactamente una vez;
3. se evalúa `end` exactamente una vez;
4. se construye y valida el `Range<T>` inline;
5. sólo entonces puede comenzar una iteración.

Para `start:end`, se evalúan start y end en ese orden y luego se materializa el
step canónico `T(1)`. El step implícito no es una llamada ni un efecto visible.

Si un operand lanza, sólo se observan los efectos y cleanups anteriores según
el orden normal de Aether; no existe todavía un Range publicable. Si un operand
termina en trap, rige la política fail-fast existente. Almacenar un range no
aplaza su validación:

```aether
var r = start():step():end(); // evalúa y valida aquí
for (x in r) { ... }          // no reevalúa sus componentes
```

Cada uso posterior copia los tres scalars del range. Las optimizaciones pueden
eliminar esa copia cuando sea inobservable.

## 4. Resolución de tipos

`Range<T>` se admite cuando `T` es exactamente uno de:

- `int8`, `int16`, `int32`, `int64` y el alias `int`;
- `uint8`, `uint16`, `uint32`, `uint64`;
- `isize`, `usize`;
- `float32`, `float64` y los aliases `float`, `double`.

`bool`, `char`, enums, strings, aggregates, references, classes, containers y
parámetros genéricos sin una futura garantía numérica de range se rechazan.

Los operands se resuelven a un único `T` mediante contextual literal typing y
las conversiones implícitas normales. Range no agrega promotion, narrowing,
signed/unsigned mixing ni conversión float especiales. Un valor ya tipado que
no puede convertirse normalmente no se legaliza por aparecer entre `:`.

El contexto puede fluir desde el binding explícito al range:

```aether
for (float32 x in 0.0:0.1:1.0) { ... }
```

Aquí las literals se contextualizan a `float32`. Sin binding explícito, las
reglas ordinarias fijan `int` para literals enteras no restringidas y `float64`
para literals flotantes no restringidas. La inferencia termina en un TypeId
canónico antes de HIR; nunca es dynamic typing.

Un binding explícito no representa una conversión por elemento. Después de la
resolución contextual, su tipo debe coincidir exactamente con el tipo de item
del iterable. En particular, `int32` no acepta silenciosamente items `int64`.

### 4.1 Step y dirección

El signo se interpreta en el tipo `T` ya resuelto:

- signed/float con `step > 0`: dirección ascendente;
- signed/float con `step < 0`: dirección descendente;
- unsigned: todo step válido es ascendente;
- `step == 0`, incluido `-0.0`, es inválido.

Como todos los componentes comparten `T`, un range unsigned descendente no se
expresa mediante step negativo. El programador debe escoger un tipo signed si
necesita esa secuencia. No se introduce un step signed heterogéneo para ranges
unsigned.

`start:end` siempre usa step positivo uno. Por tanto `10:0` es vacío, no una
cuenta regresiva.

## 5. Semántica de ranges enteros

Sea el range validado `(s, d, e)`.

- Si `d > 0` y `s > e`, la secuencia es vacía.
- Si `d < 0` y `s < e`, la secuencia es vacía.
- En cualquier otra combinación compatible, el primer item es `s`.
- Ascendiendo se emite un candidato mientras sea `<= e`.
- Descendiendo se emite un candidato mientras sea `>= e`.
- `s == e` produce exactamente `s` una vez con cualquier step no cero.

Así:

```text
0:10       = 0, 1, 2, ..., 10
0:2:10     = 0, 2, 4, 6, 8, 10
10:-2:0    = 10, 8, 6, 4, 2, 0
0:-1:10    = vacío
10:1:0     = vacío
```

Elegir vacío para dirección incompatible hace que una relación dinámica que
cruza no cambie súbitamente a trap ni a una dirección inferida. La dirección
depende sólo del step y cero sigue siendo el único error de dirección.

La progresión se define en enteros matemáticos y se proyecta sólo cuando el
siguiente valor es representable y satisface el límite. El avance interno no
debe ejecutar una suma overflowing después de haber emitido el último valor.
Por ejemplo `MAX:MAX` con step implícito emite `MAX` una vez y termina, sin
trap. Esto no debilita el overflow de operaciones aritméticas escritas por el
usuario: es la condición de agotamiento propia de Range.

El número de items es finito porque T es acotado y el step no es cero. El
lowering puede usar suma checked con una prueba previa equivalente, un entero
interno más ancho o aritmética de distancia; nunca wraparound.

## 6. Semántica de ranges float

Los ranges float se definen para el TypeId IEEE original. No se promueve
`float32` a `float64` durante generación y no se consulta locale, rounding mode
ambiental ni libc formatting.

### 6.1 Operands admitidos

En construcción:

- cualquier NaN en start, step o end produce `InvalidRangeOperand`;
- cualquier `+Inf` o `-Inf` en start, step o end produce
  `InvalidRangeOperand`;
- `+0.0` y `-0.0` como step producen `ZeroRangeStep`;
- signed zero es válido como start o end y conserva sus bits cuando se emite
  como primer item.

Ambos son traps estructurados no capturables bajo el modelo actual. Un caso
constante demostrable debe diagnosticarse antes de MIR en vez de generar un
trap inevitable. Exigir operands finitos evita ranges infinitos encubiertos y
mantiene local la garantía de terminación.

### 6.2 Generación por índice

El item lógico cero es exactamente `s`. Para `k > 0`, el candidato es:

```text
p(k) = round_T(convert_T(k) * d)
v(k) = round_T(s + p(k))
```

`convert_T`, multiplicación y suma usan las reglas IEEE estrictas del tipo T.
Son operaciones separadas: no FMA, extended precision, reassociation ni fast
math. `k` es un entero interno exacto no negativo; su conversión no es una
conversión source nueva ni cambia las reglas disponibles al usuario.

No se define la secuencia como `previous + d`. Por ello cada candidato depende
de start, step e índice, no del error acumulado de todos los candidatos previos.

### 6.3 Continuación, progreso y endpoint

Para step positivo un candidato finito se emite si `v(k) <= e`; para step
negativo se emite si `v(k) >= e`. Antes de emitir todo candidato posterior al
primero se exige progreso estricto respecto del último item emitido:

- positivo: `v(k) > previous`;
- negativo: `v(k) < previous`.

Si el candidato todavía está dentro del límite pero no progresa, se produce
`FloatRangeNoProgress`. No se omiten duplicados ni se incrementa k en secreto
hasta encontrar otro valor. Esta regla cubre steps demasiado pequeños para la
magnitud de start y la pérdida de precisión de `convert_T(k)`.

Si un candidato cruza el límite, el range termina sin emitirlo. Un infinito
producido por overflow IEEE durante multiplicación/suma se trata como un cruce
en la dirección de avance y agota el range; nunca se emite, porque los items de
un range construido válidamente son finitos. Un NaN generado durante el cálculo
produce `InvalidRangeProgress` en lugar de hacer depender el resultado de una
comparación unordered.

El contador interno nunca puede wrappear. Si su representación física se
agota mientras todavía haría falta decidir otro candidato, se produce
`RangeIterationLimit`; una implementación puede escoger una representación
mayor que `usize`, pero no cambiar el resultado silenciosamente. Entre el
dominio finito de T, el progreso estricto y ese guard, toda ejecución termina o
produce un trap en cantidad finita de pasos.

La inclusividad es una condición de comparación, no una promesa de alcanzar
los bits de end. Por ejemplo `0.0:0.1:1.0` emite todos los `v(k)` ordenados que
satisfacen el límite. `1.0` aparece sólo si algún cálculo estricto produce ese
valor representable exacto. No existe epsilon oculto, snapping al endpoint ni
iteración adicional especial.

Signed zero obedece comparaciones IEEE después del primer item. Como `-0.0` y
`+0.0` comparan iguales, un range entre ambos puede emitir una vez los bits de
start; no duplica el cero para representar ambos signos.

## 7. `Range<T>` como valor

Range es un tipo compiler-known del **lenguaje**, no una API de `std`. Su
representación semántica mínima es:

```text
Range<T> { start: T, step: T, end: T }
```

Para todos los T admitidos es `Copy`, `Relocatable`, `Storable` y no necesita
drop. La representación es inline, de tamaño aproximado `3 * sizeof(T)` más el
padding exigido por layout; no contiene puntero, capacity, contador, vtable ni
estado de iteración. La dirección se deriva de step.

Esta forma permite:

```aether
var r = 0:2:10;
for (i in r) { ... }
```

sin allocation ni runtime helper. La identidad `Range<T>` debe ser canónica en
el TypeArena y no depender del spelling de aliases. El layout físico sigue
siendo ABI interno hasta que una frontera pública lo estabilice.

No se abre todavía un constructor nominal, fields públicos, `length`, indexing,
equality, hashing, conversiones a collections ni methods. Tampoco se promete
que cualquier `Range<U>` futuro tenga estas capacidades si U se amplía más allá
de scalars.

Range pertenece al lenguaje porque syntax, contextual typing, dirección,
traps, floating progress y lowering verificable requieren conocimiento de
frontend y middle-end. Colocarlo en `std` haría que la misma expresión cambiara
de significado según imports y ocultaría reglas que el backend debe preservar.

## 8. Iteración de `Array<T>` y `List<T>`

### 8.1 Orden y longitud

Array y List se recorren por índices `0, 1, ..., length-1`, en ese orden. La
expresión iterable se evalúa una vez y la longitud se lee exactamente una vez,
después de obtener el iterable y antes del primer header. Esa longitud es el
extent de la iteración.

No se toma una copia de los elementos. El item se lee o presta al entrar a su
iteración, de modo que una modificación no estructural legal de un elemento
todavía no visitado puede ser observada más tarde.

Para List, el préstamo de estructura que sostiene el loop impide que su length
o backing cambien, por lo cual el snapshot no puede quedar obsoleto mediante
código Aether aceptado. No se usa una concurrent-modification exception,
version counter ni chequeo runtime por vuelta.

Los bounds checks siguen siendo semánticamente los de indexing. El verificador
puede probar que `index < captured_length == current_length` y permitir que el
backend elimine el check redundante. Si no existe esa prueba, el check no se
omite.

### 8.2 Evaluación y lifetime del iterable

- Un lvalue Array/List se presta sin consumirlo. Su owner no puede moverse,
  reemplazarse ni destruirse hasta salir del loop.
- Un `*reference` que produce un Place conserva la provenance del owner y las
  capacidades de lectura existentes.
- Un resultado temporal owning se transfiere a un root oculto del loop. Su
  lifetime se extiende hasta la salida completa y se destruye exactamente una
  vez allí o durante unwind.
- Una expresión inválida, moved-from o no legible se rechaza antes de lowering.

Esta extensión es específica del root oculto que recibe un resultado owning ya
completo; no convierte rvalues arbitrarios en Places prestables ni generaliza
la extensión de temporales de referencias de V9.

### 8.3 Categoría del binding

Sea T el elemento exacto de la colección:

| Propiedad de T | Tipo del binding | Operación por item |
|---|---|---|
| T es `Copy` | `T` | lectura/copia del valor |
| T no es `Copy` | `ref T` | préstamo compartido al slot |

El segundo caso no ejecuta Alias de string/class/interface, retain/release,
Clone, deep copy, Take, Move ni Relocate. El owner del slot continúa siendo la
colección. El binding no puede escapar del body conforme a las reglas de
referencias vigentes.

Iteración no amplía por sí sola la admisión de elementos de una colección. Así,
`List<string>` usa hoy esta regla de préstamo porque esa colección ya es legal;
`List<ClassHandle>` tendrá la misma regla cuando otro milestone admita handles
de clase en storage, pero ITERATION-ARCH-1 no elimina el gate actual de
Storable/composición OOP para conseguir ese ejemplo.

La categoría forma parte del tipo visible. Por ello:

```aether
for (value in strings) { ... }              // value: ref string
for (ref string value in strings) { ... }   // válido y explícito
for (string value in strings) { ... }       // error: requeriría Alias/owner
```

El acceso al pointee usa la sintaxis explícita normal (`*value`). No se agrega
auto-deref sólo para disimular el préstamo. Un diagnóstico puede proponer
`ref string` o un futuro modo de iteración owning, pero V1 no inventa ese modo.

Que un aggregate sea grande pero `Copy` conserva semántica por valor. El
optimizador puede scalarizar o prestar internamente si demuestra equivalencia,
sin cambiar mutabilidad, lifetime ni aliasing observables.

### 8.4 Mutación y aliasing

El binding de un `for` normal nunca es `ref mut`; no permite modificar el slot
actual. Esta decisión no reserva una spelling implícita mutable.

Durante cualquier iteración activa de List se rechazan sobre el mismo root, o
un alias que pueda alcanzarlo:

- `push`, `reserve` y cualquier operación con posible reallocation;
- `pop`, `swap_remove`, `remove` y cualquier cambio de length/rango;
- move, replacement o drop del List;
- una llamada por `ref mut List<T>` o por un aggregate que lo contiene cuando
  el análisis de efectos no pueda probar ausencia de mutación estructural.

La prohibición es estática e independiente de spare capacity. Array no tiene
mutaciones estructurales, pero su owner tampoco puede moverse/reemplazarse
mientras el loop conserva provenance.

Para elementos `Copy`, una asignación ordinaria a un elemento de la misma
colección es no estructural y puede admitirse si el path es escribible. El
binding actual sigue siendo la copia ya obtenida; asignaciones a índices futuros
pueden afectar los valores que se obtendrán después.

Para elementos no-Copy, el `ref T` del item vive durante todo el body. Mientras
vive se rechaza replacement/extraction del slot si puede ser el prestado. V1
reutiliza la provenance existente: puede aceptar una operación sobre un slot
demostrablemente disjunto, pero relaciones dinámicas, aliases o nesting
ambiguos fallan cerrado. La mutación interior observable a través de otros
aliases sigue las reglas del tipo; `ref T` es capacidad read-only, no prueba de
inmutabilidad global ni promesa LLVM `noalias`.

Al terminar normalmente el body o ejecutar `continue`, el préstamo del item
termina antes del avance. El préstamo estructural del iterable dura hasta la
salida completa del loop.

## 9. Binding, scope y shadowing

El binding recibe un `LocalId` nuevo y sólo es visible dentro del body. No es
visible en la expresión iterable, en start/step/end ni después del loop.

La declaración sigue las reglas lexicales actuales:

- puede shadowear un binding de un scope exterior cuando el resolver ordinario
  lo permita;
- no puede colisionar con otro nombre del mismo scope, un alias/root importado
  protegido ni un nombre cuya regla actual prohíba shadowing;
- el tipo explícito se resuelve en el scope exterior; el nombre nuevo entra en
  scope sólo después de resolver y validar el iterable.

Cada vuelta crea semánticamente una instancia nueva del binding, con
inicialización, lifetime y cleanup propios. En V1 los bindings range y Copy no
requieren drop; el binding `ref T` tampoco posee el pointee. La regla fresh es
normativa para futuras closures: si se admiten capturas, cada closure deberá
capturar la instancia de su vuelta o la feature deberá fallar cerrada hasta
implementar esa representación. No podrá cambiarse retroactivamente a “un slot
compartido por todas las vueltas”.

El backend puede reutilizar la misma dirección física cuando no existe escape
ni observación de identidad. Eso es storage reuse, no identidad source.

## 10. Salidas, cleanup y excepciones

El loop introduce dos niveles de recursos conceptuales:

1. el estado del iterable, vivo desde el preheader hasta la salida del loop;
2. el binding y temporales del body, nuevos en cada vuelta.

Las transferencias obedecen:

- fallthrough del body: limpia body/binding y ejecuta avance;
- `continue`: limpia los scopes abandonados y el binding, luego va al latch;
- `break`: limpia los scopes abandonados y el binding, luego sale sin avanzar;
- `return`: materializa primero el resultado según el contrato vigente, limpia
  body, binding, estado/root oculto del iterable y scopes exteriores;
- excepción: el edge unwind limpia en orden inverso todo lo completamente
  inicializado, incluido el root temporal iterable, y continúa con el mismo
  `ExceptionEvent`;
- entrada a `finally`: conserva el target pendiente de break/continue/return
  conforme a EXCEPTION-V4 y retoma exactamente el header/latch/exit fijado;
- trap: termina sin promesa nueva de cleanup y nunca entra a catch/finally.

Un lvalue collection prestado no se destruye al salir del loop. Un temporal
collection owning sí. El estado de Range contiene sólo scalars y no necesita
drop. Si futuros iterables agregan recursos, deberán satisfacer esta misma
frontera explícita; no se infiere cleanup desde un objeto iterator opaco.

## 11. Modelo HIR

El AST conserva sintaxis; HIR debe cerrar significado. Una forma orientativa es:

```text
ForIn {
    binding: { LocalId, TypeId, BindingCategory },
    iterable: ResolvedIterable,
    body,
    span
}

ResolvedIterable =
    Range { RangeTypeId, item_type, start, step, end, direction_contract }
  | Array { owner_place_or_temp, item_type, item_access, extent }
  | List  { owner_place_or_temp, item_type, item_access, extent,
            structural_borrow }

BindingCategory = CopyValue | SharedElementBorrow
```

HIR debe conservar/verificar:

- TypeId exacto del iterable, item y binding;
- step explícito o implícito ya tipado, sin perder spans originales;
- orden de evaluación y validaciones de Range;
- categoría Copy/Borrow y provenance del owner;
- si la collection es lvalue prestado o temporal owning capturado;
- snapshot de length y clasificación de efectos/invalidation;
- `break`/`continue` targets lexicales y regiones de cleanup/finally;
- ausencia de conversiones por item, moves y Alias ocultos.

Range almacenado llega como una expresión ordinaria `Range<T>`; el HIR de
`for` no reinterpreta su source spelling ni reevalúa sus fields. Un range literal
puede conservar forma reconocible para diagnostics/const folding sin recibir
otra semántica.

## 12. Lowering MIR

`for-in` baja a CFG estructurado ordinario. No necesita sobrevivir como una
instrucción monolítica, pero MIR debe conservar operaciones/metadata suficientes
para verificar el protocolo.

### 12.1 Range entero

```text
preheader:
    eval/validate range once
    establish direction and initial current
    branch compatible ? header : exit
header:
    prove current within inclusive bound
    initialize fresh binding = current
    goto body
body:
    ...
    fallthrough/continue -> body_cleanup -> latch
    break -> body_cleanup -> exit
latch:
    compute exhaustion or checked next without wrap
    next exists ? current = next; goto header : goto exit
exit:
    iterable cleanup if required
```

### 12.2 Range float

El preheader valida finitud/step y fija `k=0`, `previous=start`. El latch
incrementa el contador sin wrap; el siguiente candidate se calcula desde
`start`, `step` y k mediante las dos operaciones IEEE separadas. El CFG distingue
crossed-bound, no-progress, NaN generado y counter exhaustion. Ningún optimizer
puede sustituirlo por suma recurrente bajo perfiles normales.

### 12.3 Array/List

```text
preheader:
    evaluate/capture owner once
    length_snapshot = length(owner) once
    index = 0
header:
    index < length_snapshot ? item : exit
item:
    CopyValue: binding = checked/proven load owner[index]
    Borrow:    binding = Borrow(owner[index])
    goto body
body:
    ...
latch:
    end item borrow
    index = proven_nonwrapping(index + 1)
    goto header
exit:
    end structural borrow; drop hidden owner if any
```

El incremento es seguro por `index < length_snapshot` y por la representación
válida de length; el verifier debe comprobar esa dominancia, no confiar en un
flag del frontend. La dirección del descriptor proyectado se resuelve antes del
loop y se mantiene mediante la frontera de memoria selectiva existente.

MIR conserva `LoopId`, header/latch/exit, targets de break/continue, scopes de
cleanup, categoría de item, root/provenance, captured length, progress contract
y efectos que pueden lanzar o trap. Los backedges deben conservar estados de
ownership compatibles; `for` no legaliza moves loop-carried antes rechazados.

## 13. SSA y backend

SSA recibe sólo MIR verificado. Debe representar:

- phis exactos del índice/counter y del current cuando corresponda;
- memory locals para roots address-taken o prestados según la frontera vigente;
- borrows y usos con TypeId/provenance exactos;
- edges normal, break, continue, return y unwind;
- cleanup y ownership lineal de temporales owning;
- guards dominantes de bounds, dirección, float progress y counter overflow.

El verificador SSA reconstruye el protocolo desde CFG y operands; no acepta una
marca `verified_for` como sustituto. Debe rechazar, entre otras corrupciones:
reevaluar operands, cambiar orden, usar `<` en vez de `<=`, wrap de índice,
advance en break, omitir advance en continue, prestar el TypeId incorrecto,
mover un elemento owning, perder un drop o conectar un trap a catch.

LLVM puede emitir loops, phis, loads/GEPs y comparisons ordinarios. Range no
llama allocator. Array/List no crean iterator object. El backend puede eliminar
bounds checks, scalarizar Range o reutilizar slots sólo con pruebas preservadas
por MIR/SSA. O0 y O2 deben observar igual secuencia, traps, effects y cleanup.

## 14. Costos contractuales

| Operación | Allocation | Costo por item | Ownership por item |
|---|---:|---:|---|
| Range integer | 0 | comparación + avance | copia scalar |
| Range float | 0 | conversión de k + mul + add + checks | copia scalar |
| Array/List de Copy | 0 adicional | índice + load (+ check no eliminado) | copia T |
| Array/List owning | 0 adicional | índice + borrow | ninguno |

La creación de un List/Array temporal conserva sus costos propios; el loop no
agrega otra collection ni iterator. Capturar temporal significa transferir su
owner existente, no clonarlo.

La ausencia de retain/release por item owning es contractual para el `for`
normal. Una optimización no puede introducirlos como semántica observable ni
usar fast math para modificar cantidad/contenido de items float. Tampoco puede
hoistear/reordenar effects de start, step, end, iterable o body.

## 15. Primer vertical recomendado

El primer vertical debe ser **ITERATION-V1 — `int` range `for-in` nativo**:

1. parsear `for (x in start:end)` y `for (x in start:step:end)`;
2. admitir sólo el TypeId canónico `int`/`int64` en esta fila inicial;
3. implementar operands expresivos evaluados una vez izquierda→derecha;
4. implementar step default, inclusividad, descendente explícito, dirección
   incompatible vacía y zero-step diagnostic/trap;
5. asignar binding LocalId fresh, con inferencia o `int x` exacto;
6. bajar a CFG explícito con overflow-safe exhaustion;
7. componer `break`, `continue`, nested loops, return, throw/catch y finally;
8. verificar independientemente HIR, MIR y SSA, incluido cleanup;
9. emitir LLVM nativo Linux x86-64 en O0/O2, sin runtime/heap helper;
10. fallar cerrado para Range de otros T y para Array/List `for-in` hasta sus
    verticales correspondientes.

Qualification mínima:

- secuencias exactas empty/singleton/ascending/stride/descending/MAX/MIN;
- funciones con side effects para probar evaluación única y orden;
- step cero constante y dinámico;
- dirección incompatible dinámica;
- break antes de advance y continue con un solo advance;
- scopes, shadowing, nested loops y binding no visible después;
- return/unwind/finally con contadores de cleanup;
- dumps deterministas y corrupciones de cada contrato HIR/MIR/SSA;
- ausencia de allocation, iterator helpers, wrap y diferencias O0/O2;
- tests workspace, fmt, clippy, diff check y differential nativo.

El siguiente vertical natural es Range para todos los enteros; después Range
float con corpus bit-exact y guards de progreso; luego Array/List Copy; por
último el binding `ref T` para elementos owning con pruebas de ARC cero e
invalidación. El orden puede agrupar verticales si cada fila mantiene evidencia
nativa completa, pero no debe aceptar sintaxis antes de su ruta backend.

## 16. Decisiones abiertas posteriores

Esta arquitectura deja deliberadamente fuera, sin debilitar V1:

- spelling y semántica de iteración mutable (`ref mut`) y de consumo/move;
- una forma explícita de pedir Alias/value sobre elementos owning;
- iteración sobre View, Vector/Matrix views, string/Text y otras sequences;
- nombre público, constructor y API de `Range<T>`;
- capabilities genéricas necesarias para `Range<T>` simbólico;
- iterators/iterables user-defined y su relación con ownership/effects;
- closures, aunque la identidad fresh por vuelta ya queda fijada;
- optimizaciones vectorizadas y análisis de trip count float;
- ranges abiertos, infinitos, reverse helpers, slicing y custom strides.

Un futuro protocolo iterable deberá bajar a una forma verificable equivalente,
declarar lifetime/cleanup/effects y evitar dispatch/allocation ocultos. No puede
cambiar retrospectivamente el significado de Range, Array o List ni convertir
el `for` normal en consumo destructivo.

## 17. Consecuencias

La decisión ofrece una forma única y legible de recorrer intervalos y las dos
colecciones computacionales básicas sin introducir prematuramente un framework
de iterators. Las direcciones vacías son composables; los errores reales —step
cero, operands float no finitos o falta de progreso— fallan de manera explícita.

El modelo float evita epsilon y acumulación recurrente, a costa visible de una
multiplicación por item y de traps de progreso para secuencias que la precisión
no puede representar. El modelo de collections evita copies/ARC de owners y
hace visible `ref T` en el tipo del binding. MIR/SSA conservan suficiente
estructura para probar bounds, progreso, ownership, targets y cleanup antes de
LLVM, manteniendo la política native-first del proyecto.
