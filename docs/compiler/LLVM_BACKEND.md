# Initial LLVM Backend

Aether now has a minimal textual LLVM IR backend under
`aether.backend.llvm`. It consumes verified SSA modules and returns a `.ll`
string. The recommended CLI execution entry point is:

```bash
aether examples/llvm/return_5.ae
echo $?
```

Plain `aether program.ae` lowers through the General SSA builder, runs the SSA
optimizer, emits LLVM IR, invokes `clang` using temporary files, executes the
temporary native program, forwards stdout/stderr, propagates the program exit
code, and removes the temporary `.ll` and executable.

The LLVM IR inspection entry point is:

```bash
aether --emit-llvm examples/llvm/return_5.ae
```

Use `aether build` for a permanent native executable from the same limited
subset:

```bash
aether build examples/llvm/return_5.ae
aether build examples/llvm/return_5.ae -o return_5
aether build examples/llvm/return_5.ae --keep-llvm
```

`--emit-llvm` prints textual LLVM IR to stdout only and does not run `clang`.
`aether build` writes LLVM IR to a temporary `.ll` file and invokes `clang` to
produce a native executable. If `-o`/`--output` is omitted, the executable is
written under `build/` using the source name without `.ae`; for example
`examples/llvm/return_5.ae` produces `build/return_5`. `aether build` creates
any needed output directories automatically. `--keep-llvm` keeps the generated
LLVM IR next to the executable output, for example `build/hello.ll` for the
default output path or `hello.ll` when using `-o hello`.

Native execution and builds require `clang` on `PATH`.

## Example Programs

The repository keeps small native-build examples in `examples/llvm/`. Each one
uses only the currently supported LLVM subset and returns a predictable process
exit code from `main`:

| Example | Expected exit code |
| --- | ---: |
| `return_5.ae` | 5 |
| `arithmetic.ae` | 23 |
| `max.ae` | 12 |
| `countdown.ae` | 0 |
| `sum_to_n.ae` | 15 |
| `gcd_iterative.ae` | 6 |
| `identity_call.ae` | 23 |
| `string_identity.ae` | 0 |
| `string_choose.ae` | 0 |
| `double_add.ae` | 17 |
| `double_compare.ae` | 19 |
| `int_to_double.ae` | 12 |
| `double_to_int.ae` | 14 |
| `list_literal.ae` | 3 |
| `list_for_sum.ae` | 6 |
| `list_index.ae` | 2 |
| `list_set_alias.ae` | 9 |
| `list_copy.ae` | 19 |
| `list_contains.ae` | 1 |
| `list_reverse.ae` | 41 |

To build and run an example:

```bash
aether examples/llvm/gcd_iterative.ae
echo $?

aether build examples/llvm/gcd_iterative.ae -o build/gcd_iterative
./build/gcd_iterative
echo $?
```

The integration test suite walks `examples/llvm/*.ae`, runs each example
directly with `aether`, builds each example with `aether build`, runs the
resulting executable, and checks the expected exit code. These tests require
`clang`; when `clang` is not available on `PATH`, the native execution cases
are skipped.

## Supported Subset

- SSA input: `SSAModule`.
- Functions with no parameters, integer, boolean, double, or string parameters.
- Integer, boolean, double, and string return values.
- Void functions with empty `return`.
- `SSAConst` integer, boolean, and double values, emitted as immediate LLVM
  operands.
- `SSAConst` string values, emitted as private global constants and used as
  `ptr` operands:
  - Aether `string` currently maps to LLVM `ptr`.
  - Literal bytes are UTF-8 encoded with a trailing `\00`.
  - LLVM string initializers escape quotes, backslashes, control bytes, and
    non-ASCII bytes with `\XX` byte escapes.
  - Identical literal values are deduplicated within one emitted module.
  - The resulting `ptr` values can flow through SSA variables, assignments,
    returns, direct calls, and phi nodes.
- `SSABinaryOp` integer operations:
  - `add` -> `add`
  - `sub` -> `sub`
  - `mul` -> `mul`
  - `div` -> `sdiv`
  - `mod` and `rem` -> `srem`
- `SSACompareOp` integer comparisons over `i32`, producing `i1`:
  - `lt` -> `icmp slt`
  - `le` -> `icmp sle`
  - `gt` -> `icmp sgt`
  - `ge` -> `icmp sge`
  - `eq` -> `icmp eq`
  - `ne` -> `icmp ne`
- `SSABinaryOp` double operations:
  - `add` -> `fadd`
  - `sub` -> `fsub`
  - `mul` -> `fmul`
  - `div` -> `fdiv`
- `SSACompareOp` ordered/equality comparisons over `double`, producing `i1`:
  - `lt` -> `fcmp olt`
  - `le` -> `fcmp ole`
  - `gt` -> `fcmp ogt`
  - `ge` -> `fcmp oge`
  - `eq` -> `fcmp oeq`
  - `ne` -> `fcmp one`
- `SSACast` explicit numeric casts:
  - `int -> double` -> `sitofp i32 %x to double`
  - `double -> int` -> `fptosi double %x to i32`
- `SSABranch` with a `bool`/`i1` condition:
  - `branch %cond, then0, else0` -> `br i1 %cond, label %then0, label %else0`
- `SSAJump`:
  - `jump exit0` -> `br label %exit0`
- `SSAPhi` over supported scalar types (`int`/`i32`, `bool`/`i1`, `double`,
  and string `ptr`):
  - `phi(then0: %2, else0: %3)` ->
    `phi i32 [ %2, %then0 ], [ %3, %else0 ]`
- `SSACall` direct function calls over supported scalar types:
  - `%4: int = call @foo(%1, %2)` ->
    `%0 = call i32 @foo(i32 %1, i32 %2)`
  - `call @foo(...)` with no SSA result ->
    `call void @foo(...)`
- `SSAVectorNew` and `SSAMatrixNew` allocate contiguous temporary storage.
- `SSAVectorGet` and `SSAMatrixGet` load scalar elements from that contiguous
  storage. Matrix indexing is row-major and uses the lowered column count.
- `SSAListNew` allocates a temporary heap list header plus contiguous element
  storage using the phase 1 layout:

  ```llvm
  %AetherList = type { i64, i64, ptr }
  ; length, capacity, data
  ```

  In this phase `length == capacity` at literal construction and there is no
  growth or `realloc`.
- `SSAListLength` loads the `length` field and truncates it to Aether `int`.
- `SSAListIsEmpty` compares the `length` field with zero.
- `SSAListGet` loads an element from the contiguous `data` buffer for both
  lowered `for x in xs` loops and explicit `xs[i]` reads.
- `SSAListSet` loads the same `data` pointer and stores the element for
  `xs[i] = value`. It has no SSA result and is preserved as a side effect.
- `SSAListCopy` calls `aether_list_copy`, which allocates a distinct header and
  data buffer, then copies element representations with `llvm.memcpy`. The copy
  is shallow: pointer-valued elements keep the same pointer.
- `SSAListContains` calls a generated linear-search helper specialized for
  `int`, `double`, `boolean`, `string`, or reference values. Strings use
  `strcmp`; reference values use pointer equality.
- `SSAListReverse` calls an in-place byte-swap loop. It allocates no new list or
  data buffer and is preserved as a side effect.
- List references are passed and returned as the same header pointer, so an
  indexed store through an assignment, parameter, or returned alias is visible
  through every alias.
- `SSAReturn`.

This means an `if`/`else` where both branches return directly can compile to
LLVM IR, and an `if`/`else` that merges a supported scalar value can also be
emitted completely through `SSAPhi`, including string values as `ptr`.

String is now a full SSA value type in this subset. The backend keeps the
representation as LLVM `ptr`: general string operations remain unsupported,
but `List<string>.contains` compares contents with `strcmp`.

Direct recursion should work automatically because recursive calls use the same
ordinary LLVM call emission as any other direct function call. There is no
special recursion lowering in the backend.

`while` loops whose SSA form uses branches, jumps, phi nodes, and supported
calls can now be emitted by this backend subset.

Type mapping:

- `int` -> `i32`
- `void` -> `void`
- `bool` -> `i1`
- `double` -> `double`
- `string` -> `ptr`
- `List<T>` -> `ptr` to `%AetherList`

Example:

```llvm
define i32 @main() {
entry:
  %0 = add i32 2, 3
  ret i32 %0
}
```

Comparison example:

```llvm
define i1 @greater(i32 %a, i32 %b) {
entry:
  %0 = icmp sgt i32 %a, %b
  ret i1 %0
}
```

Control-flow example:

```llvm
define i32 @choose(i32 %x) {
entry:
  %0 = icmp sgt i32 %x, 0
  br i1 %0, label %then0, label %else0
then0:
  br label %merge0
else0:
  br label %merge0
merge0:
  %1 = phi i32 [ 1, %then0 ], [ 2, %else0 ]
  ret i32 %1
}
```

Call example:

```llvm
define i32 @identity(i32 %x) {
entry:
  ret i32 %x
}

define i32 @main() {
entry:
  %0 = call i32 @identity(i32 5)
  ret i32 %0
}
```

Cast example:

```llvm
define double @widen(i32 %x) {
entry:
  %0 = sitofp i32 %x to double
  ret double %0
}
```

String literal example:

```llvm
@.str.0 = private unnamed_addr constant [6 x i8] c"hello\00"

define ptr @hello() {
entry:
  ret ptr @.str.0
}
```

String phi example:

```llvm
define ptr @choose(i1 %flag) {
entry:
  br i1 %flag, label %then0, label %else0
then0:
  br label %merge0
else0:
  br label %merge0
merge0:
  %0 = phi ptr [ @.str.1, %then0 ], [ @.str.0, %else0 ]
  ret ptr %0
}
```

## Limitations

The backend deliberately does not support these yet:

- Full `List<T>` backend API. Phases 1 and 2 support list literals with an
  expected `List<T>` type, `.length`, `.is_empty`, List parameters/returns,
  `for x in xs` / `for T x in xs`, explicit indexed reads and indexed stores.
- List `copy`, `contains`, `indexOf`, `reverse`, `sort`, length-changing
  mutation, capacity growth, `realloc`, ownership, `free`, or GC.
- List indexing does not add bounds checks in phase 2; compiled out-of-range
  access has undefined behavior, matching the existing aggregate backend
  policy.

- implicit casts
- bool casts or string casts
- structs, classes, full List API, or complex numbers
- string concatenation, comparison, printing, length, indexing, mutation,
  heap allocation, or runtime ownership
- complex boolean lowering
- `println`
- general user/runtime calls beyond the backend helpers emitted internally
- ownership-aware heap allocation, deallocation, or collection
- imports or packages
- indirect calls, function pointers, or varargs
- LLVM optimization passes
- linking beyond invoking `clang` on the generated `.ll`
- cross-compilation
- JIT or `llc` build paths

Unsupported input raises `LLVMBackendError` with messages beginning with:

```text
LLVM backend does not support ...
```
