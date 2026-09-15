# UNCAUGHT-EXCEPTION-DIAGNOSTICS-ARCH-1 — nominal root diagnostic

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-15.

Este milestone fija el diagnóstico V1 de una excepción Aether que abandona el
entrypoint. No modifica compiler-next, runtime, stdlib, tests ni compiler
legacy. La implementación y qualification pertenecen a un vertical posterior.

La salida normativa, cuando el descriptor y stderr funcionan normalmente, es
exactamente:

```text
Unhandled <fully-qualified-exception-type>\n
```

El nombre es el del tipo nominal dinámico del objeto lanzado. El proceso termina
con status **70**, independientemente del valor que habría retornado `main`.

## 1. Decisiones resumidas

- La frontera es el wrapper nativo `main` generado por compiler-next, en el
  landing pad root del `invoke` al `main` Aether.
- Sólo un `ExceptionEvent` Aether que escapa de ese invoke activa el reporter.
  Traps y fallos de proceso no se convierten en exceptions ni se capturan.
- El reporter carga el descriptor desde el objeto payload. Por tanto observa la
  clase concreta que fue construida y lanzada, no el tipo estático de una
  variable, parámetro, catch o call.
- Cada class descriptor obtiene una referencia a metadata diagnóstica estática.
  Para V1 esa metadata sólo es un slice `{bytes, length}` con el display nominal.
- No se cambia el header del objeto: continúa conteniendo refcount y un único
  puntero a su class descriptor. No se agrega metadata por instancia.
- Un tipo declarado en package nombrado se muestra como
  `<package-source>.<type-name>`. El origin interno Project/Toolchain no se
  imprime. Así, los tipos STD se muestran naturalmente como `std.IO.X` o
  `std.File.X`.
- Un tipo del anonymous package se muestra sólo como `<type-name>`. No se
  sintetiza `main`, `default`, `root` ni `anonymous`.
- La clase Core inyectada `Exception` se muestra como `Exception`; su ubicación
  física provisional en el módulo entry no le atribuye el package del usuario.
- El reporter escribe a file descriptor 2, incluye exactamente un LF final y
  no usa `std.IO`, formatting, strings Aether ni heap allocation.
- El root reporta antes de terminar el catch nativo. Después llama una sola vez
  a la operación vigente de fin de catch; el destructor del record libera su
  única obligación sobre el payload.
- Un fallo de escritura produce sólo salida best-effort, no otra exception. El
  root igualmente completa el evento y retorna 70.

## 2. Estado actual auditado

### 2.1 Transporte y boundary

EXCEPTION-V1 baja el `ExceptionEvent` a Itanium EH en Linux x86-64. El wrapper
nativo actual invoca el entry Aether con un unwind edge hacia
`aether_unhandled`. Ese landing pad obtiene el record mediante
`__cxa_begin_catch`, carga su payload, llama al reporter, ejecuta
`__cxa_end_catch` y retorna 70.

El sitio físico ya es el boundary correcto. El cambio futuro reemplaza el texto
constante del reporter, no agrega un `try` fuente alrededor de `main`, no altera
el ABI del entry Aether y no instala TLS ni un handler por frame.

### 2.2 Objeto, descriptor y matching

Un class object tiene actualmente este prefijo privado conceptual:

```text
ObjectHeader {
    strong_count
    class_descriptor*
}
```

La construcción guarda el descriptor de la clase exacta. Upcasts, aliases,
propagación, catch binding y rethrow preservan el mismo objeto; no reemplazan su
descriptor. `ExceptionMatches` ya carga ese puntero dinámico y lo compara con
descriptors canónicos.

Por ello la identidad concreta necesaria **ya llega al root**. No hace falta
agregar un type id al `ExceptionEvent` ni copiar el tipo estático al throw
record. Hacerlo crearía dos autoridades que podrían divergir.

El descriptor LLVM actual, sin embargo, es un array privado de punteros cuyo
primer slot es destroy y cuyos slots restantes sirven a dispatch/witnesses. No
contiene un display nominal accesible de forma uniforme. El backend podría
generar un switch de todos los descriptor pointers a literals, como hace hoy el
matching bootstrap, pero eso duplicaría una tabla de identidad y convertiría el
reporter en conocimiento cerrado del programa. La decisión V1 es extender el
descriptor canónico mínimamente.

### 2.3 Identidad fuente disponible en compile time

`ClassInfo` ya conserva `module` y `name`; `ModuleInfo.key.package` distingue
`Named { origin, path }` de `Anonymous`. `PackagePath.source()` conserva los
segmentos con `.`. Es información suficiente para construir una vez, durante
codegen, el display estable. `ModuleInfo.display_name`, el mangled symbol, el
logical source key y el path físico no son autoridad para este propósito.

## 3. Boundary exacto y clasificación

El único boundary V1 es:

```text
native main
  invoke aether entry main
    normal -> convierte su int al status ordinario
    Aether unwind -> root landing pad -> report -> finish event -> status 70
```

El evento sólo se considera reportable después de que el mecanismo EH vigente
lo haya reconocido como el record privado Aether y haya entregado un payload
válido. El reporter no acepta un puntero C arbitrario como excepción. La
restricción FFI vigente —ninguna exception extranjera entra y ninguna Aether
sale por una frontera C— permanece cerrada. Un port futuro debe ofrecer la
misma clasificación aunque no use Itanium EH.

No activan esta ruta:

- retorno ordinario de `main`, incluso si retorna 70;
- division/bounds/allocation/ARC/runtime-invariant traps;
- señales, abort, crash handlers o foreign exceptions;
- una excepción consumida por cualquier catch Aether antes del root.

El boundary no construye ni lanza otra excepción, no ejecuta catch matching
fuente y no cambia el payload.

## 4. Tipo dinámico concreto

La única autoridad para el tipo mostrado es el `class_descriptor*` cargado del
payload vivo. El algoritmo conceptual es:

```text
payload -> dynamic class descriptor -> diagnostic metadata -> display bytes
```

Está prohibido derivar el display desde:

- el tipo estático del operando de `throw`;
- `Exception` o el tipo de un catch anterior;
- el descriptor de una base que haya matcheado;
- el nombre de la función que lanzó;
- el RTTI/type-info usado por el unwinder;
- un mangled symbol.

Así, si un owner está tipado como `MyBaseException` pero apunta a un
`MyConcreteException`, el resultado sigue siendo el display de
`MyConcreteException`. Bare rethrow conserva exactamente ese resultado porque
reutiliza record, payload y descriptor.

MIR/SSA no necesitan una nueva copia del ClassId en el evento. Sus invariantes
actuales de owner único y forwarding sin sustitución son suficientes. Puede
agregarse una operación terminal explícita `ReportUnhandled(event)` a dumps o
verificadores si mejora la inspección, pero no es requisito semántico del V1 y
no debe permitir disponer el evento dos veces.

## 5. Naming y display source-facing

El display se calcula en compile time a partir de identidad nominal canónica:

| Identidad de declaración | Display V1 |
| --- | --- |
| `PackageKey::Named(_, A.B)` + `E` | `A.B.E` |
| `PackageKey::Anonymous` + `E` | `E` |
| toolchain `Named(Toolchain, std.IO)` + `E` | `std.IO.E` |
| Core compiler-owned `Exception` | `Exception` |

`OriginKey` evita colisiones internamente, pero no es sintaxis Aether y nunca se
imprime. La raíz `std` ya está reservada a la toolchain, por lo que omitir el
origin no crea una identidad fuente falsa. Packages parciales comparten el
mismo `PackageKey`; el archivo contribuyente no aparece en el nombre.

El anonymous package carece deliberadamente de path fuente. Concatenar su label
de dump (`<anonymous package>`) o su logical source produciría un nombre que el
programador nunca pudo escribir y queda prohibido.

Las clases actuales son declaraciones top-level; no existe nesting nominal de
clases que deba codificarse en V1. Si una feature futura admite tipos nominales
anidados, debe extender la identidad semántica con la cadena de enclosing
nominals y su display será `<package.>Outer.Inner.E`. No puede inferir nesting
desde `$`, mangling, scopes LLVM ni el path del archivo. Este milestone no
reserva una sintaxis de nesting ni admite la feature.

Los bytes se emiten tal como resulta del spelling nominal canónico aceptado por
el frontend, con `.` como separador. No se aplica filesystem normalization,
locale, demangling ni dependencia del CWD.

## 6. Metadata runtime mínima

El class descriptor incorpora un slot fijo adicional que apunta a una record
estática, inmutable y privada:

```text
ClassDescriptorPrefix {
    destroy_fn
    diagnostic_type*
    // virtual/interface slots existentes, con offsets recalculados
}

DiagnosticTypeMetadata {
    bytes*
    byte_length
}
```

`bytes` apunta a una constante del módulo/objeto generado. `byte_length` es la
longitud exacta y no incluye terminador NUL. El reporter es length-aware; un NUL
no tendría significado especial aunque la gramática actual no lo admita en un
identifier.

La metadata se emite para toda clase alcanzable que pueda ocupar un descriptor.
Como los descriptors comparten layout, las clases que no derivan de Exception
también pueden apuntar a su metadata nominal; no existe API Aether para
observarla. Esto cuesta un word estático por descriptor más la constante
deduplicable, pero **cero bytes por objeto**, cero loads en el path ordinario y
cero registros extra en el event. Si el linker/backend puede probar que un
descriptor jamás necesita diagnóstico, puede usar null o eliminar su record,
siempre que todos los posibles tipos dinámicos derivados de Exception conserven
metadata válida.

Un único puntero en el descriptor se prefiere a insertar `bytes` y `length`
directamente porque mantiene pequeño el prefijo común y deja una record
extensible de metadata diagnóstica. Esa record no es reflection general:

- no es addressable desde source;
- no enumera fields, methods, bases, interfaces ni source locations;
- no participa en matching, casts o dispatch;
- no es una ABI pública ni un registro global por nombre;
- su string es presentación, nunca autoridad de identidad.

La autoridad de catch matching continúa siendo el descriptor canónico y las
relaciones nominales verificadas. Dos strings iguales nunca hacen que dos tipos
matcheen.

Agregar el slot desplaza los offsets físicos de virtual slots y witnesses. El
primer vertical debe centralizar esos índices en el backend y actualizar todas
las cargas; no debe preservar números mágicos divergentes. Como el class ABI es
privado y se genera/linkea en conjunto en V1, esto no constituye una ruptura de
ABI público.

## 7. stderr, formato y newline

En el caso saludable, stderr recibe exactamente tres slices concatenados:

```text
"Unhandled "
dynamic diagnostic name bytes
"\n"
```

No hay prefijo del driver, comillas, colon, mensaje adicional, color ni
whitespace extra. LF (`0x0A`) es obligatorio, incluso cuando stderr es un
terminal. stdout no recibe bytes del reporter.

La implementación usa una primitive privada non-throwing equivalente a
`write_all(fd=2, bytes, length)`. Debe manejar short writes y puede reintentar
`EINTR` cuando el target lo declara seguro. No llama a `std.IO.eprintln`: esa
API puede lanzar precisamente durante el path que debe contener el fallo, usa
objetos string y agregaría resolución/ownership innecesarios.

## 8. Exit code

El status estable V1 para una excepción Aether no capturada es **70**. Consolida
la elección ya implementada y calificada por EXCEPTION-V1.

- Cero continúa significando éxito.
- Los retornos ordinarios de `main` conservan su conversión vigente, incluido un
  retorno ordinario de 70; el canal stderr distingue observacionalmente ambos,
  pero el status no pretende codificar la causa completa.
- El valor parcial/no producido por un `main` que lanzó nunca se consulta.
- Todos los tipos de exception uncaught usan 70.
- Un fallo de escritura del diagnostic no cambia 70.

No se reserva en este milestone un mapa de status por excepción. El número es
contrato del proceso V1, no parte del object ABI ni del record del unwinder.

## 9. Ownership, orden y cleanup

Al ejecutar `throw`, el owner del payload se transfiere al record EH privado. El
event mantiene exactamente esa obligación durante propagation. Los cleanups de
frames ya atravesados han concluido antes de que el evento alcance el landing
pad root; el boundary no los repite.

Orden normativo en root:

1. comenzar/obtener el evento capturado con la operación EH vigente;
2. pedir prestado el payload vivo al record;
3. cargar descriptor y metadata, y escribir el diagnóstico;
4. dejar de usar payload, descriptor y metadata;
5. finalizar exactamente una vez el catch/evento;
6. el destructor del record libera exactamente una vez su owner de payload;
7. retornar status 70.

El root **no** hace un `aether_object_release(payload)` manual además de
`end_catch`. En el diseño vigente, `__cxa_end_catch` provoca la destrucción del
record cuando corresponde y `aether_exception_record_destroy` realiza ese
release. Un release manual sería double-drop. Omitir `end_catch` filtraría
record y payload.

La impresión precede al release porque nombre y descriptor se alcanzan desde el
payload. La metadata estática sobrevive al objeto, pero el root no conserva un
puntero interior del payload después de finalizar el event. Aliases de bindings
de catches previos obedecen sus cleanups léxicos antes de rethrow/resume y no
cambian la obligación del record.

`finally` mantiene su semántica: se ejecuta durante unwind antes del root. Si
termina normalmente, llega el mismo event; si altera el control según las reglas
ya calificadas, este milestone no introduce una excepción especial.

## 10. Fallos del propio diagnostic

El path normal del reporter no asigna memoria, no crea `string`, no formatea y
es `nounwind`. Por tanto no puede producir una excepción Aether ni un trap de
OOM por una allocation propia.

La política para IO de stderr es best-effort:

- short write: continuar con los bytes restantes;
- `EINTR`: reintentar bajo el contrato del target;
- error terminal o zero progress: abandonar las escrituras restantes;
- en todos esos casos: finalizar el event y retornar 70.

Si stderr falla puede observarse una línea truncada o ninguna salida. No se
escribe un fallback a stdout, no se lanza `IOException`, no se entra
recursivamente al reporter y no se preserva errno como status de proceso.

Metadata nula, longitud imposible, payload corrupto o descriptor inválido son
violaciones de invariantes del runtime, no condiciones recuperables. Pueden
terminar mediante el trap vigente. El root no captura ese trap ni promete
cleanup posterior a corrupción. Bajo metadata válida, ninguna carga o cálculo
del reporter debe usar operaciones checked que introduzcan traps evitables.

Una OOM ocurrida antes, durante la construcción o durante el empaquetado de la
exception sigue siendo un trap y nunca se presenta como `Unhandled E`. No hay
OOM propia después de que el event válido alcanza el boundary.

## 11. Compatibilidad e invariantes

Este diseño no cambia:

- jerarquía, construcción, `throw`, bare rethrow o catch ordering;
- matching exacto/base ni su autoridad nominal;
- exceptional CFG, unwind, cleanup, drop flags o `finally`;
- semántica o captura de traps;
- firma y retorno ordinario del entrypoint;
- excepción-free elision del runtime EH;
- compiler legacy.

Un programa exception-free debe seguir sin emitir record/reporter EH. La
metadata nominal de clases ordinarias puede ser eliminada por reachability. Un
programa con exceptions capturadas puede contener el reporter por ser una ruta
posible del entry, pero no escribe nada si el event no llega al root.

O0 y O2 deben conservar bytes, status, tipo dinámico y lifecycle idénticos. Las
optimizaciones pueden deduplicar literals/records, pero no sustituir el dynamic
descriptor por un tipo estático salvo prueba de exactitud que preserve el mismo
resultado observable.

## 12. Primer vertical de implementación

Nombre recomendado: **UNCAUGHT-EXCEPTION-DIAGNOSTICS-V1 — concrete nominal
root report**.

Orden de implementación:

1. agregar una construcción frontend/backend única del display desde
   `ClassInfo` y `PackageKey`, con caso explícito para Core `Exception`;
2. extender el descriptor con `diagnostic_type*`, emitir records/literals
   estáticos y centralizar los offsets de destroy/virtual/witness;
3. reemplazar el reporter constante por loads del descriptor dinámico y writes
   length-aware non-throwing a fd 2;
4. conservar el landing pad root y verificar el orden report/end-event/status;
5. agregar qualification nativa O0/O2 y probes de lifecycle.

La matriz mínima debe cubrir:

- `std.File.FileNotFoundException`;
- `std.IO.InvalidTextEncodingException`;
- una exception de usuario en package nombrado;
- una exception de usuario en anonymous package;
- base estática con objeto derived concreto;
- exception atrapada sin diagnóstico;
- rethrow finalmente uncaught;
- `finally` observado antes del diagnóstico;
- stdout vacío y stderr byte-exacto con un LF;
- status 70, también frente a un `main` que retorna 70 normalmente;
- alloc/free, retain/release y destroy balanceados sin leak/double-drop;
- fallo/short write/EINTR de stderr mediante seam privado inyectable;
- equivalencia O0/O2;
- ausencia del runtime EH en un programa exception-free;
- dumps/verificadores corruptos para metadata/event disposition cuando aplique.

Los tests de naming deben compilar por el catálogo real para no confundir
`ModuleInfo.display_name` con `PackageKey`. Los tests de lifecycle deben contar
la disposición después del report y no insertar un release manual en el
fixture.

## 13. Fuera de scope

- stack traces, frames, source locations o line numbers;
- mensajes, `what()`, `toString()`, payload rendering o causes;
- nested/chained/suppressed exceptions;
- colores, panic reports, logging, crash handlers o debugger integration;
- reflection, lookup por nombre, casts o serialización de type metadata;
- distinguir exception types mediante exit code;
- cambios a traps, FFI, unwinder o targets adicionales;
- API pública para descriptors o metadata;
- compiler legacy.

## 14. Decisiones abiertas

No queda ninguna decisión abierta que bloquee el vertical V1. Permanecen para
milestones independientes:

- formato de message/cause/stack trace y política de symbolication;
- ABI estable de descriptors/runtime y soporte de separate compilation;
- nombres de tipos nominales anidados si esa superficie se admite;
- política portable de status en targets que no exponen un exit code POSIX;
- contención de foreign exceptions en exports/callbacks futuros;
- sincronización/atomicidad de diagnostics bajo threads;
- fallback de bajo nivel para stderr cerrado o irrecuperable;
- generalizar `DiagnosticTypeMetadata` a reflection, que requiere otra
  arquitectura y no se infiere de este record privado.

