# Aether — COMPOUND-ASSIGNMENT-V1 — Reporte de implementación

Estado: **CLOSED**

Fecha: 2026-11-27

Autoridad: `compiler-next`; base inspeccionada `5e1360694c65`.

## 1. Contrato implementado

Se implementaron los cinco tokens y su forma exclusivamente statement:
`+=`, `-=`, `*=`, `/=` y `%=`. Se conservó `=` sin cambiar su orden vigente.
Los destinos implementados son escalares numéricos built-in, incluidos aliases
transparentes, y el RHS se tipa exactamente contra el tipo del destino. `%=`
rechaza floats. No se habilitaron String, owners, genéricos, `++`, `--`, bitwise
ni potenciación.

El milestone queda cerrado con la alternativa nominal dedicada para fields
escalares de class y con reconstrucción independiente de identidad, lifetime y
efectos en HIR/MIR/SSA, sin ampliar la superficie OOP ni el modelo ARC.

## 2. Cambios por capa

- Lexer: maximal munch para los cinco tokens.
- Parser/AST: `CompoundAssign` statement-only; usos expresivos y chaining no
  forman una expresión válida.
- HIR: `HirStmtKind::CompoundAssign`, identidad estable de fuente, tipo exacto,
  operación concreta checked/IEEE y destino cerrado `Place | ClassScalarField`.
- MIR: `CompoundLoad` y `CompoundCommit` explícitos. El destino se baja antes del
  RHS y ambos extremos conservan id, tipo y destino estructural, incluido el
  receiver nominal capturado una sola vez.
- SSA: conserva ambas operaciones, comprueba cardinalidad, igualdad estructural,
  dominance y que el commit consuma un binario derivado del old cargado.
- LLVM: materializa el pointer una vez en el load, lo reutiliza en el commit y
  usa la aritmética checked/IEEE existente. Para class fields deriva el offset
  verificado del mismo `FieldId` usado por `FieldRead`/`FieldWrite`.

## 3. Riesgos y auditoría adversarial

La auditoría encontró que la implementación parcial estabilizaba operandos y
puntero, pero el frontend liberaba conceptualmente la ubicación después de
`place()` y antes de analizar el RHS. Por tanto, un pointer capturado podía cruzar
una mutación estructural admitida por las reglas ordinarias de borrows. Que el
backend reutilizara el pointer no probaba su validez.

Son expresables y quedaron cubiertos por fuente:

- mutación del mismo slot/field y de otro slot/field mediante alias (permitidas);
- `pop`, `remove` y `swap_remove` directos en el RHS (rechazados);
- `push`, `reserve`, crecimiento de Matrix, reducción o reemplazo a través de una
  llamada con `ref mut` al owner (rechazados);
- reemplazo del root mediante `ref mut` (rechazado);
- la misma exposición a través de `Function<...>`/llamada indirecta (rechazada);
- throw de una llamada RHS bajo `try/catch` (admitido, sin commit en unwind).

`push` y `reserve` son statements, no expresiones, por lo que dentro del RHS sólo
son alcanzables a través de una llamada. Bypass de protección, provenance alterada,
fin anticipado de región, store/commit insertado tras invalidación y CFG artificial
requieren corrupción MIR/SSA o fixtures internos. Los fields escalares de class
usan la identidad nominal dedicada descrita abajo.

## 4. Estrategia y estabilización de Places

La ruta genérica captura base, referencia e índices antes de `CompoundLoad`.
El pointer emitido por el backend se conserva por identidad de transacción y no
se recalculan dirección ni bounds en el commit. El orden implementado es Place,
checks/load, RHS, binario y store.

Durante el análisis de ownership, la provenance owner y, para destinos indexados,
el backing/rango del slot quedan registrados como una región viva mientras se
analiza el RHS. Se reutilizan `borrowed`, `storage_borrowed`, `storage_ranges`, la
provenance existente y una marca estrecha de owner compound protegido. La marca no
confiere exclusividad ni `noalias`: llamadas que sólo reciben `ref mut` a un escalar
siguen admitidas, incluso sobre el mismo slot.

## 5. Reconstrucción independiente de mutation effects

Sobre provenance coincidente se permiten `ElementMutation` escalares que preservan
ubicación. `StableStructuralMutation` (`pop`, `remove`, `swap_remove`) se rechaza
durante la región aunque un índice constante pareciera sobrevivir. Las llamadas
directas o indirectas con `ref mut` al List owner/backing protegido se rechazan,
cubriendo `PotentiallyRelocatingMutation`, reducción y reemplazo desconocido. Una
provenance distinta no queda bloqueada.

MIR y SSA ya no aceptan el `CompoundAssignId` como prueba de seguridad. Ambos
verificadores reconstruyen la provenance alcanzable desde la base estabilizada,
siguiendo locals/values, borrows, loads, views y phis verificables. Dentro de cada
región load--commit clasifican y rechazan conservadoramente:

- `ListPush`, `ListReserve`, `ListSetLength`, `MatrixAdd`, `Take` y `Relocate`;
- reemplazo de descriptors/owners, Move, Drop y destrucción de enum owners;
- stores a un root o path envolvente del slot protegido;
- calls directas e indirectas que reciben una referencia mutable no escalar con
  provenance coincidente; calls sin resumen suficiente fallan cerrado;
- transfer/cleanup de handles que alcance la misma provenance; una escritura
  escalar de class que preserva identidad no se confunde con invalidación;
- cualquier ciclo CFG dentro de la región protegida, evitando que load, RHS o
  efectos puedan repetirse antes del commit.

Los stores escalares a slots que preservan ubicación siguen siendo
`ElementMutation` y no se introduce exclusividad ni `noalias`. Este cierre es
deliberadamente conservador y no constituye MemorySSA ni análisis global de alias.

## 6. Cobertura de destinos

Cubiertos por tests de compilación: local, field de struct, field escalar de class,
Array, List, Buffer, Vector, Matrix, ViewMut, `ref mut` y proyecciones escalares.
La ruta de class conserva
`ClassScalarField { receiver, class, field, field_type, mutable, initialized }` y
cubre field propio/heredado accesible, `this`, acceso externo público y método
`mut`; rechaza receiver read-only, privado inaccesible y no inicializado. La
representación `ClassField` del Place genérico sigue reservada para storage
interior indexable y no fue falseada.

## 7. Aliasing y evidencia de estabilidad

El old se captura antes del RHS y el commit final usa ese valor. Tests positivos
demuestran que una llamada puede escribir el mismo elemento/field o uno distinto
sin invalidar la ubicación; el resultado usa el old capturado y el commit final
gana. El receiver permanece como operando vivo del load al commit, de modo que ARC
ubica su última liberación después de la transacción sin retain/release duplicado.
No se asume `noalias` para `ref mut` ni receivers de class.

## 8. Excepciones y traps

Los traps enteros, división/remainder y IEEE float reutilizan el plan binario
ordinario. El commit se emite después del binario, por lo que overflow, división
por cero, conversion trap o unwind previo no publican el resultado compuesto.
No hay rollback de efectos ya ejecutados por el RHS.

MIR y SSA recorren ahora el CFG desde cada `CompoundLoad`: todo path normal debe
alcanzar su `CompoundCommit`, los paths de trap/throw pueden terminar sin commit y
un unwind de una instrucción intermedia no puede volver a alcanzar el commit. Un
test con throw/catch conserva exactamente un commit en la continuación normal.

## 9. Verificadores, CFG y corpus adversarial

HIR reconstruye tipo, writability y operación admitida; ownership vuelve a derivar
la provenance protegida desde el Place, sin aceptar metadata. MIR y SSA rechazan
load o commit duplicado/faltante, mismatch de id/destino/tipo, orden invertido, un
commit cuyo operando no derive del old, bypass normal del commit y exception edges
que reingresen al commit. SSA agrega dominance.

El corpus interno corrompe HIR, MIR y SSA después del frontend. Cubre identidad y
tipo HIR alterados; ClassId, FieldId, tipo, mutabilidad, inicialización y receiver
de class alterados; destino o índice distinto; load/commit duplicado o ausente;
commit anticipado; bypass de commit en un branch normal; resultado no derivado del
old; y una transformación posterior que mueve un `reserve` y su store de descriptor
dentro de la región. Cada caso
demuestra rechazo del verificador de esa capa. Los tests de excepciones cubren RHS
normal y RHS con throw/catch, y los recorridos MIR/SSA rechazan bypass normal,
unwind que reingresa al commit y ciclos/joins que puedan repetir la región.

No existe metadata de protección que una corrupción pueda omitir o terminar
temprano: la región se reconstruye obligatoriamente desde el único
`CompoundLoad` hasta el único `CompoundCommit`. Alterar ese orden, cardinalidad o
CFG invalida la IR.

## 10. Qualification

Ejecutado durante esta entrega de cierre de seguridad:

- suite focal `compound_assignment_v1`: **16 passed**, incluidas ejecuciones
  nativas genérica y de class fields, aliasing, invalidaciones y throw del RHS;
- corrupción dedicada de class fields HIR/MIR/SSA: **PASS**;
- `cargo check --workspace`: **PASS**;
- `cargo test --workspace -j 1 --no-fail-fast`: **no se registra como PASS**.
  Una corrida previa alcanzó todas las suites verdes hasta el hang de registry;
  la repetición actual fue limitada a 240 s y terminó por timeout mientras las
  suites largas de álgebra lineal continuaban verdes, antes de registry;
- doc-tests completos del workspace: **PASS**;
- `cargo fmt --all --check`: **PASS**;
- `cargo clippy --workspace --all-targets -j 1`: **PASS con warnings**. Los
  warnings abarcan lints históricos del workspace y algunos lints estilísticos
  no bloqueantes en los visitantes/verificadores tocados; no hubo error de
  Clippy;
- harness diferencial: **PASS**;
- diferencial oficial: **PASS, 96 checked, 0 failures**;
- ASan+UBSan focal sobre compound indexado y class field: **PASS** con clang en
  Linux x86_64;
- `git diff --check`: **PASS**.

O1/O3 no se incorporaron: la CLI productiva conserva únicamente O0/O2. El único
impedimento del gate global queda formalmente clasificado abajo.

## 11. Diagnóstico de registry y riesgos residuales

El test
`aether-registry::linear_algebra_oal_publishes_and_runs_real_qr_consumer` se
reprodujo individualmente en el working tree: timeout de 15 s, exit 124, después
de iniciar el único test. Una exportación limpia de `5e136069` creada en `/tmp`
con `git archive` reprodujo el mismo bloqueo por más de 60 s y terminó con exit
124. El fixture usa RegistryStore/RegistryCache locales y
`DriverRequest::RunProject`; no depende de red ni servicios externos.
Clasificación: **problema preexistente confirmado**, no regresión atribuible a
compound assignment. No se modificó, eliminó ni deshabilitó registry/OAL.

Como riesgo residual, se rechaza conservadoramente
`pop/remove/swap_remove` sobre la provenance protegida incluso cuando índices
constantes podrían demostrar que el slot capturado sobrevive; también se rechaza
toda llamada con `ref mut List<T>` coincidente aunque su implementación concreta no
mute estructuralmente. Estos son falsos positivos intencionales.

El impedimento de qualification global queda formalmente clasificado con
comparación contra el commit base. No queda una obligación funcional normativa
pendiente de COMPOUND-ASSIGNMENT-V1.

## 12. Rendimiento

Cada statement agrega un load y un store escalares, más la misma operación y los
mismos checks del binario ordinario. Base e índices se evalúan una vez. No se
agregó runtime, helper aritmético ni copia owning. La metadata de identidad se
elimina después de verificación y no tiene representación runtime.

## 13. Archivos del milestone

- frontend: `ast.rs`, `lexer.rs`, `parser.rs`, `hir.rs`, `hir/classes.rs`,
  `lib.rs`;
- middle/backend: `mir.rs`, `ssa.rs`, `aether-middle/src/lib.rs`,
  `aether-backend-llvm/src/lib.rs`;
- qualification: `compound_assignment_v1.rs` y los dos programas fuente
  `compound_assignment*_v1.ae`;
- contratos: este reporte y `AETHER_V1_SEMANTIC_CONTRACT.md`, además de los
  documentos de arquitectura ya abiertos por el milestone.

## 14. Commit sugerido

`feat(compiler-next): close numeric compound assignment for class fields`
