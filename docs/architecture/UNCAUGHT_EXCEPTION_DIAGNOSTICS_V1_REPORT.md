# UNCAUGHT-EXCEPTION-DIAGNOSTICS-V1 — concrete nominal root report

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-15, para el bootstrap nativo
Linux x86-64 de `compiler-next`, bajo el contrato de
[UNCAUGHT-EXCEPTION-DIAGNOSTICS-ARCH-1](UNCAUGHT_EXCEPTION_DIAGNOSTICS_ARCH_1.md).

## Resultado

Una excepción Aether que abandona `main` escribe exclusivamente en stderr:

```text
Unhandled <tipo-nominal-dinámico-con-package>\n
```

y termina con status 70. La qualification fija byte por byte
`std.File.FileNotFoundException`, `std.IO.InvalidTextEncodingException`, una
clase de package de proyecto nombrado, una clase del package anónimo y una
instancia derived lanzada mediante un owner de base. Una excepción capturada no
produce salida; bare rethrow conserva el mismo tipo concreto; un retorno normal
de 70 conserva stderr vacío y queda distinguido por canal.

El display se construye una vez durante codegen desde `ClassInfo.module/name` y
`ModuleInfo.key.package`. `PackageKey::Named` usa `PackagePath.source()` más el
nombre de clase; `PackageKey::Anonymous` usa sólo el nombre de clase. La raíz
Core inyectada se trata explícitamente como `Exception`. No participan
`ModuleInfo.display_name`, origin Project/Toolchain, mangling, logical/source
path, filename ni CWD.

## Descriptor y ABI privado

El descriptor de toda clase emitida tiene ahora este prefijo uniforme:

```text
slot 0: destroy_fn
slot 1: diagnostic_type*
slot 2...: virtual targets
después: interface witnesses
```

Cada `diagnostic_type` es una constante privada `{bytes*, byte_length}` y sus
bytes nominales son otra constante privada sin terminador requerido. El header
del objeto permanece `{strong_count, class_descriptor*}` y el handle continúa
siendo un puntero: se agregan cero bytes por instancia. La metadata no es
source-addressable, no participa en matching/casts/dispatch y no enumera ningún
otro dato; no se agregó reflection.

Los offsets físicos quedaron centralizados en el módulo de clases: offset del
descriptor dentro del objeto, slots destroy/diagnostic, base de virtuales, base
de witnesses, drop de witness y métodos de witness. Emisión y cargas comparten
esas funciones. Las suites OOP-V2/V3/OPT/POLISH califican que dispatch virtual,
witnesses, devirtualización y destrucción dinámica siguen coherentes después
del nuevo slot.

## Reporter y root

El landing pad del wrapper nativo `main` sigue siendo el único root boundary.
Después de `__cxa_begin_catch`, toma prestado el payload vivo, carga su descriptor
dinámico y la metadata, concatena los tres slices estáticos `"Unhandled "`,
nombre y LF, y recién entonces ejecuta una vez `__cxa_end_catch`. No hay release
manual: el destructor del record conserva la única liberación del payload.

`aether_report_unhandled` y su primitive privada `write_all` son `nounwind`, no
asignan, no crean strings Aether, no llaman a `std.IO` y escriben length-aware
al fd 2. El loop completa short writes, consulta errno y reintenta `EINTR`; cero
progreso o error terminal corta el resto best-effort. En todos esos casos el
root termina el evento y retorna 70, sin fallback a stdout.

La ruta exception-free continúa sin personality, `__cxa_*`, reporter ni metadata
diagnóstica de clases. Traps conservan sus terminadores fail-fast y nunca entran
en catch ni en el reporter.

## Composición con `finally`

La qualification root descubrió que un `try/finally` sin catches marcaba su
landing pad intermedio como catcher físico por la mera existencia del contexto
de finalización. Al reanudar hacia el root podía volver a seleccionar ese mismo
frame. `HandlerContext` conserva ahora si existen cláusulas catch reales y sólo
en ese caso emite `catch ptr null`; un finally-only usa un cleanup landing pad.

Esto no cambia la superficie ni el protocolo de `finally`: el mismo evento se
guarda, atraviesa una vez la región compartida y se reanuda. El caso nativo O0/O2
observa stdout producido antes del throw, completa el finally y luego obtiene el
diagnóstico root exacto. Toda la suite EXCEPTION-V4 permanece verde.

## Qualification

La suite nueva
`compiler-next/crates/aether-driver/tests/uncaught_exception_diagnostics_v1.rs`
cubre:

- nombres STD, named, anonymous y derived dinámico en O0/O2;
- caught sin salida, bare rethrow uncaught y finally antes del root;
- stdout intacto, stderr byte-exacto, un LF y status 70;
- retorno ordinario 70 con ambos canales vacíos;
- metadata estática, header/size de objeto sin crecimiento y loads desde el
  descriptor dinámico;
- reporter sin allocation/string/`std.IO` y ausencia completa en un programa
  exception-free;
- `EINTR`, writes de un byte, error terminal tras prefijo parcial y ausencia de
  fallback;
- report antes de cleanup, un solo `__cxa_end_catch`, release/destroy únicos y
  balance heap cero después de terminar el evento;
- metadata diagnóstica nula inyectada que falla fast sin convertirse en una
  excepción; las corrupciones MIR/SSA vigentes continúan rechazando disposición
  inválida del evento.

Resultados finales:

| Comando | Resultado |
| --- | --- |
| `cargo test --workspace` | 491 passed, 0 failed, 0 ignored |
| `cargo fmt --all --check` | pass |
| `cargo clippy --workspace --all-targets -- -D warnings` | pass |
| `git diff --check` | pass |
| `bash compiler-next/tests/run-differential.sh` | checked=21, failures=0 |

## Scope preservado

No se agregaron messages, causes, stack traces, source locations, colores,
formatting general ni reflection. No se cambió matching, throw, catch, rethrow,
ownership del evento, status ordinario, traps, FFI ni compiler legacy. El cambio
preexistente en `examples/word_stats/main.ae` se preservó sin tocar.
