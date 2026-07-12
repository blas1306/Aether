from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import NoReturn

from .. import ast
from ..errors import IRBackendUnsupportedFeatureError
from ..types import (
    AetherType,
    ArrayType as AetherArrayType,
    ListType as AetherListType,
    MatrixType as AetherMatrixType,
    VectorType as AetherVectorType,
)
from .model import (
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRJump,
    IRListGet,
    IRListCopy,
    IRListContains,
    IRListClear,
    IRListPop,
    IRListPush,
    IRListIndexOf,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListSet,
    IRListReverse,
    IRSequenceSort,
    IRLoad,
    IRMatrixGet,
    IRMatrixAdd,
    IRMatrixMatMul,
    IRMatrixVectorMul,
    IRMatrixScale,
    IRMatrixSub,
    IRMatrixColumns,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixSet,
    IRModule,
    IROuterProduct,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    IRVectorGet,
    IRVectorAdd,
    IRVectorDot,
    IRVectorMatrixMul,
    IRVectorScale,
    IRVectorSub,
    IRVectorLength,
    IRVectorNew,
    IRVectorSet,
)
from .types import (
    ArrayType,
    BoolType,
    ComplexType,
    DoubleType,
    FloatType,
    IntType,
    IRType,
    ListType,
    MatrixType,
    StringType,
    VectorType,
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


@dataclass(frozen=True)
class _LoopTargets:
    break_target: str
    continue_target: str


@dataclass(frozen=True)
class _WhileBlocks:
    condition: IRBasicBlock
    body: IRBasicBlock
    exit: IRBasicBlock


@dataclass(frozen=True)
class _ForBlocks:
    condition: IRBasicBlock
    body: IRBasicBlock
    increment: IRBasicBlock
    exit: IRBasicBlock


@dataclass(frozen=True)
class _IndexableIterable:
    value: IRValue
    element_type: IRType
    length: IRValue
    get_instruction: type[IRArrayGet] | type[IRListGet] | type[IRVectorGet]


_MISSING_LOCAL = object()


@dataclass
class _FunctionContext:
    block: IRBasicBlock
    blocks: list[IRBasicBlock]
    return_type: IRType
    parameters: dict[str, IRParameter]
    locals: dict[str, IRValue] = field(default_factory=dict)
    matrix_dimensions: dict[str, tuple[int, int]] = field(default_factory=dict)
    vector_lengths: dict[str, int] = field(default_factory=dict)
    loop_targets: list[_LoopTargets] = field(default_factory=list)
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
            slot_type = (
                self._lower_type(statement.type_name)
                if statement.type_name is not None
                else None
            )
            value = self._lower_expression(
                statement.initializer,
                context,
                target_type=slot_type,
            )
            if (
                isinstance(slot_type, VectorType)
                and slot_type.orientation is None
                and isinstance(value.type, VectorType)
            ):
                slot_type = value.type
            slot_type = slot_type if slot_type is not None else value.type
            self._require_same_type(
                value.type,
                slot_type,
                f"variable '{statement.name}' requires an implicit conversion",
            )
            slot = IRValue(statement.name, slot_type)
            context.locals[statement.name] = slot
            self._copy_aggregate_metadata(value, slot, context)
            context.block.instructions.append(IRStore(slot, value))
            return

        if isinstance(statement, ast.Assignment):
            if isinstance(statement.name, ast.MatrixIndexExpression):
                self._lower_matrix_index_assignment(statement.name, statement.expression, statement, context)
                return
            if isinstance(statement.name, ast.IndexExpression):
                self._lower_index_assignment(statement.name, statement.expression, statement, context)
                return
            if not isinstance(statement.name, str):
                self._fail("IR backend requires a variable or aggregate element assignment target.", statement)
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
            value = self._lower_expression(
                statement.expression,
                context,
                target_type=slot.type,
            )
            self._require_same_type(
                value.type,
                slot.type,
                f"assignment to '{statement.name}' requires an implicit conversion",
            )
            self._copy_aggregate_metadata(value, slot, context)
            context.block.instructions.append(IRStore(slot, value))
            return

        if isinstance(statement, ast.IndexAssignment):
            self._lower_index_assignment(
                ast.IndexExpression(statement.array, statement.index, statement.line, statement.column),
                statement.expression,
                statement,
                context,
            )
            return

        if isinstance(statement, ast.MatrixIndexAssignment):
            self._lower_matrix_index_assignment(
                ast.MatrixIndexExpression(
                    statement.matrix,
                    statement.row,
                    statement.column_index,
                    statement.line,
                    statement.column,
                ),
                statement.expression,
                statement,
                context,
            )
            return

        if isinstance(statement, ast.ReturnStatement):
            if statement.expression is None:
                if not isinstance(context.return_type, VoidType):
                    self._fail("IR backend cannot return void from a non-void function.", statement)
                context.block.instructions.append(IRReturn())
                return
            value = self._lower_expression(
                statement.expression,
                context,
                target_type=context.return_type,
            )
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

        if isinstance(statement, ast.ForInStatement):
            self._lower_for_in(statement, context)
            return

        if isinstance(statement, ast.BreakStatement):
            self._emit_break(statement, context)
            return

        if isinstance(statement, ast.ContinueStatement):
            self._emit_continue(statement, context)
            return

        if isinstance(statement, ast.ExpressionStatement):
            expression = statement.expression
            if isinstance(expression, ast.CallExpression) and (
                expression.callee == "pop" or expression.callee.endswith(".pop")
            ):
                self._lower_call(expression, context)
                return
            if isinstance(expression, ast.CallExpression) and (
                expression.callee == "push" or expression.callee.endswith(".push")
            ):
                arguments = expression.arguments
                if expression.callee.endswith(".push"):
                    receiver = expression.callee.rsplit(".", 1)[0]
                    arguments = [ast.Identifier(receiver, expression.line, expression.column), *arguments]
                if expression.keyword_arguments or len(arguments) != 2:
                    self._unsupported(expression, "invalid push call")
                list_value = self._lower_expression(arguments[0], context)
                if not isinstance(list_value.type, ListType):
                    self._unsupported(expression, "push on non-list")
                value = self._lower_expression(arguments[1], context, target_type=list_value.type.element)
                self._require_same_type(
                    value.type,
                    list_value.type.element,
                    "push value requires an implicit conversion",
                )
                context.block.instructions.append(IRListPush(list_value, value))
                return
            if isinstance(expression, ast.CallExpression) and (
                expression.callee == "clear" or expression.callee.endswith(".clear")
            ):
                arguments = expression.arguments
                if expression.callee.endswith(".clear"):
                    receiver = expression.callee.rsplit(".", 1)[0]
                    arguments = [ast.Identifier(receiver, expression.line, expression.column), *arguments]
                if expression.keyword_arguments or len(arguments) != 1:
                    self._unsupported(expression, "invalid clear call")
                list_value = self._lower_expression(arguments[0], context)
                if not isinstance(list_value.type, ListType):
                    self._unsupported(expression, "clear on non-list")
                context.block.instructions.append(IRListClear(list_value))
                return
            if isinstance(expression, ast.CallExpression) and (
                expression.callee == "sort" or expression.callee.endswith(".sort")
            ):
                arguments = expression.arguments
                if expression.callee.endswith(".sort"):
                    receiver = expression.callee.rsplit(".", 1)[0]
                    arguments = [ast.Identifier(receiver, expression.line, expression.column), *arguments]
                if expression.keyword_arguments or len(arguments) != 1:
                    self._unsupported(expression, "invalid sort call")
                sequence = self._lower_expression(arguments[0], context)
                if not isinstance(sequence.type, (ArrayType, ListType)):
                    self._unsupported(expression, "sort on non-sequence")
                context.block.instructions.append(IRSequenceSort(sequence))
                return
            if isinstance(expression, ast.CallExpression) and (
                expression.callee == "reverse" or expression.callee.endswith(".reverse")
            ):
                arguments = expression.arguments
                if expression.callee.endswith(".reverse"):
                    receiver = expression.callee.rsplit(".", 1)[0]
                    arguments = [ast.Identifier(receiver, expression.line, expression.column), *arguments]
                if expression.keyword_arguments or len(arguments) != 1:
                    self._unsupported(expression, "invalid reverse call")
                list_value = self._lower_expression(arguments[0], context)
                if not isinstance(list_value.type, ListType):
                    self._unsupported(expression, "reverse on non-list")
                context.block.instructions.append(IRListReverse(list_value))
                return
            self._unsupported(statement)

        self._unsupported(statement)

    @staticmethod
    def _new_block(name: str) -> IRBasicBlock:
        return IRBasicBlock(name)

    def _new_while_blocks(self, index: int) -> _WhileBlocks:
        return _WhileBlocks(
            condition=self._new_block(f"cond{index}"),
            body=self._new_block(f"body{index}"),
            exit=self._new_block(f"exit{index}"),
        )

    def _new_for_blocks(self, index: int) -> _ForBlocks:
        return _ForBlocks(
            condition=self._new_block(f"for.cond{index}"),
            body=self._new_block(f"for.body{index}"),
            increment=self._new_block(f"for.inc{index}"),
            exit=self._new_block(f"for.exit{index}"),
        )

    @staticmethod
    def _append_block(context: _FunctionContext, block: IRBasicBlock) -> IRBasicBlock:
        context.blocks.append(block)
        return block

    @staticmethod
    def _enter_block(context: _FunctionContext, block: IRBasicBlock) -> IRBasicBlock:
        context.block = block
        return block

    def _append_and_enter(
        self,
        context: _FunctionContext,
        block: IRBasicBlock,
    ) -> IRBasicBlock:
        self._append_block(context, block)
        return self._enter_block(context, block)

    def _emit_jump_if_open(self, block: IRBasicBlock, target: str) -> bool:
        if self._is_terminated(block):
            return False
        block.instructions.append(IRJump(target))
        return True

    def _emit_current_jump_if_open(
        self,
        context: _FunctionContext,
        target: str,
    ) -> bool:
        return self._emit_jump_if_open(context.block, target)

    def _emit_branch(
        self,
        block: IRBasicBlock,
        condition: IRValue,
        true_target: str,
        false_target: str,
        operation: str,
    ) -> None:
        self._require_same_type(condition.type, BoolType(), operation)
        block.instructions.append(IRBranch(condition, true_target, false_target))

    def _finish_if_merge(
        self,
        context: _FunctionContext,
        index: int,
        then_end: IRBasicBlock,
        else_end: IRBasicBlock | None,
        merge_block: IRBasicBlock | None,
    ) -> None:
        open_blocks = [
            block
            for block in (then_end, else_end)
            if block is not None and not self._is_terminated(block)
        ]
        if merge_block is None:
            if not open_blocks:
                context.block = else_end if else_end is not None else then_end
                return
            merge_block = self._new_block(f"merge{index}")

        for block in open_blocks:
            self._emit_jump_if_open(block, merge_block.name)

        self._append_and_enter(context, merge_block)

    def _active_loop_targets(
        self,
        statement: ast.Statement,
        context: _FunctionContext,
    ) -> _LoopTargets:
        if not context.loop_targets:
            if isinstance(statement, ast.BreakStatement):
                self._fail("IR backend found break outside a loop after typechecking.", statement)
            self._fail("IR backend found continue outside a loop after typechecking.", statement)
        return context.loop_targets[-1]

    def _emit_break(
        self,
        statement: ast.BreakStatement,
        context: _FunctionContext,
    ) -> None:
        self._emit_current_jump_if_open(
            context,
            self._active_loop_targets(statement, context).break_target,
        )

    def _emit_continue(
        self,
        statement: ast.ContinueStatement,
        context: _FunctionContext,
    ) -> None:
        self._emit_current_jump_if_open(
            context,
            self._active_loop_targets(statement, context).continue_target,
        )

    @contextmanager
    def _loop_context(
        self,
        context: _FunctionContext,
        *,
        break_target: str,
        continue_target: str,
        loop_variable: str | None = None,
        loop_slot: IRValue | None = None,
    ) -> Iterator[None]:
        previous_local: IRValue | object = _MISSING_LOCAL
        if loop_variable is not None:
            if loop_slot is None:
                raise ValueError("loop_slot is required when loop_variable is set")
            previous_local = context.locals.get(loop_variable, _MISSING_LOCAL)
            context.locals[loop_variable] = loop_slot

        context.loop_targets.append(_LoopTargets(break_target, continue_target))
        try:
            yield
        finally:
            context.loop_targets.pop()
            if loop_variable is not None:
                if previous_local is _MISSING_LOCAL:
                    context.locals.pop(loop_variable, None)
                else:
                    context.locals[loop_variable] = previous_local

    def _lower_index_assignment(
        self,
        target: ast.IndexExpression,
        value_expression: ast.Expression,
        statement: ast.Statement,
        context: _FunctionContext,
    ) -> None:
        indexed = self._lower_expression(target.array, context)
        if isinstance(indexed.type, ListType):
            index = self._lower_expression(target.index, context)
            self._require_same_type(index.type, IntType(), "list index must be int")
            value = self._lower_expression(
                value_expression,
                context,
                target_type=indexed.type.element,
            )
            self._require_same_type(
                value.type,
                indexed.type.element,
                "list index assignment requires an implicit conversion",
            )
            context.block.instructions.append(IRListSet(indexed, index, value))
            return
        if isinstance(indexed.type, VectorType):
            index = self._lower_expression(target.index, context)
            self._require_same_type(index.type, IntType(), "vector index must be int")
            value = self._lower_expression(
                value_expression,
                context,
                target_type=indexed.type.element,
            )
            self._require_same_type(
                value.type,
                indexed.type.element,
                "vector index assignment requires an implicit conversion",
            )
            context.block.instructions.append(IRVectorSet(indexed, index, value))
            return
        if not isinstance(indexed.type, ArrayType):
            self._fail(
                f"IR backend only supports index assignment for arrays and vectors, got '{indexed.type}'.",
                statement,
            )
        index = self._lower_expression(target.index, context)
        self._require_same_type(index.type, IntType(), "array index must be int")
        value = self._lower_expression(
            value_expression,
            context,
            target_type=indexed.type.element,
        )
        self._require_same_type(
            value.type,
            indexed.type.element,
            "array index assignment requires an implicit conversion",
        )
        context.block.instructions.append(IRArraySet(indexed, index, value))

    def _lower_matrix_index_assignment(
        self,
        target: ast.MatrixIndexExpression,
        value_expression: ast.Expression,
        statement: ast.Statement,
        context: _FunctionContext,
    ) -> None:
        matrix = self._lower_expression(target.matrix, context)
        if not isinstance(matrix.type, MatrixType):
            self._fail(
                f"IR backend only supports two-dimensional assignment for matrices, got '{matrix.type}'.",
                statement,
            )
        dimensions = context.matrix_dimensions.get(matrix.name)
        if dimensions is None:
            self._fail(
                "IR backend requires known matrix dimensions for A[i, j].",
                statement,
            )
        _rows, cols = dimensions
        row = self._lower_expression(target.row, context)
        self._require_same_type(row.type, IntType(), "matrix row index must be int")
        column = self._lower_expression(target.column, context)
        self._require_same_type(column.type, IntType(), "matrix column index must be int")
        value = self._lower_expression(
            value_expression,
            context,
            target_type=matrix.type.element,
        )
        self._require_same_type(
            value.type,
            matrix.type.element,
            "matrix index assignment requires an implicit conversion",
        )
        context.block.instructions.append(IRMatrixSet(matrix, row, column, value, cols))

    def _lower_if(self, statement: ast.IfStatement, context: _FunctionContext) -> None:
        condition = self._lower_expression(statement.condition, context)

        index = context.if_index()
        then_block = self._new_block(f"then{index}")
        else_block = (
            self._new_block(f"else{index}") if statement.else_body is not None else None
        )
        merge_block = (
            self._new_block(f"merge{index}")
            if statement.else_body is None
            else None
        )

        false_target = else_block.name if else_block is not None else merge_block.name
        self._emit_branch(
            context.block,
            condition,
            then_block.name,
            false_target,
            "if condition must be bool",
        )

        self._append_and_enter(context, then_block)
        self._lower_statements(statement.body, context)
        then_end = context.block

        else_end = else_block
        if else_block is not None:
            self._append_and_enter(context, else_block)
            self._lower_statements(statement.else_body or [], context)
            else_end = context.block

        self._finish_if_merge(context, index, then_end, else_end, merge_block)

    def _lower_while(
        self,
        statement: ast.WhileStatement,
        context: _FunctionContext,
    ) -> None:
        index = context.loop_index()
        blocks = self._new_while_blocks(index)

        self._emit_current_jump_if_open(context, blocks.condition.name)

        self._append_and_enter(context, blocks.condition)
        condition = self._lower_expression(statement.condition, context)
        self._emit_branch(
            blocks.condition,
            condition,
            blocks.body.name,
            blocks.exit.name,
            "while condition must be bool",
        )

        self._append_and_enter(context, blocks.body)
        with self._loop_context(
            context,
            break_target=blocks.exit.name,
            continue_target=blocks.condition.name,
        ):
            self._lower_statements(statement.body, context)
        body_end = context.block
        self._emit_jump_if_open(body_end, blocks.condition.name)

        self._append_and_enter(context, blocks.exit)

    def _lower_for_in(
        self,
        statement: ast.ForInStatement,
        context: _FunctionContext,
    ) -> None:
        if isinstance(statement.iterable, ast.RangeExpression):
            self._lower_for_range(statement, statement.iterable, context)
            return

        self._lower_for_indexable(statement, context)

    def _lower_for_range(
        self,
        statement: ast.ForInStatement,
        expression: ast.RangeExpression,
        context: _FunctionContext,
    ) -> None:
        index = context.loop_index()
        blocks = self._new_for_blocks(index)

        start = self._lower_expression(expression.start, context)
        end = self._lower_expression(expression.end, context)
        if expression.step is None:
            step = context.temporary(IntType())
            context.block.instructions.append(IRConst(step, 1))
            step_value = 1
        else:
            step = self._lower_expression(expression.step, context)
            step_value = self._constant_int(expression.step)

        for label, value in (("start", start), ("end", end), ("step", step)):
            self._require_same_type(value.type, IntType(), f"for range {label} must be int")
        if step_value == 0:
            self._fail("IR backend does not support for ranges with a zero step yet.", statement)

        loop_slot = IRValue(statement.variable, IntType())

        with self._loop_context(
            context,
            break_target=blocks.exit.name,
            continue_target=blocks.increment.name,
            loop_variable=statement.variable,
            loop_slot=loop_slot,
        ):
            context.block.instructions.append(IRStore(loop_slot, start))
            self._emit_current_jump_if_open(context, blocks.condition.name)

            self._append_and_enter(context, blocks.condition)
            self._lower_for_range_condition(
                context,
                index,
                loop_slot,
                step,
                end,
                step_value,
                blocks,
            )

            self._append_and_enter(context, blocks.body)
            self._lower_statements(statement.body, context)
            self._emit_jump_if_open(context.block, blocks.increment.name)

            self._append_and_enter(context, blocks.increment)
            current_for_increment = context.temporary(IntType())
            blocks.increment.instructions.append(IRLoad(current_for_increment, loop_slot))
            next_value = context.temporary(IntType())
            blocks.increment.instructions.append(
                IRBinaryOp(next_value, "add", current_for_increment, step)
            )
            blocks.increment.instructions.append(IRStore(loop_slot, next_value))
            self._emit_jump_if_open(blocks.increment, blocks.condition.name)

            self._append_and_enter(context, blocks.exit)

    def _lower_for_range_condition(
        self,
        context: _FunctionContext,
        index: int,
        loop_slot: IRValue,
        step: IRValue,
        end: IRValue,
        step_value: int | None,
        blocks: _ForBlocks,
    ) -> None:
        if step_value is not None:
            current = context.temporary(IntType())
            blocks.condition.instructions.append(IRLoad(current, loop_slot))
            condition = context.temporary(BoolType())
            operator = "le" if step_value > 0 else "ge"
            blocks.condition.instructions.append(
                IRCompareOp(condition, operator, current, end)
            )
            self._emit_branch(
                blocks.condition,
                condition,
                blocks.body.name,
                blocks.exit.name,
                "for range condition must be bool",
            )
            return

        positive_check_block = self._new_block(f"for.pos{index}")
        negative_check_block = self._new_block(f"for.neg{index}")
        negative_bound_block = self._new_block(f"for.neg.bound{index}")
        current = context.temporary(IntType())
        blocks.condition.instructions.append(IRLoad(current, loop_slot))
        zero = context.temporary(IntType())
        blocks.condition.instructions.append(IRConst(zero, 0))
        step_positive = context.temporary(BoolType())
        blocks.condition.instructions.append(IRCompareOp(step_positive, "gt", step, zero))
        self._emit_branch(
            blocks.condition,
            step_positive,
            positive_check_block.name,
            negative_check_block.name,
            "for range step sign condition must be bool",
        )

        self._append_block(context, positive_check_block)
        positive_condition = context.temporary(BoolType())
        positive_check_block.instructions.append(
            IRCompareOp(positive_condition, "le", current, end)
        )
        self._emit_branch(
            positive_check_block,
            positive_condition,
            blocks.body.name,
            blocks.exit.name,
            "for range positive bound condition must be bool",
        )

        self._append_block(context, negative_check_block)
        step_negative = context.temporary(BoolType())
        negative_check_block.instructions.append(IRCompareOp(step_negative, "lt", step, zero))
        self._emit_branch(
            negative_check_block,
            step_negative,
            negative_bound_block.name,
            blocks.exit.name,
            "for range negative step condition must be bool",
        )

        self._append_block(context, negative_bound_block)
        negative_condition = context.temporary(BoolType())
        negative_bound_block.instructions.append(
            IRCompareOp(negative_condition, "ge", current, end)
        )
        self._emit_branch(
            negative_bound_block,
            negative_condition,
            blocks.body.name,
            blocks.exit.name,
            "for range negative bound condition must be bool",
        )

    def _lower_for_indexable(
        self,
        statement: ast.ForInStatement,
        context: _FunctionContext,
    ) -> None:
        index = context.loop_index()
        blocks = self._new_for_blocks(index)
        iterable = self._lower_indexable_iterable(statement, context)

        index_slot = IRValue(f"for.{index}.index", IntType())
        loop_slot = IRValue(statement.variable, iterable.element_type)

        with self._loop_context(
            context,
            break_target=blocks.exit.name,
            continue_target=blocks.increment.name,
            loop_variable=statement.variable,
            loop_slot=loop_slot,
        ):
            one = self._initialize_indexable_loop_index(context, index_slot)
            self._emit_current_jump_if_open(context, blocks.condition.name)

            self._append_and_enter(context, blocks.condition)
            self._lower_for_indexable_condition(context, index_slot, iterable, blocks)

            self._append_and_enter(context, blocks.body)
            self._lower_for_indexable_body_prelude(
                context,
                index_slot,
                loop_slot,
                iterable,
            )
            self._lower_statements(statement.body, context)
            self._emit_jump_if_open(context.block, blocks.increment.name)

            self._append_and_enter(context, blocks.increment)
            self._lower_for_indexable_increment(context, index_slot, one, blocks)

            self._append_and_enter(context, blocks.exit)

    def _lower_indexable_iterable(
        self,
        statement: ast.ForInStatement,
        context: _FunctionContext,
    ) -> _IndexableIterable:
        iterable = self._lower_expression(statement.iterable, context)
        if isinstance(iterable.type, ArrayType):
            length = context.temporary(IntType())
            context.block.instructions.append(IRArrayLength(length, iterable))
            return _IndexableIterable(
                iterable,
                iterable.type.element,
                length,
                IRArrayGet,
            )
        if isinstance(iterable.type, ListType):
            length = context.temporary(IntType())
            context.block.instructions.append(IRListLength(length, iterable))
            return _IndexableIterable(
                iterable,
                iterable.type.element,
                length,
                IRListGet,
            )
        if isinstance(iterable.type, VectorType):
            length = context.temporary(IntType())
            context.block.instructions.append(IRVectorLength(length, iterable))
            return _IndexableIterable(
                iterable,
                iterable.type.element,
                length,
                IRVectorGet,
            )
        self._fail(
            f"IR backend only supports for loops over int ranges, arrays, lists, and vectors, got '{iterable.type}'.",
            statement,
        )

    def _initialize_indexable_loop_index(
        self,
        context: _FunctionContext,
        index_slot: IRValue,
    ) -> IRValue:
        zero = context.temporary(IntType())
        context.block.instructions.append(IRConst(zero, 0))
        one = context.temporary(IntType())
        context.block.instructions.append(IRConst(one, 1))
        context.block.instructions.append(IRStore(index_slot, zero))
        return one

    def _lower_for_indexable_condition(
        self,
        context: _FunctionContext,
        index_slot: IRValue,
        iterable: _IndexableIterable,
        blocks: _ForBlocks,
    ) -> None:
        current_index = context.temporary(IntType())
        blocks.condition.instructions.append(IRLoad(current_index, index_slot))
        condition = context.temporary(BoolType())
        blocks.condition.instructions.append(
            IRCompareOp(condition, "lt", current_index, iterable.length)
        )
        self._emit_branch(
            blocks.condition,
            condition,
            blocks.body.name,
            blocks.exit.name,
            "for indexable condition must be bool",
        )

    def _lower_for_indexable_body_prelude(
        self,
        context: _FunctionContext,
        index_slot: IRValue,
        loop_slot: IRValue,
        iterable: _IndexableIterable,
    ) -> None:
        body_index = context.temporary(IntType())
        context.block.instructions.append(IRLoad(body_index, index_slot))
        element = context.temporary(iterable.element_type)
        context.block.instructions.append(
            iterable.get_instruction(element, iterable.value, body_index)
        )
        context.block.instructions.append(IRStore(loop_slot, element))

    def _lower_for_indexable_increment(
        self,
        context: _FunctionContext,
        index_slot: IRValue,
        one: IRValue,
        blocks: _ForBlocks,
    ) -> None:
        increment_index = context.temporary(IntType())
        blocks.increment.instructions.append(IRLoad(increment_index, index_slot))
        next_index = context.temporary(IntType())
        blocks.increment.instructions.append(
            IRBinaryOp(next_index, "add", increment_index, one)
        )
        blocks.increment.instructions.append(IRStore(index_slot, next_index))
        self._emit_jump_if_open(blocks.increment, blocks.condition.name)

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
        *,
        target_type: IRType | None = None,
    ) -> IRValue:
        if isinstance(expression, ast.Literal):
            return self._lower_literal(expression, context)

        if isinstance(expression, (ast.ArrayLiteral, ast.ListLiteral)):
            return self._lower_braced_literal(expression, context, target_type)

        if isinstance(expression, ast.MatrixLiteral):
            if expression.vector:
                return self._lower_vector_literal(expression, context, target_type)
            return self._lower_matrix_literal(expression, context, target_type)

        if isinstance(expression, ast.Identifier):
            slot = context.locals.get(expression.name)
            if slot is not None:
                result = context.temporary(slot.type)
                context.block.instructions.append(IRLoad(result, slot))
                self._copy_aggregate_metadata(slot, result, context)
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
            if expression.operator in {"+", "-", "*"}:
                aggregate_binary = self._lower_aggregate_binary(
                    expression,
                    left,
                    right,
                    context,
                )
                if aggregate_binary is not None:
                    return aggregate_binary
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

        if isinstance(expression, ast.IndexExpression):
            indexed = self._lower_expression(expression.array, context)
            if isinstance(indexed.type, ListType):
                index = self._lower_expression(expression.index, context)
                self._require_same_type(index.type, IntType(), "list index must be int")
                result = context.temporary(indexed.type.element)
                context.block.instructions.append(IRListGet(result, indexed, index))
                return result
            if isinstance(indexed.type, VectorType):
                index = self._lower_expression(expression.index, context)
                self._require_same_type(index.type, IntType(), "vector index must be int")
                result = context.temporary(indexed.type.element)
                context.block.instructions.append(IRVectorGet(result, indexed, index))
                return result
            if not isinstance(indexed.type, ArrayType):
                self._fail(
                    f"IR backend only supports indexing arrays and vectors, got '{indexed.type}'.",
                    expression,
                )
            index = self._lower_expression(expression.index, context)
            self._require_same_type(index.type, IntType(), "array index must be int")
            result = context.temporary(indexed.type.element)
            context.block.instructions.append(IRArrayGet(result, indexed, index))
            return result

        if isinstance(expression, ast.MatrixIndexExpression):
            matrix = self._lower_expression(expression.matrix, context)
            if not isinstance(matrix.type, MatrixType):
                self._fail(
                    f"IR backend only supports two-dimensional indexing matrices, got '{matrix.type}'.",
                    expression,
                )
            dimensions = context.matrix_dimensions.get(matrix.name)
            if dimensions is None:
                self._fail(
                    "IR backend requires known matrix dimensions for A[i, j].",
                    expression,
                )
            _rows, cols = dimensions
            row = self._lower_expression(expression.row, context)
            self._require_same_type(row.type, IntType(), "matrix row index must be int")
            column = self._lower_expression(expression.column, context)
            self._require_same_type(column.type, IntType(), "matrix column index must be int")
            result = context.temporary(matrix.type.element)
            context.block.instructions.append(IRMatrixGet(result, matrix, row, column, cols))
            return result

        if isinstance(expression, ast.FieldAccess):
            target = self._lower_expression(expression.target, context)
            if expression.field_name == "length" and isinstance(target.type, ArrayType):
                result = context.temporary(IntType())
                context.block.instructions.append(IRArrayLength(result, target))
                return result
            if expression.field_name == "length" and isinstance(target.type, ListType):
                result = context.temporary(IntType())
                context.block.instructions.append(IRListLength(result, target))
                return result
            if expression.field_name == "is_empty" and isinstance(target.type, ListType):
                result = context.temporary(BoolType())
                context.block.instructions.append(IRListIsEmpty(result, target))
                return result
            if expression.field_name == "length" and isinstance(target.type, VectorType):
                result = context.temporary(IntType())
                context.block.instructions.append(IRVectorLength(result, target))
                return result
            if expression.field_name in {"rows", "columns"} and isinstance(target.type, MatrixType):
                dimensions = context.matrix_dimensions.get(target.name)
                if dimensions is None:
                    self._fail(
                        f"IR backend requires known matrix dimensions for .{expression.field_name}.",
                        expression,
                    )
                rows, cols = dimensions
                result = context.temporary(IntType())
                if expression.field_name == "rows":
                    context.block.instructions.append(IRMatrixRows(result, target, rows))
                else:
                    context.block.instructions.append(IRMatrixColumns(result, target, cols))
                return result
            self._unsupported(expression, f"field '{expression.field_name}'")

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
        method_name = call.callee.rsplit(".", 1)[-1]
        arguments = call.arguments
        if "." in call.callee and method_name in {"copy", "contains", "indexOf", "pop"}:
            receiver = call.callee.rsplit(".", 1)[0]
            arguments = [ast.Identifier(receiver, call.line, call.column), *arguments]
        if method_name == "copy" and len(arguments) == 1:
            list_value = self._lower_expression(arguments[0], context)
            if isinstance(list_value.type, ListType):
                result = context.temporary(list_value.type)
                context.block.instructions.append(IRListCopy(result, list_value))
                return result
        if method_name == "contains" and len(arguments) == 2:
            list_value = self._lower_expression(arguments[0], context)
            if isinstance(list_value.type, ListType):
                value = self._lower_expression(
                    arguments[1], context, target_type=list_value.type.element
                )
                self._require_same_type(
                    value.type,
                    list_value.type.element,
                    "contains value requires an implicit conversion",
                )
                result = context.temporary(BoolType())
                context.block.instructions.append(IRListContains(result, list_value, value))
                return result
        if method_name == "indexOf" and len(arguments) == 2:
            list_value = self._lower_expression(arguments[0], context)
            if isinstance(list_value.type, ListType):
                value = self._lower_expression(
                    arguments[1], context, target_type=list_value.type.element
                )
                self._require_same_type(
                    value.type,
                    list_value.type.element,
                    "indexOf value requires an implicit conversion",
                )
                result = context.temporary(IntType())
                context.block.instructions.append(IRListIndexOf(result, list_value, value))
                return result
        if method_name == "pop" and len(arguments) == 1:
            list_value = self._lower_expression(arguments[0], context)
            if isinstance(list_value.type, ListType):
                result = context.temporary(list_value.type.element)
                context.block.instructions.append(IRListPop(result, list_value))
                return result
        if call.callee in _CAST_BUILTINS:
            return self._lower_cast(call, context)
        signature = self._signatures.get(call.callee)
        if signature is None:
            self._unsupported(call, f"callee '{call.callee}'")
        if isinstance(signature.return_type, VoidType):
            self._unsupported(call, "void return value")

        if len(call.arguments) != len(signature.parameters):
            raise ValueError(
                f"Checked call to '{call.callee}' has {len(call.arguments)} arguments; "
                f"expected {len(signature.parameters)}"
            )
        arguments = tuple(
            self._lower_expression(argument, context, target_type=parameter_type)
            for argument, parameter_type in zip(call.arguments, signature.parameters)
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

    def _lower_braced_literal(
        self,
        expression: ast.ArrayLiteral | ast.ListLiteral,
        context: _FunctionContext,
        target_type: IRType | None,
    ) -> IRValue:
        if isinstance(target_type, ArrayType):
            return self._lower_array_literal(expression, context, target_type)
        if isinstance(target_type, ListType) and isinstance(expression, ast.ListLiteral):
            return self._lower_list_literal(expression, context, target_type)
        self._unsupported(expression, "braced literal without Array<T> or List<T> target type")

    def _lower_array_literal(
        self,
        expression: ast.ArrayLiteral | ast.ListLiteral,
        context: _FunctionContext,
        target_type: ArrayType,
    ) -> IRValue:
        elements = tuple(
            self._lower_expression(element, context, target_type=target_type.element)
            for element in expression.elements
        )
        for element in elements:
            self._require_same_type(
                element.type,
                target_type.element,
                "array literal element requires an implicit conversion",
            )
        result = context.temporary(target_type)
        context.block.instructions.append(IRArrayNew(result, elements))
        return result

    def _lower_list_literal(
        self,
        expression: ast.ListLiteral,
        context: _FunctionContext,
        target_type: ListType,
    ) -> IRValue:
        elements = tuple(
            self._lower_expression(element, context, target_type=target_type.element)
            for element in expression.elements
        )
        for element in elements:
            self._require_same_type(
                element.type,
                target_type.element,
                "list literal element requires an implicit conversion",
            )
        result = context.temporary(target_type)
        context.block.instructions.append(IRListNew(result, elements))
        return result

    def _lower_vector_literal(
        self,
        expression: ast.MatrixLiteral,
        context: _FunctionContext,
        target_type: IRType | None,
    ) -> IRValue:
        elements_source: list[ast.Expression]
        if expression.orientation == "column" and all(len(row) == 1 for row in expression.rows):
            elements_source = [row[0] for row in expression.rows]
        elif len(expression.rows) == 1:
            elements_source = expression.rows[0]
        else:
            self._unsupported(expression, "non-vector literal")
        if not elements_source:
            self._unsupported(expression, "empty vector literal")

        element_target_type = target_type.element if isinstance(target_type, VectorType) else None
        elements = tuple(
            self._lower_expression(element, context, target_type=element_target_type)
            for element in elements_source
        )

        if isinstance(target_type, VectorType):
            orientation = target_type.orientation or expression.orientation
            vector_type = VectorType(target_type.element, orientation)
        else:
            element_type = elements[0].type
            if any(element.type != element_type for element in elements):
                self._fail(
                    "IR backend does not support implicit conversion inside vector literals yet.",
                    expression,
                )
            vector_type = VectorType(element_type, expression.orientation or "row")

        for element in elements:
            self._require_same_type(
                element.type,
                vector_type.element,
                "vector literal element requires an implicit conversion",
            )
        result = context.temporary(vector_type)
        context.vector_lengths[result.name] = len(elements)
        context.block.instructions.append(IRVectorNew(result, elements, vector_type.orientation))
        return result

    def _lower_matrix_literal(
        self,
        expression: ast.MatrixLiteral,
        context: _FunctionContext,
        target_type: IRType | None,
    ) -> IRValue:
        row_lengths = [len(row) for row in expression.rows]
        if not row_lengths or any(length == 0 for length in row_lengths):
            self._unsupported(expression, "empty matrix literal")
        if any(length != row_lengths[0] for length in row_lengths):
            self._fail("IR backend cannot lower ragged matrix literals.", expression)

        element_target_type = target_type.element if isinstance(target_type, MatrixType) else None
        elements_source = [element for row in expression.rows for element in row]
        elements = tuple(
            self._lower_expression(element, context, target_type=element_target_type)
            for element in elements_source
        )

        if isinstance(target_type, MatrixType):
            matrix_type = MatrixType(target_type.element)
        else:
            element_type = elements[0].type
            if any(element.type != element_type for element in elements):
                self._fail(
                    "IR backend does not support implicit conversion inside matrix literals yet.",
                    expression,
                )
            matrix_type = MatrixType(element_type)

        for element in elements:
            self._require_same_type(
                element.type,
                matrix_type.element,
                "matrix literal element requires an implicit conversion",
            )
        result = context.temporary(matrix_type)
        context.matrix_dimensions[result.name] = (len(expression.rows), row_lengths[0])
        context.block.instructions.append(IRMatrixNew(result, elements, len(expression.rows), row_lengths[0]))
        return result

    @staticmethod
    def _copy_aggregate_metadata(source: IRValue, target: IRValue, context: _FunctionContext) -> None:
        dimensions = context.matrix_dimensions.get(source.name)
        if dimensions is not None:
            context.matrix_dimensions[target.name] = dimensions
        vector_length = context.vector_lengths.get(source.name)
        if vector_length is not None:
            context.vector_lengths[target.name] = vector_length

    def _lower_aggregate_binary(
        self,
        expression: ast.BinaryExpression,
        left: IRValue,
        right: IRValue,
        context: _FunctionContext,
    ) -> IRValue | None:
        operator = expression.operator
        if operator not in {"+", "-", "*"}:
            return None

        if operator == "*":
            vector_dot = self._lower_vector_dot(expression, left, right, context)
            if vector_dot is not None:
                return vector_dot
            outer_product = self._lower_outer_product(expression, left, right, context)
            if outer_product is not None:
                return outer_product
            matrix_matmul = self._lower_matrix_matmul(expression, left, right, context)
            if matrix_matmul is not None:
                return matrix_matmul
            matrix_vector_mul = self._lower_matrix_vector_mul(expression, left, right, context)
            if matrix_vector_mul is not None:
                return matrix_vector_mul
            vector_matrix_mul = self._lower_vector_matrix_mul(expression, left, right, context)
            if vector_matrix_mul is not None:
                return vector_matrix_mul
            return self._lower_aggregate_scale(expression, left, right, context)

        if isinstance(left.type, VectorType) or isinstance(right.type, VectorType):
            if not isinstance(left.type, VectorType) or not isinstance(right.type, VectorType):
                return None
            if left.type.orientation != right.type.orientation:
                self._fail(
                    f"IR backend requires vector operands with the same orientation for '{operator}', "
                    f"got '{left.type}' and '{right.type}'.",
                    expression,
                )
            self._require_same_type(
                right.type.element,
                left.type.element,
                f"vector {self._aggregate_operation_name(operator)} requires matching element types",
            )
            left_length = context.vector_lengths.get(left.name)
            right_length = context.vector_lengths.get(right.name)
            if left_length is None or right_length is None:
                self._fail(
                    f"IR backend requires known vector lengths for Vector {operator} Vector.",
                    expression,
                )
            if left_length != right_length:
                self._fail(
                    f"IR backend requires equal vector lengths for '{operator}', got {left_length} and {right_length}.",
                    expression,
                )
            result = context.temporary(left.type)
            context.vector_lengths[result.name] = left_length
            instruction_type = IRVectorAdd if operator == "+" else IRVectorSub
            context.block.instructions.append(instruction_type(result, left, right, left_length, left.type.orientation))
            return result

        if isinstance(left.type, MatrixType) or isinstance(right.type, MatrixType):
            if not isinstance(left.type, MatrixType) or not isinstance(right.type, MatrixType):
                return None
            self._require_same_type(
                right.type.element,
                left.type.element,
                f"matrix {self._aggregate_operation_name(operator)} requires matching element types",
            )
            left_dimensions = context.matrix_dimensions.get(left.name)
            right_dimensions = context.matrix_dimensions.get(right.name)
            if left_dimensions is None or right_dimensions is None:
                self._fail(
                    f"IR backend requires known matrix dimensions for Matrix {operator} Matrix.",
                    expression,
                )
            if left_dimensions != right_dimensions:
                self._fail(
                    f"IR backend requires equal matrix dimensions for '{operator}', "
                    f"got {left_dimensions[0]}x{left_dimensions[1]} and "
                    f"{right_dimensions[0]}x{right_dimensions[1]}.",
                    expression,
                )
            result = context.temporary(left.type)
            context.matrix_dimensions[result.name] = left_dimensions
            instruction_type = IRMatrixAdd if operator == "+" else IRMatrixSub
            context.block.instructions.append(instruction_type(result, left, right, left_dimensions[0], left_dimensions[1]))
            return result

        return None

    def _lower_vector_dot(
        self,
        expression: ast.BinaryExpression,
        left: IRValue,
        right: IRValue,
        context: _FunctionContext,
    ) -> IRValue | None:
        if not isinstance(left.type, VectorType) or not isinstance(right.type, VectorType):
            return None
        if left.type.orientation != "row" or right.type.orientation != "column":
            return None

        left_length = context.vector_lengths.get(left.name)
        right_length = context.vector_lengths.get(right.name)
        if left_length is None or right_length is None:
            self._fail(
                "IR backend requires known vector lengths for Vector<Row> * Vector<Column>.",
                expression,
            )
        if left_length != right_length:
            self._fail(
                f"IR backend requires equal vector lengths for Vector<Row> * Vector<Column>, "
                f"got {left_length} and {right_length}.",
                expression,
            )

        result_type = self._binary_result_type("*", left.type.element, right.type.element)
        result = context.temporary(result_type)
        context.block.instructions.append(IRVectorDot(result, left, right, left_length))
        return result

    def _lower_outer_product(
        self,
        expression: ast.BinaryExpression,
        left: IRValue,
        right: IRValue,
        context: _FunctionContext,
    ) -> IRValue | None:
        if not isinstance(left.type, VectorType) or not isinstance(right.type, VectorType):
            return None
        if left.type.orientation != "column" or right.type.orientation != "row":
            return None

        left_length = context.vector_lengths.get(left.name)
        right_length = context.vector_lengths.get(right.name)
        if left_length is None or right_length is None:
            self._fail(
                "IR backend requires known vector lengths for Vector<Column> * Vector<Row>.",
                expression,
            )

        result_type = self._binary_result_type("*", left.type.element, right.type.element)
        result = context.temporary(MatrixType(result_type))
        context.matrix_dimensions[result.name] = (left_length, right_length)
        context.block.instructions.append(IROuterProduct(result, left, right, left_length, right_length))
        return result

    def _lower_matrix_matmul(
        self,
        expression: ast.BinaryExpression,
        left: IRValue,
        right: IRValue,
        context: _FunctionContext,
    ) -> IRValue | None:
        if not isinstance(left.type, MatrixType) or not isinstance(right.type, MatrixType):
            return None

        left_dimensions = context.matrix_dimensions.get(left.name)
        right_dimensions = context.matrix_dimensions.get(right.name)
        if left_dimensions is None or right_dimensions is None:
            self._fail(
                "IR backend requires known matrix dimensions for Matrix * Matrix.",
                expression,
            )

        result_type = self._binary_result_type("*", left.type.element, right.type.element)
        result = context.temporary(MatrixType(result_type))
        context.matrix_dimensions[result.name] = (left_dimensions[0], right_dimensions[1])
        context.block.instructions.append(
            IRMatrixMatMul(
                result,
                left,
                right,
                left_dimensions[0],
                left_dimensions[1],
                right_dimensions[1],
            )
        )
        return result

    def _lower_matrix_vector_mul(
        self,
        expression: ast.BinaryExpression,
        left: IRValue,
        right: IRValue,
        context: _FunctionContext,
    ) -> IRValue | None:
        if not isinstance(left.type, MatrixType) or not isinstance(right.type, VectorType):
            return None
        if right.type.orientation != "column":
            return None

        left_dimensions = context.matrix_dimensions.get(left.name)
        right_length = context.vector_lengths.get(right.name)
        if left_dimensions is None or right_length is None:
            self._fail(
                "IR backend requires known dimensions for Matrix * Vector<Column>.",
                expression,
            )
        if left_dimensions[1] != right_length:
            self._fail(
                f"IR backend requires compatible dimensions for Matrix * Vector<Column>, "
                f"got {left_dimensions[0]}x{left_dimensions[1]} and length {right_length}.",
                expression,
            )

        result_type = self._binary_result_type("*", left.type.element, right.type.element)
        result = context.temporary(VectorType(result_type, "column"))
        context.vector_lengths[result.name] = left_dimensions[0]
        context.block.instructions.append(
            IRMatrixVectorMul(result, left, right, left_dimensions[0], left_dimensions[1])
        )
        return result

    def _lower_vector_matrix_mul(
        self,
        expression: ast.BinaryExpression,
        left: IRValue,
        right: IRValue,
        context: _FunctionContext,
    ) -> IRValue | None:
        if not isinstance(left.type, VectorType) or not isinstance(right.type, MatrixType):
            return None
        if left.type.orientation != "row":
            return None

        left_length = context.vector_lengths.get(left.name)
        right_dimensions = context.matrix_dimensions.get(right.name)
        if left_length is None or right_dimensions is None:
            self._fail(
                "IR backend requires known dimensions for Vector<Row> * Matrix.",
                expression,
            )
        if left_length != right_dimensions[0]:
            self._fail(
                f"IR backend requires compatible dimensions for Vector<Row> * Matrix, "
                f"got length {left_length} and {right_dimensions[0]}x{right_dimensions[1]}.",
                expression,
            )

        result_type = self._binary_result_type("*", left.type.element, right.type.element)
        result = context.temporary(VectorType(result_type, "row"))
        context.vector_lengths[result.name] = right_dimensions[1]
        context.block.instructions.append(
            IRVectorMatrixMul(result, left, right, right_dimensions[0], right_dimensions[1])
        )
        return result

    @staticmethod
    def _aggregate_operation_name(operator: str) -> str:
        if operator == "+":
            return "addition"
        if operator == "-":
            return "subtraction"
        return "multiplication"

    def _lower_aggregate_scale(
        self,
        expression: ast.BinaryExpression,
        left: IRValue,
        right: IRValue,
        context: _FunctionContext,
    ) -> IRValue | None:
        if isinstance(left.type, VectorType) or isinstance(right.type, VectorType):
            if isinstance(left.type, VectorType) and isinstance(right.type, VectorType):
                return None
            vector = left if isinstance(left.type, VectorType) else right
            scalar = right if vector is left else left
            if not isinstance(scalar.type, _NUMERIC_IR_TYPES):
                return None
            scalar = self._coerce_scalar_for_scale(
                scalar,
                vector.type.element,
                "vector scalar multiplication requires matching scalar and element types",
                context,
            )
            length = context.vector_lengths.get(vector.name)
            if length is None:
                self._fail(
                    "IR backend requires known vector length for scalar * Vector.",
                    expression,
                )
            result = context.temporary(vector.type)
            context.vector_lengths[result.name] = length
            context.block.instructions.append(
                IRVectorScale(result, vector, scalar, length, vector.type.orientation)
            )
            return result

        if isinstance(left.type, MatrixType) or isinstance(right.type, MatrixType):
            if isinstance(left.type, MatrixType) and isinstance(right.type, MatrixType):
                return None
            matrix = left if isinstance(left.type, MatrixType) else right
            scalar = right if matrix is left else left
            if not isinstance(scalar.type, _NUMERIC_IR_TYPES):
                return None
            scalar = self._coerce_scalar_for_scale(
                scalar,
                matrix.type.element,
                "matrix scalar multiplication requires matching scalar and element types",
                context,
            )
            dimensions = context.matrix_dimensions.get(matrix.name)
            if dimensions is None:
                self._fail(
                    "IR backend requires known matrix dimensions for scalar * Matrix.",
                    expression,
                )
            result = context.temporary(matrix.type)
            context.matrix_dimensions[result.name] = dimensions
            context.block.instructions.append(
                IRMatrixScale(result, matrix, scalar, dimensions[0], dimensions[1])
            )
            return result

        return None

    def _coerce_scalar_for_scale(
        self,
        scalar: IRValue,
        element_type: IRType,
        operation: str,
        context: _FunctionContext,
    ) -> IRValue:
        if scalar.type == element_type:
            return scalar
        if isinstance(scalar.type, IntType) and isinstance(element_type, DoubleType):
            result = context.temporary(element_type)
            context.block.instructions.append(IRCast(result, scalar))
            return result
        self._require_same_type(scalar.type, element_type, operation)
        return scalar

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
        if isinstance(type_name, AetherArrayType):
            return ArrayType(self._lower_type(type_name.element_type))
        if isinstance(type_name, AetherListType):
            return ListType(self._lower_type(type_name.element_type))
        if isinstance(type_name, AetherVectorType):
            return VectorType(self._lower_type(type_name.element_type), type_name.orientation)
        if isinstance(type_name, AetherMatrixType):
            return MatrixType(self._lower_type(type_name.element_type))
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
            if isinstance(statement, ast.Assignment) and isinstance(statement.name, str):
                names.add(statement.name)
            elif isinstance(statement, ast.IfStatement):
                names.update(self._assigned_names(statement.body))
                if statement.else_body is not None:
                    names.update(self._assigned_names(statement.else_body))
            elif isinstance(statement, ast.WhileStatement):
                names.update(self._assigned_names(statement.body))
            elif isinstance(statement, ast.ForInStatement):
                names.update(self._assigned_names(statement.body))
        return names

    def _constant_int(self, expression: ast.Expression) -> int | None:
        if isinstance(expression, ast.Literal) and expression.type_name == "int":
            return expression.value if isinstance(expression.value, int) else None
        if isinstance(expression, ast.UnaryExpression) and expression.operator == "-":
            operand = self._constant_int(expression.operand)
            return -operand if operand is not None else None
        return None

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
