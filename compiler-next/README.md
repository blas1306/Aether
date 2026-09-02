# Aether NEXT-VERTICAL-7

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
  -> scalar and aggregate promotion -> SsaIr -> VerifiedSsa
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
closed grammar and compact IR do not justify a parser framework, serialization,
LLVM binding, or general CLI dependency yet.

## Vertical-7 grammar

```text
program    := import* (alias | struct | enum | function)+ EOF
import     := "import" IDENT ";"
alias      := "alias" IDENT "=" type ";"
struct     := "struct" IDENT "{" field* "}"
field      := type IDENT ";"
enum       := "enum" IDENT "{" variant ("," variant)* ","? "}"
variant    := IDENT | IDENT "(" type ("," type)* ")"
function   := type IDENT "(" parameters? ")" block
parameters := parameter ("," parameter)*
parameter  := type IDENT
type       := (IDENT ".")? ("bool" | integer-type | float-type | IDENT)
block      := "{" statement* "}"
statement  := type IDENT "=" expression ";"
            | place "=" expression ";"
            | "if" "(" expression ")" block ("else" block)?
            | "while" "(" expression ")" block
            | "match" "(" expression ")" "{" match-arm+ "}"
            | "return" expression ";"
match-arm  := variant-path ("(" IDENT ("," IDENT)* ")")? "=>" block
expression := integer | float | "true" | "false" | IDENT | apply
            | expression "." IDENT | "(" expression ")" | "-" expression
            | expression ("*" | "/" | "%" | "+" | "-" | "<" | "<=" | ">" | ">="
                         | "==" | "!=") expression
apply      := IDENT "(" arguments? ")"
            | IDENT "." IDENT "(" arguments? ")"
            | IDENT "." IDENT "." IDENT "(" arguments? ")"
variant-path := IDENT "." IDENT | IDENT "." IDENT "." IDENT
arguments  := expression ("," expression)*
place      := IDENT ("." IDENT)*
```

Application syntax remains neutral in the AST. Semantic analysis resolves its
source application/path to exactly one of `Call(FunctionId, ...)`, explicit
scalar conversion, `StructInit(StructId, ...)` or `EnumInit`; no ambiguity
survives HIR. The
canonical aggregate construction is positional, for example
`Point(3.0, 4.0)`. Arguments map to `FieldId`s in declaration order and every
field is required. This is structural construction, not a function call or a
user-defined constructor. Named initializers and named arguments are not part
of Vertical-5.

Structs are nominal, module-owned value types. Same-layout declarations have
different `StructId`s, including declarations with the same spelling in two
modules. Imported struct types and construction require direct qualification,
for example `geometry.Point`; imports never inject unqualified type names.
Transparent aliases to structs preserve the underlying nominal identity.
Functions, structs, enums and aliases share one fail-closed top-level namespace
per module, so an application spelling always has one interpretation.

Enums are nominal, module-owned value types. `EnumId` identifies a declaration
and `VariantId { enum_id, index }` identifies a declaration-order variant in
O(1); source spellings are metadata below HIR. Variants are never injected into
local scope. Construction
is qualified (`Number.Integer(42)`, payloadless `State.Idle`, and imported
`types.Number.Integer(42)`). Positional payloads use ordinary contextual literal
and widening rules. Transparent aliases preserve the original `EnumId` and may
qualify construction.

Vertical-6 `match` is a statement with block arms, positional payload bindings,
and no wildcard, guard, nested pattern or result value. Every variant must
occur exactly once. HIR resolves the scrutinee `EnumId`, every arm `VariantId`
and every binding `LocalId`, rejecting duplicates and missing variants before
MIR.

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

Canonical semantic types use the compact, copyable, session-local identity
`TypeId(u32)`. A session-owned `TypeArena` provides the only authoritative
`TypeId -> TypeData` mapping and interns the reverse `TypeData -> TypeId`
mapping. Its current data variants are `Bool`, `Integer`, `Float`,
`Struct(StructId)` and `Enum(EnumId)`. HIR is the first canonical boundary;
HIR, MIR, SSA, signatures, fields and enum payloads transport IDs rather than
copies of `TypeData`. MIR and SSA share the immutable arena through ordinary
Rust `Arc` ownership. IDs are never addresses, persistent fingerprints, ABI
identities or meaningful outside their owning compilation.

`StructId`, `EnumId`, `VariantId` and `FieldId` remain declaration/component
identities. Interning `Struct(StructId)` or `Enum(EnumId)` preserves nominality,
so equal layouts never imply equal `TypeId`s. Transparent built-in and user
aliases resolve directly to the underlying ID and do not receive a `TypeData`
variant. In particular `int == int64`, `float == float32`, `double == float64`
and `byte == uint8`, while `isize != int64` and `usize != uint64` even on
x86_64.

Struct and enum declarations are collected in all discovered modules before
aliases, payload/field types and function signatures are resolved. A
target-aware DFS rejects self and mutual by-value recursion across both
aggregate kinds, calculates nested size/alignment/padding,
and preserves source field order as physical bootstrap order. `layout_of`
forms the shared `(TypeId, TargetProperties) -> TypeLayout` boundary; aggregate
results are cached in declaration metadata once per single-target session.
Reordering fields
is therefore a source API change. The layout and aggregate calling convention
are internal bootstrap contracts, not public ABI.

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
visibility policy makes every top-level function, struct and enum in a
discovered module available through a direct qualifier, but imported declarations never
enter unqualified scope. This policy is deliberately not the final v1
visibility design.

The frontend collects every struct/enum identity and signature in every
discovered module before checking any body. `FunctionId` is global and dense within the compilation
session, while names and module spellings remain metadata after resolution.
Local/qualified calls both become a concrete `FunctionId`, admitting forward
calls, recursion, import cycles and cross-module mutual recursion without
textual or filesystem order exceptions. Parameters retain ordinary
function-local `LocalId` identities and value semantics.

HIR carries the canonical type arena, `StructInfo`/`FieldInfo` and
`EnumInfo`/`VariantInfo` tables plus
fully resolved `StructInit`, `EnumInit`, matches and field places. MIR uses the
reusable `Place { local, projections: FieldId* }`
model for reads and nested stores. SSA promotes aggregates as ordinary SSA
values: construction is `Aggregate`, field reads are `ExtractField`, and field
mutation produces a new aggregate with `InsertField`. This functional update
strategy makes copy-by-value observable without `alloca`, MemorySSA, sharing or
ownership machinery. LLVM lowers these operations to named aggregate types,
`insertvalue` and `extractvalue`; aggregate parameters and results use the
internal bootstrap ABI by value.

MIR lowers enum matching to `EnumDiscriminant` and a reusable multi-way
`Switch`; arm entries perform explicit `EnumPayload` copies into binding locals.
SSA retains verified `EnumConstruct`, tag, payload and switch operations. LLVM
uses a fixed bootstrap `i32` tag and a typed envelope
`{ tag, variant-0-tuple, variant-1-tuple, ... }`, initialized from zero. This is
larger than a byte union but avoids type-punning, stack storage and MemorySSA.
Tags follow declaration order from zero. Tags, layout and aggregate calling
convention remain internal bootstrap details; niche/union compaction is
deferred.

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

`tests/differential.tsv` remains the versioned admission manifest. It distinguishes
legacy-equivalent cases, deliberate `int64` changes, v1-contract cases,
open-decision rejection and fail-closed rejection. The integration suite checks
all new-compiler admission expectations and executes multiple native artifacts.
Legacy-equivalent native cases are separately compared with the legacy CLI in
qualification environments that contain its Python dependencies.
`tests/modules/v1-contract.tsv` records the Vertical-2 multi-file contract;
these cases are not forced through legacy differential semantics.

### Vertical-7 timing snapshot

A warm debug-build comparison against the pre-migration `HEAD`, using 30 full
compilations of `tests/programs/v6_enums.ae`, measured means in the low
microseconds: frontend signature+body analysis 195.1 -> 278.6 us, MIR verify
107.8 -> 112.0 us, and SSA verify 142.8 -> 157.0 us. The frontend phase boundary
also moved target layout from signature collection into semantic analysis.
These tiny-input figures are noisy, but they show a real current cost from
arena construction/property lookup and the new invalid-ID integrity scans.
`TypeId` itself is 32-bit and comparisons avoid copying/matching `TypeData`;
MIR/SSA share the arena with `Arc` instead of cloning it. Optimizing the scans or
property-query hot paths is accepted follow-up debt; no unsafe/global cache or
weaker verification was introduced to improve this microbenchmark.

## Bootstrap ABI and deliberate limits

One entry module plus transitively imported source modules and exactly one
selected `int main()` in the entry module are admitted. An imported module may
spell a function `main`, but it is never selected as process entry. Function
parameter and result lowering (scalars and LLVM aggregates) is an
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
heap values, strings, named initializers, methods, ownership, optimization
pipeline, public ABI, runtime, or LLVM library binding. Unsupported forms fail
closed before lowering.
