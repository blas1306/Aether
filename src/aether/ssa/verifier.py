from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import NoReturn

from aether.analysis.cfg import CFG, CFGEdge, CFGNode
from aether.analysis.dominators import DominatorAnalysis, DominatorResult
from aether.ir.types import (
    ArrayType,
    BoolType,
    ClassRefType,
    ComplexType,
    DoubleType,
    EnumType,
    FloatType,
    FunctionType,
    IntType,
    InterfaceType,
    IRType,
    ListType,
    MatrixType,
    MethodResultType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)
from aether.ir.scalar_math import scalar_math_result_type
from aether.ir.model import IREnumConstant
from aether.ir.equality import ir_eq_capability
from aether.string_parsing import (
    DOUBLE_PARSE_RESULT_TYPE,
    INT_PARSE_RESULT_TYPE,
    PARSE_DOUBLE_BUILTIN,
    PARSE_INT_BUILTIN,
)
from aether.string_value import STRING_SPLIT_BUILTIN, STRING_TRIM_BUILTIN
from aether.process_arguments import PROCESS_ARGS_BUILTIN
from aether.text_file_io import (
    FILE_READ_RESULT_TYPE,
    FILE_STATUS_TYPE,
    READ_TEXT_BUILTIN,
    TEXT_FILE_BUILTINS,
)

from .model import (
    SSAArrayCopy,
    SSAArrayGet,
    SSAArrayLength,
    SSAArrayNew,
    SSAArraySlice,
    SSAArraySet,
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACast,
    SSACall,
    SSACallIndirect,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAFunctionRef,
    SSAInstruction,
    SSAJump,
    SSAListGet,
    SSAListCopy,
    SSAListSlice,
    SSAListContains,
    SSAListClear,
    SSAListPop,
    SSAListPush,
    SSAListInsert,
    SSAListRemoveAt,
    SSAListIndexOf,
    SSAListIsEmpty,
    SSAListLength,
    SSAListNew,
    SSAListSet,
    SSAListReverse,
    SSASequenceSort,
    SSAMatrixColumns,
    SSAMatrixAdd,
    SSAMatrixMatMul,
    SSAMatrixVectorMul,
    SSAMatrixScale,
    SSAMatrixSub,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAMatrixRows,
    SSAMatrixSet,
    SSAModule,
    SSAOuterProduct,
    SSAPrint,
    SSAStructGet,
    SSAStructNew,
    SSAStructSet,
    SSAMethodResultNew,
    SSAMethodResultReceiver,
    SSAMethodResultValue,
    SSAPhi,
    SSAReturn,
    SSAUnaryOp,
    SSAValue,
    SSAVectorGet,
    SSAVectorAdd,
    SSAVectorDot,
    SSAVectorMatrixMul,
    SSAVectorScale,
    SSAVectorSub,
    SSAVectorLength,
    SSAVectorNew,
    SSAVectorSet,
)


class SSAVerificationError(ValueError):
    """Raised when an SSA module is internally inconsistent."""


@dataclass(frozen=True)
class _DefinitionSite:
    block_name: str | None
    instruction_index: int | None

    @property
    def is_parameter(self) -> bool:
        return self.block_name is None


class SSAVerifier:
    """Validate hand-built Aether SSA modules."""

    _TERMINATORS = (SSABranch, SSAJump, SSAReturn)
    _NUMERIC_TYPES = (IntType, FloatType, DoubleType, ComplexType)
    _REAL_TYPES = (IntType, FloatType, DoubleType)

    def __init__(self, module: SSAModule) -> None:
        self.module = module
        self._functions: dict[str, SSAFunction] = {}
        self._structs = {}

    def verify(self) -> SSAModule:
        """Verify the module and return it unchanged on success."""
        self._functions = {}
        self._structs = {definition.name: definition for definition in self.module.structs}
        self._verify_module()
        return self.module

    def _verify_module(self) -> None:
        self._verify_struct_definitions()
        seen: set[str] = set()
        for function in self.module.functions:
            if function.name in seen:
                self._fail(f"Duplicate function '{function.name}'")
            seen.add(function.name)
            self._functions[function.name] = function

        for function in self.module.functions:
            self._verify_function(function)

    def _verify_struct_definitions(self) -> None:
        if len(self._structs) != len(self.module.structs):
            self._fail("Duplicate nominal struct definition")
        edges: dict[str, tuple[str, ...]] = {}
        for definition in self.module.structs:
            if not definition.name:
                self._fail("Struct definition name must not be empty")
            field_names = [name for name, _type in definition.fields]
            if len(field_names) != len(set(field_names)):
                self._fail(f"Struct '{definition.name}' has duplicate fields")
            for field_name, field_type in definition.fields:
                if isinstance(field_type, VoidType) or not self._is_valid_type(field_type):
                    self._fail(
                        f"Struct '{definition.name}' field '{field_name}' has invalid or incomplete type {field_type}"
                    )
            edges[definition.name] = tuple(
                field_type.name
                for _field_name, field_type in definition.fields
                if isinstance(field_type, StructType)
            )

        visited: set[str] = set()
        active: list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in active:
                cycle = " -> ".join((*active[active.index(name):], name))
                self._fail(f"Recursive by-value struct layout has infinite size: {cycle}")
            active.append(name)
            for target in edges.get(name, ()):
                visit(target)
            active.pop()
            visited.add(name)

        for name in edges:
            visit(name)

    def _verify_function(self, function: SSAFunction) -> None:
        self._verify_type(function.return_type, f"return type of function '{function.name}'")
        self._verify_parameters(function)

        if not function.blocks:
            self._fail(f"Function '{function.name}' has no blocks")

        blocks = self._collect_blocks(function)
        if function.entry_block not in blocks:
            self._fail(
                f"Function '{function.name}' has no entry block "
                f"'{function.entry_block}'"
            )

        self._verify_block_structure(function, blocks)
        predecessors = self._predecessors(blocks)
        value_types, definition_sites = self._collect_definitions(function)
        self._verify_borrowed_elements(function)

        for block in function.blocks:
            self._verify_phi_placement(function, block)
            self._verify_instructions(function, block, blocks, predecessors, value_types)

        dominators = DominatorAnalysis(
            self._cfg(function),
            entry_block=function.entry_block,
        ).compute()
        self._verify_dominance(function, predecessors, definition_sites, dominators)

    def _verify_borrowed_elements(self, function: SSAFunction) -> None:
        borrowed: dict[str, str] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if not isinstance(instruction, (SSAArrayGet, SSAListGet)):
                    continue
                if instruction.borrowed:
                    if not instruction.borrow_scope:
                        self._fail("borrow_element requires an iteration scope")
                    if instruction.borrow_scope != block.name:
                        self._fail(
                            f"borrow_element '%{instruction.result.name}' is defined "
                            f"outside its declared scope '{instruction.borrow_scope}'"
                        )
                    borrowed[instruction.result.name] = instruction.borrow_scope
                elif instruction.borrow_scope is not None:
                    self._fail("owned collection get cannot declare a borrow scope")

        if not borrowed:
            return
        acquired = {
            argument.name
            for block in function.blocks
            for instruction in block.instructions
            if isinstance(instruction, SSACall)
            and instruction.builtin == "__aether_retain"
            for argument in instruction.arguments
            if argument.name in borrowed
        }
        receiver_fields = {
            SSAArraySet: "array",
            SSAListSet: "list_value",
            SSAListPush: "list_value",
            SSAListInsert: "list_value",
            SSAListRemoveAt: "list_value",
            SSAListPop: "list_value",
            SSAListClear: "list_value",
            SSAListReverse: "list_value",
            SSASequenceSort: "sequence",
            SSAStructSet: "struct",
        }
        for block in function.blocks:
            for instruction in block.instructions:
                if (
                    isinstance(instruction, SSAReturn)
                    and instruction.value is not None
                    and instruction.value.name in borrowed
                    and isinstance(
                        instruction.value.type,
                        (ArrayType, ListType, StringType),
                    )
                    and instruction.value.name not in acquired
                ):
                    self._fail(
                        "Borrowed iteration value cannot escape its iteration scope without copying"
                    )
                if isinstance(instruction, SSAPhi):
                    if any(
                        value.name in borrowed and value.name not in acquired
                        for _predecessor, value in instruction.incoming
                    ):
                        self._fail("Borrowed iteration value cannot flow through phi")
                for instruction_type, field_name in receiver_fields.items():
                    if isinstance(instruction, instruction_type):
                        receiver = getattr(instruction, field_name)
                        if receiver.name in borrowed and receiver.name not in acquired:
                            self._fail("Cannot mutate through borrowed iteration element")
                        break

    def _verify_parameters(self, function: SSAFunction) -> None:
        seen: set[str] = set()
        for parameter in function.parameters:
            if parameter.name in seen:
                self._fail(
                    f"Duplicate parameter '{parameter.name}' in function '{function.name}'"
                )
            seen.add(parameter.name)
            self._verify_type(
                parameter.type,
                f"parameter '{parameter.name}' of function '{function.name}'",
            )

    def _collect_blocks(self, function: SSAFunction) -> dict[str, SSABasicBlock]:
        blocks: dict[str, SSABasicBlock] = {}
        for block in function.blocks:
            if not block.name:
                self._fail(f"Function '{function.name}' has a block with no name")
            if block.name in blocks:
                self._fail(f"Duplicate block '{block.name}' in function '{function.name}'")
            blocks[block.name] = block
        return blocks

    def _verify_block_structure(
        self,
        function: SSAFunction,
        blocks: dict[str, SSABasicBlock],
    ) -> None:
        for block in function.blocks:
            if not block.instructions:
                self._fail(
                    f"Block '{block.name}' in function '{function.name}' has no terminator"
                )

            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, self._TERMINATORS):
                    if index != len(block.instructions) - 1:
                        self._fail(f"Instruction after terminator in block '{block.name}'")
                    self._verify_terminator_targets(function, instruction, blocks)
                    break
            else:
                self._fail(
                    f"Block '{block.name}' in function '{function.name}' has no terminator"
                )

    def _verify_terminator_targets(
        self,
        function: SSAFunction,
        instruction: SSAInstruction,
        blocks: dict[str, SSABasicBlock],
    ) -> None:
        if isinstance(instruction, SSAJump):
            if instruction.target not in blocks:
                self._fail(
                    f"Unknown jump target '{instruction.target}' in function '{function.name}'"
                )
            return

        if isinstance(instruction, SSABranch):
            if instruction.true_target == instruction.false_target:
                self._fail(
                    f"Branch in function '{function.name}' has duplicate target "
                    f"'{instruction.true_target}'"
                )
            for target in (instruction.true_target, instruction.false_target):
                if target not in blocks:
                    self._fail(
                        f"Unknown branch target '{target}' in function '{function.name}'"
                    )

    def _predecessors(
        self,
        blocks: dict[str, SSABasicBlock],
    ) -> dict[str, set[str]]:
        predecessors: dict[str, set[str]] = {name: set() for name in blocks}
        for block in blocks.values():
            for successor in self._successors(block):
                predecessors[successor].add(block.name)
        return predecessors

    def _collect_definitions(
        self,
        function: SSAFunction,
    ) -> tuple[dict[str, IRType], dict[str, _DefinitionSite]]:
        value_types: dict[str, IRType] = {}
        definition_sites: dict[str, _DefinitionSite] = {}
        for parameter in function.parameters:
            self._define_value_type(value_types, parameter, function)
            definition_sites[parameter.name] = _DefinitionSite(None, None)

        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                result = self._instruction_result(instruction)
                if result is None:
                    continue
                self._verify_type(result.type, f"value '{self._value(result)}'")
                self._define_value_type(value_types, result, function)
                definition_sites[result.name] = _DefinitionSite(block.name, index)

        return value_types, definition_sites

    def _define_value_type(
        self,
        value_types: dict[str, IRType],
        value: SSAValue,
        function: SSAFunction,
    ) -> None:
        existing = value_types.get(value.name)
        if existing is not None:
            self._fail(f"Duplicate value '{self._value(value)}' in function '{function.name}'")
        value_types[value.name] = value.type

    def _verify_phi_placement(self, function: SSAFunction, block: SSABasicBlock) -> None:
        seen_non_phi = False
        for instruction in block.instructions:
            if isinstance(instruction, self._TERMINATORS):
                return
            if isinstance(instruction, SSAPhi):
                if seen_non_phi:
                    self._fail(
                        f"Phi instruction after non-phi instruction in block '{block.name}'"
                    )
                continue
            seen_non_phi = True

    def _verify_instructions(
        self,
        function: SSAFunction,
        block: SSABasicBlock,
        blocks: dict[str, SSABasicBlock],
        predecessors: dict[str, set[str]],
        value_types: dict[str, IRType],
    ) -> None:
        for instruction in block.instructions:
            if isinstance(instruction, SSAConst):
                self._verify_const(instruction)
                continue

            if isinstance(instruction, SSABinaryOp):
                self._require_defined(instruction.left, value_types)
                self._require_defined(instruction.right, value_types)
                result_type = self._binary_result_type(instruction)
                self._require_type(
                    instruction.result.type,
                    result_type,
                    f"Binary op '{instruction.operator}' result type mismatch",
                )
                continue

            if isinstance(instruction, SSAUnaryOp):
                self._require_defined(instruction.operand, value_types)
                self._verify_unary(instruction)
                continue

            if isinstance(instruction, SSACompareOp):
                self._require_defined(instruction.left, value_types)
                self._require_defined(instruction.right, value_types)
                self._verify_compare(instruction)
                continue

            if isinstance(instruction, SSACast):
                self._require_defined(instruction.value, value_types)
                self._verify_cast(instruction)
                continue

            if isinstance(instruction, SSACall):
                self._verify_call(instruction, value_types)
                continue

            if isinstance(instruction, SSAFunctionRef):
                callee = self._functions.get(instruction.function)
                if callee is None:
                    self._fail(f"Reference to undefined function '{instruction.function}'")
                expected = FunctionType(
                    tuple(parameter.type for parameter in callee.parameters),
                    callee.return_type,
                )
                self._require_type(
                    instruction.result.type,
                    expected,
                    f"Function reference '{instruction.function}' type mismatch",
                )
                continue

            if isinstance(instruction, SSACallIndirect):
                self._verify_indirect_call(instruction, value_types)
                continue

            if isinstance(instruction, SSAPrint):
                self._require_defined(instruction.value, value_types)
                if not isinstance(
                    instruction.value.type,
                    (
                        IntType,
                        BoolType,
                        StringType,
                        DoubleType,
                        EnumType,
                        ArrayType,
                        ListType,
                        VectorType,
                        MatrixType,
                        StructType,
                    ),
                ):
                    self._fail(
                        "Print value must be a printable scalar or aggregate, "
                        f"got {instruction.value.type}"
                    )
                if isinstance(instruction.value.type, VectorType):
                    if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 1:
                        self._fail("Vector print requires one known length")
                elif isinstance(instruction.value.type, MatrixType):
                    if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 2:
                        self._fail("Matrix print requires known rows and columns")
                elif instruction.aggregate_shape is not None:
                    self._fail("Scalar print must not carry an aggregate shape")
                continue

            if isinstance(instruction, SSAStructNew):
                definition = self._structs.get(instruction.result.type.name) if isinstance(instruction.result.type, StructType) else None
                if definition is None or len(instruction.fields) != len(definition.fields):
                    self._fail("Struct new requires a declared struct and all canonical fields")
                for value, (_name, field_type) in zip(instruction.fields, definition.fields):
                    self._require_defined(value, value_types)
                    self._require_type(value.type, field_type, "Struct field type mismatch")
                continue

            if isinstance(instruction, SSAStructGet):
                self._require_defined(instruction.struct, value_types)
                definition = self._structs.get(instruction.struct.type.name) if isinstance(instruction.struct.type, StructType) else None
                if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                    self._fail("Struct get requires a valid canonical field")
                self._require_type(instruction.result.type, definition.fields[instruction.field_index][1], "Struct get result type mismatch")
                continue

            if isinstance(instruction, SSAStructSet):
                self._require_defined(instruction.struct, value_types)
                self._require_defined(instruction.value, value_types)
                definition = self._structs.get(instruction.struct.type.name) if isinstance(instruction.struct.type, StructType) else None
                if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                    self._fail("Struct set requires a valid canonical field")
                self._require_type(instruction.value.type, definition.fields[instruction.field_index][1], "Struct set value type mismatch")
                self._require_type(instruction.result.type, instruction.struct.type, "Struct set result type mismatch")
                continue

            if isinstance(instruction, SSAMethodResultNew):
                self._require_defined(instruction.receiver, value_types)
                if not isinstance(instruction.result.type, MethodResultType):
                    self._fail("Method result requires MethodResultType")
                self._require_type(instruction.receiver.type, instruction.result.type.receiver, "Method receiver type mismatch")
                if isinstance(instruction.result.type.value, VoidType):
                    if instruction.value is not None:
                        self._fail("Void method result cannot contain a value")
                else:
                    if instruction.value is None:
                        self._fail("Non-void method result requires a value")
                    self._require_defined(instruction.value, value_types)
                    self._require_type(instruction.value.type, instruction.result.type.value, "Method value mismatch")
                continue

            if isinstance(instruction, SSAMethodResultReceiver):
                self._require_defined(instruction.method_result, value_types)
                if not isinstance(instruction.method_result.type, MethodResultType):
                    self._fail("Method receiver extraction requires MethodResultType")
                self._require_type(instruction.result.type, instruction.method_result.type.receiver, "Method receiver result mismatch")
                continue

            if isinstance(instruction, SSAMethodResultValue):
                self._require_defined(instruction.method_result, value_types)
                if not isinstance(instruction.method_result.type, MethodResultType):
                    self._fail("Method value extraction requires MethodResultType")
                self._require_type(instruction.result.type, instruction.method_result.type.value, "Method value result mismatch")
                continue

            if isinstance(instruction, SSAArrayNew):
                self._verify_array_new(instruction, value_types)
                continue

            if isinstance(instruction, SSAListNew):
                self._verify_list_new(instruction, value_types)
                continue

            if isinstance(instruction, SSAArrayCopy):
                self._verify_array_copy(instruction, value_types)
                continue

            if isinstance(instruction, SSAListCopy):
                self._verify_list_copy(instruction, value_types)
                continue

            if isinstance(instruction, SSAListContains):
                self._verify_list_contains(instruction, value_types)
                continue

            if isinstance(instruction, SSAListIndexOf):
                self._verify_list_index_of(instruction, value_types)
                continue

            if isinstance(instruction, SSAListClear):
                self._verify_list_clear(instruction, value_types)
                continue

            if isinstance(instruction, SSAListPush):
                self._verify_list_push(instruction, value_types)
                continue

            if isinstance(instruction, SSAListInsert):
                self._verify_list_insert(instruction, value_types)
                continue

            if isinstance(instruction, SSAListPop):
                self._verify_list_pop(instruction, value_types)
                continue

            if isinstance(instruction, SSAListRemoveAt):
                self._verify_list_remove_at(instruction, value_types)
                continue

            if isinstance(instruction, SSAListReverse):
                self._verify_list_reverse(instruction, value_types)
                continue
            if isinstance(instruction, SSASequenceSort):
                self._verify_sequence_sort(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorNew):
                self._verify_vector_new(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixNew):
                self._verify_matrix_new(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorAdd):
                self._verify_vector_add(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorSub):
                self._verify_vector_sub(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorScale):
                self._verify_vector_scale(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorDot):
                self._verify_vector_dot(instruction, value_types)
                continue

            if isinstance(instruction, SSAOuterProduct):
                self._verify_outer_product(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixAdd):
                self._verify_matrix_add(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixSub):
                self._verify_matrix_sub(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixScale):
                self._verify_matrix_scale(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixMatMul):
                self._verify_matrix_matmul(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixVectorMul):
                self._verify_matrix_vector_mul(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorMatrixMul):
                self._verify_vector_matrix_mul(instruction, value_types)
                continue

            if isinstance(instruction, SSAArrayGet):
                self._verify_array_get(instruction, value_types)
                continue

            if isinstance(instruction, SSAArraySlice):
                self._verify_array_slice(instruction, value_types)
                continue

            if isinstance(instruction, SSAListSlice):
                self._verify_list_slice(instruction, value_types)
                continue

            if isinstance(instruction, SSAListGet):
                self._verify_list_get(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorGet):
                self._verify_vector_get(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixGet):
                self._verify_matrix_get(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorLength):
                self._verify_vector_length(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixRows):
                self._verify_matrix_rows(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixColumns):
                self._verify_matrix_columns(instruction, value_types)
                continue

            if isinstance(instruction, SSAArraySet):
                self._verify_array_set(instruction, value_types)
                continue

            if isinstance(instruction, SSAListSet):
                self._verify_list_set(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorSet):
                self._verify_vector_set(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixSet):
                self._verify_matrix_set(instruction, value_types)
                continue

            if isinstance(instruction, SSAArrayLength):
                self._verify_array_length(instruction, value_types)
                continue

            if isinstance(instruction, SSAListLength):
                self._verify_list_length(instruction, value_types)
                continue

            if isinstance(instruction, SSAListIsEmpty):
                self._verify_list_is_empty(instruction, value_types)
                continue

            if isinstance(instruction, SSAPhi):
                self._verify_phi(
                    function,
                    instruction,
                    block,
                    blocks,
                    predecessors,
                    value_types,
                )
                continue

            if isinstance(instruction, SSABranch):
                self._require_defined(instruction.condition, value_types)
                if not isinstance(instruction.condition.type, BoolType):
                    self._fail("Branch condition must be bool")
                continue

            if isinstance(instruction, SSAJump):
                continue

            if isinstance(instruction, SSAReturn):
                self._verify_return(function, instruction, value_types)
                continue

            self._fail(f"Unsupported SSA instruction '{type(instruction).__name__}'")

    def _verify_compare(self, instruction: SSACompareOp) -> None:
        result_type = self._compare_operand_result_type(instruction)
        self._require_type(
            instruction.result.type,
            BoolType(),
            f"Compare op '{instruction.operator}' result type mismatch",
        )
        self._require_type(
            instruction.result.type,
            result_type,
            f"Compare op '{instruction.operator}' result type mismatch",
        )

    def _verify_call(
        self,
        instruction: SSACall,
        value_types: dict[str, IRType],
    ) -> None:
        if instruction.builtin is not None:
            for argument in instruction.arguments:
                self._require_defined(argument, value_types)
            if instruction.builtin == PROCESS_ARGS_BUILTIN:
                if instruction.function != PROCESS_ARGS_BUILTIN:
                    self._fail("Process-arguments builtin must retain its canonical semantic name")
                if (
                    instruction.result is None
                    or instruction.arguments
                    or instruction.result.type != ArrayType(StringType())
                ):
                    self._fail("System.args builtin requires () -> owned array<string>")
                return
            if instruction.builtin == "__aether_string_byte_length":
                if instruction.function != instruction.builtin:
                    self._fail("String byte-length builtin must retain its canonical semantic name")
                if (
                    instruction.result is None
                    or len(instruction.arguments) != 1
                    or not isinstance(instruction.arguments[0].type, StringType)
                    or not isinstance(instruction.result.type, IntType)
                ):
                    self._fail("String byte-length builtin requires string -> int")
                return
            if instruction.builtin == STRING_TRIM_BUILTIN:
                if instruction.function != STRING_TRIM_BUILTIN:
                    self._fail("String trim builtin must retain its canonical semantic name")
                if (
                    instruction.result is None
                    or len(instruction.arguments) != 1
                    or not isinstance(instruction.arguments[0].type, StringType)
                    or not isinstance(instruction.result.type, StringType)
                ):
                    self._fail("String trim builtin requires string -> owned string")
                return
            if instruction.builtin == STRING_SPLIT_BUILTIN:
                if instruction.function != STRING_SPLIT_BUILTIN:
                    self._fail("String split builtin must retain its canonical semantic name")
                if (
                    instruction.result is None
                    or len(instruction.arguments) != 2
                    or any(not isinstance(argument.type, StringType) for argument in instruction.arguments)
                    or instruction.result.type != ArrayType(StringType())
                ):
                    self._fail("String split builtin requires (string, string) -> owned array<string>")
                return
            if instruction.builtin in {PARSE_INT_BUILTIN, PARSE_DOUBLE_BUILTIN}:
                expected_name = (
                    INT_PARSE_RESULT_TYPE
                    if instruction.builtin == PARSE_INT_BUILTIN
                    else DOUBLE_PARSE_RESULT_TYPE
                )
                if instruction.function != instruction.builtin:
                    self._fail("String parsing builtin must retain its canonical semantic name")
                if (
                    instruction.result is None
                    or len(instruction.arguments) != 1
                    or not isinstance(instruction.arguments[0].type, StringType)
                    or instruction.result.type != StructType(expected_name)
                ):
                    self._fail(
                        f"String parsing builtin '{instruction.builtin}' requires "
                        f"string -> struct {expected_name}"
                    )
                return
            if instruction.builtin in TEXT_FILE_BUILTINS:
                if instruction.function != instruction.builtin:
                    self._fail("Text-file builtin must retain its canonical semantic name")
                expected_arity = 1 if instruction.builtin == READ_TEXT_BUILTIN else 2
                if (
                    instruction.result is None
                    or len(instruction.arguments) != expected_arity
                    or any(not isinstance(argument.type, StringType) for argument in instruction.arguments)
                ):
                    self._fail(
                        f"Text-file builtin '{instruction.builtin}' requires "
                        f"{expected_arity} string argument(s) and a result"
                    )
                if instruction.builtin == READ_TEXT_BUILTIN:
                    if instruction.result.type != StructType(FILE_READ_RESULT_TYPE):
                        self._fail("io.readText result must be FileReadResult")
                    definition = self._structs.get(FILE_READ_RESULT_TYPE)
                    if (
                        definition is None
                        or len(definition.fields) != 2
                        or definition.fields[0] != ("content", StringType())
                        or definition.fields[1][0] != "status"
                        or not isinstance(definition.fields[1][1], EnumType)
                        or definition.fields[1][1].name != FILE_STATUS_TYPE
                    ):
                        self._fail("FileReadResult requires canonical {string, FileStatus} layout")
                elif (
                    not isinstance(instruction.result.type, EnumType)
                    or instruction.result.type.name != FILE_STATUS_TYPE
                ):
                    self._fail("Text-file write result must be FileStatus")
                return
            if instruction.builtin in {"__aether_retain", "__aether_release"}:
                if instruction.function != instruction.builtin:
                    self._fail("Lifecycle builtin call must retain its canonical semantic name")
                if instruction.result is not None or len(instruction.arguments) != 1:
                    self._fail("Lifecycle builtin requires one argument and no result")
                argument_type = instruction.arguments[0].type
                if not isinstance(
                    argument_type,
                    (StringType, StructType, MethodResultType, ArrayType, ListType),
                ):
                    self._fail(
                        f"Lifecycle builtin does not support argument type {argument_type}"
                    )
                return
            if instruction.result is None:
                self._fail(f"Scalar builtin '{instruction.builtin}' must produce a result")
            try:
                expected_type = scalar_math_result_type(
                    instruction.builtin,
                    tuple(argument.type for argument in instruction.arguments),
                )
            except ValueError as exc:
                self._fail(str(exc))
            if instruction.function != instruction.builtin:
                self._fail("Scalar builtin call must retain its canonical semantic name")
            if instruction.result.type != expected_type:
                self._fail(
                    f"Scalar builtin '{instruction.builtin}' result type mismatch: "
                    f"expected {expected_type}, got {instruction.result.type}"
                )
            return
        callee = self._functions.get(instruction.function)
        if callee is None:
            self._fail(f"Call to undefined function '{instruction.function}'")

        expected = len(callee.parameters)
        actual = len(instruction.arguments)
        if actual != expected:
            self._fail(
                f"Function '{instruction.function}' expects {expected} arguments, got {actual}"
            )

        for index, (argument, parameter) in enumerate(
            zip(instruction.arguments, callee.parameters),
            start=1,
        ):
            self._require_defined(argument, value_types)
            if argument.type != parameter.type:
                self._fail(
                    f"Argument {index} to function '{instruction.function}' type mismatch: "
                    f"expected {parameter.type}, got {argument.type}"
                )

        if isinstance(callee.return_type, VoidType):
            if instruction.result is not None:
                self._fail(
                    f"Call to void function '{instruction.function}' cannot produce a value"
                )
            return

        if instruction.result is None:
            self._fail(
                f"Call to function '{instruction.function}' must produce a result "
                f"of type {callee.return_type}"
            )

        if instruction.result.type != callee.return_type:
            self._fail(
                f"Call result type mismatch: expected {callee.return_type}, "
                f"got {instruction.result.type}"
            )

    def _verify_indirect_call(
        self,
        instruction: SSACallIndirect,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.callee, value_types)
        if not isinstance(instruction.callee.type, FunctionType):
            self._fail(f"Indirect call requires callable callee, got {instruction.callee.type}")
        signature = instruction.callee.type
        if len(instruction.arguments) != len(signature.parameter_types):
            self._fail(
                f"Indirect call expects {len(signature.parameter_types)} arguments, "
                f"got {len(instruction.arguments)}"
            )
        for index, (argument, parameter_type) in enumerate(
            zip(instruction.arguments, signature.parameter_types), start=1
        ):
            self._require_defined(argument, value_types)
            self._require_type(
                argument.type,
                parameter_type,
                f"Indirect call argument {index} type mismatch",
            )
        if isinstance(signature.return_type, VoidType):
            if instruction.result is not None:
                self._fail("Indirect call to void callable cannot produce a value")
        elif instruction.result is None:
            self._fail(
                f"Indirect call must produce a result of type {signature.return_type}"
            )
        else:
            self._require_type(
                instruction.result.type,
                signature.return_type,
                "Indirect call result type mismatch",
            )

    def _verify_array_new(
        self,
        instruction: SSAArrayNew,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, ArrayType):
            self._fail(f"Array new result must be array type, got {instruction.result.type}")
        for element in instruction.elements:
            self._require_defined(element, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Array literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_list_new(
        self,
        instruction: SSAListNew,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, ListType):
            self._fail(f"List new result must be list type, got {instruction.result.type}")
        for element in instruction.elements:
            self._require_defined(element, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"List literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_new(
        self,
        instruction: SSAVectorNew,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector new result must be vector type, got {instruction.result.type}")
        if instruction.result.type.orientation not in {"row", "column"}:
            self._fail(f"Vector new requires row or column orientation, got {instruction.result.type}")
        if instruction.orientation not in {"row", "column"}:
            self._fail(f"Vector new requires row or column instruction orientation, got {instruction.orientation}")
        if instruction.orientation != instruction.result.type.orientation:
            self._fail(
                f"Vector new orientation mismatch: result type is {instruction.result.type.orientation}, "
                f"instruction is {instruction.orientation}"
            )
        for element in instruction.elements:
            self._require_defined(element, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Vector literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_matrix_new(
        self,
        instruction: SSAMatrixNew,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix new result must be matrix type, got {instruction.result.type}")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Matrix new dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        if len(instruction.elements) != instruction.rows * instruction.cols:
            self._fail(
                f"Matrix new element count mismatch: expected {instruction.rows * instruction.cols}, "
                f"got {len(instruction.elements)}"
            )
        for element in instruction.elements:
            self._require_defined(element, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Matrix literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_add(
        self,
        instruction: SSAVectorAdd,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, value_types, "add")

    def _verify_vector_sub(
        self,
        instruction: SSAVectorSub,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, value_types, "sub")

    def _verify_vector_binary(
        self,
        instruction: SSAVectorAdd | SSAVectorSub,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, value_types)
        self._require_defined(instruction.right, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector {operation} result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.left.type, VectorType) or not isinstance(instruction.right.type, VectorType):
            self._fail(
                f"Vector {operation} expects vector operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.length <= 0:
            self._fail(f"Vector {operation} length must be positive, got {instruction.length}")
        if instruction.left.type.orientation != instruction.right.type.orientation:
            self._fail(f"Vector {operation} operands must have the same orientation")
        if instruction.orientation != instruction.result.type.orientation:
            self._fail(f"Vector {operation} instruction orientation must match result type")
        if instruction.result.type != instruction.left.type:
            self._fail(
                f"Vector {operation} result type mismatch: expected {instruction.left.type}, got {instruction.result.type}"
            )
        if instruction.right.type != instruction.left.type:
            self._fail(
                f"Vector {operation} operand type mismatch: expected {instruction.left.type}, got {instruction.right.type}"
            )

    def _verify_vector_scale(
        self,
        instruction: SSAVectorScale,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        self._require_defined(instruction.scalar, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector scale result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector scale expects vector operand, got {instruction.vector.type}")
        if instruction.length <= 0:
            self._fail(f"Vector scale length must be positive, got {instruction.length}")
        if instruction.orientation != instruction.result.type.orientation:
            self._fail("Vector scale instruction orientation must match result type")
        if instruction.result.type != instruction.vector.type:
            self._fail(
                f"Vector scale result type mismatch: expected {instruction.vector.type}, got {instruction.result.type}"
            )
        if instruction.scalar.type != instruction.vector.type.element:
            self._fail(
                f"Vector scale scalar type mismatch: expected {instruction.vector.type.element}, got {instruction.scalar.type}"
            )

    def _verify_vector_dot(
        self,
        instruction: SSAVectorDot,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.left, value_types)
        self._require_defined(instruction.right, value_types)
        if not isinstance(instruction.left.type, VectorType) or not isinstance(instruction.right.type, VectorType):
            self._fail(
                f"Vector dot expects vector operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.left.type.orientation != "row" or instruction.right.type.orientation != "column":
            self._fail("Vector dot is only defined for Vector<Row> * Vector<Column>")
        if instruction.length <= 0:
            self._fail(f"Vector dot length must be positive, got {instruction.length}")
        expected = self._numeric_binary_result_type(
            instruction.left.type.element,
            instruction.right.type.element,
        )
        if instruction.result.type != expected:
            self._fail(
                f"Vector dot result type mismatch: expected {expected}, got {instruction.result.type}"
            )

    def _verify_outer_product(
        self,
        instruction: SSAOuterProduct,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.column, value_types)
        self._require_defined(instruction.row, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Outer product result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.column.type, VectorType) or not isinstance(instruction.row.type, VectorType):
            self._fail(
                f"Outer product expects vector operands, got {instruction.column.type} and {instruction.row.type}"
            )
        if instruction.column.type.orientation != "column" or instruction.row.type.orientation != "row":
            self._fail("Outer product is only defined for Vector<Column> * Vector<Row>")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Outer product dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        expected_element = self._numeric_binary_result_type(
            instruction.column.type.element,
            instruction.row.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Outer product result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_matrix_add(
        self,
        instruction: SSAMatrixAdd,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, value_types, "add")

    def _verify_matrix_sub(
        self,
        instruction: SSAMatrixSub,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, value_types, "sub")

    def _verify_matrix_binary(
        self,
        instruction: SSAMatrixAdd | SSAMatrixSub,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, value_types)
        self._require_defined(instruction.right, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix {operation} result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.left.type, MatrixType) or not isinstance(instruction.right.type, MatrixType):
            self._fail(
                f"Matrix {operation} expects matrix operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Matrix {operation} dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        if instruction.result.type != instruction.left.type:
            self._fail(
                f"Matrix {operation} result type mismatch: expected {instruction.left.type}, got {instruction.result.type}"
            )
        if instruction.right.type != instruction.left.type:
            self._fail(
                f"Matrix {operation} operand type mismatch: expected {instruction.left.type}, got {instruction.right.type}"
            )

    def _verify_matrix_scale(
        self,
        instruction: SSAMatrixScale,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        self._require_defined(instruction.scalar, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix scale result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix scale expects matrix operand, got {instruction.matrix.type}")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Matrix scale dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        if instruction.result.type != instruction.matrix.type:
            self._fail(
                f"Matrix scale result type mismatch: expected {instruction.matrix.type}, got {instruction.result.type}"
            )
        if instruction.scalar.type != instruction.matrix.type.element:
            self._fail(
                f"Matrix scale scalar type mismatch: expected {instruction.matrix.type.element}, got {instruction.scalar.type}"
            )

    def _verify_matrix_matmul(
        self,
        instruction: SSAMatrixMatMul,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.left, value_types)
        self._require_defined(instruction.right, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix matmul result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.left.type, MatrixType) or not isinstance(instruction.right.type, MatrixType):
            self._fail(
                f"Matrix matmul expects matrix operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.rows <= 0 or instruction.inner <= 0 or instruction.cols <= 0:
            self._fail(
                f"Matrix matmul dimensions must be positive, got "
                f"{instruction.rows}x{instruction.inner} and {instruction.inner}x{instruction.cols}"
            )
        expected_element = self._numeric_binary_result_type(
            instruction.left.type.element,
            instruction.right.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Matrix matmul result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_matrix_vector_mul(
        self,
        instruction: SSAMatrixVectorMul,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        self._require_defined(instruction.vector, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Matrix vector mul result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.matrix.type, MatrixType) or not isinstance(instruction.vector.type, VectorType):
            self._fail(
                f"Matrix vector mul expects matrix and vector operands, got "
                f"{instruction.matrix.type} and {instruction.vector.type}"
            )
        if isinstance(instruction.result.type, VectorType) and instruction.result.type.orientation != "column":
            self._fail("Matrix vector mul result must be Vector<Column>")
        if isinstance(instruction.vector.type, VectorType) and instruction.vector.type.orientation != "column":
            self._fail("Matrix vector mul operand must be Vector<Column>")
        if instruction.rows <= 0 or instruction.inner <= 0:
            self._fail(
                f"Matrix vector mul dimensions must be positive, got "
                f"{instruction.rows}x{instruction.inner} and {instruction.inner}"
            )
        expected_element = self._numeric_binary_result_type(
            instruction.matrix.type.element,
            instruction.vector.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Matrix vector mul result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_vector_matrix_mul(
        self,
        instruction: SSAVectorMatrixMul,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        self._require_defined(instruction.matrix, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector matrix mul result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.vector.type, VectorType) or not isinstance(instruction.matrix.type, MatrixType):
            self._fail(
                f"Vector matrix mul expects vector and matrix operands, got "
                f"{instruction.vector.type} and {instruction.matrix.type}"
            )
        if isinstance(instruction.result.type, VectorType) and instruction.result.type.orientation != "row":
            self._fail("Vector matrix mul result must be Vector<Row>")
        if isinstance(instruction.vector.type, VectorType) and instruction.vector.type.orientation != "row":
            self._fail("Vector matrix mul operand must be Vector<Row>")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(
                f"Vector matrix mul dimensions must be positive, got "
                f"{instruction.rows} and {instruction.rows}x{instruction.cols}"
            )
        expected_element = self._numeric_binary_result_type(
            instruction.vector.type.element,
            instruction.matrix.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Vector matrix mul result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_array_get(
        self,
        instruction: SSAArrayGet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, value_types)
        self._require_defined(instruction.index, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array get expects array value, got {instruction.array.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Array get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.array.type.element:
            self._fail(
                f"Array get result type mismatch: expected "
                f"{instruction.array.type.element}, got {instruction.result.type}"
            )

    def _verify_array_slice(
        self,
        instruction: SSAArraySlice,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, value_types)
        self._require_defined(instruction.start, value_types)
        self._require_defined(instruction.end, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array slice expects array value, got {instruction.array.type}")
        if not isinstance(instruction.start.type, IntType):
            self._fail(f"Array slice start must be int, got {instruction.start.type}")
        if not isinstance(instruction.end.type, IntType):
            self._fail(f"Array slice end must be int, got {instruction.end.type}")
        if instruction.result.type != instruction.array.type:
            self._fail(
                f"Array slice result type mismatch: expected "
                f"{instruction.array.type}, got {instruction.result.type}"
            )

    def _verify_vector_get(
        self,
        instruction: SSAVectorGet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        self._require_defined(instruction.index, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector get expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Vector get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.vector.type.element:
            self._fail(
                f"Vector get result type mismatch: expected "
                f"{instruction.vector.type.element}, got {instruction.result.type}"
            )

    def _verify_list_get(
        self,
        instruction: SSAListGet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.index, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List get expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.list_value.type.element:
            self._fail(
                f"List get result type mismatch: expected "
                f"{instruction.list_value.type.element}, got {instruction.result.type}"
            )

    def _verify_matrix_get(
        self,
        instruction: SSAMatrixGet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        self._require_defined(instruction.row, value_types)
        self._require_defined(instruction.column, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix get expects matrix value, got {instruction.matrix.type}")
        if not isinstance(instruction.row.type, IntType):
            self._fail(f"Matrix get row index must be int, got {instruction.row.type}")
        if not isinstance(instruction.column.type, IntType):
            self._fail(f"Matrix get column index must be int, got {instruction.column.type}")
        if instruction.cols <= 0:
            self._fail(f"Matrix get column count must be positive, got {instruction.cols}")
        if instruction.result.type != instruction.matrix.type.element:
            self._fail(
                f"Matrix get result type mismatch: expected "
                f"{instruction.matrix.type.element}, got {instruction.result.type}"
            )

    def _verify_array_set(
        self,
        instruction: SSAArraySet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, value_types)
        self._require_defined(instruction.index, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array set expects array value, got {instruction.array.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Array set index must be int, got {instruction.index.type}")
        if instruction.value.type != instruction.array.type.element:
            self._fail(
                f"Array set value type mismatch: expected "
                f"{instruction.array.type.element}, got {instruction.value.type}"
            )

    def _verify_vector_set(
        self,
        instruction: SSAVectorSet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        self._require_defined(instruction.index, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector set expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Vector set index must be int, got {instruction.index.type}")
        if instruction.value.type != instruction.vector.type.element:
            self._fail(
                f"Vector set value type mismatch: expected "
                f"{instruction.vector.type.element}, got {instruction.value.type}"
            )

    def _verify_list_set(
        self,
        instruction: SSAListSet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.index, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List set expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List set index must be int, got {instruction.index.type}")
        if instruction.value.type != instruction.list_value.type.element:
            self._fail(
                f"List set value type mismatch: expected "
                f"{instruction.list_value.type.element}, got {instruction.value.type}"
            )

    def _verify_matrix_set(
        self,
        instruction: SSAMatrixSet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        self._require_defined(instruction.row, value_types)
        self._require_defined(instruction.column, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix set expects matrix value, got {instruction.matrix.type}")
        if not isinstance(instruction.row.type, IntType):
            self._fail(f"Matrix set row index must be int, got {instruction.row.type}")
        if not isinstance(instruction.column.type, IntType):
            self._fail(f"Matrix set column index must be int, got {instruction.column.type}")
        if instruction.cols <= 0:
            self._fail(f"Matrix set column count must be positive, got {instruction.cols}")
        if instruction.value.type != instruction.matrix.type.element:
            self._fail(
                f"Matrix set value type mismatch: expected "
                f"{instruction.matrix.type.element}, got {instruction.value.type}"
            )

    def _verify_array_length(
        self,
        instruction: SSAArrayLength,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array length expects array value, got {instruction.array.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Array length result must be int, got {instruction.result.type}")

    def _verify_list_length(
        self,
        instruction: SSAListLength,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List length expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"List length result must be int, got {instruction.result.type}")

    def _verify_array_copy(self, instruction: SSAArrayCopy, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.array, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array copy expects array value, got {instruction.array.type}")
        self._require_type(instruction.result.type, instruction.array.type, "Array copy result type mismatch")

    def _verify_list_copy(self, instruction: SSAListCopy, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List copy expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.result.type, instruction.list_value.type, "List copy result type mismatch")

    def _verify_list_slice(self, instruction: SSAListSlice, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.start, value_types)
        self._require_defined(instruction.end, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List slice expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.start.type, IntType):
            self._fail(f"List slice start must be int, got {instruction.start.type}")
        if not isinstance(instruction.end.type, IntType):
            self._fail(f"List slice end must be int, got {instruction.end.type}")
        self._require_type(
            instruction.result.type,
            instruction.list_value.type,
            "List slice result type mismatch",
        )

    def _verify_list_contains(self, instruction: SSAListContains, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List contains expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.value.type, instruction.list_value.type.element, "List contains value type mismatch")
        if ir_eq_capability(instruction.value.type, self._structs) is None:
            self._fail(f"List contains requires Eq({instruction.value.type})")
        if not isinstance(instruction.result.type, BoolType):
            self._fail(f"List contains result must be bool, got {instruction.result.type}")

    def _verify_list_index_of(self, instruction: SSAListIndexOf, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List index_of expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.value.type, instruction.list_value.type.element, "List index_of value type mismatch")
        if ir_eq_capability(instruction.value.type, self._structs) is None:
            self._fail(f"List index_of requires Eq({instruction.value.type})")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"List index_of result must be int, got {instruction.result.type}")

    def _verify_list_reverse(self, instruction: SSAListReverse, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List reverse expects list value, got {instruction.list_value.type}")

    def _verify_list_clear(self, instruction: SSAListClear, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List clear expects list value, got {instruction.list_value.type}")

    def _verify_list_push(self, instruction: SSAListPush, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List push expects list value, got {instruction.list_value.type}")
        self._require_type(
            instruction.value.type,
            instruction.list_value.type.element,
            "List push value type mismatch",
        )

    def _verify_list_insert(self, instruction: SSAListInsert, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.index, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List insert expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List insert index must be int, got {instruction.index.type}")
        self._require_type(
            instruction.value.type,
            instruction.list_value.type.element,
            "List insert value type mismatch",
        )

    def _verify_list_pop(self, instruction: SSAListPop, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List pop expects list value, got {instruction.list_value.type}")
        self._require_type(
            instruction.result.type,
            instruction.list_value.type.element,
            "List pop result type mismatch",
        )

    def _verify_list_remove_at(self, instruction: SSAListRemoveAt, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, value_types)
        self._require_defined(instruction.index, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List remove_at expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List remove_at index must be int, got {instruction.index.type}")
        self._require_type(
            instruction.result.type,
            instruction.list_value.type.element,
            "List remove_at result type mismatch",
        )

    def _verify_sequence_sort(self, instruction: SSASequenceSort, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.sequence, value_types)
        if not isinstance(instruction.sequence.type, (ArrayType, ListType)):
            self._fail(f"Sequence sort expects array or list value, got {instruction.sequence.type}")
        if not isinstance(instruction.sequence.type.element, (IntType, DoubleType, StringType)):
            self._fail(f"Sequence sort does not support element type {instruction.sequence.type.element}")

    def _verify_list_is_empty(
        self,
        instruction: SSAListIsEmpty,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List is_empty expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.result.type, BoolType):
            self._fail(f"List is_empty result must be bool, got {instruction.result.type}")

    def _verify_vector_length(
        self,
        instruction: SSAVectorLength,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector length expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Vector length result must be int, got {instruction.result.type}")

    def _verify_matrix_rows(
        self,
        instruction: SSAMatrixRows,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix rows expects matrix value, got {instruction.matrix.type}")
        if instruction.rows <= 0:
            self._fail(f"Matrix rows count must be positive, got {instruction.rows}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix rows result must be int, got {instruction.result.type}")

    def _verify_matrix_columns(
        self,
        instruction: SSAMatrixColumns,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix columns expects matrix value, got {instruction.matrix.type}")
        if instruction.columns <= 0:
            self._fail(f"Matrix columns count must be positive, got {instruction.columns}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix columns result must be int, got {instruction.result.type}")

    def _verify_phi(
        self,
        function: SSAFunction,
        instruction: SSAPhi,
        block: SSABasicBlock,
        blocks: dict[str, SSABasicBlock],
        predecessors: dict[str, set[str]],
        value_types: dict[str, IRType],
    ) -> None:
        if not instruction.incoming:
            self._fail(f"Phi '{self._value(instruction.result)}' has no incoming values")
        if block.name == function.entry_block:
            self._fail(
                f"Phi '{self._value(instruction.result)}' is not allowed in entry "
                f"block '{block.name}'"
            )
        if not predecessors[block.name]:
            self._fail(
                f"Phi '{self._value(instruction.result)}' in block '{block.name}' "
                "has no CFG predecessors"
            )

        seen_blocks: set[str] = set()
        for incoming_block, value in instruction.incoming:
            if incoming_block not in blocks:
                self._fail(
                    f"Phi incoming block '{incoming_block}' does not exist "
                    f"in function block '{block.name}'"
                )
            if incoming_block in seen_blocks:
                self._fail(
                    f"Duplicate incoming block '{incoming_block}' "
                    f"for phi '{self._value(instruction.result)}'"
                )
            seen_blocks.add(incoming_block)

            if incoming_block not in predecessors[block.name]:
                self._fail(
                    f"Phi incoming block '{incoming_block}' is not a predecessor "
                    f"of block '{block.name}'"
                )

            self._require_defined(value, value_types)
            if value.type != instruction.result.type:
                self._fail(
                    f"Phi '{self._value(instruction.result)}' type mismatch: "
                    f"expected {instruction.result.type}, got {value.type}"
                )

        missing_blocks = predecessors[block.name] - seen_blocks
        if missing_blocks:
            missing_block = min(missing_blocks)
            self._fail(
                f"Phi '{self._value(instruction.result)}' in block '{block.name}' "
                f"is missing an incoming value for predecessor '{missing_block}'"
            )

    def _cfg(self, function: SSAFunction) -> CFG:
        edges = tuple(
            CFGEdge(block.name, successor)
            for block in function.blocks
            for successor in self._successors(block)
        )
        return CFG(
            function.name,
            tuple(CFGNode(block.name) for block in function.blocks),
            edges,
        )

    def _verify_dominance(
        self,
        function: SSAFunction,
        predecessors: dict[str, set[str]],
        definition_sites: dict[str, _DefinitionSite],
        dominators: DominatorResult,
    ) -> None:
        """Verify ordinary uses and edge-sensitive phi uses.

        Parameters are available throughout the function. For unreachable
        blocks, the entry-rooted dominance relation intentionally proves only
        same-block ordering; phi values defined directly in an unreachable
        predecessor are still checked at that predecessor's terminator.
        """
        blocks = {block.name: block for block in function.blocks}

        for block in function.blocks:
            for use_index, instruction in enumerate(block.instructions):
                if isinstance(instruction, SSAPhi):
                    self._verify_phi_dominance(
                        instruction,
                        block,
                        blocks,
                        predecessors,
                        definition_sites,
                        dominators,
                    )
                    continue

                for value in self._instruction_operands(instruction):
                    site = definition_sites[value.name]
                    if site.is_parameter:
                        continue

                    assert site.block_name is not None
                    assert site.instruction_index is not None
                    if site.block_name == block.name:
                        if site.instruction_index >= use_index:
                            self._fail(
                                f"SSA value '{self._value(value)}' is used before its "
                                f"definition in block '{block.name}'"
                            )
                        continue

                    if dominators.is_reachable(block.name) and dominators.dominates(
                        site.block_name,
                        block.name,
                    ):
                        continue

                    self._fail(
                        f"SSA value '{self._value(value)}' used in block "
                        f"'{block.name}' is not dominated by its definition in "
                        f"block '{site.block_name}'"
                    )

    def _verify_phi_dominance(
        self,
        instruction: SSAPhi,
        block: SSABasicBlock,
        blocks: dict[str, SSABasicBlock],
        predecessors: dict[str, set[str]],
        definition_sites: dict[str, _DefinitionSite],
        dominators: DominatorResult,
    ) -> None:
        # Exact predecessor validation ran before this phase, so every incoming
        # label is safe to resolve here.
        assert {name for name, _value in instruction.incoming} == predecessors[block.name]

        for predecessor, value in instruction.incoming:
            site = definition_sites[value.name]
            if site.is_parameter:
                continue

            assert site.block_name is not None
            assert site.instruction_index is not None
            if site.block_name == predecessor:
                terminator_index = len(blocks[predecessor].instructions) - 1
                if site.instruction_index < terminator_index:
                    continue
            elif dominators.is_reachable(predecessor) and dominators.dominates(
                site.block_name,
                predecessor,
            ):
                continue

            self._fail(
                f"Phi '{self._value(instruction.result)}' in block '{block.name}' "
                f"uses value '{self._value(value)}' for predecessor "
                f"'{predecessor}', but that value is not available at the end "
                f"of the predecessor; its definition is in block "
                f"'{site.block_name}'"
            )

    @classmethod
    def _instruction_operands(cls, instruction: SSAInstruction) -> tuple[SSAValue, ...]:
        if isinstance(instruction, (SSAConst, SSAPhi)):
            return ()

        operands: list[SSAValue] = []
        for field in fields(instruction):
            if field.name == "result":
                continue
            operands.extend(cls._contained_values(getattr(instruction, field.name)))
        return tuple(operands)

    @classmethod
    def _contained_values(cls, value: object) -> list[SSAValue]:
        if isinstance(value, SSAValue):
            return [value]
        if isinstance(value, (tuple, list)):
            contained: list[SSAValue] = []
            for item in value:
                contained.extend(cls._contained_values(item))
            return contained
        if is_dataclass(value):
            contained = []
            for field in fields(value):
                contained.extend(cls._contained_values(getattr(value, field.name)))
            return contained
        return []

    def _verify_return(
        self,
        function: SSAFunction,
        instruction: SSAReturn,
        value_types: dict[str, IRType],
    ) -> None:
        if instruction.value is None:
            if not isinstance(function.return_type, VoidType):
                self._fail(
                    f"Return type mismatch: expected {function.return_type}, got void"
                )
            return

        self._require_defined(instruction.value, value_types)
        if instruction.value.type != function.return_type:
            self._fail(
                f"Return type mismatch: expected {function.return_type}, "
                f"got {instruction.value.type}"
            )

    def _verify_const(self, instruction: SSAConst) -> None:
        value = instruction.value
        result_type = instruction.result.type

        if isinstance(value, IREnumConstant):
            if not isinstance(result_type, EnumType):
                self._fail(
                    f"Enum const type mismatch: expected enum {value.enum_name}, got {result_type}"
                )
            if value.enum_name != result_type.name:
                self._fail(
                    f"Enum const identity mismatch: expected {result_type.name}, got {value.enum_name}"
                )
            if not 0 <= value.member_id < len(result_type.variants):
                self._fail(
                    f"Enum const member id {value.member_id} is invalid for {result_type.name}"
                )
            if result_type.variants[value.member_id] != value.member_name:
                self._fail(
                    f"Enum const member '{value.member_name}' does not match declaration {result_type.name}"
                )
            if value.discriminant != value.member_id:
                self._fail(
                    f"Enum const discriminant {value.discriminant} is invalid for member '{value.member_name}'"
                )
            return

        if isinstance(value, bool):
            expected: IRType | tuple[type[IRType], ...] = BoolType()
        elif isinstance(value, int):
            expected = IntType()
        elif isinstance(value, float):
            expected = (FloatType, DoubleType)
        elif isinstance(value, complex):
            expected = ComplexType()
        elif isinstance(value, str):
            expected = StringType()
        elif value is None:
            return
        else:
            return

        if isinstance(expected, tuple):
            if not isinstance(result_type, expected):
                expected_text = " or ".join(str(type_()) for type_ in expected)
                self._fail(
                    f"Const type mismatch: expected {expected_text}, got {result_type}"
                )
            return

        if result_type != expected:
            self._fail(f"Const type mismatch: expected {expected}, got {result_type}")

    def _binary_result_type(self, instruction: SSABinaryOp) -> IRType:
        left = instruction.left.type
        right = instruction.right.type
        operator = instruction.operator

        if operator == "add" and isinstance(left, StringType) and isinstance(right, StringType):
            return StringType()

        if operator in {"add", "sub", "mul", "div", "rem", "mod"}:
            if not isinstance(left, self._NUMERIC_TYPES) or not isinstance(
                right,
                self._NUMERIC_TYPES,
            ):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            if operator in {"rem", "mod"} and (
                not isinstance(left, self._REAL_TYPES)
                or not isinstance(right, self._REAL_TYPES)
            ):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            if operator == "div" and isinstance(left, IntType) and isinstance(right, IntType):
                return DoubleType()
            if isinstance(left, ComplexType) or isinstance(right, ComplexType):
                return ComplexType()
            if isinstance(left, DoubleType) or isinstance(right, DoubleType):
                return DoubleType()
            if isinstance(left, FloatType) or isinstance(right, FloatType):
                return FloatType()
            return IntType()

        if operator in {"eq", "ne"}:
            if left != right:
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            return BoolType()

        if operator in {"lt", "le", "gt", "ge"}:
            if not isinstance(left, self._REAL_TYPES) or not isinstance(
                right,
                self._REAL_TYPES,
            ):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            return BoolType()

        if operator in {"and", "or"}:
            if not isinstance(left, BoolType) or not isinstance(right, BoolType):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            return BoolType()

        self._fail(f"Unsupported binary operator '{operator}'")

    def _verify_unary(self, instruction: SSAUnaryOp) -> None:
        if instruction.operator != "not":
            self._fail(f"Unsupported unary operator '{instruction.operator}'")
        if not isinstance(instruction.operand.type, BoolType):
            self._fail(
                f"Unary op 'not' requires bool operand, got {instruction.operand.type}"
            )
        self._require_type(
            instruction.result.type,
            BoolType(),
            "Unary op 'not' result type mismatch",
        )

    def _compare_operand_result_type(self, instruction: SSACompareOp) -> IRType:
        left = instruction.left.type
        right = instruction.right.type
        operator = instruction.operator

        if isinstance(left, (VectorType, MatrixType)):
            expected_rank = 1 if isinstance(left, VectorType) else 2
            shape = instruction.aggregate_shape
            if operator not in {"eq", "ne"} or left != right:
                self._fail(
                    f"Aggregate compare requires equal operands and eq/ne, got {left}, {right}, {operator}"
                )
            if shape is None or len(shape) != expected_rank or any(size <= 0 for size in shape):
                self._fail(f"Aggregate compare requires a positive rank-{expected_rank} shape")
            if not isinstance(left.element, (IntType, DoubleType, BoolType, StringType)):
                self._fail(f"Aggregate compare does not support element type {left.element}")
            return BoolType()

        if instruction.aggregate_shape is not None:
            self._fail("Scalar compare must not carry an aggregate shape")

        if operator in {"lt", "le", "gt", "ge"}:
            if not (
                isinstance(left, IntType)
                and isinstance(right, IntType)
                or isinstance(left, DoubleType)
                and isinstance(right, DoubleType)
            ):
                self._fail(
                    f"Compare op '{operator}' requires int or double operands, got {left} and {right}"
                )
            return BoolType()

        if operator in {"eq", "ne"}:
            if left != right:
                self._fail(
                    f"Compare op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            if ir_eq_capability(left, self._structs) is None:
                self._fail(
                    f"Compare op '{operator}' does not support operands of type {left}"
                )
            return BoolType()

        self._fail(f"Unsupported compare operator '{operator}'")

    def _verify_cast(self, instruction: SSACast) -> None:
        source = instruction.value.type
        target = instruction.result.type
        if (
            isinstance(source, IntType)
            and isinstance(target, (FloatType, DoubleType))
            or isinstance(source, (FloatType, DoubleType))
            and isinstance(target, (IntType, FloatType, DoubleType))
            and source != target
        ):
            return
        self._fail(f"Cast requires int/double operands, got {source} to {target}")

    def _require_defined(
        self,
        value: SSAValue,
        value_types: dict[str, IRType],
    ) -> None:
        expected_type = value_types.get(value.name)
        if expected_type is None:
            self._fail(f"Undefined value '{self._value(value)}'")
        if expected_type != value.type:
            self._fail(
                f"Value '{self._value(value)}' type mismatch: "
                f"expected {expected_type}, got {value.type}"
            )

    def _require_type(self, actual: IRType, expected: IRType, message: str) -> None:
        if actual != expected:
            self._fail(f"{message}: expected {expected}, got {actual}")

    @staticmethod
    def _instruction_result(instruction: SSAInstruction) -> SSAValue | None:
        if isinstance(instruction, (SSAConst, SSABinaryOp, SSAUnaryOp, SSACompareOp, SSACast, SSAPhi, SSAFunctionRef)):
            return instruction.result
        if isinstance(instruction, SSACall):
            return instruction.result
        if isinstance(instruction, SSACallIndirect):
            return instruction.result
        if isinstance(
            instruction,
            (
                SSAArrayNew,
                SSAArrayCopy,
                SSAArrayGet,
                SSAArraySlice,
                SSAListNew,
                SSAListGet,
                SSAListCopy,
                SSAListSlice,
                SSAListContains,
                SSAListIndexOf,
                SSAListPop,
                SSAListRemoveAt,
                SSAVectorGet,
                SSAMatrixGet,
                SSAArrayLength,
                SSAListLength,
                SSAListIsEmpty,
                SSAVectorLength,
                SSAMatrixRows,
                SSAMatrixColumns,
                SSAVectorNew,
                SSAMatrixNew,
                SSAVectorAdd,
                SSAVectorDot,
                SSAOuterProduct,
                SSAVectorScale,
                SSAMatrixAdd,
                SSAMatrixMatMul,
                SSAMatrixVectorMul,
                SSAVectorMatrixMul,
                SSAMatrixScale,
                SSAVectorSub,
                SSAMatrixSub,
                SSAStructNew,
                SSAStructGet,
                SSAStructSet,
                SSAMethodResultNew,
                SSAMethodResultReceiver,
                SSAMethodResultValue,
            ),
        ):
            return instruction.result
        return None

    def _numeric_binary_result_type(self, left: IRType, right: IRType) -> IRType:
        if not isinstance(left, self._NUMERIC_TYPES) or not isinstance(right, self._NUMERIC_TYPES):
            self._fail(f"Numeric operation requires numeric operands, got {left} and {right}")
        if isinstance(left, ComplexType) or isinstance(right, ComplexType):
            return ComplexType()
        if isinstance(left, DoubleType) or isinstance(right, DoubleType):
            return DoubleType()
        if isinstance(left, FloatType) or isinstance(right, FloatType):
            return FloatType()
        return IntType()

    @staticmethod
    def _successors(block: SSABasicBlock) -> tuple[str, ...]:
        terminator = block.instructions[-1]
        if isinstance(terminator, SSAJump):
            return (terminator.target,)
        if isinstance(terminator, SSABranch):
            return (terminator.true_target, terminator.false_target)
        return ()

    def _verify_type(self, type_: IRType, context: str) -> None:
        if not self._is_valid_type(type_):
            self._fail(f"Invalid SSA type for {context}: {type_!r}")

    def _is_valid_type(self, type_: IRType) -> bool:
        if isinstance(type_, EnumType):
            return bool(type_.name) and bool(type_.variants) and len(set(type_.variants)) == len(type_.variants)
        if isinstance(type_, StructType):
            return bool(type_.name) and type_.name in self._structs
        if isinstance(
            type_,
            (
                IntType,
                FloatType,
                DoubleType,
                BoolType,
                StringType,
                VoidType,
                ComplexType,
                ClassRefType,
                InterfaceType,
                FunctionType,
            ),
        ):
            return True
        if isinstance(type_, NullableType):
            return self._is_valid_type(type_.inner)
        if isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
            return self._is_valid_type(type_.element)
        if isinstance(type_, MethodResultType):
            return self._is_valid_type(type_.receiver) and self._is_valid_type(type_.value)
        return False

    @staticmethod
    def _value(value: SSAValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise SSAVerificationError(message)
