from __future__ import annotations

import hashlib


INTERFACE_ABI_VERSION = 1
"""Version of the internal two-word native interface ABI."""


def witness_symbol(interface_id: str, concrete_type_id: str) -> str:
    """Return the stable private symbol for one concrete/interface pair."""

    interface_bytes = interface_id.encode("utf-8")
    concrete_bytes = concrete_type_id.encode("utf-8")
    descriptor = interface_bytes + b"\0" + concrete_bytes
    digest = hashlib.sha256(descriptor).hexdigest()[:16]
    return (
        f"__ae_witness_i{len(interface_bytes)}_{interface_bytes.hex()}"
        f"__c{len(concrete_bytes)}_{concrete_bytes.hex()}__{digest}"
    )


def interface_type_symbol(interface_id: str) -> str:
    """Return the deterministic named LLVM aggregate for an interface."""

    encoded = interface_id.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"%interface.{encoded.hex()[:80]}.{digest}"
