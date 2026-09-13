# TEXT-V1 — exact scalar-indexed Text

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-12, para el backend nativo
bootstrap Linux x86-64 de `compiler-next`, bajo el contrato de
[TEXT-ARCH-1](TEXT_ARCH_1.md).

## Módulo STD y tipos

`import Text` resuelve una entrada canónica read-only distribuida por el driver.
La resolución intercepta la identidad reservada antes de consultar el filesystem
del proyecto, por lo que un `Text.ae` vecino no puede suplantarla. Importar sigue
siendo explícito y no agrega prelude ni inicialización de módulo.

El módulo declara los nominales ordinarios `Text.ScalarOffset`, representado por
un `usize`, y `Text.FindResult`, con variantes `Found(ScalarOffset)` y
`NotFound`. `Text.scalarOffset` construye únicamente el wrapper; bounds se
validan al usarlo contra un string. Ambos tipos conservan identidad nominal en
HIR, MIR, SSA y layout LLVM.

## Búsqueda y consultas

`codePointCount` cuenta bytes iniciales de scalars UTF-8 y trata combining marks
como scalars independientes. `contains`, `startsWith`, `endsWith`, `find` y
`findFrom` son exactos, case-sensitive y sin normalización. Needle vacío sigue
las reglas de TEXT-ARCH-1 y no encontrado construye `FindResult.NotFound`.

La búsqueda bytewise es segura por el invariante UTF-8 canónico. El perfil
Linux usa `memmem` de glibc: su implementación selecciona búsqueda Two-Way para
el caso general y conserva worst-case lineal, sin tabla heap ni búsqueda naive
`O(H*N)`. El byte encontrado se convierte a offset scalar antes de publicar el
resultado. Las consultas no llaman allocator ni retain.

## Substring y trim

`substring` compara primero `start <= endExclusive`, resuelve ambas fronteras
scalar recorriendo UTF-8 y sólo entonces materializa el rango. Offset fuera del
texto produce `TextPositionOutOfBounds`; rango invertido produce
`InvalidTextRange`. Vacío usa el singleton, rango completo hace Alias y un rango
propio no vacío realiza una allocation exacta y una copia.

`trim` reconoce únicamente space, tab, LF, CR, form feed y vertical tab ASCII.
NBSP y los demás whitespaces Unicode se conservan. Identidad, todo-vacío y rango
propio siguen respectivamente Alias, singleton vacío y copia fresh.

## Split

`split` hace dos pasadas lineales de matches exactos, izquierdos y no solapados:
la primera calcula con aritmética checked el número de slots y la segunda
publica cada string owner. Siempre crea un `List<string>` fresh; conserva
fragmentos iniciales, finales y adyacentes vacíos. Sin match, el único elemento
es Alias del source; fragmentos propios no vacíos se copian una sola vez y los
vacíos usan el singleton. Separador vacío toma `EmptyTextSeparator` antes de
allocation.

El Drop estructural existente de `List<string>` destruye el prefijo publicado
en orden inverso y cada obligación string exactamente una vez. Returns normales,
early returns y landing pads reutilizan el cleanup general de GENERAL-V2.

## Ownership y allocation

Los inputs string de todas las operaciones se bajan como lecturas borrowed: no
se crea Alias para lvalues. Un string temporal permanece owned durante la
operación y se destruye después. `FindResult` y `ScalarOffset` son Copy. Los
resultados de substring/trim y cada elemento de split usan las decisiones
Alias/fresh descritas arriba; `List<string>` siempre es un owner fresh.

La instrumentación privada de GENERAL-V1 sigue observando allocation, retain,
release y free. Las consultas tienen cero allocation/retain; materialización y
cleanup conservan balance exacto tanto en O0 como en O2.

## Primitives privadas

La frontera de representación agrega solamente:

```text
textByteAt(ref string, usize) -> byte
copyUtf8ByteRange(ref string, usize, usize) -> string
```

Ambas se emiten como símbolos LLVM `internal`. La primera comprueba bounds y no
asigna. La segunda comprueba orden, bounds y fronteras UTF-8 antes de publicar,
aplicando los fast paths vacío/completo y copiando rangos propios. No son
importables, no habilitan `s[i]` y no aparecen como `StringOp` públicos.

## HIR, MIR, SSA, runtime y backend

`TextOp<O>` conserva la identidad cerrada de cada llamada STD separada de
`StringOp<O>`, operandos borrowed, tipos/resultados nominales y efectos owning.
HIR rechaza módulo, aridad y tipos incorrectos. MIR hace explícitos temporales,
Transfer y Drop y reconstruye el ledger de owners. SSA vuelve a validar tipos,
dominancia, consumos y resultados; O2 reusa la reverificación existente.

El backend sólo acepta SSA verificada. Los cuerpos internos implementan decode,
scalar↔byte, comparación, búsqueda, trim y split y consumen las dos primitives
de representación. Un programa sin una operación `Text` no emite ningún símbolo
`aether_text_*`; importar el módulo sin usarlo tampoco selecciona helpers.

## Qualification y corrupciones

`text_v1_smoke.ae` y `text_v1.rs` cubren en O0/O2:

- UTF-8 de uno, dos, tres y cuatro bytes, combining mark y U+0000;
- haystack/needle vacíos; matches inicial, medio, final, ausente y desde final;
- substring vacío, completo y propio; rangos invertidos y offsets fuera de bounds;
- los seis bytes trim y NBSP no recortado;
- split inicial/final/adyacente, sin match y separador vacío;
- patrón repetitivo adversarial de 20.001 bytes;
- construcción y match nominal de `ScalarOffset`/`FindResult`;
- shadowing por archivo de usuario y ausencia de helpers sin uso;
- lifecycle normal de strings y `List<string>` y traps fail-fast.

Los verificadores HIR/MIR/SSA reconstruyen el contrato cerrado de operandos y
resultado de `TextOp`; las suites generales continúan corrompiendo ownership,
Drop, CFG y unwind de strings/colecciones independientemente. La qualification
de cierre ejecuta la workspace completa, fmt, clippy con warnings como errores,
`git diff --check` y el differential nativo.

## O0/O2 y deuda restante

O0 y O2 producen los mismos resultados, traps y balances de ownership; O2 no
cambia unidades, equivalencia Unicode ni reglas de Alias. La búsqueda general
depende por ahora del `memmem` lineal del perfil glibc calificado; portar el
runtime a otro libc/target exige seleccionar o incluir una implementación
Two-Way equivalente y recalificarla.

Siguen fuera, sin stubs ni reservas nuevas: regex, `StringView`, indexing o
slicing sintáctico, iteración pública, `Bytes`, formatting/interpolation,
normalización/graphemes, case folding/collation, parsing numérico, hashing y
builders públicos. Tampoco se estabiliza ABI/package binario de stdlib.
