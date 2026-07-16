# Parsing numérico explícito desde `string`

Estado: implementado end-to-end en el perfil 15 (AST, intérprete IR y
LLVM/native), 15 de julio de 2026.

## API pública y resultados

La API no introduce sintaxis ni conversiones implícitas:

```aether
IntParseResult parseInt(string text);
DoubleParseResult parseDouble(string text);
```

Los tres tipos nominales incorporados son equivalentes a:

```aether
enum ParseStatus { Success, Empty, InvalidFormat, OutOfRange }
struct IntParseResult { int value; ParseStatus status; }
struct DoubleParseResult { double value; ParseStatus status; }
```

`value` vale `0`/`0.0` cuando `status != Success`. Es sólo el valor default del
field, no un sentinel: el programa debe consultar `status` antes de consumirlo.
No se añadieron excepciones, nullable, `Option` ni `Result<T,E>`.

## Gramática

`parseInt` acepta exactamente decimal ASCII:

```text
sign? digit+
sign  := "+" | "-"
digit := "0" ... "9"
```

Acumula la magnitud con un límite previo por dígito. Acepta
`-2147483648` sin intentar representar antes su magnitud en i32 y devuelve
`OutOfRange` fuera de `[-2147483648, 2147483647]`.

`parseDouble` acepta exactamente:

```text
sign? ((digit+ ("." digit*)?) | ("." digit+))
      (("e" | "E") sign? digit+)?
```

Por tanto acepta `123`, `.5`, `5.`, `1e10` y `-2.5e-3`. `NaN`, `Infinity` y
`-Infinity` se rechazan como `InvalidFormat`; no hay spellings especiales.
Overflow decimal a infinito devuelve `OutOfRange`. Underflow, subnormales y
signed zero siguen IEEE-754 y son `Success`.

Ambos parsers son estrictos: vacío es `Empty`; whitespace, coma decimal,
underscores, prefijos, trailing garbage, NUL embebido y cualquier byte no ASCII
son `InvalidFormat`. No se aplica `trim` implícito.

El perfil 16 agrega el método explícito `string.trim()`. Por tanto
`parseInt(" 42 ")` sigue siendo `InvalidFormat`, mientras
`parseInt(" 42 ".trim())` es `Success`; lo mismo aplica a `parseDouble`. Trim
no forma parte del parser y sólo elimina space, tab, LF, CR, form feed y
vertical tab ASCII en los extremos. Los parsers no llaman al helper de trim.

## Runtime y backends

La semántica compartida del host vive en `string_parsing.py` y trabaja sobre
los bytes UTF-8 autoritativos de `StringValue`. Python `int()` no define el
contrato; el entero usa un parser propio. `float()` se invoca sólo después de
que una gramática de bytes cerrada haya rechazado todas las extensiones del
host, y overflow/underflow se normalizan explícitamente.

IR conserva `parseInt`/`parseDouble` como calls builtin tipadas con resultado
nominal, ubicación fuente y efecto de lectura de memoria. No son casts ni
operaciones matemáticas plegables. IR/SSA verifier comprueban argumento,
resultado y layout; DCE puede eliminar una call realmente no usada porque no
modifica memoria ni hace panic por input inválido, pero nunca elimina el valor
cuando sus fields se consumen.

Native usa `aether_parse_int` y `aether_parse_double`, toma prestado el handle
ARC y consulta length/data sin `strlen`. El helper double valida primero una
máquina de estados byte-aware y llama `strtod_l` con un locale C creado por
`newlocale`; no observa el locale del proceso, comprueba infinito y trata
underflow como resultado IEEE normal. Un fallo al crear el locale es un fallo
de infraestructura y hace panic; una entrada inválida normal nunca lo hace.

Los structs de resultado son triviales (scalar + enum), por lo que funcionan
en locals, retornos, structs anidados, `Array`/`List`, copy, slice y `for-in`.

## Fuera de alcance

No se añadieron formatting/toString general, conversiones implícitas, split,
input, argv, archivos, iteración Unicode, spellings de NaN/infinito ni
constant folding de parsing. La dependencia native actual de `newlocale` y
`strtod_l` forma parte del runtime POSIX usado por el backend clang; portar el
backend a una libc sin esas APIs requiere un adaptador locale-equivalente.
