# Aether Native Profile v1

> Classification: **Normative**. Language contract **Aether 1.0 stable
> profile**; native capability profile schema/version `23`. This profile is
> frozen for the `1.0.0-rc.4` candidate; the language and capability profile
> versions are independent identifiers.

## 1. Conformance language

The terms **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative. Text
explicitly labelled informative is not a conformance requirement.

This document gives the executable LLVM/native capability refinement of the
language specified by
[Aether 1.0 Language Specification](AETHER_LANGUAGE_SPEC_V1.md). It neither
widens nor narrows that current language contract. Frontend-only experiments
are outside Aether 1.0. The dated profile-22 audit is historical evidence and
is not an authority over this current reference.

## 2. Conforming implementation

A conforming Aether v1 native implementation:

- **MUST** parse and type-check before backend selection;
- **MUST** run the profile-23 capability detector before IR lowering;
- **MUST** accept a program only when every detected use is inside the native
  subset, including the restrictions described below;
- **MUST** reject an excluded use with an `AE-BACKEND-*` diagnostic, source
  location, capability, and typed reason before backend-specific lowering;
- **MUST NOT** silently fall back to AST execution;
- **MUST** preserve, for every accepted program, the observable AST/native
  parity contract in section 7.

The executable CLI entry points are `aether FILE`, `aether run FILE`, and
`aether build FILE -o OUTPUT`. `--emit-ir`, `--emit-cfg`, `--emit-ssa`, and
`--emit-llvm` are inspection interfaces, not additional language profiles.

## 3. Generated capability inventory

The following block is generated from `NATIVE_CAPABILITY_PROFILE` in
`src/aether/capabilities.py`. `python scripts/render_native_profile.py --check`
**MUST** fail if the checked-in table differs. A state has these meanings:

- **COMPLETE**: every language use represented by that capability and admitted
  by its typed detector is supported end to end.
- **PARTIAL**: only the subset in section 4 and in the typed capability gate is
  supported. A partial state is never permission to attempt unsupported code.
- **UNSUPPORTED**: every detected use is rejected before lowering.

<!-- BEGIN GENERATED CAPABILITY PROFILE -->
Profile schema/version: `23`.

Inventory: 32 COMPLETE, 31 PARTIAL, 3 UNSUPPORTED.

| Capability | State | Contract area |
| --- | --- | --- |
| `primitive-types` | **PARTIAL** | Primitive scalar and nullable types. |
| `variables-and-const` | **PARTIAL** | Variable and const declarations. |
| `arithmetic` | **PARTIAL** | Scalar arithmetic and comparisons. |
| `integer-safety` | **COMPLETE** | Checked i32 arithmetic and division. |
| `functions` | **PARTIAL** | Typed functions, parameters, calls, and recursion. |
| `void-functions` | **COMPLETE** | Functions and calls returning void. |
| `function-values` | **PARTIAL** | Typed top-level callable values plus AST expression-function compatibility. |
| `return` | **COMPLETE** | Function return statements. |
| `if` | **COMPLETE** | Conditional control flow. |
| `while` | **COMPLETE** | While loops. |
| `for` | **PARTIAL** | Inclusive integer range loops. |
| `for-in` | **PARTIAL** | Iteration over collection values. |
| `break` | **COMPLETE** | Loop break statements. |
| `continue` | **COMPLETE** | Loop continue statements. |
| `strings` | **PARTIAL** | String values and string operations. |
| `string-transport` | **COMPLETE** | String literals, parameters, fields, elements, and returns. |
| `string-equality` | **COMPLETE** | Length-aware string equality and inequality. |
| `dynamic-string-object` | **COMPLETE** | Owned immutable UTF-8 string objects. |
| `string-lifecycle` | **PARTIAL** | Retain/release and recursive string value lifecycle. |
| `string-concatenation` | **COMPLETE** | Public string concatenation. |
| `string-byte-length` | **COMPLETE** | Constant-time public string byte length. |
| `string-parsing` | **COMPLETE** | Public parsing from strings. |
| `integer-string-parsing` | **COMPLETE** | Strict structured decimal parsing from string to int. |
| `double-string-parsing` | **COMPLETE** | Strict structured locale-independent parsing from string to double. |
| `string-trim` | **COMPLETE** | Explicit trimming of Aether v1 ASCII whitespace. |
| `string-split` | **COMPLETE** | Exact byte-based string splitting into owned fields. |
| `print` | **PARTIAL** | print and println output. |
| `input` | **UNSUPPORTED** | Typed input calls. |
| `process-arguments` | **PARTIAL** | Access to process arguments. |
| `cli-argument-forwarding` | **COMPLETE** | CLI forwarding after the first -- separator. |
| `modules` | **PARTIAL** | Package and module units. |
| `imports` | **PARTIAL** | Module and symbol imports. |
| `structs` | **PARTIAL** | Struct values and fields. |
| `struct-constructors` | **PARTIAL** | Struct constructors. |
| `struct-methods` | **PARTIAL** | Struct methods and this. |
| `classes` | **COMPLETE** | Reference-semantics classes. |
| `class-constructors` | **COMPLETE** | Class constructors. |
| `class-methods` | **COMPLETE** | Class methods and this. |
| `interfaces` | **COMPLETE** | Nominal interfaces with class carriers, struct boxing, witness dispatch, and ownership. |
| `enums` | **COMPLETE** | Enums without payloads. |
| `array` | **PARTIAL** | Array values and operations. |
| `array-slicing` | **PARTIAL** | Array and collection slicing. |
| `list` | **PARTIAL** | List values and operations. |
| `const-collection-references` | **COMPLETE** | Read-only Array/List access paths rooted at a const reference. |
| `borrowed-for-in-elements` | **COMPLETE** | Read-only non-owning Array/List element bindings in for-in. |
| `collection-object-lifecycle` | **COMPLETE** | Strong RC ownership and final destruction for Array/List objects. |
| `aggregate-collection-elements` | **PARTIAL** | By-value aggregate elements in Array and List storage. |
| `structural-equality` | **COMPLETE** | Typed structural Eq(T) for structs and Array/List values. |
| `eq-collection-search` | **COMPLETE** | List contains/indexOf using the element type's Eq(T). |
| `vector` | **PARTIAL** | Vector values and operations. |
| `matrix` | **PARTIAL** | Matrix values and operations. |
| `scalar-math` | **PARTIAL** | Scalar mathematical functions and constants. |
| `generics` | **UNSUPPORTED** | User-defined generic declarations. |
| `error-handling` | **UNSUPPORTED** | Native exception semantics: throw, rethrow, try/catch, and propagation from throwing calls. |
| `files` | **PARTIAL** | Language-level file input and output. |
| `text-file-read` | **PARTIAL** | Complete UTF-8 text-file reads. |
| `text-file-write` | **PARTIAL** | Complete UTF-8 text-file writes. |
| `text-file-append` | **PARTIAL** | Complete UTF-8 text-file appends. |
| `atomic-text-file-write` | **PARTIAL** | Atomic same-filesystem UTF-8 text-file replacement. |
| `durable-text-file-write` | **PARTIAL** | Durable UTF-8 text-file replacement with file and directory fsync. |
| `alpt1-encode` | **COMPLETE** | Manual canonical ALPT1 Transaction ledger encoding. |
| `alpt1-decode` | **COMPLETE** | Fail-closed byte-aware ALPT1 Transaction ledger decoding. |
| `expense-ledger-load` | **COMPLETE** | Expense ledger loading through io.readText and ALPT1 decode. |
| `expense-ledger-save` | **COMPLETE** | Expense ledger saving through canonical ALPT1 encoding. |
| `expense-ledger-atomic-save` | **PARTIAL** | Atomic and durable POSIX expense ledger saving through io.writeTextAtomic. |
| `optimization-profiles` | **PARTIAL** | Selectable compiler optimization profiles. |
<!-- END GENERATED CAPABILITY PROFILE -->

## 4. Exact partial-subset rules

These rules refine every **PARTIAL** row. The programmatic gate is the
executable authority for combinations of these rules; its positive and
negative corpus is part of this profile.

- Primitive types, variables, arithmetic, functions, calls and comparisons
  support `int`, `double`, and `boolean`, plus the explicitly complete string,
  nullable, enum, struct, class, interface and collection cases below. Native
  **MUST reject** `float`, `complex`, tuples/destructuring and any conversion,
  cast, operator, builtin, print shape or ABI position without native lowering.
  The supported numeric subset includes contextual `int -> double`, mixed
  `int`/`double` arithmetic and comparisons, identity `int`/`double` casts,
  checked `int ^ int`, and libm-backed power whenever either operand is
  `double`. `double -> int` remains explicit.
- `for` supports inclusive integer ranges with positive, negative or dynamic
  nonzero steps. A statically zero step **MUST** be rejected by the gate; a
  runtime zero step **MUST** panic.
- Function values are capture-free top-level user functions with an exact
  structural `R(P1, ...)` signature. Closures, lambdas, bound methods, builtins
  or builtins as values, returned callables, and unspecialized
  generic functions are excluded.
- Strings support UTF-8 transport, ARC lifecycle, content equality,
  concatenation, `byteLength`, `trim`, `split`, `parseInt`, and `parseDouble`.
  Interpolation and implicit formatting are excluded.
- Modules support complete/selective imports and aliases, transitive calls,
  privacy, functions, supported structs, methods and signatures. Imported
  globals, constants requiring storage, and executable top-level module
  initialization are excluded.
- Structs are acyclic nominal value layouts composed only of backend-supported
  fields. Construction, methods, assignment/copy, parameters, owned returns,
  printing and equality are supported when every transitive field has layout,
  lifecycle and `Eq` where required.
- Nullable `T?` is a tagged `{present,payload}` value for every representable
  payload. Classes are non-null reference handles with ARC, definite field
  initialization, identity equality, constructors and static method dispatch.
  Interfaces are `{carrier,witness}` values with witness-driven calls,
  class-carrier aliasing, owned struct boxes, and type-directed copy/drop.
- `Array<T>` and `List<T>` support reference assignment, lifecycle, explicit
  shallow `copy()`, copying slices, const aliases, borrowed `for-in`, structural
  equality and the registered operations when `T` has a supported native
  layout and required lifecycle/`Eq` hooks. Unsupported aggregate element
  layouts are rejected.
- Vector/Matrix support the typed, shaped `int`/`double` core registered by the
  gate. A function, struct or collection boundary that would lose required
  shape metadata is excluded. Advanced `Math.LinearAlgebra` remains AST-only.
- Scalar math is exactly the consolidated real surface: `sin`, `cos`, `tan`,
  `exp`, `ln`, `log`, `sqrt`, `abs`, `Math.mod`, `Math.factorial`,
  `Math.floor`, `Math.ceil`, and `Math.pi`, subject to typed overloads.
  Experimental complex functions are excluded.
- Process arguments support `System.args()` on the supported native platform.
  Text files support `io.readText`, `io.writeText`, `io.writeTextAtomic`, and
  `io.appendText` on that platform. Files do not imply binary IO, streams,
  directories, locks, backups or general transactions.
- ALPT1 capabilities cover only the checked-in revision-1 Expense Tracker
  codec and its atomic-save dogfood; they do not define reflection or generic
  serialization.
- Optimization profile names describe compiler validation coverage. They do
  not promise different optimization strength: the current public `-O2`
  inspection profile aliases `-O1`.

## 5. Excluded capabilities

Profile 23 supports tagged nullable values, concrete classes, constructors,
statically dispatched class methods, and nominal interfaces. Interface support
includes class carriers, owned struct boxes, declaration-ordered witness
dispatch, nullable and collection transport, and type-directed copy/drop.

It rejects `input`, user generics, and `throw`/`try`/`catch`. Interface
inheritance/default methods, class inheritance/override, downcasts, reflection,
user destructors, weak references, exceptions/unwind, and stable FFI remain
outside the profile. The obsolete staging capability `native-interface-abi`
and combined capability `string-split-trim` are not catalog entries in profile
23; `interfaces`, `string-split`, and `string-trim` are the authoritative
granular capabilities.

Internal exception qualification does not widen this profile. Its accepted
contract requires `Error.message()` to be semantically non-throwing: lowering
must use a call with no Aether exceptional successor, while unrecoverable
internal failure remains panic/fail-fast. No second `Error` or recursive
exception handling is permitted. `ERROR_HANDLING` is required only when
execution may require native exception semantics: `throw`, rethrow,
`try`/`catch`, throwing bodies or constructors, and calls/invokes that require
exception propagation. Merely implementing `Error` or using `Error` values as
ordinary interface values—including `Error.message()`, parameters, returns,
storage, nullable values, and containers—does not require the capability.
`ERROR_HANDLING` remains `UNSUPPORTED`.

## 6. Platform and toolchain

The validated RC native platform is **Linux x86_64** with a `clang` executable
on `PATH`. Release validation uses clang 21, but the release does not declare a
stable LLVM IR or C ABI and does not bundle clang. The generated runtime is
emitted into LLVM IR by the installed Python package; no source checkout or
separate Aether runtime installation is permitted.

The implementation **MUST** diagnose a missing clang clearly. Windows is not a
supported native platform: process arguments and file paths still require an
explicit UTF-16 boundary. POSIX in general is not claimed because errno, path,
atomic replacement and durability behavior have only been validated on Linux.

The auxiliary AST differential reference is exercised on Linux x86_64 with
CPython 3.10 or newer. That host configuration is test infrastructure, not a
second language or release platform.

## 7. Observable parity guarantee

For every program accepted by profile 23, AST and native execution **MUST**
agree on:

- stdout bytes and stderr bytes, including the public formatting of values;
- process exit code;
- panic message, public stream and exit code;
- final bytes of files included in the parity case.

The differential runner compares all of these under controlled locale and
environment at clang `-O0`, `-O1`, and `-O2`. Native panics terminate with exit
code 1 and do not unwind Aether frames. A profile-conforming optimizer **MUST
NOT** remove or reorder observable traps, allocation, IO, or lifecycle effects.

## 8. Informative implementation note

Profile 23 is a feature-contract version, not the Aether language version and
not an ABI version. Increasing it records a changed capability boundary. It
does not by itself change package metadata or plugin compatibility. Profile 23
was bumped because Phase 5.2–5.4 materially added nullable, class, and complete
interface execution to the native boundary after profile 22 was frozen.
