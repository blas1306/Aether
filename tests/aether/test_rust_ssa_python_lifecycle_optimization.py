from __future__ import annotations

import importlib.util
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
