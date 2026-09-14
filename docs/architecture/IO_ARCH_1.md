# IO-ARCH-1 — console and text file IO

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-14.

Este milestone diseña la primera entrada/salida estándar de Aether para consola
y archivos de texto UTF-8. No modifica todavía parser, resolver, HIR, MIR, SSA,
backend, standard library ni runtime. La admisión requiere un vertical nativo
posterior y calificado.

La decisión usa la organización de
[MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md), el `string` UTF-8 de
[GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md), la biblioteca
[TEXT-ARCH-1](TEXT_ARCH_1.md) y las exceptions unchecked de
[EXCEPTION-ARCH-2](EXCEPTION_ARCH_2.md). No introduce `Bytes`, streams,
`Option<T>`, `Result<T,E>`, nullability ni una familia pública de operaciones
de IR.

## 1. Decisiones resumidas

- La API pública vive en los packages explícitos `std.IO` y `std.File`.
- `print` y `println` siguen siendo símbolos Core/prelude sobre stdout. No se
  duplican en `std.IO`.
- `readLine` retorna `std.IO.ReadLineResult`, con `Line(string)` y `End`. EOF no
  usa `null`, `-1`, string vacío ni ningún sentinel.
- Una línea termina en LF. Se consume LF y, sólo en la secuencia CRLF, también
  se elimina el CR inmediatamente anterior. Un CR aislado es contenido.
- Texto externo con UTF-8 inválido lanza
  `std.IO.InvalidTextEncodingException`. No se reemplazan bytes por U+FFFD y no
  se publica un `string` inválido.
- Fallos operativos de consola y filesystem usan exceptions unchecked. Errno,
  códigos POSIX y strings del host no forman parte de la API pública.
- OOM, overflow de tamaños, corrupción de runtime/string/ARC e ICE siguen
  siendo traps fail-fast no capturables y sin promesa de unwind.
- El path bootstrap es `string`, borrowed durante la llamada. No es una API de
  bytes ni un `Path` complejo y no implica normalización portable.
- `readLine` y `readText` retornan owners string independientes. `writeText`
  toma path y contenido prestados.
- `writeText` crea si no existe y trunca/reemplaza el contenido si existe. No
  es append, atomic replace ni durable write.
- Partial reads/writes y `EINTR` o su equivalente son responsabilidad interna:
  se reintenta sólo cuando el target declara que no hubo progreso y que repetir
  es seguro; se itera hasta EOF o hasta haber escrito todo. Un error terminal
  nunca se presenta como éxito parcial.
- Las funciones STD son calls estáticas ordinarias con efectos verificados. El
  runtime privado contiene buffers, adaptación del target, syscalls/libc y la
  publicación validada de strings; esos detalles no son packages importables.

## 2. Superficie pública

La superficie normativa inicial es:

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

Las declaraciones efectivas pertenecen respectivamente a `package std.IO;` y
`package std.File;`; la notación calificada anterior describe su identidad
pública. Los imports conceden lookup calificado y no abren los namespaces.

`ReadLineResult` es un enum nominal ordinario, `Copy = false` porque su variante
`Line` puede contener un string owner, `Relocatable = true`, `Storable = true` y
`needs_drop = true`. Matching y destrucción usan las reglas generales de enums
owning. La variante `End` no contiene payload ni owner.

`print` y `println` conservan sus firmas Core/prelude `(string) -> void`, su
borrow durante la llamada, su output length-aware y el LF exacto de `println`.
No se agregan `std.IO.print`, `std.IO.println`, aliases ni forwarding wrappers.
`eprint`/`eprintln` existen porque seleccionan stderr, una capacidad que Core no
expone. No se agrega formatting ni overloads para otros tipos.

## 3. Semántica exacta de consola

### 3.1 Canales

- `readLine` lee del stdin del proceso.
- `print` y `println` escriben al stdout del proceso.
- `eprint` y `eprintln` escriben al stderr del proceso.
- Cada operación preserva el orden de calls Aether observado en el mismo
  thread. No se promete coordinación con escrituras extranjeras, otros
  procesos ni threads futuros.
- Ninguna función cierra stdin, stdout o stderr.

`eprint(value)` escribe exactamente `data[0:byteLength(value)]`, incluido
U+0000. `eprintln(value)` escribe esos mismos bytes y después exactamente el
byte LF `0x0A`. No usa `%s`, `strlen`, modo de texto del host ni el cero auxiliar
del backing. No realiza traducción a CRLF.

Esta arquitectura clasifica un fallo terminal detectado al escribir stdout o
stderr como `std.IO.IOException`, incluidos los Core `print`/`println`. Esto
refina la parte todavía no cerrada del error operativo de CORE-V1 sin duplicar
su API. La implementación Core puede adquirir una dependencia interna y
alcanzable por uso sobre la identidad canónica de `std.IO.IOException`; eso no
equivale a un import implícito del usuario ni abre `std.IO` para lookup. El
vertical IO deberá migrar y calificar ambos canales de output conjuntamente.

### 3.2 Delimitación de `readLine`

Una invocación consume la siguiente línea lógica con estas reglas, idénticas
en todos los targets admitidos:

1. acumula bytes desde la posición actual de stdin hasta el primer LF `0x0A` o
   hasta EOF;
2. si encontró LF, lo consume y no lo incluye en el resultado;
3. si el byte inmediatamente anterior al LF es CR `0x0D`, consume ese CR como
   parte de la terminación CRLF y tampoco lo incluye;
4. cualquier otro CR, incluido un CR antes de EOF o seguido por un byte distinto
   de LF, permanece como U+000D en el contenido;
5. valida UTF-8 estrictamente después de retirar el terminador y antes de
   publicar el string.

Consecuencias normativas:

| Bytes disponibles | Resultado |
|---|---|
| `61 62 63 0A` | `Line("abc")` |
| `61 62 63 0D 0A` | `Line("abc")` |
| `0A` o `0D 0A` | `Line("")` |
| `61 62 63` seguido de EOF | `Line("abc")` |
| EOF antes de consumir bytes | `End` |
| `61 0D 62 0A` | `Line("a\rb")` |

Una última línea sin newline se entrega una sola vez. La siguiente invocación
retorna `End`. Una línea vacía es `Line("")` y nunca se confunde con EOF.
Múltiples líneas vacías producen un resultado `Line("")` por cada terminador.

La búsqueda de LF es bytewise y segura: `0x0A` no puede aparecer como byte de
continuación dentro de una secuencia UTF-8 válida. La validación final sigue
siendo obligatoria porque el input externo aún no satisface el invariante.

### 3.3 EOF nominal

EOF es una condición ordinaria y frecuente del protocolo de lectura, no una
exception. Se representa exclusivamente con:

```aether
enum ReadLineResult {
    Line(string),
    End
}
```

No se introduce `Option<T>` ni `Result<T,E>` general por esta API. Tampoco se
reserva string vacío, un valor especial de string, `null`, `-1`, `usize.max` o
un singleton inspeccionable. El caller usa matching exhaustivo ordinario.

EOF sólo significa que no quedan bytes antes de comenzar la próxima línea. Un
error operativo de lectura no es EOF y lanza `IOException`. Un EOF observado
después de bytes produce primero `Line`; nunca descarta la última línea.

## 4. UTF-8 externo y publicación de `string`

Todo resultado `Line(string)` y todo resultado de `readText` debe satisfacer el
invariante global: UTF-8 bien formado, sin overlong encodings, surrogates,
secuencias truncadas ni valores mayores que U+10FFFF. U+0000 es válido. No se
aplica normalización, case mapping, locale ni eliminación de BOM.

Un BOM UTF-8 inicial válido (`EF BB BF`) se conserva como U+FEFF. `readText` no
normaliza newlines. Sólo `readLine` elimina su terminador LF/CRLF conforme a la
sección 3.2.

Si stdin o un archivo contiene UTF-8 inválido en el contenido que la operación
intenta materializar:

- no se publica un string parcial o corrupto;
- no se hace replacement lossless/lossy ni se inserta U+FFFD;
- no se devuelve otra variante de `ReadLineResult`;
- se liberan los buffers privados ya adquiridos y se lanza
  `std.IO.InvalidTextEncodingException`.

Para `readLine`, la invocación consume hasta el terminador o EOF antes de que la
validación pueda fallar. Capturar la exception no rebobina stdin: una llamada
posterior continúa después de la línea inválida consumida. Si los bytes
inválidos terminaban en EOF, la siguiente llamada retorna `End`.

Para `readText`, la exception no entrega los bytes ni un string parcial. No se
promete que el archivo no haya cambiado concurrentemente durante la lectura.

La elección de exception es deliberada. EOF forma parte del control normal y
merece una variante exhaustiva. Encoding inválido impide cumplir una operación
cuya única salida útil es texto válido y comparte la misma categoría operativa
en consola y archivo. Una tercera variante de `ReadLineResult` no resolvería
`readText` sin crear otra familia nominal o un `Result` general. La exception
unchecked permite recuperación explícita sin contaminar firmas ni confundir el
fallo con OOM.

GENERAL-ARCH-1 reservó un error estructurado para la futura conversión explícita
`Bytes -> string`. Esta decisión no diseña ni contradice esa futura API value:
una conversión pura sobre bytes que el caller ya posee puede elegir `Result`,
mientras una operación externa effectful usa la jerarquía IO unchecked. No se
generaliza esta decisión a parsing, codecs o `Result`.

Si un string Aether ya publicado contiene UTF-8 inválido, el origen no es input
ordinario: se ha roto un invariante del compiler/runtime. Detectarlo produce un
trap de corrupción no capturable, nunca `InvalidTextEncodingException`.

## 5. Modelo de exceptions

### 5.1 Jerarquía nominal inicial

La jerarquía pública mínima es:

```text
Exception
└── std.IO.IOException                         open
    ├── std.IO.InvalidTextEncodingException   final
    ├── std.File.FileNotFoundException         final
    └── std.File.PermissionDeniedException     final
```

No se agrega `FileException`: no aporta una política de catch distinta en esta
superficie pequeña. Tampoco se agregan clases por syscall u operación
(`OpenException`, `ReadException`, `WriteException`, `CloseException`) ni una
clase por valor de errno.

Las clases pueden comenzar sin fields ni message obligatorio. Su identidad
nominal, herencia y lifecycle son los ordinarios de exceptions/classes. Paths,
operación, message, cause y códigos diagnósticos consultables quedan abiertos
hasta que una API de payload no fuerce string/class storage o ABI prematuros.

### 5.2 Clasificación de fallos operativos

Se lanzan exceptions unchecked así:

| Condición | Exception pública |
|---|---|
| stdin/stdout/stderr no usable, read/write terminal, broken pipe y equivalentes | `std.IO.IOException` |
| target de lectura no existe, o falta un componente padre requerido por read/write | `std.File.FileNotFoundException` |
| acceso denegado por permisos/policy del provider | `std.File.PermissionDeniedException` |
| bytes externos no son UTF-8 válido | `std.IO.InvalidTextEncodingException` |
| otro fallo de open/read/write/close o provider filesystem | `std.IO.IOException` |

Cuando una condición podría encajar en una subclase, se usa la más específica
que el provider pueda determinar de forma fiable. No se infieren permisos a
partir de texto de error. Si el target no puede distinguir una categoría, usa
`IOException`, nunca una clasificación falsa.

En Linux bootstrap, `ENOENT` y el equivalente de componente requerido
inexistente se traducen a `FileNotFoundException` —sin impedir que `writeText`
cree su target final—; `EACCES`/`EPERM` se traducen a
`PermissionDeniedException`; una interrupción de open/read/write se reintenta
cuando POSIX garantiza que no hubo progreso; otros errores terminales se
traducen a `IOException`. Esta tabla es implementación privada, no contrato de
que Aether exponga errno.

El runtime C/POSIX no lanza a través de la frontera FFI. Retorna al wrapper STD
un status privado categorizado. El wrapper construye y lanza la exception Aether
después de liberar recursos temporales. Si ya existe una exception activa, el
cleanup privado no lanza otra; conserva la excepción primaria y contiene el
fallo secundario según la política fail-fast de runtime.

### 5.3 Traps que no cambian

Siguen siendo terminación fail-fast, no entran en `catch (Exception e)` y no
prometen ejecutar `finally` ni cleanup:

- `AllocationFailure` al reservar buffers, strings, exception objects o records
  de unwinding;
- `AllocationSizeOverflow` y cualquier overflow checked de capacidad, longitud,
  header o conversión necesaria para representar el input;
- corrupción de string, buffer, descriptor, handle nativo, ARC o estado interno
  del runtime;
- retain/release underflow u overflow;
- ICE y violaciones verificadas de invariantes HIR/MIR/SSA/backend.

La falta de memoria nunca se traduce a `IOException`, incluso si ocurre durante
`readText`. Encoding inválido nunca se traduce a trap salvo que lo inválido sea
un string Aether ya publicado. Un tamaño externo válido pero no representable
en el target es `AllocationSizeOverflow`, no una exception filesystem.

## 6. Paths bootstrap

El path bootstrap es `string`:

```aether
string std.File.readText(ref string path);
void std.File.writeText(ref string path, ref string value);
```

Esto es suficiente para el primer target y evita diseñar prematuramente root,
components, normalization, symlinks, volume prefixes, canonicalization y
security capabilities. No implica que `string` sea el tipo final de toda API de
filesystem.

El path se presta durante la llamada. La función no retiene el owner, no lo
modifica y no adopta su backing. U+0000 embebido no puede representarse ante los
providers bootstrap y produce `IOException` antes de abrir nada; no se trunca
como C string.

La adaptación debe ser no-lossy:

- Linux/POSIX bootstrap codifica los scalars del string como sus bytes UTF-8
  exactos y agrega un terminador privado sólo para la llamada nativa;
- un target con path Unicode ancho debe convertir todos los scalars de forma
  exacta a su representación nativa o fallar con `IOException`;
- nunca se usa locale ambiente ni replacement silencioso.

La API no promete que un mismo spelling designe el mismo objeto entre targets.
Separadores, roots, drive/volume syntax, case sensitivity, nombres reservados,
symlink resolution y límites de componentes pertenecen al filesystem/provider.
El contrato portable sólo exige adaptación sin pérdida, rechazo explícito de
paths no representables y las semánticas de operación de las secciones 7 y 8.

Un path vacío no recibe significado especial de Aether. Se entrega al provider
y normalmente falla como `IOException`, salvo que el provider documente una
identidad válida. La stdlib no ejecuta expansión de `~`, variables de ambiente,
globs, búsqueda en PATH ni canonicalización.

## 7. `readText`

`readText(path)` abre el recurso identificado para lectura, lee bytes hasta EOF,
valida el contenido completo como UTF-8 y sólo entonces publica un string owner.

- El archivo vacío retorna un owner del string vacío; físicamente puede usar el
  singleton inmortal.
- Un archivo no vacío retorna contenido owned independiente de path, buffers y
  handle nativo. “Fresh” describe la obligación entregada al caller, no una
  identidad de backing públicamente observable.
- Se conservan todos los bytes válidos, incluidos U+0000, BOM, LF y CRLF.
- No se agrega terminador al contenido, no se normalizan newlines y no se
  interpreta el archivo por líneas.
- Un size hint de metadata puede reservar capacidad, pero nunca es autoridad:
  la lectura continúa hasta EOF y usa aritmética checked al crecer.
- El resultado no es snapshot atómico frente a writers concurrentes. Es la
  secuencia observada por las reads de esa invocación.

Partial reads son normales. Un read de menos bytes que la capacidad no significa
EOF. La implementación repite read hasta EOF, reintenta interrupciones
transitorias equivalentes a `EINTR` cuando el target informa cero progreso y
preserva el orden de bytes. Un error
terminal después de haber leído un prefijo libera el buffer, no publica ese
prefijo y lanza la exception correspondiente.

Un provider non-blocking que informa “would block” no convierte el caso en
async ni en EOF: la API síncrona lanza `IOException` salvo que el adapter pueda
esperar de acuerdo con el contrato síncrono del target. Pipes, devices y
pseudo-files no reciben garantías adicionales; si el provider los admite, la
operación sigue leyendo hasta EOF y puede no terminar.

El handle se cierra en success y en las salidas excepcionales recuperables. Un
fallo de close observado después de una lectura por lo demás exitosa lanza
`IOException` y descarta el resultado aún no publicado. Si ya existe un fallo
primario, close no lo reemplaza con una segunda exception.

## 8. `writeText`

`writeText(path, value)` tiene la semántica exacta **create-or-truncate**:

1. adapta y valida el path sin modificar el filesystem;
2. abre para escritura, creando un archivo regular si no existe;
3. si ya existe un archivo escribible, su contenido se trunca a longitud cero
   como parte de la apertura;
4. escribe exactamente los bytes UTF-8 de `value`, incluido U+0000;
5. cierra el handle y retorna sólo si todos los pasos observables tuvieron éxito.

No falla por el mero hecho de que el archivo ya exista. No agrega al final, no
preserva un sufijo anterior, no agrega BOM ni newline y no transforma LF a la
convención del host. Escribir `""` crea o deja un archivo de longitud cero.

Los parámetros path y value son borrows shared que permanecen vivos durante la
operación. La función no adopta ni retiene sus backings. Si ambos aliases
designan el mismo string owner, siguen siendo dos borrows ordinarios y seguros.

Partial writes son normales y se reintentan desde el primer byte no escrito.
Una interrupción transitoria se reintenta sólo cuando el target informa que no
hubo progreso; si informa una cantidad, se avanza exactamente esa cantidad. Un
write que informa cero progreso sin una condición de espera resoluble se trata
como `IOException` para evitar un loop infinito. Success significa que todos
los bytes fueron aceptados por el provider y el close no informó error.

La operación **no es transaccional**. La apertura puede truncar antes del primer
write. Si ocurre permission error previo a abrir, el archivo queda intacto; si
ocurre un error después de create/truncate o después de writes parciales, el
path puede contener un archivo vacío o el prefijo escrito. Se lanza la exception
correspondiente y no se intenta rollback, borrar el archivo o restaurar el
contenido anterior.

Success no promete persistencia en almacenamiento estable, `fsync`, flush de
directorios, atomic rename, exclusión frente a otros writers ni preservación de
metadata. Permisos de un archivo nuevo provienen de la policy del provider; en
Linux bootstrap son los permisos de creación ordinarios restringidos por
`umask`. Esos bits no forman parte de la API portable.

## 9. Ownership, temporaries y cleanup

| Operación | Inputs | Resultado | Obligación |
|---|---|---|---|
| `readLine` → `Line` | stdin effect | enum owner con string owner | caller destruye/mueve el resultado |
| `readLine` → `End` | stdin effect | enum sin payload owning | valor ordinario |
| `eprint`/`eprintln` | `ref string` | ninguno | borrow sólo durante la call |
| `readText` | `ref string path` | string owner independiente | caller recibe una obligación |
| `writeText` | `ref string path`, `ref string value` | ninguno | ambos borrows sólo durante la call |

Buffers de bytes, path adapters y handles son owners privados. En success se
transfieren a la publicación validada o se liberan antes del return. En una
exception operativa se limpian antes del throw. Los strings Aether ya
inicializados en caller/callee participan del unwind normal de EXCEPTION-V4.

Un resultado `Line` o `readText` no presta storage del runtime, stdin o archivo.
El runtime valida y copia/adopta únicamente una allocation propia compatible
antes de publicar el handle opaco. Memoria de libc o del kernel no se expone ni
se adopta sin una transferencia privada probada contra el allocator de string.

Un trap de OOM/overflow/corrupción conserva la política global de no cleanup.
No se finge strong exception safety para una terminación fail-fast.

## 10. Frontera `std.IO`, `std.File` y Core

### 10.1 `std.IO`

Posee consola y errores comunes de IO:

- `ReadLineResult`, `readLine`, `eprint`, `eprintln`;
- `IOException` e `InvalidTextEncodingException`;
- la semántica común de fallos operativos de los canales estándar.

No posee paths, filesystem, binary IO, streams, formatting ni duplicados de
`print`/`println`.

### 10.2 `std.File`

Posee operaciones por path y errores específicos de filesystem:

- `readText`, `writeText`;
- `FileNotFoundException`, `PermissionDeniedException`.

Importa internamente `std.IO` para derivar y lanzar su base común. No introduce
un objeto File, handles públicos, directories, metadata o un `Path` complejo.

### 10.3 Core/prelude

Mantiene exclusivamente `print`/`println` para stdout. Sus nombres siguen
disponibles sin import; no hacen visible `std.IO` ni sus exception classes. Un
caller que quiera capturar específicamente `IOException` importa `std.IO`; un
caller que sólo usa `print` no necesita hacerlo.

## 11. Standard library y runtime privado

Las cinco funciones públicas son funciones normales de toolchain con
`SymbolKey` canónico. HIR conserva target, tipos, modes de parámetro, ownership
de resultado y efectos de read/write/allocation/unwind. MIR representa los
calls potencialmente throwing con successor normal y excepcional cuando el CFG
lo requiera. SSA conserva esos efectos y owners. Inlining vuelve a verificación.

No se agregan `IOOp`, `FileOp`, `ReadLineOp`, `ReadTextOp` ni un opcode público
por operación. El backend no identifica la semántica leyendo spellings y no
reconstruye exceptions a partir de errno.

El runtime privado y los módulos privilegiados de stdlib pueden ofrecer, sin
fijar aquí nombres ABI:

- acceso length-aware a stdin/stdout/stderr;
- open/read/write/close y adaptación de handles del target;
- un acumulador byte privado con crecimiento checked;
- buffering persistente privado para no perder bytes leídos más allá de un LF;
- validación UTF-8 y publicación de un string owner;
- adaptación no-lossy de paths;
- loops de partial read/write y retry de interrupción;
- status internos categorizados y limpieza non-throwing.

La frontera C devuelve status/handles privados y nunca deja cruzar exceptions
Aether o extranjeras. Un status puede conservar errno internamente para decidir
una categoría, pero errno no llega a HIR, al objeto público ni al diagnostic API.

Mientras Aether no tenga `Bytes`, raw pointers ni un byte builder seguro, el
bootstrap puede concentrar más del loop/buffering en runtime. Esto es deuda de
implementación, no autoridad semántica ni motivo para crear un opcode por API.
Cuando esas abstracciones existan, la lógica portable puede migrar a bodies STD
sin cambiar las firmas ni el contrato observable.

Reachability sigue pay-for-what-you-use: importar sin usar no emite helpers. Un
programa que sólo usa `readText` no necesita stdin buffering; uno sin IO/File no
enlaza esta capa. Descriptors de exceptions sólo se incluyen cuando una ruta
alcanzable puede construirlas, sujeto a metadata mínima del target EH.

## 12. Linux bootstrap y contrato portable

El primer target recomendado es Linux x86-64, single-threaded, LLVM native EH,
ABI runtime privada y libc/POSIX como adaptación inicial. Allí pueden usarse
file descriptors, `read`, `write`, `open`/`openat` y `close`, siempre detrás de
la frontera privada.

Son semántica portable obligatoria:

- identidad y firmas de la API;
- EOF nominal y distinción de línea vacía;
- delimitación LF, normalización exclusiva de CRLF y preservación de CR aislado;
- bytes exactos LF en `println`/`eprintln`;
- UTF-8 estricto, U+0000 válido, BOM preservado y ausencia de replacement;
- ownership/borrows y ausencia de resultados parciales publicados;
- create-or-truncate de `writeText`, escritura completa en success y su falta
  explícita de atomicidad/durabilidad;
- retry de interrupciones transitorias y loops sobre partial IO;
- jerarquía nominal y categorías públicas, con fallback honesto a IOException;
- separación entre exceptions operativas y traps de runtime;
- no exposición de errno, handles, layout string o buffers.

Son detalles de target/provider y no pueden filtrarse como supuesto portable:

- números de file descriptor, errno y flags POSIX;
- separadores/path roots, case sensitivity, symlinks y nombres reservados;
- permisos/umask, ownership de archivos y ACLs;
- tamaño de chunks, estrategia de buffering y uso de metadata como hint;
- atomicidad que un filesystem concreto proporcione accidentalmente;
- scheduling, terminal echo, encoding/configuración del terminal fuera de los
  bytes que Aether recibe o emite;
- ABI de unwinding, calling convention y símbolos runtime.

Cada target nuevo debe calificar su adapter, exception transport, path
conversion, partial IO, cleanup y bytes observables. Un target sin filesystem
puede no ofrecer `std.File` en su perfil; no lo implementa como success vacío ni
como trap silencioso. Un target sin EH calificado no admite este vertical.

“Retry de interrupción” no autoriza repetir ciegamente una operación cuyo
commit sea incierto. En particular, algunos contratos de `close` dejan el estado
del handle ambiguo tras interrupción. El adapter del target debe cerrar/invalidar
su owner exactamente una vez y reportar `IOException` si no puede certificar
success; nunca reutiliza un handle incierto ni duplica un efecto para aparentar
portabilidad.

## 13. Representación y verificación por fases

### HIR

- resuelve packages y `SymbolKey` de calls normales;
- conserva `ReadLineResult` y exception `ClassId` nominales;
- registra inputs borrowed, resultados owning y efectos
  `reads_external`/`writes_external`/`may_allocate`/`may_unwind` conceptuales;
- no contiene errno, fd, path C ni buffer layout.

### MIR

- materializa temporaries y Transfer/Move/Drop del enum/string;
- da a calls potencialmente throwing successors normal/excepcional;
- ejecuta cleanup de owners inicializados antes de propagar exceptions;
- conserva traps sin exceptional successor;
- no representa EOF como exceptional edge.

### SSA

- conserva resultados sólo en el edge normal y `ExceptionEvent` sólo en el
  excepcional;
- verifica dominancia, efectos ordenados y consumo único de owners;
- impide CSE, eliminación o reordenamiento de reads/writes externos;
- permite convertir invoke a call sólo con prueba vigente de `nounwind`.

### Backend/runtime

- traduce calls verificadas al ABI privado y al EH del target;
- no decide semántica de línea, EOF, UTF-8, ownership o exception pública;
- no convierte un status fallido en success parcial;
- contiene toda frontera C y valida layouts/versiones de runtime.

## 14. Primer vertical recomendado

Nombre: **IO-V1 — UTF-8 console and whole-text files**.

Target: Linux x86-64, single thread, LLVM native EH, runtime ABI privada. Debe
admitir en una sola ruta source→native:

1. packages canónicos `std.IO` y `std.File`, sus cinco funciones y cuatro
   exception classes;
2. `ReadLineResult` con matching y lifecycle owning completos;
3. stdin con LF, CRLF, empty line, repeated empty lines, EOF inmediato y última
   línea sin newline;
4. stderr length-aware con U+0000 y LF exacto;
5. `readText` exacto, vacío, multibyte, U+0000, BOM y archivo que crece/entrega
   partial reads;
6. `writeText` create, truncate, empty, overwrite más corto y partial writes;
7. UTF-8 inválido en stdin y archivo como
   `InvalidTextEncodingException`, con cleanup y recuperación;
8. missing/permission/generic IO como matching nominal exacto/subtipo;
9. EINTR inyectado, short read/write, zero-progress write y fallo después de un
   prefijo;
10. OOM, size overflow y corrupción de string como traps no capturables;
11. HIR/MIR/SSA con calls ordinarias, exceptional CFG y verificadores
    independientes;
12. reachability sin helpers de ramas no usadas y equivalencia O0/O2.

La fixture debe comprobar stdout, stderr y archivos como bytes, no mediante
rendering de terminal. Los tests de escritura fallida deben observar y aceptar
el prefijo/truncado permitido, demostrando que no existe una garantía
transaccional accidental. Los tests de exceptions deben verificar cleanup de
strings, buffers y records exactamente una vez.

El vertical no agrega Bytes, streams, seek, async, sockets, directories,
metadata avanzada, `Path`, formatting, serialization, scanners ni nuevos modos
de apertura. Tampoco estabiliza ABI pública de stdlib/runtime.

## 15. Alternativas evaluadas

| Tema | Alternativa | Decisión |
|---|---|---|
| EOF | string vacío | rechazada: una línea vacía es valor ordinario |
| EOF | null, `-1` o sentinel | rechazada: amplía nullability o mezcla dominios |
| EOF | `Option<string>` general | diferida: expansión innecesaria para una API |
| EOF | `ReadLineResult` nominal | elegida: local, exhaustivo y owning verificable |
| UTF-8 inválido | replacement U+FFFD | rechazada: pierde bytes y oculta corrupción externa |
| UTF-8 inválido | trap | rechazada para input externo: es condición operativa recuperable |
| UTF-8 inválido | variante de cada resultado | rechazada: fragmenta APIs y aproxima un Result incompleto |
| UTF-8 inválido | exception nominal | elegida: uniforme para stdin/file y separada de OOM |
| jerarquía | una clase por syscall/errno | rechazada: filtra plataforma y multiplica catch policy |
| jerarquía | sólo IOException | insuficiente para missing, permission y decode comunes |
| filesystem base | `FileException` intermedia | rechazada inicialmente: no agrega una frontera útil |
| path | bytes | fuera de scope hasta Bytes y política no-Unicode |
| path | `Path` complejo | diferido: demasiada policy para el bootstrap |
| path | string borrowed | elegido: pequeño, seguro y adaptable sin pérdida |
| write | fail if exists | rechazado para `writeText`; requeriría otro nombre/policy |
| write | atomic replace | diferido: temp/rename/metadata tienen semántica filesystem propia |
| write | create-or-truncate | elegido: simple, explícito y portable con límites declarados |
| lowering | opcode por función | rechazado: las APIs son calls STD ordinarias |
| lowering | runtime privado con status | elegido para bootstrap sin Bytes/unsafe públicos |

## 16. Decisiones abiertas y gates

No bloquean IO-V1 salvo donde se indica:

- payload público de exceptions: message, operation, path, cause y diagnostics;
- API futura para inspeccionar una categoría más rica sin exponer errno;
- `Path`, paths no-Unicode en POSIX, canonicalization y sandbox capabilities;
- modos append, exclusive create, atomic replace y durability/fsync;
- política explícita para symlinks, special files y TOCTOU-sensitive APIs;
- límites configurables de `readLine`/`readText` antes de OOM;
- buffering configurable, flush público y coordinación entre stdout/stderr;
- threads y sincronización de stdin/stdout/stderr;
- stdin encoding seleccionable y APIs lossy explícitas;
- `Bytes`, binary file IO, byte views y la forma general de `Result`/`Option`;
- adapters Windows, Darwin, WASI y targets sin filesystem;
- ABI/versionado de stdlib precompilada y runtime separado;
- efecto público `nounwind`/IO; las exceptions continúan unchecked en firmas.

Antes de implementar IO-V1 sí debe cerrarse la firma fuente concreta de `void`
si el parser aún no la admite para estas funciones, y debe comprobarse que las
restricciones actuales de classes/enums owning permiten las cuatro exceptions y
`ReadLineResult` sin bypass especial. Cualquier extensión necesaria se califica
como dependencia general, no como excepción ad hoc para IO.

## 17. Consecuencias

La superficie distingue claramente tres clases de outcome: EOF nominal como
control normal, fallos operativos/encoding como exceptions recuperables y fallos
de recursos/invariantes como traps. Ningún estado válido necesita null o magic
values. El caller recibe sólo strings UTF-8 owned y nunca observa buffers o
handles del host.

`writeText` es útil y predecible sin prometer transacciones que POSIX/libc no
ofrecen por sí solos. La semántica de líneas y bytes es idéntica entre targets,
mientras path spelling y permisos permanecen correctamente en el provider. La
separación entre calls STD, runtime privado y adaptación POSIX evita congelar
una syscall o un opcode por función y deja que una futura biblioteca escrita en
Aether absorba la lógica cuando existan Bytes y builders seguros.
