# Aether — OWNING-CLOSURES-READ-V1 — Implementation & Qualification Report

## Estado

`OWNING-CLOSURES-READ-V1 BLOCKED` (1 de noviembre de 2026).

No se modificaron producción, runtime ni los contratos cerrados de
`Function`. El preflight encontró una dependencia normativa ausente que no se
puede sustituir mediante metadata paralela, convenciones locales o una prueba
cross-module aparente.

## Preflight realizado

Se leyeron completos `FIRST_CLASS_CLOSURES_ARCH_1.md` y su reporte de cierre, y
se inspeccionaron los caminos reales de:

- parser, `LambdaId` y declarations sintéticas de anonymous functions;
- `TypeArena`, `TypeData::Function`, propiedades, sustitución y layouts;
- `FunctionRef`/`IndirectCall` y sus verificadores HIR, MIR y SSA;
- ownership, Alias, Move, Drop, replacement, borrows y `EndBorrow`;
- exception events, cleanup normal/unwind y backend LLVM;
- allocator, ARC de string/class/interface, linkage y resolución de packages.

El árbol estaba limpio antes del trabajo. Las regresiones dedicadas previas
quedaron verdes: `anonymous_functions_v1` 5/5 y `function_values_v1` 8/8, con
`CARGO_INCREMENTAL=0` y Cargo serial.

Como gate de no-regresión también se ejecutó `CARGO_INCREMENTAL=0 cargo test
--workspace -j 1`: PASS completo, incluidos frontend, HIR/MIR/SSA, backend,
ownership, references, strings, classes/interfaces, exceptions V1–V4, OOP,
generics, Plots, Graphics, packages, consumers numéricos y doc-tests. `cargo
fmt --all --check` pasó. `cargo clippy --workspace --all-targets -j 1` terminó
con código cero y únicamente warnings preexistentes (`assert_is_empty`,
`needless_borrows_for_generic_args`, `match_same_arms`, `too_many_lines` y
equivalentes); este trabajo no agregó source Rust ni warnings nuevos.

## Bloqueo normativo

`ClosureABI-v1` exige metadata de package que registre y compare, como mínimo,
la versión de Closure ABI, Aether ABI, target triple, fingerprint de data
layout y compiler ABI epoch. Una mezcla incompatible debe rechazarse antes de
ejecutar. El milestone prohíbe inventar un canal de metadata paralelo y ordena
clasificar `BLOCKED` si la infraestructura vigente no ofrece ese contrato.

La infraestructura actual no posee una frontera binaria de packages:

1. `aether-package::PackageMetadata` transporta solamente nombre, versión y la
   línea opcional de compatibilidad `aether`.
2. `CompilationSession` descubre y parsea todas las fuentes alcanzables,
   incluidas las de dependencias.
3. El driver reúne todo el programa en un único `TypedHir`, un único SSA y una
   única llamada a `LlvmTextBackend.emit`.
4. El backend produce un único módulo LLVM y declara expresamente su ABI y
   mangling como bootstrap internos, no como ABI pública.
5. No existe importación de interfaces/objetos Aether precompilados, loader de
   metadata ABI ni etapa donde comparar dos epochs/layouts de compilaciones
   independientes.

Por tanto, un test source con dos módulos sólo demuestra compilación conjunta;
no puede verificar ownership cross-module ni rechazo de ABI incompatible. Una
sección LLVM ad hoc, un campo privado sólo del driver o una convención en el
manifest serían exactamente la metadata paralela prohibida y tampoco crearían
un consumer binario independiente.

## Reproducers mínimos

Se agregaron inputs en `reproducers/owning_closures_read_v1/`:

- `automatic_copy_capture.ae` alcanza el frontend vigente y falla con `E0359`,
  confirmando que la declaración sintética capture-free carece del scope
  léxico exterior necesario para free-variable analysis.
- `explicit_capture_clause.ae` falla en parsing porque la gramática actual
  exige `=>` inmediatamente después de los parámetros.

Estos dos puntos son trabajo propio del vertical y son implementables. No son
por sí solos el motivo de `BLOCKED`; aíslan el estado source actual. El bloqueo
es que no hay forma honesta de ejecutar el caso requerido de incompatibilidad
ABI productor/consumer sin diseñar primero la frontera general de artefactos y
metadata compilada.

## Avances deliberadamente no iniciados

No se agregó parcialmente `TypeData::Closure`, sintaxis, operaciones HIR/MIR/
SSA, helpers ARC ni lowering LLVM. Publicar esas piezas sin el ABI cross-module
bloqueante dejaría un carrier retornable cuyo contrato no puede calificarse y
contradiría la orden de detener la implementación afectada. Tampoco se
introdujeron registries, TLS trampolines, casts de autoridad ni bridges
`Function`/`Closure`.

La qualification funcional, de corrupción HIR/MIR/SSA, runtime O0/O2 y unwind
queda `NOT RUN`, no `PASS`: aún no existe implementación productiva que pueda
ser calificada. Los casos cerrados previos sí se ejecutaron únicamente como
baseline.

## Prerrequisito para desbloquear

Hace falta un milestone general de ABI de artefactos Aether que proporcione:

- formato compiler-owned de interface/object metadata versionada;
- emisión y consumo independiente de libraries compiladas;
- target/data-layout fingerprint y compiler ABI epoch generales;
- validación fail-closed antes del link/load;
- reachability y linkage estable para símbolos runtime y glue referenciados
  desde valores exportados.

Una vez cerrado ese prerrequisito, este milestone puede implementar el diseño
ya normativo sin reabrir `Function` ni la semántica de captures.

## Archivos agregados

- `docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`
- `reproducers/owning_closures_read_v1/README.md`
- `reproducers/owning_closures_read_v1/automatic_copy_capture.ae`
- `reproducers/owning_closures_read_v1/explicit_capture_clause.ae`

Clasificación final: **BLOCKED**.
