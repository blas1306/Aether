# EXPENSE-TRACKER-ALPT1-CODEC-V1

Estado: **implementado**, 2026-09-22.

## Resultado

El formato persistente ALPT1 del Expense Tracker ya puede codificarse y
decodificarse enteramente en source Aether admitido por `compiler-next`. El
vertical está en
`compiler-next/tests/modules/expense_tracker_alpt1_codec_v1/`: `model.ae`
define el dominio mínimo, `codec.ae` contiene el codec puro y `main.ae` es el
fixture ejecutable. No se portaron la CLI, argv, load/save, append ni la
publicación atómica.

No fue necesario cambiar el lenguaje, la biblioteca estándar, el runtime ni
ninguna fase del compilador. Tampoco apareció un blocker nuevo de
`compiler-next`.

## Formato preservado

El writer conserva el wire format ALPT1 revision 1:

```text
AETHER-PERSISTENCE LF
format-version 1 LF
application aether.expense-tracker LF
schema expense-ledger LF
schema-revision 1 LF
schema-min-reader 1 LF
record-count N LF
end-header LF
record transaction F LF
field NAME TYPE BYTE_LENGTH LF
PAYLOAD LF
...
end-record LF
end-file LF
```

`fieldFragment` obtiene `BYTE_LENGTH` con `byteLength`; ids, counts, lengths y
amounts se emiten con `str(int)`, `str(usize)` y `str(double)`. Un fixture
compara el resultado completo contra bytes ALPT1 canónicos y comprueba, por
ejemplo, que `é` ocupa 2 bytes aunque sea un único scalar.

Como exige este vertical, el codec conserva amounts finitos positivos y
negativos. La restricción de dominio de la aplicación legacy que sólo permitía
amounts positivos pertenece a `addTransaction`/CLI y no se trasladó al codec
puro. Esto permite demostrar la preservación de `double` sin incorporar la
aplicación completa.

## Decoder byte-based y fail-closed

El decoder mantiene un único cursor `usize` sobre offsets de bytes. Las líneas
de control se encuentran recorriendo `std.Text.byteAt`; sus rangos se comparan
sin `substring`, `split` ni `lines`. Los payloads se extraen exclusivamente con
`std.Text.byteSlice(start, end)`, que hace recuperable un corte dentro de un
code point UTF-8. Los enteros y doubles se convierten únicamente mediante
`std.Text.parseInt` y `std.Text.parseDouble`.

El cursor nunca retrocede y cada byte de framing/payload se consume una vez;
las búsquedas auxiliares se limitan a tokens de control o a los 64 fields
admitidos por record. El recorrido del input es O(n), con límites legacy de
10.000 records, 64 fields y 1 MiB por payload.

La publicación es transaccional en memoria: cada `Transaction` se agrega a una
lista `staged`, pero cualquier error devuelve un `Ledger` nuevo y vacío. La
lista sólo forma parte del resultado exitoso después de validar todos los
records, `end-file` y EOF exacto. Por tanto, trailing garbage o corrupción
tardía no exponen un ledger parcialmente válido.

Se conservan fields aditivos desconocidos con nombres/tipos válidos, el orden
libre de fields, headers `optional-*` y el rechazo de duplicados. Los seis
fields conocidos siguen siendo obligatorios. El writer continúa siendo
canónico y siempre emite exactamente esos seis fields en el orden legacy.

## Qualification

El fixture ejecutable cubre en O0 y O2:

- ASCII, `é`, `λ`, emoji y longitudes UTF-8 en bytes;
- strings vacíos, espacios, `:`, LF, CRLF y NUL dentro de payloads;
- tres transactions y round-trip `encode -> decode -> encode`;
- ids `int64` mínimo/máximo;
- amounts positivos y negativos, `f64::MAX` y el menor normal positivo;
- fields reordenados, field aditivo desconocido y header opcional;
- longitud no numérica, overflow de longitud, payload truncado y corte dentro
  de un code point;
- delimitador ausente, integer inválido, overflow/underflow de double, field
  count inconsistente, duplicados, trailing garbage y delimitadores internos
  válidos.

La integración
`compiler-next/crates/aether-driver/tests/expense_tracker_alpt1_codec_v1.rs`
compila y ejecuta el corpus en ambos niveles de optimización. También verifica
que HIR, MIR y SSA contienen `ByteAt`, `ByteSlice`, `ParseInt` y `ParseDouble`,
y que el source no usa las alternativas prohibidas ni APIs fuera de scope.

Validación de cierre:

```text
cargo test --workspace                                      pass
cargo fmt --all --check                                     pass
cargo clippy --workspace --all-targets -- -D warnings       pass
git diff --check                                            pass
bash compiler-next/tests/run-differential.sh                pass
```

## Scope deliberadamente no implementado

Este vertical no introduce `std.Process.args`, `writeTextAtomic`, `appendText`,
load/save de archivos ni comandos `add|list|summary`. No reemplaza ALPT1 por
JSON, CSV o framing por líneas y no accede a helpers privados del runtime. El
port completo del ejemplo permanece separado hasta que se aborden, en sus
propios milestones, argv y publicación atómica.
