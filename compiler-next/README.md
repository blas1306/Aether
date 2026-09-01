# Aether NEXT-VERTICAL-4

This directory is the isolated Rust implementation of the first reconstruction
slice. It does not replace the production `aether` CLI or import any legacy
Python object, JSON schema, Initial IR, or SSA representation.

## Pipeline and crates

```text
entry SourceFile
  -> transitive discovery -> CompilationSession(module graph + source table)
  -> lexer/parser once per source -> ParsedProgram
  -> global declaration collection -> resolver/type analysis -> TypedHir
  -> CFG lowering -> FlowMir -> VerifiedMir
  -> scalar promotion -> SsaIr -> VerifiedSsa
  -> LLVM backend -> textual LLVM
  -> clang toolchain -> Linux x86_64 executable
```

- `aether-frontend`: `SourceId`-qualified spans, structured diagnostics,
  lexer/parser, resolved module graph, global declaration collection, name
  resolution and typed HIR.
- `aether-middle`: explicit CFG MIR, MIR verifier, pruned dominance-frontier SSA
  construction, dominance analysis and SSA verifier.
- `aether-backend-llvm`: the backend interface and textual LLVM implementation.
- `aether-driver`: the in-process session pipeline, phase timings, clang
  toolchain boundary and the internal `aether-next` command.

The workspace has no third-party Rust dependencies. This is intentional: the
closed grammar and scalar IR do not justify a parser framework, serialization,
LLVM binding, or general CLI dependency yet.

## Vertical-4 grammar

```text
program    := import* (alias | function)+ EOF
import     := "import" IDENT ";"
alias      := "alias" IDENT "=" type ";"
function   := type IDENT "(" parameters? ")" block
parameters := parameter ("," parameter)*
parameter  := type IDENT
type       := "bool" | integer-type | float-type | IDENT
block      := "{" statement* "}"
statement  := type IDENT "=" expression ";"
            | IDENT "=" expression ";"
            | "if" "(" expression ")" block ("else" block)?
            | "while" "(" expression ")" block
            | "return" expression ";"
expression := integer | float | "true" | "false" | IDENT | call | "(" expression ")"
call       := IDENT "(" arguments? ")"
            | IDENT "." IDENT "(" arguments? ")"
arguments  := expression ("," expression)*
            | "-" expression
            | expression ("*" | "/" | "%" | "+" | "-" | "<" | "<=" | ">" | ">="
                         | "==" | "!=") expression
```

After name/type resolution, a one-argument call whose callee names a built-in
or module-local alias type is an explicit value conversion:
`TargetType(expression)`. It is not an ordinary call, user-defined constructor,
bitcast or reinterpretation.

The canonical scalar set is `bool`, `int8`/`16`/`32`/`64`,
`uint8`/`16`/`32`/`64`, `isize`, `usize`, `float32` and `float64`. Transparent
built-ins are `int = int64`, `byte = uint8`, `float = float32`, and
`double = float64`. User `alias` declarations are module-local transparent
aliases; chains are canonicalized once and cycles are rejected.

Integer and floating literals remain source spellings until contextual typing;
unconstrained defaults are `int64` and `float64`. Non-literal implicit
conversions are limited to widening within the signed family, widening within
the unsigned family, and `float32 -> float64`. HIR records each widening as a
`SignExtend`, `ZeroExtend`, or `FloatExtend`; MIR and SSA verify it explicitly.
Signed/unsigned, integer/float, narrowing, and bool/numeric conversions remain
invalid implicitly. Explicit numeric conversions are represented by a fully
typed `CastKind`. Integer conversions trap rather than wrap when the value is
not representable; float-to-integer truncates toward zero and traps for NaN,
infinity or an unrepresentable result. Integer-to-float and float narrowing may
round according to IEEE semantics. Bool has no numeric conversions.

Canonical scalar types are explicit enums, not strings. A global `TypeId`
interner is intentionally deferred: it becomes useful when recursive composite
types and instantiated generics make structural type values recursive or
expensive, but adds no correctness or performance value for this closed scalar
set.

All integer `+`, `-`, `*`, and signed negation are checked at their exact
width. LLVM uses signed or unsigned overflow intrinsics without `nsw`/`nuw`.
Integer `/` returns the same promoted integer type and truncates toward zero
when signed. Integer `%` is the corresponding remainder, so `-5 % 2 == -1`.
Zero divisors trap; signed `MIN / -1` traps separately, while `MIN % -1` is
lowered safely to zero. Floats use ordinary strict-baseline
`fadd`/`fsub`/`fmul`/`fdiv` without fast-math; floating division by zero follows
IEEE and floating `%` remains rejected.
Floating `==`, `<`, `<=`, `>`, `>=` are ordered (false with NaN); `!=` is
unordered (true with NaN).

The driver treats the entry file's directory as the explicit bootstrap source
root. `import math;` resolves only `<source-root>/math.ae`; there is no PATH,
environment, standard-library, registry or manifest search. Discovery is a
linear work queue keyed by logical module name, so every reachable file is
read and parsed once even with shared dependencies or cycles.

`SourceId` qualifies every span and indexes source provenance. `ModuleId` is a
separate, session-local logical identity; source paths never become semantic
identity. The resolved module graph uses `ModuleId` edges. The bootstrap
visibility policy makes every top-level function in a discovered module
available through a direct qualified call, but imported functions never enter
unqualified scope. This policy is deliberately not the final v1 visibility
design.

The frontend collects every signature in every discovered module before
checking any body. `FunctionId` is global and dense within the compilation
session, while names and module spellings remain metadata after resolution.
Local/qualified calls both become a concrete `FunctionId`, admitting forward
calls, recursion, import cycles and cross-module mutual recursion without
textual or filesystem order exceptions. Parameters retain ordinary
function-local `LocalId` identities and scalar value semantics.

HIR carries the resolved module table and keeps the global function table
separate from typed bodies. MIR and SSA remain strictly function-local CFGs in
program containers; they do no module/name resolution. Dumps expose module and
source identities, import edges, global functions, parameters and resolved
calls.

## Development CLI

```bash
cargo run -p aether-driver --bin aether-next -- build input.ae -o output
cargo run -p aether-driver --bin aether-next -- run input.ae
cargo run -p aether-driver --bin aether-next -- build input.ae \
  --emit ast --emit hir --emit mir --emit ssa --emit llvm --timings
```

`run` calls the same build function with a temporary artifact and executes that
artifact. There is no interpreter or fallback.

## Qualification

Run all layer and native tests with:

```bash
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
tests/run-differential.sh
```

`tests/differential.tsv` remains the versioned scalar manifest. It distinguishes
legacy-equivalent cases, deliberate `int64` changes, v1-contract cases,
open-decision rejection and fail-closed rejection. The integration suite checks
all new-compiler admission expectations and executes multiple native artifacts.
Legacy-equivalent native cases are separately compared with the legacy CLI in
qualification environments that contain its Python dependencies.
`tests/modules/v1-contract.tsv` records the Vertical-2 multi-file contract;
these cases are not forced through legacy differential semantics.

## Bootstrap ABI and deliberate limits

One entry module plus transitively imported source modules and exactly one
selected `int main()` in the entry module are admitted. An imported module may
spell a function `main`, but it is never selected as process entry. Function
parameter and result lowering (`i64`/`i1`) is an
**internal bootstrap ABI**, not a stable Aether ABI and not `extern C`.
Bootstrap LLVM symbols use deterministic length-delimited logical module and
function names. They do not depend on discovery-order IDs and cannot collide
for the admitted identifiers. The scheme is intentionally temporary, is not a
public ABI, and still leaves packages, overload signatures and generic
substitutions for later milestones.

A generated platform `main` calls the internal Aether entry, truncates its
semantic `int64` result to the host `i32` process status, and returns that to
the toolchain. POSIX generally exposes only its low status byte. This mapping
is a platform/toolchain observable, not the final meaning of returning an
Aether `int`.

Modules are declaration-only: there are no globals, top-level statements,
module initializers or initialization order. This is precisely why import
cycles have no execution-order meaning in this slice. There are also no
packages, nested/selective/wildcard/aliased imports, reexports, visibility
keywords, overloads, generics, function values, closures, extern functions,
heap values, strings, aggregates, ownership, optimization
pipeline, public ABI, runtime, or LLVM library binding. Unsupported forms fail
closed before lowering.
