from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TokenType(str, Enum):
    EOF = "EOF"
    IDENTIFIER = "IDENTIFIER"
    INT_LITERAL = "INT_LITERAL"
    FLOAT_LITERAL = "FLOAT_LITERAL"
    STRING_LITERAL = "STRING_LITERAL"
    BOOLEAN_LITERAL = "BOOLEAN_LITERAL"
    TYPE = "TYPE"
    FUNCTION = "FUNCTION"
    RETURN = "RETURN"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    FOR = "FOR"
    IN = "IN"
    IMPORT = "IMPORT"
    PLUS = "+"
    PLUS_EQUAL = "+="
    MINUS = "-"
    DOT_PLUS = ".+"
    DOT_MINUS = ".-"
    STAR = "*"
    DOT_STAR = ".*"
    SLASH = "/"
    BACKSLASH = "\\"
    PERCENT = "%"
    CARET = "^"
    COLON = ":"
    EQUAL = "="
    EQUAL_EQUAL = "=="
    BANG_EQUAL = "!="
    AMP_AMP = "&&"
    PIPE_PIPE = "||"
    LESS = "<"
    LESS_EQUAL = "<="
    GREATER = ">"
    GREATER_EQUAL = ">="
    LEFT_PAREN = "("
    RIGHT_PAREN = ")"
    LEFT_BRACE = "{"
    RIGHT_BRACE = "}"
    LEFT_BRACKET = "["
    RIGHT_BRACKET = "]"
    COMMA = ","
    SEMICOLON = ";"
    DOT = "."


AETHER_TYPES = {"int", "float", "double", "string", "boolean", "Matrix", "Vector"}
PRIMITIVE_TYPES = {"int", "float", "double", "string", "boolean"}

KEYWORDS: dict[str, TokenType] = {
    "function": TokenType.FUNCTION,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "in": TokenType.IN,
    "import": TokenType.IMPORT,
    "true": TokenType.BOOLEAN_LITERAL,
    "false": TokenType.BOOLEAN_LITERAL,
    **{type_name: TokenType.TYPE for type_name in AETHER_TYPES},
}


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    literal: object | None
    line: int
    column: int
