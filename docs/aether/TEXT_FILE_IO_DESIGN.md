# I/O mínimo de archivos de texto UTF-8

Estado: implementado en perfil 18, 16 de julio de 2026.

## API pública

La API pertenece al módulo estándar `io`; no es global y sus nombres explicitan
que operan sobre texto:

```aether
import io;

FileReadResult loaded = io.readText("notes.txt");
FileStatus saved = io.writeText("notes.txt", "hello");
FileStatus appended = io.appendText("notes.txt", "\nmore");
```

Los imports completos, aliases (`import io as Files`) y selectivos siguen las
reglas normales de módulos. Los tipos nominales de bootstrap son:

```aether
enum FileStatus {
    Success, NotFound, PermissionDenied, InvalidPath, InvalidUtf8, IoError
}

struct FileReadResult {
    string content;
    FileStatus status;
}
```

`content` siempre es el string vacío cuando `status != Success`. El string
vacío no es sentinel: un archivo vacío también retorna `Success` y el caller
debe comprobar el status.

## Bytes y paths

`readText` abre y acumula bytes en chunks, comprueba crecimiento y valida UTF-8
estrictamente antes de construir un string owned. Acepta archivos vacíos,
preserva NUL embebido y no traduce newlines. La lectura no confía en `ftell`,
por lo que también puede consumir archivos especiales que terminen en EOF; no
se promete streaming, atomicidad ni un límite público inferior al del runtime
string.

`writeText` crea o trunca y `appendText` crea o abre al final. Ambas recorren
short writes y escriben exactamente `content.byteLength` bytes. No usan
`strlen`, `%s` ni agregan newline, terminador observable o separador.

Los paths v1 deben ser strings UTF-8 no vacíos y sin NUL. No se expanden `~`,
variables de entorno ni URLs; tampoco se normalizan o resuelven de forma
anticipada. En POSIX el filesystem permite nombres con bytes arbitrarios, pero
esta API restringe su frontera pública a UTF-8. Symlinks siguen la semántica
normal del sistema operativo; no se promete sandbox, protección TOCTOU ni
atomicidad entre operaciones.

## Errores y cleanup

Los fallos esperables no lanzan excepciones: inexistencia, permiso, path
inválido y UTF-8 inválido se normalizan a los miembros públicos
correspondientes; los demás fallos se vuelven `IoError`. `errno` queda como
detalle privado. Descriptores, path C y buffers parciales se cierran/liberan en
todos los retornos normales. Un fallo de allocation del objeto string native
conserva la política abortiva actual del runtime; no existe exception unwinding.

## Backends y efectos

AST usa `os.open/read/write/close` en modo binario con normalización explícita.
IR y SSA conservan calls builtin inequívocas `io.readText`, `io.writeText` e
`io.appendText`, firma, ubicación y efectos. Read es lectura observable con
allocation; write/append son escrituras observables. DCE no las elimina y los
pases actuales no implementan CSE, duplicación, fusión ni reordenamiento de
estas calls.

LLVM llama a helpers privados `aether_read_text` y `aether_write_text` sobre
handles string length-aware. La lectura crece en chunks, valida con el mismo
validador RFC 3629 y construye un resultado `{ptr, i32}` owned. El runtime
native de esta fase está habilitado solamente en Linux/POSIX. Windows se
rechaza antes de emitir LLVM porque falta convertir explícitamente paths UTF-8
a UTF-16; otras plataformas POSIX requieren todavía su frontera portable de
`errno`.

No se incluyen archivos binarios, streams públicos, directorios, stdin, APIs
avanzadas de paths, JSON, CSV ni `split`.
