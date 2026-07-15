from __future__ import annotations

from dataclasses import dataclass

from aether.ir.types import DoubleType, IntType, IRType

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMScalarMathRuntime:
    calls: frozenset[tuple[str, tuple[IRType, ...], IRType]]

    def append(self, sections: list[str], common: LLVMRuntimeCommon) -> None:
        names = {name for name, _arguments, _result in self.calls}
        rounded_to_int = {
            name
            for name, arguments, _result in self.calls
            if name in {"Math.floor", "Math.ceil"}
            and not isinstance(arguments[0], IntType)
        }
        uses_double_mod = any(
            name == "Math.mod"
            and not all(isinstance(type_, IntType) for type_ in arguments)
            for name, arguments, _result in self.calls
        )
        if names & {"sin", "cos", "tan", "exp", "ln", "log"}:
            symbols = {
                {"ln": "log", "log": "log10"}.get(name, name)
                for name in names & {"sin", "cos", "tan", "exp", "ln", "log"}
            }
            for symbol in sorted(symbols):
                common.declare(sections, f"declare double @{symbol}(double)")
        if "sqrt" in names:
            common.declare(sections, "declare double @llvm.sqrt.f64(double)")
        if any(
            name == "abs" and isinstance(arguments[0], DoubleType)
            for name, arguments, _result in self.calls
        ):
            common.declare(sections, "declare double @llvm.fabs.f64(double)")
        if "Math.floor" in rounded_to_int or uses_double_mod:
            common.declare(sections, "declare double @llvm.floor.f64(double)")
        if "Math.ceil" in rounded_to_int:
            common.declare(sections, "declare double @llvm.ceil.f64(double)")

        if any(
            name == "abs" and isinstance(arguments[0], IntType)
            for name, arguments, _result in self.calls
        ):
            self._append_panic(
                sections,
                common,
                "aether_math_integer_overflow_panic",
                ".aether.math.integer.overflow",
                "Aether panic: Integer overflow",
            )
            sections.append(self._checked_abs_i32())

        if "Math.factorial" in names:
            self._append_panic(
                sections,
                common,
                "aether_math_factorial_domain_panic",
                ".aether.math.factorial.domain",
                "Math.factorial(...) requires a non-negative integer.",
            )
            if not any("aether_math_integer_overflow_panic" in section for section in sections):
                self._append_panic(
                    sections,
                    common,
                    "aether_math_integer_overflow_panic",
                    ".aether.math.integer.overflow",
                    "Aether panic: Integer overflow",
                )
            common.declare(
                sections,
                "declare { i32, i1 } @llvm.smul.with.overflow.i32(i32, i32)",
            )
            sections.append(self._checked_factorial_i32())

        if "Math.mod" in names:
            self._append_panic(
                sections,
                common,
                "aether_math_division_by_zero_panic",
                ".aether.math.division.zero",
                "Math.mod(...) is undefined for divisor zero.",
            )
            if any(
                all(isinstance(type_, IntType) for type_ in arguments)
                for name, arguments, _result in self.calls
                if name == "Math.mod"
            ):
                sections.append(self._floor_mod_i32())
            if any(
                not all(isinstance(type_, IntType) for type_ in arguments)
                for name, arguments, _result in self.calls
                if name == "Math.mod"
            ):
                sections.append(self._floor_mod_f64())

        if rounded_to_int:
            if "Math.floor" in rounded_to_int:
                self._append_panic(
                    sections,
                    common,
                    "aether_math_floor_to_int_panic",
                    ".aether.math.floor.to.int",
                    "Math.floor(...) cannot convert NaN or infinity to int.",
                )
                sections.append(self._rounded_to_i32("floor"))
            if "Math.ceil" in rounded_to_int:
                self._append_panic(
                    sections,
                    common,
                    "aether_math_ceil_to_int_panic",
                    ".aether.math.ceil.to.int",
                    "Math.ceil(...) cannot convert NaN or infinity to int.",
                )
                sections.append(self._rounded_to_i32("ceil"))

    @staticmethod
    def _append_panic(
        sections: list[str],
        common: LLVMRuntimeCommon,
        function_name: str,
        global_name: str,
        message: str,
    ) -> None:
        if any(f"@{function_name}()" in section for section in sections):
            return
        size = len(message.encode("ascii")) + 1
        sections.append(
            f"@{global_name} = private unnamed_addr constant [{size} x i8] c\"{message}\\00\""
        )
        sections.append(common.panic_helper(function_name, global_name, size))

    @staticmethod
    def _checked_abs_i32() -> str:
        return "\n".join(
            [
                "define private i32 @aether_checked_abs_i32(i32 %value) {",
                "entry:",
                "  %is_min = icmp eq i32 %value, -2147483648",
                "  br i1 %is_min, label %panic, label %select",
                "panic:",
                "  call void @aether_math_integer_overflow_panic()",
                "  unreachable",
                "select:",
                "  %negative = icmp slt i32 %value, 0",
                "  %negated = sub i32 0, %value",
                "  %result = select i1 %negative, i32 %negated, i32 %value",
                "  ret i32 %result",
                "}",
            ]
        )

    @staticmethod
    def _checked_factorial_i32() -> str:
        return "\n".join(
            [
                "define private i32 @aether_checked_factorial_i32(i32 %value) {",
                "entry:",
                "  %negative = icmp slt i32 %value, 0",
                "  br i1 %negative, label %domain, label %loop",
                "domain:",
                "  call void @aether_math_factorial_domain_panic()",
                "  unreachable",
                "loop:",
                "  %factor = phi i32 [ 2, %entry ], [ %next, %ok ]",
                "  %acc = phi i32 [ 1, %entry ], [ %product, %ok ]",
                "  %more = icmp sle i32 %factor, %value",
                "  br i1 %more, label %multiply, label %done",
                "multiply:",
                "  %pair = call { i32, i1 } @llvm.smul.with.overflow.i32(i32 %acc, i32 %factor)",
                "  %product = extractvalue { i32, i1 } %pair, 0",
                "  %overflow = extractvalue { i32, i1 } %pair, 1",
                "  br i1 %overflow, label %overflow_panic, label %ok",
                "overflow_panic:",
                "  call void @aether_math_integer_overflow_panic()",
                "  unreachable",
                "ok:",
                "  %next = add i32 %factor, 1",
                "  br label %loop",
                "done:",
                "  ret i32 %acc",
                "}",
            ]
        )

    @staticmethod
    def _floor_mod_i32() -> str:
        return "\n".join(
            [
                "define private i32 @aether_floor_mod_i32(i32 %left, i32 %right) {",
                "entry:",
                "  %zero = icmp eq i32 %right, 0",
                "  br i1 %zero, label %panic, label %special_check",
                "panic:",
                "  call void @aether_math_division_by_zero_panic()",
                "  unreachable",
                "special_check:",
                "  %is_min = icmp eq i32 %left, -2147483648",
                "  %is_negative_one = icmp eq i32 %right, -1",
                "  %special = and i1 %is_min, %is_negative_one",
                "  br i1 %special, label %special_zero, label %remainder",
                "special_zero:",
                "  ret i32 0",
                "remainder:",
                "  %raw = srem i32 %left, %right",
                "  %raw_nonzero = icmp ne i32 %raw, 0",
                "  %left_negative = icmp slt i32 %left, 0",
                "  %right_negative = icmp slt i32 %right, 0",
                "  %different_sign = xor i1 %left_negative, %right_negative",
                "  %adjust = and i1 %raw_nonzero, %different_sign",
                "  %adjusted = add i32 %raw, %right",
                "  %result = select i1 %adjust, i32 %adjusted, i32 %raw",
                "  ret i32 %result",
                "}",
            ]
        )

    @staticmethod
    def _floor_mod_f64() -> str:
        return "\n".join(
            [
                "define private double @aether_floor_mod_f64(double %left, double %right) {",
                "entry:",
                "  %zero = fcmp oeq double %right, 0.0",
                "  br i1 %zero, label %panic, label %calculate",
                "panic:",
                "  call void @aether_math_division_by_zero_panic()",
                "  unreachable",
                "calculate:",
                "  %quotient = fdiv double %left, %right",
                "  %floored = call double @llvm.floor.f64(double %quotient)",
                "  %product = fmul double %floored, %right",
                "  %result = fsub double %left, %product",
                "  ret double %result",
                "}",
            ]
        )

    @staticmethod
    def _rounded_to_i32(operation: str) -> str:
        return "\n".join(
            [
                f"define private i32 @aether_{operation}_to_i32(double %value) {{",
                "entry:",
                f"  %rounded = call double @llvm.{operation}.f64(double %value)",
                "  %nan = fcmp uno double %rounded, %rounded",
                "  %too_low = fcmp olt double %rounded, -2.1474836480000000e+09",
                "  %too_high = fcmp ogt double %rounded, 2.1474836470000000e+09",
                "  %outside = or i1 %too_low, %too_high",
                "  %invalid = or i1 %nan, %outside",
                "  br i1 %invalid, label %panic, label %convert",
                "panic:",
                f"  call void @aether_math_{operation}_to_int_panic()",
                "  unreachable",
                "convert:",
                "  %result = fptosi double %rounded to i32",
                "  ret i32 %result",
                "}",
            ]
        )
