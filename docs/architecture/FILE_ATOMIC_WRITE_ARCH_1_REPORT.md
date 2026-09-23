# FILE-ATOMIC-WRITE-ARCH-1 — report

Estado: **DISEÑO CERRADO; NO IMPLEMENTADO**, 2026-09-22. Documento normativo:
[FILE_ATOMIC_WRITE_ARCH_1](FILE_ATOMIC_WRITE_ARCH_1.md).

## Resultado

Se cerró una nueva función ordinaria de `std.File`:

```aether
void std.File.writeTextAtomic(ref string path, ref string value);
```

Los dos strings se prestan durante la call y no se modifican ni retienen. La
función escribe exactamente los bytes UTF-8 de `value`, incluido U+0000, sin
BOM, newline o transformación. Un retorno normal deja en `path` un archivo
regular con el contenido nuevo completo.

## Garantía denominada “atomic”

V1 promete **atomic replacement de la entrada target**, no durabilidad. Un
observer que abre/resuelve el target alrededor de la publicación ve la entrada
anterior o la nueva completa; nunca ve en el target un prefijo escrito por esta
operación ni una ventana de ausencia causada por delete-then-move. Descriptores
ya abiertos pueden seguir viendo el objeto anterior.

No se promete `fsync`, power-loss durability, metadata durability, aislamiento,
locking, transacción multi-file ni rollback después del publish. La
implementación V1 no ejecuta `fsync` de archivo o directorio. Tras power loss o
crash del kernel, incluso después de un retorno normal, la API no garantiza qué
versión persistirá.

## Estrategia POSIX

El adapter abre una sola vez el parent, crea allí un temporal con token aleatorio
de al menos 128 bits y create-new exclusivo, escribe todos los bytes, cierra y
publica mediante un único rename anclado al mismo handle de directorio. Nunca
usa `/tmp`, `path + ".tmp"`, truncado previo, delete-then-rename ni una segunda
resolución textual del parent.

Partial writes se completan mediante loop y retry sólo cuando repetir es seguro.
Close termina antes del rename. Todo trabajo de IO potencialmente fallible queda
antes del commit; después de rename exitoso sólo hay cleanup privado
non-throwing y return.

Un path relativo conserva su spelling y se resuelve al abrir el parent. El
componente final symlink se reemplaza como entrada y no se sigue hacia su
referent. Writers concurrentes usan temporales distintos y quedan bajo
last-successful-rename-wins.

## Fallos, rollback y cleanup

Se reutilizan `std.IO.IOException`,
`std.File.FileNotFoundException` y
`std.File.PermissionDeniedException`. No se agrega `Result<T,E>`, exception por
syscall ni errno público.

Un fallo recuperable de create, write, close o rename antes de publish deja el
target anterior intacto y dispara cleanup best effort del temporal. El fallo de
la operación es primario; un error posterior de close/unlink no lo reemplaza ni
oculta y puede dejar un orphan documentado. Las rutas normales no dejan
temporales.

Process kill antes del rename puede dejar un orphan, pero conserva el target. Un
kill alrededor del rename deja old o new completo y el caller puede no saber si
publicó. Un provider cuyo rename puede reportar failure después de commit no
califica hasta cerrar esa ambigüedad. No existe una fase de IO fallible posterior
al rename en V1.

## Metadata y seguridad

El temporal POSIX se crea como archivo regular con `0666 & ~umask`. Al
reemplazar se publica un objeto nuevo: no se preservan mode, owner, ACL, xattrs,
timestamps, flags, hard links ni identidad de inode. Un target read-only puede
ser reemplazable si lo permite el directorio. Esta policy evita introducir
clonado de metadata y sus races/fallos en V1.

La impredecibilidad razonable del nombre reduce interferencia, pero la propiedad
de seguridad decisiva es `O_EXCL`/create-new: una entrada preexistente nunca se
abre ni trunca. El handle estable del parent cierra la carrera de sustitución de
directorio y el rename reemplaza la entrada final sin seguir symlinks. La API no
es una sandbox y no bloquea a otro proceso que ya puede escribir el directorio.

## Compiler/runtime y reachability

HIR/MIR/SSA ven un direct call ordinario `may_allocate`, `may_unwind` y con
efecto externo. Conservan dos borrows, exceptional cleanup y orden de efectos;
no agregan syntax, `FileOp`, ownership source-visible ni temporales filesystem
como valores. El bootstrap puede usar un helper runtime target-specific con
status privado.

Importar `std.File` o usar sólo `readText`/`writeText` no enlaza entropy,
create-exclusive, rename ni cleanup atomic. Usar la función no enlaza `fsync`.
Una futura API durable tendrá identidad y reachability separadas.

## Portabilidad y qualification

FILE-ATOMIC-WRITE-V1 comienza POSIX-only. Windows queda aislado tras la frontera
target-specific y sólo podrá calificarse con una primitive demostrada de
reemplazo atómico para targets existentes e inexistentes. No se permitirá una
emulación delete/copy/move visible.

La qualification posterior cubrirá O0/O2, target ausente/existente, empty,
UTF-8, NUL, contenido grande, overwrite, paths relativos, symlinks, permisos,
fallos inyectados por fase, cleanup/orphans, precedencia de errors, observers y
writers concurrentes, process kill, exception cleanup, verificadores IR y
reachability. Los tests distinguirán expresamente atomic visibility de crash
durability y comprobarán la ausencia de `fsync`; no convertirán el comportamiento
accidental de un filesystem tras reboot en contrato.

Este milestone agregó solamente los dos documentos de arquitectura. No
implementó código, no agregó tests ejecutables y no cambió programas admitidos.
