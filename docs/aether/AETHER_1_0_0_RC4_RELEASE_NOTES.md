# Aether 1.0.0-rc.4 — Release notes

> Classification: **Current reference** for the `1.0.0-rc.4` candidate.

## What RC4 is

Aether 1.0.0-rc.4 reconciles the compiler implemented through Phase 5.4 with
native capability profile 24. It is still a release candidate, does not claim
production readiness, and does not define a public ABI. The Python package
identity is `1.0.0rc4`; the planned tag is `v1.0.0-rc.4`.

Profile 24 promotes the qualified native exception implementation after
profile 23 added nullable values, reference-semantics classes, class methods,
and interfaces with class carriers and struct boxing. The historical `native-interface-abi` staging
capability and the combined `string-split-trim` capability were removed.
Granular `interfaces`, `string-split`, and `string-trim` capabilities describe
the compiler directly.

## Optimizer and consistency remediation

- IR and SSA optimizer operand traversal is structural and covers every
  dataclass instruction, including class, interface, lifecycle, indirect-call,
  collection, and phi operands.
- Dead-phi elimination, trivial-phi rewriting, algebraic simplification, DCE,
  SCCP use tracking, and copy-like replacement paths share that traversal.
- Capability, profile, documentation, examples, and release validation are
  checked before the Python suite in local CI.
- Dated Phase 6.0 and earlier audits are historical evidence, not current
  normative references.
- The schema-2 catalog classifies 95 examples as `V1_NATIVE`, 19 as
  `AST_ONLY_EXPERIMENTAL`, and none as `BROKEN`.

## Backends and limits

LLVM/native is the release backend for the profile. The AST interpreter is an
auxiliary semantic reference and supports additional experiments. Native
interfaces include declaration-ordered witness dispatch, class carriers,
owned struct boxes, nullable/collection transport, and type-directed copy/drop.
Inheritance, interface inheritance, default methods, downcasts, reflection,
user-defined destructors, foreign exception unwinding, weak references, and a stable FFI
remain outside the profile.

The accepted 2026-08-09 Exception Release Qualification v2 decision promotes
native `error-handling` to `COMPLETE`. Stable Linux x86_64 execution uses the
private event-out implementation. LLVM EH remains comparison/test-only, panic
remains uncatchable, `Error.message()` remains nonthrowing, and throwable
foreign calls or callbacks remain unsupported and fail closed.

The validated native platform remains Linux x86_64 with `clang` on `PATH`.

## Installation

```bash
python3 -m venv .venv
.venv/bin/python -m pip install dist/aether_language-1.0.0rc4-py3-none-any.whl
.venv/bin/aether --version
```

Expected identity:

```text
Aether 1.0.0-rc.4
Native capability profile 24
```
