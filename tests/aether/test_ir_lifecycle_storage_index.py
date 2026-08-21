from __future__ import annotations

from aether.ir import (
    ArrayType,
    BoolType,
    ClassRefType,
    IRAssign,
    IRBasicBlock,
    IRBranch,
    IRCopyInit,
    IRDestroy,
    IRFunction,
    IRInitDefault,
    IRJump,
    IRModule,
    IRMoveInit,
    IRParameter,
    IRRelocate,
    IRReturn,
    IRStorage,
    IRValue,
    IRVerifier,
    IntType,
    ListType,
    StringType,
    StructType,
    VoidType,
)


_LIFECYCLE_INSTRUCTIONS = (
    IRInitDefault,
    IRCopyInit,
    IRMoveInit,
    IRAssign,
    IRDestroy,
    IRRelocate,
)


def _reference_scan(function: IRFunction, name: str) -> bool:
    """The pre-TEST-PERF-3.2 predicate, retained only for equivalence tests."""
    return any(
        isinstance(instruction, _LIFECYCLE_INSTRUCTIONS)
        and any(
            isinstance(value, IRStorage) and value.name == name
            for value in (
                getattr(instruction, "destination", None),
                getattr(instruction, "source", None),
                getattr(instruction, "value", None),
            )
        )
        for block in function.blocks
        for instruction in block.instructions
    )


def test_lifecycle_storage_index_matches_reference_scan_and_is_function_local() -> None:
    scalar = IRStorage("scalar", IntType())
    owned = IRStorage("owned", StringType())
    moved = IRStorage("moved", StringType())
    assigned = IRStorage("assigned", StringType())
    array = IRStorage("array", ArrayType(StringType()))
    list_value = IRStorage("list", ListType(StringType()))
    aggregate = IRStorage("aggregate_field", StructType("Aggregate"))
    constructor = IRStorage("constructor_temporary", ClassRefType("Box"))
    exception = IRStorage("exception_payload", StructType("Failure"))
    source = IRValue("source", StringType())
    first = IRFunction(
        "first",
        [],
        VoidType(),
        [
            IRBasicBlock(
                "entry",
                [
                    IRInitDefault(scalar),
                    IRCopyInit(owned, source),
                    IRMoveInit(moved, owned),
                    IRAssign(assigned, source),
                    IRRelocate(owned, moved, 1),
                    IRDestroy(assigned),
                    IRInitDefault(array),
                    IRInitDefault(list_value),
                    IRInitDefault(aggregate),
                    IRInitDefault(constructor),
                    IRInitDefault(exception),
                    IRReturn(),
                ],
            )
        ],
    )
    # The same spelling in another function must not inherit membership.
    second = IRFunction(
        "second",
        [],
        VoidType(),
        [IRBasicBlock("entry", [IRReturn()])],
    )

    for function in (first, second):
        indexed = IRVerifier._build_lifecycle_storage_index(function)
        for name in (
            "scalar",
            "owned",
            "moved",
            "assigned",
            "array",
            "list",
            "aggregate_field",
            "constructor_temporary",
            "exception_payload",
            "missing",
        ):
            assert (name in indexed) == _reference_scan(function, name)


class _CountingVerifier(IRVerifier):
    def __init__(self, module: IRModule) -> None:
        super().__init__(module)
        self.index_builds = 0
        self.membership_queries = 0

    def _build_lifecycle_storage_index(self, function: IRFunction) -> frozenset[str]:
        self.index_builds += 1
        return super()._build_lifecycle_storage_index(function)

    def _is_lifecycle_storage(self, function: IRFunction, name: str) -> bool:
        self.membership_queries += 1
        return super()._is_lifecycle_storage(function, name)


def test_lifecycle_discovery_scans_once_while_cfg_queries_scale() -> None:
    condition = IRParameter("condition", BoolType())
    storage = IRStorage("owner", IntType())
    blocks = [
        IRBasicBlock("entry", [IRInitDefault(storage), IRJump("branch0")])
    ]
    for index in range(80):
        next_name = f"branch{index + 1}" if index < 79 else "exit"
        blocks.extend(
            [
                IRBasicBlock(
                    f"branch{index}",
                    [IRBranch(condition, f"left{index}", f"right{index}")],
                ),
                IRBasicBlock(f"left{index}", [IRJump(f"merge{index}")]),
                IRBasicBlock(f"right{index}", [IRJump(f"merge{index}")]),
                IRBasicBlock(f"merge{index}", [IRJump(next_name)]),
            ]
        )
    blocks.append(IRBasicBlock("exit", [IRDestroy(storage), IRReturn()]))
    function = IRFunction("large_cfg", [condition], VoidType(), blocks)
    verifier = _CountingVerifier(IRModule([function]))

    verifier.verify()

    assert verifier.index_builds == 1
    assert verifier.membership_queries >= 80
