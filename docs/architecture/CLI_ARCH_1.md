# CLI-ARCH-1 — official Aether CLI and project boundary

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-26.

Este milestone define la futura CLI oficial `aether`, su frontera in-process
con `aether-driver`, el contrato inicial de `aether.toml` y la transición del
CLI Python actual a `aether-legacy`. No agrega comandos, crates, manifests de
proyecto, resolución de dependencias ni nuevos binarios. Hasta un vertical de
implementación, los ejecutables y flags actuales conservan su comportamiento.

La autoridad del compilador nuevo sigue siendo `compiler-next`. Este documento
no cambia semántica source, pipeline, runtime ni formato de artefactos.

## 1. Decisiones cerradas

- La nueva CLI oficial será un ejecutable Rust llamado `aether` y usará
  `compiler-next` directamente.
- El frontend CLI poseerá parsing, UX, configuración y resolución explícita de
  proyecto; `aether-driver` poseerá `check`, `build` y `run`.
- La llamada CLI → driver será una API Rust tipada en el mismo proceso. La CLI
  no ejecutará `aether-next`, `aether-legacy` ni otra CLI para compilar.
- `run`, `build` y `check` exigirán exactamente un target archivo o directorio.
- Sólo un primer argumento que denote un archivo `.ae` tendrá shorthand a
  `run`; `aether .` no existirá.
- `--` será la frontera irreversible entre argumentos de Aether y argumentos
  del programa, únicamente para `run` y su shorthand.
- Un target archivo nunca buscará ni adoptará `aether.toml`. Un target
  directorio será exactamente el project root y deberá contener directamente
  `aether.toml`.
- `aether.toml` V1 describirá identidad, compatibilidad de toolchain, un entry
  ejecutable opcional y dependencias registry/path. No incluirá git, profiles,
  workspaces, features, dependencias nativas, build scripts ni múltiples
  targets ejecutables.
- El nombre de package será también su namespace de import. No habrá traducción
  implícita entre spellings.
- La CLI Python actual se renombrará `aether-legacy`, quedará congelada salvo
  fixes críticos y se retirará sólo tras alcanzar el gate de la sección 15.
- La nueva experiencia no tendrá `--compiler next|legacy` ni fallback al
  compilador legacy.

## 2. Capas y ownership

```text
argv / cwd / environment
          |
          v
  aether-cli  (binario `aether`)
  - gramática y ayuda
  - configuración de UX
  - clasificación explícita file/project
  - lectura y validación de aether.toml
  - conversión a DriverRequest
          |
          | llamada Rust in-process
          v
  aether-driver
  - check/build/run
  - planificación de inputs ya resueltos
  - selección de fase y outputs
  - toolchain/link y ejecución del artefacto
          |
          v
  frontend -> HIR -> MIR -> SSA -> backend
```

`aether-cli` no contiene lexer, parser, typechecker, lowering, optimizaciones,
codegen ni reglas duplicadas de entrypoint Aether. Presenta diagnostics del
driver pero no intenta reconstruirlos. `aether-driver` no interpreta argv,
elige shorthand, busca manifests ni decide precedencia de configuración.

El driver puede ejecutar `clang` como toolchain y el artefacto producido para
`run`: ésas son fronteras de proceso necesarias, no shell-out a otra CLI Aether.
Debe usar `Command` con argumentos separados, nunca construir un comando de
shell. La ejecución del programa hereda stdin/stdout/stderr salvo que una API
embebida solicite captura explícita en el futuro.

La implementación recomendada añade en un milestone posterior un crate
`compiler-next/crates/aether-cli` con binario `aether`. El crate existente
`aether-driver` permanece librería de orquestación. Su binario bootstrap
`aether-next` puede seguir siendo una herramienta interna mientras migra la
suite, pero no forma parte de la interfaz instalada final ni es invocado por
`aether`.

## 3. Gramática pública V1

La gramática conceptual inicial es:

```text
Invocation     := "aether" (CommandInvocation | FileShorthand)
CommandInvocation := Run | Build | Check | Init
Run            := "run" Target RunOption* ("--" ProgramArg*)?
Build          := "build" Target BuildOption*
Check          := "check" Target CheckOption*
Init           := "init" InitOption* PackageName
FileShorthand  := AeFile RunOption* ("--" ProgramArg*)?
Target         := AeFile | Directory
```

El spelling canónico documentado es:

```text
aether run file.ae
aether run .
aether build file.ae
aether build .
aether check file.ae
aether check .
```

`aether file.ae` se normaliza antes de ejecución al mismo request que
`aether run file.ae`. El shorthand se reconoce sólo cuando el primer token:

1. no es una opción;
2. no coincide con un subcomando conocido por esa versión de la CLI; y
3. tiene extensión final `.ae`.

La prioridad del subcomando evita ambigüedad aunque exista un archivo llamado
`run`. Agregar un subcomando futuro puede reservar ese primer token, pero no
afecta archivos `.ae` porque los comandos oficiales no usan esa extensión.
Tras reconocer el shorthand, se aplican exactamente parser, opciones, frontera
`--`, driver request y códigos de salida de `run`; no existe una segunda ruta.

Son errores de uso, antes de invocar al driver:

```text
aether run
aether build
aether check
aether .
aether run one.ae two.ae
```

`test`, `add`, `remove`, `sync`, `update`, `install`, `uninstall` y `publish`
son espacio reservado de evolución, no comandos V1 presentes ni stubs. Un
token desconocido falla como subcomando desconocido; nunca se trata como path
salvo la regla `.ae` anterior.

El orden exacto de opciones de compilación se cerrará con el primer vertical,
pero no podrá debilitar la cardinalidad del target ni el significado de `--`.
Opciones globales como `--help` y `--version` son UX y no requests del driver.

## 4. Frontera estricta `--`

En `run`, el primer `--` termina por completo el parsing de Aether. Cada token
posterior, incluso `--help`, `-O2`, otro `--` o un path, se entrega al programa
en el mismo orden y sin reinterpretación:

```text
aether run file.ae -- arg1 -x -- arg2
                         \________________/
                           argv del programa
```

La frontera funciona idénticamente para proyectos y shorthand:

```text
aether run . -- arg1 arg2
aether file.ae -- arg1 arg2
```

El separador no pertenece al argv resultante. Sin separador, ningún token se
reenvía implícitamente. `build` y `check` no ejecutan programa y por ello
rechazan `--` y cualquier cola posterior; no la ignoran. La CLI nunca vuelve a
parsear lo que ya quedó a la derecha de la frontera.

## 5. Resolución de target

La CLI resuelve el único spelling recibido contra el CWD y consulta el tipo de
filesystem una vez. Un archivo regular con extensión `.ae` produce
`ResolvedTarget::File`; un directorio produce `ResolvedTarget::Project`. Un
path inexistente, una extensión distinta, un manifest pasado como archivo o un
tipo especial falla con diagnóstico de CLI. Symlinks se resuelven a su target;
la identidad canónica resultante se pasa al driver para evitar dos roots
accidentales para el mismo objeto.

### 5.1 Archivo

Para `aether run foo.ae`, y de igual manera para `build` y `check`:

- `foo.ae` es exactamente el entry/input seleccionado;
- su directorio contenedor puede servir como source root del grafo de imports
  que el compilador ya resuelva;
- no se consulta `aether.toml` en ese directorio ni en ancestors/descendants;
- no se adopta nombre, dependencias, entry ni configuración de un proyecto
  circundante;
- un manifest inválido vecino no puede afectar el resultado.

Resolver imports propios del source graph no constituye project discovery. El
request de archivo sigue siendo standalone y no obtiene identidad de package
desde el path.

### 5.2 Directorio

Para `aether run path/`, el directorio canónico es exactamente el project root.
La CLI prueba sólo `<root>/aether.toml` como archivo regular:

- no asciende a ancestors;
- no busca manifests en descendants;
- no convierte automáticamente el CWD en target;
- no elige entre varios manifests.

Por tanto `aether run .` falla claramente si `./aether.toml` no existe. Un
manifest encontrado mediante un symlink dentro del root sigue siendo el único
manifest directo, pero su lectura no cambia el root canónico ni permite escapar
las reglas de paths de aplicación de la sección 8.

Esta política se denomina **resolución explícita de proyecto**, no búsqueda
implícita. El CWD sólo resuelve el spelling relativo; no participa luego en
identidad, cache keys ni selección de manifest.

## 6. Request tipado hacia el driver

La frontera futura debe expresar intención, no volver a entregar argv:

```text
DriverRequest {
    operation: Check | Build | Run { program_args },
    input: StandaloneFile(StandaloneInput) | Project(ProjectPlan),
    compilation: CompilationOptions,
    output: OutputPolicy,
}
```

`StandaloneInput` contiene el archivo canónico y el source root explícito.
`ProjectPlan` contiene root/manifest canónicos, metadata validada, roots source
e información de dependencias ya clasificada. Los tipos concretos se diseñarán
en Rust, pero deben hacer imposible representar target ausente, dos targets,
argumentos de programa en `build/check` o un proyecto sin manifest.

El driver valida de nuevo invariantes relevantes en su frontera; no confía en
que un caller distinto del CLI haya construido paths seguros. A partir del plan
crea una sesión del compiler pipeline, sin duplicar análisis semántico.

Las operaciones tienen contratos distintos:

- `check`: parsea, resuelve y analiza el grafo completo; no requiere clang, no
  enlaza, no crea ejecutable y no ejecuta. El pipeline debe exponer un límite
  semántico real en vez de generar LLVM para desecharlo.
- `build`: compila outputs retenidos según la clase del package. El nombre y
  formato final de artefactos de librería se cierra en su vertical, pero la API
  no puede exigir un entry ejecutable para validar un package library-only.
- `run`: exige exactamente un runnable entry, construye un artefacto temporal,
  lo ejecuta con `program_args` y limpia el temporal aun ante error normal.

No se implementa esta API en CLI-ARCH-1. Las funciones bootstrap actuales
`build_path`/`run_path_with_arguments` son evidencia reutilizable, no el
contrato final: hoy mezclan discovery, pipeline, link y algunas decisiones de
CLI, y `check` necesita una frontera dedicada.

## 7. `aether.toml` V1

Forma conceptual:

```toml
[package]
name = "myProject"
version = "0.1.0"
aether = "1"

[application]
entry = "src/main.ae"

[dependencies]
linearAlgebra = "1.2"
localLibrary = { path = "../localLibrary" }
```

El archivo es UTF-8 y TOML. Keys o tablas desconocidas bajo el schema V1
fallan cerradas con su ubicación cuando el parser la provea; no se ignoran por
si pertenecieran a una versión futura. `[package]`, `name` y `version` son
obligatorios. `[application]`, `application.entry`, `package.aether` y
`[dependencies]` son opcionales.

`package.name` y `package.version` forman la identidad declarada. `version` usa
SemVer. `package.aether` es un requerimiento de compatibilidad del lenguaje y
toolchain, no la versión del package ni del formato de manifest. El valor
conceptual `"1"` acepta una toolchain que implemente la línea de lenguaje
Aether 1 compatible; el vertical de manifest fijará la gramática completa de
constraints antes de aceptar otros spellings. Si se omite inicialmente, la CLI
usa la línea compatible que documente esa release y puede advertir, pero no
inventa el campo en disco.

La edición futura de `aether.toml` por `init/add/remove` debe usar writes
atómicos y preservar contenido no gestionado siempre que el schema lo admita.
CLI-ARCH-1 no implementa ninguna mutación.

## 8. Application y roots de package

`[application].entry` es un path relativo al project root, debe terminar en
`.ae`, resolver a un archivo regular y permanecer dentro del root tras resolver
symlinks. Paths absolutos, `..` que escape y targets especiales se rechazan.

La selección runnable es determinista:

1. si existe `application.entry`, usar exactamente ese archivo o diagnosticar
   su ausencia/invalidez;
2. en otro caso, si `<root>/src/main.ae` existe como archivo regular, usarlo;
3. en otro caso, el package no tiene runnable entry.

No se buscan otros `main.ae`, no se inspecciona el source para adivinar un
entry y no se cae de un `application.entry` inválido a la convención. V1 admite
como máximo un target source por package. Múltiples binarios y una tabla de
targets quedan fuera.

La única convención library V1 es `<root>/src/lib.ae`; no existe `[library]` ni
otro root configurable. La clasificación completa es:

| Files/manifest | Clase V1 |
|---|---|
| entry de aplicación solamente | application package |
| `src/lib.ae` solamente | library package |
| ambos | error: múltiples targets no soportados |
| ninguno | error: package sin source root |

La existencia se comprueba después de aplicar la regla de entry, por lo que un
`application.entry` declarado pero inválido siempre es error y nunca cae a
`src/main.ae` o `src/lib.ae`. El root de librería obedece el mismo confinamiento
al project root que el entry de aplicación.

`aether run <project>` falla para la clase library. `check` y `build` aceptan
ambas clases; build de library produce un artefacto de package retenido, cuyo
encoding/extensión física debe cerrarse antes de implementar ese vertical. No
se finge un `main`, no se enlaza un ejecutable para una library y no se compilan
automáticamente ambos roots.

El compilador, no el parser de TOML, valida finalmente que el archivo elegido
contenga un entrypoint Aether válido. `application.entry` selecciona una unidad;
no declara ni sintetiza `main`.

## 9. Dependencies V1

Cada key de `[dependencies]` es simultáneamente:

- el nombre esperado del package resuelto;
- el namespace disponible para imports; y
- la identidad escrita por comandos futuros como `aether add`.

No hay aliases V1. Si metadata descargada o el manifest local declara otro
`package.name`, la resolución falla; no reetiqueta el package.

Una dependencia posee exactamente una fuente:

```toml
[dependencies]
statistics = "1.2"                    # registry + constraint
localLibrary = { path = "../localLibrary" } # project local
```

La string de registry es una constraint de versión, no URL ni git ref. Un path
se resuelve relativo al manifest que lo declara, puede estar fuera del root y
debe apuntar a un directorio con `aether.toml` directo. La misma política de no
buscar ancestors/descendants se aplica recursivamente. Cycles, nombres
discordantes, manifests duplicados por canonicalización y constraints
incompatibles deben diagnosticarse determinísticamente.

Git dependencies, URLs arbitrarias y tablas que mezclen `path`, `git` o una
versión registry quedan fuera. CLI-ARCH-1 sólo fija el modelo; no elige registry,
protocolo, lockfile, cache, algoritmo de resolución ni política offline.

## 10. Naming

La convención oficial y de documentación es `camelCase`:

```text
linearAlgebra
statistics
differentialEquations
```

Un nombre aceptado debe ser un identificador Aether válido utilizable como
segmento de namespace. La implementación no agrega un linter bloqueante que
exija camelCase si otro identificador Aether es válido. Sí rechaza nombres que
no puedan ser namespace y no transforma spellings:

```text
linear-algebra  !=  linearAlgebra
```

No hay kebab-to-camel, case folding, normalización de guiones ni alias mágico.
La comparación usa la identidad canónica que defina el lenguaje para sus
identificadores. Las OAL y documentación oficial publican nombres camelCase.

## 11. `init` futuro

El comando V1 previsto:

```text
aether init myProject
```

creará conceptualmente, sin sobrescribir paths existentes:

```text
myProject/
  aether.toml
  src/
    main.ae
```

El nombre del directorio solicitado y `package.name` serán `myProject`; no se
transforman. Una variante posterior:

```text
aether init --lib myLibrary
```

creará conceptualmente:

```text
myLibrary/
  aether.toml
  src/
    lib.ae
```

`init` validará completamente el nombre antes de escribir y publicará el árbol
de forma recuperable/atómica en la medida que permita el filesystem.

No se implementa `init`, `--lib` ni un template en este milestone. Tampoco se
publican flags o help placeholders que parezcan soporte parcial.

## 12. Configuración y composabilidad

La configuración de CLI sólo puede decidir concerns de toolchain/UX ya
representables en `CompilationOptions` y `OutputPolicy`. La precedencia futura
será explícita: argumentos CLI sobre configuración de proyecto, ésta sobre
defaults de toolchain. Variables de entorno admitidas deberán estar enumeradas;
no se leerán opciones arbitrarias del entorno.

La selección de target, nombre/version del package, entry y dependencias no se
puede cambiar silenciosamente por configuración global. En particular ningún
config convierte un file target en project target ni habilita discovery hacia
arriba.

Para composabilidad:

- stdout queda reservado al resultado solicitado y a output del programa;
- progress, diagnostics y timings van a stderr;
- éxito sin output solicitado puede ser silencioso;
- color obedece TTY/configuración y una futura opción estable;
- diagnostics conservan paths/source spans del compiler pipeline;
- no hay prompts interactivos en `run/build/check`.

Un modo machine-readable puede agregarse después como contrato versionado; no
se infiere parseando texto humano ni se crea un stub ahora.

## 13. Errores y códigos de salida

La implementación distinguirá al menos:

| Resultado | Exit status |
|---|---:|
| éxito de `check/build/init` | 0 |
| uso CLI, target o manifest inválido | 2 |
| fallo de compilación/toolchain | 1 |
| `run`: programa termina normalmente | status del programa |
| `run`: señal/status no representable | 1, con diagnóstico |

La colisión entre un exit 2 del programa y un error de uso se acepta: el canal
y el hecho de haber iniciado el programa los distinguen. La CLI no reescribe
stdout/stderr ni traduce argumentos para hacerlos distinguibles.

Diagnostics mínimos específicos incluyen target requerido, path inexistente,
archivo no `.ae`, target directory sin `aether.toml` directo, manifest inválido,
entry configurado inválido y project sin runnable entry. Deben nombrar el path
exactamente probado y no sugerir que se buscó fuera de él.

## 14. Espacio futuro del package manager

La separación permite agregar después:

```text
test  add  remove  sync  update
install  uninstall  publish
```

Los comandos que muten manifests/lockfiles pertenecerán a `aether-cli` o a un
futuro crate de proyecto/package management reutilizable, no al compiler
frontend. La resolución producirá el mismo `ProjectPlan` consumido por el
driver. El compiler pipeline recibe un grafo resuelto y no conoce registry,
credenciales, red ni UX.

No se decide todavía la diferencia exacta entre `sync/update`, scopes de
`install`, autenticación de `publish`, lockfile o layout de cache. Reservar el
espacio no autoriza comportamiento ni permite aceptar esos comandos.

## 15. Transición legacy

La migración se hace por hitos observables:

1. **CLI-ARCH-1 (este milestone):** sólo contrato documental. `aether` actual,
   `aether-next` y packaging no cambian.
2. **Bootstrap Rust:** aparece el crate CLI y sus pruebas bajo nombre de
   desarrollo; llama in-process al driver y cubre targets archivo para
   `run/build/check`.
3. **Proyecto/init:** implementa resolución exacta de directorio, manifest,
   roots `src/main.ae`/`src/lib.ae` e `init`; califica packages application y
   library-only.
4. **Promoción:** packaging instala la CLI Rust como `aether` y la CLI Python
   como `aether-legacy` en un único cambio coordinado. Documentación, extensiones
   de editor, scripts y tests dejan de depender de flags legacy.
5. **Freeze:** desde la promoción, legacy recibe sólo fixes críticos de
   seguridad, pérdida de datos o regresiones que bloqueen migración. Features y
   cambios normales van sólo a Rust/compiler-next.
6. **Retiro:** `aether-legacy` se elimina cuando la nueva CLI cubra y esté
   calificada para `run`, `build`, `check`, `init` y package manager V1.

La promoción no mantiene dos compiladores detrás de `aether`. La nueva CLI no
acepta `--compiler`, no consulta una variable equivalente y no cae a legacy si
compiler-next rechaza un programa. Los usuarios que necesiten la superficie
histórica la invocan explícitamente como `aether-legacy` durante la ventana.

El nombre `aether-next` queda como bootstrap interno y se retira de instalación
pública cuando ya no lo necesiten tests/herramientas. No se renombra como
`aether` sin separar antes parsing CLI del driver.

## 16. Matriz normativa de comportamiento

| Invocación futura | Resultado |
|---|---|
| `aether run main.ae` | run standalone exacto; ignora manifests vecinos |
| `aether main.ae` | exactamente el request anterior |
| `aether main.ae -- -x` | ejecuta standalone con argv `[-x]` |
| `aether check main.ae` | check standalone, sin link |
| `aether build main.ae` | build standalone |
| `aether run .` con manifest directo y entry | ejecuta ese proyecto |
| `aether run .` sin manifest directo | error; no asciende ni desciende |
| `aether run project/` | `project/` es el root exacto |
| `aether run project/src/main.ae` | standalone; no adopta `project/` |
| `aether run lib/` sin entry runnable | error de runnable entry |
| `aether check lib/` válido | permitido conceptualmente |
| `aether .` | error; no shorthand de proyecto |
| `aether run` | error de target requerido |
| `aether build . -- args` | error; no argv de programa |
| `aether --compiler next run main.ae` | opción desconocida en CLI nueva |
| `aether add linearAlgebra` antes de package-manager V1 | comando no disponible |

## 17. Primer vertical recomendado

**CLI-V1-BOOTSTRAP** debería:

1. crear `aether-cli` y una gramática probada sin stubs de package manager;
2. introducir requests tipados y separar `check` semántico de codegen/link;
3. implementar `run/build/check` para archivo con target obligatorio, shorthand
   `.ae` y frontera estricta `--`;
4. llamar al driver in-process y eliminar cualquier necesidad de shell-out a
   `aether-next`;
5. probar que manifests vecinos nunca se leen y que argv se conserva byte por
   byte según lo entrega el sistema operativo;
6. mantener nombres instalados sin cambios hasta el milestone de promoción.

El vertical posterior de proyecto implementará TOML, directory targets,
application/library roots, el formato físico del output library e `init`; el
package manager vendrá después. Cada promoción necesita tests de unidad del
parser, integración de filesystem, API directa del driver y end-to-end O0/O2.

## 18. Fuera de scope y decisiones diferidas

Quedan fuera de CLI-ARCH-1:

- toda modificación de Rust/Python/packaging y todo nuevo ejecutable;
- implementación de manifest, `init` o comandos futuros;
- registry, networking, lockfile, cache y algoritmo de dependencias;
- encoding, extensión y artifact layout físico de librerías;
- cross-compilation, selección de toolchain instalada y distribución;
- workspaces, profiles, features, git/native dependencies y build scripts;
- múltiples binarios/targets, tests de package y publishing;
- formatos JSON de diagnostics o protocolo estable para IDEs.

Estas decisiones no habilitan discovery implícito, traducción de nombres,
fallback legacy ni lógica del compilador dentro de la CLI. Cualquier excepción
requiere un nuevo milestone explícito.
