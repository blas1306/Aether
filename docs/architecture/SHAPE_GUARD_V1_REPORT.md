# SHAPE-GUARD-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-28.

Autoridad normativa:

- [SHAPE-GUARD-ARCH-1](SHAPE_GUARD_ARCH_1.md);
- [SHAPE-GUARD-ARCH-1-REPORT](SHAPE_GUARD_ARCH_1_REPORT.md).

## Resultado

Se implementó la primitiva global reservada y statement-only:

```aether
shapeGuard(condition);
```

La forma reutiliza el statement de call existente; no agrega keyword. Admite
exactamente un argumento de tipo canónico `bool`, no admite argumentos de tipo,
calificación, forma método, uso como valor ni shadowing/redeclaración efectiva.
Los rechazos de esta superficie usan el diagnóstico compacto `E0473`, salvo el
diagnóstico de conversión ordinario que pueda producir el operando no booleano.

La condición se evalúa una vez y se materializa antes de ramificar. `true`
continúa por el success edge. `false` alcanza exclusivamente el trap
estructurado `ShapeMismatch`. Los efectos, calls y traps producidos al evaluar
la condición conservan su semántica y preceden al guard; no existe captura,
conversión a Exception, unwind del guard, payload, mensaje ni allocation.

## Representación y verificación

HIR incorpora `HirStmtKind::ShapeGuard { condition, trap }`, con
`HirTrapKind::ShapeMismatch` y el span completo del statement. El nodo es
independiente de `MathStep::ShapeGuard`. El verificador HIR recalcula tipo,
trap, origen statement source, span y validez/ownership de la expresión.

MIR incorpora el terminator explícito:

```text
ShapeGuard { condition, success, failure, trap, span }
```

La evaluación ordinaria de la condición termina en una materialización `bool`
única inmediatamente anterior al terminator. El fail block es canónico, vacío,
sin landing pad ni unwind, tiene sólo el guard como predecesor y termina en
`Trap(ShapeMismatch)`. El success block es distinto, canónico y único camino a
los statements posteriores. El verificador rechaza corrupción de operando,
materialización, targets, trap, fail block y span.

SSA preserva `SsaTerminator::ShapeGuard` sin convertirlo en branch genérico. Su
verificador vuelve a comprobar de forma independiente tipo, definición,
dominance, materialización, targets/predecessors, identidad del trap, fail
block sin phis/instrucciones, ausencia de unwind y span.

## Backend y optimización

LLVM baja el terminator a una rama condicional. El failure block usa el
`SsaTerminator::Trap(ShapeMismatch)` existente y por tanto converge en:

```text
trap_shape_mismatch
llvm.trap
unreachable
```

No se agregó helper `aether_shape_guard`, ABI, runtime, allocation ni dispatch
por package. No existe actualmente un pass general apropiado para folding de
este control flow; por decisión V1, `ShapeGuard` permanece explícito en dumps
HIR/MIR/SSA tanto en O0 como en O2. El folding queda como trabajo futuro y no
se introdujo una optimización ad hoc.

## Calificación

Las pruebas nuevas cubren:

- `true`/`false` y la ruta exacta `ShapeMismatch` en O0/O2;
- evaluación única y ordering antes/dentro/después;
- fallo antes de allocation, indexing, división y call posterior;
- preservación de `DivisionByZero` originado dentro de la condición;
- fin de borrow temporal antes de la continuación;
- relaciones arbitrarias de `rows`, `columns` y `dimension`, con extents cero;
- package ordinario y consumer separado;
- diagnostics de tipo, aridad, type arguments, valor, forma qualified/method y
  shadowing/redeclaración;
- presencia explícita en HIR/MIR/SSA y ausencia del helper prohibido;
- corrupciones HIR/MIR/SSA de tipo, trap, targets, fail block, span y marcas de
  unwind/landing pad.

También quedaron verdes las regresiones existentes de `Matrix.add`, slice
assignment y operaciones matemáticas que producen `ShapeMismatch`. La revisión
del diff confirma que la implementación no consulta nombres de `linearAlgebra`,
`linearAlgebra`, `solve`, `OAL`, `Matrix` ni `Vector`. La búsqueda sobre líneas
agregadas del código productivo sólo encuentra nombres `Matrix*` en el reflow
de rustfmt de la lista pública preexistente de exports; no hay branch, lookup,
path ni comportamiento nuevo asociado a esos nombres.

Validación ejecutada desde `compiler-next` cuando corresponde al workspace
Cargo:

```text
cargo test --workspace                                      PASS
cargo fmt --all --check                                    PASS
cargo clippy --workspace --all-targets -- -D warnings      PASS
git diff --check                                           PASS
bash compiler-next/tests/run-differential.sh               PASS (21, 0 fallos)
```

`solve` no fue implementado ni modificado.
