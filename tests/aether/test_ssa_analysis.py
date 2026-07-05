from __future__ import annotations

from aether.ssa.analysis import Constant, Overdefined, Unknown, Worklist


def test_lattice_merge_unknown_unknown() -> None:
    assert Unknown().merge(Unknown()) == Unknown()


def test_lattice_merge_unknown_constant() -> None:
    assert Unknown().merge(Constant(5)) == Constant(5)
    assert Constant(5).merge(Unknown()) == Constant(5)


def test_lattice_merge_equal_constants() -> None:
    assert Constant(5).merge(Constant(5)) == Constant(5)


def test_lattice_merge_different_constants() -> None:
    assert Constant(5).merge(Constant(7)) == Overdefined()


def test_lattice_merge_with_overdefined() -> None:
    assert Constant(5).merge(Overdefined()) == Overdefined()
    assert Overdefined().merge(Constant(5)) == Overdefined()
    assert Unknown().merge(Overdefined()) == Overdefined()


def test_lattice_equality() -> None:
    assert Unknown() == Unknown()
    assert Overdefined() == Overdefined()
    assert Constant(5) == Constant(5)
    assert Constant(5) != Constant(7)
    assert Unknown() != Overdefined()


def test_lattice_textual_representation() -> None:
    assert repr(Unknown()) == "Unknown"
    assert str(Unknown()) == "Unknown"
    assert repr(Constant(5)) == "Constant(5)"
    assert str(Constant("x")) == "Constant('x')"
    assert repr(Overdefined()) == "Overdefined"
    assert str(Overdefined()) == "Overdefined"


def test_lattice_hash() -> None:
    assert hash(Unknown()) == hash(Unknown())
    assert hash(Overdefined()) == hash(Overdefined())
    assert hash(Constant(5)) == hash(Constant(5))


def test_worklist_push_pop() -> None:
    worklist: Worklist[str] = Worklist()

    worklist.push("node")

    assert worklist.pop() == "node"
    assert worklist.empty()


def test_worklist_avoids_duplicates() -> None:
    worklist: Worklist[str] = Worklist()

    worklist.push("node")
    worklist.push("node")

    assert worklist.pop() == "node"
    assert worklist.empty()


def test_worklist_fifo_order() -> None:
    worklist: Worklist[str] = Worklist()

    worklist.push("a")
    worklist.push("b")
    worklist.push("c")

    assert worklist.pop() == "a"
    assert worklist.pop() == "b"
    assert worklist.pop() == "c"


def test_worklist_allows_requeue_after_pop() -> None:
    worklist: Worklist[str] = Worklist()

    worklist.push("node")
    assert worklist.pop() == "node"
    worklist.push("node")

    assert worklist.pop() == "node"
    assert worklist.empty()


def test_worklist_clear() -> None:
    worklist: Worklist[str] = Worklist()

    worklist.push("a")
    worklist.push("b")
    worklist.clear()

    assert worklist.empty()


def test_worklist_empty() -> None:
    worklist: Worklist[str] = Worklist()

    assert worklist.empty()
    worklist.push("node")
    assert not worklist.empty()
