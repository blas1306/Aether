from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from .model import (
    IRAssign,
    IRArrayCopy,
    IRArrayLength,
    IRArrayNew,
    IRArraySlice,
    IRArraySet,
    IRBasicBlock,
    IRBinaryOp,
    IRConst,
    IRCall,
    IRCallIndirect,
    IRCatchEntry,
    IRClassGet,
    IRClassSet,
    IRClassNew,
    IRInterfaceCall,
    IRInterfaceConstruct,
    IRInvoke,
    IRCompareOp,
    IRCopyInit,
    IRCast,
    IRDestroy,
    IREnumConstant,
    IRFunction,
    IRInitDefault,
    IRInstruction,
    IRListNew,
    IRListCopy,
    IRListGet,
    IRListSlice,
    IRListInsert,
    IRListIsEmpty,
    IRListLength,
    IRListPop,
    IRListRemoveAt,
    IRListPush,
    IRListSet,
    IRArrayGet,
    IRLoad,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRModule,
    IRMoveInit,
    IRPrint,
    IRPropagate,
    IRRelocate,
    IRReturn,
    IRStorage,
    IRStore,
    IRStructDefinition,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRValue,
    IRVectorNew,
)
from .types import (
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
    ExceptionEventType,
)


LIFECYCLE_INSTRUCTIONS = (
    IRInitDefault,
    IRCopyInit,
    IRMoveInit,
    IRAssign,
    IRDestroy,
    IRRelocate,
)


@dataclass(frozen=True)
class LifecycleTraits:
    """Representation-independent lifecycle facts used before LLVM layout."""

    trivially_copyable: bool
    trivially_relocatable: bool
    needs_destroy: bool
    supports_default: bool
    fields: tuple[tuple[str, IRType], ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class LifecycleFieldStep:
    operation: str
    path: tuple[str, ...]
    type: IRType


class LifecycleTypeRegistry:
    """Recursive nominal type classification shared by verifier and lowering.

    String ownership is expanded only after this registry and the verifier have
    checked the generic lifecycle program.
    """

    def __init__(self, structs: list[IRStructDefinition]) -> None:
        self._structs = {definition.name: definition for definition in structs}
        self._cache: dict[IRType, LifecycleTraits] = {}
        self._active: set[str] = set()

    def traits(self, type_: IRType) -> LifecycleTraits:
        cached = self._cache.get(type_)
        if cached is not None:
            return cached
        result = self._compute(type_)
        self._cache[type_] = result
        return result

    def synthesis_plan(
        self,
        type_: IRType,
        operation: str,
    ) -> tuple[LifecycleFieldStep, ...]:
        """Flatten recursive struct lifecycle in its required source order."""

        if operation not in {
            "init_default",
            "copy_init",
            "move_init",
            "assign",
            "destroy",
            "relocate",
            "rollback",
        }:
            raise ValueError(f"unknown lifecycle operation '{operation}'")

        result: list[LifecycleFieldStep] = []

        def visit(current: IRType, path: tuple[str, ...]) -> None:
            traits = self.traits(current)
            fields = traits.fields
            if not fields:
                result.append(LifecycleFieldStep(operation, path, current))
                return
            ordered = reversed(fields) if operation in {"destroy", "rollback"} else fields
            for field_name, field_type in ordered:
                visit(field_type, (*path, field_name))

        visit(type_, ())
        return tuple(result)

    def _compute(self, type_: IRType) -> LifecycleTraits:
        if isinstance(
            type_,
            (IntType, FloatType, DoubleType, BoolType, ComplexType, EnumType),
        ):
            return LifecycleTraits(True, True, False, True)
        if isinstance(type_, StringType):
            return LifecycleTraits(False, True, True, True)
        if isinstance(type_, (ArrayType, ListType)):
            # Collection values are one-word handles, but copying a live handle
            # creates another strong owner.  Relocation remains bitwise because
            # it consumes the source lifetime.
            return LifecycleTraits(False, True, True, True)
        if isinstance(type_, VectorType):
            return LifecycleTraits(
                True,
                True,
                False,
                type_.orientation in {"row", "column"},
                reason=(
                    None
                    if type_.orientation in {"row", "column"}
                    else "vector default requires a concrete orientation"
                ),
            )
        if isinstance(type_, MatrixType):
            return LifecycleTraits(
                True,
                True,
                False,
                False,
                reason="matrix default requires compile-time dimensions",
            )
        if isinstance(type_, FunctionType):
            return LifecycleTraits(True, True, False, False)
        if isinstance(type_, NullableType):
            inner = self.traits(type_.inner)
            if inner.reason is not None and not inner.trivially_relocatable:
                return LifecycleTraits(
                    False,
                    False,
                    False,
                    True,
                    reason=f"nullable payload lifecycle is unavailable: {inner.reason}",
                )
            return LifecycleTraits(
                inner.trivially_copyable,
                True,
                inner.needs_destroy,
                True,
            )
        if isinstance(type_, ClassRefType):
            # A class value is an owning, non-null one-word handle.  Copies
            # retain, moves relocate the handle, and destruction releases it.
            # There is deliberately no implicit/default class value.
            return LifecycleTraits(False, True, True, False)
        if isinstance(type_, InterfaceType):
            # Phase 5.4A admits class carriers only.  The existential owns that
            # carrier while its witness pointer is immortal metadata.
            return LifecycleTraits(False, True, True, False)
        if isinstance(type_, VoidType):
            return LifecycleTraits(False, False, False, False, reason="void has no storage")
        if isinstance(type_, MethodResultType):
            fields = (("receiver", type_.receiver), ("value", type_.value))
            return self._aggregate_traits(fields)
        if isinstance(type_, StructType):
            definition = self._structs.get(type_.name)
            if definition is None:
                return LifecycleTraits(
                    False,
                    False,
                    False,
                    False,
                    reason=f"nominal struct '{type_.name}' has no definition",
                )
            if type_.name in self._active:
                return LifecycleTraits(False, False, False, False, reason="recursive layout")
            self._active.add(type_.name)
            try:
                return self._aggregate_traits(definition.fields)
            finally:
                self._active.remove(type_.name)
        return LifecycleTraits(False, False, False, False, reason="unknown IR type")

    def _aggregate_traits(
        self,
        fields: tuple[tuple[str, IRType], ...],
    ) -> LifecycleTraits:
        children = [self.traits(field_type) for _name, field_type in fields]
        return LifecycleTraits(
            all(child.trivially_copyable for child in children),
            all(child.trivially_relocatable for child in children),
            any(child.needs_destroy for child in children),
            all(child.supports_default for child in children),
            fields,
        )


class LifecycleExpander:
    """Expand verified lifecycle IR immediately before SSA construction."""

    def __init__(self, module: IRModule) -> None:
        self.module = module
        self.registry = LifecycleTypeRegistry(module.structs)
        self._next = 0
        self._used_names: set[str] = set()
        self._owned_values: set[IRValue] = set()
        self._used_values: set[IRValue] = set()
        self._remaining_uses: Counter[IRValue] = Counter()

    def expand(self) -> IRModule:
        functions = [self._expand_function(function) for function in self.module.functions]
        return IRModule(functions, list(self.module.structs))

    def _expand_function(self, function: IRFunction) -> IRFunction:
        self._owned_values = set()
        self._used_values = set()
        self._remaining_uses = Counter()
        # Operand discovery reflects over every instruction field.  Keep its
        # immutable result for this function so the census and ordered rewrite
        # consume the same occurrences without rescanning the instruction.
        operand_occurrences: list[list[tuple[IRValue, ...]]] = []
        for block in function.blocks:
            block_occurrences: list[tuple[IRValue, ...]] = []
            for instruction in block.instructions:
                occurrences = self._instruction_operand_occurrences(instruction)
                block_occurrences.append(occurrences)
                self._used_values.update(occurrences)
                self._remaining_uses.update(occurrences)
                if isinstance(instruction, (IRCall, IRCallIndirect, IRInterfaceCall)) and instruction.result is not None:
                    if self.registry.traits(instruction.result.type).needs_destroy:
                        self._owned_values.add(instruction.result)
                elif (
                    isinstance(instruction, IRBinaryOp)
                    and instruction.operator == "add"
                    and isinstance(instruction.result.type, StringType)
                ):
                    self._owned_values.add(instruction.result)
                elif isinstance(instruction, (IRArrayGet, IRListGet, IRListPop, IRListRemoveAt)):
                    if isinstance(instruction, (IRArrayGet, IRListGet)) and instruction.borrowed:
                        continue
                    if self.registry.traits(instruction.result.type).needs_destroy:
                        self._owned_values.add(instruction.result)
                elif isinstance(
                    instruction,
                    (IRArrayNew, IRArrayCopy, IRListNew, IRListCopy, IRArraySlice, IRListSlice),
                ):
                    if self.registry.traits(instruction.result.type).needs_destroy:
                        self._owned_values.add(instruction.result)
                elif isinstance(instruction, IRStructNew):
                    if self.registry.traits(instruction.result.type).needs_destroy:
                        self._owned_values.add(instruction.result)
                elif isinstance(instruction, IRStructSet):
                    if self.registry.traits(instruction.result.type).needs_destroy:
                        self._owned_values.add(instruction.result)
                elif isinstance(instruction, IRMethodResultNew):
                    if self.registry.traits(instruction.result.type).needs_destroy:
                        self._owned_values.add(instruction.result)
                elif isinstance(instruction, IRClassNew):
                    self._owned_values.add(instruction.result)
                elif isinstance(instruction, IRInterfaceConstruct):
                    self._owned_values.add(instruction.result)
                elif isinstance(instruction, IRClassGet):
                    if self.registry.traits(instruction.result.type).needs_destroy:
                        self._owned_values.add(instruction.result)
            operand_occurrences.append(block_occurrences)
        self._used_names = {parameter.name for parameter in function.parameters}

        def record_names(value: object) -> None:
            if isinstance(value, IRValue):
                self._used_names.add(value.name)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    record_names(item)

        for block in function.blocks:
            for instruction in block.instructions:
                for value in vars(instruction).values():
                    record_names(value)
        numeric_names = [int(name) for name in self._used_names if name.isdigit()]
        self._next = max(numeric_names, default=-1) + 1
        blocks = []
        for block, block_occurrences in zip(function.blocks, operand_occurrences):
            instructions: list[IRInstruction] = []
            for instruction, occurrences in zip(
                block.instructions, block_occurrences
            ):
                instructions.extend(self._expand_instruction(instruction))
                self._remaining_uses.subtract(occurrences)
            blocks.append(IRBasicBlock(block.name, self._fold_trivial_return_transfer(instructions)))
        expanded = IRFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            blocks,
            function.may_throw,
        )
        return self._repair_constructor_invocation_ownership(expanded)

    def _repair_constructor_invocation_ownership(
        self,
        function: IRFunction,
    ) -> IRFunction:
        """Give a pre-invoke constructor receiver one disposition per edge.

        A struct constructor borrows the caller's default receiver and returns
        a distinct updated receiver in ``MethodResultType``.  The caller must
        therefore release its original on both edges.  A class constructor
        mutates the same object that becomes the normal result, so its original
        is released only on the exceptional edge.

        Dedicated exceptional trampolines are required because a handler may
        have several invoke predecessors with different receiver owners.
        """

        used_blocks = {block.name for block in function.blocks}
        cleanup_blocks: list[IRBasicBlock] = []
        replacements: dict[tuple[str, int], IRInvoke] = {}
        normal_releases: dict[str, list[IRCall]] = {}
        cleanup_index = 0

        def unique_block() -> str:
            nonlocal cleanup_index
            while True:
                name = f"constructor.receiver.cleanup{cleanup_index}"
                cleanup_index += 1
                if name not in used_blocks:
                    used_blocks.add(name)
                    return name

        for block in function.blocks:
            for instruction_index, instruction in enumerate(block.instructions):
                if (
                    not isinstance(instruction, IRInvoke)
                    or not instruction.function.endswith(".__ctor")
                    or not instruction.arguments
                ):
                    continue
                receiver = instruction.arguments[0]
                if not isinstance(receiver.type, (StructType, ClassRefType)):
                    raise ValueError(
                        "constructor invoke receiver must be a struct or class owner"
                    )
                if not self.registry.traits(receiver.type).needs_destroy:
                    continue

                if isinstance(receiver.type, StructType):
                    normal_releases.setdefault(instruction.normal_target, []).append(
                        IRCall(
                            "__aether_release",
                            (receiver,),
                            None,
                            "__aether_release",
                        )
                    )

                event = self._temporary(ExceptionEventType())
                cleanup_name = unique_block()
                cleanup_blocks.append(
                    IRBasicBlock(
                        cleanup_name,
                        [
                            IRCatchEntry(
                                event,
                                f"constructor_receiver_cleanup{cleanup_index - 1}",
                                (),
                            ),
                            IRCall(
                                "__aether_release",
                                (receiver,),
                                None,
                                "__aether_release",
                            ),
                            IRPropagate(
                                event,
                                instruction.exceptional_target,
                                instruction.exceptional_target_event,
                            ),
                        ],
                    )
                )
                replacements[(block.name, instruction_index)] = replace(
                    instruction,
                    exceptional_target=cleanup_name,
                    exceptional_target_event=event,
                )

        if not replacements:
            return function

        rewritten: list[IRBasicBlock] = []
        for block in function.blocks:
            instructions = [
                replacements.get((block.name, index), instruction)
                for index, instruction in enumerate(block.instructions)
            ]
            releases = normal_releases.get(block.name, ())
            if releases:
                instructions = [*releases, *instructions]
            rewritten.append(IRBasicBlock(block.name, instructions))
        rewritten.extend(cleanup_blocks)
        return IRFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            rewritten,
            function.may_throw,
        )

    @staticmethod
    def _fold_trivial_return_transfer(
        instructions: list[IRInstruction],
    ) -> list[IRInstruction]:
        """Remove the temporary return slot after all lifecycle is trivial.

        The verified pre-expansion IR has already proved the ownership
        transfer.  For the current ABI, store+load through ``$return`` adds no
        code and folding it restores the primitive IR shape consumed by SSA.
        """

        if len(instructions) < 3:
            return instructions
        store, load, returned = instructions[-3:]
        if not (
            isinstance(store, IRStore)
            and isinstance(store.slot, IRStorage)
            and isinstance(load, IRLoad)
            and load.slot == store.slot
            and hasattr(returned, "transferred_storage")
            and getattr(returned, "transferred_storage") in {None, store.slot}
            and getattr(returned, "value", None) == load.result
        ):
            return instructions
        from .model import IRReturn

        prefix = instructions[:-3]
        if (
            prefix
            and isinstance(prefix[-1], IRLoad)
            and prefix[-1].result == store.value
        ):
            moved_load = prefix[-1]
            return [
                *prefix[:-1],
                IRLoad(load.result, moved_load.slot),
                IRReturn(load.result),
            ]
        return [*prefix, IRReturn(store.value)]

    def _expand_instruction(self, instruction: IRInstruction) -> list[IRInstruction]:
        if isinstance(instruction, IRReturn):
            # Ownership transfer has been discharged into concrete retain/move
            # and cleanup operations.  Keeping the pre-expansion storage marker
            # would make later IR optimization re-verify a slot that is no
            # longer semantically transferred.
            return [IRReturn(instruction.value)]
        if (
            isinstance(instruction, IRCast)
            and isinstance(instruction.result.type, NullableType)
            and self.registry.traits(instruction.result.type).needs_destroy
        ):
            if instruction.value in self._owned_values:
                self._owned_values.remove(instruction.value)
                self._owned_values.add(instruction.result)
                return self._release_unused_result(instruction, [instruction])
            if self._contains_interface(instruction.result.type):
                raw = self._temporary(instruction.result.type)
                cast = IRCast(raw, instruction.value)
                copy = IRCall(
                    "__aether_interface_copy_owned",
                    (raw,),
                    instruction.result,
                    "__aether_interface_copy_owned",
                )
                self._owned_values.add(instruction.result)
                return self._release_unused_result(instruction, [cast, copy])
            emitted: list[IRInstruction] = [
                instruction,
                IRCall(
                    "__aether_retain",
                    (instruction.result,),
                    None,
                    "__aether_retain",
                ),
            ]
            self._owned_values.add(instruction.result)
            return self._release_unused_result(instruction, emitted)
        if (
            isinstance(instruction, IRBinaryOp)
            and instruction.operator == "add"
            and isinstance(instruction.result.type, StringType)
        ):
            emitted: list[IRInstruction] = [instruction]
            for operand in (instruction.left, instruction.right):
                if operand in self._owned_values:
                    self._owned_values.remove(operand)
                    emitted.append(
                        IRCall("__aether_release", (operand,), None, "__aether_release")
                    )
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, IRStructNew):
            emitted: list[IRInstruction] = []
            for field in instruction.fields:
                if not self.registry.traits(field.type).needs_destroy:
                    continue
                if field in self._owned_values:
                    self._owned_values.remove(field)
                else:
                    emitted.append(
                        IRCall("__aether_retain", (field,), None, "__aether_retain")
                    )
            emitted.append(instruction)
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, IRStructSet):
            emitted: list[IRInstruction] = []
            definition = self.registry.traits(instruction.struct.type)
            field_type = definition.fields[instruction.field_index][1]

            # Acquire the replacement before dropping the old field so an
            # assignment such as `value.field = value.field` remains valid.
            if self.registry.traits(instruction.value.type).needs_destroy:
                if instruction.value in self._owned_values:
                    self._owned_values.remove(instruction.value)
                else:
                    emitted.append(
                        IRCall(
                            "__aether_retain",
                            (instruction.value,),
                            None,
                            "__aether_retain",
                        )
                    )

            # The functional struct update produces a new owned aggregate.
            # Copy preserved fields when the input is borrowed, or consume a
            # temporary input owner when one is available.  In both cases the
            # replaced field's old ownership is discharged exactly once.
            if instruction.struct in self._owned_values:
                self._owned_values.remove(instruction.struct)
            elif definition.needs_destroy:
                emitted.append(
                    IRCall(
                        "__aether_retain",
                        (instruction.struct,),
                        None,
                        "__aether_retain",
                    )
                )
            if self.registry.traits(field_type).needs_destroy:
                old_field = self._temporary(field_type)
                emitted.extend(
                    [
                        IRStructGet(
                            old_field,
                            instruction.struct,
                            instruction.field_index,
                            instruction.field_name,
                        ),
                        IRCall(
                            "__aether_release",
                            (old_field,),
                            None,
                            "__aether_release",
                        ),
                    ]
                )
            emitted.append(instruction)
            if definition.needs_destroy:
                self._owned_values.add(instruction.result)
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, IRMethodResultNew):
            emitted: list[IRInstruction] = []
            fields = (
                (instruction.receiver,)
                if instruction.value is None
                else (instruction.receiver, instruction.value)
            )
            for field in fields:
                if not self.registry.traits(field.type).needs_destroy:
                    continue
                if field in self._owned_values:
                    self._owned_values.remove(field)
                else:
                    emitted.append(
                        IRCall(
                            "__aether_retain",
                            (field,),
                            None,
                            "__aether_retain",
                        )
                    )
            emitted.append(instruction)
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, IRMethodResultReceiver):
            if instruction.method_result in self._owned_values:
                self._owned_values.remove(instruction.method_result)
            if self.registry.traits(instruction.result.type).needs_destroy:
                self._owned_values.add(instruction.result)
            return self._release_unused_result(instruction, [instruction])
        if isinstance(instruction, IRMethodResultValue):
            if self.registry.traits(instruction.result.type).needs_destroy:
                self._owned_values.add(instruction.result)
            return self._release_unused_result(instruction, [instruction])
        if isinstance(instruction, IRClassNew):
            return self._release_unused_result(instruction, [instruction])
        if isinstance(instruction, IRInterfaceConstruct):
            emitted: list[IRInstruction] = []
            if isinstance(instruction.carrier.type, StructType):
                emitted.append(instruction)
                if instruction.carrier in self._owned_values:
                    self._owned_values.remove(instruction.carrier)
                    emitted.append(
                        IRCall(
                            "__aether_release",
                            (instruction.carrier,),
                            None,
                            "__aether_release",
                        )
                    )
                return self._release_unused_result(instruction, emitted)
            if instruction.carrier in self._owned_values:
                self._owned_values.remove(instruction.carrier)
            else:
                emitted.append(
                    IRCall(
                        "__aether_retain",
                        (instruction.carrier,),
                        None,
                        "__aether_retain",
                    )
                )
            emitted.append(instruction)
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, IRClassGet):
            emitted: list[IRInstruction] = [instruction]
            if self.registry.traits(instruction.result.type).needs_destroy:
                emitted.append(
                    IRCall(
                        "__aether_retain",
                        (instruction.result,),
                        None,
                        "__aether_retain",
                    )
                )
            if instruction.object in self._owned_values:
                self._owned_values.remove(instruction.object)
                emitted.append(
                    IRCall(
                        "__aether_release",
                        (instruction.object,),
                        None,
                        "__aether_release",
                    )
                )
            return self._release_unused_result(instruction, emitted)
        if (
            isinstance(instruction, IRCompareOp)
            and instruction.operator in {"eq", "ne"}
            and self.registry.traits(instruction.left.type).needs_destroy
        ):
            emitted: list[IRInstruction] = [instruction]
            current_uses = Counter(
                self._instruction_operand_occurrences(instruction)
            )
            for operand in dict.fromkeys((instruction.left, instruction.right)):
                if (
                    operand in self._owned_values
                    and self._remaining_uses[operand] <= current_uses[operand]
                ):
                    self._owned_values.remove(operand)
                    emitted.append(
                        IRCall(
                            "__aether_release",
                            (operand,),
                            None,
                            "__aether_release",
                        )
                    )
            return emitted
        if isinstance(instruction, (IRArrayGet, IRListGet)):
            emitted: list[IRInstruction] = [instruction]
            collection = (
                instruction.array
                if isinstance(instruction, IRArrayGet)
                else instruction.list_value
            )
            if collection in self._owned_values:
                self._owned_values.remove(collection)
                emitted.append(
                    IRCall("__aether_release", (collection,), None, "__aether_release")
                )
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, (IRArrayLength, IRListLength, IRListIsEmpty)):
            emitted = [instruction]
            collection = (
                instruction.array
                if isinstance(instruction, IRArrayLength)
                else instruction.list_value
            )
            if collection in self._owned_values:
                self._owned_values.remove(collection)
                emitted.append(
                    IRCall("__aether_release", (collection,), None, "__aether_release")
                )
            return emitted
        if isinstance(instruction, (IRArrayNew, IRListNew)):
            emitted: list[IRInstruction] = [instruction]
            for element in instruction.elements:
                if element in self._owned_values:
                    self._owned_values.remove(element)
                    emitted.append(
                        IRCall("__aether_release", (element,), None, "__aether_release")
                    )
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, (IRArraySet, IRListSet, IRListPush, IRListInsert)):
            emitted = [instruction]
            value = instruction.value
            if value in self._owned_values:
                self._owned_values.remove(value)
                emitted.append(
                    IRCall("__aether_release", (value,), None, "__aether_release")
                )
            return emitted
        if isinstance(instruction, IRClassSet):
            emitted = [instruction]
            if instruction.value in self._owned_values:
                self._owned_values.remove(instruction.value)
                emitted.append(
                    IRCall(
                        "__aether_release",
                        (instruction.value,),
                        None,
                        "__aether_release",
                    )
                )
            return emitted
        if isinstance(instruction, IRInitDefault):
            emitted, value = self._default_value(instruction.destination.type)
            return [*emitted, IRStore(instruction.destination, value)]
        if isinstance(instruction, IRCopyInit):
            source_instructions, source = self._loaded(instruction.source)
            if not self.registry.traits(source.type).needs_destroy:
                return [*source_instructions, IRStore(instruction.destination, source)]
            if source in self._owned_values:
                self._owned_values.remove(source)
                return [*source_instructions, IRStore(instruction.destination, source)]
            if self._contains_interface(source.type):
                copy = self._temporary(source.type)
                return [
                    *source_instructions,
                    IRCall(
                        "__aether_interface_copy_owned",
                        (source,),
                        copy,
                        "__aether_interface_copy_owned",
                    ),
                    IRStore(instruction.destination, copy),
                ]
            return [
                *source_instructions,
                IRCall("__aether_retain", (source,), None, "__aether_retain"),
                IRStore(instruction.destination, source),
            ]
        if isinstance(instruction, IRAssign):
            source_instructions, source = self._loaded(instruction.source)
            if not self.registry.traits(source.type).needs_destroy:
                return [*source_instructions, IRStore(instruction.destination, source)]
            old = self._temporary(instruction.destination.type)
            retain = []
            if source in self._owned_values:
                self._owned_values.remove(source)
            elif self._contains_interface(source.type):
                copy = self._temporary(source.type)
                return [
                    *source_instructions,
                    IRCall(
                        "__aether_interface_copy_owned",
                        (source,),
                        copy,
                        "__aether_interface_copy_owned",
                    ),
                    IRLoad(old, instruction.destination),
                    IRStore(instruction.destination, copy),
                    IRCall("__aether_release", (old,), None, "__aether_release"),
                ]
            else:
                retain.append(IRCall("__aether_retain", (source,), None, "__aether_retain"))
            return [
                *source_instructions,
                *retain,
                IRLoad(old, instruction.destination),
                IRStore(instruction.destination, source),
                IRCall("__aether_release", (old,), None, "__aether_release"),
            ]
        if isinstance(instruction, (IRCall, IRCallIndirect, IRInterfaceCall)):
            emitted: list[IRInstruction] = [instruction]
            arguments = instruction.arguments
            for index, argument in enumerate(arguments):
                if (
                    isinstance(instruction, IRCall)
                    and instruction.function.endswith(".__ctor")
                    and index == 0
                ):
                    # The constructor borrows `this`; the allocation remains
                    # the owned result of the surrounding construction.
                    continue
                if argument in self._owned_values:
                    self._owned_values.remove(argument)
                    emitted.append(
                        IRCall("__aether_release", (argument,), None, "__aether_release")
                    )
            if (
                isinstance(instruction, IRCall)
                and instruction.function.endswith(".__ctor")
                and instruction.arguments
                and isinstance(instruction.arguments[0].type, StructType)
                and self.registry.traits(instruction.arguments[0].type).needs_destroy
            ):
                emitted.append(
                    IRCall(
                        "__aether_release",
                        (instruction.arguments[0],),
                        None,
                        "__aether_release",
                    )
                )
            if (
                isinstance(instruction, IRInterfaceCall)
                and instruction.receiver in self._owned_values
            ):
                self._owned_values.remove(instruction.receiver)
                emitted.append(
                    IRCall(
                        "__aether_release",
                        (instruction.receiver,),
                        None,
                        "__aether_release",
                    )
                )
            return self._release_unused_result(instruction, emitted)
        if isinstance(instruction, IRPrint):
            emitted = [instruction]
            if instruction.value in self._owned_values:
                self._owned_values.remove(instruction.value)
                emitted.append(
                    IRCall(
                        "__aether_release",
                        (instruction.value,),
                        None,
                        "__aether_release",
                    )
                )
            return emitted
        if isinstance(instruction, IRMoveInit):
            temporary = self._temporary(instruction.source.type)
            result = [
                IRLoad(temporary, instruction.source),
                IRStore(instruction.destination, temporary),
            ]
            traits = self.registry.traits(instruction.source.type)
            if traits.needs_destroy and traits.supports_default:
                defaults, empty = self._default_value(instruction.source.type)
                result.extend((*defaults, IRStore(instruction.source, empty)))
            return result
        if isinstance(instruction, IRRelocate):
            temporary = self._temporary(instruction.source.type)
            return [
                IRLoad(temporary, instruction.source),
                IRStore(instruction.destination, temporary),
            ]
        if isinstance(instruction, IRDestroy):
            if not self.registry.traits(instruction.value.type).needs_destroy:
                return []
            value = self._temporary(instruction.value.type)
            return [
                IRLoad(value, instruction.value),
                IRCall("__aether_release", (value,), None, "__aether_release"),
            ]
        return self._release_unused_result(instruction, [instruction])

    def _release_unused_result(
        self,
        instruction: IRInstruction,
        emitted: list[IRInstruction],
    ) -> list[IRInstruction]:
        result = getattr(instruction, "result", None)
        if (
            isinstance(result, IRValue)
            and result in self._owned_values
            and result not in self._used_values
        ):
            self._owned_values.remove(result)
            emitted.append(IRCall("__aether_release", (result,), None, "__aether_release"))
        return emitted

    @staticmethod
    def _instruction_operand_occurrences(
        instruction: IRInstruction,
    ) -> tuple[IRValue, ...]:
        operands: list[IRValue] = []

        def visit(value: object) -> None:
            if isinstance(value, IRValue):
                operands.append(value)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    visit(item)

        for name, value in vars(instruction).items():
            if name in {"result", "destination", "source_location"}:
                continue
            visit(value)
        return tuple(operands)

    def _loaded(self, source: IRValue) -> tuple[list[IRInstruction], IRValue]:
        if not isinstance(source, IRStorage):
            return [], source
        temporary = self._temporary(source.type)
        return [IRLoad(temporary, source)], temporary

    def _default_value(self, type_: IRType) -> tuple[list[IRInstruction], IRValue]:
        instructions: list[IRInstruction] = []
        if isinstance(type_, StructType):
            traits = self.registry.traits(type_)
            values = []
            for _name, field_type in traits.fields:
                field_instructions, field_value = self._default_value(field_type)
                instructions.extend(field_instructions)
                values.append(field_value)
            result = self._temporary(type_)
            instructions.append(IRStructNew(result, tuple(values)))
            return instructions, result
        if isinstance(type_, ArrayType):
            result = self._temporary(type_)
            return [IRArrayNew(result, ())], result
        if isinstance(type_, ListType):
            result = self._temporary(type_)
            return [IRListNew(result, ())], result
        if isinstance(type_, NullableType):
            result = self._temporary(type_)
            return [IRConst(result, None)], result
        if isinstance(type_, VectorType):
            result = self._temporary(type_)
            return [IRVectorNew(result, (), type_.orientation)], result
        if isinstance(type_, EnumType):
            if not type_.variants:
                raise ValueError(f"enum '{type_.name}' has no default variant")
            result = self._temporary(type_)
            value = IREnumConstant(type_.name, type_.variants[0], 0, 0)
            return [IRConst(result, value)], result
        if isinstance(type_, BoolType):
            literal: object = False
        elif isinstance(type_, StringType):
            literal = ""
        elif isinstance(type_, (DoubleType, FloatType, ComplexType)):
            literal = 0.0
        elif isinstance(type_, IntType):
            literal = 0
        else:
            raise ValueError(f"type '{type_}' has no lifecycle default")
        result = self._temporary(type_)
        return [IRConst(result, literal)], result

    def _temporary(self, type_: IRType) -> IRValue:
        while True:
            name = str(self._next)
            self._next += 1
            if name not in self._used_names:
                self._used_names.add(name)
                return IRValue(name, type_)

    def _contains_interface(
        self,
        type_: IRType,
        active: frozenset[str] = frozenset(),
    ) -> bool:
        if isinstance(type_, InterfaceType):
            return True
        if isinstance(type_, NullableType):
            return self._contains_interface(type_.inner, active)
        if isinstance(type_, MethodResultType):
            return self._contains_interface(
                type_.receiver, active
            ) or self._contains_interface(type_.value, active)
        if isinstance(type_, StructType) and type_.name not in active:
            traits = self.registry.traits(type_)
            nested = active | {type_.name}
            return any(
                self._contains_interface(field_type, nested)
                for _name, field_type in traits.fields
            )
        return False


def expand_lifecycle(module: IRModule) -> IRModule:
    # Compiler pipelines may receive an already-expanded module (for example
    # IR optimization followed by SSA construction).  Internal ARC calls are
    # emitted only by this pass; seeing one makes expansion idempotent and
    # avoids treating already-transferred collection temporaries as owners a
    # second time.
    if any(
        isinstance(instruction, IRCall)
        and instruction.builtin
        in {
            "__aether_retain",
            "__aether_release",
            "__aether_interface_copy_owned",
        }
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ):
        return module
    return LifecycleExpander(module).expand()
