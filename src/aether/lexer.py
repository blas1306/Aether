from __future__ import annotations

from .errors import AetherSyntaxError
from .tokens import KEYWORDS, Token, TokenType


class Lexer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens: list[Token] = []
        self.start = 0
        self.current = 0
        self.line = 1
        self.column = 1
        self.start_line = 1
        self.start_column = 1

    def scan_tokens(self) -> list[Token]:
        while not self._is_at_end():
            self.start = self.current
            self.start_line = self.line
            self.start_column = self.column
            self._scan_token()
        self.tokens.append(Token(TokenType.EOF, "", None, self.line, self.column))
        return self.tokens

    def _scan_token(self) -> None:
        char = self._advance()
        if char in " \r\t":
            return
        if char == "\n":
            self.line += 1
            self.column = 1
            return
        if char == "#":
            self._skip_line_comment()
            return
        if char == "/" and self._match("/"):
            self._skip_line_comment()
            return

        single_char_tokens = {
            "(": TokenType.LEFT_PAREN,
            ")": TokenType.RIGHT_PAREN,
            "{": TokenType.LEFT_BRACE,
            "}": TokenType.RIGHT_BRACE,
            "[": TokenType.LEFT_BRACKET,
            "]": TokenType.RIGHT_BRACKET,
            ",": TokenType.COMMA,
            ";": TokenType.SEMICOLON,
            ":": TokenType.COLON,
            "-": TokenType.MINUS,
            "*": TokenType.STAR,
            "/": TokenType.SLASH,
            "\\": TokenType.BACKSLASH,
            "%": TokenType.PERCENT,
            "^": TokenType.CARET,
            "'": TokenType.APOSTROPHE,
            "?": TokenType.QUESTION,
        }
        if char == "+":
            self._add_token(TokenType.PLUS_EQUAL if self._match("=") else TokenType.PLUS)
            return
        if char == ".":
            if self._match("+"):
                self._add_token(TokenType.DOT_PLUS)
                return
            if self._match("-"):
                self._add_token(TokenType.DOT_MINUS)
                return
            if self._match("*"):
                self._add_token(TokenType.DOT_STAR)
                return
            self._add_token(TokenType.DOT)
            return
        if char in single_char_tokens:
            self._add_token(single_char_tokens[char])
            return
        if char == "=":
            self._add_token(TokenType.EQUAL_EQUAL if self._match("=") else TokenType.EQUAL)
            return
        if char == "!":
            if self._match("="):
                self._add_token(TokenType.BANG_EQUAL)
                return
            raise self._syntax_error("Unexpected character '!'. Did you mean '!='?")
        if char == "&":
            if self._match("&"):
                self._add_token(TokenType.AMP_AMP)
                return
            raise self._syntax_error("Unexpected character '&'. Did you mean '&&'?")
        if char == "|":
            if self._match("|"):
                self._add_token(TokenType.PIPE_PIPE)
                return
            raise self._syntax_error("Unexpected character '|'. Did you mean '||'?")
        if char == "<":
            self._add_token(TokenType.LESS_EQUAL if self._match("=") else TokenType.LESS)
            return
        if char == ">":
            self._add_token(TokenType.GREATER_EQUAL if self._match("=") else TokenType.GREATER)
            return
        if char == '"':
            self._string()
            return
        if char.isdigit():
            self._number()
            return
        if char.isalpha() or char == "_":
            self._identifier()
            return
        raise self._syntax_error(f"Unexpected character {char!r}.")

    def _identifier(self) -> None:
        while self._peek().isalnum() or self._peek() == "_":
            self._advance()
        if self._peek() == "!" and self._peek_next() != "=":
            self._advance()
        text = self.source[self.start : self.current]
        token_type = KEYWORDS.get(text, TokenType.IDENTIFIER)
        literal: object | None = None
        if token_type == TokenType.BOOLEAN_LITERAL:
            literal = text == "true"
        if text == "im":
            token_type = TokenType.IMAG_LITERAL
            literal = 1j
        self._add_token(token_type, literal)

    def _number(self) -> None:
        while self._peek().isdigit():
            self._advance()
        is_float = False
        if self._peek() == "." and self._peek_next().isdigit():
            is_float = True
            self._advance()
            while self._peek().isdigit():
                self._advance()
        if self._peek() in {"e", "E"} and self._can_start_exponent():
            is_float = True
            self._advance()
            if self._peek() in {"+", "-"}:
                self._advance()
            while self._peek().isdigit():
                self._advance()
        text = self.source[self.start : self.current]
        if self._peek() == "i" and self._peek_next() == "m" and not self._peek_after_next().isalnum() and self._peek_after_next() != "_":
            self._advance()
            self._advance()
            text = self.source[self.start : self.current - 2]
            value = float(text) if is_float else int(text)
            self._add_token(TokenType.IMAG_LITERAL, complex(0.0, value))
            return
        if is_float:
            self._add_token(TokenType.FLOAT_LITERAL, float(text))
        else:
            self._add_token(TokenType.INT_LITERAL, int(text))

    def _string(self) -> None:
        chars: list[str] = []
        while not self._is_at_end():
            char = self._advance()
            if char == '"':
                text = self.source[self.start : self.current]
                self.tokens.append(Token(TokenType.STRING_LITERAL, text, "".join(chars), self.start_line, self.start_column))
                return
            if char == "\n":
                self.line += 1
                self.column = 1
                chars.append("\n")
                continue
            if char == "\\":
                chars.append(self._escape_sequence())
                continue
            chars.append(char)
        raise self._syntax_error("Unterminated string literal.")

    def _escape_sequence(self) -> str:
        if self._is_at_end():
            raise self._syntax_error("Unterminated escape sequence.")
        char = self._advance()
        escapes = {'"': '"', "\\": "\\", "$": "$", "n": "\n", "t": "\t", "r": "\r"}
        if char not in escapes:
            raise self._syntax_error(f"Unsupported escape sequence '\\{char}'.")
        return escapes[char]

    def _skip_line_comment(self) -> None:
        while self._peek() != "\n" and not self._is_at_end():
            self._advance()

    def _match(self, expected: str) -> bool:
        if self._is_at_end() or self.source[self.current] != expected:
            return False
        self._advance()
        return True

    def _peek(self) -> str:
        if self._is_at_end():
            return "\0"
        return self.source[self.current]

    def _peek_next(self) -> str:
        if self.current + 1 >= len(self.source):
            return "\0"
        return self.source[self.current + 1]

    def _peek_after_next(self) -> str:
        if self.current + 2 >= len(self.source):
            return "\0"
        return self.source[self.current + 2]

    def _can_start_exponent(self) -> bool:
        next_char = self._peek_next()
        if next_char.isdigit():
            return True
        if next_char in {"+", "-"}:
            return self._peek_after_next().isdigit()
        return False

    def _advance(self) -> str:
        char = self.source[self.current]
        self.current += 1
        self.column += 1
        return char

    def _add_token(self, token_type: TokenType, literal: object | None = None) -> None:
        text = self.source[self.start : self.current]
        self.tokens.append(Token(token_type, text, literal, self.start_line, self.start_column))

    def _is_at_end(self) -> bool:
        return self.current >= len(self.source)

    def _syntax_error(self, message: str) -> AetherSyntaxError:
        return AetherSyntaxError(message, line=self.start_line, column=self.start_column)


def lex(source: str) -> list[Token]:
    return Lexer(source).scan_tokens()
