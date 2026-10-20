# TEXT-UTF8-BUILDER-V1 — reporte de implementación y qualification

Estado: **CLOSED**, 2026-10-20.

Autoridad normativa:
[TEXT-UTF8-BUILDER-ARCH-1](TEXT_UTF8_BUILDER_ARCH_1.md),
[TEXT-UTF8-BUILDER-ARCH-1-REPORT](TEXT_UTF8_BUILDER_ARCH_1_REPORT.md),
`AETHER_V1_SEMANTIC_CONTRACT`, `TEXT-BYTE-ACCESS`, los verticales GENERAL de
string, `FORMAT-V1` y el lifecycle vigente de exceptions/runtime.

## Superficie pública

Se implementó exactamente la extensión autorizada de `std.Text`:

```aether
public class InvalidUtf8Exception : Exception {
    public init() {}
}

public string fromUtf8(ref Buffer<uint8> bytes, usize length);
```

La API requiere el import ordinario, admite alias y conserva los tipos exactos
del Buffer, borrow, longitud y resultado. No se agregó overload, constructor
raw/unchecked, FFI, allowlist de consumers ni dependencia de graphics/SVG.

## Semántica y frontera runtime

La frontera privada `aether_text_from_utf8_prefix` recibe data, longitud física
y longitud del prefijo. Comprueba primero `length <= buffer_length`; el fallo
termina en el trap `IndexOutOfBounds` sin leer bytes ni crear strings. Un
prefijo vacío se publica mediante `aether_string_from_buffer`, cuyo fast path
devuelve el singleton canónico sin allocation.

Para prefijos no vacíos, la frontera llama una vez al validador general
`aether_utf8_validate`. Sólo después de validar publica un owner mediante
`aether_string_from_buffer`, que reutiliza `aether_string_allocate`, reserva el
layout privado exacto y copia exactamente `length` bytes. El adapter Aether
traduce exclusivamente el status inválido a una instancia nominal de
`std.Text.InvalidUtf8Exception`; bounds, overflow, OOM y corrupción conservan
los traps globales.

La validación acepta únicamente UTF-8 canónico de Unicode scalar values. Se
rechazan continuations aisladas, `C0/C1`, `F5..FF`, truncados, continuations
incorrectas, overlongs, surrogates y valores superiores a U+10FFFF. No hay
normalización ni sustitución U+FFFD. Los bytes posteriores al prefijo no se
leen ni validan, y el Buffer permanece intacto y reusable en todos los paths.

El algoritmo usa una pasada O(n) de validación y una copia O(n), con O(1)
auxiliar fuera del resultado. No hay concatenación incremental, fragments ni
allocations por byte. Los counters califican cero allocations string para
vacío e inválido y exactamente una allocation/un free para éxito no vacío.

## Validador compartido y reachability

Se extrajo el validador que estaba ligado a Process a un módulo runtime general.
Process, `IO.readLine`, `IO.readText` y `std.Text.fromUtf8` llaman la misma
definición privada. Cuando más de una frontera es alcanzable, el artefacto
contiene una única definición de `aether_utf8_validate`; ya no existen copias
`aether_process_utf8` ni `aether_io_utf8`.

La reachability se decide con `FunctionInstanceInfo`, package canónico con
origin Toolchain y firma exacta. Importar `std.Text` sin usar `fromUtf8` no emite
el adapter, la frontera, el validador por esta causa, el allocator de la nueva
exception ni su descriptor. Una función homónima de usuario no recibe ningún
privilegio.

## Lowering, ownership y exceptions

El resolver especial de Text delega `fromUtf8` al catálogo ordinario de
overloads. HIR, MIR y SSA muestran una call directa, el shared borrow del
Buffer, el resultado owning, el successor excepcional, `EndBorrow` y el Drop
del resultado en sus paths correspondientes. No existe `TextOp::FromUtf8`.

La qualification del nuevo path reveló que la propagación final de una
exception podía alcanzar `ResumeUnwind` o `ForwardUnwind` con owners vivos. El
lowering MIR ahora emite sus drops condicionales en orden inverso antes de esas
terminaciones cuando no hay `finally`. Esto conserva el string publicado si
una call posterior lanza y elimina cualquier owner parcial en el path
excepcional; las suites completas de exceptions y ownership permanecen verdes.

Los gates de corrupción alteran por separado operandos, retorno, metadata de
borrow, Drop y successor excepcional en MIR/SSA. Los verificadores rechazan
cada variante.

## Qualification

Se agregó
`compiler-next/crates/aether-driver/tests/text_utf8_builder_v1.rs` y la fixture
`compiler-next/tests/programs/text_utf8_builder_v1_smoke.ae`. Los ocho tests
ejecutan source-to-native en O0/O2 y cubren:

- vacío, ASCII, secuencias de 2/3/4 bytes y todos los extremos normativos;
- emoji, combining marks sin normalización, BOM, TAB, CR, LF y NUL;
- prefijo válido con garbage posterior, corte dentro de secuencia y bounds;
- Buffer dinámico grande, `byteLength`/`byteAt` exactos e independencia después
  de mutar o destruir el Buffer;
- toda la matriz inválida, catch nominal, Buffer reusable y diagnóstico no
  capturado con identidad `std.Text`;
- allocation/free exactos, ausencia de owner parcial, concat y allocations en
  el validador;
- call ordinaria y lifecycle visibles en HIR/MIR/SSA, reachability negativa,
  identidad canónica y singleton del validador compartido;
- rechazo de API mal tipada, homónimos y acceso a constructores raw inventados.

## Validación final

Ejecutado en `compiler-next` salvo donde se indica:

```text
cargo test -p aether-driver --test text_utf8_builder_v1
  PASS: 8 passed
cargo test -p aether-driver --test text_byte_access_v1
  PASS: 6 passed
cargo test -p aether-driver --test text_v1
  PASS: 8 passed
cargo test -p aether-driver --test general_v1_string
  PASS: 7 passed
cargo test -p aether-driver --test general_v2_string_composition
  PASS: 6 passed
cargo test -p aether-driver --test format_v1
  PASS: 10 passed
cargo test -p aether-driver --test process_args_v1
  PASS: 9 passed
cargo test -p aether-driver --test io_v1
  PASS: 12 passed
cargo test -p aether-driver --test exception_v4
  PASS: 7 passed
cargo test --workspace
  PASS
cargo fmt --all --check
  PASS
cargo clippy --workspace --all-targets -- -D warnings
  PASS
bash compiler-next/tests/run-differential.sh
  PASS: checked=21 failures=0
git diff --check
  PASS
```

No se modificó productivamente `graphics`.

CLOSED
