# Aether — COMPOUND-ASSIGNMENT-ARCH-1 — Reporte

Estado: **ARCHITECTURE CLOSED**

Fecha: 2026-11-27

Autoridad inspeccionada: `compiler-next` en `5e1360694c65`

## 1. Resultado

Se cerró el contrato arquitectónico de `+=`, `-=`, `*=`, `/=` y `%=` en
`COMPOUND_ASSIGNMENT_ARCH_1.md`. No se implementó sintaxis ni código productivo y
no se inició `COMPOUND-ASSIGNMENT-V1`.

La arquitectura queda cerrada porque define sin ambigüedad:

- forma fuente statement-only y ausencia de valor/chaining;
- tabla V1 limitada a escalares numéricos built-in y aliases transparentes;
- cobertura exacta de Places ya escribibles por asignación simple;
- orden destino/check/load/RHS/operator/store;
- identidad y lifetime de Place estabilizado;
- invalidación, aliasing, ownership y mutation effects;
- comportamiento ante throw y trap sin prometer rollback;
- representación HIR/MIR/SSA verificable y lowering LLVM sin opcode nuevo;
- verificadores independientes, corrupción adversarial y qualification.

## 2. Evidencia inspeccionada

Se revisaron como autoridad:

- `docs/reports/CORE_OPERATORS_AND_ASSIGNMENT_AUDIT_1.md`;
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`;
- `compiler-next/crates/aether-frontend/src/hir.rs`;
- `compiler-next/crates/aether-middle/src/mir.rs`;
- `compiler-next/crates/aether-middle/src/ssa.rs`;
- los contratos de assignment, Place, Copy/Move, `ReplaceString`,
  `ReplaceOwned`, mutation effects, invalidation, borrow regions, checked
  arithmetic y traps alcanzados desde esos módulos.

Hechos determinantes:

1. HIR, MIR y SSA ya preservan una ruta de Place estructurada.
2. Los fields escalares de class usan el camino dedicado
   `ClassOp::FieldRead/FieldWrite`; `ClassField` como base del Place genérico tiene
   el contrato distinto de storage interior indexable.
3. MIR captura receiver/reference/índices como operandos, pero assignment simple
   baja actualmente RHS antes de `lower_place`.
4. Los operadores escalares ya seleccionan operaciones checked/IEEE concretas;
   middle-end no necesita reinferir tipos.
5. `MutationEffect` diferencia element mutation, structural stable y potentially
   relocating, mientras `InvalidationShape` cubre slots/rangos.
6. Copy scalar evita Move, partial move, Drop y replacement owning.
7. Los verificadores existentes ofrecen el patrón fail-closed necesario, pero una
   secuencia de load/store común perdería la relación semántica demasiado pronto.

No se consultó una implementación legacy como autoridad.

## 3. Decisiones de cierre

### Tipado

El operador compuesto reutiliza el resolver del binario correspondiente y exige que
su resultado canónico sea exactamente el tipo canónico del destino. No se crea
narrowing implícito. `%=` queda limitado a integers.

Whole String/Vector/Matrix, owners, genéricos y lifecycle quedan fuera. Sí se
admiten elementos escalares de containers y fields escalares cuando el mismo Place
ya es válido para `=`.

### Evaluación e invalidación

La ubicación se estabiliza y comprueba antes del load y antes del RHS. La región
protege validez de storage, slot y lifetime, pero no introduce exclusividad general
para `ref mut`.

Una escritura RHS que preserve ubicación puede ocurrir incluso sobre el mismo slot;
el compound commit usa el old capturado y gana al final. Crecimiento/realloc,
reducción/reordenamiento invalidante, reemplazo, Move o Drop del root se rechazan
cuando alcanzan la misma provenance. Efectos desconocidos con acceso posible al
root fallan cerrado.

### Fallos

Bounds y acceso fallan antes de ejecutar RHS. Throw del RHS o trap aritmético omite
el compound store. Los efectos ya ejecutados por el RHS no se revierten. Esto evita
la ambigüedad entre "no escribir el resultado" y una transacción con rollback, que
Aether no ofrece.

### IR

HIR conserva `CompoundAssign`. El destino middle-end es una suma cerrada entre el
Place estructural general y el field escalar de class dedicado; no se confunden dos
contratos actuales diferentes. MIR y SSA mantienen un id, compound load y compound
commit asociados a la misma identidad hasta la última verificación. El binary plan
sigue usando operaciones existentes. LLVM recibe load/FieldRead, checks, aritmética
y store/FieldWrite ordinarios; no se justifica una operación de backend nueva.

## 4. Deuda registrada

La asignación simple conserva su orden vigente RHS→operandos dinámicos del destino.
Compound assignment fija destino/check/load→RHS. La diferencia queda documentada
como deuda de coherencia y no fue alterada por este milestone.

También quedan para implementación, sin reabrir la semántica:

- codificación Rust concreta de los records middle-end;
- precisión del resumen interprocedural de efectos; un caso no probado debe
  rechazarse conservadoramente;
- elección entre keepalive explícito o prueba equivalente para class receivers;
- wording/códigos finales de diagnósticos.

Los operadores `++`, `--`, bitwise, shifts y `**=` no fueron habilitados. El diseño
sólo reserva una ruta de extensión.

## 5. Qualification exigida

El futuro milestone de implementación deberá demostrar:

- parsing statement-only y negativos expresivos;
- tipado exacto para todas las familias escalares y aliases;
- evaluación única y orden observable en todos los Place shapes;
- protección correcta frente a cada `MutationEffect`/`InvalidationShape`;
- no-store en paths de bounds, throw y trap;
- invariantes HIR/MIR/SSA mediante tests de corrupción independientes;
- paridad semántica `-O0`…`-O3` y ausencia de backend unchecked;
- ninguna regresión ni ampliación accidental de assignment simple.

## 6. Higiene del trabajo

Se preservaron los cambios personales preexistentes. No se ejecutaron commit,
push, reset, clean ni stash. El alcance de este cierre son exclusivamente los dos
documentos de arquitectura solicitados.
