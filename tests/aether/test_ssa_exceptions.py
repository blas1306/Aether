from __future__ import annotations

import pytest

from aether.ir import BoolType, IRInterpreter, IRLowerer
from aether.ir.interpreter import IRExecutionError
from aether.pipeline import parse_source
from aether.ssa import (
    GeneralSSABuilder,
    SSACall,
    SSACatchEntry,
    SSACFGBuilder,
    SSADTOError,
    SSAExceptionDestroy,
    SSAExceptionMatch,
    SSAInterpreter,
    SSAInterfaceCall,
    SSAInvoke,
    SSAInvokeIndirect,
    SSAInvokeInterface,
    SSAModule,
    SSAPackException,
    SSAPhi,
    SSAPropagate,
    SSAVerificationError,
    SSAVerifier,
    SSAValue,
    predecessors,
    reachable_blocks,
    reverse_postorder,
    rewrite_edge,
    ssa_module_from_json,
    ssa_module_to_json,
    successor_edges,
    print_ssa,
)
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


ERROR_TYPES = """
struct FileError implements Error {
    string text;
    string message() { return text; }
}

struct NetworkError implements Error {
    string text;
    string message() { return text; }
}
"""


def _lower(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    ir = IRLowerer().lower(program)
    ssa = GeneralSSABuilder().build(ir)
    assert SSAVerifier(ssa).verify() is ssa
    return ir, ssa


def _instructions(module: SSAModule):
    return (
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    )


def test_lowering_preserves_all_invoke_forms_and_typed_exceptional_edges() -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
void directFailure() {
    throw NetworkError("direct");
}

void indirectFailure() {
    throw FileError("indirect");
}

void apply(void() operation) {
    operation();
}

int main() {
    try {
        directFailure();
        apply(indirectFailure);
    } catch (Error error) {
        println(error.message());
    }
    return 0;
}
"""
    )

    instructions = tuple(_instructions(module))
    assert any(isinstance(item, SSAInvoke) for item in instructions)
    assert any(isinstance(item, SSAInvokeIndirect) for item in instructions)
    assert any(isinstance(item, SSAInterfaceCall) for item in instructions)
    assert not any(isinstance(item, SSAInvokeInterface) for item in instructions)
    assert all(
        item.normal_arguments
        == (() if item.result is None else (item.result,))
        and item.exceptional_arguments == (item.exception,)
        for item in instructions
        if isinstance(item, (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface))
    )

    main = next(function for function in module.functions if function.name == "main")
    cfg = SSACFGBuilder().build(main)
    invoke_block = next(
        block
        for block in main.blocks
        if isinstance(
            block.instructions[-1],
            (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface),
        )
    )
    assert [edge.kind for edge in successor_edges(invoke_block)] == [
        "normal",
        "exceptional",
    ]
    assert any(edge.kind == "exceptional" for edge in cfg.edges)


def test_throwing_constructor_lowers_as_direct_invoke() -> None:
    _ir, module = _lower(
        """
struct ConstructionError implements Error {
    string text;
    string message() { return text; }
}

struct Wrapper {
    int value;
    constructor(int initial) {
        value = initial;
        throw ConstructionError("constructor");
    }
}

int main() {
    try {
        Wrapper item = Wrapper(1);
    } catch (ConstructionError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    constructor_invoke = next(
        instruction
        for instruction in _instructions(module)
        if isinstance(instruction, SSAInvoke)
        and instruction.function == "Wrapper.__ctor"
    )
    assert constructor_invoke.exceptional_arguments == (
        constructor_invoke.exception,
    )

    interpreter = SSAInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == "constructor\n"


def test_ssa_interpreter_matches_initial_ir_for_nested_throwing_interface() -> None:
    ir, ssa = _lower(
        """
interface ThrowingOperation {
    string run();
}

class ThrowingRunner implements ThrowingOperation {
    public string run() {
        throw NetworkError("new");
    }
}

struct OldError implements Error {
    string message() { return "old"; }
}

struct NetworkError implements Error {
    string text;
    string message() { return text; }
}

int main() {
    ThrowingOperation operation = ThrowingRunner();
    try {
        try {
            throw OldError();
        } catch (Error old) {
            println(operation.run());
        }
    } catch (NetworkError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    ir_interpreter = IRInterpreter(ir)
    ssa_interpreter = SSAInterpreter(ssa)

    assert ir_interpreter.call("main") == ssa_interpreter.call("main") == 0
    assert ir_interpreter.output == ssa_interpreter.output == "new\n"
    cleanup = next(
        block
        for function in ssa.functions
        if function.name == "main"
        for block in function.blocks
        if block.name.startswith("invoke.cleanup")
    )
    assert isinstance(cleanup.instructions[0], SSACatchEntry)
    assert isinstance(cleanup.instructions[1], SSAExceptionDestroy)
    assert isinstance(cleanup.instructions[-1], SSAPropagate)


@pytest.mark.parametrize(
    ("source", "invoke_type", "expected"),
    [
        (
            """
void failNew() {
    throw NetworkError("direct");
}

void exercise() {
    try {
        throw FileError("old");
    } catch (FileError old) {
        failNew();
    }
}

int main() {
    try {
        exercise();
    } catch (NetworkError error) {
        println(error.message());
    }
    return 0;
}
""",
            SSAInvoke,
            "direct\n",
        ),
        (
            """
void failNew() {
    throw NetworkError("indirect");
}

void exercise(void() operation) {
    try {
        throw FileError("old");
    } catch (FileError old) {
        operation();
    }
}

int main() {
    try {
        exercise(failNew);
    } catch (NetworkError error) {
        println(error.message());
    }
    return 0;
}
""",
            SSAInvokeIndirect,
            "indirect\n",
        ),
        (
            """
interface ThrowingOperation {
    string run();
}

class ThrowingRunner implements ThrowingOperation {
    public string run() {
        throw NetworkError("interface");
    }
}

struct OldError implements Error {
    string message() { return "old"; }
}

int main() {
    ThrowingOperation operation = ThrowingRunner();
    try {
        try {
            throw OldError();
        } catch (Error old) {
            println(operation.run());
        }
    } catch (NetworkError error) {
        println(error.message());
    }
    return 0;
}
""",
            SSAInvokeInterface,
            "interface\n",
        ),
    ],
)
def test_nested_throwing_invoke_in_catch_preserves_linear_ownership(
    source: str,
    invoke_type: type[object],
    expected: str,
) -> None:
    _ir, module = _lower(ERROR_TYPES + source)
    invoke = next(
        instruction
        for instruction in _instructions(module)
        if isinstance(instruction, invoke_type)
        and instruction.exceptional_target.startswith("invoke.cleanup")
    )
    function = next(
        function
        for function in module.functions
        if any(
            invoke is instruction
            for block in function.blocks
            for instruction in block.instructions
        )
    )
    cleanup = next(
        block
        for block in function.blocks
        if block.name == invoke.exceptional_target
    )
    assert isinstance(cleanup.instructions[0], SSACatchEntry)
    assert isinstance(cleanup.instructions[1], SSAExceptionDestroy)
    assert isinstance(cleanup.instructions[-1], SSAPropagate)

    interpreter = SSAInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == expected


def test_handler_keeps_existing_phi_convention_before_catch_entry() -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
void fail() {
    throw FileError("phi");
}

int main() {
    int value = 1;
    try {
        fail();
        value = 2;
        fail();
    } catch (FileError error) {
        println(value);
    }
    return 0;
}
"""
    )
    main = next(function for function in module.functions if function.name == "main")
    handler = next(
        block
        for block in main.blocks
        if any(isinstance(instruction, SSACatchEntry) for instruction in block.instructions)
        and any(isinstance(instruction, SSAPhi) for instruction in block.instructions)
    )
    first_non_phi = next(
        instruction
        for instruction in handler.instructions
        if not isinstance(instruction, SSAPhi)
    )
    assert isinstance(handler.instructions[0], SSAPhi)
    assert isinstance(first_non_phi, SSACatchEntry)

    interpreter = SSAInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == "1\n"

    optimized = SSAOptimizerPipeline(verify_after_each=True).run(module)
    optimized_interpreter = SSAInterpreter(optimized)
    assert optimized_interpreter.call("main") == 0
    assert optimized_interpreter.output == "1\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
int main() {
    try {
        throw NetworkError("ordered");
    } catch (FileError wrong) {
        println("wrong");
    } catch (NetworkError exact) {
        println(exact.message());
    }
    return 0;
}
""",
            "ordered\n",
        ),
        (
            """
int main() {
    try {
        throw FileError("catch-all");
    } catch (Error error) {
        println(error.message());
    }
    return 0;
}
""",
            "catch-all\n",
        ),
        (
            """
void fail() {
    throw FileError("original");
}

void relay() {
    try {
        fail();
    } catch (Error error) {
        throw;
    }
}

int main() {
    try {
        relay();
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
""",
            "original\n",
        ),
        (
            """
void maybeFail(boolean fail) {
    if (fail) {
        throw NetworkError("wrong");
    }
}

int main() {
    try {
        maybeFail(false);
        println("normal");
    } catch (NetworkError error) {
        println(error.message());
    }
    return 0;
}
""",
            "normal\n",
        ),
    ],
)
def test_ssa_interpreter_exception_semantics_match_initial_ir(
    source: str,
    expected: str,
) -> None:
    ir, module = _lower(ERROR_TYPES + source)
    ir_interpreter = IRInterpreter(ir)
    ssa_interpreter = SSAInterpreter(module)

    assert ir_interpreter.call("main") == ssa_interpreter.call("main") == 0
    assert ir_interpreter.output == ssa_interpreter.output == expected


def test_exception_ssa_json_round_trip_and_printer_are_stable() -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
void fail() {
    throw FileError("serialized");
}

int main() {
    try {
        fail();
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    encoded = ssa_module_to_json(module)
    decoded = ssa_module_from_json(encoded)

    assert decoded == module
    assert print_ssa(decoded) == print_ssa(module)
    assert '"kind": "exception_pack"' in encoded
    assert '"kind": "invoke"' in encoded
    assert '"may_throw": true' in encoded

    malformed = encoded.replace('"tag": "value"', '"tag": "storage"', 1)
    with pytest.raises(SSADTOError, match=r"storage.*not legal in SSA"):
        ssa_module_from_json(malformed)


def test_optimizers_retain_exception_events_handlers_and_cleanup() -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
int main() {
    try {
        throw FileError("kept");
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    optimized = SSAOptimizerPipeline(verify_after_each=True).run(module)
    interpreter = SSAInterpreter(optimized)

    assert interpreter.call("main") == 0
    assert interpreter.output == "kept\n"
    assert any(isinstance(item, SSAPackException) for item in _instructions(optimized))
    assert any(
        isinstance(item, SSAExceptionDestroy) for item in _instructions(optimized)
    )
    assert any(isinstance(item, SSACatchEntry) for item in _instructions(optimized))


@pytest.mark.parametrize("mutation", ["double_destroy", "borrow_after", "leak"])
def test_verifier_rejects_invalid_linear_event_paths(mutation: str) -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
int main() {
    try {
        throw FileError("invalid");
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    catch_block = next(
        block
        for function in module.functions
        if function.name == "main"
        for block in function.blocks
        if any(
            isinstance(item, SSAExceptionDestroy)
            for item in block.instructions
        )
    )
    destroy_index = next(
        index
        for index, item in enumerate(catch_block.instructions)
        if isinstance(item, SSAExceptionDestroy)
    )
    destroy = catch_block.instructions[destroy_index]
    assert isinstance(destroy, SSAExceptionDestroy)
    if mutation == "double_destroy":
        catch_block.instructions.insert(destroy_index + 1, destroy)
    elif mutation == "borrow_after":
        catch_block.instructions.insert(
            destroy_index + 1,
            SSAExceptionMatch(
                SSAValue("late_match", BoolType()),
                destroy.event,
                "FileError",
            ),
        )
    else:
        catch_block.instructions.pop(destroy_index)

    with pytest.raises(
        SSAVerificationError,
        match=r"consum|borrowed after|ownership merge|leaks owned",
    ):
        SSAVerifier(module).verify()


def test_exceptional_edges_participate_in_reachability_rpo_and_predecessors() -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
void fail() {
    throw FileError("cfg");
}

int main() {
    try {
        fail();
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    main = next(function for function in module.functions if function.name == "main")
    invoke_block = next(
        block
        for block in main.blocks
        if isinstance(block.instructions[-1], SSAInvoke)
    )
    invoke = invoke_block.instructions[-1]
    assert isinstance(invoke, SSAInvoke)

    assert invoke.exceptional_target in reachable_blocks(main)
    assert invoke.exceptional_target in reverse_postorder(main)
    incoming = predecessors(main)[invoke.exceptional_target]
    assert any(
        edge.source == invoke_block.name and edge.kind == "exceptional"
        for edge in incoming
    )

    rewritten = rewrite_edge(
        invoke,
        old_target=invoke.exceptional_target,
        new_target="replacement.handler",
    )
    assert isinstance(rewritten, SSAInvoke)
    assert rewritten.normal_target == invoke.normal_target
    assert rewritten.exceptional_target == "replacement.handler"
    assert rewritten.exceptional_arguments == invoke.exceptional_arguments


def test_unhandled_ssa_exception_reports_without_becoming_panic() -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
int main() {
    throw NetworkError("unhandled");
}
"""
    )
    with pytest.raises(
        IRExecutionError,
        match=r"Unhandled NetworkError exception",
    ):
        SSAInterpreter(module).call("main")


@pytest.mark.parametrize(
    "corruption",
    ["missing_exceptional_release", "double_exceptional_release", "normal_use_after_release"],
)
def test_ssa_verifier_rejects_malformed_constructor_receiver_cleanup(
    corruption: str,
) -> None:
    _ir, module = _lower(
        ERROR_TYPES
        + """
struct Wrapper {
    string initialized;
    Array<string> nested;
    constructor() {
        initialized = "owned";
        nested = {"partial"};
        throw FileError("constructor");
    }
}
int main() {
    try { Wrapper value = Wrapper(); }
    catch (FileError error) { println(error.message()); }
    return 0;
}
"""
    )
    function = next(function for function in module.functions if function.name == "main")
    invoke = next(
        instruction
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAInvoke) and instruction.function == "Wrapper.__ctor"
    )
    receiver = invoke.arguments[0]
    blocks = {block.name: block for block in function.blocks}
    cleanup = blocks[invoke.exceptional_target]
    normal = blocks[invoke.normal_target]

    if corruption == "missing_exceptional_release":
        cleanup.instructions.pop(1)
    elif corruption == "double_exceptional_release":
        cleanup.instructions.insert(2, cleanup.instructions[1])
    else:
        normal.instructions.insert(
            1,
            SSACall(
                "__aether_retain",
                (receiver,),
                None,
                "__aether_retain",
            ),
        )

    with pytest.raises(SSAVerificationError, match="[Cc]onstructor receiver|cleanup"):
        SSAVerifier(module).verify()
