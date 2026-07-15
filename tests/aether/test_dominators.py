from __future__ import annotations

from aether.analysis.cfg import CFG, CFGEdge, CFGNode
from aether.analysis.dominators import DominatorAnalysis


def _cfg(name: str, nodes: list[str], edges: list[tuple[str, str]]) -> CFG:
    return CFG(
        name,
        tuple(CFGNode(node) for node in nodes),
        tuple(CFGEdge(source, target) for source, target in edges),
    )


def test_dominators_for_linear_function() -> None:
    result = DominatorAnalysis(
        _cfg(
            "linear",
            ["entry", "middle", "exit"],
            [("entry", "middle"), ("middle", "exit")],
        )
    ).compute()

    assert result.dominators("entry") == {"entry"}
    assert result.dominators("middle") == {"entry", "middle"}
    assert result.dominators("exit") == {"entry", "middle", "exit"}


def test_dominators_for_if_else() -> None:
    result = DominatorAnalysis(
        _cfg(
            "choose",
            ["entry", "then0", "else0", "merge0"],
            [
                ("entry", "then0"),
                ("entry", "else0"),
                ("then0", "merge0"),
                ("else0", "merge0"),
            ],
        )
    ).compute()

    assert result.dominators("then0") == {"entry", "then0"}
    assert result.dominators("else0") == {"entry", "else0"}
    assert result.dominators("merge0") == {"entry", "merge0"}


def test_dominators_for_while() -> None:
    result = DominatorAnalysis(
        _cfg(
            "sumTo",
            ["entry", "cond0", "body0", "exit0"],
            [
                ("entry", "cond0"),
                ("cond0", "body0"),
                ("cond0", "exit0"),
                ("body0", "cond0"),
            ],
        )
    ).compute()

    assert result.dominators("cond0") == {"entry", "cond0"}
    assert result.dominators("body0") == {"entry", "cond0", "body0"}
    assert result.dominators("exit0") == {"entry", "cond0", "exit0"}


def test_unreachable_block_is_self_dominated_root() -> None:
    result = DominatorAnalysis(
        _cfg(
            "hasDeadBlock",
            ["entry", "exit", "dead"],
            [("entry", "exit")],
        )
    ).compute()

    assert result.dominators("dead") == {"dead"}
    assert result.immediate_dominator("dead") is None
    assert result.dominator_tree_children("dead") == set()


def test_immediate_dominators_are_computed() -> None:
    result = DominatorAnalysis(
        _cfg(
            "sumTo",
            ["entry", "cond0", "body0", "exit0"],
            [
                ("entry", "cond0"),
                ("cond0", "body0"),
                ("cond0", "exit0"),
                ("body0", "cond0"),
            ],
        )
    ).compute()

    assert result.immediate_dominator("entry") is None
    assert result.immediate_dominator("cond0") == "entry"
    assert result.immediate_dominator("body0") == "cond0"
    assert result.immediate_dominator("exit0") == "cond0"


def test_dominator_tree_children_are_computed() -> None:
    result = DominatorAnalysis(
        _cfg(
            "sumTo",
            ["entry", "cond0", "body0", "exit0"],
            [
                ("entry", "cond0"),
                ("cond0", "body0"),
                ("cond0", "exit0"),
                ("body0", "cond0"),
            ],
        )
    ).compute()

    assert result.dominator_tree_children("entry") == {"cond0"}
    assert result.dominator_tree_children("cond0") == {"body0", "exit0"}
    assert result.dominator_tree_children("body0") == set()
    assert result.dominator_tree_children("exit0") == set()


def test_dominators_for_entry_only_function() -> None:
    result = DominatorAnalysis(_cfg("onlyEntry", ["entry"], [])).compute()

    assert result.dominators("entry") == {"entry"}
    assert result.immediate_dominator("entry") is None
    assert result.dominator_tree_children("entry") == set()


def test_nested_loops_and_multiple_returns() -> None:
    result = DominatorAnalysis(
        _cfg(
            "nested",
            [
                "entry",
                "outer",
                "inner",
                "inner_body",
                "outer_latch",
                "early_return",
                "final_return",
            ],
            [
                ("entry", "outer"),
                ("outer", "inner"),
                ("outer", "final_return"),
                ("inner", "inner_body"),
                ("inner", "outer_latch"),
                ("inner_body", "inner"),
                ("inner_body", "early_return"),
                ("outer_latch", "outer"),
            ],
        )
    ).compute()

    assert result.dominators("inner_body") == {
        "entry",
        "outer",
        "inner",
        "inner_body",
    }
    assert result.immediate_dominator("outer_latch") == "inner"
    assert result.immediate_dominator("early_return") == "inner_body"
    assert result.immediate_dominator("final_return") == "outer"
    assert result.strictly_dominates("outer", "inner_body")
    assert not result.strictly_dominates("inner_body", "inner_body")


def test_explicit_entry_need_not_be_first_cfg_node() -> None:
    result = DominatorAnalysis(
        _cfg(
            "nonfirst",
            ["dead", "start", "exit"],
            [("start", "exit")],
        ),
        entry_block="start",
    ).compute()

    assert not result.is_reachable("dead")
    assert result.is_reachable("start")
    assert result.is_reachable("exit")
    assert result.dominators("exit") == {"start", "exit"}
