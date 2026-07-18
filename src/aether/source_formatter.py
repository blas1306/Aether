from __future__ import annotations

from .lexer import lex
from .tokens import Token, TokenType


_CONTROL_KEYWORDS = {TokenType.IF, TokenType.WHILE, TokenType.FOR}
_EXPRESSION_CONTINUATIONS = {
    TokenType.PLUS, TokenType.MINUS, TokenType.DOT_PLUS, TokenType.DOT_MINUS,
    TokenType.STAR, TokenType.DOT_STAR, TokenType.SLASH, TokenType.BACKSLASH,
    TokenType.PERCENT, TokenType.CARET, TokenType.COLON, TokenType.EQUAL_EQUAL,
    TokenType.BANG_EQUAL, TokenType.AMP_AMP, TokenType.PIPE_PIPE, TokenType.LESS,
    TokenType.LESS_EQUAL, TokenType.GREATER, TokenType.GREATER_EQUAL,
}
_BRACED_EXPRESSION_PREDECESSORS = {
    TokenType.IN, TokenType.LEFT_PAREN, TokenType.LEFT_BRACKET, TokenType.COMMA,
    TokenType.EQUAL, *_EXPRESSION_CONTINUATIONS,
}


def format_source(source: str) -> str:
    """Canonicalize supported headers while preserving all other source text."""
    migrated = migrate_control_flow_headers(source)[0]
    return format_abbreviated_function_bodies(migrated)


def format_abbreviated_function_bodies(source: str) -> str:
    """Canonicalize spacing around ``=`` in single-expression functions."""
    tokens = lex(source)
    line_offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []
    for index, token in enumerate(tokens[1:-1], start=1):
        if token.type != TokenType.EQUAL:
            continue
        if tokens[index - 1].type != TokenType.RIGHT_PAREN:
            continue
        if not _closes_function_parameter_list(tokens, index - 1):
            continue
        _replace_whitespace(
            source,
            replacements,
            _token_end(tokens[index - 1], line_offsets),
            _offset(token, line_offsets),
            " ",
        )
        _replace_whitespace(
            source,
            replacements,
            _token_end(token, line_offsets),
            _offset(tokens[index + 1], line_offsets),
            " ",
        )
    for start, end, replacement in sorted(set(replacements), reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def _closes_function_parameter_list(tokens: list[Token], close_index: int) -> bool:
    depth = 1
    cursor = close_index - 1
    while cursor >= 0:
        token_type = tokens[cursor].type
        if token_type == TokenType.RIGHT_PAREN:
            depth += 1
        elif token_type == TokenType.LEFT_PAREN:
            depth -= 1
            if depth == 0:
                return cursor > 0 and tokens[cursor - 1].type == TokenType.IDENTIFIER
        elif token_type in {TokenType.SEMICOLON, TokenType.LEFT_BRACE, TokenType.RIGHT_BRACE} and depth == 1:
            return False
        cursor -= 1
    return False


def migrate_control_flow_headers(source: str) -> tuple[str, int]:
    """Return rc.2-compatible source and the number of legacy headers migrated."""
    tokens = lex(source)
    line_offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []
    migrated = 0

    for index, token in enumerate(tokens[:-1]):
        if token.type == TokenType.ELSE:
            if index > 0:
                _replace_whitespace(
                    source,
                    replacements,
                    _token_end(tokens[index - 1], line_offsets),
                    _offset(token, line_offsets),
                    " ",
                )
            _replace_whitespace(
                source,
                replacements,
                _token_end(token, line_offsets),
                _offset(tokens[index + 1], line_offsets),
                " ",
            )
            continue
        if token.type not in _CONTROL_KEYWORDS:
            continue
        close_index = _parenthesized_header_close(tokens, index + 1)
        if close_index is not None:
            block_index = close_index + 1
            _replace_whitespace(
                source,
                replacements,
                _token_end(token, line_offsets),
                _offset(tokens[index + 1], line_offsets),
                " ",
            )
            if close_index > index + 2:
                _replace_whitespace(
                    source,
                    replacements,
                    _token_end(tokens[index + 1], line_offsets),
                    _offset(tokens[index + 2], line_offsets),
                    "",
                )
                _replace_whitespace(
                    source,
                    replacements,
                    _token_end(tokens[close_index - 1], line_offsets),
                    _offset(tokens[close_index], line_offsets),
                    "",
                )
            _replace_whitespace(
                source,
                replacements,
                _token_end(tokens[close_index], line_offsets),
                _offset(tokens[block_index], line_offsets),
                " ",
            )
            continue
        if (
            tokens[index + 1].type == TokenType.LEFT_PAREN
            and not _grouped_prefix_has_expression_continuation(tokens, index + 1)
        ):
            # A parenthesized prefix followed by a statement rather than an
            # expression continuation is not an rc.1 Aether header.  This
            # also prevents embedded C/Python strings from being rewritten.
            continue

        block_index = _header_block_index(tokens, index + 1)
        if block_index is None:
            continue
        keyword_end = _token_end(token, line_offsets)
        expression_start = _offset(tokens[index + 1], line_offsets)
        block_start = _offset(tokens[block_index], line_offsets)
        expression_end = block_start
        while expression_end > expression_start and source[expression_end - 1].isspace():
            expression_end -= 1
        _replace_whitespace(source, replacements, keyword_end, expression_start, " (")
        _replace_whitespace(source, replacements, expression_end, block_start, ") ")
        migrated += 1

    for start, end, replacement in sorted(set(replacements), reverse=True):
        source = source[:start] + replacement + source[end:]
    return source, migrated


def _replace_whitespace(
    source: str,
    replacements: list[tuple[int, int, str]],
    start: int,
    end: int,
    replacement: str,
) -> None:
    if source[start:end].strip():
        return
    if source[start:end] != replacement:
        replacements.append((start, end, replacement))


def _parenthesized_header_close(tokens: list[Token], start: int) -> int | None:
    if tokens[start].type != TokenType.LEFT_PAREN:
        return None
    depth = 0
    for index in range(start, len(tokens)):
        token_type = tokens[index].type
        if token_type == TokenType.LEFT_PAREN:
            depth += 1
        elif token_type == TokenType.RIGHT_PAREN:
            depth -= 1
            if depth == 0:
                return index if index + 1 < len(tokens) and tokens[index + 1].type == TokenType.LEFT_BRACE else None
        elif token_type == TokenType.EOF:
            return None
    return None


def _grouped_prefix_has_expression_continuation(tokens: list[Token], start: int) -> bool:
    depth = 0
    for index in range(start, len(tokens)):
        token_type = tokens[index].type
        if token_type == TokenType.LEFT_PAREN:
            depth += 1
        elif token_type == TokenType.RIGHT_PAREN:
            depth -= 1
            if depth == 0:
                return (
                    index + 1 < len(tokens)
                    and tokens[index + 1].type in _EXPRESSION_CONTINUATIONS
                )
        elif token_type == TokenType.EOF:
            return False
    return False


def _header_block_index(tokens: list[Token], start: int) -> int | None:
    parens = brackets = braces = 0
    previous_type: TokenType | None = None
    for index in range(start, len(tokens)):
        token_type = tokens[index].type
        if token_type == TokenType.EOF:
            return None
        if token_type == TokenType.LEFT_PAREN:
            parens += 1
        elif token_type == TokenType.RIGHT_PAREN:
            parens -= 1
        elif token_type == TokenType.LEFT_BRACKET:
            brackets += 1
        elif token_type == TokenType.RIGHT_BRACKET:
            brackets -= 1
        elif token_type == TokenType.LEFT_BRACE and parens == 0 and brackets == 0:
            if braces > 0:
                braces += 1
            elif previous_type in _BRACED_EXPRESSION_PREDECESSORS:
                braces = 1
            else:
                return index
        elif token_type == TokenType.RIGHT_BRACE and braces > 0:
            braces -= 1
        previous_type = token_type
    return None


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    offsets.extend(index + 1 for index, char in enumerate(source) if char == "\n")
    return offsets


def _offset(token: Token, line_offsets: list[int]) -> int:
    return line_offsets[token.line - 1] + token.column - 1


def _token_end(token: Token, line_offsets: list[int]) -> int:
    return _offset(token, line_offsets) + len(token.lexeme)
