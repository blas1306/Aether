# IEEE-FLOAT-CONSTANTS-V1 — reporte de implementación

## API y resolución Core

La única API pública agregada es:

```aether
T epsilon<T: IEEEFloat>();
```

`epsilon` forma parte del manifest cerrado de Core/prelude v1 mediante
`CoreSymbol::Epsilon`. Por ello está disponible sin import y se resuelve por el
lookup normal del prelude, respetando shadowing de declaraciones del package.
No se agregaron aliases, wrapper en `std.Math`, capability, witness, dictionary
ni implementación de usuario.

La llamada exige exactamente un type argument explícito y cero value
arguments. El analyzer resuelve ese type argument con las reglas ordinarias y
exige que `TypeArena::guarantees_capability(T, IEEEFloat)` sea verdadero. Esto
admite `float32`, `float64`, sus aliases transparentes `float` y `double`, y el
forwarding desde un binder `T: IEEEFloat`. Rechaza mediante diagnostics
generales la omisión o exceso de type arguments, value arguments,
`epsilon<int32>()` y forwarding desde `T: RealOps`. No hay inferencia desde el
tipo de retorno ni desde el contexto esperado.

## HIR y monomorfización

El HIR paramétrico usa un nodo separado de `AlgebraicValue`:

```text
IEEEFloatConstant {
    kind: Epsilon,
    result_type: T,
    required_marker: IEEEFloat,
}
```

El verificador paramétrico vuelve a comprobar el kind cerrado, la igualdad
entre `result_type` y el tipo de la expresión, la identidad exacta del marker y
que el binder pruebe `IEEEFloat`. No confía sólo en el analyzer. Las pruebas de
corrupción cubren marker incorrecto, tipo sin garantía, nodo residual concreto
y payload/tipo inconsistente.

Al sustituir un genérico, el nodo se materializa directamente como uno de los
valores HIR existentes:

| tipo canónico | HIR concreto |
| --- | --- |
| `float32` | `Float32(0x34000000)` |
| `float64` | `Float64(0x3cb0000000000000)` |

Las llamadas concretas producen esos mismos nodos inmediatamente. No se usa
parsing decimal, aritmética, `pow`, `nextafter`, libm ni cálculo floating-point
del host. `float` se canonicaliza a `float32` y `double` a `float64` antes de
seleccionar el payload.

El verificador de HIR concreto rechaza cualquier `IEEEFloatConstant` residual.
MIR conserva únicamente constantes float ordinarias; SSA y LLVM heredan esa
representación. No existen opcode nuevo, llamada a `epsilon`, branch por
`TypeId`, tabla, vtable, helper runtime, FFI, inicialización global ni símbolo
linkable nuevo.

## Qualification

La qualification automatizada cubre:

- identidad única `epsilon` en Core/prelude y ausencia de aliases;
- llamadas directas para `float32` y `float64`;
- aliases `float` y `double` con TypeId canónico;
- forwarding `T: IEEEFloat`;
- payloads HIR exactos `0x34000000` y `0x3cb0000000000000`;
- eliminación del nodo paramétrico antes de MIR, SSA y LLVM;
- ejecución nativa de `1 + epsilon<T>() > 1` para ambas precisiones en O0 y O2;
- diagnostics negativos de type/value arity y constraint;
- verificación fail-closed ante corrupción interna;
- acceso sin import de Core desde un package ordinario `linearAlgebra`.

La semántica resultante es pura, total, O(1), sin allocations, exceptions,
traps, lectura del rounding mode ni estado global. Los payloads se materializan
antes de optimización, por lo que O0 y O2 observan los mismos bits. No se tomó
`1 + epsilon/2 == 1` como requisito.

## Regresión

El cambio no modifica el lattice de capabilities ni las implementaciones de
`Zero`, `One`, operaciones aritméticas, `Abs`, `Sqrt`, el marker `IEEEFloat`,
los kernels de álgebra lineal, MIR, SSA, LLVM o runtime. La validación final del
milestone comprende:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```
