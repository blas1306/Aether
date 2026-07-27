from __future__ import annotations

from dataclasses import dataclass

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
    IRModule,
    IRMoveInit,
    IRPrint,
    IRRelocate,
    IRReturn,
    IRStorage,
    IRStore,
    IRStructDefinition,
    IRStructNew,
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
        if isinstance(type_, (ClassRefType, InterfaceType)):
            return LifecycleTraits(
                False,
                False,
                False,
                False,
                reason=f"lifecycle layout for '{type_}' is not defined",
            )
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

    def expand(self) -> IRModule:
        functions = [self._expand_function(function) for function in self.module.functions]
        return IRModule(functions, list(self.module.structs))

    def _expand_function(self, function: IRFunction) -> IRFunction:
        self._owned_values = set()
        self._used_values = set()
        for block in function.blocks:
            for instruction in block.instructions:
                self._used_values.update(self._instruction_operands(instruction))
                if isinstance(instruction, (IRCall, IRCallIndirect)) and instruction.result is not None:
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
        self._used_names = {parameter.name for parameter in function.parameters}
        for block in function.blocks:
            for instruction in block.instructions:
                result = getattr(instruction, "result", None)
                if isinstance(result, IRValue):
                    self._used_names.add(result.name)
        numeric_names = [int(name) for name in self._used_names if name.isdigit()]
        self._next = max(numeric_names, default=-1) + 1
        blocks = []
        for block in function.blocks:
            instructions: list[IRInstruction] = []
            for instruction in block.instructions:
                instructions.extend(self._expand_instruction(instruction))
            blocks.append(IRBasicBlock(block.name, self._fold_trivial_return_transfer(instructions)))
        return IRFunction(function.name, list(function.parameters), function.return_type, blocks)

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
            emitted: list[IRInstruction] = [instruction]
            if instruction.value in self._owned_values:
                self._owned_values.remove(instruction.value)
            else:
                emitted.append(
                    IRCall(
                        "__aether_retain",
                        (instruction.result,),
                        None,
                        "__aether_retain",
                    )
                )
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
            else:
                retain.append(IRCall("__aether_retain", (source,), None, "__aether_retain"))
            return [
                *source_instructions,
                *retain,
                IRLoad(old, instruction.destination),
                IRStore(instruction.destination, source),
                IRCall("__aether_release", (old,), None, "__aether_release"),
            ]
        if isinstance(instruction, (IRCall, IRCallIndirect)):
            emitted: list[IRInstruction] = [instruction]
            for argument in instruction.arguments:
                if argument in self._owned_values:
                    self._owned_values.remove(argument)
                    emitted.append(
                        IRCall("__aether_release", (argument,), None, "__aether_release")
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
            if self.registry.traits(instruction.source.type).needs_destroy:
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
    def _instruction_operands(instruction: IRInstruction) -> set[IRValue]:
        operands: set[IRValue] = set()

        def visit(value: object) -> None:
            if isinstance(value, IRValue):
                operands.add(value)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    visit(item)

        for name, value in vars(instruction).items():
            if name in {"result", "destination", "source_location"}:
                continue
            visit(value)
        return operands

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


def expand_lifecycle(module: IRModule) -> IRModule:
    # Compiler pipelines may receive an already-expanded module (for example
    # IR optimization followed by SSA construction).  Internal ARC calls are
    # emitted only by this pass; seeing one makes expansion idempotent and
    # avoids treating already-transferred collection temporaries as owners a
    # second time.
    if any(
        isinstance(instruction, IRCall)
        and instruction.builtin in {"__aether_retain", "__aether_release"}
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ):
        return module
    return LifecycleExpander(module).expand()
