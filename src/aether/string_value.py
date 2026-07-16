from __future__ import annotations


IMMORTAL = 1 << 0
UTF8_VALID = 1 << 1


class StringValue:
    """Interpreter-side value for Aether's immutable UTF-8 string object.

    The Python interpreter does not model addresses or allocations, but it does
    keep the representation facts that are semantically relevant: authoritative
    UTF-8 bytes, byte length, immortality and a checked strong owner count.
    """

    __slots__ = ("_utf8", "flags", "strong_count", "unclaimed_owners", "_released")

    def __init__(self, utf8: bytes, *, immortal: bool = False) -> None:
        try:
            utf8.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("Aether string data must be valid UTF-8") from exc
        self._utf8 = bytes(utf8)
        self.flags = UTF8_VALID | (IMMORTAL if immortal else 0)
        self.strong_count = 0 if immortal else 1
        self.unclaimed_owners = 0 if immortal else 1
        self._released = False

    @classmethod
    def literal(cls, text: str) -> "StringValue":
        if not isinstance(text, str):
            raise TypeError("Aether string literals require str input")
        if not text:
            return EMPTY_STRING
        try:
            encoded = text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("Aether string literals must encode as valid UTF-8") from exc
        return cls(encoded, immortal=True)

    @classmethod
    def from_utf8(cls, data: bytes | bytearray | memoryview) -> "StringValue":
        encoded = bytes(data)
        if not encoded:
            return EMPTY_STRING
        return cls(encoded)

    @classmethod
    def dynamic(cls, text: str) -> "StringValue":
        if not isinstance(text, str):
            raise TypeError("Aether dynamic strings require str input")
        encoded = text.encode("utf-8", errors="strict")
        if not encoded:
            return EMPTY_STRING
        return cls(encoded)

    @property
    def utf8_bytes(self) -> bytes:
        self._require_live()
        return self._utf8

    @property
    def byte_length(self) -> int:
        self._require_live()
        return len(self._utf8)

    @property
    def immortal(self) -> bool:
        return bool(self.flags & IMMORTAL)

    def retain(self) -> "StringValue":
        self._require_live()
        if self.immortal:
            return self
        if self.strong_count >= (1 << 63) - 1:
            raise OverflowError("Aether string reference count overflow")
        self.strong_count += 1
        return self

    def claim_owner(self) -> "StringValue":
        self._require_live()
        if self.immortal:
            return self
        if self.unclaimed_owners:
            self.unclaimed_owners -= 1
            return self
        return self.retain()

    def offer_owner(self) -> "StringValue":
        self._require_live()
        if self.immortal:
            return self
        if self.unclaimed_owners:
            return self
        self.retain()
        self.unclaimed_owners += 1
        return self

    def release(self) -> None:
        self._require_live()
        if self.immortal:
            return
        if self.strong_count <= 0:
            raise RuntimeError("Aether string reference count underflow")
        self.strong_count -= 1
        if self.unclaimed_owners > self.strong_count:
            self.unclaimed_owners = self.strong_count
        if self.strong_count == 0:
            self._released = True

    def logical_copy(self) -> "StringValue":
        return self.retain()

    def _require_live(self) -> None:
        if self._released:
            raise RuntimeError("Aether string object was already released")

    def __str__(self) -> str:
        self._require_live()
        return self._utf8.decode("utf-8")

    def __repr__(self) -> str:
        return f"StringValue({self._utf8!r}, immortal={self.immortal})"

    def __len__(self) -> int:
        return self.byte_length

    def __bool__(self) -> bool:
        return bool(self.byte_length)

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        if encoding.lower().replace("_", "-") != "utf-8" or errors != "strict":
            return str(self).encode(encoding, errors)
        return self.utf8_bytes

    def __fspath__(self) -> str:
        return str(self)

    def __eq__(self, other: object) -> bool:
        self._require_live()
        if isinstance(other, StringValue):
            other._require_live()
            return self is other or self._utf8 == other._utf8
        if isinstance(other, str):
            try:
                return self._utf8 == other.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                return False
        return False

    def __hash__(self) -> int:
        self._require_live()
        return hash(self._utf8)

    def __add__(self, other: object) -> "StringValue":
        if not isinstance(other, StringValue):
            return NotImplemented
        self._require_live()
        other._require_live()
        return StringValue.from_utf8(self._utf8 + other._utf8)


# The valid empty handle is unique and immortal in the interpreter model too.
EMPTY_STRING = object.__new__(StringValue)
EMPTY_STRING._utf8 = b""
EMPTY_STRING.flags = IMMORTAL | UTF8_VALID
EMPTY_STRING.strong_count = 0
EMPTY_STRING.unclaimed_owners = 0
EMPTY_STRING._released = False


def as_string_value(value: str | StringValue, *, literal: bool = True) -> StringValue:
    if isinstance(value, StringValue):
        return value
    return StringValue.literal(value) if literal else StringValue.dynamic(value)
