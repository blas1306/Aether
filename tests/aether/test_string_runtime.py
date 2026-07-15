from __future__ import annotations

import shutil
import subprocess

import pytest

from aether.backend.llvm import print_llvm
from aether.ir import BoolType, IntType, StringType
from aether.ssa import (
    SSABasicBlock,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAModule,
    SSAPrint,
    SSAReturn,
    SSAValue,
)
from aether.string_value import EMPTY_STRING, IMMORTAL, UTF8_VALID, StringValue


def test_empty_is_canonical_valid_and_immortal() -> None:
    assert StringValue.from_utf8(b"") is EMPTY_STRING
    assert StringValue.dynamic("") is EMPTY_STRING
    assert EMPTY_STRING.byte_length == 0
    assert EMPTY_STRING.utf8_bytes == b""
    assert EMPTY_STRING.flags == IMMORTAL | UTF8_VALID
    EMPTY_STRING.retain()
    EMPTY_STRING.release()
    assert EMPTY_STRING.strong_count == 0


def test_dynamic_retain_release_is_checked_and_frees_once() -> None:
    value = StringValue.from_utf8(b"owned")
    assert value.strong_count == 1
    assert value.retain() is value
    assert value.strong_count == 2
    value.release()
    assert value.strong_count == 1
    value.release()
    with pytest.raises(RuntimeError, match="already released"):
        value.release()


def test_reference_count_overflow_is_checked() -> None:
    value = StringValue.from_utf8(b"overflow")
    value.strong_count = (1 << 63) - 1
    with pytest.raises(OverflowError, match="overflow"):
        value.retain()


def test_utf8_bytes_length_embedded_null_and_content_equality() -> None:
    left = StringValue.from_utf8(b"a\x00\xc3\xa9")
    right = StringValue.from_utf8(bytes(bytearray(b"a\x00\xc3\xa9")))
    different = StringValue.from_utf8(b"a")
    assert left is not right
    assert left == right
    assert left != different
    assert left.byte_length == 4
    assert str(left) == "a\x00é"


def test_invalid_utf8_is_rejected_before_publication() -> None:
    with pytest.raises(ValueError, match="valid UTF-8"):
        StringValue.from_utf8(b"\xff")
    with pytest.raises(ValueError, match="valid UTF-8"):
        StringValue.from_utf8(b"\xed\xa0\x80")


def _embedded_null_module() -> SSAModule:
    string = StringType()
    boolean = BoolType()
    integer = IntType()
    left = SSAValue("left", string)
    right = SSAValue("right", string)
    equal = SSAValue("equal", boolean)
    result = SSAValue("result", integer)
    return SSAModule([
        SSAFunction(
            "main",
            [],
            integer,
            [SSABasicBlock("entry", [
                SSAConst(left, "a\x00b"),
                SSAConst(right, "a\x00b"),
                SSACompareOp(equal, "eq", left, right),
                SSAPrint(left, True),
                SSAConst(result, 0),
                SSAReturn(result),
            ])],
        )
    ])


def test_llvm_string_object_helpers_and_literal_layout() -> None:
    llvm = print_llvm(_embedded_null_module())
    assert "%AetherStringObject = type { i64, i64, i32, i32, [0 x i8] }" in llvm
    assert "i64 3, i64 0, i32 3, i32 0" in llvm
    for helper in (
        "aether_string_empty",
        "aether_string_retain",
        "aether_string_release",
        "aether_string_byte_length",
        "aether_string_data",
        "aether_string_equal",
        "aether_string_print",
        "aether_string_from_utf8",
    ):
        assert f"@{helper}" in llvm
    assert "@memcmp" in llvm
    assert "@strcmp" not in llvm
    assert 'c"a\\00b\\00"' in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_print_preserves_embedded_null(tmp_path) -> None:
    llvm_path = tmp_path / "string.ll"
    executable = tmp_path / "string"
    llvm_path.write_text(print_llvm(_embedded_null_module()), encoding="utf-8")
    completed = subprocess.run(
        [shutil.which("clang") or "clang", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    run = subprocess.run([str(executable)], check=False, capture_output=True)
    assert run.returncode == 0
    assert run.stdout == b"a\x00b\n"
