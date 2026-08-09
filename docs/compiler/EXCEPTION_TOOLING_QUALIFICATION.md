# Exception Tooling Qualification (Hotfix D)

> Classification: **Audit**. Status: **ERQ-005 closed** on 2026-08-02. This is a tooling audit, not a
> language or backend promotion. The stable native capability gate is unchanged.

## Official tooling

The complete supported tooling list is:

- Aether CLI
- Aether LSP
- VS Code extension
- IntelliJ plugin

The formatter and language service are shared implementation layers used by
those tools; they are not additional products.

## Capability matrix

Legend: **Yes** is directly supported, **Delegated** is supplied by the shared
LSP/compiler service, **Partial** names a bounded implementation, **No** is an
explicitly unsupported capability, and **N/A** is not applicable.

| Capability | CLI / formatter | Language service / LSP | VS Code | IntelliJ |
| --- | --- | --- | --- | --- |
| `throw` of an `Error` implementation | Yes in frontend and stable native run/build/check/inspection | Yes: completion, parsing, diagnostics and recovery | Delegated; keyword highlighted | Delegated; keyword highlighted |
| bare rethrow (`throw;`) | Same as `throw`; AST inspection distinguishes it | Yes; completion inserts `throw;`, diagnostics enforce catch context | Delegated; `throw` highlighted | Delegated; `throw` highlighted |
| `try` / `catch` | Yes in frontend, AST run, inspection and formatter | Yes | Delegated; both highlighted | Delegated; both highlighted |
| multiple catches | Yes; source order is preserved and formatted | Yes: parser/type diagnostics and full-document synchronization | Delegated | Delegated |
| typed and root `Error` catches | Yes; `catch (name)` remains accepted root-catch sugar | Yes; completion emits the explicit typed form, while diagnostics/symbols also handle the sugar | Delegated; `Error` highlighted | Delegated; `Error` highlighted |
| `Error` | Ordinary interface use is accepted; exception control remains gated on the stable native route | Yes; completion exposes `Error`, never `Exception` | Highlighted as a type | Highlighted as a keyword/type token |
| `Error.message()` | Yes; compiler owns the nonthrowing semantic rule | Root-catch member completion and hover; semantic diagnostics come only from the compiler | Delegated | Delegated |
| parser recovery | CLI diagnostics stop on ordinary command execution; parser inspection is available | Yes: compiler `parse_with_recovery`, followed by compiler type diagnostics | Delegated | Delegated |
| semantic diagnostics | Compiler authority | Yes: the language service calls the compiler parser/typechecker; no duplicate catch rules | Delegated | Delegated |
| hover | N/A | Partial, document-local; catch binders and root `Error.message()` are covered | Delegated | Delegated |
| completion | N/A | Partial, document-local/regex-assisted; current exception keywords, typed snippets, binders and `Error.message()` are covered | Delegated; no separate snippet catalog | Delegated; no separate completion engine |
| document symbols | N/A | Partial, document-local; catch binders are emitted | Delegated | Delegated; PSI remains a file shell |
| formatting | Shared formatter API; **no CLI `format` command** | Yes through `textDocument/formatting`; exception formatting is idempotent | Delegated | Delegated |
| syntax highlighting | N/A | No semantic-token provider | TextMate: exception keywords and `Error` | Independent lexer: exception keywords and `Error` |
| semantic tokens | N/A | **No** | **No** | **No**; lexical highlighting only |
| go-to-definition | N/A | Partial, document-local; catch binders covered | Delegated | Delegated |
| find references | N/A | Partial, document-local lexical references; catch scope is bounded | Delegated | Delegated |
| rename | N/A | **No; not advertised by the server** | **No** | **No** |
| incremental parsing | N/A | **No**: incremental document notifications are accepted, but each change replaces and reparses the full document | Delegated | Delegated |
| workspace indexing | CLI resolves imports from the source root | **No persistent index**; import diagnostics resolve from the document directory, while navigation/completion remain document-local | **No** beyond the shared LSP | **No** beyond the shared LSP |

## CLI command qualification

The supported command behavior is intentionally asymmetric while the stable
native capability remains disabled:

- `aether run --backend=ast FILE` executes exception syntax and reports handled
  or unhandled events through normal diagnostics.
- native `run`, `build`, `--check`, and `--emit-llvm` consistently reject
  exception control/effect semantics for the promoted native route; there is no
  silent AST fallback.
- inspection flags such as `--tokens` and `--ast` expose the accepted frontend
  syntax. IR/SSA/native inspection remains subject to its existing backend
  capability boundary.
- source formatting is available through the shared formatter and LSP. A CLI
  `format` subcommand does not exist and is not claimed.

## Editor qualification

The VS Code manifest registers `.ae`, the shared language server, the CLI
commands, the TextMate grammar and language configuration. Its extension-owned
tests verify the current exception grammar and the absence of `Exception`.

The IntelliJ metadata registers `.ae`, its lexical highlighter, file-level PSI
parser shell and the shared language server. Its lexer tests cover `try`,
`catch`, `throw`, bare rethrow text and `Error`, and reject `Exception` as an
Aether keyword. Structural PSI parsing and independent semantic completion are
not claimed.

## Qualification conclusion

ERQ-005 is closed because every advertised exception feature now follows the
current `Error`-based surface, and every absent feature is explicitly marked
unsupported. This closure does not promote native exception support and does
not change parser, typechecker, IR, SSA, lifecycle, runtime or backend rules.

## Validation

- Focused formatter, language-service, LSP, CLI, run-file and release-contract
  selection: **219 passed**.
- IntelliJ Gradle suite: **passed**.
- VS Code npm suite: **not runnable in this environment because Node/npm are
  unavailable**; its JSON/TypeScript test sources were audited.
- Full Python suite: **4425 passed, 12 failed, 4 skipped**. All 12 failures are
  the pre-existing `test_import_aliases.py` row/column vector-format mismatch;
  no tooling file in Hotfix D participates in those results.
- Release documentation, capability consistency, diagnostics contract and
  examples-catalog checks: **passed**.
- `compileall` for `src`, `tests` and `scripts`: **passed**.
- `git diff --check`: **passed**.
