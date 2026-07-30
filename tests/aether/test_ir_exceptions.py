from __future__ import annotations

import pytest

from aether.analysis.cfg import CFGBuilder
from aether.ir import (
    BoolType,
    ExceptionEventType,
    IRBasicBlock,
    IRCatchEntry,
    IRExceptionDestroy,
    IRExceptionMatch,
    IRFunction,
    IRInterpreter,
    IRInvoke,
    IRInvokeIndirect,
    IRInvokeInterface,
    IRLowerer,
    IRModule,
    IRPackException,
    IRParameter,
    IRPropagate,
    IRRethrow,
    IRThrow,
    IRValue,
    IRVerificationError,
    IRVerifier,
    VoidType,
    print_ir,
)
from aether.ir.dto import ir_module_from_json, ir_module_to_json
from aether.ir.interpreter import IRExecutionError
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import parse_source
from aether.runner import run_aether
from aether.typechecker import TypeChecker


ERROR_TYPES = """
struct FileError implements Error {
    string text;
    string message() { return text; }
}

class NetworkError implements Error {
    string text;
    public string message() { return text; }
}
"""


def _lower(source: str) -> IRModule:
    program = parse_source(source)
    TypeChecker().check(program)
    module = IRLowerer().lower(program)
    assert IRVerifier(module).verify() is module
    return module


def _execute(module: IRModule) -> tuple[object, str]:
    interpreter = IRInterpreter(module)
    return interpreter.call("main"), interpreter.output


def _instructions(module: IRModule):
    return (
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    )


def test_lowering_exposes_ordered_handlers_and_exceptional_cfg_edges() -> None:
    module = _lower(
        ERROR_TYPES
        + """
void fail() {
    throw NetworkError("offline");
}

int main() {
    try {
        fail();
    } catch (FileError file) {
        println("wrong");
    } catch (NetworkError network) {
        println(network.message());
    } catch (Error fallback) {
        println("fallback");
    }
    return 0;
}
"""
    )

    main = next(function for function in module.functions if function.name == "main")
    invoke = next(
        instruction
        for block in main.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRInvoke)
    )
    entry = next(
        instruction
        for block in main.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCatchEntry)
        and instruction.handler_id != "root"
    )
    cfg = CFGBuilder().build(main)

    assert main.may_throw
    assert invoke.effects.may_throw
    assert entry.catch_types == ("FileError", "NetworkError", "Error")
    assert [(edge.target, edge.kind) for edge in cfg.edges if edge.source == "entry"] == [
        (invoke.normal_target, "normal"),
        (invoke.exceptional_target, "exceptional"),
    ]


def test_nested_rethrow_and_exact_matching_match_frontend_interpreter() -> None:
    source = (
        ERROR_TYPES
        + """
int main() {
    try {
        try {
            throw FileError("original");
        } catch (FileError inner) {
            println("inner");
            throw;
        } catch (Error sibling) {
            println("wrong sibling");
        }
    } catch (NetworkError wrong) {
        println("wrong outer");
    } catch (FileError outer) {
        println(outer.message());
    }
    return 0;
}
"""
    )
    module = _lower(source)

    result, output = _execute(module)

    assert result == 0
    assert output == run_aether(source).output == "inner\noriginal\n"
    assert any(isinstance(item, IRRethrow) for item in _instructions(module))
    assert any(isinstance(item, IRPropagate) for item in _instructions(module))


def test_error_catch_borrows_payload_and_interface_invoke_executes() -> None:
    source = (
        ERROR_TYPES
        + """
int main() {
    try {
        throw FileError("root");
    } catch (Error error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    module = _lower(source)

    assert any(isinstance(item, IRInvokeInterface) for item in _instructions(module))
    assert _execute(module) == (0, "root\n")


def test_unknown_callable_is_conservatively_invoked_and_propagates() -> None:
    module = _lower(
        ERROR_TYPES
        + """
void fail() {
    throw FileError("indirect");
}

void apply(void() operation) {
    operation();
}

int main() {
    try {
        apply(fail);
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
"""
    )

    apply = next(function for function in module.functions if function.name == "apply")

    assert apply.may_throw
    assert any(
        isinstance(item, IRInvokeIndirect)
        for block in apply.blocks
        for item in block.instructions
    )
    assert _execute(module) == (0, "indirect\n")


def test_exception_ir_json_and_printer_round_trip_is_lossless() -> None:
    module = _lower(
        ERROR_TYPES
        + """
int main() {
    try {
        throw FileError("serialized");
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
"""
    )

    encoded = ir_module_to_json(module)
    decoded = ir_module_from_json(encoded)

    assert decoded == module
    assert print_ir(decoded) == print_ir(module)
    assert '"kind": "exception_pack"' in encoded
    assert '"may_throw": true' in encoded
    assert "exceptional" in print_ir(module)


def test_initial_ir_optimizers_preserve_exception_behavior_and_transfers() -> None:
    module = _lower(
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

    optimized = OptimizerPipeline().run(module)

    assert IRVerifier(optimized).verify() is optimized
    assert _execute(optimized) == (0, "kept\n")
    assert any(isinstance(item, IRPackException) for item in _instructions(optimized))
    assert any(isinstance(item, IRThrow) for item in _instructions(optimized))
    assert any(
        isinstance(item, IRExceptionDestroy) for item in _instructions(optimized)
    )


def test_unhandled_event_reaches_root_without_becoming_a_panic() -> None:
    module = _lower(
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
        IRInterpreter(module).call("main")


def test_verifier_rejects_rethrow_without_catch_owned_event() -> None:
    event = IRParameter("event", ExceptionEventType())
    module = IRModule(
        [
            IRFunction(
                "main",
                [event],
                VoidType(),
                [IRBasicBlock("entry", [IRRethrow(event)])],
                may_throw=True,
            )
        ]
    )

    with pytest.raises(
        IRVerificationError,
        match=r"Rethrow requires an event introduced by an active catch handler",
    ):
        IRVerifier(module).verify()


def test_verifier_rejects_event_use_after_destroy() -> None:
    module = _lower(
        ERROR_TYPES
        + """
int main() {
    try {
        throw FileError("x");
    } catch (FileError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    main = next(function for function in module.functions if function.name == "main")
    catch_block = next(
        block
        for block in main.blocks
        if any(isinstance(item, IRExceptionDestroy) for item in block.instructions)
    )
    destroy_index = next(
        index
        for index, item in enumerate(catch_block.instructions)
        if isinstance(item, IRExceptionDestroy)
    )
    event = catch_block.instructions[destroy_index].event
    catch_block.instructions.insert(
        destroy_index + 1,
        IRExceptionMatch(
            IRValue("late_match", BoolType()),
            event,
            "FileError",
        ),
    )

    with pytest.raises(
        IRVerificationError,
        match=r"is used after consumption",
    ):
        IRVerifier(module).verify()


@pytest.mark.parametrize(
    ("source", "invoke_type"),
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
            IRInvoke,
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
            IRInvokeIndirect,
        ),
        (
            """
struct ThrowingError implements Error {
    string text;
    string message() {
        throw NetworkError("interface");
    }
}

int main() {
    try {
        try {
            throw ThrowingError("old");
        } catch (Error old) {
            println(old.message());
        }
    } catch (NetworkError error) {
        println(error.message());
    }
    return 0;
}
""",
            IRInvokeInterface,
        ),
    ],
)
def test_invoke_leaving_catch_destroys_old_event_before_new_propagation(
    source: str,
    invoke_type: type[object],
) -> None:
    module = _lower(ERROR_TYPES + source)
    invoke = next(
        instruction
        for instruction in _instructions(module)
        if isinstance(instruction, invoke_type)
        and instruction.exceptional_target.startswith("invoke.cleanup")
    )
    function = next(
        function
        for function in module.functions
        if any(invoke is item for block in function.blocks for item in block.instructions)
    )
    cleanup = next(
        block
        for block in function.blocks
        if block.name == invoke.exceptional_target
    )

    assert isinstance(cleanup.instructions[0], IRCatchEntry)
    assert isinstance(cleanup.instructions[1], IRExceptionDestroy)
    assert isinstance(cleanup.instructions[-1], IRPropagate)
    result, output = _execute(module)
    assert result == 0
    assert output in {"direct\n", "indirect\n", "interface\n"}


def test_verifier_rejects_missing_caught_event_cleanup_on_invoke_failure() -> None:
    module = _lower(
        ERROR_TYPES
        + """
void failNew() {
    throw NetworkError("new");
}

int main() {
    try {
        try {
            throw FileError("old");
        } catch (FileError old) {
            failNew();
        }
    } catch (NetworkError error) {
        println(error.message());
    }
    return 0;
}
"""
    )
    main = next(function for function in module.functions if function.name == "main")
    cleanup = next(
        block for block in main.blocks if block.name.startswith("invoke.cleanup")
    )
    cleanup.instructions = [
        instruction
        for instruction in cleanup.instructions
        if not isinstance(instruction, IRExceptionDestroy)
    ]

    with pytest.raises(
        IRVerificationError,
        match=r"leaks another owned event|ownership merge",
    ):
        IRVerifier(module).verify()
