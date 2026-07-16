from __future__ import annotations


IMMORTAL = 1 << 0
UTF8_VALID = 1 << 1
MAX_STRING_LENGTH = (1 << 63) - 1
STRING_HEADER_SIZE = 24
ARRAY_HEADER_SIZE = 24
STRING_HANDLE_SIZE = 8
STRING_TRIM_BUILTIN = "__aether_string_trim"
STRING_SPLIT_BUILTIN = "__aether_string_split"
STRING_SPLIT_EMPTY_SEPARATOR_MESSAGE = (
    "Aether panic: string split separator cannot be empty"
)
ASCII_WHITESPACE_BYTES = frozenset((0x20, 0x09, 0x0A, 0x0D, 0x0C, 0x0B))


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
            return aether_string_equal(self, other)
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
        return aether_string_concat(self, other)


# The valid empty handle is unique and immortal in the interpreter model too.
EMPTY_STRING = object.__new__(StringValue)
EMPTY_STRING._utf8 = b""
EMPTY_STRING.flags = IMMORTAL | UTF8_VALID
EMPTY_STRING.strong_count = 0
EMPTY_STRING.unclaimed_owners = 0
EMPTY_STRING._released = False


def aether_string_equal(left: object, right: object) -> bool:
    """Length-aware Aether string equality used by every Python runtime path."""

    if left is right:
        return True
    if not isinstance(left, StringValue) or not isinstance(right, StringValue):
        return False
    left._require_live()
    right._require_live()
    return left.byte_length == right.byte_length and left.utf8_bytes == right.utf8_bytes


def aether_string_concat(left: StringValue, right: StringValue) -> StringValue:
    """Concatenate two UTF-8 string objects and return one owned result.

    Empty fast paths still honor the owned-return convention: borrowed dynamic
    operands acquire another owner, while an unclaimed temporary can transfer
    its existing owner.
    """

    if not isinstance(left, StringValue) or not isinstance(right, StringValue):
        raise TypeError("Aether string concatenation requires two string values")
    left._require_live()
    right._require_live()
    left_length = left.byte_length
    right_length = right.byte_length
    if left_length == 0 and right_length == 0:
        return EMPTY_STRING
    if left_length == 0:
        return right.offer_owner()
    if right_length == 0:
        return left.offer_owner()
    total = left_length + right_length
    if total > MAX_STRING_LENGTH:
        raise OverflowError("Aether string concatenation length overflow")
    allocation_size = STRING_HEADER_SIZE + total + 1
    if allocation_size > MAX_STRING_LENGTH:
        raise OverflowError("Aether string allocation size overflow")
    return StringValue.from_utf8(left.utf8_bytes + right.utf8_bytes)


def aether_string_trim(value: StringValue) -> StringValue:
    """Trim Aether v1 ASCII whitespace and return an owned string.

    The scan is deliberately byte based.  The six ASCII whitespace bytes are
    single-byte UTF-8 code units and cannot occur inside a valid multibyte
    sequence, so trimming only at the two ends preserves valid UTF-8.  Embedded
    NUL is ordinary content and is never treated as whitespace.
    """

    if not isinstance(value, StringValue):
        raise TypeError("Aether string trim requires a string value")
    value._require_live()
    data = value.utf8_bytes
    length = value.byte_length

    start = 0
    while start < length and data[start] in ASCII_WHITESPACE_BYTES:
        start += 1
    if start == length:
        return EMPTY_STRING

    end = length
    while end > start and data[end - 1] in ASCII_WHITESPACE_BYTES:
        end -= 1
    if start == 0 and end == length:
        # ``offer_owner`` is the interpreter model's owned-return operation:
        # it retains a borrowed object and may transfer an already-unclaimed
        # temporary owner.  Native always performs the retain fast path.
        return value.offer_owner()

    trimmed_length = end - start
    if trimmed_length > MAX_STRING_LENGTH:
        raise OverflowError("Aether string trim length overflow")
    allocation_size = STRING_HEADER_SIZE + trimmed_length + 1
    if allocation_size > MAX_STRING_LENGTH:
        raise OverflowError("Aether string allocation size overflow")
    return StringValue.from_utf8(data[start:end])


def aether_string_split(
    text: StringValue,
    separator: StringValue,
    *,
    wrap_values: bool = False,
):
    """Split an Aether string on exact, non-overlapping UTF-8 byte matches.

    This is deliberately a two-pass, length-aware implementation.  The first
    pass counts left-to-right non-overlapping matches; the second creates an
    exact-size ``Array<string>`` and transfers one owned string into every
    element.  Empty fields are preserved.  Non-empty fragments are independent
    allocations, except for the permitted no-match fast path which retains the
    receiver.  Complexity is O(n * m) for text length ``n`` and separator
    length ``m``; total fragment bytes copied are O(n).
    """

    if not isinstance(text, StringValue) or not isinstance(separator, StringValue):
        raise TypeError("Aether string split requires string receiver and separator")
    text._require_live()
    separator._require_live()
    separator_length = separator.byte_length
    if separator_length == 0:
        from .errors import AetherRuntimeError

        raise AetherRuntimeError(STRING_SPLIT_EMPTY_SEPARATOR_MESSAGE)

    data = text.utf8_bytes
    separator_bytes = separator.utf8_bytes
    text_length = text.byte_length
    matches = 0
    index = 0
    last_candidate = text_length - separator_length
    while index <= last_candidate:
        if data[index : index + separator_length] == separator_bytes:
            if matches >= MAX_STRING_LENGTH - 1:
                raise OverflowError("Aether string split part count overflow")
            matches += 1
            index += separator_length
        else:
            index += 1

    part_count = matches + 1
    # The native Array<string> buffer contains one pointer-sized handle per
    # part.  Its object header is a separate fixed-size allocation.
    if ARRAY_HEADER_SIZE > MAX_STRING_LENGTH:
        raise OverflowError("Aether string split Array header size overflow")
    if part_count > MAX_STRING_LENGTH // STRING_HANDLE_SIZE:
        raise OverflowError("Aether string split Array allocation size overflow")

    from .collection_value import array_alloc

    def store_fragment(fragment: StringValue) -> None:
        fragment.claim_owner()
        stored: object = fragment
        if wrap_values:
            from .types import AetherValue

            stored = AetherValue("string", fragment)
        try:
            list.append(result, stored)
        except BaseException:
            fragment.release()
            raise

    def fragment_from_range(start: int, end: int) -> StringValue:
        length = end - start
        if length == 0:
            return EMPTY_STRING
        if length > MAX_STRING_LENGTH - STRING_HEADER_SIZE - 1:
            raise OverflowError("Aether string split fragment allocation size overflow")
        return StringValue.from_utf8(data[start:end])

    result = array_alloc("string")
    try:
        if matches == 0:
            fragment = text.offer_owner()
            store_fragment(fragment)
            result.capacity = part_count
            return result

        start = 0
        index = 0
        while index <= last_candidate:
            if data[index : index + separator_length] != separator_bytes:
                index += 1
                continue
            fragment = fragment_from_range(start, index)
            store_fragment(fragment)
            index += separator_length
            start = index

        fragment = fragment_from_range(start, text_length)
        store_fragment(fragment)
        result.capacity = part_count
        return result
    except BaseException:
        result.release()
        raise


def as_string_value(value: str | StringValue, *, literal: bool = True) -> StringValue:
    if isinstance(value, StringValue):
        return value
    return StringValue.literal(value) if literal else StringValue.dynamic(value)
