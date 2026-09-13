# TEXT-ARCH-1 — report

Estado: **DISEÑO CERRADO; TEXT-V1 IMPLEMENTADO**, 2026-09-12. Documento
completo: [TEXT_ARCH_1](TEXT_ARCH_1.md). Qualification:
[TEXT_V1_REPORT](TEXT_V1_REPORT.md).

## API propuesta

El módulo estándar explícito `Text` ofrece:

```text
codePointCount, contains, startsWith, endsWith,
find, findFrom, substring, trim, split -> List<string>
```

Todas las entradas string son borrows shared. La comparación y búsqueda son
exactas, case-sensitive y sin normalización. `Text` también define el nominal
`ScalarOffset`, su constructor `scalarOffset(usize)` y
`FindResult = Found(ScalarOffset) | NotFound`.

## Unidades e índices

Las posiciones públicas son offsets desde cero en Unicode scalar values; los
rangos son semiabiertos `[start, endExclusive)`. `ScalarOffset` evita confundir
una posición textual con `byteLength`. Los byte offsets son exclusivamente
privados. Resolver offsets y contar scalars recorre UTF-8; no se añade cache ni
index table al objeto string.

`find`/`contains` garantizan O(H+N) worst-case, O(1) auxiliar y cero allocation.
`substring` cuesta O(bytes recorridos + bytes copiados). `trim` y `split` son
lineales en bytes; split copia como máximo una vez el payload de los fragmentos.

## Core/runtime frente a stdlib

El core público no crece: conserva `string`, literals, lifecycle, concat,
igualdad y `byteLength`. `Text.*` son llamadas estáticas ordinarias del módulo
`std::Text`, no miembros mágicos ni nuevos `StringOp`.

La frontera privada mínima aporta acceso borrowed a un byte y copia validada de
un rango de bytes UTF-8. Count, conversión scalar↔byte, búsqueda lineal, trim y
split se escriben como Aether normal. HIR/MIR/SSA conservan call, borrow,
allocation, trap y ownership; una optimización puede inlinear sin convertirse
en autoridad semántica.

`import Text` resuelve el módulo canónico distribuido y versionado con la
toolchain. No hay prelude, shadowing por filesystem, module initialization ni
fallback al intérprete/host. Sólo código y helpers alcanzables se enlazan.

## Ownership y allocation

- Count y búsquedas no asignan ni hacen Alias.
- Substring propio no vacío y trim cambiado producen fresh string por copia.
- Substring completo y trim sin cambios pueden retornar Alias owned del source.
- Resultados vacíos usan el singleton vacío.
- Split siempre produce un List fresh; fragmentos propios son fresh, el único
  fragmento sin match puede ser Alias y vacíos usan el singleton.

String sigue siendo inmutable, no-Copy y sin views/COW. Alias, Transfer y Drop
mantienen las obligaciones de GENERAL-V1/V2.

## Errores, bounds y casos vacíos

`findFrom` acepta posiciones hasta el final inclusive. `substring` exige
`start <= endExclusive <= codePointCount`. Violaciones producen los traps
fail-fast `TextPositionOutOfBounds` o `InvalidTextRange`, antes de allocation.
No encontrado es `NotFound`, no null, `-1` ni sentinel.

Needle vacío está contenido, es prefix/suffix y `find` lo encuentra en cero;
`findFrom` lo encuentra en `start`. Separator vacío produce
`EmptyTextSeparator`. Split hace matches no solapados de izquierda a derecha y
conserva vacíos, incluido `split("", ",") == {""}`.

`trim` usa de forma estable sólo ASCII space, tab, LF, CR, form feed y vertical
tab. No elimina Unicode whitespace ni depende de locale/versiones Unicode.

## Primer vertical

`TEXT-V1 — exact scalar-indexed Text` debe entregar en una ruta nativa el módulo
STD, tipos nominales, dos primitives privadas, toda la API anterior y split con
`List<string>`. Qualification debe cubrir UTF-8 de 1–4 bytes, combining marks,
NUL, vacíos, bounds, patrones adversariales, ownership/allocation, traps,
cleanup, O0/O2, verificadores HIR/MIR/SSA y ausencia de helpers sin uso.

## Decisiones abiertas

Quedan para trabajos separados: ergonomía general de nominal wrappers,
iteración/cursors, `Text.Unicode.trimWhitespace` con datos versionados,
`StringView`, Bytes/decode, replace/join y variantes limitadas de split,
primitive privada vectorizada basada en perfiles y ABI/package estable de
stdlib. Regex, graphemes, normalization, locale/collation, case folding
complejo, formatting, builders públicos, hashing y parsing numérico continúan
fuera de alcance.
