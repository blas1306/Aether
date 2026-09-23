# FILE-ATOMIC-WRITE-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO EN POSIX/LINUX**, 2026-09-22.

Autoridad normativa:

- [FILE_ATOMIC_WRITE_ARCH_1](FILE_ATOMIC_WRITE_ARCH_1.md)
- [FILE_ATOMIC_WRITE_ARCH_1_REPORT](FILE_ATOMIC_WRITE_ARCH_1_REPORT.md)

## Resultado

`std.File` expone ahora:

```aether
void std.File.writeTextAtomic(ref string path, ref string value);
```

La función se mantiene como una call STD ordinaria con dos borrows compartidos,
resultado `void`, efectos externos y posibilidad de allocation/unwind. No se
agregó syntax, `FileOp`, `AtomicWriteOp`, `Result<T,E>`, append, locking ni API
durable. `readText` y `writeText` no cambiaron de semántica.

El backend bootstrap reconoce la identidad canónica de la función y emite un
adapter Linux privado únicamente cuando la call es alcanzable. La superficie
pública de errores continúa siendo `std.IO.IOException`,
`std.File.FileNotFoundException` y
`std.File.PermissionDeniedException`; errno, descriptors y nombres temporales
no cruzan el boundary.

## Adapter POSIX/Linux

La ruta implementada:

1. valida que el path no sea vacío, no contenga U+0000 y tenga basename final;
2. separa parent/basename y abre el parent una sola vez de forma estable;
3. obtiene 128 bits de `getrandom`, forma un nombre privado fijo
   `.aether-write-` más 32 dígitos hex y descarta un candidato igual al target;
4. crea con `openat(parent, ..., O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC, 0666)` y
   limita a 16 los intentos por colisión;
5. completa partial writes, reintenta `EINTR` sólo con progreso cero seguro y
   rechaza zero progress;
6. cierra el temporal con éxito antes del publish;
7. ejecuta exactamente un `renameat(parent, temp, parent, target)` sin retry;
8. destruye estado privado de forma non-throwing, sin rollback tras publish.

Los failures pre-publish conservan el target e intentan `unlinkat` del temporal.
El status primario se captura antes de cleanup; fallos secundarios de close o
unlink no lo reemplazan. El temporal nuevo usa `0666 & ~umask`; no se copian
mode, owner, ACL, xattrs, timestamps, inode, hard links ni otra metadata.

No hay `fsync`, `fdatasync`, `syncfs`, apertura del target, truncado previo,
`unlink(target)`, copy/delete, `/tmp`, `path + ".tmp"` ni segunda resolución del
parent. Un symlink target se reemplaza como entrada. Windows no se declara
calificado ni recibe fallback no atómico.

## Reachability e IR

Importar `std.File`, no usar la función o usar sólo `readText`/`writeText` no
emite `getrandom`, `openat`, `renameat`, `unlinkat` ni el helper atomic. La ruta
atomic tampoco contiene `fsync`.

HIR conserva las dos adaptaciones `CallScopedSharedBorrow`; MIR y SSA conservan
una call ordinaria, sus edges excepcionales, `EndBorrow` y cleanup. Los
verificadores existentes rechazan corrupción HIR del contrato de call-borrow y
la qualification agregó corrupciones independientes de metadata de borrow en
MIR y SSA. Los dumps comprueban que no aparece una operación especializada.

## Qualification

La suite `file_atomic_write_v1` cubre:

- target inexistente/existente, vacío, ASCII, UTF-8 multibyte, U+0000, newline y
  contenido grande;
- O0/O2, overwrite, path relativo, parent explícito y basename cercano a
  `NAME_MAX`;
- reemplazo del symlink target, rechazo de target directory, mode bajo umask e
  inode/metadata nueva;
- partial writes, `EINTR`, zero progress y failure de write sin publicación;
- fallos deterministas de entropy, parent open, exclusive create, close, rename
  y unlink cleanup;
- precedencia del error primario y orphan permitido cuando falla unlink;
- colisión, agotamiento bounded, candidato igual al target y symlink
  precreado nunca seguido ni truncado;
- rename fallido sin retry, temporales separados entre writers y observer que
  sólo acepta old/new completos;
- `SIGKILL` antes, alrededor y después del publish, comprobando old/new y las
  reglas de orphan;
- unwind por exception con `EndBorrow`, cleanup y contadores de allocations y
  frees balanceados, sin leaks ni double drops;
- ausencia de temporales en rutas normales, reachability selectivo, ausencia de
  `fsync` y preservación de la call ordinaria en HIR/MIR/SSA.

Se agregó además `atomic_main.ae` a la fixture ALPT1 de Expense Tracker. La
fixture ejecuta `encodeLedger`, `std.File.writeTextAtomic`,
`std.File.readText` y `decodeLedger` sobre un archivo real, incluyendo UTF-8 y
U+0000, tanto en O0 como en O2. No se portó el resto de la aplicación.

## Garantía y límites

Un retorno normal garantiza bytes UTF-8 exactos y publicación atómica del
nombre: observers ven el archivo anterior o el nuevo completo. No garantiza
durabilidad ante power loss, persistencia de metadata, rollback posterior al
rename, locking, CAS ni preservación de metadata. Writers concurrentes siguen
last-successful-rename-wins.

## Verificación ejecutada

Desde `compiler-next`:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash tests/run-differential.sh
```

Desde la raíz del repositorio:

```text
git diff --check
```

Todos los comandos finalizaron correctamente.
