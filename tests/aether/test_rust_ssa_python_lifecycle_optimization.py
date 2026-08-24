from __future__ import annotations

from hashlib import sha256
import importlib.util
import inspect
import json
from pathlib import Path

import pytest

from aether.ir.dto import ir_module_to_dto
from aether.ir.lifecycle import LifecycleExpander, expand_lifecycle
from aether.ir.model import (
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInitDefault,
    IRModule,
    IRReturn,
    IRStorage,
    IRValue,
)
from aether.ir.types import IntType, MatrixType, StringType, VoidType


ROOT = Path(__file__).resolve().parents[2]
MEASURER = ROOT / "scripts/measure_rust_ssa_python_lifecycle_optimization.py"
CHECKER = ROOT / "scripts/check_rust_ssa_python_lifecycle_optimization.py"
EVIDENCE = ROOT / "docs/compiler/rust_ssa_python_lifecycle_optimization.json"
REPORT = ROOT / "docs/compiler/RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZATION.md"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_module(name: str, type_: object) -> IRModule:
    slot = IRStorage("slot", type_)
    return IRModule(
        [
            IRFunction(
                name,
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRInitDefault(slot), IRReturn()])],
            )
        ]
    )


def _invalid_module() -> IRModule:
    slot = IRStorage("slot", MatrixType(IntType()))
    return IRModule(
        [IRFunction("invalid", [], VoidType(), [IRBasicBlock("entry", [IRInitDefault(slot), IRReturn()])])]
    )


def test_operand_occurrences_are_discovered_once_per_instruction() -> None:
    value = IRValue("value", IntType())
    module = IRModule(
        [
            IRFunction(
                "count",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 1), IRReturn(value)],
                    )
                ],
            )
        ]
    )

    class CountingExpander(LifecycleExpander):
        operand_walks = 0

        def _instruction_operand_occurrences(self, instruction):
            self.operand_walks += 1
            return super()._instruction_operand_occurrences(instruction)

    expander = CountingExpander(module)
    optimized = expander.expand()

    assert expander.operand_walks == 2
    assert ir_module_to_dto(optimized) == ir_module_to_dto(expand_lifecycle(module))


def test_reference_normalizer_does_not_require_git_history(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _module("rust_3_13_measure_no_history", MEASURER)

    def unavailable(*_args, **_kwargs):
        raise AssertionError("ordinary qualification must not execute a subprocess")

    monkeypatch.setattr(runner.subprocess, "check_output", unavailable)
    module = _valid_module("no_history", StringType())

    assert ir_module_to_dto(runner._reference_normalizer()(module)) == ir_module_to_dto(
        expand_lifecycle(module)
    )


def test_frozen_reference_hash_is_exact_and_deterministic() -> None:
    runner = _module("rust_3_13_measure_fixture_hash", MEASURER)
    payload = runner.REFERENCE_FIXTURE.read_bytes()

    assert runner.BASELINE_REVISION == "b5987ef192f3a68a92bb5149787513939dcfcd16"
    assert runner.REFERENCE_FIXTURE_SHA256 == (
        "8b142a0e81145084a5017b38444e7c76fb619ec5c874791166f00dcf42037ada"
    )
    assert sha256(payload).hexdigest() == runner.REFERENCE_FIXTURE_SHA256
    assert runner._reference_fixture_source().encode("utf-8") == payload


def test_history_maintenance_check_accepts_match_and_rejects_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _module("rust_3_13_measure_history_check", MEASURER)
    payload = runner.REFERENCE_FIXTURE.read_bytes()

    def matching_history(command, *, cwd):
        assert command == [
            "git",
            "show",
            f"{runner.BASELINE_REVISION}:src/aether/ir/lifecycle.py",
        ]
        assert cwd == ROOT
        return payload

    monkeypatch.setattr(runner.subprocess, "check_output", matching_history)
    assert runner._verify_reference_fixture_against_history() == (
        runner.REFERENCE_FIXTURE_SHA256
    )

    altered = tmp_path / "altered_reference.py"
    altered.write_bytes(payload + b"# altered\n")
    with pytest.raises(RuntimeError, match="reference fixture SHA-256 mismatch"):
        runner._verify_reference_fixture_against_history(altered)

    monkeypatch.setattr(
        runner.subprocess,
        "check_output",
        lambda *_args, **_kwargs: payload + b"# altered history\n",
    )
    with pytest.raises(RuntimeError, match="differs from"):
        runner._verify_reference_fixture_against_history()


def test_before_measurement_route_is_the_frozen_preoptimization_reference() -> None:
    runner = _module("rust_3_13_measure_route", MEASURER)

    assert "reference = _reference_normalizer()" in inspect.getsource(runner.measure)
    assert 'implementations = {"before": reference, "after": expand_lifecycle}' in (
        inspect.getsource(runner._measure_module)
    )


def test_exact_baseline_and_optimized_normalized_ir_match_representative_corpus() -> None:
    runner = _module("rust_3_13_measure_reference", MEASURER)
    reference = runner._reference_normalizer()
    for relative in (
        "benchmarks/arithmetic.ae",
        "benchmarks/list_for_sum.ae",
        "examples/structs/custom_constructor_and_equality.ae",
        "examples/classes/implements_interface.ae",
        "corpus/exceptions/positive/cleanup_during_unwinding.ae",
    ):
        module, _digest = runner.base._load_module(relative)
        assert ir_module_to_dto(reference(module)) == ir_module_to_dto(
            expand_lifecycle(module)
        )


def test_reference_and_optimized_preserve_invalid_error_type_and_message() -> None:
    runner = _module("rust_3_13_measure_invalid", MEASURER)
    reference = runner._reference_normalizer()
    module = _invalid_module()

    with pytest.raises(ValueError) as before:
        reference(module)
    with pytest.raises(ValueError) as after:
        expand_lifecycle(module)

    assert type(before.value) is type(after.value)
    assert str(before.value) == str(after.value)


def test_invocations_do_not_share_mutable_state_in_all_required_orders() -> None:
    first = _valid_module("A", StringType())
    second = _valid_module("B", IntType())
    invalid = _invalid_module()
    expected_a = ir_module_to_dto(expand_lifecycle(first))
    expected_b = ir_module_to_dto(expand_lifecycle(second))

    assert [ir_module_to_dto(expand_lifecycle(item)) for item in (first, second)] == [expected_a, expected_b]
    assert [ir_module_to_dto(expand_lifecycle(item)) for item in (second, first)] == [expected_b, expected_a]
    assert [ir_module_to_dto(expand_lifecycle(item)) for item in (first, first)] == [expected_a, expected_a]
    with pytest.raises(ValueError):
        expand_lifecycle(invalid)
    assert ir_module_to_dto(expand_lifecycle(first)) == expected_a
    assert ir_module_to_dto(expand_lifecycle(second)) == expected_b
    with pytest.raises(ValueError):
        expand_lifecycle(invalid)


def test_checked_in_rust_3_13_evidence_passes_every_contract() -> None:
    record = _module("rust_3_13_checker", CHECKER).build_record(EVIDENCE, REPORT)

    assert record["decision"] == "RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZED"
    assert all(record["checks"].values())


def test_checker_rejects_corrupted_raw_samples(tmp_path: Path) -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    evidence["deep_cfg"][0]["measurements"]["lifecycle_normalization"]["before"][
        "median_seconds"
    ] += 1.0
    corrupted = tmp_path / "evidence.json"
    corrupted.write_text(json.dumps(evidence), encoding="utf-8")

    record = _module("rust_3_13_checker_corrupt", CHECKER).build_record(
        corrupted, REPORT
    )

    assert record["checks"]["comparable_raw_measurements"] is False
