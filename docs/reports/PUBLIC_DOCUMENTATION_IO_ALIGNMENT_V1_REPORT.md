# Aether — PUBLIC-DOCUMENTATION-IO-ALIGNMENT-V1

Estado: **CLOSED**

Fecha: 2026-11-25

Checkout calificado: `main` @ `6ca7813cde4df61761ffc20a87bd2553aa24f1eb`

## 1. Resultado

F5 de
[APPLICATION-MATURITY-ASSESSMENT-V1](APPLICATION_MATURITY_ASSESSMENT_V1.md)
queda resuelto en la documentación pública raíz. El onboarding ya usa la
superficie promovida de `compiler-next`: `std.Process`, `std.File`, `std.IO` y
`std.Text`; las firmas, retornos, excepciones, comandos y paths coinciden con
source, tests y consumers actuales.

La documentación distingue ahora publicación atómica de durabilidad. No se
atribuye `fsync`, persistencia ante crash o pérdida de energía, locking ni
preservación de metadata a `std.File.writeTextAtomic`.

Este milestone no modifica compiler, runtime, STD, OAL, APIs, tests de
producción, ejemplos ni semántica de IO.

## 2. Preflight y preservación

El preflight observó:

- rama `main`, alineada con `origin/main`;
- HEAD `6ca7813cde4df61761ffc20a87bd2553aa24f1eb`;
- cambios tracked previos en `examples/ProbandoNR/probandoNR2.ae` y
  `examples/ProbandoNR/probandoNR3.ae`;
- locks y binarios no versionados bajo `examples/ProbandoNR/` y
  `examples/assessment/`;
- `probandoNR3C` y `tmp_lambda_test.ae` no versionados.

Todos se preservaron y permanecieron fuera del diff de este milestone. No se
ejecutaron `reset`, `clean`, `stash`, commit ni push.

Se inspeccionaron el README raíz, el índice y los documentos públicos de IO,
Text y Process, el assessment y su consolidation, las arquitecturas y reportes
CLOSED de IO/File/Text/Process, el catálogo toolchain, el lowering LLVM, las
suites vigentes, las tres aplicaciones del assessment y el Expense Tracker
histórico.

## 3. Errores documentales originales

Los hallazgos estaban concentrados en el resumen de capacidades y el onboarding
de [README.md](../../README.md):

| Hallazgo original | Clasificación | Evidencia vigente |
|---|---|---|
| `System.args()` e `import System;` | desactualizado | la API promovida es `Array<string> std.Process.args()` y requiere `import std.Process;` |
| `import io;` y calls `io.*` | desactualizado | las operaciones whole-text pertenecen a `std.File`; las excepciones base y de encoding, a `std.IO` |
| `FileReadResult`/`FileStatus` | incorrecto | `readText` retorna `string`; ambos writes retornan `void` y los fallos operativos lanzan excepciones nominales |
| `io.appendText` dentro de la superficie promovida | incorrecto | `std.File` expone `readText`, `writeText` y `writeTextAtomic`; no expone append |
| Jerarquía de fallos no documentada | incompleto | `FileNotFoundException`, `PermissionDeniedException` e `InvalidTextEncodingException` derivan de `std.IO.IOException` |
| “save atómico/durable” | ambiguo e incorrecto | el reemplazo del nombre es atómico; la implementación no ofrece durabilidad |
| `fsync` de archivo y directorio | incorrecto | source no emite `fsync` y la suite lo comprueba de forma negativa |
| `examples/expense_tracker/Main.ae` | incorrecto | el entry point real es `examples/expense_tracker/main.ae` |
| firmas inline de IO | incorrecto | describían código que no compila contra la CLI/std promovidas |

La sintaxis CLI `aether run ... -- args...` era correcta. El defecto estaba en
el módulo consultado por el programa y en el casing del path del ejemplo, no en
el forwarding posterior a `--`.

## 4. Contratos verificados

### 4.1 File e IO

El catálogo toolchain en
[`aether-driver/src/lib.rs`](../../compiler-next/crates/aether-driver/src/lib.rs)
declara exactamente:

```aether
string std.File.readText(ref string path);
void std.File.writeText(ref string path, ref string value);
void std.File.writeTextAtomic(ref string path, ref string value);
```

`readText` valida UTF-8 estricto y retorna un string owned. Las operaciones
preservan bytes UTF-8 admitidos, incluido U+0000, sin agregar BOM, newline ni
terminador. `writeText` usa create-or-truncate y no es transaccional: un fallo
posterior al truncado puede dejar cero bytes o un prefijo.

La jerarquía pública calificada es:

```text
Exception
└── std.IO.IOException
    ├── std.IO.InvalidTextEncodingException
    ├── std.File.FileNotFoundException
    └── std.File.PermissionDeniedException
```

Otros fallos operativos terminales usan la base `IOException`; OOM, overflow y
corrupción interna conservan la política de trap y no se presentan como errores
IO recuperables.

### 4.2 Text y Process

`std.Text.lines(ref string) -> List<string>` y
`std.Text.trim(ref string) -> string` requieren `import std.Text`. `lines`
reconoce LF y CRLF según su contrato CLOSED y retorna una lista owning fresh.

`std.Process.args() -> Array<string>` requiere `import std.Process`, excluye
`argv[0]` y entrega un snapshot owned nuevo por call. La CLI reenvía al programa
lo escrito después de `--`; no reinterpreta quoting, globbing, variables ni
paths resueltos por el shell.

### 4.3 Escritura atómica

El contrato verificado separa cuatro propiedades:

| Propiedad | Garantía calificada |
|---|---|
| Publicación atómica | Sí, en Linux/POSIX calificado: el temporal se escribe y cierra en el mismo directorio y se publica mediante un único `renameat`. |
| Preservación old/new ante error pre-publish | Un fallo recuperable de create/write/close/rename anterior a publicar conserva el target anterior o su ausencia. El cleanup del temporal es best effort y puede quedar un orphan si el cleanup o el proceso fallan. |
| Visibilidad | Un observer que resuelve el nombre target ve la entrada anterior o la nueva completa, nunca un prefijo producido por esta operación ni una ventana delete-then-move. Un descriptor abierto antes puede seguir viendo el objeto anterior. Writers concurrentes quedan en last-successful-rename-wins. |
| Durabilidad | No. No se ejecutan `fsync`/`fdatasync` de archivo ni `fsync` de directorio. Incluso después de retorno normal no se garantiza qué versión sobrevivirá a crash del kernel o pérdida de energía. |

El reemplazo publica un archivo nuevo y no promete preservar mode, owner, ACL,
xattrs, timestamps, inode o hard links. Tampoco ofrece locking, aislamiento,
CAS, rollback posterior a publish ni transacciones multiarchivo.

Estas conclusiones coinciden con
[IO-V1](../architecture/IO_V1_REPORT.md),
[FILE-ATOMIC-WRITE-ARCH-1](../architecture/FILE_ATOMIC_WRITE_ARCH_1.md),
[FILE-ATOMIC-WRITE-V1](../architecture/FILE_ATOMIC_WRITE_V1_REPORT.md),
[TEXT-V1](../architecture/TEXT_V1_REPORT.md),
[TEXT-LINES-V1](../architecture/TEXT_LINES_V1_REPORT.md) y
[PROCESS-ARGS-V1](../architecture/PROCESS_ARGS_V1_REPORT.md).

## 5. Cambios realizados

En `README.md` se hicieron sólo cambios focales:

1. se migró el resumen de `System`/`io` a `std.Process`/`std.File`;
2. se eliminaron `appendText`, `FileReadResult` y `FileStatus` de la superficie
   promovida;
3. se documentaron retornos y excepciones nominales reales;
4. se agregó un consumer mínimo de `std.File`, `std.IO`, `std.Text` y
   `std.Process`;
5. se separaron atomicidad, preservación pre-publish, visibilidad y durabilidad;
6. se corrigió `Main.ae` a `main.ae` y se calificaron los comandos publicados;
7. se enlazaron los reportes CLOSED que gobiernan la superficie actual.

No se reescribieron secciones ajenas a F5.

## 6. Ejemplos calificados

El snippet nuevo del README se materializó como consumer real aislado fuera del
repositorio y se ejecutó con la CLI del checkout.

| Gate | O0 | O2 | Resultado |
|---|---:|---:|---|
| `aether check` del snippet | PASS | PASS | compila contra los cuatro packages `std.*` documentados |
| `aether run` con `README.md` como input | PASS | PASS | `lines: 541`; outputs escritos idénticos byte a byte |
| `aether check examples/expense_tracker/main.ae` | PASS | PASS | path y programa publicados válidos |
| Expense Tracker `add` y `list` con ledger temporal | PASS | PASS | exit 0, output esperado y ledgers O0/O2 idénticos |

El tracker histórico usa efectivamente `std.Process.args`, `std.Text`,
`std.File.readText` y `std.File.writeTextAtomic`; su README local describe
correctamente atomicidad sin durabilidad. Las aplicaciones del assessment
confirman además `std.File.writeText` para create-or-truncate y las mismas
excepciones nominales.

## 7. Límites reales de IO

- whole-text UTF-8; no bytes/binario, streams, seek, directorios, mmap ni async;
- paths string sin expansión de `~`, environment, glob ni canonicalization;
- `writeText` puede dejar estado parcial ante fallo;
- `writeTextAtomic` está calificado en Linux/POSIX del bootstrap, no en Windows
  ni automáticamente en filesystems remotos;
- el nombre target cambia atómicamente, pero no hay snapshot global entre dos
  opens, coordinación con writers truncantes externos ni aislamiento;
- no hay durabilidad confirmada, locking, backups, CAS, journaling ni
  transacción multiarchivo;
- atomic write puede cambiar metadata y dejar un temporal orphan ante kill,
  crash o fallo secundario de cleanup.

## 8. Archivos modificados

- `README.md`;
- `docs/reports/PUBLIC_DOCUMENTATION_IO_ALIGNMENT_V1_REPORT.md`.

## 9. Gates

| Gate | Resultado |
|---|---:|
| snippet `check` O0/O2 | 2/2 PASS |
| snippet `run` O0/O2 | 2/2 PASS |
| Expense Tracker `check` O0/O2 | 2/2 PASS |
| Expense Tracker `add` + `list` O0/O2 | 4/4 PASS |
| `io_v1` | 12/12 PASS |
| `file_atomic_write_v1` | 15/15 PASS |
| `text_v1` | 8/8 PASS |
| `process_args_v1` | 9/9 PASS |
| outputs/ledgers O0 vs O2 | byte a byte idénticos |
| integridad documental de release | PASS |
| targets de links internos modificados | PASS |
| búsqueda de nombres/API legacy en `README.md` | PASS, cero matches |
| whitespace en ambos documentos del milestone | PASS |
| `git diff --check` | PASS |

La suite focal suma **44 pass, 0 fail**. No se ejecutó el workspace global: el
cambio es exclusivamente documental y las suites focales cubren cada API y
garantía citada. `scripts/check_release_docs.py` confirmó la integridad y
clasificación documental. `git diff --check` no reportó errores; el reporte
nuevo, todavía untracked, se comprobó además con una búsqueda directa de
whitespace final.

## 10. Riesgos pendientes

- La qualification de atomic replacement sigue limitada al target
  `x86_64-unknown-linux-gnu`/POSIX local usado por `compiler-next`; no debe
  extrapolarse a Windows, FUSE, cloud o network filesystems.
- Crash/power-loss durability permanece deliberadamente fuera de la API. Una
  futura API durable necesitará identidad, orden de sync, errores posteriores a
  publish y qualification propios.
- Documentos Design/RFC e históricos conservan snapshots de superficies
  anteriores. El README actualizado enlaza reportes CLOSED actuales para IO;
  una consolidación documental global de esos snapshots no forma parte de F5.

## 11. Cierre

El onboarding raíz ya compila contra la superficie pública vigente, los paths y
comandos publicados fueron ejecutados, y el texto no confunde atomicidad con
durabilidad ni promete `fsync`. Por tanto, **F5 y
PUBLIC-DOCUMENTATION-IO-ALIGNMENT-V1 quedan CLOSED**.

Mensaje de commit propuesto:

```text
docs(io): align public IO and persistence contracts
```

No se hizo commit ni push.
