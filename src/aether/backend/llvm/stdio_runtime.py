from __future__ import annotations

from dataclasses import dataclass
import sys

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMStdioRuntime:
    """Resolve C standard streams through the target platform's actual ABI.

    ``stdout`` and ``stderr`` are C source-level macros, not portable linker
    symbols.  Generated LLVM therefore calls these private accessors instead
    of assuming that the macro is backed by an exported global on every CRT.
    """

    stdout: bool
    stderr: bool
    platform: str | None = None

    def append(self, sections: list[str]) -> None:
        if not self.stdout and not self.stderr:
            return

        platform = self.platform or sys.platform
        if platform == "win32":
            LLVMRuntimeCommon.declare(
                sections, "declare ptr @__acrt_iob_func(i32)"
            )
            if self.stdout:
                sections.append(self._windows_accessor("stdout", 1))
            if self.stderr:
                sections.append(self._windows_accessor("stderr", 2))
            return

        if platform == "darwin":
            if self.stdout:
                LLVMRuntimeCommon.declare(
                    sections, "@__stdoutp = external global ptr"
                )
                sections.append(self._global_accessor("stdout", "__stdoutp"))
            if self.stderr:
                LLVMRuntimeCommon.declare(
                    sections, "@__stderrp = external global ptr"
                )
                sections.append(self._global_accessor("stderr", "__stderrp"))
            return

        if self.stdout:
            LLVMRuntimeCommon.declare(sections, "@stdout = external global ptr")
            sections.append(self._global_accessor("stdout", "stdout"))
        if self.stderr:
            LLVMRuntimeCommon.declare(sections, "@stderr = external global ptr")
            sections.append(self._global_accessor("stderr", "stderr"))

    @staticmethod
    def _global_accessor(stream: str, symbol: str) -> str:
        return "\n".join(
            [
                f"define private ptr @aether_{stream}_stream() {{",
                "entry:",
                f"  %stream = load ptr, ptr @{symbol}",
                "  ret ptr %stream",
                "}",
            ]
        )

    @staticmethod
    def _windows_accessor(stream: str, index: int) -> str:
        return "\n".join(
            [
                f"define private ptr @aether_{stream}_stream() {{",
                "entry:",
                f"  %stream = call ptr @__acrt_iob_func(i32 {index})",
                "  ret ptr %stream",
                "}",
            ]
        )
