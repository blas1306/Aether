from __future__ import annotations

import pytest

from aether.analysis.cfg import CFGBuilder
from aether.ir import (
    BoolType,
    ExceptionEventType,
    IRBasicBlock,
    IRCatchEntry,
    IRDestroy,
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
    RustVerifierAcceptedOutcome,
    RustVerifierRejectedOutcome,
    VoidType,
    build_canonical_rust_verifier_request,
    print_ir,
)
from aether.ir.dto import ir_module_from_json, ir_module_to_json
from aether.ir.interpreter import IRExecutionError
from aether.ir.optimizer import OptimizerPipeline
from aether.ir.rust_verifier import SubprocessRustVerifierClient
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


def test_bare_rethrow_inside_nested_try_bypasses_inner_handler_linearly() -> None:
    source = (
        ERROR_TYPES
        + """
void fail() { throw FileError("nested"); }

void relay() {
    try {
        fail();
    } catch (FileError active) {
        try {
            throw;
        } catch (FileError innerSibling) {
            println("wrong inner sibling");
        }
    }
}

int main() {
    try {
        relay();
    } catch (FileError outer) {
        println(outer.message());
    }
    return 0;
}
"""
    )
    module = _lower(source)
    relay = next(function for function in module.functions if function.name == "relay")
    rethrow = next(
        instruction
        for block in relay.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRRethrow)
    )

    assert rethrow.target == "exception.propagate"
    assert not any(
        isinstance(instruction, IRCatchEntry)
        and instruction.handler_id == "handler1"
        for block in relay.blocks
        for instruction in block.instructions
    )
    assert _execute(module) == (0, "nested\n")
    assert run_aether(source).output == "nested\n"

    decoded = ir_module_from_json(ir_module_to_json(module))
    assert decoded == module
    assert print_ir(decoded) == print_ir(module)
    optimized = OptimizerPipeline().run(decoded)
    assert IRVerifier(optimized).verify() is optimized
    assert _execute(optimized) == (0, "nested\n")

    from aether.ssa import GeneralSSABuilder, SSAInterpreter, SSAVerifier
    from aether.ssa.optimizer import SSAOptimizerPipeline

    ssa = GeneralSSABuilder().build(optimized)
    assert SSAVerifier(ssa).verify() is ssa
    ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    assert SSAVerifier(ssa).verify() is ssa
    interpreter = SSAInterpreter(ssa)
    assert interpreter.call("main") == 0
    assert interpreter.output == "nested\n"


@pytest.mark.parametrize(
    ("nested_body", "outer_catch"),
    [
        (
            "try { throw; } catch (NetworkError wrong) { println(\"wrong\"); }",
            "catch (FileError exact) { println(exact.message()); }",
        ),
        (
            "try { try { throw; } catch (NetworkError wrong1) { println(\"wrong1\"); } } "
            "catch (NetworkError wrong2) { println(\"wrong2\"); }",
            "catch (Error root) { println(root.message()); }",
        ),
    ],
)
def test_rethrow_crosses_two_and_three_nested_handler_levels(
    nested_body: str,
    outer_catch: str,
) -> None:
    source = ERROR_TYPES + f"""
void fail() {{ throw FileError("deep"); }}
void relay() {{
    try {{ fail(); }} catch (FileError active) {{ {nested_body} }}
}}
int main() {{
    try {{ relay(); }} {outer_catch}
    return 0;
}}
"""
    module = _lower(source)

    assert _execute(module) == (0, "deep\n")
    assert run_aether(source).output == "deep\n"
    assert sum(isinstance(item, IRRethrow) for item in _instructions(module)) == 1


@pytest.mark.parametrize("catch_type", ["NetworkError", "Error"])
def test_rethrow_from_inner_catch_destroys_enclosing_event_and_skips_siblings(
    catch_type: str,
) -> None:
    source = ERROR_TYPES + f"""
void failFile() {{ throw FileError("old"); }}
void failNetwork() {{ throw NetworkError("new"); }}
void relay() {{
    try {{
        failFile();
    }} catch (FileError old) {{
        try {{
            failNetwork();
        }} catch (NetworkError inner) {{
            throw;
        }} catch (Error sibling) {{
            println("wrong sibling");
        }}
    }}
}}
int main() {{
    try {{ relay(); }} catch ({catch_type} outer) {{ println(outer.message()); }}
    return 0;
}}
"""
    module = _lower(source)
    relay = next(function for function in module.functions if function.name == "relay")
    block = next(
        block
        for block in relay.blocks
        if isinstance(block.instructions[-1], IRRethrow)
    )
    rethrow = block.instructions[-1]
    assert isinstance(rethrow, IRRethrow)
    destroyed = [
        instruction.event
        for instruction in block.instructions[:-1]
        if isinstance(instruction, IRExceptionDestroy)
    ]

    assert destroyed
    assert all(event != rethrow.event for event in destroyed)
    assert _execute(module) == (0, "new\n")
    assert run_aether(source).output == "new\n"


def test_inner_unmatched_and_new_throw_have_one_terminal_disposition_each() -> None:
    unmatched_source = ERROR_TYPES + """
void failFile() { throw FileError("old"); }
void failNetwork() { throw NetworkError("unmatched"); }
void relay() {
    try { failFile(); } catch (FileError old) {
        try { failNetwork(); } catch (FileError wrong) { println("wrong"); }
    }
}
int main() {
    try { relay(); } catch (NetworkError outer) { println(outer.message()); }
    return 0;
}
"""
    unmatched = _lower(unmatched_source)
    assert _execute(unmatched) == (0, "unmatched\n")

    new_throw_source = ERROR_TYPES + """
struct ReplacementError implements Error {
    string text;
    string message() { return text; }
}
void failFile() { throw FileError("old"); }
void failNetwork() { throw NetworkError("inner"); }
void relay() {
    try { failFile(); } catch (FileError old) {
        try { failNetwork(); } catch (NetworkError inner) {
            throw ReplacementError("replacement");
        }
    }
}
int main() {
    try { relay(); } catch (ReplacementError outer) { println(outer.message()); }
    return 0;
}
"""
    replacement = _lower(new_throw_source)
    relay = next(function for function in replacement.functions if function.name == "relay")
    throw_block = next(
        block
        for block in relay.blocks
        if isinstance(block.instructions[-1], IRThrow)
        and block.instructions[-1].event.type == ExceptionEventType()
    )
    terminal = throw_block.instructions[-1]
    assert isinstance(terminal, IRThrow)
    old_destroys = [
        item
        for item in throw_block.instructions[:-1]
        if isinstance(item, IRExceptionDestroy)
    ]
    assert len(old_destroys) == 2
    assert all(item.event != terminal.event for item in old_destroys)
    assert _execute(replacement) == (0, "replacement\n")


@pytest.mark.parametrize(
    ("extra", "relay_parameters", "before_rethrow", "invoke_type", "expected"),
    [
        (
            "void probe() { if (false) { throw NetworkError(\"probe\"); } }",
            "",
            "probe();",
            IRInvoke,
            "direct\n",
        ),
        (
            "void probe() { if (false) { throw NetworkError(\"probe\"); } }",
            "void() operation",
            "operation();",
            IRInvokeIndirect,
            "indirect\n",
        ),
        (
            "",
            "",
            "println(active.message());",
            IRInvokeInterface,
            "interface\ninterface\n",
        ),
    ],
)
def test_direct_indirect_and_interface_invokes_before_nested_rethrow(
    extra: str,
    relay_parameters: str,
    before_rethrow: str,
    invoke_type: type[object],
    expected: str,
) -> None:
    binder_type = "Error" if invoke_type is IRInvokeInterface else "FileError"
    argument = "probe" if invoke_type is IRInvokeIndirect else ""
    label = expected.splitlines()[0]
    source = ERROR_TYPES + f"""
{extra}
void fail() {{ throw FileError("{label}"); }}
void relay({relay_parameters}) {{
    try {{ fail(); }} catch ({binder_type} active) {{
        try {{
            {before_rethrow}
            throw;
        }} catch (NetworkError sibling) {{
            println("wrong sibling");
        }}
    }}
}}
int main() {{
    try {{ relay({argument}); }} catch (FileError outer) {{ println(outer.message()); }}
    return 0;
}}
"""
    module = _lower(source)
    relay = next(function for function in module.functions if function.name == "relay")

    assert any(
        isinstance(item, invoke_type)
        for block in relay.blocks
        for item in block.instructions
    )
    assert _execute(module) == (0, expected)
    assert run_aether(source).output == expected


def test_nested_rethrow_cleanup_ladder_preserves_mutable_state_and_owner() -> None:
    source = ERROR_TYPES + """
void fail() { throw FileError("cleanup"); }
void relay() {
    string outer = "outer";
    try { fail(); } catch (FileError active) {
        string middle = "middle";
        try {
            string inner = "inner";
            throw;
        } catch (NetworkError sibling) {
            println("wrong");
        }
    }
}
int main() {
    int state = 1;
    try { relay(); } catch (FileError outer) {
        state = 2;
        println(state);
        println(outer.message());
    }
    return 0;
}
"""
    module = _lower(source)
    relay = next(function for function in module.functions if function.name == "relay")
    block = next(
        block for block in relay.blocks if isinstance(block.instructions[-1], IRRethrow)
    )
    rethrow = block.instructions[-1]
    assert isinstance(rethrow, IRRethrow)
    cleanup = block.instructions[:-1]

    assert [item.value.name for item in cleanup if isinstance(item, IRDestroy)][-3:] == [
        "inner",
        "middle",
        "outer",
    ]
    assert not any(
        isinstance(item, IRExceptionDestroy) and item.event == rethrow.event
        for item in cleanup
    )
    assert _execute(module) == (0, "2\ncleanup\n")


def test_irv149_still_rejects_duplicate_terminal_use_after_fixed_rethrow(
    rust_verifier_executable,
) -> None:
    module = _lower(
        ERROR_TYPES
        + """
void failFile() { throw FileError("old"); }
void failNetwork() { throw NetworkError("transferred"); }
void relay() {
    try { failFile(); } catch (FileError old) {
        try { failNetwork(); } catch (NetworkError active) { throw; }
    }
}
int main() {
    try { relay(); } catch (NetworkError outer) { println(outer.message()); }
    return 0;
}
"""
    )
    block = next(
        block
        for function in module.functions
        for block in function.blocks
        if isinstance(block.instructions[-1], IRRethrow)
    )
    rethrow = block.instructions[-1]
    assert isinstance(rethrow, IRRethrow)
    old_destroy = next(
        item
        for item in block.instructions[:-1]
        if isinstance(item, IRExceptionDestroy) and item.event != rethrow.event
    )
    block.instructions.remove(old_destroy)

    with pytest.raises(
        IRVerificationError,
        match="ownership merge|leaks another owned event",
    ) as failure:
        IRVerifier(module).verify()
    assert failure.value.normalized_failure is not None
    assert failure.value.normalized_failure.invariant_id == "IRV-149"

    invocation = SubprocessRustVerifierClient(
        executable=rust_verifier_executable
    ).verify(build_canonical_rust_verifier_request(module))
    assert isinstance(invocation.outcome, RustVerifierRejectedOutcome)
    assert invocation.outcome.diagnostic.invariant_id == "IRV-149"


def test_fixed_nested_rethrow_is_accepted_by_python_and_rust_verifiers(
    rust_verifier_executable,
) -> None:
    module = _lower(
        ERROR_TYPES
        + """
void fail() { throw FileError("rust"); }
void relay() {
    try { fail(); } catch (FileError active) {
        try { throw; } catch (NetworkError sibling) { println("wrong"); }
    }
}
int main() {
    try { relay(); } catch (Error outer) { println(outer.message()); }
    return 0;
}
"""
    )
    invocation = SubprocessRustVerifierClient(
        executable=rust_verifier_executable
    ).verify(build_canonical_rust_verifier_request(module))

    assert isinstance(invocation.outcome, RustVerifierAcceptedOutcome)


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
