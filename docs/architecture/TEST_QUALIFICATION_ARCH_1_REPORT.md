# TEST-QUALIFICATION-ARCH-1 — informe de auditoría

Estado: **AUDIT COMPLETE**
Fecha: 2026-11-27

## 1. Resultado ejecutivo

La qualification actual tiene cobertura fuerte pero una frontera débil: el
comando oficial `cargo test --workspace` mezcla qualification interna del
compilador, conformidad observable, tests algorítmicos de OAL, package/registry,
CLI, LSP y consumers end-to-end. La mezcla ocurre sobre todo dentro de
`aether-driver` y `aether-registry`; por eso separar sólo por crate perdería
cobertura o mantendría el acoplamiento.

Se diseñaron cuatro perfiles: Compiler Core, Language Conformance, OAL
Integration y Full Ecosystem. Full conserva todos los tests sin exclusiones.
Los milestones de lenguaje cierran con Core + Conformance y regresiones focales
según impacto; OAL y Full escalan cuando la superficie tocada lo justifica y se
mantienen como gates periódicos/release.

El detalle normativo del diseño está en
`docs/architecture/TEST_QUALIFICATION_ARCH_1.md`.

## 2. Preflight preservado

Estado encontrado:

- rama `main`, cuatro commits por delante de `origin/main`;
- modificaciones personales en frontend, HIR, MIR, SSA, LLVM, contrato
  semántico y ejemplos;
- `bitwise_operators_v1.rs` y documentación BITWISE sin trackear;
- otros reports y artefactos personales ajenos a esta auditoría.

No se tocó ese trabajo. No se ejecutaron commit, push, reset, clean ni stash.
Los únicos archivos creados por esta fase son este informe y la arquitectura
asociada.

## 3. Evidencia inspeccionada

Se inspeccionaron:

- `compiler-next/Cargo.toml` y los nueve manifests de crates;
- source tests y todos los integration test binaries Rust;
- 351 fixtures en `tests/programs`, 109 fixtures multi-módulo y sus manifests;
- `run-differential.sh`, `run-legacy-differential.sh` y
  `test-differential-harness.sh`;
- paquetes `linearAlgebra`, `graphics`, `plots`, consumers, locks y goldens;
- package resolution/cache/publish y registry store/e2e;
- README de qualification y reports históricos con resultados/timings.

No se ejecutó la qualification completa ni el test QR: el objetivo era diseño,
el working tree contiene BITWISE no commiteado y ya existe evidencia repetida de
duración suficiente para clasificarlo.

## 4. Inventario resumido

| Área | Autoridad principal | Cobertura secundaria |
| --- | --- | --- |
| Lexer/parser/AST | unit tests frontend | vertical y features del driver |
| Tipos/HIR | HIR/types unitarios | inferencia, modules, diagnostics, features |
| MIR/SSA/verificadores | middle unitarios | corrupciones independientes en driver |
| LLVM/runtime | backend unitario | ejecución nativa O0/O2 y contadores |
| Ownership/OOP | HIR/MIR + OOP V1–V3/opt | OAL owners/views/closures |
| Conformance | vertical, programas/módulos, differential 96 | suites focales |
| STD | module_std + strings/text/format/io/etc. | consumers reales |
| OAL | 199 tests linear/graphics/plots | registry QR y consumers |
| Package/registry | package 25 integration tests; registry 5 | driver materialization |
| Ecosistema | CLI, LSP, analysis, workspace | Full Ecosystem |

Conteos del working tree: 1.203 `#[test]`, 926 bajo driver, 96 casos
diferenciales, 26 suites linear, dos graphics y cinco plots. Incluyen la suite
BITWISE no trackeada y no deben usarse como baseline del commit actual.

## 5. Hallazgos de dependencias y cobertura

### OAL que ejercita el compilador

OAL aporta evidencia no replicada con la misma profundidad por fixtures cortos:
compilación de un módulo genérico muy grande, monomorfización, views/strides,
owners y unwind en algoritmos reales, budgets de allocations, IR sin residuo
genérico, O0/O2 y composición plots → graphics con invocables. Esa evidencia
justifica smokes focales y runs periódicos.

No obstante, exactitud SVD/eigen/QR, oráculos NumPy, políticas de cutoff,
serialización SVG, ticks, estilos y goldens son contratos de librería. Un fallo
allí necesita triage y no demuestra por sí mismo una regresión del compilador.

### Registry/package

Los tests de package verifican semver, locks, update/yank, path/registry,
prerelease, ciclos, CAS, offline, checksums, archives hostiles, concurrencia,
HTTPS fail-closed, publicación y atomicidad. `registry_materialization_v1`
demuestra que un package salido del CAS resuelve imports y compila en O0/O2.

La suite registry añade autenticación, ownership, immutability, official,
concurrencia de publicación y dos flujos e2e con ejecución de consumers. No es
correcto clasificar sus cinco tests como una sola responsabilidad.

### Casos lentos y hangs

El caso dominante es
`linear_algebra_oal_publishes_and_runs_real_qr_consumer`. Hay reportes de PASS
en 698,68, 699,32, 699,35, 701,84, 708,32, 708,84, 710,77, 711,28, 715,27 y
724,36 s; revisiones posteriores registran 951,74–1.094,48 s. La instrumentación
histórica observó CPU 99,4–99,7%, memoria estable y finalización normal.

También existen timeouts documentados a 15, 30, 60, 240 y 300 s. Se conservaron
como ejecuciones incompletas: esos presupuestos son inferiores a la duración
normal y no prueban deadlock. El “hang preexistente” se documenta como timeout
preexistente/aparente; no se intenta resolver en esta auditoría.

## 6. Clasificación del consumer QR

El test construye y publica el archive real de `linearAlgebra`, marca la versión
official, crea un consumidor, ejecuta add/sync, valida manifest y lock,
materializa el package, resuelve el import y ejecuta la batería QR en O0 y O2.
Usa store/cache locales y no depende de Internet público.

Clasificación:

- primaria: OAL Integration, publicación/consumo end-to-end;
- secundaria: compatibilidad registry/package/import;
- terciaria: smoke de compiler/backend/runtime a gran escala;
- no corresponde a Compiler Core.

Se ejecuta en qualification global porque el integration test pertenece a un
crate miembro y `cargo test --workspace` no posee taxonomía ni exclusión. Esa
razón mecánica no debe convertirse en política de cierre universal.

## 7. Gates y comandos entregados

La arquitectura define comandos reproducibles para:

- Core: unit tests frontend/middle/backend más verificadores y ownership/OOP
  focales;
- Conformance: todos los binaries no OAL del driver, harness y diferencial de
  96 casos;
- OAL: 199 tests linear/graphics/plots, materialización, package y registry;
- Full: `cargo test --workspace -j 1 --no-fail-fast`, diferencial, clippy y fmt.

Hasta implementar un manifest, Conformance y OAL usan una selección explícita
por nombre de test binary. Se documenta como transición y riesgo, no como diseño
final. Full ejecuta el workspace literal y evita que un test nuevo quede oculto.

## 8. Política de cierre recomendada

- lexer/parser: Core + Conformance obligatorios; OAL focal si cambia sintaxis
  usada en packages grandes;
- HIR/MIR/SSA: Core + Conformance; verificadores afectados y OAL focal por
  generics/ownership/imports;
- ownership/OOP: Core + Conformance; plots/linear focal cuando cambia carriers,
  views, closures o unwind;
- LLVM/runtime: Core + Conformance O0/O2; consumer OAL focal si toca ABI,
  helpers, ARC u optimización;
- STD/OAL: suite afectada obligatoria; OAL Integration obligatorio para OAL;
- registry/package: package + registry + e2e pequeño obligatorios; QR cuando la
  publicación/materialización/import OAL pueda cambiar;
- CLI/packaging: suites CLI/package y Full obligatorio para release.

Full Ecosystem queda periódico, pre-release y obligatorio para cambios
transversales. Un perfil ajeno BLOCKED por timeout preexistente no bloquea
automáticamente un milestone si sus gates obligatorios pasan y existe baseline;
el workspace tampoco se declara PASS.

## 9. Criterio de resultados

- PASS: terminó todo lo obligatorio con expectativas satisfechas.
- FAIL: fallo semántico, assertion, verifier, trap, diagnostic, golden, crash o
  lint obligatorio.
- BLOCKED: infraestructura/plataforma ausente o timeout sin conclusión.

Un timeout nunca se convierte en PASS. Para QR se recomienda provisionalmente
1.500 s y un presupuesto Full de al menos 2.400 s, con telemetría de CPU/RSS/fase
y terminación del árbol de procesos.

## 10. Implementación futura mínima

Se propone un milestone posterior que agregue un manifest versionado de suites
y `tests/qualify.sh` con cuatro perfiles, validación de tests sin clasificar,
timeouts por suite, output JSON/JUnit y baselines por plataforma. No debe cambiar
expectativas ni eliminar cobertura. Las suites mixtas sólo se dividen cuando
sea necesario para seleccionar responsabilidades de forma estable.

## 11. Archivos de esta fase

- `docs/architecture/TEST_QUALIFICATION_ARCH_1.md`
- `docs/architecture/TEST_QUALIFICATION_ARCH_1_REPORT.md`

No se modificaron tests, scripts, Cargo manifests, código productivo ni
documentos de milestones cerrados. No se hizo commit ni push.
