# OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1 — Amendment 1 report

Estado: **REVISIÓN DOCUMENTAL COMPLETADA; QUALIFICATION TODAVÍA ABIERTA**,
2026-10-28.

Documento normativo:
[OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1-AMENDMENT-1](OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1_AMENDMENT_1.md).
No se declara `OWNING-STRUCT-FIELD-REPLACEMENT-V1` CLOSED.

## Resultado ejecutivo

La exigencia original mezclaba dos objetivos distintos: seguridad de los
programas que V1 admite y reconstrucción general de non-lexical lifetimes. La
revisión del contrato y de los verificadores muestra que el segundo no es
necesario para el primero. El perfil vigente puede ser seguro mediante regiones
léxicas conservadoras, cierres explícitos ya representados, owner provenance y
`may_borrow_storage_of`, siempre que las capas fallen cerradas y se completen
las pruebas pendientes. No se encontró una ruta concreta ya demostrada que
permita usar después del commit una referencia al backing destruido; si una
prueba futura la encuentra, continúa siendo bloqueo de seguridad.

La matriz original también exigía handles class/interface dentro de structs,
pero el contrato global los rechaza transitivamente con E0274. Ampliar storage
para satisfacer una prueba de ReplaceOwned sería un cambio de lenguaje ajeno a
este milestone. La enmienda convierte esos casos en negativos normativos y
limita los positivos a tipos concretos ya Storable, Relocatable, non-Copy y
drop-needing.

`SSA-STORE-PROVENANCE-V1` está CLOSED y se adopta como baseline. El bypass de
Store owning sobre dereference ya no figura como trabajo abierto; sus tests se
mantienen como regresión.

## Evidencia revisada

### Borrow y alias

- El contrato V9 hace las referencias no owning, no retornables, no
  almacenables, single-initialization y conservadoramente léxicas. `ref mut`
  concede escritura, no exclusividad ni `noalias`.
- Owner analysis impide reemplazar un root local mientras permanece vivo un
  borrow/view derivado.
- MIR/SSA ya representan cierres verificables para call/format borrows; los
  scopes de iteration tienen protección delimitada. Esos casos no necesitan
  inferencia de “último uso”.
- `TypeArena::may_borrow_storage_of` compara referencia/view contra la
  topología de storage del owner y recorre aggregates, nullable y elementos de
  Buffer/Array/List/Vector/Matrix. HIR, MIR y SSA usan la consulta al verificar
  replacement por parámetro.
- El reproducer histórico `ref mut Buffer<int>` junto a `ref int` del mismo
  backing reveló un bypass real y ahora se rechaza. La regla también rechaza
  conservadoramente callers observados como disjuntos cuando la firma no
  expresa esa disjointness.

El análisis actual no prueba todavía toda la qualification enmendada. Faltan
casos dedicados de reborrow/copia de referencia y control flow, y corrupciones
de metadata Begin/End. Esta carencia es una deuda de prueba; sólo vuelve a ser
de arquitectura si aparece un programa admitido cuya procedencia no pueda
representarse de forma conservadora.

### Tipos y Drop

La autoridad central mantiene separadas `Copy`, `Relocatable`, `Storable` y
`needs_drop`; sólo `Copy => Relocatable`. Un bound `T: Storable` no prueba Drop
ni relocation y por ello no autoriza ReplaceOwned simbólico. Las instancias
concretas sustituidas sí pueden calificarse por su `TypeId` y drop glue.

Los positivos existentes cubren Buffer, Array, List, Vector, Matrix, aggregate
owning y generic instance concreta. `string` usa `ReplaceString`, no la
operación general. Los tests existentes confirman E0274 para class/interface
fields en structs. No hay base técnica para cambiar esas reglas globales en
esta tarea.

### Ownership y SSA

La implementación conserva una operación explícita en HIR/MIR/SSA, materializa
RHS antes del commit, publica new antes de Drop(old), consume RHS una vez y no
transiciona el root drop flag. Las pruebas actuales cubren exceptions,
siblings, consecutive replacement, O0/O2 y varias corrupciones.

El milestone SSA cerrado agrega provenance cerrada y un ledger reconstruido.
Un dereference Store sólo puede ser Copy o un descriptor commit tipado; un
Store no puede falsificar ReplaceOwned cambiando su etiqueta. El reporte CLOSED
incluye corrupción de provenance, producer/value/place, commit duplicado y
Drop de RootTransfer omitido/reordenado.

## Qualification efectiva tras la enmienda

| Área | Evidencia actual | Estado para cierre |
|---|---|---|
| operación HIR/MIR/SSA distinta | tests dedicados existentes | PASS heredado; rerun final requerido |
| Store provenance | milestone y suite CLOSED | BASELINE PASS; regresión obligatoria |
| Buffer direct/nested/ref mut | native O0/O2 y dumps | PASS heredado |
| Array/List/Vector/Matrix | positivos O0/O2 | PASS heredado |
| aggregate/generic concreto y siblings | positivos existentes | PASS heredado |
| class/interface fields | E0274 en tests | PASS como negativo; fuera de matriz positiva |
| symbolic `T: Storable` | no hay Drop positivo | rechazo requerido; ampliar prueba dedicada |
| RHS throw/post-commit throw | test O0/O2 | PASS heredado |
| alias de element/view por parámetro | negativos por storage family | PASS heredado |
| owner local distinto | positivo existente | PASS heredado |
| reborrow/copia/CFG joins | cobertura dedicada no demostrada | PENDIENTE |
| FieldId/root drop flag/duplicate consume | corruption dedicada incompleta | PENDIENTE |
| lifecycle por identidad | sólo counters agregados e inspección LLVM | PENDIENTE, indispensable |
| backend omit/duplicate/reorder Drop | store-before-drop estático, sin mutation harness por identidad | PENDIENTE |

Esta tabla no proclama resultados nuevos: resume evidencia documentada por los
reportes existentes y marca explícitamente lo que debe volverse a ejecutar o
agregar para el cierre.

## Instrumentación: mínimo frente a observabilidad

Los contadores agregados prueban balance global, pero pueden ocultar que se
destruyó la identidad equivocada, que un sibling fue reemplazado o que dos
errores se compensaron. Por eso la identidad de `v0`, `v1`, `v2`, temporales y
siblings es indispensable para la secuencia publish/drop y exceptions.

No se necesita convertir todo drop glue en una API observable ni instrumentar
ARC de class/interface handles prohibidos en structs. Tampoco es requisito un
contador productivo de commits. Hooks sólo de test o un ledger del harness son
suficientes si detectan omisión, duplicación, reordenamiento y cambio de
identidad en O0/O2.

## Gates revisados sin falsear estado

La última evidencia registrada es:

- `owning_struct_field_replacement_v1`: **12/12 PASS**;
- `ssa_store_provenance_v1`: **5/5 PASS**;
- frontend/middle y vertical: **PASS**;
- `cargo test --workspace`: **PASS** en el reporte CLOSED de SSA;
- `cargo fmt --check`: **PASS**;
- repository `git diff --check`: **PASS**;
- Clippy con `-D warnings`: **FAIL preexistente** por `assert_is_empty` y
  `needless_borrows_for_generic_args` en frontend.

Clippy no se renombra PASS. La enmienda permite clasificar ese resultado como
problema preexistente de tooling, separado de regresiones introducidas, si el
rerun final demuestra la misma atribución y el alcance modificado queda limpio.
Una dependencia o toolchain ausente se registrará como `BLOCKED`/`NOT RUN`, no
como éxito. Ningún archivo ajeno debe editarse para alterar esas etiquetas.

## Lista concreta pendiente para CLOSED

1. Agregar positivos/negativos de borrow del RHS con End explícito y negativos
   de referencia léxica cuyo último uso ocurrió pero cuyo scope sigue abierto.
2. Agregar reborrow y copia de referencia/view desde local y parámetro, con
   branches, joins y uso posterior al replacement/End.
3. Corromper independientemente FieldId/proyección HIR, root drop flag MIR,
   consumo RHS omitido/duplicado MIR/SSA y metadata de región/End MIR/SSA.
4. Agregar eventos por identidad para consecutive replacements, siblings,
   RHS throw y final cleanup, comparados en O0/O2.
5. Hacer que el harness detecte backend old-Drop omitido, duplicado o anterior
   a publish; conservar además la inspección LLVM store-before-drop.
6. Completar el negativo paramétrico `T: Storable` y las propiedades
   concrete/Storable/Relocatable/needs-drop corruptas.
7. Reejecutar suites dedicadas, SSA baseline, ownership, collections,
   exceptions/finally, classes/interfaces, optimization, vertical, workspace,
   fmt, Clippy y `git diff --check`, clasificando cada resultado según la
   enmienda.
8. Actualizar el contrato global y el reporte final con la evidencia obtenida,
   sin declarar otros milestones cerrados por transitividad.

## Archivos y alcance

Esta tarea creó únicamente:

- `docs/architecture/OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1_AMENDMENT_1.md`;
- `docs/architecture/OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1_AMENDMENT_1_REPORT.md`.

No se modificó código productivo, tests, Graphics, SVG, Plots, ejemplos del
usuario ni documentación no relacionada. No se hizo commit ni push.
