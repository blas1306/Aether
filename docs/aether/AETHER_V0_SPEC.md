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

Aether v0 has six primitive types:

- `int`
- `float`
- `double`
- `complex`
- `string`
- `boolean`

## Type Inference

Aether supports inference for assignments without explicit type annotations.

| Literal | Inferred type |
|---|---|
| `5` | `int` |
| `5.2` | `double` |
| `im`, `2im`, `1 + 2im` | `complex` |
| `"hola"` | `string` |
| `true` / `false` | `boolean` |

`float` values must be requested explicitly:

```aether
float x = 5.2;
```

`null` has no inferred variable type. A declaration or assignment like `x = null;` is an error because Aether cannot infer the intended nullable base type.

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

## Null and Nullable Types

`null` is a special literal that belongs only to explicitly nullable types. It is not a member of every reference-like type.

A nullable type is written by adding `?` to the base type:

```aether
string? name = null;
int? maybeN = null;
double? maybeX = null;
Vector<double>? maybeV = null;
Matrix<double>? maybeA = null;
```

Rules:

- `null` can be assigned to `T?`.
- A value of type `T` can be assigned to `T?`.
- `null` cannot be assigned to non-nullable `T`.
- `x = null;` without an explicit type is an error.
- A variable inferred as non-nullable remains non-nullable.
- `T?` is not automatically treated as `T`.

```aether
string? name = "Aether";
name = null;
name = "Aether";

string title = null; // error
x = null;            // error
```

Comparisons with `null` are supported:

```aether
string? name = null;

if name == null {
    println("empty");
}
```

`print(...)` and `println(...)` render null values as `null`.

Current limitation: v0 does not perform smart casts or null narrowing yet. Inside `if name != null { ... }`, `name` still has type `string?`.

## Constants

`const` declares a variable whose name cannot be reassigned after initialization:

```aether
const int maxIter = 100;
const double tol = 1e-8;
const name = "Aether";
```

`const` can be used with an explicit type or with local inference. Inferred constants use the same rules as inferred variables:

```aether
const n = 10; // n is int
```

In Aether v0, `const` prevents direct reassignment of the identifier:

```aether
const int n = 3;
n = 4; // error: Cannot assign to constant 'n'
n += 1; // error: Cannot assign to constant 'n'
```

This is not deep immutability yet. If a matrix or vector value can be mutated through element assignment today, `const` does not freeze its contents in v0.

## Type Aliases

`alias` declares a type synonym:

```aether
alias Real = double;
alias Index = int;

Real x = 2.5;
double y = x; // valid: Real is not a nominal type
```

Aliases are compile-time type information and do not exist as runtime values. An alias must resolve to an existing type:

```aether
alias Real = double;
alias Scalar = Real;
alias RealVector = Vector<double>;
```

Alias chains are resolved transitively. Cycles are errors:

```aether
alias A = B;
alias B = A; // error: Cyclic type alias involving 'A'

alias Self = Self; // error
```

`Matrix<T>` and `Vector<T>` aliases work for the existing primitive element types supported by Aether v0. Full generic type parameters are still reserved for a future version.

Invalid targets, duplicate alias names, and collisions with values/functions in the same scope are errors:

```aether
alias Foo = DoesNotExist; // error
alias Real = double;
alias Real = int;         // error
int Real = 3;             // error
```

### Alias Limitations

Aliases of generic container types work when fully instantiated:

```aether
alias RealVector = Vector<double>;     // valid
RealVector v = [1.0, 2.0];             // valid
```

However, using an alias of a primitive type as a type parameter does not yet work:

```aether
alias Real = double;
Vector<Real> v = [1.0, 2.0];            // NOT YET supported; use Vector<double> instead
```

This limitation will be addressed when full generic type parameters are implemented.

## Structs

Aether v0 supports a minimal data-only `struct` form. A struct is a nominal type with an explicit list of typed fields, an automatic positional constructor, and field access with `.`.

```aether
public struct Point {
    double x;
    double y;
}

Point p = Point(1.0, 2.0);
println(p.x);
println(p.y);
```

Struct declarations are top-level only in this version. They may use `public` or `private` in the same way as other top-level declarations:

```aether
private struct InternalData {
    int n;
}
```

Fields must have explicit types and unique names:

```aether
struct Point {
    double x;
    double y;
}
```

Field-level `public`, `private`, and `const` are not supported yet. Methods, nested declarations, custom constructors, and constructor overloads are also not supported inside structs.

The automatic constructor is positional and checks the declared field types:

```aether
Point p = Point(1.0, 2.0); // valid
Point q = Point(1.0);      // error: wrong argument count
Point r = Point("x", 2.0); // error: incompatible field type
```

Local inference works with struct constructor calls:

```aether
p = Point(1.0, 2.0);
println(p.x);
```

Struct aliases are type aliases. An alias can be used both as the annotated type and as the constructor name:

```aether
struct Point {
    double x;
    double y;
}

alias P = Point;
P p = P(1.0, 2.0);
```

Struct fields may use existing aliases:

```aether
alias Real = double;

struct Point {
    Real x;
    Real y;
}
```

Structs may contain fields whose type is another visible struct:

```aether
struct Point {
    double x;
    double y;
}

struct Segment {
    Point a;
    Point b;
}

Segment s = Segment(Point(0.0, 0.0), Point(1.0, 1.0));
println(s.a.x);
println(s.b.y);
```

Struct values can be passed to and returned from functions:

```aether
Point origin() {
    return Point(0.0, 0.0);
}

Point shift(Point p, double dx, double dy) {
    return Point(p.x + dx, p.y + dy);
}
```

Field reads are typechecked. Accessing a missing field or using field access on a non-struct value is an error:

```aether
println(p.z); // error

int x = 3;
println(x.y); // error
```

Field assignment is supported for this shallow data model:

```aether
Point p = Point(1.0, 2.0);
p.x = 3.0;
println(p.x); // 3.0
```

The assignment target must start from a variable or another field rooted in a variable. Assignment to a field on a temporary value is not supported:

```aether
Point(1.0, 2.0).x = 5.0; // error
```

This follows the current shallow `const` rule. A `const` binding prevents rebinding the variable name, but it does not deep-freeze the fields of the struct value yet.

Structural equality is not implemented yet. Comparing structs with `==` or `!=` is an error in v0:

```aether
println(Point(1.0, 2.0) == Point(1.0, 2.0)); // error
```

`print(...)` and `println(...)` render structs with field names:

```aether
println(Point(1.0, 2.0)); // Point(x=1.0, y=2.0)
```

Packaged files export only public structs:

```aether
package Geometry;

public struct Point {
    double x;
    double y;
}

private struct Hidden {
    int value;
}
```

```aether
import Geometry;

Point p = Point(1.0, 2.0); // valid
Hidden h = Hidden(3);      // error: Hidden is private
```

A public struct cannot expose a private local type in one of its fields:

```aether
package Geometry;

private struct Internal {
    int x;
}

public struct Wrapper {
    Internal value; // error
}
```

Current struct limitations:

- No methods inside structs.
- No custom constructors or overloaded constructors.
- No field visibility.
- No new generic struct parameters.
- No inheritance, interfaces, traits, or protocols.
- No destructuring or pattern matching for structs.
- No operator overloading for structs.
- No structural equality for structs.
- No deep `const`.
- Struct lowering to IR/JIT is not implemented.

## Visibility Modifiers

Top-level declarations may be prefixed with `public` or `private`:

```aether
public int inc(int x) {
    return x + 1;
}

private const int internalLimit = 100;
public alias Real = double;
```

The accepted order in v0 is:

- `public` or `private`
- optional `const` for variable declarations
- the declaration itself

`public private` and repeated visibility modifiers are errors.

Visibility is recorded in the AST and symbol metadata. Inside a single file, `public` and `private` do not restrict access between declarations. Across file imports, packaged files export only `public` declarations.

In files with a `package` declaration, top-level declarations without a visibility modifier are private by default. In scripts without `package`, existing script behavior is preserved and unmodified top-level declarations are available to legacy file imports.

## Packages and File Imports

Aether v0 supports a first incremental multi-file module model without requiring declarations to live inside a class.

```aether
package Math.LinearAlgebra;

public double norm(Vector<double> v) {
    return 0.0;
}

private double helper(Vector<double> v) {
    return 1.0;
}
```

`package` is a top-level declaration. If present, it must be the first non-comment declaration in the file, before imports and normal declarations. A file may declare at most one package. The package name is stored as a dotted logical path such as `Math.LinearAlgebra`.

Another file can import the package:

```aether
import Math.LinearAlgebra;

println(norm([1; 2; 3]));
```

The initial file mapping is intentionally simple:

```text
Math.LinearAlgebra -> Math/LinearAlgebra.ae
Config             -> Config.ae
```

Resolution is relative to the active source root. When running a saved file from the editor/runtime, the source root is the file's containing directory. Direct `run_aether(...)` calls can pass an explicit `source_root`; otherwise the current working directory is used to preserve existing script-import behavior.

For packaged files, only `public` top-level variables/constants, aliases, structs, and functions are exported to importers:

```aether
package Math.Types;

public alias Real = double;
public const int DEFAULT_ITER = 100;
```

```aether
import Math.Types;

Real x = 2.5;
println(DEFAULT_ITER);
```

`private` declarations and declarations without a modifier remain usable inside their own file but are not visible through imports. Attempting to use a private imported name is a type error. File imports also reject missing modules, import cycles, collisions with local symbols, and collisions between two imported modules exporting the same unqualified name.

Builtin namespaces remain separate from file modules. A builtin import such as `import Math.LinearAlgebra` continues to expose the registered stdlib aliases. If a builtin namespace and a file module have the same name, the builtin namespace is preferred in this version.

Current package/import limitations:

- A package maps to one `.ae` file; multi-file packages are not implemented yet.
- Specific imports, import aliases such as `import X as Y`, and explicit wildcards are not implemented yet.
- Cyclic imports are rejected.
- `private` is enforced across imports only; declarations in the same file can still use each other.
- Classes, interfaces, exceptions, and package-level class visibility are outside this version.

## Implicit Conversions

Only safe widening conversions are implicit:

- `int -> float`
- `int -> double`
- `int -> complex`
- `float -> double`
- `float -> complex`
- `double -> complex`

Lossy or cross-domain conversions are not implicit:

- `complex -> double`
- `complex -> float`
- `complex -> int`
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
- `complex(expr)`
- `string(expr)`
- `boolean(expr)`

Numeric casts to `int` truncate toward zero:

```aether
int x = int(3.9); // x = 3
```

`string(value)` converts a value to its textual representation.

`complex(value)` converts a numeric value to complex, and `complex(real, imag)` constructs `real + imag*im`.

`boolean(number)` and `boolean(string)` are not implemented in v0 and must fail.

## Operators

Arithmetic operators:

- `+`
- `-`
- `*`
- `/`
- `%`

`/` is always real division. Integer division is not implemented with `/`.

```aether
int a = 5;
int b = 2;
double c = a / b; // c = 2.5
```

`%` computes a truncating remainder, matching Java/C#/C/C++ sign behavior. It is defined as:

```text
a % b = a - trunc(a / b) * b
```

The divisor must not be zero:

```aether
println(5 % 3);    // 2
println(-5 % 3);   // -2
println(5 % -3);   // 2
println(-5 % -3);  // -2
```

Use `Math.mod(a, b)` for floor/Python-like modulo:

```aether
println(Math.mod(5, 3));    // 2
println(Math.mod(-5, 3));   // 1
println(Math.mod(5, -3));   // -1
println(Math.mod(-5, -3));  // -2
```

Promotion rules follow the wider numeric type. Important cases:

- `int + int -> int`
- `int / int -> double`
- `int + float -> float`
- `int + double -> double`
- `float + double -> double`
- `float + float -> float`
- `double + double -> double`
- `double + complex -> complex`
- `complex + complex -> complex`

The same numeric promotion model applies to `-`, `*`, and `/`, except that `/` is real division.

Complex values use `im` as the imaginary unit:

```aether
z = 1 + 2im;
w = complex(3, -4);
println(z * w);
```

The alias `i` is not reserved; use `im` for imaginary literals. Ordered comparisons and `%` require real numeric operands and reject `complex`.

Strings:

```aether
string s = "hola" + " mundo"; // valid
```

`string + numeric` and `numeric + string` are not allowed.

String literals support interpolation with `$expr$`. The expression is parsed as Aether, typechecked in the current scope, evaluated at runtime, and formatted with the same display rules used by `print(...)` and `println(...)`.

```aether
n = 4;
println("n = $n$");       // n = 4
println("n^2 = $n^2$");   // n^2 = 16
println("Precio: \$10");  // Precio: $10
```

Empty interpolation (`$$` or `$   $`), unclosed interpolation, invalid embedded expressions, and undefined names inside interpolation are errors.

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

Aether separates the internal array representation from mathematical vectors and matrices:

- `[ ... ]` creates a mathematical `Matrix<T>` literal.
- The public `array(...)` constructor is not part of Aether v0.

Array element types are still used internally and can be written with `[]` after a primitive type:

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

Non-empty `[ ... ]` literals are not array literals anymore, and non-empty programming-array literals are not exposed in Aether v0. Empty typed arrays remain a transitional compatibility feature.

The builtin `length(array)` returns the array length as an `int` for internal array values. `length(...)` does not accept matrices; use `rows(matrix)` and `cols(matrix)` for matrices.

## Vectors And Matrices

Aether supports mathematical matrix literals with MATLAB/Julia-like bracket syntax:

```aether
[1 2 3]       // Matrix<int>, shape 1x3
[1, 2, 3]     // Vector<int>, length 3
[1; 2; 3]     // Vector<int>, length 3
[1 2; 3 4]    // Matrix<int>, shape 2x2
[1 2; 3.0 4]  // Matrix<double>, shape 2x2
```

Spaces separate matrix columns. Commas preserve Aether's vector literal form for scalar values. Semicolons separate rows or vector entries. All matrix rows must have the same number of columns. Elements must be homogeneous or numerically promotable:

- `int -> float`
- `int -> double`
- `float -> double`

Mixed incompatible elements are type errors:

```aether
[1 "x"]; // error
[1 2; 3]; // error, ragged rows
```

Bracket literals also support Julia-style block concatenation for existing scalar, vector, transposed-vector, and matrix values:

```aether
A = [1 2; 3 4];
B = [5 6; 7 8];
[A B]        // [1 2 5 6; 3 4 7 8]
[A; B]       // [1 2; 3 4; 5 6; 7 8]
[A [9; 10]]  // [1 2 9; 3 4 10]
```

For block concatenation, `Vector<T>` values are treated as columns and `TransposeVector<T>` values are treated as rows. A pure vertical concatenation of vectors, such as `[v; w]`, returns a `Vector<T>`. Comma-separated matrix or vector blocks are intentionally not supported in v0:

```aether
[A];    // error
[A, B]; // error
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
println(A);       // [1 2; 99 4]
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

`print(...)` and `println(...)` render `Matrix<T>` and `Vector<T>` values with a compact mathematical display format:

```aether
println([1 2 3]);        // [1 2 3]
println([1; 2; 3]);      // [1; 2; 3]
println([1 2; 3 4]);     // [1 2; 3 4]
println([1.0 2.5; 3 4]); // [1.0 2.5; 3.0 4.0]
println(["a" "b";
         "c" "d"]);      // ["a" "b"; "c" "d"]
println([true false;
         false true]);   // [true false; false true]
```

Matrix values with shape `1x1` print as scalars. This keeps mathematical results readable even when the internal value remains a matrix:

```aether
println(Math.LinearAlgebra.matmul([1 2], [3; 4])); // 11
```

Internal array values use comma-separated list display and are not rendered as mathematical vectors. Runtime types remain distinct: `Matrix<T>`/`Vector<T>` for bracket literals, and `T[]` for internal arrays.

Matrix equality compares by shape and content. Incompatible element types are type errors. Comparing `Matrix<T>` or `Vector<T>` with an internal array is an `AetherTypeError`.

## Math.LinearAlgebra

Aether v0 introduces a first explicit mathematical namespace:

```aether
Math.LinearAlgebra.inner(u, v)
Math.LinearAlgebra.norm(v)
Math.LinearAlgebra.transpose(A)
Math.LinearAlgebra.matmul(A, B)
Math.LinearAlgebra.solve(A, b)
Math.LinearAlgebra.eig(A)
Math.LinearAlgebra.SVD(A)
Math.LinearAlgebra.LU(A)
Math.LinearAlgebra.LDU(A)
Math.LinearAlgebra.N(A)
Math.LinearAlgebra.R(A)
Math.LinearAlgebra.rank(A)
```

This namespace is a simulated builtin namespace for now, implemented through the Aether stdlib registry. Calls can always be resolved by their full builtin names, such as `"Math.LinearAlgebra.inner"`. A builtin `import Math.LinearAlgebra` also exposes the direct aliases in this namespace.

Importing the builtin namespace exposes unqualified aliases for direct use:

```aether
import Math.LinearAlgebra
S, D = eig(A);
```

`Math.LinearAlgebra.inner(u, v)` computes the usual Euclidean inner product:

```text
sum(u_i * v_i)
```

Both arguments must be mathematical vectors represented as `Matrix<T>` or `Vector<T>` values with shape `1xN` or `Nx1`. Row-row, column-column, row-column, and column-row combinations are valid when the effective lengths match. General matrices with both dimensions greater than one are errors. Internal arrays are not vectors for this API.

Vector elements must be numeric: `int`, `float`, or `double`. `boolean` and `string` vector elements are errors. The result uses the existing numeric promotion rules:

```aether
println(Math.LinearAlgebra.inner([1 2 3], [4 5 6]));  // 32
println(Math.LinearAlgebra.inner([1; 2; 3], [4; 5; 6])); // 32
println(Math.LinearAlgebra.inner([1 2 3], [4; 5; 6])); // 32
```

These are errors:

```aether
Math.LinearAlgebra.inner([1 2; 3 4], [1 2; 3 4]);
Math.LinearAlgebra.inner([1 2 3], [1 2]);
```

`Math.LinearAlgebra.norm(v)` computes the induced Euclidean norm:

```text
sqrt(inner(v, v))
```

The argument rules are the same: `v` must be a numeric mathematical row or column vector, not a general matrix and not an internal array. The result is a `double` in the current implementation:

```aether
println(Math.LinearAlgebra.norm([3 4]));     // 5.0
println(Math.LinearAlgebra.norm([1 2 2]));   // 3.0
```

Basic real numeric builtins such as `sin(x)`, `cos(x)`, `exp(x)`, `ln(x)`, and `log(x)` are available globally and accept real numeric scalar arguments. Complex-aware scalar builtins are:

- `complex(x)` and `complex(real, imag)`
- `real(z)`
- `imag(z)`
- `conj(z)`
- `abs(z)`
- `angle(z)`
- `sqrt(z)`

`sqrt(real_non_negative)` returns `double`; `sqrt(negative_real)` and `sqrt(complex)` return `complex`.

`Math.LinearAlgebra.transpose(A)` returns a new transposed matrix:

```aether
println(Math.LinearAlgebra.transpose([1 2 3]));    // [1; 2; 3]
println(Math.LinearAlgebra.transpose([1; 2; 3]));  // [1 2 3]
println(Math.LinearAlgebra.transpose([1 2; 3 4])); // [1 3; 2 4]
```

The argument must be a mathematical `Matrix<T>` or `Vector<T>` with numeric elements. Internal arrays, scalar values, and matrices with `boolean` or `string` elements are errors for this linear algebra builtin. `transpose` does not mutate the original value. Shape rules are:

- `1xN -> Nx1`
- `Nx1 -> 1xN`
- `MxN -> NxM`

`Math.LinearAlgebra.matmul(A, B)` computes standard matrix multiplication explicitly:

```text
if A is m x n and B is n x p, matmul(A, B) is m x p
```

Both arguments must be mathematical `Matrix<T>` or `Vector<T>` values with numeric elements. Internal arrays, scalar values, and matrices with `boolean` or `string` elements are errors. The inner dimensions must match. Row and column vectors follow their matrix shapes:

```aether
println(Math.LinearAlgebra.matmul([1 2; 3 4], [5 6; 7 8])); // [19 22; 43 50]
println(Math.LinearAlgebra.matmul([1 2 3], [4; 5; 6]));     // 32
println(Math.LinearAlgebra.matmul([1; 2; 3], [4 5 6]));     // [4 5 6; 8 10 12; 12 15 18]
println(Math.LinearAlgebra.matmul([1 2; 3 4], [5; 6]));     // [17; 39]
println(Math.LinearAlgebra.matmul([1 2], [3 4; 5 6]));      // [13 16]
```

`matmul` returns a new matrix and does not mutate either operand. It uses existing numeric promotion rules: `int` with `int` remains `int`, combinations involving `float` or `double` widen as usual, and combinations involving `complex` produce `complex`.

The `*` operator is still not matrix multiplication in Aether v0. Matrix multiplication is available only through the explicit `Math.LinearAlgebra.matmul(A, B)` builtin.

`Math.LinearAlgebra.solve(A, b)` solves linear systems with Julia-like left-division semantics. The expression `A \ b` is equivalent to `Math.LinearAlgebra.solve(A, b)`.

The coefficient argument `A` must be a numeric mathematical matrix. The right-hand side `b` must be a numeric mathematical vector or matrix with `rows(b) == rows(A)`. Row-vector right-hand sides with matching length are treated as column vectors. The result is a `Matrix<double>`/`Vector<double>` for real systems, or `Matrix<complex>`/`Vector<complex>` when either `A` or `b` is complex:

```aether
A = [2 1; 1 3];
b = [1; 2];
println(A \ b); // [0.2; 0.6]

B = [2 4; 8 12];
println(Math.LinearAlgebra.solve([2 0; 0 4], B)); // [1.0 2.0; 2.0 3.0]
```

Square full-rank systems use a direct solve. Rectangular or rank-deficient systems use a least-squares/minimum-norm solution. No implicit narrowing to `int` is performed.

`Math.LinearAlgebra.eig(A)` computes a diagonalization of a square numeric matrix over the real or complex numbers. It returns a tuple `(S, D)` where the columns of `S` are eigenvectors and `D` is diagonal, so `A * S == S * D` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [1 1; 0 2];
S, D = eig(A);
```

The result uses `Matrix<double>` values when the factors are real and `Matrix<complex>` values when the input or the computed eigenstructure is complex. Matrices that are not square or are not diagonalizable are errors in Aether v0.

`Math.LinearAlgebra.SVD(A)` computes a full singular value decomposition of a real or complex numeric matrix. It returns a tuple `(U, S, V)` where `U` is `rows(A)xrows(A)`, `S` is `rows(A)xcols(A)`, and `V` is `cols(A)xcols(A)`, so `A == U * S * V'` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [3 2; 1 0; 0 0];
U, S, V = SVD(A);
println(U * S * V');
```

For complex inputs, `U` and `V` use `Matrix<complex>` and `S` remains `Matrix<double>` because singular values are real. Empty matrices are errors in Aether v0.

`Math.LinearAlgebra.LU(A)` computes an LU factorization of a square real or complex numeric matrix with row pivoting. It returns a tuple `(P, L, U)` where `P` is a real permutation matrix, `L` is unit lower-triangular, and `U` is upper-triangular, so `P * A == L * U` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [2 1; 4 5];
P, L, U = LU(A);
```

`Math.LinearAlgebra.LDU(A)` computes the corresponding LDU factorization. It returns `(P, L, D, U)` where `P` is a real permutation matrix, `L` is unit lower-triangular, `D` is diagonal, and `U` is unit upper-triangular, so `P * A == L * D * U` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [4 8; 2 6];
P, L, D, U = LDU(A);
```

For complex inputs, `P` remains `Matrix<double>` and the other factors use `Matrix<complex>`. Matrices that are not square are errors in Aether v0. `LDU` also requires nonzero diagonal pivots after the LU factorization, because the upper factor is normalized through the diagonal factor.

`Math.LinearAlgebra.N(A)` returns an orthonormal basis for the null space as columns. `Math.LinearAlgebra.R(A)` returns an orthonormal basis for the column space as columns. `Math.LinearAlgebra.rank(A)` returns the numeric matrix rank as an `int`:

```aether
import Math.LinearAlgebra
A = [1 im; 0 0];
K = N(A);
B = R(A);
r = rank(A);
```

For complex inputs, `N` and `R` return `Matrix<complex>`. For real inputs, they return `Matrix<double>`.

## Matrix Arithmetic

Aether supports `+` and `-` for numeric matrices with the same shape. Row vectors and column vectors are matrices, so shape still matters:

```aether
println([1 2 3] + [4 5 6]); // [5 7 9]
[1 2 3] + [1; 2; 3];        // error, 1x3 vs 3x1
```

Internal arrays do not participate in matrix/vector arithmetic or equality.

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

`break` and `continue` are supported inside `for` and `while` loops:

```aether
for i in 1:10 {
    if i == 5 {
        break;
    }
    println(i);
}

while true {
    continue;
}
```

`break` exits only the innermost loop. `continue` advances only the innermost loop. Using either statement outside a loop is an `AetherTypeError`:

```aether
break;    // error: break used outside of a loop.
continue; // error: continue used outside of a loop.
```

Labeled breaks and labeled loops are not part of v0.

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
- Non-`void` functions require a return value on all evident paths.
- `void` functions may end without a `return` and may use `return;` for early exit.
- `void` is only valid as a block function return type. It is not a variable, parameter, tuple, array, matrix, or vector element type.
- Calls to `void` functions are valid only as statements; they cannot be assigned, passed as arguments, returned from non-`void` functions, or used inside expressions.
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

Valid `void` procedure:

```aether
void emit(int x) {
    if x < 0 {
        return;
    }
    println(x);
}

emit(3);
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
- `Math.mod(a, b)`
- `Math.LinearAlgebra.inner(u, v)`
- `Math.LinearAlgebra.norm(v)`
- `Math.LinearAlgebra.transpose(A)`
- `Math.LinearAlgebra.matmul(A, B)`
- `Math.LinearAlgebra.solve(A, b)`
- `Math.LinearAlgebra.eig(A)`
- `Math.LinearAlgebra.SVD(A)`
- `Math.LinearAlgebra.LU(A)`
- `Math.LinearAlgebra.LDU(A)`
- `Math.LinearAlgebra.N(A)`
- `Math.LinearAlgebra.R(A)`
- `Math.LinearAlgebra.rank(A)`

Side-effect builtins such as `print(...)`, `println(...)`, and plotting commands return `void`, except `savefig(...)`, which returns the output path as a `string`.
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

`array(...)` is not a recognized builtin in Aether v0.

`length(array)` accepts one internal array argument and returns an `int`.

`rows(matrix)` and `cols(matrix)` accept one `Matrix<T>` or `Vector<T>` argument and return `int` dimensions.

`sin(x)`, `cos(x)`, `tan(x)`, `exp(x)`, `ln(x)`, and `log(x)` accept one real numeric scalar and return `double`. `sqrt(x)` accepts numeric scalars and returns `double` for non-negative real inputs or `complex` for negative/complex inputs. `abs(x)` accepts one numeric scalar and returns `double` for `complex` inputs. `real(x)`, `imag(x)`, `conj(x)`, and `angle(x)` are available for numeric scalars. `Math.mod(a, b)` accepts two real numeric scalars and returns floor/Python-like modulo.

`Math.LinearAlgebra.inner(u, v)`, `Math.LinearAlgebra.norm(v)`, `Math.LinearAlgebra.transpose(A)`, `Math.LinearAlgebra.matmul(A, B)`, `Math.LinearAlgebra.solve(A, b)`, `Math.LinearAlgebra.eig(A)`, `Math.LinearAlgebra.SVD(A)`, `Math.LinearAlgebra.LU(A)`, `Math.LinearAlgebra.LDU(A)`, `Math.LinearAlgebra.N(A)`, `Math.LinearAlgebra.R(A)`, and `Math.LinearAlgebra.rank(A)` are explicit simulated-namespace builtins for numeric mathematical vectors and matrices. See `Math.LinearAlgebra` above.

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

`.ae` files are the active Aether script format in the editor and use the persistent Aether REPL for interactive input. Legacy `.mtx`, `.mtex`, and `.mtn` workflows are outside the active Aether Studio surface. A basic Aether LSP server exists for diagnostics and completions; a full IDE protocol feature set is not part of v0.

## Not Implemented Yet

The following are intentionally not implemented in Aether v0:

### Arrays and Matrices

- Full ND tensors (only 1D vectors and 2D matrices are supported)
- Multidimensional slicing (only 1D vector slicing with `:` is supported; matrix slicing is not available)
- Broadcasting semantics (implicit dimension expansion for operations)
- Slice assignment (reading slices works; assignment to slices does not)

### Language Features

- Comprehensions (list, generator, etc.)
- Methods in structs (structs have constructors and field access only)
- Generics (aliases of generic types like `Vector<double>` work; generic type parameters for custom structs do not)
- Exceptions / error handling
- JIT compilation
- Multi-file packages (each package maps to one `.ae` file)
- Import aliases and specific imports (`import X as Y`, `from X import Y`)

### Ecosystem

- Rust core (currently Python-based)
- Full LSP feature set
- Formatter
- Notebooks `.aen`
- Documents `.aed`
- Package manager
- Integer division `//`

## Design Philosophy

Aether combines a Java/C-like surface syntax with `{}` blocks and explicit type syntax, plus comfortable inference inspired by Julia.

The language is intended for scientific and computational work. Numeric behavior favors predictable real arithmetic, explicit casts for lossy conversions, and early semantic errors whenever possible.

The current Python implementation is a prototype and executable specification. It is deliberately structured around clear lexer, parser, AST, typechecker, scope, and interpreter stages so the core can later be ported to Rust without depending on PyQt or legacy document/runtime pipelines.
