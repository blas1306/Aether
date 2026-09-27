# PACKAGE-LOCK-RESOLUTION-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-26.

Autoridad normativa:
[PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md),
[PACKAGE-MANAGER-ARCH-1 report](PACKAGE_MANAGER_ARCH_1_REPORT.md),
[PACKAGE-IDENTITY-V1 report](PACKAGE_IDENTITY_V1_REPORT.md) y
[CLI-ARCH-1](CLI_ARCH_1.md).

Este vertical implementa resolución determinista y `aether.lock` sin agregar
HTTP, registry real, CAS, archives, publish ni environments.

## Resultado

El workspace incorpora `aether-package`, una capa reutilizable y sin red que
posee:

- `PackageName`, `PackageVersion` y `PackageInstanceKey`;
- schema fail-closed de `aether.toml`;
- parser de requirements V1;
- `RegistryProvider`;
- resolución conjunta path/registry;
- schema, lectura, validación, serialización y escritura atómica de
  `aether.lock`;
- operaciones API `sync` y `update`.

`aether-cli` dejó de duplicar manifest y resolución path. Para proyectos usa
`sync` con una frontera de registry explícitamente ausente. Por eso un proyecto
path-only crea o reutiliza lock normalmente y una resolución registry nueva no
simula conectividad. Un embedding o test puede entregar un `RegistryProvider`.

La capa package produce un `ResolvedGraph`. La CLI lo entrega a
`ProjectPlan::resolved`; el driver revalida paths, metadata, identities, edges y
DAG antes de compilar. Frontend, HIR, MIR, SSA y backend no leen TOML, lock,
requirements ni conceptos de transporte.

## Identidad preservada

`PackageInstanceKey` conserva exactamente las formas calificadas por
PACKAGE-IDENTITY-V1:

```text
Root     { manifest, name, version }
Path     { manifest, name, version }
Registry { registry, name, version, checksum }
```

La definición se movió a `aether-package` y frontend la reutiliza; no existe
una segunda identidad traducida. Root/path mantienen el manifest canónico como
identidad de sesión. Registry usa el ID lógico `official`, nombre, SemVer exacta
y checksum.

Los edges continúan perteneciendo al owner:

```text
(owner instance, dependency import name) -> exact PackageInstanceKey
```

El driver y frontend conservan resolución contextual, separación nominal y
mangling por instancia. Un nodo sólo se comparte si la identidad exacta
coincide. La presencia global de una transitiva no concede un import directo;
la regresión `E0242` continúa activa.

## Requirements V1

`VersionRequirement` acepta únicamente:

```text
Compatible | "^" Compatible | "=" FullSemVer
```

Las formas compatibles implementan los límites especiales para major cero:
`1.x` avanza hasta `<2.0.0`, `0.2.x` hasta `<0.3.0` y `0.0.3` hasta
`<0.0.4`. No admiten prereleases. La forma exacta exige SemVer completa y sí
puede seleccionar prerelease/build metadata.

Wildcards, tilde, inequalities, ranges, OR, listas, componentes incompletos en
la forma exacta y componentes numéricos con ceros iniciales se rechazan sin
reinterpretación.

## Registry abstraction y estrategia

`RegistryProvider` sólo expone dos operaciones síncronas y sin transporte:

1. enumerar versiones y su estado yanked;
2. obtener metadata exacta de una versión, incluido checksum, dependencies y
   una raíz ya materializada conceptualmente.

El resolver procesa dependency keys en orden `BTreeMap`. Para cada edge
registry parsea todas las versiones, filtra requirement y yanks, ordena por
precedencia SemVer y, ante igual precedencia por build metadata, por spelling
UTF-8. Selecciona la última. El orden entregado por el provider no influye.

La selección es edge-local. No existe solver global, unificación por nombre,
backtracking ni minimización del número de versiones. Después de seleccionar,
el resolver obtiene metadata exacta, verifica name/version/checksum, contrasta
la materialización y recorre dependencies. Metadata registry que declare un
edge path falla cerrada.

Una pila de identidades exactas detecta cycles path, registry o mixtos. El mapa
de nodos interna por `PackageInstanceKey`, mientras path también deduplica por
manifest canónico. El resultado es siempre un DAG multi-root.

## Integración path

Las reglas calificadas en PACKAGE-IDENTITY-V1 se movieron sin debilitarlas:

- locator relativo al manifest owner;
- canonicalización y manifest directo;
- schema, nombre, versión y línea Aether validados;
- igualdad entre dependency key y `package.name`;
- library `src/lib.ae` obligatoria para dependencias;
- dedupe de spellings/symlinks por manifest canónico;
- cycles después de canonicalizar;
- coexistencia de path y registry en el mismo grafo.

Root/path pueden declarar ambos tipos de edge. Registry no puede declarar path.

## Schema real de `aether.lock`

El encoding implementado es TOML machine-generated:

```toml
lock-version = 1
root = "root:app@0.1.0"

[[package]]
id = "path+../local#local@1.0.0"
name = "local"
version = "1.0.0"
source = "path+../local"

[[package]]
id = "registry+official:math@1.2.3#sha256:..."
name = "math"
version = "1.2.3"
source = "registry+official"
checksum = "sha256:..."

[[package.dependencies]]
name = "vector"
target = "registry+official:vector@2.0.0#sha256:..."
```

Todos los nodos, incluido root, tienen ID, nombre, versión, source y edges
exactos. Registry agrega checksum. Packages se ordenan por ID; edges por nombre
y target. Los IDs registry incluyen checksum para que el target sea una
identidad material inequívoca.

Path persiste únicamente un locator canónico relativo al directorio del lock,
con `/` lógico y `..` cuando corresponde. El manifest absoluto sigue existiendo
sólo en `PackageInstanceKey` durante la sesión. Paths no UTF-8, absolutos no
relativizables o de otro prefijo/volumen se rechazan al generar el lock.

## Validación y operaciones

Un lock leído se valida fail-closed antes de construir el grafo:

- `lock-version`, root existente y alcance completo desde root;
- IDs únicos, targets no dangling, dependency names únicos y DAG;
- ID, source, name, version y checksum coherentes;
- edges directos del manifest con la misma source class;
- versión registry locked aún compatible con el requirement;
- metadata registry exacta y materialización coincidente;
- path canónico, nombre, versión y topología todavía coincidentes;
- package key igual al nombre del target.

`sync` reutiliza el grafo locked válido sin enumerar releases nuevas. La
consulta exacta permite conservar una versión ahora yanked. Sin lock, resuelve y
crea `aether.lock` atómicamente. Cualquier divergencia falla e indica ejecutar
`aether update`; no reescribe por sorpresa.

`update` ignora selecciones anteriores, resuelve todo el grafo con el snapshot
actual y reemplaza el lock. No cambia constraints y no ofrece update parcial.
Una selección nueva jamás toma una versión yanked.

La serialización ocurre antes de tocar disco. La publicación usa un temporal en
el mismo directorio, `write_all`, `sync_all` y rename. Fallos de parseo,
resolución, portabilidad, serialización o escritura dejan intacto el lock
anterior; un temporal fallido se intenta retirar.

## Evidencia

La suite del nuevo crate usa exclusivamente un registry in-memory y roots
temporales. Cubre:

- gramática, caret `1.x`/`0.x`/`0.0.x`, exactas y prereleases;
- mayor compatible, tie-break de build metadata y orden de provider;
- multiversión edge-local y sharing exacto;
- transitivas registry y grafo mixto path/registry;
- rechazo de path metadata registry y cycles;
- creación y output canónico/relativo del lock;
- reuso frente a release nueva, update y reglas yanked;
- divergencia de manifest/source/constraint;
- checksum, topología path, IDs duplicados, dangling edges y cycles locked;
- preservación del lock anterior ante una resolución fallida.

Las regresiones CLI conservan diamond/symlink, multiversión, mismatch nominal
cross-version e import transitivo no declarado. El grafo multi-root se compila y
ejecuta tanto en O0 como O2.

## Deuda restante

Este vertical no implementa red ni materialización real. La raíz entregada por
`RegistryProvider` representa source ya disponible sólo para mantener aislada
la resolución y probar la frontera del compiler.

Quedan para verticales posteriores:

1. cliente HTTPS y snapshot/protocolo del registry oficial;
2. descarga, SHA-256 de bytes, archive validation/extraction y CAS global;
3. provider productivo y política offline;
4. UX pública completa de `sync`/`update` y comandos `add/remove`;
5. publish/auth/yank remoto;
6. environments e install/uninstall;
7. fingerprints persistentes de contenido path/root.

Ninguna deuda autoriza mover red/TOML al compiler, seleccionar globalmente por
nombre, colapsar versions nominales o conceder imports transitivos no
declarados.
