# Aether public diagnostics contract

This document defines the stable public diagnostic categories and codes for
Aether 1.0. Diagnostic wording may improve; category and code meanings are
stable within the 1.x line.

## Categories

| Category | Meaning | Default exit |
| --- | --- | ---: |
| `syntax` | The source is not valid Aether syntax. | 1 |
| `type` | The source violates a static semantic or type rule. | 1 |
| `capability` | Valid source requests a feature unavailable in the selected backend. | 1 |
| `runtime` | The Aether program failed while executing. | 1 |
| `toolchain` | A required external build tool is absent or cannot be invoked. | 3 |
| `internal_compiler_error` | An accepted program exposed a compiler invariant failure or unexpected compiler exception. | 70 |

CLI usage errors use exit 2, interruption uses exit 130, and success uses exit
0. A successfully executed native program otherwise returns its own exit code.

`verification` is an internal compiler phase, not a normal source-error
category. `IRVerificationError` and `SSAVerificationError` remain available to
internal APIs and unit tests that construct arbitrary IR, but a failure reached
while compiling Aether source is reported publicly as `internal_compiler_error`.

## Stable codes

| Code | Public meaning |
| --- | --- |
| `AE-SYNTAX-001` | Syntax error. |
| `AE-TYPE-001` | Type or static semantic error. |
| `AE-ERROR-MESSAGE-NONTHROWING` | An `Error.message()` implementation may produce an Aether exception, violating its language-defined non-throwing contract. |
| `AE-BACKEND-*` | Backend capability rejection; the existing detailed suffix is preserved. |
| `AE-RUNTIME-001` | Aether runtime error. |
| `TOOLCHAIN-CLANG-001` | Clang is missing or cannot be invoked. |
| `ICE-IR-VERIFY-001` | Aether generated invalid IR. |
| `ICE-SSA-BUILD-001` | Aether failed to construct SSA from valid IR. |
| `ICE-SSA-VERIFY-001` | Aether generated invalid SSA. |
| `ICE-LLVM-EMIT-001` | LLVM emission was invalid or rejected by Clang. |
| `ICE-NATIVE-BOUNDARY-001` | Native exception containment verification rejected an unsafe compiler-generated boundary. The note carries the internal `NBV-*` reason documented in `NATIVE_BOUNDARY_CONTAINMENT.md`. |
| `ICE-OPT-001` | An optimizer invariant failed unexpectedly. |
| `ICE-UNEXPECTED-001` | An otherwise unclassified compiler exception escaped. |

Clang rejecting LLVM emitted by Aether is a compiler bug, not a generic
toolchain failure. A missing Clang executable is a toolchain error. Technical
Clang stderr is summarized by default and is available in debug output.

## Debug mode and reporting bugs

Normal diagnostics never include Python tracebacks. An ICE names its phase and
source filename, explains that the failure is a compiler bug, and suggests
running the same command with `--debug`. Debug mode adds the original exception,
cause chain, traceback, and relevant internal paths; it does not alter language
or execution semantics. Syntax, type, capability, and runtime errors remain
traceback-free under `--debug`.

When reporting an ICE, include the Aether version, command mode/backend,
platform, stable ICE code, the smallest source that reproduces it, and debug
output after reviewing it for local paths or other private data.

The LSP never publishes exception objects or Python tracebacks as source
diagnostics. An analyzer failure is summarized with `ICE-UNEXPECTED-001`.
