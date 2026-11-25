# FRONTEND-STACK-USAGE-V1 — Reporte de cierre

Estado: **CLOSED**
Fecha: 2026-11-24
HEAD inspeccionado: `3c5c4518 refactor(examples): simplify scientific curve fitting`

## 1. Causa raíz

El fallo no era monomorfización numérica. El parser construye las cadenas `&&` y `||` con la asociatividad izquierda existente, y el analizador recorría esa espina recursivamente:

```text
Analyzer::expression
  -> Analyzer::binary
    -> Analyzer::expression(left)
      -> Analyzer::binary
        -> ...
```

En Rust debug, cada nivel retenía simultáneamente un frame muy grande de `Analyzer::expression` y otro de `Analyzer::binary`. La cadena del test original tiene 18 niveles lógicos; solamente esos dos frames sumaban aproximadamente 1.870.848 bytes antes de contar el harness, diagnósticos, coerciones y demás llamadas activas.

La investigación posterior encontró dos recorridos recursivos adicionales de la misma espina lógica: `Monomorphizer::substitute_expr` y `Builder::lower_expr`. No provocaban primero el test de 18 niveles, pero sí seguían siendo un riesgo real para la qualification de 128 operadores.

El tamaño no se atribuyó a `AstExprKind`, `HirExpr` o `Checked` de forma aislada. Las secciones de tamaño de stack emitidas por rustc muestran que los frames grandes pertenecen a funciones con `match` extensos y muchos temporales de ramas mutuamente excluyentes. Rust debug reserva el máximo requerido por toda la función y conserva almacenamiento/lifetimes de temporales mucho más agresivamente que el build optimizado.

## 2. Baseline y frames originales

Reproducción exacta, sin `RUST_MIN_STACK`:

```text
cargo test -p aether-driver --test numeric_capabilities_v1 \
  every_numeric_capability_and_alias_reifies_before_mir -- --exact --nocapture

thread 'every_numeric_capability_and_alias_reifies_before_mir' has overflowed its stack
fatal runtime error: stack overflow, aborting
```

El límite del shell era 8 MiB (`ulimit -s = 8192`), pero libtest crea un thread separado con stack predeterminado de 2 MiB. La prueba original falló con 2.097.152 bytes y pasó con 2.621.440 bytes. Estos valores acotan el pico, pero no son una medición byte-exacta del high-water mark.

Medición con `RUSTC_BOOTSTRAP=1 RUSTFLAGS='-Z emit-stack-sizes'` y `llvm-readobj --stack-sizes`:

| Función debug original | Hex | Bytes |
|---|---:|---:|
| `Analyzer::expression` | `0xE938` | 59.704 |
| `Analyzer::binary` | `0xACC8` | 44.232 |
| `Monomorphizer::substitute_expr` | `0x15E28` | 89.640 |
| `Builder::lower_expr` | `0xE1B8` | 57.784 |

La evidencia explica el carácter debug-only del fallo: en release, LLVM reduce drásticamente estos frames y puede inlinear el helper lógico. No se usó release para sustituir ningún gate debug.

## 3. Alternativas evaluadas

- A. Extraer el despacho lógico y las ramas complejas: elegida para impedir que las cadenas lógicas reentren en `Analyzer::expression` y `Analyzer::binary` completos.
- B. Acortar lifetimes de temporales individuales: descartada como corrección principal; el frame es el agregado de una función muy grande y el resultado sería frágil frente a cambios no relacionados.
- C. Recorrer iterativamente las cadenas asociativas: elegida de forma localizada para la espina izquierda de `&&`/`||` en análisis, monomorfización y lowering MIR.
- D. Cambiar perfiles Cargo o aumentar el stack: descartada; habría ocultado el defecto estructural y no protege consumidores con stacks menores.

No se modificó el parser ni la asociatividad del AST.

## 4. Corrección elegida

`Analyzer::expression` es ahora un dispatcher pequeño. Las expresiones no lógicas se delegan a `expression_non_logical`; las cadenas lógicas se aplanan solamente por su espina izquierda y se reconstruyen en el mismo orden.

Para cada nodo lógico, el analizador conserva exactamente la secuencia anterior:

1. analiza el lado izquierdo;
2. guarda `null_states`;
3. aplica `refine_for_condition` con la verdad requerida por `&&` o `||`;
4. analiza el RHS bajo ese refinamiento;
5. restaura el estado guardado;
6. crea `ShortCircuitAnd` o `ShortCircuitOr` con el span original.

La monomorfización reconstruye iterativamente los mismos nodos HIR, sustituyendo tipo y span de cada nodo. El lowering MIR emite, por cada operador y en el orden original, los mismos bloques `rhs`, `short` y `join` y el mismo branch condicional.

## 5. Cambios realizados

- Extracción de `Analyzer::expression_non_logical`.
- Nuevo recorrido iterativo de la espina lógica en `Analyzer::logical_binary`.
- Eliminación de la rama lógica recursiva de `Analyzer::binary`.
- Nuevo `Monomorphizer::substitute_short_circuit` iterativo.
- Nuevo `Builder::lower_short_circuit` iterativo.
- Qualification dedicada de profundidad y semántica.
- Sin cambios a Cargo, parser, sistema de tipos, STD, OAL ni semántica pública.

## 6. Stack antes y después

Frames debug finales:

| Función debug final | Hex | Bytes | Papel en cadenas lógicas |
|---|---:|---:|---|
| `Analyzer::expression` | `0x628` | 1.576 | dispatcher; no recorre la espina |
| `Analyzer::logical_binary` | `0x1458` | 5.208 | un frame iterativo |
| `Analyzer::expression_non_logical` | `0xE938` | 59.704 | no se reentra por la espina lógica |
| `Analyzer::binary` | `0x9C38` | 39.992 | no recibe `&&`/`||` |
| `Monomorphizer::substitute_expr` | `0x14DC8` | 85.448 | no recurre por la espina lógica |
| `Monomorphizer::substitute_short_circuit` | `0x11F8` | 4.600 | un frame iterativo |
| `Builder::lower_expr` | `0xDAE8` | 56.040 | no recurre por la espina lógica |
| `Builder::lower_short_circuit` | `0x928` | 2.344 | un frame iterativo |

Frames release finales medidos en el mismo toolchain:

| Función release final | Bytes |
|---|---:|
| `Analyzer::expression` | 1.240 |
| `Analyzer::expression_non_logical` | 2.888 |
| `Analyzer::binary` | 3.544 |
| `Monomorphizer::substitute_expr` | 13.272 |
| `Monomorphizer::substitute_short_circuit` | 1.096 |
| `Builder::lower_expr` | 2.744 |
| `Builder::lower_short_circuit` | 808 |

`Analyzer::logical_binary` fue inlineado en release y no aparece como símbolo independiente.

Como evidencia alternativa del pico total, el test original final pasa con un thread de 524.288 bytes y falla con 393.216 bytes. Antes de la corrección fallaba con 2.097.152 bytes y recién pasaba con 2.621.440 bytes. Los probes con `RUST_MIN_STACK` se usaron exclusivamente para medir; todas las qualifications se ejecutaron con la variable ausente.

No se declara un high-water mark exacto porque no se instrumentó cada cambio del stack pointer. La combinación de secciones de frame, eliminación verificable de la recursión y umbrales del thread proporciona evidencia independiente suficiente.

## 7. Tests de profundidad

`frontend_stack_usage_v1.rs` cubre:

- 1, 8, 19, 64 y 128 operadores;
- `&&` y `||`;
- comparaciones numéricas en cada operando;
- operadores mezclados y paréntesis;
- calls con mutación observable para probar orden izquierda-a-derecha;
- RHS que no debe ejecutarse por short-circuit;
- refinamiento nullable en `&&` y `||`;
- condición inválida de 128 operadores que debe producir diagnóstico de tipo;
- ejecución nativa O0 y O2;
- presencia exacta de `ShortCircuitAnd` y `ShortCircuitOr` en HIR.

Los tamaños son qualification, no límites normativos del lenguaje.

## 8. Preservación semántica

Las pruebas verifican que:

- `false && rhs` no ejecuta `rhs`;
- `true || rhs` no ejecuta `rhs`;
- dos calls productivas dejan una traza `12`, demostrando orden izquierda-a-derecha y ausencia de duplicación;
- las ramas omitidas no alteran la traza;
- `value != null && positive(value)` conserva el refinamiento nullable;
- los paréntesis y operadores mezclados conservan precedencia y resultado;
- los dumps contienen exactamente los mismos nodos lógicos por operador;
- las suites Nullable, Borrow Ergonomics, Ownership, HIR/MIR/SSA y diagnostics siguen pasando.

No cambió borrowing, lifetime, ownership, coerción, diagnostics, spans, MIR, SSA ni evaluación observable.

## 9. Qualification O0/O2

El test original `numeric_capabilities_v1::every_numeric_capability_and_alias_reifies_before_mir` pasa sin aumentar el stack y continúa compilando/ejecutando su corpus en O0 y O2.

Los nuevos tests de profundidad y semántica también ejecutan binarios nativos en O0 y O2. La suite focal completó 62 tests sin fallos entre:

- Numeric Capabilities;
- Nullable V1;
- Index Dereference Diagnostic V1;
- Borrow Ergonomics;
- Iteration V1/V2/V3;
- Owning Collection Fields V1;
- Linear Algebra Ownership Ergonomics V1;
- Shape Contract Diagnostics V1;
- FRONTEND-STACK-USAGE-V1.

No se obtuvo una medición reproducible de tiempo de análisis aislado antes/después. Los tiempos de pared observados incluyen caché, clang y link, por lo que no se usan para afirmar una mejora de rendimiento.

## 10. Gates completos

Ejecutados desde `compiler-next`, sin `RUST_MIN_STACK`:

| Gate | Resultado |
|---|---|
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | PASS |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS con warnings preexistentes/no relacionados |
| `git diff --check` | PASS |

El workspace completo terminó. La prueba más lenta, `linear_algebra_oal_publishes_and_runs_real_qr_consumer`, finalizó correctamente en 708,32 s; no se contó ninguna ejecución interrumpida.

Clippy conserva warnings en cambios ajenos ya presentes (`HirStmtKind`, SSA, CLI y otros tests); el test nuevo no añade warnings.

## 11. Archivos modificados por este milestone

- `compiler-next/crates/aether-frontend/src/hir.rs`
- `compiler-next/crates/aether-middle/src/mir.rs`
- `compiler-next/crates/aether-driver/tests/frontend_stack_usage_v1.rs`
- `docs/architecture/FRONTEND_STACK_USAGE_V1_REPORT.md`

Los dos archivos de implementación ya contenían cambios pendientes de otros milestones. Se preservaron y los cambios de este milestone se limitaron a los recorridos descritos. No se hizo commit ni push.

## 12. Riesgos restantes

- Otras familias de expresiones todavía pasan por funciones debug con frames grandes. Este cierre elimina la multiplicación de esos frames para cadenas lógicas; no pretende rediseñar todo el analizador.
- Árboles artificiales profundamente anidados por el lado derecho mediante miles de paréntesis todavía pueden depender de recorridos recursivos generales. El parser ordinario produce la cadena asociativa por la izquierda que ahora se procesa iterativamente.
- `refine_for_condition` conserva su recorrido recursivo pequeño. Ya no se combina con los frames gigantes y los casos de 128 operadores pasan, pero un futuro frontend completamente no recursivo podría convertir también ese visitante si aparecen corpus mucho más profundos.
- Los warnings Clippy ajenos deben resolverse en sus milestones propietarios; cambiarlos aquí habría violado la preservación del trabajo pendiente.

Los criterios de cierre se cumplen: el test original pasa con stack estándar, la recursión problemática fue eliminada en las tres fases que la recorrían, la evidencia de stack mejoró de más de 2 MiB a menos de 512 KiB para el caso original, las pruebas semánticas pasan y el workspace completo finaliza sin regresiones.
