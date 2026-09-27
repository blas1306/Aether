# PACKAGE-MANAGER-ARCH-1 — package manager V1

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-26.

Este milestone define el package manager de la CLI oficial `aether`. Su modelo
de resolución y reproducibilidad toma a Cargo como referencia; su flujo normal
busca la inmediatez de uv: un proyecto funciona sin crear ni activar un
environment y los comandos de uso frecuente tienen efectos simples y
predecibles.

No agrega comandos, crates, red, registry, cache, lockfile ni cambios al
compiler. La autoridad de CLI y proyecto sigue siendo
[CLI-ARCH-1](CLI_ARCH_1.md) y sus reportes de implementación. Cuando este
documento habla de una operación futura describe el contrato de
PACKAGE-MANAGER-V1, no funcionalidad disponible hoy.

## 1. Decisiones cerradas

- Existirá un registry público central, conceptualmente **Aether Package
  Registry**. Este milestone no fija su dominio.
- Los nombres son globalmente únicos dentro del registry. El nombre de package,
  la key de `[dependencies]` y el namespace de import son el mismo spelling.
- `camelCase` es la convención oficial; se acepta cualquier identificador Aether
  válido. V1 no tiene aliases, case folding ni traducciones de nombre.
- Las Official Aether Libraries (OAL) son versiones normales del mismo registry,
  diferenciadas sólo por ownership y metadata oficial.
- V1 admite dependencias del registry oficial y de path local. Git, registries
  privados y URLs arbitrarias quedan fuera.
- `aether.lock` registra el grafo exacto. Se genera tanto para applications como
  para libraries, debe versionarse, y nunca se incluye como autoridad al
  publicar una library.
- El grafo puede contener varias versiones del mismo nombre. Cada source unit
  resuelve imports en el contexto de la instancia de package que la posee; el
  source nunca escribe `name@version`.
- El resolver V1 es determinista, edge-local y usa la versión no-yanked más alta
  que satisfaga cada constraint. Nodos con identidad exacta igual se comparten;
  no se fuerza una versión global por nombre.
- `sync` conserva toda selección compatible del lock; `update` autoriza una
  resolución nueva. No existe actualización silenciosa durante build/check/run.
- Los archives verificados viven en un cache global content-addressed. `.aether/`
  contiene estado y outputs del proyecto, no copias privadas obligatorias de
  cada dependencia.
- Los packages publicados son source-first, sus versiones son inmutables y no
  ejecutan código durante instalación. Yank impide selecciones nuevas pero no
  invalida locks existentes.
- Project dependencies, environments opcionales e installs de usuario son tres
  scopes disjuntos. Un build de proyecto nunca consulta libraries instaladas
  globalmente ni un environment de manera implícita.
- El package manager termina en un grafo resuelto que extiende `ProjectPlan`.
  Registry, red, credenciales, cache y TOML raw no atraviesan la frontera del
  compiler.

## 2. Modelo y vocabulario

Una **versión publicada** se identifica por:

```text
RegistryPackageId = (registry-id, package-name, exact-semver)
```

El `registry-id` V1 es una constante lógica como `official`, no una URL. Así un
cambio futuro de hostname no cambia identidad ni lockfiles.

Una **instancia resuelta** agrega su fuente:

```text
ResolvedPackageId = Registry(registry-id, name, version, checksum)
                  | Path(canonical-path, name, version)
                  | Root(canonical-project-root, name, version)
```

El path canónico sólo es identidad de sesión para deduplicar y detectar cycles;
no se persiste como path absoluto. El lockfile guarda un locator relativo y
portable. Para registry, checksum forma parte de la identidad material exacta.

Cada nodo posee su manifest validado, uno o más source units catalogados por el
driver futuro, su clase application/library y una tabla:

```text
dependency import name -> exact ResolvedPackageId
```

La tabla pertenece al nodo, no al proceso entero. Por eso `A` puede resolver
`import math` a `math@1.8.0` y `B` resolver el mismo spelling a `math@2.1.0`.
Dentro de una instancia dada sólo puede existir un target directo por nombre.

El grafo resuelto debe ser un DAG. Un ciclo por registry, path o una mezcla de
ambos es error; V1 no define inicialización ni link de ciclos.

## 3. Registry oficial

El Aether Package Registry mantiene al menos:

- nombre global y versiones SemVer;
- owners actuales y publisher que realizó cada publicación;
- metadata permitida (descripción, licencia, repository/documentation cuando se
  estabilicen sus keys, clase y estado oficial OAL);
- manifest/dependencies normalizados por versión;
- archive source inmutable, tamaño y checksum criptográfico;
- estado `published` o `yanked`, timestamps y auditoría de cambios de estado.

La API de resolución debe poder obtener metadata versionada y el artifact por
checksum. HTTPS es obligatorio para el transporte, pero la autenticidad mínima
V1 termina en verificar el checksum esperado; package signing queda diferido.
Las respuestas que afectan resolución se ordenan por SemVer en el cliente y no
por orden de respuesta del servidor.

Una pareja `(name, version)` se crea una sola vez. Reintentar con los mismos
bytes puede ser idempotente; intentar reemplazarla con bytes o metadata
resolutiva distintos falla. Yank es una mutación de estado, no una eliminación
ni una republicación.

El registry reserva el nombre por primer alta autorizada. El estado OAL se
concede mediante ownership/control administrativo de Aether; no cambia
protocolo, archive, imports, solver ni compiler.

## 4. Naming y OAL

Una key bajo `[dependencies]` debe pasar exactamente `PackageName`: un
identificador Aether no-keyword. La comparación es sensible a mayúsculas y usa
el spelling exacto, sin normalización:

```text
linearAlgebra != linear_algebra != LinearAlgebra
```

El manifest resuelto debe declarar el mismo `package.name` que la key. Un
desacuerdo falla y no prueba otra fuente. Esta misma regla aplica a packages de
path y metadata del registry.

Los source units importables de una versión deben declarar exactamente el root
`package.name` o uno de sus descendants (`linearAlgebra` o
`linearAlgebra.Dense`, por ejemplo). No pueden contribuir a otro root público.
Un entry de application/tool puede ser anonymous como permite el lenguaje, pero
esa unidad no se vuelve importable; un package publicado como library debe
contener al menos una unidad named bajo su root.

Las OAL futuras como `linearAlgebra`, `statistics` y `optimization`:

- se agregan con `aether add` y se importan como cualquier dependencia;
- pueden depender de packages normales y coexistir en varias versiones;
- no reciben un `OriginKey` privilegiado, lookup alternativo, prelude, ABI ni
  permiso implícito;
- muestran un badge/owner oficial sólo como metadata de confianza y UX.

`std` continúa siendo toolchain y namespace reservado. No se publica como OAL
ni se resuelve mediante el registry.

## 5. Manifest y constraints

Se conserva el schema de `aether.toml` ya implementado:

```toml
[package]
name = "myProject"
version = "0.1.0"
aether = "1"

[dependencies]
linearAlgebra = "1.2"
localLibrary = { path = "../localLibrary" }
```

Cada dependencia posee exactamente una fuente. La forma string significa
registry oficial; la tabla V1 sólo admite la key `path`. Tablas desconocidas,
strings vacías, combinaciones de fuentes y metadata extra fallan cerradas.

### 5.1 Gramática mínima de versiones

V1 acepta deliberadamente sólo:

```text
Requirement := Compatible | "^" Compatible | "=" FullSemVer
Compatible  := Major | Major "." Minor | Major "." Minor "." Patch
Major/Minor/Patch := "0" | NonZeroDigit Digit*
```

La forma sin prefijo equivale a `^`. Sus intervalos son SemVer/Cargo-like:

| Constraint | Intervalo |
|---|---|
| `1` | `>=1.0.0, <2.0.0` |
| `1.2` o `^1.2` | `>=1.2.0, <2.0.0` |
| `1.2.3` | `>=1.2.3, <2.0.0` |
| `0.2` | `>=0.2.0, <0.3.0` |
| `0.2.3` | `>=0.2.3, <0.3.0` |
| `0.0.3` | `>=0.0.3, <0.0.4` |
| `=1.2.3` | sólo `1.2.3` |

`=FullSemVer` usa SemVer completo y puede nombrar prerelease/build metadata.
Las formas compatibles V1 sólo admiten componentes release numéricos y nunca
seleccionan prereleases. Wildcards, `~`, inequalities, listas, OR y ranges
quedan fuera y se rechazan en vez de reinterpretarse.

La versión elegida es la mayor por precedencia SemVer. Si dos versiones tienen
igual precedencia por diferir sólo en build metadata, el registry las ordena
además por spelling UTF-8 ascendente y elige la última; publicar versiones con
la misma precedencia debería advertirse, pero el resultado no depende del
servidor.

## 6. `aether.lock`

`aether.lock` es TOML machine-generated, con schema versionado. La CLI puede
reescribirlo por completo en orden canónico; el usuario no debe editarlo. Su
forma conceptual es:

```toml
lock-version = 1

[[package]]
id = "registry+official:linearAlgebra@1.2.4"
name = "linearAlgebra"
version = "1.2.4"
source = "registry+official"
checksum = "sha256:<hex>"
dependencies = ["registry+official:vectorMath@3.0.1"]

[[package]]
id = "path+../localLibrary#localLibrary@0.4.0"
name = "localLibrary"
version = "0.4.0"
source = "path+../localLibrary"
dependencies = []
```

El encoding final puede usar tablas estructuradas en vez de estos strings, pero
debe preservar exactamente: schema, id inequívoco, nombre, versión, fuente,
checksum registry y edges por ID. Los entries se ordenan por ID; los edges por
nombre y luego target ID. El package raíz no necesita checksum, pero el lock
identifica cuál de sus dependencias directas apunta a cada nodo.

Un path se almacena con `/`, relativo al root que contiene el lock y después de
canonicalizar/deduplicar el target. Puede contener `..` para un sibling. V1
rechaza generar un lock si el target canónico no puede expresarse como path
relativo UTF-8 estable. Nunca persiste home, drive/CWD accidental ni un path
absoluto. Dos spellings que canonicalizan al mismo manifest son un nodo; si
declaran ese mismo nodo bajo nombres distintos, falla.

Los path packages aparecen en el lock con nombre, versión, locator y edges, pero
sin checksum contractual. El lock fija su identidad y topología, no congela los
bytes de una checkout local editable. Su contenido actual participa del build
fingerprint; reproducibilidad byte-a-byte para paths exige versionar/copiar esa
checkout por medios externos.

Applications y libraries raíz generan y versionan lockfile para que sus propios
`sync/check/build` sean repetibles. Al publicar una library, su lock no entra al
archive ni restringe al consumidor: se publican sus constraints, y el grafo se
resuelve en el contexto del lock del consumidor.

## 7. Estrategia de resolución V1

La resolución se ejecuta con un snapshot lógico de metadata recibido durante la
operación. Para cada nodo, las dependency keys se procesan en orden UTF-8:

1. validar manifest, nombre y constraints;
2. para path, canonicalizar el directorio exacto, exigir `aether.toml` directo,
   validar name/version y deduplicar por manifest canónico;
3. para registry, enumerar versiones no-yanked compatibles en orden SemVer,
   elegir la mayor y obtener su metadata exacta;
4. internar el nodo por identidad exacta y recorrer sus edges;
5. mantener una pila DFS de identidades; reencontrar una identidad en la pila
   produce un cycle diagnostic con la cadena completa;
6. emitir el grafo y lock en orden canónico, independiente de concurrencia,
   `readdir`, timestamps y orden de respuestas.

La selección es **por edge**. Requerimientos que eligen exactamente
`(registry, name, version, checksum)` comparten nodo. Requerimientos compatibles
pueden converger naturalmente en la misma versión; requerimientos incompatibles
pueden elegir versiones distintas. No hay backtracking para reducir el número
de versiones ni unificación global. Un constraint falla sólo si su fuente no
ofrece candidato, su metadata es inválida o crea un ciclo. Esta estrategia es
simple, determinista y completa para el modelo V1 porque las selecciones de
edges diferentes no se restringen mutuamente.

Una publicación de registry no puede depender de path: `publish` la rechaza.
Un package de path sí puede tener paths transitivos, siempre relativos al
manifest que los declara; al serializar el lock todos se relocalizan respecto
del root del lock.

### 7.1 Reuso del lock

Antes de consultar selecciones nuevas, el resolver valida el lock completo:

- cada edge del manifest sigue existiendo, con misma fuente, y su versión
  locked satisface la constraint actual;
- cada nodo/edge transitivo coincide con metadata de la versión locked;
- cada path aún canonicaliza, conserva nombre/versión y produce la misma
  topología declarada;
- no hay IDs duplicados, dangling edges ni cycles;
- todo artifact registry conserva el checksum locked.

`sync` reutiliza el grafo si es válido y sólo materializa objetos faltantes. No
sube versiones porque apareció una release nueva. Si manifest y lock difieren,
falla indicando ejecutar `aether update` (o el comando mutador que corresponda),
en vez de cambiar resolución silenciosamente.

`update` ignora selecciones locked como preferencia, vuelve a resolver todas las
dependencies contra el snapshot actual y escribe el nuevo lock atómicamente.
Una futura selección parcial `update <name>` queda fuera de V1.

Sin lockfile, `sync` resuelve con la estrategia anterior, materializa y crea el
lock atómicamente. En modo offline sólo puede hacerlo si cache local contiene
metadata suficiente y todos los artifacts; de lo contrario falla sin inventar
una versión. El flag/nombre final de offline se cierra en implementación CLI.

## 8. Semántica de comandos de proyecto

```text
aether add <package>
aether remove <package>
aether sync
aether update
```

`add` valida un nombre exacto, consulta el registry, elige la última versión
release y escribe una constraint compatible con su major/minor (por ejemplo
`"1.2"`). Modifica `[dependencies]`, resuelve el grafo completo, materializa y
actualiza `aether.lock`. Si ya existe la key, falla y pide edición/update
explícitos; V1 no tiene aliases ni flags de source alternativo. Soporte de
`add --path` puede agregarse en el vertical sin cambiar el manifest, pero no es
obligatorio para la forma pedida `add <package>`.

`remove` elimina exactamente esa dependencia directa, resuelve desde el
manifest restante, poda nodos inalcanzables y actualiza el lock. No borra
objetos del cache global. Un package sólo transitivo no puede removerse por
nombre desde el root.

`add` y `remove` publican manifest y lock como una transacción recuperable:
preparan ambos archivos temporales, validan el resultado y reemplazan de forma
atómica; ante fallo de red/resolución no dejan el manifest cambiado a medias.
Se preservan tablas/comments no gestionados cuando la librería TOML lo permita,
pero `[dependencies]` queda ordenada canónicamente.

`sync` nunca edita `aether.toml`. Con lock válido no actualiza versiones; sin
lock crea la resolución inicial. Es la operación que debe bastar después de
clonar un proyecto.

`update` nunca cambia constraints del manifest. Autoriza candidatos compatibles
más nuevos, reescribe el lock y materializa lo necesario. Cambiar de major o
otra constraint requiere editar el manifest o un futuro comando explícito.

`run/build/check` de proyecto exigen manifest-lock coherentes. Pueden realizar
el equivalente local/offline de `sync` para objetos ya locked, pero nunca una
resolución nueva con red ni un update implícito.

## 9. Cache y materialización

El layout conceptual, no una API estable, es:

```text
~/.cache/aether/
  registry/official/       # metadata cacheada, no autoridad de identidad
  objects/sha256/ab/<hex>  # archive por bytes/checksum
  sources/sha256/ab/<hex>/ # extracción verificada e inmutable
  tmp/                     # descargas/extracciones incompletas

<project>/.aether/
  build/
  state/                   # fingerprints e índices baratos del proyecto
```

La ubicación real usa la convención de cache de cada OS y puede ser configurable
explícitamente; no participa en identidad. Dos proyectos que referencian el
mismo checksum usan el mismo objeto/source, sin copiarlo al proyecto.

Una descarga se escribe a un temporal, se limita por tamaño, se hashea mientras
llega, se compara fail-closed con el checksum de metadata/lock y sólo entonces
se publica por rename. La extracción rechaza paths absolutos, `..`, symlinks,
hardlinks, devices y colisiones normalizadas. Se verifica en temporal y se
publica como árbol read-only. Locks de proceso evitan writers concurrentes; un
writer muerto sólo deja temporales recolectables.

Al abrir un objeto existente se valida al menos tamaño/digest contra su nombre
antes de confiar en él. Mismatch o estructura incompleta marca corrupción,
descarta/reemplaza el objeto mediante la ruta atómica y, si no puede
redescargarse, falla. Nunca se continúa con bytes distintos ni se corrige el
lock al checksum observado.

Cache/build identity incluye checksum exacto para registry; para path/root,
digest determinista de manifests y source inputs actuales; toolchain/línea
Aether, target, profile/opciones semánticas y versión de formato de artifact.
Mtime, checkout absoluto, URL del registry y presencia de installs globales no
son identidad.

## 10. Contenido y publicación

Un archive V1 contiene sólo paths relativos normalizados:

```text
aether.toml
src/**/*.ae
README / README.*       # opcional
LICENSE / LICENSE.*     # opcional
```

La lista se ordena bytewise y el formato del archive fija timestamps, modes y
separadores para producir bytes reproducibles. Se rechazan symlinks, archivos
especiales, sources fuera de `src/`, manifests que apunten fuera y paths que
colisionen tras normalización. `.git/`, `.aether/`, caches, outputs, executables
generados y binaries arbitrarios nunca se incluyen. No se estabiliza ABI de
packages binarios.

`aether publish`:

1. exige un package library/tool publicable y manifest/schema/nombre/versión
   válidos;
2. rechaza path/git/private dependencies y valida que toda dependency registry
   tenga constraint V1;
3. cataloga y chequea el source permitido con compiler-next, incluyendo que
   todo namespace publicable permanezca bajo `package.name`;
4. construye el archive determinista, calcula `sha256` y muestra el conjunto
   que publicará;
5. autentica mediante token de cuenta enviado sólo por HTTPS;
6. crea de forma atómica la versión inmutable o confirma un retry idempotente.

V1 no ejecuta hooks, build scripts, generadores, código nativo ni código del
package durante publish/install/sync. Tampoco sube `aether.lock` como autoridad
de una library.

`yank name@version` (comando final por cerrar) requiere owner. Una versión
yanked no es candidata para `add`, un `sync` sin lock ni `update`, pero un lock
existente puede descargarla y usarla verificando el checksum. Unyank puede
restaurar candidaturas sin cambiar bytes.

El modelo mínimo de ownership contiene accounts, varios owners por nombre y
tokens revocables con scope publish. El primer publisher autorizado se vuelve
owner; cualquier alta/baja/transferencia futura debe quedar auditada y evitar
dejar cero owners. UX exacta de login, recuperación, 2FA, organizaciones y
delegación se difiere junto con el servidor.

## 11. Environments e install

Los scopes no se mezclan:

1. **Project:** `[dependencies]` + `aether.lock`; default reproducible.
2. **Virtual environment:** directorio aislado seleccionado explícitamente.
3. **User environment:** default de `install`, bajo data/config del usuario.

El flujo project no necesita environment ni activación. Una UX futura mínima
puede ofrecer `aether env create <path>` y seleccionar un environment con
`--env <path>`; activarlo sólo configura esa selección y antepone su directorio
de tools a `PATH`. Sin `--env` ni activación, `install` usa el user environment.
La variable concreta de activación queda por cerrar y nunca afecta un build de
proyecto.

```text
aether install <package> [--env <path>]
aether uninstall <package> [--env <path>]
```

`install` resuelve y mantiene un manifest/lock propio del environment. Si el
package expone un executable/tool, instala un launcher administrado en el
`bin` del environment; no copia un binary ABI publicado, sino que construye
desde source con la toolchain compatible. Si es library-only, puede existir en
el environment para sesiones/comandos que seleccionen explícitamente ese
environment, pero nunca entra en imports de un proyecto. `uninstall` elimina
la raíz solicitada, poda su grafo/launchers y no purga el cache compartido.

`add/remove` siempre operan el project root explícito. `install/uninstall`
siempre operan el environment seleccionado. `PATH` sólo expone tools; una
library global no crea namespaces visibles por accidente. La metadata
publicada debe declarar si el package es library, tool/application o ambos;
V1 sigue admitiendo como máximo los targets que cierre la arquitectura CLI.

## 12. Integración con `ProjectPlan` y compiler

La frontera deseada es conceptual:

```text
ResolvedProjectPlan {
    root: RootPackage,
    packages: ordered map ResolvedPackageId -> ResolvedPackage,
    edges: (owner-id, import-name) -> target-id,
    source_units: exact logical key + provider locator + content identity,
    entry: exact root source unit,
}
```

El package-manager/project layer posee TOML, lockfile, registry client, cache,
canonicalización y solver. Convierte registry/path/cache en providers de source
ya verificados y entrega al driver:

- roots/source units exactos y sus nombres lógicos;
- identidad nominal exacta de cada instancia;
- edges permitidos por owner e import namespace;
- entry y clase del root.

El driver revalida invariantes estructurales y construye el `PackageIndex`.
Frontend/HIR/MIR/SSA/backend no leen TOML, URLs, credentials ni cache paths.
Imports se resuelven consultando `(owning ResolvedPackageId, first namespace)`;
descendientes permanecen dentro de la misma instancia target.

La identidad nominal que hoy es `PackageKey = (OriginKey, PackagePath)` debe
pasar a incluir un `PackageInstanceKey` estable. Al menos registry/name/version/
checksum para registry, identidad de sesión+content para path/root y toolchain
para `std`. `PackageId` puede seguir siendo un entero denso de sesión, pero se
interna desde esa clave completa. Mangling, type identity y caches usan la clave
estructural, no sólo el spelling. Por tanto `math@1::Vector` y
`math@2::Vector` nunca son asignables por coincidencia de nombre/layout.

Los source imports no incorporan versión. El contexto del source unit determina
su owner; el edge locked de ese owner determina el target. Un source no puede
importar un package transitivo que su propio manifest no declare, aunque exista
en el grafo por otro camino.

## 13. Local path dependencies

Para `localLibrary = { path = "../localLibrary" }`:

- el spelling se resuelve respecto del directorio del manifest que lo declara;
- el target canónico debe ser directorio y contener `aether.toml` regular
  directo; no se buscan ancestors/descendants;
- `package.name` debe ser exactamente `localLibrary` y su versión debe ser
  SemVer; no existe fallback al registry ante ningún error;
- se canonicaliza antes de deduplicar y antes de detectar cycles;
- dos edges al mismo manifest canónico comparten instancia si esperan el mismo
  nombre; spellings/nombres contradictorios fallan;
- la recursion valida dependencies del manifest local con las mismas reglas;
- el lock registra locator relativo, metadata y edges como define la sección 6.

Symlinks pueden usarse sólo si su target final satisface estas reglas. La
identidad/dedupe usa el target canónico; el locator portable del lock apunta a
ese target desde el root. Un cambio de symlink que resuelva a otro manifest
invalida el lock.

## 14. Reproducibilidad y fallos

- Con lock válido, el lock manda sobre releases nuevas y yanks.
- El manifest manda sobre el lock respecto de dependencies permitidas y
  constraints. Una divergencia no se arregla silenciosamente.
- Un registry package yanked pero locked sigue disponible por identidad exacta;
  un nuevo solver no lo selecciona.
- Checksum distinto en descarga, cache o metadata es error de integridad
  fail-closed. No se recompone el lock a partir de bytes recibidos.
- Una versión locked desaparecida del servidor puede seguir usarse desde cache
  verificado; sin objeto verificable, `sync` falla. El registry debería retener
  artifacts yanked permanentemente, pero el cliente no asume bytes distintos.
- Installs globales/environments, CWD, orden de filesystem y timestamps nunca
  agregan edges ni cambian selecciones.
- Path deps aportan topología locked pero bytes mutables; el build detecta
  cambios mediante fingerprint. Esta es la única relajación V1 explícita de
  reproducibilidad de contenido.
- Writes de manifest/lock, downloads y extracciones se hacen mediante temporales
  y reemplazo atómico; un fallo no publica estado parcial como válido.

## 15. Baseline de seguridad y confianza

V1 exige HTTPS, versions inmutables, SHA-256, validación fail-closed, archive
confinement, límites de tamaño/archivos y tokens que no aparezcan en lock,
manifest, argv, logs ni diagnostics. Redirects no pueden enviar credenciales a
otro origin sin política explícita.

Packages son datos source hasta que el usuario pide check/build/run. Sync,
install y publish no ejecutan código arbitrario del package. No hay build
scripts, native hooks, post-install, macros ejecutables ni dependency hooks.
Esto no sustituye auditing, signing, transparency logs o malware review; todos
quedan fuera del baseline V1.

## 16. Auditoría de la implementación actual

### 16.1 Reutilizable

- `aether-cli` ya decodifica TOML con `deny_unknown_fields` y representa
  `Registry(String)` / `Path { path }`; ese schema y validación fail-closed son
  la base inmediata.
- `PackageName` valida el spelling exacto como identificador Aether y
  `PackageVersion` usa SemVer; deben moverse o compartirse con la capa package.
- La resolución exacta de root/manifest, canonicalización, confinement, writes
  temporales de `init` y requests tipados ya establecen patrones reutilizables.
- `CompilationSession` ya cataloga imports, ordena source paths, asigna IDs
  densos y conserva `SourceUnitKey`, `LogicalSourceKey` y edges semánticos.
- La separación CLI in-process/driver y `check` antes de backend ya coincide con
  la frontera requerida.

### 16.2 Deuda que PACKAGE-MANAGER-V1 debe reemplazar

- `resolve_project` rechaza incondicionalmente todo `[dependencies]` no vacío
  después de una validación superficial. Debe delegar manifest+lock al resolver.
- `ProjectPlan` contiene un solo `source: PathBuf`, metadata del root y clase;
  no puede expresar grafo, source providers, package instances ni edges.
- `CompilationSession::discover` deriva el source root del entry y escanea ese
  árbol. No puede combinar roots exactos de cache/path ni impedir imports
  transitivos no declarados sin recibir un catálogo resuelto.
- `OriginKey` sólo distingue `Project` y `Toolchain`. Todas las dependencies
  quedarían nominalmente confundidas; debe incorporar instancia/fuente exacta.
- El resolver de imports actual decide `Project` vs `Toolchain` por el prefijo
  `std`; debe consultar la tabla de edges del package owner.
- El artifact `.aetherlib` es metadata bootstrap, no package binario, registry
  artifact ni ABI. No debe usarse para publish/cache de dependencies.
- No existen lockfile, registry client, cache CAS, archive seguro, atomic edit
  coordinado ni comandos reservados implementados.

La implementación conviene separarse en un crate reutilizable de
manifest/lock/resolution/cache, consumido por `aether-cli`. El driver recibe el
plan resuelto por API tipada y no depende de ese crate para red o UX.

## 17. Orden recomendado para PACKAGE-MANAGER-V1

1. extraer schema/naming/SemVer y agregar parser+writer canónico de lock;
2. introducir identidades de instancia, catálogo multi-root y `ProjectPlan`
   resuelto sin red, calificándolo primero con grafos de path;
3. implementar solver determinista contra un trait de registry fake y tests de
   multiversión/cycles/yank/lock reuse;
4. agregar CAS, archive validation y cliente HTTPS sin llevarlos al driver;
5. habilitar `sync/update`, luego mutación transaccional `add/remove`;
6. cerrar publish/auth contra un servicio concreto;
7. implementar environments e `install/uninstall` después del flujo project.

Tests deben usar registry/cache temporales y fixtures deterministas; ninguna
suite ordinaria depende de Internet ni del registry real.

## 18. Decisiones diferidas y fuera de scope

Quedan deliberadamente fuera:

- dominio, vendor/protocolo HTTP final, operación del servidor y SLA;
- native dependencies, hooks y equivalente de `build.rs`;
- ABI/package binario y artifacts precompilados;
- registries privados, mirrors como fuentes de identidad y federación;
- firmas, transparency log, attestations y policy corporativa;
- git dependencies, workspaces, features y optional/platform dependencies;
- cross-compilation variants y resolución por target;
- plugins, scripts y macros ejecutables;
- update parcial, aliases/renames y varios registries;
- UX final de login, yank, env activation, offline y garbage collection;
- sandbox de packages al ejecutar tools ya instalados.

Ninguna decisión diferida permite que un project consulte global installs,
que el compiler acceda a red/TOML o que versiones distintas compartan identidad
nominal.
