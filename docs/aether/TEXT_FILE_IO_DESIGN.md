# I/O mínimo de archivos de texto UTF-8

Estado: núcleo implementado en perfil 18; escritura atómica/durable añadida en
perfil 21, 16 de julio de 2026.

## API pública

La API pertenece al módulo estándar `io`; no es global y sus nombres explicitan
que operan sobre texto:

```aether
import io;

FileReadResult loaded = io.readText("notes.txt");
FileStatus saved = io.writeText("notes.txt", "hello");
FileStatus published = io.writeTextAtomic("ledger.alpt", encoded);
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

`writeTextAtomic(path, content)` conserva esa escritura exacta y publica un
inode nuevo mediante rename atómico en el mismo filesystem. No cambia la
semántica ni las garantías de `writeText`.

Los paths v1 deben ser strings UTF-8 no vacíos y sin NUL. Para escritura
atómica, raíz `/`, trailing slash y componente base vacío son `InvalidPath`.
Un path sin `/` usa `.` como directorio padre. No se expanden `~`,
variables de entorno ni URLs; tampoco se normalizan o resuelven de forma
anticipada. En POSIX el filesystem permite nombres con bytes arbitrarios, pero
esta API restringe su frontera pública a UTF-8. Symlinks siguen la semántica
normal del sistema operativo; no se promete sandbox, protección TOCTOU ni
atomicidad entre operaciones generales.

## Publicación atómica y durabilidad

La implementación POSIX de `writeTextAtomic`:

1. crea con `mkstemp` un temporal único en el directorio destino y modo `0600`;
2. escribe todos los bytes, reintentando `EINTR` y short writes;
3. ejecuta `fsync` y cierra el temporal;
4. usa `rename`/`os.replace` directamente sobre el destino, sin borrarlo antes;
5. abre y sincroniza el directorio padre, y finalmente lo cierra.

`Success` significa que el contenido nuevo completo está visible y que se
confirmaron el sync del archivo y del directorio. Un fallo anterior al rename
deja intacto el destino previo y hace cleanup best-effort del temporal. Un
fallo al abrir, sincronizar o cerrar el directorio ocurre después de la
publicación: retorna el `FileStatus` apropiado, normalmente `IoError`, pero el
contenido nuevo puede estar visible y no se intenta rollback.

`fsync` reduce el riesgo de pérdida ante caída; las garantías últimas dependen
del kernel, filesystem, hardware y configuración, y no equivalen a una
transacción multiarchivo. AST nombra el temporal
`.<base>.aether-atomic-<aleatorio>.tmp`; native usa
`<base>.aether-atomic-XXXXXX`, expandido por `mkstemp`. Un fallo normal intenta
eliminarlo. `SIGKILL`, pérdida de energía o fallo de `unlink` pueden dejar un
huérfano reconocible; esta versión no los recolecta.

## Metadata, symlinks y concurrencia

El archivo publicado es el temporal `0600`, propiedad del proceso creador. V1
no clona mode, owner, ACL, xattrs, timestamps ni otra metadata anterior. Si el
destino es un symlink, POSIX rename reemplaza el symlink mismo, no su referent.

No hay locking ni detección de lost updates. Dos writers pueden preparar
temporales en paralelo; cada rename publica un archivo completo y el último
rename exitoso gana.

## Fault injection y evidencia

AST inyecta fallos reemplazando sólo fronteras privadas del módulo durante el
test. Native enlaza un shim exclusivo de tests que intercepta syscalls; el
runtime productivo no consulta environment ni expone hooks. La matriz cubre
creación, write/short write, fsync de archivo, close, rename, apertura/fsync de
directorio y fallo de unlink. También hay casos de UTF-8/NUL, contenido largo,
paths absolutos/relativos, symlink, writers concurrentes, IR/SSA/DCE y clang
O0/O1/O2.

## Errores y cleanup

Los fallos esperables no lanzan excepciones: inexistencia, permiso, path
inválido y UTF-8 inválido se normalizan a los miembros públicos
correspondientes; los demás fallos se vuelven `IoError`. `errno` queda como
detalle privado. Descriptores, path C y buffers parciales se cierran/liberan en
todos los retornos normales. Un fallo de allocation del objeto string native
conserva la política abortiva actual del runtime; no existe exception unwinding.

## Backends y efectos

AST usa operaciones binarias, `tempfile`, `os.fsync` y `os.replace` con
normalización explícita. IR y SSA conservan calls builtin inequívocas
`io.readText`, `io.writeText`, `io.writeTextAtomic` e `io.appendText`, firma,
ubicación y efectos. Read es lectura observable con
allocation; write/append son escrituras observables. DCE no las elimina y los
pases actuales no implementan CSE, duplicación, fusión ni reordenamiento de
estas calls.

LLVM llama a helpers privados `aether_read_text`, `aether_write_text` y
`aether_write_text_atomic` sobre
handles string length-aware. La lectura crece en chunks, valida con el mismo
validador RFC 3629 y construye un resultado `{ptr, i32}` owned. El runtime
native de esta fase está habilitado solamente en Linux/POSIX. Windows se
rechaza antes de emitir LLVM porque falta convertir explícitamente paths UTF-8
a UTF-16; otras plataformas POSIX requieren todavía su frontera portable de
`errno`. No se declara soporte Windows de reemplazo durable sin una
implementación y pruebas wide-character reales. AST retorna `IoError` antes de
crear el temporal en hosts no POSIX; las capacidades atómica/durable quedan
parciales por plataforma en ambos perfiles.

No se incluyen archivos binarios, streams públicos, directorios, stdin, APIs
avanzadas de paths, JSON, CSV ni `split`.
