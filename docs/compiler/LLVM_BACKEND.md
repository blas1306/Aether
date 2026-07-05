# Initial LLVM Backend

Aether now has a minimal textual LLVM IR backend under
`aether.backend.llvm`. It consumes verified-looking SSA modules directly and
returns a `.ll` string. It is intentionally not connected to the CLI yet.

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

## Limitations

The backend deliberately does not support these yet:

- structs, classes, lists, arrays, strings, complex numbers, or doubles
- complex boolean lowering
- `println`
- runtime calls
- heap allocation
- imports or packages
- LLVM optimization passes
- automatic linking
- automatic execution
- CLI flags such as `--emit-llvm`
- `SSAPhi`, `SSABranch`, `SSAJump`, `SSACall`, or `SSACompareOp`

Unsupported input raises `LLVMBackendError` with messages beginning with:

```text
LLVM backend does not support ...
```
