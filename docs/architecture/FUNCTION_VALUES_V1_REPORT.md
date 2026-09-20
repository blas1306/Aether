# FUNCTION-VALUES-V1 — Newton callable spine

Estado: implementado y calificado el 2026-09-15.

## Alcance cerrado

Este vertical implementa valores función no capturantes con una única sintaxis
source:

```aether
Function<(P1, ...), R>
```

Admite cero, uno o varios parámetros y permite `void` únicamente como retorno.
El frontend representa los tipos source mediante `AstTypeKind`, sin rediseñar
las demás superficies del sistema de tipos. El tipo semántico canónico es
`TypeData::Function { parameters: TypeArgsId, result: TypeId }`; la identidad es
estructural e invariante.

Las propiedades cerradas de `Function` son `Copy`, `Relocatable` y `Storable`,
sin `Drop`. Su layout y ABI runtime son exactamente un pointer. No se introdujo
environment, descriptor, allocation, ARC ni lifecycle propio.

## Resolución y generics

Una función top-level de usuario, visible y no genérica puede aparecer como
valor. La firma se deriva exclusivamente de su declaración. Esto funciona tanto
para nombres locales al módulo como para referencias calificadas importadas.
Una referencia a función genérica abierta se rechaza con `E0355`, incluso si el
contexto contiene un `Function` esperado: V1 no infiere una monomorphization
desde ese expected type.

Los tipos `Function<(T), T>` dentro de declaraciones genéricas participan en la
sustitución estructural normal. Las instancias quedan totalmente concretas antes
de MIR. Los builtins/intrinsics como valores se rechazan con `E0356` y los
métodos/bound methods con `E0354`. Closures, lambdas, constructors, virtual o
interface method references, null callables y FFI pointers permanecen cerrados.

## IR, reachability y exceptions

Las calls cuya declaración es conocida conservan `Call`. Materializar la
dirección produce `FunctionRef`, y llamar un local o parámetro `Function`
produce `IndirectCall`. Ambas operaciones permanecen explícitas y verificadas
en HIR, MIR y SSA; los verificadores comprueban target, firma, callee, aridad,
argumentos y resultado exactos, además de impedir tipos genéricos residuales.

Reachability sigue los targets de `FunctionRef`, por lo que una función usada
solamente por address-taking continúa emitida. Una call indirecta se considera
conservadoramente may-unwind y reutiliza los unwind edges, cleanup blocks,
landing pads y regiones `finally` existentes.

LLVM usa `ptr` para el valor y conserva la dirección exacta del símbolo, sin
`bitcast` ni `ptrtoint`. La firma canónica determina directamente los tipos de
argumentos y retorno de `call`/`invoke`. Por ejemplo, Newton contiene:

```llvm
%v10 = invoke double %v0(double %v5) ...
%v11 = invoke double %v1(double %v5) ...
```

## Diagnósticos

- `E0110`: sintaxis `Function` no canónica.
- `E0350`: `void` usado como parámetro.
- `E0351`: referencia y expected `Function` con firmas distintas.
- `E0352`: aridad incorrecta en call indirecta.
- `E0353`: argumento incompatible con la firma indirecta.
- `E0354`: método o bound method usado como valor.
- `E0355`: función genérica abierta usada como valor.
- `E0356`: builtin/intrinsic usado como valor.
- `E0357`: retorno o storage de `Function` reservado para verticales posteriores.

La expectativa histórica de `unsupported_function_value.ae` se migró de
`E0215` a `E0351`, porque una función top-level ya es un valor válido y el error
real del fixture es asignarla a `int`.

## Qualification

`compiler-next/crates/aether-driver/tests/function_values_v1.rs` cubre:

- tipo canónico, invariancia, properties y prohibición de `void` como parámetro;
- `Function<(), int>`, unary, múltiples parámetros y retorno `void`;
- locals, parámetros y referencias importadas;
- distinción `Call`/`FunctionRef`/`IndirectCall` en HIR, MIR y SSA;
- firmas incompatibles, aridad, sintaxis, generic abierta, builtin y método;
- sustitución concreta de `Function<(T), T>` antes de MIR;
- retorno normal y unwind indirecto con `try`/`catch`/`finally`;
- target únicamente address-taken, ausencia de lifecycle propio y LLVM sin
  casts;
- gates cerrados para retorno, fields, payloads y `Array`/`List<Function>`;
- ejecución nativa equivalente en O0 y O2.

El ejemplo obligatorio `examples/newton/main.ae` produce en ambos perfiles:

```text
Root: 1.487962065498177
Residual: 0
```

Gates ejecutados desde `compiler-next` cuando corresponde:

```text
cargo test --workspace                                      PASS
cargo fmt --all --check                                    PASS
cargo clippy --workspace --all-targets -- -D warnings      PASS
git diff --check                                           PASS
bash compiler-next/tests/run-differential.sh               PASS (21/21)
```

## Deliberadamente diferido

Permanecen tras gates cerrados los retornos de `Function`, fields, payloads de
enum y `Array`/`List<Function<...>>`. No se implementaron closures ni ninguna
extensión de callable fuera de FUNCTION-VALUES-V1.
