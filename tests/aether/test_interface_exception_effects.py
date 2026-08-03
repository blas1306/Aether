from __future__ import annotations

from dataclasses import replace

import pytest

from aether.backend.llvm import LLVMBackend
from aether.errors import AetherTypeError
from aether.exception_effects import analyze_exception_effects
from aether.interface_abi import dispatch_thunk_symbol
from aether.ir import (
    IRInterfaceCall,
    IRInterfaceConstruct,
    IRInvokeInterface,
    IRLowerer,
    IRVerificationError,
    IRVerifier,
)
from aether.ir.dto import ir_module_from_json, ir_module_to_json
from aether.pipeline import parse_source
from aether.ssa import (
    GeneralSSABuilder,
    SSAInterfaceCall,
    SSAInvokeInterface,
    SSAVerificationError,
    SSAVerifier,
    ssa_module_from_json,
    ssa_module_to_json,
)
from aether.typechecker import TypeChecker


SOURCE = """
interface Action {
    void execute();
    Action next();
    string label();
}

interface View {
    string view();
}

interface Named {
    string name();
}

struct DispatchError implements Error {
    string? detail;
    string message() { return "dispatch"; }
}

struct Quiet implements Action {
    void execute() { }
    Action next() { return this; }
    string label() { return "quiet"; }
}

class Loud implements Action {
    public void execute() { throw DispatchError(null); }
    public Action next() { return this; }
    public string label() { return "loud"; }
}

struct Multi implements View, Named {
    string text;
    string view() { return text; }
    string name() { return text; }
}

class ClassView implements View {
    string text;
    public string view() { return text; }
}

Action identity(Action value) { return value; }

void nested(Action value) {
    identity(value).next().execute();
}

void useAction(Action value) {
    value.execute();
    println(value.label());
}

void useView(View value) {
    println(value.view());
}

void useName(Named value) { println(value.name()); }

void renderError(Error error) { println(error.message()); }

Action quietAction() { return Quiet(); }
Action loudAction() { return Loud(); }
View multiView() { return Multi("multi"); }
Named multiName() { return Multi("multi"); }
View classView() { return ClassView("class"); }

int main() { return 0; }
"""


def _lower():
    program = parse_source(SOURCE)
    TypeChecker().check(program)
    initial = IRLowerer().lower(program)
    IRVerifier(initial).verify()
    ssa = GeneralSSABuilder().build(initial)
    SSAVerifier(ssa).verify()
    return program, initial, ssa


def _instructions(module, instruction_type):
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, instruction_type)
    ]


def test_semantic_effect_summary_is_the_interface_dispatch_authority() -> None:
    program = parse_source(SOURCE)
    TypeChecker().check(program)
    summary = analyze_exception_effects(program)

    assert summary.interface_slot_may_throw("Action.execute")
    assert not summary.interface_slot_may_throw("Action.next")
    assert not summary.interface_slot_may_throw("Action.label")
    assert not summary.interface_slot_may_throw("View.view")
    assert not summary.interface_slot_may_throw("Named.name")
    assert not summary.interface_slot_may_throw("Error.message")
    assert summary.function_may_throw("Loud.execute")
    assert summary.function_may_throw("nested")
    assert summary.function_may_throw("useAction")
    assert not summary.function_may_throw("Quiet.execute")
    assert not summary.function_may_throw("DispatchError.message")


def test_nullable_interface_receiver_cannot_bypass_dispatch_effect_typing() -> None:
    program = parse_source(
        """
interface Action { void execute(); }
void maybe(Action? value) { value.execute(); }
"""
    )

    with pytest.raises(AetherTypeError, match=r"Action\?.*execute"):
        TypeChecker().check(program)


def test_initial_ir_uses_exactly_one_interface_call_shape_per_slot_effect() -> None:
    _program, initial, _ssa = _lower()
    invokes = _instructions(initial, IRInvokeInterface)
    calls = _instructions(initial, IRInterfaceCall)

    assert invokes
    assert {instruction.slot.method_id for instruction in invokes} == {
        "Action.execute"
    }
    assert all(instruction.slot.may_throw for instruction in invokes)
    assert {instruction.slot.method_id for instruction in calls} >= {
        "Action.next",
        "Action.label",
        "View.view",
        "Named.name",
        "Error.message",
    }
    assert all(not instruction.slot.may_throw for instruction in calls)
    encoded = ir_module_to_json(initial)
    assert ir_module_from_json(encoded) == initial
    assert '"may_throw": true' in encoded

    functions = {function.name: function for function in initial.functions}
    assert functions["nested"].may_throw
    assert functions["useAction"].may_throw
    assert not functions["useView"].may_throw

    witnesses = [
        instruction.witness
        for instruction in _instructions(initial, IRInterfaceConstruct)
    ]
    execute_slots = [
        slot
        for witness in witnesses
        for slot in witness.method_slots
        if slot.method_id == "Action.execute"
    ]
    assert {witness.carrier_kind for witness in witnesses} >= {"box", "class"}
    assert execute_slots and all(slot.may_throw for slot in execute_slots)
    assert all(slot.receiver_ownership == "borrowed" for slot in execute_slots)
    assert all(
        witness.box_layout is not None
        and witness.box_layout.ownership == "owned_value"
        for witness in witnesses
        if witness.carrier_kind == "box"
    )


def test_ssa_preserves_interface_effect_and_exceptional_cfg_exactly() -> None:
    _program, initial, ssa = _lower()
    ir_invokes = _instructions(initial, IRInvokeInterface)
    ssa_invokes = _instructions(ssa, SSAInvokeInterface)
    ir_calls = _instructions(initial, IRInterfaceCall)
    ssa_calls = _instructions(ssa, SSAInterfaceCall)

    assert len(ssa_invokes) == len(ir_invokes)
    assert len(ssa_calls) == len(ir_calls)
    assert all(instruction.slot.may_throw for instruction in ssa_invokes)
    assert all(not instruction.slot.may_throw for instruction in ssa_calls)
    assert all(
        instruction.exceptional_arguments == (instruction.exception,)
        for instruction in ssa_invokes
    )
    encoded = ssa_module_to_json(ssa)
    assert ssa_module_from_json(encoded) == ssa
    assert '"may_throw": true' in encoded


def test_verifiers_reject_interface_call_shape_effect_disagreements() -> None:
    _program, initial, ssa = _lower()
    ir_invoke = _instructions(initial, IRInvokeInterface)[0]
    object.__setattr__(
        ir_invoke,
        "slot",
        replace(ir_invoke.slot, may_throw=False),
    )
    with pytest.raises(IRVerificationError, match="may_throw"):
        IRVerifier(initial).verify()

    ssa_invoke = _instructions(ssa, SSAInvokeInterface)[0]
    object.__setattr__(
        ssa_invoke,
        "slot",
        replace(ssa_invoke.slot, may_throw=False),
    )
    with pytest.raises(SSAVerificationError, match="may_throw"):
        SSAVerifier(ssa).verify()


def test_llvm_uses_slot_effect_for_interface_thunk_and_call_selection() -> None:
    _program, _initial, ssa = _lower()
    llvm = LLVMBackend().emit(ssa)
    quiet_execute = dispatch_thunk_symbol(
        "Action", "Quiet", 0, "Action.execute"
    )
    loud_execute = dispatch_thunk_symbol(
        "Action", "Loud", 0, "Action.execute"
    )
    multi_view = dispatch_thunk_symbol("View", "Multi", 0, "View.view")

    assert (
        f"define private void @{quiet_execute}(ptr %carrier, ptr %__ae_exception_out)"
        in llvm
    )
    assert (
        f"define private void @{loud_execute}(ptr %carrier, ptr %__ae_exception_out)"
        in llvm
    )
    assert f"define private ptr @{multi_view}(ptr %carrier)" in llvm
    assert "invoke.interface.event.out" in llvm
    assert "call ptr %interface.call.thunk" in llvm
    assert "invoke.error.message.failed" not in llvm
