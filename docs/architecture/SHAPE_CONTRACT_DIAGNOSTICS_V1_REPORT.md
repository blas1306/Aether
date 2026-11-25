# SHAPE-CONTRACT-DIAGNOSTICS-V1 — reporte de implementación y qualification

Estado de F3: **CLOSED**, 2026-11-24.

Excepción explícita: `cargo test --workspace -j 1` **no es PASS**. Se detiene
en un único test de `nullable_v1` que fue reproducido sin F3 aplicando sólo el
cambio local previo de INDEX-DEREFERENCE-DIAGNOSTIC-V1 (F2) sobre `HEAD`.
La independencia está demostrada en la sección 8; el fallo no fue corregido ni
su expectativa fue modificada dentro de F3.

> Seguimiento de integración, 2026-11-25: la excepción anterior se conserva
> como resultado histórico de la qualification de F3, no como PASS
> retroactivo. `INDEX-DEREFERENCE-DIAGNOSTIC-V1-AMENDMENT-1` corrigió después
> la compatibilidad F2/Nullable, y `FRONTEND-STACK-USAGE-V1` eliminó el
> agotamiento de stack independiente. En esa ejecución posterior,
> `cargo test --workspace -j 1` completó con PASS sin `RUST_MIN_STACK`. Por
> tanto la excepción ya no bloquea el workspace integrado actual.

Autoridad normativa: `SHAPE_CONTRACT_DIAGNOSTICS_ARCH_1.md`.

## 1. Preflight y preservación

Estado inspeccionado antes de la qualification:

```text
branch: main
HEAD: 3c5c451854cbddb2d5296ed1873ae837a5e03908
index: sin cambios staged
worktree: cambios tracked y untracked preexistentes
```

El worktree mezclaba tres trabajos locales no committed:

| Grupo | Cambios identificados | Preservación |
|---|---|---|
| F1, OWNING-COLLECTION-FIELDS-V1 | `aether-middle/src/ssa.rs`, suite, fixture y reportes propios | no se revirtió ni corrigió |
| F2, INDEX-DEREFERENCE-DIAGNOSTIC-V1 | rama Dereference de `aether-frontend/src/hir.rs`, suite y reporte propios | no se revirtió ni corrigió |
| F3, SHAPE-CONTRACT-DIAGNOSTICS-V1 | transporte HIR/MIR/SSA, backend, CLI y suites listadas abajo | objeto de esta qualification |
| Ajeno | `examples/ProbandoNR`, binarios/locks, assessment, `tmp_lambda_test.ae`, `probandoNR3C` y reportes de aplicación | no se modificó intencionalmente |

No se ejecutaron `reset`, `stash`, `clean`, `checkout` sobre el worktree, commit
ni push. El aislamiento histórico usó una exportación temporal de `HEAD` en
`/tmp`, con una compilación a la vez y un `CARGO_TARGET_DIR` propio.

## 2. Archivos de F3

| Archivo | Responsabilidad de F3 |
|---|---|
| `compiler-next/crates/aether-frontend/src/ast.rs` | retiene nombre lógico y texto fuente hasta análisis semántico |
| `compiler-next/crates/aether-frontend/src/parser.rs` | inicializa esa procedencia lógica |
| `compiler-next/crates/aether-frontend/src/lib.rs` | exporta los tipos internos de sitio |
| `compiler-next/crates/aether-frontend/src/hir.rs` | crea, transporta y verifica `TrapDiagnosticSite`; el mismo archivo contiene el cambio previo de F2 |
| `compiler-next/crates/aether-frontend/src/hir/mathematical.rs` | metadata propia de productos algebraicos nativos |
| `compiler-next/crates/aether-middle/src/algebraic.rs` | contrato del sitio en kernels algebraicos |
| `compiler-next/crates/aether-middle/src/mir.rs` | observaciones reutilizadas y verificación MIR |
| `compiler-next/crates/aether-middle/src/ssa.rs` | transporte/dominance/verificación SSA; el mismo archivo contiene cambios previos de F1 |
| `compiler-next/crates/aether-backend-llvm/src/lib.rs` | constantes privadas, writer, decimal y reporter antes del trap |
| `compiler-next/crates/aether-backend-llvm/src/algebraic.rs` | fail edge diagnóstico de kernels nativos |
| `compiler-next/crates/aether-cli/src/lib.rs` | presentación Unix de la señal real |
| `compiler-next/crates/aether-driver/tests/language_parity.rs` | procedencia lógica esperada en sesiones |
| `compiler-next/crates/aether-driver/tests/shape_guard_v1.rs` | ordering, IR y corrupción MIR/SSA |
| `compiler-next/crates/aether-driver/tests/shape_contract_diagnostics_v1.rs` | outputs exactos O0/O2, IR y ausencia de EH |
| `compiler-next/crates/aether-cli/tests/bootstrap.rs` | binario directo, `aether run`, señal y canales en O0/O2 |
| este reporte | evidencia de cierre |

La qualification agregó assertions, no funcionalidad productiva, para fijar
los outputs exactos de solve, dot y CLI que antes sólo se ejecutaban de forma
indirecta en otras suites.

## 3. Resultado semántico y transporte

`ShapeMismatch` sigue siendo un trap abortivo y no capturable. F3 no crea una
exception, no agrega unwind y no cambia la superficie source
`shapeGuard(bool)`.

- HIR crea un `TrapDiagnosticSiteId { function, ordinal }` y conserva operación
  source-facing, source lógico, span, línea/columna, contrato y labels.
- Para comparaciones directas de extents, MIR reutiliza exactamente los dos
  operandos que construyen el booleano. No clona ni vuelve a ejecutar `rows`,
  `columns`, `dimension` o `length`.
- SSA conserva esos operandos y verifica tipo `usize`, definición, dominance,
  owner, ordinal/provenance, correspondencia con la comparación y fail block.
- Los kernels algebraicos usan el mismo transporte con contratos de su dominio;
  la multiplicación matricial informa `columns(left) == rows(right)`.
- LLVM emite un helper `internal nounwind`, conversión decimal en stack y un
  writer length-aware a fd 2. El fail edge llama al reporter y luego conserva
  `llvm.trap` + `unreachable`.
- El happy path no llama reporter ni writer. Los programas exception-free de la
  suite no contienen `__cxa_throw`.

Las suites `condition_is_evaluated_once_and_source_order_is_preserved` y
`false_guard_precedes_later_allocation_index_division_and_call` pasaron en
O0/O2. Los tests de borrowing, ownership y exceptions listados en la sección 7
también pasaron. No se observó cambio en resolución válida de Dereference,
borrowing, ownership, evaluation order, exceptions ni traps de otros tipos.

## 4. Outputs exactos de ShapeMismatch

Cada celda `PASS Dn` significa igualdad byte a byte de stderr, stdout vacío y
terminación directa por señal 4. Los resultados O0 y O2 se probaron por
separado.

| Caso | O0 | O2 |
|---|---:|---:|
| solve, matriz no square | PASS D1 | PASS D1 |
| solve, RHS incompatible | PASS D2 | PASS D2 |
| dot incompatible | PASS D3 | PASS D3 |
| multiplicación matricial incompatible | PASS D4 | PASS D4 |
| fallback de contrato arbitrario | PASS D5 | PASS D5 |
| múltiples sitios; falla el segundo | PASS D5 | PASS D5 |

D1:

```text
Aether trap: ShapeMismatch at linearAlgebra.ae:448:5 in linearAlgebra.solve: rows(*A) == columns(*A) [rows(*A)=1, columns(*A)=2]
```

D2:

```text
Aether trap: ShapeMismatch at linearAlgebra.ae:449:5 in linearAlgebra.solve: dimension(*b) == rows(*A) [dimension(*b)=1, rows(*A)=2]
```

D3:

```text
Aether trap: ShapeMismatch at linearAlgebra.ae:48:5 in linearAlgebra.dot: length(*a) == length(*b) [length(*a)=2, length(*b)=1]
```

D4:

```text
Aether trap: ShapeMismatch at product.ae:4:21 in main: columns(left) == rows(right) [columns(left)=3, rows(right)=2]
```

D5:

```text
Aether trap: ShapeMismatch at fallback.ae:3:3 in main: 1+1==3
```

El caso D5 contiene primero `shapeGuard(true)` y después el guard que falla. La
salida corresponde al segundo sitio y LLVM conserva símbolos distintos
`aether_shape_site_0_0_prefix` y `aether_shape_site_0_1_prefix`. Ninguna salida
contiene CWD ni path absoluto.

Como cobertura adicional de captura, el test de extents fijó en O0/O2:

```text
Aether trap: ShapeMismatch at extent.ae:3:3 in main: rows(value)==columns(value) [rows(value)=2, columns(value)=3]
```

## 5. Binario directo y CLI

`bootstrap::run_reports_real_sigill_after_the_child_shape_diagnostic` se
ejecutó separadamente en O0 y O2.

Binario directo, ambos niveles:

```text
code: None
signal: 4
stdout: <vacío>
stderr: Aether trap: ShapeMismatch at shape.ae:2:3 in main: false\n
```

`aether run`, ambos niveles:

```text
CLI exit code: 1
stdout: <vacío>
stderr:
Aether trap: ShapeMismatch at shape.ae:2:3 in main: false
aether: error: program terminated by signal 4 (SIGILL)
```

Un retorno ordinario 132 permaneció `code=132`, stdout/stderr vacíos; no fue
confundido con SIGILL.

## 6. Verificación y corrupción de IR

La evidencia cruzada queda en dumps HIR/MIR/SSA/LLVM de la suite dedicada:

- HIR, MIR y SSA contienen `TrapDiagnosticSiteId`, contrato y labels del sitio;
- MIR/SSA usan los operandos materiales de la comparación y sus verificadores
  rechazan observaciones inventadas o de tipo incorrecto;
- el fail block permanece sin trabajo source, sin landing pad/unwind y termina
  en el mismo `ShapeMismatch`;
- LLVM contiene `call void @aether_report_shape_mismatch` antes de la rama al
  bloque compartido con `call void @llvm.trap()`;
- la metadata y los helpers son privados; no se agregó ABI pública.

Corruption tests ejecutados:

| Capa | Matriz rechazada |
|---|---:|
| HIR | 8 corrupciones, incluidas operación vacía, owner incorrecto, span incorrecto y label inventado |
| MIR | 10 corrupciones de condición, trap, CFG, span, fail block y metadata/observaciones |
| SSA | 11 corrupciones equivalentes, incluidos phis/instrucciones en fail edge y observación no dominante/admitida |
| kernels | suites Vertical 31/32/33 y `matrix_add_v1` rechazaron sus corrupciones independientes |

## 7. Qualification ejecutada

| Suite | Resultado |
|---|---:|
| HIR corruption focal `shape_guard_hir_contract_fails_closed` | 1/1 PASS |
| `shape_contract_diagnostics_v1` | 4/4 PASS, O0/O2 |
| `shape_guard_v1` | 8/8 PASS |
| `linear_algebra_solve_v1` | 9/9 PASS |
| kernels Vertical 31 / 32 / 33 | 10/10, 12/12, 12/12 PASS |
| `matrix_add_v1` | 6/6 PASS |
| `uncaught_exception_diagnostics_v1` | 5/5 PASS |
| CLI bootstrap focal | 1/1 PASS, O0/O2 |
| F2 `index_dereference_diagnostic_v1` | 4/4 PASS |
| F1 `owning_collection_fields_v1` | 6/6 PASS, incluido ASan |
| `linear_algebra_ownership_ergonomics_v1` | 6/6 PASS |
| exceptions V1 / V2 / V3 / V4 | 6/6, 8/8, 8/8, 7/7 PASS |
| `nullable_v1` | **9/10; 1 FAIL independiente** |

La ejecución global pasó todos los crates y test binaries alcanzados desde el
inicio hasta `module_std_v1`; Cargo se detuvo al fallar `nullable_v1`. Por ello
los binaries posteriores no constituyen una suite global completada, aunque las
suites focales de F3 se ejecutaron independientemente y pasaron.

## 8. Fallo exacto de nullable_v1 y aislamiento

Test:

```text
nullable_functions_and_references_refine_without_conflating_storage
```

Fragmento source causal:

```aether
int read((ref int)? value){if(value!=null){return *value;}return 0;}
```

Expectativa: el refinamiento `value != null` permite desreferenciar la
referencia nullable, compilar el programa y obtener status 0 en O0/O2.

Observado:

```text
code: E0271
phase: Semantic
category: Type
span: 90..96 (`*value`)
source: nullable_v1.ae
message: cannot dereference expression of type `(ref int64)?`: `*` requires `ref T` or `ref mut T`; `*` does not create a borrow
```

El diagnóstico se emite durante análisis semántico al resolver el Place de
Dereference. No se obtiene Typed HIR válido para la función, no hay lowering a
MIR/SSA/LLVM y nunca se alcanza un `ShapeGuard`.

Comparación controlada:

| Estado | Construcción | Resultado focal |
|---|---|---|
| A | exportación limpia de `HEAD` | PASS |
| B | A + únicamente las dos modificaciones documentadas de F2 en la rama Dereference y sus helpers; sin F1 ni F3 | FAIL con E0271, tipo y span idénticos; source lógico `<memory>` |
| C | worktree actual, con F1/F2/F3 | FAIL con el mismo E0271, tipo y span; F3 mejora el source lógico a `nullable_v1.ae` |

B demuestra causalidad mínima: `dereference_operand_is_place` inspecciona
`place.ty` antes de que el refinamiento nullable de `expression` produzca el
payload `ref int`. Como `place.ty` sigue siendo `(ref int)?`, F2 emite E0271.
F1 no puede ser causal porque sólo cambia SSA y el fallo ocurre antes de MIR.
F3 tampoco es causal: el mismo fallo existe sin su metadata, backend y CLI.

No se cambió el test. Resolver la compatibilidad entre F2 y el refinamiento de
nullable requiere una decisión/corrección propia de Dereference/nullable y
queda fuera del alcance cerrado de F3.

## 9. Gates

| Gate | Resultado |
|---|---|
| `cargo check --workspace` | PASS |
| `cargo fmt --all --check` | PASS después de formatear sólo las assertions nuevas |
| `cargo clippy --workspace --all-targets -j 1` | PASS con warnings no fatales existentes en frontend, middle, CLI y tests previos |
| `git diff --check` | PASS |
| `cargo test --workspace -j 1` | **FAIL**, un test de `nullable_v1`; no se declara PASS |

La suite global no se repitió tras confirmar el fallo determinista.

## 10. Limitaciones reales

- F1, F2 y F3 no son commits separados. No es posible reconstruir un checkout
  histórico exacto de todos los estados locales intermedios.
- Sí fue posible reconstruir la causa mínima relevante: `HEAD` y `HEAD` más el
  cambio exacto de Dereference de F2. Esa comparación es suficiente porque el
  error ocurre antes de toda capa tocada por F1 y antes del transporte de F3.
- La qualification de señal/reporting es específica del bootstrap Linux
  x86-64 normativo; otros targets conservan el fallback de CLI pero no fueron
  calificados aquí.
- El gate global queda incompleto después de `nullable_v1`; no se presenta como
  evidencia de que absolutamente todo el workspace pasó.

## 11. Justificación de cierre

F3 cumple la arquitectura: conserva el trap abortivo, evaluación única,
ordering, ausencia de unwind/EH y reporter best-effort por sitio. Sus casos
positivos, negativos, O0/O2, corrupción, kernels, CLI, ownership y exceptions
pasan. Los outputs identifican el sitio correcto, no contienen paths absolutos
y son anteriores a SIGILL.

El único bloqueo global conocido fue reproducido con F2 aislado y sin F3. La
condición de cierre permite un problema resuelto **o demostrado independiente**;
se cumple la segunda alternativa con evidencia ejecutable A/B/C. Por tanto
SHAPE-CONTRACT-DIAGNOSTICS-V1 (F3) queda **CLOSED**, manteniendo como excepción
explícita el fallo independiente de nullable/F2 y sin afirmar que
`cargo test --workspace -j 1` pasó.
