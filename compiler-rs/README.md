# Aether compiler Rust workspace

This workspace is the isolated home for native Aether compiler components. It
establishes the project structure and development policy only: the production
compiler remains entirely on its existing Python path.

## Crates

- `aether-ir` owns the language-independent Rust representation of Aether IR.
  It contains no verifier, parser, serializer, DTO, or compiler integration.
- `aether-verifier` verifies declaration and instruction-local type consistency
  in owned Aether IR. CFG, dominance, ownership/lifecycle, and optimization
  verification remain separate later passes.
- `aether-python` will provide the eventual Python integration boundary. It does
  not contain PyO3 bindings or compiler integration yet.

The dependency direction will be from integration crates toward core compiler
crates. The core IR crate must not depend on Python.

## Development

The workspace pins its Rust toolchain and keeps shared edition, minimum Rust
version, lint, formatting, and build-profile settings in the workspace root.
Run workspace commands from this directory:

```console
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features
cargo check --workspace
cargo test --workspace
```
