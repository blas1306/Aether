from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import NoReturn

from aether.range_safety import RANGE_STEP_NONZERO_BUILTIN
from aether.integer_arithmetic import INT_MAX, INT_MIN, is_aether_int
from aether.interface_abi import (
    ERASED_BOX_HEADER_SIZE,
    INTERFACE_ABI_VERSION,
    copy_owned_symbol,
    dispatch_thunk_symbol,
    drop_owned_symbol,
    witness_symbol,
)
from .erased_layout import ErasedLayoutError, align_up, erased_size_alignment

from .model import (
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
    IRCatchEntry,
    IRClassGet,
    IRClassNew,
    IRClassSet,
    IRInterfaceCall,
    IRInterfaceConstruct,
    IRInvoke,
    IRInvokeIndirect,
    IRInvokeInterface,
    IRCompareOp,
    IRConst,
    IRCopyInit,
    IRDestroy,
    IRExceptionDestroy,
    IRExceptionMatch,
    IRExceptionPayload,
    IREnumConstant,
    IRFunction,
    IRFunctionRef,
    IRInstruction,
    IRInitDefault,
    IRJump,
    IRListGet,
    IRListCopy,
    IRListSlice,
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
    IRMoveInit,
    IROuterProduct,
    IRPrint,
    IRPackException,
    IRPropagate,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRReturn,
    IRRethrow,
    IRRelocate,
    IRStorage,
    IRStore,
    IRThrow,
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
from .lifecycle import LifecycleTypeRegistry
from .equality import ir_eq_capability
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
from aether.text_codec import (
    TEXT_BYTE_AT_BUILTIN,
    TEXT_BYTE_SLICE_BUILTIN,
    TEXT_CONCAT_FRAGMENTS_BUILTIN,
    TEXT_FORMAT_DOUBLE_BUILTIN,
    TEXT_FORMAT_INT_BUILTIN,
    TEXT_CODEC_BUILTINS,
)
from .types import (
    ArrayType,
    BoolType,
    ClassRefType,
    ComplexType,
    DoubleType,
    ExceptionEventType,
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
from .scalar_math import scalar_math_result_type
from .verification_result import (
    VerifierCategory,
    VerifierFailure,
    VerifierLocation,
    VerifierSeverity,
)


class IRVerificationError(ValueError):
    """Raised when an IR module is internally inconsistent."""

    def __init__(
        self,
        message: str,
        *,
        normalized_failure: VerifierFailure | None = None,
    ) -> None:
        super().__init__(message)
        self.normalized_failure = normalized_failure


@dataclass(frozen=True)
class _State:
    values: frozenset[str]
    slots: frozenset[str]
    moved: frozenset[str] = frozenset()
    destroyed: frozenset[str] = frozenset()

    def intersect(self, other: _State) -> _State:
        return _State(
            values=self.values & other.values,
            slots=self.slots & other.slots,
            moved=self.moved & other.moved,
            destroyed=self.destroyed & other.destroyed,
        )


class IRVerifier:
    """Validate the initial executable Aether IR subset."""

    _TERMINATORS = (
        IRReturn,
        IRJump,
        IRBranch,
        IRInvoke,
        IRInvokeIndirect,
        IRInvokeInterface,
        IRThrow,
        IRRethrow,
        IRPropagate,
    )
    _NUMERIC_TYPES = (IntType, FloatType, DoubleType, ComplexType)
    _REAL_TYPES = (IntType, FloatType, DoubleType)

    def __init__(self, module: IRModule) -> None:
        self.module = module
        self._functions: dict[str, IRFunction] = {}
        self._structs = {}
        self._lifecycle: LifecycleTypeRegistry | None = None
        self._active_rule: tuple[str, VerifierCategory] | None = None
        self._active_location: VerifierLocation | None = None
        self._active_instruction: IRInstruction | None = None
        self._lifecycle_expanded = False

    def verify(self) -> IRModule:
        """Verify the module and return it unchanged on success."""
        self._functions = {}
        self._structs = {definition.name: definition for definition in self.module.structs}
        self._lifecycle = LifecycleTypeRegistry(self.module.structs)
        self._active_rule = None
        self._active_location = None
        self._active_instruction = None
        self._lifecycle_expanded = any(
            isinstance(instruction, IRCall)
            and instruction.builtin
            in {"__aether_retain", "__aether_release", "__aether_interface_copy_owned"}
            for function in self.module.functions
            for block in function.blocks
            for instruction in block.instructions
        )
        self._verify_module()
        return self.module

    def _verify_module(self) -> None:
        self._verify_struct_definitions()
        seen: set[str] = set()
        for function in self.module.functions:
            if function.name in seen:
                self._fail(
                    f"Duplicate function '{function.name}'",
                    rule=("IRV-006", VerifierCategory.DEFINITIONS),
                )
            seen.add(function.name)
            self._functions[function.name] = function

        self._verify_interface_effect_metadata()
        for function in self.module.functions:
            self._verify_function(function)

    def _verify_interface_effect_metadata(self) -> None:
        effects: dict[str, bool] = {}
        for function in self.module.functions:
            for block in function.blocks:
                for instruction in block.instructions:
                    slots = (
                        instruction.witness.method_slots
                        if isinstance(instruction, IRInterfaceConstruct)
                        else (
                            (instruction.slot,)
                            if isinstance(
                                instruction,
                                (IRInterfaceCall, IRInvokeInterface),
                            )
                            else ()
                        )
                    )
                    for slot in slots:
                        if type(slot.may_throw) is not bool:
                            self._fail(
                                f"Interface slot '{slot.method_id}' may_throw metadata must be boolean",
                                rule=("IRV-130", VerifierCategory.TYPES),
                            )
                        prior = effects.setdefault(slot.method_id, slot.may_throw)
                        if prior != slot.may_throw:
                            self._fail(
                                f"Interface slot '{slot.method_id}' has contradictory may_throw metadata",
                                rule=("IRV-145", VerifierCategory.CALLS),
                            )
                        if slot.method_id == "Error.message" and slot.may_throw:
                            self._fail(
                                "Error.message interface slot must be non-throwing",
                                rule=("IRV-145", VerifierCategory.CALLS),
                            )

                    if isinstance(instruction, IRInterfaceConstruct):
                        for slot in instruction.witness.method_slots:
                            method = slot.method_id.rsplit(".", 1)[-1]
                            target = self._functions.get(
                                f"{instruction.witness.concrete_type_id}.{method}"
                            )
                            if target is not None and target.may_throw and not slot.may_throw:
                                self._fail(
                                    f"Interface witness slot '{slot.method_id}' lost may_throw metadata",
                                    rule=("IRV-145", VerifierCategory.CALLS),
                                )

    def _verify_struct_definitions(self) -> None:
        if len(self._structs) != len(self.module.structs):
            self._fail(
                "Duplicate nominal struct definition",
                rule=("IRV-001", VerifierCategory.DEFINITIONS),
            )
        edges: dict[str, tuple[str, ...]] = {}
        for definition in self.module.structs:
            if not definition.name:
                self._fail(
                    "Struct definition name must not be empty",
                    rule=("IRV-002", VerifierCategory.DEFINITIONS),
                )
            field_names = [name for name, _type in definition.fields]
            if len(field_names) != len(set(field_names)):
                self._fail(
                    f"Struct '{definition.name}' has duplicate fields",
                    rule=("IRV-003", VerifierCategory.DEFINITIONS),
                )
            for field_name, field_type in definition.fields:
                if isinstance(field_type, VoidType) or not self._is_valid_type(field_type):
                    self._fail(
                        f"Struct '{definition.name}' field '{field_name}' has invalid or incomplete type {field_type}",
                        rule=("IRV-004", VerifierCategory.TYPES),
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
                self._fail(
                    f"Recursive by-value struct layout has infinite size: {cycle}",
                    rule=("IRV-005", VerifierCategory.TYPES),
                )
            active.append(name)
            for target in edges.get(name, ()):
                visit(target)
            active.pop()
            visited.add(name)

        for name in edges:
            visit(name)

    def _verify_function(self, function: IRFunction) -> None:
        self._verify_parameters(function)
        self._verify_type(function.return_type, f"return type of function '{function.name}'")

        if not function.blocks:
            self._fail(
                f"Function '{function.name}' has no blocks",
                rule=("IRV-016", VerifierCategory.CFG),
            )

        blocks = self._collect_blocks(function)
        if "entry" not in blocks:
            self._fail(
                f"Function '{function.name}' has no entry block",
                rule=("IRV-017", VerifierCategory.CFG),
            )

        self._verify_block_structure(function, blocks)
        self._verify_exception_structure(function, blocks)
        self._verify_exception_event_ownership(function, blocks)
        self._verify_constructor_receiver_ownership(function, blocks)

        value_types = self._collect_value_types(function)
        slot_types = self._collect_slot_types(function)

        self._verify_borrowed_elements(function)
        self._verify_reachable_values(function, blocks, value_types, slot_types)
        self._verify_all_non_void_paths_return(function, blocks)

    def _verify_constructor_receiver_ownership(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        """Verify the edge-specific owner transfer synthesized for constructors."""

        if not self._lifecycle_expanded:
            return
        assert self._lifecycle is not None

        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if not isinstance(instruction, (IRCall, IRInvoke)):
                    continue
                if not instruction.function.endswith(".__ctor") or not instruction.arguments:
                    continue

                receiver = instruction.arguments[0]
                if not self._lifecycle.traits(receiver.type).needs_destroy:
                    continue

                if isinstance(instruction, IRCall):
                    if isinstance(receiver.type, StructType):
                        following = block.instructions[index + 1 :]
                        self._require_single_receiver_release(
                            receiver,
                            following,
                            block.name,
                        )
                    continue

                cleanup = blocks.get(instruction.exceptional_target)
                if cleanup is None or not self._is_constructor_cleanup_block(
                    cleanup,
                    receiver,
                ):
                    self._fail(
                        f"Constructor invoke in block '{block.name}' does not have one "
                        "dedicated exceptional receiver cleanup",
                        rule=("IRV-150", VerifierCategory.LIFECYCLE),
                    )

                if isinstance(receiver.type, StructType):
                    normal = blocks.get(instruction.normal_target)
                    if normal is None:
                        self._fail(
                            f"Constructor invoke in block '{block.name}' has no normal block",
                            rule=("IRV-150", VerifierCategory.LIFECYCLE),
                        )
                    self._require_single_receiver_release(
                        receiver,
                        normal.instructions,
                        normal.name,
                    )

    @staticmethod
    def _is_release_of(instruction: IRInstruction, receiver: IRValue) -> bool:
        return (
            isinstance(instruction, IRCall)
            and instruction.builtin == "__aether_release"
            and instruction.function == "__aether_release"
            and instruction.arguments == (receiver,)
            and instruction.result is None
        )

    def _is_constructor_cleanup_block(
        self,
        block: IRBasicBlock,
        receiver: IRValue,
    ) -> bool:
        instructions = block.instructions
        return (
            len(instructions) == 3
            and isinstance(instructions[0], IRCatchEntry)
            and self._is_release_of(instructions[1], receiver)
            and isinstance(instructions[2], IRPropagate)
            and instructions[2].event == instructions[0].event
        )

    def _require_single_receiver_release(
        self,
        receiver: IRValue,
        instructions: list[IRInstruction],
        block_name: str,
    ) -> None:
        releases = [
            index
            for index, item in enumerate(instructions)
            if self._is_release_of(item, receiver)
        ]
        if len(releases) != 1:
            self._fail(
                f"Constructor receiver '{receiver.name}' does not have exactly one "
                f"normal release in block '{block_name}'",
                rule=("IRV-150", VerifierCategory.LIFECYCLE),
            )
        release_index = releases[0]
        if any(
            receiver in self._instruction_operands(item)
            for item in instructions[release_index + 1 :]
        ):
            self._fail(
                f"Constructor receiver '{receiver.name}' is used after release in "
                f"block '{block_name}'",
                rule=("IRV-150", VerifierCategory.LIFECYCLE),
            )

    @classmethod
    def _instruction_operands(cls, instruction: IRInstruction) -> tuple[IRValue, ...]:
        operands: list[IRValue] = []
        for field in fields(instruction):
            if field.name == "result" or field.metadata.get("ir_definition", False):
                continue
            operands.extend(cls._contained_values(getattr(instruction, field.name)))
        if isinstance(instruction, (IRInvoke, IRInvokeIndirect, IRInvokeInterface)):
            definitions = {instruction.exception}
            if instruction.result is not None:
                definitions.add(instruction.result)
            operands = [value for value in operands if value not in definitions]
        return tuple(operands)

    @classmethod
    def _contained_values(cls, value: object) -> list[IRValue]:
        if isinstance(value, IRValue):
            return [value]
        if isinstance(value, (tuple, list)):
            return [
                contained
                for item in value
                for contained in cls._contained_values(item)
            ]
        if is_dataclass(value):
            return [
                contained
                for field in fields(value)
                for contained in cls._contained_values(getattr(value, field.name))
            ]
        return []

    def _verify_exception_event_ownership(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        """Prove one terminal disposition for every live event on every path."""

        handler_events = {
            block.name: block.instructions[0].event
            for block in function.blocks
            if block.instructions
            and isinstance(block.instructions[0], IRCatchEntry)
        }
        if not handler_events and not any(
            isinstance(instruction, IRPackException)
            for block in function.blocks
            for instruction in block.instructions
        ):
            return

        inputs: dict[str, dict[str, frozenset[str]]] = {
            name: {} for name in blocks
        }
        inputs["entry"]["<entry>"] = frozenset()
        worklist = ["entry"]
        queued = {"entry"}
        processed: dict[str, frozenset[str]] = {}

        while worklist:
            block_name = worklist.pop(0)
            queued.discard(block_name)
            predecessor_states = inputs[block_name]
            if not predecessor_states:
                continue

            normalized = []
            for state in predecessor_states.values():
                live = set(state)
                handler_event = handler_events.get(block_name)
                if handler_event is not None:
                    live.add(handler_event.name)
                normalized.append(frozenset(live))

            first = normalized[0]
            if any(state != first for state in normalized[1:]):
                self._fail(
                    f"Incompatible exception-event ownership merge at block "
                    f"'{block_name}'",
                    rule=("IRV-149", VerifierCategory.LIFECYCLE),
                )
            if processed.get(block_name) == first:
                continue
            processed[block_name] = first

            outgoing = self._transfer_exception_events(
                blocks[block_name],
                set(first),
            )
            for target, state in outgoing:
                frozen = frozenset(state)
                if inputs[target].get(block_name) == frozen:
                    continue
                inputs[target][block_name] = frozen
                if target not in queued:
                    worklist.append(target)
                    queued.add(target)

        for block in function.blocks:
            if block.name in processed:
                continue
            created = {
                instruction.result.name
                for instruction in block.instructions
                if isinstance(instruction, IRPackException)
            }
            consumed = {
                instruction.event.name
                for instruction in block.instructions
                if isinstance(
                    instruction,
                    (
                        IRExceptionDestroy,
                        IRThrow,
                        IRRethrow,
                        IRPropagate,
                    ),
                )
            }
            leaked = created - consumed
            if leaked:
                self._fail(
                    f"Owned exception event '%{min(leaked)}' is created "
                    "without a terminal disposition",
                    rule=("IRV-149", VerifierCategory.LIFECYCLE),
                )

    def _transfer_exception_events(
        self,
        block: IRBasicBlock,
        live: set[str],
    ) -> list[tuple[str, set[str]]]:
        for instruction in block.instructions:
            if isinstance(instruction, IRCatchEntry):
                continue
            if isinstance(instruction, IRPackException):
                live.add(instruction.result.name)
                continue
            if isinstance(instruction, (IRExceptionMatch, IRExceptionPayload)):
                if instruction.event.name not in live:
                    self._fail(
                        f"Exception event '{self._value(instruction.event)}' "
                        "is borrowed after consumption",
                        rule=("IRV-149", VerifierCategory.LIFECYCLE),
                    )
                continue
            if isinstance(instruction, IRExceptionDestroy):
                self._consume_exception_event(instruction.event, live)
                continue
            if isinstance(instruction, (IRThrow, IRRethrow, IRPropagate)):
                self._consume_exception_event(instruction.event, live)
                if instruction.target is None:
                    if live:
                        self._fail(
                            f"Exceptional unwind from block '{block.name}' "
                            "leaks another owned event",
                            rule=("IRV-149", VerifierCategory.LIFECYCLE),
                        )
                    return []
                return [(instruction.target, set(live))]
            if isinstance(
                instruction,
                (IRInvoke, IRInvokeIndirect, IRInvokeInterface),
            ):
                return [
                    (instruction.normal_target, set(live)),
                    (instruction.exceptional_target, set(live)),
                ]
            if isinstance(instruction, IRJump):
                return [(instruction.target, set(live))]
            if isinstance(instruction, IRBranch):
                return [
                    (instruction.true_target, set(live)),
                    (instruction.false_target, set(live)),
                ]
            if isinstance(instruction, IRReturn):
                if live:
                    names = ", ".join(f"%{name}" for name in sorted(live))
                    self._fail(
                        f"Return from block '{block.name}' leaks owned "
                        f"exception event(s): {names}",
                        rule=("IRV-149", VerifierCategory.LIFECYCLE),
                    )
                return []
        raise AssertionError(f"Verified block '{block.name}' has no terminator")

    def _consume_exception_event(
        self,
        event: IRValue,
        live: set[str],
    ) -> None:
        if event.name not in live:
            self._fail(
                f"Exception event '{self._value(event)}' is consumed more than "
                "once or after propagation",
                rule=("IRV-149", VerifierCategory.LIFECYCLE),
            )
        live.remove(event.name)

    def _verify_exception_structure(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        if type(function.may_throw) is not bool:
            self._fail(
                f"Function '{function.name}' may_throw metadata must be boolean",
                rule=("IRV-130", VerifierCategory.TYPES),
            )

        handler_events: dict[str, IRValue] = {}
        catch_event_names: set[str] = set()
        handler_ids: set[str] = set()
        for block in function.blocks:
            entries = [
                instruction
                for instruction in block.instructions
                if isinstance(instruction, IRCatchEntry)
            ]
            if not entries:
                continue
            if len(entries) != 1 or not isinstance(block.instructions[0], IRCatchEntry):
                self._fail(
                    f"Handler entry in block '{block.name}' must be its first and only catch_entry",
                    rule=("IRV-131", VerifierCategory.CFG),
                )
            entry = entries[0]
            if not isinstance(entry.event.type, ExceptionEventType):
                self._fail(
                    f"Handler '{entry.handler_id}' event must have exception_event type",
                    rule=("IRV-132", VerifierCategory.TYPES),
                )
            if not entry.handler_id or entry.handler_id in handler_ids:
                self._fail(
                    f"Duplicate or empty exception handler id '{entry.handler_id}'",
                    rule=("IRV-133", VerifierCategory.DEFINITIONS),
                )
            handler_ids.add(entry.handler_id)
            if len(set(entry.catch_types)) != len(entry.catch_types):
                self._fail(
                    f"Handler '{entry.handler_id}' contains duplicate catch metadata",
                    rule=("IRV-134", VerifierCategory.INSTRUCTIONS),
                )
            if "Error" in entry.catch_types and entry.catch_types[-1] != "Error":
                self._fail(
                    f"Handler '{entry.handler_id}' has catches after Error",
                    rule=("IRV-135", VerifierCategory.INSTRUCTIONS),
                )
            handler_events[block.name] = entry.event
            if entry.handler_id != "root":
                catch_event_names.add(entry.event.name)

        exceptional_predecessors: dict[str, int] = {
            name: 0 for name in handler_events
        }
        normal_predecessors: dict[str, int] = {
            name: 0 for name in handler_events
        }
        has_exception_ir = False
        for block in function.blocks:
            terminator = block.instructions[-1]
            if isinstance(terminator, (IRInvoke, IRInvokeIndirect, IRInvokeInterface)):
                has_exception_ir = True
                if terminator.normal_target == terminator.exceptional_target:
                    self._fail(
                        "Invoke normal and exceptional successors must be distinct",
                        rule=("IRV-136", VerifierCategory.CFG),
                    )
                if not isinstance(terminator.exception.type, ExceptionEventType):
                    self._fail(
                        "Invoke exception result must have exception_event type",
                        rule=("IRV-137", VerifierCategory.TYPES),
                    )
                expected = handler_events.get(terminator.exceptional_target)
                if expected is None or expected != terminator.exceptional_target_event:
                    self._fail(
                        "Invoke exceptional edge must supply the target handler event",
                        rule=("IRV-138", VerifierCategory.CFG),
                    )
                exceptional_predecessors[terminator.exceptional_target] += 1
                if terminator.normal_target in normal_predecessors:
                    normal_predecessors[terminator.normal_target] += 1
            elif isinstance(terminator, (IRThrow, IRRethrow, IRPropagate)):
                has_exception_ir = True
                if not isinstance(terminator.event.type, ExceptionEventType):
                    self._fail(
                        "Exceptional transfer operand must have exception_event type",
                        rule=("IRV-139", VerifierCategory.TYPES),
                    )
                if (terminator.target is None) != (terminator.target_event is None):
                    self._fail(
                        "Exceptional transfer target and target event must appear together",
                        rule=("IRV-140", VerifierCategory.CFG),
                    )
                if terminator.target is not None:
                    expected = handler_events.get(terminator.target)
                    if expected is None or expected != terminator.target_event:
                        self._fail(
                            "Exceptional transfer must supply the target handler event",
                            rule=("IRV-141", VerifierCategory.CFG),
                        )
                    exceptional_predecessors[terminator.target] += 1
            else:
                for successor in self._successors(block):
                    if successor in normal_predecessors:
                        normal_predecessors[successor] += 1

            for instruction in block.instructions:
                if isinstance(
                    instruction,
                    (
                        IRPackException,
                        IRCatchEntry,
                        IRExceptionMatch,
                        IRExceptionPayload,
                        IRExceptionDestroy,
                    ),
                ):
                    has_exception_ir = True

        for handler, event in handler_events.items():
            if exceptional_predecessors[handler] == 0:
                self._fail(
                    f"Exception handler block '{handler}' is not reachable from an exceptional edge",
                    rule=("IRV-142", VerifierCategory.CFG),
                )
            if normal_predecessors[handler]:
                self._fail(
                    f"Exception handler block '{handler}' has a normal predecessor",
                    rule=("IRV-143", VerifierCategory.CFG),
                )
            if not isinstance(event.type, ExceptionEventType):
                raise AssertionError("handler event type checked above")

        if has_exception_ir and not function.may_throw:
            self._fail(
                f"Function '{function.name}' contains exception IR but may_throw is false",
                rule=("IRV-144", VerifierCategory.CALLS),
            )

        for block in function.blocks:
            consumed_events: set[str] = set()
            for instruction in block.instructions:
                event = (
                    instruction.event
                    if isinstance(
                        instruction,
                        (
                            IRExceptionMatch,
                            IRExceptionPayload,
                            IRExceptionDestroy,
                            IRThrow,
                            IRRethrow,
                            IRPropagate,
                        ),
                    )
                    else None
                )
                if event is not None and event.name in consumed_events:
                    self._fail(
                        f"Exception event '%{event.name}' is used after consumption",
                        rule=("IRV-148", VerifierCategory.LIFECYCLE),
                    )
                if isinstance(instruction, IRRethrow) and (
                    instruction.event.name not in catch_event_names
                ):
                    self._fail(
                        "Rethrow requires an event introduced by an active catch handler",
                        rule=("IRV-147", VerifierCategory.INSTRUCTIONS),
                    )
                if isinstance(
                    instruction,
                    (IRExceptionDestroy, IRThrow, IRRethrow, IRPropagate),
                ):
                    consumed_events.add(instruction.event.name)
                if isinstance(instruction, IRCall) and instruction.builtin is None:
                    if instruction.may_throw_effect:
                        self._fail(
                            "A call marked may_throw must use invoke",
                            rule=("IRV-145", VerifierCategory.CALLS),
                        )
                    callee = self._functions.get(instruction.function)
                    if callee is not None and callee.may_throw:
                        self._fail(
                            f"Call to may_throw function '{callee.name}' must use invoke",
                            rule=("IRV-145", VerifierCategory.CALLS),
                        )
                if isinstance(instruction, IRInvoke):
                    callee = self._functions.get(instruction.function)
                    if callee is None or not callee.may_throw:
                        self._fail(
                            f"Invoke target '{instruction.function}' is not a may_throw function",
                            rule=("IRV-146", VerifierCategory.CALLS),
                        )
                if isinstance(instruction, IRInterfaceCall) and instruction.slot.may_throw:
                    self._fail(
                        f"Interface call to may_throw slot '{instruction.slot.method_id}' must use invoke",
                        rule=("IRV-145", VerifierCategory.CALLS),
                    )
                if isinstance(instruction, IRInvokeInterface) and not instruction.slot.may_throw:
                    self._fail(
                        f"Interface invoke target '{instruction.slot.method_id}' is not may_throw",
                        rule=("IRV-146", VerifierCategory.CALLS),
                    )

    def _verify_borrowed_elements(self, function: IRFunction) -> None:
        borrowed: dict[str, str] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if not isinstance(instruction, (IRArrayGet, IRListGet)):
                    continue
                if instruction.borrowed:
                    if not instruction.borrow_scope:
                        self._fail(
                            "borrow_element requires an iteration scope",
                            rule=("IRV-037", VerifierCategory.BORROWING),
                            primary_location=self._instruction_location(instruction),
                        )
                    if instruction.borrow_scope != block.name:
                        self._fail(
                            f"borrow_element '{self._value(instruction.result)}' is defined "
                            f"outside its declared scope '{instruction.borrow_scope}'",
                            rule=("IRV-038", VerifierCategory.BORROWING),
                            primary_location=self._instruction_location(instruction),
                        )
                    borrowed[instruction.result.name] = instruction.borrow_scope
                elif instruction.borrow_scope is not None:
                    self._fail(
                        "owned collection get cannot declare a borrow scope",
                        rule=("IRV-039", VerifierCategory.BORROWING),
                        primary_location=self._instruction_location(instruction),
                    )

        if not borrowed:
            return
        receiver_fields = {
            IRArraySet: "array",
            IRListSet: "list_value",
            IRListPush: "list_value",
            IRListInsert: "list_value",
            IRListRemoveAt: "list_value",
            IRListPop: "list_value",
            IRListClear: "list_value",
            IRListReverse: "list_value",
            IRSequenceSort: "sequence",
            IRStructSet: "struct",
        }
        for block in function.blocks:
            acquired: set[str] = set()
            for instruction in block.instructions:
                if (
                    isinstance(instruction, IRCall)
                    and instruction.builtin == "__aether_retain"
                ):
                    acquired.update(
                        argument.name
                        for argument in instruction.arguments
                        if argument.name in borrowed
                    )
                if (
                    isinstance(instruction, IRStore)
                    and instruction.value.name in borrowed
                    and self._lifecycle_traits(instruction.value.type).needs_destroy
                    and instruction.value.name not in acquired
                ):
                    self._fail(
                        "Borrowed iteration value cannot be stored as owned without copying",
                        rule=("IRV-040", VerifierCategory.BORROWING),
                    )
                if isinstance(instruction, IRReturn):
                    if instruction.value is not None and instruction.value.name in borrowed:
                        self._fail(
                            "Borrowed iteration value cannot escape its iteration scope without copying",
                            rule=("IRV-041", VerifierCategory.BORROWING),
                        )
                for instruction_type, field_name in receiver_fields.items():
                    if isinstance(instruction, instruction_type):
                        receiver = getattr(instruction, field_name)
                        if receiver.name in borrowed:
                            self._fail(
                                "Cannot mutate through borrowed iteration element",
                                rule=("IRV-042", VerifierCategory.BORROWING),
                            )
                        break

    def _verify_parameters(self, function: IRFunction) -> None:
        seen: set[str] = set()
        for parameter in function.parameters:
            if parameter.name in seen:
                self._fail(
                    f"Duplicate parameter '{parameter.name}' in function '{function.name}'",
                    rule=("IRV-007", VerifierCategory.DEFINITIONS),
                )
            seen.add(parameter.name)
            self._verify_type(
                parameter.type,
                f"parameter '{parameter.name}' of function '{function.name}'",
            )

    def _collect_blocks(self, function: IRFunction) -> dict[str, IRBasicBlock]:
        blocks: dict[str, IRBasicBlock] = {}
        for block in function.blocks:
            if block.name in blocks:
                self._fail(
                    f"Duplicate block '{block.name}' in function '{function.name}'",
                    rule=("IRV-008", VerifierCategory.DEFINITIONS),
                )
            blocks[block.name] = block
        return blocks

    def _verify_block_structure(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        for block in function.blocks:
            if not block.instructions:
                self._fail(
                    f"Block '{block.name}' in function '{function.name}' has no terminator",
                    rule=("IRV-018", VerifierCategory.CFG),
                )

            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, self._TERMINATORS):
                    if index != len(block.instructions) - 1:
                        self._fail(
                            f"Instruction after terminator in block '{block.name}'",
                            rule=("IRV-019", VerifierCategory.CFG),
                        )
                    self._verify_terminator_targets(function, instruction, blocks)
                    break
            else:
                self._fail(
                    f"Block '{block.name}' in function '{function.name}' has no terminator",
                    rule=("IRV-018", VerifierCategory.CFG),
                )

    def _verify_terminator_targets(
        self,
        function: IRFunction,
        instruction: IRInstruction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        if isinstance(instruction, IRJump):
            if instruction.target not in blocks:
                self._fail(
                    f"Unknown jump target '{instruction.target}' in function '{function.name}'",
                    rule=("IRV-020", VerifierCategory.CFG),
                )
            return

        if isinstance(instruction, IRBranch):
            for target in (instruction.true_target, instruction.false_target):
                if target not in blocks:
                    self._fail(
                        f"Unknown branch target '{target}' in function '{function.name}'",
                        rule=("IRV-020", VerifierCategory.CFG),
                    )
            return

        if isinstance(instruction, (IRInvoke, IRInvokeIndirect, IRInvokeInterface)):
            for target in (
                instruction.normal_target,
                instruction.exceptional_target,
            ):
                if target not in blocks:
                    self._fail(
                        f"Unknown invoke target '{target}' in function '{function.name}'",
                        rule=("IRV-020", VerifierCategory.CFG),
                    )
            return

        if isinstance(instruction, (IRThrow, IRRethrow, IRPropagate)):
            if instruction.target is not None and instruction.target not in blocks:
                self._fail(
                    f"Unknown exceptional target '{instruction.target}' in function '{function.name}'",
                    rule=("IRV-020", VerifierCategory.CFG),
                )

    def _collect_value_types(self, function: IRFunction) -> dict[str, IRType]:
        value_types: dict[str, IRType] = {}
        for parameter in function.parameters:
            self._define_value_type(value_types, parameter, function)

        for block in function.blocks:
            for instruction in block.instructions:
                for result in self._instruction_results(instruction):
                    location = self._instruction_location(instruction)
                    self._verify_type(
                        result.type,
                        f"value '{self._value(result)}'",
                        primary_location=location,
                    )
                    self._define_value_type(
                        value_types,
                        result,
                        function,
                        primary_location=location,
                    )

        return value_types

    def _define_value_type(
        self,
        value_types: dict[str, IRType],
        value: IRValue,
        function: IRFunction,
        primary_location: VerifierLocation | None = None,
    ) -> None:
        existing = value_types.get(value.name)
        if existing is not None:
            self._fail(
                f"Duplicate value '{self._value(value)}' in function '{function.name}'",
                rule=("IRV-009", VerifierCategory.DEFINITIONS),
                primary_location=primary_location,
            )
        value_types[value.name] = value.type

    def _collect_slot_types(self, function: IRFunction) -> dict[str, IRType]:
        slot_types: dict[str, IRType] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                for slot in self._instruction_storages(instruction):
                    location = self._instruction_location(instruction)
                    self._verify_type(
                        slot.type,
                        f"slot '{self._value(slot)}'",
                        primary_location=location,
                    )
                    existing = slot_types.get(slot.name)
                    if existing is not None and existing != slot.type:
                        self._fail(
                            f"Slot '{self._value(slot)}' type mismatch: "
                            f"expected {existing}, got {slot.type}",
                            rule=("IRV-010", VerifierCategory.TYPES),
                            primary_location=location,
                        )
                    slot_types[slot.name] = slot.type
        return slot_types

    @staticmethod
    def _instruction_storages(instruction: IRInstruction) -> tuple[IRValue, ...]:
        if isinstance(instruction, IRStore):
            return (instruction.slot,)
        if isinstance(instruction, IRLoad):
            return (instruction.slot,) if isinstance(instruction.slot, IRStorage) else ()
        if isinstance(instruction, IRInitDefault):
            return (instruction.destination,)
        if isinstance(instruction, (IRCopyInit, IRAssign)):
            if isinstance(instruction.source, IRStorage):
                return (instruction.destination, instruction.source)
            return (instruction.destination,)
        if isinstance(instruction, (IRRelocate, IRMoveInit)):
            return (instruction.destination, instruction.source)
        if isinstance(instruction, IRDestroy):
            return (instruction.value,)
        if isinstance(instruction, IRReturn) and instruction.transferred_storage is not None:
            return (instruction.transferred_storage,)
        return ()

    def _verify_reachable_values(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
        value_types: dict[str, IRType],
        slot_types: dict[str, IRType],
    ) -> None:
        entry = _State(
            values=frozenset(parameter.name for parameter in function.parameters),
            slots=frozenset(),
        )
        inputs: dict[str, _State] = {"entry": entry}
        worklist = ["entry"]

        while worklist:
            block_name = worklist.pop(0)
            block = blocks[block_name]
            state = inputs[block_name]
            output = self._transfer_block(
                function,
                block,
                state,
                value_types,
                slot_types,
            )

            for successor in self._successors(block):
                successor_output = self._state_for_successor(
                    block,
                    successor,
                    output,
                )
                existing = inputs.get(successor)
                if existing is not None:
                    lifecycle_slots = {
                        name
                        for name in slot_types
                        if self._is_lifecycle_storage(function, name)
                    }
                    if (existing.slots & lifecycle_slots) != (
                        successor_output.slots & lifecycle_slots
                    ):
                        inconsistent = sorted(
                            (existing.slots ^ successor_output.slots)
                            & lifecycle_slots
                        )[0]
                        self._fail(
                            f"Lifecycle state for storage '%{inconsistent}' is inconsistent "
                            f"across control-flow paths entering block '{successor}'",
                            rule=("IRV-036", VerifierCategory.LIFECYCLE),
                        )
                updated = (
                    successor_output
                    if existing is None
                    else existing.intersect(successor_output)
                )
                if updated != existing:
                    inputs[successor] = updated
                    worklist.append(successor)

        unreachable_state = _State(
            values=frozenset(value_types),
            slots=frozenset(slot_types),
        )
        for block_name, block in blocks.items():
            if block_name not in inputs:
                # Unreachable blocks still get local instruction/type checks, but
                # they have no executable incoming path that can prove slot stores.
                self._transfer_block(
                    function,
                    block,
                    unreachable_state,
                    value_types,
                    slot_types,
                )

    @staticmethod
    def _state_for_successor(
        block: IRBasicBlock,
        successor: str,
        state: _State,
    ) -> _State:
        terminator = block.instructions[-1]
        if not isinstance(
            terminator,
            (IRInvoke, IRInvokeIndirect, IRInvokeInterface),
        ):
            if (
                isinstance(terminator, (IRThrow, IRRethrow, IRPropagate))
                and terminator.target == successor
                and terminator.target_event is not None
            ):
                return _State(
                    state.values | {terminator.target_event.name},
                    state.slots,
                    state.moved,
                    state.destroyed,
                )
            return state

        values = set(state.values)
        if successor == terminator.normal_target:
            values.discard(terminator.exception.name)
            values.discard(terminator.exceptional_target_event.name)
        elif successor == terminator.exceptional_target:
            if terminator.result is not None:
                values.discard(terminator.result.name)
            values.add(terminator.exception.name)
            values.add(terminator.exceptional_target_event.name)
        return _State(
            frozenset(values),
            state.slots,
            state.moved,
            state.destroyed,
        )

    @staticmethod
    def _is_lifecycle_storage(function: IRFunction, name: str) -> bool:
        return any(
            isinstance(instruction, (IRInitDefault, IRCopyInit, IRMoveInit, IRAssign, IRDestroy, IRRelocate))
            and any(
                isinstance(value, IRStorage) and value.name == name
                for value in (
                    getattr(instruction, "destination", None),
                    getattr(instruction, "source", None),
                    getattr(instruction, "value", None),
                )
            )
            for block in function.blocks
            for instruction in block.instructions
        )

    def _transfer_block(
        self,
        function: IRFunction,
        block: IRBasicBlock,
        state: _State,
        value_types: dict[str, IRType],
        slot_types: dict[str, IRType],
    ) -> _State:
        current = state
        for instruction in block.instructions:
            previous_rule = self._active_rule
            previous_location = self._active_location
            previous_instruction = self._active_instruction
            self._active_rule = self._rule_for_instruction(instruction)
            self._active_instruction = instruction
            self._active_location = self._instruction_location(instruction)
            try:
                current = self._transfer_instruction(
                    function,
                    instruction,
                    current,
                    value_types,
                    slot_types,
                )
            finally:
                self._active_rule = previous_rule
                self._active_location = previous_location
                self._active_instruction = previous_instruction
        return current

    @staticmethod
    def _rule_for_instruction(
        instruction: IRInstruction,
    ) -> tuple[str, VerifierCategory]:
        if isinstance(instruction, IRConst):
            invariant_id = "IRV-068" if isinstance(instruction.value, IREnumConstant) else "IRV-069"
            return invariant_id, VerifierCategory.CONSTANTS
        if isinstance(instruction, IRBinaryOp):
            if instruction.operator in {"add", "sub", "mul", "div", "rem", "mod", "pow"}:
                invariant_id = "IRV-070"
            elif instruction.operator in {"eq", "ne"}:
                invariant_id = "IRV-071"
            elif instruction.operator in {"lt", "le", "gt", "ge"}:
                invariant_id = "IRV-072"
            else:
                invariant_id = "IRV-073"
            return invariant_id, VerifierCategory.OPERATORS
        if isinstance(instruction, IRCompareOp):
            invariant_id = "IRV-075" if instruction.aggregate_shape is not None else "IRV-076"
            return invariant_id, VerifierCategory.OPERATORS
        if isinstance(instruction, IRCall):
            if instruction.builtin is None:
                return "IRV-052", VerifierCategory.CALLS
            builtin_rules = {
                PROCESS_ARGS_BUILTIN: "IRV-055",
                RANGE_STEP_NONZERO_BUILTIN: "IRV-056",
                "__aether_string_byte_length": "IRV-057",
                STRING_TRIM_BUILTIN: "IRV-058",
                STRING_SPLIT_BUILTIN: "IRV-059",
                PARSE_INT_BUILTIN: "IRV-060",
                PARSE_DOUBLE_BUILTIN: "IRV-060",
                READ_TEXT_BUILTIN: "IRV-062",
                "io.writeText": "IRV-062",
                "io.writeTextAtomic": "IRV-062",
                "io.appendText": "IRV-062",
                "__aether_retain": "IRV-066",
                "__aether_release": "IRV-066",
                "__aether_interface_copy_owned": "IRV-066",
            }
            invariant_id = builtin_rules.get(instruction.builtin, "IRV-067")
            if instruction.builtin in TEXT_CODEC_BUILTINS:
                invariant_id = "IRV-065"
            return invariant_id, VerifierCategory.BUILTINS

        rules: tuple[tuple[type[IRInstruction], str, VerifierCategory], ...] = (
            (IRLoad, "IRV-033", VerifierCategory.TYPES),
            (IRStore, "IRV-034", VerifierCategory.DATA_FLOW),
            (IRInitDefault, "IRV-044", VerifierCategory.LIFECYCLE),
            (IRCopyInit, "IRV-045", VerifierCategory.LIFECYCLE),
            (IRMoveInit, "IRV-046", VerifierCategory.LIFECYCLE),
            (IRAssign, "IRV-047", VerifierCategory.LIFECYCLE),
            (IRDestroy, "IRV-048", VerifierCategory.LIFECYCLE),
            (IRRelocate, "IRV-049", VerifierCategory.LIFECYCLE),
            (IRUnaryOp, "IRV-074", VerifierCategory.OPERATORS),
            (IRCast, "IRV-077", VerifierCategory.TYPES),
            (IRPrint, "IRV-078", VerifierCategory.INSTRUCTIONS),
            (IRStructNew, "IRV-079", VerifierCategory.STRUCTS),
            (IRClassNew, "IRV-125", VerifierCategory.INSTRUCTIONS),
            (IRClassGet, "IRV-126", VerifierCategory.STRUCTS),
            (IRClassSet, "IRV-127", VerifierCategory.STRUCTS),
            (IRInterfaceConstruct, "IRV-128", VerifierCategory.INSTRUCTIONS),
            (IRInterfaceCall, "IRV-129", VerifierCategory.CALLS),
            (IRStructGet, "IRV-080", VerifierCategory.STRUCTS),
            (IRStructSet, "IRV-081", VerifierCategory.STRUCTS),
            (IRMethodResultNew, "IRV-082", VerifierCategory.METHOD_RESULTS),
            (IRMethodResultReceiver, "IRV-083", VerifierCategory.METHOD_RESULTS),
            (IRMethodResultValue, "IRV-084", VerifierCategory.METHOD_RESULTS),
            (IRArrayNew, "IRV-085", VerifierCategory.COLLECTIONS),
            (IRListNew, "IRV-086", VerifierCategory.COLLECTIONS),
            (IRArrayGet, "IRV-087", VerifierCategory.COLLECTIONS),
            (IRArraySet, "IRV-088", VerifierCategory.COLLECTIONS),
            (IRArraySlice, "IRV-089", VerifierCategory.COLLECTIONS),
            (IRArrayLength, "IRV-090", VerifierCategory.COLLECTIONS),
            (IRArrayCopy, "IRV-091", VerifierCategory.COLLECTIONS),
            (IRListGet, "IRV-092", VerifierCategory.COLLECTIONS),
            (IRListSet, "IRV-093", VerifierCategory.COLLECTIONS),
            (IRListSlice, "IRV-094", VerifierCategory.COLLECTIONS),
            (IRListLength, "IRV-095", VerifierCategory.COLLECTIONS),
            (IRListIsEmpty, "IRV-096", VerifierCategory.COLLECTIONS),
            (IRListCopy, "IRV-097", VerifierCategory.COLLECTIONS),
            (IRListContains, "IRV-098", VerifierCategory.COLLECTIONS),
            (IRListIndexOf, "IRV-099", VerifierCategory.COLLECTIONS),
            (IRListClear, "IRV-100", VerifierCategory.COLLECTIONS),
            (IRListReverse, "IRV-101", VerifierCategory.COLLECTIONS),
            (IRListPush, "IRV-102", VerifierCategory.COLLECTIONS),
            (IRListInsert, "IRV-103", VerifierCategory.COLLECTIONS),
            (IRListPop, "IRV-104", VerifierCategory.COLLECTIONS),
            (IRListRemoveAt, "IRV-105", VerifierCategory.COLLECTIONS),
            (IRSequenceSort, "IRV-106", VerifierCategory.COLLECTIONS),
            (IRVectorNew, "IRV-107", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixNew, "IRV-108", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorAdd, "IRV-109", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorSub, "IRV-109", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorScale, "IRV-110", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorDot, "IRV-111", VerifierCategory.LINEAR_ALGEBRA),
            (IROuterProduct, "IRV-112", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixAdd, "IRV-113", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixSub, "IRV-113", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixScale, "IRV-114", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixMatMul, "IRV-115", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixVectorMul, "IRV-116", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorMatrixMul, "IRV-117", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorGet, "IRV-118", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorSet, "IRV-119", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixGet, "IRV-120", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixSet, "IRV-121", VerifierCategory.LINEAR_ALGEBRA),
            (IRVectorLength, "IRV-122", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixRows, "IRV-123", VerifierCategory.LINEAR_ALGEBRA),
            (IRMatrixColumns, "IRV-124", VerifierCategory.LINEAR_ALGEBRA),
            (IRFunctionRef, "IRV-051", VerifierCategory.CALLS),
            (IRCallIndirect, "IRV-053", VerifierCategory.CALLS),
            (IRBranch, "IRV-021", VerifierCategory.CFG),
            (IRJump, "IRV-020", VerifierCategory.CFG),
            (IRReturn, "IRV-025", VerifierCategory.RETURNS),
        )
        for instruction_type, invariant_id, category in rules:
            if isinstance(instruction, instruction_type):
                return invariant_id, category
        return "IRV-023", VerifierCategory.INSTRUCTIONS

    def _transfer_instruction(
        self,
        function: IRFunction,
        instruction: IRInstruction,
        state: _State,
        value_types: dict[str, IRType],
        slot_types: dict[str, IRType],
    ) -> _State:
        if isinstance(instruction, IRConst):
            self._verify_const(instruction)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRLoad):
            self._require_slot_exists(instruction.slot, slot_types)
            self._require_slot_stored(instruction.slot, state)
            self._require_type(
                instruction.result.type,
                slot_types[instruction.slot.name],
                f"Load type mismatch for slot '{self._value(instruction.slot)}'",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRStore):
            self._require_defined(instruction.value, state, value_types)
            self._require_slot_exists(instruction.slot, slot_types)
            self._require_type(
                instruction.value.type,
                slot_types[instruction.slot.name],
                f"Store type mismatch for slot '{self._value(instruction.slot)}'",
            )
            return _State(
                state.values,
                state.slots | {instruction.slot.name},
                state.moved - {instruction.slot.name},
                state.destroyed - {instruction.slot.name},
            )

        if isinstance(instruction, IRInitDefault):
            self._verify_lifecycle_destination(instruction.destination, slot_types)
            self._require_uninitialized(instruction.destination, state, "init_default")
            traits = self._lifecycle_traits(instruction.destination.type)
            if not traits.supports_default:
                self._fail(
                    f"init_default is not supported for type {instruction.destination.type}: "
                    f"{traits.reason or 'no valid default value'}"
                )
            return self._initialize_storage(state, instruction.destination)

        if isinstance(instruction, IRCopyInit):
            self._verify_lifecycle_destination(instruction.destination, slot_types)
            self._require_uninitialized(instruction.destination, state, "copy_init")
            self._require_lifecycle_source(instruction.source, state, value_types, slot_types)
            self._require_type(
                instruction.source.type,
                instruction.destination.type,
                f"copy_init type mismatch for '{self._value(instruction.destination)}'",
            )
            return self._initialize_storage(state, instruction.destination)

        if isinstance(instruction, IRMoveInit):
            self._verify_lifecycle_destination(instruction.destination, slot_types)
            self._verify_lifecycle_destination(instruction.source, slot_types)
            if instruction.destination.name == instruction.source.name:
                self._fail("move_init source and destination must not be the same storage")
            self._require_uninitialized(instruction.destination, state, "move_init")
            self._require_live_storage(instruction.source, state, "move_init source")
            self._require_type(
                instruction.source.type,
                instruction.destination.type,
                f"move_init type mismatch for '{self._value(instruction.destination)}'",
            )
            initialized = self._initialize_storage(state, instruction.destination)
            return _State(
                initialized.values,
                initialized.slots - {instruction.source.name},
                initialized.moved | {instruction.source.name},
                initialized.destroyed - {instruction.source.name},
            )

        if isinstance(instruction, IRAssign):
            self._verify_lifecycle_destination(instruction.destination, slot_types)
            self._require_live_storage(instruction.destination, state, "assign destination")
            self._require_lifecycle_source(instruction.source, state, value_types, slot_types)
            self._require_type(
                instruction.source.type,
                instruction.destination.type,
                f"assign type mismatch for '{self._value(instruction.destination)}'",
            )
            # Self-assignment is deliberately valid.  Future non-trivial hooks
            # must retain-before-release or detect the alias.
            return state

        if isinstance(instruction, IRDestroy):
            self._verify_lifecycle_destination(instruction.value, slot_types)
            self._require_live_storage(instruction.value, state, "destroy operand")
            return _State(
                state.values,
                state.slots - {instruction.value.name},
                state.moved - {instruction.value.name},
                state.destroyed | {instruction.value.name},
            )

        if isinstance(instruction, IRRelocate):
            self._verify_lifecycle_destination(instruction.destination, slot_types)
            self._verify_lifecycle_destination(instruction.source, slot_types)
            if type(instruction.count) is not int or instruction.count <= 0:
                self._fail(f"relocate count must be positive, got {instruction.count}")
            if instruction.destination.name == instruction.source.name:
                self._fail("relocate source and destination must not be the same storage")
            self._require_uninitialized(instruction.destination, state, "relocate")
            self._require_live_storage(instruction.source, state, "relocate source")
            self._require_type(
                instruction.source.type,
                instruction.destination.type,
                f"relocate type mismatch for '{self._value(instruction.destination)}'",
            )
            traits = self._lifecycle_traits(instruction.source.type)
            if not traits.trivially_relocatable:
                self._fail(
                    f"relocate is not permitted for non-relocatable type "
                    f"{instruction.source.type}: {traits.reason or 'layout forbids relocation'}"
                )
            initialized = self._initialize_storage(state, instruction.destination)
            return _State(
                initialized.values,
                initialized.slots - {instruction.source.name},
                initialized.moved | {instruction.source.name},
                initialized.destroyed - {instruction.source.name},
            )

        if isinstance(instruction, IRBinaryOp):
            self._require_defined(instruction.left, state, value_types)
            self._require_defined(instruction.right, state, value_types)
            result_type = self._binary_result_type(instruction)
            self._require_type(
                instruction.result.type,
                result_type,
                f"Binary op '{instruction.operator}' result type mismatch",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRUnaryOp):
            self._require_defined(instruction.operand, state, value_types)
            self._verify_unary(instruction)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCompareOp):
            self._require_defined(instruction.left, state, value_types)
            self._require_defined(instruction.right, state, value_types)
            result_type = self._compare_result_type(instruction)
            self._require_type(
                instruction.result.type,
                result_type,
                f"Compare op '{instruction.operator}' result type mismatch",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCast):
            self._require_defined(instruction.value, state, value_types)
            self._verify_cast(instruction)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCall):
            self._verify_call(instruction, state, value_types)
            if instruction.result is None:
                return state
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRFunctionRef):
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
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCallIndirect):
            self._verify_indirect_call(instruction, state, value_types)
            if instruction.result is None:
                return state
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRPrint):
            self._require_defined(instruction.value, state, value_types)
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
                    NullableType,
                ),
            ):
                self._fail(
                    "Print value must be a printable scalar or aggregate, "
                    f"got {instruction.value.type}"
                )
            if isinstance(instruction.value.type, NullableType) and not self._is_printable_type(
                instruction.value.type.inner
            ):
                self._fail(
                    f"Nullable print payload type is not printable: {instruction.value.type.inner}"
                )
            if isinstance(instruction.value.type, VectorType):
                if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 1:
                    self._fail("Vector print requires one known length")
            elif isinstance(instruction.value.type, MatrixType):
                if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 2:
                    self._fail("Matrix print requires known rows and columns")
            elif instruction.aggregate_shape is not None:
                self._fail("Scalar print must not carry an aggregate shape")
            return state

        if isinstance(instruction, IRStructNew):
            definition = self._structs.get(instruction.result.type.name) if isinstance(instruction.result.type, StructType) else None
            if definition is None or len(instruction.fields) != len(definition.fields):
                self._fail("Struct new requires a declared struct and all canonical fields")
            for value, (_name, field_type) in zip(instruction.fields, definition.fields):
                self._require_defined(value, state, value_types)
                self._require_type(value.type, field_type, "Struct field type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRClassNew):
            if not isinstance(instruction.result.type, ClassRefType):
                self._fail(
                    f"Class new result must be class reference type, got {instruction.result.type}"
                )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRClassGet):
            self._require_defined(instruction.object, state, value_types)
            definition = (
                self._structs.get(instruction.object.type.name)
                if isinstance(instruction.object.type, ClassRefType)
                else None
            )
            if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                self._fail("Class get requires a declared class and valid canonical field")
            field_name, field_type = definition.fields[instruction.field_index]
            if instruction.field_name != field_name:
                self._fail("Class get field name/index mismatch")
            self._require_type(
                instruction.result.type,
                field_type,
                "Class get result type mismatch",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRClassSet):
            self._require_defined(instruction.object, state, value_types)
            self._require_defined(instruction.value, state, value_types)
            definition = (
                self._structs.get(instruction.object.type.name)
                if isinstance(instruction.object.type, ClassRefType)
                else None
            )
            if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                self._fail("Class set requires a declared class and valid canonical field")
            field_name, field_type = definition.fields[instruction.field_index]
            if instruction.field_name != field_name:
                self._fail("Class set field name/index mismatch")
            self._require_type(
                instruction.value.type,
                field_type,
                "Class set value type mismatch",
            )
            return state

        if isinstance(instruction, IRInterfaceConstruct):
            self._require_defined(instruction.carrier, state, value_types)
            if not isinstance(instruction.result.type, InterfaceType):
                self._fail("Interface construct result must have interface type")
            if not isinstance(instruction.carrier.type, (ClassRefType, StructType)):
                self._fail("Interface construct carrier must be a native class or struct")
            witness = instruction.witness
            expected_kind = (
                "class"
                if isinstance(instruction.carrier.type, ClassRefType)
                else "box"
            )
            if (
                witness.abi_version != INTERFACE_ABI_VERSION
                or witness.carrier_kind != expected_kind
                or witness.interface_id != instruction.result.type.name
                or witness.concrete_type_id != instruction.carrier.type.name
                or witness.symbol
                != witness_symbol(witness.interface_id, witness.concrete_type_id)
            ):
                self._fail("Interface construct has inconsistent witness identity metadata")
            if isinstance(instruction.carrier.type, StructType):
                layout = witness.box_layout
                try:
                    payload_size, payload_alignment = erased_size_alignment(
                        instruction.carrier.type, self._structs
                    )
                except ErasedLayoutError as exc:
                    self._fail(f"Interface box has unsupported erased payload: {exc}")
                if (
                    layout is None
                    or layout.payload_size != payload_size
                    or layout.payload_alignment != payload_alignment
                    or layout.payload_offset
                    != align_up(ERASED_BOX_HEADER_SIZE, payload_alignment)
                    or layout.ownership != "owned_value"
                    or layout.copy_owned_symbol
                    != copy_owned_symbol(
                        witness.interface_id, witness.concrete_type_id
                    )
                    or layout.drop_owned_symbol
                    != drop_owned_symbol(
                        witness.interface_id, witness.concrete_type_id
                    )
                ):
                    self._fail(
                        "Interface box has invalid payload layout or ownership adapters"
                    )
            elif witness.box_layout is not None:
                self._fail("Class-backed interface witness must not declare a box layout")
            if tuple(slot.index for slot in witness.method_slots) != tuple(
                range(len(witness.method_slots))
            ):
                self._fail(
                    "Interface witness method slots must use deterministic contiguous ordering"
                )
            if len({slot.method_id for slot in witness.method_slots}) != len(
                witness.method_slots
            ):
                self._fail("Interface witness method identifiers must be unique")
            for slot in witness.method_slots:
                if not slot.method_id:
                    self._fail("Interface witness method identifier must not be empty")
                expected_thunk = dispatch_thunk_symbol(
                    witness.interface_id,
                    witness.concrete_type_id,
                    slot.index,
                    slot.method_id,
                )
                if (
                    slot.receiver_ownership != "borrowed"
                    or slot.thunk_symbol != expected_thunk
                ):
                    self._fail(
                        f"Interface witness slot '{slot.method_id}' has an "
                        "invalid erased ABI or thunk signature"
                    )
                for parameter_type in slot.parameter_types:
                    self._verify_type(
                        parameter_type,
                        f"parameter metadata for witness slot '{slot.method_id}'",
                    )
                self._verify_type(
                    slot.return_type,
                    f"return metadata for witness slot '{slot.method_id}'",
                )
                method_name = slot.method_id.rsplit(".", 1)[-1]
                implementation = self._functions.get(
                    f"{witness.concrete_type_id}.{method_name}"
                )
                if implementation is None:
                    self._fail(
                        f"Interface witness slot '{slot.method_id}' has no "
                        "native class implementation"
                    )
                concrete_receiver: IRType
                expected_return: IRType
                if witness.carrier_kind == "box":
                    concrete_receiver = StructType(witness.concrete_type_id)
                    expected_return = MethodResultType(
                        concrete_receiver, slot.return_type
                    )
                else:
                    concrete_receiver = ClassRefType(witness.concrete_type_id)
                    expected_return = slot.return_type
                expected_parameters = (concrete_receiver, *slot.parameter_types)
                if (
                    tuple(parameter.type for parameter in implementation.parameters)
                    != expected_parameters
                    or implementation.return_type != expected_return
                ):
                    self._fail(
                        f"Interface witness slot '{slot.method_id}' is "
                        "incompatible with its native thunk target"
                    )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRInterfaceCall):
            self._require_defined(instruction.receiver, state, value_types)
            if not isinstance(instruction.receiver.type, InterfaceType):
                self._fail("Interface call receiver must have interface type")
            expected_prefix = f"{instruction.receiver.type.name}."
            if (
                instruction.slot.index < 0
                or not instruction.slot.method_id.startswith(expected_prefix)
                or instruction.slot.receiver_ownership != "borrowed"
                or instruction.slot.thunk_symbol
            ):
                self._fail("Interface call has invalid erased slot metadata")
            if len(instruction.arguments) != len(
                instruction.slot.parameter_types
            ):
                self._fail("Interface call argument count does not match slot signature")
            for index, (argument, parameter_type) in enumerate(
                zip(instruction.arguments, instruction.slot.parameter_types),
                start=1,
            ):
                self._require_defined(argument, state, value_types)
                self._require_type(
                    argument.type,
                    parameter_type,
                    f"Interface call argument {index} type mismatch",
                )
            if isinstance(instruction.slot.return_type, VoidType):
                if instruction.result is not None:
                    self._fail("Void interface call cannot produce a result")
                return state
            if instruction.result is None:
                self._fail("Non-void interface call must produce a result")
            self._require_type(
                instruction.result.type,
                instruction.slot.return_type,
                "Interface call result type mismatch",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRStructGet):
            self._require_defined(instruction.struct, state, value_types)
            definition = self._structs.get(instruction.struct.type.name) if isinstance(instruction.struct.type, StructType) else None
            if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                self._fail("Struct get requires a valid canonical field")
            self._require_type(instruction.result.type, definition.fields[instruction.field_index][1], "Struct get result type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRStructSet):
            self._require_defined(instruction.struct, state, value_types)
            self._require_defined(instruction.value, state, value_types)
            definition = self._structs.get(instruction.struct.type.name) if isinstance(instruction.struct.type, StructType) else None
            if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                self._fail("Struct set requires a valid canonical field")
            self._require_type(instruction.value.type, definition.fields[instruction.field_index][1], "Struct set value type mismatch")
            self._require_type(instruction.result.type, instruction.struct.type, "Struct set result type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMethodResultNew):
            self._require_defined(instruction.receiver, state, value_types)
            if not isinstance(instruction.result.type, MethodResultType):
                self._fail("Method result requires MethodResultType")
            self._require_type(instruction.receiver.type, instruction.result.type.receiver, "Method receiver type mismatch")
            if isinstance(instruction.result.type.value, VoidType):
                if instruction.value is not None:
                    self._fail("Void method result cannot contain a source value")
            else:
                if instruction.value is None:
                    self._fail("Non-void method result requires a source value")
                self._require_defined(instruction.value, state, value_types)
                self._require_type(instruction.value.type, instruction.result.type.value, "Method value type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMethodResultReceiver):
            self._require_defined(instruction.method_result, state, value_types)
            if not isinstance(instruction.method_result.type, MethodResultType):
                self._fail("Method receiver extraction requires MethodResultType")
            self._require_type(instruction.result.type, instruction.method_result.type.receiver, "Method receiver result mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMethodResultValue):
            self._require_defined(instruction.method_result, state, value_types)
            if not isinstance(instruction.method_result.type, MethodResultType):
                self._fail("Method value extraction requires MethodResultType")
            self._require_type(instruction.result.type, instruction.method_result.type.value, "Method value result mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArrayNew):
            self._verify_array_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListNew):
            self._verify_list_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArrayCopy):
            self._verify_array_copy(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListCopy):
            self._verify_list_copy(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListContains):
            self._verify_list_contains(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListIndexOf):
            self._verify_list_index_of(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListClear):
            self._verify_list_clear(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListPush):
            self._verify_list_push(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListInsert):
            self._verify_list_insert(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListPop):
            self._verify_list_pop(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListRemoveAt):
            self._verify_list_remove_at(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListReverse):
            self._verify_list_reverse(instruction, state, value_types)
            return state
        if isinstance(instruction, IRSequenceSort):
            self._verify_sequence_sort(instruction, state, value_types)
            return state

        if isinstance(instruction, IRVectorNew):
            self._verify_vector_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixNew):
            self._verify_matrix_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorAdd):
            self._verify_vector_add(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorSub):
            self._verify_vector_sub(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorScale):
            self._verify_vector_scale(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorDot):
            self._verify_vector_dot(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IROuterProduct):
            self._verify_outer_product(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixAdd):
            self._verify_matrix_add(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixSub):
            self._verify_matrix_sub(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixScale):
            self._verify_matrix_scale(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixMatMul):
            self._verify_matrix_matmul(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixVectorMul):
            self._verify_matrix_vector_mul(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorMatrixMul):
            self._verify_vector_matrix_mul(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArrayGet):
            self._verify_array_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArraySlice):
            self._verify_array_slice(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListSlice):
            self._verify_list_slice(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListGet):
            self._verify_list_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorGet):
            self._verify_vector_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixGet):
            self._verify_matrix_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorLength):
            self._verify_vector_length(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixRows):
            self._verify_matrix_rows(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixColumns):
            self._verify_matrix_columns(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArraySet):
            self._verify_array_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListSet):
            self._verify_list_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRVectorSet):
            self._verify_vector_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRMatrixSet):
            self._verify_matrix_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRArrayLength):
            self._verify_array_length(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListLength):
            self._verify_list_length(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListIsEmpty):
            self._verify_list_is_empty(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRInvoke):
            proxy = IRCall(
                instruction.function,
                instruction.arguments,
                instruction.result,
                instruction.builtin,
                instruction.source_location,
                True,
            )
            self._verify_call(proxy, state, value_types)
            current = state
            if instruction.result is not None:
                current = self._define_value(current, instruction.result)
            return self._define_value(current, instruction.exception)

        if isinstance(instruction, IRInvokeIndirect):
            proxy = IRCallIndirect(
                instruction.callee,
                instruction.arguments,
                instruction.result,
            )
            self._verify_indirect_call(proxy, state, value_types)
            current = state
            if instruction.result is not None:
                current = self._define_value(current, instruction.result)
            return self._define_value(current, instruction.exception)

        if isinstance(instruction, IRInvokeInterface):
            proxy = IRInterfaceCall(
                instruction.receiver,
                instruction.arguments,
                instruction.slot,
                instruction.result,
            )
            current = self._transfer_instruction(
                function,
                proxy,
                state,
                value_types,
                slot_types,
            )
            return self._define_value(current, instruction.exception)

        if isinstance(instruction, IRCatchEntry):
            if not isinstance(instruction.event.type, ExceptionEventType):
                self._fail("catch_entry event must have exception_event type")
            self._require_defined(instruction.event, state, value_types)
            return state

        if isinstance(instruction, IRPackException):
            self._require_defined(instruction.payload, state, value_types)
            if not isinstance(
                instruction.payload.type,
                (StructType, ClassRefType, InterfaceType),
            ):
                self._fail("exception_pack payload must be a nominal Error value")
            if not isinstance(instruction.result.type, ExceptionEventType):
                self._fail("exception_pack result must have exception_event type")
            if (
                instruction.dynamic_type is not None
                and isinstance(instruction.payload.type, (StructType, ClassRefType))
                and instruction.dynamic_type != instruction.payload.type.name
            ):
                self._fail("exception_pack descriptor does not match payload type")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRExceptionMatch):
            self._require_defined(instruction.event, state, value_types)
            if not isinstance(instruction.event.type, ExceptionEventType):
                self._fail("exception_match operand must have exception_event type")
            if not isinstance(instruction.result.type, BoolType):
                self._fail("exception_match result must be bool")
            if not instruction.catch_type:
                self._fail("exception_match catch type must not be empty")
            if instruction.catch_all != (instruction.catch_type == "Error"):
                self._fail("Only Error may be represented as a catch-all match")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRExceptionPayload):
            self._require_defined(instruction.event, state, value_types)
            if not isinstance(instruction.event.type, ExceptionEventType):
                self._fail("exception_borrow operand must have exception_event type")
            expected_name = getattr(instruction.result.type, "name", None)
            if expected_name != instruction.catch_type:
                self._fail("exception_borrow result type must match its catch descriptor")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRExceptionDestroy):
            self._require_defined(instruction.event, state, value_types)
            if not isinstance(instruction.event.type, ExceptionEventType):
                self._fail("exception_destroy operand must have exception_event type")
            return state

        if isinstance(instruction, (IRThrow, IRRethrow, IRPropagate)):
            self._require_defined(instruction.event, state, value_types)
            if isinstance(instruction, IRRethrow):
                handler_events = {
                    item.event.name
                    for candidate in function.blocks
                    for item in candidate.instructions[:1]
                    if isinstance(item, IRCatchEntry)
                }
                if instruction.event.name not in handler_events:
                    self._fail("rethrow operand is not an active handler event")
            return state

        if isinstance(instruction, IRBranch):
            self._require_defined(instruction.condition, state, value_types)
            if not isinstance(instruction.condition.type, BoolType):
                self._fail("Branch condition must be bool")
            return state

        if isinstance(instruction, IRJump):
            return state

        if isinstance(instruction, IRReturn):
            self._verify_return(function, instruction, state, value_types)
            lifecycle_live = {
                name
                for name in state.slots
                if self._is_lifecycle_storage(function, name)
            }
            transferred = (
                {instruction.transferred_storage.name}
                if instruction.transferred_storage is not None
                else set()
            )
            if instruction.transferred_storage is not None:
                self._verify_lifecycle_destination(
                    instruction.transferred_storage,
                    slot_types,
                )
                self._require_live_storage(
                    instruction.transferred_storage,
                    state,
                    "return transfer",
                )
                if instruction.value is None or instruction.value.type != instruction.transferred_storage.type:
                    self._fail(
                        "return transfer storage must match the returned value type",
                        rule=("IRV-027", VerifierCategory.LIFECYCLE),
                    )
            missing = sorted(lifecycle_live - transferred)
            if missing:
                self._fail(
                    "Return exits with live owning storage lacking cleanup: "
                    + ", ".join(f"%{name}" for name in missing),
                    rule=("IRV-028", VerifierCategory.LIFECYCLE),
                )
            return state

        self._fail(
            f"Unsupported IR instruction '{type(instruction).__name__}'",
            rule=("IRV-023", VerifierCategory.INSTRUCTIONS),
        )

    def _verify_call(
        self,
        instruction: IRCall,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if instruction.builtin is not None:
            for argument in instruction.arguments:
                self._require_defined(argument, state, value_types)
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
            if instruction.builtin == RANGE_STEP_NONZERO_BUILTIN:
                if instruction.function != RANGE_STEP_NONZERO_BUILTIN:
                    self._fail("Range-step guard must retain its canonical semantic name")
                if (
                    instruction.result is not None
                    or len(instruction.arguments) != 1
                    or not isinstance(instruction.arguments[0].type, IntType)
                ):
                    self._fail("Range-step guard requires int -> void")
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
                definition = self._structs.get(expected_name)
                expected_value = IntType() if instruction.builtin == PARSE_INT_BUILTIN else DoubleType()
                if definition is None or len(definition.fields) != 2:
                    self._fail(
                        f"String parsing result '{expected_name}' requires its canonical layout",
                        rule=("IRV-061", VerifierCategory.BUILTINS),
                    )
                if definition.fields[0] != ("value", expected_value):
                    self._fail(
                        f"String parsing result '{expected_name}' has an invalid value field",
                        rule=("IRV-061", VerifierCategory.BUILTINS),
                    )
                if definition.fields[1][0] != "status" or not isinstance(
                    definition.fields[1][1], EnumType
                ):
                    self._fail(
                        f"String parsing result '{expected_name}' has an invalid status field",
                        rule=("IRV-061", VerifierCategory.BUILTINS),
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
                        self._fail(
                            "io.readText result must be FileReadResult",
                            rule=("IRV-063", VerifierCategory.BUILTINS),
                        )
                    definition = self._structs.get(FILE_READ_RESULT_TYPE)
                    if (
                        definition is None
                        or len(definition.fields) != 2
                        or definition.fields[0] != ("content", StringType())
                        or definition.fields[1][0] != "status"
                        or not isinstance(definition.fields[1][1], EnumType)
                        or definition.fields[1][1].name != FILE_STATUS_TYPE
                    ):
                        self._fail(
                            "FileReadResult requires canonical {string, FileStatus} layout",
                            rule=("IRV-063", VerifierCategory.BUILTINS),
                        )
                elif (
                    not isinstance(instruction.result.type, EnumType)
                    or instruction.result.type.name != FILE_STATUS_TYPE
                ):
                    self._fail(
                        "Text-file write result must be FileStatus",
                        rule=("IRV-064", VerifierCategory.BUILTINS),
                    )
                return
            if instruction.builtin in TEXT_CODEC_BUILTINS:
                if instruction.function != instruction.builtin or instruction.result is None:
                    self._fail("Text codec builtin must retain its canonical name and result")
                signatures = {
                    TEXT_BYTE_AT_BUILTIN: ((StringType(), IntType()), IntType()),
                    TEXT_BYTE_SLICE_BUILTIN: ((StringType(), IntType(), IntType()), StringType()),
                    TEXT_FORMAT_INT_BUILTIN: ((IntType(),), StringType()),
                    TEXT_FORMAT_DOUBLE_BUILTIN: ((DoubleType(),), StringType()),
                    TEXT_CONCAT_FRAGMENTS_BUILTIN: ((ListType(StringType()),), StringType()),
                }
                expected_arguments, expected_result = signatures[instruction.builtin]
                if (
                    tuple(argument.type for argument in instruction.arguments) != expected_arguments
                    or instruction.result.type != expected_result
                ):
                    self._fail(f"Text codec builtin '{instruction.builtin}' has an invalid signature")
                return
            if instruction.builtin in {"__aether_retain", "__aether_release"}:
                if instruction.function != instruction.builtin:
                    self._fail("Lifecycle builtin call must retain its canonical semantic name")
                if instruction.result is not None or len(instruction.arguments) != 1:
                    self._fail("Lifecycle builtin requires one argument and no result")
                argument_type = instruction.arguments[0].type
                if not isinstance(
                    argument_type,
                    (
                        StringType,
                        StructType,
                        MethodResultType,
                        ArrayType,
                        ListType,
                        NullableType,
                        ClassRefType,
                        InterfaceType,
                    ),
                ):
                    self._fail(
                        f"Lifecycle builtin does not support argument type {argument_type}"
                    )
                return
            if instruction.builtin == "__aether_interface_copy_owned":
                if (
                    instruction.function != instruction.builtin
                    or len(instruction.arguments) != 1
                    or instruction.result is None
                    or instruction.result.type != instruction.arguments[0].type
                    or not self._lifecycle_traits(
                        instruction.arguments[0].type
                    ).needs_destroy
                ):
                    self._fail(
                        "copy_owned builtin requires one owned argument and "
                        "a same-typed result"
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
            self._require_defined(argument, state, value_types)
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
        instruction: IRCallIndirect,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.callee, state, value_types)
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
            self._require_defined(argument, state, value_types)
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
        instruction: IRArrayNew,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, ArrayType):
            self._fail(f"Array new result must be array type, got {instruction.result.type}")
        for element in instruction.elements:
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Array literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_list_new(
        self,
        instruction: IRListNew,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, ListType):
            self._fail(f"List new result must be list type, got {instruction.result.type}")
        for element in instruction.elements:
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"List literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_new(
        self,
        instruction: IRVectorNew,
        state: _State,
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
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Vector literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_matrix_new(
        self,
        instruction: IRMatrixNew,
        state: _State,
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
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Matrix literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_add(
        self,
        instruction: IRVectorAdd,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, state, value_types, "add")

    def _verify_vector_sub(
        self,
        instruction: IRVectorSub,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, state, value_types, "sub")

    def _verify_vector_binary(
        self,
        instruction: IRVectorAdd | IRVectorSub,
        state: _State,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
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
        instruction: IRVectorScale,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.scalar, state, value_types)
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
        instruction: IRVectorDot,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
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
        instruction: IROuterProduct,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.column, state, value_types)
        self._require_defined(instruction.row, state, value_types)
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
        instruction: IRMatrixAdd,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, state, value_types, "add")

    def _verify_matrix_sub(
        self,
        instruction: IRMatrixSub,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, state, value_types, "sub")

    def _verify_matrix_binary(
        self,
        instruction: IRMatrixAdd | IRMatrixSub,
        state: _State,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
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
        instruction: IRMatrixScale,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.scalar, state, value_types)
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
        instruction: IRMatrixMatMul,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
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
        instruction: IRMatrixVectorMul,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.vector, state, value_types)
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
        instruction: IRVectorMatrixMul,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.matrix, state, value_types)
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
        instruction: IRArrayGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        self._require_defined(instruction.index, state, value_types)
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
        instruction: IRArraySlice,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        self._require_defined(instruction.start, state, value_types)
        self._require_defined(instruction.end, state, value_types)
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

    def _verify_list_get(
        self,
        instruction: IRListGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List get expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.list_value.type.element:
            self._fail(
                f"List get result type mismatch: expected "
                f"{instruction.list_value.type.element}, got {instruction.result.type}"
            )

    def _verify_vector_get(
        self,
        instruction: IRVectorGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector get expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Vector get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.vector.type.element:
            self._fail(
                f"Vector get result type mismatch: expected "
                f"{instruction.vector.type.element}, got {instruction.result.type}"
            )

    def _verify_matrix_get(
        self,
        instruction: IRMatrixGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.row, state, value_types)
        self._require_defined(instruction.column, state, value_types)
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
        instruction: IRArraySet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
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
        instruction: IRVectorSet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
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
        instruction: IRListSet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
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
        instruction: IRMatrixSet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.row, state, value_types)
        self._require_defined(instruction.column, state, value_types)
        self._require_defined(instruction.value, state, value_types)
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
        instruction: IRArrayLength,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array length expects array value, got {instruction.array.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Array length result must be int, got {instruction.result.type}")

    def _verify_list_length(
        self,
        instruction: IRListLength,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List length expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"List length result must be int, got {instruction.result.type}")

    def _verify_array_copy(self, instruction: IRArrayCopy, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.array, state, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array copy expects array value, got {instruction.array.type}")
        self._require_type(instruction.result.type, instruction.array.type, "Array copy result type mismatch")
        assert self._lifecycle is not None
        traits = self._lifecycle.traits(instruction.array.type.element)
        if traits.reason is not None:
            self._fail(
                f"Array copy element type '{instruction.array.type.element}' has no lifecycle: {traits.reason}"
            )

    def _verify_list_copy(self, instruction: IRListCopy, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List copy expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.result.type, instruction.list_value.type, "List copy result type mismatch")
        assert self._lifecycle is not None
        traits = self._lifecycle.traits(instruction.list_value.type.element)
        if traits.reason is not None:
            self._fail(
                f"List copy element type '{instruction.list_value.type.element}' has no lifecycle: {traits.reason}"
            )

    def _verify_list_slice(
        self,
        instruction: IRListSlice,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.start, state, value_types)
        self._require_defined(instruction.end, state, value_types)
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
        assert self._lifecycle is not None
        traits = self._lifecycle.traits(instruction.list_value.type.element)
        if traits.reason is not None:
            self._fail(
                f"List slice element type '{instruction.list_value.type.element}' has no lifecycle: {traits.reason}"
            )

    def _verify_list_contains(self, instruction: IRListContains, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List contains expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.value.type, instruction.list_value.type.element, "List contains value type mismatch")
        if ir_eq_capability(instruction.value.type, self._structs) is None:
            self._fail(f"List contains requires Eq({instruction.value.type})")
        if not isinstance(instruction.result.type, BoolType):
            self._fail(f"List contains result must be bool, got {instruction.result.type}")

    def _verify_list_index_of(self, instruction: IRListIndexOf, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List index_of expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.value.type, instruction.list_value.type.element, "List index_of value type mismatch")
        if ir_eq_capability(instruction.value.type, self._structs) is None:
            self._fail(f"List index_of requires Eq({instruction.value.type})")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"List index_of result must be int, got {instruction.result.type}")

    def _verify_list_reverse(self, instruction: IRListReverse, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List reverse expects list value, got {instruction.list_value.type}")

    def _verify_list_clear(self, instruction: IRListClear, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List clear expects list value, got {instruction.list_value.type}")

    def _verify_list_push(self, instruction: IRListPush, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List push expects list value, got {instruction.list_value.type}")
        self._require_type(
            instruction.value.type,
            instruction.list_value.type.element,
            "List push value type mismatch",
        )

    def _verify_list_insert(self, instruction: IRListInsert, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List insert expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List insert index must be int, got {instruction.index.type}")
        self._require_type(
            instruction.value.type,
            instruction.list_value.type.element,
            "List insert value type mismatch",
        )

    def _verify_list_pop(self, instruction: IRListPop, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List pop expects list value, got {instruction.list_value.type}")
        self._require_type(
            instruction.result.type,
            instruction.list_value.type.element,
            "List pop result type mismatch",
        )

    def _verify_list_remove_at(self, instruction: IRListRemoveAt, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List remove_at expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List remove_at index must be int, got {instruction.index.type}")
        self._require_type(
            instruction.result.type,
            instruction.list_value.type.element,
            "List remove_at result type mismatch",
        )

    def _verify_sequence_sort(self, instruction: IRSequenceSort, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.sequence, state, value_types)
        if not isinstance(instruction.sequence.type, (ArrayType, ListType)):
            self._fail(f"Sequence sort expects array or list value, got {instruction.sequence.type}")
        if not isinstance(instruction.sequence.type.element, (IntType, DoubleType, StringType)):
            self._fail(f"Sequence sort does not support element type {instruction.sequence.type.element}")

    def _verify_list_is_empty(
        self,
        instruction: IRListIsEmpty,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List is_empty expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.result.type, BoolType):
            self._fail(f"List is_empty result must be bool, got {instruction.result.type}")

    def _verify_vector_length(
        self,
        instruction: IRVectorLength,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector length expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Vector length result must be int, got {instruction.result.type}")

    def _verify_matrix_rows(
        self,
        instruction: IRMatrixRows,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix rows expects matrix value, got {instruction.matrix.type}")
        if instruction.rows <= 0:
            self._fail(f"Matrix rows count must be positive, got {instruction.rows}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix rows result must be int, got {instruction.result.type}")

    def _verify_matrix_columns(
        self,
        instruction: IRMatrixColumns,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix columns expects matrix value, got {instruction.matrix.type}")
        if instruction.columns <= 0:
            self._fail(f"Matrix columns count must be positive, got {instruction.columns}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix columns result must be int, got {instruction.result.type}")

    def _verify_return(
        self,
        function: IRFunction,
        instruction: IRReturn,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if instruction.value is None:
            if not isinstance(function.return_type, VoidType):
                self._fail(
                    f"Return type mismatch: expected {function.return_type}, got void"
                )
            return

        if isinstance(instruction.value, IRStorage):
            self._require_live_storage(
                instruction.value,
                state,
                "returned storage",
            )
            self._fail(
                f"Return operand '{self._value(instruction.value)}' is storage; "
                "load or explicitly transfer it as a value",
                rule=("IRV-026", VerifierCategory.RETURNS),
            )
        self._require_defined(instruction.value, state, value_types)
        if instruction.value.type != function.return_type:
            self._fail(
                f"Return type mismatch: expected {function.return_type}, "
                f"got {instruction.value.type}"
            )

    def _verify_all_non_void_paths_return(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        if isinstance(function.return_type, VoidType):
            return

        visited: set[str] = set()
        worklist = ["entry"]
        while worklist:
            block_name = worklist.pop()
            if block_name in visited:
                continue
            visited.add(block_name)

            block = blocks[block_name]
            terminator = block.instructions[-1]
            if isinstance(terminator, IRReturn) and terminator.value is None:
                self._fail(
                    f"Function '{function.name}' may exit without returning a value",
                    rule=("IRV-024", VerifierCategory.RETURNS),
                )

            # Reverse the stable successor order for a LIFO worklist so branch
            # true targets are visited before false targets, matching the
            # verifier's retained deterministic traversal convention.
            worklist.extend(reversed(self._successors(block)))

    def _verify_const(self, instruction: IRConst) -> None:
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
            if not isinstance(result_type, NullableType):
                self._fail(
                    f"Null const requires nullable result type, got {result_type}"
                )
            return
        else:
            return

        if isinstance(result_type, IntType) and not is_aether_int(value):
            self._fail(
                f"Int const {value!r} is outside signed i32 range [{INT_MIN}, {INT_MAX}]"
            )

        if isinstance(expected, tuple):
            if not isinstance(result_type, expected):
                expected_text = " or ".join(str(type_()) for type_ in expected)
                self._fail(
                    f"Const type mismatch: expected {expected_text}, got {result_type}"
                )
            return

        if result_type != expected:
            self._fail(f"Const type mismatch: expected {expected}, got {result_type}")

    def _binary_result_type(self, instruction: IRBinaryOp) -> IRType:
        left = instruction.left.type
        right = instruction.right.type
        operator = instruction.operator

        if operator == "add" and isinstance(left, StringType) and isinstance(right, StringType):
            return StringType()

        if operator in {"add", "sub", "mul", "div", "rem", "mod", "pow"}:
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
            if left != right:
                self._fail(
                    f"Binary op '{operator}' requires explicitly coerced operands, "
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

    def _verify_unary(self, instruction: IRUnaryOp) -> None:
        if instruction.operator == "neg":
            if not isinstance(instruction.operand.type, (FloatType, DoubleType)):
                self._fail(
                    f"Unary op 'neg' requires float/double operand, got {instruction.operand.type}"
                )
            self._require_type(
                instruction.result.type,
                instruction.operand.type,
                "Unary op 'neg' result type mismatch",
            )
            return
        if instruction.operator != "not" or not isinstance(instruction.operand.type, BoolType):
            self._fail(
                f"Unary op 'not' requires bool operand, got {instruction.operand.type}"
            )
        self._require_type(
            instruction.result.type,
            BoolType(),
            "Unary op 'not' result type mismatch",
        )

    def _compare_result_type(self, instruction: IRCompareOp) -> IRType:
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

    def _verify_cast(self, instruction: IRCast) -> None:
        source = instruction.value.type
        target = instruction.result.type
        if isinstance(target, NullableType):
            source_inner = source.inner if isinstance(source, NullableType) else source
            if source_inner == target.inner or (
                isinstance(source_inner, IntType)
                and isinstance(target.inner, (FloatType, DoubleType))
            ):
                return
        if (
            source == target
            and isinstance(source, (IntType, FloatType, DoubleType))
            or
            isinstance(source, IntType)
            and isinstance(target, (FloatType, DoubleType))
            or isinstance(source, (FloatType, DoubleType))
            and isinstance(target, (IntType, FloatType, DoubleType))
            and source != target
        ):
            return
        self._fail(f"Cast requires int/double operands, got {source} to {target}")

    def _is_printable_type(self, type_: IRType) -> bool:
        if isinstance(
            type_,
            (IntType, BoolType, StringType, DoubleType, EnumType),
        ):
            return True
        if isinstance(type_, NullableType):
            return self._is_printable_type(type_.inner)
        if isinstance(type_, (ArrayType, ListType)):
            return self._is_printable_type(type_.element)
        if isinstance(type_, StructType):
            definition = self._structs.get(type_.name)
            return definition is not None and all(
                self._is_printable_type(field_type)
                for _name, field_type in definition.fields
            )
        return False

    def _require_defined(
        self,
        value: IRValue,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        builtin_argument = (
            isinstance(self._active_instruction, IRCall)
            and self._active_instruction.builtin is not None
        )
        if value.name not in state.values:
            self._fail(
                f"Undefined value '{self._value(value)}'",
                rule=(
                    ("IRV-054", VerifierCategory.CALLS)
                    if builtin_argument
                    else ("IRV-029", VerifierCategory.DATA_FLOW)
                ),
            )

        expected_type = value_types.get(value.name)
        if expected_type is not None and expected_type != value.type:
            self._fail(
                f"Value '{self._value(value)}' type mismatch: "
                f"expected {expected_type}, got {value.type}",
                rule=(
                    ("IRV-054", VerifierCategory.CALLS)
                    if builtin_argument
                    else ("IRV-030", VerifierCategory.DATA_FLOW)
                ),
            )

    def _require_slot_exists(
        self,
        slot: IRValue,
        slot_types: dict[str, IRType],
    ) -> None:
        expected_type = slot_types.get(slot.name)
        if expected_type is None:
            self._fail(
                f"Undefined slot '{self._value(slot)}'",
                rule=("IRV-031", VerifierCategory.DATA_FLOW),
            )
        if expected_type != slot.type:
            self._fail(
                f"Slot '{self._value(slot)}' type mismatch: "
                f"expected {expected_type}, got {slot.type}",
                rule=("IRV-031", VerifierCategory.DATA_FLOW),
            )

    def _require_slot_stored(self, slot: IRValue, state: _State) -> None:
        if slot.name not in state.slots:
            if slot.name in state.moved:
                self._fail(
                    f"Use of slot '{self._value(slot)}' after move",
                    rule=("IRV-032", VerifierCategory.DATA_FLOW),
                )
            if slot.name in state.destroyed:
                self._fail(
                    f"Use of slot '{self._value(slot)}' after destroy",
                    rule=("IRV-032", VerifierCategory.DATA_FLOW),
                )
            if isinstance(slot, IRStorage):
                self._fail(
                    f"Slot '{self._value(slot)}' loaded before initialization",
                    rule=("IRV-032", VerifierCategory.DATA_FLOW),
                )
            self._fail(
                f"Slot '{self._value(slot)}' loaded before store",
                rule=("IRV-032", VerifierCategory.DATA_FLOW),
            )

    def _verify_lifecycle_destination(
        self,
        storage: IRStorage,
        slot_types: dict[str, IRType],
    ) -> None:
        if not isinstance(storage, IRStorage):
            self._fail(
                f"Lifecycle destination '{self._value(storage)}' must be IRStorage, "
                f"not a computed value",
                rule=("IRV-043", VerifierCategory.LIFECYCLE),
            )
        self._require_slot_exists(storage, slot_types)
        if isinstance(storage.type, VoidType):
            self._fail(
                "Lifecycle operations cannot target void storage",
                rule=("IRV-043", VerifierCategory.LIFECYCLE),
            )

    def _require_uninitialized(
        self,
        storage: IRStorage,
        state: _State,
        operation: str,
    ) -> None:
        if storage.name in state.slots:
            self._fail(
                f"{operation} destination '{self._value(storage)}' is already alive",
                rule=("IRV-050", VerifierCategory.LIFECYCLE),
            )

    def _require_live_storage(
        self,
        storage: IRStorage,
        state: _State,
        operation: str,
    ) -> None:
        if storage.name in state.slots:
            return
        if storage.name in state.moved:
            self._fail(
                f"{operation} '{self._value(storage)}' is used after move",
                rule=("IRV-050", VerifierCategory.LIFECYCLE),
            )
        if storage.name in state.destroyed:
            self._fail(
                f"{operation} '{self._value(storage)}' is used after destroy",
                rule=("IRV-050", VerifierCategory.LIFECYCLE),
            )
        self._fail(
            f"{operation} '{self._value(storage)}' is used before initialization",
            rule=("IRV-050", VerifierCategory.LIFECYCLE),
        )

    def _require_lifecycle_source(
        self,
        source: IRValue,
        state: _State,
        value_types: dict[str, IRType],
        slot_types: dict[str, IRType],
    ) -> None:
        if isinstance(source, IRStorage):
            self._require_slot_exists(source, slot_types)
            self._require_live_storage(source, state, "lifecycle source")
            return
        self._require_defined(source, state, value_types)

    @staticmethod
    def _initialize_storage(state: _State, storage: IRStorage) -> _State:
        return _State(
            state.values,
            state.slots | {storage.name},
            state.moved - {storage.name},
            state.destroyed - {storage.name},
        )

    def _lifecycle_traits(self, type_: IRType):
        if self._lifecycle is None:
            raise AssertionError("lifecycle registry not initialized")
        return self._lifecycle.traits(type_)

    def _require_type(self, actual: IRType, expected: IRType, message: str) -> None:
        if actual != expected:
            self._fail(f"{message}: expected {expected}, got {actual}")

    @staticmethod
    def _define_value(state: _State, value: IRValue) -> _State:
        return _State(state.values | {value.name}, state.slots)

    @staticmethod
    def _instruction_result(instruction: IRInstruction) -> IRValue | None:
        if isinstance(instruction, (IRConst, IRLoad, IRBinaryOp, IRUnaryOp, IRCompareOp, IRCast, IRFunctionRef)):
            return instruction.result
        if isinstance(instruction, IRCall):
            return instruction.result
        if isinstance(instruction, IRCallIndirect):
            return instruction.result
        if isinstance(instruction, IRInterfaceCall):
            return instruction.result
        if isinstance(
            instruction,
            (
                IRArrayNew,
                IRClassNew,
                IRClassGet,
                IRInterfaceConstruct,
                IRArrayCopy,
                IRArrayGet,
                IRArraySlice,
                IRListNew,
                IRListGet,
                IRListCopy,
                IRListSlice,
                IRListContains,
                IRListIndexOf,
                IRVectorGet,
                IRMatrixGet,
                IRArrayLength,
                IRListLength,
                IRListIsEmpty,
                IRVectorLength,
                IRMatrixRows,
                IRMatrixColumns,
                IRVectorNew,
                IRMatrixNew,
                IRVectorAdd,
                IRVectorDot,
                IROuterProduct,
                IRVectorScale,
                IRMatrixAdd,
                IRMatrixMatMul,
                IRMatrixVectorMul,
                IRVectorMatrixMul,
                IRMatrixScale,
                IRVectorSub,
                IRMatrixSub,
                IRStructNew,
                IRStructGet,
                IRStructSet,
                IRMethodResultNew,
                IRMethodResultReceiver,
                IRMethodResultValue,
            ),
        ):
            return instruction.result
        return None

    @classmethod
    def _instruction_results(
        cls,
        instruction: IRInstruction,
    ) -> tuple[IRValue, ...]:
        if isinstance(instruction, (IRInvoke, IRInvokeIndirect, IRInvokeInterface)):
            return (
                *((instruction.result,) if instruction.result is not None else ()),
                instruction.exception,
            )
        if isinstance(instruction, IRCatchEntry):
            return (instruction.event,)
        if isinstance(
            instruction,
            (IRPackException, IRExceptionMatch, IRExceptionPayload),
        ):
            return (instruction.result,)
        result = cls._instruction_result(instruction)
        return () if result is None else (result,)

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
    def _successors(block: IRBasicBlock) -> tuple[str, ...]:
        terminator = block.instructions[-1]
        if isinstance(terminator, IRJump):
            return (terminator.target,)
        if isinstance(terminator, IRBranch):
            return (terminator.true_target, terminator.false_target)
        if isinstance(terminator, (IRInvoke, IRInvokeIndirect, IRInvokeInterface)):
            return (terminator.normal_target, terminator.exceptional_target)
        if isinstance(terminator, (IRThrow, IRRethrow, IRPropagate)):
            return () if terminator.target is None else (terminator.target,)
        return ()

    def _verify_type(
        self,
        type_: IRType,
        context: str,
        *,
        primary_location: VerifierLocation | None = None,
    ) -> None:
        if not self._is_valid_type(type_):
            self._fail(
                f"Invalid IR type for {context}: {type_!r}",
                rule=("IRV-011", VerifierCategory.TYPES),
                primary_location=primary_location,
            )

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
                ExceptionEventType,
                ComplexType,
                ClassRefType,
                InterfaceType,
                FunctionType,
            ),
        ):
            return True
        if isinstance(type_, NullableType):
            return (
                not isinstance(type_.inner, (NullableType, VoidType))
                and self._is_valid_type(type_.inner)
            )
        if isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
            return self._is_valid_type(type_.element)
        if isinstance(type_, MethodResultType):
            return self._is_valid_type(type_.receiver) and self._is_valid_type(type_.value)
        return False

    @staticmethod
    def _value(value: IRValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    def _fail(
        self,
        message: str,
        *,
        rule: tuple[str, VerifierCategory] | None = None,
        primary_location: VerifierLocation | None = None,
    ) -> NoReturn:
        rule = rule or self._active_rule
        if rule is None:
            raise AssertionError(f"Missing normalized verifier rule for: {message}")
        invariant_id, category = rule
        raise IRVerificationError(
            message,
            normalized_failure=VerifierFailure(
                invariant_id=invariant_id,
                severity=VerifierSeverity.ERROR,
                category=category,
                primary_location=primary_location or self._active_location,
            ),
        )

    @staticmethod
    def _instruction_location(
        instruction: IRInstruction,
    ) -> VerifierLocation | None:
        source_location = getattr(instruction, "source_location", None)
        if source_location is None:
            return None
        return VerifierLocation(
            line=source_location.line,
            column=source_location.column,
            path=source_location.path,
        )
