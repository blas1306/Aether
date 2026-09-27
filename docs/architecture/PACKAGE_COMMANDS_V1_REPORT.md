# PACKAGE-COMMANDS-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-27.

Autoridad normativa: [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md),
[PACKAGE-MANAGER-ARCH-1 report](PACKAGE_MANAGER_ARCH_1_REPORT.md),
[PACKAGE-IDENTITY-V1 report](PACKAGE_IDENTITY_V1_REPORT.md),
[PACKAGE-LOCK-RESOLUTION-V1 report](PACKAGE_LOCK_RESOLUTION_V1_REPORT.md),
[PACKAGE-CACHE-REGISTRY-V1 report](PACKAGE_CACHE_REGISTRY_V1_REPORT.md) y
[CLI-ARCH-1](CLI_ARCH_1.md).

## Resultado

La CLI oficial expone targets explícitos, sin project discovery:

```text
aether sync <project>
aether update <project>
aether add <package> <project>
aether add <package> <project> --path <locator>
aether remove <package> <project>
```

`sync` conserva una selección locked válida y sólo crea resolución cuando no
hay lock. `update` resuelve todo el grafo nuevamente y no toca el manifest.
`run`, `build` y `check` siguen pasando por `sync`: nunca actualizan
implícitamente, pero materializan artefactos locked ausentes.

`add` registry enumera releases, excluye yanks y prereleases, elige la mayor y
escribe `major.minor`, `0.minor` o `0.0.patch` según corresponda. La variante
path escribe la forma normativa `{ path = "..." }` y valida igualdad con
`package.name`. `remove` sólo acepta una dependencia directa; una nueva
resolución elimina del lock todos los nodos que dejaron de ser alcanzables.

## Configuración de transporte

Los comandos de proyecto aceptan `--registry <https-url>`,
`--cache-dir <path>` y `--offline`. La precedencia es argumentos CLI, variables
de entorno transicionales y defaults del OS. Se mantienen
`AETHER_REGISTRY_URL`, `AETHER_CACHE_DIR` y `AETHER_OFFLINE`. El endpoint HTTPS
es configuración física; la identidad continúa siendo `official` y ninguna URL
entra al lock.

## Edición y transacción

La edición usa `toml_edit`: sólo agrega o elimina la key gestionada bajo
`[dependencies]`, conservando comentarios, decoración y tablas ajenas. El
resultado se vuelve a parsear con el schema serde fail-closed antes de resolver.

Manifest y lock se publican como una transacción recuperable. Bajo un lock de
proceso por proyecto se preparan y sincronizan backups, temporales y un marker
en el mismo directorio. Se reemplaza manifest y luego lock con fsync de
directorio entre fases; sólo entonces se elimina el marker de commit. Si una
operación se interrumpe mientras el marker existe, el siguiente comando restaura
el par anterior antes de continuar. Tras quitar el marker, el par nuevo ya es
coherente y los backups son sólo residuos recolectables.

Resolución, materialización, checksum, archive validation y serialización del
lock ocurren antes de crear el marker. Un fallo en cualquiera de esas etapas no
toca ninguno de los dos archivos publicados. El CAS global nunca se poda como
efecto de `remove`.

## Evidencia

Las suites de `aether-package` y `aether-cli` cubren:

- sync con/sin lock, conservación y update compatible/yank;
- add registry, duplicado y constraints `0.x`/`0.0.x`;
- add path con locator exacto;
- remove directo, rechazo transitivo y poda;
- conservación de comentarios/formato no gestionado;
- publicación exitosa, fallo previo sin cambios y recuperación entre replaces;
- parsing/targets explícitos y flags de registry/cache/offline;
- integración posterior con `run`, `build` y `check`;
- materialización offline desde CAS y misses offline diagnósticos.

Publish/auth, environments y update parcial continúan fuera de V1.
