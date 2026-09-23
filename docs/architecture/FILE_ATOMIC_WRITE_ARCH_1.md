# FILE-ATOMIC-WRITE-ARCH-1 — reemplazo atómico de texto

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-22.

Este milestone diseña una operación general de publicación de texto completo.
No modifica parser, resolver, HIR, MIR, SSA, backend, runtime, standard library
ni tests ejecutables. La implementación y qualification pertenecen a un
vertical posterior, **FILE-ATOMIC-WRITE-V1**.

La decisión extiende la superficie de `std.File` definida por
[IO-ARCH-1](IO_ARCH_1.md). Conserva su modelo de paths borrowed, bytes UTF-8
exactos, exceptions unchecked y calls STD ordinarias. Resuelve el blocker de
publicación del ledger identificado en
[EXPENSE-TRACKER-NEXT-PORT](EXPENSE_TRACKER_NEXT_PORT_REPORT.md), pero no crea
una API específica de ledger.

## 1. Decisión resumida

`std.File` agrega conceptualmente:

```aether
void std.File.writeTextAtomic(ref string path, ref string value);
```

La firma es deliberadamente paralela a `writeText`. `path` y `value` son
borrows compartidos durante la llamada; la función no los modifica ni retiene.
`value` ya satisface el invariante UTF-8 de `string` y se escribe byte por byte,
sin BOM, newline, transcoding ni normalización.

En un target calificado, un retorno normal garantiza:

1. `path` designa un archivo regular nuevo que contiene exactamente todos los
   bytes UTF-8 de `value`;
2. la transición del nombre target fue un único reemplazo atómico del provider:
   un observer que resuelve ese nombre ve la entrada anterior o la nueva, nunca
   una entrada target que contenga un prefijo de esta escritura;
3. todos los writes y el close del archivo temporal terminaron antes de la
   publicación.

V1 **no ejecuta `fsync`** ni promete persistencia frente a power loss o crash
del sistema. Atomicidad de visibilidad y durabilidad son propiedades distintas.

La operación se implementa en POSIX mediante un temporal exclusivo en el mismo
directorio, escritura completa, close y un único `rename` que reemplaza el
target. No usa `/tmp`, no trunca primero el target y no emula el reemplazo con
`unlink(target)` seguido de `rename`.

## 2. Vocabulario normativo y garantías separadas

Los términos de este documento tienen estos significados exactos:

| Propiedad | Contrato V1 |
|---|---|
| **Atomic replacement** | **Sí**, para la entrada target en providers calificados: cada resolución concurrente observa la entrada anterior o la nueva completa; no hay estado target parcialmente escrito ni ventana target ausente creada por la operación. |
| **Crash durability** | **No**. No se fuerza el contenido del temporal a almacenamiento estable. Un crash de sistema o power loss puede perder el contenido nuevo aunque la call haya retornado. |
| **Metadata durability** | **No**. No se fuerza el directorio; la creación/reemplazo de la entrada puede perderse tras power loss. |
| **Rollback ante error** | **Sí antes de publish** para failures recuperables: el target no se modifica y se intenta borrar el temporal. **No después de publish**; V1 evita operaciones de IO fallibles después del rename. |
| **Preservación de permisos/ownership** | **No**. Se publica un archivo nuevo; no se clonan mode, owner, ACL, xattrs, timestamps, flags ni security descriptors del target anterior. |
| **Cleanup de temporales** | **Best effort ante failure recuperable** y obligatorio en las rutas normales. Un fallo secundario de cleanup no oculta el fallo primario. Process kill, system crash o un cleanup fallido pueden dejar un orphan con nombre privado. |

“Atómico” en el nombre de la API significa únicamente **atomic replacement de
la entrada target**. No significa durable, transaccional entre varios paths,
aislado entre writers, locked, rollback después del commit ni preservación de
metadata.

La garantía se refiere a observers que acceden al **nombre target** mediante el
mismo filesystem/provider. El temporal existe como una entrada separada y un
proceso con permisos para enumerar el directorio puede verlo. Un descriptor ya
abierto sobre el target anterior continúa refiriendo al objeto anterior; no se
transforma en el nuevo archivo.

## 3. Superficie pública y relación con `writeText`

La superficie relevante queda:

```aether
import std.File;

string std.File.readText(ref string path);
void std.File.writeText(ref string path, ref string value);
void std.File.writeTextAtomic(ref string path, ref string value);
```

`writeText` conserva exactamente su semántica create-or-truncate de IO-ARCH-1:
puede dejar vacío o parcialmente escrito el target si falla. No pasa a ser un
alias ni un wrapper de la nueva operación.

`writeTextAtomic` crea el target si no existe y reemplaza su entrada si existe.
No agrega append, exclusive-create público, backup, compare-and-swap, locking ni
un resultado `Result<T,E>`. El retorno `void` indica que cualquier retorno
normal cumplió el contrato; los fallos operativos usan la jerarquía existente.

Ejemplo suficiente para Expense Tracker:

```aether
string encoded = encodeLedger(ledger);
std.File.writeTextAtomic(path, encoded);
```

El encode ocurre antes de la call. Un fallo de encode no toca el filesystem y
un fallo recuperable anterior a publish no trunca el ledger anterior.

## 4. Bytes, ownership y efectos

`value` se interpreta por `byteLength`, no mediante `strlen`. Se escriben
exactamente sus bytes UTF-8, incluido U+0000. El string vacío publica un archivo
regular de longitud cero. No se agrega terminador, BOM o newline; tampoco se
traduce LF a CRLF.

Ambos parámetros son `ref string`:

- no se consume, modifica, retiene ni publica el backing de ninguno;
- el runtime puede construir adapters y buffers privados mientras dura la call;
- el archivo temporal nunca es un valor Aether ni escapa como resultado;
- aliasing entre ambos argumentos no cambia las reglas de borrow;
- el caller conserva sus owners tanto en success como tras una exception.

La función escribe estado externo, puede asignar storage privado y puede
unwind. No retorna ownership nuevo. OOM, size overflow y corrupción mantienen la
política global de traps fail-fast; no se convierten en `IOException` y no
reciben una promesa de cleanup.

## 5. Algoritmo POSIX normativo

El adapter POSIX calificado sigue esta secuencia lógica:

1. valida y adapta `path` sin tocar el filesystem;
2. separa sólo el componente final del spelling recibido y abre una vez el
   directorio padre, obteniendo un handle estable;
3. crea dentro de ese handle un nombre temporal privado mediante create-new
   exclusivo;
4. escribe todos los bytes con un loop de exact-write;
5. cierra el temporal y exige success de close;
6. ejecuta un único reemplazo `renameat(parent, temp, parent, target)` o una
   primitiva equivalente sobre el mismo handle de directorio;
7. después del rename exitoso sólo destruye memoria/handles privados mediante
   cleanup non-throwing y retorna.

La notación `renameat` describe la propiedad requerida, no congela una ABI. Un
target puede usar una variante más moderna si conserva el mismo contrato. No se
permite implementar el paso 6 como delete/copy/move, ni abrir nuevamente el
parent por su spelling entre create y publish.

No hay `fsync(temp)`, `fdatasync(temp)`, `syncfs`, flush de volumen ni
`fsync(parent)` en V1. El close es necesario para detectar errores operativos y
terminar el owner del handle, pero **close no es una barrera de durabilidad**.

### 5.1 Path relativo y selección del directorio

La operación conserva el contrato de path de IO-ARCH-1: no expande `~`,
variables, globs o `PATH`; no canonicaliza y no reinterpreta `..`, symlinks o
separadores. Para `ledger.ae`, el parent es el directorio actual que se abre al
inicio. Para `dir/ledger.ae`, se abre el spelling `dir` y toda la operación
posterior queda anclada a ese mismo handle.

Esto cierra una carrera de sustitución del parent: si otro actor renombra el
directorio después de abrirlo, create y rename siguen ocurriendo dentro del
mismo directorio abierto. La identidad se fija al resolver el parent; no se
vuelve a resolver el path textual al publicar. El comportamiento de componentes
padre que sean symlinks es el normal del provider durante esa resolución
inicial.

Un componente final vacío, un path con forma de directorio, un parent
inexistente/no-directorio o un parent que no pueda abrirse/escribirse falla
antes de publish. La API no crea directorios.

### 5.2 Nombre temporal y creación exclusiva

El temporal usa un prefijo reservado de Aether de longitud fija y un token
impredecible de al menos 128 bits obtenido de una fuente aleatoria apropiada del
OS. No concatena simplemente `".tmp"` al target y no depende de PID, reloj o un
contador como única entropía. Un formato conceptual válido es:

```text
.aether-write-<token-hex>
```

La longitud fija evita que un basename target cercano a `NAME_MAX` impida crear
el temporal. El nombre concreto y el número máximo de reintentos son privados.
Cada candidato se compara además con el basename target y se descarta si es
idéntico: el target nunca puede servir accidentalmente como su propio temporal,
ni siquiera cuando todavía no existe. Una colisión se reintenta con un token
nuevo dentro de un límite bounded; fallo de entropía o agotamiento produce
`IOException` sin tocar el target.

La creación usa semántica `O_CREAT | O_EXCL`/create-new y, cuando exista,
close-on-exec. La exclusión, no la dificultad de adivinar el token, es la defensa
de corrección contra colisiones y symlinks precreados. Nunca se abre ni trunca
una entrada temporal ya existente. Flags defensivos como `O_NOFOLLOW` pueden
usarse además, pero no sustituyen create-new exclusivo.

### 5.3 Escritura y close

Los partial writes son normales: se continúa desde el primer byte no escrito.
Una interrupción sólo se reintenta cuando el provider certifica cero progreso y
que repetir es seguro. Zero progress no resoluble es `IOException`, no un loop
infinito. Success de esta fase exige que todos los bytes fueran aceptados.

El close ocurre antes de publish. Un error de close es un failure pre-publish:
se conserva el target y se intenta borrar el temporal. No se repite ciegamente
un close cuyo contrato deja ambiguo el estado del descriptor; el adapter lo
invalida exactamente una vez y continúa el cleanup por nombre.

### 5.4 Publicación

El rename usa origen y destino dentro del mismo directorio abierto y, por tanto,
del mismo filesystem. Si el target no existe, crea la entrada target; si existe
una entrada reemplazable, la sustituye atómicamente. No hay una ventana en la
que esta operación quite primero el target.

Para calificar el provider, un resultado fallido del primitive de rename debe
certificar que el reemplazo no ocurrió. No se reintenta una operación con commit
incierto. Filesystems o protocolos remotos que pueden informar failure después
de haber efectuado el rename no satisfacen el perfil V1 hasta disponer de una
primitiva/confirmación que cierre esa ambigüedad.

La implementación organiza todo trabajo potencialmente fallible antes del
rename. Tras un rename exitoso no realiza open, write, close de archivo,
allocation, `fsync` ni otra operación de IO que pueda producir una exception
recuperable. Destruir adapters y tokens debe ser non-throwing.

## 6. Target existente, inexistente y tipos especiales

Si el target no existe, success publica el archivo temporal bajo ese nombre. Si
existe un archivo regular, success reemplaza la entrada; no modifica el inode
anterior in place. Descriptores y hard links que ya referían al inode anterior
continúan viendo su contenido anterior.

En POSIX, si el componente final es un symlink, se reemplaza **el symlink como
entrada**, sea válido o dangling; no se sigue para truncar su referent. Ésta es
una diferencia deliberada respecto de una API que abre el target para escritura
y evita que el destino cambie hacia otro archivo entre validación y write.

Una entrada final no-directory reemplazable, como FIFO/socket/device, se trata
como entrada y no se abre: si el provider permite reemplazarla, success deja un
archivo regular nuevo. Un directorio target o una entrada protegida por policy
del provider falla sin reemplazo. La API no promete reemplazar directorios.

Writers concurrentes no se serializan ni detectan conflictos. Cada writer usa
un temporal distinto; cada rename exitoso publica un archivo completo y el
último rename exitoso en el orden del provider gana. No hay compare-and-swap ni
garantía de que el contenido leído antes siga siendo la base al escribir.

## 7. Permisos y metadata

El temporal POSIX se crea como archivo regular con mode solicitado `0666`,
restringido por el `umask` y por la policy del provider. No se ejecuta `chmod`,
`chown` ni copia de metadata antes o después del rename.

Por ello, al crear un target nuevo, sus permisos son los ordinarios de un archivo
nuevo sujeto a `umask`. Al reemplazar uno existente se publican los permisos y
ownership del archivo nuevo; no se preservan ni heredan deliberadamente los del
inode anterior. En particular no se garantizan:

- mode anterior, setuid/setgid o sticky bits;
- uid/gid anterior fuera de las reglas normales de creación del directorio;
- ACLs, xattrs, labels, capabilities, resource forks o security descriptors;
- timestamps, birth time, file flags o alternate streams;
- identidad de inode/file-id ni hard links del target anterior.

Un archivo target read-only puede ser reemplazable en POSIX si los permisos del
directorio lo permiten; la función obedece al provider y no simula una prueba de
escritura sobre el archivo anterior. La policy portable es “metadata nueva del
provider, sin garantía de preservar la anterior”, no una lista portable de bits
idénticos entre sistemas.

Copiar metadata implicaría TOCTOU, nuevos fallos antes/después del commit y una
policy de seguridad más amplia. Queda fuera de V1.

## 8. Exceptions, precedencia y cleanup

No se agregan exception classes. Se reutiliza la jerarquía de IO-ARCH-1:

```text
Exception
└── std.IO.IOException
    ├── std.File.FileNotFoundException
    └── std.File.PermissionDeniedException
```

`InvalidTextEncodingException` no surge de `value`: un `string` Aether ya es
UTF-8 válido; encontrar corrupción interna es trap. La clasificación operativa
es:

| Fase/condición | Resultado público |
|---|---|
| parent/componente requerido inexistente | `FileNotFoundException` cuando el provider lo clasifique de forma fiable |
| parent open, create, write, close o rename denegado por policy | `PermissionDeniedException` cuando sea fiable |
| colisión agotada, entropía, space/quota, nombre, tipo, IO o rename genérico | `IOException` |
| U+0000/path no representable | `IOException` antes de mutar el filesystem, conforme a IO-ARCH-1 |
| OOM/overflow/corrupción | trap global, no exception IO |

Ante todo failure recuperable anterior al rename exitoso:

1. el error de create/write/close/rename es el **error primario**;
2. se cierra/invalida el handle si todavía pertenece a la operación;
3. se intenta `unlinkat` del nombre temporal dentro del parent estable;
4. los fallos de close/unlink durante cleanup son secundarios y nunca cambian
   ni ocultan la exception primaria;
5. si unlink falla, puede quedar un orphan; nunca se borra otra entrada ni se
   intenta adivinar por scanning.

El runtime privado registra/contiene un fallo secundario sólo si ya existe un
mecanismo diagnóstico interno; V1 no lo agrega al payload público ni lanza una
segunda exception. Si create nunca tuvo éxito, no hay temporal que borrar. Si
rename tuvo éxito, el nombre temporal ya fue consumido y no hay rollback.

Las rutas sin fault injection y con provider conforme deben dejar cero orphan
temporals tanto en success como en failures recuperables. Process termination y
system crash no ejecutan unwind, por lo que la promesa de cleanup no aplica.

## 9. Matriz exacta de crash, kill y errores

| Evento | Target | Temporal | Resultado conocido por caller |
|---|---|---|---|
| error antes de crear temp | anterior/ausente intacto | ninguno | exception |
| error de create/write/close antes de rename | anterior/ausente intacto | se intenta borrar; puede quedar orphan si cleanup falla | exception primaria |
| rename retorna failure certificado | anterior/ausente intacto | se intenta borrar | exception primaria |
| rename retorna success | contenido nuevo completo | nombre temp ya no existe | retorno normal; no hay IO fallible posterior |
| process kill/crash antes del rename | anterior/ausente intacto | puede quedar orphan | no hubo retorno |
| process kill durante rename | anterior o nuevo completo, según si el primitive llegó a commit | puede quedar antes del commit; consumido después | outcome no observado por caller |
| process kill después del rename y antes de observar retorno | nuevo completo en el sistema aún activo | consumido | caller no puede saber que publicó |
| power loss/crash del kernel en cualquier punto | **sin promesa V1** sobre existencia, contenido persistido o versión tras reboot | puede persistir, perderse o quedar orphan | no hubo retorno durable |

“Process kill/crash” en las tres filas centrales significa terminación del
proceso sin caída del kernel/filesystem. No puede interrumpir el rename dejando
un target con prefijo: al resolver el nombre después se observa la entrada
anterior o la nueva. No obstante, si el proceso muere alrededor del commit, un
coordinador externo no puede deducir sólo de la falta de respuesta cuál ganó.

“Power loss/crash del kernel” es diferente. Como V1 no sincroniza datos ni
directorio, ni siquiera un retorno previo constituye confirmación de
persistencia. La recuperación concreta del filesystem puede producir old, new,
ausencia u otro estado admitido por ese provider. Esta API no se describe como
crash-safe o durable.

No existe un “IO error tras rename” en la ruta diseñada: se elimina todo paso IO
fallible posterior. Si un adapter necesita uno, no puede exponer esta API V1
hasta moverlo antes del commit o diseñar una API que represente explícitamente
“publicado, durabilidad/confirmación fallida”.

## 10. Race conditions y límites de seguridad

La arquitectura cierra estas carreras:

- nombres temporales predecibles: token OS impredecible más create-new exclusivo;
- symlink plantado en el nombre temporal: la creación falla, nunca lo sigue;
- sustitución del parent entre create y rename: un único handle estable;
- target symlink swap: el rename reemplaza la entrada final actual y no abre su
  referent;
- target truncado/ausente entre write y publish: nunca se abre ni elimina antes
  del rename;
- escritores concurrentes: temporales separados y publish completo last-wins.

No promete impedir que otro proceso con permisos sobre el directorio:

- enumere, abra, modifique, renombre o borre el temporal;
- reemplace el target inmediatamente después del retorno;
- publique su propio archivo entre operaciones del caller;
- cambie permisos o metadata del directorio/entrada;
- observe el tamaño/nombre temporal por directory enumeration.

El adversario con write permission sobre el mismo directorio ya tiene autoridad
para cambiar sus entradas. La operación debe detectar interference como failure
cuando el primitive lo informe, no elevarla a aislamiento o locking. La
confidencialidad del contenido frente a lectores del directorio sigue la mode
normal `0666 & ~umask`; callers que requieran secretos o metadata específica
necesitan otra API/policy.

Directory traversal no se filtra ni reescribe. `.` y `..` se entregan al
provider durante la resolución inicial exactamente como en `std.File` actual.
Esta función no es una sandbox boundary.

## 11. Atomic visibility no equivale a snapshot global

Para cada resolución/open del nombre target, la entrada publicada es old o new.
Esto permite que un observer abra y lea una versión completa aun mientras otro
writer publica. No garantiza:

- que dos opens separados observen la misma versión;
- que un `readText` sobre un archivo que otro actor modifica **in place** sea un
  snapshot;
- coherencia entre target y otros paths o metadata;
- orden de memoria entre procesos fuera del filesystem;
- atomicidad o cache coherence especial en network/cloud filesystems.

La qualification de concurrent observers usa writers que obedecen este mismo
protocolo y readers que abren el target por iteración. La operación no puede
convertir writers extranjeros truncantes en writers atómicos.

## 12. Windows y otros targets

La semántica pública es portable; el mecanismo no lo es. El adapter Windows
debe, como mínimo:

1. convertir el path sin pérdida a la representación wide;
2. abrir de forma estable el directorio destino cuando la API disponible lo
   permita;
3. crear el temporal en ese directorio con semántica `CREATE_NEW`, token seguro
   y sharing flags deliberados;
4. escribir exactamente todos los bytes y cerrar antes de publish;
5. usar una primitive documentada y probada de rename/replace atómico para el
   caso target existente y el inexistente;
6. no implementar replace mediante delete-then-move ni copy-then-delete;
7. mapear sharing violations, ACL/policy y otros fallos a la jerarquía existente
   sin afirmar una categoría falsa.

`ReplaceFileW`, `MoveFileExW` o `SetFileInformationByHandle` sólo pueden usarse
en los casos donde su contrato, filesystem y flags demuestren las propiedades
anteriores. Sus nombres no son por sí solos prueba de atomicidad, y sus efectos
de metadata/sharing deben calificarse. Si no hay una primitive conforme para un
filesystem/target, `writeTextAtomic` no forma parte de ese capability profile;
no se ofrece una emulación visiblemente no atómica.

**FILE-ATOMIC-WRITE-V1 inicial es POSIX-only.** Windows queda detrás de una
interfaz runtime target-specific de create/write/close/replace/cleanup y no se
declara calificado en este milestone. Darwin, WASI, network filesystems y otros
providers requieren su propia qualification de atomic replace, errores y
cleanup. “POSIX-like” o “rename disponible” no basta para heredarla.

## 13. Standard library, runtime y reachability

`writeTextAtomic` es una función ordinaria de `std.File` con `SymbolKey`
canónico. No agrega syntax, keyword, `FileOp`, `AtomicWriteOp` ni un modo público
del IR. La implementación portable futura puede vivir en stdlib cuando Aether
tenga las primitivas seguras necesarias; el bootstrap puede delegar a un helper
runtime privado target-specific.

La frontera privada puede poseer handles, tokens, path adapters y status de
fase. Nunca deja cruzar una exception Aether por C/FFI: devuelve un status
categorizado y el wrapper construye la exception después del cleanup. Errno,
file descriptors, handles Windows y nombres temporales no forman parte del ABI
público.

Reachability es pay-for-what-you-use:

- importar `std.File` sin llamar esta función no emite nada nuevo;
- usar sólo `readText`/`writeText` no enlaza entropy, create-exclusive, rename ni
  cleanup propios de atomic write;
- usar `writeTextAtomic` enlaza sólo el adapter del target y las exception
  descriptors alcanzables;
- V1 no arrastra `fsync` de archivo/directorio porque no lo invoca;
- una futura API durable debe tener identidad y reachability separadas.

El linker/backend no puede conservar helpers por registro global eager ni por
el mero import de declarations.

## 14. HIR, MIR y SSA

### HIR

- resuelve un direct call ordinario a la identidad canónica de
  `std.File.writeTextAtomic`;
- verifica exactamente dos operands `ref string` y retorno `void`;
- conserva ambos borrows y los efectos conceptuales `writes_external`,
  `may_allocate` y `may_unwind`;
- no expone temp path, fd/handle, errno, rename ni una ownership kind nueva.

### MIR

- representa el call potencialmente throwing con successors normal y
  excepcional;
- ejecuta cleanup ordinario de owners Aether inicializados al unwinding;
- no materializa el temporal filesystem como local source ni publica un owner;
- conserva orden con otros efectos externos y no trata el call como pure.

### SSA

- conserva el effect ordering y el `ExceptionEvent` sólo en el edge excepcional;
- no hace CSE, DCE o movimiento del call a través de otros efectos visibles;
- verifica dominancia y lifecycle de los operands borrowed;
- sólo cambia invoke por call si una prueba vigente establece `nounwind`, algo
  que esta API no promete.

### Backend/runtime

- baja la identidad verificada al body STD/helper privado alcanzable;
- mantiene el state machine pre-publish/published dentro de la frontera privada;
- no infiere semántica por el spelling del nombre ni agrega una instruction IR;
- no permite que un status fallido publique success parcial.

## 15. Qualification de FILE-ATOMIC-WRITE-V1

El primer vertical debe ejecutarse en POSIX local calificado, en O0 y O2, y
cubrir como mínimo:

1. target inexistente y existente;
2. contenido vacío, ASCII, UTF-8 multibyte, U+0000 y contenido grande con short
   writes repetidos;
3. overwrite repetido y writers concurrentes last-successful-rename-wins;
4. observer concurrente que sólo acepta old completo o new completo, nunca
   empty/prefix ni target ausente causado por la operación;
5. paths relativos, parent explícito, basenames cercanos a `NAME_MAX`, target
   symlink y target directory;
6. permisos/mode de creación bajo `umask` y demostración de que metadata previa
   no se promete/preserva;
7. target inexistente sin confundirlo con parent inexistente;
8. failures inyectados en entropy, parent open, exclusive create, cada write,
   zero progress, close y rename;
9. ante cada failure pre-publish, bytes/identidad del target anterior intactos;
10. cleanup del temporal y fault separado de unlink que compruebe precedencia
    del error primario y orphan permitido;
11. colisión, candidato igual al basename target y symlink precreado sin
    apertura, truncado ni uso accidental del target como temporal;
12. EINTR/retry sólo donde sea seguro y ausencia de retry ante commit incierto;
13. process kill antes/durante/después de publish, comprobando sólo old/new y
    permitiendo orphan pre-publish;
14. exception cleanup de strings/temporaries Aether exactamente una vez;
15. HIR/MIR/SSA corruptos rechazados independientemente y call/effect/borrow
    preservados;
16. reachability: import sin uso y uso de otras funciones File no incluyen
    entropy/temp/rename; el atomic write no incluye `fsync`;
17. equivalencia observable O0/O2 y regresión completa de `compiler-next`.

Las pruebas de durability son **negativas/de contrato**: instrumentación verifica
que no se invoca `fsync` de archivo ni directorio y la documentación/test name
declara que success no implica power-loss persistence. No se interpreta que un
filesystem concreto sobreviva una prueba de reboot como garantía de la API.

La qualification debe usar fault injection determinista en el adapter; llenar
disco o cortar energía no sustituye la cobertura de todos los boundaries. Los
tests de bytes inspeccionan archivos como bytes, no mediante rendering de texto.

## 16. Alternativas evaluadas

| Tema | Alternativa | Decisión |
|---|---|---|
| API | cambiar `writeText` | rechazada: rompería su contrato truncante y costos |
| API | `Result<T,E>` universal | rechazada: std.File ya usa exceptions unchecked |
| publish | `path + ".tmp"` | rechazada: colisiones y ataques triviales |
| publish | temporal en `/tmp` | rechazada: puede cruzar filesystem y perder atomic rename |
| publish | truncate/write target | rechazada: expone vacío/prefijo y destruye el anterior |
| publish | unlink target + rename | rechazada: introduce ventana ausente y pérdida previa |
| parent | reabrir por spelling al final | rechazada: race de sustitución del directorio |
| metadata | clonar mode/owner/ACL/xattrs | diferida: policy amplia, privilegios y nuevos failure points |
| durability | file fsync solamente | rechazada: costo sin cerrar metadata durability |
| durability | file fsync + rename + dir fsync | diferida a una API/milestone durable separado |
| POSIX V1 | write + close + same-dir rename | elegida: atomic visibility con contrato/costo acotado |
| Windows | delete/copy/move emulado | prohibida: visiblemente no atómica |

## 17. Fuera de scope y gates futuros

Quedan fuera de este milestone:

- append y exclusive-create públicos;
- durable write, file/directory `fsync` y confirmación de power-loss;
- transacciones multi-file, locking, CAS y advisory locks;
- mmap, binary write, streams y async;
- creación de directorios, backups, versionado y journaling;
- preservación/configuración pública de permisos y metadata;
- limpieza global/automática de orphans de procesos anteriores;
- garantías especiales para cloud, FUSE o network filesystems;
- una sandbox de paths o un tipo `Path` complejo.

Una futura API durable no puede limitarse a cambiar en silencio la implementación
de esta función y llamar “durable” al resultado. Debe cerrar orden de sync,
errores posteriores al rename, filesystems soportados y el estado público
“contenido nuevo visible pero durabilidad no confirmada”. Puede ser otra función
para mantener costo y reachability explícitos.

Antes de declarar Windows calificado se requiere evidencia por filesystem y
primitive de reemplazo, además de tests de sharing, ACLs, target existente/no
existente y kill races. Antes de declarar un filesystem remoto calificado se
requiere eliminar la ambigüedad de un rename que puede retornar error después
del commit.

## 18. Consecuencias

Expense Tracker puede codificar el ledger por completo y publicarlo sin truncar
primero la versión anterior. Los readers que abren el target alrededor del
publish reciben una versión completa. Un fallo operativo recuperable antes del
rename conserva el ledger anterior, salvo que un actor externo lo cambie.

El precio explícito es que el archivo publicado tiene metadata de creación nueva
y que un success no confirma persistencia tras power loss. Esta separación
evita una promesa falsa de durabilidad, mantiene pequeño el vertical inicial y
deja una frontera target-specific donde POSIX y Windows pueden demostrar sus
propias primitives sin filtrar syscalls al lenguaje o al IR.
