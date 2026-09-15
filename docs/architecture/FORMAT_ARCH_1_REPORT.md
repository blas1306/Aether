# FORMAT-ARCH-1 — design report

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-14.

Este reporte resume la decisión normativa de
[FORMAT-ARCH-1](FORMAT_ARCH_1.md). Sólo se agregaron documentos; no se modificó
parser, frontend, HIR, MIR, SSA, backend, Core, stdlib, runtime, tests ni CLI, y
no se declara soportada ninguna sintaxis o API nueva.

## Resultado

La conversión canónica se incorpora conceptualmente como una familia cerrada
Core/prelude:

```aether
string text = str(value);
```

Admite signed/unsigned integers, `isize`/`usize`, `float32`/`float64`, `bool` y
`char`, incluidos sus aliases transparentes. No admite `string`, aggregates,
objects o generics y no es `string(value)`, un método `toString`, interface,
reflection ni dynamic dispatch. Cada call escalar produce un owner string fresh.

## Representación canónica

- enteros: decimal ASCII, sin `+`, leading zeros, grouping ni prefixes;
- bool: `true`/`false`;
- char: UTF-8 del scalar exacto, incluido U+0000 y sin quotes/escapes;
- floats: shortest decimal que round-trips al mismo binary32/binary64;
- hasta 9 dígitos significativos para binary32 y 17 para binary64, usando menos
  siempre que sea suficiente;
- fixed notation para exponentes ajustados `[-6, 21)` y scientific fuera;
- `.` decimal, `e` lowercase, locale/rounding mode del host ignorados;
- positive/negative zero: `0`/`-0`;
- infinities: `Inf`/`-Inf`; todo NaN: `NaN`.

La selección observable está fijada, no el algoritmo. Ryu, Schubfach,
Dragonbox u otro equivalente pueden usarse si producen exactamente el contrato.
`%f`, `snprintf` y formatters del host no son autoridad.

## Formatting explícito

La policy futura vive bajo import explícito:

```aether
import std.Format;

std.Format.fixed(value, fractionalDigits);
std.Format.scientific(value, fractionalDigits);
```

Ambas familias aceptarán float32/float64, redondearán nearest ties-to-even y
producirán exactamente los ceros pedidos. Width, alignment, padding, sign
policy, integer bases y descriptors quedan diferidos. No hay format strings
dinámicos ni compatibilidad printf.

`std.Format` se implementará después del primer vertical; su arquitectura queda
cerrada para que no se improvise un formato fijo como default de lenguaje.

## Interpolación

La sintaxis elegida es:

```aether
println("Iterations: ${iterations}");
println("Root: ${root}");
println("Result: ${f(x)}");
```

Sólo `${` abre un field. Un `$` no seguido de `{` y los braces `{`/`}` aislados
son texto ordinario; `{{` y `}}` ya no tienen función especial. `\${` produce
los caracteres literales `${` mediante los escapes ordinarios de string. Cada
hole contiene una expresión Aether ordinaria y no admite todavía `:spec`. El
`}` correspondiente lo cierra, respetando delimitadores/braces anidados; strings
y comments internos no lo cierran accidentalmente. `${}` diagnostica una
expresión vacía y `${expr` un field sin cierre, ambos con spans apropiados. Sólo
`string` y el set escalar de `str` son interpolables; todo lo demás falla
estáticamente aunque declare un método de nombre parecido.

Son explícitamente válidos:

```aether
"Price: $20"
"set = {1, 2, 3}"
"Root: ${root}"
"${a} + ${b} = ${a + b}"
"\${root}"
```

Las expresiones se evalúan una vez y de izquierda a derecha. Después se miden
los fragments, se comprueba la suma, se hace una allocation exacta para un
resultado no vacío y se escribe cada fragment una vez. Un resultado vacío usa
el singleton. No hay resultados `str` intermedios ni cadena de `+` O(n²).

String lvalues se prestan sin Alias adicional y sus borrows permanecen vivos
hasta copiar bytes. String temporaries se capturan como owners y se destruyen
exactamente una vez. Unwind limpia temporales inicializados; OOM/size overflow
siguen siendo traps sin unwind.

## Output y fronteras

`print`/`println` mantienen sólo `(string) -> void`. La interpolación produce su
argumento owned y output lo presta con el comportamiento length-aware/UTF-8/LF/
IOException ya calificado. Se rechaza una API variadic porque agregaría policy y
overloads a IO sin resolver composición reusable.

| Capa | Responsabilidad |
|---|---|
| Lenguaje | parsing, escaping, static hole typing, orden/evaluación única y plan owned de interpolation |
| Core/prelude | `str` canónico y `print`/`println(string)` sin cambio |
| `std.Format` | fixed/scientific y futura policy explícita |
| runtime privado | count/write determinista y allocation/publicación de backing, sin tags dinámicos |

HIR conserva fragments, tipos y conversion kind; MIR materializa captures,
borrows, cleanup y construcción; SSA verifica orden, consumo único y publicación.
Backend/runtime sólo bajan el plan verificado y seleccionan helpers alcanzables.

## Primer vertical

Se recomienda **FORMAT-V1 — canonical scalar strings and interpolation** para
calificar end-to-end:

1. toda la familia `str` y aliases;
2. extremos enteros, bool y UTF-8 char;
3. floats normales/subnormales/fronteras, special values y round-trip;
4. apertura `${`, escape `\${`, `$`/braces ordinarios, expressions y
   delimitadores anidados, strings/comments internos y diagnostics con spans
   para fields vacíos o sin cierre;
5. tipos admitidos/rechazados y evaluación única ordenada;
6. borrows/temporales/cleanup normal y excepcional;
7. una allocation final, singleton vacío y cero strings intermedios;
8. integración sin cambio con output, O0/O2, locale adversarial, reachability y
   corrupciones HIR/MIR/SSA.

`std.Format`, tipos user-defined, parsing, specifiers, variadic output, builders
públicos, reflection y logging permanecen fuera. FORMAT-V2 podrá calificar
fixed/scientific en un vertical separado.

## Evidencia arquitectónica aplicada

La decisión preserva:

- Core/prelude cerrado, identities canónicas y imports explícitos de
  MODULE-STD-V1/CORE-V1;
- `string` inmutable, UTF-8, owned, length-aware, sin COW y con
  Alias/Transfer/Drop de GENERAL-V1/V2;
- policy y algoritmos fuera del lenguaje cuando pueden vivir en STD, como en
  TEXT-ARCH-1;
- `print`/`println` Core y los fallos output/cleanup de IO-V1;
- orden izquierda→derecha, traps separados de exceptions y fases tipadas con
  verificación independiente del charter/contrato/compiler architecture.

El resultado hace cómodos los casos reales solicitados sin introducir un
sistema universal de conversión y mantiene visibles allocation, ownership,
precisión y policy numérica.

## Validación del milestone

- Se agregaron solamente `FORMAT_ARCH_1.md` y este reporte.
- No se tocó ninguna modificación preexistente del working tree.
- La especificación cubre conversión, float default, formato explícito,
  interpolation, output, capas, costos, ownership, failures, evolución de tipos
  user-defined, alternativas, dos verticales y qualification.
- Toda feature continúa no implementada y debe fallar cerrada hasta FORMAT-V1.
