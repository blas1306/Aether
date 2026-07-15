from __future__ import annotations

from aether.ir.model import (
    IRAssign,
    IRArrayCopy,
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySlice,
    IRArraySet,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCallIndirect,
    IRCompareOp,
    IRConst,
    IRCopyInit,
    IRDestroy,
    IRFunction,
    IRFunctionRef,
    IRInstruction,
    IRInitDefault,
    IRJump,
    IRListGet,
    IRListCopy,
    IRListContains,
    IRListClear,
    IRListPop,
    IRListPush,
    IRListInsert,
    IRListRemoveAt,
    IRListIndexOf,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListSet,
    IRListReverse,
    IRSequenceSort,
    IRLoad,
    IRMatrixColumns,
    IRMatrixAdd,
    IRMatrixMatMul,
    IRMatrixVectorMul,
    IRMatrixScale,
    IRMatrixSub,
    IRMatrixGet,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixSet,
    IRModule,
    IROuterProduct,
    IRPrint,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRReturn,
    IRRelocate,
    IRMoveInit,
    IRStorage,
    IRStore,
    IRUnaryOp,
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

from .result import OptimizationResult


class DeadCodeEliminator:
    """Remove pure IR instructions whose result is not used."""

    def run(self, module: IRModule) -> OptimizationResult:
        removed = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized_function, function_removed = self._eliminate_function(function)
            functions.append(optimized_function)
            removed += function_removed
        optimized = IRModule(functions, list(module.structs))
        return OptimizationResult(
            optimized,
            changed=optimized != module,
            stats={"removed": removed},
        )

    def _eliminate_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        producers = self._collect_pure_producers(function)
        live_values = self._initial_live_values(function)
        worklist = list(live_values)

        while worklist:
            value_name = worklist.pop()
            producer = producers.get(value_name)
            if producer is None:
                continue

            for operand in self._operands(producer):
                if operand.name not in live_values:
                    live_values.add(operand.name)
                    worklist.append(operand.name)

        removed = 0
        blocks: list[IRBasicBlock] = []
        for block in function.blocks:
            instructions: list[IRInstruction] = []
            for instruction in block.instructions:
                if (
                    self._is_removable(instruction)
                    and self._result(instruction).name not in live_values
                ):
                    removed += 1
                    continue
                instructions.append(instruction)
            blocks.append(IRBasicBlock(block.name, instructions))

        return (
            IRFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
            ),
            removed,
        )

    def _collect_pure_producers(
        self,
        function: IRFunction,
    ) -> dict[str, IRInstruction]:
        producers: dict[str, IRInstruction] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if self._is_removable(instruction):
                    producers[self._result(instruction).name] = instruction
        return producers

    def _initial_live_values(self, function: IRFunction) -> set[str]:
        live_values: set[str] = set()
        for block in function.blocks:
            for instruction in block.instructions:
                if self._is_removable(instruction):
                    continue
                live_values.update(
                    operand.name for operand in self._operands(instruction)
                )
        return live_values

    @classmethod
    def _is_removable(cls, instruction: IRInstruction) -> bool:
        return getattr(instruction, "result", None) is not None and not instruction.must_preserve

    @staticmethod
    def _result(instruction: IRInstruction) -> IRValue:
        result = getattr(instruction, "result", None)
        if isinstance(result, IRValue):
            return result
        raise TypeError(
            f"Instruction has no removable result: {type(instruction).__name__}"
        )

    @staticmethod
    def _operands(instruction: IRInstruction) -> tuple[IRValue, ...]:
        if isinstance(instruction, IRConst):
            return ()
        if isinstance(instruction, IRLoad):
            return ()
        if isinstance(instruction, IRStore):
            return (instruction.value,)
        if isinstance(instruction, IRInitDefault):
            return ()
        if isinstance(instruction, (IRCopyInit, IRAssign)):
            return () if isinstance(instruction.source, IRStorage) else (instruction.source,)
        if isinstance(instruction, (IRMoveInit, IRDestroy, IRRelocate)):
            return ()
        if isinstance(instruction, (IRBinaryOp, IRCompareOp)):
            return (instruction.left, instruction.right)
        if isinstance(instruction, IRUnaryOp):
            return (instruction.operand,)
        if isinstance(instruction, IRCast):
            return (instruction.value,)
        if isinstance(instruction, IRCall):
            return instruction.arguments
        if isinstance(instruction, IRFunctionRef):
            return ()
        if isinstance(instruction, IRCallIndirect):
            return (instruction.callee, *instruction.arguments)
        if isinstance(instruction, IRPrint):
            return (instruction.value,)
        if isinstance(instruction, IRStructNew):
            return instruction.fields
        if isinstance(instruction, IRStructGet):
            return (instruction.struct,)
        if isinstance(instruction, IRStructSet):
            return (instruction.struct, instruction.value)
        if isinstance(instruction, IRMethodResultNew):
            return (instruction.receiver,) if instruction.value is None else (instruction.receiver, instruction.value)
        if isinstance(instruction, (IRMethodResultReceiver, IRMethodResultValue)):
            return (instruction.method_result,)
        if isinstance(instruction, IRArrayNew):
            return instruction.elements
        if isinstance(instruction, IRListNew):
            return instruction.elements
        if isinstance(instruction, IRArrayCopy):
            return (instruction.array,)
        if isinstance(instruction, IRListCopy):
            return (instruction.list_value,)
        if isinstance(instruction, IRListContains):
            return (instruction.list_value, instruction.value)
        if isinstance(instruction, IRListIndexOf):
            return (instruction.list_value, instruction.value)
        if isinstance(instruction, IRListClear):
            return (instruction.list_value,)
        if isinstance(instruction, IRListPush):
            return (instruction.list_value, instruction.value)
        if isinstance(instruction, IRListInsert):
            return (instruction.list_value, instruction.index, instruction.value)
        if isinstance(instruction, IRListPop):
            return (instruction.list_value,)
        if isinstance(instruction, IRListRemoveAt):
            return (instruction.list_value, instruction.index)
        if isinstance(instruction, IRListReverse):
            return (instruction.list_value,)
        if isinstance(instruction, IRSequenceSort):
            return (instruction.sequence,)
        if isinstance(instruction, IRVectorNew):
            return instruction.elements
        if isinstance(instruction, IRMatrixNew):
            return instruction.elements
        if isinstance(instruction, (IRVectorAdd, IRVectorDot, IRMatrixAdd, IRMatrixMatMul, IRVectorSub, IRMatrixSub)):
            return (instruction.left, instruction.right)
        if isinstance(instruction, IROuterProduct):
            return (instruction.column, instruction.row)
        if isinstance(instruction, IRMatrixVectorMul):
            return (instruction.matrix, instruction.vector)
        if isinstance(instruction, IRVectorMatrixMul):
            return (instruction.vector, instruction.matrix)
        if isinstance(instruction, IRVectorScale):
            return (instruction.vector, instruction.scalar)
        if isinstance(instruction, IRMatrixScale):
            return (instruction.matrix, instruction.scalar)
        if isinstance(instruction, IRArrayGet):
            return (instruction.array, instruction.index)
        if isinstance(instruction, IRArraySlice):
            return (instruction.array, instruction.start, instruction.end)
        if isinstance(instruction, IRListGet):
            return (instruction.list_value, instruction.index)
        if isinstance(instruction, IRVectorGet):
            return (instruction.vector, instruction.index)
        if isinstance(instruction, IRMatrixGet):
            return (instruction.matrix, instruction.row, instruction.column)
        if isinstance(instruction, IRArraySet):
            return (instruction.array, instruction.index, instruction.value)
        if isinstance(instruction, IRListSet):
            return (instruction.list_value, instruction.index, instruction.value)
        if isinstance(instruction, IRVectorSet):
            return (instruction.vector, instruction.index, instruction.value)
        if isinstance(instruction, IRMatrixSet):
            return (instruction.matrix, instruction.row, instruction.column, instruction.value)
        if isinstance(instruction, IRArrayLength):
            return (instruction.array,)
        if isinstance(instruction, (IRListLength, IRListIsEmpty)):
            return (instruction.list_value,)
        if isinstance(instruction, IRVectorLength):
            return (instruction.vector,)
        if isinstance(instruction, (IRMatrixRows, IRMatrixColumns)):
            return (instruction.matrix,)
        if isinstance(instruction, IRBranch):
            return (instruction.condition,)
        if isinstance(instruction, IRJump):
            return ()
        if isinstance(instruction, IRReturn):
            return () if instruction.value is None else (instruction.value,)
        raise TypeError(
            f"Unsupported IR instruction: {type(instruction).__name__}"
        )
