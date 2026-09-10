# LANGUAGE-PARITY-1 — main fallthrough and source comments

Implemented and qualified on 2026-09-10, Linux x86-64. Scope is limited to
compiler-next and its documentation. No script mode, exceptions, classes,
interfaces, module semantics or runtime facilities were introduced.

## 1. Initial main behavior

Signature collection selected the root module's `main` and checked canonical
int64 plus zero parameters. Every body, including main, then required
`definitely_returns`, rejecting an empty main with E0207. Explicit main results
already flowed to the native process status. Generic main was not deliberately
admitted: its signature escaped the entry check and could reach the
monomorphizer's `non-generic entry was seeded` panic. It now receives E0201.

## 2. Initial lexer/trivia behavior

The lexer skipped space, tab, CR and LF directly in its token match. It had no
line/block comments or trivia storage. `/` and `*` were separate operator tokens.
Spans were already half-open UTF-8 byte ranges with SourceId; SourceFile derived
one-based lines and Unicode scalar columns from the original source. Strings
were not admitted.

## 3. Files changed

| File | Change |
|---|---|
| `compiler-next/crates/aether-frontend/src/lexer.rs` | Central trivia skipping, E0002 and four new lexer tests |
| `compiler-next/crates/aether-frontend/src/hir.rs` | Entry generic validation, generated-return provenance and normalization |
| `compiler-next/crates/aether-driver/tests/language_parity.rs` | Seven cross-layer/native regression tests |
| `compiler-next/tests/programs/language_parity_1.ae` | Required commented empty-main integration fixture |
| `compiler-next/tests/programs/missing_return.ae` | Preserve E0207 regression using an ordinary helper |
| `compiler-next/README.md` | Current entry/comment behavior and report link |
| `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | Admitted language guarantees |
| `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | Normative signature, returns, trivia and positions |
| `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | Phase authorities and unchanged downstream lowering |
| `docs/architecture/LANGUAGE_PARITY_1_REPORT.md` | This qualification report |

Existing unrelated untracked files were preserved. compiler-rs, legacy runtime,
legacy CLI and scrap were not modified.

## 4. Entry-point authority

`collect_program_signatures` resolves main only in `ParsedProgram.entry` and
stores its FunctionId as `DeclaredProgram.entry`. Normalization tests that
identity, not the function's spelling. Imports can define ordinary main helpers,
including bool-returning ones; importing them neither selects nor normalizes
them. A called helper main returning 7 still returns 7 natively. Missing main,
duplicate/conflicting declarations and invalid signatures retain existing routes.

## 5. Accepted main signature

Non-generic `int main()` with zero parameters and canonical int64 result.
The existing authoritative transparent alias rule also accepts `int64 main()`
and user aliases of int64. These are equivalent type spellings, not alternative
entry signatures. bool/double/int32 results, parameters and generic main receive
E0201. void and omitted return types remain invalid under existing diagnostics.

## 6. Implicit main return semantics

If the selected entry body is not definitely returning, HIR appends a normal
typed `return 0` at the function closing brace. This rule applies only to entry.
Ordinary statements, loops and nested control blocks can precede fallthrough.

## 7. Explicit main return semantics

Explicit `return 0;`, `return 7;` and other valid int results are unchanged.
No implicit return is added after unconditional returns or definitely returning
if/else and exhaustive match bodies. Existing unreachable-statement E0208 stays.

## 8. Conditional fallthrough

An if branch returning 3 retains that value. Its other path reaches the generated
zero return. Native tests execute both true and false conditions, yielding 3
and 0 respectively. Ordinary ownership/drop handling remains path-sensitive.

## 9. Ordinary-function return regression

Empty int helpers, partially returning int helpers and unused generic int
helpers still fail E0207. Imported empty/partially returning functions named
main also fail E0207 with helper-module source provenance. The existing
`missing_return.ae` fixture now uses an ordinary helper because its previous
main-only case intentionally becomes valid in this milestone.

## 10. No-script-mode evidence

Tests reject top-level calls, calls preceding an explicit main, global value
initialization, omitted return type, duplicate main and a module containing
only an ordinary helper. Comment-only input remains E0101 (empty parser input);
a module with declarations but no main remains E0200. No synthetic entry exists.

## 11. Single-line comment implementation

`skip_trivia` recognizes exact `//` before ordinary token scanning and advances
to CR, LF or EOF. Whole-line, trailing and directly adjacent comments produce no
tokens; the next token uses its real physical source coordinates.

## 12. EOF line comments

No trailing newline is required. Lexer tests cover trailing EOF comments;
normalization tests also locate the closing brace correctly when a line comment
follows it through EOF. Comment-only input lexes to EOF and remains invalid as
an empty program.

## 13. Block comment implementation

The same trivia loop recognizes exact `/*` and scans the original bytes until
the first `*/`. One-line, multiline, Unicode, adjacent and between-token comments
are covered. Braces, operators, quotes and `//` inside the comment are ignored.

## 14. Nesting policy

Non-nesting. The explicit lexer regression
`/* outer /* inner */ tail */` leaves identifier `tail`, star, slash and EOF.
An inner-looking opener has no independent state.

## 15. Unterminated comment diagnostic

E0002, Phase::Lex, DiagnosticCategory::Syntax, message
`unterminated block comment`, with the opening two-byte `/*` span. Tests include
bare opener, ordinary content, Unicode/newlines, trailing star and a nested-looking
opener. Parser EOF never replaces this lexical diagnostic.

## 16. Newline handling

LF and CRLF both remain supported. Block comments retain all physical newlines;
line comments stop before CR/LF and ordinary trivia consumes the terminator.
Existing lone-CR whitespace behavior is unchanged; line counting remains LF-based.

## 17. Span/line/column accounting

No comment-normalized source buffer is created. Token and diagnostic spans retain
original byte offsets and SourceId. SourceFile computes one-based line numbers
and Unicode scalar columns. Tests assert original token slices, nonzero SourceIds,
UTF-8 comment content and exact coordinates after multiline comments.

## 18. Comment/operator disambiguation

Division, multiplication, remainder and existing contiguous operators keep their
scanners. Tests cover `/`, `*`, `<=`, `>=`, `==`, `!=`, `=>` and `&`, plus separated
`< /*...*/ =`, `>/**/=` and `=/**/=`. Separated `!/**/=` remains invalid. No tokens
merge across comments. A slash followed immediately by a comment opener can form
`//`, so automatic test insertion puts whitespace before each comment.

## 19. Comment/string interaction

Strings remain unsupported, covered by the existing `unsupported_string`
manifest rejection. Quotes inside comments are ignored. No string syntax is
added; a future string scanner must consume the complete literal before the
next call to trivia skipping.

## 20. HIR normalization

`analyze_function` adds HirStmtKind::Return with HirExprKind::Int(0), TypeId::INT64,
and the closing brace's actual one-byte span before `synthesize_ownership`.
HirStmt.compiler_generated is provenance only, visible in dumps and copied
during substitution. Regular HIR verification checks the ordinary return value;
the marker grants no exemption. Buffer cleanup appears on its ordinary drop list.

## 21. MIR representation

Unchanged lowering evaluates the return value, emits its drops and produces the
ordinary Return terminator. No comment or implicit-return opcode is introduced.
MIR dumps expose the zero return before backend generation.

## 22. SSA representation

Ordinary MIR-to-SSA construction and verification preserve Return with zero on
the fallthrough path. No generation flag, comment node or special entry opcode
is added to SSA.

## 23. LLVM entry-point behavior

The backend is unchanged. Its `i32 @main()` wrapper calls the internal Aether
int64 entry, truncates to i32 and returns through the platform path. There is no
clamp or forced zero; POSIX exposes its usual exit-status byte. No runtime helper
or backend-only fallthrough epilogue was added.

## 24. Explicit-vs-implicit main comparison

Empty main, main with trailing EOF trivia, conditional fallthrough and a Buffer
owner are compared with explicit final zero returns. Complete LLVM is
byte-identical. MIR and SSA dumps match after removing only physical Span fields.
HIR additionally distinguishes source/generated provenance. Repeated compilations
of implicit cases produce identical complete dumps and LLVM.

## 25. Comment semantic-equivalence checks

Three representative programs cover scalar operators/control flow, generic
Copy-constrained identity and mathematical Vector<double,Row>/Matrix<double>
syntax with Matrix multiplication. Comments containing Unicode, CRLF, source-like
content and line comments are inserted between every token. Tests compare token
kinds/spellings, HIR/MIR/SSA dumps excluding only Span fields, and complete LLVM.
All comparisons pass; comments do not enter any semantic representation.

## 26. Exact tests added

Lexer unit tests:

- `comments_are_whitespace_with_physical_spans`
- `comments_do_not_merge_operators_or_nest`
- `unterminated_block_comment_points_to_opening`
- `diagnostic_after_multiline_comment_has_exact_position`

Driver integration tests in `language_parity.rs`:

- `entry_normalizes_before_ownership_and_backend`
- `terminating_entry_paths_do_not_get_duplicate_returns`
- `ordinary_returns_entry_signatures_and_no_script_mode_remain_strict`
- `imported_main_is_never_given_entry_semantics`
- `comments_preserve_tokens_and_all_semantic_phases`
- `parser_diagnostic_after_closed_comment_has_exact_position`
- `native_main_exit_codes_and_comment_integration`

The required commented empty-main fixture is checked into
`compiler-next/tests/programs/language_parity_1.ae` and included by the native test.

## 27. Diagnostic position tests

For `/*` on line 1, content on lines 2–3, `*/` on line 4 and `@` on line 5,
the lexer asserts exact byte span and rendered `position.ae:5:1` location.
A parser-invalid semicolon after the same comment is asserted at line 5,
column 3. Both are exercised with LF and CRLF. The unterminated regression
renders exactly `open.ae:2:3: error[E0002] (lex): unterminated block comment`.
A Unicode inline comment followed by an invalid character verifies character
column 7 despite a different byte offset.

## 28. Native exit-code executions

| Case | Observed status |
|---|---:|
| Empty main | 0 |
| Explicit zero | 0 |
| Explicit seven | 7 |
| Conditional explicit branch | 3 |
| Conditional fallthrough branch | 0 |
| Arithmetic and loop followed by fallthrough | 0 |
| Nested if blocks followed by fallthrough | 0 |
| Buffer owner followed by fallthrough | 0 |
| Comments around explicit zero return | 0 |
| Required commented empty-main fixture | 0 |
| Root calls imported ordinary main returning seven | 7 |

## 29. Regression result

`cargo test --workspace`: **299 passed, 0 failed**, comprising 7 LLVM backend,
7 new driver integration, 219 existing vertical integration, 44 frontend and
22 middle-end tests. Existing modules, generics, ownership, structs/enums,
refs/views, collections, V21..V33, MATH-ARCH-1 and trap coverage remains green.
`cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings`
and `git diff --check` also pass. Workspace Cargo commands run in compiler-next.

## 30. Differential result

`bash compiler-next/tests/run-differential.sh`: **checked=21, failures=0**.
The established legacy-equivalent and intentional-difference cases retain their
expected statuses. No legacy implementation or differential expectation changed.
The ordinary-function missing-return fixture remains E0207 in manifest testing.

## 31. Documentation changes

README describes admitted syntax and inspection. Charter and semantic contract
state root identity, canonical signature, entry-only fallthrough, explicit
returns, ordinary-function strictness, no script mode, both comments, nesting,
E0002 and physical positions. Architecture records centralized trivia, HIR
normalization before ownership and unchanged MIR/SSA/LLVM authorities.

## 32. Accepted debt

The existing return analysis remains structural and conservative for loops.
Bare standalone block statements and strings remain unadmitted; nested-block
tests use existing if/while grammar. Comments are skipped rather than retained
for formatting tools. SourceFile's existing coordinate calculation is unchanged.
The bootstrap host int64-to-i32/process-status mapping is unchanged. Generated
provenance is an informational HIR field and is intentionally absent downstream.

## 33. OPEN DECISIONS

None blocks this milestone. Future string/trivia tooling, richer return-flow
proofs, alternative entry arguments and a public process ABI require separate
decisions. No nested-comment policy change, script mode or alternate main
signature is implied by this work.

## 34. Recommendation for OOP-ARCH-1

Proceed as a separate architecture milestone defining object identity versus
existing value structs, ownership, construction/destruction, member lookup and
dispatch boundaries before implementation. This parity work provides no classes,
interfaces, inheritance or exceptions and chooses none of their semantics.
