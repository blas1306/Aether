from __future__ import annotations

from pathlib import Path

from . import ast
from .errors import AetherRuntimeError, AetherTypeError
from .lexer import lex
from .parser import Parser
from .scope import Scope
from .symbols import FunctionSymbol, VariableSymbol
from .stdlib import infer_builtin_type, is_builtin, validate_builtin_arity
from .stdlib.registry import builtin_aliases_for_import
from .types import (
    AetherType,
    ArrayType,
    MatrixType,
    NUMERIC_TYPES,
    RangeType,
    array_element_type,
    can_implicitly_convert,
    is_array_type,
    is_indexable_type,
    is_matrix_type,
    matrix_row_type,
    promote_numeric,
    type_to_string,
)


UNKNOWN_TYPE: AetherType | None = None
LINEAR_ALGEBRA_MODULE = "Math.LinearAlgebra"
LINEAR_ALGEBRA_SOLVE = "Math.LinearAlgebra.solve"


class TypeChecker:
    def __init__(self) -> None:
        self.global_scope: Scope[VariableSymbol] = Scope()
        self.functions: dict[str, FunctionSymbol] = {}
        self.expression_functions: dict[str, ast.ExpressionFunctionDeclaration] = {}
        self.expression_function_call_stack: set[str] = set()
        self.current_return_type: AetherType | None = None
        self.loop_variable_stack: list[tuple[str, Scope[VariableSymbol]]] = []
        self.imported_modules: set[str] = set()
        self.builtin_aliases: dict[str, str] = {}

    def check(self, program: ast.Program) -> None:
        self._check_statements(program.statements, self.global_scope)

    def _check_statements(self, statements: list[ast.Statement], scope: Scope[VariableSymbol]) -> None:
        for statement in statements:
            self._check_statement(statement, scope)

    def _check_statement(self, statement: ast.Statement, scope: Scope[VariableSymbol]) -> None:
        if isinstance(statement, ast.VarDeclaration):
            self._declare_variable(statement, scope)
            return
        if isinstance(statement, ast.Assignment):
            self._assign_variable(statement, scope)
            return
        if isinstance(statement, ast.IndexAssignment):
            self._assign_index(statement, scope)
            return
        if isinstance(statement, ast.ExpressionStatement):
            self._expression_type(statement.expression, scope)
            return
        if isinstance(statement, ast.IfStatement):
            self._require_condition_type(statement.condition, scope, "if")
            self._check_statements(statement.body, Scope(parent=scope))
            if statement.else_body is not None:
                self._check_statements(statement.else_body, Scope(parent=scope))
            return
        if isinstance(statement, ast.WhileStatement):
            self._require_condition_type(statement.condition, scope, "while")
            self._check_statements(statement.body, Scope(parent=scope))
            return
        if isinstance(statement, ast.ForInStatement):
            self._check_for_in(statement, scope)
            return
        if isinstance(statement, ast.FunctionDeclaration):
            self._declare_function(statement)
            return
        if isinstance(statement, ast.ExpressionFunctionDeclaration):
            self._declare_expression_function(statement)
            return
        if isinstance(statement, ast.ImportStatement):
            self._check_import(statement.module_name)
            return
        if isinstance(statement, ast.ReturnStatement):
            self._check_return(statement, scope)
            return
        raise AetherRuntimeError(f"Unsupported statement {statement!r}.")

    def _check_import(self, module_name: str) -> None:
        if module_name in self.imported_modules:
            return
        if module_name == "Math" or module_name.startswith("Math."):
            self.builtin_aliases.update(builtin_aliases_for_import(module_name))
            self.imported_modules.add(module_name)
            return
        module_path = Path(module_name.replace(".", "/"))
        if module_path.suffix == "":
            module_path = module_path.with_suffix(".ae")
        if not module_path.is_absolute():
            module_path = Path.cwd() / module_path
        if not module_path.is_file():
            raise AetherTypeError(f"Module '{module_name}' not found.")
        source = module_path.read_text(encoding="utf-8")
        tokens = lex(source)
        program = Parser(tokens).parse()
        module_checker = TypeChecker()
        module_checker._check_statements(program.statements, module_checker.global_scope)
        for name, symbol in module_checker.global_scope.symbols.items():
            self.global_scope.define_local(name, symbol)
        self.functions.update(module_checker.functions)
        self.expression_functions.update(module_checker.expression_functions)
        self.imported_modules.add(module_name)

    def _declare_variable(self, statement: ast.VarDeclaration, scope: Scope[VariableSymbol]) -> None:
        if (
            (
                isinstance(statement.initializer, ast.ArrayLiteral)
                and not statement.initializer.elements
            )
            or (
                isinstance(statement.initializer, ast.MatrixLiteral)
                and not statement.initializer.rows
            )
        ):
            if not is_array_type(statement.type_name):
                raise AetherTypeError("Cannot infer type of empty matrix literal.")
            scope.define_local(
                statement.name,
                VariableSymbol(statement.name, statement.type_name),
                forbid_shadowing=True,
            )
            return
        value_type = self._expression_type(statement.initializer, scope)
        if value_type is not UNKNOWN_TYPE and not self._can_assign(
            value_type,
            statement.type_name,
            initializer=statement.initializer,
            scope=scope,
        ):
            self._raise_implicit_conversion_error(value_type, statement.type_name, statement)
        scope.define_local(
            statement.name,
            VariableSymbol(statement.name, statement.type_name),
            forbid_shadowing=True,
        )

    def _assign_variable(self, statement: ast.Assignment, scope: Scope[VariableSymbol]) -> None:
        if self._is_active_loop_variable_assignment(statement.name, scope):
            raise AetherTypeError(f"Cannot assign to loop variable '{statement.name}' inside its own for-loop.")
        existing = scope.lookup(statement.name)
        if (
            (
                isinstance(statement.expression, ast.ArrayLiteral)
                and not statement.expression.elements
            )
            or (
                isinstance(statement.expression, ast.MatrixLiteral)
                and not statement.expression.rows
            )
        ):
            if existing is None:
                raise AetherTypeError("Cannot infer type of empty matrix literal.")
            if not is_array_type(existing.type_name):
                self._raise_implicit_conversion_error(ArrayType("int"), existing.type_name, statement)
            return
        value_type = self._expression_type(statement.expression, scope)
        if existing is None:
            if value_type is not UNKNOWN_TYPE:
                scope.define_local(statement.name, VariableSymbol(statement.name, value_type))
            return
        if value_type is not UNKNOWN_TYPE and not self._can_assign(
            value_type,
            existing.type_name,
            initializer=statement.expression,
            scope=scope,
        ):
            self._raise_implicit_conversion_error(value_type, existing.type_name, statement)

    def _assign_index(self, statement: ast.IndexAssignment, scope: Scope[VariableSymbol]) -> None:
        assigned_name = _assignment_root_name(statement.array)
        if assigned_name is not None and self._is_active_loop_variable_assignment(assigned_name, scope):
            raise AetherTypeError(f"Cannot assign to loop variable '{assigned_name}' inside its own for-loop.")
        array_type = self._expression_type(statement.array, scope)
        index_type = self._expression_type(statement.index, scope)
        value_type = self._expression_type(statement.expression, scope)
        if array_type is UNKNOWN_TYPE or index_type is UNKNOWN_TYPE or value_type is UNKNOWN_TYPE:
            return
        if not is_indexable_type(array_type):
            raise AetherTypeError(f"Cannot index non-indexable value of type '{type_to_string(array_type)}'.")
        if index_type != "int":
            raise AetherTypeError(f"Array index must be int, got '{type_to_string(index_type)}'.")
        element_type = matrix_row_type(array_type) if isinstance(array_type, MatrixType) else array_element_type(array_type)
        if is_array_type(element_type):
            raise AetherTypeError("Assigning a whole matrix row is not supported yet.")
        if not can_implicitly_convert(value_type, element_type):
            self._raise_implicit_conversion_error(value_type, element_type, statement)

    def _check_for_in(self, statement: ast.ForInStatement, scope: Scope[VariableSymbol]) -> None:
        iterable_type = self._expression_type(statement.iterable, scope)
        if iterable_type is UNKNOWN_TYPE:
            return
        element_type = _iterable_element_type(iterable_type)
        if element_type is None:
            raise AetherTypeError(f"Cannot iterate over value of type '{type_to_string(iterable_type)}'.")
        loop_scope: Scope[VariableSymbol] = Scope(parent=scope)
        loop_scope.define_local(
            statement.variable,
            VariableSymbol(statement.variable, element_type),
            forbid_shadowing=True,
        )
        self.loop_variable_stack.append((statement.variable, loop_scope))
        try:
            self._check_statements(statement.body, loop_scope)
        finally:
            self.loop_variable_stack.pop()

    def _is_active_loop_variable_assignment(self, name: str, scope: Scope[VariableSymbol]) -> bool:
        target_scope = scope.resolve_scope(name)
        return any(loop_name == name and loop_scope is target_scope for loop_name, loop_scope in self.loop_variable_stack)

    def _declare_function(self, statement: ast.FunctionDeclaration) -> None:
        if statement.name in self.functions:
            raise AetherTypeError(f"Function '{statement.name}' is already defined.")
        parameters = tuple(VariableSymbol(parameter.name, parameter.type_name) for parameter in statement.parameters)
        self.functions[statement.name] = FunctionSymbol(statement.name, statement.return_type, parameters)
        function_scope: Scope[VariableSymbol] = Scope(parent=self.global_scope)
        for parameter in parameters:
            function_scope.define_local(parameter.name, parameter, forbid_shadowing=True)
        previous_return_type = self.current_return_type
        self.current_return_type = statement.return_type
        try:
            self._check_statements(statement.body, function_scope)
        finally:
            self.current_return_type = previous_return_type
        if not self._statements_always_return(statement.body):
            raise AetherTypeError(f"Function '{statement.name}' may not return a value on all paths.")

    def _declare_expression_function(self, statement: ast.ExpressionFunctionDeclaration) -> None:
        if statement.name in self.functions:
            raise AetherTypeError(f"Function '{statement.name}' is already defined.")
        parameters = tuple(VariableSymbol(parameter.name, UNKNOWN_TYPE) for parameter in statement.parameters)
        self.functions[statement.name] = FunctionSymbol(statement.name, UNKNOWN_TYPE, parameters)
        self.expression_functions[statement.name] = statement
        function_scope: Scope[VariableSymbol] = Scope(parent=self.global_scope)
        for parameter in parameters:
            function_scope.define_local(parameter.name, parameter, forbid_shadowing=True)
        self._expression_type(statement.expression, function_scope)

    def _check_return(self, statement: ast.ReturnStatement, scope: Scope[VariableSymbol]) -> None:
        if self.current_return_type is None:
            raise AetherTypeError("Cannot return outside of a function.")
        value_type = self._expression_type(statement.expression, scope)
        if value_type is not UNKNOWN_TYPE and not can_implicitly_convert(value_type, self.current_return_type):
            self._raise_implicit_conversion_error(value_type, self.current_return_type, statement)

    def _require_condition_type(self, expression: ast.Expression, scope: Scope[VariableSymbol], construct: str) -> None:
        condition_type = self._expression_type(expression, scope)
        if condition_type is not UNKNOWN_TYPE and condition_type != "boolean":
            raise AetherTypeError(
                f"The condition of '{construct}' must be boolean, got '{type_to_string(condition_type)}'."
            )

    def _expression_type(self, expression: ast.Expression, scope: Scope[VariableSymbol]) -> AetherType | None:
        if isinstance(expression, ast.Literal):
            return expression.type_name
        if isinstance(expression, ast.Identifier):
            symbol = scope.lookup(expression.name)
            if symbol is None:
                raise AetherTypeError(f"Undefined variable '{expression.name}'.")
            return symbol.type_name
        if isinstance(expression, ast.UnaryExpression):
            operand_type = self._expression_type(expression.operand, scope)
            if operand_type is UNKNOWN_TYPE:
                return UNKNOWN_TYPE
            if expression.operator == "-":
                if operand_type not in {"int", "float", "double"}:
                    raise AetherTypeError("Unary '-' requires a numeric operand.")
                return operand_type
            raise AetherRuntimeError(f"Unsupported unary operator '{expression.operator}'.")
        if isinstance(expression, ast.BinaryExpression):
            return self._binary_type(expression, scope)
        if isinstance(expression, ast.RangeExpression):
            return self._range_type(expression, scope)
        if isinstance(expression, ast.CallExpression):
            return self._call_type(expression, scope)
        if isinstance(expression, ast.ArrayLiteral):
            return self._array_literal_type(expression, scope)
        if isinstance(expression, ast.MatrixLiteral):
            return self._matrix_literal_type(expression, scope)
        if isinstance(expression, ast.IndexExpression):
            return self._index_type(expression, scope)
        raise AetherRuntimeError(f"Unsupported expression {expression!r}.")

    def _binary_type(self, expression: ast.BinaryExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        left_type = self._expression_type(expression.left, scope)
        right_type = self._expression_type(expression.right, scope)
        if left_type is UNKNOWN_TYPE or right_type is UNKNOWN_TYPE:
            return UNKNOWN_TYPE
        operator = expression.operator
        if operator in {"&&", "||"}:
            if left_type != "boolean" or right_type != "boolean":
                raise AetherTypeError(f"Operator '{operator}' requires boolean operands.")
            return "boolean"
        if operator == "%":
            if left_type not in NUMERIC_TYPES or right_type not in NUMERIC_TYPES:
                raise AetherTypeError("Operator '%' requires numeric operands.")
            return promote_numeric(left_type, right_type, operator)
        if operator in {"+", "-", "*", "/", "^"}:
            if operator == "+" and left_type == "string" and right_type == "string":
                return "string"
            array_array_type = _array_array_binary_type(left_type, operator, right_type)
            if array_array_type is not None:
                return array_array_type
            scalar_array_type = _scalar_array_binary_type(left_type, operator, right_type)
            if scalar_array_type is not None:
                return scalar_array_type
            if left_type == "string" or right_type == "string":
                raise AetherTypeError(f"Operator '{operator}' cannot mix string with non-string values.")
            if left_type == "boolean" or right_type == "boolean":
                raise AetherTypeError(f"Operator '{operator}' cannot be applied to boolean values.")
            if is_array_type(left_type) or is_array_type(right_type) or is_matrix_type(left_type) or is_matrix_type(right_type):
                raise AetherTypeError(f"Operator '{operator}' requires numeric operands.")
            return promote_numeric(left_type, right_type, operator)
        if operator == "\\":
            if LINEAR_ALGEBRA_MODULE not in self.imported_modules:
                raise AetherTypeError(
                    "Operator '\\' requires import Math.LinearAlgebra.",
                    line=expression.line,
                    column=expression.column,
                )
            return infer_builtin_type(LINEAR_ALGEBRA_SOLVE, [left_type, right_type])
        if operator in {"==", "!="}:
            if not _types_comparable_for_equality(left_type, right_type):
                raise AetherTypeError(
                    f"Cannot compare '{type_to_string(left_type)}' and '{type_to_string(right_type)}' "
                    f"with '{operator}'."
                )
            return "boolean"
        if operator in {"<", "<=", ">", ">="}:
            if left_type not in {"int", "float", "double"} or right_type not in {"int", "float", "double"}:
                raise AetherTypeError(f"Operator '{operator}' requires numeric operands.")
            return "boolean"
        raise AetherRuntimeError(f"Unsupported binary operator '{operator}'.")

    def _range_type(self, expression: ast.RangeExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        operand_types = [
            self._expression_type(expression.start, scope),
            self._expression_type(expression.end, scope),
        ]
        if expression.step is not None:
            operand_types.append(self._expression_type(expression.step, scope))
        if any(operand_type is UNKNOWN_TYPE for operand_type in operand_types):
            return UNKNOWN_TYPE
        for operand_type in operand_types:
            if operand_type != "int":
                raise AetherTypeError(f"Range bounds and step must be int, got '{type_to_string(operand_type)}'.")
        return RangeType("int")

    def _array_literal_type(self, expression: ast.ArrayLiteral, scope: Scope[VariableSymbol]) -> AetherType | None:
        if not expression.elements:
            raise AetherTypeError("Cannot infer type of empty array literal.")
        element_types = [self._expression_type(element, scope) for element in expression.elements]
        if any(element_type is UNKNOWN_TYPE for element_type in element_types):
            return UNKNOWN_TYPE
        if all(is_array_type(element_type) for element_type in element_types):
            row_lengths = [len(element.elements) for element in expression.elements if isinstance(element, ast.ArrayLiteral)]
            if row_lengths and any(length != row_lengths[0] for length in row_lengths):
                raise AetherTypeError("Matrix literals must be rectangular; ragged arrays are not supported.")
        common_type = _common_array_element_type(element_types)
        return ArrayType(common_type)

    def _matrix_literal_type(self, expression: ast.MatrixLiteral, scope: Scope[VariableSymbol]) -> AetherType | None:
        if not expression.rows:
            raise AetherTypeError("Cannot infer type of empty matrix literal.")
        row_lengths = [len(row) for row in expression.rows]
        if any(length == 0 for length in row_lengths) or any(length != row_lengths[0] for length in row_lengths):
            raise AetherTypeError("Matrix literals must be rectangular; ragged rows are not supported.")
        element_types: list[AetherType | None] = []
        for row in expression.rows:
            for element in row:
                element_type = self._expression_type(element, scope)
                if element_type is not UNKNOWN_TYPE and not isinstance(element_type, str):
                    raise AetherTypeError("Matrix literals must contain scalar homogeneous compatible elements.")
                element_types.append(element_type)
        if any(element_type is UNKNOWN_TYPE for element_type in element_types):
            return UNKNOWN_TYPE
        common_type = _common_primitive_type(element_types)
        return MatrixType(common_type, len(expression.rows), row_lengths[0])

    def _index_type(self, expression: ast.IndexExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        array_type = self._expression_type(expression.array, scope)
        index_type = self._expression_type(expression.index, scope)
        if array_type is UNKNOWN_TYPE or index_type is UNKNOWN_TYPE:
            return UNKNOWN_TYPE
        if not is_indexable_type(array_type):
            raise AetherTypeError(f"Cannot index non-indexable value of type '{type_to_string(array_type)}'.")
        if index_type != "int":
            raise AetherTypeError(f"Array index must be int, got '{type_to_string(index_type)}'.")
        if isinstance(array_type, MatrixType):
            return matrix_row_type(array_type)
        return array_element_type(array_type)

    def _call_type(self, expression: ast.CallExpression, scope: Scope[VariableSymbol]) -> AetherType | None:
        builtin_name = self.builtin_aliases.get(expression.callee, expression.callee)
        if is_builtin(builtin_name):
            validate_builtin_arity(builtin_name, len(expression.arguments))
            argument_types = [self._expression_type(argument, scope) for argument in expression.arguments]
            return infer_builtin_type(builtin_name, argument_types)
        function = self.functions.get(expression.callee)
        if function is None:
            raise AetherTypeError(f"Undefined function '{expression.callee}'.")
        if len(expression.arguments) != len(function.parameters):
            raise AetherTypeError(
                f"Function '{expression.callee}' expects {len(function.parameters)} arguments "
                f"but got {len(expression.arguments)}."
            )
        if function.return_type is UNKNOWN_TYPE:
            argument_types = [self._expression_type(argument, scope) for argument in expression.arguments]
            declaration = self.expression_functions.get(expression.callee)
            if declaration is None:
                return UNKNOWN_TYPE
            return self._expression_function_return_type(declaration, argument_types)
        for argument, parameter in zip(expression.arguments, function.parameters):
            argument_type = self._expression_type(argument, scope)
            if argument_type is not UNKNOWN_TYPE and not can_implicitly_convert(argument_type, parameter.type_name):
                self._raise_implicit_conversion_error(argument_type, parameter.type_name)
        return function.return_type

    def _expression_function_return_type(
        self,
        declaration: ast.ExpressionFunctionDeclaration,
        argument_types: list[AetherType | None],
    ) -> AetherType | None:
        if any(argument_type is UNKNOWN_TYPE for argument_type in argument_types):
            return UNKNOWN_TYPE
        if declaration.name in self.expression_function_call_stack:
            return UNKNOWN_TYPE
        function_scope: Scope[VariableSymbol] = Scope(parent=self.global_scope)
        for parameter, argument_type in zip(declaration.parameters, argument_types):
            function_scope.define_local(parameter.name, VariableSymbol(parameter.name, argument_type), forbid_shadowing=True)
        self.expression_function_call_stack.add(declaration.name)
        try:
            return self._expression_type(declaration.expression, function_scope)
        finally:
            self.expression_function_call_stack.remove(declaration.name)

    def _can_assign(
        self,
        value_type: AetherType,
        target_type: AetherType,
        *,
        initializer: ast.Expression,
        scope: Scope[VariableSymbol],
    ) -> bool:
        if isinstance(initializer, ast.ArrayLiteral) and is_array_type(target_type):
            if not is_array_type(value_type):
                return False
            return self._can_assign_array_literal(initializer, target_type, scope)
        if isinstance(initializer, ast.MatrixLiteral) and isinstance(target_type, MatrixType):
            if not isinstance(value_type, MatrixType):
                return False
            return can_implicitly_convert(value_type, target_type)
        if is_array_type(value_type) or is_array_type(target_type):
            return value_type == target_type
        if is_matrix_type(value_type) or is_matrix_type(target_type):
            return can_implicitly_convert(value_type, target_type)
        if target_type == "float" and isinstance(initializer, ast.Literal) and value_type == "double":
            return True
        return can_implicitly_convert(value_type, target_type)

    def _raise_implicit_conversion_error(
        self,
        value_type: AetherType,
        target_type: AetherType,
        location: object | None = None,
    ) -> None:
        raise AetherTypeError(
            f"Cannot implicitly convert '{type_to_string(value_type)}' to '{type_to_string(target_type)}'. "
            f"Use {type_to_string(target_type)}(...) for explicit conversion.",
            line=getattr(location, "line", None),
            column=getattr(location, "column", None),
        )

    def _can_assign_array_literal(
        self,
        initializer: ast.ArrayLiteral,
        target_type: ArrayType,
        scope: Scope[VariableSymbol],
    ) -> bool:
        if not initializer.elements:
            return True
        target_element_type = array_element_type(target_type)
        for element in initializer.elements:
            element_type = self._expression_type(element, scope)
            if element_type is UNKNOWN_TYPE:
                return True
            if isinstance(target_element_type, ArrayType):
                if not isinstance(element, ast.ArrayLiteral):
                    return element_type == target_element_type
                if not is_array_type(element_type):
                    return False
                if not self._can_assign_array_literal(element, target_element_type, scope):
                    return False
                continue
            if can_implicitly_convert(element_type, target_element_type):
                continue
            if target_element_type == "float" and element_type == "double" and isinstance(element, ast.Literal):
                continue
            return False
        return True

    def _statements_always_return(self, statements: list[ast.Statement]) -> bool:
        for statement in statements:
            if self._statement_always_returns(statement):
                return True
        return False

    def _statement_always_returns(self, statement: ast.Statement) -> bool:
        if isinstance(statement, ast.ReturnStatement):
            return True
        if isinstance(statement, ast.IfStatement):
            if statement.else_body is None:
                return False
            return self._statements_always_return(statement.body) and self._statements_always_return(statement.else_body)
        return False


def _iterable_element_type(type_name: AetherType) -> AetherType | None:
    if isinstance(type_name, RangeType):
        return type_name.element_type
    if isinstance(type_name, ArrayType):
        return type_name.element_type
    if isinstance(type_name, MatrixType) and _is_vector_like_matrix_type(type_name):
        return type_name.element_type
    return None


def _is_vector_like_matrix_type(type_name: MatrixType) -> bool:
    if type_name.vector:
        return True
    if type_name.rows is None or type_name.cols is None:
        return False
    return type_name.rows == 1 or type_name.cols == 1


def _assignment_root_name(expression: ast.Expression) -> str | None:
    if isinstance(expression, ast.Identifier):
        return expression.name
    if isinstance(expression, ast.IndexExpression):
        return _assignment_root_name(expression.array)
    return None


def _common_array_element_type(element_types: list[AetherType | None]) -> AetherType:
    primitive_types = [element_type for element_type in element_types if isinstance(element_type, str)]
    array_types = [element_type for element_type in element_types if isinstance(element_type, ArrayType)]
    if primitive_types and array_types:
        raise AetherTypeError("Array literals must contain homogeneous compatible element types.")
    if primitive_types:
        return _common_primitive_type(primitive_types)
    if array_types:
        if any(is_array_type(element_type.element_type) for element_type in array_types):
            raise AetherTypeError("Arrays nested deeper than 2D are not supported in Aether v0.")
        row_element_type = _common_primitive_type([element_type.element_type for element_type in array_types])
        return ArrayType(row_element_type)
    raise AetherTypeError("Array literals must contain homogeneous compatible element types.")


def _common_primitive_type(primitive_types: list[AetherType]) -> str:
    if not all(isinstance(type_name, str) for type_name in primitive_types):
        raise AetherTypeError("Array literals must contain homogeneous compatible element types.")
    unique_types = set(primitive_types)
    if len(unique_types) == 1:
        return primitive_types[0]
    if unique_types <= NUMERIC_TYPES:
        if "double" in unique_types:
            return "double"
        if "float" in unique_types:
            return "float"
        return "int"
    raise AetherTypeError("Array literals must contain homogeneous compatible element types.")


def _types_comparable_for_equality(left_type: AetherType, right_type: AetherType) -> bool:
    if left_type == right_type:
        return True
    if isinstance(left_type, ArrayType) and isinstance(right_type, ArrayType):
        return _types_comparable_for_equality(left_type.element_type, right_type.element_type)
    if isinstance(left_type, MatrixType) and isinstance(right_type, MatrixType):
        return left_type.rows == right_type.rows and left_type.cols == right_type.cols and _types_comparable_for_equality(
            left_type.element_type,
            right_type.element_type,
        )
    if is_array_type(left_type) or is_array_type(right_type) or is_matrix_type(left_type) or is_matrix_type(right_type):
        return False
    return left_type in {"int", "float", "double"} and right_type in {"int", "float", "double"}


def _scalar_array_binary_type(left_type: AetherType, operator: str, right_type: AetherType) -> AetherType | None:
    left_is_matrix = is_matrix_type(left_type)
    right_is_matrix = is_matrix_type(right_type)
    if not left_is_matrix and not right_is_matrix:
        return None
    if left_is_matrix and right_is_matrix:
        return None
    if operator not in {"*", "/"}:
        return None
    if operator == "/" and right_is_matrix:
        return None
    matrix_type = left_type if left_is_matrix else right_type
    scalar_type = right_type if left_is_matrix else left_type
    if not isinstance(matrix_type, MatrixType) or scalar_type not in NUMERIC_TYPES:
        return None
    element_type = _numeric_matrix_scalar_type(matrix_type)
    result_element_type = promote_numeric(element_type, scalar_type, operator)
    return MatrixType(result_element_type, matrix_type.rows, matrix_type.cols, matrix_type.vector)


def _array_array_binary_type(left_type: AetherType, operator: str, right_type: AetherType) -> AetherType | None:
    if not is_matrix_type(left_type) or not is_matrix_type(right_type):
        return None
    if operator not in {"+", "-"}:
        return None
    if not isinstance(left_type, MatrixType) or not isinstance(right_type, MatrixType):
        return None
    if (
        left_type.rows is not None
        and right_type.rows is not None
        and left_type.cols is not None
        and right_type.cols is not None
        and (left_type.rows != right_type.rows or left_type.cols != right_type.cols)
    ):
        raise AetherTypeError(
            f"Operator '{operator}' requires matrices with the same shape, got "
            f"'{type_to_string(left_type)}' and '{type_to_string(right_type)}'."
        )
    left_element_type = _numeric_matrix_scalar_type(left_type)
    right_element_type = _numeric_matrix_scalar_type(right_type)
    result_element_type = promote_numeric(left_element_type, right_element_type, operator)
    rows = left_type.rows if left_type.rows is not None else right_type.rows
    cols = left_type.cols if left_type.cols is not None else right_type.cols
    return MatrixType(result_element_type, rows, cols, left_type.vector and right_type.vector)


def _numeric_matrix_scalar_type(matrix_type: MatrixType) -> str:
    if matrix_type.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Matrix operations require numeric elements.")
    return matrix_type.element_type


def check_program(program: ast.Program) -> None:
    TypeChecker().check(program)
