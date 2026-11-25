# Aether — INDEX-DEREFERENCE-DIAGNOSTIC-V1 — Reporte

Estado: **CLOSED**, 2026-11-23.

> Enmienda posterior: la integración con el refinamiento de referencias
> nullable reveló que el type probe inicial de F2 observaba sólo el tipo
> declarado del `Place`. La corrección, qualification y estado actualizado se
> documentan en
> [INDEX_DEREFERENCE_DIAGNOSTIC_V1_AMENDMENT_1_REPORT.md](INDEX_DEREFERENCE_DIAGNOSTIC_V1_AMENDMENT_1_REPORT.md).
> Este reporte conserva el historial del cierre original.

## 1. Resultado

`*lines[0]`, cuando `lines` es `List<string>`, continúa siendo inválido pero
ahora falla con E0271. No se admitió ningún programa nuevo y no se modificaron
borrowing, indexing, ownership, sintaxis, APIs ni los IR posteriores al HIR.

Diagnóstico anterior:

```text
error[E0293] (semantic): partial move of non-Copy field `string` is unsupported
```

Diagnóstico nuevo:

```text
error[E0271] (semantic): cannot dereference expression of type `string`: `*` requires `ref T` or `ref mut T`; `*` does not create a borrow
```

No se hizo commit ni push.

## 2. Preflight y preservación

HEAD inspeccionado:

```text
3c5c451854cbddb2d5296ed1873ae837a5e03908
```

El árbol ya contenía cambios pendientes de `OWNING-COLLECTION-FIELDS-V1`,
incluidos `compiler-next/crates/aether-middle/src/ssa.rs`, su suite y sus
reportes, además de ejemplos y programas de assessment. Se preservaron sin
modificación intencional. Este milestone no cambió SSA, MIR, LLVM, runtime,
STD, OAL ni programas del assessment.

Se inspeccionaron:

- `OWNING_COLLECTION_FIELDS_ARCH_1.md` y su reporte;
- `hir.rs`, `resolve_expr_place`, `load_place` y la resolución de `Place`;
- los diagnósticos E0271/E0293 existentes;
- Borrow Ergonomics, indexing de `Array`/`List`, iteración `ref` y Text.

## 3. Causa raíz

El AST del argumento conserva la forma correcta:

```text
Unary(Dereference)
└── Index
    ├── Name(lines)
    └── Integer(0)
```

La rama `resolve_expr_place(Dereference(operand))` evaluaba primero el operando
con `expression(operand, None)`. Para `lines[0]`, `expression(Index)` resolvía el
`Place` indexado y llamaba inmediatamente a `load_place`. Como el elemento era
`string`, non-Copy, `load_place` emitía E0293 antes de que Dereference pudiera
consultar `reference_info` y detectar el error semántico primario.

Por tanto E0293 no provenía de una regla de dereference ni de borrowing: era el
efecto secundario de materializar prematuramente un `Place` owning como valor.

## 4. Cambio preciso

La resolución de `Dereference(operand)` distingue ahora dos caminos:

1. Si el operando denota un `Place`, resuelve el `HirPlace` e inspecciona
   directamente `place.ty`, sin load owning.
2. Si ese tipo no tiene `reference_info`, emite E0271 sobre el span de la
   expresión de dereference completa.
3. Si es `ref T` o `ref mut T`, construye el mismo valor de referencia que el
   camino anterior y conserva la validación de mutabilidad E0272.
4. Si el operando no es un `Place`, conserva `expression(operand, None)` y la
   evaluación normal previa.

La detección de operandos Place sólo reconoce roots locales, el storage de
class que `resolve_expr_place` ya admite y sus proyecciones `Field`/`Index`,
además de dereferences reales. No captura E0293 ni reescribe diagnósticos ya
emitidos. Tampoco agrega auto-deref, implicit borrow, clone o move-out.

No se añadió una sugerencia específica de `std.Text.trim(lines[0])` o
`std.Text.trim(&lines[0])`: en este nivel la resolución de Dereference no
conserva el contexto de firma/call argument necesario para hacerla
inequívocamente machine-applicable. Añadirlo habría requerido expandir el
sistema de diagnósticos contextuales. Las dos formas correctas están cubiertas
positivamente.

## 5. Source spans

El test del reproducer comprueba que el span primario corta exactamente:

```text
*lines[0]
```

El span no se reduce al índice ni se desplaza al call exterior. Los negativos
adicionales también exigen un span presente.

## 6. Qualification positiva

Una qualification nativa combinada se compiló y ejecutó con retorno 0 en O0 y
O2. Cubre:

- borrow contextual `std.Text.trim(lines[0])`;
- borrow explícito `std.Text.trim(&lines[0])`;
- borrow indexado de `Array<string>`;
- borrow de string almacenado en struct;
- borrow de string local;
- iteración `for (ref string item in lines)`;
- dereference real de `ref string`;
- elemento Copy indexado de `List<int>`;
- import y operaciones de `std.Text`.

La qualification exige presencia de `Borrow` en HIR/MIR/SSA, `EndBorrow` en
MIR/SSA, Dereference en HIR y ausencia de `Clone` en HIR. Por construcción, el
camino válido de un local referencia conserva `HirExprKind::Local`; los Places
proyectados de referencia conservan su load Copy y los operandos no-Place
conservan `expression`. No cambió el lowering HIR/MIR/SSA/LLVM.

## 7. Qualification negativa

| Caso | Resultado |
|---|---|
| `*lines[0]`, elemento `string` | E0271 |
| `*numbers[0]`, elemento `int64` | E0271 |
| `*number()`, operando no-Place | E0271, evaluación normal |
| move real `string value = lines[0]` | E0293 |
| borrow indexado que escapa | E0273 |
| `push` con borrow indexado vivo | E0313 |
| reutilización de colección owning movida | E0291 |

Las suites existentes también conservaron E0291/E0292/E0293 y las reglas de
growth/invalidation. No se observó implicit clone ni move-out parcial nuevo.

## 8. Gates

Ejecutados y aprobados:

- test nuevo `index_dereference_diagnostic_v1`: 4/4;
- `cargo test -p aether-frontend -j 1`: 98/98;
- `borrow_ergonomics_v1`: 8/8;
- `vertical9_reference_diagnostics_fail_closed`;
- `vertical11_aggregate_ownership_diagnostics_fail_closed`;
- `vertical14_list_diagnostics_fail_closed`;
- `vertical21_collections_keep_zero_based_indices`;
- `iteration_v3`: 6/6;
- `text_v1`: 8/8;
- `owning_collection_fields_v1`: 6/6, incluida qualification O0/O2 y ASan;
- `cargo check --workspace`;
- `cargo fmt --all --check`;
- `cargo clippy --workspace --all-targets -j 1`;
- `git diff --check`.

Clippy finalizó con warnings existentes fuera de este cambio: tamaño de
`HirStmtKind`, warnings en SSA/F1 y suites previas. No emitió warnings para el
nuevo código o test.

`cargo test --workspace -j 1` se omitió: el cambio está limitado a la rama
Dereference del frontend, no toca rutas compartidas fuera de ella y las suites
focales no mostraron regresión transversal.

## 9. Archivos del milestone

- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-driver/tests/index_dereference_diagnostic_v1.rs`;
- `docs/architecture/INDEX_DEREFERENCE_DIAGNOSTIC_V1_REPORT.md`.

## 10. Cierre

INDEX-DEREFERENCE-DIAGNOSTIC-V1 queda **CLOSED**: el conjunto de programas
válidos no cambió; sólo mejoró la prioridad y precisión causal del diagnóstico
para dereference de un Place cuyo tipo no es referencia.
