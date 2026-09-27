# PACKAGE-MANAGER-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-26.

Documento normativo:
[PACKAGE_MANAGER_ARCH_1](PACKAGE_MANAGER_ARCH_1.md).

Autoridad previa: [CLI_ARCH_1](CLI_ARCH_1.md),
[CLI_ARCH_1_REPORT](CLI_ARCH_1_REPORT.md),
[CLI_V1_BOOTSTRAP_REPORT](CLI_V1_BOOTSTRAP_REPORT.md),
[CLI_V1_PROJECT_REPORT](CLI_V1_PROJECT_REPORT.md) y
[CLI_PROMOTION_REPORT](CLI_PROMOTION_REPORT.md).

## Resultado

Se cerró el package manager V1 como arquitectura, sin implementar comandos,
registry, networking ni cambios al compiler.

- El Aether Package Registry es el registry público central y usa nombres
  globales. Su ID lógico no depende del dominio web futuro.
- Package name, dependency key e import namespace son el mismo spelling exacto;
  `camelCase` es convención, no transformación. Los source units importables
  quedan confinados a ese root o sus descendants.
- Las OAL son packages normales del registry con ownership oficial, sin compiler
  magic, resolver privilegiado ni formato especial.
- `aether.toml` conserva dependencies registry string y `{ path = ... }`. La
  gramática V1 acepta constraints compatibles tipo caret y exactas `=SemVer`.
- `aether.lock` registra identidad/version/source/checksum/edges exactos. Se
  versiona en applications y libraries, pero no gobierna consumers al publicar.
- El resolver es edge-local: elige la mayor versión compatible no-yanked por
  edge, comparte identidades exactas y permite múltiples versiones sin solver
  global sofisticado.
- `sync` respeta el lock; sin lock crea la resolución inicial. `update` autoriza
  nueva resolución compatible. `add/remove` mutan manifest+lock
  transaccionalmente.
- El cache global es content-addressed, verifica SHA-256 y comparte archives/
  source inmutable entre proyectos. `.aether/` queda para state/build local.
- Publish empaqueta source permitido de forma determinista, rechaza path deps y
  crea versiones inmutables. Yank afecta candidatos nuevos, no locks existentes.
- Project, virtual environment opcional y user environment son scopes aislados.
  `add/remove` no equivalen a `install/uninstall`; libraries globales nunca
  contaminan imports de proyectos y `PATH` sólo expone tools.
- La frontera del compiler recibe source roots/providers, package identities y
  edges exactos. Nunca recibe registry URLs, credentials, red, cache policy ni
  TOML raw.

## Matriz operacional cerrada

| Operación | Manifest | Lock | Selección de versiones | Cache |
|---|---|---|---|---|
| `add p` | agrega dependency | reescribe | nueva, todo el grafo | materializa |
| `remove p` | elimina directa | poda/reescribe | resuelve grafo restante | no purga |
| `sync` con lock | no cambia | valida/conserva | ninguna nueva | materializa faltantes |
| `sync` sin lock | no cambia | crea | mayor compatible | materializa |
| `update` | no cambia | reescribe | nueva compatible | materializa |
| `install/uninstall` | sólo env | lock del env | scope seleccionado | comparte CAS |

Un manifest cambiado con lock incompatible hace fallar `sync`; no actualiza por
sorpresa. Un package yanked pero locked sigue permitido. Todo checksum distinto
falla cerrado. Los paths aparecen en el lock pero sus bytes siguen editables y
se fingerprintan en cada build.

## Modelo nominal y multiversión

La auditoría confirmó que el frontend actual usa
`PackageKey(OriginKey, PackagePath)` y que `OriginKey` sólo posee `Project` y
`Toolchain`. Eso no basta para:

```text
App -> A -> math@1
    -> B -> math@2
```

PACKAGE-MANAGER-V1 debe agregar una identidad estructural de instancia antes de
internar `PackageId`. La tabla de imports se contextualiza por owner:
`(A-instance, "math") -> math@1` y `(B-instance, "math") -> math@2`. HIR y
capas posteriores pueden conservar IDs densos dentro de la sesión, siempre que
su clave nominal/mangling/fingerprint incluya la instancia exacta. El source
continúa escribiendo `import math`, nunca `math@1`.

## Auditoría de integración

| Estado actual | Cambio requerido |
|---|---|
| `aether-cli` ya parsea registry/path con Serde fail-closed | reutilizar schema y reemplazar rechazo temporal por resolución |
| todo `[dependencies]` no vacío falla explícitamente | eliminar sólo al entregar manifest+lock al resolver real |
| `ProjectPlan` contiene root/manifest/package/source/kind | extender a grafo, instancias, source units y edges exactos |
| driver descubre escaneando el root derivado del entry | aceptar `PackageIndex`/providers multi-root ya resueltos |
| imports no-`std` reciben siempre origin `Project` | resolver por edge del package owner |
| `PackageName` y `PackageVersion` ya validan identidad/SemVer | compartirlos con la capa package sin duplicar reglas |
| `CompilationSession` ordena sources e interna IDs | conservar catálogo/IDs, alimentados por claves más fuertes |
| `.aetherlib` es metadata bootstrap | no tratarlo como archive, ABI ni artifact de registry |

La capa nueva recomendada es un crate reutilizable para manifest, lock,
resolución, registry/cache y planes. `aether-cli` posee UX y mutaciones;
`aether-driver` consume el plan. Lexer, parser, HIR, MIR, SSA y backend no
incorporan package-management policy.

## Seguridad y reproducibilidad

El baseline aprobado exige HTTPS, versiones inmutables, SHA-256, downloads y
extracciones atómicas, rechazo de traversal/links/files especiales, cache
autoverificable y fail-closed ante corrupción. No hay install-time code, build
scripts, native hooks ni binaries publicados V1.

Clonar + `aether sync` reconstruye las versiones y bytes registry exactos del
lock. Path deps reconstruyen la misma topología relativa, pero su contenido
depende deliberadamente de la checkout local; el build fingerprint detecta
cambios. Global/user installs, environments, CWD y releases nuevas no alteran
un project locked.

## Decisiones diferidas

Se difieren dominio/protocolo del servicio, UX final de auth/yank/env/offline,
GC, firmas, private registries, git, workspaces, features, optional/platform/
native dependencies, cross variants, binary ABI, build scripts y plugins.
También se difieren update parcial y aliases. Estas extensiones no pueden
debilitar identidad nominal, aislamiento de project ni frontera sin red del
compiler.

## Riesgos para PACKAGE-MANAGER-V1

1. **Cambio transversal de identidad.** Multiversión afecta catálogo, imports,
   nominal types, mangling y cache; agregar sólo paths al driver produciría
   colisiones silenciosas.
2. **Discovery actual demasiado implícito.** El scan desde el entry debe
   reemplazarse por providers/roots exactos sin romper packages parciales ni el
   anonymous entry.
3. **Edición TOML transaccional.** Preservar comments y publicar manifest+lock
   coordinadamente requiere una estrategia probada de recovery.
4. **Paths portables.** Canonicalizar para seguridad y persistir relativo para
   reproducibilidad crea casos difíciles con symlinks, drives y non-UTF-8; V1
   los rechaza cuando no son representables.
5. **Cache hostil/concurrente.** Archives corruptos, traversal, writers muertos
   y procesos simultáneos deben probarse antes de confiar en CAS compartido.
6. **Registry snapshot.** Sin respuestas/version metadata coherentes una misma
   resolución inicial podría observar estados distintos; el cliente debe fijar
   su snapshot lógico y ordenar por sí mismo.
7. **Library/tool classification.** La superficie actual admite un target V1 y
   `.aetherlib` provisional; publish/install no deben prometer una ABI ni varios
   executables accidentalmente.
8. **Legacy retirement.** El gate de retiro depende de una implementación y
   calificación reales de este diseño, no de estos documentos.

## Validación del milestone

Este milestone crea solamente el documento normativo y este reporte. No se
modifican Rust, Python, manifests de usuario, packaging, tests, CLI ni servicios
externos. Por ser un cambio documental corresponde `git diff --check`; las
suites de compiler/package manager pertenecen al vertical de implementación.
