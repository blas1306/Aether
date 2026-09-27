# CLI-PROMOTION — reporte

Estado: **IMPLEMENTADO**, 2026-09-26.

Autoridad normativa: [CLI-ARCH-1](CLI_ARCH_1.md),
[CLI-ARCH-1 report](CLI_ARCH_1_REPORT.md),
[CLI-V1-BOOTSTRAP report](CLI_V1_BOOTSTRAP_REPORT.md) y
[CLI-V1-PROJECT report](CLI_V1_PROJECT_REPORT.md).

## Resultado

El crate Rust `aether-cli` instala el binario oficial `aether` y llama a
`aether-driver` in-process. El package Python dejó libre ese nombre e instala
su interfaz histórica exclusivamente como `aether-legacy`. No hay dos entry
points de packaging que reclamen `aether`.

La selección transicional ocurre sólo por nombre:

```text
aether         -> aether-cli -> aether-driver -> compiler-next
aether-legacy  -> aether.cli -> compilador Python histórico
```

`aether` no contiene selector de compilador, no consulta variables de entorno
para elegir implementación, no reintenta con Python y no ejecuta ninguna CLI
Aether. `--compiler next`, `--compiler legacy` y sus formas con `=` fallan como
opciones desconocidas. La frontera de proceso legítima del driver sigue
limitada a clang y al artefacto nativo producido para `run`.

## Breaking changes intencionales

- El wheel Python ya no instala `aether`; instala `aether-legacy`.
- `aether` designa siempre la CLI Rust y acepta `run`, `build`, `check`,
  `init` y el shorthand de archivo `.ae`.
- Las opciones históricas como `--backend`, `--repl`, `--tokens` y
  `--compiler` pertenecen únicamente a `aether-legacy` durante la migración.
- La extensión VS Code usa la gramática Rust (`run`, `check` y
  `--emit <phase>`) y dejó de ofrecer selección de backend legacy.

## Freeze legacy

Desde esta promoción, features nuevas y cambios normales se implementan sólo
en Rust/compiler-next. `aether-legacy` queda congelado y recibe únicamente
fixes críticos de seguridad, pérdida de datos o bloqueos de migración. Todavía
no se elimina: su retiro continúa condicionado a package manager V1 además de
la superficie CLI ya implementada.

## Bootstrap interno pendiente

`aether-next` permanece en el crate `aether-driver` porque el differential
runner, pruebas directas del driver y scripts históricos de medición todavía
dependen de su parser y de su path de artefacto. No se instala mediante el
crate `aether-cli`, no se presenta como comando normal y `aether` nunca lo
invoca. Migrar esos consumidores a la API Rust tipada queda como limpieza
posterior y no bloquea el cutover público.

## Packaging

Desde la raíz del repositorio:

```bash
cargo install --path compiler-next/crates/aether-cli
python3 -m pip install .
```

El primer comando instala `aether`; el segundo instala `aether-legacy` y las
herramientas Python auxiliares. Ambos son launchers instalados y no dependen
del checkout ni del CWD para localizar su implementación.

El wheel RC versionado en `python-dist/` se regeneró con la misma ownership de
nombres y una prueba inspecciona sus `console_scripts`, evitando que un
artefacto preconstruido vuelva a instalar la antigua colisión.

No se implementó package manager, registry, red, lockfile ni ninguno de los
comandos reservados `add/remove/sync/update/install/uninstall/publish`.

## Calificación

Se ejecutaron satisfactoriamente:

```text
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
npm test                              # vscode-extension
bash compiler-next/tests/run-differential.sh  # 21 casos, 0 fallos
cargo install --path compiler-next/crates/aether-cli --locked --offline
git diff --check
```

El install probe, ejecutado fuera del checkout, produjo únicamente `aether` y
el probe del wheel confirmó únicamente `aether-legacy` para la CLI Python.
