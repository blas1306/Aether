# NUMERIC-PARSING-ARCH-1 — parsing numérico checked desde texto

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-21.

Este milestone define la primera superficie pública para convertir un `string`
completo a `int` o `double`. No modifica lexer, parser, AST, HIR, MIR, SSA,
backend, runtime, tests ni los programas actualmente admitidos. La implementación
y qualification pertenecen a **NUMERIC-PARSING-V1**.

La motivación inmediata es la auditoría de
[expense_tracker](EXPENSE_TRACKER_NEXT_PORT_REPORT.md): CLI, archivos de texto,
configuración, formatos persistentes e input interactivo necesitan distinguir un
número válido de syntax inválida y de un valor fuera de rango. El dato inválido
es ordinario en esas fronteras y no debe convertirse en trap, exception, sentinel
ni cero silencioso.

Esta decisión compone con
[TEXT-BYTE-ACCESS-ARCH-1](TEXT_BYTE_ACCESS_ARCH_1.md), que ya permite recorrer
bytes ASCII sobre un `string` UTF-8 válido, y con
[FORMAT-ARCH-1](FORMAT_ARCH_1.md)/[FORMAT-V1](FORMAT_V1_REPORT.md), que fijan
`str(int)` y `str(double)`.

## 1. Decisión resumida

`std.Text` agrega conceptualmente esta API normativa:

```aether
enum std.Text.IntParseResult {
    Value(int),
    Invalid,
    Overflow
}

enum std.Text.DoubleParseResult {
    Value(double),
    Invalid,
    Overflow,
    Underflow
}

std.Text.IntParseResult std.Text.parseInt(ref string value);
std.Text.DoubleParseResult std.Text.parseDouble(ref string value);
```

Los nombres, payloads, firma borrowed e identidades dentro de `std.Text` son
parte del contrato. `int` y `double` son sus aliases transparentes canónicos
actuales, respectivamente `int64` y `float64`; no hay selección contextual de
otro ancho.

- Ambos parsers consumen el string completo, no recortan whitespace y sólo
  reconocen bytes ASCII de su gramática.
- `parseInt` acepta exactamente `[+-]?[0-9]+` y distingue un entero fuera de
  `int64` mediante `Overflow`.
- `parseDouble` acepta decimal ordinario con punto opcional y exponente decimal
  opcional. Convierte a IEEE-754 binary64 con rounding nearest, ties-to-even.
- `parseDouble` distingue overflow a infinity y underflow de un valor decimal
  matemáticamente no nulo a signed zero. Un resultado subnormal distinto de
  cero es `Value`.
- Ningún fallo de parsing usa exception, trap, `errno`, `null`, NaN ni un valor
  numérico sentinel. Los fallos de recursos o invariantes globales conservan el
  modelo de traps existente.
- No se agrega `Result<T,E>`, `parse<T>`, typeclass, capability de parsing,
  radix configurable ni parsing parcial.

## 2. Alcance y autoridad

La operación transforma texto y vive junto a `byteAt`, `trim`, `split` y el
resto de algoritmos sobre string en `std.Text`. No pertenece a `std.Math`: Math
opera sobre valores numéricos ya construidos y no debe adquirir dependencias de
UTF-8, grammar o locale. Tampoco pertenece a Core/prelude: los programas deben
declarar `import std.Text;` y usar `std.Text.parseInt`/`parseDouble`, o un alias de
ese package.

Quedan fuera:

- otros anchos signed/unsigned, `usize`, `float32` y números complejos;
- base 2/8/16, prefijos, separators y suffixes de tipo;
- whitespace, Unicode digits/signs y reglas dependientes de locale;
- NaN/infinities textuales y NaN payloads;
- parsing incremental, prefijos válidos, offset final o diagnostics detallados;
- generic `Result`, generic `parse<T>`, protocols o conversiones user-defined;
- formatting, validación de schemas y policy de recuperación del caller.

Una API futura para otro tipo debe tener su propio milestone. No puede cambiar
la grammar ni la clasificación de estas dos funciones.

## 3. Contrato común de scanning

El input es un `string` owning válido prestado como `ref string`. La operación
no retiene el borrow, no modifica el string, no crea substring y no asigna en
los casos ordinarios. Una literal o owner puede usar la adaptación borrowed ya
calificada por BORROW-ERGONOMICS-V1.

El scanner trabaja sobre los bytes UTF-8 del string. Como todos los tokens
admitidos están en ASCII, cualquier byte `>= 0x80` es inválido sin necesidad de
decodificar su scalar. Las categorías son pruebas explícitas por valor de byte:

```text
digit := byte >= 0x30 && byte <= 0x39
plus  := byte == 0x2b
minus := byte == 0x2d
dot   := byte == 0x2e
e/E   := byte == 0x65 || byte == 0x45
```

No se llama `isspace`, `isdigit`, `strto*`, un parser Unicode ni otra operación
afectada por locale. U+0000 es simplemente un byte que no pertenece a ninguna
grammar, incluso si una biblioteca host lo trataría como terminador.

Ambas funciones deben inspeccionar la entrada completa antes de publicar la
clasificación. `Invalid` tiene precedencia sobre `Overflow` y `Underflow`: esos
dos estados significan siempre que el string sí pertenece a la grammar pero su
valor no produce un valor admitido. Por ejemplo, una secuencia enorme de dígitos
seguida por `x` es `Invalid`, no `Overflow`.

No existe success parcial. Un prefijo válido seguido por cualquier byte, incluso
whitespace o U+0000, invalida el string entero. La longitud se obtiene de la
representación length-aware; nunca de `strlen`.

## 4. Grammar y semántica de `parseInt`

### 4.1 Grammar normativa

La grammar es exactamente:

```ebnf
intText = [ sign ], digit, { digit } ;
sign    = "+" | "-" ;
digit   = "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" ;
```

Equivale a la expresión ASCII `[+-]?[0-9]+`, anclada en ambos extremos. No es
la grammar de literals source: no hay underscores, radix, suffix ni folding de
unary minus.

| Texto | Resultado |
|---|---|
| `"0"` | `Value(0)` |
| `"42"` | `Value(42)` |
| `"-42"` | `Value(-42)` |
| `"+42"` | `Value(42)` |
| `"0012"` | `Value(12)` |
| `"-0"` | `Value(0)` |
| `"9223372036854775807"` | `Value(int64.max)` |
| `"-9223372036854775808"` | `Value(int64.min)` |
| `"9223372036854775808"` | `Overflow` |
| `"-9223372036854775809"` | `Overflow` |

Son `Invalid`: `""`, `"+"`, `"-"`, `" 42"`, `"42 "`, `"12abc"`,
`"1_000"`, `"0x10"`, `"1.0"`, `"１２"` y `"−5"`. Leading zeros son
válidos porque no crean ambigüedad de base ni cambian el valor. Un signo `+` es
válido para simetría con datos humanos y con el exponente decimal; `str(int)` no
lo emite.

### 4.2 Rango y algoritmo checked

El dominio de éxito es exactamente
`[-9223372036854775808, 9223372036854775807]`. La implementation no puede
construir primero un entero host potencialmente overflowing, negar `int64.min`,
usar wrapping ni depender de undefined behavior.

Un algoritmo conforme puede acumular una magnitud unsigned con un límite elegido
por el signo:

```text
positive limit = 9223372036854775807
negative limit = 9223372036854775808

before magnitude = magnitude * 10 + digit:
    overflow iff magnitude > (limit - digit) / 10
```

Tras detectar overflow continúa validando que todos los bytes restantes sean
dígitos, sin volver a actualizar la magnitud. Al final, si la syntax completa es
válida, retorna `Overflow`; en otro caso retorna `Invalid`. Para el límite
negativo construye `int64.min` sin convertir primero `9223372036854775808` a
`int64` positivo ni aplicarle negación signed.

Éste es un esquema demostrativo, no una obligación de usar una instrucción
concreta. Cualquier implementación debe demostrar las mismas propiedades en
todas las capas y targets admitidos.

## 5. Grammar de `parseDouble`

### 5.1 Producciones normativas

La grammar decimal es:

```ebnf
doubleText = [ sign ], significand, [ exponent ] ;
sign        = "+" | "-" ;
significand = digits, [ ".", [ digits ] ]
            | ".", digits ;
exponent    = ( "e" | "E" ), [ sign ], digits ;
digits      = digit, { digit } ;
digit       = "0" | "1" | "2" | "3" | "4"
            | "5" | "6" | "7" | "8" | "9" ;
```

Debe existir al menos un dígito en el significando total. Si aparece `e`/`E`,
debe seguirle al menos un dígito después de su signo opcional. El punto sólo
puede aparecer una vez y siempre antes del exponente.

Son válidos:

```text
0        1.0       .5        0.5       5.
-1.25    +1.25     1e3       1E3       1.2e-3
-0.0     001.2500  .5E+2     5.e0
```

Son inválidos:

```text
""       +         -         .          +.
e3       1e        1e+       1e-        1.2.3
" 1.0"   "1.0 "    "1.0\n"   1_000      0x1p0
NaN      nan       Inf        inf        Infinity  -inf
１２     −5        1,5
```

Las comillas de esa tabla sólo hacen visibles los tres casos con whitespace; no
son parte del input. No hay trimming implícito. Los ceros iniciales/finales y
`5.` se admiten porque son decimal inequívoco y permiten consumir formatos
humanos comunes. Hex float queda fuera de V1.

### 5.2 Valor matemático

Después del signo, sea `C` el entero no negativo formado al concatenar todos los
dígitos antes y después del punto, `F` la cantidad de dígitos posteriores al
punto y `E` el exponente signed explícito o cero. El valor decimal exacto es:

```text
(-1 si hay '-' else +1) * C * 10^(E - F)
```

Esta definición no exige materializar `C`, `E` ni `E-F` en un entero bounded.
El scanner debe manejar una cantidad arbitraria de dígitos de input sin overflow
interno: puede saturar metadata de exponente una vez que el rango ya determina
el resultado, y debe conservar suficiente prefijo/sticky information para un
rounding correcto en casos limítrofes.

Si `C == 0`, el resultado es cero aun con un exponente de cualquier magnitud.
El signo se conserva: cualquier texto gramaticalmente válido con signo `-` y
significando cero retorna `Value(-0.0)`, incluidos `"-0"`, `"-0e9999"` y
`"-000.000e-9999"`. Esto no es underflow porque el valor matemático no es
distinto de cero.

## 6. Conversión IEEE-754 y resultados de rango

### 6.1 Rounding

Un decimal finito y sintácticamente válido se convierte directamente a
IEEE-754 binary64 usando round-to-nearest, ties-to-even. El resultado no depende
del rounding mode ambiental. La implementación debe comportarse como si hubiera
comparado el valor decimal exacto con los dos binary64 adyacentes, aunque puede
usar un algoritmo más eficiente.

No se permite parsear primero a binary32, `long double` host u otro formato y
convertir después. Tampoco se acepta un algoritmo approximate sin fallback
correcto para halfway cases.

### 6.2 Clasificación total

Tras validar la grammar completa:

| Conversión correctamente redondeada | Resultado |
|---|---|
| binary64 finito normal | `Value(value)` |
| binary64 finito subnormal distinto de cero | `Value(value)` |
| cero cuando el decimal exacto es cero | `Value(+0.0)` o `Value(-0.0)` |
| infinity desde un decimal finito fuera del rango redondeable | `Overflow` |
| cero cuando el decimal exacto era no nulo | `Underflow` |

Así, `"1e9999"` es `Overflow` y `"1e-9999"` es `Underflow`.
`"5e-324"`, el decimal shortest del mínimo subnormal, retorna ese subnormal en
`Value`. Un decimal no nulo menor puede aún redondear al mínimo subnormal; sólo
es `Underflow` si el resultado redondeado es cero.

El umbral de overflow también se decide por rounding correcto. Un decimal mayor
que `double.max` puede redondear todavía al máximo finito y ser `Value`; se usa
`Overflow` sólo si el resultado binary64 sería infinity. No se retorna
`Value(Inf)` y no se satura silenciosamente a `double.max`.

`Underflow` no lleva un payload cero. Es un fallo de conversión checked, no un
valor exitoso aproximado. El caller que conscientemente quiera saturar puede
elegir `0.0` al hacer match, pero no puede confundir esa policy con la
conversión canónica. El signo del cero hipotético no es observable dentro de la
variante sin payload.

### 6.3 NaN e infinities

`NaN`, `Inf`, `Infinity`, variaciones de casing y formas signed son `Invalid`.
Son spellings de formatting, no decimal ordinario, y aceptar algunos abriría una
segunda grammar de tokens especiales y questions sobre NaN payload/sign.

FORMAT-V1 emite exactamente `NaN`, `Inf` y `-Inf`; por ello el round-trip con
`str(double)` se promete sólo para valores finitos. Esta excepción es explícita
y deliberada. Una API futura para valores IEEE especiales puede ampliar o
separar la policy, pero no reinterpretar silenciosamente `parseDouble` V1.

## 7. Round-trip canónico

Para todo valor `x : int`:

```text
std.Text.parseInt(str(x)) == IntParseResult.Value(x)
```

La igualdad de arriba describe la variante y payload; no requiere igualdad
general nueva para enums con payload.

Para todo `x : double` finito, incluidos ambos ceros y todos los subnormales:

```text
std.Text.parseDouble(str(x)) == DoubleParseResult.Value(x)
```

En este contrato “igual” significa el mismo patrón IEEE-754 binary64. El
formatter shortest-round-trip ya selecciona un decimal que recupera esos bits,
y el parser fija el rounding correspondiente. `str(-0.0)` produce `"-0"`, cuya
grammar preserva el signo.

No se promete `parseDouble(str(x))` para NaN o infinities: sus strings canónicos
son inválidos por la sección 6.3. Tampoco se promete recuperar exactamente un
`float32` ensanchado mediante `parseDouble(str(valueFloat32))`; el formatter de
binary32 garantiza round-trip al mismo tipo y V1 todavía no define
`parseFloat`.

## 8. Resultados nominales y modelo de errores

`IntParseResult` y `DoubleParseResult` son enums nominales independientes. Sus
variantes `Value` contienen un scalar Copy; los enums completos son Copy, no
asignan y no necesitan Drop. Un caller debe resolver exhaustivamente la variante
antes de obtener el payload.

La separación de estados es observable y cerrada:

| Situación | Resultado/control |
|---|---|
| string fuera de la grammar | `Invalid` |
| entero gramatical fuera de int64 | `IntParseResult.Overflow` |
| decimal que redondea a infinity | `DoubleParseResult.Overflow` |
| decimal no nulo que redondea a cero | `DoubleParseResult.Underflow` |
| valor normal/subnormal/cero admitido | `Value(payload)` |
| OOM o tamaño interno no representable | trap global existente |
| string/runtime corrupto | invariant trap existente |
| HIR/MIR/SSA corrupto | verifier rejection |

Input inválido o fuera de rango no puede lanzar una language exception ni
producir un trap. No hay `errno` que leer/restaurar y no se captura un trap de
una conversión unchecked. La primitive privada debe retornar el estado checked
directamente.

Los nombres `Invalid`, `Overflow` y `Underflow` son deliberadamente compactos
porque ya están calificados por el tipo del enum. No se agrega una posición de
error: el caso base sólo necesita decisión, y offsets byte/scalar introducirían
una policy nueva. Un parser de diagnóstico puede construirse después sin cambiar
esta API.

## 9. Complejidad, límites y recursos

Sea `N = byteLength(value)`. Ambos parsers cuestan O(N), leen cada byte una
cantidad acotada de veces y no realizan rescans desde el inicio, substring,
`trim`, concatenación ni conversiones temporales a string.

`parseInt` usa O(1) estado. `parseDouble` también debe usar workspace bounded
independiente de `N` en el runtime bootstrap: guarda sólo los dígitos
significativos necesarios para decidir binary64, cantidad/posición decimal
saturada y un sticky bit para el resto. La elección de ese bound pertenece al
algoritmo privado y debe estar demostrada, no adivinada.

Una implementación puede usar Eisel-Lemire, fast_float, Ryu parse u otro método
correcto con fallback exacto. El nombre no forma parte del contrato. Si se
incorpora código de terceros, debe quedar versionado con la toolchain y detrás
de una primitive Aether; el comportamiento de una libc o de la versión instalada
en el host no puede convertirse en semántica source.

Inputs con millones de ceros, exponentes de millones de dígitos o significandos
muy largos siguen siendo O(N), no desbordan contadores y no provocan allocation
proporcional. Después de que magnitud/exponente estén saturados, el scanner aún
valida todos los bytes para respetar la precedencia de `Invalid`.

## 10. Frontera STD/runtime y lowering

La superficie source pertenece a `std.Text`, pero el bootstrap declaration-only
puede representarla inicialmente mediante dos variantes adicionales de la
familia `TextOp`:

```text
ParseInt    { value: ref string } -> std.Text.IntParseResult
ParseDouble { value: ref string } -> std.Text.DoubleParseResult
```

Eso no crea syntax, members de `string`, calls Core ni acceso sin import. La
identidad canónica sigue siendo la función STD; una stdlib futura con bodies
Aether puede reemplazar el puente sin cambio source.

- Resolución exige `import std.Text`, arity uno, cero type arguments y argumento
  adaptable a `ref string` bajo las reglas existentes.
- HIR conserva el `CallSiteId`, borrow y tipo nominal exacto. El verifier no
  acepta intercambiar ambos enums aunque sus layouts pudieran parecerse.
- MIR evalúa/adapta el argumento una vez y materializa un enum Copy sin owner ni
  exceptional successor.
- SSA conserva la operación checked; optimización no puede sustituir un parser
  locale-independent por `atoi`, `strtoll` o `strtod`, ni borrar estados.
- LLVM llama/emite helpers privados length-aware. El status/tag se construye
  sólo después de validar todo el input y el payload existe sólo para `Value`.

Las primitives privadas pueden devolver un pequeño status más payload out-param
o un aggregate interno. Esa ABI no es pública. No deben exponer punteros al
backing, depender de NUL, leer fuera de bounds ni publicar un valor antes de
terminar la clasificación.

El código/helper se emite sólo si la operación correspondiente es reachable.
Un programa que usa otras APIs de Text no enlaza parsing decimal por ese hecho.
La implementación de int no debe arrastrar el motor de double y viceversa.

## 11. Qualification de NUMERIC-PARSING-V1

La implementación debe probar source→native en O0 y O2, con bytes y tags exactos.

### 11.1 Enteros

- cero, `-0`, signo positivo, leading zeros y valores ordinarios;
- `int64.min`, `int64.max` y ambos vecinos fuera de rango;
- overflow temprano seguido por miles de dígitos válidos;
- overflow aparente seguido por byte inválido, que debe ser `Invalid`;
- empty/sign-only, whitespace en ambos extremos, suffix/prefix, decimal point,
  underscores, NUL embebido, ASCII no dígito, Unicode digit y Unicode minus;
- property tests contra aritmética exacta para todo el borde y corpus aleatorio;
- `parseInt(str(x))` para bordes y corpus, y preferentemente cobertura amplia.

### 11.2 Doubles

- cada producción: integer-only, punto con ambos lados, `.digits`, `digits.`,
  ambos signos, `e`/`E` y signo de exponente;
- cada ausencia obligatoria de dígito, punto/exponente repetido, trailing bytes,
  whitespace, comma, underscore, hex, NUL y no-ASCII;
- `NaN`, `Inf`, `Infinity`, casings y formas signed rechazados;
- ambos ceros desde múltiples spellings, verificando bit de signo;
- mínimo/máximo normal, mínimo/máximo subnormal, vecinos y halfway ties;
- decimales que redondean a `double.max` frente a infinity;
- decimales no nulos que redondean a mínimo subnormal frente a signed zero;
- `1e9999`, `1e-9999`, exponentes con miles de dígitos y cero con exponente
  extremo;
- corpus de casos difíciles de conversión decimal y oracle exacto independiente;
- `parseDouble(str(x))` bit-exacto para ceros, normales, subnormales, extremos y
  un corpus representativo; NaN/Inf verifican la excepción documentada.

### 11.3 Capas, módulos y regresión

- resolución sólo con import, alias de package, arity/type/type-argument errors;
- resultados nominales no intercambiables y match exhaustivo de cada variante;
- enum Copy y borrow de literal/lvalue/temporary sin retain, owner ni Drop extra;
- corrupción independiente de operand/result/op/status en HIR, MIR y SSA;
- reachability separada de helpers int/double y ausencia si no se usan;
- ejecución bajo locales distintos y rounding modes ambientales distintos;
- instrumentación de avance O(N), workspace bounded y ausencia de temporales;
- suites workspace, fmt, clippy, differential y `git diff --check`.

La comparación con un parser host sólo puede servir como oracle auxiliar para
casos donde sus reglas coincidan; no sustituye tests de grammar, clasificación
ni bit pattern definidos aquí.

## 12. Alternativas evaluadas

| Alternativa | Decisión |
|---|---|
| Core/prelude | rechazada: parsing es una capacidad textual explícita, no una conversión universal |
| `std.Math` | rechazada: grammar, UTF-8 y locale pertenecen a la frontera de texto |
| `parse<T>` generic/typeclass | diferida: ampliaría inference, constraints y error type sin necesidad para dos tipos |
| `Result<T,E>` universal | rechazada para este milestone: obligaría a diseñar una abstracción transversal por un caso cerrado |
| nullable o sentinel | rechazada: pierde Invalid/range y colisiona con cero/NaN |
| exception por input inválido | rechazada: el fallo es dato local esperado y el match forma parte del protocolo normal |
| trap por input inválido | rechazada: CLI/archivo/config no son programmer errors |
| `tryParse(value, out result)` | rechazada: boolean pierde motivo, agrega out mutation y estado parcialmente inicializado |
| whitespace implícito | rechazada: oculta bytes y mezcla parsing con policy; el caller puede usar `trim` explícitamente |
| locale/comma/Unicode digits | rechazada: hace no determinista la persistencia y amplía mucho la grammar |
| parsing parcial con offset | diferida: requiere contrato de cursor y diagnóstico distinto; V1 consume todo |
| NaN/Inf aceptados | rechazada en V1: no son decimal ordinario y abren policy de payload/casing; se documenta la excepción a round-trip |
| underflow como `Value(0)` | rechazada: impediría distinguir cero exacto de pérdida total de magnitud |
| todo underflow IEEE como error | rechazada: un subnormal no cero es un valor binary64 representable |
| `strtod`/`errno` | rechazada: locale, NUL, globals, grammar y disponibilidad del host no son contrato Aether |
| reusable big integer público | rechazada: no hace falta exponer una abstracción numérica para implementar conversión privada |

## 13. Consecuencias y frontera futura

CLI, archivos, persistencia, configuración e input interactivo pueden ahora
diseñarse sobre un único contrato determinista: el caller decide explícitamente
qué hacer ante syntax inválida y cada clase de rango. El mismo texto produce el
mismo tag y bits en todo target admitido, sin locale ni estado global.

La superficie agrega dos funciones y dos enums Copy. No agrega syntax, generic
error handling, formatter, cursor, allocation ni excepción. `parseInt` fija
int64 y `parseDouble` fija binary64; APIs para otros tipos pueden seguir el mismo
patrón nominal o motivar una abstracción común en un milestone posterior, con
evidencia de más de un caso y sin alterar este contrato.
