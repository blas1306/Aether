# Aether Language Specification v1

> Classification: **Normative**. Release: `1.0.0-rc.2` (Python package
> version `1.0.0rc2`). This specification defines the language; backend
> availability is defined separately by
> [Aether Native Profile v1](AETHER_NATIVE_PROFILE_V1.md).

## 1. Status and conformance

The terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** express normative
requirements. Sections explicitly labelled informative are not requirements.
Examples illustrate rules but do not replace them.

An Aether v1 implementation **MUST** accept every well-formed program within
the profile it claims, **MUST** reject ill-formed programs with a diagnostic,
and **MUST NOT** silently substitute a different backend. The AST profile is
the semantic reference for the full frontend surface. The native profile is a
normative, deliberately smaller implementation subset.

This document is not a tutorial and does not define a stable C ABI, LLVM IR
format, package registry, binary-module format, FFI, thread model, or bitwise
reproducible build format.

## 2. Lexical structure

### 2.1 Source text

An `.ae` source file **MUST** be decoded as UTF-8. A byte stream that is not
valid UTF-8 **MUST NOT** be accepted as Aether source. After decoding, source
locations are one-based line and column positions in decoded source text.

Space, horizontal tab, carriage return, and line feed separate tokens except
inside string literals. Newlines have no statement-termination meaning.
Simple statements end in `;`; blocks are delimited by `{` and `}`.

`#` and `//` begin a line comment outside a string. The comment continues to
the next line feed or end of file. Aether v1 has no block comment syntax.

### 2.2 Identifiers and keywords

An identifier starts with `_` or a Unicode alphabetic character and continues
with `_` or Unicode alphanumeric characters. Identifiers are case-sensitive.
The implementation **MUST NOT** normalize Unicode identifiers implicitly.

The reserved words are:

```text
alias as boolean break catch class complex const constructor continue double
else enum Exception false float for from function if implements import in int
interface List Matrix null package private public return static string struct
throw true try Vector void while Array ParseStatus IntParseResult
DoubleParseResult FileStatus FileReadResult
```

Some reserved type names denote privileged generic or bootstrap nominal types.
`static` is reserved but static declarations are not part of v1. A source
program **MUST NOT** use a reserved word as an identifier.

### 2.3 Literals

Integer literals are nonempty decimal digits without separators or a sign. A
leading `-` is the unary negation operator. An `int` value is a checked signed
32-bit integer in `[-2147483648, 2147483647]`. A positive literal magnitude
MUST NOT exceed `2147483647`, with one structural exception: the magnitude
`2147483648` MAY appear as the immediate operand of unary `-`, producing
exactly `-2147483648`. It is invalid by itself, and any larger negative or
positive literal is a compile-time error. The magnitude is validated before
conversion to i32; truncation and wrapping are not permitted.

This rule applies uniformly in variables and constants, arguments, returns,
fields and collection literals. Overflow in a calculated expression such as
`2147483647 + 1` remains a checked operation overflow; it is not an invalid
literal. Arbitrary-precision integers used by a compiler host, including
Python integers in the reference implementation, do not define Aether numeric
semantics.

Real literals contain a decimal point, a decimal exponent, or both. Exponents
use `e` or `E`, an optional sign, and at least one digit. Real literals infer
`double`; `float` requires an explicit typed context or conversion. Hexadecimal,
octal, binary, digit separators and suffixes are not v1 syntax.

`im`, or a numeric literal immediately followed by `im`, is a `complex`
literal. Complex is language-defined but outside the native profile.

The boolean literals are `true` and `false`. `null` is the sole null literal
and has no inferable variable type without a nullable target type.

A string literal is delimited by `"`. It denotes valid UTF-8 text and may
contain a source newline. The only escapes are `\"`, `\\`, `\$`, `\n`, `\t`,
and `\r`; any other escape is a syntax error. `${expression}` interpolation is
part of the language frontend and produces a string using public value
formatting. It is not in native profile 22.

## 3. Program and module structure

### 3.1 Files and declarations

One `.ae` file is one source module. A file MAY start with exactly one
`package dotted.name;` declaration, and that declaration **MUST** precede all
other items. A package name identifies the file module for imports; v1 does not
define multi-file package merging.

Top-level items MAY be aliases, structs, classes, interfaces, enums, typed
functions, expression functions, variables/constants, imports, or executable
statements. Struct, class, interface and enum declarations **MUST** be
top-level. Visibility modifiers apply only to top-level declarations and to
members where their grammar permits them.

In a module with a package declaration, only `public` top-level declarations
are exported. Unmarked and `private` declarations are not importable. In an
unpackaged entry script, top-level declarations are visible within that file.
Visibility does not change access between declarations in the same file.

### 3.2 Imports

The supported forms are:

```aether
import Math;
import Geometry as G;
from Geometry import Point;
from Geometry import Point as P;
```

A dotted file-module name maps to the corresponding relative `.ae` path under
the source root. Imports **MUST** be resolved, type-checked, cached, and checked
for cycles before execution. Wildcard imports are not supported. An import
alias introduces only its local binding. A selective import **MUST** respect
the target declaration's visibility.

Builtin namespaces such as `Math`, `System`, `io`, and `text` do not require a
source file. A backend MAY support fewer imported declaration kinds, but it
**MUST** reject the excluded kind according to its profile.

### 3.3 Entry point and top-level execution

An explicit program entry point has the exact signature `int main()` and
declares no parameters. Falling off its end returns zero. Its returned `int`
is the process exit code.

If the entry file has executable top-level statements and no explicit `main`,
the implementation **MUST** preserve their source order in a synthetic
`int main()` and append `return 0;`. An entry file **MUST NOT** combine an
explicit `main` with executable top-level statements. Top-level constants are
available to explicit `main`; backend profiles may restrict imported module
storage and initialization.

An imported function named `main` is an ordinary qualified function and is
not the process entry point. Native executable construction **MUST** require
one normalized root entry point.

## 4. Types

### 4.1 Scalar and special types

- `int` is checked signed i32.
- `boolean` contains only `true` and `false`; `bool` is not a spelling.
- `double` is IEEE-754 binary64.
- `float` is a distinct real type supported by the frontend/AST profile; a
  decimal literal does not infer it.
- `complex` is a frontend/AST complex value type.
- `string` is an immutable, non-null UTF-8 value described in section 10.
- `void` denotes no value and is valid only where a return type is expected.
- `Exception` is the bootstrap nominal value caught by language exceptions.
- `T?` is nullable `T`; `void?`, `null?`, and nested nullable types are invalid.
- `null` is a literal type assignable only to a compatible nullable target.

`float`, `complex`, nullable types and exceptions are language-defined even
when a backend profile marks them unsupported. Host-language representations
are not part of their public contract.

### 4.2 Nominal declarations

An `enum` defines a nominal type and an ordered list of distinct, payload-free
variants. Variant identity includes the declaring module and enum. Source
order assigns deterministic discriminants; numeric conversion, bit flags,
payloads and pattern matching are not v1 enum features.

A `struct` defines a nominal value type. Its fields have declared types.
Assignment, parameter binding and return copy or move the value according to
section 9; a struct does not acquire reference identity because a field is a
reference type. Acyclic by-value layout is required.

A `class` defines a nominal mutable reference type. Class assignment and
parameter binding alias the same instance. Constructors initialize instances;
methods access the receiver through `this`. Classes are defined by the
language but unsupported by native profile 22.

An `interface` defines a nominal set of method signatures. A struct or class
declaring `implements I` **MUST** provide compatible methods. Dispatch exists
in the AST profile and is unsupported by native profile 22.

An alias declaration `alias Name = T;` introduces another spelling for `T`.
Aliases may be forward-referenced but **MUST NOT** form a cycle. Aliases do not
create a new runtime representation.

### 4.3 Collections and mathematical containers

`Array<T>` is a mutable, fixed-length reference collection. `List<T>` is a
mutable, variable-length reference collection. Both use zero-based element
indexes. Their ownership, aliasing, copy, slicing and equality rules are in
sections 9 and 10.

`Vector<T>` and `Matrix<T>` are shaped mathematical values with public
one-based indexes. They are not aliases for Array/List. Their element type,
shape and vector orientation participate in type checking. The privileged
transpose-vector and range forms are inferred types rather than source type
keywords.

A range expression is `start:end` or `start:step:end`, is inclusive at the
end when reached, and contains `int` values. A zero step panics or is rejected
early when statically known.

Tuple values and destructuring are defined in the AST profile, with source
type syntax `(T1, T2, ...)`; native profile 22 excludes them. User-defined
generic declarations are not implemented. The generic spellings above are
privileged language types, not evidence of general generics.

### 4.4 Bootstrap result types

The base library exposes nominal `ParseStatus`, `IntParseResult`,
`DoubleParseResult`, `FileStatus`, and `FileReadResult`. Their definitions are
specified in section 13. They are real public types, not sentinel conventions.

## 5. Variables, constants and scope

A typed declaration has `T name = expression;`. The initializer is mandatory
and **MUST** be assignable to `T`. `const T name = expression;` creates a
non-reassignable binding. `const name = expression;` may infer `T` when it is
unambiguous.

At statement position, assignment to an unknown identifier (`name = expr;`)
declares an inferred mutable variable in the AST profile. Assignment to a
known identifier updates that binding and **MUST** preserve its type. Native
profile 22 requires the declaration forms accepted by its capability gate.
An empty collection literal and `null` cannot infer a type without a target.

Every block creates a lexical scope. Parameters, loop variables, catch
variables and locals belong to their scope. A local declaration **MUST NOT**
shadow a visible outer binding, and duplicate declarations in one scope are
invalid. A local is visible only after its declaration. Top-level type and
function signatures are collected before bodies, so forward calls, mutual
recursion, later aliases and later nominal types are permitted.

Assignment to a `const` binding is invalid. For structs and collections,
read-only access propagates through value fields and nested collection paths.
It stops after dereferencing a contained class handle: `const` restricts an
access path and does not globally freeze aliased objects.

## 6. Expressions and conversions

Postfix calls, indexing, slicing, field access and method calls bind most
tightly. Then come unary `-` and `!`, right-associative `^`, multiplicative
`*`, `.*`, `/`, `\`, `%`, additive `+`, `-`, `.+`, `.-`, comparisons,
equality, `&&`, `||`, and finally range `:`. Parentheses override precedence.

Arithmetic is statically typed. Checked `int` addition, subtraction,
multiplication, negation, division and remainder panic on overflow or invalid
integer division. Integer remainder uses a quotient truncated toward zero.
`double` division is IEEE-754, including infinities, signed zero and NaN.
`&&` and `||` require booleans and **MUST** short-circuit. `!` requires a
boolean.

Ordered comparisons require a supported ordered numeric type. Equality is
governed exclusively by `Eq(T)` in section 11. Assignment, argument and return
conversion use the declared widening rules; a backend **MUST NOT** perform a
conversion it cannot preserve. Explicit scalar conversion uses a type call,
for example `double(x)` or `int(x)`. Native profile 22 accepts only the
conversion subset it enumerates.

`value[index]` indexes a collection or mathematical container. Array/List
indexes are zero-based; Vector/Matrix indexes are one-based. Bounds are checked
before access. `value[start:end]` is a two-bound slice only for supported
collections: it is zero-based, half-open `[start,end)`, checks
`0 <= start <= end <= length`, and creates independent outer storage. Slice
assignment is not supported.

Field access is `value.name`; method call is `value.name(args...)`. Assignment
through an lvalue may target a variable, element or field rooted in a variable,
subject to mutability, const and borrowed-loop rules. Fields of temporaries
are not assignment targets.

## 7. Control flow

Control-flow headers require parentheses. The normative grammar is:

```text
if_statement    := "if" "(" expression ")" block
                   ("else" (if_statement | block))?
while_statement := "while" "(" expression ")" block
for_statement   := "for" "(" iterator_binding "in" expression ")" block
iterator_binding := type identifier | identifier
```

`if (condition) { ... } else { ... }` and `while (condition) { ... }` require
a `boolean` condition. `else` is optional. `else if` is exactly an `if`
nested in the else branch and does not introduce different scope, evaluation,
return or lifecycle rules. A block is mandatory.

`for (name in iterable) { ... }` or `for (T name in iterable) { ... }` binds
one loop variable. For ranges, iteration follows inclusive range semantics.
A zero step detected as a constant is a compile-time error; a dynamic step
that evaluates to zero panics before iteration. The terminal range value is
processed without a subsequent increment, including `INT_MAX`/`INT_MIN`, while
a genuine checked overflow before reaching the endpoint remains a panic. For
Array/List, each element binding is a borrowed read-only value for that
iteration. The loop variable **MUST NOT** be assigned or used to mutate the
borrowed element through a value path. Mutating the iterated collection's
structure during its loop is invalid.

Aether 1.0.0-rc.2 requires parentheses around `if`, `while`, and `for`
headers. Source written for rc.1 must be migrated; the rc.1 forms are not an
alternative grammar.

`break;` and `continue;` are valid only inside a loop and target the innermost
loop. `return expression;` is valid in a non-void function and must match its
return type. `return;` is valid in a void function. Every reachable path in a
non-void function other than normalized `main` **MUST** return a value.

## 8. Functions and callables

A typed function is `R name(P1 a, P2 b) { ... }`; the optional `function`
keyword is accepted for compatibility. Parameters require explicit types and
are passed left to right. Calls check arity and parameter types. Direct
recursion, mutual recursion and calls before declaration are permitted.

The callable type spelling is `R(P1, P2, ...)`. A callable value contains a
capture-free reference to a top-level user function with the exact structural
signature. v1 does not define closures, lambdas, captured environments, bound
methods, builtin values, covariant callable conversion, or returned callables.
Expression functions (`f(x) = expression;`) remain an AST exploration feature
and are not typed callables or part of the native profile.

Parameters are borrowed for lifecycle purposes. A function must not destroy a
borrowed argument. A returned nontrivial value is owned by the caller. These
rules do not change source-level mutability: Array/List and class parameters
alias their object, while struct parameters are values.

## 9. Ownership and lifecycle

### 9.1 General rules

`int`, `boolean`, `float`, `double`, `complex`, payload-free enums and callable
references are copied as scalar values when their backend supports them.
Struct assignment copies the struct logically, recursively applying each
field's copy rule. Class assignment copies a reference and aliases the same
instance.

`string` is immutable and may share storage. Copying a string creates a valid
logical owner (normally retain); moving transfers ownership without changing
the text. A returned string is owned. A string parameter is borrowed.

Array/List assignment is O(1) reference assignment and aliases the same
mutable collection object. Parameter binding uses the same reference; mutation
is visible to the caller, while rebinding the parameter is local. Return
transfers an owned reference and never performs an implicit deep copy.

The implementation lifecycle operations are initialization, copy
initialization, move initialization, assignment, destruction and relocation.
Each live owning slot **MUST** be destroyed exactly once on normal structured
control flow. A move consumes or resets its source according to the type.
These operations are semantic; an implementation **MUST NOT** substitute raw
byte copying for a type that owns references.

### 9.2 Explicit collection copy and slicing

`array.copy()` and `list.copy()` create a new collection descriptor and buffer.
They logically copy each element. This is a shallow structural copy with
respect to nested reference values: nested Array/List/class objects remain
aliased; strings may share immutable storage; structs are copied by value.

Array/List slicing has the same element-copy rule and creates independent outer
storage. Mutating the outer source does not resize or replace elements in the
slice, but a nested reference reachable from both may still be shared. There
is no implicit copy-on-write, deep copy, view type, or public identity operator.

### 9.3 Const and borrowed iteration

A const Array/List binding is a read-only reference path, not a frozen object.
A mutable alias may still mutate the shared container, and the const alias
observes that mutation. A `for-in` Array/List element is borrowed and read-only;
the loop does not copy it and the binding must not escape its iteration.

No broader ownership promise is made for currently unsupported native classes,
interfaces, nullable aggregates, Vector/Matrix or future types beyond the
rules stated here and their backend profile.

## 10. Strings and collections

A string is immutable valid UTF-8 with an explicit byte length. Equality uses
bytes/content; no normalization, locale collation or grapheme segmentation is
implicit. `s.byteLength` returns the byte count as checked `int`. v1 has no
`s[i]` operation.

`a + b` concatenates two strings without implicit scalar conversion.
`s.trim()` removes only ASCII bytes space, tab, LF, CR, form feed and vertical
tab at both ends. `s.split(separator)` performs exact, left-to-right,
non-overlapping UTF-8 byte matching, preserves all empty fields, returns an
owned `Array<string>`, and panics for an empty separator.

Array/List expose `.length`; List also exposes `.is_empty`. Array exposes
`copy()` and `sort()`. List exposes `push`, `pop`, `insert`, `removeAt`,
`contains`, `indexOf`, `clear`, `size`, `copy`, `reverse`, and `sort` with the
typed arities enforced by the implementation. `pop`, removal and indexing
perform bounds checks. Allocation and length conversion are checked. Sort is
defined only for its registered ordered element types.

Array is fixed length: element assignment is permitted but structural growth
is not. List growth provides the strong guarantee for checked allocation and
element-copy failures: either the operation completes or the prior logical
list remains valid. No shrinking policy, capacity value, iterator object or
concurrent mutation contract is public v1 API.

Vector/Matrix literals and operators preserve type, shape and orientation.
Vector/Matrix public indexes are one-based even though Array/List indexes are
zero-based. A backend **MUST** diagnose a shape or metadata boundary it cannot
represent rather than silently flatten it.

## 11. Equality

`Eq(T)` is the single compile-time capability required by `==`, `!=`,
Array/List structural equality, `contains`, and `indexOf`. It is defined for:

- `int`, `boolean`, `float`, `double`, `complex`, `string`, and `null` in a
  compatible nullable comparison;
- enums of the same nominal identity;
- structs only when every field defines `Eq`;
- nullable `T?`, Array/List, Vector/Matrix and tuples only when their element
  or component types define `Eq`.

Numeric operands may use the normal numeric promotion before exact equality.
Floating equality is IEEE: NaN is unequal to itself and signed zeroes compare
equal. No tolerance or approximate comparison is implicit. Strings compare
content. Structs compare fields in declaration order. Collections compare
kind, length, order and elements structurally, not object identity or capacity.

Classes, interfaces, callables, ranges, `void`, `Exception`, and a struct or
collection containing a non-`Eq` component do not define equality. Applying
equality to them is a type error; an implementation **MUST NOT** fall back to
host identity.

## 12. Errors and panic

A static syntax, name, type, capability or backend error prevents execution.
Expected operational failures SHOULD use structured result/status values where
the base library defines them.

A panic is an unrecoverable language safety failure. Public panic output is
`Aether panic: <message>` followed by a newline on stdout, and the process exit
code is 1. Checked integer overflow, integer division by zero, invalid bounds,
zero range step, empty split separator, allocation/length overflow and other
registered safety checks panic. Native v1 panics do not unwind Aether frames.

`throw expression;` and `try { ... } catch (name) { ... }` define basic AST
exception handling with an `Exception` catch value. There is no `finally`,
stack trace contract, exception hierarchy or native unwind in v1. Native
profile 22 rejects language exception handling before lowering.

## 13. Base standard library

Only this section is a v1 base-library commitment. APIs present in the Python
registry but not listed here (notably plotting and advanced linear algebra)
are implementation extensions and do not establish portable v1 conformance.

### 13.1 Output and scalar conversion

`print(values...)` writes values to stdout without a trailing newline;
`println(values...)` appends one newline. Public booleans are `true`/`false`.
Public double formatting uses 15 significant digits, preserves a visible `.0`
for integral finite values, and spells special values `NaN`, `Infinity`, and
`-Infinity`. It is deliberately distinct from ALPT1 round-trip formatting.

The explicit scalar conversions are `int`, `float`, `double`, `string`, and
`boolean` for the typed combinations supported by the selected backend. There
is no implicit stringify operation.

### 13.2 Scalar math

The consolidated real scalar surface is `sin`, `cos`, `tan`, `exp`, `ln`,
`log`, `sqrt`, `abs`, `Math.mod`, `Math.factorial`, `Math.floor`,
`Math.ceil`, and constant `Math.pi`. `log` is base 10 and `ln` is natural log.
The exact overloads and native subset are enforced by the typechecker/profile.
Complex helpers (`complex`, `real`, `imag`, `conj`, `angle`) are AST
extensions, not native v1 commitments.

### 13.3 Parsing

```aether
enum ParseStatus { Success, Empty, InvalidFormat, OutOfRange }
struct IntParseResult { int value; ParseStatus status; }
struct DoubleParseResult { double value; ParseStatus status; }
```

`parseInt(string)` and `parseDouble(string)` are strict, length-aware and
locale-independent. They do not trim implicitly; callers use `trim()`
explicitly. The value field is zero on failure but is not a sentinel; callers
**MUST** inspect `status`. Integer parsing enforces i32 range. Double parsing
accepts only the finite decimal grammar implemented by the language and
rejects NaN/infinity spellings.

### 13.4 Process arguments

`System.args() -> Array<string>` returns a fresh owned snapshot of the program
arguments after the CLI's first `--`. It does not include the executable or
source path. Every call returns an independent outer Array and all arguments
must cross the platform boundary as valid UTF-8. `main` remains parameterless.

### 13.5 UTF-8 text files

```aether
enum FileStatus {
    Success, NotFound, PermissionDenied, InvalidPath, InvalidUtf8, IoError
}
struct FileReadResult { string content; FileStatus status; }
```

`io.readText(path) -> FileReadResult`, `io.writeText(path, content) ->
FileStatus`, `io.writeTextAtomic(path, content) -> FileStatus`, and
`io.appendText(path, content) -> FileStatus` operate on exact UTF-8 bytes,
preserve embedded NUL and newlines, and do not add a terminator or newline.
On read failure, `content` is empty and the status is authoritative.

Paths are nonempty UTF-8 strings without NUL; the API performs no `~`,
environment-variable or URL expansion. On validated Linux,
`writeTextAtomic` writes a unique same-directory temporary, fsyncs it,
renames it, and fsyncs the parent directory. A post-rename durability failure
may return failure after the new content became visible. The API does not
promise sandboxing, locking, backups, metadata preservation, binary IO,
streaming or multi-file transactions.

### 13.6 Bootstrap text helpers and ALPT1

The `text.byteAt`, `text.byteSlice`, `text.formatInt`, `text.formatDouble`, and
`text.concatFragments` functions are a checked bootstrap surface used by the
revision-1 ALPT1 Expense Tracker codec. They do not imply arbitrary byte
strings, Unicode slicing, reflection or generic serialization. The normative
ALPT1 byte format remains defined in
[Persistence Format Design](PERSISTENCE_FORMAT_DESIGN.md); this language
release does not change ALPT1.

## 14. Backend model

Language semantics and backend support are separate. Acceptance by the parser
and typechecker does not imply acceptance by every backend. The AST backend is
the reference for frontend-defined features. The LLVM/native backend **MUST**
apply [profile 22](AETHER_NATIVE_PROFILE_V1.md) before lowering and reject
excluded programs without fallback.

For a program accepted by native profile 22, stdout, stderr, exit status,
panic behavior and selected file effects **MUST** match AST execution as
defined by the profile's observable parity guarantee. Internal layouts,
reference counts, helper names and LLVM text are not observable language API.

## Appendix A — Informative document map

The current normative documents are this specification and the native profile.
Design/RFC documents explain implementation decisions. `AETHER_V0_SPEC.md` is
historical, `AETHER_V1_RELEASE_READINESS.md` is an audit snapshot, and
`BACKEND_FEATURE_PARITY.md` is an engineering audit. Where they conflict with
this specification for release `1.0.0-rc.2`, this specification prevails.
