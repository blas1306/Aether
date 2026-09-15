# ITERATION-V1 — `int` range `for-in` nativo

Estado: **IMPLEMENTADO** en `compiler-next`, perfil nativo Linux x86-64,
2026-09-15.

Documento normativo: [ITERATION_ARCH_1.md](ITERATION_ARCH_1.md).

## Superficie admitida

ITERATION-V1 admite exclusivamente `for (binding in range)` con las formas
`start:end` y `start:step:end`. El binding puede inferirse o escribirse como
`int name`; operands, item y binding se cierran al TypeId canónico `int64`.
Ranges de float u otros enteros, valores Range almacenados y `for-in` sobre
Array/List siguen fallando cerrado.

El AST conserva `AstForBinding` y los dos o tres operands de `AstExprKind::Range`
sin fabricar el step implícito. HIR materializa `HirStmtKind::ForRange` con
`LoopId`, LocalId del binding, TypeIds exactos, operands en orden, evidencia de
step implícito y body léxico. El binding entra en scope sólo para el body y
puede shadowear un binding exterior.

## Semántica y CFG

Start, step y end se evalúan y capturan exactamente una vez, de izquierda a
derecha. El step omitido se materializa después de los dos operands fuente como
`int64(1)`. Un step constante cero produce E0442; uno dinámico llega al trap
estructurado no capturable `ZeroRangeStep` antes del test de dirección y de la
primera iteración.

El lowering genera preheader, validación, selección de dirección, entradas de
compatibilidad ascendente/descendente, header, body, latch, guards de avance y
exit. Las comparaciones de entrada y del candidato son inclusivas. Una dirección
incompatible salta al exit. `continue` apunta al latch y `break` al exit.

Antes de sumar, el latch compara el current con `INT_MAX-step` para avance
positivo o `INT_MIN-step` para avance negativo. Sólo la rama probadamente
representable ejecuta el add checked; después compara el candidato con end.
Así, alcanzar o cruzar el límite agota el range sin wrap ni trap espurio,
incluidos `INT_MAX:INT_MAX` y el límite `INT_MIN` descendente.

Range no crea objeto iterator, no llama runtime y no asigna heap. Sus tres
scalars se capturan en temporales inline y el estado físico promovible es
current/step/end. La operación `RangeBinding` conserva en SSA la identidad de
la inicialización fresh del binding sin introducir código distinto de una copia
scalar.

## Verificación independiente

HIR verifica LoopId canónico, item/binding/operand `int64`, step implícito +1,
rechazo de cero constante y el body tipado. MIR conserva `RangeLoop` con todos
los bloques del protocolo y `RangeOperand(Start|Step|End)`; su verificador
reconstruye captura única ordenada, zero trap, dirección, header/body/latch/exit,
targets, guards representables, add checked y comparaciones inclusivas.

SSA recibe esa metadata desde MIR verificado pero vuelve a comprobar el CFG y
las operaciones SSA efectivas: identidad de binding, capturas ordenadas,
trap, targets, guards de exhaustion, avances y comparaciones. No existe una
marca `verified_for`; las corrupciones se detectan sobre bloques, operands y
operaciones reales.

LLVM consume sólo VerifiedSsa. `RangeOperand` y `RangeBinding` son copias SSA;
el resto usa branches, phis, comparaciones e intrinsics checked ya existentes.
`ZeroRangeStep` baja directamente a la política fail-fast de `llvm.trap`, sin
helper de range ni conexión a catch/finally.

## Control flow, excepciones y ownership

Nested loops, fallthrough, break, continue y return reutilizan las fronteras de
cleanup existentes. El binding y el estado range son Copy/no-drop. Los owners
creados dentro del body reciben los mismos drops normales, de return y unwind
que en `while`. Throws conservan el ExceptionEvent y los traps no hacen unwind.

La composición de un transfer de loop con finalizers anidados expuso y corrigió
un defecto general previo: el contador de finalizers pendientes de break/
continue incluía finalizers exteriores al loop. Ahora sólo atraviesa los
finalizers abiertos después de entrar al loop; un break no abandona por error
un `try/finally` que contiene al loop. La corrección beneficia también a while.

## Qualification

La suite `iteration_v1` cubre en O0 y O2:

- empty, singleton, ascending, stride y descending;
- direcciones incompatibles constantes y dinámicas;
- INT_MIN/INT_MAX y exhaustion sin overflow;
- step cero constante y dinámico;
- efectos que prueban evaluación única y orden start/step/end;
- break antes del advance, continue con un solo advance y loops anidados;
- scope, shadowing y rechazo del binding después del loop;
- return, throw/catch/finally y cleanup de Buffer durante unwind;
- corrupciones HIR, MIR y SSA;
- ausencia de malloc/free y de helpers/objetos de iteración;
- equivalencia observable O0/O2.

El fixture `tests/programs/iteration_v1_smoke.ae` aporta una ejecución nativa
estable al corpus del repositorio. La qualification final ejecutó sin fallos:
`cargo test --workspace`, `cargo fmt --all --check`,
`cargo clippy --workspace --all-targets -- -D warnings`, `git diff --check` y
`bash compiler-next/tests/run-differential.sh`.

## Límites conservados

No se admiten todavía otros tipos integer, ranges float, iteración de Array/List,
bindings ref, iteración mutable o consuming, custom Iterable/Iterator,
generators, slicing ni comprehensions. Tampoco se publica constructor, fields o
API general de Range en este vertical.
