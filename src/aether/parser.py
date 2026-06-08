from __future__ import annotations

from . import ast
from .errors import AetherSyntaxError
from .lexer import lex
from .tokens import AETHER_TYPES, PRIMITIVE_TYPES, Token, TokenType
from .types import AetherType, ArrayType, ListType, MatrixType, NULL_TYPE, NullableType, TupleType, VectorType


STRING_ESCAPES = {'"': '"', "\\": "\\", "$": "$", "n": "\n", "t": "\t", "r": "\r"}


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.current = 0
        self.expression_function_name: str | None = None
        self.matrix_literal_depth = 0
        self.block_depth = 0
        self.type_aliases: set[str] = set()

    def parse(self) -> ast.Program:
        statements: list[ast.Statement] = []
        package_name: str | None = None
        while not self._is_at_end():
            package_name = self._parse_top_level_item(statements, package_name)
        return ast.Program(statements, package_name)

    def parse_with_recovery(self) -> tuple[ast.Program, list[AetherSyntaxError]]:
        statements: list[ast.Statement] = []
        errors: list[AetherSyntaxError] = []
        package_name: str | None = None
        while not self._is_at_end():
            try:
                package_name = self._parse_top_level_item(statements, package_name)
            except AetherSyntaxError as exc:
                errors.append(exc)
                self._synchronize()
        return ast.Program(statements, package_name), errors

    def parse_expression(self) -> ast.Expression:
        expression = self._expression()
        if not self._is_at_end():
            raise self._error(self._peek(), "Expected end of expression.")
        return expression

    def _parse_top_level_item(self, statements: list[ast.Statement], package_name: str | None) -> str | None:
        if self._match(TokenType.PACKAGE):
            package_token = self._previous()
            if package_name is not None:
                raise self._error(package_token, "Duplicate package declaration.")
            if statements:
                raise self._error(package_token, "Package declaration must appear before other declarations.")
            return self._package_declaration()
        statements.append(self._declaration_or_statement())
        return package_name

    def _declaration_or_statement(self) -> ast.Statement:
        if self._check(TokenType.PACKAGE):
            raise self._error(self._peek(), "Package declaration must appear before other declarations.")
        visibility = self._visibility_modifier()
        if visibility is not None:
            if self.block_depth > 0:
                raise self._error(self._previous(), "Visibility modifiers are only supported on top-level declarations.")
            if self._match(TokenType.FUNCTION):
                return self._function_declaration(visibility)
            if self._match(TokenType.CONST):
                return self._var_declaration(is_const=True, visibility=visibility)
            if self._match(TokenType.ALIAS):
                return self._alias_declaration(visibility)
            if self._match(TokenType.STRUCT):
                return self._struct_declaration(visibility)
            if self._match(TokenType.ENUM):
                return self._enum_declaration(visibility)
            if self._looks_like_function_declaration():
                return self._function_declaration(visibility)
            if self._looks_like_expression_function_declaration():
                return self._expression_function_declaration(visibility)
            if self._looks_like_var_declaration():
                return self._var_declaration(visibility=visibility)
            raise self._error(self._peek(), "Expected declaration after visibility modifier.")
        if self._match(TokenType.ALIAS):
            return self._alias_declaration()
        if self._match(TokenType.STRUCT):
            if self.block_depth > 0:
                raise self._error(self._previous(), "Struct declarations are only supported at top level.")
            return self._struct_declaration()
        if self._match(TokenType.ENUM):
            if self.block_depth > 0:
                raise self._error(self._previous(), "Enum declarations are only supported at top level.")
            return self._enum_declaration()
        if self._match(TokenType.FUNCTION):
            return self._function_declaration()
        if self._looks_like_function_declaration():
            return self._function_declaration()
        if self._looks_like_expression_function_declaration():
            return self._expression_function_declaration()
        return self._statement()

    def _visibility_modifier(self) -> ast.Visibility:
        if not self._match(TokenType.PUBLIC, TokenType.PRIVATE):
            return None
        visibility = self._previous().lexeme
        if self._check(TokenType.PUBLIC) or self._check(TokenType.PRIVATE):
            raise self._error(self._peek(), "Cannot combine or repeat visibility modifiers.")
        return visibility

    def _function_declaration(self, visibility: ast.Visibility = None) -> ast.FunctionDeclaration:
        return_type = self._parse_return_type_annotation("Expected function return type.")
        name_token = self._consume(TokenType.IDENTIFIER, "Expected function name.")
        name = name_token.lexeme
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
        return ast.FunctionDeclaration(
            return_type,
            name,
            parameters,
            body,
            visibility,
            name_token.line,
            name_token.column,
        )

    def _expression_function_declaration(self, visibility: ast.Visibility = None) -> ast.ExpressionFunctionDeclaration:
        name_token = self._consume(TokenType.IDENTIFIER, "Expected function name.")
        name = name_token.lexeme
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
        return ast.ExpressionFunctionDeclaration(
            name,
            parameters,
            expression,
            visibility,
            name_token.line,
            name_token.column,
        )

    def _alias_declaration(self, visibility: ast.Visibility = None) -> ast.AliasDeclaration:
        alias_token = self._consume(TokenType.IDENTIFIER, "Expected alias name.")
        self._consume(TokenType.EQUAL, "Expected '=' in alias declaration.")
        target_type = self._parse_type_annotation("Expected type name in alias declaration.", allow_unknown_identifier=True)
        self._consume(TokenType.SEMICOLON, "Expected ';' after alias declaration.")
        self.type_aliases.add(alias_token.lexeme)
        return ast.AliasDeclaration(alias_token.lexeme, target_type, alias_token.line, alias_token.column, visibility)

    def _struct_declaration(self, visibility: ast.Visibility = None) -> ast.StructDeclaration:
        if self.block_depth > 0:
            raise self._error(self._previous(), "Struct declarations are only supported at top level.")
        name_token = self._consume(TokenType.IDENTIFIER, "Expected struct name.")
        self._consume(TokenType.LEFT_BRACE, "Expected '{' before struct fields.")
        fields: list[ast.StructField] = []
        field_names: set[str] = set()
        while not self._check(TokenType.RIGHT_BRACE) and not self._is_at_end():
            if self._check(TokenType.CONST):
                raise self._error(self._peek(), "Struct fields cannot be const yet.")
            if self._check(TokenType.PUBLIC) or self._check(TokenType.PRIVATE):
                raise self._error(self._peek(), "Struct fields do not support visibility modifiers yet.")
            if self._check(TokenType.FUNCTION) or self._check(TokenType.STRUCT):
                raise self._error(self._peek(), "Methods and nested declarations are not supported inside structs.")
            type_name = self._parse_type_annotation("Expected explicit field type in struct declaration.")
            field_token = self._consume(TokenType.IDENTIFIER, "Expected field name.")
            if self._check(TokenType.LEFT_PAREN):
                raise self._error(field_token, "Methods inside struct are not supported yet.")
            if field_token.lexeme in field_names:
                raise self._error(field_token, f"Duplicate field '{field_token.lexeme}' in struct '{name_token.lexeme}'.")
            field_names.add(field_token.lexeme)
            fields.append(ast.StructField(field_token.lexeme, type_name, field_token.line, field_token.column))
            self._consume(TokenType.SEMICOLON, "Expected ';' after struct field.")
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after struct declaration.")
        return ast.StructDeclaration(name_token.lexeme, fields, name_token.line, name_token.column, visibility)

    def _enum_declaration(self, visibility: ast.Visibility = None) -> ast.EnumDeclaration:
        if self.block_depth > 0:
            raise self._error(self._previous(), "Enum declarations are only supported at top level.")
        name_token = self._consume(TokenType.IDENTIFIER, "Expected enum name.")
        self._consume(TokenType.LEFT_BRACE, "Expected '{' before enum variants.")
        variants: list[ast.EnumVariant] = []
        variant_names: set[str] = set()
        if self._check(TokenType.RIGHT_BRACE):
            raise self._error(self._peek(), f"Enum '{name_token.lexeme}' must declare at least one variant.")
        while not self._check(TokenType.RIGHT_BRACE) and not self._is_at_end():
            if self._check(TokenType.PUBLIC) or self._check(TokenType.PRIVATE):
                raise self._error(self._peek(), "Enum variants do not support visibility modifiers.")
            if self._check(TokenType.FUNCTION) or self._check(TokenType.STRUCT) or self._check(TokenType.ENUM):
                raise self._error(self._peek(), "Methods and nested declarations are not supported inside enums.")
            variant_token = self._consume(TokenType.IDENTIFIER, "Expected enum variant name.")
            if self._check(TokenType.LEFT_PAREN):
                raise self._error(variant_token, "Enum variants cannot have payloads.")
            if variant_token.lexeme in variant_names:
                raise self._error(
                    variant_token,
                    f"Duplicate variant '{variant_token.lexeme}' in enum '{name_token.lexeme}'.",
                )
            variant_names.add(variant_token.lexeme)
            variants.append(ast.EnumVariant(variant_token.lexeme, variant_token.line, variant_token.column))
            if not self._match(TokenType.COMMA):
                break
            if self._check(TokenType.RIGHT_BRACE):
                break
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after enum declaration.")
        return ast.EnumDeclaration(name_token.lexeme, variants, name_token.line, name_token.column, visibility)

    def _package_declaration(self) -> str:
        module_name = self._consume(TokenType.IDENTIFIER, "Expected package name after 'package'.").lexeme
        while self._match(TokenType.DOT):
            module_name += "." + self._consume(TokenType.IDENTIFIER, "Expected identifier after '.'.").lexeme
        self._consume(TokenType.SEMICOLON, "Expected ';' after package declaration.")
        return module_name

    def _statement(self) -> ast.Statement:
        if self._match(TokenType.IF):
            if_token = self._previous()
            condition = self._expression()
            body = self._block()
            else_body = self._block() if self._match(TokenType.ELSE) else None
            return ast.IfStatement(condition, body, else_body, if_token.line, if_token.column)
        if self._match(TokenType.WHILE):
            while_token = self._previous()
            return ast.WhileStatement(self._expression(), self._block(), while_token.line, while_token.column)
        if self._match(TokenType.IMPORT):
            import_token = self._previous()
            module_name = self._consume(TokenType.IDENTIFIER, "Expected module name after 'import'.").lexeme
            while self._match(TokenType.DOT):
                module_name += "." + self._consume(TokenType.IDENTIFIER, "Expected identifier after '.'.").lexeme
            self._consume_optional_import_terminator()
            return ast.ImportStatement(module_name, import_token.line, import_token.column)
        if self._match(TokenType.FOR):
            for_token = self._previous()
            variable = self._consume(TokenType.IDENTIFIER, "Expected loop variable after 'for'.").lexeme
            self._consume(TokenType.IN, "Expected 'in' after loop variable.")
            iterable = self._expression()
            return ast.ForInStatement(variable, iterable, self._block(), for_token.line, for_token.column)
        if self._match(TokenType.RETURN):
            return_token = self._previous()
            expression = None if self._check(TokenType.SEMICOLON) else self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after return statement.")
            return ast.ReturnStatement(expression, return_token.line, return_token.column)
        if self._match(TokenType.BREAK):
            break_token = self._previous()
            self._consume(TokenType.SEMICOLON, "Expected ';' after break statement.")
            return ast.BreakStatement(break_token.line, break_token.column)
        if self._match(TokenType.CONTINUE):
            continue_token = self._previous()
            self._consume(TokenType.SEMICOLON, "Expected ';' after continue statement.")
            return ast.ContinueStatement(continue_token.line, continue_token.column)
        if self._match(TokenType.THROW):
            throw_token = self._previous()
            if not self._can_start_expression(self._peek()):
                raise self._error(self._peek(), "Expected expression after 'throw'.")
            expression = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after throw statement.")
            return ast.ThrowStatement(expression, throw_token.line, throw_token.column)
        if self._match(TokenType.TRY):
            try_token = self._previous()
            try_body = self._block()
            self._consume(TokenType.CATCH, "Expected 'catch' after try block.")
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'catch'.")
            catch_name = self._consume(TokenType.IDENTIFIER, "Expected catch variable name.").lexeme
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after catch variable name.")
            catch_body = self._block()
            return ast.TryCatchStatement(try_body, catch_name, catch_body, try_token.line, try_token.column)
        if self._match(TokenType.CONST):
            return self._var_declaration(is_const=True)
        if self._looks_like_var_declaration():
            return self._var_declaration()
        if self._looks_like_destructuring_assignment():
            return self._destructuring_assignment()
        expression = self._expression()
        if self._match(TokenType.EQUAL):
            equals = self._previous()
            value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after assignment.")
            if isinstance(expression, ast.Identifier):
                return ast.Assignment(expression.name, value, equals.line, equals.column)
            if isinstance(expression, ast.MatrixIndexExpression):
                return ast.MatrixIndexAssignment(
                    expression.matrix,
                    expression.row,
                    expression.column,
                    value,
                    equals.line,
                    equals.column,
                )
            if isinstance(expression, ast.IndexExpression):
                return ast.IndexAssignment(expression.array, expression.index, value, equals.line, equals.column)
            if isinstance(expression, ast.FieldAccess):
                if not self._is_field_assignment_lvalue(expression):
                    raise self._error(
                        equals,
                        "Field assignment target must start from a variable; assigning to fields on temporaries is not supported.",
                    )
                return ast.FieldAssignment(expression.target, expression.field_name, value, equals.line, equals.column)
            raise self._error(self._previous(), "Invalid assignment target.")
        if self._match(TokenType.PLUS_EQUAL):
            plus_equals = self._previous()
            value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after assignment.")
            if isinstance(expression, ast.Identifier):
                return ast.Assignment(
                    expression.name,
                    ast.BinaryExpression(expression, "+", value, plus_equals.line, plus_equals.column),
                    plus_equals.line,
                    plus_equals.column,
                )
            raise self._error(self._previous(), "Invalid assignment target.")
        self._consume(TokenType.SEMICOLON, "Expected ';' after expression.")
        return ast.ExpressionStatement(expression)

    def _destructuring_assignment(self) -> ast.DestructuringAssignment:
        first = self._consume(TokenType.IDENTIFIER, "Expected variable name in destructuring assignment.")
        names = [first.lexeme]
        while self._match(TokenType.COMMA):
            if self._check(TokenType.EQUAL):
                raise self._error(self._peek(), "Single-element destructuring assignment is not supported.")
            names.append(self._consume(TokenType.IDENTIFIER, "Expected variable name after ','.").lexeme)
        equals = self._consume(TokenType.EQUAL, "Expected '=' after destructuring assignment target.")
        value = self._expression()
        self._consume(TokenType.SEMICOLON, "Expected ';' after assignment.")
        return ast.DestructuringAssignment(names, value, equals.line, equals.column)

    def _var_declaration(self, *, is_const: bool = False, visibility: ast.Visibility = None) -> ast.VarDeclaration:
        declaration_token = self._peek()
        type_name: AetherType | None = None
        if not is_const or self._looks_like_var_declaration():
            type_name = self._parse_type_annotation("Expected type name.")
        name = self._consume(TokenType.IDENTIFIER, "Expected variable name.").lexeme
        self._consume(TokenType.EQUAL, "Expected '=' in variable declaration.")
        initializer = self._expression()
        self._consume(TokenType.SEMICOLON, "Expected ';' after variable declaration.")
        return ast.VarDeclaration(type_name, name, initializer, declaration_token.line, declaration_token.column, is_const, visibility)

    def _block(self) -> list[ast.Statement]:
        self._consume(TokenType.LEFT_BRACE, "Expected '{' before block.")
        statements: list[ast.Statement] = []
        self.block_depth += 1
        try:
            while not self._check(TokenType.RIGHT_BRACE) and not self._is_at_end():
                statements.append(self._declaration_or_statement())
            self._consume(TokenType.RIGHT_BRACE, "Expected '}' after block.")
            return statements
        finally:
            self.block_depth -= 1

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
            operator = self._previous()
            self._require_expression_after_operator(operator)
            right = self._logical_and()
            expr = ast.BinaryExpression(expr, operator.lexeme, right, operator.line, operator.column)
        return expr

    def _logical_and(self) -> ast.Expression:
        expr = self._equality()
        while self._match(TokenType.AMP_AMP):
            operator = self._previous()
            self._require_expression_after_operator(operator)
            right = self._equality()
            expr = ast.BinaryExpression(expr, operator.lexeme, right, operator.line, operator.column)
        return expr

    def _equality(self) -> ast.Expression:
        expr = self._comparison()
        while self._match(TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL):
            operator = self._previous()
            self._require_expression_after_operator(operator)
            right = self._comparison()
            expr = ast.BinaryExpression(expr, operator.lexeme, right, operator.line, operator.column)
        return expr

    def _comparison(self) -> ast.Expression:
        expr = self._term()
        while self._match(TokenType.LESS, TokenType.LESS_EQUAL, TokenType.GREATER, TokenType.GREATER_EQUAL):
            operator = self._previous()
            self._require_expression_after_operator(operator)
            right = self._term()
            expr = ast.BinaryExpression(expr, operator.lexeme, right, operator.line, operator.column)
        return expr

    def _term(self) -> ast.Expression:
        expr = self._factor()
        while self._match(TokenType.PLUS, TokenType.MINUS, TokenType.DOT_PLUS, TokenType.DOT_MINUS):
            operator = self._previous()
            if self._is_matrix_signed_column_boundary(operator):
                self.current -= 1
                break
            self._require_expression_after_operator(operator)
            right = self._factor()
            expr = ast.BinaryExpression(expr, operator.lexeme, right, operator.line, operator.column)
        return expr

    def _factor(self) -> ast.Expression:
        expr = self._power()
        while self._match(TokenType.STAR, TokenType.DOT_STAR, TokenType.SLASH, TokenType.BACKSLASH, TokenType.PERCENT):
            operator = self._previous()
            self._require_expression_after_operator(operator)
            right = self._power()
            expr = ast.BinaryExpression(expr, operator.lexeme, right, operator.line, operator.column)
        return expr

    def _power(self) -> ast.Expression:
        expr = self._unary()
        if self._match(TokenType.CARET):
            operator = self._previous()
            self._require_expression_after_operator(operator)
            right = self._power()
            expr = ast.BinaryExpression(expr, operator.lexeme, right, operator.line, operator.column)
        return expr

    def _unary(self) -> ast.Expression:
        if self._match(TokenType.MINUS):
            operator = self._previous()
            return ast.UnaryExpression(operator.lexeme, self._unary(), operator.line, operator.column)
        return self._postfix()

    def _postfix(self) -> ast.Expression:
        expr = self._primary()
        while True:
            if self._match(TokenType.LEFT_BRACKET):
                bracket = self._previous()
                index = self._index_component()
                if self._match(TokenType.COMMA):
                    column = self._index_component()
                    self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after matrix index.")
                    expr = ast.MatrixIndexExpression(expr, index, column, bracket.line, bracket.column)
                    continue
                self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after index.")
                expr = ast.IndexExpression(expr, index, bracket.line, bracket.column)
                continue
            if self._match(TokenType.APOSTROPHE):
                operator = self._previous()
                expr = ast.UnaryExpression(operator.lexeme, expr, operator.line, operator.column)
                continue
            if self._match(TokenType.BANG):
                operator = self._previous()
                expr = ast.UnaryExpression(operator.lexeme, expr, operator.line, operator.column)
                continue
            if self._match(TokenType.DOT):
                field = self._consume(TokenType.IDENTIFIER, "Expected field name after '.'.")
                expr = ast.FieldAccess(expr, field.lexeme, field.line, field.column)
                continue
            if self._match(TokenType.LEFT_PAREN) and isinstance(expr, ast.FieldAccess):
                arguments, keyword_arguments = self._call_arguments()
                expr = ast.MethodCall(
                    expr.target,
                    expr.field_name,
                    arguments,
                    keyword_arguments,
                    expr.line,
                    expr.column,
                )
                continue
            break
        return expr

    def _index_component(self) -> ast.Expression:
        if self._match(TokenType.COLON):
            return ast.FullSlice()
        return self._expression()

    def _primary(self) -> ast.Expression:
        if self._match(TokenType.BOOLEAN_LITERAL):
            return ast.Literal(self._previous().literal, "boolean")
        if self._match(TokenType.NULL_LITERAL):
            return ast.Literal(None, NULL_TYPE)
        if self._match(TokenType.INT_LITERAL):
            return ast.Literal(self._previous().literal, "int")
        if self._match(TokenType.FLOAT_LITERAL):
            return ast.Literal(self._previous().literal, "double")
        if self._match(TokenType.IMAG_LITERAL):
            return ast.Literal(self._previous().literal, "complex")
        if self._match(TokenType.STRING_LITERAL):
            return self._string_literal_expression(self._previous())
        if self._match(TokenType.IDENTIFIER, TokenType.TYPE):
            name_token = self._previous()
            parts = [name_token.lexeme]
            field_tokens: list[Token] = []
            while self._match(TokenType.DOT):
                field_token = self._consume(TokenType.IDENTIFIER, "Expected identifier after '.'.")
                part = field_token.lexeme
                parts.append(part)
                field_tokens.append(field_token)
            name = ".".join(parts)
            if self._match(TokenType.LEFT_PAREN):
                call_token = self._previous()
                arguments, keyword_arguments = self._call_arguments()
                if name == "input":
                    if keyword_arguments:
                        raise self._error(call_token, "input() does not accept keyword arguments.")
                    return ast.InputCall(arguments, call_token.line, call_token.column)
                return ast.CallExpression(name, arguments, keyword_arguments, name_token.line, name_token.column)
            if len(parts) > 1:
                expr: ast.Expression = ast.Identifier(parts[0], name_token.line, name_token.column)
                for part, field_token in zip(parts[1:], field_tokens):
                    expr = ast.FieldAccess(expr, part, field_token.line, field_token.column)
                return expr
            if name in AETHER_TYPES:
                raise self._error(self._previous(), f"Type name '{name}' must be used as a call or declaration.")
            return ast.Identifier(name, name_token.line, name_token.column)
        if self._match(TokenType.LEFT_BRACKET):
            return self._matrix_literal()
        if self._match(TokenType.LEFT_BRACE):
            return self._list_literal()
        if self._match(TokenType.LEFT_PAREN):
            expr = self._expression()
            if self._match(TokenType.COMMA):
                if self._check(TokenType.RIGHT_PAREN):
                    raise self._error(self._peek(), "Single-element tuple literals are not supported.")
                elements = [expr, self._expression()]
                while self._match(TokenType.COMMA):
                    if self._check(TokenType.RIGHT_PAREN):
                        raise self._error(self._peek(), "Trailing comma in tuple literal is not supported.")
                    elements.append(self._expression())
                self._consume(TokenType.RIGHT_PAREN, "Expected ')' after tuple literal.")
                return ast.TupleLiteral(elements)
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after expression.")
            return expr
        raise self._error(self._peek(), "Expected expression.")

    def _call_arguments(self) -> tuple[list[ast.Expression], dict[str, ast.Expression]]:
        arguments: list[ast.Expression] = []
        keyword_arguments: dict[str, ast.Expression] = {}
        saw_keyword_argument = False
        if not self._check(TokenType.RIGHT_PAREN):
            while True:
                if self._check(TokenType.IDENTIFIER) and self._check_next(TokenType.EQUAL):
                    saw_keyword_argument = True
                    keyword_name = self._advance().lexeme
                    if keyword_name in keyword_arguments:
                        raise self._error(self._previous(), f"Duplicate keyword argument '{keyword_name}'.")
                    self._consume(TokenType.EQUAL, "Expected '=' after keyword argument name.")
                    keyword_arguments[keyword_name] = self._expression()
                else:
                    if saw_keyword_argument:
                        raise self._error(self._peek(), "Positional arguments cannot follow keyword arguments.")
                    arguments.append(self._expression())
                if not self._match(TokenType.COMMA):
                    break
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after arguments.")
        return arguments, keyword_arguments

    def _string_literal_expression(self, token: Token) -> ast.Expression:
        if not self._has_interpolation_start(token.lexeme):
            return ast.Literal(token.literal, "string")
        return ast.InterpolatedString(self._parse_interpolated_string_parts(token), token.line, token.column)

    def _has_interpolation_start(self, lexeme: str) -> bool:
        raw = lexeme[1:-1]
        index = 0
        while index < len(raw):
            if raw[index] == "\\":
                index += 2
                continue
            if raw[index] == "$":
                return True
            index += 1
        return False

    def _parse_interpolated_string_parts(self, token: Token) -> list[str | ast.Expression]:
        raw = token.lexeme[1:-1]
        parts: list[str | ast.Expression] = []
        text: list[str] = []
        index = 0
        while index < len(raw):
            char = raw[index]
            if char == "\\":
                text.append(self._decode_string_escape(raw, index, token))
                index += 2
                continue
            if char == "$":
                if text:
                    parts.append("".join(text))
                    text = []
                expression_source, index = self._read_interpolation_expression(raw, index + 1, token)
                expression_source = expression_source.strip()
                if not expression_source:
                    raise self._error(token, "Interpolacion de string vacia.")
                parts.append(self._parse_interpolation_expression(expression_source, token))
                continue
            text.append(char)
            index += 1
        if text:
            parts.append("".join(text))
        return parts

    def _read_interpolation_expression(self, raw: str, start: int, token: Token) -> tuple[str, int]:
        expression: list[str] = []
        index = start
        while index < len(raw):
            char = raw[index]
            if char == "\\":
                expression.append(self._decode_string_escape(raw, index, token))
                index += 2
                continue
            if char == "$":
                return "".join(expression), index + 1
            expression.append(char)
            index += 1
        raise self._error(token, "Interpolacion de string sin cerrar.")

    def _decode_string_escape(self, raw: str, index: int, token: Token) -> str:
        if index + 1 >= len(raw):
            raise self._error(token, "Secuencia de escape sin cerrar en string.")
        escaped = raw[index + 1]
        value = STRING_ESCAPES.get(escaped)
        if value is None:
            raise self._error(token, f"Secuencia de escape no soportada '\\{escaped}'.")
        return value

    def _parse_interpolation_expression(self, source: str, token: Token) -> ast.Expression:
        try:
            return Parser(lex(source)).parse_expression()
        except AetherSyntaxError as exc:
            raise self._error(token, f"Expresion de interpolacion invalida {source!r}: {exc}") from exc

    def _is_field_assignment_lvalue(self, expression: ast.FieldAccess) -> bool:
        target = expression.target
        if isinstance(target, ast.Identifier):
            return True
        if isinstance(target, ast.FieldAccess):
            return self._is_field_assignment_lvalue(target)
        return False

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

    def _consume_optional_import_terminator(self) -> None:
        import_end = self._previous()
        if self._match(TokenType.SEMICOLON):
            return
        if self._is_at_end() or self._peek().line > import_end.line:
            return
        raise self._error(self._peek(), "Expected ';' or newline after import statement.")

    def _synchronize(self) -> None:
        if self._is_at_end():
            return
        error_line = self._peek().line
        self._advance()
        while not self._is_at_end():
            if self._previous().type == TokenType.SEMICOLON:
                return
            if self._peek().type in {
                TokenType.PACKAGE,
                TokenType.IMPORT,
                TokenType.PUBLIC,
                TokenType.PRIVATE,
                TokenType.CONST,
                TokenType.ALIAS,
                TokenType.STRUCT,
                TokenType.ENUM,
                TokenType.FUNCTION,
                TokenType.TYPE,
                TokenType.IF,
                TokenType.WHILE,
                TokenType.FOR,
                TokenType.RETURN,
                TokenType.BREAK,
                TokenType.CONTINUE,
                TokenType.TRY,
                TokenType.CATCH,
                TokenType.THROW,
            } and self._peek().line > error_line:
                return
            self._advance()

    def _parse_return_type_annotation(self, message: str) -> AetherType:
        if self._check(TokenType.TYPE) and self._peek().lexeme == "void":
            token = self._advance()
            if self._check(TokenType.LEFT_BRACKET):
                raise self._error(token, "'void' cannot be used as an array type.")
            if self._check(TokenType.QUESTION):
                raise self._error(self._peek(), "'void' cannot be nullable.")
            return "void"
        return self._parse_type_annotation(message, allow_unknown_identifier=True)

    def _parse_type_annotation(self, message: str, *, allow_unknown_identifier: bool = True) -> AetherType:
        if self._match(TokenType.LEFT_PAREN):
            element_types = [self._parse_tuple_type_element()]
            if not self._match(TokenType.COMMA):
                raise self._error(self._peek(), "Tuple return types require at least two element types.")
            element_types.append(self._parse_tuple_type_element())
            while self._match(TokenType.COMMA):
                element_types.append(self._parse_tuple_type_element())
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after tuple return type.")
            return self._nullable_suffix(TupleType(tuple(element_types)))
        token = self._consume_type(message, allow_unknown_identifier=allow_unknown_identifier)
        if token.lexeme == "void":
            raise self._error(token, "'void' is only valid as a function return type.")
        if token.lexeme in {"Array", "List"}:
            element_type = "double"
            if self._match(TokenType.LESS):
                element_type = self._parse_type_annotation(f"Expected element type inside {token.lexeme}<...>.")
                self._consume(TokenType.GREATER, f"Expected '>' after {token.lexeme} element type.")
            if token.lexeme == "Array":
                return self._nullable_suffix(ArrayType(element_type))
            return self._nullable_suffix(ListType(element_type))
        if token.lexeme in {"Matrix", "Vector"}:
            element_type = "double"
            if self._match(TokenType.LESS):
                element_token = self._consume(TokenType.TYPE, f"Expected element type inside {token.lexeme}<...>.")
                if element_token.lexeme not in PRIMITIVE_TYPES:
                    raise self._error(element_token, f"Expected primitive element type inside {token.lexeme}<...>.")
                self._consume(TokenType.GREATER, f"Expected '>' after {token.lexeme} element type.")
                element_type = element_token.lexeme
            if token.lexeme == "Vector":
                return self._nullable_suffix(VectorType(element_type))
            return self._nullable_suffix(MatrixType(element_type))
        type_name: AetherType = token.lexeme
        if self._check(TokenType.LEFT_BRACKET):
            raise self._error(self._peek(), "Array type syntax 'T[]' is not public; use Array<T>.")
        return self._nullable_suffix(type_name)

    def _nullable_suffix(self, type_name: AetherType) -> AetherType:
        if not self._match(TokenType.QUESTION):
            return type_name
        return NullableType(type_name)

    def _parse_tuple_type_element(self) -> AetherType:
        element_type = self._parse_type_annotation("Expected tuple element type.")
        if self._check(TokenType.IDENTIFIER) and self._check_next_any(TokenType.COMMA, TokenType.RIGHT_PAREN):
            self._advance()
        return element_type

    def _consume_type(self, message: str, *, allow_unknown_identifier: bool = False) -> Token:
        if self._check(TokenType.TYPE) or (
            self._check(TokenType.IDENTIFIER) and (allow_unknown_identifier or self._peek().lexeme in self.type_aliases)
        ):
            token = self._advance()
        else:
            raise self._error(self._peek(), message)
        if token.type == TokenType.TYPE and token.lexeme not in AETHER_TYPES:
            raise self._error(token, f"Unknown type '{token.lexeme}'.")
        return token

    def _looks_like_var_declaration(self) -> bool:
        cursor = self._type_annotation_end_cursor(self.current)
        if cursor is None or cursor + 1 >= len(self.tokens):
            return False
        return self.tokens[cursor].type == TokenType.IDENTIFIER and self.tokens[cursor + 1].type == TokenType.EQUAL

    def _looks_like_destructuring_assignment(self) -> bool:
        if self.current + 3 >= len(self.tokens) or self.tokens[self.current].type != TokenType.IDENTIFIER:
            return False
        cursor = self.current + 1
        saw_comma = False
        while cursor < len(self.tokens) and self.tokens[cursor].type == TokenType.COMMA:
            saw_comma = True
            cursor += 1
            if cursor >= len(self.tokens) or self.tokens[cursor].type != TokenType.IDENTIFIER:
                return False
            cursor += 1
        return saw_comma and cursor < len(self.tokens) and self.tokens[cursor].type == TokenType.EQUAL

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
        if start >= len(self.tokens):
            return None
        if self.tokens[start].type == TokenType.LEFT_PAREN:
            cursor = self._tuple_type_element_end_cursor(start + 1)
            if cursor is None or cursor >= len(self.tokens) or self.tokens[cursor].type != TokenType.COMMA:
                return None
            while cursor < len(self.tokens) and self.tokens[cursor].type == TokenType.COMMA:
                cursor = self._tuple_type_element_end_cursor(cursor + 1)
                if cursor is None:
                    return None
            if cursor >= len(self.tokens) or self.tokens[cursor].type != TokenType.RIGHT_PAREN:
                return None
            cursor += 1
            if cursor < len(self.tokens) and self.tokens[cursor].type == TokenType.QUESTION:
                cursor += 1
            return cursor
        if self.tokens[start].type not in {TokenType.TYPE, TokenType.IDENTIFIER}:
            return None
        cursor = start + 1
        if self.tokens[start].lexeme in {"Array", "List"} and cursor < len(self.tokens) and self.tokens[cursor].type == TokenType.LESS:
            cursor = self._type_annotation_end_cursor(cursor + 1)
            if cursor is None or cursor >= len(self.tokens) or self.tokens[cursor].type != TokenType.GREATER:
                return None
            cursor += 1
        elif self.tokens[start].lexeme in {"Matrix", "Vector"} and cursor < len(self.tokens) and self.tokens[cursor].type == TokenType.LESS:
            if (
                cursor + 2 >= len(self.tokens)
                or self.tokens[cursor + 1].type != TokenType.TYPE
                or self.tokens[cursor + 1].lexeme not in PRIMITIVE_TYPES
                or self.tokens[cursor + 2].type != TokenType.GREATER
            ):
                return None
            cursor += 3
        if cursor < len(self.tokens) and self.tokens[cursor].type == TokenType.QUESTION:
            cursor += 1
        return cursor

    def _is_alias_type_token(self, index: int) -> bool:
        return index < len(self.tokens) and self.tokens[index].type == TokenType.IDENTIFIER and self.tokens[index].lexeme in self.type_aliases

    def _tuple_type_element_end_cursor(self, start: int) -> int | None:
        cursor = self._type_annotation_end_cursor(start)
        if cursor is None:
            return None
        if (
            cursor + 1 < len(self.tokens)
            and self.tokens[cursor].type == TokenType.IDENTIFIER
            and self.tokens[cursor + 1].type in {TokenType.COMMA, TokenType.RIGHT_PAREN}
        ):
            return cursor + 1
        return cursor

    def _matrix_literal(self) -> ast.MatrixLiteral:
        self.matrix_literal_depth += 1
        try:
            if self._match(TokenType.RIGHT_BRACKET):
                return ast.MatrixLiteral([])
            rows: list[list[ast.Expression]] = []
            has_space_columns = False
            uses_commas = False
            while True:
                row: list[ast.Expression] = []
                if self._check(TokenType.SEMICOLON) or self._check(TokenType.RIGHT_BRACKET):
                    raise self._error(self._peek(), "Expected expression in matrix literal.")
                while not self._check(TokenType.SEMICOLON) and not self._check(TokenType.RIGHT_BRACKET):
                    row.append(self._expression())
                    if self._match(TokenType.COMMA):
                        uses_commas = True
                        if self._check(TokenType.SEMICOLON) or self._check(TokenType.RIGHT_BRACKET):
                            raise self._error(self._previous(), "Trailing comma in matrix literal is not supported.")
                        continue
                    if self._check(TokenType.SEMICOLON) or self._check(TokenType.RIGHT_BRACKET):
                        break
                    if self._can_start_expression(self._peek()):
                        has_space_columns = True
                        continue
                    raise self._error(self._peek(), "Expected column separator, row separator, or ']'.")
                rows.append(row)
                if not self._match(TokenType.SEMICOLON):
                    break
                if self._check(TokenType.RIGHT_BRACKET):
                    raise self._error(self._previous(), "Trailing ';' in matrix literal is not supported.")
            self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after matrix literal.")
            orientation = None
            if len(rows) == 1:
                orientation = "row"
            elif all(len(row) == 1 for row in rows):
                orientation = "column"
            return ast.MatrixLiteral(rows, vector=not has_space_columns, orientation=orientation, uses_commas=uses_commas)
        finally:
            self.matrix_literal_depth -= 1

    def _list_literal(self) -> ast.ListLiteral:
        if self._match(TokenType.RIGHT_BRACE):
            return ast.ListLiteral([])
        elements: list[ast.Expression] = []
        while True:
            if self._check(TokenType.RIGHT_BRACE):
                raise self._error(self._peek(), "Expected expression in list literal.")
            elements.append(self._expression())
            if self._match(TokenType.COMMA):
                if self._check(TokenType.RIGHT_BRACE):
                    raise self._error(self._previous(), "Trailing comma in list literal is not supported.")
                continue
            if self._check(TokenType.RIGHT_BRACE):
                break
            if self._can_start_expression(self._peek()):
                raise self._error(self._peek(), "Expected ',' between list elements.")
            raise self._error(self._peek(), "Expected ',' or '}' in list literal.")
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after list literal.")
        return ast.ListLiteral(elements)

    def _is_matrix_signed_column_boundary(self, operator: Token) -> bool:
        if self.matrix_literal_depth == 0 or operator.type != TokenType.MINUS:
            return False
        if self._is_at_end():
            return False
        operand = self._peek()
        return (
            self._has_whitespace_before(operator)
            and self._tokens_touch(operator, operand)
            and self._can_start_expression(operand)
        )

    def _has_whitespace_before(self, token: Token) -> bool:
        token_index = self._token_index(token)
        if token_index is None or token_index == 0:
            return False
        previous = self.tokens[token_index - 1]
        if previous.line != token.line:
            return False
        return token.column > previous.column + len(previous.lexeme)

    def _tokens_touch(self, left: Token, right: Token) -> bool:
        return left.line == right.line and right.column == left.column + len(left.lexeme)

    def _token_index(self, token: Token) -> int | None:
        for index, candidate in enumerate(self.tokens):
            if candidate is token:
                return index
        return None

    def _can_start_expression(self, token: Token) -> bool:
        return token.type in {
            TokenType.BOOLEAN_LITERAL,
            TokenType.NULL_LITERAL,
            TokenType.INT_LITERAL,
            TokenType.FLOAT_LITERAL,
            TokenType.IMAG_LITERAL,
            TokenType.STRING_LITERAL,
            TokenType.IDENTIFIER,
            TokenType.TYPE,
            TokenType.LEFT_BRACKET,
            TokenType.LEFT_BRACE,
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

    def _check_next_any(self, *token_types: TokenType) -> bool:
        if self.current + 1 >= len(self.tokens):
            return False
        return self.tokens[self.current + 1].type in token_types

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
        if token.type == TokenType.EOF:
            return AetherSyntaxError(f"{message} at end of file.", line=token.line, column=token.column)
        return AetherSyntaxError(f"{message} near {token.lexeme!r}.", line=token.line, column=token.column)
