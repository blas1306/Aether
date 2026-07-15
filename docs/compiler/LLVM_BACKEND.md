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

## Runtime architecture

The textual runtime is assembled on demand from three focused generators:

- `array_runtime.py` owns `%AetherArray = type { i64, ptr, i64 }`, Array allocation,
  checked length conversion, bounds panic/checks, and Array field accessors.
- `list_runtime.py` owns `%AetherList = type { i64, i64, ptr, i64 }`, capacity,
  growth, and List-only operations.
- `runtime_common.py` owns checked allocation arithmetic, checked `malloc`,
  deduplicated libc/intrinsic declarations, and the sort helpers shared by
  Array and List.

This split does not change either layout or ABI. Array and List still use
different data field indices and only share semantics independent of their
headers. Representative Array/List LLVM output remained byte-identical through
the extraction.

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
| `list_index_of.ae` | 12 |
| `list_set_alias.ae` | 9 |
| `list_copy.ae` | 19 |
| `list_contains.ae` | 1 |
| `list_reverse.ae` | 41 |
| `list_sort.ae` | 123 |
| `array_sort.ae` | 124 |

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
  %AetherList = type { i64, i64, ptr, i64 }
  ; length, capacity, data
  ```

  Literal construction validates nonnegative length and checked
  `length * element_size` before allocating either header or data, then starts
  with `length == capacity`; later `push` may grow and replace `data` while
  retaining this header pointer.
- `SSAListLength` loads the `length` field and calls
  `aether_list_length_to_int`. Values in `0..INT32_MAX` convert to Aether
  `int`; larger or invalid values panic with
  `Aether panic: List length does not fit in int`.
- `SSAListIsEmpty` compares the `length` field with zero.
- `SSAListGet` sign-extends the source index, calls the private
  `aether_list_check_index` helper, and only then loads an element from the
  contiguous `data` buffer. This applies to lowered `for x in xs` loops and
  explicit `xs[i]` reads.
- `SSAListSet` uses the same check before loading `data`, calculating the
  element GEP, or storing for `xs[i] = value`. It has no SSA result and is
  preserved as a side effect.
- `aether_list_check_index` loads `length` and requires
  `index >= 0 && index < length`. Failure calls a private `noreturn` panic
  helper, prints `Aether panic: List index out of bounds`, and exits with code
  1. Thus an invalid set cannot write the list buffer.
- `SSAListCopy` calls `aether_list_copy`, which allocates a distinct header and
  data buffer, then copies element representations with `llvm.memcpy`. It
  validates bytes before calling `aether_list_new`, skips memcpy for zero
  bytes, and never copies with a wrapped size. The copy is shallow:
  pointer-valued elements keep the same pointer.
- `SSAListContains` calls a generated i64 linear-search helper specialized for
  `int`, `double`, `boolean`, `string`, or reference values. Strings use
  `strcmp`; reference values use pointer equality. It compares the i64 result
  with `-1` directly and does not narrow an index merely to answer boolean.
- `SSAListIndexOf` calls the same i64 search and then
  `aether_list_index_to_int`: absence remains `-1`, a found index through
  `INT32_MAX` converts to i32, and a larger index panics with
  `Aether panic: List index does not fit in int`.
- `SSAListClear` has no result and is side-effecting. It emits only a GEP to
  field 0 of `%AetherList` followed by `store i64 0`; it does not load or store
  capacity/data and does not allocate, free, or call a runtime helper.
- `SSAListPush` has no result and is side-effecting. It checks `length + 1`,
  calls internal `aether_list_reserve`, reloads `data`, stores the shallow
  element representation, and updates `length` only after the store. Reserve
  grows `0 -> 1` or doubles capacity, validates arithmetic overflow, uses a
  checked allocation, copies existing bytes, frees the old owned buffer, and
  updates `data`/`capacity` without replacing the header.
- `SSAListPop` is side-effecting and produces the list element type. It checks
  `length == 0` through the existing panic mechanism before subtracting,
  loads `data[length - 1]`, then stores the new length. It does not call
  reserve, allocate, free, shrink, clear the dead slot, or change capacity,
  data, or the header pointer. Pointer-valued elements are returned shallowly.
- `SSAListReverse` calls an in-place byte-swap loop. It allocates no new list or
  data buffer and is preserved as a side effect.
- `SSASequenceSort` is the common side-effecting instruction for
  `List<T>.sort()` and `Array<T>.sort()`. Lowering extracts the existing data
  pointer and current length, then calls exactly one type-specialized helper:
  `aether_sort_i32`, `aether_sort_f64`, or `aether_sort_string`.
- The sort helpers implement stable bottom-up merge sort with `O(n log n)`
  time and `O(n)` temporary storage. They never replace the collection header
  or data buffer and therefore preserve identity, length, array size, and list
  capacity. The `double` helper places NaNs last and treats signed zeroes as
  equivalent; the string helper uses locale-independent unsigned UTF-8 byte
  order through `strcmp`.
- Sort validates `length * element_size` before allocating its temporary
  buffer, checks each copied run size, clamps merge bounds using remaining
  lengths, and branches before doubling width. No temporary allocation,
  pointer offset, or memcpy size is derived from wrapped arithmetic.
- `aether_checked_mul_i64` centralizes unsigned i64 multiplication checks;
  `aether_checked_allocation_bytes` adds nonnegative length/element-size
  validation. `aether_alloc` checks nonzero `malloc` results and delegates to
  `aether_allocation_failure_panic`.
- List references are passed and returned as the same header pointer, so an
  indexed store through an assignment, parameter, or returned alias is visible
  through every alias.
- `SSAReturn`.

This means an `if`/`else` where both branches return directly can compile to
LLVM IR, and an `if`/`else` that merges a supported scalar value can also be
emitted completely through `SSAPhi`, including string values as `ptr`.

String is now a full SSA value type in this subset. The backend keeps the
representation as LLVM `ptr`: general string operations remain unsupported,
but `List<string>.contains` and `List<string>.indexOf` compare contents with
`strcmp`.

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

- Full `List<T>` backend API. Phases 1, 2, 3, `clear` from phase 4a, `push` from phase 4b, and `pop` from phase 4c support list literals with an
  expected `List<T>` type, `.length`, `.is_empty`, List parameters/returns,
  `for x in xs` / `for T x in xs`, explicit indexed reads and indexed stores.
- Length-changing mutation other than `clear`/`push`/`pop`, shrinking, public
  reserve, general ownership, or GC. `clear`, `push`, `pop`, `copy`, `contains`,
  `indexOf`, `reverse`, and stable `sort` are supported. `clear` preserves
  capacity/data; pop also preserves them, while push may replace the owned data
  buffer but preserves header.
- List and Array get/set indexing have native bounds checks and controlled,
  container-specific panics. General Vector and Matrix bounds checks remain
  outside this backend increment.

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
