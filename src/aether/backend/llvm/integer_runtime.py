from __future__ import annotations

from dataclasses import dataclass

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMIntegerRuntime:
    """Checked i32 arithmetic helpers used by scalar and aggregate lowering."""

    operators: frozenset[str]

    @staticmethod
    def helper_name(operator: str) -> str:
        normalized = "rem" if operator == "mod" else operator
        return f"aether_checked_{normalized}_i32"

    def append(self, sections: list[str], common: LLVMRuntimeCommon) -> None:
        if not self.operators:
            return

        if self.operators & {"div", "mod", "rem"}:
            sections.append(
                '@.aether.integer.division.zero = private unnamed_addr constant [31 x i8] '
                'c"Aether panic: Division by zero\\00"'
            )
            sections.append(
                common.panic_helper(
                    "aether_integer_division_by_zero_panic",
                    ".aether.integer.division.zero",
                    31,
                )
            )
        if self.operators & {"add", "sub", "mul", "div"}:
            sections.append(
                '@.aether.integer.overflow = private unnamed_addr constant [31 x i8] '
                'c"Aether panic: Integer overflow\\00"'
            )
            sections.append(
                common.panic_helper(
                    "aether_integer_overflow_panic",
                    ".aether.integer.overflow",
                    31,
                )
            )

        for operator in ("add", "sub", "mul"):
            if operator in self.operators:
                self._append_overflow_helper(sections, operator)
        if "div" in self.operators:
            sections.append(self._division_helper())
        if self.operators & {"mod", "rem"}:
            sections.append(self._remainder_helper())

    @classmethod
    def _append_overflow_helper(cls, sections: list[str], operator: str) -> None:
        intrinsic = {"add": "sadd", "sub": "ssub", "mul": "smul"}[operator]
        LLVMRuntimeCommon.declare(
            sections,
            f"declare {{ i32, i1 }} @llvm.{intrinsic}.with.overflow.i32(i32, i32)",
        )
        sections.append(
            "\n".join(
                [
                    f"define private i32 @{cls.helper_name(operator)}(i32 %left, i32 %right) {{",
                    "entry:",
                    f"  %pair = call {{ i32, i1 }} @llvm.{intrinsic}.with.overflow.i32(i32 %left, i32 %right)",
                    "  %result = extractvalue { i32, i1 } %pair, 0",
                    "  %overflow = extractvalue { i32, i1 } %pair, 1",
                    "  br i1 %overflow, label %panic, label %ok",
                    "panic:",
                    "  call void @aether_integer_overflow_panic()",
                    "  unreachable",
                    "ok:",
                    "  ret i32 %result",
                    "}",
                ]
            )
        )

    @classmethod
    def _division_helper(cls) -> str:
        return "\n".join(
            [
                f"define private double @{cls.helper_name('div')}(i32 %left, i32 %right) {{",
                "entry:",
                "  %is_zero = icmp eq i32 %right, 0",
                "  br i1 %is_zero, label %division_by_zero, label %overflow_check",
                "division_by_zero:",
                "  call void @aether_integer_division_by_zero_panic()",
                "  unreachable",
                "overflow_check:",
                "  %is_min = icmp eq i32 %left, -2147483648",
                "  %is_negative_one = icmp eq i32 %right, -1",
                "  %overflow = and i1 %is_min, %is_negative_one",
                "  br i1 %overflow, label %overflow_panic, label %divide",
                "overflow_panic:",
                "  call void @aether_integer_overflow_panic()",
                "  unreachable",
                "divide:",
                "  %left_double = sitofp i32 %left to double",
                "  %right_double = sitofp i32 %right to double",
                "  %result = fdiv double %left_double, %right_double",
                "  ret double %result",
                "}",
            ]
        )

    @classmethod
    def _remainder_helper(cls) -> str:
        return "\n".join(
            [
                f"define private i32 @{cls.helper_name('rem')}(i32 %left, i32 %right) {{",
                "entry:",
                "  %is_zero = icmp eq i32 %right, 0",
                "  br i1 %is_zero, label %division_by_zero, label %special_check",
                "division_by_zero:",
                "  call void @aether_integer_division_by_zero_panic()",
                "  unreachable",
                "special_check:",
                "  %is_min = icmp eq i32 %left, -2147483648",
                "  %is_negative_one = icmp eq i32 %right, -1",
                "  %special = and i1 %is_min, %is_negative_one",
                "  br i1 %special, label %zero, label %remainder",
                "zero:",
                "  ret i32 0",
                "remainder:",
                "  %result = srem i32 %left, %right",
                "  ret i32 %result",
                "}",
            ]
        )
