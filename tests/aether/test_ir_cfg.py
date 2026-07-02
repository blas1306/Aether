from __future__ import annotations

from aether.ir import CFGBuilder, DOTPrinter, IRLowerer
from aether.pipeline import parse_source
from aether.typechecker import TypeChecker


def _lower(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def _cfg(source: str, function_index: int = 0):
    return CFGBuilder().build(_lower(source).functions[function_index])


def _node_names(source: str) -> list[str]:
    return [node.name for node in _cfg(source).nodes]


def _edge_pairs(source: str) -> set[tuple[str, str]]:
    return {(edge.source, edge.target) for edge in _cfg(source).edges}


def test_cfg_for_linear_function_has_entry_node_and_no_edges() -> None:
    cfg = _cfg(
        """
int answer() {
    return 42;
}
"""
    )

    assert cfg.function_name == "answer"
    assert [node.name for node in cfg.nodes] == ["entry"]
    assert cfg.edges == ()


def test_cfg_for_if_without_else_contains_branch_and_merge_edges() -> None:
    source = """
int absLike(int x) {
    if x < 0 {
        x = 0 - x;
    }
    return x;
}
"""

    assert _node_names(source) == ["entry", "then0", "merge0"]
    assert _edge_pairs(source) == {
        ("entry", "then0"),
        ("entry", "merge0"),
        ("then0", "merge0"),
    }


def test_cfg_for_if_else_contains_then_else_and_merge_edges() -> None:
    source = """
int choose(int x) {
    int y = 0;
    if x > 0 {
        y = 1;
    } else {
        y = 2;
    }
    return y;
}
"""

    assert _node_names(source) == ["entry", "then0", "else0", "merge0"]
    assert _edge_pairs(source) == {
        ("entry", "then0"),
        ("entry", "else0"),
        ("then0", "merge0"),
        ("else0", "merge0"),
    }


def test_cfg_for_while_contains_loop_back_edge() -> None:
    source = """
int sumTo(int n) {
    int i = 0;
    int sum = 0;

    while i < n {
        sum = sum + i;
        i = i + 1;
    }

    return sum;
}
"""

    assert _node_names(source) == ["entry", "cond0", "body0", "exit0"]
    assert _edge_pairs(source) == {
        ("entry", "cond0"),
        ("cond0", "body0"),
        ("cond0", "exit0"),
        ("body0", "cond0"),
    }


def test_dot_printer_contains_nodes_and_edges() -> None:
    cfg = _cfg(
        """
int sumTo(int n) {
    while n > 0 {
        n = n - 1;
    }
    return n;
}
"""
    )

    dot = DOTPrinter().to_dot(cfg)

    assert dot.startswith("digraph sumTo {")
    assert "    entry;" in dot
    assert "    cond0;" in dot
    assert "    body0;" in dot
    assert "    exit0;" in dot
    assert "    entry -> cond0;" in dot
    assert "    cond0 -> body0;" in dot
    assert "    cond0 -> exit0;" in dot
    assert "    body0 -> cond0;" in dot


def test_cfg_builder_handles_multiple_functions_independently() -> None:
    module = _lower(
        """
int first() {
    return 1;
}

int second(int x) {
    if x > 0 {
        return 1;
    } else {
        return 0;
    }
}
"""
    )

    first = CFGBuilder().build(module.functions[0])
    second = CFGBuilder().build(module.functions[1])

    assert first.function_name == "first"
    assert [node.name for node in first.nodes] == ["entry"]
    assert first.edges == ()
    assert second.function_name == "second"
    assert [node.name for node in second.nodes] == ["entry", "then0", "else0"]
    assert {(edge.source, edge.target) for edge in second.edges} == {
        ("entry", "then0"),
        ("entry", "else0"),
    }
