from __future__ import annotations

from dataclasses import dataclass

from .numeric_locale import LLVMNumericLocaleABI
from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMRuntimeIO:
    """Declarations and fixed format strings used by scalar print operations."""

    enabled: bool
    platform: str | None = None

    def append(self, sections: list[str]) -> None:
        if not self.enabled:
            return

        LLVMRuntimeCommon.declare(sections, "declare i32 @printf(ptr, ...)")
        LLVMRuntimeCommon.declare(sections, "declare i32 @putchar(i32)")
        LLVMRuntimeCommon.declare(sections, "declare i32 @fputs(ptr, ptr)")
        LLVMRuntimeCommon.declare(sections, "declare i64 @fwrite(ptr, i64, i64, ptr)")
        locale = LLVMNumericLocaleABI(self.platform)
        locale.append_declarations(sections, formatting=True)
        LLVMRuntimeCommon.declare(sections, "declare void @exit(i32) noreturn")
        sections.extend(
            [
                '@.aether.io.int = private unnamed_addr constant [3 x i8] c"%d\\00"',
                '@.aether.io.intln = private unnamed_addr constant [4 x i8] c"%d\\0A\\00"',
                '@.aether.io.double = private unnamed_addr constant [6 x i8] c"%.15g\\00"',
                '@.aether.io.doubleln = private unnamed_addr constant [7 x i8] c"%.15g\\0A\\00"',
                '@.aether.io.double.suffix = private unnamed_addr constant [3 x i8] c".0\\00"',
                '@.aether.io.double.nan = private unnamed_addr constant [4 x i8] c"NaN\\00"',
                '@.aether.io.double.inf = private unnamed_addr constant [9 x i8] c"Infinity\\00"',
                '@.aether.io.double.ninf = private unnamed_addr constant [10 x i8] c"-Infinity\\00"',
                '@.aether.io.locale.c = private unnamed_addr constant [2 x i8] c"C\\00"',
                '@.aether.io.locale.error = private unnamed_addr constant [51 x i8] c"Aether panic: public double formatting unavailable\\00"',
                '@.aether.io.true = private unnamed_addr constant [5 x i8] c"true\\00"',
                '@.aether.io.false = private unnamed_addr constant [6 x i8] c"false\\00"',
                self._double_print_helper(locale),
            ]
        )

    @staticmethod
    def _double_print_helper(locale: LLVMNumericLocaleABI) -> str:
        create_locale = locale.create("%locale", "%locale_name")
        format_double = locale.format_double(
            result="%written32",
            data="%data",
            size=64,
            format_="@.aether.io.double",
            value="%value",
            locale="%locale",
        )
        return "\n".join(
            [
                "define private void @aether_print_double(double %value, i1 %newline) {",
                "entry:",
                "  %bits = bitcast double %value to i64",
                "  %exponent = and i64 %bits, 9218868437227405312",
                "  %fraction = and i64 %bits, 4503599627370495",
                "  %special = icmp eq i64 %exponent, 9218868437227405312",
                "  br i1 %special, label %classify, label %finite",
                "classify:",
                "  %is_inf = icmp eq i64 %fraction, 0",
                "  br i1 %is_inf, label %infinity, label %nan",
                "nan:",
                "  br label %special_write",
                "infinity:",
                "  %sign = and i64 %bits, -9223372036854775808",
                "  %negative = icmp ne i64 %sign, 0",
                "  %inf_text = select i1 %negative, ptr @.aether.io.double.ninf, ptr @.aether.io.double.inf",
                "  br label %special_write",
                "special_write:",
                "  %special_text = phi ptr [ @.aether.io.double.nan, %nan ], [ %inf_text, %infinity ]",
                "  %special_stream = call ptr @aether_stdout_stream()",
                "  %special_result = call i32 @fputs(ptr %special_text, ptr %special_stream)",
                "  br label %finish",
                "finite:",
                "  %locale_name = getelementptr [2 x i8], ptr @.aether.io.locale.c, i64 0, i64 0",
                f"  {create_locale}",
                "  %locale_failed = icmp eq ptr %locale, null",
                "  br i1 %locale_failed, label %panic, label %format",
                "format:",
                "  %buffer = alloca [64 x i8], align 1",
                "  %data = getelementptr [64 x i8], ptr %buffer, i64 0, i64 0",
                *(f"  {line}" for line in format_double),
                "  %written = sext i32 %written32 to i64",
                "  br label %scan",
                "scan:",
                "  %index = phi i64 [ 0, %format ], [ %next, %scan_next ]",
                "  %needs_suffix = phi i1 [ true, %format ], [ %still_needs_suffix, %scan_next ]",
                "  %scan_done = icmp eq i64 %index, %written",
                "  br i1 %scan_done, label %write, label %scan_byte",
                "scan_byte:",
                "  %byte_ptr = getelementptr i8, ptr %data, i64 %index",
                "  %byte = load i8, ptr %byte_ptr",
                "  %is_dot = icmp eq i8 %byte, 46",
                "  %is_e = icmp eq i8 %byte, 101",
                "  %is_E = icmp eq i8 %byte, 69",
                "  %has_lower_marker = or i1 %is_dot, %is_e",
                "  %has_marker = or i1 %has_lower_marker, %is_E",
                "  %still_needs_suffix = select i1 %has_marker, i1 false, i1 %needs_suffix",
                "  br label %scan_next",
                "scan_next:",
                "  %next = add i64 %index, 1",
                "  br label %scan",
                "write:",
                "  %stream = call ptr @aether_stdout_stream()",
                "  %write_result = call i64 @fwrite(ptr %data, i64 1, i64 %written, ptr %stream)",
                "  br i1 %needs_suffix, label %suffix, label %finish",
                "suffix:",
                "  %suffix_result = call i32 @fputs(ptr @.aether.io.double.suffix, ptr %stream)",
                "  br label %finish",
                "finish:",
                "  br i1 %newline, label %line, label %done",
                "line:",
                "  %newline_result = call i32 @putchar(i32 10)",
                "  br label %done",
                "done:",
                "  ret void",
                "panic:",
                "  %panic_result = call i32 @puts(ptr @.aether.io.locale.error)",
                "  call void @exit(i32 1)",
                "  unreachable",
                "}",
            ]
        )
