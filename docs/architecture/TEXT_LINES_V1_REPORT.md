# TEXT-LINES-V1 — owning line decomposition

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-15, para el backend nativo
bootstrap Linux x86-64 de `compiler-next`.

## Superficie pública

La única API agregada es:

```aether
std.Text.lines(ref string text) -> List<string>
```

Requiere `import std.Text`. BORROW-ERGONOMICS-V1 adapta naturalmente un lvalue,
literal o temporal, por lo que la forma habitual es
`List<string> lines = std.Text.lines(text);`, sin `&`. El borrow compartido dura
sólo la llamada. No se agregaron overloads, métodos de `string`, views,
iteradores ni tipos públicos.

## Semántica cerrada

`lines` reconoce LF (`U+000A`) y CRLF como terminadores. No incluye sus bytes en
los strings resultantes. CR sólo participa en un terminador cuando está
inmediatamente antes de LF; en cualquier otra posición se conserva. U+0085,
U+2028, U+2029 y los demás separadores Unicode son contenido ordinario en V1.

La tabla normativa es:

| Input | Resultado |
|---|---|
| `""` | `{}` |
| `"a"` | `{"a"}` |
| `"a\nb"` | `{"a", "b"}` |
| `"a\nb\n"` | `{"a", "b"}` |
| `"\n"` | `{""}` |
| `"\n\n"` | `{"", ""}` |
| `"a\n\nb"` | `{"a", "", "b"}` |
| `"a\r\nb\r\n"` | `{"a", "b"}` |

El terminador final no representa otra línea posterior y por eso no genera un
fragmento vacío adicional. Los terminadores iniciales o consecutivos sí
representan líneas vacías reales y se preservan. Esta regla no modifica
`std.Text.split`: `split("a\n", "\n")` continúa devolviendo
`{"a", ""}`.

## Representación e implementación

HIR incorpora la operación cerrada `TextOp::Lines`; MIR y SSA conservan su
identidad, call site, borrow y resultado owning. Los verificadores reconstruyen
un único operando `ref string` y un resultado `List<string>`. `creates_owner`
incluye la operación, de modo que se reutilizan Transfer, Drop, cleanup de
colecciones y landing pads existentes.

El backend baja la operación a `aether_text_lines`, un helper LLVM `internal`.
La primera pasada cuenta LF y determina si existe tail después del último
terminador; la segunda publica cada rango. Un CR inmediatamente anterior a LF
se resta del extremo del rango. La copia pasa por
`aether_text_copy_range`, que ya valida fronteras UTF-8 y aplica los fast paths
de singleton vacío, Alias de rango completo y copia fresh. El descriptor final
es la representación ordinaria `{storage, length, capacity}` de `List<string>`;
el input vacío usa el descriptor cero y no asigna storage.

El algoritmo es O(n) en tiempo, O(k) en slots para k líneas y no interpreta NUL
como terminador. Como LF y CR son ASCII, nunca coinciden dentro de una secuencia
UTF-8 multibyte válida. La aritmética del número y tamaño de slots conserva los
checks de overflow del runtime Text/List.

## Ownership, cleanup y unwind

El input sólo se lee durante la call. Cada elemento publicado posee exactamente
una obligación string: rangos propios son allocations fresh, el rango completo
es un Alias retenido y los vacíos usan el singleton inmortal. El Drop estructural
de `List<string>` libera el prefijo inicializado y su storage por las rutas
generales. Early return y exception unwind usan los mismos cleanup plans; no se
introdujo manejo de memoria paralelo.

La qualification instrumenta contadores de allocation/free de heap y strings y
exige balance cero al terminar, tanto normalmente como después de lanzar con la
lista viva. Esto detecta leaks y dobles drops junto con los verificadores de
ownership existentes.

## Qualification

La cobertura nativa ejecuta en O0 y O2:

- todos los ejemplos normativos;
- LF y CRLF mezclados, terminadores finales y líneas vacías internas;
- CR aislado y U+2028 conservados como contenido;
- UTF-8 multibyte y U+0000 dentro de líneas;
- `std.Text.lines(text)` mediante implicit shared argument borrow;
- resultado owning, Drop normal y cleanup durante unwind;
- regresión explícita de `std.Text.split` con fragmento final vacío;
- presencia de `Lines` en HIR/MIR/SSA y helper interno alcanzable en LLVM.

La qualification de cierre ejecuta `cargo test --workspace`, `cargo fmt
--all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
`git diff --check` y `tests/run-differential.sh`.

## Exclusiones

TEXT-LINES-V1 no agrega lectura streaming, conservación de terminadores,
normalización de newline, Unicode line breaking, iteración lazy, views ni una
API configurable. Cualquier extensión requiere otro contrato.
