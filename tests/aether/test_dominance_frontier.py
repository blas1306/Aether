from __future__ import annotations

from aether.analysis.cfg import CFG, CFGEdge, CFGNode
from aether.analysis.dominance_frontier import DominanceFrontierAnalysis
from aether.analysis.dominators import DominatorAnalysis


def _cfg(name: str, nodes: list[str], edges: list[tuple[str, str]]) -> CFG:
    return CFG(
        name,
        tuple(CFGNode(node) for node in nodes),
        tuple(CFGEdge(source, target) for source, target in edges),
    )


def _frontiers(cfg: CFG):
    dominators = DominatorAnalysis(cfg).compute()
    return DominanceFrontierAnalysis(cfg, dominators).compute()


def test_dominance_frontier_for_linear_function_is_empty() -> None:
    result = _frontiers(
        _cfg(
            "linear",
            ["entry", "middle", "exit"],
            [("entry", "middle"), ("middle", "exit")],
        )
    )

    assert result.frontier("entry") == set()
    assert result.frontier("middle") == set()
    assert result.frontier("exit") == set()


def test_dominance_frontier_for_if_else_contains_merge() -> None:
    result = _frontiers(
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
    )

    assert result.frontier("entry") == set()
    assert result.frontier("then0") == {"merge0"}
    assert result.frontier("else0") == {"merge0"}
    assert result.frontier("merge0") == set()


def test_dominance_frontier_for_while_contains_loop_header() -> None:
    result = _frontiers(
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
    )

    assert result.frontier("entry") == set()
    assert result.frontier("cond0") == {"cond0"}
    assert result.frontier("body0") == {"cond0"}
    assert result.frontier("exit0") == set()


def test_unreachable_block_has_empty_dominance_frontier() -> None:
    result = _frontiers(
        _cfg(
            "hasDeadBlock",
            ["entry", "left", "right", "merge", "dead"],
            [
                ("entry", "left"),
                ("entry", "right"),
                ("left", "merge"),
                ("right", "merge"),
            ],
        )
    )

    assert result.frontier("left") == {"merge"}
    assert result.frontier("right") == {"merge"}
    assert result.frontier("dead") == set()


def test_unreachable_join_block_has_empty_dominance_frontier() -> None:
    result = _frontiers(
        _cfg(
            "hasDeadJoin",
            ["entry", "exit", "dead_left", "dead_right", "dead_merge"],
            [
                ("entry", "exit"),
                ("dead_left", "dead_merge"),
                ("dead_right", "dead_merge"),
            ],
        )
    )

    assert result.frontier("dead_left") == set()
    assert result.frontier("dead_right") == set()
    assert result.frontier("dead_merge") == set()


def test_entry_only_function_has_empty_dominance_frontier() -> None:
    result = _frontiers(_cfg("onlyEntry", ["entry"], []))

    assert result.frontier("entry") == set()


def test_frontier_returns_empty_set_for_block_without_frontier() -> None:
    result = _frontiers(_cfg("noJoin", ["entry", "exit"], [("entry", "exit")]))

    assert result.frontier("exit") == set()
