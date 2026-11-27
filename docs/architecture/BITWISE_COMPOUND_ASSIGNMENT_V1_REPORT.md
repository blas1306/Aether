# Aether — BITWISE-COMPOUND-ASSIGNMENT-V1 report

Estado: **CLOSED**

Fecha: 2026-11-27

Base inspeccionada: `934138dfbc2b28a5c7aca86953fda044e4b6739f`

## 1. Semántica y superficie

Se implementaron `&=`, `|=`, `^=`, `<<=` y `>>=` exclusivamente como
statements. El lexer aplica maximal munch sin cambiar `&`, `|`, `^`, `<<`,
`>>`, `&&`, `||` ni los operadores anteriores. Los usos expresivos y chaining
se rechazan; no se agregaron `**=`, incremento prefijo, wrapping ni operaciones
bitwise sobre aggregates.

Los cinco operadores reutilizan `HirStmtKind::CompoundAssign` y la transacción
identificada `CompoundLoad`/`CompoundCommit`. Destino, referencia, receiver e
índices se estabilizan y cargan antes del RHS. El old capturado alimenta el
binario y sólo el resultado normal llega al commit único. Los efectos previos
del RHS no se revierten si después ocurre un trap.

## 2. Tipado

El destino debe ser un escalar entero nativo escribible o un alias transparente.
AND/OR/XOR exigen el mismo `TypeId` canónico en destino y RHS después de la
resolución contextual; no heredan el widening de los binarios ordinarios.

En shifts, el RHS conserva cualquiera de los diez tipos enteros nativos. No se
convierte al tipo del destino ni a `usize`. El destino fija tipo, ancho,
signedness y resultado. La operación HIR concreta representa de forma explícita
la distinción: `ShiftLeftChecked`, `ShiftRightArithmetic` o
`ShiftRightLogical`; los verificadores permiten un RHS heterogéneo sólo para
estas variantes.

## 3. IR, traps y backend

HIR vuelve a comprobar writability, clase nominal, tipo de destino, tipo RHS,
operador y signedness. MIR baja el destino estable a un `CompoundLoad`, evalúa
el RHS y emite el mismo `BinaryOp` usado por BITWISE-OPERATORS-V1. MIR y SSA
reconstruyen el contrato del binario, identidad y tipo load/commit, dependencia
respecto de old, cardinalidad, CFG excepcional y protección de provenance.

AND/OR/XOR no tienen trap. Ambos shifts validan primero el count y producen
`ShiftCountOutOfRange` si es negativo o no menor que el ancho. `<<=` valida a
continuación representabilidad y produce `IntegerOverflow` si corresponde. El
commit queda después de ambos guards. LLVM reutiliza `and`, `or`, `xor`, `shl`,
`ashr` y `lshr`, además del pointer estabilizado por compound assignment. No se
agregaron `nsw`, `nuw`, `exact`, counts enmascarados ni truncamientos fuente.

## 4. Lifetime, aliasing y excepciones

Se conservan sin cambios la provenance, protección de backing, keepalive/ARC y
clasificación de invalidaciones de COMPOUND-ASSIGNMENT-V1. Un RHS puede escribir
el mismo slot escalar o uno distinto sin crear exclusividad: el commit calcula
con el old capturado y gana al final. Reemplazo o mutación estructural capaz de
invalidar el destino se rechaza. Trap, throw o unwind anteriores al commit no
publican resultado y no revierten efectos ya ocurridos en el RHS.

## 5. Qualification

La suite `bitwise_compound_assignment_v1.rs` cubre los cinco operadores, diez
tipos enteros, aliases, RHS exacto inválido, counts heterogéneos, signedness,
guards de count/overflow, locales, fields de struct/class, Array/List/Buffer,
Vector/Matrix, ViewMut, `ref mut`, read-only, evaluación transaccional, aliasing
del mismo slot, invalidación estructural, corrupción independiente HIR/MIR/SSA
y ejecución nativa O0/O2.

Resultados observados:

- suite focal: **PASS — 7/7**, con ejecución nativa O0/O2;
- regresión BITWISE-OPERATORS-V1: **PASS — 7/7**;
- regresión COMPOUND-ASSIGNMENT-V1: **PASS — 16/16**;
- Compiler Core: **PASS — 14/14**;
- Language Conformance: **PASS — 78/78**;
- diferencial oficial: **PASS — 96/96**, `mode=official checked=96
  failures=0`;
- `cargo check --workspace`: **PASS**;
- `cargo fmt --all --check`: **PASS**;
- `cargo clippy --workspace --all-targets`: **PASS con warnings históricos no
  bloqueantes**;
- `git diff --check`: **PASS**.

OAL Integration: **NOT RUN**. Full Ecosystem: **NOT RUN**. No se infiere el
estado de esos perfiles a partir de suites focales o Conformance.

La suite cerrada `bitwise_operators_v1.rs` sólo retira del corpus negativo el
programa statement `x&=1`, porque ésa era una exclusión expresa de
BITWISE-OPERATORS-V1 que este milestone posterior reemplaza. El `assert!` del
corpus no se eliminó, relajó ni sustituyó y las otras expectativas permanecen
idénticas. La aceptación de compound assignment queda cubierta por la nueva
suite focal; mantener la expectativa negativa anterior haría contradictorios
los dos contratos. No se alteró ninguna otra assertion de la suite cerrada.

`bitwise_compound_assignment_v1` está clasificada como integración de
conformance observable en los perfiles Conformance y Full. La validación del
manifest confirma que Conformance la ejecuta, que ninguna integración anterior
quedó sin clasificar y que Full conserva como autoridad agregada el comando
literal `cargo test --workspace -j 1 --no-fail-fast`.

## 6. Exclusiones

No se implementaron nuevos mecanismos de ownership, aliasing, MemorySSA o
rollback; tampoco operadores heterogéneos generales, overloads bitwise,
potenciación, wrapping ni bitwise elementwise sobre aggregates.

## 7. Archivos modificados

- `compiler-next/crates/aether-frontend/src/{lexer,ast,parser,hir}.rs`;
- `compiler-next/crates/aether-middle/src/mir.rs`;
- `compiler-next/crates/aether-driver/tests/{bitwise_operators_v1,bitwise_compound_assignment_v1}.rs`;
- `compiler-next/tests/qualification.toml`;
- `docs/architecture/{AETHER_V1_SEMANTIC_CONTRACT,BITWISE_COMPOUND_ASSIGNMENT_V1_REPORT}.md`.

Los cambios personales preexistentes observados en `examples/` y `docs/reports/`
se preservaron. No se hizo reset, clean, stash ni push.
