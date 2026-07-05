# Initial LLVM Backend

Aether now has a minimal textual LLVM IR backend under
`aether.backend.llvm`. It consumes verified-looking SSA modules directly and
returns a `.ll` string. The CLI inspection entry point is:

```bash
aether --emit-llvm hello.ae
```

The CLI also has a first native build command for the same limited subset:

```bash
aether build hello.ae
aether build hello.ae -o hello
aether build hello.ae --keep-llvm
```

`--emit-llvm` prints textual LLVM IR to stdout only. `aether build` writes LLVM
IR to a temporary `.ll` file and invokes `clang` to produce a native
executable. If `-o`/`--output` is omitted, the executable is written next to the
source file using the source path without `.ae`; for example
`examples/llvm/return_5.ae` produces `examples/llvm/return_5`. `--keep-llvm`
keeps the generated LLVM IR next to the executable output, for example
`hello.ll`.

Native builds require `clang` on `PATH`.

## Supported Subset

- SSA input: `SSAModule`.
- Functions with no parameters or integer parameters.
- Integer return values.
- Void functions with empty `return`.
- `SSAConst` integer values, emitted as immediate LLVM operands.
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
- `SSAReturn`.

Type mapping:

- `int` -> `i32`
- `void` -> `void`
- `bool` -> `i1`

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

## Limitations

The backend deliberately does not support these yet:

- structs, classes, lists, arrays, strings, complex numbers, or doubles
- complex boolean lowering
- `println`
- runtime calls
- heap allocation
- imports or packages
- LLVM optimization passes
- linking beyond invoking `clang` on the generated `.ll`
- cross-compilation
- JIT or `llc` build paths
- automatic execution after build
- `SSAPhi`, `SSABranch`, `SSAJump`, or `SSACall`
- branch/phi lowering for boolean control flow

Unsupported input raises `LLVMBackendError` with messages beginning with:

```text
LLVM backend does not support ...
```
