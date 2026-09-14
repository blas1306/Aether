# IO-V1 — UTF-8 console and whole-text files

## Resultado

IO-V1 incorpora la primera superficie nativa de entrada/salida de Aether para el target bootstrap Linux x86-64. La API pública se resuelve como funciones y tipos nominales ordinarios del catálogo toolchain; no se agregaron `IOOp`, `FileOp` ni otra operación pública especial en HIR, MIR o SSA.

## Packages y API

`import std.IO;` expone:

```aether
enum ReadLineResult { Line(string), End }
open class IOException : Exception
class InvalidTextEncodingException : IOException
ReadLineResult readLine()
void eprint(ref string value)
void eprintln(ref string value)
```

`import std.File;` expone y depende internamente de `std.IO`:

```aether
class FileNotFoundException : std.IO.IOException
class PermissionDeniedException : std.IO.IOException
string readText(ref string path)
void writeText(ref string path, ref string value)
```

`print` y `println` permanecen únicamente en Core/prelude. `std.IO` no contiene wrappers duplicados.

Las funciones toolchain tienen `FunctionInstanceInfo`, módulo y `SymbolKey` canónicos. Los aliases de importación desaparecen antes de HIR como en MODULE-STD-V1.

## Dependencias generales cerradas

La superficie requirió dos capacidades generales, implementadas sin casos especiales de IO:

- `void` es ahora un tipo fuente de retorno. Admite `return;` y caída implícita al final, usa un token unitario privado entre HIR/MIR/SSA/backend y no es storable ni owning. Se rechaza como local, parámetro, field o payload.
- `ref string` usa el modelo general de referencias y permite borrows compartidos de owners `string`; el borrow no retiene ni consume al owner.

También se corrigió el aprovisionamiento especulativo de drop flags en programas exception-enabled: si una función no obtiene ningún exceptional edge, sus flags especulativos se eliminan antes de SSA. Esto permite retornar owning enums sin inventar cleanup condicional desconectado y mantiene la verificación fail-closed existente.

## EOF y `readLine`

El runtime mantiene EOF como estado normal, separado de errores:

- EOF sin bytes pendientes produce `ReadLineResult.End`;
- una línea vacía produce `Line("")`;
- LF se consume;
- un CR inmediatamente anterior al LF se consume junto con él;
- CR aislado se conserva;
- una última línea sin newline se publica una sola vez; la llamada siguiente produce `End`.

La línea completa se consume antes de validar UTF-8. Por eso una `InvalidTextEncodingException` recuperada no deja el cursor en medio de la línea inválida y la siguiente llamada comienza en la línea siguiente.

## UTF-8

La frontera privada valida UTF-8 estricto de uno a cuatro bytes, incluyendo las restricciones de overlong encodings, surrogates y el máximo U+10FFFF. U+0000 es contenido válido.

La validación ocurre antes de publicar un owner. Un error libera el buffer privado y produce `std.IO.InvalidTextEncodingException`; nunca publica un prefijo. OOM y overflow de crecimiento/publicación terminan con trap y no crean una excepción recuperable.

`readText` conserva exactamente los bytes UTF-8 admitidos, incluidos BOM, LF, CRLF, CR aislado y U+0000. No normaliza texto.

## Jerarquía de excepciones

La jerarquía nominal es:

```text
Exception
└── std.IO.IOException
    ├── std.IO.InvalidTextEncodingException
    ├── std.File.FileNotFoundException
    └── std.File.PermissionDeniedException
```

Errores terminales genéricos de consola, `open`, `read`, `write` o `close` se traducen a `IOException`. `ENOENT` se traduce a `FileNotFoundException`; `EACCES` y `EPERM`, a `PermissionDeniedException`. El matching usa los descriptores nominales existentes, no códigos source-visible.

## Semántica de File y paths

`readText` abre en lectura y consume el archivo completo. `writeText` usa create-or-truncate con modo solicitado `0666`, sujeto al umask. No promete append, exclusividad, atomicidad, rollback ni durabilidad.

Paths y valores son borrows de `string`. La frontera copia temporalmente el path a una representación terminada en NUL únicamente después de recorrer su longitud explícita. Un NUL embebido falla con `IOException` antes de `open`. No existe expansión, canonicalization, glob ni un tipo `Path`.

## Ownership y cleanup de recursos

`ReadLineResult.Line` transporta un owner `string`; `readText` devuelve un owner `string`. Los argumentos de IO/File continúan siendo borrows.

Los buffers privados se liberan una vez en éxito, EOF y errores recuperables. Los file descriptors se cierran una vez; `close` no se reintenta porque un EINTR de `close` no garantiza que repetir sea seguro. Los exception records y payloads recorren el protocolo existente de excepciones y ARC. La publicación del string ocurre solamente después de finalizar IO y validar UTF-8.

## Core `print`/`println`

El driver detecta uso alcanzable de la superficie Core y materializa sólo la clase interna `std.IO.IOException` necesaria para el fallo de stdout. Esto no agrega un import, no abre `std.IO` para lookup y no cambia la identidad Core.

El output Core queda marcado `may_unwind` en MIR y SSA. El backend usa `invoke` cuando hay cleanup excepcional y la frontera convierte un fallo terminal de stdout en `IOException`. SIGPIPE se ignora en la frontera para observar EPIPE como error recuperable.

## HIR, MIR y SSA

Las llamadas públicas aparecen como llamadas directas ordinarias con callee/instance canónico. HIR conserva los `ref string`; MIR y SSA conservan los operands de referencia, el resultado owning y los exceptional edges.

EOF es un resultado normal. Las operaciones que pueden producir excepciones tienen `may_unwind`; los traps de OOM, overflow o corrupción no tienen unwind edge. Los verificadores MIR/SSA incluyen Core output en su contrato de invoke/unwind y continúan rechazando metadata inconsistente.

## Runtime y frontera POSIX

El backend selecciona cuerpos privados para las funciones toolchain por package origin, package path y nombre canónicos. La frontera usa `open`, `read`, `write`, `close`, `realloc`, `free`, `signal` y `__errno_location` de libc/POSIX.

Reads y writes mantienen loops internos. EINTR se reintenta en `open`, `read` y `write`, donde repetir es seguro. Writes positivos parciales avanzan por el prefijo confirmado; progreso cero es terminal. Si un write falla después de un prefijo, el prefijo externo permanece —la API no es transaccional— y se lanza `IOException` sin publicar ningún resultado parcial de Aether.

## Reachability

Los paquetes toolchain sólo entran por grants `std.IO`/`std.File` o por la dependencia interna mínima de Core output. El backend emite cuerpos IO únicamente para funciones alcanzables:

- imports sin uso no emiten `aether_io_read_line`, `aether_io_read_text` ni `aether_io_write_text`;
- un programa readText-only no emite el helper de stdin;
- Core output sin import no concede nombres de `std.IO` al módulo fuente.

## Calificación

`crates/aether-driver/tests/io_v1.rs` cubre O0/O2 y los siguientes grupos:

- LF, CRLF, CR aislado, línea vacía, EOF inmediato y última línea sin newline;
- UTF-8 multibyte, U+0000 y BOM;
- UTF-8 inválido en stdin y archivo, incluida recuperación en la línea siguiente;
- stderr y LF exactos;
- readText y writeText con creación, truncado, overwrite más corto y vacío;
- EINTR inyectado en read/write, writes cortos, progreso cero y fallo después de prefijo;
- matching nominal de encoding, not-found, permission y IOException;
- fallo de Core stdout sin import `std.IO`;
- reachability y ausencia de `IOOp`/`FileOp` en HIR/MIR/SSA.

Las suites previas de strings, Core, módulos, excepciones, ownership, corrupciones MIR/SSA y ejecución diferencial siguen actuando como regresión para cleanup exacto, traps y equivalencia de optimización.

## Deuda restante

No se incorporó ninguna feature fuera de IO-V1. Permanecen fuera de alcance bytes/binary IO, streams, seek, async, networking, directories, metadata avanzada, `Path`, append, exclusive create, atomic replace, durability, formatting, serialization y scanners.

La ABI de runtime continúa siendo privada y bootstrap; una futura estabilización de ABI deberá definir sus propios símbolos/versionado sin convertir estos status internos en superficie del lenguaje.
