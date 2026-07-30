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
    TRY = "TRY"
    CATCH = "CATCH"
    THROW = "THROW"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    FOR = "FOR"
    IN = "IN"
    IMPORT = "IMPORT"
    FROM = "FROM"
    AS = "AS"
    PACKAGE = "PACKAGE"
    CONST = "CONST"
    ALIAS = "ALIAS"
    STRUCT = "STRUCT"
    CLASS = "CLASS"
    CONSTRUCTOR = "CONSTRUCTOR"
    STATIC = "STATIC"
    INTERFACE = "INTERFACE"
    IMPLEMENTS = "IMPLEMENTS"
    ENUM = "ENUM"
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
    BANG = "!"
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


AETHER_TYPES = {
    "int",
    "float",
    "double",
    "complex",
    "string",
    "boolean",
    "Array",
    "List",
    "Matrix",
    "Vector",
    "Error",
    "Exception",
    "void",
    "ParseStatus",
    "IntParseResult",
    "DoubleParseResult",
    "FileStatus",
    "FileReadResult",
}
PRIMITIVE_TYPES = {"int", "float", "double", "complex", "string", "boolean"}

KEYWORDS: dict[str, TokenType] = {
    "function": TokenType.FUNCTION,
    "return": TokenType.RETURN,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "try": TokenType.TRY,
    "catch": TokenType.CATCH,
    "throw": TokenType.THROW,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "in": TokenType.IN,
    "import": TokenType.IMPORT,
    "from": TokenType.FROM,
    "as": TokenType.AS,
    "package": TokenType.PACKAGE,
    "const": TokenType.CONST,
    "alias": TokenType.ALIAS,
    "struct": TokenType.STRUCT,
    "class": TokenType.CLASS,
    "constructor": TokenType.CONSTRUCTOR,
    "static": TokenType.STATIC,
    "interface": TokenType.INTERFACE,
    "implements": TokenType.IMPLEMENTS,
    "enum": TokenType.ENUM,
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
