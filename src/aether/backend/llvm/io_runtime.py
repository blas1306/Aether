from __future__ import annotations

from dataclasses import dataclass

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMRuntimeIO:
    """Declarations and fixed format strings used by scalar print operations."""

    enabled: bool

    def append(self, sections: list[str]) -> None:
        if not self.enabled:
            return

        LLVMRuntimeCommon.declare(sections, "declare i32 @printf(ptr, ...)")
        LLVMRuntimeCommon.declare(sections, "declare i32 @putchar(i32)")
        LLVMRuntimeCommon.declare(sections, "declare i32 @fputs(ptr, ptr)")
        LLVMRuntimeCommon.declare(sections, "@stdout = external global ptr")
        sections.extend(
            [
                '@.aether.io.int = private unnamed_addr constant [3 x i8] c"%d\\00"',
                '@.aether.io.intln = private unnamed_addr constant [4 x i8] c"%d\\0A\\00"',
                '@.aether.io.double = private unnamed_addr constant [6 x i8] c"%.17g\\00"',
                '@.aether.io.doubleln = private unnamed_addr constant [7 x i8] c"%.17g\\0A\\00"',
                '@.aether.io.true = private unnamed_addr constant [5 x i8] c"true\\00"',
                '@.aether.io.false = private unnamed_addr constant [6 x i8] c"false\\00"',
            ]
        )
