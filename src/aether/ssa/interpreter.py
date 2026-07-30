from __future__ import annotations

from dataclasses import fields
from typing import Any

from aether.ir import model as ir_model
from aether.ir.interpreter import IRInterpreter
from aether.ir.model import (
    IRBasicBlock,
    IRFunction,
    IRInstruction,
    IRModule,
    IRParameter,
    IRStorage,
    IRValue,
)
from aether.ir.types import ExceptionEventType

from .model import (
    SSABasicBlock,
    SSABranch,
    SSACatchEntry,
    SSAFunction,
    SSAInstruction,
    SSAInvoke,
    SSAInvokeIndirect,
    SSAInvokeInterface,
    SSAJump,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAPropagate,
    SSARethrow,
    SSAReturn,
    SSAThrow,
    SSAValue,
)
from .verifier import SSAVerifier


class SSAInterpreter:
    """Execute verified SSA without selecting a native exception ABI.

    The execution adapter translates value-identical SSA operations to the
    authoritative Initial IR interpreter. Phi selection is materialized in
    deterministic per-edge interpreter-only trampolines; exception operations
    and invoke control flow remain explicit throughout the translation.
    """

    def __init__(self, module: SSAModule) -> None:
        SSAVerifier(module).verify()
        self.module = module
        self._ir_interpreter = IRInterpreter(_module_to_ir(module))

    @property
    def output(self) -> str:
        return self._ir_interpreter.output

    def call(self, function_name: str, arguments: list[Any] | None = None) -> Any:
        return self._ir_interpreter.call(
            function_name, () if arguments is None else arguments
        )


def _module_to_ir(module: SSAModule) -> IRModule:
    return IRModule(
        [_function_to_ir(function) for function in module.functions],
        list(module.structs),
    )


def _function_to_ir(function: SSAFunction) -> IRFunction:
    blocks = {block.name: block for block in function.blocks}
    handler_events = {
        block.name: entry.event
        for block in function.blocks
        if isinstance(
            (
                entry := next(
                    (
                        instruction
                        for instruction in block.instructions
                        if not isinstance(instruction, SSAPhi)
                    ),
                    None,
                )
            ),
            SSACatchEntry,
        )
    }
    handler_blocks = set(handler_events)
    phis = {
        block.name: tuple(
            instruction
            for instruction in block.instructions
            if isinstance(instruction, SSAPhi)
        )
        for block in function.blocks
    }

    edge_trampolines: dict[tuple[str, str], str] = {}
    used_names = set(blocks)
    for source in function.blocks:
        for target in _successors(source):
            if not phis.get(target):
                continue
            base = f"{source.name}.to.{target}.phi"
            name = base
            suffix = 1
            while name in used_names:
                name = f"{base}.{suffix}"
                suffix += 1
            used_names.add(name)
            edge_trampolines[(source.name, target)] = name
            if target in handler_events:
                handler_events[name] = SSAValue(
                    f"$ssa.edge.event.{name}",
                    ExceptionEventType(),
                )

    translated: list[IRBasicBlock] = []
    trampolines: list[IRBasicBlock] = []
    for block in function.blocks:
        instructions: list[IRInstruction] = []
        catch_entry = next(
            (
                instruction
                for instruction in block.instructions
                if isinstance(instruction, SSACatchEntry)
            ),
            None,
        )
        if catch_entry is not None:
            instructions.append(
                _instruction_to_ir(
                    catch_entry,
                    block.name,
                    edge_trampolines,
                    handler_events,
                )
            )
        for phi in phis[block.name]:
            instructions.append(
                ir_model.IRLoad(
                    _ir_value(phi.result),
                    _phi_storage(block.name, phi.result),
                )
            )
        for instruction in block.instructions:
            if isinstance(instruction, (SSAPhi, SSACatchEntry)):
                continue
            instructions.append(
                _instruction_to_ir(
                    instruction,
                    block.name,
                    edge_trampolines,
                    handler_events,
                )
            )
        translated.append(IRBasicBlock(block.name, instructions))

        for target in _successors(block):
            trampoline_name = edge_trampolines.get((block.name, target))
            if trampoline_name is None:
                continue
            stores = []
            for phi in phis[target]:
                incoming = next(
                    value
                    for predecessor, value in phi.incoming
                    if predecessor == block.name
                )
                stores.append(
                    ir_model.IRStore(
                        _phi_storage(target, phi.result),
                        _ir_value(incoming),
                    )
                )
            if target in handler_blocks:
                edge_event = handler_events[trampoline_name]
                stores.insert(
                    0,
                    ir_model.IRCatchEntry(
                        _ir_value(edge_event),
                        f"ssa_edge_{trampoline_name}",
                        (),
                    ),
                )
                stores.append(
                    ir_model.IRPropagate(
                        _ir_value(edge_event),
                        target,
                        _ir_value(handler_events[target]),
                    )
                )
            else:
                stores.append(ir_model.IRJump(target))
            trampolines.append(IRBasicBlock(trampoline_name, stores))

    return IRFunction(
        function.name,
        [
            IRParameter(parameter.name, parameter.type)
            for parameter in function.parameters
        ],
        function.return_type,
        [*translated, *trampolines],
        function.may_throw,
    )


def _instruction_to_ir(
    instruction: SSAInstruction,
    source_block: str,
    trampolines: dict[tuple[str, str], str],
    handler_events: dict[str, SSAValue],
) -> IRInstruction:
    def target(name: str) -> str:
        return trampolines.get((source_block, name), name)

    if isinstance(instruction, SSAInvoke):
        exceptional_target = target(instruction.exceptional_target)
        return ir_model.IRInvoke(
            instruction.function,
            tuple(_ir_value(value) for value in instruction.arguments),
            None if instruction.result is None else _ir_value(instruction.result),
            _ir_value(instruction.exception),
            target(instruction.normal_target),
            exceptional_target,
            _ir_value(handler_events[exceptional_target]),
            instruction.builtin,
            instruction.source_location,
        )
    if isinstance(instruction, SSAInvokeIndirect):
        exceptional_target = target(instruction.exceptional_target)
        return ir_model.IRInvokeIndirect(
            _ir_value(instruction.callee),
            tuple(_ir_value(value) for value in instruction.arguments),
            None if instruction.result is None else _ir_value(instruction.result),
            _ir_value(instruction.exception),
            target(instruction.normal_target),
            exceptional_target,
            _ir_value(handler_events[exceptional_target]),
        )
    if isinstance(instruction, SSAInvokeInterface):
        exceptional_target = target(instruction.exceptional_target)
        return ir_model.IRInvokeInterface(
            _ir_value(instruction.receiver),
            tuple(_ir_value(value) for value in instruction.arguments),
            instruction.slot,
            None if instruction.result is None else _ir_value(instruction.result),
            _ir_value(instruction.exception),
            target(instruction.normal_target),
            exceptional_target,
            _ir_value(handler_events[exceptional_target]),
        )
    if isinstance(instruction, (SSAThrow, SSARethrow, SSAPropagate)):
        ir_type = {
            SSAThrow: ir_model.IRThrow,
            SSARethrow: ir_model.IRRethrow,
            SSAPropagate: ir_model.IRPropagate,
        }[type(instruction)]
        if instruction.target is None:
            return ir_type(_ir_value(instruction.event))
        exceptional_target = target(instruction.target)
        return ir_type(
            _ir_value(instruction.event),
            exceptional_target,
            _ir_value(handler_events[exceptional_target]),
        )
    if isinstance(instruction, SSAJump):
        return ir_model.IRJump(target(instruction.target))
    if isinstance(instruction, SSABranch):
        return ir_model.IRBranch(
            _ir_value(instruction.condition),
            target(instruction.true_target),
            target(instruction.false_target),
        )
    if isinstance(instruction, SSAReturn):
        return ir_model.IRReturn(
            None if instruction.value is None else _ir_value(instruction.value)
        )

    ir_name = f"IR{type(instruction).__name__[3:]}"
    ir_type = getattr(ir_model, ir_name, None)
    if ir_type is None:
        raise TypeError(
            f"SSA interpreter has no Initial IR equivalent for "
            f"{type(instruction).__name__}"
        )
    arguments = {
        field.name: _to_ir_value(getattr(instruction, field.name))
        for field in fields(instruction)
    }
    return ir_type(**arguments)


def _to_ir_value(value: object) -> object:
    if isinstance(value, SSAValue):
        return _ir_value(value)
    if isinstance(value, tuple):
        return tuple(_to_ir_value(item) for item in value)
    if isinstance(value, list):
        return [_to_ir_value(item) for item in value]
    return value


def _ir_value(value: SSAValue) -> IRValue:
    if isinstance(value, SSAParameter):
        return IRParameter(value.name, value.type)
    return IRValue(value.name, value.type)


def _phi_storage(block_name: str, value: SSAValue) -> IRStorage:
    return IRStorage(f"$ssa.phi.{block_name}.{value.name}", value.type)


def _successors(block: SSABasicBlock) -> tuple[str, ...]:
    terminator = block.instructions[-1]
    if isinstance(terminator, SSAJump):
        return (terminator.target,)
    if isinstance(terminator, SSABranch):
        return (terminator.true_target, terminator.false_target)
    if isinstance(
        terminator,
        (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface),
    ):
        return (terminator.normal_target, terminator.exceptional_target)
    if isinstance(terminator, (SSAThrow, SSARethrow, SSAPropagate)):
        return () if terminator.target is None else (terminator.target,)
    return ()
