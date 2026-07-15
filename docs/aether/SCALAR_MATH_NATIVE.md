# Matemática escalar en LLVM/native

Estado comprobado el 15 de julio de 2026. La fuente canónica legible por el
compilador es `src/aether/scalar_math.py`; este documento registra la política
de tipos, dominio y lowering.

## Inventario

La superficie consolidada actual es `sin`, `cos`, `tan`, `exp`, `ln`, `log`,
`sqrt`, `abs`, `Math.mod`, `Math.factorial`, `Math.floor`, `Math.ceil` y la
constante `Math.pi`. `ln` es logaritmo natural y `log` es base 10.

`complex`, `real`, `imag`, `conj` y `angle` se conservan como builtins AST
experimentales; no pertenecen al subconjunto native mientras `complex` no
tenga representación/ABI. `cbrt`, `asin`, `acos`, `atan`, `atan2`, `sinh`,
`cosh`, `tanh`, `exp2`, `log2`, `log10` (como nombre separado), `pow`, `round`, `trunc`, `min`, `max`, `hypot`
y `fma` no son hoy funciones del lenguaje: quedan como propuestas futuras, no
como huecos del backend. El operador `^` conserva su contrato separado.

## Tipos y dominio

- Las trascendentes aceptan `int`, `float` o `double` en AST y devuelven
  `double`, que es la firma histórica del lenguaje. No se promete retorno del
  mismo tipo. El perfil native aún rechaza `float` como tipo primitivo antes
  del lowering; el recorrido compilado cubierto es `int`/`double`.
- `abs` conserva el tipo real de entrada. `abs(INT_MIN)` produce el panic
  checked de overflow i32. El overload complejo devuelve `double` y sigue
  siendo solo AST.
- `Math.floor` y `Math.ceil` devuelven `int`; NaN, infinito o un resultado fuera
  de i32 hacen panic porque no existe un entero representable.
- `Math.mod` acepta dos reales compatibles, conserva el tipo común y usa
  módulo floor/Python, distinto del operador `%` truncante.
- `Math.factorial` acepta `int`, rechaza negativos y comprueba overflow i32.

Los reales siguen IEEE-754 para las operaciones cuyo contrato es real:
logaritmos de real negativo producen NaN; `ln(0.0)`/`log(0.0)` producen infinito negativo;
overflow de `exp` produce infinito; NaN e infinitos se propagan mediante
intrinsics/`libm`. No se consulta `errno` ni se habilita fast-math. Las
operaciones con retorno entero mantienen sus panics checked.

Existe una discrepancia heredada que impide marcar la capacidad completa: el
AST devuelve dinámicamente `complex` para `sqrt` de un real negativo aunque el
typechecker infiere `double`. Native no tiene ABI complejo y el intrinsic real
produce NaN. Los reales no negativos sí tienen paridad E2E. Resolver esa
inconsistencia requiere primero decidir el contrato de `complex`, fuera del
alcance de este bloque.

## Frontera de implementación

| Operación | Lowering native |
| --- | --- |
| `sqrt` | `llvm.sqrt.f64` |
| `abs(double)` | `llvm.fabs.f64` |
| `abs(int)` | helper Aether checked |
| `Math.floor`, `Math.ceil` | intrínseco LLVM + conversión i32 checked |
| `sin`, `cos`, `tan`, `exp`, `ln`, `log` | ABI `libm`; `ln→log`, `log→log10` |
| `Math.mod`, `Math.factorial` | helpers Aether tipados/checked |
| `Math.pi` | `double` constante inmediata, sin global ni init de módulo |

IR y SSA usan una call común con un identificador builtin canónico. Una call de
usuario con texto parecido no adquiere ese identificador. Verificadores,
printers y conversiones SSA lo preservan; el intérprete IR ejecuta el mismo
builtin AST. DCE puede borrar llamadas reales puras, pero conserva `abs(int)`,
floor/ceil, mod y factorial por sus caminos de panic. No se hace folding host de
trascendentes ni se aplican identidades inseguras para IEEE-754.

En Linux el builder agrega `-lm` solo cuando el LLVM emitido declara símbolos
trascendentes. Clang y una `libm` compatible con ABI C son los requisitos
actuales; Windows queda sin esa opción explícita y no tiene cobertura E2E en
este repositorio.

El build native todavía usa un único pipeline SSA fijo: los nombres `-O0`,
`-O1` y `-O2` pertenecen hoy a inspección/optimización IR y no seleccionan un
perfil LLVM native. Por eso la validación de este bloque cubre el pipeline
native real y los pases IR/SSA, no tres niveles native que aún no existen.

`Math.pi` es la única constante pública actual. No existen `PI` global ni `E`,
y esta implementación no amplía silenciosamente esa API.
