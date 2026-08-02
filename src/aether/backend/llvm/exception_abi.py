from __future__ import annotations

import hashlib


EXCEPTION_RUNTIME_ABI_VERSION = 1
"""Version of the private compiler/runtime exception-event contract."""

EXCEPTION_EVENT_MAGIC = 0x4145544845524558
"""Private ``AETHEREX`` marker used to fail closed on malformed handles."""


def exception_descriptor_symbol(nominal_id: str) -> str:
    """Return a collision-safe symbol for one canonical nominal descriptor.

    The complete UTF-8 spelling is part of the symbol.  The digest is only a
    readability/linker aid and is never used as the identity by itself.
    """

    encoded = nominal_id.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"__ae_exception_desc_n{len(encoded)}_{encoded.hex()}__{digest}"

