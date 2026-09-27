# CLI-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-26.

Documento normativo: [CLI_ARCH_1](CLI_ARCH_1.md).

## Resultado

Se cerró la arquitectura de la futura CLI oficial sin modificar código ni
prometer disponibilidad anticipada.

- La CLI Rust `aether` será un frontend del `aether-driver` in-process y de
  `compiler-next`; no contendrá fases semánticas ni ejecutará otra CLI Aether.
- `run/build/check` requieren un target. Sólo un primer token `.ae` habilita
  shorthand exacto de `run`; `aether .` queda rechazado.
- `--` termina irreversiblemente el parsing en `run` y preserva toda la cola
  para el programa. `build/check` lo rechazan.
- Archivo y proyecto son modos disjuntos. Un archivo ignora manifests vecinos;
  un directorio exige `aether.toml` directo y nunca dispara búsqueda en
  ancestors o descendants.
- La frontera CLI/driver usa requests tipados que no pueden representar target
  ausente, argv en operaciones no ejecutables ni proyecto sin manifest.
- `check` debe terminar antes de codegen/link; `build` y `run` permanecen en el
  driver, junto con toolchain y ejecución.
- `aether.toml` V1 fija identidad `name/version`, compatibilidad opcional
  `aether`, entry de aplicación y dependencies registry/path.
- `application.entry` es relativo, `.ae` y confinado al root; si se omite,
  `src/main.ae` es la única convención runnable.
- `src/lib.ae` es el único root library V1. Packages library-only son válidos
  para `check/build`, no para `run`; application+library en un mismo package es
  el caso de múltiples targets deliberadamente excluido.
- Package name e import namespace son una sola identidad. `camelCase` es la
  convención oficial, no una traducción ni una restricción extra sobre
  identificadores Aether válidos.
- Los comandos de package management tienen espacio reservado, sin stubs ni
  semántica inventada.
- La promoción renombrará coordinadamente la CLI Python a `aether-legacy` y
  pondrá la CLI Rust en `aether`; la nueva CLI no tendrá `--compiler` ni
  fallback legacy.

## Evidencia del estado actual

La inspección de `compiler-next` confirmó una separación parcial aprovechable:

| Estado actual | Consecuencia arquitectónica |
|---|---|
| `aether-driver` ya expone compilación de sesión, build y run | se conserva como librería de orquestación, no se duplica en CLI |
| el binario `aether-next` parsea argv dentro del crate driver | parsing debe moverse a `aether-cli`; el binario queda bootstrap interno |
| `build_path` descubre source, compila y enlaza | el request final debe separar input resuelto y operación |
| `run_path_with_arguments` ya reenvía un vector sin shell | se conserva el principio y se tipa la frontera `--` en CLI |
| no existe operación pública `check` que corte antes de LLVM | el primer vertical debe crear un límite semántico real |
| la CLI Python posee `--compiler` y localiza `aether-next` | es conducta transicional legacy, no base de la CLI nueva |
| no existe soporte actual de `aether.toml` en compiler-next | el manifest se mantiene fuera del compiler pipeline y sin implementación aquí |

Las APIs actuales son evidencia, no autoridad pública final. En particular no
se renombra el binario driver existente ni se convierte su parser mínimo en la
CLI oficial.

## Fronteras cerradas

```text
argv + filesystem explícito
        -> aether-cli
        -> DriverRequest tipado
        -> aether-driver
        -> compiler-next pipeline
        -> clang / artefacto sólo cuando la operación lo requiere
```

Project discovery significa validar el directorio entregado, no buscar uno. La
resolución de imports desde el archivo elegido sigue siendo trabajo legítimo
del compiler source graph y no permite adoptar metadata de un manifest vecino.

Manifest/dependency resolution puede crecer luego en un crate reutilizable,
pero entrega un `ProjectPlan`; nunca empuja registry, red o TOML hacia frontend,
HIR, MIR, SSA o backend.

## Transición aprobada

1. bootstrap Rust bajo nombre de desarrollo;
2. soporte de proyectos e `init`;
3. promoción coordinada: Rust `aether`, Python `aether-legacy`;
4. freeze legacy salvo fixes críticos;
5. retiro tras cubrir `run/build/check/init` y package manager V1.

No habrá período permanente de selección `next|legacy` detrás de un único
comando. La elección transicional es explícita por nombre de ejecutable.

## Validación de este milestone

- Se crearon únicamente el documento normativo, este reporte y un enlace de
  descubrimiento documental.
- No se modificaron crates, manifests Cargo/TOML de usuario, Python, packaging,
  tests, pipeline, runtime ni binarios.
- La gramática, shorthand, `--`, targets, entry, schema conceptual, naming,
  capas, salida, transición y gate de retiro quedan definidos.
- Registry, lockfile, encoding físico de artefactos de librería y
  package-manager UX permanecen explícitamente diferidos y no pueden inferirse
  de esta arquitectura.

No corresponde ejecutar suites de compilador: no cambió código ejecutable. La
calificación de CLI empieza en `CLI-V1-BOOTSTRAP`, con unit, filesystem,
driver-API y end-to-end tests.
