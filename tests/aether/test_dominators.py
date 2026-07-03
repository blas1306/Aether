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
