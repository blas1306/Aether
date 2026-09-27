# CLI-V1-PROJECT — reporte

Estado: **IMPLEMENTADO**, 2026-09-26.

Autoridad normativa: [CLI-ARCH-1](CLI_ARCH_1.md),
[CLI-ARCH-1 report](CLI_ARCH_1_REPORT.md) y
[CLI-V1-BOOTSTRAP report](CLI_V1_BOOTSTRAP_REPORT.md).

## Resultado

`aether-cli-next` acepta ahora targets directory exactos para `run`, `build` y
`check`, además de `init <packageName>` e `init --lib <packageName>`. El modo
standalone, su shorthand `.ae`, la frontera `--` y sus outputs permanecen
separados: un archivo nunca consulta un manifest vecino.

La resolución de proyecto canonicaliza una sola raíz entregada por el usuario
y prueba solamente `<root>/aether.toml`. No asciende, no busca descendants y no
adopta el CWD implícitamente.

## Schema implementado

El manifest se decodifica como TOML UTF-8 mediante tipos Serde con
`deny_unknown_fields`:

```toml
[package]
name = "myProject"       # obligatorio; identificador Aether exacto
version = "0.1.0"        # obligatorio; SemVer
aether = "1"             # opcional; por ahora sólo acepta "1"

[application]
entry = "src/main.ae"    # tabla y key opcionales

[dependencies]           # tabla opcional
```

Tablas y keys desconocidas fallan cerradas. Las dependencias admiten solamente
la forma string registry o `{ path = "..." }`; sus nombres y valores básicos
se validan. La política temporal es deliberadamente fail-closed: cualquier
`[dependencies]` no vacío termina con un error explícito porque este vertical
no resuelve registry, paths ni grafos. No hay red, cache ni lockfile. Esta
política será reemplazada por PACKAGE-MANAGER-V1.

## ProjectPlan y clasificación

La CLI construye `ProjectPlan { root, manifest, package, source, kind }` con
paths canónicos y metadata tipada (`PackageName`, `PackageVersion`). El driver
revalida el manifest directo, confinamiento y tipo regular `.ae`; un caller
embebido no puede saltarse esas invariantes.

La selección es exacta: un `application.entry` declarado debe ser relativo,
`.ae`, regular y permanecer dentro de root, sin fallback ante error. Sin entry
se prueba sólo `src/main.ae`. La única raíz library es `src/lib.ae`. App+library
falla como múltiples targets; ninguna raíz falla como package sin source.
`run` acepta sólo application; `check/build` aceptan ambas.

El frontend conserva TOML y discovery fuera de sus capas. Para analizar una
library sin cambiar la ABI ejecutable, el frontend agrega únicamente en memoria
un sentinel privado `main` como raíz técnica del pipeline actual; no se escribe
source, no se enlaza y no aparece como target o artefacto público. Todo el source
library atraviesa parseo, resolución, HIR, MIR y SSA verificados.

## Outputs

Los proyectos usan exclusivamente:

```text
<root>/.aether/build/
  <packageName>             # application executable
  <packageName>.aetherlib   # library bootstrap metadata
```

`build` crea el directorio bajo demanda. El `.aetherlib` registra versión de
formato bootstrap, identidad, versión y source relativo después de un check
semántico exitoso. No es un ejecutable, object file, ABI de distribución ni
formato de registry estable. `run` application usa un ejecutable temporal,
reenvía argv como `OsString`, preserva status y limpia el temporal.

## Init

`init` valida primero el nombre sin transformarlo, construye manifest y source
en un sibling temporal y publica con rename. Rechaza cualquier path destino ya
existente y limpia el árbol temporal tras fallos recuperables. La variante app
crea `src/main.ae`; `--lib` crea `src/lib.ae`. No crea git ni lockfile y no
descarga nada.

## Calificación

La suite cubre root exacto, ausencia de manifest directo, no-discovery en
ancestors/descendants, TOML/schema/name/SemVer inválidos, entry explícito y
escape, fallback `src/main.ae`, library-only, app+lib, ausencia de roots,
rechazo de run library, check/build library, layout `.aether/build`, ambas
formas de init/no-overwrite, standalone con manifest inválido vecino, argv y
O0/O2 de proyecto.

Se ejecutaron los gates requeridos:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

## Deuda explícita

Antes de promoción faltan el cambio coordinado de nombres/packaging y la
eliminación eventual del sentinel interno cuando el IR modele libraries sin
entry de proceso. PACKAGE-MANAGER-V1 debe reemplazar el rechazo temporal de
dependencies e introducir resolución, registry/cache y lockfile. El formato
`.aetherlib` debe reemplazarse o versionarse antes de prometer ABI o
distribución de packages.
