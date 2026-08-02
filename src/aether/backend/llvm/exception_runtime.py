from __future__ import annotations

from dataclasses import dataclass

from .exception_abi import EXCEPTION_EVENT_MAGIC, EXCEPTION_RUNTIME_ABI_VERSION
from .runtime_common import LLVMRuntimeCommon


@dataclass(frozen=True)
class LLVMExceptionRuntime:
    """Emit the private, explicit event-out exception runtime.

    Source code never observes these layouts.  The compiler moves ``ptr``
    handles linearly; only these helpers inspect an event.
    """

    enabled: bool

    def append(self, sections: list[str]) -> None:
        if not self.enabled:
            return

        declare = LLVMRuntimeCommon.declare
        declare(sections, "declare void @free(ptr)")
        declare(sections, "declare i64 @fwrite(ptr, i64, i64, ptr)")
        declare(sections, "declare i32 @fputs(ptr, ptr)")
        declare(sections, "declare void @exit(i32) noreturn")
        declare(sections, "@stderr = external global ptr")
        sections.extend(
            [
                "@__ae_exception_live_events_v1 = private global i64 0",
                "@__ae_exception_fault_mask_v1 = private global i32 0",
                '@.ae.exception.invariant = private unnamed_addr constant [46 x i8] c"Aether panic: invalid private exception event\\00"',
                '@.ae.exception.prefix = private unnamed_addr constant [29 x i8] c"Aether unhandled exception: \\00"',
                '@.ae.exception.separator = private unnamed_addr constant [3 x i8] c": \\00"',
                '@.ae.exception.newline = private unnamed_addr constant [2 x i8] c"\\0A\\00"',
                '@.ae.exception.reporting = private unnamed_addr constant [41 x i8] c"Aether panic: exception reporting failed\\00"',
                self._panic(),
                self._validate(),
                self._create(),
                self._borrow(),
                self._matches(),
                self._destroy(),
                self._root_terminate(),
            ]
        )

    @staticmethod
    def _panic() -> str:
        return "\n".join(
            [
                "define private void @__ae_exception_panic_v1() noreturn {",
                "entry:",
                "  %stream = load ptr, ptr @stderr",
                "  %ignored = call i32 @fputs(ptr @.ae.exception.invariant, ptr %stream)",
                "  call void @exit(i32 1)",
                "  unreachable",
                "}",
            ]
        )

    @staticmethod
    def _validate() -> str:
        return "\n".join(
            [
                "define private void @__ae_exception_validate_v1(ptr %event) {",
                "entry:",
                "  %nonnull = icmp ne ptr %event, null",
                "  br i1 %nonnull, label %header, label %panic",
                "header:",
                "  %magic_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 0",
                "  %magic = load i64, ptr %magic_ptr",
                f"  %magic_ok = icmp eq i64 %magic, {EXCEPTION_EVENT_MAGIC}",
                "  %abi_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 1",
                "  %abi = load i32, ptr %abi_ptr",
                f"  %abi_ok = icmp eq i32 %abi, {EXCEPTION_RUNTIME_ABI_VERSION}",
                "  %state_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 2",
                "  %state = load i32, ptr %state_ptr",
                "  %live = icmp eq i32 %state, 1",
                "  %header_ok = and i1 %magic_ok, %abi_ok",
                "  %valid = and i1 %header_ok, %live",
                "  br i1 %valid, label %check_descriptor, label %panic",
                "check_descriptor:",
                "  %descriptor_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 3",
                "  %descriptor = load ptr, ptr %descriptor_ptr",
                "  %descriptor_nonnull = icmp ne ptr %descriptor, null",
                "  br i1 %descriptor_nonnull, label %check_descriptor_abi, label %panic",
                "check_descriptor_abi:",
                "  %descriptor_version = load i64, ptr %descriptor",
                f"  %descriptor_ok = icmp eq i64 %descriptor_version, {EXCEPTION_RUNTIME_ABI_VERSION}",
                "  br i1 %descriptor_ok, label %done, label %panic",
                "panic:",
                "  call void @__ae_exception_panic_v1()",
                "  unreachable",
                "done:",
                "  ret void",
                "}",
            ]
        )

    @staticmethod
    def _create() -> str:
        size = "ptrtoint (ptr getelementptr (%AetherExceptionEventV1, ptr null, i64 1) to i64)"
        return "\n".join(
            [
                "define private ptr @__ae_exception_create_v1(ptr %descriptor, ptr %carrier, i32 %line, i32 %column) {",
                "entry:",
                "  %faults = load i32, ptr @__ae_exception_fault_mask_v1",
                "  %allocation_fault_bit = and i32 %faults, 1",
                "  %allocation_fault = icmp ne i32 %allocation_fault_bit, 0",
                "  br i1 %allocation_fault, label %panic, label %validate",
                "validate:",
                "  %descriptor_nonnull = icmp ne ptr %descriptor, null",
                "  %carrier_nonnull = icmp ne ptr %carrier, null",
                "  %valid = and i1 %descriptor_nonnull, %carrier_nonnull",
                "  br i1 %valid, label %allocate, label %panic",
                "allocate:",
                f"  %event = call ptr @aether_alloc(i64 {size})",
                "  %magic_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 0",
                f"  store i64 {EXCEPTION_EVENT_MAGIC}, ptr %magic_ptr",
                "  %abi_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 1",
                f"  store i32 {EXCEPTION_RUNTIME_ABI_VERSION}, ptr %abi_ptr",
                "  %state_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 2",
                "  store i32 1, ptr %state_ptr",
                "  %descriptor_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 3",
                "  store ptr %descriptor, ptr %descriptor_ptr",
                "  %carrier_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 4",
                "  store ptr %carrier, ptr %carrier_ptr",
                "  %line_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 5",
                "  store i32 %line, ptr %line_ptr",
                "  %column_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 6",
                "  store i32 %column, ptr %column_ptr",
                "  %count = load i64, ptr @__ae_exception_live_events_v1",
                "  %next = add nuw i64 %count, 1",
                "  store i64 %next, ptr @__ae_exception_live_events_v1",
                "  ret ptr %event",
                "panic:",
                "  call void @__ae_exception_panic_v1()",
                "  unreachable",
                "}",
            ]
        )

    @staticmethod
    def _borrow() -> str:
        return "\n\n".join(
            [
                "\n".join(
                    [
                        "define private ptr @__ae_exception_borrow_carrier_v1(ptr %event) {",
                        "entry:",
                        "  call void @__ae_exception_validate_v1(ptr %event)",
                        "  %carrier_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 4",
                        "  %carrier = load ptr, ptr %carrier_ptr",
                        "  ret ptr %carrier",
                        "}",
                    ]
                ),
                "\n".join(
                    [
                        "define private ptr @__ae_exception_borrow_witness_v1(ptr %event) {",
                        "entry:",
                        "  call void @__ae_exception_validate_v1(ptr %event)",
                        "  %descriptor_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 3",
                        "  %descriptor = load ptr, ptr %descriptor_ptr",
                        "  %witness_ptr = getelementptr %AetherExceptionDescriptorV1, ptr %descriptor, i32 0, i32 2",
                        "  %witness = load ptr, ptr %witness_ptr",
                        "  ret ptr %witness",
                        "}",
                    ]
                ),
            ]
        )

    @staticmethod
    def _matches() -> str:
        return "\n".join(
            [
                "define private i1 @__ae_exception_matches_v1(ptr %event, ptr %expected_descriptor) {",
                "entry:",
                "  call void @__ae_exception_validate_v1(ptr %event)",
                "  %descriptor_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 3",
                "  %descriptor = load ptr, ptr %descriptor_ptr",
                "  %matches = icmp eq ptr %descriptor, %expected_descriptor",
                "  ret i1 %matches",
                "}",
            ]
        )

    @staticmethod
    def _destroy() -> str:
        return "\n".join(
            [
                "define private void @__ae_exception_destroy_v1(ptr %event) {",
                "entry:",
                "  call void @__ae_exception_validate_v1(ptr %event)",
                "  %state_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 2",
                "  store i32 2, ptr %state_ptr",
                "  %descriptor_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 3",
                "  %descriptor = load ptr, ptr %descriptor_ptr",
                "  %witness_ptr = getelementptr %AetherExceptionDescriptorV1, ptr %descriptor, i32 0, i32 2",
                "  %witness = load ptr, ptr %witness_ptr",
                "  %drop_ptr = getelementptr %AetherWitnessHeader, ptr %witness, i32 0, i32 5",
                "  %drop = load ptr, ptr %drop_ptr",
                "  %carrier_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 4",
                "  %carrier = load ptr, ptr %carrier_ptr",
                "  call void %drop(ptr %carrier)",
                "  %count = load i64, ptr @__ae_exception_live_events_v1",
                "  %valid_count = icmp ugt i64 %count, 0",
                "  br i1 %valid_count, label %free_event, label %panic",
                "free_event:",
                "  %next = sub nuw i64 %count, 1",
                "  store i64 %next, ptr @__ae_exception_live_events_v1",
                "  call void @free(ptr %event)",
                "  ret void",
                "panic:",
                "  call void @__ae_exception_panic_v1()",
                "  unreachable",
                "}",
            ]
        )

    @staticmethod
    def _root_terminate() -> str:
        return "\n".join(
            [
                "define private void @__ae_exception_root_terminate_v1(ptr %event) noreturn {",
                "entry:",
                "  call void @__ae_exception_validate_v1(ptr %event)",
                "  %faults = load i32, ptr @__ae_exception_fault_mask_v1",
                "  %message_fault_bit = and i32 %faults, 4",
                "  %message_fault = icmp ne i32 %message_fault_bit, 0",
                "  br i1 %message_fault, label %reporting_failure, label %message",
                "message:",
                "  %descriptor_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 3",
                "  %descriptor = load ptr, ptr %descriptor_ptr",
                "  %name_ptr = getelementptr %AetherExceptionDescriptorV1, ptr %descriptor, i32 0, i32 1",
                "  %name = load ptr, ptr %name_ptr",
                "  %witness_ptr = getelementptr %AetherExceptionDescriptorV1, ptr %descriptor, i32 0, i32 2",
                "  %witness = load ptr, ptr %witness_ptr",
                "  %slots = getelementptr %AetherWitnessHeader, ptr %witness, i32 1",
                "  %slot = getelementptr %AetherWitnessSlot, ptr %slots, i64 0",
                "  %thunk_ptr = getelementptr %AetherWitnessSlot, ptr %slot, i32 0, i32 2",
                "  %thunk = load ptr, ptr %thunk_ptr",
                "  %carrier_ptr = getelementptr %AetherExceptionEventV1, ptr %event, i32 0, i32 4",
                "  %carrier = load ptr, ptr %carrier_ptr",
                "  %message_event_out = alloca ptr, align 8",
                "  store ptr null, ptr %message_event_out",
                "  %text = call ptr %thunk(ptr %carrier, ptr %message_event_out)",
                "  %message_event = load ptr, ptr %message_event_out",
                "  %message_failed = icmp ne ptr %message_event, null",
                "  br i1 %message_failed, label %message_threw, label %report",
                "message_threw:",
                "  call void @__ae_exception_destroy_v1(ptr %message_event)",
                "  br label %reporting_failure",
                "report:",
                "  %stream = load ptr, ptr @stderr",
                "  %prefix_ok32 = call i32 @fputs(ptr @.ae.exception.prefix, ptr %stream)",
                "  %name_ok32 = call i32 @fputs(ptr %name, ptr %stream)",
                "  %separator_ok32 = call i32 @fputs(ptr @.ae.exception.separator, ptr %stream)",
                "  %length = call i64 @aether_string_byte_length(ptr %text)",
                "  %data = call ptr @aether_string_data(ptr %text)",
                "  %written = call i64 @fwrite(ptr %data, i64 1, i64 %length, ptr %stream)",
                "  %newline_ok32 = call i32 @fputs(ptr @.ae.exception.newline, ptr %stream)",
                "  %prefix_bad = icmp slt i32 %prefix_ok32, 0",
                "  %name_bad = icmp slt i32 %name_ok32, 0",
                "  %separator_bad = icmp slt i32 %separator_ok32, 0",
                "  %newline_bad = icmp slt i32 %newline_ok32, 0",
                "  %short_write = icmp ne i64 %written, %length",
                "  %bad0 = or i1 %prefix_bad, %name_bad",
                "  %bad1 = or i1 %separator_bad, %newline_bad",
                "  %bad2 = or i1 %bad0, %bad1",
                "  %report_bad = or i1 %bad2, %short_write",
                "  %report_fault_bit = and i32 %faults, 8",
                "  %report_fault = icmp ne i32 %report_fault_bit, 0",
                "  %failed = or i1 %report_bad, %report_fault",
                "  call void @aether_string_release(ptr %text)",
                "  br i1 %failed, label %reporting_failure, label %finish",
                "reporting_failure:",
                "  call void @__ae_exception_destroy_v1(ptr %event)",
                "  %failure_stream = load ptr, ptr @stderr",
                "  %ignored = call i32 @fputs(ptr @.ae.exception.reporting, ptr %failure_stream)",
                "  call void @exit(i32 1)",
                "  unreachable",
                "finish:",
                "  call void @__ae_exception_destroy_v1(ptr %event)",
                "  call void @exit(i32 1)",
                "  unreachable",
                "}",
            ]
        )
