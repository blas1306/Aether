# Aether — PLOTS-INVOCABLE-INTEGRATION-V1 — Final Qualification Report

Fecha: 2026-11-15.

## Estado

**PLOTS-INVOCABLE-INTEGRATION-V1: CLOSED.**

`plots.plotFunction` publica ahora una única entrada genérica borrowed. Los
consumers Function existentes y los nuevos consumers Closure compilan,
enlazan, ejecutan y renderizan SVG completo en O0/O2. La qualification focal,
el package productivo y el workspace completo quedaron verdes.

El bloqueo LLVM que dejó la investigación anterior en PARTIAL fue corregido y
calificado por `LLVM-RUNTIME-DECLARATION-CONSISTENCY-V1`. La regresión positiva
de este milestone confirma que no reaparece: el cierre de reachability contiene
los targets Closure y un wrapper IO emitido siempre tiene su helper canónico.

## Preflight y alcance

El worktree estaba limpio al retomar el milestone. La corrección de reachability
estaba presente, el reproducer Closure + SVG ya enlazaba O0/O2, la API productiva
seguía usando la firma Function anterior y permanecían disponibles el fixture
`plots/tests/invocable_consumer` y la suite
`plots_invocable_integration_v1.rs`. No había cambios ajenos en Plots que
pudieran sobrescribirse.

No se modificaron Invocable, Borrowed Invocable, overload resolution, runtime,
ABI, Graphics/SVG, otras bibliotecas ni ejemplos personales. En particular,
`examples/svd.ae` no fue modificado. No se hizo commit ni push.

## Firma productiva final

La firma concreta anterior fue sustituida por:

```aether
public Figure2D plotFunction<C: Invocable<(float64), float64>>(
    ref C target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options)
```

El cuerpo de sampling no cambió. Conserva el orden de validaciones, el grid
incluyendo ambos extremos, el tratamiento de no finitos, las excepciones y la
delegación a `line(&points, options)`.

No se mantuvo el overload concreto: Function satisface ambas entradas y el
reproducer conserva el diagnóstico `E0461 ambiguous overload`. No se cambió el
ranking general.

## Compatibilidad source, exports y mangling

Pasaron calls package-qualified desde otros módulos con:

- Function lvalue y función top-level;
- lambda sin captura;
- Closure lvalue y fresh;
- captures Copy, Alias y Move, también fresh;
- inferencia de `C` a través del límite de módulo/package.

Los consumers Function versionados, los tests de sampling y el generador de
goldens mantienen su sintaxis. Las especializaciones Function/Closure se
resuelven con la identidad genérica y el mangling normal de instancias; la suite
de imports, forwarding y mangling genérico también quedó verde.

La identidad pública sí cambia de función concreta a declaración genérica.
Tomar `plotFunction` como un valor `Function` sin especialización no está
garantizado. No se promete compatibilidad ABI con el símbolo concreto anterior;
la evidencia de compatibilidad es source y corresponde a los calls calificados.

## Qualification productiva Function/Closure + SVG

`plots/tests/invocable_consumer` fue comprobado y ejecutado con el package real:

| Gate | O0 | O2 |
|---|---:|---:|
| `aether check .` | PASS | N/A |
| `aether run .` | PASS | PASS |
| Function/top-level/lambda | PASS | PASS |
| Closure Copy/Alias/Move lvalue y fresh | PASS | PASS |
| render SVG completo | PASS | PASS |

La suite dedicada carga las fuentes productivas de Plots, Graphics y sus
módulos SVG. Para la misma función cuadrática, una Function y una Closure
capturante producen documentos SVG byte-idénticos en O0/O2. Un segundo render
de la misma Figure también es idéntico, y el owner Closure sigue siendo
invocable después de `plotFunction`.

El caso establece `title`, `xLabel` e `yLabel` no vacíos antes del sampling; la
igualdad completa del documento Function/Closure demuestra que las
`FigureOptions` recorren el mismo camino. Las suites `plots_function_sampling_v1`,
`plots_2d_line_v1` y `graphics_svg_backend_v1` verifican además XML bien formado,
estructura exacta, cardinalidad y datos del sampling, painter order y goldens
byte por byte O0/O2. No hubo cambios en los goldens.

La LLVM Closure + SVG enlaza mediante Clang en ambos niveles. Los helpers IO
inalcanzables no aparecen. El caso positivo de `readLine` con una Closure exige
exactamente una call y una definición privada del helper; por tanto no quedan
calls LLVM a helpers sin declaración/definición.

## Ownership, coste y exceptions

Para la Closure lvalue capturante, los contadores al terminar `main` son
idénticos en O0/O2:

| Retain | Release | Destroy |
|---:|---:|---:|
| 0 | 1 | 1 |

El release/destroy pertenece al owner original. La frontera borrowed agrega
cero retain/release, cero allocation de adapter y ningún thunk de adaptación.
MIR contiene `ClosureCall` y `EndClosureBorrow`; MIR/SSA/LLVM no retienen
`CapabilityInvoke`, `BorrowedCapabilityInvoke` ni símbolos de adapter. La
invocación ocurre repetidamente dentro del loop de sampling y el owner puede
reutilizarse después.

La prueba de unwind hace throw desde el callback durante el sampling, captura
la excepción fuera de `plotFunction`, verifica cleanup y vuelve a invocar el
owner. Pasa O0/O2 con los mismos contadores. Los gates CLOSED de Borrowed
Invocable, reejecutados aquí, cubren Closure fresh destruida exactamente una
vez, Function fresh, captures Copy/Alias/Move, temporaries, forwarding, y la
preservación de `CallSiteId`, `ExceptionEventId`, catch/rethrow/finally. No se
duplicó esa matriz dentro de Plots.

Las firmas incompatibles por aridad, tipo de parámetro o resultado son
rechazadas con diagnóstico Invocable/E0205 antes de codegen.

## Regresiones y gates

Entorno: `TMPDIR=/tmp`, `CARGO_INCREMENTAL=0`, Cargo serial `-j 1`.

| Comando/gate | Exit | Resultado |
|---|---:|---|
| `plots_invocable_integration_v1` | 0 | 6 passed |
| `plots_function_sampling_v1` | 0 | 8 passed |
| `plots_2d_line_v1` | 0 | 5 passed |
| `graphics_svg_backend_v1` | 0 | 11 passed |
| `invocable_capability_m4` | 0 | 7 passed |
| `borrowed_invocable_param_m3` | 0 | 6 passed |
| `io_v1` | 0 | 12 passed |
| `generic_inference_ref_argument_v1` | 0 | 5 passed |
| package productivo `check`, `run -O0`, `run -O2` | 0/0/0 | PASS |
| `cargo check --workspace` | 0 | PASS |
| `cargo test --workspace -j 1` | 0 | PASS completo, incluidos doc-tests |
| `cargo fmt --all --check` | 0 | PASS después del formato mecánico del test nuevo |
| `cargo clippy --workspace --all-targets -j 1` | 0 | PASS; warnings históricos no promovidos a error |
| `git diff --check` global | 0 | PASS |
| `git diff --check` limitado al milestone | 0 | PASS |

El test largo `linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó
normalmente en 1096.14 s y pasó. No se canceló, no se aplicó timeout y no se
clasificó durante su fase silenciosa.

El resultado global y el limitado coinciden: no existe diferencia ajena de
whitespace en el worktree actual. El aviso del encargo sobre posible whitespace
preexistente en `examples/svd.ae` no se materializó en este checkout.

## Archivos modificados

- `plots/src/lib.ae`: firma productiva borrowed genérica;
- `compiler-next/crates/aether-driver/tests/plots_invocable_integration_v1.rs`:
  qualification directa de producción y equivalencia/determinismo SVG;
- `docs/architecture/PLOTS_INVOCABLE_INTEGRATION_V1_REPORT.md`: este cierre.

El fixture productivo ya existente fue ejecutado sin necesidad de modificarlo.
El lock temporal vacío creado por el runner durante la qualification fue
retirado y no forma parte del diff.

## Cierre

La migración productiva, consumers Function/Closure, SVG O0/O2, sampling,
goldens, ownership, exceptions, reachability y todos los gates globales están
verdes dentro del alcance definido.

**Clasificación final: PLOTS-INVOCABLE-INTEGRATION-V1 CLOSED.**
