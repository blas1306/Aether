import json
from pathlib import Path

from aether.benchmark import _optimized_ssa
from aether.ir.types import StringType
from aether.optimization import optimization_profile
from aether.ssa import model as m


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/compiler/o2_immediate_array_string_borrow.json"
EXPENSE = ROOT / "examples/expense_tracker/Main.ae"
FUNCTION = "__ae_m11_Persistence__function_12_decodeLedger"


def _current_sites():
    module = _optimized_ssa(
        EXPENSE.read_text(encoding="utf-8"), EXPENSE, optimization_profile("O2")
    )
    function = next(item for item in module.functions if item.name == FUNCTION)
    rows = {}
    for block in function.blocks:
        for index, instruction in enumerate(block.instructions):
            if not isinstance(instruction, m.SSAArrayGet):
                continue
            if not isinstance(instruction.result.type, StringType):
                continue
            rows[instruction.result.name] = (block, index, instruction)
    return rows


def test_companion_report_is_canonical_and_preserves_historical_layers():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert REPORT.read_text(encoding="utf-8") == json.dumps(
        report, indent=2, sort_keys=True
    ) + "\n"
    assert report["pre_o2_9_7"]["explicit_ssa"] == {"retain": 48, "release": 904}
    assert report["post_o2_9_7"]["explicit_ssa"] == {"retain": 48, "release": 901}
    assert [row["consumer"] for row in report["candidates"]] == [
        "byteLength", "parseInt", "parseInt",
    ]


def test_exact_three_sites_are_borrowed_and_stable_region_remains_owned():
    sites = _current_sites()
    expected = {
        "365": ("logic.rhs37", "__aether_string_byte_length"),
        "484": ("merge49", "parseInt"),
        "587": ("merge57", "parseInt"),
    }
    for value, (block_name, builtin) in expected.items():
        block, index, get = sites[value]
        assert block.name == block_name
        assert get.borrowed
        consumer = block.instructions[index + 1]
        assert isinstance(consumer, m.SSACall)
        assert consumer.builtin == builtin
        assert consumer.arguments.count(get.result) == 1
        assert not any(
            isinstance(item, m.SSACall)
            and item.builtin == "__aether_release"
            and item.arguments == (get.result,)
            for item in block.instructions
        )

    stable_block, stable_index, stable = sites["373"]
    assert stable_block.name == "logic.rhs38"
    assert not stable.borrowed
    assert stable_index + 1 < len(stable_block.instructions)
