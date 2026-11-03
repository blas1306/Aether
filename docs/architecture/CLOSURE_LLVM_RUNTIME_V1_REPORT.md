# Aether — CLOSURE-LLVM-RUNTIME-V1 — Implementation & Qualification

Estado: **PARTIAL — IMPLEMENTACIÓN PRODUCTIVA Y QUALIFICATION FOCAL COMPLETAS;
GATE DE WORKSPACE NO VERDE**, 3 de noviembre de 2026.

## Resultado

El backend LLVM productivo de closures owning read-only quedó implementado a
partir de `VerifiedSsa`. Se retiró la frontera `E0376`; no se modificó el ABI de
`Function`, no se añadió un Callable general y no se reconstruyen capturas por
nombres source.

`ClosureABI-v1` usa un carrier `ptr` owning al byte cero de:

```text
0   usize strong_count
8   ptr   invoke_thunk
16  ptr   destroy_thunk
24+ payload, alineado según sus fields
```

El backend acepta el bootstrap x86-64 vigente, calcula offsets, tamaño y
alignment mediante `layout_of` y aritmética checked, y aborta fail-closed si se
intenta emitir Closure con un target de word/pointer distinto de 64 bits.

## Implementación

- `ClosureCreate` asigna el box, escribe header, adquiere captures en orden
  canónico y publica el carrier sólo después del último store.
- `Copy` materializa un snapshot; `Alias` usa el retain intrínseco de string,
  class/interface o Closure; `Move` transfiere los bits del root ya invalidado
  por el ownership IR.
- Las adquisiciones V1 son nounwind o traps abortivos. Por ello no existe hoy
  un unwind recuperable entre captures; el contrato de prefijo queda preservado
  sin inventar una ruta de rollback inobservable.
- Cada environment genera un invoke thunk `R(ptr box, P...)` con prototype
  derivado de la firma verificada. Sólo el thunk proyecta el payload y entrega
  los `capture_slots` read-only al body sintético.
- Cada environment genera un destroy thunk `void(ptr) nounwind`, destruye en
  orden inverso y libera con el size/alignment exactos.
- Los drops aparentes de `capture_slots` en el body no emiten destrucción LLVM:
  esos slots son vistas privadas read-only y su única destrucción corresponde
  al destroy thunk.
- `ClosureAlias`, `ClosureBorrow`, `ClosureCall` y `EndClosureBorrow` poseen
  lowering propio. La call carga exclusivamente offset 8, pasa el box oculto,
  conserva el borrow en normal/unwind y no hace ARC por invocación.
- `aether_closure_retain_v1` y `aether_closure_release_v1` son versionados,
  nounwind y fail-closed para zero/overflow/underflow. El último release fija
  count cero antes de llamar al destroy thunk.
- Invoke/destroy/body y todas sus dependencias permanecen emitidos aunque el
  único root visible sea un pointer almacenado en el header. El mangling parte
  de la identidad única del target sintético, que incluye package/source,
  lambda/instancia y firma del programa conjunto.

No se añadieron TLS, trampolines globales, GC, weak ownership ni conversiones
`Function`/`Closure`.

## Qualification productiva

`aether-driver/tests/owning_closures_read_v1.rs` ejecuta binarios reales O0/O2
y cubre:

- Copy automático y snapshot frente a mutación exterior;
- Alias de string, class, interface y otra Closure;
- Move explícito de aggregate owning;
- captures mixtas/parciales, varios parámetros e invocación repetida;
- closure nunca invocada, paths condicionales y destrucción al salir;
- paso/retorno, supervivencia al creator, alias de argumento, replacement y
  self-assignment;
- lambdas anidadas y captura transitiva;
- excepción desde el body, catch, normal/unwind borrow cleanup y owner vivo;
- fuentes/packages declarados distintos dentro de una `CompilationSession`;
- offsets 0/8/16/24, reachability, prototype oculto y destroy `nounwind`;
- contadores exactos: retain 1, release 2, destroy 1, alloc 1, free 1 para un
  paso owning por alias;
- AddressSanitizer para captures mixtas (UAF/double-free). LeakSanitizer no es
  utilizable bajo la política ptrace del entorno; la instrumentación
  alloc/free y el gate de balance del runtime verifican leaks en los consumers.

Resultado focal final: **25/25 PASS**. Los corruption tests HIR/MIR/SSA y los
tests de capture/ownership IR permanecen en el mismo target.

Regresiones focales adicionales ejecutadas:

- `anonymous_functions_v1`: 5/5 PASS;
- `function_values_v1`: 8/8 PASS;
- `exception_v1`: 6/6 PASS;
- `exception_v2`: 8/8 PASS;
- `exception_v3`: 8/8 PASS;
- `exception_v4`: 7/7 PASS.

`cargo fmt --all --check`, Clippy del workspace y `git diff --check`
finalizaron con código 0. Clippy conserva warnings preexistentes; los dos
warnings nuevos del backend fueron corregidos.

`CARGO_INCREMENTAL=0 cargo test --workspace -j 1` ejecutó todo el workspace y
todos los grupos anteriores al último terminaron PASS, incluidos `vertical`
220/220, frontend 78/78, middle 29/29 y registry 4/5. El último test,
`linear_algebra_oal_publishes_and_runs_real_qr_consumer`, terminó **FAIL** porque
el consumer salió 88 en O0. Durante este trabajo aparecieron cambios ajenos en
`linearAlgebra/src/lib.ae` y su consumer que añaden `dot` y hacen retornar 600
si esa nueva prueba falla; esos cambios se preservaron y no pertenecen a este
subvertical. Por tanto el workspace completo no se declara PASS.

## Alcance ABI

Se calificó interoperabilidad entre funciones, módulos fuente y packages
fuente compilados conjuntamente. Artefactos Aether producidos por
compilaciones independientes, metadata ABI persistida y bibliotecas
precompiladas continúan **OUT OF SCOPE** según
`FIRST_CLASS_CLOSURES_ARCH_1_ABI_SCOPE_AMENDMENT.md`.

## Archivos del subvertical

- `compiler-next/crates/aether-backend-llvm/src/lib.rs`;
- `compiler-next/crates/aether-driver/src/lib.rs`;
- `compiler-next/crates/aether-driver/tests/owning_closures_read_v1.rs`;
- `compiler-next/crates/aether-driver/tests/anonymous_functions_v1.rs`;
- `compiler-next/tests/modules/owning_closures_read_v1/main.ae`;
- `compiler-next/tests/modules/owning_closures_read_v1/provider.ae`;
- `docs/architecture/CLOSURE_LLVM_RUNTIME_V1_REPORT.md`;
- `docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`.

Clasificación conservadora: **CLOSURE-LLVM-RUNTIME-V1 PARTIAL** únicamente por
el gate global de workspace no verde; backend y qualification específica están
completos. `OWNING-CLOSURES-READ-V1` permanece **PARTIAL** hasta rerun verde del
workspace después de integrar o corregir los cambios concurrentes de
`linearAlgebra`.
