from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TokenType(str, Enum):
    EOF = "EOF"
    IDENTIFIER = "IDENTIFIER"
    INT_LITERAL = "INT_LITERAL"
    FLOAT_LITERAL = "FLOAT_LITERAL"
    IMAG_LITERAL = "IMAG_LITERAL"
    STRING_LITERAL = "STRING_LITERAL"
    BOOLEAN_LITERAL = "BOOLEAN_LITERAL"
    NULL_LITERAL = "NULL_LITERAL"
    TYPE = "TYPE"
    FUNCTION = "FUNCTION"
    RETURN = "RETURN"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    FOR = "FOR"
    IN = "IN"
    IMPORT = "IMPORT"
    PACKAGE = "PACKAGE"
    CONST = "CONST"
    ALIAS = "ALIAS"
    STRUCT = "STRUCT"
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
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
    QUESTION = "?"
    LEFT_PAREN = "("
    RIGHT_PAREN = ")"
    LEFT_BRACE = "{"
    RIGHT_BRACE = "}"
    LEFT_BRACKET = "["
    RIGHT_BRACKET = "]"
    COMMA = ","
    SEMICOLON = ";"
    DOT = "."
    APOSTROPHE = "'"


AETHER_TYPES = {"int", "float", "double", "complex", "string", "boolean", "Matrix", "Vector", "void"}
PRIMITIVE_TYPES = {"int", "float", "double", "complex", "string", "boolean"}

KEYWORDS: dict[str, TokenType] = {
    "function": TokenType.FUNCTION,
    "return": TokenType.RETURN,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "in": TokenType.IN,
    "import": TokenType.IMPORT,
    "package": TokenType.PACKAGE,
    "const": TokenType.CONST,
    "alias": TokenType.ALIAS,
    "struct": TokenType.STRUCT,
    "public": TokenType.PUBLIC,
    "private": TokenType.PRIVATE,
    "true": TokenType.BOOLEAN_LITERAL,
    "false": TokenType.BOOLEAN_LITERAL,
    "null": TokenType.NULL_LITERAL,
    **{type_name: TokenType.TYPE for type_name in AETHER_TYPES},
}


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    literal: object | None
    line: int
    column: int
