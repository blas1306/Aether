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
    assert CAPABILITY_PROFILE_VERSION == "4"
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
class Box { int value; }
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
    assert {issue.requirement.capability for issue in issues} >= {
        Capability.CLASSES,
        Capability.ENUMS,
    }


def test_ast_accepts_feature_marked_complete() -> None:
    assert AST_CAPABILITY_PROFILE.support_for(Capability.INPUT).state is CapabilityState.COMPLETE
    assert run_aether('string name = input("Name: "); println(name);', input_reader=lambda: "Ada\n").output == "Name: Ada\n"


def test_ast_accepts_its_partial_expression_function_subset() -> None:
    assert AST_CAPABILITY_PROFILE.support_for(Capability.FUNCTION_VALUES).state is CapabilityState.PARTIAL
    assert run_aether("square(x) = x * x; println(square(3));").output == "9\n"


def test_native_rejects_unsupported_feature_before_ir_lowering(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_lowered(*_args, **_kwargs):
        raise AssertionError("IR lowering must not run")

    monkeypatch.setattr("aether.ir.lowering.IRLowerer.lower", fail_if_lowered)
    typed = _typed("class Box { int value; }")

    with pytest.raises(BackendCapabilityError) as captured:
        LLVMBuilder().emit_llvm(typed)

    assert captured.value.issues[0].diagnostic_code == "AE-BACKEND-CLASSES"
    assert "valid Aether" in captured.value.issues[0].hint


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

    assert "define i32 @main()" in llvm
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
