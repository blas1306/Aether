# NUMERIC-CAPABILITIES-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad normativa:

- [NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC_CAPABILITIES_ARCH_1_REPORT](NUMERIC_CAPABILITIES_ARCH_1_REPORT.md).

## Resultado

`compiler-next` extiende su sistema estático y cerrado de capabilities numéricas.
No se modificó `linearAlgebra`, no se agregó dispatch runtime y no cambió el
ABI de las instancias concretas.

La vocabulary atómica resultante es:

```text
Zero  One
Add   Sub   Mul   Div   Negate
Equal Order
Abs   Sqrt
IEEEFloat
```

Se conservan `Copy`, `Relocatable` y `Storable` como propiedades estructurales.
`RingOps`, `FieldOps` y `RealOps` se expanden durante collection a sus atoms
normativos. La metadata de cada binder retiene por separado los spellings y
spans declarados y el cierre normalizado utilizado para proofs. Por ello se
rechazan tanto duplicaciones directas como solapamientos vía alias, por ejemplo
`RingOps + Add`.

## Satisfaction, aliases e `IEEEFloat`

La tabla concreta queda cerrada en `TypeArena`:

| capability | tipos concretos V1 |
|---|---|
| `Zero`, `One`, `Add`, `Sub`, `Mul`, `Equal`, `Order` | integers y floats |
| `Div`, `Sqrt` | `float32`, `float64` |
| `Negate`, `Abs` | signed integers y floats |
| `IEEEFloat` | exactamente `float32`, `float64` |

`RingOps` contiene `Zero + One + Add + Sub + Mul + Negate + Equal`;
`FieldOps` agrega `Div`; `RealOps` agrega `Order + Abs + Sqrt`.

`IEEEFloat` es nominal y sellada. Su garantía implica `RealOps + Copy +
Relocatable + Storable`; el cierre inverso no existe. En consecuencia, un
binder `T: IEEEFloat` puede satisfacer un callee `U: RealOps`, mientras que un
binder `T: RealOps` no puede satisfacer un callee `U: IEEEFloat`. Ninguna
capability numérica se deriva desde fields, aggregates o collections.

## Literales algebraicos

Con expected type exactamente igual a un parámetro genérico:

- `0` requiere `Zero` y produce `AlgebraicValue::Zero`;
- `1` requiere `One` y produce `AlgebraicValue::One`.

No existe un cast intermedio desde integer. `2`, `-1`, `0.0`, `1.0` y `1e0`
siguen rechazados para `T`. La sustitución materializa directamente `0`/`1` en
el integer concreto o los bits de `+0.0`/`1.0` de la precisión float concreta.

## Operadores y Core math

Los cuerpos paramétricos registran la prueba que autoriza cada operación:

| source | HIR paramétrico | requirement |
|---|---|---|
| `T + T`, `T - T`, `T * T`, `T / T` | `CapabilityBinary` | `Add`, `Sub`, `Mul`, `Div` |
| `-T` | `CapabilityUnary` | `Negate` |
| `==`, `!=` | `CapabilityCompare` | `Equal` |
| `<`, `<=`, `>`, `>=` | `CapabilityCompare` | `Order` |
| `abs(T)`, `sqrt(T)` | `CapabilityMath` | `Abs`, `Sqrt` |

`CapabilityCompare` produce `bool`. `CapabilityMath` conserva explícitamente
`result_type`, igual a `T` en V1. `abs` y `sqrt` siguen resolviendo a los mismos
símbolos Core/prelude existentes; no se agregaron trascendentales ni helpers de
package.

La reificación usa las operaciones concretas vigentes: división float,
negación float o integer checked, comparaciones numéricas y Core `abs`/`sqrt`.
Así se preservan `IntegerOverflow`, NaN unordered y `+0 == -0`.

## Verificación y monomorfización

El verificador paramétrico reconstruye el requirement desde cada operación y
comprueba homogeneidad, tipo de resultado y guarantee del binder. También
rechaza metadata de operación/resultado incoherente.

Durante instantiation se sustituyen todos los `TypeId`, se reifican las
operaciones simbólicas, se convierten `Zero`/`One` a constantes y `Abs`/`Sqrt`
a `CoreCall`. La verificación HIR concreta falla cerrada si sobrevive cualquier
`AlgebraicValue`, `CapabilityBinary`, `CapabilityUnary`, `CapabilityCompare` o
`CapabilityMath`. Una compilación fallida no publica un `TypedHir` ejecutable.

## MIR, SSA, LLVM y coste

No se agregaron opcodes de capability a MIR o SSA. Ambas capas siguen viendo
solamente tipos y operaciones concretas y conservan sus verificadores
existentes. LLVM no consulta capabilities.

La qualification confirma instancias y símbolos separados para `float32` y
`float64`, ejecución nativa O0/O2 y ausencia de calls indirectas, witnesses,
vtables, boxing, `Any`, dispatch por `TypeId` y allocations atribuibles al
sistema de constraints.

## Diagnostics y qualification

Los diagnostics generales cubren capability desconocida, duplicada (también
vía alias), operación o literal sin guarantee, instanciación explícita o
inferida inválida y mismatch sellado de `IEEEFloat`. No se agregaron diagnostics
específicos de `linearAlgebra`.

La suite `numeric_capabilities_v1` cubre:

- cada capability individual y los tres aliases;
- integers, `float32` y `float64` según la tabla cerrada;
- forwarding `RealOps -> FieldOps`, rechazo `RealOps -> IEEEFloat` y
  `IEEEFloat -> RealOps`;
- literales algebraicos y literales genéricos prohibidos;
- rechazo de integer `Div`, unsigned `Negate`/`RingOps` y aggregates;
- presencia de nodos simbólicos sólo en HIR paramétrico;
- reificación completa antes de MIR/SSA/LLVM y ejecución nativa O0/O2.

Validación del milestone:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

## Alcance

No se modificó `linearAlgebra/src/lib.ae` ni sus constructors, LU, solve, det o
QR. Su migración permanece para el milestone posterior previsto por la
arquitectura.
