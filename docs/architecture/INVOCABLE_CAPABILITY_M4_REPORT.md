# Aether — INVOCABLE-CAPABILITY-V1 — M4 Final Qualification

Fecha: 2026-11-09.

Estado: **M4 CLOSED; INVOCABLE-CAPABILITY-V1 CLOSED**.

M0, M1, M2 y M3 permanecen CLOSED. Esta qualification no inicia
`BORROWED-INVOCABLE-PARAM-V1` ni otro milestone.

## Resultado

Los 17 gates normativos de la sección 18 de
`INVOCABLE_CAPABILITY_ARCH_1.md` quedaron verdes con verificación focal,
ejecución nativa O0/O2, corrupciones independientes y workspace completo.

La única corrección productiva de M4 permite usar un `CapabilityInvoke` con
resultado `void` como effect statement. El nodo ya estaba tipado y verificado;
la regla de statements sólo enumeraba `Call` e `IndirectCall` y lo rechazaba
antes de especializar con E0311. No cambiaron representación, dispatch,
ownership, ABI, runtime ni backend.

## Matriz de los 17 gates

| # | Gate normativo | Prueba/evidencia | Estado |
|---:|---|---|---|
| 1 | Gramática contextual y diagnósticos | parser `parses/rejects_*invocable*`; M0/M1 | PASS |
| 2 | Requirement/signature/evidence canónicos, sin `TypeData::Invocable` | tests de `types` y `invocable_requirements_have_canonical_owned_evidence`; búsqueda del enum | PASS |
| 3 | Aliases, 0/1/N parámetros y `void` | M0/M1, Function/Lambda V1 y M4 `zero_multi_parameter_and_void_*` O0/O2 | PASS |
| 4 | Sustitución y forwarding simbólico | `invocable_signatures_are_*substitutable`, forwarding e imports M4 | PASS |
| 5 | Inferencia exacta; sólo Function/Closure | tests frontend y M4 de aridad, cada posición, resultado, narrowing/widening y no-callable | PASS |
| 6 | Body generic validado antes de especializar | M2 generic HIR; negativos Copy/Alias/aritmética/equality/storage/`ref C` | PASS |
| 7 | Invocation repetida sin Copy/Alias implícitos | M2/M3 `twice`; MIR/SSA y contadores M4 | PASS |
| 8 | Ownership by-value y cleanup simbólico | M2 obligations; M3 Function/Closure ignored, fresh, lvalue y transfer; Owning Closures | PASS |
| 9 | Return/early-return/unwind sin leak, double-drop o UAM | M2/M3, owning-param, corruption tests y ejecución balanceada | PASS |
| 10 | Rewriting a spines existentes | M3 inspecciona `IndirectCall` y Closure borrow/call/end; M4 ejecución | PASS |
| 11 | `CallSiteId`/`ExceptionEventId` y may-unwind | M2/M3; M4 Function, Closure, argumento throwing, catch, rethrow y finally | PASS |
| 12 | Corruption matrix HIR/specialization/MIR/SSA | matriz de la sección siguiente | PASS |
| 13 | Cero residuo en MIR/SSA/LLVM | guards de HIR/MIR, tests M3 y ausencia textual en LLVM M4 | PASS |
| 14 | Matriz O0/O2 y consumer numérico | siete tests M4; integración por rectángulos con cinco carriers | PASS |
| 15 | Cero allocation/thunk de adaptación y cero ARC por call | comparación instrumentada directa/Invocable O0/O2 | PASS |
| 16 | Sin cambios de runtime, ABI o libraries | diff limitado a frontend, tests, fixtures y docs | PASS |
| 17 | Documentación y evidencia reproducible | este reporte y estados de arquitectura actualizados | PASS |

## Qualification de tipos, inferencia y varios callables

Se reutilizaron las pruebas M0/M1 para canonicalización, aliases, firmas
generic anidadas, argumentos explícitos/inferidos, forwarding, requirements de
binders distintos y múltiples constraints. M4 agrega rechazos ejecutados para:

- aridad;
- primera y segunda posición de una firma binaria, independientemente;
- resultado;
- `float32` por `float64` y `float64` por `float32`, sin narrowing/widening;
- import de un consumer generic desde otro módulo fuente.

El consumer `combine` usa binders independientes `F` y `G`, `P: Copy` para
autorizar las dos lecturas de `x`, y `R: RingOps` para autorizar `+`. FF, FC,
CF y CC ejecutan en O0/O2. HIR contiene exactamente **4 instancias** de la
declaración y las cuatro parejas de kinds; no se promete una instancia por
lambda ni direct dispatch.

## Ownership, exceptions y cleanup

La evidencia combinada cubre:

- Function by-value Copy/sin drop;
- Closure fresh por transfer, lvalue con Alias/retain/release y capture Move;
- parámetro ignorado, invocación repetida, retorno de `C`, early return y
  branches;
- use-after-move y operaciones universales no autorizadas rechazadas;
- throw desde Function y Closure, throw durante argumentos, catch, rethrow y
  finally;
- `EndClosureBorrow` normal y excepcional antes del cleanup;
- cleanup de temporaries, owner transferido y ausencia de double-drop/leak.

Los casos `finally` de Closure M4 usan un carrier fresh, por lo que también
califican la materialización y cleanup excepcional del temporary. La frontera
lvalue y el unwind de un carrier lvalue se califican por separado en M3 y
Owning Closures; Exceptions V4 conserva sus casos de owners a través de
finally.

## Coste y dispatch

Se comparó un consumer que invoca dos veces `C: Invocable<(int),int>` contra
el mismo consumer con parámetro `Closure<(int),int>` directo. En ambos perfiles
los contadores exactos fueron idénticos:

| Contador | Directo | Invocable | Delta |
|---|---:|---:|---:|
| closure retain | 1 | 1 | 0 |
| closure release | 2 | 2 | 0 |
| closure destroy | 1 | 1 | 0 |
| heap alloc | 1 | 1 | 0 |
| heap free | 1 | 1 | 0 |

El retain/release corresponde exclusivamente a la entrada by-value de un
Closure lvalue; dos invocaciones no agregan ARC. LLVM no contiene
`CapabilityInvoke` ni símbolo de adapter. M3 confirma que Function conserva
indirect call y Closure conserva su box e invoke thunk. No se afirma zero-cost
universal ni inlining.

La medición básica de code size es estructural: el caso FF/FC/CF/CC produce
cuatro cuerpos especializados, uno por combinación real de kinds. No se agregó
thunk por instancia y no se usa el número de lambdas como promesa de tamaño.

## Consumer numérico

El fixture implementa midpoint rectangles con
`C: Invocable<(float64),float64>`, `n=100`, y ejecuta:

- Function top-level;
- lambda no capturante fresh;
- Closure con capture Copy;
- Closure con capture Alias;
- Closure con capture Move.

Para `x²` en `[0,1]`, el esperado independiente es
`1/3 - 1/(12*100²) = 0.333325`; para `2x` es `1`. La tolerancia explícita es
`1e-12`, holgada frente al error de redondeo y muy menor que el error de
discretización que separa `0.333325` de `1/3`. Se realizan 100 evaluaciones por
carrier, **500 invocaciones** totales por perfil. O0 y O2 retornan 0 y el gate
de allocation balance valida cleanup.

## Corruption matrix

| Corrupción | Autoridad que la rechaza |
|---|---|
| declaration/owner, binder, ordinal, requirement, evidence, signature | generic HIR M0/M2 |
| callee type, aridad, argumento, resultado, RepeatableRead, MayUnwind, site/provenance | generic HIR M2 |
| owner state, move/return, cleanup normal/early/unwind | generic HIR ownership replay |
| firma o satisfaction adulterada al sustituir | specialization M3 |
| Function como ClosureCall / Closure como IndirectCall | concrete HIR M3 |
| drop Function inventado / drop Closure omitido | concrete ownership verifier |
| borrow token, carrier durante borrow, missing/duplicate EndClosureBorrow | MIR/SSA Owning Closures |
| dispatch kind, callee, args y result | Function Values y Closure MIR/SSA |
| cleanup normal/excepcional, evento/site, landing pad, catch/rethrow/finally | Exceptions V1–V4 MIR/SSA |
| `GenericParam`, evidence o `CapabilityInvoke` residual | concrete HIR y frontera MIR/SSA |

Estas pruebas construyen o mutan IR directamente; no dependen sólo de parser
negativo ni de que una fase anterior produzca IR válido.

## Qualification focal y global

Entorno: `CARGO_INCREMENTAL=0`, `TMPDIR=/tmp/aether-invocable-m4`, directorio
creado y comprobado escribible; Cargo serial (`-j 1`).

| Comando | Exit | Resultado |
|---|---:|---|
| `cargo test -p aether-frontend -j 1` | 0 | 93 passed; doc-tests PASS |
| suites focales driver M3/M4, Function, lambdas, closures, inference, constraints, ownership y Exceptions | 0 | 97 passed |
| `cargo test -p aether-driver --test invocable_capability_m4 -j 1` | 0 | 7 passed O0/O2 |
| `cargo test --workspace -j 1` | 0 | **1020 passed**, 0 failed, 0 ignored; 113 grupos |
| `cargo fmt --all --check` | 0 | sin diferencias |
| `cargo clippy --workspace --all-targets -j 1` | 0 | warnings preexistentes permitidos |
| `git diff --check` | 0 | limpio |

El workspace alcanzó los doc-tests de los siete crates (0 doctests, 0 fallos).
El test final `linear_algebra_oal_publishes_and_runs_real_qr_consumer` terminó
PASS en **961.32 s**, ejecutó O0/O2 y mostró progreso numérico. No se aplicó
timeout artificial. Log completo:
`/tmp/aether-invocable-m4-workspace.log`.

Clippy conserva categorías preexistentes como `large_enum_variant`,
`needless_borrows_for_generic_args`, `match_same_arms`, `assert_is_empty`,
`too_many_lines`, `single_match_else` y `manual_let_else`; M4 no agrega una
categoría nueva.

## Archivos modificados

- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-driver/tests/invocable_capability_m4.rs`;
- `compiler-next/tests/modules/invocable_capability_m4/main.ae`;
- `compiler-next/tests/modules/invocable_capability_m4/provider.ae`;
- `docs/architecture/INVOCABLE_CAPABILITY_ARCH_1.md`;
- `docs/architecture/INVOCABLE_CAPABILITY_ARCH_1_REPORT.md`;
- `docs/architecture/INVOCABLE_CAPABILITY_M4_REPORT.md`.

No se modificaron runtime, ABI, Plots, linearAlgebra, libraries productivas ni
ejemplos personales. No se hizo commit ni push.

## Fuera de scope

Permanecen fuera invocation por `ref C`, `Callable`/`CallableRef`, erasure,
adapters Function/Closure, traits generales, generic lambdas, closures
mutables/consuming, storage heterogéneo, migración de libraries, ABI entre
artefactos independientes y nuevos helpers runtime.

Clasificación final: **M4 CLOSED; INVOCABLE-CAPABILITY-V1 CLOSED**.
