# SHAPE-CONTRACT-DIAGNOSTICS-ARCH-1 — diagnóstico abortivo por sitio

Estado: **ARCHITECTURE CLOSED; NO IMPLEMENTADA**, 2026-11-23.

Este milestone es exclusivamente documental. No modifica compiler-next,
runtime, CLI, STD, `linearAlgebra`, ejemplos, tests ni contratos de exceptions,
traps u ownership.

## 1. Decisión

Las violaciones dinámicas de shape conservan el trap abortivo y no capturable
`ShapeMismatch`. Antes de ejecutar el `llvm.trap` terminal, el ejecutable debe
emitir en stderr un diagnóstico best-effort, no asignante y específico del
sitio que identifique:

- categoría `ShapeMismatch`;
- operación fuente;
- contrato que falló;
- ubicación lógica fuente;
- valores ya calculados de los extents cuando puedan transportarse sin volver
  a evaluar expresiones.

No se crea `DimensionMismatchException`, no se convierte el trap en exception,
no se agrega unwind y no se promete cleanup de owners todavía vivos. La
superficie cerrada permanece exactamente:

```aether
shapeGuard(condition);
```

con un único `bool`, evaluación única y el mismo ordering. El cambio es de
metadata diagnóstica interna y del fail path, no de semántica source ni API
pública.

La CLI no es autoridad de la causa. En Unix debe describir la señal real cuando
`ExitStatus::code()` sea `None`, conservar status CLI 1 y no clasificar una
señal como un trap Aether. El diagnóstico de contrato debe haber sido escrito
por el artefacto antes de la señal.

## 2. Autoridades preservadas

Esta decisión compone sin reemplazar:

- `SHAPE-GUARD-ARCH-1` y `SHAPE-GUARD-V1`: statement global, un `bool`,
  `ShapeMismatch`, fail edge abortivo, sin payload source ni unwind;
- `LINEAR-ALGEBRA-SOLVE-ARCH-1`: matriz square y RHS compatible son
  precondiciones abortivas; singularidad continúa siendo
  `SingularMatrixException`;
- el contrato semántico V1, sección 8.2: el trap es estructurado en MIR/SSA y
  puede bajar a target trap con diagnóstico y terminación no exitosa;
- `EXCEPTION-ARCH-2` y EXCEPTION-V1..V4: los traps no entran a `catch`, no usan
  el record EH y no adquieren cleanup/finally;
- `UNCAUGHT-EXCEPTION-DIAGNOSTICS-V1`: sólo exceptions Aether que escapan del
  entry usan `Unhandled <type>` y status 70;
- `CLI-ARCH-1`: un programa terminado por señal produce status CLI 1 con un
  diagnóstico, sin reescritura de stdout/stderr del programa.

`ShapeMismatch` sigue siendo una violación de contrato. La ausencia actual de
texto no autoriza reclasificarla como fallo matemático recuperable.

## 3. Diagnóstico normativo

En el target bootstrap Linux x86-64, un sitio con metadata completa escribe una
sola línea UTF-8:

```text
Aether trap: ShapeMismatch at <source>:<line>:<column> in <operation>: <contract> [<observation>=<value>, ...]\n
```

Ejemplo conceptual para el reproducer:

```text
Aether trap: ShapeMismatch at linearAlgebra/src/lib.ae:449:5 in linearAlgebra.solve: dimension(*b) == rows(*A) [dimension(*b)=1, rows(*A)=2]
```

Reglas:

1. `<source>` es el nombre lógico de sesión, nunca un path absoluto ni el CWD.
2. `<operation>` usa identidad nominal source-facing; no usa mangling.
3. `<contract>` es una representación canónica del predicado fuente o, para
   kernels nativos, un texto estático propiedad de ese dominio.
4. Las observaciones sólo contienen escalares ya materializados por el check.
   No se reejecuta `rows`, `columns`, `dimension`, `length` ni una call general.
5. Si no existe una captura segura, se omiten los corchetes. El diagnóstico
   todavía debe incluir operación, contrato y ubicación.
6. El orden de observaciones es el orden fuente/semántico del check.
7. stdout no recibe bytes. stderr lleva un LF final.
8. Un error o short write aplica política best-effort y no evita el trap.

Para condiciones directas comparables, el texto y los nombres hacen visible la
relación en vez de inventar roles universales `expected`/`actual`. Por ejemplo,
`rows(A) == columns(A)` tiene dos observaciones de la misma matriz, mientras
que `dimension(b) == rows(A)` permite reconocer RHS observado y orden esperado.
El dominio puede usar labels `expected`/`observed` sólo cuando su contrato los
define inequívocamente.

La primera implementación no necesita capturar valores para condiciones
arbitrarias, calls con efectos, conjunciones ni predicados que no puedan
descomponerse preservando evaluación única. El fallback estático es obligatorio;
las capturas son una mejora condicionada a prueba estructural de no reevaluación.

## 4. Flujo y punto de pérdida actual

```text
linearAlgebra.solve / dot
  -> shapeGuard(bool)
  -> HIR ShapeGuard { condition, ShapeMismatch, span }
  -> MIR ShapeGuard { bool, success, failure, trap, span }
  -> SSA ShapeGuard { bool, success, failure, trap, span }
  -> failure: Trap(ShapeMismatch)
  -> backend: shared trap_shape_mismatch
  -> llvm.trap + unreachable
  -> Linux: SIGILL (4), sin stdout/stderr
  -> driver: ExitStatus { code=None, signal=4 }
  -> CLI: descarta la señal concreta y retorna 1 con texto genérico
```

La información se degrada en dos fronteras distintas:

- antes/durante lowering, `shapeGuard` conserva sólo el `bool` final y el span;
  no conserva el contrato legible ni los operandos/extents que lo produjeron;
- en LLVM, todos los `ShapeMismatch` de una función convergen en una etiqueta
  que sólo llama `llvm.trap`; el proceso no emite categoría ni sitio;
- la CLI recibe únicamente el resultado de proceso. Una señal no puede
  reconstruir categoría, operación o dimensiones porque varios traps usan el
  mismo mecanismo físico.

Por ello cambiar sólo el mensaje de la CLI no resuelve F3.

## 5. Metadata interna por sitio

El programa verificado incorpora una tabla interna conceptual:

```text
TrapDiagnosticSite {
    kind: ShapeMismatch,
    operation: SourceOperationIdentity,
    source_name: LogicalSourceName,
    span: Span,
    contract_text: StaticUtf8,
    observation_labels: [StaticUtf8],
}
```

`HirStmtKind::ShapeGuard`, `Terminator::ShapeGuard` y
`SsaTerminator::ShapeGuard` conservan un `TrapDiagnosticSiteId` además de sus
campos vigentes. MIR/SSA pueden asociar una lista acotada de operandos escalares
de observación al sitio. No es un payload source, un objeto runtime ni una
exception.

La sesión ya posee `SourceId`, nombre/texto de `SourceFile`, identidad de
función y spans. El frontend debe construir el sitio desde esas autoridades
antes de descartar el texto fuente. No se deriva desde LLVM, mangling, paths
físicos ni heurísticas por nombre de package.

Los verificadores recalculan como mínimo:

- site id existente y único para el sitio semántico;
- `kind == ShapeMismatch` y span idéntico al guard;
- operación propietaria coherente con la función;
- strings estáticos válidos y sin NUL requerido;
- cantidad/tipos de observaciones admitidos;
- definición y dominance de cada operando SSA;
- ninguna evaluación adicional atribuible al diagnóstico;
- failure block vacío de trabajo source, sin unwind y terminado por el mismo
  `ShapeMismatch`.

La metadata de presentación no decide control flow. Si se corrompe, la
verificación falla cerrada antes del backend.

## 6. Captura sin coste semántico

Para un predicado directo sobre extents, el lowering puede materializar una vez
los operandos, construir el `bool` y mantener esos mismos valores vivos sólo
hasta el fail edge:

```text
left  = dimension(b)
right = rows(A)
condition = left == right
ShapeGuard(condition, observations=[left, right])
```

Está prohibido clonar el árbol de expresión para obtener observaciones. Si una
descomposición puede cambiar efectos, traps, borrow lifetime, orden o número de
evaluaciones, el sitio usa el fallback sin valores.

Los kernels matemáticos nativos no pasan por `shapeGuard`, pero ya materializan
extents para sus checks estructurados. Sus productores de IR pueden registrar
el mismo tipo de sitio con contrato propiedad del kernel, por ejemplo:

```text
matrix multiplication requires columns(left) == rows(right)
```

Esto comparte transporte y reporter, no fusiona la autoría de mensajes ni
supone que todo `ShapeMismatch` nació en Linear Algebra.

En el happy path no hay call, write, formatting ni allocation adicional. Los
extents observados ya eran necesarios para la comparación. La única posible
diferencia física es liveness hasta el fail edge y metadata estática; debe
medirse en qualification.

## 7. Backend y reporter privado

Cada fail edge diagnosticable emite:

1. una call a un helper LLVM `internal nounwind` de reporte;
2. el mismo `llvm.trap` vigente;
3. `unreachable`.

El helper reutiliza la primitive privada length-aware de escritura a fd 2 ya
calificada por el diagnóstico de exceptions, pero su emisión no debe arrastrar
EH, class descriptors ni `__cxa_*` a programas exception-free. Los enteros
observados se convierten a decimal en un buffer de stack de tamaño acotado; no
se usa heap, `string`, formatting Aether, STD ni locale.

No se crea símbolo público, ABI de errores, record de unwinding ni dependencia
entre módulos precompilados. En el modelo actual todo el grafo source se genera
y enlaza conjuntamente; el helper y las constantes son privados y deduplicables.

El write es efecto observable y debe permanecer antes del trap en O0/O2. Un
optimizer puede eliminar el sitio completo sólo si prueba que el fallo es
inalcanzable. No puede compartir sitios perdiendo su identidad ni mover el
reporte al success path.

## 8. Terminación y CLI

La terminación directa permanece abortiva. En el target observado:

- binario directo: `code=None`, `signal=4` (`SIGILL`), stderr diagnóstico;
- `aether run`: el hijo escribe el mismo stderr, la CLI informa después la
  señal y retorna 1 conforme a CLI-ARCH-1.

Texto CLI Unix recomendado:

```text
aether: error: program terminated by signal 4 (SIGILL)
```

La CLI obtiene el número mediante `ExitStatusExt::signal`; el nombre puede ser
una tabla target-specific pequeña con fallback numérico. No captura ni reordena
stdout/stderr y no suprime el diagnóstico del hijo. No imprime
`ShapeMismatch`, porque `SIGILL` no identifica el `TrapKind`.

Un retorno ordinario de 132 sigue siendo un exit code ordinario. Una señal 4
continúa produciendo status CLI 1, no 132. En targets sin señal representable se
mantiene un fallback equivalente al texto vigente. Esta mejora de presentación
no cambia la semántica general de termination.

## 9. Alternativa B: excepción nominal

Crear `DimensionMismatchException` permitiría payload, catch, unwind y cleanup,
pero se rechaza para las APIs existentes:

- contradice los contratos CLOSED que clasifican shapes dinámicos como
  `ShapeMismatch` abortivo;
- cambia qué bloques `catch(Exception)` pueden observar;
- cambia las garantías de `finally` y destrucción de owners;
- introduce exceptional edges/calls y coste/code size en APIs hoy trap-only;
- obliga a decidir payload y compatibilidad de todas las APIs públicas;
- confunde precondiciones con resultados matemáticos recuperables.

`SingularMatrixException` y `RankDeficientMatrixException` no son precedentes
para esta conversión: representan outcomes algorítmicos de inputs con shape
válida. Permanecen nominales, capturables y con unwind.

Una futura API explícitamente checked podría declarar una excepción o resultado
de dimensión y validar antes de ejecutar una operación trapping. Sería una API
nueva y una decisión normativa independiente; no puede capturar ni reanudar
después de `llvm.trap`.

## 10. Alcance transversal

Se comparte sólo el transporte mínimo:

- tabla de sitio estática;
- writer privado best-effort;
- formatting decimal no asignante en fail path;
- preservación de sitio y observaciones en IR;
- presentación de señal en CLI.

Cada dominio conserva categoría, contrato y disponibilidad de valores:

| Dominio | Mensaje/observaciones posibles | Política |
|---|---|---|
| shape | operación, relación de extents, extents ya calculados | primer vertical |
| bounds | índice y extent ya calculados | candidato posterior |
| overflow | operación/tipo; operandos sólo si ya disponibles | candidato posterior |
| allocation | size solicitado/categoría sin intentar asignar | candidato posterior |
| invariantes internas | categoría y sitio seguro; evitar leer estado corrupto | separado |

No se crea un framework source general, `panic(message)`, custom traps, registry
dinámico, reflection ni handler de señales. Cada ampliación exige su propia
qualification y no puede atribuir a un trap datos que el IR no posee.

## 11. Qualification futura

### 11.1 Tests semánticos/runtime

| Caso | Evidencia requerida en O0 y O2 |
|---|---|
| solve 2x2 + RHS length 2 | éxito, stderr vacío, sin reporter ejecutado |
| solve no square | `ShapeMismatch`, contrato square y dos extents correctos |
| solve 2x2 + RHS length 1 | contrato RHS, valores 1 y 2, fail antes de LU/allocation |
| producto matricial incompatible | contrato del kernel nativo, no texto de solve |
| dot de dimensiones distintas | contrato de `linearAlgebra.dot`, valores correctos |
| shapes compatibles vacías/no vacías | sin falso diagnóstico |
| condición guard con efectos | evaluación exactamente una vez |
| fallo al escribir stderr | igualmente termina por el trap original |
| `try/catch(Exception)` alrededor del mismatch | no captura el trap |
| `try/finally` alrededor del mismatch | sin nueva garantía de finally |
| singular LU | captura `SingularMatrixException`, sin texto de trap |
| rank deficient QR | captura `RankDeficientMatrixException`, sin texto de trap |
| exception uncaught | `Unhandled <type>`, status 70, sin texto de trap |
| IR | site id/span/kind/observaciones en HIR/MIR/SSA y write antes de trap |
| corrupciones | site/kind/span/operando/dominance inválidos rechazados |
| ownership | ausencia de unwind/cleanup edge nuevo; fail-before-work preservado |

### 11.2 Tests de presentación/proceso

| Invocación | stdout | stderr | resultado |
|---|---|---|---|
| binario directo mismatch | vacío | línea de trap exacta | señal target, hoy SIGILL 4 |
| `aether run` mismatch | vacío | línea trap + línea señal CLI | exit 1 |
| binario directo compatible | aplicación | vacío | exit ordinario |
| `aether run` compatible | aplicación | vacío | status del programa |
| programa retorna 132 | según programa | sin señal CLI | exit 132 |
| proceso recibe otra señal | preservado | sólo descripción real de señal | exit CLI 1 |

Los tests de semántica no deben hacer asserts sobre wording CLI. Los tests CLI
no deben inferir `TrapKind` desde la señal. Las pruebas directas usan artefactos
retenidos de `aether build`; las de CLI usan el temporal de `aether run`.

## 12. Plan de implementación

1. Fijar `TrapDiagnosticSite` y su tabla interna, sin nueva sintaxis.
2. Retener identidad de operación, source lógico, span y contrato canónico en
   HIR; calificar fallback sin observaciones.
3. Preservar site id y capturas seguras en MIR/SSA con verificación fail-closed.
4. Instrumentar primero `shapeGuard` y los productores nativos de
   `ShapeMismatch`, sin tocar otros trap kinds.
5. Emitir writer/reporter privado, estáticos y formatting de extents sólo en
   fail paths; mantener `llvm.trap` terminal.
6. Hacer signal-aware la presentación Unix de `aether run`, conservando exit 1.
7. Agregar matrices semántica/runtime y CLI separadas en O0/O2.
8. Ejecutar suites shape, Linear Algebra, exceptions, ownership, CLI y gates de
   workspace; publicar reporte V1 separado.
9. Evaluar otros trap kinds en milestones posteriores, no dentro de F3.

## 13. Riesgos y mitigaciones

- **Reevaluación accidental:** observaciones sólo reutilizan valores del check;
  el verifier rechaza capturas sin definición/dominance válida.
- **Code size:** constantes deduplicables y un helper privado por módulo final;
  medir O0/O2 antes de ampliar otros traps.
- **Paths no reproducibles:** usar source lógico, nunca path absoluto.
- **Divergencia O0/O2:** write es side effect; goldens nativos cubren ambos.
- **Confusión señal/trap:** sólo el ejecutable nombra `TrapKind`; la CLI nombra
  exclusivamente la señal.
- **Reporter que falla:** no allocation, `nounwind`, writes best-effort y trap
  incondicional posterior.
- **Promesa falsa de cleanup:** docs y tests verifican ausencia de unwind y
  finally obligatorio.
- **Mensajes demasiado generales:** autoría de contrato permanece en cada
  productor; no se usa un texto único para todo `ShapeMismatch`.

## 14. Bloqueos y cierre

No queda un bloqueo semántico para implementar la solución elegida. Deben
resolverse durante el vertical, sin reabrir la decisión:

- representación Rust concreta de la tabla/site id;
- pretty-print canónico exacto y escape de snippets;
- límite inicial de observaciones;
- tabla de nombres de señales soportadas por target.

Son detalles de implementación calificables. La causa opaca está localizada y
la estrategia preserva traps, exceptions, ownership y CLI-ARCH-1 sin nueva ABI
pública. Por ello este milestone se declara **ARCHITECTURE CLOSED**.
