"""Canonical ownership contracts for immediate borrowed SSA consumers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aether.ssa import model as m


class BorrowedArgumentAcceptance(Enum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BorrowedArgumentContract:
    arguments: frozenset[int]
    no_retain: bool
    no_store: bool
    no_transfer: bool
    return_relation: str
    may_throw: bool
    may_panic: bool


# These are internal Aether operations whose implementations synchronously read
# the String.  None keeps the argument or returns an alias to it.  byteLength
# can trap on an invalid runtime value, but a borrowed argument has no cleanup
# obligation and the owning Array remains live on that path.
TRUSTED_BORROWED_CONSUMERS: dict[str, BorrowedArgumentContract] = {
    "__aether_string_byte_length": BorrowedArgumentContract(
        frozenset({0}), True, True, True, "scalar", False, True,
    ),
    "parseInt": BorrowedArgumentContract(
        frozenset({0}), True, True, True, "fresh_value", False, False,
    ),
    "parseDouble": BorrowedArgumentContract(
        frozenset({0}), True, True, True, "fresh_value", False, False,
    ),
}


def consumer_accepts_borrowed_arg(
    instruction: object, argument_index: int,
) -> BorrowedArgumentAcceptance:
    """Return YES only for an explicit, complete no-escape contract."""
    if isinstance(instruction, m.SSACompareOp):
        return (BorrowedArgumentAcceptance.YES if argument_index in (0, 1)
                else BorrowedArgumentAcceptance.NO)
    if isinstance(instruction, m.SSAPrint):
        return (BorrowedArgumentAcceptance.YES if argument_index == 0
                else BorrowedArgumentAcceptance.NO)
    if not isinstance(instruction, m.SSACall):
        return BorrowedArgumentAcceptance.UNKNOWN
    contract = TRUSTED_BORROWED_CONSUMERS.get(instruction.builtin or "")
    if contract is None:
        return BorrowedArgumentAcceptance.UNKNOWN
    complete = contract.no_retain and contract.no_store and contract.no_transfer
    if argument_index not in contract.arguments or not complete or contract.may_throw:
        return BorrowedArgumentAcceptance.NO
    return BorrowedArgumentAcceptance.YES
