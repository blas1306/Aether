from __future__ import annotations

from . import ast
from .errors import AetherSyntaxError
from .tokens import AETHER_TYPES, PRIMITIVE_TYPES, Token, TokenType
from .types import AetherType, ArrayType, MatrixType


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.current = 0
        self.expression_function_name: str | None = None

    def parse(self) -> ast.Program:
        statements: list[ast.Statement] = []
        while not self._is_at_end():
            statements.append(self._declaration_or_statement())
        return ast.Program(statements)

    def _declaration_or_statement(self) -> ast.Statement:
        if self._match(TokenType.FUNCTION):
            return self._function_declaration()
        if self._looks_like_function_declaration():
            return self._function_declaration()
        if self._looks_like_expression_function_declaration():
            return self._expression_function_declaration()
        return self._statement()

    def _function_declaration(self) -> ast.FunctionDeclaration:
        return_type = self._parse_type_annotation("Expected function return type.")
        name = self._consume(TokenType.IDENTIFIER, "Expected function name.").lexeme
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after function name.")
        parameters: list[ast.Parameter] = []
        if not self._check(TokenType.RIGHT_PAREN):
            while True:
                param_type = self._parse_type_annotation("Expected parameter type.")
                param_name = self._consume(TokenType.IDENTIFIER, "Expected parameter name.").lexeme
                parameters.append(ast.Parameter(param_type, param_name))
                if not self._match(TokenType.COMMA):
                    break
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after parameters.")
        body = self._block()
        return ast.FunctionDeclaration(return_type, name, parameters, body)

    def _expression_function_declaration(self) -> ast.ExpressionFunctionDeclaration:
        name = self._consume(TokenType.IDENTIFIER, "Expected function name.").lexeme
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after function name.")
        parameters: list[ast.ExpressionParameter] = []
        parameter_names: set[str] = set()
        if not self._check(TokenType.RIGHT_PAREN):
            while True:
                if not self._check(TokenType.IDENTIFIER):
                    token = self._peek()
                    if token.type == TokenType.EOF:
                        raise self._error(token, f"Expected parameter name in expression function '{name}'.")
                    raise self._error(token, f"Invalid parameter name '{token.lexeme}' in expression function '{name}'.")
                param_name = self._advance().lexeme
                if param_name in parameter_names:
                    raise self._error(
                        self._previous(),
                        f"Duplicate parameter '{param_name}' in expression function '{name}'.",
                    )
                parameter_names.add(param_name)
                parameters.append(ast.ExpressionParameter(param_name))
                if not self._match(TokenType.COMMA):
                    if not self._check(TokenType.RIGHT_PAREN):
                        raise self._error(
                            self._peek(),
                            f"Expected ',' or ')' in parameter list for expression function '{name}'.",
                        )
                    break
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after parameters.")
        self._consume(TokenType.EQUAL, "Expected '=' before expression function body.")
        if not self._can_start_expression(self._peek()):
            raise self._error(self._peek(), f"Expected expression after '=' in expression function '{name}'.")
        previous_expression_function_name = self.expression_function_name
        self.expression_function_name = name
        try:
            expression = self._expression()
        finally:
            self.expression_function_name = previous_expression_function_name
        self._consume(TokenType.SEMICOLON, "Expected ';' after expression function declaration.")
        return ast.ExpressionFunctionDeclaration(name, parameters, expression)

    def _statement(self) -> ast.Statement:
        if self._match(TokenType.IF):
            condition = self._expression()
            body = self._block()
            else_body = self._block() if self._match(TokenType.ELSE) else None
            return ast.IfStatement(condition, body, else_body)
        if self._match(TokenType.WHILE):
            return ast.WhileStatement(self._expression(), self._block())
        if self._match(TokenType.FOR):
            variable = self._consume(TokenType.IDENTIFIER, "Expected loop variable after 'for'.").lexeme
            self._consume(TokenType.IN, "Expected 'in' after loop variable.")
            iterable = self._expression()
            return ast.ForInStatement(variable, iterable, self._block())
        if self._match(TokenType.RETURN):
            return_token = self._previous()
            expression = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after return value.")
            return ast.ReturnStatement(expression, return_token.line, return_token.column)
        if self._looks_like_var_declaration():
            return self._var_declaration()
        expression = self._expression()
        if self._match(TokenType.EQUAL):
            equals = self._previous()
            value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after assignment.")
            if isinstance(expression, ast.Identifier):
                return ast.Assignment(expression.name, value, equals.line, equals.column)
            if isinstance(expression, ast.IndexExpression):
                return ast.IndexAssignment(expression.array, expression.index, value, equals.line, equals.column)
            raise self._error(self._previous(), "Invalid assignment target.")
        if self._match(TokenType.PLUS_EQUAL):
            plus_equals = self._previous()
            value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after assignment.")
            if isinstance(expression, ast.Identifier):
                return ast.Assignment(
                    expression.name,
                    ast.BinaryExpression(expression, "+", value),
                    plus_equals.line,
                    plus_equals.column,
                )
            raise self._error(self._previous(), "Invalid assignment target.")
        self._consume(TokenType.SEMICOLON, "Expected ';' after expression.")
        return ast.ExpressionStatement(expression)

    def _var_declaration(self) -> ast.VarDeclaration:
        declaration_token = self._peek()
        type_name = self._parse_type_annotation("Expected type name.")
        name = self._consume(TokenType.IDENTIFIER, "Expected variable name.").lexeme
        self._consume(TokenType.EQUAL, "Expected '=' in variable declaration.")
        initializer = self._expression()
        self._consume(TokenType.SEMICOLON, "Expected ';' after variable declaration.")
        return ast.VarDeclaration(type_name, name, initializer, declaration_token.line, declaration_token.column)

    def _block(self) -> list[ast.Statement]:
        self._consume(TokenType.LEFT_BRACE, "Expected '{' before block.")
        statements: list[ast.Statement] = []
        while not self._check(TokenType.RIGHT_BRACE) and not self._is_at_end():
            statements.append(self._declaration_or_statement())
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after block.")
        return statements

    def _expression(self) -> ast.Expression:
        return self._range()

    def _range(self) -> ast.Expression:
        expr = self._logical_or()
        if not self._match(TokenType.COLON):
            return expr
        self._require_expression_after_operator(self._previous())
        second = self._logical_or()
        if self._match(TokenType.COLON):
            self._require_expression_after_operator(self._previous())
            end = self._logical_or()
            return ast.RangeExpression(expr, end, second)
        return ast.RangeExpression(expr, second)

    def _logical_or(self) -> ast.Expression:
        expr = self._logical_and()
        while self._match(TokenType.PIPE_PIPE):
            operator = self._previous().lexeme
            self._require_expression_after_operator(self._previous())
            right = self._logical_and()
            expr = ast.BinaryExpression(expr, operator, right)
        return expr

    def _logical_and(self) -> ast.Expression:
        expr = self._equality()
        while self._match(TokenType.AMP_AMP):
            operator = self._previous().lexeme
            self._require_expression_after_operator(self._previous())
            right = self._equality()
            expr = ast.BinaryExpression(expr, operator, right)
        return expr

    def _equality(self) -> ast.Expression:
        expr = self._comparison()
        while self._match(TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL):
            operator = self._previous().lexeme
            self._require_expression_after_operator(self._previous())
            right = self._comparison()
            expr = ast.BinaryExpression(expr, operator, right)
        return expr

    def _comparison(self) -> ast.Expression:
        expr = self._term()
        while self._match(TokenType.LESS, TokenType.LESS_EQUAL, TokenType.GREATER, TokenType.GREATER_EQUAL):
            operator = self._previous().lexeme
            self._require_expression_after_operator(self._previous())
            right = self._term()
            expr = ast.BinaryExpression(expr, operator, right)
        return expr

    def _term(self) -> ast.Expression:
        expr = self._factor()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            operator = self._previous().lexeme
            self._require_expression_after_operator(self._previous())
            right = self._factor()
            expr = ast.BinaryExpression(expr, operator, right)
        return expr

    def _factor(self) -> ast.Expression:
        expr = self._power()
        while self._match(TokenType.STAR, TokenType.SLASH):
            operator = self._previous().lexeme
            self._require_expression_after_operator(self._previous())
            right = self._power()
            expr = ast.BinaryExpression(expr, operator, right)
        return expr

    def _power(self) -> ast.Expression:
        expr = self._unary()
        if self._match(TokenType.CARET):
            operator = self._previous().lexeme
            self._require_expression_after_operator(self._previous())
            right = self._power()
            expr = ast.BinaryExpression(expr, operator, right)
        return expr

    def _unary(self) -> ast.Expression:
        if self._match(TokenType.MINUS):
            return ast.UnaryExpression(self._previous().lexeme, self._unary())
        return self._postfix()

    def _postfix(self) -> ast.Expression:
        expr = self._primary()
        while self._match(TokenType.LEFT_BRACKET):
            index = self._expression()
            self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after index.")
            expr = ast.IndexExpression(expr, index)
        return expr

    def _primary(self) -> ast.Expression:
        if self._match(TokenType.BOOLEAN_LITERAL):
            return ast.Literal(self._previous().literal, "boolean")
        if self._match(TokenType.INT_LITERAL):
            return ast.Literal(self._previous().literal, "int")
        if self._match(TokenType.FLOAT_LITERAL):
            return ast.Literal(self._previous().literal, "double")
        if self._match(TokenType.STRING_LITERAL):
            return ast.Literal(self._previous().literal, "string")
        if self._match(TokenType.IDENTIFIER, TokenType.TYPE):
            name = self._previous().lexeme
            dotted = False
            while self._match(TokenType.DOT):
                dotted = True
                part = self._consume(TokenType.IDENTIFIER, "Expected identifier after '.'.").lexeme
                name = f"{name}.{part}"
            if self._match(TokenType.LEFT_PAREN):
                arguments: list[ast.Expression] = []
                if not self._check(TokenType.RIGHT_PAREN):
                    while True:
                        arguments.append(self._expression())
                        if not self._match(TokenType.COMMA):
                            break
                self._consume(TokenType.RIGHT_PAREN, "Expected ')' after arguments.")
                return ast.CallExpression(name, arguments)
            if dotted:
                raise self._error(self._previous(), "Dotted names are only supported for builtin calls.")
            if name in AETHER_TYPES:
                raise self._error(self._previous(), f"Type name '{name}' must be used as a call or declaration.")
            return ast.Identifier(name)
        if self._match(TokenType.LEFT_BRACKET):
            return self._matrix_literal()
        if self._match(TokenType.LEFT_PAREN):
            expr = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after expression.")
            return expr
        raise self._error(self._peek(), "Expected expression.")

    def _match(self, *token_types: TokenType) -> bool:
        for token_type in token_types:
            if self._check(token_type):
                self._advance()
                return True
        return False

    def _consume(self, token_type: TokenType, message: str) -> Token:
        if self._check(token_type):
            return self._advance()
        raise self._error(self._peek(), message)

    def _parse_type_annotation(self, message: str) -> AetherType:
        token = self._consume_type(message)
        if token.lexeme in {"Matrix", "Vector"}:
            self._consume(TokenType.LESS, f"Expected '<' after {token.lexeme}.")
            element_token = self._consume(TokenType.TYPE, f"Expected element type inside {token.lexeme}<...>.")
            if element_token.lexeme not in PRIMITIVE_TYPES:
                raise self._error(element_token, f"Expected primitive element type inside {token.lexeme}<...>.")
            self._consume(TokenType.GREATER, f"Expected '>' after {token.lexeme} element type.")
            return MatrixType(element_token.lexeme, vector=token.lexeme == "Vector")
        type_name: AetherType = token.lexeme
        while self._match(TokenType.LEFT_BRACKET):
            self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after '[' in array type.")
            type_name = ArrayType(type_name)
        return type_name

    def _consume_type(self, message: str) -> Token:
        token = self._consume(TokenType.TYPE, message)
        if token.lexeme not in AETHER_TYPES:
            raise self._error(token, f"Unknown type '{token.lexeme}'.")
        return token

    def _looks_like_var_declaration(self) -> bool:
        cursor = self._type_annotation_end_cursor(self.current)
        if cursor is None or cursor + 1 >= len(self.tokens):
            return False
        return self.tokens[cursor].type == TokenType.IDENTIFIER and self.tokens[cursor + 1].type == TokenType.EQUAL

    def _looks_like_function_declaration(self) -> bool:
        cursor = self._type_annotation_end_cursor(self.current)
        if cursor is None or cursor + 2 >= len(self.tokens):
            return False
        if self.tokens[cursor].type != TokenType.IDENTIFIER or self.tokens[cursor + 1].type != TokenType.LEFT_PAREN:
            return False
        cursor += 2
        depth = 1
        while cursor < len(self.tokens):
            token_type = self.tokens[cursor].type
            if token_type == TokenType.LEFT_PAREN:
                depth += 1
            elif token_type == TokenType.RIGHT_PAREN:
                depth -= 1
                if depth == 0:
                    return cursor + 1 < len(self.tokens) and self.tokens[cursor + 1].type == TokenType.LEFT_BRACE
            elif token_type == TokenType.LEFT_BRACE:
                return False
            cursor += 1
        return False

    def _looks_like_expression_function_declaration(self) -> bool:
        if self.current + 2 >= len(self.tokens):
            return False
        if self.tokens[self.current].type != TokenType.IDENTIFIER:
            return False
        if self.tokens[self.current + 1].type != TokenType.LEFT_PAREN:
            return False
        depth = 1
        cursor = self.current + 2
        while cursor < len(self.tokens):
            token_type = self.tokens[cursor].type
            if token_type == TokenType.LEFT_PAREN:
                depth += 1
            elif token_type == TokenType.RIGHT_PAREN:
                depth -= 1
                if depth == 0:
                    return cursor + 1 < len(self.tokens) and self.tokens[cursor + 1].type == TokenType.EQUAL
            elif token_type in {TokenType.SEMICOLON, TokenType.LEFT_BRACE, TokenType.RIGHT_BRACE, TokenType.EOF}:
                return False
            cursor += 1
        return False

    def _require_expression_after_operator(self, operator: Token) -> None:
        if self.expression_function_name is None:
            return
        if self._can_start_expression(self._peek()):
            return
        raise self._error(
            self._peek(),
            f"Expected expression after '{operator.lexeme}' in expression function '{self.expression_function_name}'.",
        )

    def _type_annotation_end_cursor(self, start: int) -> int | None:
        if start >= len(self.tokens) or self.tokens[start].type != TokenType.TYPE:
            return None
        cursor = start + 1
        if self.tokens[start].lexeme in {"Matrix", "Vector"}:
            if (
                cursor + 2 >= len(self.tokens)
                or self.tokens[cursor].type != TokenType.LESS
                or self.tokens[cursor + 1].type != TokenType.TYPE
                or self.tokens[cursor + 1].lexeme not in PRIMITIVE_TYPES
                or self.tokens[cursor + 2].type != TokenType.GREATER
            ):
                return None
            cursor += 3
        while cursor + 1 < len(self.tokens) and self.tokens[cursor].type == TokenType.LEFT_BRACKET:
            if self.tokens[cursor + 1].type != TokenType.RIGHT_BRACKET:
                return None
            cursor += 2
        return cursor

    def _matrix_literal(self) -> ast.MatrixLiteral:
        if self._match(TokenType.RIGHT_BRACKET):
            return ast.MatrixLiteral([])
        rows: list[list[ast.Expression]] = []
        while True:
            row: list[ast.Expression] = []
            if self._check(TokenType.SEMICOLON) or self._check(TokenType.RIGHT_BRACKET):
                raise self._error(self._peek(), "Expected expression in matrix literal.")
            while not self._check(TokenType.SEMICOLON) and not self._check(TokenType.RIGHT_BRACKET):
                row.append(self._expression())
                if self._match(TokenType.COMMA):
                    if self._check(TokenType.SEMICOLON) or self._check(TokenType.RIGHT_BRACKET):
                        raise self._error(self._previous(), "Trailing comma in matrix literal is not supported.")
                    continue
                if self._check(TokenType.SEMICOLON) or self._check(TokenType.RIGHT_BRACKET):
                    break
                if self._can_start_expression(self._peek()):
                    continue
                raise self._error(self._peek(), "Expected column separator, row separator, or ']'.")
            rows.append(row)
            if not self._match(TokenType.SEMICOLON):
                break
            if self._check(TokenType.RIGHT_BRACKET):
                raise self._error(self._previous(), "Trailing ';' in matrix literal is not supported.")
        self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after matrix literal.")
        return ast.MatrixLiteral(rows)

    def _can_start_expression(self, token: Token) -> bool:
        return token.type in {
            TokenType.BOOLEAN_LITERAL,
            TokenType.INT_LITERAL,
            TokenType.FLOAT_LITERAL,
            TokenType.STRING_LITERAL,
            TokenType.IDENTIFIER,
            TokenType.TYPE,
            TokenType.LEFT_BRACKET,
            TokenType.LEFT_PAREN,
            TokenType.MINUS,
        }

    def _check(self, token_type: TokenType) -> bool:
        if self._is_at_end():
            return False
        return self._peek().type == token_type

    def _check_next(self, token_type: TokenType) -> bool:
        if self.current + 1 >= len(self.tokens):
            return False
        return self.tokens[self.current + 1].type == token_type

    def _advance(self) -> Token:
        if not self._is_at_end():
            self.current += 1
        return self._previous()

    def _is_at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]

    def _error(self, token: Token, message: str) -> AetherSyntaxError:
        location = f"line {token.line}, column {token.column}"
        if token.type == TokenType.EOF:
            return AetherSyntaxError(f"{message} at end of file ({location}).")
        return AetherSyntaxError(f"{message} at {location}, near {token.lexeme!r}.")
