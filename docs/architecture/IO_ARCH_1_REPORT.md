# IO-ARCH-1 — design report

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-14.

Este reporte resume la decisión normativa de
[IO-ARCH-1](IO_ARCH_1.md). No se modificó código de compiler, runtime o stdlib y
no se declara admitida ninguna API nueva.

## Resultado

La primera superficie de IO queda organizada así:

```aether
import std.IO;

enum std.IO.ReadLineResult {
    Line(string),
    End
}

std.IO.ReadLineResult std.IO.readLine();
void std.IO.eprint(ref string value);
void std.IO.eprintln(ref string value);
```

```aether
import std.File;

string std.File.readText(ref string path);
void std.File.writeText(ref string path, ref string value);
```

`print` y `println` permanecen en Core/prelude y no reciben duplicados en
`std.IO`. `std.IO` agrega stderr y stdin; `std.File` agrega operaciones whole-
text por path. Todas son funciones estáticas ordinarias de package, no objetos
namespace ni opcodes públicos.

## EOF y líneas

`readLine` retorna `ReadLineResult` porque EOF y una línea vacía son estados
válidos distintos. `Line("")` representa una línea vacía; `End` significa EOF
antes de consumir bytes. No hay null, entero negativo, string sentinel ni un
`Option<T>` general introducido sólo para esta función.

LF termina una línea y se consume. CRLF también termina una línea y se eliminan
ambos bytes. Un CR que no esté inmediatamente antes del LF se conserva como
contenido. EOF después de bytes entrega una última `Line`; sólo la siguiente
call retorna `End`.

## UTF-8 y categorías de fallo

stdin y `readText` validan estrictamente antes de publicar `string`. UTF-8
inválido lanza `std.IO.InvalidTextEncodingException`; no reemplaza por U+FFFD,
no retorna contenido parcial y no produce trap. En `readLine`, la línea inválida
ya fue consumida y una recuperación continúa con la siguiente línea.

La decisión separa:

| Evento | Mecanismo |
|---|---|
| EOF | `ReadLineResult.End` |
| input externo UTF-8 inválido | `InvalidTextEncodingException` unchecked |
| fallo operativo de consola/filesystem | `IOException` o subtipo unchecked |
| OOM/size overflow | trap fail-fast |
| string Aether publicado corrupto | runtime invariant trap |

La conversión futura de bytes ya poseídos a string puede seguir usando un
resultado value; IO externo no introduce por ello un sistema general `Result`.

## Jerarquía de exceptions

La jerarquía inicial es deliberadamente pequeña:

```text
Exception
└── std.IO.IOException
    ├── std.IO.InvalidTextEncodingException
    ├── std.File.FileNotFoundException
    └── std.File.PermissionDeniedException
```

Otros errores terminales usan `IOException`. No existe `FileException`, una
clase por operación ni errno público. Linux puede traducir internamente
`ENOENT`, `EACCES` y `EPERM`, pero los targets que no puedan clasificar con
fiabilidad deben caer honestamente a la base.

Los fallos terminales de stdout/stderr también son `IOException`. Esto incluye
la semántica futura de los Core `print`/`println`, sin moverlos ni duplicarlos.
La dependencia sólo aparece si el símbolo alcanzable necesita esa ruta; no abre
`std.IO` para lookup del usuario.

## Paths y ownership

El path bootstrap es `ref string`: se presta, se adapta sin pérdida al provider
y no se retiene. En Linux sus bytes UTF-8 se pasan length-aware a un adapter que
agrega el terminador privado; un U+0000 embebido falla antes de open y nunca
trunca el path como C string.

Esta elección no hace portable el spelling del filesystem. Separadores, roots,
case, symlinks, permisos y nombres reservados siguen siendo policy del target.
No hay expansión de `~`, variables, globs ni canonicalization.

Los resultados de `readLine` y `readText` entregan ownership independiente. Un
resultado vacío puede usar el singleton string sin cambiar la obligación lógica.
Paths y contenido de `writeText` son borrows compartidos durante la call.

## Read/write exactos

`readText` lee hasta EOF, tolera reads parciales, reintenta interrupciones sin
progreso cuando el target declara seguro hacerlo y valida el contenido completo.
Un size de metadata sólo puede ser hint. Un error después de un prefijo descarta
el buffer y lanza; nunca publica un string parcial.

`writeText` es create-or-truncate:

- crea si el path no existe;
- trunca a cero si existe y es escribible;
- escribe exactamente el UTF-8 de `value`, sin BOM/newline/transcoding;
- itera sobre partial writes y reintenta sólo interrupciones sin progreso cuyo
  contrato permita repetir;
- retorna sólo después de escribir todo y cerrar sin error.

No es atomic replace ni durable write. Un error posterior a create/truncate
puede dejar un archivo vacío o un prefijo. No hay rollback. Success tampoco
promete `fsync`, coordinación con otros writers ni metadata preservada.

## Frontera de implementación

HIR/MIR/SSA deben ver calls normales con identidad canónica, borrows, ownership,
efectos externos y exceptional successors. No se introducen `IOOp`/`FileOp` por
función. EOF es un valor normal; traps no tienen exceptional edge.

El runtime privado contiene la adaptación que hoy no puede escribirse con la
superficie segura de Aether: handles, buffers de bytes, stdin buffering,
partial IO, EINTR, validación/publicación UTF-8 y traducción de status. La
frontera C nunca deja cruzar exceptions y puede conservar errno sólo como dato
privado. Los wrappers STD limpian recursos y construyen las exceptions Aether.

Linux x86-64/POSIX es el bootstrap recomendado, pero son portables los bytes y
delimitadores, EOF nominal, UTF-8 estricto, ownership, create-or-truncate,
partial IO, categorías públicas y separación exception/trap. File descriptors,
errno, flags, umask, chunk sizes, path grammar y ABI EH no son portables.

## Primer vertical recomendado

**IO-V1 — UTF-8 console and whole-text files** debe implementar conjuntamente:

1. los dos packages, cinco funciones, enum y cuatro classes;
2. LF/CRLF/empty/EOF/final-line y buffering sin pérdida;
3. stderr/stdout length-aware, U+0000 y LF exacto;
4. whole-file read y create/truncate/write completos;
5. invalid UTF-8 y fallos missing/permission/generic mediante EH nominal;
6. short IO, EINTR, zero progress y fallos después de prefijos inyectables;
7. OOM/overflow/corrupción como traps no capturables;
8. ownership/cleanup exactos, verificadores HIR/MIR/SSA, O0/O2 y reachability.

Debe seguir fuera de scope Bytes, binary IO, streams, buffering público, seek,
async, networking, directories, metadata avanzada, complex Path, formatting,
serialization y token scanners.

## Decisiones abiertas

Quedan para milestones posteriores los payloads/message/cause de exceptions,
un `Path` rico y paths POSIX no-Unicode, append/exclusive-create/atomic replace,
durability, symlink/security policy, límites configurables de lectura, flush y
buffering públicos, threads, codecs/lossy input, Bytes/Result/Option generales,
otros targets y ABI estable de stdlib/runtime.

Antes de IO-V1 debe comprobarse que la superficie fuente vigente admite el
`void` requerido y la composición owning de `ReadLineResult`/exceptions sin
exenciones específicas de IO.

## Evidencia arquitectónica aplicada

La decisión conserva los límites ya calificados:

- `std` reservado, imports jerárquicos y reachability por símbolo de
  MODULE-STD-V1;
- `print`/`println` Core sin import de CORE-V1;
- string no nulo, UTF-8 válido, length-aware y owning de GENERAL-V1/V2;
- resultados nominales locales sin sentinel, siguiendo `FindResult` de TEXT-V1;
- exceptions nominales unchecked, cleanup explícito y traps separados de
  EXCEPTION-V1..V4;
- calls tipadas y effects verificables a través de HIR → MIR → SSA, con runtime
  y libc detrás de ABI privada.

El resultado evita dos expansiones prematuras: un sistema general de streams/
results y una operación especial de compiler por cada función STD. A la vez
cierra toda semántica observable necesaria para calificar un primer vertical
portable sobre el bootstrap Linux.
