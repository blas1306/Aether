"""Canonical ownership-provenance contracts for trusted Aether helpers.

These contracts describe compiler/runtime semantics only.  An unlisted helper,
ordinary direct call, or external symbol has no provenance contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReturnedIdentity(Enum):
    FRESH = "fresh"
    ARGUMENT = "argument"
    BORROW = "borrow"
    UNKNOWN = "unknown"


class ReturnedOwnership(Enum):
    OWNED = "owned"
    BORROWED = "borrowed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TrustedHelperContract:
    identity: ReturnedIdentity
    ownership: ReturnedOwnership
    argument: int | None = None
    may_escape_arguments: bool = False
    may_throw_or_panic: bool = False
    may_retain_or_store_arguments: bool = False


# Keep this deliberately small.  Allocation effects in ``SSA model`` are not
# by themselves sufficient proof of returned ownership identity.
TRUSTED_HELPER_CONTRACTS: dict[str, TrustedHelperContract] = {
    "text.formatInt": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
    ),
    "text.formatDouble": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
    ),
    "text.concatFragments": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
    ),
    "io.readText": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
        may_throw_or_panic=True,
    ),
    "System.args": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
    ),
    "__aether_string_trim": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
        may_throw_or_panic=True,
    ),
    "__aether_string_split": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
        may_throw_or_panic=True,
    ),
    "__aether_interface_copy_owned": TrustedHelperContract(
        ReturnedIdentity.FRESH, ReturnedOwnership.OWNED,
        may_throw_or_panic=True,
    ),
}


def trusted_helper_contract(name: str | None) -> TrustedHelperContract | None:
    return TRUSTED_HELPER_CONTRACTS.get(name) if name is not None else None
