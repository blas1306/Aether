from __future__ import annotations

from dataclasses import dataclass, field
from typing import NoReturn

from .. import ast
from ..types import AetherType
from .model import (
    IRBasicBlock,
    IRBinaryOp,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
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
_EQUALITY_IR_TYPES = (IntType, BoolType, StringType)


@dataclass(frozen=True)
class _FunctionSignature:
    parameters: tuple[IRType, ...]
    return_type: IRType


@dataclass
class _FunctionContext:
    block: IRBasicBlock
    return_type: IRType
    parameters: dict[str, IRParameter]
    locals: dict[str, IRValue] = field(default_factory=dict)
    next_temporary: int = 0

    def temporary(self, type_: IRType) -> IRValue:
        value = IRValue(str(self.next_temporary), type_)
        self.next_temporary += 1
        return value


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
        context = _FunctionContext(
            block=block,
            return_type=signature.return_type,
            parameters={parameter.name: parameter for parameter in parameters},
        )

        for statement in declaration.body:
            if self._is_terminated(block):
                raise NotImplementedError(
                    "IR lowering not implemented for statements after ReturnStatement"
                )
            self._lower_statement(statement, context)

        if not self._is_terminated(block):
            if isinstance(signature.return_type, VoidType):
                block.instructions.append(IRReturn())
            else:
                raise NotImplementedError(
                    f"IR lowering requires a direct return in function '{declaration.name}'"
                )

        return IRFunction(declaration.name, parameters, signature.return_type, [block])

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

        if isinstance(statement, ast.ReturnStatement):
            if statement.expression is None:
                if not isinstance(context.return_type, VoidType):
                    raise NotImplementedError("IR lowering cannot return void from a non-void function")
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

        self._unsupported(statement)

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
            raise NotImplementedError(
                f"IR lowering not implemented for Identifier '{expression.name}' outside local scope"
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
        if not isinstance(type_, (IntType, BoolType, StringType)):
            self._unsupported(literal, f"literal type '{type_}'")
        result = context.temporary(type_)
        context.block.instructions.append(IRConst(result, literal.value))
        return result

    def _lower_call(self, call: ast.CallExpression, context: _FunctionContext) -> IRValue:
        if call.keyword_arguments:
            self._unsupported(call, "keyword arguments")
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

    def _binary_result_type(self, operator: str, left: IRType, right: IRType) -> IRType:
        if isinstance(left, StringType) and isinstance(right, StringType) and operator == "+":
            return StringType()
        if not isinstance(left, _NUMERIC_IR_TYPES) or not isinstance(right, _NUMERIC_IR_TYPES):
            raise NotImplementedError(
                f"IR lowering not implemented for BinaryExpression with operand types '{left}' and '{right}'"
            )
        if operator == "%" and (
            not isinstance(left, _REAL_IR_TYPES) or not isinstance(right, _REAL_IR_TYPES)
        ):
            raise NotImplementedError(
                f"IR lowering not implemented for BinaryExpression operator '%' "
                f"with operand types '{left}' and '{right}'"
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
            if isinstance(left, IntType) and isinstance(right, IntType):
                return BoolType()
            raise NotImplementedError(
                f"IR lowering not implemented for ordered comparison with operand types "
                f"'{left}' and '{right}'"
            )

        if operator in {"eq", "ne"}:
            if left == right and isinstance(left, _EQUALITY_IR_TYPES):
                return BoolType()
            raise NotImplementedError(
                f"IR lowering not implemented for equality comparison with operand types "
                f"'{left}' and '{right}'"
            )

        raise NotImplementedError(
            f"IR lowering not implemented for comparison operator '{operator}'"
        )

    @staticmethod
    def _lower_type(type_name: AetherType | None) -> IRType:
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
        raise NotImplementedError(f"IR lowering not implemented for type '{type_name}'")

    @staticmethod
    def _require_same_type(actual: IRType, expected: IRType, operation: str) -> None:
        if actual != expected:
            raise NotImplementedError(
                f"IR lowering not implemented when {operation}: '{actual}' to '{expected}'"
            )

    @staticmethod
    def _is_terminated(block: IRBasicBlock) -> bool:
        return bool(block.instructions) and isinstance(block.instructions[-1], IRReturn)

    @staticmethod
    def _unsupported(node: object, detail: str | None = None) -> NoReturn:
        suffix = f" ({detail})" if detail is not None else ""
        raise NotImplementedError(
            f"IR lowering not implemented for {type(node).__name__}{suffix}"
        )


def lower_to_ir(program: ast.Program) -> IRModule:
    return IRLowerer().lower(program)
