# PACKAGE-PUBLISH-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-27.

Autoridad normativa: [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md),
[su reporte](PACKAGE_MANAGER_ARCH_1_REPORT.md),
[PACKAGE-IDENTITY-V1](PACKAGE_IDENTITY_V1_REPORT.md),
[PACKAGE-LOCK-RESOLUTION-V1](PACKAGE_LOCK_RESOLUTION_V1_REPORT.md),
[PACKAGE-CACHE-REGISTRY-V1](PACKAGE_CACHE_REGISTRY_V1_REPORT.md) y
[PACKAGE-COMMANDS-V1](PACKAGE_COMMANDS_V1_REPORT.md).

## Resultado

La CLI oficial incorpora targets explícitos:

```text
aether publish <project>
aether publish <project> --dry-run
```

V1 publica únicamente libraries con `src/lib.ae`, un `aether.toml` estricto,
nombre/versión válidos y un único target. Antes de leer credenciales ejecuta el
check in-process de compiler-next sobre el grafo resuelto. Esto también aplica
las reglas de ownership de source units y rechaza namespaces fuera de
`package.name`. Applications, targets múltiples y path dependencies se
rechazan. Las dependencies publicadas son sólo constraints registry V1.

La resolución utilizada para check no escribe `aether.lock`; el lock de la
checkout tampoco se incluye ni actúa como autoridad para consumers.

## Archive determinista

`aether-package::build_publication` produce el mismo tar POSIX sin compresión
que consume el CAS V1. Ordena paths bytewise y fija mode `0644`, uid/gid y mtime.
Sólo agrega:

```text
aether.toml
src/**/*.ae
README / README.*
LICENSE / LICENSE.*
```

No agrega directorios de VCS, `.aether`, lockfiles, outputs ni archivos
arbitrarios. Rechaza symlinks y especiales dentro de la superficie publicada.
Calcula `sha256:<hex>` sobre los bytes finales exactos. El inspector compartido
reutiliza el allowlist, normalización y confinement de
PACKAGE-CACHE-REGISTRY-V1 y vuelve a parsear manifest, identidad y constraints.

## Dry run

`--dry-run` valida, resuelve, chequea, genera y vuelve a inspeccionar el archive;
muestra `name@version`, checksum, tamaño y lista exacta de archivos. No consulta
`AETHER_REGISTRY_TOKEN`, no envía requests mutantes y no crea/modifica el lock
del proyecto.

## Protocolo de publicación

El protocolo de lectura aprobado se conserva:

```text
GET /v1/packages/{name}/versions
GET /v1/packages/{name}/{version}
GET /v1/packages/{name}/{version}/archive?checksum=...
```

La mutación nueva es:

```text
POST /v1/packages/{name}/{version}
Authorization: Bearer <token>
Content-Type: application/x-tar
X-Aether-Checksum: sha256:<hex>
```

El body es el archive exacto, no un envelope que duplique metadata confiable.
El servidor limita el request, vuelve a calcular SHA-256, inspecciona el tar,
parsea `aether.toml`, deriva constraints y exige que identidad de route,
manifest y checksum coincidan. Los errores HTTP son genéricos y no reflejan
tokens. El cliente productivo sigue exigiendo HTTPS, origin sin credentials y
redirects deshabilitados. El proceso reference habla HTTP detrás de un TLS
terminator; no existe un bypass HTTP en el cliente productivo.

## Servicio y almacenamiento

El workspace incluye el crate/bin separado `aether-registry`. Su storage V1 es
filesystem persistente, apropiado para una referencia single-node:

```text
<storage>/
  registry.lock
  tokens/<sha256(token)>.json
  packages/<name>/owners.json
  packages/<name>/versions/<version>/metadata.json
  packages/<name>/versions/<version>/archive.tar
  tmp/
```

No existe estado crítico únicamente in-memory. `aether-registry serve
<storage> <bind>` sirve el protocolo. Para producción, TLS y límites de
conexión perimetrales se terminan delante del proceso; el cliente nunca acepta
HTTP. Este storage serializa mutaciones con un file lock cross-process. Es una
base deliberadamente mínima, no un diseño de registry distribuido.

## Auth, ownership y OAL

`aether publish` obtiene el secret exclusivamente desde
`AETHER_REGISTRY_TOKEN`; no hay argumento CLI, manifest, lock, URL ni log que lo
contenga. El comando administrativo:

```text
aether-registry create-token <storage> <account>
```

genera el token desde el CSPRNG del OS, persiste sólo su SHA-256 y presenta el
plaintext una vez. No se inventó OAuth ni login incompleto.

El primer publish autenticado reserva globalmente el nombre y crea su owner.
`owners.json` representa un set de múltiples owners aunque la UX para
administrarlo queda diferida. Versiones posteriores requieren membership en
ese set. El bit `official` forma parte de metadata de protocolo con default
false y sólo puede alterarlo la operación administrativa local
`set-official`; no existe `publish-official` ni tratamiento especial en
resolver, archive o compiler.

## Atomicidad e inmutabilidad

El servidor valida completamente antes de tomar visibilidad. Escribe archive y
metadata sincronizados dentro de `tmp/`; la primera publicación renombra un
package completo con owners+version, y las posteriores renombran el directorio
completo de versión. Después sincroniza el directorio padre. Nunca existe una
metadata visible sin archive ni una versión parcial.

`(name, version)` no se reemplaza. Un retry con los mismos bytes y campos
inmutables devuelve `identical`; bytes, checksum, constraints o identidad
distintos producen conflicto. El lock de storage también protege first publish
y publishes concurrentes. La prueba concurrente exige exactamente un
`created` y que todos los otros writers converjan en retry idéntico.

## Yank

El servicio prepara `POST /v1/packages/{name}/{version}/yank` y
`RegistryStore::yank`. Requiere owner y sólo cambia el flag: nunca elimina ni
reemplaza archive/checksum. `versions` lo expone para excluirlo de resolución
nueva y exact metadata/archive siguen disponibles para locks existentes. La UX
`aether yank` queda diferida.

## Evidencia end-to-end

Las suites sin Internet cubren archive reproducible y cerrado, auth, reserva de
nombre, publish no autorizado, owner, retry idéntico, conflicto de bytes,
checksum/identidad/archive inválidos, path dependency, symlinks, compilation y
namespace failures, concurrencia, official metadata y yank sin delete.

Un test controlado publica `flowLibrary@1.0.0`, hace `add` y `sync` en un
consumer, materializa desde el registry/CAS y ejecuta el consumer en O0 y O2.
Después publica `1.1.0`, demuestra que `sync` conserva el lock 1.0.0 y que
`update` selecciona 1.1.0.

## Deuda restante

Quedan fuera login/account UX, owner management/auditing UI, comando CLI de
yank/unyank, storage distribuido/object storage, rate limiting de producción,
malware scanning, signing/transparency, organizations, private registries,
git/native/build-script/binary packages y environments/install.
