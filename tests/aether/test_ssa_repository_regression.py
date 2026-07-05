from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from aether.pipeline import IRBackend, prepare_typed_program
from aether.ssa import (
    GeneralSSABuilder,
    SSABranch,
    SSABuilder,
    SSAFunction,
    SSAInstruction,
    SSAJump,
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAVerifier,
    print_ssa,
)
from aether.typechecker import TypeChecker


ROOT_DIR = Path(__file__).resolve().parents[2]
EXAMPLE_ROOTS = (
    ROOT_DIR / "examples",
    ROOT_DIR / "examples" / "ir",
    ROOT_DIR / "benchmarks",
    ROOT_DIR / "samples",
    ROOT_DIR / "demos",
)


@dataclass(frozen=True)
class BuildResult:
    module: SSAModule | None
    error: Exception | None

    @property
    def ok(self) -> bool:
        return self.module is not None


@dataclass
class RegressionStats:
    discovered: int = 0
    lowered: int = 0
    compared: int = 0
    successful_comparisons: int = 0
    pattern_passed: int = 0
    general_passed: int = 0
    pattern_only: int = 0
    general_only: int = 0
    non_comparable: int = 0


def test_general_ssa_matches_pattern_for_supported_repository_examples(request) -> None:
    paths = _discover_aether_examples()
    stats = RegressionStats(discovered=len(paths))
    failures: list[str] = []

    for path in paths:
        try:
            ir_module = IRBackend().lower_verified(
                prepare_typed_program(
                    path.read_text(encoding="utf-8"),
                    TypeChecker(source_root=path.parent),
                )
            )
        except Exception:
            stats.non_comparable += 1
            continue

        stats.lowered += 1
        pattern = _build_pattern(ir_module)
        general = _build_general(ir_module)

        if pattern.ok:
            stats.pattern_passed += 1
        if general.ok:
            stats.general_passed += 1

        if pattern.ok and not general.ok:
            stats.pattern_only += 1
            failures.append(
                f"{_relative(path)}: General SSA failed where Pattern passed: "
                f"{general.error}"
            )
            continue

        if not pattern.ok:
            if general.ok:
                stats.general_only += 1
            else:
                stats.non_comparable += 1
            continue

        assert general.module is not None
        assert pattern.module is not None
        stats.compared += 1

        try:
            _assert_equivalent_supported_properties(
                pattern.module,
                general.module,
                path,
            )
        except AssertionError as error:
            failures.append(f"{_relative(path)}: {error}")
            continue

        stats.successful_comparisons += 1

    _write_summary(request, stats)

    if failures:
        pytest.fail(
            "General SSA repository regression failures:\n\n"
            + "\n\n".join(failures)
        )


def _discover_aether_examples() -> list[Path]:
    paths: set[Path] = set()
    for root in EXAMPLE_ROOTS:
        if root.exists():
            paths.update(root.rglob("*.ae"))
    return sorted(paths)


def _build_pattern(module) -> BuildResult:
    try:
        ssa_module = SSABuilder().build(module)
        SSAVerifier(ssa_module).verify()
        return BuildResult(ssa_module, None)
    except Exception as error:
        return BuildResult(None, error)


def _build_general(module) -> BuildResult:
    try:
        ssa_module = GeneralSSABuilder().build(module)
        SSAVerifier(ssa_module).verify()
        return BuildResult(ssa_module, None)
    except Exception as error:
        return BuildResult(None, error)


def _assert_equivalent_supported_properties(
    pattern: SSAModule,
    general: SSAModule,
    path: Path,
) -> None:
    _assert_no_slot_traffic(pattern, path, "Pattern")
    _assert_no_slot_traffic(general, path, "General")
    assert [function.name for function in general.functions] == [
        function.name for function in pattern.functions
    ], "function list differs"

    pattern_functions = {function.name: function for function in pattern.functions}
    general_functions = {function.name: function for function in general.functions}
    for name, pattern_function in pattern_functions.items():
        general_function = general_functions[name]
        _assert_signature_matches(pattern_function, general_function, name)
        _assert_blocks_match(pattern_function, general_function, name)
        _assert_phi_counts_match(pattern_function, general_function, name)
        _assert_terminators_match(pattern_function, general_function, name)


def _assert_no_slot_traffic(module: SSAModule, path: Path, builder_name: str) -> None:
    printed = print_ssa(module)
    assert " load " not in printed, (
        f"{builder_name} SSA for {_relative(path)} still contains load traffic"
    )
    assert " store " not in printed, (
        f"{builder_name} SSA for {_relative(path)} still contains store traffic"
    )
    assert "\n    load " not in printed, (
        f"{builder_name} SSA for {_relative(path)} still contains load traffic"
    )
    assert "\n    store " not in printed, (
        f"{builder_name} SSA for {_relative(path)} still contains store traffic"
    )


def _assert_signature_matches(
    pattern: SSAFunction,
    general: SSAFunction,
    function_name: str,
) -> None:
    assert [(parameter.name, parameter.type) for parameter in general.parameters] == [
        (parameter.name, parameter.type) for parameter in pattern.parameters
    ], f"signature differs for function '{function_name}'"
    assert general.return_type == pattern.return_type, (
        f"return type differs for function '{function_name}'"
    )


def _assert_blocks_match(
    pattern: SSAFunction,
    general: SSAFunction,
    function_name: str,
) -> None:
    assert [block.name for block in general.blocks] == [
        block.name for block in pattern.blocks
    ], f"block list differs for function '{function_name}'"


def _assert_phi_counts_match(
    pattern: SSAFunction,
    general: SSAFunction,
    function_name: str,
) -> None:
    assert _phi_counts_by_block(general) == _phi_counts_by_block(pattern), (
        f"phi counts differ for function '{function_name}'"
    )


def _phi_counts_by_block(function: SSAFunction) -> dict[str, int]:
    return {
        block.name: sum(
            isinstance(instruction, SSAPhi) for instruction in block.instructions
        )
        for block in function.blocks
    }


def _assert_terminators_match(
    pattern: SSAFunction,
    general: SSAFunction,
    function_name: str,
) -> None:
    pattern_blocks = {block.name: block for block in pattern.blocks}
    general_blocks = {block.name: block for block in general.blocks}

    for name, pattern_block in pattern_blocks.items():
        pattern_terminator = pattern_block.instructions[-1]
        general_terminator = general_blocks[name].instructions[-1]
        assert _terminator_shape(general_terminator) == _terminator_shape(
            pattern_terminator
        ), f"terminator differs in function '{function_name}' block '{name}'"


def _terminator_shape(instruction: SSAInstruction) -> tuple[object, ...]:
    if isinstance(instruction, SSABranch):
        return (
            SSABranch,
            instruction.condition.type,
            instruction.true_target,
            instruction.false_target,
        )
    if isinstance(instruction, SSAJump):
        return (SSAJump, instruction.target)
    if isinstance(instruction, SSAReturn):
        return (
            SSAReturn,
            None if instruction.value is None else instruction.value.type,
        )
    raise AssertionError(f"Expected terminator, got {type(instruction).__name__}")


def _write_summary(request, stats: RegressionStats) -> None:
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return

    lines = (
        f"Programs discovered: {stats.discovered}",
        f"Programs lowered to IR: {stats.lowered}",
        f"Programas comparados: {stats.compared}",
        f"Comparaciones exitosas: {stats.successful_comparisons}",
        f"Pattern paso: {stats.pattern_passed}",
        f"General paso: {stats.general_passed}",
        f"Pattern-only: {stats.pattern_only}",
        f"General-only: {stats.general_only}",
        f"No comparables: {stats.non_comparable}",
    )
    reporter.write_sep("-", "SSA repository regression")
    for line in lines:
        reporter.write_line(line)


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT_DIR))
