# CORE-V1 — initial prelude spine

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-14, para `compiler-next` en el
perfil nativo bootstrap Linux x86-64, bajo
[MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md).

## Manifest y frontera

`PRELUDE_V1` es una tabla cerrada y versionada con exactamente:

```text
print, println, byteLength
abs, min, max, clamp
sqrt, exp, ln, sin, cos, tan
```

No contiene `List<T>`, no crea una raíz source Core, no abre `std` ni ningún
namespace y no equivale a un import. `std.Math` y sus algoritmos especializados
continúan detrás de imports explícitos y este vertical no agregó allí ninguna API.

## Identidad canónica y lookup

Cada entrada resuelve a `CoreSymbol`, `CoreSymbolKey { profile, ordinal,
member }` y una `CoreFunction` con tipo de parámetro concreto. El profile v1,
ordinal y member se reconstruyen y comparan en HIR, MIR y SSA; modificar uno de
ellos, el símbolo, la aridad, operands o resultado invalida el IR. Los dumps de
las tres fases conservan esa identidad y los `TypeId` canónicos, no sólo el
spelling de la llamada.

El lookup no calificado aplica lexical → member del package actual → manifest
del prelude. Un lexical callable se rechaza como function value todavía no
admitido y no cae accidentalmente al prelude. Un member del package actual sí
shadowea Core. Imports y aliases de `std` no agregan nombres no calificados ni
modifican el manifest. Después de resolver, HIR recibe la `CoreFunction` exacta;
no existe `PreludeOp` ni reinterpretación posterior del nombre.

## Firmas admitidas

| Símbolo | Firmas CORE-V1 |
|---|---|
| `print`, `println` | `(string) -> efecto de output` |
| `byteLength` | `(string) -> usize` |
| `abs` | `(T) -> T`, T = enteros signed fijos, `isize`, `float32`, `float64` |
| `min`, `max`, `clamp` | homogéneas `(T,T)->T` y `(T,T,T)->T`, T = todos los enteros admitidos, `float32`, `float64` |
| `sqrt`, `exp`, `ln`, `sin`, `cos`, `tan` | `(T) -> T`, T = `float32` o `float64` |

No hay overload sets generales. El resolver local selecciona una de estas
familias cerradas a partir de los operands y del contexto de literals. Sólo usa
el widening existente dentro de familias signed, unsigned y
`float32 -> float64`; no agrega narrowing, signed/unsigned, integer/float ni
otras conversiones implícitas. `abs` unsigned se rechaza.

## Semántica y lowering

`print`/`println` reutilizan el output length-aware de GENERAL-V1, incluido
U+0000, y `byteLength` consulta la longitud UTF-8 almacenada en O(1). Sus
operands son borrowed y los owners temporales conservan el cleanup existente.

`abs` de enteros signed conserva el ancho y atrapa `IntegerOverflow` para MIN;
no hace wrapping. `min`, `max` y `clamp` enteros comparan con signedness exacta.
`clamp(x,lo,hi)` es la composición `min(max(x,lo),hi)` y no inventa un trap para
límites invertidos.

Los floats preservan el tipo. `abs`, `min` y `max` bajan a `fabs[f]`, `fmin[f]`
y `fmax[f]`; clamp compone `fmax` y `fmin`. NaN, infinities y signed zero siguen
esas operaciones IEEE/libm: `fmin`/`fmax` devuelven el operand numérico cuando
sólo el otro es NaN. Las trascendentales bajan a las variantes float/double de
libm (`ln` a `log[f]`). Dominio, polos, NaN e Inf siguen libm/IEEE en el perfil;
no se crean exceptions Aether ni fast-math.

`CoreCall<O>` es una llamada de biblioteca Core tipada y resuelta, compartida
por las tres IR. No se agregó un opcode/intrinsic de lenguaje por función. Los
únicos caminos especiales conservados son las razones semánticas previas:
output/string fundamental y el trap checked de `abs` entero.

## Reachability y link

Una referencia Core crea un nodo sólo en el body alcanzable. El backend declara
únicamente las variantes libm usadas; el driver agrega `-lm` sólo cuando aparece
esa dependencia. Un body no alcanzable que menciona `exp` o `println` no emite
libm ni runtime string.

## Qualification y corrupciones

`core_v1.rs`, `module_std_v1.rs` y el test interno HIR cubren uso sin imports;
UTF-8 multibyte/U+0000; todos los tipos admitidos de `min`/`max`/`clamp` y
`abs` en O0/O2; ambas precisiones de trascendentales; dominio, NaN, Inf y signed
zero; widening y rechazos; shadowing; independencia de imports std; reachability;
y corrupciones independientes de identidad en HIR, MIR y SSA. Las suites
MODULE-STD-V1, GENERAL-V1/V2 y TEXT-V1 permanecen verdes.

La calificación de cierre ejecutó `cargo test --workspace` (430 tests),
`cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D
warnings`, `git diff --check` y el differential nativo completo
(`checked=21, failures=0`).

## Deuda restante

Quedan fuera `List<T>` Core, un framework general de overload resolution,
overloads definidos por usuario, imports selectivos/apertura de namespaces,
formatting, parsing, IO/File y matemática especializada. El disambiguador futuro
de overloads deberá convertir estas firmas cerradas en identidades persistentes
sin usar `TypeId` de sesión ni ordinals como ABI. También quedan abiertas la
precisión/reproducibilidad formal de libm, otros targets y la distribución física
de bodies Core precompilados; ninguna amplía la superficie admitida aquí.
