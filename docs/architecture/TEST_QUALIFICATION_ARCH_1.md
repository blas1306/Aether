# TEST-QUALIFICATION-ARCH-1

Estado: **AUDIT COMPLETE / DESIGN PROPOSED**
Fecha de auditoría: 2026-11-27
Ámbito: `compiler-next` y las librerías oficiales Aether presentes en este
repositorio.

## 1. Decisión

La qualification se divide en cuatro perfiles por responsabilidad, no por
crate. Core y Conformance forman la ruta de lenguaje; OAL es un eje de
integración separado y Full es la unión sin exclusiones:

1. **Compiler Core**: invariantes internas del compilador, verificadores,
   ownership, backend y runtime mínimo.
2. **Language Conformance**: Compiler Core más programas Aether que fijan la
   semántica observable, diagnósticos, traps, O0/O2 y diferencial oficial.
3. **OAL Integration**: librerías oficiales y su integración real, incluido el
   consumo a través de packages cuando corresponda.
4. **Full Ecosystem**: todas las pruebas del workspace, sin omisiones, más los
   gates oficiales que viven fuera de Cargo.

Los perfiles son ejes de evidencia y no una jerarquía de importancia. En
particular, OAL Integration no es requisito automático para cerrar todo cambio
del lenguaje. Full Ecosystem conserva la detección periódica de interacciones
que los perfiles focales no cubren.

No se cambia, elimina, ignora ni deshabilita ninguna prueba en esta fase.

## 2. Preflight y restricciones observadas

La auditoría comenzó sobre `main`, cuatro commits por delante de `origin/main`,
con un working tree sucio. Se preservaron todos los cambios personales. En
particular, BITWISE-OPERATORS-V1 tenía cambios no commiteados en frontend, HIR,
MIR, SSA y LLVM, además de
`crates/aether-driver/tests/bitwise_operators_v1.rs` sin trackear. Los conteos de
este documento son por tanto una fotografía del working tree, no una declaración
del último commit.

No se ejecutaron `commit`, `push`, `reset`, `clean` ni `stash`. Tampoco se
modificaron tests, scripts, manifests Cargo, código productivo ni milestones
cerrados.

## 3. Topología actual

El workspace contiene nueve crates:

| Crate | Responsabilidad predominante | Por qué no basta para clasificar |
| --- | --- | --- |
| `aether-frontend` | lexer, parser, AST, tipos, HIR, ownership semántico | Sus tests unitarios cubren varias capas; depende de `aether-package` para identidad de módulos. |
| `aether-middle` | lowering MIR, SSA, verificadores y optimización OOP | Las corrupciones independientes más fuertes también viven en integration tests del driver. |
| `aether-backend-llvm` | emisión LLVM y helpers de runtime | La mayor parte de la evidencia nativa O0/O2 vive en el driver. |
| `aether-driver` | orquestación y ejecución | Mezcla core, conformance, STD, OAL, registry y end-to-end. |
| `aether-package` | manifests, resolución, lock, CAS, transporte y publicación | Tiene lógica pura de resolución y también integración de filesystem/registry. |
| `aether-registry` | almacenamiento y política de publicación | Su suite mezcla contratos del servicio, consumo real y OAL. |
| `aether-cli` | CLI productiva y bootstrap | Sus pruebas cubren parsing de CLI, proyectos y packaging. |
| `aether-analysis` | diagnósticos/editor/lifecycle/symbols | Consume frontend/package, pero no califica el compilador nativo completo. |
| `aether-lsp` | protocolo y servidor LSP | Es ecosistema/editor, no lenguaje core. |

Fotografía del inventario encontrada:

- 1.203 atributos `#[test]` bajo `compiler-next/crates`;
- 926 en el árbol de tests del driver;
- 351 fixtures `.ae` en `tests/programs` y 109 en `tests/modules`;
- 96 filas normativas en `tests/differential.tsv`;
- 40 filas en el contrato multi-módulo `tests/modules/v1-contract.tsv`;
- 26 archivos / 147 tests de `linear_algebra_*`, 2 / 19 de `graphics_*` y
  5 / 33 de `plots_*`.

### 3.1 Comandos vigentes y alcance real

La documentación actual de `compiler-next` prescribe:

| Comando actual | Alcance real |
| --- | --- |
| `cargo test --workspace` | Todos los unit, integration y doc tests de los nueve crates; mezcla core, conformance, OAL, package, registry, CLI, analysis y LSP. |
| `cargo clippy --workspace --all-targets -- -D warnings` | Calidad estática de todo target del workspace; no prueba semántica observable. |
| `tests/run-differential.sh` | Gate normativo de 96 programas del compilador actual: status exacto, diagnostic ID o trap. Construye `aether-next` si no se provee `AETHER_NEXT_BIN`. |
| `tests/test-differential-harness.sh` | Autotest del harness: aislamiento de legacy, expectativas erróneas, compiler roto y fallos de infraestructura. |
| `tests/run-legacy-differential.sh` | Observación histórica opt-in; su disponibilidad y exit status no pertenecen a qualification oficial. |
| `cargo test -p <crate>` | Todo el crate elegido; sólo es una frontera útil cuando sus responsabilidades son homogéneas. `aether-driver` y `aether-registry` no lo son. |
| `cargo test -p aether-driver --test <suite>` | Gate focal reproducible por feature; hoy es la unidad práctica de selección más precisa y estable. |

Los scripts de medición `tests/measure-*.py` y los JSON bajo `tests/timings`
producen evidencia descriptiva de fases/costes; no forman parte del gate oficial.
Los workflows Rust de `.github/workflows` califican autoridades IR/verificadores
y promoción en CI, pero no sustituyen el contrato local anterior ni ofrecen la
separación Core/Conformance/OAL solicitada.

## 4. Inventario por responsabilidad real

### 4.1 Lexer, parser y AST

Cobertura directa:

- unit tests de `aether-frontend/src/lexer.rs`, `parser.rs` y `core.rs`;
- `aether-frontend/tests/symbol_source_mapping.rs`;
- negativos sintácticos y de módulos en `aether-driver/tests/vertical.rs`;
- suites focales como `package_ergonomics_v1`, `default_parameters_v1`,
  `anonymous_functions_v1`, `compound_assignment_v1`, `postfix_update_v1` y,
  cuando sea incorporada al baseline, `bitwise_operators_v1`.

Los tests del driver no son “backend tests” sólo porque terminan compilando:
muchos fijan precedencia, forma AST, spans y diagnósticos antes de llegar a HIR.

### 4.2 Resolución de tipos y HIR

Cobertura directa:

- 74 unit tests en `aether-frontend/src/hir.rs`, ocho en `types.rs` y ocho en
  `hir/classes.rs` en la fotografía auditada;
- tests de inferencia genérica, capabilities, overloads, aliases, imports,
  visibilidad, nominalidad y diagnósticos en el driver;
- `module_std_v1`, `package_ergonomics_v1` y fixtures multi-módulo;
- assertions y corrupciones HIR retenidas en suites de cada feature.

### 4.3 MIR, SSA y verificadores

Cobertura directa:

- 17 unit tests de MIR y 18 de SSA;
- `ssa_store_provenance_v1` como qualification independiente del verificador;
- corrupciones MIR/SSA en `core_v1`, `const_v1`, OOP V1/V2/V3,
  `oop_opt_1`, ownership, exceptions, invocables y suites de features;
- verificación del output optimizado antes de LLVM en suites O2.

Es una cobertura cruzada deliberada: los unit tests prueban invariantes locales;
las mutaciones del driver demuestran que cada IR rechaza metadata u operaciones
forjadas sin confiar en la fase anterior.

### 4.4 LLVM y runtime

Cobertura directa:

- unit tests en `aether-backend-llvm/src/lib.rs` y `text.rs`;
- compilación con clang y ejecución de artefactos en el driver;
- contadores de allocations, ARC, drops, unwinding y helpers emitidos;
- O0/O2 en core, OOP, exceptions, strings/text, IO, collections y matemática;
- traps por overflow, división, casts, bounds y shapes.

El backend no queda calificado ejecutando sólo `cargo test -p
aether-backend-llvm`: la evidencia de ABI y runtime está principalmente en los
tests nativos del driver.

### 4.5 Ownership y OOP

Cobertura directa:

- síntesis y validación de ownership en HIR y MIR;
- `borrow_ergonomics_v1`, invocables borrowed, closures, owning fields,
  early-return y replacement;
- `oop_v1`, `oop_v2`, `oop_v3`, `oop_opt_1`, class buffers y referencias a
  handles;
- corrupciones independientes, ARC físico/lógico, dispatch, destrucción,
  keepalives y unwind en O0/O2.

Estas suites pertenecen simultáneamente a Compiler Core (invariantes y
verificadores) y Language Conformance (comportamiento nativo). Hasta que exista
selección por test, se ejecuta el binario de integración completo en ambos
perfiles cuando el área lo requiere; no se finge una precisión que Cargo no
ofrece hoy.

### 4.6 Conformidad de programas Aether

Cobertura directa:

- `vertical` y sus módulos `vertical31`, `vertical32`, `vertical33`;
- fixtures en `tests/programs` y `tests/modules`;
- suites focales del driver para core language, módulos, strings, collections,
  exceptions, OOP y herramientas del lenguaje;
- `tests/run-differential.sh`, que valida 96 expectativas actuales: exit status,
  diagnostic ID o trap.

`run-differential.sh` no compara contra LLVM ni contra el compilador Python. Es
un gate normativo de `compiler-next`. `run-legacy-differential.sh` es sólo
evidencia histórica y nunca debe decidir PASS/FAIL de qualification oficial.

### 4.7 Traps, O0/O2 y diferencial

No constituyen una sola suite:

- el manifiesto diferencial incluye aceptación, rechazo y traps;
- el driver ejecuta pares O0/O2 y compara status, salida, goldens o contadores;
- `oop_opt_1` prueba la transformación y la reverificación de SSA;
- overflow, división/casts, bounds y shapes se encuentran en `vertical` y suites
  focales.

Riesgo actual: no hay una etiqueta mecánica que garantice que todo test
semántico con O0 tenga su par O2. El futuro manifest de qualification debe
registrar explícitamente `profiles`, `optimization` y `timeout`.

### 4.8 STD y OAL

STD es la superficie estándar materializada o emitida por el compilador:
`module_std_v1`, strings/text, numeric parsing, iteration, format, IO, process,
file y helpers de runtime. Sus tests suelen ser conformance porque fijan tipos,
diagnósticos, ownership y comportamiento observable del lenguaje/runtime.

OAL son paquetes fuente oficiales externos al core en este repositorio:

- `linearAlgebra` y las 26 suites `linear_algebra_*`;
- `graphics` y `graphics_{foundation,svg_backend}_v1`;
- `plots` y las cinco suites `plots_*`;
- consumers, manifests, locks y goldens de esos paquetes.

No toda prueba OAL tiene la misma responsabilidad:

- tests de superficie, algoritmos, oráculos NumPy, SVG y goldens son
  predominantemente de librería;
- assertions de lowering genérico, ownership, unwind, allocations, O0/O2 e IR
  también ejercitan el compilador, pero en composición con código OAL;
- consumers multi-paquete son integración;
- publicación y consumo por registry son ecosistema end-to-end.

### 4.9 Registry y package management

`aether-package/tests/resolution.rs` verifica resolución semver, multiversión,
lock estable, update, yank, prerelease, ciclos, add/remove y dependencias path.
`registry_cache.rs` verifica HTTPS fail-closed, metadata, CAS, offline, checksum,
archives hostiles, concurrencia y materialización. `publish.rs` verifica el
allowlist y la identidad del archive de publicación.

`aether-driver/tests/registry_materialization_v1.rs` cruza CAS, resolución,
import y check de un consumidor en O0/O2. Es un smoke de integración package →
compiler y no una prueba del servicio registry.

`aether-registry/tests/registry.rs` contiene cinco responsabilidades distintas:

- ownership, immutability, retry, yank y metadata official;
- autenticación, checksum e identidad del archive;
- first-publish concurrente;
- publish/add/sync/lock/update y ejecución de un consumidor pequeño O0/O2;
- publicación y ejecución del consumidor QR real de `linearAlgebra`.

### 4.10 CLI, publicación y end-to-end

`aether-cli/tests/bootstrap.rs` y `aether-driver/tests/cli_v1_api.rs` cubren la
frontera CLI. Los tests de package/publication cubren artefactos y resolución.
Los dos últimos tests del registry cruzan filesystem, store, package manager,
driver, compiler, clang y ejecución nativa; son end-to-end aunque estén dentro
del crate `aether-registry`.

## 5. Mapa de cobertura cruzada

| Contrato | Core | Conformance | OAL | Ecosystem |
| --- | :---: | :---: | :---: | :---: |
| Tokens, AST, tipos, HIR | primario | programas/errores | uso compuesto | indirecto |
| MIR/SSA y verificadores | primario | corrupciones/features | lowering de librerías | indirecto |
| LLVM/ABI/runtime mínimo | primario | primario observable | carga real | completo |
| Ownership/OOP | invariantes | semántica y errores | stress de owners | completo |
| Traps y O0/O2 | mínimo focal | primario | compatibilidad | completo |
| Algoritmos y API OAL | no | smoke elegido | primario | completo |
| Package resolution/import | no salvo identidad de módulo | imports locales | consumers | primario |
| Publish/registry/CAS | no | no | consumer publicado | primario |
| CLI/LSP/editor | no | CLI sólo si afecta semántica | no | primario |

La duplicación útil se conserva. Un smoke OAL no reemplaza una prueba pequeña de
lenguaje, y una prueba pequeña no reemplaza el stress de un consumer real.

## 6. Gates propuestos

Todos los comandos se ejecutan desde `compiler-next` salvo indicación contraria.
Los bloques siguientes son reproducibles hoy. La selección con `find` es una
transición explícita; el plan de implementación elimina esa dependencia de
nombres mediante un manifest versionado.

### 6.1 Compiler Core

Ejecuta unit tests de las capas y los integration tests que prueban
verificadores/ownership/backend mínimo:

```bash
cargo test -p aether-frontend --lib
cargo test -p aether-frontend --test symbol_source_mapping
cargo test -p aether-middle --lib
cargo test -p aether-backend-llvm --lib

for suite in core_v1 const_v1 ssa_store_provenance_v1 \
  borrow_ergonomics_v1 owning_struct_field_replacement_v1 \
  oop_v1 oop_v2 oop_v3 oop_opt_1; do
  cargo test -p aether-driver --test "$suite"
done
```

Dependencias: Rust 1.85+, Cargo; clang y Linux x86-64 para los casos nativos
condicionados. No necesita red, registry externo ni OAL.

Tiempo: no se midió en esta auditoría para no contaminar BITWISE-OPERATORS-V1.
Los reports no conservan un baseline agregado fiable de este subconjunto.

Riesgo: la lista focal no contiene cada verificador agregado por cada feature.
Todo cambio HIR/MIR/SSA debe sumar sus suites afectadas según la política de la
sección 9. PASS requiere exit 0 en todos los comandos. Un assertion failure,
crash o rechazo de IR válido es FAIL. Plataforma/herramienta obligatoria ausente
es BLOCKED, no PASS.

### 6.2 Language Conformance

Ejecuta Compiler Core, después todas las suites del driver excepto las de OAL y
el smoke de registry materializado, y los dos gates diferenciales oficiales:

```bash
# Ejecutar primero Compiler Core.
mapfile -t conformance_suites < <(
  find crates/aether-driver/tests -maxdepth 1 -name '*.rs' -printf '%f\n' |
    sed 's/\.rs$//' |
    grep -Ev '^(linear_algebra_.*|graphics_.*|plots_.*|registry_materialization_v1|cli_v1_api|managed_tool_build_v1)$' |
    sort
)
for suite in "${conformance_suites[@]}"; do
  cargo test -p aether-driver --test "$suite"
done
bash tests/test-differential-harness.sh
bash tests/run-differential.sh
```

El filtro excluye responsabilidades OAL, registry y CLI/packaging, no “tests
lentos”. `vertical`, traps, errores, STD y pares O0/O2 permanecen incluidos.
Mientras BITWISE esté sólo en el working tree, su suite aparece en la selección
pero su resultado no debe presentarse como baseline del repositorio.

Dependencias: las de Core, filesystem temporal y capacidad de ejecutar
artefactos nativos. No necesita Internet ni compilador legacy.

Tiempo: no medido como perfil; el diferencial observado históricamente completa
96 casos, pero los reports consultados no registran duración comparable. Riesgo:
la exclusión por nombre es frágil y algunos archivos mezclan assertions
internas/observables. PASS/FAIL/BLOCKED usa la misma regla que Core; una
divergencia O0/O2, diagnostic ID incorrecto o trap ausente es FAIL.

### 6.3 OAL Integration

Ejecuta las suites de las tres OAL, el cruce CAS/import, package management y
registry, incluido el consumer QR real:

```bash
for suite in $(
  find crates/aether-driver/tests -maxdepth 1 \
    \( -name 'linear_algebra_*.rs' -o -name 'graphics_*.rs' -o -name 'plots_*.rs' \) \
    -printf '%f\n' | sed 's/\.rs$//' | sort
); do
  cargo test -p aether-driver --test "$suite"
done
cargo test -p aether-driver --test registry_materialization_v1
cargo test -p aether-package
cargo test -p aether-registry --test registry -j 1
```

Dependencias: Core compiler, clang/Linux para nativo, filesystem temporal y
espacio para CAS/builds. Los clientes de tests son locales/in-process; el caso
QR no requiere Internet público.

Tiempo observado: el test QR solo terminó normalmente en 698,68–724,36 s en
varios reports cercanos y en 951,74–1.094,48 s en revisiones con closures; otros
runs documentaron 960,04–1.083,20 s. El consumer monolítico fue estimado en
aprox. 3:20 para O0 y 5:00 para O2. Es por amplia diferencia el caso conocido
más lento.

Riesgos: oráculos y goldens pueden fallar por defectos de librería sin implicar
una regresión del lenguaje; a la inversa, OAL detecta combinaciones genéricas,
ownership y escala que los fixtures pequeños no ejercitan. PASS requiere todos
los tests. Un fallo reproducible es FAIL del perfil y debe triagearse por dueño.
Timeout sin diagnóstico suficiente es BLOCKED; jamás PASS.

### 6.4 Full Ecosystem

Ejecuta literalmente todo el workspace sin exclusiones y los gates oficiales
externos a Cargo:

```bash
cargo test --workspace -j 1 --no-fail-fast
bash tests/test-differential-harness.sh
bash tests/run-differential.sh
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
```

`-j 1` favorece reproducibilidad y permite atribuir la cola larga; no excluye
nada. Se recomienda un presupuesto global mínimo de 2.400 s y uno individual de
1.500 s para QR hasta disponer de telemetría por suite. Un límite universal de
300 s es inválido para el baseline conocido.

Dependencias: unión de los otros perfiles más toolchain de lint/formato y
plataformas soportadas. Tiempo: el total no fue medido aquí; la cola QR por sí
sola suele requerir 12–18 minutos. PASS sólo si todos los comandos terminan en
0. Un timeout deja Full Ecosystem BLOCKED/incompleto. No se puede inferir PASS
porque todo lo anterior al timeout estaba verde.

## 7. Qué aporta OAL y qué es exclusivamente librería

Cobertura de compilador difícil de sustituir hoy:

- monomorfización y lowering de grandes cuerpos genéricos con tipos concretos;
- owners, views, strides, empty extents, unwind y budgets de allocations en
  algoritmos reales;
- estabilidad de O0/O2 y ausencia de dispatch/residuos genéricos en IR;
- closures/invocables cruzando packages (`plots`), composición
  plots → graphics y ejecución de consumers;
- stress de frontend y backend por el gran módulo `linearAlgebra`.

Cobertura predominantemente de librería:

- exactitud QR/LU/Cholesky/SVD/eigen y comparación con NumPy/LAPACK;
- políticas numéricas propias de OAL, API/surface guards y orden de kernels;
- serialización SVG, estilo, ticks y goldens gráficos;
- detalles de algoritmos, budgets y helpers privados que no forman parte del
  contrato general del lenguaje.

Smokes de compatibilidad recomendados:

- `linear_algebra_constructors_v1` y `linear_algebra_qr_v1` para generics,
  filled init, ownership y lowering;
- `graphics_foundation_v1::public_consumer_runs_at_o0_and_o2` para consumer y
  lifecycle;
- `plots_invocable_integration_v1` para closures borrowed e imports;
- `registry_materialization_v1` para CAS → import → check O0/O2;
- `publish_add_sync_run_locked_then_update_end_to_end` para flujo registry
  pequeño.

Estos smokes se agregan a un milestone sólo cuando su superficie puede verse
afectada; no convierten todo OAL Integration en bloqueo universal.

## 8. Caso registry QR

`linear_algebra_oal_publishes_and_runs_real_qr_consumer` verifica, en una única
prueba:

1. construcción determinista del archive `linearAlgebra@0.1.0` y allowlist de
   `aether.toml` + `src/lib.ae`;
2. publicación autenticada en `RegistryStore` local;
3. metadata `official`;
4. creación de un consumidor independiente;
5. `add`, modificación del manifest, resolución, `sync`, CAS/materialización y
   lock;
6. resolución de `import linearAlgebra` desde el package materializado;
7. compilación y ejecución del consumer QR real en O0 y O2.

Clasificación primaria: **OAL Integration / Full Ecosystem end-to-end**.
Clasificaciones secundarias: registry/package compatibility y smoke de
compiler/runtime a gran escala. No es Compiler Core ni debería bloquear por
defecto un milestone de lexer, parser u operador aislado.

Está dentro de la qualification global porque `aether-registry` es miembro del
workspace y `cargo test --workspace` ejecuta todos sus integration tests. No
existe hoy un gate global con taxonomía; la pertenencia al crate produce esa
inclusión accidental.

Los timeouts preexistentes de 15, 30, 60, 240 y 300 s no demuestran deadlock:
hay evidencia posterior de tres ejecuciones cercanas a 699–702 s, CPU sostenida
99,4–99,7%, RSS estable y finalización normal. Aun así, un run interrumpido debe
registrarse como BLOCKED/incompleto, nunca PASS. Esta auditoría no intenta
optimizar ni reparar el caso.

## 9. Política por tipo de cambio

Leyenda: **M** obligatorio para cierre; **R** recomendado/focal según impacto;
**P** periódico (nightly/pre-release); `—` no requerido por defecto.

| Cambio | Core | Conformance | OAL | Full | Suites adicionales mínimas |
| --- | :---: | :---: | :---: | :---: | --- |
| Lexer/parser/AST | M | M | R | P | suite de sintaxis afectada; OAL smoke si cambia gramática usada por packages grandes |
| HIR/MIR/SSA/tipos | M | M | R | P | corrupciones/verificadores afectados; OAL genérico/ownership relevante |
| Ownership/closures/OOP | M | M | R | P | OOP V1–V3, opt, unwind; plots invocables y linear ownership si toca carriers |
| LLVM/backend/runtime | M | M | R | P | pares O0/O2; OAL smoke o QR si cambia ABI/helpers/optimización usados |
| STD | M | M | R | P | suite STD afectada y consumers de OAL que importen esa superficie |
| OAL fuente/API | R | R | M | R | suites de la librería y consumers dependientes |
| Registry/package | — | R | M | R | package resolution/cache/publish, materialización y e2e pequeño; QR si afecta publicación/consumo OAL |
| CLI/packaging | — | R | R | M para release | bootstrap/API, publish y consumer real según comando alterado |

Full Ecosystem es obligatorio además para releases, cambios transversales de
workspace/manifests/toolchain y antes de declarar estable un nuevo perfil. En
CI periódico debe correr aunque ningún milestone lo use como gate de cierre.

Reglas de escalamiento OAL para cambios del compilador:

- imports, visibilidad, packages o monomorfización → linear/plots consumers;
- ownership, views, generics, exceptions o closures → las suites OAL que usan el
  carrier afectado;
- LLVM, ABI, ARC, unwind, math helpers u O2 → al menos un consumer OAL O0/O2;
- matrices, shapes, capabilities numéricas o IEEE → linearAlgebra focal;
- file/format/XML/string runtime → graphics/plots focal;
- registry/CAS/lock/publication → e2e pequeño obligatorio y QR recomendado o
  obligatorio si cambia el archive/materialización/import de una OAL.

## 10. PASS, FAIL, BLOCKED y timeouts

- **PASS**: todos los comandos obligatorios del perfil terminaron y todas las
  expectativas se cumplieron.
- **FAIL**: assertion, diagnostic ID, status, trap, golden, verifier, crash o
  lint obligatorio incumplido. Un fallo preexistente sigue siendo FAIL del
  perfil, aunque pueda no ser atribuible al milestone.
- **BLOCKED**: el perfil no pudo concluir por infraestructura ausente, plataforma
  no disponible o timeout sin resultado. BLOCKED no equivale a FAIL del cambio
  ni a PASS del perfil.

Para permitir el cierre de un milestone con un problema preexistente fuera de
su gate obligatorio se exige: reproducción en baseline/base limpia, prueba sin
cambios en esa superficie, resultado focal obligatorio PASS, dueño/seguimiento
explícito y lenguaje documental “perfil BLOCKED”, nunca “workspace PASS”. Si el
cambio toca la superficie fallida, la excepción deja de ser aplicable.

Los timeouts futuros deben ser por suite/test, registrar fase, CPU, RSS, último
progreso y duración, y matar el árbol de procesos completo. Para QR se adopta
provisionalmente 1.500 s. Silencio de stdout no es hang; CPU sostenida y avance
de O0 a O2 son progreso.

## 11. Plan mínimo de implementación futuro

Sin implementarlo en esta fase:

1. crear `compiler-next/tests/qualification.toml` con cada test binary/script,
   perfiles, responsabilidades, plataforma, O0/O2, timeout y owner;
2. crear un único `tests/qualify.sh <core|conformance|oal|full>` que valide el
   manifest, liste el plan y produzca JSON/JUnit con tiempos;
3. hacer que `full` ejecute `cargo test --workspace` literalmente; el manifest
   no puede ocultar tests nuevos del workspace;
4. agregar una verificación que falle si aparece un integration test Rust sin
   clasificación;
5. dividir sólo las suites verdaderamente mixtas cuando se necesite selección
   estable por responsabilidad, sin eliminar assertions;
6. conservar `run-differential.sh` como autoridad normativa e invocarlo desde
   Conformance y Full;
7. mantener smokes cruzados explícitos y ejecutar OAL/Full periódicamente;
8. guardar baselines de duración por plataforma y alertar por regresión, sin
   convertir automáticamente lentitud en defecto semántico.

La implementación debe aterrizar en un milestone separado. Esta arquitectura no
autoriza cambios a scripts, tests o manifests actuales.
