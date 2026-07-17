# Migrating control flow from rc.1 to rc.2

Aether 1.0.0-rc.2 requires parentheses around if, while, and for headers.
Source written for rc.1 must be migrated.

The accepted forms are:

```aether
if (condition) {
} else if (otherCondition) {
} else {
}

while (condition) {
}

for (int item in values) {
}

for (item in values) {
}
```

The old forms are rejected rather than accepted as a compatibility grammar.
Missing opening parentheses report `Expected '(' after '<keyword>'.` plus an
Aether 1.0 migration hint; missing closing parentheses report the construct-
specific `Expected ')' after ...` diagnostic.

Repository and downstream sources can use the token-aware migrator:

```bash
python scripts/migrate_control_flow_rc2.py path/to/source-or-directory
python scripts/migrate_control_flow_rc2.py --check path/to/source-or-directory
```

The migrator ignores strings and comments and is idempotent. Editors consuming
the Aether LSP receive canonical snippets and document formatting for this
syntax. The future VS Code extension must consume that same LSP contract; no
separate VS Code grammar is introduced by rc.2.
