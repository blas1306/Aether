from __future__ import annotations

from dataclasses import dataclass
import sys

from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMNumericLocaleABI:
    """Platform spelling for an explicit C numeric locale in the host CRT."""

    platform: str | None = None

    @property
    def target(self) -> str:
        return self.platform or sys.platform

    @property
    def is_windows(self) -> bool:
        return self.target == "win32"

    def append_declarations(
        self,
        sections: list[str],
        *,
        parsing: bool = False,
        formatting: bool = False,
    ) -> None:
        declare = LLVMRuntimeCommon.declare
        if self.is_windows:
            declare(sections, "declare ptr @_create_locale(i32, ptr)")
            declare(sections, "declare void @_free_locale(ptr)")
            if parsing:
                declare(sections, "declare double @_strtod_l(ptr, ptr, ptr)")
            if formatting:
                declare(
                    sections,
                    "declare i32 @_snprintf_l(ptr, i64, ptr, ptr, ...)",
                )
            return

        declare(sections, "declare ptr @newlocale(i32, ptr, ptr)")
        declare(sections, "declare void @freelocale(ptr)")
        if parsing:
            declare(sections, "declare double @strtod_l(ptr, ptr, ptr)")
        if formatting:
            declare(sections, "declare ptr @uselocale(ptr)")
            declare(sections, "declare i32 @snprintf(ptr, i64, ptr, ...)")

    def create(self, result: str, locale_name: str) -> str:
        if self.is_windows:
            # MSVCRT/UCRT LC_NUMERIC is 4; _create_locale takes a category,
            # unlike POSIX newlocale which takes a category mask.
            return f"{result} = call ptr @_create_locale(i32 4, ptr {locale_name})"
        # Darwin and glibc assign different values to LC_NUMERIC, hence their
        # different LC_NUMERIC_MASK values.
        mask = 16 if self.target == "darwin" else 2
        return (
            f"{result} = call ptr @newlocale(i32 {mask}, ptr {locale_name}, "
            "ptr null)"
        )

    def free(self, locale: str) -> str:
        function = "_free_locale" if self.is_windows else "freelocale"
        return f"call void @{function}(ptr {locale})"

    def parse_double(self, result: str, data: str, locale: str) -> str:
        function = "_strtod_l" if self.is_windows else "strtod_l"
        return (
            f"{result} = call double @{function}(ptr {data}, ptr null, "
            f"ptr {locale})"
        )

    def format_double(
        self,
        *,
        result: str,
        data: str,
        size: int,
        format_: str,
        value: str,
        locale: str,
        previous: str = "%previous",
        ignored: str = "%ignored",
    ) -> list[str]:
        if self.is_windows:
            return [
                (
                    f"{result} = call i32 (ptr, i64, ptr, ptr, ...) "
                    f"@_snprintf_l(ptr {data}, i64 {size}, ptr {format_}, "
                    f"ptr {locale}, double {value})"
                ),
                self.free(locale),
            ]
        return [
            f"{previous} = call ptr @uselocale(ptr {locale})",
            (
                f"{result} = call i32 (ptr, i64, ptr, ...) @snprintf("
                f"ptr {data}, i64 {size}, ptr {format_}, double {value})"
            ),
            f"{ignored} = call ptr @uselocale(ptr {previous})",
            self.free(locale),
        ]
