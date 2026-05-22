# Aether v0 Language Specification

## Status

Aether v0 is the initial language specification and executable prototype for Aether Studio. It is implemented in Python as a clean, isolated language core while the final architecture is prepared for a future Rust core.

This document describes the current v0 behavior. It is intentionally small and conservative: the goal is to stabilize syntax, typing, scoping, semantic checks, and execution before adding larger scientific features.

## Files

| Extension | Purpose |
|---|---|
| `.ae` | Aether scripts and programs |
| `.aen` | Future Aether notebooks |
| `.aed` | Future Aether computational documents |

Only `.ae` scripts are recognized at a basic level in v0. Notebooks and computational documents are reserved for later stages.

## Base Syntax

Aether uses braces for blocks:

```aether
if x > 0 {
    println(x);
}
```

Simple statements must end with `;`.

The semicolon is only a statement terminator. It does not silence output. Assignments do not print automatically. In script mode, only `print(...)` and `println(...)` produce output.

```aether
x = 5;
println(x);
```

## Primitive Types

Aether v0 has five primitive types:

- `int`
- `float`
- `double`
- `string`
- `boolean`

## Type Inference

Aether supports inference for assignments without explicit type annotations.

| Literal | Inferred type |
|---|---|
| `5` | `int` |
| `5.2` | `double` |
| `"hola"` | `string` |
| `true` / `false` | `boolean` |

`float` values must be requested explicitly:

```aether
float x = 5.2;
```

## Declarations and Assignments

Explicit declarations:

```aether
int x = 5;
x = 6;
```

Inferred variables:

```aether
y = 2.5;
```

A variable has a fixed type after it is created. This is true for both explicitly declared variables and inferred variables. Changing a variable to an incompatible type is not allowed.

```aether
x = 5;
x = "hola"; // error
```

## Implicit Conversions

Only safe widening conversions are implicit:

- `int -> float`
- `int -> double`
- `float -> double`

Lossy or cross-domain conversions are not implicit:

- `double -> float`
- `double -> int`
- `float -> int`
- `string` to any non-string type
- `boolean` to any non-boolean type
- numeric types to `boolean`
- numeric types to `string`

```aether
double x = 5;   // valid
int y = 2.5;    // error
```

## Explicit Casts

Aether v0 supports casts as function calls:

- `int(expr)`
- `float(expr)`
- `double(expr)`
- `string(expr)`
- `boolean(expr)`

Numeric casts to `int` truncate toward zero:

```aether
int x = int(3.9); // x = 3
```

`string(value)` converts a value to its textual representation.

`boolean(number)` and `boolean(string)` are not implemented in v0 and must fail.

## Operators

Arithmetic operators:

- `+`
- `-`
- `*`
- `/`

`/` is always real division. Integer division is not implemented with `/`.

```aether
int a = 5;
int b = 2;
double c = a / b; // c = 2.5
```

Promotion rules follow the wider numeric type. Important cases:

- `int + int -> int`
- `int / int -> double`
- `int + float -> float`
- `int + double -> double`
- `float + double -> double`
- `float + float -> float`
- `double + double -> double`

The same numeric promotion model applies to `-`, `*`, and `/`, except that `/` is real division.

Strings:

```aether
string s = "hola" + " mundo"; // valid
```

`string + numeric` and `numeric + string` are not allowed.

Booleans do not participate in arithmetic:

```aether
true + 1; // error
```

## Comparisons

Numeric comparisons return `boolean`:

```aether
x = 3 < 4; // boolean
```

Supported:

- numeric comparisons such as `int < double`
- `string == string`
- `boolean == boolean`
- `!=` for comparable values

Not supported in v0:

- `string < string`
- `boolean < boolean`

## Arrays 1D

Aether now separates programming arrays from mathematical vectors and matrices:

- `[ ... ]` creates a mathematical `Matrix<T>` literal.
- `array(...)` creates a programming array/list, written as `T[]`.

Arrays are homogeneous, mutable, one-dimensional, and indexed from zero.

```aether
a = array(1, 2, 3);       // int[]
b = array("a", "b");     // string[]
c = array(true, false);   // boolean[]
println(a[0]);            // prints 1
a[0] = 10;
```

`array(...)` infers a homogeneous primitive scalar element type. Numeric values use normal widening:

- `array(1, 2, 3) -> int[]`
- `array(1, 2.5) -> double[]`
- `array(1, "x")` is a type error.
- `array()` is a type error because the element type cannot be inferred yet.
- `array([1 2 3])` is a type error.
- `array([1 2; 3 4])` is a type error.

For Aether v0, `array(...)` only accepts these scalar primitive element types: `int`, `float`, `double`, `string`, and `boolean`. It does not accept `Matrix<T>`, `Vector<T>`, or nested arrays as elements.

Array element types are still written with `[]` after a primitive type:

- `int[]`
- `float[]`
- `double[]`
- `string[]`
- `boolean[]`

For compatibility during the transition, empty typed arrays remain valid:

```aether
int[] xs = []; // valid
x = [];        // error
```

Non-empty `[ ... ]` literals are not array literals anymore. Use `array(...)` for programming arrays. Arrays are programming containers; they are intentionally separate from mathematical `Matrix<T>` and `Vector<T>` values.

The builtin `length(array)` returns the array length as an `int`. `length(...)` only accepts arrays; use `rows(matrix)` and `cols(matrix)` for matrices.

## Vectors And Matrices

Aether supports mathematical matrix literals with MATLAB/Julia-like bracket syntax:

```aether
[1 2 3]       // Matrix<int>, shape 1x3
[1, 2, 3]     // Matrix<int>, shape 1x3
[1; 2; 3]     // Matrix<int>, shape 3x1
[1 2; 3 4]    // Matrix<int>, shape 2x2
[1 2; 3.0 4]  // Matrix<double>, shape 2x2
```

Spaces and commas separate columns. Semicolons separate rows. All rows must have the same number of columns. Elements must be homogeneous or numerically promotable:

- `int -> float`
- `int -> double`
- `float -> double`

Mixed incompatible elements are type errors:

```aether
[1 "x"]; // error
[1 2; 3]; // error, ragged rows
```

Explicit mathematical types are:

```aether
Matrix<int> A = [1 2; 3 4];
Matrix<double> B = [1 2; 3.0 4];
Vector<int> row = [1 2 3];
Vector<int> col = [1; 2; 3];
Vector<double> v = [1 2.5 3];
```

`Matrix<T>` accepts any 2D shape. `Vector<T>` is a conceptual alias for a `Matrix<T>` whose shape is either `1xN` or `Nx1`; assigning a matrix with both `rows > 1` and `cols > 1` to `Vector<T>` is an `AetherTypeError`. Internally this implementation may represent vectors as `MatrixType(element_type, rows, cols)`.

`Matrix<int>` and `Vector<int>` reject `double` values because narrowing is not implicit. `Matrix<double>` and `Vector<double>` accept `int` and `double` values. `Matrix<string>` does not accept numeric matrix literals.

Matrices are mutable and zero-based. `A[0]` currently returns the first row as an internal array value; this is provisional. `A[0][1]` returns an element, and nested index assignment mutates the element:

```aether
A = [1 2; 3 4];
println(A[0][1]); // 2
A[1][0] = 99;
println(A);       // [1 2;
                  //  99 4]
```

`rows(matrix)` and `cols(matrix)` return matrix dimensions as `int` values. They accept row vectors, column vectors, and 2D matrices:

```aether
println(rows([1 2 3]));      // 1
println(cols([1 2 3]));      // 3
println(rows([1; 2; 3]));    // 3
println(cols([1; 2; 3]));    // 1
println(rows([1 2; 3 4]));   // 2
println(cols([1 2; 3 4]));   // 2
```

`length(matrix)` is a type error in the separated model. `rows(array)` and `cols(array)` are also type errors.

`print(...)` and `println(...)` render `Matrix<T>` and `Vector<T>` values with a mathematical display format:

```aether
println([1 2 3]);        // [1 2 3]
println([1; 2; 3]);      // [1;
                         //  2;
                         //  3]
println([1 2; 3 4]);     // [1 2;
                         //  3 4]
println([1.0 2.5; 3 4]); // [1.0 2.5;
                         //  3.0 4.0]
println(["a" "b";
         "c" "d"]);      // ["a" "b";
                         //  "c" "d"]
println([true false;
         false true]);   // [true false;
                         //  false true]
```

Matrix values with shape `1x1` print as scalars. This keeps mathematical results readable even when the internal value remains a matrix:

```aether
println(Math.LinearAlgebra.matmul([1 2], [3; 4])); // 11
```

Programming arrays from `array(...)` keep a distinct display and are not rendered as mathematical vectors:

```aether
println(array(1, 2, 3)); // array(1, 2, 3)
```

This display format is stable for v0. Runtime types remain distinct: `Matrix<T>`/`Vector<T>` for bracket literals, and `T[]` for `array(...)`.

Matrix equality compares by shape and content. Incompatible element types are type errors. Comparing `Matrix<T>` or `Vector<T>` with a programming array is an `AetherTypeError`.

## Math.LinearAlgebra

Aether v0 introduces a first explicit mathematical namespace:

```aether
Math.LinearAlgebra.inner(u, v)
Math.LinearAlgebra.norm(v)
Math.LinearAlgebra.transpose(A)
Math.LinearAlgebra.matmul(A, B)
```

This namespace is a simulated builtin namespace for now, implemented through the Aether stdlib registry rather than a real module loader. There is no real import system, module system, package loader, or `using`/`import` behavior yet. Calls are resolved by their full builtin names, such as `"Math.LinearAlgebra.inner"`. This keeps program meaning stable: future imports must not make the same source code mean something else.

Only explicit namespace calls are supported. The unqualified names `inner(...)`, `norm(...)`, `transpose(...)`, and `matmul(...)` are not introduced by this feature.

`Math.LinearAlgebra.inner(u, v)` computes the usual Euclidean inner product:

```text
sum(u_i * v_i)
```

Both arguments must be mathematical vectors represented as `Matrix<T>` or `Vector<T>` values with shape `1xN` or `Nx1`. Row-row, column-column, row-column, and column-row combinations are valid when the effective lengths match. General matrices with both dimensions greater than one are errors. Programming arrays from `array(...)` are not vectors for this API.

Vector elements must be numeric: `int`, `float`, or `double`. `boolean` and `string` vector elements are errors. The result uses the existing numeric promotion rules:

```aether
println(Math.LinearAlgebra.inner([1 2 3], [4 5 6]));  // 32
println(Math.LinearAlgebra.inner([1; 2; 3], [4; 5; 6])); // 32
println(Math.LinearAlgebra.inner([1 2 3], [4; 5; 6])); // 32
```

These are errors:

```aether
Math.LinearAlgebra.inner([1 2; 3 4], [1 2; 3 4]);
Math.LinearAlgebra.inner(array(1, 2, 3), array(4, 5, 6));
Math.LinearAlgebra.inner([1 2 3], [1 2]);
```

`Math.LinearAlgebra.norm(v)` computes the induced Euclidean norm:

```text
sqrt(inner(v, v))
```

The argument rules are the same: `v` must be a numeric mathematical row or column vector, not a general matrix and not an `array(...)`. The result is a `double` in the current implementation:

```aether
println(Math.LinearAlgebra.norm([3 4]));     // 5.0
println(Math.LinearAlgebra.norm([1 2 2]));   // 3.0
```

Basic real numeric builtins such as `sin(x)`, `cos(x)`, `exp(x)`, `ln(x)`, `log(x)`, and `sqrt(x)` are available globally. They accept numeric scalar arguments; complex numbers are not implemented in Aether v0.

`Math.LinearAlgebra.transpose(A)` returns a new transposed matrix:

```aether
println(Math.LinearAlgebra.transpose([1 2 3]));    // [1;
                                                   //  2;
                                                   //  3]
println(Math.LinearAlgebra.transpose([1; 2; 3]));  // [1 2 3]
println(Math.LinearAlgebra.transpose([1 2; 3 4])); // [1 3;
                                                   //  2 4]
```

The argument must be a mathematical `Matrix<T>` or `Vector<T>` with numeric elements. Programming arrays from `array(...)`, scalar values, and matrices with `boolean` or `string` elements are errors for this linear algebra builtin. `transpose` does not mutate the original value. Shape rules are:

- `1xN -> Nx1`
- `Nx1 -> 1xN`
- `MxN -> NxM`

`Math.LinearAlgebra.matmul(A, B)` computes standard matrix multiplication explicitly:

```text
if A is m x n and B is n x p, matmul(A, B) is m x p
```

Both arguments must be mathematical `Matrix<T>` or `Vector<T>` values with numeric elements. Programming arrays from `array(...)`, scalar values, and matrices with `boolean` or `string` elements are errors. The inner dimensions must match. Row and column vectors follow their matrix shapes:

```aether
println(Math.LinearAlgebra.matmul([1 2; 3 4], [5 6; 7 8])); // [19 22;
                                                           //  43 50]
println(Math.LinearAlgebra.matmul([1 2 3], [4; 5; 6]));     // 32
println(Math.LinearAlgebra.matmul([1; 2; 3], [4 5 6]));     // [4 5 6;
                                                           //  8 10 12;
                                                           //  12 15 18]
println(Math.LinearAlgebra.matmul([1 2; 3 4], [5; 6]));     // [17;
                                                           //  39]
println(Math.LinearAlgebra.matmul([1 2], [3 4; 5 6]));      // [13 16]
```

`matmul` returns a new matrix and does not mutate either operand. It uses existing numeric promotion rules: `int` with `int` remains `int`, while combinations involving `float` or `double` widen as usual.

The `*` operator is still not matrix multiplication in Aether v0. Matrix multiplication is available only through the explicit `Math.LinearAlgebra.matmul(A, B)` builtin.

## Matrix Arithmetic

Aether supports `+` and `-` for numeric matrices with the same shape. Row vectors and column vectors are matrices, so shape still matters:

```aether
println([1 2 3] + [4 5 6]); // [5 7 9]
[1 2 3] + [1; 2; 3];        // error, 1x3 vs 3x1
```

Programming arrays do not participate in matrix/vector arithmetic or equality. These are type errors:

```aether
array(1, 2, 3) + [1 2 3];
[1 2 3] + array(1, 2, 3);
array(1, 2, 3) - [1 2 3];
[1 2 3] * array(1, 2, 3);
array(1, 2, 3) == [1 2 3];
[1 2 3] == array(1, 2, 3);
```

Supported scalar operations are:

- `matrix * scalar`
- `scalar * matrix`
- `matrix / scalar`

The scalar must be numeric. Division is real division over each element.

The following remain intentionally unsupported:

- matrix-matrix `*` and `/`
- vector-vector `*` and `/`
- unqualified `dot(...)`
- matrix multiplication through operator `*`
- determinant
- inverse
- broadcasting
- slicing
- ranges
- operator overloading for matrix multiplication

## Scopes

Aether is block-scoped.

The following constructs create scopes:

- `if` blocks
- `else` blocks
- `while` blocks
- functions

Variables created inside a block do not escape that block. Variables from outer scopes are visible and may be updated from an inner block. Shadowing is not allowed in v0.

```aether
x = 1;

if true {
    x = 2;
    y = 3;
}

println(x); // valid, prints 2
println(y); // error
```

Redeclaring a visible variable in an inner scope is an error:

```aether
int x = 1;

if true {
    double x = 2.5; // error: shadowing is not allowed
}
```

Function parameters and local variables live only inside the function call.

## Control Flow

`if`:

```aether
if condition {
    println("yes");
}
```

`if` / `else`:

```aether
if condition {
    println("yes");
} else {
    println("no");
}
```

`while`:

```aether
while x < 10 {
    x = x + 1;
}
```

Conditions must be `boolean`. Numeric and string values are not accepted as conditions.

```aether
if 1 {
    println("bad");
} // error
```

## Functions

Block functions are typed and have typed parameters. They are intended for complex logic.

```aether
int add(int a, int b) {
    return a + b;
}
```

Rules:

- The return type is required.
- Parameters must be typed.
- The official declaration form is `<return_type> <name>(params) { ... }`.
- The old `function <return_type> ...` form is legacy/deprecated and kept only for temporary compatibility.
- A return value is required on all evident paths.
- Return values must match the declared return type, allowing safe widening.
- Function call arity is checked.
- Function argument types are checked, allowing safe widening.
- Duplicate parameter names are not allowed.
- Duplicate global function names are not allowed in v0.

Expression functions are available for compact mathematical definitions:

```aether
f(x) = x^2 + 1;
g(x, y) = x^2 + y^2;
```

Expression function parameters are untyped. The implementation infers the return type from the expression at call sites when possible, and otherwise treats it dynamically until runtime evaluation. Expression functions can call builtins and can read existing globals according to the same global-scope rules as block functions:

```aether
a = 2;
f(x) = sin(x)^2 + cos(x)^2;
g(x) = a*x + 1;

println(f(0.0)); // 1.0
println(g(3));   // 7
```

Expression functions and block functions share the same global function namespace. Redefining a function name is an `AetherTypeError`.

Valid widening:

```aether
double f() {
    return 2;
}
```

Invalid return:

```aether
int f() {
    return 2.5;
}
```

Invalid missing return:

```aether
int f(int x) {
    if x > 0 {
        return x;
    }
} // error: may not return on all paths
```

Valid evident return:

```aether
int f(int x) {
    if x > 0 {
        return x;
    } else {
        return 0;
    }
}
```

## Builtins

Aether v0 recognizes these builtins:

- `print(...)`
- `println(...)`
- `array(...)`
- `length(array)`
- `rows(matrix)`
- `cols(matrix)`
- `sin(x)`
- `cos(x)`
- `tan(x)`
- `exp(x)`
- `ln(x)`
- `log(x)`
- `sqrt(x)`
- `abs(x)`
- `Math.LinearAlgebra.inner(u, v)`
- `Math.LinearAlgebra.norm(v)`
- `Math.LinearAlgebra.transpose(A)`
- `Math.LinearAlgebra.matmul(A, B)`
- `int(...)`
- `float(...)`
- `double(...)`
- `string(...)`
- `boolean(...)`

`print` and `println` accept one or more arguments. `print` does not add a newline. `println` adds one newline.

```aether
print("x = ");
println(x);
```

`array(...)` creates a homogeneous 1D programming array of primitive scalar values. It requires at least one argument in v0 and rejects `Matrix<T>`/`Vector<T>` arguments.

`length(array)` accepts one array argument and returns an `int`.

`rows(matrix)` and `cols(matrix)` accept one `Matrix<T>` or `Vector<T>` argument and return `int` dimensions.

`sin(x)`, `cos(x)`, `tan(x)`, `exp(x)`, `ln(x)`, `log(x)`, and `sqrt(x)` accept one numeric scalar and return `double`. `ln(x)` is the natural logarithm. `log(x)` is base 10. `ln`, `log`, and `sqrt` reject values outside their real domains. `abs(x)` accepts one numeric scalar and returns the same numeric type.

`Math.LinearAlgebra.inner(u, v)`, `Math.LinearAlgebra.norm(v)`, `Math.LinearAlgebra.transpose(A)`, and `Math.LinearAlgebra.matmul(A, B)` are explicit simulated-namespace builtins for numeric mathematical vectors and matrices. See `Math.LinearAlgebra` above.

## Errors

Aether has its own error hierarchy:

- `AetherSyntaxError`: invalid syntax or malformed source.
- `AetherTypeError`: static semantic errors and type errors.
- `AetherRuntimeError`: runtime failures that are not caught statically.

The typechecker is expected to catch semantic errors before execution whenever possible, including undefined variables, undefined functions, invalid argument counts, invalid argument types, invalid conditions, and invalid returns.

## Pipeline

Aether v0 runs through this pipeline:

```text
Lexer -> Parser -> TypeChecker -> Interpreter
```

The interpreter should only run after lexical, syntactic, and semantic checks succeed.

## Script and Session Execution

`run_aether(source)` executes in a fresh Aether session each time, so globals do not persist across calls.

`AetherSession` provides REPL/session execution with persistent global variables and function definitions across `run(source)` calls. Each call still uses the same pipeline (`Lexer -> Parser -> TypeChecker -> Interpreter`). Failed runs roll back the session to its previous committed state, so errors do not destroy earlier variables or functions.

The `.ae` editor now selects an `Aether REPL` panel backed by a persistent `AetherSession`. The `Restart REPL` control creates a fresh session. Aether does not auto-print expression statements yet; use `print(...)` or `println(...)` for visible output.

## Editor Integration

`.ae` files are the active Aether script format in the editor and use the persistent Aether REPL for interactive input. Legacy `.mtx`, `.mtex`, and `.mtn` workflows are outside the active Aether Studio surface.

## Not Implemented Yet

The following are intentionally not implemented in Aether v0:

- ND tensors
- slicing
- broadcasting
- comprehensions
- imports
- modules/packages
- JIT
- Rust core
- LSP
- formatter
- notebooks `.aen`
- documents `.aed`
- package manager
- integer division `//`

## Design Philosophy

Aether combines a Java/C-like surface syntax with `{}` blocks and explicit type syntax, plus comfortable inference inspired by Julia.

The language is intended for scientific and computational work. Numeric behavior favors predictable real arithmetic, explicit casts for lossy conversions, and early semantic errors whenever possible.

The current Python implementation is a prototype and executable specification. It is deliberately structured around clear lexer, parser, AST, typechecker, scope, and interpreter stages so the core can later be ported to Rust without depending on PyQt or legacy document/runtime pipelines.
