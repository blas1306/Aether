from __future__ import annotations

from aether.backend.llvm.io_runtime import LLVMRuntimeIO
from aether.backend.llvm.stdio_runtime import LLVMStdioRuntime
from aether.backend.llvm.string_runtime import LLVMStringRuntime


def _render_stdio(platform: str) -> str:
    sections: list[str] = []
    LLVMStdioRuntime(stdout=True, stderr=True, platform=platform).append(sections)
    return "\n\n".join(sections)


def test_darwin_standard_streams_use_exported_crt_pointer_symbols() -> None:
    llvm = _render_stdio("darwin")

    assert "@__stdoutp = external global ptr" in llvm
    assert "@__stderrp = external global ptr" in llvm
    assert "load ptr, ptr @__stdoutp" in llvm
    assert "load ptr, ptr @__stderrp" in llvm
    assert "@stdout = external" not in llvm
    assert "@stderr = external" not in llvm


def test_windows_standard_streams_use_ucrt_accessor() -> None:
    llvm = _render_stdio("win32")

    assert "declare ptr @__acrt_iob_func(i32)" in llvm
    assert "call ptr @__acrt_iob_func(i32 1)" in llvm
    assert "call ptr @__acrt_iob_func(i32 2)" in llvm
    assert "@stdout = external" not in llvm
    assert "@stderr = external" not in llvm


def test_elf_standard_stream_behavior_is_preserved_behind_private_accessors() -> None:
    llvm = _render_stdio("linux")

    assert "@stdout = external global ptr" in llvm
    assert "@stderr = external global ptr" in llvm
    assert "define private ptr @aether_stdout_stream()" in llvm
    assert "define private ptr @aether_stderr_stream()" in llvm


def test_darwin_numeric_locale_uses_darwin_lc_numeric_mask() -> None:
    sections: list[str] = []
    LLVMRuntimeIO(enabled=True, platform="darwin").append(sections)
    llvm = "\n\n".join(sections)

    assert "call ptr @newlocale(i32 16" in llvm
    assert "call ptr @newlocale(i32 2" not in llvm


def test_windows_print_and_string_conversion_use_ucrt_locale_api() -> None:
    sections: list[str] = []
    LLVMRuntimeIO(enabled=True, platform="win32").append(sections)
    LLVMStringRuntime(
        enabled=True, parsing=True, codec=True, platform="win32"
    ).append(sections)
    llvm = "\n\n".join(sections)

    assert "declare ptr @_create_locale(i32, ptr)" in llvm
    assert "call ptr @_create_locale(i32 4" in llvm
    assert "@_snprintf_l" in llvm
    assert "@_strtod_l" in llvm
    assert "@_free_locale" in llvm
    assert "@newlocale" not in llvm
    assert "@uselocale" not in llvm
    assert "@strtod_l" not in llvm
