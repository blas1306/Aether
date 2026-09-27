# ENVIRONMENTS-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-27.

Autoridad: [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md),
[su reporte](PACKAGE_MANAGER_ARCH_1_REPORT.md),
[PACKAGE-COMMANDS-V1](PACKAGE_COMMANDS_V1_REPORT.md) y
[PACKAGE-PUBLISH-V1](PACKAGE_PUBLISH_V1_REPORT.md).

## Resultado

La CLI oficial incorpora environments opcionales con tres scopes estrictamente
separados:

```text
aether env create <path>
aether install <package> [--env <path>] [registry-options] [-O0|-O2]
aether uninstall <package> [--env <path>] [registry-options]
```

`add/remove/sync/update` continúan operando exclusivamente sobre proyectos.
`install/uninstall` sólo operan sobre el environment seleccionado. La selección
de un environment, su `bin` en `PATH` o la presencia de libraries instaladas no
agrega edges al `ProjectPlan` de un proyecto y no participa en imports, mangling,
fingerprints ni resolución reproducible.

`--registry`, `--cache-dir`, `--offline`, `AETHER_REGISTRY_URL`,
`AETHER_CACHE_DIR` y `AETHER_OFFLINE` conservan su precedencia y alimentan el
mismo `RegistrySnapshotProvider`, metadata cache y CAS de proyectos. No existe
un solver, downloader o materializador paralelo para environments.

## Layout y environment de usuario

`env create` publica un directorio nuevo de forma atómica. El layout V1 es:

```text
<env>/
  aether.toml             # roots solicitados, administrado por Aether
  aether.lock             # grafo exacto del environment
  bin/                    # sólo launchers de tools directos
  state/
    environment-v1        # marker/schema interno
    tools/                # artifacts source-built administrados
  src/lib.ae              # root sintético interno; no es importable por proyectos
```

Sin `--env`, `AETHER_ENV` selecciona un environment existente como comodidad de
activación. Si tampoco está presente, se usa y crea bajo demanda el environment
de usuario estándar:

- Linux/Unix: `$XDG_DATA_HOME/aether/environments/default`, o
  `$HOME/.local/share/aether/environments/default` sin `XDG_DATA_HOME`;
- macOS: `$HOME/Library/Application Support/Aether/environments/default`;
- Windows: `%LOCALAPPDATA%\Aether\environments\default`.

La activación V1 no requiere script: equivale a definir `AETHER_ENV=<env>` y
anteponer `<env>/bin` a `PATH`. `--env` siempre es suficiente y tiene
precedencia. Ninguna de las dos acciones afecta builds de proyecto.

## Install, uninstall y tools

`install` agrega o reemplaza el root registry solicitado en el manifest del
environment, resuelve el grafo completo con las reglas edge-local existentes,
materializa source verificado desde el CAS y publica un lock canónico. Repetir
`install` es una reinstalación coherente y permite seleccionar una release
compatible nueva. Una library queda registrada y locked, pero no recibe
launcher ni se vuelve visible para imports de proyectos.

`uninstall` exige que el nombre sea un root directo, elimina sólo ese root,
resuelve el conjunto restante y poda nodos transitivos inalcanzables y
launchers. Nunca elimina archives ni sources del CAS global. Artifacts source
build antiguos bajo `state/tools` pueden quedar como datos recolectables; no son
autoridad ni quedan expuestos por `bin`.

La declaración mínima de executable V1 reutiliza el target único ya cerrado:

```toml
[package]
name = "formatter"
version = "1.0.0"

[application]
entry = "src/main.ae" # opcional; éste es el default
```

Un package application expone exactamente un comando, con el spelling exacto
de `package.name`. Un package con `src/lib.ae` es library-only. Tener ambos
targets sigue rechazado porque V1 no incorpora múltiples targets/bins. Publish
acepta ahora source packages de cualquiera de esas dos clases y conserva el
manifest como declaración autoritativa; no se publica ni consume ABI binaria.

Para un tool, install promueve únicamente su nodo application y grafo alcanzable
a un `ProjectPlan` de compilación, construye desde source con compiler-next y
escribe el executable bajo `<env>/state/tools/<name>/<version>/`. El launcher de
`bin` apunta a ese artifact administrado, preserva argumentos, funciona con
paths que contienen espacios y nunca depende del checkout ni del source
materializado. `-O0` y `-O2` seleccionan el perfil de una instalación explícita;
otros tools ya instalados no se recompilan incidentalmente.

## Transacciones y concurrencia

Cada operación se serializa con el mismo estilo de file lock cross-process del
package manager. Resolución, materialización y build terminan antes de publicar
estado visible. Manifest, lock y el conjunto completo de launchers se preparan
en temporales sincronizados; un marker recuperable gobierna los replaces. Ante
una interrupción se restauran manifest, lock y `bin` anteriores como una unidad.
Después de retirar el marker, el estado nuevo es el commit y los backups son
residuos recolectables.

La implementación incluye fault injection en las cuatro fronteras de
publicación y verifica recuperación del par manifest/lock y launchers. Un check
optimista del manifest evita publicar una resolución preparada contra un
environment modificado concurrentemente.

## Evidencia

Las suites locales, sin Internet público, cubren:

- creación y layout con paths que contienen espacios;
- install de library sin launcher y de tool con launcher ejecutable;
- roots/locks aislados en dos environments y CAS compartido;
- segunda instalación completamente offline desde metadata/archive/source CAS;
- dependencias transitivas y poda al desinstalar el último root que las alcanza;
- reinstalación sin recompilar tools ajenos;
- publicación e inspección cerrada de un source package application;
- build administrado fuera del source y ejecución nativa en O0 y O2;
- reemplazo del launcher, eliminación al uninstall y recuperación por fault;
- parser de `env create`, `install`, `uninstall`, `--env` y opciones de registry.

La separación de imports permanece estructural: sólo las dependencies del
manifest+lock del proyecto llegan al driver. `AETHER_ENV` y `PATH` se consultan
únicamente en la ruta CLI de environments/ejecución de comandos.

## Límites conservados

No se agregaron registries privados, dependencias nativas, packages binarios,
build scripts, workspaces, features, activation magic, installs system-wide,
firmas ni múltiples bins. Los launchers ejecutan código sólo cuando el usuario
invoca el comando; resolución/materialización no ejecutan hooks del package.
