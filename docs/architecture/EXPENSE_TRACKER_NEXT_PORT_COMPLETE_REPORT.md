# Expense Tracker: port completo a `compiler-next`

Estado: **implementado y calificado**, 2026-09-22.

## Resultado

`examples/expense_tracker/main.ae` implementa la aplicación persistente completa
del Expense Tracker sobre la superficie pública actual de `compiler-next`:

```text
<ledger.alpt> add <expense|income> <id> <amount> <category> <description> <date>
<ledger.alpt> list
<ledger.alpt> summary
```

Las invocaciones se ejecutan como procesos separados y comparten únicamente el
ledger ALPT1. Un path inexistente se interpreta como ledger vacío; una carga
corrupta se rechaza fail-closed; `add` publica mediante
`std.File.writeTextAtomic` sólo después de decodificar y validar el estado
anterior completo.

No se agregó ninguna feature de lenguaje, stdlib o runtime.

## Nueva auditoría legacy frente a `compiler-next`

| Superficie legacy | Clasificación final | Resolución |
| --- | --- | --- |
| `from X import Y`, `public`, packages cortos | 2. Spelling distinto | `import expense_tracker.*` y nombres calificados. |
| `System.args()` | 2. Spelling distinto | `std.Process.args()`. |
| `parseInt` / `parseDouble` globales y `ParseStatus` | 2. Spelling distinto | `std.Text.parseInt` / `parseDouble` y `match` exhaustivo sobre sus enums de resultado. |
| `.trim()`, `.byteLength`, métodos de `List` | 2. Spelling distinto | `std.Text.trim`, `byteLength`, `length` y `push`. |
| Iteración owning de `Transaction` | 1. Diferencia semántica/API | `for (ref Transaction value in list)` para elementos non-Copy. |
| Assignment/parameters legacy con aliasing de `List` | 1. Diferencia semántica/API | Ownership exclusivo; `Ledger` se mueve o se presta con `ref`/`ref mut`. |
| Igualdad de enums | 1. API soportada | Comparación directa con `==`/`!=`. |
| `println(a, b, ...)` | 2. Spelling distinto | Un único string compuesto con `+`, `str` o interpolación soportada. |
| Codec ALPT1 byte-framed | 1. API soportada | `std.Text.byteAt`, `byteSlice`, `parseInt` y `parseDouble`. |
| `io.readText` / status | 1. API distinta | `std.File.readText` con exceptions nominales mapeadas a `LedgerStatus`. |
| `io.writeTextAtomic` / status | 1. API distinta | `std.File.writeTextAtomic` con exceptions nominales y publicación atómica. |
| `appendText` de `persist-check` | 3. Feature ausente, no esencial | Se omite el helper; los comandos reales no usan append. |
| `copy`, slicing, `contains`, `indexOf` del demo | 3. Features ausentes, no esenciales | Se omiten checks de dogfood sin impacto en la app persistente. |
| Composición larga de strings | 5. Posible con ergonomía incómoda | El writer ALPT1 y las líneas de reporte se construyen incrementalmente. |
| Parámetros owning con múltiples early returns | 4. Bug/regresión de SSA evitable | El verificador rechazaba owners no consumidos; los helpers naturalmente observadores usan `ref` y el mutador usa `ref mut`. No se cambió el compilador. |
| Argumentos tras `aether-next run ... --` | 4. Bug de integración | El runtime y `std.Process.args` ya estaban soportados, pero el driver rechazaba `--`. El driver ahora reenvía los argumentos al artifact nativo. |

La nueva auditoría no encontró una feature estructural ausente que impidiera el
port natural. Los cuatro blockers del informe inicial —argv, parsing numérico,
framing byte-based y escritura atómica— ya estaban implementados antes de este
trabajo.

## Cambios de source

- `Main.ae` fue sustituido por el entry canónico lowercase `main.ae` con
  `int main()` y CLI estricta.
- `Transaction.ae` define el enum, la transacción owning y `Ledger`.
- `Ledger.ae` encapsula el alta y rechaza montos no positivos o no finitos.
- `Reports.ae` resume e itera por referencia sin clonar transacciones.
- `Persistence.ae` adapta el codec validado por
  `expense_tracker_alpt1_codec_v1` y agrega wrappers reales de load/save.
- El README documenta el comando `compiler-next`, códigos de salida y garantías.
- `aether-next run` acepta `-- args...` y los pasa al proceso compilado; el API
  existente `run_path` conserva compatibilidad y delega en
  `run_path_with_arguments`.

## Persistencia ALPT1

El port reutiliza el codec ya calificado, no una reimplementación line-based.
Conserva los seis fields `id`, `type`, `amount`, `category`, `description` y
`date`, longitudes en bytes UTF-8, payloads con espacios, `:`, LF, CRLF y NUL,
orden libre de fields al leer, extensions desconocidas válidas, límites de
recursos y output canónico al escribir.

El decoder acumula en un ledger staged y sólo lo devuelve tras validar records,
`end-file` y EOF exacto. En cualquier error devuelve un ledger vacío con status
y offset. La CLI nunca guarda después de una carga fallida.

`writeTextAtomic` reemplaza el nombre de forma atómica. Esto no promete
durabilidad ante power loss: no hay `fsync`, locking, backup, CAS ni preservación
de metadata; writers concurrentes siguen last-successful-rename-wins.

## CLI y dominio

La CLI exige aridad exacta y distingue uso/dominio (`2`), carga/formato (`3`) y
guardado (`4`). IDs con formato inválido u overflow se rechazan. Amounts con
formato inválido, overflow, underflow, NaN, infinito, cero o signo negativo se
rechazan. Los strings del dominio no se recortan ni reinterpretan; sólo ID y
amount aplican `std.Text.trim`, igual que la política legacy.

## Funcionalidad legacy omitida deliberadamente

- El demo in-memory sin argumentos y sus assertions de collections.
- `split-check`, que era una inspección aislada de `split`.
- `persist-check`, que ejercitaba `appendText` sobre un archivo auxiliar ajeno al
  ledger.
- `filterByType`, usado sólo por el demo histórico.

Ninguna omisión afecta `add`, `list`, `summary`, ALPT1 ni la persistencia entre
procesos. No se recrearon `System`, imports selectivos, aliases legacy de
`List`, output variádico ni script mode.

## Qualification end-to-end

`expense_tracker_next_port_complete.rs` compila el ejemplo en O0 y O2 y lanza
procesos nativos separados para cubrir:

- ledger inicialmente ausente y consultas vacías;
- múltiples `add` seguidos de `list` y `summary`;
- overwrite atómico real (contenido e inode nuevos);
- UTF-8 multibyte, emoji, espacios, `:` y LF dentro de argumentos;
- ids y amounts válidos, inválidos y con overflow;
- CLI incompleta, argumentos sobrantes, tipo y comando desconocidos;
- ALPT1 corrupto rechazado sin sobrescritura;
- fallo pre-publish inyectado en `renameat`, exit `4` y preservación byte a byte
  del ledger anterior;
- forwarding real de `aether-next run ... -- args...`.

Resultado específico del port:

```text
cargo test -p aether-driver --test expense_tracker_next_port_complete
3 passed; 0 failed
```

También se ejecutó manualmente el comando público:

```text
aether examples/expense_tracker/main.ae --compiler next -- ledger.alpt summary
income: 0
expenses: 0
balance: 0
```

La validación global de cierre incluye `cargo test --workspace`,
`cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
`git diff --check` y `bash compiler-next/tests/run-differential.sh`.

## Conclusión de madurez

El port demuestra que `compiler-next` ya puede sostener una aplicación modular
pequeña pero real: dominio owning, listas de structs con strings, enums,
iteration por borrow, parsing checked, framing byte-based, exceptions de IO,
argv real y publicación atómica. La principal fricción restante no es una
ausencia funcional sino ergonomía y robustez del ownership en helpers con
control flow: pasar aggregates owning por valor puede exponer una regresión SSA
que los borrows explícitos evitan. El gap del driver para argv era pequeño pero
end-to-end crítico y quedó cubierto sin ampliar el lenguaje ni el runtime.
