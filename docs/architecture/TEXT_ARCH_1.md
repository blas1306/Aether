# TEXT-ARCH-1 — initial text standard library

Estado: **DECISIÓN DE ARQUITECTURA; TEXT-V1 IMPLEMENTADO**, 2026-09-12. La
admisión nativa exacta se registra en [TEXT_V1_REPORT](TEXT_V1_REPORT.md).

## 1. Decisión resumida

Aether expondrá la primera biblioteca de texto como el módulo estándar
explícito `Text`, operando sobre el `string` UTF-8 válido, inmutable, no nulo y
owning ya definido por
[GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md) y admitido por
[GENERAL-V1](GENERAL_V1_STRING_REPORT.md). `string` no se convierte en clase,
colección indexable ni buffer mutable.

La superficie inicial será:

```aether
import Text;

usize Text.codePointCount(ref string value);
bool Text.contains(ref string value, ref string needle);
bool Text.startsWith(ref string value, ref string prefix);
bool Text.endsWith(ref string value, ref string suffix);
Text.FindResult Text.find(ref string value, ref string needle);
Text.FindResult Text.findFrom(
    ref string value,
    ref string needle,
    Text.ScalarOffset start
);
string Text.substring(
    ref string value,
    Text.ScalarOffset start,
    Text.ScalarOffset endExclusive
);
string Text.trim(ref string value);
List<string> Text.split(ref string value, ref string separator);

Text.ScalarOffset Text.scalarOffset(usize value);

enum Text.FindResult {
    Found(Text.ScalarOffset),
    NotFound
}
```

Las firmas son notación normativa de API, no una exigencia de implementar
namespaces como objetos ni métodos. Los parámetros `ref string` son borrows
shared durante la llamada; ninguna consulta adquiere un owner ni hace Alias.

Las posiciones públicas cuentan **Unicode scalar values** desde cero. No se
publican byte offsets. `ScalarOffset(k)` designa la frontera situada después de
los primeros `k` scalars, por lo que el final válido es
`scalarOffset(codePointCount(value))`. Los rangos son `[start, endExclusive)`.
El wrapper nominal evita mezclar accidentalmente `byteLength(value)` con una
posición textual; no cambia el costo físico esperado respecto de `usize`.

Las coincidencias son exactas, case-sensitive y sin normalización. Dado que
todo string contiene UTF-8 válido y canónico por scalar, una comparación exacta
de bytes implementa esa igualdad y nunca produce una coincidencia pública en
mitad de una secuencia UTF-8.

## 2. Autoridad y alcance

Esta decisión concreta la frontera `STD Text` que GENERAL-ARCH-1 dejó abierta.
Respeta:

- [GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md): string fundamental, inmutable y
  UTF-8 válido; `byteLength` explícito; sin `s[i]`; substring owned por límites
  de code points; algoritmos de texto fuera del core;
- [GENERAL-V1](GENERAL_V1_STRING_REPORT.md): handle opaco de una palabra,
  Alias/Transfer/Drop, concat, igualdad y longitud en bytes ya calificados;
- [GENERAL-V2](GENERAL_V2_STRING_COMPOSITION_REPORT.md): `List<string>` y su
  lifecycle estructural ya tienen un modelo válido, sin hacer `string` Copy;
- el [charter](AETHER_V1_LANGUAGE_CHARTER.md): costos, allocation, ownership y
  bounds deben ser predecibles e inspeccionables, y sólo la ruta nativa completa
  puede admitir una feature;
- la [arquitectura del compilador](AETHER_COMPILER_ARCHITECTURE.md): llamadas
  de biblioteca conservan tipos, efectos y ownership a través de HIR/MIR/SSA;
  backend y runtime consumen únicamente estados verificados.

Quedan expresamente fuera: regex, grapheme clusters, normalización, locale,
collation, case folding complejo, formatting/interpolation, builders mutables
públicos, `StringView`, hashing, parsing numérico, conversiones `Bytes` y
`s[i]`. Tampoco se añade slicing sintáctico.

## 3. Unidades, posiciones y rangos

### 3.1 Unidad pública

La unidad pública es el **Unicode scalar value**, el mismo significado que
`char`. No es byte, code unit UTF-16 ni grapheme cluster. “Code point” en los
nombres de esta API significa exclusivamente Unicode scalar value; surrogates
no pueden existir en un string Aether.

`Text.ScalarOffset` es un nominal pequeño alrededor de `usize`:

- cuenta scalars anteriores a una frontera;
- comienza en cero;
- puede representar el final `codePointCount(value)`;
- no prueba por sí solo que sea válido para un string concreto;
- es `Copy`, `Relocatable`, `Storable` y no necesita Drop;
- no permite aritmética implícita con byte offsets.

`Text.scalarOffset(k)` sólo etiqueta la unidad y no recorre un string. La
validación ocurre al usar el offset contra un valor concreto. El payload
`usize` podrá ser inspeccionado mediante una consulta trivial del módulo; el
spelling exacto de esa consulta puede cerrarse junto con la sintaxis pública de
nominal wrappers, sin sustituir el tipo por un alias transparente.

`substring` usa un rango semiabierto `[start, endExclusive)`. Esto permite
representar el vacío en cualquier frontera y evita aritmética `end + 1`. No se
introduce un `Text.Range` en este milestone: dos offsets nominales son
suficientes y mantienen la llamada legible.

### 3.2 Resolución física

Un scalar offset no promete acceso O(1). Resolverlo recorre UTF-8 desde el
inicio del string, salvo que una implementación pueda reutilizar de forma
local un cursor ya verificado. El objeto string no adquiere tabla de índices,
cache de scalar count ni campos nuevos.

Los byte offsets existen sólo dentro de `Text` y de la frontera privada con
core/runtime. Nunca aparecen en firmas públicas, diagnostics que sugieran una
posición textual ni valores retornados al usuario.

## 4. Semántica de la API

### 4.1 Count y consultas booleanas

`codePointCount(value)` cuenta scalars decodificando el UTF-8 válido. No se
llama `length`, porque `byteLength` y el futuro conteo de graphemes son unidades
distintas.

`contains`, `startsWith` y `endsWith` comparan contenido exacto. No consumen ni
modifican sus argumentos. Sus reglas para needle vacío son:

- `contains(value, "") == true`;
- `startsWith(value, "") == true`;
- `endsWith(value, "") == true`.

Un prefix/suffix más largo en bytes que `value` no coincide. La comparación de
bytes es válida precisamente porque ambos operandos son UTF-8 válido y no se
aplica equivalencia Unicode adicional.

### 4.2 Búsqueda

`find(value, needle)` devuelve la primera coincidencia exacta de izquierda a
derecha. El índice retornado es el scalar offset del comienzo. `findFrom`
empieza en la frontera scalar `start` y también devuelve un offset relativo al
inicio del string completo.

El resultado no usa `null`, un entero signed con `-1`, `usize.max` ni el final
del string como sentinel. Es el enum nominal:

```aether
enum FindResult {
    Found(ScalarOffset),
    NotFound
}
```

Esto mantiene el dominio de índices unsigned, no hace ambiguo el match vacío al
final y no introduce nullability ni una abstracción general `Option` sólo para
esta función. Un futuro `Option<T>` general podrá motivar una migración de API
normal, pero no queda presupuesto ni implícito aquí.

Para needle vacío:

- `find(value, "")` es `Found(scalarOffset(0))`;
- `findFrom(value, "", start)` es `Found(start)`, incluido el final válido.

Las coincidencias no vacías nunca se solapan para el consumidor `split`; `find`
sólo retorna la primera y por ello no necesita una regla de solapamiento.

### 4.3 Substring owned

`substring(value, start, endExclusive)` devuelve el contenido del rango scalar
exacto como un owner `string`. No devuelve una view y no prolonga el backing por
una referencia prestada.

- un rango propio no vacío produce un string heap fresh mediante una copia
  exacta del rango UTF-8;
- el rango completo puede devolver Alias owned de `value` en O(1);
- cualquier rango vacío devuelve Alias del singleton vacío;
- ninguna ruta modifica el source ni publica UTF-8 parcial.

“Owned substring” significa que el resultado puede almacenarse y sobrevivir al
borrow de entrada. No significa identidad de backing fresh en casos donde la
identidad es inobservable. La posibilidad de Alias en rango completo/vacío es
parte del contrato de costos, no una optimización que el programa pueda detectar.

### 4.4 Trim bootstrap

`trim(value)` elimina de ambos extremos solamente estos seis ASCII bytes:

| Carácter | Byte |
|---|---:|
| space | `0x20` |
| horizontal tab | `0x09` |
| line feed | `0x0A` |
| carriage return | `0x0D` |
| form feed | `0x0C` |
| vertical tab | `0x0B` |

No elimina NUL, NBSP, NEL ni ningún otro Unicode White_Space. La definición es
independiente de locale y de la versión de Unicode. Se conserva el spelling
breve `trim` porque ésta es la política bootstrap elegida, pero su conjunto no
se ampliará silenciosamente. Una operación Unicode futura deberá tener contrato
y nombre separados dentro de `Text.Unicode`.

Si no hay nada que eliminar, retorna Alias owned de `value`. Si todo se elimina,
retorna el singleton vacío. En otro caso produce una copia heap fresh del rango
conservado.

### 4.5 Split

`split(value, separator)` usa coincidencias exactas, de izquierda a derecha y
no solapadas. Devuelve siempre un `List<string>` owner fresh y **conserva los
elementos vacíos**. Por tanto:

```text
split("a,,b,", ",") -> {"a", "", "b", ""}
split(",a", ",")    -> {"", "a"}
split("", ",")      -> {""}
split("abc", "x")   -> {"abc"}
split("ababa", "aba") -> {"", "ba"}
```

Conservar vacíos hace que delimitadores iniciales, finales y adyacentes no
pierdan información. Filtrar vacíos es una política separada que podrá
componerse en stdlib; no se agrega un flag booleano ambiguo al bootstrap.

Un separator vacío es un error de contrato y produce `EmptyTextSeparator`
antes de allocation. No se interpreta como “entre cada scalar”: esa operación
tendría una semántica de colección distinta y además requeriría decidir qué
hacer en ambos extremos.

Cada elemento de salida es un owner independiente según el lifecycle normal:

- un elemento vacío usa Alias del singleton vacío;
- si no hay match, el único elemento puede ser Alias de `value`;
- todo fragmento propio no vacío es un string heap fresh por copia.

El List es fresh incluso cuando sólo contiene un Alias. Destruirlo ejecuta el
Drop estructural ya definido para `List<string>`.

## 5. Bounds, errores y traps

Las APIs que reciben offsets validan en unidad scalar:

- `findFrom`: `0 <= start <= codePointCount(value)`;
- `substring`: `0 <= start <= endExclusive <= codePointCount(value)`.

`usize` y `ScalarOffset` hacen imposible un valor negativo. Un offset mayor que
el final produce el trap estructurado no recuperable
`TextPositionOutOfBounds`. `start > endExclusive` produce
`InvalidTextRange`. `split` con separator vacío produce
`EmptyTextSeparator`.

Estos traps representan precondiciones/programmer errors, siguen el modelo
fail-fast vigente, no tienen exceptional successor y no introducen Result ni
exceptions recuperables. Se detectan antes de allocation o publicación de un
resultado. Allocation-size overflow y OOM conservan
`AllocationSizeOverflow`/`AllocationFailure`; corrupción de invariantes internos
conserva su trap de runtime.

La búsqueda sin coincidencia no es error: retorna `NotFound`. String vacío,
needle vacío, rango vacío y elementos vacíos de split son valores ordinarios.

## 6. Complejidad y allocation

En esta tabla `H`, `N` y `S` son longitudes en bytes de haystack/value, needle
y separator; `P` son bytes hasta la frontera scalar relevante y `R` los bytes
del rango copiado. Las cotas son semánticas del bootstrap, no claims de una
libc concreta.

| Operación | Tiempo worst-case | Espacio auxiliar / allocation |
|---|---|---|
| `scalarOffset(k)` | O(1) | ninguno |
| `codePointCount` | O(H) | O(1), sin allocation |
| `startsWith` / `endsWith` | O(N), con rechazo O(1) por longitud | O(1), sin allocation |
| `find` / `contains` | O(H + N) | O(1), sin allocation |
| `findFrom` | O(H + N), incluida resolución de `start` | O(1), sin allocation |
| `substring` vacío/completo | O(P) para validar offsets; completo puede requerir recorrer H | sin heap string nuevo |
| `substring` propio | O(P + R) | una allocation string y R bytes copiados |
| `trim` sin cambio / todo vacío | O(H) | sin heap string nuevo |
| `trim` con cambio | O(H) | una allocation string y hasta H bytes copiados |
| `split` | O(H + S) más inicialización del List | List fresh; a lo sumo una allocation string por fragmento propio no vacío; bytes de payload copiados totales <= H |

La garantía lineal de búsqueda requiere un algoritmo exacto con worst-case
lineal y espacio constante, por ejemplo Two-Way. No se especifica el algoritmo
concreto ni se permite degradar silenciosamente a búsqueda naive O(H*N). Una
implementación puede usar otra estrategia o especializar needles de uno o pocos
bytes si preserva las cotas, el orden y la ausencia de allocation en consultas.

`split` puede hacer una primera pasada para contar matches, reservar capacidad
y una segunda para copiar fragmentos. Ambas pasadas siguen siendo lineales.
Debe usar aritmética checked para cantidad de elementos, capacidad y tamaños.

## 7. Ownership y efectos

| API/caso | Entrada | Resultado string/colección | Allocation permitida |
|---|---|---|---|
| count/contains/starts/ends/find | borrow shared | scalar/bool/enum Copy | ninguna |
| substring vacío | borrow shared | Alias del singleton vacío | ninguna |
| substring completo | borrow shared | Alias owned del source | ninguna |
| substring propio no vacío | borrow shared | fresh owner | una string |
| trim sin cambio | borrow shared | Alias owned del source | ninguna |
| trim todo ASCII whitespace | borrow shared | Alias del singleton vacío | ninguna |
| trim cambiado | borrow shared | fresh owner | una string |
| split | borrows shared | List owner fresh; elementos Alias o fresh según rango | storage del List y fragmentos propios |

Todo Alias conserva una obligación lógica independiente y puede ejecutar retain;
Transfer entrega los resultados fresh al caller; Drop libera cada owner restante.
Una implementación optimizada puede elidir ARC sólo con la autoridad y
reverificación ordinarias. No se adopta memoria del List como backing string, no
hay COW y ningún resultado permite mutar payload.

Si una allocation falla después de haber creado resultados parciales de
`split`, el comportamiento fail-fast actual no promete unwind. Cuando exista
allocation recuperable, el lowering deberá agregar cleanup explícito del List y
de sus elementos ya inicializados antes de cambiar esa política.

## 8. Frontera core/runtime/stdlib

### 8.1 Lenguaje y core público

No se agrega opcode público, operador, sintaxis ni member mágico. El core
mantiene solamente lo ya decidido: `string`, literals, UTF-8 válido,
Alias/Transfer/Drop, `+`, `==`/`!=` y `byteLength`. `Text.ScalarOffset` y
`Text.FindResult` son nominales ordinarios de biblioteca.

### 8.2 Primitives privadas mínimas

La implementación Aether de `Text` necesita acceso controlado a la
representación sin exponer bytes como API de usuario. El módulo privado de
soporte ofrece conceptualmente sólo:

```text
textByteAt(ref string value, usize byteOffset) -> byte
copyUtf8ByteRange(
    ref string value,
    usize byteStart,
    usize byteEndExclusive
) -> string
```

`textByteAt` es read-only, non-allocating y no crea un borrow que escape. Su
precondición `byteOffset < byteLength(value)` se verifica en la frontera segura;
la stdlib puede permitir que bounds-check elimination quite comprobaciones
redundantes sólo después de prueba. No es `s[i]` y no está importable por código
ordinario.

`copyUtf8ByteRange` conoce layout y allocation. Comprueba aritmética, orden,
bounds y que ambos extremos sean fronteras UTF-8 antes de publicar el resultado.
Retorna singleton/Alias para vacío/completo y copia exactamente un rango propio.
Recibe byte offsets sólo desde código privilegiado de stdlib; la revalidación de
runtime protege el invariante aunque la biblioteca esté mal compilada.

No se necesita una primitive pública de scanning. Decodificación UTF-8,
resolución scalar↔byte, Two-Way search, trim y split son algoritmos normales
escribibles en Aether sobre esas dos operaciones y `byteLength`. Una primitive
privada posterior de comparación/scanning sólo se justifica por medición y debe
preservar la misma semántica y cotas; no crea un nuevo `StringOp` público.

### 8.3 Representación en IR

Las llamadas `Text.*` se resuelven como calls estáticas ordinarias a funciones
del módulo distribuido:

- HIR conserva la identidad de función, tipos nominales, borrows, ownership de
  resultado, efectos de allocation/trap y spans;
- MIR hace explícitos temporales, List parcialmente inicializado, Transfer y
  cleanup aplicable;
- SSA conserva calls y efectos verificables; inlining o especialización vuelve
  a verificación como cualquier transformación;
- backend baja únicamente las dos primitives privadas y las operaciones core
  de string ya verificadas.

El compilador no incorpora `Contains`, `Find`, `Trim`, `Substring` o `Split` a
`StringOp`. Puede reconocer una función por identidad estable para inline o
const-eval, pero esa optimización no es autoridad semántica y el programa sigue
siendo válido sin ella.

## 9. Módulo y distribución STD

`Text` es un módulo lógico distribuido con la toolchain y versionado por el
manifest de la standard library. No es un objeto global ni requiere module
initialization. Su uso es explícito:

```aether
import Text;

bool present = Text.contains(name, "ae");
Text.FindResult at = Text.find(name, "ther");
```

También puede participar de las formas generales de alias/import selectivo
cuando éstas estén admitidas; no recibe reglas de lookup especiales después de
resolver su `ModuleId`.

La raíz STD es una entrada explícita y read-only del module resolver, posterior
a la resolución de módulos del proyecto pero en un namespace reservado: un
archivo de usuario no puede suplantar el `ModuleId` canónico `std::Text`.
`import Text` selecciona ese módulo canónico; si se desea importar un módulo de
proyecto homónimo debe usarse una identidad/ruta explícita que el sistema de
paquetes defina. Colisiones no se resuelven por orden accidental del filesystem.

Las primitives viven en un módulo interno, provisionalmente
`std::private::TextCore`, ausente del namespace importable y del API manifest.
El build de la toolchain compila `Text` como biblioteca Aether contra el runtime
ABI versionado. El linker incluye sólo cuerpos/helpers alcanzables. Un programa
que no importa/usa `Text` no adquiere código de búsqueda, trim o split.

La versión del módulo, el runtime manifest y el perfil del lenguaje deben ser
compatibles. No hay fallback al intérprete legacy, al host Python ni a libc con
semántica dependiente de plataforma.

## 10. Primer vertical recomendado

**TEXT-V1 — exact scalar-indexed Text** debe admitir como una sola ruta
source→native:

1. resolución del módulo STD canónico `Text`, sin prelude ni shadowing;
2. `ScalarOffset` y `FindResult`, construcción, match y diagnostics;
3. las dos primitives privadas con firmas/efectos verificados;
4. count, contains, startsWith, endsWith, find/findFrom, substring y trim;
5. split exacto a `List<string>` con preservación de vacíos;
6. ownership Alias/fresh y traps exactamente como este documento;
7. O0/O2 sin diferencia observable y ausencia de helpers en programas que no
   usan `Text`.

La qualification mínima debe cubrir ASCII, scalars de dos/tres/cuatro bytes,
combining marks tratados como scalars separados, U+0000, empty haystack,
empty needle, empty separator, match inicial/medio/final/ausente, patrones con
prefijos repetidos adversariales, offsets al inicio/final/fuera de bounds,
rangos invertidos/vacíos/completos, los seis whitespaces ASCII y whitespace
Unicode no recortado.

También debe medir/observar:

- cero allocations y cero Alias para consultas;
- Alias de substring completo y trim sin cambio;
- una copia para substring/trim propios;
- List fresh, payload total copiado y Drops exactos de split;
- comportamiento lineal de búsqueda sobre familias adversariales, sin fijar
  constantes de tiempo;
- traps antes de allocation y corrupción independiente de HIR/MIR/SSA para
  tipos, borrow/result ownership, bounds y efectos;
- cleanup normal, early return y unwind de resultados ya publicados donde el
  modelo general de exceptions lo requiera.

Nada de este plan declara TEXT-V1 implementado.

## 11. Alternativas evaluadas

| Tema | Alternativa | Decisión y motivo |
|---|---|---|
| posiciones | bytes públicos | rechazada: rápidas pero cortan la abstracción textual y se confunden con caracteres |
| posiciones | scalar offsets en `usize` desnudo | rechazada: permite pasar `byteLength` sin señal estática |
| posiciones | grapheme offsets | diferida: requiere segmentación y datos Unicode versionados |
| no encontrado | `-1`/signed index | rechazada: mezcla dominio y obliga conversiones peligrosas |
| no encontrado | `usize.max` o length sentinel | rechazada: magic value; length es match válido para needle vacío |
| no encontrado | nullable/`Option` general | rechazada para este milestone: amplía el lenguaje/biblioteca sin necesidad |
| no encontrado | `FindResult` nominal | elegida: exhaustivo, no ambiguo y sin nullability |
| split vacío | separar cada scalar | rechazada: semántica especial y bordes discutibles |
| split empties | eliminarlos por defecto | rechazada: pierde delimitadores y hace el resultado menos reversible |
| trim | Unicode White_Space | diferida: requiere versión/datos; no debe cambiar silenciosamente con Unicode |
| trim | seis ASCII explícitos | elegida: pequeña, estable, locale-free y compatible con el bootstrap histórico |
| substring | shared view | diferida: requiere lifetime/provenance y puede retener backings grandes |
| búsqueda | opcode por API | rechazada: congela algoritmos de biblioteca en cada fase/backend |
| búsqueda | naive O(H*N) | rechazada: mal worst-case evitable para una API estándar fundamental |

## 12. Decisiones abiertas posteriores

No bloquean TEXT-V1:

- spelling general para extraer el `usize` de nominal wrappers y ergonomía de
  pattern matching importado, sin debilitar `ScalarOffset` a alias transparente;
- una API separada `Text.Unicode.trimWhitespace` y versionado de sus datos;
- iteración pública de string por `char` y cursores reutilizables para varias
  operaciones scalar sin rescans;
- `StringView` una vez que lifetimes/provenance no escapables tengan contrato;
- replace/join, límites de cantidad, split con límite y políticas explícitas de
  filtrado;
- exposición segura de `Bytes`, decode/encode y conversiones;
- si perfiles demuestran beneficio, una primitive privada de scanning o
  vectorización que preserve el contrato lineal y no-allocation;
- packaging/ABI estable de una stdlib precompilada entre versiones de toolchain.

Regex, normalization, graphemes, locale/collation, complex case folding,
formatting/interpolation, hashing y parsing numérico requieren decisiones
independientes; no son extensiones implícitas de esta arquitectura.

## 13. Consecuencias

La API textual usa una unidad inequívoca y segura aunque ubicar una posición
UTF-8 sea O(n). Las consultas no asignan ni adquieren owners. Las operaciones
que materializan contenido retornan strings owned y sólo comparten backing en
casos identidad definidos. `split` conserva información y compone con el
lifecycle ya calificado de `List<string>`.

El runtime conoce layout, bounds de bytes y publicación de un string; la stdlib
conoce algoritmos de texto. Así `Text` puede evolucionar como Aether normal sin
convertir cada operación útil en sintaxis, builtin u opcode del lenguaje.
