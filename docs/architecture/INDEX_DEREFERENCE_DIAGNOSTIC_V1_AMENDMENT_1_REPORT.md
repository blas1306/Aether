# Aether — INDEX-DEREFERENCE-DIAGNOSTIC-V1-AMENDMENT-1 — Reporte

Estado: **CLOSED**, implementada 2026-11-24; cierre integrado reconciliado
2026-11-25.

La corrección y sus qualifications focales quedaron completas el 2026-11-24:
`nullable_v1` y la suite F2 pasaron simultáneamente. En esa ejecución, el gate
exacto obligatorio `cargo test --workspace -j 1` abortó más adelante en un test
independiente por agotamiento de stack; por esa razón el estado original fue
**PARTIAL**. El fallo fue aislado también con F2 anterior a esta enmienda y no
se oculta ni se reclasifica retroactivamente como PASS.

Posteriormente, `FRONTEND-STACK-USAGE-V1` corrigió la recursión de la espina
lógica que causaba el agotamiento. Su qualification integrada ejecutó el mismo
gate completo, sin `RUST_MIN_STACK`, y obtuvo PASS. Esa evidencia posterior
satisface el requisito de cierre pendiente; la distinción temporal se conserva
en la sección 8.

No se hizo commit ni push.

## 1. Regresión encontrada

F2 corrigió correctamente la prioridad diagnóstica de `*lines[0]`, evitando el
load owning que producía E0293 y emitiendo E0271. Sin embargo, para todo
operando con forma de `Place` consultaba inmediatamente `place.ty`.

En el caso válido:

```aether
int read((ref int)? value) {
    if (value != null) {
        return *value;
    }
    return 0;
}
```

`place.ty` seguía siendo el tipo declarado `(ref int)?`. F2 emitía E0271 antes
de permitir que el refinamiento ya demostrado produjera el payload `ref int`.
La comparación A/B/C de `SHAPE_CONTRACT_DIAGNOSTICS_V1_REPORT.md` quedó
reproducida por el test focal original antes del cambio.

## 2. Causa exacta

Nullable V1 mantiene dos hechos separados:

- el tipo declarado/almacenado del local, que permanece `(ref int)?`;
- el estado de flujo `Unknown | Null | NonNull` del root estable.

El camino anterior a F2 ejecutaba `expression(operand, None)`. Para un nombre
nullable con estado `NonNull`, `expression` construye
`HirExprKind::NullablePayload { access: Copy, proof, ... }` y devuelve el tipo
efectivo del payload. Como `ref int` es Copy, Dereference recibía correctamente
una referencia.

F2 evitó esa evaluación para todos los `Place` a fin de no materializar
`lines[0]`, pero la inspección nominal perdió el refinamiento. La regresión no
estaba en `reference_info`, Nullable V1, MIR, SSA ni F3: ocurría durante la
resolución HIR de Dereference, antes de construir MIR.

## 3. Solución aplicada

Se agregó una query localizada `flow_refined_place_type(&HirPlace)`. Devuelve
el payload nullable sólo cuando el `Place` es exactamente un local root sin
proyecciones y su estado CLOSED existente es `NullState::NonNull`; en cualquier
otro caso devuelve `place.ty`.

La rama Dereference ahora:

1. resuelve el operando Place sin cargarlo;
2. consulta su tipo efectivo por el estado de flujo existente;
3. rechaza con E0271 si ese tipo efectivo no es referencia;
4. sólo cuando el tipo efectivo difiere del declarado reutiliza
   `expression(operand, Some(effective_type))`, que materializa el
   `NullablePayload` y su proof canónica;
5. conserva el camino F2 sin load para Places no refinados y el camino normal
   para operandos no-Place.

No se agregó un lattice, proof, cast ni mecanismo de refinamiento paralelo. La
evaluación runtime sigue siendo única. Los errores previos, spans, mutabilidad,
tipos de pointee y ownership permanecen en los caminos existentes.

## 4. Tipo declarado frente a tipo refinado

| Estado | Tipo almacenado | Tipo efectivo | Resultado de `*value` |
|---|---|---|---|
| sin proof | `(ref int)?` | `(ref int)?` | E0271 |
| rama `value != null` | `(ref int)?` | `ref int` | dereference válido |
| rama else de `value == null` | `(ref int)?` | `ref int` | dereference válido |
| después de `value = null` | `(ref int)?` | `(ref int)?` | E0271 |

El refinamiento sólo aplica al local root estable. Fields e índices no reciben
facts de Nullable V1. Además, el lenguaje vigente rechaza almacenar referencias
nullable en fields con E0274 y como elementos persistentes de `List` con E0310;
no se inventó soporte para esas combinaciones.

## 5. Conservación del E0271 original

La suite `index_dereference_diagnostic_v1` pasó 6/6. Congela:

- `*lines[0]` sobre `List<string>`: E0271 y span exacto `*lines[0]`;
- indexed Copy non-reference y resultado non-Place: E0271;
- nullable reference sin proof: E0271 con tipo `(ref int64)?`;
- proof invalidada por asignación a `null`: E0271;
- partial move owning real: E0293;
- escapes/invalidation/move reales: E0273, E0313 y E0291;
- dereference real de `ref T`, borrow contextual y explícito, sin Clone.

`List<string>[i]` continúa siendo `string`, no `ref string`. Dereference no crea
borrow y no se reintrodujo `expression(operand, None)` para todos los Places.

## 6. Qualification nullable O0/O2

`nullable_v1`: **10/10 PASS**. El caso originalmente fallido
`nullable_functions_and_references_refine_without_conflating_storage` compila y
ejecuta correctamente en O0/O2.

La regresión focal nueva ejecuta en O0/O2:

- parámetro nullable refinado en rama then;
- rama else válida de `value == null`;
- referencia nullable almacenada en local y refinada;
- presencia simultánea de `NullablePayload` y Dereference en HIR.

Los negativos cubren ausencia de proof e invalidación por escritura. La suite
nullable existente conserva invalidación por alias mutable, joins, loops,
short-circuit y rechazo de payload owning.

## 7. Qualification F2 y ownership

Resultados focales:

| Suite | Resultado |
|---|---:|
| `index_dereference_diagnostic_v1` | 6/6 PASS |
| `borrow_ergonomics_v1` | 8/8 PASS |
| `iteration_v3` | 6/6 PASS |
| `text_v1` | 8/8 PASS |
| `owning_collection_fields_v1` | 6/6 PASS, incluido ASan y O0/O2 |
| `vertical9_reference_diagnostics_fail_closed` | PASS |
| `vertical11_aggregate_ownership_diagnostics_fail_closed` | PASS |
| `vertical14_list_diagnostics_fail_closed` | PASS |
| `vertical21_collections_keep_zero_based_indices` | PASS |

Los dumps focales conservan Borrow/EndBorrow, Dereference y ausencia de Clone.
No se modificaron MIR, SSA, LLVM, runtime, STD ni OAL para esta enmienda.

## 8. Resultado completo del workspace

### 8.1 Ejecución original de esta enmienda — resultado histórico

Ejecutado desde `compiler-next`:

| Gate | Resultado |
|---|---|
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | **FAIL; no completó** |
| `cargo fmt --all --check` | PASS después de formatear el test nuevo |
| `cargo clippy --workspace --all-targets -j 1` | PASS con warnings preexistentes |
| `git diff --check` | PASS |

El test global superó el punto de fallo histórico: `nullable_v1` pasó 10/10 y
continuó por las suites posteriores. Luego abortó en:

```text
numeric_capabilities_v1::every_numeric_capability_and_alias_reifies_before_mir
fatal runtime error: stack overflow
```

El fallo se reprodujo con el test exacto. Una comparación controlada retirando
únicamente la query/camino refinado de esta enmienda, restaurando F2 previo,
produjo el mismo stack overflow. El source del test no contiene nullable ni
dereference. Con `RUST_MIN_STACK=8388608` el test exacto pasa. Por tanto el
fallo está aislado como independiente de AMENDMENT-1, pero el comando normativo
exacto no terminó y no se presenta como PASS. No se amplió el alcance para
corregir consumo de stack en monomorphization/capabilities.

### 8.2 Seguimiento posterior — cierre del bloqueo de stack

`FRONTEND-STACK-USAGE-V1` identificó que el fallo no provenía de
monomorphization numérica ni de la integración F2/Nullable. La causa era el
recorrido recursivo de cadenas `&&`/`||` por frames debug grandes en análisis,
monomorphization y lowering MIR. El milestone sustituyó esa recursión de la
espina izquierda por recorridos iterativos localizados, sin cambiar la
asociatividad del AST ni la semántica de short-circuit.

Su reporte de cierre registra, desde `compiler-next` y con `RUST_MIN_STACK`
ausente:

| Gate posterior | Resultado |
|---|---|
| test exacto `numeric_capabilities_v1::every_numeric_capability_and_alias_reifies_before_mir` | PASS O0/O2 |
| `nullable_v1` | PASS dentro de las 62 pruebas focales |
| `index_dereference_diagnostic_v1` | PASS dentro de las 62 pruebas focales |
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | **PASS; workspace completo** |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS con warnings preexistentes/no relacionados |
| `git diff --check` | PASS |

Esta tabla es una ejecución posterior, no una corrección del resultado de la
tabla 8.1. El FAIL histórico conserva su valor como evidencia de aislamiento;
el PASS posterior demuestra que el bloqueo independiente dejó de existir en el
estado integrado que incluye esta enmienda.

## 9. Archivos modificados por la enmienda

- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-driver/tests/index_dereference_diagnostic_v1.rs`;
- `docs/architecture/INDEX_DEREFERENCE_DIAGNOSTIC_V1_REPORT.md`;
- `docs/architecture/INDEX_DEREFERENCE_DIAGNOSTIC_V1_AMENDMENT_1_REPORT.md`.

Los cambios pendientes de F1, F2, F3, assessment y `examples/ProbandoNR` se
preservaron. No se usaron reset, stash, checkout, clean, commit ni push.

## 10. Compatibilidad con F3 y estado

La enmienda no toca metadata `ShapeMismatch`, reporter LLVM ni presentación
signal-aware. El gate global atravesó las suites de F3 y emitió sus diagnósticos
nativos esperados antes del fallo independiente posterior. El source lógico y
span de E0271 continúan usando el transporte F3 vigente.

La corrección de integración F2/Nullable está implementada y calificada. El
gate obligatorio que no completó en la ejecución histórica fue repetido por
`FRONTEND-STACK-USAGE-V1` después de corregir su causa independiente y pasó
completo, sin aumentar el stack mediante variables de entorno. Por tanto
**INDEX-DEREFERENCE-DIAGNOSTIC-V1-AMENDMENT-1 queda CLOSED**.
