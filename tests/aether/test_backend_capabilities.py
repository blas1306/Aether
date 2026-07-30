from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from aether.backend.llvm import LLVMBuilder
from aether.capabilities import (
    AST_CAPABILITY_PROFILE,
    BACKEND_CAPABILITY_PROFILES,
    CAPABILITY_CATALOG,
    CAPABILITY_PROFILE_VERSION,
    E2E_TESTED_CAPABILITIES,
    NATIVE_CAPABILITY_PROFILE,
    BackendCapabilityError,
    BackendCapabilityProfile,
    BackendIdentity,
    Capability,
    CapabilityState,
    backend_capability_issues,
    detect_required_capabilities,
    validate_backend_capabilities,
)
from aether.pipeline import prepare_typed_program
from aether.errors import AetherTypeError
from aether.runner import run_aether
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]


def _typed(source: str, *, source_root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=source_root))


def _required(source: str, *, source_root: Path | None = None):
    return {
        requirement.capability: requirement
        for requirement in detect_required_capabilities(
            _typed(source, source_root=source_root)
        )
    }


def test_profiles_are_versioned_identified_and_cover_the_canonical_catalog() -> None:
    assert CAPABILITY_PROFILE_VERSION == "23"
    assert AST_CAPABILITY_PROFILE.backend is BackendIdentity.AST
    assert NATIVE_CAPABILITY_PROFILE.backend is BackendIdentity.NATIVE
    assert AST_CAPABILITY_PROFILE.version == CAPABILITY_PROFILE_VERSION
    assert NATIVE_CAPABILITY_PROFILE.version == CAPABILITY_PROFILE_VERSION
    assert set(BACKEND_CAPABILITY_PROFILES) == {
        BackendIdentity.AST,
        BackendIdentity.NATIVE,
    }
    assert set(CAPABILITY_CATALOG) == set(Capability)
    assert len({definition.diagnostic_code for definition in CAPABILITY_CATALOG.values()}) == len(Capability)
    assert (
        AST_CAPABILITY_PROFILE.support_for(Capability.COLLECTION_OBJECT_LIFECYCLE).state
        is CapabilityState.PARTIAL
    )
    assert (
        NATIVE_CAPABILITY_PROFILE.support_for(Capability.COLLECTION_OBJECT_LIFECYCLE).state
        is CapabilityState.COMPLETE
    )
    assert (
        AST_CAPABILITY_PROFILE.support_for(Capability.PROCESS_ARGUMENTS).state
        is CapabilityState.COMPLETE
    )
    assert (
        NATIVE_CAPABILITY_PROFILE.support_for(Capability.PROCESS_ARGUMENTS).state
        is CapabilityState.PARTIAL
    )
    assert (
        NATIVE_CAPABILITY_PROFILE.support_for(Capability.FOR).state
        is CapabilityState.PARTIAL
    )
    assert (
        NATIVE_CAPABILITY_PROFILE.support_for(Capability.INTERFACES).state
        is CapabilityState.COMPLETE
    )
    assert "native-interface-abi" not in {capability.value for capability in Capability}
    assert "string-split-trim" not in {capability.value for capability in Capability}
    for capability in (
        Capability.ATOMIC_TEXT_FILE_WRITE,
        Capability.DURABLE_TEXT_FILE_WRITE,
        Capability.EXPENSE_LEDGER_ATOMIC_SAVE,
    ):
        assert AST_CAPABILITY_PROFILE.support_for(capability).state is CapabilityState.PARTIAL
        assert NATIVE_CAPABILITY_PROFILE.support_for(capability).state is CapabilityState.PARTIAL


def test_profile_rejects_unknown_capabilities_and_invalid_states() -> None:
    with pytest.raises(ValueError, match="Unknown backend capability"):
        AST_CAPABILITY_PROFILE.support_for("not-a-capability")  # type: ignore[arg-type]

    capabilities = dict(AST_CAPABILITY_PROFILE.capabilities)
    capabilities[Capability.INPUT] = replace(
        capabilities[Capability.INPUT],
        state="available",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="Invalid state"):
        BackendCapabilityProfile(
            BackendIdentity.AST,
            CAPABILITY_PROFILE_VERSION,
            capabilities,
        )


def test_complete_capabilities_have_registered_e2e_evidence() -> None:
    for backend, profile in BACKEND_CAPABILITY_PROFILES.items():
        complete = {
            capability
            for capability, support in profile.capabilities.items()
            if support.state is CapabilityState.COMPLETE
        }
        assert complete <= E2E_TESTED_CAPABILITIES[backend]


def test_detector_reports_only_capabilities_used_by_simple_checked_program() -> None:
    required = _required("int main() { int x = 1 + 2; return x; }")

    assert {
        Capability.FUNCTIONS,
        Capability.PRIMITIVE_TYPES,
        Capability.VARIABLES_AND_CONST,
        Capability.ARITHMETIC,
        Capability.INTEGER_SAFETY,
        Capability.RETURN,
    } <= set(required)
    assert Capability.MODULES not in required
    assert Capability.CLASSES not in required


def test_detector_reports_import_and_deduplicates_repeated_imports(tmp_path: Path) -> None:
    (tmp_path / "One.ae").write_text("package One; public int one() { return 1; }", encoding="utf-8")
    (tmp_path / "Two.ae").write_text("package Two; public int two() { return 2; }", encoding="utf-8")
    required = _required(
        "import One; import Two; int main() { return One.one() + Two.two(); }",
        source_root=tmp_path,
    )

    assert required[Capability.IMPORTS].line == 1
    assert required[Capability.MODULES].line == 1
    assert sum(capability is Capability.IMPORTS for capability in required) == 1


@pytest.mark.parametrize(
    ("source", "capability"),
    [
        ("class Box { int value; }", Capability.CLASSES),
        ("interface Value { int get(); }", Capability.INTERFACES),
        ("enum Color { Red, Blue }", Capability.ENUMS),
        ("int main() { double x = sqrt(4.0); return 0; }", Capability.SCALAR_MATH),
        ("import Math; int main() { double x = Math.pi; return 0; }", Capability.SCALAR_MATH),
        ("import Math as M; int main() { int x = M.factorial(4); return 0; }", Capability.SCALAR_MATH),
        ('int main() { string x = input("x: "); return 0; }', Capability.INPUT),
        ('int main() { try { throw "bad"; } catch (error) { println(error); } return 0; }', Capability.ERROR_HANDLING),
    ],
)
def test_detector_reports_major_ast_only_features(source: str, capability: Capability) -> None:
    assert capability in _required(source)


def test_approved_exception_syntax_remains_unsupported_and_never_reaches_ir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = _typed(
        """
int main() {
    try {
        throw "legacy placeholder";
    } catch (FileError file_error) {
        println(file_error);
    } catch (Error error) {
        throw;
    }
    return 0;
}
"""
    )

    assert (
        NATIVE_CAPABILITY_PROFILE.support_for(Capability.ERROR_HANDLING).state
        is CapabilityState.UNSUPPORTED
    )
    issue = next(
        issue
        for issue in backend_capability_issues(typed, BackendIdentity.NATIVE)
        if issue.requirement.capability is Capability.ERROR_HANDLING
    )
    assert issue.diagnostic_code == "AE-BACKEND-ERROR_HANDLING"

    def fail_if_lowered(*_args, **_kwargs):
        raise AssertionError("IR lowering must not run for exception syntax")

    monkeypatch.setattr(
        "aether.ir.lowering.IRLowerer.lower_checked_program",
        fail_if_lowered,
    )
    with pytest.raises(BackendCapabilityError, match="AE-BACKEND-ERROR_HANDLING"):
        LLVMBuilder().emit_llvm(typed)


def test_detector_reports_function_reference_used_by_plots() -> None:
    source = """
import Plots;
double f(double x) { return x; }
int main() { Plots.plot(f, 0.0, 1.0); return 0; }
"""
    requirement = _required(source)[Capability.FUNCTION_VALUES]

    assert requirement.detail == "function passed as a value"
    assert requirement.line == 4


def test_multiple_native_issues_are_deduplicated_and_keep_locations() -> None:
    typed = _typed(
        """
class Box { int value; int get() { return value; } }
enum Color { Red, Blue }
int main() {
    double a = sqrt(4.0);
    double b = abs(a);
    return 0;
}
"""
    )
    issues = backend_capability_issues(typed, BackendIdentity.NATIVE)

    assert [issue.requirement.capability for issue in issues].count(Capability.SCALAR_MATH) == 0
    assert issues == ()
    assert Capability.ENUMS not in {issue.requirement.capability for issue in issues}


def test_ast_accepts_feature_marked_complete() -> None:
    assert AST_CAPABILITY_PROFILE.support_for(Capability.INPUT).state is CapabilityState.COMPLETE
    assert run_aether('string name = input("Name: "); println(name);', input_reader=lambda: "Ada\n").output == "Name: Ada\n"


def test_ast_accepts_abbreviated_function_as_normal_typed_function() -> None:
    assert run_aether("square(int x) = x * x; println(square(3));").output == "9\n"


def test_native_accepts_class_methods_through_ir_lowering() -> None:
    typed = _typed(
        "class Box { int value; public int get() { return value; } } "
        "int main() { Box box = Box(7); return box.get(); }"
    )

    assert backend_capability_issues(typed, BackendIdentity.NATIVE) == ()
    assert "define i32 @Box.get(ptr %this)" in LLVMBuilder().emit_llvm(typed)


def test_native_still_emits_supported_program_and_runs_ssa_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aether.ssa.verifier import SSAVerifier

    calls = 0
    original = SSAVerifier.verify

    def recording_verify(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(SSAVerifier, "verify", recording_verify)
    llvm = LLVMBuilder().emit_llvm(_typed("int main() { return 0; }"))

    assert "define i32 @__aether_program_main()" in llvm
    assert "define i32 @main(i32 %argc, ptr %argv)" in llvm
    assert calls >= 1


def test_partial_string_capability_accepts_transport_but_rejects_interpolation() -> None:
    assert NATIVE_CAPABILITY_PROFILE.support_for(Capability.STRINGS).state is CapabilityState.PARTIAL
    LLVMBuilder().emit_llvm(_typed('string identity(string x) { return x; } int main() { println(identity("ok")); return 0; }'))

    typed = _typed('int main() { int n = 2; println("n = $n$"); return 0; }')
    with pytest.raises(BackendCapabilityError) as captured:
        validate_backend_capabilities(typed, BackendIdentity.NATIVE)

    issue = next(issue for issue in captured.value.issues if issue.requirement.capability is Capability.STRINGS)
    assert issue.state is CapabilityState.PARTIAL
    assert issue.requirement.detail == "interpolated string"


def test_string_literal_transport_is_not_mistaken_for_a_dynamic_operation() -> None:
    typed = _typed('string choose(boolean flag) { if (flag) { return "yes"; } return "no"; }')

    issues = backend_capability_issues(typed, BackendIdentity.NATIVE)

    assert not any(issue.requirement.capability is Capability.STRINGS for issue in issues)
    LLVMBuilder().emit_llvm(typed)


def test_native_accepts_concat_and_string_equality() -> None:
    typed = _typed("string operation(string left, string right) { return left + right; }")
    assert not backend_capability_issues(typed, BackendIdentity.NATIVE)
    assert "call ptr @aether_string_concat" in LLVMBuilder().emit_llvm(typed)

    equality = _typed(
        "string operation(string left, string right) { "
        "string copy = left; boolean result = left == right; return copy; }"
    )
    assert not backend_capability_issues(equality, BackendIdentity.NATIVE)


def test_string_concat_and_byte_length_are_complete_profile_14_capabilities() -> None:
    required = _required(
        'int main() { string value = "é" + "🙂"; return value.byteLength; }'
    )

    assert Capability.STRING_CONCATENATION in required
    assert Capability.STRING_BYTE_LENGTH in required
    assert (
        NATIVE_CAPABILITY_PROFILE.support_for(Capability.STRING_CONCATENATION).state
        is CapabilityState.COMPLETE
    )
    assert (
        NATIVE_CAPABILITY_PROFILE.support_for(Capability.STRING_BYTE_LENGTH).state
        is CapabilityState.COMPLETE
    )


def test_string_capability_diagnostic_is_deduplicated() -> None:
    typed = _typed(
        "string join(string left, string right) { "
        "string first = left + right; return first + right; }"
    )

    issues = [
        issue
        for issue in backend_capability_issues(typed, BackendIdentity.NATIVE)
        if issue.requirement.capability is Capability.STRING_CONCATENATION
    ]

    assert issues == []


def test_string_operations_in_imported_modules_are_supported(tmp_path: Path) -> None:
    (tmp_path / "Text.ae").write_text(
        "package Text; public string join(string left, string right) { return left + right; }",
        encoding="utf-8",
    )
    typed = _typed(
        'import Text; int main() { println("transport only"); return 0; }',
        source_root=tmp_path,
    )

    assert not any(
        issue.requirement.capability is Capability.STRING_CONCATENATION
        for issue in backend_capability_issues(typed, BackendIdentity.NATIVE)
    )
    assert "call ptr @aether_string_concat" in LLVMBuilder().emit_llvm(typed)


def test_numerical_methods_example_is_accepted_by_native_profile() -> None:
    example = ROOT / "examples" / "numerical_methods"
    typed = _typed((example / "main.ae").read_text(encoding="utf-8"), source_root=example)

    issues = backend_capability_issues(typed, BackendIdentity.NATIVE)
    assert not any(issue.requirement.capability is Capability.MODULES for issue in issues)
    assert not any(issue.requirement.capability is Capability.IMPORTS for issue in issues)
    assert not any(issue.requirement.capability is Capability.FUNCTION_VALUES for issue in issues)
    assert not any(issue.requirement.capability is Capability.INTERFACES for issue in issues)
    assert not any(issue.requirement.capability is Capability.ERROR_HANDLING for issue in issues)
    assert not any(issue.requirement.capability is Capability.SCALAR_MATH for issue in issues)
    assert "call double %" in LLVMBuilder().emit_llvm(typed)


def test_native_scalar_math_profile_accepts_consolidated_and_rejects_experimental_calls() -> None:
    assert NATIVE_CAPABILITY_PROFILE.support_for(Capability.SCALAR_MATH).state is CapabilityState.PARTIAL

    supported = _typed("int main() { double x = sqrt(4.0) + sin(0.0); return 0; }")
    assert not any(
        issue.requirement.capability is Capability.SCALAR_MATH
        for issue in backend_capability_issues(supported, BackendIdentity.NATIVE)
    )

    experimental = _typed("int main() { double x = real(1.0); return 0; }")
    issue = next(
        issue
        for issue in backend_capability_issues(experimental, BackendIdentity.NATIVE)
        if issue.requirement.capability is Capability.SCALAR_MATH
    )
    assert issue.requirement.requires_complete_support is True
    assert issue.requirement.detail == "experimental scalar builtin 'real'"


@pytest.mark.parametrize(
    ("source", "capability", "detail"),
    [
        (
            "int main() { boolean value = boolean(1); return 0; }",
            Capability.PRIMITIVE_TYPES,
            "cast from 'int' to 'boolean'",
        ),
        (
            "int main() { value = 1; return value; }",
            Capability.VARIABLES_AND_CONST,
            "implicit declaration by assignment",
        ),
        (
            "float identity(float value) { return value; } int main() { float value = float(16777217); println(identity(value)); return 0; }",
            Capability.PRIMITIVE_TYPES,
            "type 'float' has no stable LLVM/native ABI",
        ),
        (
            "(int, int) pair() { return (1, 2); } int main() { return 0; }",
            Capability.PRIMITIVE_TYPES,
            "tuple type",
        ),
        (
            "int main() { List<int> values = {1}; return values.size(); }",
            Capability.LIST,
            "List.size() has no LLVM/native lowering",
        ),
        (
            'import Plots; int main() { Plots.title("sound gate"); return 0; }',
            Capability.MODULES,
            "has no LLVM/native lowering",
        ),
        (
            "Vector<int, Row> pass(Vector<int, Row> value) { return value; } int main() { return 0; }",
            Capability.VECTOR,
            "carries shape metadata across a function boundary",
        ),
        (
            "int main() { Array<Vector<int, Row>> values = {[1, 2]}; return 0; }",
            Capability.AGGREGATE_COLLECTION_ELEMENTS,
            "shape metadata is not preserved",
        ),
        (
            "int main() { println(); return 0; }",
            Capability.PRINT,
            "zero-argument println()",
        ),
        (
            "int main() { Array<int> inner = {1}; Array<Array<int>> outer = {inner}; println(outer); return 0; }",
            Capability.PRINT,
            "unsupported element type 'Array<int>'",
        ),
        (
            'int main() { Exception error = Exception("bad"); return 0; }',
            Capability.ERROR_HANDLING,
            "Exception",
        ),
    ],
    ids=(
        "boolean-cast",
        "implicit-declaration",
        "float",
        "tuple",
        "list-size",
        "unsupported-builtin",
        "shape-bearing-signature",
        "shape-bearing-collection",
        "empty-print",
        "nested-collection-print",
        "exception-value",
    ),
)
def test_native_soundness_regressions_reject_before_lowering(
    source: str,
    capability: Capability,
    detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = _typed(source)
    issue = next(
        issue
        for issue in backend_capability_issues(typed, BackendIdentity.NATIVE)
        if issue.requirement.capability is capability
    )

    assert detail in (issue.requirement.detail or "")
    assert issue.diagnostic_code == CAPABILITY_CATALOG[capability].diagnostic_code
    assert issue.requirement.line >= 1
    assert issue.requirement.column >= 1

    def fail_if_lowered(*_args, **_kwargs):
        raise AssertionError("IR lowering must not run")

    monkeypatch.setattr(
        "aether.ir.lowering.IRLowerer.lower_checked_program",
        fail_if_lowered,
    )
    with pytest.raises(BackendCapabilityError):
        LLVMBuilder().emit_llvm(typed)


@pytest.mark.parametrize(
    "source",
    [
        "int main() { return 7 % 3; }",
        "int main() { double value = double(1); println(value); return 0; }",
        "int main() { int value = 1; value = 2; return value; }",
        "double sum(double left, double right) { return left + right; } int main() { return 0; }",
        "int main() { List<int> values = {2, 1}; values.sort(); return values.length; }",
        "int main() { Vector<int, Row> value = [1, 2]; return value.length; }",
        'int main() { println("ok"); return 0; }',
        "int main() { for (i in 1:2:3) { println(i); } return 0; }",
    ],
    ids=(
        "int-remainder",
        "explicit-double-cast",
        "declared-assignment",
        "homogeneous-arithmetic",
        "supported-sort-and-length",
        "local-vector-shape",
        "print-value",
        "nonzero-range-step",
    ),
)
def test_native_soundness_positive_subsets_emit_llvm(source: str) -> None:
    typed = _typed(source)

    assert backend_capability_issues(typed, BackendIdentity.NATIVE) == ()
    assert "define i32 @main(i32 %argc, ptr %argv)" in LLVMBuilder().emit_llvm(typed)


def test_declaration_only_module_emits_valid_library_llvm_and_build_rejects_before_lowering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = _typed("int helper() { return 1; }")
    llvm = LLVMBuilder().emit_llvm(typed)

    assert "define i32 @helper()" in llvm
    assert "define i32 @main(i32 %argc, ptr %argv)" not in llvm
    assert "@__aether_program_main" not in llvm

    def fail_if_lowered(*_args, **_kwargs):
        raise AssertionError("IR lowering must not run")

    monkeypatch.setattr(
        "aether.ir.lowering.IRLowerer.lower_checked_program",
        fail_if_lowered,
    )
    with pytest.raises(AetherTypeError, match="requires one entry point"):
        LLVMBuilder().build(typed, output_path=tmp_path / "program")


def test_platform_partial_process_arguments_reject_before_lowering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = _typed(
        "import System; int main() { Array<string> arguments = System.args(); return arguments.length; }"
    )
    monkeypatch.setattr("aether.capabilities.sys.platform", "win32")

    issue = next(
        issue
        for issue in backend_capability_issues(typed, BackendIdentity.NATIVE)
        if issue.requirement.capability is Capability.PROCESS_ARGUMENTS
    )
    assert issue.requirement.requires_complete_support is True

    def fail_if_lowered(*_args, **_kwargs):
        raise AssertionError("IR lowering must not run")

    monkeypatch.setattr(
        "aether.ir.lowering.IRLowerer.lower_checked_program",
        fail_if_lowered,
    )
    with pytest.raises(BackendCapabilityError):
        LLVMBuilder().emit_llvm(typed)
