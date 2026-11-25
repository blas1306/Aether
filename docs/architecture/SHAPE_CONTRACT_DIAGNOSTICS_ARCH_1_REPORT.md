# SHAPE-CONTRACT-DIAGNOSTICS-ARCH-1 — reporte de investigación

Estado: **ARCHITECTURE CLOSED; NO IMPLEMENTADA**, 2026-11-23.

Autoridad normativa:
[SHAPE-CONTRACT-DIAGNOSTICS-ARCH-1](SHAPE_CONTRACT_DIAGNOSTICS_ARCH_1.md).

## 1. Resultado

F3 no es exclusivamente un defecto de CLI. `linearAlgebra` conoce la relación
de dimensiones, HIR/MIR/SSA preservan `ShapeMismatch` y el span, pero no
transportan contrato legible ni operandos observables. El backend converge el
fallo en `llvm.trap`; Linux entrega SIGILL 4 sin salida. La CLI sólo mira
`ExitStatus::code()`, pierde la señal concreta y muestra el fallback genérico.

Se cierra una arquitectura única: diagnóstico estático por sitio y extents ya
calculados en el fail edge, writer privado no asignante, y el mismo
`llvm.trap` terminal. `shapeGuard` continúa abortivo, no capturable y sin unwind.
La CLI sólo mejora la descripción de la señal y nunca reconstruye el trap.

## 2. Preflight y preservación

Checkout observado:

```text
branch: main (alineada con origin/main)
HEAD: 3c5c451854cbddb2d5296ed1873ae837a5e03908
staging: vacío
```

Cambios locales preexistentes preservados:

- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-middle/src/ssa.rs`;
- `examples/ProbandoNR/probandoNR2.ae`;
- suites/reportes no versionados de F1/F2;
- assessment y consolidation no versionados;
- `examples/assessment/`, `examples/ProbandoNR/.aether-package.lock` y
  `tmp_lambda_test.ae`.

No se editó ninguno. Los artefactos `.aether/` y lock efímero creados para la
reproducción fueron retirados del árbol. El probe de dot fue trasladado a `/tmp`.
Los únicos cambios de este milestone son los dos documentos solicitados.

## 3. Autoridades inspeccionadas

Se contrastaron:

- `APPLICATION_MATURITY_ASSESSMENT_V1.md` y
  `APPLICATION_MATURITY_CONSOLIDATION_V1_REPORT.md`;
- contrato semántico V1, sección 8.2;
- `SHAPE-GUARD-ARCH-1`, su reporte y `SHAPE-GUARD-V1`;
- arquitectura/implementación de solve;
- `EXCEPTION-ARCH-2`, EXCEPTION-V4 y diagnósticos de exception uncaught;
- `CLI-ARCH-1`, driver, CLI y backend LLVM actuales;
- `linearAlgebra/src/lib.ae` y tests de shape, solve, matrix add, math kernels y
  exceptions.

La autoridad admite explícitamente traps abortivos con diagnóstico y exit no
exitoso; no exige que `ShapeMismatch` se vuelva exception.

## 4. Reproducción verificada

Target: Linux x86-64. CLI:
`compiler-next/target/debug/aether`. Se capturaron stdout, stderr, return code y
señal con `subprocess`, evitando la conversión shell habitual de señal a 128+N.

Secuencia usada por perfil:

```text
compiler-next/target/debug/aether build \
  examples/assessment/numerical-solver -O0|-O2
examples/assessment/numerical-solver/.aether/build/assessmentNumericalSolver \
  dimension-mismatch
compiler-next/target/debug/aether run \
  examples/assessment/numerical-solver -O0|-O2 -- dimension-mismatch
```

### 4.1 Numerical Solver

Input del modo `dimension-mismatch`:

```text
A = [[1,0],[0,1]]  # 2x2
b = [1]            # Column length 1
la.solve(A,b)
```

| Perfil | Ejecución | stdout | stderr | exit code | señal |
|---|---|---|---|---:|---:|
| O0 | binario directo | vacío | vacío | none | 4 SIGILL |
| O0 | `aether run` | vacío | fallback genérico + LF | 1 | none (CLI) |
| O2 | binario directo | vacío | vacío | none | 4 SIGILL |
| O2 | `aether run` | vacío | fallback genérico + LF | 1 | none (CLI) |

Texto CLI exacto:

```text
aether: error: program terminated without a representable exit status
```

No hubo diferencia O0/O2. El binario directo demuestra que la CLI no oculta un
mensaje previo: el artefacto no escribe ningún byte.

### 4.2 Dot incompatible

Se compiló un consumer temporal que llama:

```aether
Vector<float64,Column> left = [1.0, 2.0];
Vector<float64,Column> right = [3.0];
float64 result = la.dot(left, right);
```

| Perfil | Ejecución | stdout | stderr | exit code | señal |
|---|---|---|---|---:|---:|
| O0 | binario directo | vacío | vacío | none | 4 SIGILL |
| O0 | `aether run` | vacío | fallback genérico + LF | 1 | none (CLI) |
| O2 | binario directo | vacío | vacío | none | 4 SIGILL |
| O2 | `aether run` | vacío | fallback genérico + LF | 1 | none (CLI) |

Este caso también usa `shapeGuard`, pero en otro contrato público. Los kernels
nativos de suma/producto poseen productores de `ShapeMismatch` distintos; los
tests y el backend confirman que convergen físicamente en la misma etiqueta. No
se deduce por ello que todos los traps matemáticos nacen en Linear Algebra.

### 4.3 Excepciones nominales de control

Los modos existentes conservaron:

| Caso | Resultado observado |
|---|---|
| singular LU O0 | stdout `LU rejected singular matrix`, exit 0 |
| rank deficient QR O2 | stdout `QR rejected rank-deficient matrix`, exit 0 |

Esto confirma la frontera: shape inválida aborta; singularidad/rank deficiency
con shape válida se transportan como exceptions nominales y son capturables.

## 5. Causa raíz por capa

### API Linear Algebra

`solve(A,b)` comprueba primero square y luego longitud RHS. `dot` comprueba
igualdad de dimensiones. En este punto existen container descriptors y el
source expresa el contrato completo.

### `shapeGuard`

HIR conserva la expresión bool, `ShapeMismatch` y span. MIR materializa el bool
en un temporal y crea success/failure. El failure block sólo termina en
`Trap(ShapeMismatch)`. SSA preserva la misma estructura y dominance.

La operación ya no lleva una descripción source-facing del contrato. Tras
materializar el bool, tampoco hay una lista normativa de los extents que lo
produjeron.

### LLVM

El backend emite una rama al failure block y éste salta a
`trap_shape_mismatch`. Esa etiqueta contiene:

```llvm
; structured Aether trap: ShapeMismatch
call void @llvm.trap()
unreachable
```

El comentario sólo existe en IR; no es output runtime. No hay helper, payload,
writer ni ABI de error. En el target probado `llvm.trap` se materializa como
SIGILL 4.

### Driver y CLI

El driver usa `Command::status()` y devuelve el `ExitStatus` completo. La CLI
consulta sólo `status.code()`. Si es `None`, imprime el fallback y retorna 1.
Por tanto el driver todavía posee la señal, pero ya no posee operación,
dimensiones o `TrapKind`; la CLI además omite la única información concreta que
sí queda, el número de señal.

## 6. Qué información falta

| Información | Existe inicialmente | Llega al proceso/CLI hoy |
|---|---|---|
| categoría `ShapeMismatch` | sí, HIR/MIR/SSA | no |
| operación `linearAlgebra.solve`/`dot` | sí, función source | no |
| relación esperada | sí, predicado source | no |
| extents observados | sí durante evaluación | no, queda sólo bool |
| span | sí hasta SSA | no se renderiza |
| terminación por señal | kernel/driver | driver sí; CLI no la muestra |

No hay una restricción del exception ABI que impida diagnosticar: el trap no
debe entrar en ese ABI. El problema es ausencia de metadata/canal en el fail
path abortivo.

## 7. Alternativas evaluadas

### A. Mantener el trap abortivo — elegida

Ventajas:

- respeta todos los contratos CLOSED;
- no cambia APIs ni catch behavior;
- no agrega unwind/cleanup;
- no introduce coste de formatting/IO en success;
- puede reutilizar writer privado ya calificado;
- sirve a `shapeGuard` y kernels nativos sin atribuirles el mismo origen.

La metadata por sitio y observaciones reusadas permiten mensaje accionable
antes de la misma señal. No existe ABI público nuevo.

### B. Excepción nominal recuperable — rechazada

Aunque permitiría payload y catch, convertiría una precondición vigente en
outcome recuperable, cambiaría overloads/expectativas públicas, exceptional
CFG, cleanup, `finally`, code size y resultados de programas con catch-all.
También exigiría una decisión normativa sobre todas las APIs de shape.

Las exceptions matemáticas actuales no justifican esa conversión:
`SingularMatrixException` y `RankDeficientMatrixException` ocurren después de
validar shapes y representan un resultado del algoritmo.

### Sólo CLI — rechazada

Mostrar `SIGILL` mejora honestidad, pero no distingue shape, overflow, bounds u
otro `llvm.trap`. Mapear señal 4 a `ShapeMismatch` produciría falsos
diagnósticos. La CLI no puede recuperar dimensiones inexistentes.

### Mensaje dinámico/source API nueva — diferida

Agregar strings o aridad a `shapeGuard` rompería su superficie exacta y el
contrato sin payload. Tampoco se justifica un framework general de panic. La
tabla interna obtiene el mínimo necesario sin nueva sintaxis.

## 8. Contrato elegido y cambios mínimos futuros

1. Agregar metadata interna de sitio a guards/traps de shape.
2. Retener operación, span, source lógico y contrato canónico.
3. Reusar operandos de extents únicamente cuando no haya reevaluación.
4. Emitir reporter privado best-effort en stderr antes de `llvm.trap`.
5. Mantener señal, no unwind y no cleanup.
6. Hacer que la CLI muestre señal/nombre y conserve exit 1.
7. Calificar por separado runtime/semántica y presentación CLI.

No se requiere exception record, class nueva, cambio de Linear Algebra API,
runtime público, signal handler ni conversión signal-to-trap.

## 9. Riesgos

- El source exacto debe convertirse en texto canónico reproducible sin paths
  absolutos.
- Capturar extents no puede evaluar dos veces ni prolongar borrows source.
- Metadata y formatting incrementan tamaño estático; deben medirse.
- O2 no puede fusionar sitios perdiendo mensajes.
- Un reporter de emergencia no puede asignar ni lanzar.
- La CLI debe distinguir señal de exit ordinario del mismo número convencional.

Las mitigaciones y verificaciones obligatorias están cerradas en el documento
normativo.

## 10. Qualification propuesta

La matriz normativa incluye:

- compatible, matriz no square, RHS incompatible, producto y dot incompatibles;
- O0/O2, directo y CLI;
- exit code, señal, stdout y stderr exactos;
- ausencia de falsos diagnósticos;
- preservación de `SingularMatrixException` y
  `RankDeficientMatrixException`;
- exception uncaught status 70 sin contaminación;
- ausencia de catch/unwind/finally/cleanup nuevos;
- fail-before-allocation/access y evaluación única;
- IR, corruption tests y reporter best-effort.

Los asserts de wording/exit de CLI quedan fuera de los tests semánticos. Los
tests CLI no deducen categoría desde señales.

## 11. Validación de esta fase

No corresponde modificar ni ejecutar una suite de implementación para cerrar
la arquitectura. La evidencia funcional se obtuvo con reproducciones O0/O2 y
la evidencia estructural mediante inspección de source/tests vigentes. Después
de crear los documentos se exige `git diff --check` y verificación de que el
worktree sólo suma estos dos entregables propios.

## 12. Bloqueos pendientes

No hay bloqueo arquitectónico. Quedan detalles internos del futuro vertical:
tipo Rust de la tabla, pretty-print exacto, límite de observaciones y tabla de
señales. Ninguno requiere cambiar la clasificación abortiva elegida.

Se identifica el origen del diagnóstico opaco y existe una estrategia
implementable sin contradicción semántica. Estado final:
**ARCHITECTURE CLOSED; NO IMPLEMENTADA**.
