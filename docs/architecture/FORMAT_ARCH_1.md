# FORMAT-ARCH-1 — numeric formatting and interpolation

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-14.

Este milestone fija la primera frontera de conversión escalar a `string`,
formatting numérico explícito, interpolación y composición con output. No
modifica todavía lexer, parser, resolver, HIR, MIR, SSA, backend, Core, standard
library ni runtime. Ninguna sintaxis o API descrita aquí está admitida hasta un
vertical nativo posterior y calificado.

La decisión usa el Core/prelude cerrado de
[MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md) y
[CORE-V1](CORE_V1_REPORT.md), el valor `string` de
[GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md), su lifecycle calificado en
[GENERAL-V1](GENERAL_V1_STRING_REPORT.md), la frontera algorítmica de
[TEXT-ARCH-1](TEXT_ARCH_1.md) y el output de
[IO-ARCH-1](IO_ARCH_1.md)/[IO-V1](IO_V1_REPORT.md). Respeta la evaluación
izquierda→derecha, los traps fail-fast y las fronteras tipadas del charter,
contrato semántico y arquitectura del compiler.

No introduce un método universal `toString`, una interfaz `Stringifiable`,
reflection, inspección dinámica de tipos ni dispatch runtime de formatting.

## 1. Decisiones resumidas

- Core/prelude agrega una familia cerrada `str(value) -> string` para los
  escalares primitivos. No es un cast, constructor de `string`, función generic
  ni protocolo extensible por usuario.
- Cada `str` produce un owner string fresh con contenido canónico, determinista
  y sin dependencia del locale, rounding mode o formatter del host.
- Enteros usan decimal ASCII; `bool` usa `true`/`false`; `char` produce el UTF-8
  de exactamente un Unicode scalar value.
- `float32` y `float64` usan una representación decimal shortest-round-trip de
  su tipo original. La política observable queda fijada, pero no un algoritmo
  concreto como Ryu, Schubfach o Dragonbox.
- La notación float usa `.` y `e`, elimina ceros no significativos, preserva
  signed zero y escribe `NaN`, `Inf` y `-Inf`. Payload y signo de NaN no se
  textualizan.
- `std.Format` posee el formatting con policy. Su primer API explícito será
  sólo `fixed` y `scientific` con cantidad de dígitos fraccionarios; width,
  padding y sign policy quedan para otro milestone.
- La interpolación ordinaria se escribe `"Root: ${root}"`. Es sintaxis del
  lenguaje, resuelve cada hole estáticamente y produce un único `string` owned.
  Sólo `${` abre un field; `$`, `{` y `}` aislados son texto ordinario.
- Los holes V1 aceptan `string` y exactamente los escalares admitidos por
  `str`. Un tipo distinto falla en análisis semántico; no se consulta un método,
  witness, descriptor, RTTI ni tag runtime.
- Las expresiones de holes se evalúan una sola vez y de izquierda a derecha.
  Una implementación mide y escribe fragments en un backing final, con a lo
  sumo una allocation string y sin cadenas de concatenaciones O(n²).
- `print`/`println` mantienen exclusivamente `(string) -> void`. La
  interpolación resuelve composición reusable sin multiplicar overloads ni
  agregar separator/flush policy a Core.

## 2. Alcance y vocabulario

Esta decisión distingue tres operaciones:

1. **conversión canónica**: un valor escalar produce su representación textual
   única mediante `str`;
2. **formatting explícito**: el caller elige una policy decimal acotada mediante
   `std.Format`;
3. **interpolación**: sintaxis que evalúa fragments tipados, usa conversión
   canónica y compone un string owned.

“Canónico” significa que dos implementaciones conformes producen los mismos
bytes UTF-8 para el mismo valor y tipo Aether. No significa que el string
conserve toda metadata no observable del valor, como un NaN payload.

“Fresh” en esta API significa un owner producido por la operación, no Alias de
un argumento. Para los outputs escalares no vacíos del primer vertical se
materializa un backing heap exacto con una obligación inicial. Identidad de
backing continúa sin ser observable, pero allocation y ownership sí son costos
inspeccionables. Interpolación tiene sus propios fast paths de la sección 8.

Quedan fuera parsing de string a número, locale, currency, date/time, printf,
format strings dinámicos, una DSL compleja de format en compile time,
serialization, logging, reflection, un framework general Display/Debug y
formatting de tipos user-defined.

## 3. Conversión Core `str`

### 3.1 Superficie cerrada

La superficie conceptual de Core/prelude es:

```aether
string str(int8 value);
string str(int16 value);
string str(int32 value);
string str(int64 value);
string str(uint8 value);
string str(uint16 value);
string str(uint32 value);
string str(uint64 value);
string str(isize value);
string str(usize value);
string str(float32 value);
string str(float64 value);
string str(bool value);
string str(char value);
```

Los aliases transparentes comparten la firma canónica correspondiente:
`int` usa `int64`, `float` usa `float32`, `double` usa `float64` y `byte` usa
`uint8`. No existen overloads adicionales por spelling de alias.

`str` sigue el precedente de las familias cerradas de CORE-V1. El resolver
selecciona la firma por `TypeId` canónico antes de HIR. No se agrega resolución
general de overloads, generic `str<T>`, constraint, callable value ni fallback
por nombre. Un member del package actual puede shadowear el nombre prelude bajo
la precedencia ya decidida; una call resuelta conserva siempre su identidad
Core o de usuario exacta.

No se incluye `str(string)`: un string ya es el valor textual y copiar/aliasar
su owner es una decisión distinta de convertir un escalar. Tampoco se admiten
en este milestone enums, structs, classes, interfaces, collections, Vector,
Matrix, nullable, exceptions ni referencias.

### 3.2 Por qué `str`, no `string(value)` ni `format(value)`

`string(value)` se rechaza como superficie inicial porque en Aether
`TargetType(expression)` ya significa conversión de valor para tipos numéricos.
Hacer que `string` actúe a la vez como tipo fundamental, constructor y familia
abierta de presentación mezclaría conversión semántica con formatting y
sugeriría una cast universal inexistente.

`format(value)` tampoco es el nombre canónico: “format” implica policy, mientras
`str` selecciona una sola representación estable. El nombre breve satisface el
caso común y deja toda selección de estilo calificada bajo `std.Format`.

### 3.3 Efectos y ownership

Los argumentos escalares son Copy y se pasan por valor. `str`:

- evalúa el argumento una vez;
- no modifica estado externo ni consulta locale;
- puede calcular su longitud sin allocation;
- comprueba tamaño total y allocation antes de publicar el resultado;
- retorna un `string` owner fresh, `Copy=false` y `needs_drop=true`;
- no puede lanzar una language exception por el valor convertido.

`AllocationSizeOverflow` y `AllocationFailure` conservan los traps globales no
capturables. Ningún resultado parcial se publica. El owner resultante usa
Transfer/Move y Drop ordinarios; no hay COW ni string mutable.

## 4. Representaciones escalares canónicas

### 4.1 Enteros

Todo entero se escribe en base diez con bytes ASCII:

- cero es `0`;
- un signed negativo empieza con un único `-`;
- positivos y unsigned no tienen `+`;
- no hay leading zeros, separators, prefixes ni suffixes;
- el mínimo signed se formatea directamente desde su magnitud representable,
  sin negarlo en su propio tipo y sin `IntegerOverflow`;
- `isize`/`usize` usan el valor de su target admitido, pero la misma regla
  textual decimal.

La representación no depende de ancho salvo por el dominio de valores. Por
ejemplo, el valor siete produce `"7"` para todo tipo entero y `uint64.max`
produce `"18446744073709551615"`.

### 4.2 Booleanos

`false` produce `"false"` y `true` produce `"true"`, exactamente en lowercase
ASCII. No se admiten `0`/`1`, casing alternativo ni traducción por locale.

### 4.3 `char`

`char` produce exactamente la codificación UTF-8 del Unicode scalar value:
entre uno y cuatro bytes. No agrega quotes, escapes, prefijo ni representación
`U+...`. U+0000 produce un string de longitud uno que contiene el byte cero; no
produce el string vacío ni termina el contenido.

Surrogates no necesitan fallback porque no son valores `char` válidos. Un valor
que viole esa invariancia es corrupción compiler/runtime y hace trap; no se
reemplaza por U+FFFD.

## 5. Float canónico

### 5.1 Objetivo shortest-round-trip

Para todo valor finito no cero de `float32` o `float64`, `str` produce el
decimal con el menor número de dígitos significativos que, al ser leído para
el **mismo tipo IEEE** mediante conversión decimal correctamente redondeada a
nearest, ties-to-even, recupera exactamente el mismo patrón de bits.

El criterio se aplica directamente a binary32 o binary64. Un `float32` no se
promueve primero a float64 para decidir dígitos. Si varios decimales de igual
longitud significativa recuperan el mismo valor, se elige el más cercano al
valor binario exacto; un empate decimal usa significando par. Ésta es la regla
de selección observable común de shortest-round-trip, independientemente del
algoritmo usado para encontrarla.

El resultado necesita como máximo nueve dígitos significativos para binary32 y
diecisiete para binary64; usa menos siempre que el round-trip lo permita. Esos
límites no son una precisión fija rellenada con ceros.

La garantía de round-trip define la futura pareja con parsing tipado, pero no
admite parsing en este milestone.

### 5.2 Selección de notación

Sea `k` el exponente decimal ajustado del decimal shortest, de modo que hay un
dígito no cero antes del punto en notación científica. Se usa:

- notación fija si `-6 <= k < 21`;
- notación científica en cualquier otro caso.

La notación fija usa sólo dígitos y, si es necesario, un `.`. No agrega `.0` y
elimina ceros fraccionarios que no pertenezcan al significando shortest. La
notación científica usa un dígito antes de `.`, omite el punto si no quedan
dígitos posteriores y usa `e`, signo `+` o `-` obligatorio y el exponente sin
leading zeros.

Ejemplos de forma, sujetos al valor IEEE exacto:

```text
1.0       -> 1
1.5       -> 1.5
1000000.0 -> 1000000
1e21      -> 1e+21
1e-7      -> 1e-7
```

El separador decimal siempre es `.`. No hay grouping, whitespace ni dependencia
de `LC_NUMERIC`, locale del proceso, rounding mode hardware o libc.

### 5.3 Cero, infinities y NaN

Los casos no ordinarios son exactos:

| Valor IEEE | Resultado |
|---|---|
| positive zero | `0` |
| negative zero | `-0` |
| positive infinity | `Inf` |
| negative infinity | `-Inf` |
| cualquier NaN | `NaN` |

Signed zero se preserva porque ya es observable en la semántica IEEE. Para NaN
se canonicaliza sólo el texto: payload, quiet/signaling state y sign bit no se
exponen. Formatting no altera el valor fuente.

### 5.4 Algoritmo privado

Ryu, Schubfach, Dragonbox y algoritmos equivalentes son candidatos apropiados.
FORMAT-ARCH-1 no congela uno ni permite delegar el contrato a su versión. La
implementación elegida debe demostrar exhaustivamente binary32 y con corpus
dirigido/property tests binary64 que cumple selección, round-trip y bytes
canónicos. `snprintf`, `%f`, streams C++ o formatter del host no son autoridad
semántica.

## 6. Formatting explícito en `std.Format`

### 6.1 Primera superficie

El primer formatting con policy será deliberadamente pequeño:

```aether
import std.Format;

string std.Format.fixed(float32 value, usize fractionalDigits);
string std.Format.fixed(float64 value, usize fractionalDigits);
string std.Format.scientific(float32 value, usize fractionalDigits);
string std.Format.scientific(float64 value, usize fractionalDigits);
```

Los aliases `float`/`double` resuelven a las firmas canónicas. No hay formato
para enteros en esta primera superficie porque su representación decimal
canónica ya cubre el caso bootstrap y width/sign/padding deben diseñarse juntos.

`fixed(v,n)` emite exactamente `n` dígitos después del punto, omitiendo el punto
si `n == 0`. `scientific(v,n)` emite un dígito antes del punto, exactamente `n`
dígitos posteriores, y `e` seguido por signo obligatorio y exponente sin
leading zeros. Ambos redondean el valor binario exacto al último dígito decimal
con nearest, ties-to-even, independientemente del rounding mode ambiente.

Un carry decimal reajusta el dígito y exponente científicos de forma normalizada.
El signo de todo valor finito negativo se conserva aunque su magnitud redondee a
cero; por ejemplo, un valor negativo suficientemente pequeño puede producir
`-0.00` con `fixed(value, 2)`.

Trailing zeros solicitados forman parte del resultado. Negative zero conserva
`-`. NaN e infinities usan los spellings canónicos y no reciben punto, ceros ni
exponente aunque `fractionalDigits` sea distinto de cero.

La cantidad no tiene un máximo semántico arbitrario. Cálculos de longitud usan
aritmética checked; tamaños no representables y OOM mantienen
`AllocationSizeOverflow`/`AllocationFailure`. Una implementation puede aplicar
un límite de recursos del target sólo si el perfil lo declara como límite de
string, no como truncado silencioso.

### 6.2 Lo que no entra todavía

Width, alignment, fill, sign-always, integer bases, grouping y una estructura
nominal de opciones se difieren. Agregarlos como flags posicionales haría
ilegible la API; cuando exista evidencia conjunta se diseñará un descriptor o
familia nominal extensible. No se reserva `printf`, `%` formatting, un string de
formato dinámico ni mini-lenguaje interpretado en runtime.

El primer vertical recomendado por esta arquitectura no necesita implementar
`std.Format`: primero debe calificar conversión canónica e interpolación. La API
anterior es el siguiente vertical acotado y no debe admitirse parcialmente.

## 7. Sintaxis de interpolación

### 7.1 Forma

Una literal string puede contener replacement fields:

```aether
int iterations = 7;
double root = 1.234567;

string line = "Root: ${root}";
println("Iterations: ${iterations}");
println("Root: ${root}");
println("Result: ${f(x)}");
```

Cada field contiene una expresión Aether no vacía:

```text
InterpolatedString  := `"` (TextChunk | Escape | InterpolationField)* `"`
InterpolationField := `${` Expression `}`
```

La gramática ilustrativa no sustituye la gramática completa de literals. El
scanner da precedencia al sistema ordinario de escapes de string y reconoce un
field sólo ante la secuencia source no escapada `${`. Un `$` no seguido de `{`
no inicia ningún modo especial; `$`, `{` y `}` aislados son texto ordinario
dentro de una string. Ya no existen `{{` y `}}` como escapes especiales de
interpolación: cada brace de esas secuencias es texto ordinario. `\${` produce
los caracteres literales `${` mediante el sistema normal de escapes de string
y no abre un field.

Después de `${`, el contenido se parsea como una expresión Aether ordinaria.
El `}` correspondiente cierra el field. Delimitadores, incluidos braces,
anidados dentro de la expresión deben balancearse mediante el lexer/parser
normal. Strings y comments internos se tokenizan completos, por lo que sus
braces y secuencias `${` no cierran ni abren accidentalmente el field. El `}`
de cierre a profundidad cero no forma parte de la expresión. No se admite `:`
format specifier, conversion flag, nombre implícito, shorthand de debug ni
brace dinámico.

`${}` se rechaza con un diagnóstico de expresión vacía cuyo span cubre el
field. `${expr` sin el `}` correspondiente se rechaza como field sin cierre,
con un span que parte del `${` y alcanza el punto donde se detecta el cierre
ausente. Los errores internos restantes conservan los diagnostics y spans del
parser de expresiones ordinario, contextualizados por el field.

Una literal sin fields continúa siendo el `StringOp::Literal` inmortal actual.
Braces existentes dentro de literals no cambian de significado y no requieren
escaping. En particular, `"{root}"` es texto ordinario, no interpolación. El
reconocimiento de `${` es puramente sintáctico y no depende de si un nombre
resuelve.

Son explícitamente válidos:

```aether
"Price: $20"
"set = {1, 2, 3}"
"Root: ${root}"
"${a} + ${b} = ${a + b}"
"\${root}"
```

### 7.2 Tipos interpolables

V1 acepta exactamente:

- `string`;
- todos los signed/unsigned integers e `isize`/`usize`;
- `float32` y `float64`;
- `bool`;
- `char`.

Aliases transparentes no crean casos nuevos. Cada scalar usa exactamente los
bytes de `str` para su valor y tipo. Un string aporta sus bytes existentes sin
quotes, escaping adicional ni normalización.

El tipo de cada expresión debe ser concreto y pertenecer al set cerrado. Un
generic `T`, struct, enum, class, interface, collection, mathematical type,
reference o cualquier otro valor produce un diagnóstico semántico en el hole,
aunque accidentalmente tenga un método llamado `str` o `toString`. No existe
runtime fallback ni inspección de descriptor.

## 8. Evaluación, construcción y costos

### 8.1 Orden y evaluación única

La operación completa sigue estas etapas observables:

1. los holes se evalúan exactamente una vez, de izquierda a derecha;
2. cada resultado se captura con su tipo y categoría owning ya resueltos;
3. tras evaluar todos los holes, se miden fragments y suma el tamaño UTF-8 en
   orden con aritmética checked;
4. si el total no es vacío, se reserva un backing final exacto;
5. text chunks y valores capturados se escriben en orden y el owner se publica.

Así, efectos y exceptions de todas las expresiones ocurren antes de la
allocation final. Un `AllocationSizeOverflow` de composición se observa después
de evaluar los holes y antes de allocation; OOM se observa al reservar el
backing. Ambos son traps no capturables y conservan la política global sin
promesa de cleanup.

El formatter de un scalar admitido no llama código user-defined, no lanza una
exception y no vuelve a evaluar la expresión. Una optimización puede mezclar
medición y captura sólo si prueba equivalencia de orden, effects, traps y
ownership.

### 8.2 Ownership de operands

Un operand scalar es Copy. Un string lvalue se presta durante la interpolación;
copiar sus bytes al backing final no crea por sí mismo un Alias owner ni retain.
El borrow permanece vivo hasta que sus bytes se han escrito, por lo que la
evaluación de holes posteriores no puede mover, reemplazar o invalidar ese
owner bajo las reglas normales.

Un string temporal producido por un hole se captura como owner y vive hasta la
escritura final. Se transfiere a un temporary root, no se retiene por Alias, y
se destruye exactamente una vez después de copiarlo o durante el unwind de una
expresión posterior. Strings owning capturados y otros temporales ya
inicializados participan del cleanup excepcional ordinario, en orden inverso.

La interpolation no consume un string lvalue, no adopta su backing y no cambia
su ARC. No usa COW ni un mutable public string.

### 8.3 Allocation y complejidad

Para un resultado total no vacío, la garantía bootstrap es una allocation
string exacta y una escritura de cada byte del resultado. No se materializan
los resultados escalares de `str`, no se ejecuta una serie de `+` y no se
publica un builder intermedio. Tiempo y espacio son O(bytes del resultado más
el costo de evaluar holes).

Si el total es vacío, la operación retorna un owner del singleton vacío y no
asigna heap. Una literal sin holes sigue siendo estática. Estos fast paths no
cambian que el resultado source sea un `string` owned con una obligación de
Transfer/Drop.

Un backend puede usar un builder privado de dos pasadas o helpers count/write.
Ese builder no es source-visible, no escapa, no es el backing mutable de un
`string` publicado y no justifica COW. Si una estrategia futura evita la primera
pasada debe preservar una sola allocation, orden, traps y tamaño exacto.

## 9. Desugaring y representación por fases

La interpolación es syntax sugar en el sentido de que no agrega dynamic
formatting ni una nueva categoría de valor. No se define, sin embargo, como el
árbol literal de calls `str(x)` y operadores `+`, porque eso exigiría strings y
allocations intermedios que contradicen su contrato de costos.

### HIR

HIR contiene una operación tipada `Interpolation` conceptual con una secuencia
ordenada de:

- chunks UTF-8 ya decodificados y validados;
- expressions resueltas una vez;
- `TypeId` canónico;
- conversión estática `StringBorrow` o `CanonicalScalarFormat`;
- tipo resultado `string`, ownership fresh y spans del field/chunk.

El verifier reconstruye el set interpolable y no acepta un protocolo, target
por spelling ni formatter dinámico. Calls explícitas `str` siguen siendo
`CoreCall` con identidad/firma Core y no se confunden con la operación fusionada.

### MIR

MIR materializa evaluación ordenada, captures, borrows, temporales owning,
cleanup normal/excepcional, suma checked, allocation y publicación. Debe
representar el resultado como no inicializado hasta completar todos los bytes.
No hay owner parcial source-visible. Los traps de size/OOM no tienen exceptional
successor; las expresiones de holes conservan sus edges `may_unwind` reales.

### SSA

SSA conserva fragment order, tipos, efectos, borrow keepalives, checked size y
un único yield owner. Su verifier prueba que cada expresión/capture tiene una
definición, cada owner temporal un consumo/Drop por path aplicable, el backing
se publica una vez y ninguna transformación duplica/reordena holes. Una
interpolación no puede degradarse silenciosamente a concatenación cuadrática.

### Backend/runtime

El backend baja sólo el plan verificado. El runtime privado puede aportar:

- longitud y emisión decimal de cada integer category;
- longitud y emisión float shortest-round-trip;
- longitud/emisión UTF-8 de `char` y constantes bool;
- allocation checked de string no publicado y publicación final;
- acceso borrowed length-aware a fragments string.

Los helpers tienen firmas/effects versionados y se seleccionan por reachability.
No reciben un boxed `Any`, tag dinámico, format string C ni callback user-defined.
La implementación nunca usa `strlen` o `%s`; U+0000 sigue siendo contenido.

## 10. Integración con output

Core conserva:

```aether
void print(string value);
void println(string value);
```

Su semántica sigue siendo la de GENERAL-V1/CORE-V1/IO-V1: borrow durante la
call, output length-aware, LF exacto de `println`, partial writes internos y
`IOException` en un fallo terminal. La única novedad futura en:

```aether
println("Root: ${root}");
```

es que el argumento se construye primero como un owner string temporal. La call
lo presta y después el temporal se destruye exactamente una vez, tanto en el
retorno normal como si output lanza.

No se admite `println("Root: ", root)`. Una API variadic/multi-value tendría que
decidir separators, overload resolution, formatting de cada tipo, ownership,
atomicidad/partial IO y duplicación para stderr/files. Además sólo serviría para
output: no produciría un label, path, diagnostic o string reusable. Mantener una
entrada string conserva Core pequeño y hace que interpolación sea la única
composición general.

Una optimización futura puede escribir una interpolación usada exclusivamente
por output directamente al canal sólo si preserva toda la observabilidad de
allocation, traps, evaluación, exception de write y cleanup. Como esta
arquitectura hace allocation un costo semántico inspeccionable, el primer
vertical no aplica esa fusión.

## 11. Frontera lenguaje/Core/STD/runtime

| Capa | Responsabilidad |
|---|---|
| Lenguaje | sintaxis/escaping de interpolación, evaluación única y ordenada, set estático interpolable, ownership del resultado y representación verificable por fases |
| Core/prelude | familia cerrada `str` y representación canónica scalar; `print`/`println(string)` sin cambio |
| `std.Format` | policy explícita `fixed`/`scientific`; futuros descriptors de width/sign/padding sólo por decisión separada |
| Runtime privado | count/write numérico determinista, backing final, allocation/publicación y bridges length-aware; nunca lookup o dispatch de usuario |

La representación numérica canónica pertenece a la semántica de Core aunque el
algoritmo viva físicamente en runtime. `std.Format` es explícito porque elegir
precision/notación es policy. La interpolation pertenece al lenguaje porque su
parsing, orden, evaluación única, static typing y plan de ownership no pueden
reconstruirse desde una call ordinaria después de perder la estructura source.

## 12. Exceptions, traps y cleanup

- Una expresión dentro de un hole conserva exactamente sus effects y puede
  lanzar conforme a su call resuelta.
- Ante unwind, todos los temporales completamente inicializados de holes
  anteriores se destruyen una vez en orden inverso. El resultado final todavía
  no existe.
- Canonical scalar conversion y los formatters privados no producen language
  exceptions por valores ordinarios, incluidos NaN e infinities.
- `AllocationSizeOverflow`, `AllocationFailure`, ARC corruption y un `char`
  runtime inválido son traps fail-fast sin exceptional successor ni promesa de
  cleanup.
- Una call posterior a `print`/`println` puede lanzar `IOException`; el owner
  interpolado ya publicado participa entonces del cleanup excepcional normal.

No se crea una exception `FormatException`: todos los format choices de esta
superficie son estáticos y los argumentos están tipados. Un format string
dinámico malformado es inrepresentable porque no existe esa API.

## 13. Tipos user-defined y evolución

Formatting custom, enums, structs/classes y debug formatting quedan abiertos.
La dirección compatible es una futura capability/protocol estática, explícita y
opt-in, posiblemente con destinos de escritura prestados y modos Display/Debug
separados. Debe diseñar coherence, generics, throwing behavior, allocation,
recursion/cycles, privacy y verifier/runtime representation antes de admitir un
solo tipo de usuario.

Esa dirección no será:

- un método virtual universal heredado por todos los valores;
- una conversión implícita basada en nombre `toString`;
- reflection de fields o enum tags;
- boxing en `Any` y runtime type switches;
- permiso para que un formatter mutable escape o publique UTF-8 parcial.

Agregar una capability futura podrá ampliar un nuevo perfil de interpolación,
pero no cambia retroactivamente qué programas acepta el set V1 cerrado ni la
representación canónica de escalares.

## 14. Alternativas evaluadas

| Alternativa | Ventajas | Costos | Decisión |
|---|---|---|---|
| `str` Core cerrado | breve, estático, estable, separa conversión de policy | familia compiler-known acotada | **Elegida** |
| `string(value)` | parece conversión de tipo | colisiona con `T(expr)` numérico y sugiere cast universal | Rechazada |
| `format(value)` sin options | nombre familiar | no expresa ninguna policy distinta de lo canónico | Rechazada |
| `value.toString()` universal | discoverability OO | exige protocolo/dispatch para todo valor y confunde classes con value types | Rechazada |
| `%f`/`snprintf` como default | implementación disponible | precisión fija, locale/host, round-trip y special values no portables | Rechazada |
| algoritmo float concreto normativo | output reproducible | congela implementation y evolución innecesariamente | Rechazado; se fija resultado, no algoritmo |
| sólo conversión canónica | vertical mínimo | no cubre reportes con decimales controlados | Elegida para primer vertical; `std.Format` es el siguiente |
| descriptor general de format V1 | extensible | options/ABI/coherence prematuros | Diferido |
| strings ordinarios con `${expr}` | apertura inequívoca, `$` y braces ordinarios permanecen texto | `\${` es necesario para texto literal `${` | **Elegida** |
| strings ordinarios con `{expr}` | sigilo más corto | captura braces ordinarios y exige `{{`/`}}` y migración | Rechazada |
| prefijo `f"..."` | no cambia literals existentes | dos clases de literal y más ruido en el caso dominante | Rechazado inicialmente |
| interpolation como `+`/`str` literal | lowering simple | múltiples allocations y O(n²) en cadenas | Rechazada |
| builder privado con un backing | una allocation, costos claros | requiere operación estructurada en IR | **Elegido** |
| `println` variadic | cómodo sólo al imprimir | overload/IO policy grande, no compone como valor | Rechazada para V1 |

## 15. Primer vertical recomendado

Nombre: **FORMAT-V1 — canonical scalar strings and interpolation**.

Target bootstrap: Linux x86-64, single thread, runtime ABI privada y EH ya
calificado por IO-V1. Debe admitir en una sola ruta source→native:

1. las catorce firmas canónicas de `str`, aliases transparentes y selección
   Core cerrada;
2. decimal exacto de todos los tipos enteros, incluidos cada MIN/MAX e
   `isize`/`usize` del target;
3. bool lowercase y todos los anchos UTF-8 de `char`, incluido U+0000;
4. shortest-round-trip de binary32/binary64, notation thresholds, NaN/Inf y
   signed zero exactos;
5. parsing de interpolation abierta sólo por `${`, `\${` literal, `$` y braces
   ordinarios, expressions/delimitadores anidados, strings/comments dentro del
   hole y diagnostics con spans para `${}` y fields sin cierre;
6. el set estático de holes y rechazo fail-closed de todos los demás tipos;
7. evaluación única izquierda→derecha con effects, traps y exceptions;
8. string lvalue borrowed, temporary string owned, cleanup normal/unwind y
   resultado owner único;
9. cero allocations intermedias, una allocation para resultado no vacío y
   fast path singleton para vacío;
10. `print`/`println` sin cambio de firmas, con cleanup si output lanza;
11. HIR/MIR/SSA explícitos y corrupciones independientes de tipo, orden,
    conversion kind, size plan, owner consumption y publicación;
12. reachability por helper, equivalencia O0/O2, locale host adversarial y
    ausencia total de formatting runtime en programas sin `str`/interpolation.

Qualification float32 debe poder recorrer exhaustivamente los patrones de bits
o justificar una partición equivalente reproducible. Float64 debe combinar
vectors de frontera, potencias, subnormals, vecinos ULP, random property corpus
y round-trip contra un parser de prueba correctamente redondeado; ese parser no
se publica como API Aether. Outputs se comparan como bytes, no visualmente.

El vertical debe excluir `std.Format`, formatting de user types, parsing,
format specifiers dentro de holes, width/padding/sign policy, println variadic,
builders públicos, reflection, logging y cambios a string/IO.

## 16. Vertical posterior de formato explícito

**FORMAT-V2 — explicit fixed/scientific float formatting** puede implementar
las cuatro firmas `std.Format` después de FORMAT-V1. Debe verificar rounding
ties-to-even, trailing zeros exactos, scientific exponent, special values,
negative zero, precisiones cero/grandes, checked size/OOM, ownership, imports,
reachability y ausencia de locale. No agrega sintaxis dentro de interpolation:
la forma de conectar policy explícita con un hole necesita otra decisión o se
compone hoy como expresión string temporal cuando esa API sea admitida.

## 17. Decisiones abiertas y gates

No bloquean FORMAT-V1:

- API integer para bases, uppercase, prefixes y grouping;
- width, alignment, arbitrary fill, sign-always y un descriptor nominal;
- sintaxis de format specifier dentro de interpolation;
- integración de `std.Format` que evite el temporary string sin duplicar policy;
- custom Display/Debug estático y coherence para tipos user-defined;
- formatting de enums, collections, Vector/Matrix y cycles de objetos;
- locale/currency y versionado de datos de locale;
- límites de output configurables antes de OOM;
- compile-time formatting/constant folding y política de artifact reproducible;
- direct-to-output fusion y cómo exponer su cambio de allocation costs;
- otros targets, runtime separado y ABI estable de Core/stdlib.

Antes de FORMAT-V1 deben cerrarse en implementación los tokens/AST exactos de
una literal interpolada sin debilitar spans ni comments, y una representación
de fragment plan que cada verifier pueda reconstruir. Antes de admitir tipos
user-defined debe existir un contrato general de capability/coherence/effects;
un método con nombre coincidente nunca basta.

## 18. Consecuencias

Los casos científicos comunes quedan directos:

```aether
println("Iterations: ${iterations}");
println("Root: ${root}");
```

sin convertir output en una familia variadic ni ocultar reflection. Los mismos
valores pueden convertirse explícitamente con `str` y reutilizarse fuera de IO.
El default float es corto, round-trippable y estable entre locales/targets
conformes; el control decimal futuro permanece claramente calificado en
`std.Format`.

La estructura de interpolation sobrevive hasta MIR/SSA, de modo que evaluación,
ownership, una sola allocation y cleanup son verificables en lugar de depender
de una optimización tardía. Core crece sólo con una familia cerrada, stdlib posee
policy y runtime conserva algoritmos/representación privados.
