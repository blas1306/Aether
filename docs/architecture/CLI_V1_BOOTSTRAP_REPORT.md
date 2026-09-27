# CLI-V1-BOOTSTRAP — reporte

Estado: **IMPLEMENTADO**, 2026-09-26.

Autoridad normativa: [CLI-ARCH-1](CLI_ARCH_1.md) y
[CLI-ARCH-1 report](CLI_ARCH_1_REPORT.md).

## Resultado

Se agregó el crate `compiler-next/crates/aether-cli` y su binario temporal de
desarrollo `aether-cli-next`. No se promovió el nombre `aether`, no se renombró
la CLI Python y no se agregó project/manifest/package management.

El flujo nuevo es in-process:

```text
argv -> aether-cli -> DriverRequest -> aether-driver -> compiler pipeline
```

`aether-cli` posee ahora la gramática de `run`, `build`, `check` y shorthand
`.ae`, la frontera irreversible `--`, la cardinalidad y clasificación del
target y los errores de uso. Un file target se canonicaliza como archivo
regular `.ae`; no se busca ni se lee `aether.toml`.

## Frontera tipada

El driver expone `DriverRequest::{Check, Build, Run}` con requests distintos:

- `CheckRequest` contiene un único `StandaloneFile` y opciones de compilación;
- `BuildRequest` agrega únicamente un path de artefacto retenido;
- `RunRequest` agrega únicamente `program_args: Vec<OsString>`.

Esta forma no puede representar target ausente o múltiple, ni argumentos de
programa en build/check. `StandaloneFile::new` vuelve a validar y canonicalizar
la frontera para callers distintos de la CLI. `execute` y
`execute_with_toolchain` son las entradas Rust in-process.

La cola posterior al primer `--` se conserva como `OsString`, sin pasar por
shell ni por una conversión UTF-8 con pérdida. La CLI no vuelve a interpretar
ningún token de esa cola.

## Límite real de `check`

El pipeline de sesión se separó en análisis y backend. `check` ejecuta:

1. discovery, lectura, lexer/parser y resolución del source graph;
2. colección de firmas y análisis semántico/typecheck;
3. lowering a MIR y `verify_mir`;
4. construcción de SSA y `verify_ssa`;
5. en O2, `optimize_oop`, que devuelve SSA nuevamente verificado.

Se detiene ahí. No llama a `LlvmTextBackend.emit`, no produce LLVM, no invoca
clang, no enlaza y no crea ejecutable. Pedir `--emit llvm` a `check` se rechaza
como uso inválido.

## Build, run y outputs bootstrap

`build file.ae` retiene el ejecutable en el path del source sin la extensión
`.ae`; `-o path` selecciona un path explícito. La CLI escribe el path resultante
en stdout. Esta política es sólo para standalone y no anticipa layout
`.aether/` de proyectos.

`run` construye un ejecutable temporal, hereda stdin/stdout/stderr, ejecuta con
argv exacto y devuelve el status normal del programa. Un guard RAII elimina el
artefacto tanto en éxito como ante errores normales de build/exec. Un status
sin código representable produce diagnóstico y exit 1.

## Compatibilidad conservada

Siguen existiendo `aether-next`, su parser bootstrap interno y las APIs
`compile_source`, `compile_session`, `build_path`, `run_path` y
`run_path_with_arguments`, porque tests, herramientas de medición, el runner
diferencial y la CLI Python transicional dependen de ellos. La nueva CLI no
usa el parser de `aether-next`: construye el request tipado y llama al driver.
La API String antigua adapta a la nueva ejecución con `OsString`.

No hay shell-out a otra CLI Aether. En código productivo de la ruta nueva,
`aether-cli` no contiene `Command`; los únicos `Command::new` del driver son
clang y el artefacto nativo temporal. `aether-next` no es invocado por la CLI.

## Pruebas

Se agregaron pruebas unitarias, de API y end-to-end para:

- parser, target obligatorio/único, shorthand idéntico a run y precedencia;
- `--`, cola exacta incluyendo otro `--` y bytes no UTF-8;
- rechazo de `--`/colas en build y check;
- paths con espacios y manifest vecino inválido ignorado;
- argv real, artifact de build, ausencia de artifact/LLVM en check;
- limpieza temporal, status del programa y errores de target con exit 2;
- API directa del driver, check con clang deliberadamente inexistente y
  ejecución O0/O2.

Validación ejecutada:

- `cargo test --workspace`: OK;
- `cargo fmt --all --check`: OK;
- `cargo clippy --workspace --all-targets -- -D warnings`: OK;
- `git diff --check`: OK;
- `bash compiler-next/tests/run-differential.sh`: 21 casos, 0 fallos.

## Deuda del siguiente vertical

Quedan deliberadamente fuera `ProjectPlan`, lectura/validación de
`aether.toml`, targets directorio, project root explícito, `init`, layout de
outputs de proyecto, targets library/application, resolución de dependencias,
lockfile, registry/cache y package management. También quedan para el cutover
posterior la promoción del binario Rust a `aether`, el rename Python a
`aether-legacy` y el retiro eventual de las APIs/bootstrap `aether-next`.
