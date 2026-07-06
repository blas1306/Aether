from __future__ import annotations

from dataclasses import dataclass, field
from typing import NoReturn

from .. import ast
from ..errors import IRBackendUnsupportedFeatureError
from ..types import AetherType
from .model import (
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
)
from .types import (
    BoolType,
    ComplexType,
    DoubleType,
    FloatType,
    IntType,
    IRType,
    StringType,
    VoidType,
)


_BINARY_OPERATORS = {
    "+": "add",
    "-": "sub",
    "*": "mul",
    "/": "div",
    "%": "rem",
}
_COMPARE_OPERATORS = {
    "<": "lt",
    "<=": "le",
    ">": "gt",
    ">=": "ge",
    "==": "eq",
    "!=": "ne",
}
_NUMERIC_IR_TYPES = (IntType, FloatType, DoubleType, ComplexType)
_REAL_IR_TYPES = (IntType, FloatType, DoubleType)
_EQUALITY_IR_TYPES = (IntType, DoubleType, BoolType, StringType)
_CAST_BUILTINS = {"int", "float", "double", "string", "boolean"}


@dataclass(frozen=True)
class _FunctionSignature:
    parameters: tuple[IRType, ...]
    return_type: IRType


@dataclass
class _FunctionContext:
    block: IRBasicBlock
    blocks: list[IRBasicBlock]
    return_type: IRType
    parameters: dict[str, IRParameter]
    locals: dict[str, IRValue] = field(default_factory=dict)
    next_temporary: int = 0
    next_if: int = 0
    next_loop: int = 0

    def temporary(self, type_: IRType) -> IRValue:
        value = IRValue(str(self.next_temporary), type_)
        self.next_temporary += 1
        return value

    def if_index(self) -> int:
        index = self.next_if
        self.next_if += 1
        return index

    def loop_index(self) -> int:
        index = self.next_loop
        self.next_loop += 1
        return index


class IRLowerer:
    """Lower the initial checked-AST subset to Aether IR."""

    def __init__(self) -> None:
        self._signatures: dict[str, _FunctionSignature] = {}

    def lower(self, program: ast.Program) -> IRModule:
        """Lower a typechecked program without changing the main pipeline."""
        self._signatures = self._collect_signatures(program)
        return IRModule(
            [self._lower_function(statement) for statement in program.statements]
        )

    def _collect_signatures(self, program: ast.Program) -> dict[str, _FunctionSignature]:
        signatures: dict[str, _FunctionSignature] = {}
        for statement in program.statements:
            if not isinstance(statement, ast.FunctionDeclaration):
                self._unsupported(statement)
            signatures[statement.name] = _FunctionSignature(
                tuple(self._lower_type(parameter.type_name) for parameter in statement.parameters),
                self._lower_type(statement.return_type),
            )
        return signatures

    def _lower_function(self, declaration: ast.FunctionDeclaration) -> IRFunction:
        signature = self._signatures[declaration.name]
        parameters = [
            IRParameter(parameter.name, parameter_type)
            for parameter, parameter_type in zip(declaration.parameters, signature.parameters)
        ]
        block = IRBasicBlock("entry")
        blocks = [block]
        context = _FunctionContext(
            block=block,
            blocks=blocks,
            return_type=signature.return_type,
            parameters={parameter.name: parameter for parameter in parameters},
        )
        assigned_names = self._assigned_names(declaration.body)
        for parameter in parameters:
            if parameter.name in assigned_names:
                slot = IRValue(parameter.name, parameter.type)
                context.locals[parameter.name] = slot
                context.block.instructions.append(IRStore(slot, parameter))

        for statement in declaration.body:
            if self._is_terminated(context.block):
                self._fail("IR backend does not support statements after a terminated block yet.", statement)
            self._lower_statement(statement, context)

        if not self._is_terminated(context.block):
            if isinstance(signature.return_type, VoidType):
                context.block.instructions.append(IRReturn())
            else:
                self._fail(
                    f"IR backend requires a direct return in function '{declaration.name}' yet.",
                    declaration,
                )

        return IRFunction(declaration.name, parameters, signature.return_type, blocks)

    def _lower_statement(self, statement: ast.Statement, context: _FunctionContext) -> None:
        if isinstance(statement, ast.VarDeclaration):
            value = self._lower_expression(statement.initializer, context)
            slot_type = (
                self._lower_type(statement.type_name)
                if statement.type_name is not None
                else value.type
            )
            self._require_same_type(
                value.type,
                slot_type,
                f"variable '{statement.name}' requires an implicit conversion",
            )
            slot = IRValue(statement.name, slot_type)
            context.locals[statement.name] = slot
            context.block.instructions.append(IRStore(slot, value))
            return

        if isinstance(statement, ast.Assignment):
            value = self._lower_expression(statement.expression, context)
            slot = context.locals.get(statement.name)
            if slot is None:
                parameter = context.parameters.get(statement.name)
                if parameter is None:
                    self._fail(
                        f"IR backend does not support assignment to '{statement.name}' outside local scope yet.",
                        statement,
                    )
                slot = IRValue(statement.name, parameter.type)
                context.locals[statement.name] = slot
                context.blocks[0].instructions.insert(0, IRStore(slot, parameter))
            self._require_same_type(
                value.type,
                slot.type,
                f"assignment to '{statement.name}' requires an implicit conversion",
            )
            context.block.instructions.append(IRStore(slot, value))
            return

        if isinstance(statement, ast.ReturnStatement):
            if statement.expression is None:
                if not isinstance(context.return_type, VoidType):
                    self._fail("IR backend cannot return void from a non-void function.", statement)
                context.block.instructions.append(IRReturn())
                return
            value = self._lower_expression(statement.expression, context)
            self._require_same_type(
                value.type,
                context.return_type,
                "return requires an implicit conversion",
            )
            context.block.instructions.append(IRReturn(value))
            return

        if isinstance(statement, ast.IfStatement):
            self._lower_if(statement, context)
            return

        if isinstance(statement, ast.WhileStatement):
            self._lower_while(statement, context)
            return

        self._unsupported(statement)

    def _lower_if(self, statement: ast.IfStatement, context: _FunctionContext) -> None:
        condition = self._lower_expression(statement.condition, context)
        self._require_same_type(condition.type, BoolType(), "if condition must be bool")

        index = context.if_index()
        then_block = IRBasicBlock(f"then{index}")
        else_block = (
            IRBasicBlock(f"else{index}") if statement.else_body is not None else None
        )
        merge_block = (
            IRBasicBlock(f"merge{index}")
            if statement.else_body is None
            else None
        )

        false_target = else_block.name if else_block is not None else merge_block.name
        context.block.instructions.append(
            IRBranch(condition, then_block.name, false_target)
        )

        context.blocks.append(then_block)
        context.block = then_block
        self._lower_statements(statement.body, context)
        then_end = context.block
        then_terminated = self._is_terminated(then_end)

        else_end = else_block
        else_terminated = False
        if else_block is not None:
            context.blocks.append(else_block)
            context.block = else_block
            self._lower_statements(statement.else_body or [], context)
            else_end = context.block
            else_terminated = self._is_terminated(else_end)
            if not then_terminated or not else_terminated:
                merge_block = IRBasicBlock(f"merge{index}")

        if merge_block is None:
            context.block = else_end if else_end is not None else then_end
            return

        if not then_terminated:
            then_end.instructions.append(IRJump(merge_block.name))
        if else_end is not None and not else_terminated:
            else_end.instructions.append(IRJump(merge_block.name))

        context.blocks.append(merge_block)
        context.block = merge_block

    def _lower_while(
        self,
        statement: ast.WhileStatement,
        context: _FunctionContext,
    ) -> None:
        index = context.loop_index()
        condition_block = IRBasicBlock(f"cond{index}")
        body_block = IRBasicBlock(f"body{index}")
        exit_block = IRBasicBlock(f"exit{index}")

        context.block.instructions.append(IRJump(condition_block.name))

        context.blocks.append(condition_block)
        context.block = condition_block
        condition = self._lower_expression(statement.condition, context)
        self._require_same_type(condition.type, BoolType(), "while condition must be bool")
        condition_block.instructions.append(
            IRBranch(condition, body_block.name, exit_block.name)
        )

        context.blocks.append(body_block)
        context.block = body_block
        self._lower_statements(statement.body, context)
        body_end = context.block
        if not self._is_terminated(body_end):
            body_end.instructions.append(IRJump(condition_block.name))

        context.blocks.append(exit_block)
        context.block = exit_block

    def _lower_statements(
        self,
        statements: list[ast.Statement],
        context: _FunctionContext,
    ) -> None:
        for statement in statements:
            if self._is_terminated(context.block):
                self._fail("IR backend does not support statements after a terminated block yet.", statement)
            self._lower_statement(statement, context)

    def _lower_expression(
        self,
        expression: ast.Expression,
        context: _FunctionContext,
    ) -> IRValue:
        if isinstance(expression, ast.Literal):
            return self._lower_literal(expression, context)

        if isinstance(expression, ast.Identifier):
            slot = context.locals.get(expression.name)
            if slot is not None:
                result = context.temporary(slot.type)
                context.block.instructions.append(IRLoad(result, slot))
                return result
            parameter = context.parameters.get(expression.name)
            if parameter is not None:
                return parameter
            self._fail(
                f"IR backend does not support identifier '{expression.name}' outside local scope yet.",
                expression,
            )

        if isinstance(expression, ast.BinaryExpression):
            binary_operator = _BINARY_OPERATORS.get(expression.operator)
            compare_operator = _COMPARE_OPERATORS.get(expression.operator)
            if binary_operator is None and compare_operator is None:
                self._unsupported(expression, f"operator '{expression.operator}'")
            left = self._lower_expression(expression.left, context)
            right = self._lower_expression(expression.right, context)
            if compare_operator is not None:
                result_type = self._comparison_result_type(
                    compare_operator,
                    left.type,
                    right.type,
                )
                result = context.temporary(result_type)
                context.block.instructions.append(
                    IRCompareOp(result, compare_operator, left, right)
                )
                return result
            result_type = self._binary_result_type(expression.operator, left.type, right.type)
            result = context.temporary(result_type)
            context.block.instructions.append(IRBinaryOp(result, binary_operator, left, right))
            return result

        if isinstance(expression, ast.UnaryExpression):
            if expression.operator != "-":
                self._unsupported(expression, f"operator '{expression.operator}'")
            operand = self._lower_expression(expression.operand, context)
            if not isinstance(operand.type, _NUMERIC_IR_TYPES):
                self._unsupported(expression, f"operand type '{operand.type}'")
            zero = context.temporary(operand.type)
            context.block.instructions.append(IRConst(zero, 0))
            result = context.temporary(operand.type)
            context.block.instructions.append(IRBinaryOp(result, "sub", zero, operand))
            return result

        if isinstance(expression, ast.CallExpression):
            return self._lower_call(expression, context)

        self._unsupported(expression)

    def _lower_literal(self, literal: ast.Literal, context: _FunctionContext) -> IRValue:
        type_ = self._lower_type(literal.type_name)
        if not isinstance(type_, (IntType, DoubleType, BoolType, StringType)):
            self._unsupported(literal, f"literal type '{type_}'")
        result = context.temporary(type_)
        context.block.instructions.append(IRConst(result, literal.value))
        return result

    def _lower_call(self, call: ast.CallExpression, context: _FunctionContext) -> IRValue:
        if call.keyword_arguments:
            self._unsupported(call, "keyword arguments")
        if call.callee in _CAST_BUILTINS:
            return self._lower_cast(call, context)
        signature = self._signatures.get(call.callee)
        if signature is None:
            self._unsupported(call, f"callee '{call.callee}'")
        if isinstance(signature.return_type, VoidType):
            self._unsupported(call, "void return value")

        arguments = tuple(
            self._lower_expression(argument, context) for argument in call.arguments
        )
        if len(arguments) != len(signature.parameters):
            raise ValueError(
                f"Checked call to '{call.callee}' has {len(arguments)} arguments; "
                f"expected {len(signature.parameters)}"
            )
        for index, (argument, parameter_type) in enumerate(
            zip(arguments, signature.parameters),
            start=1,
        ):
            self._require_same_type(
                argument.type,
                parameter_type,
                f"argument {index} to '{call.callee}' requires an implicit conversion",
            )

        result = context.temporary(signature.return_type)
        context.block.instructions.append(IRCall(call.callee, arguments, result))
        return result

    def _lower_cast(self, call: ast.CallExpression, context: _FunctionContext) -> IRValue:
        if len(call.arguments) != 1:
            raise ValueError(
                f"Checked cast '{call.callee}' has {len(call.arguments)} arguments; expected 1"
            )

        value = self._lower_expression(call.arguments[0], context)
        target_type = self._lower_type(call.callee)
        if not self._is_supported_numeric_cast(value.type, target_type):
            self._fail(
                f"IR backend does not support cast from '{value.type}' to '{target_type}' yet.",
                call,
            )

        result = context.temporary(target_type)
        context.block.instructions.append(IRCast(result, value))
        return result

    def _binary_result_type(self, operator: str, left: IRType, right: IRType) -> IRType:
        if isinstance(left, StringType) and isinstance(right, StringType) and operator == "+":
            return StringType()
        if not isinstance(left, _NUMERIC_IR_TYPES) or not isinstance(right, _NUMERIC_IR_TYPES):
            self._fail(
                f"IR backend does not support binary expressions with operand types '{left}' and '{right}' yet."
            )
        if operator == "%" and (
            not isinstance(left, _REAL_IR_TYPES) or not isinstance(right, _REAL_IR_TYPES)
        ):
            self._fail(
                f"IR backend does not support '%' with operand types '{left}' and '{right}' yet."
            )
        if operator == "/" and isinstance(left, IntType) and isinstance(right, IntType):
            return DoubleType()
        if isinstance(left, ComplexType) or isinstance(right, ComplexType):
            return ComplexType()
        if isinstance(left, DoubleType) or isinstance(right, DoubleType):
            return DoubleType()
        if isinstance(left, FloatType) or isinstance(right, FloatType):
            return FloatType()
        return IntType()

    def _comparison_result_type(self, operator: str, left: IRType, right: IRType) -> IRType:
        if operator in {"lt", "le", "gt", "ge"}:
            if (
                isinstance(left, IntType)
                and isinstance(right, IntType)
                or isinstance(left, DoubleType)
                and isinstance(right, DoubleType)
            ):
                return BoolType()
            self._fail(
                f"IR backend does not support ordered comparison with operand types '{left}' and '{right}' yet."
            )

        if operator in {"eq", "ne"}:
            if left == right and isinstance(left, _EQUALITY_IR_TYPES):
                return BoolType()
            self._fail(
                f"IR backend does not support equality comparison with operand types '{left}' and '{right}' yet."
            )

        self._fail(f"IR backend does not support comparison operator '{operator}' yet.")

    def _lower_type(self, type_name: AetherType | None) -> IRType:
        if type_name == "int":
            return IntType()
        if type_name == "float":
            return FloatType()
        if type_name == "double":
            return DoubleType()
        if type_name == "complex":
            return ComplexType()
        if type_name == "boolean":
            return BoolType()
        if type_name == "string":
            return StringType()
        if type_name == "void":
            return VoidType()
        self._fail(f"IR backend does not support type '{type_name}' yet.")

    def _require_same_type(self, actual: IRType, expected: IRType, operation: str) -> None:
        if actual != expected:
            self._fail(
                f"IR backend does not support implicit conversion when {operation}: "
                f"'{actual}' to '{expected}'."
            )

    @staticmethod
    def _is_supported_numeric_cast(source: IRType, target: IRType) -> bool:
        return (
            isinstance(source, IntType)
            and isinstance(target, DoubleType)
            or isinstance(source, DoubleType)
            and isinstance(target, IntType)
        )

    @staticmethod
    def _is_terminated(block: IRBasicBlock) -> bool:
        return bool(block.instructions) and isinstance(
            block.instructions[-1],
            (IRReturn, IRJump, IRBranch),
        )

    def _assigned_names(self, statements: list[ast.Statement]) -> set[str]:
        names: set[str] = set()
        for statement in statements:
            if isinstance(statement, ast.Assignment):
                names.add(statement.name)
            elif isinstance(statement, ast.IfStatement):
                names.update(self._assigned_names(statement.body))
                if statement.else_body is not None:
                    names.update(self._assigned_names(statement.else_body))
            elif isinstance(statement, ast.WhileStatement):
                names.update(self._assigned_names(statement.body))
        return names

    @staticmethod
    def _unsupported(node: object, detail: str | None = None) -> NoReturn:
        feature = _feature_name(node)
        detail_text = f" ({detail})" if detail is not None else ""
        line = getattr(node, "line", None)
        column = getattr(node, "column", None)
        raise IRBackendUnsupportedFeatureError(
            f"IR backend does not support {feature}{detail_text} yet.",
            line=line if isinstance(line, int) else None,
            column=column if isinstance(column, int) else None,
        )

    @staticmethod
    def _fail(message: str, node: object | None = None) -> NoReturn:
        line = getattr(node, "line", None)
        column = getattr(node, "column", None)
        raise IRBackendUnsupportedFeatureError(
            message,
            line=line if isinstance(line, int) else None,
            column=column if isinstance(column, int) else None,
        )


def _feature_name(node: object) -> str:
    names = {
        "AliasDeclaration": "alias declarations",
        "StructDeclaration": "struct declarations",
        "ClassDeclaration": "class declarations",
        "InterfaceDeclaration": "interface declarations",
        "EnumDeclaration": "enum declarations",
        "ExpressionFunctionDeclaration": "expression functions",
        "VarDeclaration": "top-level variable declarations",
        "ImportStatement": "imports",
        "ExpressionStatement": "expression statements",
        "DestructuringAssignment": "destructuring assignments",
        "IndexAssignment": "index assignments",
        "MatrixIndexAssignment": "matrix index assignments",
        "FieldAssignment": "field assignments",
        "ForInStatement": "for-in loops",
        "BreakStatement": "break statements",
        "ContinueStatement": "continue statements",
        "ThrowStatement": "throw statements",
        "TryCatchStatement": "try/catch statements",
        "MatrixLiteral": "matrix literals",
        "ArrayLiteral": "array literals",
        "ListLiteral": "list literals",
        "IndexExpression": "index expressions",
        "FieldAccess": "field access",
    }
    return names.get(type(node).__name__, type(node).__name__)


def lower_to_ir(program: ast.Program) -> IRModule:
    return IRLowerer().lower(program)
