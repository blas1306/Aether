# Aether — BITWISE-OPERATORS-ARCH-1

Estado: **CLOSED; ARQUITECTURA APROBADA; IMPLEMENTACIÓN NO INICIADA**

Fecha: 2026-11-27

Base auditada: `a3e5f124df6bea1e8e7e4073a55f33306d107bbf`

Alcance: contrato semántico y arquitectura para `compiler-next`. Este documento
no habilita sintaxis, no modifica el lenguaje implementado y no autoriza
potenciación ni asignaciones compuestas bitwise.

## 1. Resumen de la arquitectura aprobada

La superficie futura es:

```aether
left & right   // AND bitwise
left | right   // OR bitwise
left ^ right   // XOR bitwise
~value         // NOT bitwise
left << count  // shift izquierdo checked
left >> count  // shift derecho aritmético o lógico según left
```

Las decisiones ya fijadas por el encargo son:

- `^` significa exclusivamente XOR bitwise;
- `**` y `pow(a, b)` quedan reservados conceptualmente para potenciación en
  `EXPONENTIATION-V1`; no forman parte de BITWISE-OPERATORS-V1;
- `&` conserva el borrow unario y `&mut` conserva el borrow mutable;
- `&&`, `||` y `!` siguen siendo operadores lógicos distintos;
- `|` no puede apropiarse de una posición perteneciente a la gramática de tipos;
- V1 no incluye `&=`, `|=`, `^=`, `<<=`, `>>=` ni `**=`.

Las decisiones normativas aprobadas son:

1. `&`, `|`, `^` y `~` operan sobre el patrón de bits de un entero de ancho
   fijo, preservan ese ancho y nunca hacen trap.
2. Los operadores binarios de bits usan las conversiones enteras ordinarias ya
   existentes y, tras ellas, exigen dos operandos del mismo `TypeId` canónico.
3. Los shifts no usan esa regla homogénea: el resultado y la representación los
   determina el operando izquierdo; la cantidad puede ser cualquiera de los diez
   enteros nativos y no se convierte implícitamente a un tipo fuente distinto.
4. Una cantidad negativa o mayor o igual al ancho hace trap
   `ShiftCountOutOfRange` antes de emitir cualquier shift LLVM.
5. `>>` es aritmético para signed y lógico para unsigned.
6. `<<` es checked para signed y unsigned: hace `IntegerOverflow` si el valor
   matemático `left * 2^count` no cabe en el tipo izquierdo. No descarta bits
   significativos silenciosamente.

Estas decisiones cierran BITWISE-OPERATORS-ARCH-1. No autorizan iniciar ni
implementar BITWISE-OPERATORS-V1.

## 2. Preflight y autoridad observada

HEAD coincide exactamente con la base esperada. El preflight encontró cambios
personales ajenos en `examples/ProbandoNR/`, dos reports no trackeados bajo
`docs/reports/` y `examples/ProbandoNR/probandoNR3C`. No se modifican, mueven ni
normalizan.

La autoridad auditada es:

- `aether-frontend/src/lexer.rs`: maximal munch para `&&`; `&` ya es token
  independiente; `||` existe, pero un `|` aislado hoy es error léxico. No existen
  todavía tokens `^`, `~`, `<<`, `>>` ni `**`.
- `aether-frontend/src/parser.rs`: precedencia descendente actual
  `unary`, multiplicativa, aditiva, comparación, igualdad, range, `&&`, `||`.
  El borrow vive en `unary`; los genéricos consumen tokens `<` y `>` individuales.
- `aether-frontend/src/ast.rs`: `AstUnaryOp` separa negación, dereference,
  borrows y logical-not; `AstBinaryOp` separa aritmética, comparación y lógica.
- `aether-frontend/src/types.rs`: existen diez enteros canónicos. `isize` y
  `usize` conservan identidad distinta de `int64`/`uint64`, incluso en x86-64.
- `aether-frontend/src/hir.rs`: los aliases son transparentes y resuelven a un
  `TypeId` canónico; `TypeAliasInfo` conserva nombre y spelling declarados. Los
  literals enteros son contextuales y por defecto `int64`. `common()` sólo
  ensancha entre anchos fijos de igual signedness; no mezcla signed/unsigned,
  integer/float ni tipos sized con fixed-width.
- los verificadores HIR, MIR y SSA reconstruyen contratos de operandos, resultado
  y traps; MIR/SSA usan actualmente un solo tipo para ambos operandos de
  `BinaryOp`.
- LLVM usa intrinsics checked para suma/resta/multiplicación, guards explícitas
  antes de división/remainder y opcodes ordinarios para operaciones ya probadas
  seguras. Este precedente impide delegar estados inválidos a poison o UB.
- compound assignment ya estabiliza destino con `CompoundLoad`/`CompoundCommit`
  y conserva un commit único sólo en el camino normal.

El `AstTypeKind` vigente no contiene unions y el parser de tipos no consume `|`.
Por tanto no hay hoy una unión de tipos implementada que preservar, pero el token
y la gramática deben mantenerse contextualmente separados para no impedir ni
reinterpretar esa superficie futura.

## 3. Matriz de tipos

### 3.1 Tipos nativos y representación

| Tipo | Signed | Ancho en target vigente | Admitido como valor bitwise | Admitido como count |
|---|---:|---:|---:|---:|
| `int8` | sí | 8 | sí | sí |
| `int16` | sí | 16 | sí | sí |
| `int32` | sí | 32 | sí | sí |
| `int64` / `int` | sí | 64 | sí | sí |
| `uint8` / `byte` | no | 8 | sí | sí |
| `uint16` | no | 16 | sí | sí |
| `uint32` | no | 32 | sí | sí |
| `uint64` | no | 64 | sí | sí |
| `isize` | sí | pointer width, hoy 64 | sí | sí |
| `usize` | no | pointer width, hoy 64 | sí | sí |

Aliases transparentes de cualquiera de ellos se admiten con el mismo `TypeId`
canónico y el mismo comportamiento. `bool`, `float32`, `float64`, `char`,
`string`, nullable, referencias, functions/closures, enums, structs, classes,
collections, views, vectors, matrices y demás aggregates se rechazan. No hay
conversión implícita entre entero y `bool` en ninguna dirección.

### 3.2 `&`, `|` y `^`

Se aplica exactamente el `common()` ordinario de enteros:

| Izquierdo | Derecho | Resultado |
|---|---|---|
| mismo tipo canónico | mismo tipo | ese tipo |
| mismo signo, fixed-width, uno ensancha sin pérdida al otro | distinto ancho | el más ancho |
| signed con unsigned | cualquiera | error |
| `isize`/`usize` con otro tipo distinto | cualquiera | error |
| entero con float/bool/char/string/aggregate | cualquiera | error |

No se agrega una promoción integral estilo C ni una conversión basada solamente
en el ancho físico. En particular, `int64 & isize`, `uint64 | usize` e
`int32 ^ uint32` son errores aunque los pares puedan compartir ancho. Esto
preserva identidades, evita reinterpretación de signo y no introduce narrowing.

Tras las conversiones ordinarias, ambos operandos y el resultado tienen el mismo
`TypeId`. Un literal a un lado adopta contextualmente el tipo del otro operando
si cabe. Dos literals usan el expected type entero cuando existe y `int64` en su
ausencia. Un literal fuera de rango es diagnóstico; nunca se trunca.

### 3.3 `~`

`~T -> T` exige un único entero nativo o alias transparente. No promociona el
operando y no acepta una expected type diferente como conversión de resultado.
Un literal puede adoptar contextualmente la expected type entera; sin contexto
es `int64`.

### 3.4 Shifts

`L << R` y `L >> R` tienen un contrato deliberadamente heterogéneo:

- `L` puede ser cualquiera de los diez enteros y fija ancho, signedness y
  `TypeId` del resultado;
- `R` puede ser cualquiera de los diez enteros, con cualquier ancho o signedness;
- no se busca un tipo común entre `L` y `R`;
- no existe conversión fuente implícita del count al tipo de `L` ni a `usize`;
- un literal count sin otro contexto conserva `int64`; su valor se valida contra
  el ancho de `L`;
- el backend puede normalizar internamente un count ya probado a la anchura LLVM
  requerida. Esa conversión es exacta porque `0 <= R < width(L)`, y no es una
  conversión observable del lenguaje.

Esto admite `int8_value << uint64_count` sin truncar el count antes de validarlo.
También hace observable y comprobable un count signed negativo, en vez de
reinterpretarlo como un unsigned enorme.

### 3.5 Diagnósticos y aliases

La decisión semántica se toma con tipos canónicos, pero un diagnóstico debe usar
el spelling fuente del operando cuando esté disponible, por ejemplo: “`Mask16`
(alias de `uint16`) no admite …”. Puede añadir “tipo canónico `uint16`”.

La infraestructura actual conserva aliases de declaración globalmente, pero un
`HirLocal` sólo conserva el `TypeId` canónico. La implementación deberá llevar
provenance de spelling hasta la resolución/diagnóstico del operador o emitir el
diagnóstico antes de descartarla. No se propone volver nominal un alias ni
insertarlo en MIR/SSA.

## 4. Semántica de AND, OR, XOR y NOT

Para un tipo de ancho `N`, sea `bits_N(x)` el único patrón de `N` bits que
representa `x`. Unsigned usa binario ordinario. Signed queda normativamente
definido como complemento a dos, con rango `[-2^(N-1), 2^(N-1)-1]`.

```text
bits_N(x & y) = bits_N(x) AND bits_N(y)
bits_N(x | y) = bits_N(x) OR  bits_N(y)
bits_N(x ^ y) = bits_N(x) XOR bits_N(y)
bits_N(~x)    = NOT(bits_N(x)) restringido a N bits
```

El resultado se interpreta de nuevo con la signedness del `TypeId` resultante.
No hay overflow, widening adicional, trap ni flags `nsw`/`nuw`. `~x` equivale
matemáticamente a `-x - 1` para signed en complemento a dos, pero debe
implementarse como complemento de patrón: no hereda overflow de negación/resta.

Ejemplos normativos:

| Expresión tipada | Patrón/result |
|---|---|
| `~uint8(0)` | `0xff`, `255` |
| `~int8(0)` | `0xff`, `-1` |
| `int8(-128) ^ int8(-1)` | `0x7f`, `127` |
| `int8(-1) & int8(1)` | `0x01`, `1` |

Const folding debe convertir cada constante al patrón unsigned de `N` bits,
aplicar la operación, enmascarar a `N` bits y reinterpretar signed si corresponde.
Debe producir exactamente el mismo resultado que O0 y O2. Una optimización puede
usar identidades algebraicas (`x & 0`, `x ^ x`, etc.) sólo si conserva la
evaluación y efectos de operandos: no puede eliminar una expresión observable.

Estos operadores son escalares concretos. V1 no agrega capabilities genéricas,
overloads, elementwise implícito ni una infraestructura algebraica nueva.

## 5. Semántica normativa de shifts

Sea `N = width(L)` y `k` el valor matemático de `R` antes de cualquier
normalización backend.

### 5.1 Validación del count

El orden obligatorio es:

1. evaluar `L` una vez;
2. evaluar `R` una vez;
3. si `R` es signed, comprobar `k >= 0`;
4. comprobar `k < N` en el dominio completo de `R`;
5. sólo en el bloque válido normalizar `k` de forma exacta y ejecutar el shift.

`k < 0` y `k >= N` hacen el mismo trap fuente `ShiftCountOutOfRange`, cuyo
diagnóstico debe incluir count y ancho cuando sean conocidos. Separar ambos
motivos en metadata diagnóstica es válido, pero no debe cambiar la clase pública
de fallo sin otro acuerdo.

Un count constante inválido es diagnóstico de compilación y no llega a MIR. Un
count dinámico conserva guard y trap bajo O0/O2. LLVM nunca recibe un shift con
count fuera de rango, por lo que no puede producir poison.

### 5.2 Shift derecho

- unsigned usa zero-fill y baja a LLVM `lshr`;
- signed replica el bit de signo y baja a LLVM `ashr`;
- los `k` bits bajos descartados no causan overflow;
- `x >> 0 == x`;
- para signed negativos el resultado es el floor de `x / 2^k`, por ejemplo
  `int8(-3) >> 1 == -2`.

No existe una forma implícita de shift derecho lógico sobre signed. Si se necesita,
el programa debe convertir explícitamente a un unsigned del mismo ancho y aceptar
el contrato checked de ese cast.

### 5.3 Shift izquierdo checked

El valor conceptual es `L * 2^k` con precisión no acotada. Si ese valor no cabe
en el rango de `type(L)`, la operación hace `IntegerOverflow`; de otro modo retorna
la representación exacta en el mismo tipo.

Las cotas de representabilidad se calculan **únicamente después** de que la
validación de 5.1 haya demostrado `0 <= k < N`. Un count inválido hace
`ShiftCountOutOfRange` sin evaluar cotas de overflow. Tanto folding como runtime
deben calcular las cotas mediante precisión ampliada o comparaciones/divisiones
que no puedan desbordar; la propia verificación no puede causar overflow del
host o del lenguaje, poison ni UB.

- unsigned: válido iff `L <= MAX >> k`;
- signed: válido iff `MIN >> k <= L <= MAX >> k`, usando shift aritmético en las
  cotas y sólo después de validar `k`;
- `k == 0` siempre preserva `L`;
- negativos signed son válidos cuando el producto cabe: `int8(-2) << 2 == -8`;
- `int8(64) << 1` y `int8(-65) << 1` hacen `IntegerOverflow`;
- ningún bit significativo se descarta silenciosamente.

Después de la prueba puede emitirse LLVM `shl` ordinario, sin `nsw`/`nuw`. La
guard es autoridad; el optimizer puede demostrarla y simplificarla, pero no
suponerla. El trap de count precede al de overflow porque la operación no tiene
valor matemático admitido con un count inválido. Esta prioridad se conserva
incluso si `L` sería no representable para un count válido cercano.

### 5.4 Alternativas comparadas

| Alternativa | Ventaja | Problema | Decisión |
|---|---|---|---|
| shift puramente binario, descarta bits | familiar en lenguajes de sistemas | contradice aritmética integer checked; oculta pérdida | descartar para `<<` operator |
| `<<` checked; `>>` definido por signo | coherente con `+`, `-`, `*`; no pierde bits a escondidas | requiere guards explícitas | **V1 aprobada** |
| operator wrapping + API checked | operator barato | invierte la expectativa actual de Aether | no para V1 |
| operator checked + APIs wrapping/checked | conserva default seguro y permite intención explícita futura | requiere otro diseño de API | compatible, fuera de V1 |

Una API futura puede distinguir `wrappingShl`, `checkedShl` o variantes
equivalentes, pero nombres, retorno y disponibilidad no quedan fijados aquí.

## 6. Precedencia y gramática

### 6.1 Tabla aprobada

De mayor a menor precedencia:

| Nivel | Operadores/formas | Asociatividad |
|---:|---|---|
| 1 | primary, call, member, subscript | postfix/izquierda |
| 2 | `!`, `~`, unary `-`, dereference `*`, borrow `&`, `&mut` | prefijo/derecha |
| 3 | `*`, `/`, `%` | izquierda |
| 4 | `+`, `-` | izquierda |
| 5 | `<<`, `>>` | izquierda |
| 6 | bitwise `&` | izquierda |
| 7 | bitwise `^` | izquierda |
| 8 | bitwise `|` | izquierda |
| 9 | `<`, `<=`, `>`, `>=` | izquierda, semánticamente no encadenable |
| 10 | `==`, `!=` | izquierda |
| 11 | range `a:b` / `a:s:b` | no asociativo (contrato vigente, sin cambios) |
| 12 | `&&` | izquierda y short-circuit |
| 13 | `||` | izquierda y short-circuit |

Así, `a + b << c` es `(a + b) << c`, `a & b == c` es
`(a & b) == c`, y `a | b && p` es `(a | b) && p`, que exige una comparación
explícita porque no hay conversión integer-to-bool. Bitwise se coloca por encima
de comparación/equality deliberadamente: evita el conocido parse sorprendente
de estilo C para `flags & MASK == 0` y favorece la lectura como test de máscara.
El range existente conserva expresamente su precedencia entre igualdad y lógica,
su asociatividad no asociativa y todas sus formas vigentes. BITWISE-OPERATORS-V1
no modifica su contrato. Cualquier revisión general de range será trabajo futuro
independiente.

El parser ordinario y el parser reducido de selectors deben compartir exactamente
estos niveles. La producción de range continúa tomando endpoints mediante el
nivel de igualdad vigente; los niveles bitwise se insertan por encima de
comparación e igualdad, sin reescribir la producción ni la asociatividad de range.

### 6.2 Tokens y conflictos

Maximal munch debe reconocer antes los tokens largos:

- `&&` antes de `&`, `||` antes de `|`;
- `<<` antes de `<`, `<=` según segundo carácter;
- `>>` antes de `>`, `>=` según segundo carácter;
- en un milestone futuro, `<<=`, `>>=`, `&=`, `|=`, `^=` deberán preceder sus
  prefijos. V1 no necesita aceptarlos como statements.

BITWISE-OPERATORS-V1 no agrega un token `**` ni modifica preventivamente su
tokenización actual: los dos `*` no reciben semántica accidental de potencia.
`^` es siempre XOR, nunca potencia. El token `**`, su gramática y `pow` se
incorporarán conjuntamente en `EXPONENTIATION-V1`. El lexer de este milestone se
limita a los seis operadores bitwise y a sus conflictos léxicos necesarios.

`&x` y `&mut x` siguen resolviéndose sólo en posición prefix; `a & b` sólo en el
nivel infix. `&&` nunca se descompone. El mismo principio separa `|` de `||`.

`>>` crea un conflicto real con cierres genéricos contiguos, por ejemplo
`Outer<Inner<int>>`. La decisión es un token léxico `GreaterGreater` que el
parser de expresiones interpreta como shift y que **sólo el parser de tipos**
puede consumir como dos cierres `>` con spans correctos. No se debe insertar
whitespace, cambiar el source text ni usar un lexer dependiente del symbol table.
El lookahead `generic_suffix_before_apply()` y el detector de declaraciones deben
entender esa partición contextual. `a >> b` fuera de tipo nunca se parte.

El token `Pipe` queda disponible en expresiones. `ty()` no debe consumirlo salvo
que una gramática de unions autorizada lo haga en su propio nivel. En HEAD no hay
tal gramática, de modo que `A | B` en posición de tipo continúa siendo error.

### 6.3 Casos adversariales obligatorios

```text
&x & y                 // (&x) & y; luego typing probablemente rechaza ref
&mut x                 // borrow mutable, no AND
a&&b, a&b, a & &b      // tres tokenizaciones/AST distintos
a||b, a|b, a | |b      // lógico, bitwise, segundo Pipe inválido como prefix
~x == y                // (~x) == y
a + b << c & d ^ e | f // ((((a+b)<<c)&d)^e)|f
a << b < c             // (a << b) < c
a & b == c             // (a & b) == c
a == b & c             // a == (b & c)
a >> b >> c            // (a >> b) >> c
Outer<Inner<int>>       // dos cierres de tipo
f<Outer<Inner<int>>>()  // cierres y apply genérico
f<int>(x) >> 1         // cierre genérico seguido por shift
a > > b                // dos `>`, no shift
a ** b                 // sin token/semántica nueva en V1; nunca potencia aquí
a ^= b; a **= b;       // no admitidos en V1
```

## 7. Modelo HIR, MIR, SSA y LLVM

### 7.1 AST/HIR

AST necesita variantes explícitas `BitwiseNot`, `BitwiseAnd`, `BitwiseOr`,
`BitwiseXor`, `ShiftLeft`, `ShiftRight`; no debe representar `~` como aritmética
ni `^` como power.

HIR normativo:

```text
HirUnaryOp::BitwiseNot
HirBinaryOp::{BitwiseAnd, BitwiseOr, BitwiseXor}
HirBinaryOp::{ShiftLeftChecked, ShiftRightArithmetic, ShiftRightLogical}
```

La selección arithmetic/logical ocurre en HIR usando signedness del operando
izquierdo; no se deja al backend. `ShiftLeftChecked` usa
`ShiftCountOutOfRange` y, tras count válido, `IntegerOverflow`. Los bitwise
ordinarios no tienen trap.

El verificador HIR reconstruye independientemente:

- integer nativo para cada operando aplicable;
- igualdad exacta de operand/result en AND/OR/XOR;
- operand/result exacto en NOT;
- result igual al izquierdo para shifts;
- opcode derecho consistente con signedness izquierda;
- count entero independiente;
- ninguna coerción narrowing o signedness escondida.

### 7.2 MIR/SSA

Las operaciones AND/OR/XOR caben en el `BinaryOp` homogéneo actual y NOT en
`UnaryOp`. Los shifts demuestran una necesidad concreta de extender el contrato:
izquierdo y count pueden tener tipos distintos. No se debe falsear homogeneidad
insertando una coerción fuente.

La extensión mínima aprobada es que el contrato de las variantes shift
valide por separado `left_type`, `count_type` y `result_type`, manteniendo el
`Rvalue::Binary`/`SsaOp::Binary` existente si sus verificadores dejan de exigir
igualdad sólo para esos opcodes. Una estructura genérica nueva de operaciones
heterogéneas no está justificada.

MIR y SSA conservan dos traps ordenados para shift izquierdo:

```text
primary_trap   = ShiftCountOutOfRange
secondary_trap = IntegerOverflow
```

Para shift derecho sólo existe el primero. Si la representación actual de dos
traps presupone división, debe generalizarse únicamente el contrato de trap del
opcode, no crear un pseudo-divide. Los verificadores deben rechazar count no
entero, result alterado, opcode signedness incorrecto, trap ausente/cambiado,
operandos intercambiados y normalización count antes de la guard.

El orden de evaluación izquierda-derecha se conserva en lowering. Las guards y
traps son efectos y no pueden moverse antes de efectos de los operandos ni después
de un uso del resultado.

### 7.3 Const folding

HIR pliega únicamente cuando todos los valores requeridos son constantes:

- AND/OR/XOR/NOT mediante patrón de ancho `N`;
- count inválido como diagnóstico `ShiftCountOutOfRange`;
- left shift no representable como diagnóstico `IntegerOverflow`;
- right shift con la misma regla signed/unsigned runtime.

MIR/SSA y LLVM no deben recibir un valor plegado que el verificador no pudiera
aceptar como operación original. Las pruebas comparan resultado/trap contractual,
no sólo el IR textual generado.

### 7.4 LLVM

Mapping final:

| Operación verificada | LLVM |
|---|---|
| AND | `and iN` |
| OR | `or iN` |
| XOR | `xor iN` |
| NOT | `xor iN value, -1` |
| left shift válido y sin overflow | `shl iN` sin flags |
| right shift signed | `ashr iN` |
| right shift unsigned | `lshr iN` |

Para shifts dinámicos, primero se compara el count en su propio ancho y
signedness. Sólo el successor válido lo extiende o trunca exactamente a `iN`.
El `shl` se emite después de la prueba de representabilidad. No se emiten
`nsw`, `nuw`, `exact`, masked counts, `% width`, casts previos a la guard ni
`freeze` para ocultar poison. O0 y O2 deben tener el mismo resultado o trap.

## 8. Asignaciones compuestas futuras

`&=`, `|=` y `^=` pueden reutilizar directamente la transacción existente:

1. estabilizar destino y ejecutar `CompoundLoad`;
2. evaluar RHS una vez;
3. aplicar el opcode homogéneo sin trap propio;
4. `CompoundCommit` único en camino normal.

`<<=` y `>>=` también pueden reutilizar load/commit, pero requieren además:

- destino integer y resultado exactamente del tipo destino;
- count integer independiente, no necesariamente del tipo destino;
- guard `0 <= count < width(destination)` después del RHS;
- en `<<=`, guard de overflow antes del commit;
- ausencia de commit en cualquiera de esos traps;
- preservation de la ubicación estabilizada durante todas las guards.

No hace falta una transacción nueva. Sí hace falta que la metadata de compound
admita un RHS con tipo diferente del destination para shifts. Ninguna de estas
formas se implementa en V1 y `**=` no se reserva como operación admitida.

## 9. Qualification requerida para V1

### 9.1 Lexer/parser

- maximal munch y spans para todos los pares/largos conflictivos;
- tabla completa de precedencia y asociatividad, incluidos range y selectors;
- borrow `&`/`&mut`, `&&`, `||`, `!` sin regresión;
- nested generics con `>>`, generic call seguido por shift y `> >` separado;
- tokenización vigente de `**` sin semántica accidental; no se agrega el token;
  `^` nunca es power;
- rechazo de forms compound fuera de milestone;
- no aceptación accidental de union types mediante `|`.

### 9.2 Tipos y constantes

- cada operador sobre los diez tipos, alias transparente y literals contextuales;
- cada widening ordinario admitido y todos los cruces de signedness, sized/fixed
  y narrowing rechazados;
- bool, ambos floats, char, string, ref, nullable y aggregates rechazados;
- cero, all-ones, sign bit, mínimos/máximos y negativos;
- aliases visibles en diagnósticos sin cambiar `TypeId` canónico;
- folding de patrón comparado contra ejecución runtime.

### 9.3 Shifts

- counts `-1`, `0`, `1`, `N-1`, `N`, `N+1` y máximos de cada tipo count;
- cada tipo izquierdo cruzado con counts signed/unsigned más estrechos, iguales
  y más anchos;
- right signed negativo prueba sign extension; unsigned prueba zero-fill;
- left shift válido en límites y overflow positivo/negativo/unsigned;
- signed `MIN`/`MAX`, unsigned `MAX`, counts `0` y `N-1`, y vecinos exactos de
  cada frontera representable;
- prioridad `ShiftCountOutOfRange` sobre `IntegerOverflow`, incluidos casos donde
  `L` es `MIN`/`MAX` y el count es `-1`, `N` o el máximo de su tipo;
- cálculo de cotas que no causa overflow, poison ni UB;
- prueba LLVM que demuestra guard antes de `shl`/`ashr`/`lshr`;
- ejecución nativa O0/O2 y differential oficial con resultado/trap idéntico.

### 9.4 Verificadores y regresión

- corrupciones HIR, MIR y SSA independientes para opcode, operand types, result,
  signedness, traps y orden;
- comparación/lógica, ranges, selectors, generics, aliases y compound assignment;
- suites completas de `compiler-next`, `cargo check`, fmt, clippy y
  `git diff --check`;
- differential oficial, no un oracle LLVM accidental.

La qualification global debe registrar por separado la excepción preexistente
del registry: `linear_algebra_oal_publishes_and_runs_real_qr_consumer` puede
quedar colgado. Un timeout allí no se declara PASS ni regresión bitwise sin
evidencia diferencial contra la base. No se cambia, deshabilita ni omite para
obtener verde.

## 10. Criterios de aceptación

BITWISE-OPERATORS-V1 sólo puede cerrarse cuando:

1. la implementación respete las decisiones aprobadas sobre tipo de count,
   count inválido, `<<` checked, naturaleza signed de `>>` y precedencia;
2. todos los operadores estén tipados y verificados en cada capa;
3. ningún shift inválido alcance LLVM;
4. O0, O2, folding y differential coincidan con este contrato;
5. no exista conversión implícita a bool, narrowing ni reinterpretación silenciosa;
6. borrow, lógica, genéricos, gramática de tipos y compound vigentes no regresen;
7. los tests de corrupción fallen cerrados;
8. cualquier excepción global se documente con baseline y no se presente como
   éxito del milestone.

## 11. Plan de implementación acotado

1. Agregar tokens y tests léxicos, incluida partición contextual de `>>` en tipos.
2. Agregar niveles parser y AST con tests adversariales.
3. Implementar resolución escalar HIR, literals, alias-aware diagnostics y folding.
4. Agregar opcodes/verificación HIR.
5. Extender mínimamente MIR/SSA para opcodes y shifts heterogéneos con traps.
6. Emitir guards LLVM y opcodes sin flags; inspeccionar O0/O2.
7. Agregar tests focales, corrupción, native y differential.
8. Ejecutar qualification completa y producir el report V1.

No se incluyen power/`pow`, capabilities genéricas bitwise, vectorización,
compound bitwise, APIs wrapping/checked, nuevos targets ni unions de tipos.

## 12. Cierre de decisiones

| Cuestión | Decisión normativa | Estado |
|---|---|---|
| tipos de count | cualquiera de los diez enteros | **aprobado** |
| count inválido | trap único `ShiftCountOutOfRange` | **aprobado** |
| `<<` | checked para signed y unsigned | **aprobado** |
| `>>` signed | aritmético | **aprobado** |
| precedencia | bitwise sobre comparación/igualdad; range sin cambios | **aprobado** |
| operaciones binarias bitwise no-shift | conversiones ordinarias y luego homogéneas | **aprobado** |
| representación signed | complemento a dos | **aprobado** |
| `>>` en tipos | partición contextual para genéricos anidados | **aprobado** |
| IR | reutilización de infraestructura existente cuando sea posible | **aprobado** |

No quedan decisiones de BITWISE-OPERATORS-ARCH-1 pendientes de aprobación. El
milestone arquitectónico queda `CLOSED`; BITWISE-OPERATORS-V1 permanece sin
iniciar y sujeto a sus propios criterios de implementación y qualification.
