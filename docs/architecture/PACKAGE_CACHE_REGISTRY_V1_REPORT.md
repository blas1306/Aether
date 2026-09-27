# PACKAGE-CACHE-REGISTRY-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-26.

Autoridad normativa: [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md),
[su reporte](PACKAGE_MANAGER_ARCH_1_REPORT.md),
[PACKAGE-IDENTITY-V1](PACKAGE_IDENTITY_V1_REPORT.md) y
[PACKAGE-LOCK-RESOLUTION-V1](PACKAGE_LOCK_RESOLUTION_V1_REPORT.md).

## Resultado

`aether-package` posee ahora el transporte y la materialización productiva. El
resolver conserva su interfaz `RegistryProvider`; ni `aether-driver` ni el
frontend conocen HTTP, URLs, cache o archives. `PackageInstanceKey`, resolución
edge-local, multiversión, edges contextuales, yanks locked y separación nominal
no cambiaron.

`run`, `build` y `check` construyen un snapshot productivo cuando se configura
`AETHER_REGISTRY_URL`. `AETHER_CACHE_DIR` permite seleccionar el cache y
`AETHER_OFFLINE=1` selecciona la política offline. Sin URL ni modo offline se
preserva el diagnóstico explícito anterior para una dependencia registry; no
se fijó un hostname oficial que la arquitectura aún deja abierto.

## Protocolo cliente V1

`RegistryClient` define tres operaciones reusables:

1. `GET /v1/packages/{name}/versions` devuelve
   `{ "versions": [{ "version", "yanked" }] }`;
2. `GET /v1/packages/{name}/{version}` devuelve metadata exacta con `name`,
   `version`, `yanked`, `checksum`, `dependencies` y `archive_size`;
3. `GET /v1/packages/{name}/{version}/archive?checksum=...` entrega el archive
   exacto.

`HttpsRegistryClient` sólo acepta endpoints `https://`, rechaza user-info y
desactiva redirects. Así ningún redirect puede cambiar origin o reenviar
credenciales implícitamente. El registry lógico continúa siendo `official`; el
endpoint físico nunca entra en identidad ni lock.

El provider congela la primera observación de versions y metadata exacta en
mapas ordenados durante una operación. El resolver sigue imponiendo el orden
SemVer y su desempate normativo, de modo que el orden de respuesta y la
concurrencia no introducen nondeterminismo.

## Cache global y metadata

La ubicación por defecto usa la convención de cache del OS y este layout:

```text
<cache>/
  registry/official/versions/<name>.json
  registry/official/metadata/<name>/<version>.json
  objects/sha256/ab/<digest>
  sources/sha256/ab/<digest>/
  tmp/
```

Los envelopes JSON de metadata llevan `schema = 1` y se validan
fail-closed. Online obtiene una observación nueva y la publica atómicamente;
ante fallo de transporte puede usar una observación exacta cacheada válida.
Offline sólo lee cache. Versions y metadata son aceleradores versionados, no
identidad. Un lock exacto puede reutilizar metadata y objeto preservados aunque
el servidor no esté disponible.

## Descarga e integridad

La descarga se escribe a un temporal exclusivo, aplica simultáneamente el
límite configurado y `archive_size`, calcula SHA-256 incrementalmente, exige el
tamaño exacto y compara `sha256:<hex>` exactamente. Sólo después de `sync_all`
se publica por rename al CAS. Un error o stream truncado elimina el temporal y
no publica bytes parciales.

Todo objeto preexistente se abre, limita, mide y vuelve a hashear antes de
usarlo. Corrupción es cache miss en online y error en offline; nunca reemplaza
checksum, metadata o lock con los bytes observados.

## Archive y extracción

El formato V1 cerrado es **tar POSIX sin compresión**. Sólo admite archivos
regulares y directorios para:

```text
aether.toml
src/**/*.ae
README / README.*
LICENSE / LICENSE.*
```

La extracción manual, siempre a temporal, rechaza paths absolutos, `..`, `.` y
separadores alternativos, symlinks, hardlinks, devices, otros especiales,
paths no UTF-8, entries fuera del allowlist y colisiones después de
normalización. Limita cantidad de archivos y bytes expandidos y usa creación
exclusiva por archivo.

Antes de publicar verifica `aether.toml` directo, schema, `package.name`,
`package.version` y dependencies registry exactas contra metadata. Sólo después
renombra el árbol al CAS y lo vuelve read-only. No existe package ABI binaria.

## Concurrencia e inmutabilidad

Cada digest tiene un lock advisory de proceso en `tmp/<digest>.lock`. Bajo ese
lock se revalida estado existente, se descarga, extrae y publica. Dos writers
del mismo digest convergen en un único objeto y árbol; nunca observan estado
parcial. Los únicos residuos posibles son temporales con nombre exclusivo.
`cleanup_temporaries` toma el lock no bloqueante del digest antes de recolectar
residuos, sin usar mtime como autoridad.

Los árboles `sources` son compartidos por checksum entre proyectos y se marcan
read-only. No se copian a `.aether/` ni el path del cache forma identidad.

## Offline, lock e integración

`RegistryPolicy::{Online, Offline}` es reusable fuera de CLI. Offline no
construye ni invoca transporte: una enumeración nueva requiere versions
cacheadas; un nodo locked requiere metadata exacta y objeto/source verificable.
Cada ausencia o corrupción produce un diagnóstico específico y nunca inventa
una versión ni ignora checksum.

`sync` con lock sigue llamando sólo metadata exacta y materializa el checksum
locked; no enumera releases. Sin lock y `update` enumeran contra el snapshot,
excluyen yanks nuevos y materializan todo antes de la escritura atómica del
lock. Un fallo de descarga, checksum, extracción o manifest ocurre antes de
publicar/cambiar el lock. Una versión yanked ya locked sigue siendo válida.

## Evidencia

Las pruebas nuevas, sin Internet, cubren protocolo mediante un cliente
controlado, HTTPS obligatorio, versions/metadata/archive, SHA correcto y
incorrecto, truncamiento, límite, objeto corrupto y reuso, traversal, links,
special files, colisión normalizada, mismatch de manifest, writers
concurrentes, recolección de temporales, online, offline locked, metadata
offline ausente y artifact offline ausente.

Las pruebas de resolución existentes continúan cubriendo yanks, lock inmutable
ante fallo, multiversión y grafo edge-local. Una regresión de `aether-driver`
compila un package realmente extraído desde el CAS en O0 y O2.

## Deuda restante

Quedan fuera deliberadamente `publish`, auth/tokens, yank remoto,
installs/environments, signing, transparency, native dependencies, build
scripts, binaries, private registries y git dependencies. Los flags públicos y
la UX de `sync/update/add/remove` fueron cerrados por
[PACKAGE-COMMANDS-V1](PACKAGE_COMMANDS_V1_REPORT.md); este vertical conserva la
autoridad sobre transporte, cache y materialización.
