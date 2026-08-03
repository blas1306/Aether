from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend
from aether.capabilities import (
    BackendIdentity,
    Capability,
    backend_capability_issues,
    detect_required_capabilities,
)
from aether.ir import (
    IRInterfaceCall,
    IRInterpreter,
    IRInvokeInterface,
    IRLowerer,
    IRVerificationError,
    IRVerifier,
)
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import parse_source, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder, SSAInterpreter, SSAVerifier
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _stress_source(
    *,
    catch_depth: int = 24,
    handler_count: int = 12,
    mutate_nested: bool = False,
    seed_interface_throw_fact: bool = True,
) -> str:
    error_types = "\n".join(
        f'''struct E{index} implements Error {{
    string message() {{ return "E{index}"; }}
}}'''
        for index in range(handler_count)
    )
    nested = "throw E0();"
    for index in range(catch_depth):
        mutation = "cleanupCount = cleanupCount + 1; " if mutate_nested else ""
        nested = (
            f"try {{ {nested} }} "
            f"catch (E0 nested{index}) {{ {mutation}throw; }}"
        )
    handlers = "\n".join(
        f'catch (E{index} wrong{index}) {{ println("wrong{index}"); }}'
        for index in range(handler_count)
    )
    first_array = ", ".join(str(value) for value in range(128))
    second_array = ", ".join(str(value) for value in range(128, 256))
    first_list = ", ".join(f'"s{value}"' for value in range(32))
    second_list = ", ".join(f'"s{value}"' for value in range(32, 64))
    cleanup_declaration = "int cleanupCount = 0;" if mutate_nested else ""
    cleanup_observation = "println(cleanupCount);" if mutate_nested else 'println("nested");'
    interface_dispatches = "\n".join("    dynamic.message();" for _ in range(250))
    interface_body = f'{interface_dispatches}\n    println(dynamic.message());'
    if seed_interface_throw_fact:
        interface_body = (
            'try { throw E0(); } catch (Error ignoredSeed) { }\n'
            f'    try {{\n{interface_body}\n    }} '
            'catch (Error unexpected) { println("wrong-interface"); }'
        )

    return f'''
{error_types}

struct DeepError implements Error {{
    string text;
    Array<Array<int>> arrays;
    List<List<string>> lists;
    string message() {{ return text; }}
}}

class ClassError implements Error {{
    string text;
    Array<Array<int>> arrays;
    List<List<string>> lists;
    public string message() {{ return text; }}
}}

void deepFailure(int depth) {{
    if (depth == 0) {{
        throw DeepError(
            "deep-owned",
            {{{{{first_array}}}, {{{second_array}}}}},
            {{{{{first_list}}}, {{{second_list}}}}}
        );
    }}
    deepFailure(depth - 1);
}}

void nestedStress() {{
    {cleanup_declaration}
    try {{ {nested} }}
    catch (E0 finalNested) {{ {cleanup_observation} }}
}}

void payloadStress() {{
    try {{ deepFailure(48); }}
    {handlers}
    catch (DeepError exact) {{ println(exact.message()); }}
}}

void interfaceStress() {{
    Error dynamic = ClassError(
        "class-interface",
        {{{{1, 2}}, {{3, 4}}}},
        {{{{"a", "b"}}, {{"c", "d"}}}}
    );
    {interface_body}
}}

void eventStress() {{
    int events = 0;
    while (events < 500) {{
        try {{ throw E1(); }}
        catch (E1 repeated) {{ events = events + 1; }}
        catch (Error impossible) {{ println("wrong-root"); }}
    }}
    println(events);
}}

int main() {{
    nestedStress();
    payloadStress();
    interfaceStress();
    eventStress();
    return 0;
}}
'''


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is unavailable")
def test_generated_exception_stress_is_deterministic_across_all_internal_stages(
    tmp_path: Path,
) -> None:
    source = _stress_source()
    program = parse_source(source)
    TypeChecker().check(program)

    ast_output = run_aether(source).output
    initial_ir = IRLowerer().lower(program)
    assert IRVerifier(initial_ir).verify() is initial_ir
    ir_interpreter = IRInterpreter(initial_ir)
    assert ir_interpreter.call("main") == 0

    optimized_ir = OptimizerPipeline().run(initial_ir)
    assert IRVerifier(optimized_ir).verify() is optimized_ir
    optimized_ir_interpreter = IRInterpreter(optimized_ir)
    assert optimized_ir_interpreter.call("main") == 0

    ssa = GeneralSSABuilder().build(optimized_ir)
    assert SSAVerifier(ssa).verify() is ssa
    ssa_interpreter = SSAInterpreter(ssa)
    assert ssa_interpreter.call("main") == 0

    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    optimized_ssa_interpreter = SSAInterpreter(optimized_ssa)
    assert optimized_ssa_interpreter.call("main") == 0

    expected = "nested\ndeep-owned\nclass-interface\n500\n"
    assert (
        ast_output
        == ir_interpreter.output
        == optimized_ir_interpreter.output
        == ssa_interpreter.output
        == optimized_ssa_interpreter.output
        == expected
    )

    llvm_path = tmp_path / "exception-release-stress.ll"
    executable = tmp_path / "exception-release-stress"
    llvm_path.write_text(LLVMBackend().emit(optimized_ssa), encoding="utf-8")
    built = subprocess.run(
        [
            shutil.which("clang") or "clang",
            "-O2",
            "-Wno-override-module",
            str(llvm_path),
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr

    observations = [
        subprocess.run(
            [str(executable)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        for _ in range(2)
    ]
    assert [
        (completed.returncode, completed.stdout, completed.stderr)
        for completed in observations
    ] == [(0, expected, ""), (0, expected, "")]


def test_nested_rethrow_mutation_with_later_error_message_verifies() -> None:
    nested = "throw E0();"
    for index in range(24):
        nested = (
            f"try {{ {nested} }} catch (E0 nested{index}) {{ "
            "cleanupCount = cleanupCount + 1; throw; }"
        )
    source = f'''
struct E0 implements Error {{
    string message() {{ return "nested"; }}
}}
class LaterError implements Error {{
    string text;
    public string message() {{ return text; }}
}}
int main() {{
    int cleanupCount = 0;
    try {{ {nested} }}
    catch (E0 finalNested) {{ println(cleanupCount); }}
    Error later = LaterError("later");
    println(later.message());
    return 0;
}}
'''
    program = parse_source(source)
    TypeChecker().check(program)

    assert run_aether(source).output == "24\nlater\n"
    initial_ir = IRLowerer().lower(program)
    assert IRVerifier(initial_ir).verify() is initial_ir
    interpreter = IRInterpreter(initial_ir)
    assert interpreter.call("main") == 0
    assert interpreter.output == "24\nlater\n"


def test_interface_dispatch_only_function_has_consistent_nonthrowing_effect() -> None:
    source = _stress_source(seed_interface_throw_fact=False)
    program = parse_source(source)
    TypeChecker().check(program)

    initial_ir = IRLowerer().lower(program)
    assert IRVerifier(initial_ir).verify() is initial_ir
    function = next(
        function for function in initial_ir.functions if function.name == "interfaceStress"
    )
    assert not function.may_throw
    assert any(
        isinstance(instruction, IRInterfaceCall)
        and instruction.slot.method_id == "Error.message"
        and not instruction.slot.may_throw
        for block in function.blocks
        for instruction in block.instructions
    )
    assert not any(
        isinstance(instruction, IRInvokeInterface)
        for block in function.blocks
        for instruction in block.instructions
    )


def test_error_conformance_only_is_release_qualified_as_ordinary_interface_use() -> None:
    source = '''
struct PrintableError implements Error {
    string message() { return "ordinary-interface-use"; }
}
int main() {
    Error value = PrintableError();
    println(value.message());
    return 0;
}
'''
    typed = prepare_typed_program(source, TypeChecker())

    requirements = {
        requirement.capability for requirement in detect_required_capabilities(typed)
    }
    issues = backend_capability_issues(typed, BackendIdentity.NATIVE)

    assert Capability.ERROR_HANDLING not in requirements
    assert not any(
        issue.requirement.capability is Capability.ERROR_HANDLING
        for issue in issues
    )

    module = IRLowerer().lower_checked_program(typed.checked_program)
    main = next(function for function in module.functions if function.name == "main")
    assert any(
        isinstance(instruction, IRInterfaceCall)
        and instruction.slot.method_id == "Error.message"
        for block in main.blocks
        for instruction in block.instructions
    )
    assert not any(
        isinstance(instruction, IRInvokeInterface)
        for block in main.blocks
        for instruction in block.instructions
    )


def test_error_message_documentation_has_one_authoritative_rule() -> None:
    root = Path(__file__).resolve().parents[2]
    current_contracts = (
        root / "docs/compiler/EXCEPTION_ARCHITECTURE_RESOLUTION.md",
        root / "docs/compiler/COMPLETE_EXCEPTION_MODEL_RFC.md",
        root / "docs/compiler/exceptions/EXCEPTION_FROZEN_SEMANTICS_CHECKLIST.md",
        root / "docs/compiler/NATIVE_BOUNDARY_CONTAINMENT.md",
        root / "docs/compiler/adr/ADR-EXCEPTION-RUNTIME-ABI.md",
        root / "docs/aether/AETHER_LANGUAGE_SPEC_V1.md",
        root / "docs/aether/AETHER_NATIVE_PROFILE_V1.md",
        root / "docs/aether/AETHER_DIAGNOSTICS.md",
    )
    for document in current_contracts:
        text = document.read_text(encoding="utf-8")
        assert "`Error.message()`" in text, document
        assert "non-throwing" in text, document

    normative_capability_contracts = (
        root / "docs/aether/AETHER_LANGUAGE_SPEC_V1.md",
        root / "docs/aether/AETHER_NATIVE_PROFILE_V1.md",
    )
    for document in normative_capability_contracts:
        text = document.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        assert (
            "`ERROR_HANDLING` is required only when execution may require "
            "native exception semantics"
        ) in normalized, document
        assert "does not require" in normalized, document

    historical = (
        root / "docs/compiler/COMPLETE_EXCEPTION_MODEL_RFC.md",
        root / "docs/compiler/COMPLETE_EXCEPTION_MODEL_DECISION_LOG.md",
        root / "docs/compiler/CHECKED_EXCEPTIONS_ARCHITECTURE_STUDY.md",
    )
    for document in historical:
        opening = "\n".join(
            document.read_text(encoding="utf-8").splitlines()[:15]
        )
        assert "Historical status:" in opening, document

    runtime = (
        root / "src/aether/backend/llvm/exception_runtime.py"
    ).read_text(encoding="utf-8")
    assert "message_event_out" not in runtime
    assert "message_threw" not in runtime
    assert "recursive-throw containment" not in runtime
