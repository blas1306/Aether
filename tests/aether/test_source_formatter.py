from __future__ import annotations

from aether.source_formatter import format_source, migrate_control_flow_headers


def test_formatter_canonicalizes_control_flow_and_else_if() -> None:
    source = """
if( true ){
}else if ( false ) {
} else {
}
while( value < 3 ){
}
for( int i in values ){
}
"""

    assert format_source(source) == """
if (true) {
} else if (false) {
} else {
}
while (value < 3) {
}
for (int i in values) {
}
"""


def test_formatter_is_idempotent() -> None:
    source = "if ((a && b) || c) {\n} else if (d) {\n}\n"
    formatted = format_source(source)
    assert format_source(formatted) == formatted


def test_token_aware_migrator_preserves_comments_and_strings() -> None:
    source = 'println("if old { }");\n# while old { }\nif ready {\n}\n'
    migrated, count = migrate_control_flow_headers(source)
    assert count == 1
    assert migrated == 'println("if old { }");\n# while old { }\nif (ready) {\n}\n'


def test_token_aware_migrator_does_not_rewrite_c_control_statements() -> None:
    source = 'if (ready) return 1;\nif (other) { return 2; }\n'
    migrated, count = migrate_control_flow_headers(source)
    assert count == 0
    assert migrated == source
