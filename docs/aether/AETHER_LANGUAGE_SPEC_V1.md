# Aether 1.0 Language Specification

> Classification: **Normative**. Contract: **Aether 1.0 stable profile**.
> Native capability profile: **23**. This is the profile frozen for the
> `1.0.0-rc.4` release candidate; publishing this document does not by itself
> change the package version.

## 1. Scope and conformance

The terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** express normative
requirements. Text explicitly labelled informative is not a requirement.

Aether 1.0 is the single language profile defined by this document and refined
by [Aether Native Profile v1](AETHER_NATIVE_PROFILE_V1.md). It is not the union
of every construction recognized by the parser, type checker, AST interpreter,
or internal compiler layers. The profile-22
[Aether v1 Profile Audit](AETHER_V1_PROFILE_AUDIT.md) is dated historical
evidence. The current executable boundary is profile 23 and is summarized in
section 15.

A conforming Aether 1.0 implementation:

- **MUST** accept every well-formed program in this stable profile on its
  declared platform;
- **MUST** reject a program outside the profile before backend lowering, with
  a syntax, type, or `AE-BACKEND-*` capability diagnostic as applicable;
- **MUST NOT** infer language support from frontend or AST acceptance;
- **MUST NOT** silently fall back to another backend;
- **MUST** preserve the observable semantics in this document.

LLVM/native is the official execution backend. The AST interpreter is an
auxiliary interpreter, the REPL backend, and the differential semantic
reference for programs already admitted by the stable profile. The IR
interpreter is internal infrastructure. Extra AST behavior is experimental and
does not extend Aether 1.0.

The validated platform is **Linux x86_64** with `clang` on `PATH`. Aether 1.0
does not define a stable C ABI, LLVM IR format, FFI, thread model, package
registry, binary-module format, or bit-for-bit reproducible build format.

## 2. Lexical structure

### 2.1 Source text and tokens

An `.ae` source file **MUST** be valid UTF-8. Source locations use one-based
line and column positions in decoded text. Space, horizontal tab, carriage
return, and line feed separate tokens except inside string literals. Newlines
do not terminate statements. Simple statements end in `;`; blocks use `{` and
`}`.

`#` and `//` start a line comment outside a string. Aether 1.0 has no block
comment syntax.

An identifier starts with `_` or a Unicode alphabetic character and continues
with `_` or Unicode alphanumeric characters. Identifiers are case-sensitive
and are not normalized implicitly.

The stable grammar uses these reserved words:

```text
alias as boolean break class const constructor continue double else enum false
for from function if implements import in int interface List Matrix null
package private public return string struct true Vector void while Array ParseStatus IntParseResult
DoubleParseResult FileStatus FileReadResult
```

The implementation also reserves the experimental spellings `catch`,
`complex`, `float`, `static`, `throw`, and `try`. Reservation
prevents their use as identifiers; it does not make their associated
constructions part of Aether 1.0.

### 2.2 Literals

Integer literals are nonempty decimal digits without separators or a sign.
`int` is checked signed i32 in `[-2147483648, 2147483647]`. The magnitude
`2147483648` is valid only as the immediate operand of unary `-`, producing
`-2147483648`; every larger magnitude is a compile-time error. Host integer
width never changes Aether semantics.

Real literals contain a decimal point, a decimal exponent, or both. Exponents
use `e` or `E`, an optional sign, and at least one digit. They have type
`double`. Hexadecimal, octal, binary, digit separators, and numeric suffixes
are not Aether 1.0 syntax.

The boolean literals are `true` and `false`.

A string literal is delimited by `"`, denotes valid UTF-8 text, and may contain
a source newline. The only escapes are `\"`, `\\`, `\$`, `\n`, `\t`, and
`\r`; any other escape is a syntax error. String interpolation is not part of
Aether 1.0. A dollar sign that could start the frontend's experimental
interpolation form **MUST** be written as `\$` in a stable string literal.

### 2.3 Collection and mathematical literals

Brace literals initialize `Array<T>` or `List<T>` according to their declared
target type:

```aether
Array<int> fixed = {1, 2, 3};
List<string> names = {"Ada", "Lin"};
```

Bracket literals create local shaped mathematical values. Commas separate
columns and semicolons separate rows:

```aether
Vector<int, Row> row = [1, 2, 3];
Vector<int, Column> column = [1; 2; 3];
Matrix<double> matrix = [1.0, 2.0; 3.0, 4.0];
```

All rows in a matrix literal **MUST** have equal length. Element type and shape
are checked statically.

## 3. Programs and modules

### 3.1 Top-level declarations

One source file is one module. It MAY start with one
`package dotted.name;` declaration, which **MUST** precede every other item.
Aether 1.0 does not define multi-file package merging.

Stable top-level items are imports, type aliases, payload-free enums, structs,
classes, interfaces, typed functions, abbreviated expression functions, and
executable statements for a synthetic entry point. Nominal type declarations
**MUST** be top-level. Nested functions are not permitted by the stable
profile.

In a packaged module, only `public` top-level declarations are exported.
Unmarked and `private` declarations remain module-private. Visibility does not
change access within the declaring file.

`alias Name = T;` introduces another spelling for a supported Aether 1.0 type.
Aliases MAY be forward-referenced, **MUST NOT** form cycles, and do not create a
new runtime representation or admit an otherwise excluded type.

### 3.2 Imports

The stable import forms are:

```aether
import Geometry;
import Geometry as G;
from Geometry import Point;
from Geometry import Point as P;
```

A dotted module name maps to a relative `.ae` file beneath the source root.
Imports **MUST** be resolved, type-checked, cached, and checked for cycles before
execution. Wildcard imports are not supported. Selective imports **MUST**
respect visibility.

Functions, supported structs, enums, type aliases, and capture-free callable
signatures may cross a module boundary. Imported mutable globals, constants
requiring storage, and executable module initialization are outside Aether
1.0. Builtin namespaces such as `Math`, `System`, `io`, and `text` do not
require source files.

### 3.3 Entry point

An explicit entry point has the exact signature `int main()` and no
parameters. Falling off its end returns zero; an explicit returned `int` is the
process exit code.

If the entry file contains executable top-level statements and no explicit
`main`, the implementation **MUST** preserve their source order in a synthetic
`int main()` and append `return 0;`. An entry file **MUST NOT** combine an
explicit `main` with executable top-level statements. Imported `main`
functions are ordinary qualified functions and never become the root entry.

## 4. Types

### 4.1 Scalar and special types

- `int` is checked signed i32.
- `double` is IEEE-754 binary64.
- `boolean` contains only `true` and `false`; `bool` is not a spelling.
- `string` is an immutable, non-null UTF-8 value.
- `void` denotes no value and is valid only as a function return type.

For a representable non-void type `T`, `T?` contains either absent `null` or a
present `T`. `null` has no standalone runtime object identity. Assigning `T`
to `T?` creates present; assigning `T?` to `T` is invalid without an explicit
language operation. Equality compares tags and only compares payloads when
both values are present. Flow-sensitive smart casts are not defined.

### 4.2 Enums and structs

An `enum` defines a nominal type with an ordered list of distinct,
payload-free variants. Variant identity includes its declaring module and enum.
Source order assigns deterministic discriminants, but Aether 1.0 defines no
numeric conversion, bit flags, payloads, or pattern matching for enums.

A `struct` is a nominal value type with declared fields whose transitive layout
is supported by profile 23. Recursive by-value layouts are invalid. Struct
assignment, parameter passing, and return use value semantics while applying
the lifecycle rules of every field.

A struct receives an automatic positional constructor when it has no explicit
constructor. It MAY declare one explicit `constructor(...) { ... }` and typed
methods. Within a constructor or method, fields may be referenced directly;
`this.field` is the explicit equivalent. Construction **MUST** initialize every
field before use.

### 4.3 Classes and interfaces

A `class` is a nominal mutable reference type. Construction creates a distinct
non-null identity. Assignment, parameter passing and return preserve aliasing;
`==` and `!=` compare identity for values of the same class. Fields require
definite initialization. A class MAY declare one constructor and typed
instance methods; method dispatch on a concrete class is static. Strong ARC
manages ownership, but cycles are not collected.

An `interface` is a nominal method contract. A class or struct declares
`implements I` and **MUST** provide every method with the exact parameter and
return types. Conversion to `I` preserves class identity and boxes a struct as
an owned value snapshot. Calls dispatch through declaration-ordered witness
metadata. Copying an interface retains a class carrier or logically copies a
struct box. Interface inheritance, default methods, reflection, downcast/type
tests, and interface equality are not defined.

Inheritance, `extends`, `super`, override, user destructors, weak references,
and user-defined equality remain outside Aether 1.0.

### 4.4 Callable values

The structural callable spelling is `Function<(P1, P2, ...), R>`. The
parentheses around the parameter list are mandatory, including for a single
parameter; `Function<P1, R>` is invalid. A callable value is only
a capture-free reference to a top-level user function with the exact signature.
Callable assignment, parameters, local selection, imports, and indirect calls
are supported. Section 8 gives the remaining restrictions.

### 4.5 Collections

`Array<T>` is a mutable fixed-length reference collection. `List<T>` is a
mutable variable-length reference collection. Both use zero-based indexing.
Their stable element types are `int`, `double`, `boolean`, `string`,
payload-free enums, nullable values, classes, interfaces, and registered
acyclic structs when profile 23 provides every required layout and lifecycle
hook.

Nested Array/List element layouts, shaped Vector/Matrix elements, and every
unregistered aggregate layout are outside Aether 1.0. An operation requiring
printing, ordering, or `Eq(T)` is available only when `T` has that capability.

`Vector<int>`, `Vector<double>`, `Matrix<int>`, and `Matrix<double>` are local,
shaped mathematical values with one-based indexes. A vector orientation is
`Row` or `Column`; omitted orientation is inferred from its literal. Shape is
not source-level genericity and **MUST NOT** cross a function, struct,
collection, or callable ABI boundary.

### 4.6 Bootstrap result types

The base library exposes the nominal types `ParseStatus`, `IntParseResult`,
`DoubleParseResult`, `FileStatus`, and `FileReadResult` defined in section 12.
They are ordinary public enum/struct values, not sentinel conventions.

## 5. Variables, constants, and scope

A mutable declaration is `T name = expression;`. A constant declaration is
`const T name = expression;`. The explicit type and initializer are mandatory,
and the initializer **MUST** be assignable to `T`. Assignment to an unknown
identifier does not declare a stable variable.

Simple assignment updates an existing mutable variable, field, or supported
index and preserves its type. `name += expression;` is the only stable
compound assignment; its target is a mutable variable binding, and it is valid
exactly when `name + expression` is valid and assignable back to the binding.
No other compound assignment belongs to Aether 1.0.

Every block creates a lexical scope. Parameters, loop variables, and locals
belong to their block. A declaration **MUST NOT** shadow a visible outer
binding; duplicates in one scope are invalid. A local is visible only after
its declaration. Top-level type and function signatures are collected before
bodies, allowing forward calls, mutual recursion, later aliases, and later
nominal types.

A `const` binding cannot be reassigned. Read-only access propagates through
struct fields and nested access paths. For Array/List it makes that reference
path read-only; another mutable alias may still mutate the shared collection.

## 6. Expressions and conversions

### 6.1 Precedence and evaluation

Postfix calls, indexing, slicing, field access, and method calls bind most
tightly. They are followed by unary `-` and `!`, right-associative `^`,
multiplicative `*`, `/`, `%`, additive `+`, `-`, ordered comparisons, equality,
`&&`, `||`, and finally range `:`. Parentheses override precedence.

Operands and call arguments evaluate left to right. `&&` and `||` require
booleans and **MUST** short-circuit. `!` requires a boolean.

### 6.2 Numeric semantics

Checked `int` addition, subtraction, multiplication, negation, division,
remainder, and integer power panic on overflow. Integer remainder uses a
quotient truncated toward zero. `int / int` produces `double`. `double`
arithmetic follows IEEE-754, including NaN, infinity, and signed zero.

The stable conversions are:

| Source | Target/result | Rule |
| --- | --- | --- |
| `int` | `double` | implicit exact widening |
| `double` | `int` | explicit `int(value)`, truncating toward zero |
| `int op double` | `double` | widen the `int` before the operation |
| `double op int` | `double` | widen the `int` before the operation |
| `int` to `int`, `double` to `double` | same type | explicit identity cast is a no-op |

The expected `double` type may come from an initializer, assignment, argument,
return, supported struct field, field write, or target-typed literal. No
implicit `double -> int` conversion exists. No boolean/string or other scalar
cast belongs to Aether 1.0.

Power has this stable table:

| Base | Exponent | Result | Semantics |
| --- | --- | --- | --- |
| `int` | `int` | `int` | non-negative exponent; checked exponentiation by squaring |
| `double` | `double` | `double` | libm/IEEE-754 `pow` semantics |
| `double` | `int` | `double` | widen exponent, then floating power |
| `int` | `double` | `double` | widen base, then floating power |

For integer power, `x ^ 0 == 1`, including `0 ^ 0`. A statically visible
negative integer exponent is a type error; a dynamic negative exponent panics
before multiplication.

### 6.3 Equality

`Eq(T)` is the single compile-time capability required by `==`, `!=`,
Array/List structural equality, `contains`, and `indexOf`. It is defined for
`int`, `double`, `boolean`, `string`, same-identity enums, structs whose fields
all define `Eq`, and supported Array/List values whose elements define `Eq`.

Floating equality is IEEE: NaN is unequal to itself and signed zeroes compare
equal. Strings compare UTF-8 content. Structs compare fields in declaration
order. Array/List compare kind, length, order, and elements structurally, not
object identity or capacity. Callable, Vector, Matrix, range, and `void` values
do not define stable equality.

## 7. Control flow and iteration

Control-flow headers require parentheses and blocks:

```text
if_statement     := "if" "(" expression ")" block
                    ("else" (if_statement | block))?
while_statement  := "while" "(" expression ")" block
for_statement    := "for" "(" iterator_binding "in" iterable ")" block
iterator_binding := type identifier | identifier
```

`if` and `while` conditions **MUST** be boolean. `else if` is an `if` nested in
the else branch. `break;` and `continue;` are valid only inside a loop and
target the innermost loop.

A stable range exists only as the direct iterable expression of a `for`:
`start:end` or `start:step:end`. Its operands are `int`; the endpoint is
inclusive when reached. Positive, negative, and dynamic nonzero steps are
supported. A statically zero step is rejected; a dynamic zero step panics
before iteration. The terminal `INT_MAX`/`INT_MIN` value is processed without
a subsequent increment. A range cannot be stored, passed, or returned.

`for-in` also accepts supported Array, List, and Vector expressions. Array/List
elements are borrowed and read-only for the iteration. The binding cannot be
assigned, used to mutate a borrowed value path, or escape the iteration, and
the collection structure cannot be changed by that loop. Matrix and string
iteration are not part of Aether 1.0.

`return expression;` must match a non-void function's return type. `return;`
is valid in a void function. Every reachable path in a non-void function other
than normalized `main` **MUST** return a value. Early return is supported.

## 8. Functions

A typed function is `R name(P1 a, P2 b) { ... }`; the optional `function`
keyword is an equivalent stable spelling. Parameters have explicit types,
evaluate left to right, and are borrowed for lifecycle purposes. Calls enforce
arity and exact assignability. Forward calls, direct recursion, and mutual
recursion are supported.

A single-expression function replaces its block with `= expression;`:

```aether
double square(double x) = x * x;
square(double x) = x * x;
```

The first form declares its return type; the second infers only the return
type. Parameter types remain mandatory. Both forms desugar to an ordinary
function with one return before backend selection. They do not create a
function value or an anonymous function.

A callable value may reference, store, select, pass, import, and invoke only a
top-level capture-free user function whose structural signature matches
exactly. Aether 1.0 has no nested functions, lambdas, closures, captures, bound
methods as values, builtin functions as values, callable covariance, or
callable return types.

A returned nontrivial value is owned by the caller. Parameters remain borrowed
and **MUST NOT** be destroyed by the callee.

## 9. Struct and collection lifecycle

`int`, `double`, `boolean`, payload-free enums, and callable references are
copied as scalar values. Struct copy recursively applies each field's copy
rule. An implementation **MUST NOT** use raw byte copying for a value that owns
references.

`string` is immutable and may share storage. Copy creates a valid logical
owner, normally by retain; move transfers ownership. A returned string is
owned and a parameter is borrowed.

Array/List assignment is O(1) reference assignment and aliases the same
mutable collection object. Parameter binding aliases the object; rebinding the
parameter is local. Return transfers an owned reference and never performs an
implicit deep copy.

Each owning slot **MUST** be destroyed exactly once on normal structured
control flow, including block exit, early return, `break`, and `continue`.
Native v1 panics do not unwind Aether frames.

`copy()` and slicing create independent outer storage and logically copy each
element. This is a shallow structural copy for contained reference values:
strings may share immutable storage and structs copy by value. Aether 1.0 has
no copy-on-write, deep-copy operator, public identity operator, or view type.

## 10. Strings and collections

### 10.1 Strings

A string is immutable valid UTF-8 with an explicit byte length. Equality is by
content bytes; no normalization, locale collation, grapheme segmentation, or
indexing is implicit.

- `a + b` concatenates strings without implicit scalar conversion.
- `s.byteLength` returns the byte count as checked `int`.
- `s.trim()` removes ASCII space, tab, LF, CR, form feed, and vertical tab from
  both ends.
- `s.split(separator)` performs exact, left-to-right, non-overlapping UTF-8
  byte matching, preserves empty fields, returns an owned `Array<string>`, and
  panics for an empty separator.

### 10.2 Array and List

Array/List indexing is zero-based and checked. A slice `value[start:end]` is
zero-based, half-open `[start,end)`, checks
`0 <= start <= end <= length`, and creates independent outer storage. Slice
assignment is not supported.

Both kinds expose `.length` and `copy()`. `Array` additionally exposes
`sort()`. `List` exposes `.is_empty`, `push`, `pop`, `insert`, `removeAt`,
`contains`, `indexOf`, `clear`, `copy`, `reverse`, and `sort`. Their registered
arities and result types are enforced statically. `pop`, removal, insertion,
and indexing check bounds. Sort is available only for `int`, `double`, and
`string` elements. Array length is fixed; List growth is checked and either
completes or preserves the prior logical list.

No public capacity, shrink policy, iterator object, or concurrent mutation
contract exists.

## 11. Vector and Matrix core

The stable local core is limited to shaped `int`/`double` values admitted by
profile 23:

- construction from rectangular literals;
- one-based checked element read and write;
- `Vector.length`, `Matrix.rows`, and `Matrix.columns`;
- same-shape `Vector + Vector`, `Vector - Vector`, `Matrix + Matrix`, and
  `Matrix - Matrix`;
- scalar multiplication on either side;
- row-vector × column-vector dot product;
- column-vector × row-vector outer product;
- compatible Matrix × Matrix, row-Vector × Matrix, and Matrix × column-Vector
  multiplication;
- `for-in` over Vector values.

Result shape and vector orientation are checked statically and preserved.
Vector/Matrix slicing, Matrix iteration, transpose, elementwise dotted
operators, solve, norm, eigen/SVD/LU operations, and any boundary that loses
shape metadata are not Aether 1.0.

## 12. Base standard library

Only this section is a stable base-library commitment. A registry entry or AST
implementation not listed here is not a portable Aether 1.0 API.

### 12.1 Output and scalar math

`print(values...)` writes supported layouts without a trailing newline;
`println(values...)` appends one newline. Booleans print as `true`/`false`.
Doubles use 15 significant digits, retain visible `.0` for integral finite
values, and spell special values `NaN`, `Infinity`, and `-Infinity`.

The stable real math surface is `sin`, `cos`, `tan`, `exp`, `ln`, `log`,
`sqrt`, `abs`, `Math.mod`, `Math.factorial`, `Math.floor`, `Math.ceil`, and
`Math.pi`, subject to their registered `int`/`double` overloads. `log` is base
10 and `ln` is natural logarithm.

### 12.2 Parsing

```aether
enum ParseStatus { Success, Empty, InvalidFormat, OutOfRange }
struct IntParseResult { int value; ParseStatus status; }
struct DoubleParseResult { double value; ParseStatus status; }
```

`parseInt(string)` and `parseDouble(string)` are strict, length-aware, and
locale-independent. They do not trim. The value field is zero on failure but
is not a sentinel; callers **MUST** inspect `status`. Integer parsing enforces
i32 range. Double parsing accepts the stable finite decimal grammar and
rejects NaN/infinity spellings.

### 12.3 Process arguments

`System.args() -> Array<string>` returns a fresh owned snapshot of arguments
after the CLI's first `--`. It excludes the executable and source path. Every
call returns independent outer storage and every argument **MUST** be valid
UTF-8 at the platform boundary.

### 12.4 UTF-8 text files

```aether
enum FileStatus {
    Success, NotFound, PermissionDenied, InvalidPath, InvalidUtf8, IoError
}
struct FileReadResult { string content; FileStatus status; }
```

`io.readText(path) -> FileReadResult`, `io.writeText(path, content) ->
FileStatus`, `io.writeTextAtomic(path, content) -> FileStatus`, and
`io.appendText(path, content) -> FileStatus` operate on exact UTF-8 bytes,
preserve embedded NUL and newlines, and add neither terminator nor newline. On
read failure `content` is empty and `status` is authoritative.

Paths are nonempty UTF-8 strings without NUL. The API performs no `~`,
environment-variable, or URL expansion. On Linux, atomic write uses a unique
same-directory temporary, fsyncs it, renames it, and fsyncs the parent. A
post-rename durability failure may report failure after new content is
visible. There is no promise of sandboxing, locking, backups, metadata
preservation, binary IO, streaming, or multi-file transactions.

### 12.5 Bootstrap text helpers and ALPT1

`text.byteAt`, `text.byteSlice`, `text.formatInt`, `text.formatDouble`, and
`text.concatFragments` are the checked bootstrap surface for the revision-1
ALPT1 Expense Tracker codec. They do not imply byte strings, Unicode slicing,
reflection, or generic serialization. The normative byte format is defined in
[Persistence Format Design](PERSISTENCE_FORMAT_DESIGN.md).

## 13. Panics and diagnostics

A static syntax, name, type, or capability error prevents
execution. Excluded frontend constructions **MUST** fail before native
lowering. A capability diagnostic uses its stable `AE-BACKEND-*` category,
source location, and reason. A conforming implementation **MUST NOT** expose an
unexpected host traceback as a user-language diagnostic.

IR, SSA, or LLVM verification failure after the frontend accepts source is an
internal compiler error, not a source diagnostic. The public categories, stable
codes, debug behavior, and exit codes are defined by
[AETHER_DIAGNOSTICS.md](AETHER_DIAGNOSTICS.md).

A panic is an unrecoverable safety failure. Public panic output is
`Aether panic: <message>` plus newline on stdout and process exit code 1.
Checked integer overflow, invalid integer division/remainder, bounds failure,
zero range step, empty split separator, allocation/length overflow, and other
registered safety checks panic. Panic aborts native execution and performs no
stack unwind.

Allocation failure and stack overflow are platform failures, not controlled
Aether panics. Exception handling and cleanup during panic are not part of the
stable contract.

## 14. Compiler and tooling contract

`aether FILE` and `aether run FILE` select native execution by default.
`aether build FILE -o OUTPUT` creates a native executable. Backend selection is
explicit through `--backend=llvm`, `--backend=ast`, or `--backend=ir`; only
native is the stable execution frontier. The REPL uses AST and identifies
itself as such.

Native compilation **MUST** run the profile gate, verified IR, verified SSA,
and post-pass verification before LLVM emission. O0 and O1 are the stable
validation profiles. O2 currently aliases O1 and does not define a distinct
Aether 1.0 optimization promise. Inspection outputs such as `--emit-ir`,
`--emit-cfg`, `--emit-ssa`, and `--emit-llvm` expose no stable internal ABI.

For every admitted program, native and the AST differential reference **MUST**
agree on stdout bytes, stderr bytes, process exit code, panic output/status,
and selected final file bytes under controlled environment and locale.

The release tooling surface includes a formatter for stable syntax,
lexer/parser/type diagnostics from the LSP, and an IntelliJ lexer/highlighter
consistent with stable strings and operators. Tooling recognition never
widens the language profile.

Windows and macOS are not supported native platforms. Missing `clang` is a
release-gate failure and **MUST** be diagnosed rather than converted to an AST
fallback.

## 15. Current profile inventory and exclusions

The stable executable inventory is the capability catalog and typed subset in
[Aether Native Profile v1](AETHER_NATIVE_PROFILE_V1.md), version 23. The
profile-22 audit row inventory is retained only as a dated audit and **MUST
NOT** override the current compiler/profile contract.

Current exclusions include inferred local declarations, non-`+=` compounds,
stored or non-int ranges, nested functions, imported storage/initialization,
`float`, `complex`, tuples, `Any`, user generics, lambdas/closures, unsupported
or recursive collection layouts, advanced Vector/Matrix, string
interpolation/general formatting, input, general persistence/DB, plotting,
binary/stream/process IO, exceptions, class/interface inheritance, default
interface methods, reflection/downcasts, weak references, user destructors,
GC/cycle collection, panic unwind, controlled stack overflow, a distinct O2,
cross-platform native support, `long`, do-while, and match.

The excluded exception implementation is still constrained by its accepted
architecture during qualification: `Error.message()` is semantically non-throwing
and must never produce an Aether exception. A throwing
implementation is rejected semantically. An unrecoverable internal failure
uses the existing panic contract and must not construct a second `Error` or
recursively invoke exception handling. This rule does not admit exception
syntax into Aether 1.0 or enable `ERROR_HANDLING` in profile 23.

`ERROR_HANDLING` is required only when execution may require native exception
semantics: `throw`, bare rethrow, `try`/`catch`, a throwing constructor or
function body, or a call/invoke whose semantic effect requires exception
propagation. The `Error` interface is otherwise an ordinary nominal interface.
Declaring a struct or class that implements `Error`, calling
`Error.message()`, or passing, returning, storing, making nullable, or placing
`Error` values in containers does not require `ERROR_HANDLING`.

The expected rejection categories are specified by
[Aether Native Profile v1](AETHER_NATIVE_PROFILE_V1.md) and the negative corpus.
The [non-normative frontend experiments annex](AETHER_FRONTEND_EXPERIMENTS.md)
records recognized implementation experiments without assigning them Aether
1.0 semantics.

## Appendix A — Document authority (informative)

This specification and the native profile are the normative release contract.
The profile audit and profile decision are dated profile-22 closure evidence.
Design/RFC, readiness, parity, and v0 documents are historical or informative
and do not expand Aether 1.0. Where such a document conflicts with this
specification, this specification prevails.
