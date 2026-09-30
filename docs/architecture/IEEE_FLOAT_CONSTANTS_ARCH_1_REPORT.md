# IEEE-FLOAT-CONSTANTS-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-30.

Autoridad normativa:

- [IEEE-FLOAT-CONSTANTS-ARCH-1](IEEE_FLOAT_CONSTANTS_ARCH_1.md).

## Resultado

Se cierra una única superficie pública:

```aether
T epsilon<T: IEEEFloat>();
```

`epsilon` será una primitive estándar de Core/prelude, disponible sin import
desde package source ordinario. No se agregan aliases, associated constants ni
wrappers por precisión. La forma `epsilon<T>()` exige type argument explícito:
la inferencia vigente no usa expected return types y no habrá magic específico
para `epsilon()`.

## Semántica cerrada

El valor es la distancia entre `1` y su siguiente representable mayor en el
formato concreto:

| instancia | valor | bits exactos |
|---|---:|---:|
| `epsilon<float32>()` | `2^-23` | `0x34000000` |
| `epsilon<float64>()` | `2^-52` | `0x3cb0000000000000` |

Retorna exactamente `T`. No significa menor normal, menor subnormal, unit
roundoff ni tolerancia algorítmica.

## Capability y lowering

No se modifica `NUMERIC-CAPABILITIES-V1`. Epsilon es una propiedad del dominio
nominal sellado `IEEEFloat`, no una operación algebraica implementable por tipos
arbitrarios. `T: IEEEFloat` es toda la prueba requerida; en V1 sólo puede
concretarse a `float32` o `float64`.

HIR paramétrico conservará un nodo de constante IEEE con kind `Epsilon`, result
type `T` y requirement `IEEEFloat`. Durante monomorphization se sustituirá
directamente por el constant node float tipado con uno de los dos payloads. HIR
concreto rechazará cualquier nodo residual. MIR, SSA y LLVM verán únicamente
una constante ordinaria; no habrá call, helper runtime, libm/FFI, global,
allocation, trap, exception, TypeId branch, string comparison, witness, vtable
ni lookup table runtime.

La representación elegida son bits IEEE, no parsing de decimal aproximado ni
cálculo runtime. Por construcción el resultado no depende de constant folding,
locale, host rounding o nivel de optimización.

## Qualification futura

`IEEE-FLOAT-CONSTANTS-V1` deberá comprobar ambos payloads directamente en las
fases del compilador, ejecución de `1 + epsilon > 1` y resultado bitwise
idéntico en O0/O2. También cubrirá forwarding genérico, aliases transparentes,
diagnostics negativos, corruption tests y ausencia de artefactos runtime.

`1 + epsilon/2 == 1` no es requisito portable: depende de
round-to-nearest-ties-to-even y el contrato aún no hace observable/normativo el
ambient rounding mode. Sólo podrá usarse como evidencia adicional en un harness
que fije y registre explícitamente ese modo.

## Alcance

Este cierre sólo agrega documentación. No se modificó código, tests, manifests,
`linearAlgebra`, OAL, Core, runtime ni capabilities. Min normal/subnormal,
infinities, NaNs, otros límites de formato, `nextafter`, `ulp` y nuevos formatos
quedan fuera de scope.

