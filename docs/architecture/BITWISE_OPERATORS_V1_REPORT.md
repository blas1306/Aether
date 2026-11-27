# Aether — BITWISE-OPERATORS-V1 report

Estado: **CLOSED**

Fecha: 2026-11-27

Base: `a3e5f124df6bea1e8e7e4073a55f33306d107bbf`

Autoridad normativa:
[BITWISE_OPERATORS_ARCH_1](BITWISE_OPERATORS_ARCH_1.md).

## 1. Semántica implementada

Se implementaron `&`, `|`, `^`, `~`, `<<` checked y `>>`. AND, OR, XOR y
NOT operan sobre el patrón exacto del entero; signed se reinterpreta en
complemento a dos y no genera overflow. `>>` selecciona `ashr` para signed y
`lshr` para unsigned. `<<` representa el producto matemático por `2^count` y
genera `IntegerOverflow` si el resultado no cabe.

Un count signed negativo o cualquier count mayor o igual al ancho izquierdo
genera `ShiftCountOutOfRange`. Los constantes inválidos se diagnostican en HIR;
los dinámicos conservan guards explícitos.

## 2. Cambios por capa

- Lexer: tokens maximal-munch para `<<`/`>>` y tokens simples para `|`, `^`,
  `~`; se preservan `&`, `&&`, `||`, comparaciones y operadores previos.
- Parser/AST: seis variantes explícitas, asociatividad izquierda y NOT prefijo.
- HIR: tipado entero, selección signedness de `>>`, folding exacto y
  verificación independiente.
- MIR/SSA: opcodes explícitos, count heterogéneo y traps ordenados. Los
  verificadores reconstruyen tipo izquierdo, tipo count, resultado, signedness
  y metadata de traps.
- LLVM: `and`, `or`, `xor`, NOT como XOR con all-ones, `shl`, `ashr` y `lshr`.
  No se emiten flags `nsw`, `nuw` ni `exact`.

## 3. Precedencia efectiva

De mayor a menor:

```text
postfix/primary
! ~ unary- * & &mut
* / %
+ -
<< >>
&
^
|
< <= > >=
== !=
range :
&&
||
```

Los nuevos binarios asocian a izquierda. Range conserva su contrato no
asociativo.

## 4. Tipado y conversiones

Los diez enteros nativos y aliases transparentes están admitidos. AND/OR/XOR
reutilizan el widening entero ordinario y después exigen operandos/resultados
con el mismo `TypeId` canónico. No se mezclan signed/unsigned ni sized/fixed.
NOT preserva exactamente el tipo del operando.

En shifts, el izquierdo determina tipo, ancho y resultado; el count conserva
independientemente cualquiera de los diez tipos enteros. No existe conversión
fuente a `usize` ni al tipo izquierdo. Literales contextuales y aliases siguen
usando la infraestructura existente.

## 5. Guards y traps

El lowering evalúa izquierdo y count una vez y en ese orden. LLVM compara el
count en su representación original: primero negatividad signed, luego
`count < width`. Sólo el bloque válido normaliza exactamente el count.

Para `<<`, el guard de representabilidad calcula el producto en `i128` mediante
doblado checked por construcción después del guard del count; no ejecuta el
`shl` fuente para comprobar overflow. El orden LLVM observado es guard de count,
guard de overflow y recién entonces el único `shl` fuente. Counts inválidos no
alcanzan ningún shift; valores no representables no alcanzan el `shl` final.

## 6. Constant folding

El folding convierte valores a patrones unsigned de N bits, aplica la operación,
enmascara y reinterpreta signed. Los shifts constantes validan count antes de
representabilidad. No se usa overflow de Rust como autoridad y los resultados
se contrastaron con ejecución nativa O0/O2.

## 7. Genéricos y conflictos léxicos

`>>` se divide contextualmente sólo al consumir cierres de tipos, incluidas
firmas `Function`/`Invocable` y lookahead de declaraciones locales. Cada cierre
retiene el byte correspondiente del span original; no se modifica el texto.
Una llamada genérica seguida por `>>` conserva el operador shift. `|` no se
incorporó a la gramática de tipos.

## 8. Verificadores y corrupción

La suite focal corrompe de forma independiente:

- HIR: signedness/opcode de un shift;
- MIR: trap primario de `ShiftLeftChecked`;
- SSA: trap secundario y orden contractual de `ShiftLeftChecked`.

Los tres verificadores rechazan la corrupción antes del backend.

## 9. Qualification final observada

| Gate | Resultado observado |
| --- | --- |
| Compiler Core | **PASS — 14/14** |
| Language Conformance | **PASS — 77/77** |
| Differential oficial | **PASS — 96 casos, 0 fallos** |
| Suite focal BITWISE | **PASS — 7/7**, incluida en Conformance |
| OAL Integration | perfil completo no ejecutado |
| Full Ecosystem | no ejecutado |

Las ejecuciones nativas focales pasaron en O0/O2, incluidos los guards y traps
dinámicos. Los verificadores HIR, MIR y SSA reconstruyen independientemente los
tipos de operandos, signedness, tipo de resultado y metadata ordenada de traps;
las corrupciones independientes de las tres capas fueron rechazadas. Las suites
existentes ejecutadas por Conformance cubrieron borrow, operadores lógicos,
compound assignment, ranges, selectors y genéricos, además del diferencial
oficial.

El análisis del diff identificó una interacción real con cierres `>>` de tipos
genéricos y con el backend. Por ello se ejecutaron dos smokes OAL focales:

- `linear_algebra_constructors_v1` — **4/4 PASS**;
- `plots_invocable_integration_v1` — **6/6 PASS**, con casos O0/O2.

No se ejecutaron indiscriminadamente los perfiles OAL o Full. En particular,
estos smokes no atribuyen PASS al perfil OAL Integration completo.

## 10. Excepciones y riesgos residuales

La excepción histórica del registry
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` permanece sin modificar
y no fue ejecutada en este cierre. OAL Integration completo y Full Ecosystem
conservan resultado desconocido; ninguno se declara PASS ni BLOCKED. La
qualification obligatoria del milestone es Core + Conformance, ambos observados
en PASS mediante los perfiles reproducibles de TEST-QUALIFICATION-V1.

## 11. Limitaciones

No se implementan `&=`, `|=`, `^=`, `<<=`, `>>=`, `**`, `**=` ni `pow`. No hay
overloads, capabilities genéricas bitwise, union types ni operaciones
elementwise nuevas.

## 12. Archivos modificados

- `compiler-next/crates/aether-frontend/src/{lexer,parser,ast,hir}.rs`;
- `compiler-next/crates/aether-middle/src/{mir,ssa}.rs`;
- `compiler-next/crates/aether-backend-llvm/src/lib.rs`;
- `compiler-next/crates/aether-driver/tests/bitwise_operators_v1.rs`;
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`;
- `docs/architecture/BITWISE_OPERATORS_ARCH_1.md`;
- `docs/architecture/BITWISE_OPERATORS_ARCH_1_REPORT.md`;
- `docs/architecture/BITWISE_OPERATORS_V1_REPORT.md`.

Los cambios personales preexistentes en `examples/ProbandoNR/`, `scrap/` y
`docs/reports/` se preservaron.

## 13. Commit sugerido

```text
feat(compiler-next): implement checked integer bitwise operators
```

## Cierre

La implementación normativa y todos los gates obligatorios del milestone están
completos. `BITWISE-OPERATORS-V1` se declara **CLOSED** con Compiler Core,
Language Conformance y el diferencial oficial en PASS. OAL Integration y Full
Ecosystem no fueron ejecutados y no reciben un resultado inferido. No se hizo
push.
