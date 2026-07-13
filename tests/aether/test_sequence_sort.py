from __future__ import annotations

import math
import shutil

import pytest

from aether.backend.llvm import LLVMRunner, print_llvm
from aether.errors import AetherTypeError
from aether.ir import (
    ArrayType as IRArrayType,
    DoubleType,
    IRArrayNew,
    IRBasicBlock,
    IRConst,
    IRFunction,
    IRInterpreter,
    IRLowerer,
    IRModule,
    IRReturn,
    IRSequenceSort,
    IRValue,
    StringType,
)
from aether.ir.optimizer import OptimizerPipeline
from aether.pipeline import lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSASequenceSort
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.stdlib.core import sort_builtin
from aether.typechecker import TypeChecker
from aether.types import AetherValue, ArrayType, ListType


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


@pytest.mark.parametrize("container", ["List", "Array"])
@pytest.mark.parametrize(
    ("element_type", "literal", "expected"),
    [
        ("int", "{}", []),
        ("int", "{7}", [7]),
        ("int", "{1, 2, 3}", [1, 2, 3]),
        ("int", "{4, 3, 2, 1}", [1, 2, 3, 4]),
        ("int", "{3, 1, 3, 2, 1}", [1, 1, 2, 3, 3]),
        ("double", "{4.0, 1.0, 2.0, -3.0}", [-3.0, 1.0, 2.0, 4.0]),
        ("string", '{"z", "A", "a", "é", "aa"}', ["A", "a", "aa", "z", "é"]),
    ],
)
def test_ast_runtime_sorts_array_and_list_in_place(
    container: str,
    element_type: str,
    literal: str,
    expected: list[object],
) -> None:
    result = run_aether(f"{container}<{element_type}> xs = {literal}; xs.sort();")

    assert [element.value for element in result.env["xs"].value] == expected


@pytest.mark.parametrize("container", ["List", "Array"])
def test_sort_alias_observes_same_mutated_container(container: str) -> None:
    result = run_aether(
        f"""
{container}<int> a = {{3, 2, 1}};
{container}<int> b = a;
b.sort();
"""
    )

    assert result.env["a"].value is result.env["b"].value
    assert [element.value for element in result.env["a"].value] == [1, 2, 3]


@pytest.mark.parametrize("container", ["List", "Array"])
def test_sort_preserves_length_and_returns_void(container: str) -> None:
    result = run_aether(
        f"""
{container}<int> xs = {{3, 1, 2}};
int before = xs.length;
xs.sort();
int after = xs.length;
"""
    )

    assert result.env["before"].value == result.env["after"].value == 3
    with pytest.raises(AetherTypeError, match="void"):
        run_aether(f"{container}<int> xs = {{2, 1}}; int result = xs.sort();")


def test_runtime_double_total_order_and_stability() -> None:
    nan_first = AetherValue("double", float("nan"))
    nan_second = AetherValue("double", -float("nan"))
    negative_zero = AetherValue("double", -0.0)
    positive_zero = AetherValue("double", 0.0)
    values = [
        nan_first,
        AetherValue("double", float("inf")),
        negative_zero,
        AetherValue("double", float("-inf")),
        positive_zero,
        nan_second,
        AetherValue("double", 2.0),
    ]
    sequence = AetherValue(ListType("double"), values)

    result = sort_builtin([sequence])

    assert result.type_name == "void"
    assert [item.value for item in values[:4]] == [float("-inf"), -0.0, 0.0, 2.0]
    assert values[1] is negative_zero
    assert values[2] is positive_zero
    assert values[4].value == float("inf")
    assert values[5] is nan_first and math.isnan(values[5].value)
    assert values[6] is nan_second and math.isnan(values[6].value)


def test_ir_interpreter_uses_utf8_byte_order_and_double_total_order() -> None:
    def execute(element_type, raw_values):
        constants = tuple(IRValue(f"v{index}", element_type) for index in range(len(raw_values)))
        sequence = IRValue("sequence", IRArrayType(element_type))
        instructions = [IRConst(value, raw) for value, raw in zip(constants, raw_values)]
        instructions.extend([IRArrayNew(sequence, constants), IRSequenceSort(sequence), IRReturn(sequence)])
        module = IRModule(
            [IRFunction("sort_values", [], sequence.type, [IRBasicBlock("entry", instructions)])]
        )
        return IRInterpreter(module).call("sort_values")

    nan_a = float("nan")
    nan_b = -float("nan")
    doubles = execute(DoubleType(), [nan_a, 1.0, -0.0, float("-inf"), 0.0, float("inf"), nan_b])
    strings = execute(StringType(), ["é", "z", "aa", "a", "A"])

    assert doubles[:5] == [float("-inf"), -0.0, 0.0, 1.0, float("inf")]
    assert math.isnan(doubles[5]) and math.isnan(doubles[6])
    assert strings == ["A", "a", "aa", "z", "é"]


@pytest.mark.parametrize(
    ("declaration", "element_type"),
    [
        ("", "boolean"),
        ("", "int?"),
        ("struct Point { int x; }", "Point"),
        ("class Box { int x; }", "Box"),
        ("interface Named { string name(); }", "Named"),
        ("enum Color { Red, Blue }", "Color"),
        ("", "List<int>"),
        ("", "Array<int>"),
        ("", "Vector<int>"),
        ("", "Matrix<int>"),
    ],
)
@pytest.mark.parametrize("container", ["List", "Array"])
def test_sort_rejects_every_non_orderable_type(
    declaration: str,
    element_type: str,
    container: str,
) -> None:
    source = f"{declaration}\nvoid reject({container}<{element_type}> xs) {{ xs.sort(); }}"

    with pytest.raises(AetherTypeError):
        _typed(source)


def test_sort_lowers_to_one_common_side_effecting_ir_and_ssa_instruction() -> None:
    source = """
int main() {
    Array<int> a = {2, 1};
    List<int> b = {4, 3};
    a.sort();
    b.sort();
    return a[0] + b[0];
}
"""
    typed = _typed(source)
    ir = OptimizerPipeline().run(IRLowerer().lower(typed.program))
    ssa = SSAOptimizerPipeline().run(lower_to_verified_ssa(typed))

    assert sum(isinstance(item, IRSequenceSort) for block in ir.functions[0].blocks for item in block.instructions) == 2
    assert sum(isinstance(item, SSASequenceSort) for block in ssa.functions[0].blocks for item in block.instructions) == 2


def test_llvm_array_and_list_reuse_the_same_specialized_helpers() -> None:
    source = """
int main() {
    Array<int> ai = {2, 1}; List<int> li = {4, 3};
    Array<double> ad = {2.0, 1.0}; List<double> ld = {4.0, 3.0};
    Array<string> atext = {"b", "a"}; List<string> ls = {"d", "c"};
    ai.sort(); li.sort(); ad.sort(); ld.sort(); atext.sort(); ls.sort();
    return ai[0] + li[0];
}
"""
    llvm = print_llvm(lower_to_verified_ssa(_typed(source)))

    assert llvm.count("define private void @aether_sort_i32") == 1
    assert llvm.count("define private void @aether_sort_f64") == 1
    assert llvm.count("define private void @aether_sort_string") == 1
    assert llvm.count("call void @aether_sort_i32") == 2
    assert llvm.count("call void @aether_sort_f64") == 2
    assert llvm.count("call void @aether_sort_string") == 2
    assert "@strcmp" in llvm
    assert "fcmp uno double" in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is not available")
@pytest.mark.parametrize("container", ["List", "Array"])
def test_clang_build_and_run_sort_int_double_string_and_alias(container: str) -> None:
    source = f"""
int main() {{
    {container}<int> a = {{3, 2, 1, 2}};
    {container}<int> b = a;
    b.sort();
    {container}<double> d = {{4.0, 2.0, 1.0}};
    d.sort();
    {container}<string> s = {{"é", "z", "A", "aa"}};
    s.sort();
    if (a[0] != 1) {{ return 1; }} if (a[1] != 2) {{ return 1; }}
    if (a[2] != 2) {{ return 1; }} if (a[3] != 3) {{ return 1; }}
    if (d[0] != 1.0) {{ return 2; }} if (d[1] != 2.0) {{ return 2; }}
    if (d[2] != 4.0) {{ return 2; }}
    return 0;
}}
"""

    assert LLVMRunner().run(_typed(source)) == 0


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is not available")
@pytest.mark.parametrize("container", ["List", "Array"])
def test_clang_double_sort_places_infinities_and_nan(container: str) -> None:
    source = f"""
int main() {{
    double nan = 0.0 / 0.0;
    double positiveInfinity = 1.0 / 0.0;
    double negativeInfinity = (0.0 - 1.0) / 0.0;
    double negativeZero = 0.0 - 0.0;
    {container}<double> xs = {{nan, positiveInfinity, negativeZero, 0.0, negativeInfinity, 2.0}};
    xs.sort();
    if (xs[0] != negativeInfinity) {{ return 1; }}
    if (xs[3] != 2.0) {{ return 1; }}
    if (xs[4] != positiveInfinity) {{ return 1; }}
    if (xs[5] == xs[5]) {{ return 2; }}
    return 0;
}}
"""

    assert LLVMRunner().run(_typed(source)) == 0
