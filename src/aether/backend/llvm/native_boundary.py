from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aether.interface_abi import INTERFACE_ABI_VERSION, dispatch_thunk_symbol
from aether.ir.model import IRWitnessTable
from aether.ir.types import (
    ClassRefType,
    InterfaceType,
    MethodResultType,
    StringType,
    StructType,
)
from aether.process_arguments import PROCESS_ARGS_BUILTIN
from aether.range_safety import RANGE_STEP_NONZERO_BUILTIN
from aether.scalar_math import NATIVE_SCALAR_MATH_FUNCTIONS
from aether.ssa.model import (
    SSACall,
    SSACallIndirect,
    SSAExceptionMatch,
    SSAExceptionPayload,
    SSAFunctionRef,
    SSAInterfaceConstruct,
    SSAInvoke,
    SSAInvokeIndirect,
    SSAInvokeInterface,
    SSAModule,
    SSAPackException,
    SSAPropagate,
    SSARethrow,
    SSAThrow,
)
from aether.string_parsing import PARSE_BUILTINS
from aether.string_value import STRING_SPLIT_BUILTIN, STRING_TRIM_BUILTIN
from aether.text_codec import TEXT_CODEC_BUILTINS
from aether.text_file_io import TEXT_FILE_BUILTINS

from .exception_abi import (
    EXCEPTION_RUNTIME_ABI_VERSION,
    ExceptionLoweringStrategy,
)
from .types import LLVMBackendError


class NativeBoundaryDisposition(str, Enum):
    """Milestone-6 disposition for a native-facing edge."""

    SAFE = "SAFE"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"
    REQUIRES_FUTURE_FFI = "REQUIRES FUTURE FFI"


class RuntimeExceptionBehavior(str, Enum):
    """The only exception behavior assigned to a runtime helper."""

    CANNOT_THROW = "cannot throw"
    MAY_PANIC = "may panic"
    MAY_THROW_AETHER_EXCEPTION = "may throw Aether exception"
    UNSUPPORTED = "unsupported"


class RuntimeVisibility(str, Enum):
    INTERNAL_ONLY = "internal only"
    PUBLIC_ONLY = "public only"
    UNSUPPORTED = "unsupported"


class NativeBoundaryDiagnostic(str, Enum):
    EXCEPTION_CROSSING_FOREIGN_BOUNDARY = "NBV-001"
    THROWING_CALLBACK = "NBV-002"
    UNSUPPORTED_NATIVE_INVOKE = "NBV-003"
    UNSUPPORTED_EXTERNAL_MAY_THROW = "NBV-004"
    RUNTIME_ABI_MISMATCH = "NBV-005"
    DESCRIPTOR_MISMATCH = "NBV-006"
    CALLBACK_EXCEPTION = "NBV-007"
    MISSING_CONTAINMENT = "NBV-008"
    WRONG_OWNERSHIP_TRANSFER = "NBV-009"
    RUNTIME_HELPER_CLASSIFICATION = "NBV-010"
    INTERFACE_ABI_MISMATCH = "NBV-011"


class NativeBoundaryVerificationError(LLVMBackendError):
    """Fail-closed rejection raised before textual LLVM is generated."""

    def __init__(self, code: NativeBoundaryDiagnostic, message: str) -> None:
        self.code = code
        self.detail = message
        super().__init__(f"{code.value}: {message}")


@dataclass(frozen=True)
class NativeBoundaryRequest:
    """Internal audit hook for a boundary form not exposed by Aether syntax."""

    name: str
    kind: str
    may_throw: bool = False
    event_transport: bool = False
    contained: bool = False
    transfers_event_ownership: bool = False


@dataclass(frozen=True)
class RuntimeHelperSpec:
    semantic_name: str
    exception_behavior: RuntimeExceptionBehavior
    visibility: RuntimeVisibility
    ownership: str
    event_transport: bool = False


def _helper(
    name: str,
    behavior: RuntimeExceptionBehavior,
    ownership: str,
) -> RuntimeHelperSpec:
    return RuntimeHelperSpec(
        name,
        behavior,
        RuntimeVisibility.INTERNAL_ONLY,
        ownership,
    )


# This registry is deliberately keyed by the semantic helper identity visible in
# verified SSA.  LLVM helper spellings are private implementation details and are
# inventoried by family in NATIVE_BOUNDARY_CONTAINMENT.md.
RUNTIME_HELPER_INVENTORY: dict[str, RuntimeHelperSpec] = {
    PROCESS_ARGS_BUILTIN: _helper(
        PROCESS_ARGS_BUILTIN,
        RuntimeExceptionBehavior.MAY_PANIC,
        "returns a new owned Array<string>; allocation/invariant failure panics",
    ),
    RANGE_STEP_NONZERO_BUILTIN: _helper(
        RANGE_STEP_NONZERO_BUILTIN,
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows its scalar argument; zero step terminates as panic",
    ),
    "__aether_string_byte_length": _helper(
        "__aether_string_byte_length",
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows the string; invalid storage or i32 overflow panics",
    ),
    STRING_TRIM_BUILTIN: _helper(
        STRING_TRIM_BUILTIN,
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows input and returns one owned string; allocation failure panics",
    ),
    STRING_SPLIT_BUILTIN: _helper(
        STRING_SPLIT_BUILTIN,
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows inputs and returns one owned Array<string>; invalid size/allocation panics",
    ),
    "__aether_retain": _helper(
        "__aether_retain",
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows an owner and creates one additional owner; bad ARC state panics",
    ),
    "__aether_release": _helper(
        "__aether_release",
        RuntimeExceptionBehavior.MAY_PANIC,
        "consumes one owner; bad ARC state panics",
    ),
    "__aether_interface_copy_owned": _helper(
        "__aether_interface_copy_owned",
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows an interface and returns one independent owner; bad witness/allocation panics",
    ),
}


# Complete family-level audit for helpers synthesized after SSA verification.
# Every emitted helper belongs to exactly one row; concrete monomorphized suffixes
# inherit the row's behavior, visibility and ownership contract.
RUNTIME_HELPER_FAMILY_INVENTORY: dict[str, RuntimeHelperSpec] = {
    "libc/libm/POSIX imports": RuntimeHelperSpec(
        "libc/libm/POSIX imports",
        RuntimeExceptionBehavior.CANNOT_THROW,
        RuntimeVisibility.PUBLIC_ONLY,
        "raw pointers/statuses only; never receive or return an Aether event",
    ),
    "allocation and ARC": _helper(
        "allocation and ARC",
        RuntimeExceptionBehavior.MAY_PANIC,
        "allocator returns initialized ownership; retain adds and release consumes one owner",
    ),
    "string runtime": _helper(
        "string runtime",
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrowed inputs; owned results; malformed storage/size/allocation fail fast",
    ),
    "Array/List runtime": _helper(
        "Array/List runtime",
        RuntimeExceptionBehavior.MAY_PANIC,
        "collection owners remain explicit; bounds/size/allocation/ARC failures panic",
    ),
    "Vector/Matrix runtime": _helper(
        "Vector/Matrix runtime",
        RuntimeExceptionBehavior.MAY_PANIC,
        "collection owners remain explicit; bounds/shape/corruption failures panic",
    ),
    "file runtime": _helper(
        "file runtime",
        RuntimeExceptionBehavior.MAY_PANIC,
        "OS failures return FileStatus; only corrupt Aether storage can panic",
    ),
    "process entry/runtime": _helper(
        "process entry/runtime",
        RuntimeExceptionBehavior.MAY_PANIC,
        "argv is borrowed during startup; snapshots are owned; root consumes an event",
    ),
    "compiler-generated value/lifecycle helpers": _helper(
        "compiler-generated value/lifecycle helpers",
        RuntimeExceptionBehavior.MAY_PANIC,
        "copy/retain creates ownership and drop/release consumes it; invariant failures panic",
    ),
    "interface dispatch thunks": RuntimeHelperSpec(
        "interface dispatch thunks",
        RuntimeExceptionBehavior.MAY_THROW_AETHER_EXCEPTION,
        RuntimeVisibility.INTERNAL_ONLY,
        "borrow receiver; throwing targets use the private event-out slot",
        event_transport=True,
    ),
    "private exception event helpers": RuntimeHelperSpec(
        "private exception event helpers",
        RuntimeExceptionBehavior.MAY_THROW_AETHER_EXCEPTION,
        RuntimeVisibility.INTERNAL_ONLY,
        "pack creates one owner; borrow creates none; transfer moves; destroy/root consume",
        event_transport=True,
    ),
    "panic/reporting helpers": _helper(
        "panic/reporting helpers",
        RuntimeExceptionBehavior.MAY_PANIC,
        "never return and never create a catchable event",
    ),
    "future native callback adapters": RuntimeHelperSpec(
        "future native callback adapters",
        RuntimeExceptionBehavior.UNSUPPORTED,
        RuntimeVisibility.UNSUPPORTED,
        "no callback ABI or event ownership contract exists",
    ),
}

for _name in PARSE_BUILTINS:
    RUNTIME_HELPER_INVENTORY[_name] = _helper(
        _name,
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows the string and returns a value/status aggregate; corrupt storage panics",
    )
for _name in TEXT_FILE_BUILTINS:
    RUNTIME_HELPER_INVENTORY[_name] = _helper(
        _name,
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows strings and returns status/owned result; OS failures are values, invariant failure panics",
    )
for _name in TEXT_CODEC_BUILTINS:
    RUNTIME_HELPER_INVENTORY[_name] = _helper(
        _name,
        RuntimeExceptionBehavior.MAY_PANIC,
        "borrows inputs and returns a value/owner; invalid range, size or allocation panics",
    )
for _name in NATIVE_SCALAR_MATH_FUNCTIONS:
    RUNTIME_HELPER_INVENTORY[_name] = _helper(
        _name,
        (
            RuntimeExceptionBehavior.MAY_PANIC
            if _name in {"abs", "Math.mod", "Math.factorial", "Math.floor", "Math.ceil"}
            else RuntimeExceptionBehavior.CANNOT_THROW
        ),
        "borrows scalar arguments and returns a scalar; never transports an event",
    )


class NativeBoundaryVerifier:
    """Verify containment facts that are specific to native lowering.

    SSA verification proves CFG and linear event ownership.  This verifier adds
    the native-only negative guarantee: event transport is accepted solely for
    module-owned Aether functions and compiler-owned interface thunks.
    """

    def __init__(
        self,
        module: SSAModule,
        *,
        exception_runtime_abi_version: int = EXCEPTION_RUNTIME_ABI_VERSION,
        interface_abi_version: int = INTERFACE_ABI_VERSION,
        exception_strategy: ExceptionLoweringStrategy = ExceptionLoweringStrategy.EVENT_OUT,
        boundary_requests: tuple[NativeBoundaryRequest, ...] = (),
    ) -> None:
        self.module = module
        self.exception_runtime_abi_version = exception_runtime_abi_version
        self.interface_abi_version = interface_abi_version
        self.exception_strategy = exception_strategy
        self.boundary_requests = boundary_requests
        self._functions = {function.name: function for function in module.functions}

    def verify(self) -> SSAModule:
        self._verify_abi_versions()
        self._verify_runtime_inventory()
        for request in self.boundary_requests:
            self._verify_boundary_request(request)
        function_refs = self._function_references()
        witnesses = self._witnesses()
        self._verify_witnesses(witnesses)
        self._verify_descriptors()

        for function in self.module.functions:
            for block in function.blocks:
                for instruction in block.instructions:
                    if isinstance(instruction, SSACall):
                        self._verify_call(instruction)
                    elif isinstance(instruction, SSAInvoke):
                        self._verify_direct_invoke(instruction)
                    elif isinstance(instruction, SSACallIndirect):
                        self._verify_indirect_call(
                            function.name, instruction, function_refs
                        )
                    elif isinstance(instruction, SSAInvokeIndirect):
                        self._verify_indirect_invoke(
                            function.name, instruction, function_refs
                        )
                    elif isinstance(instruction, SSAInvokeInterface):
                        self._verify_interface_invoke(instruction, witnesses)
                    elif isinstance(instruction, (SSAThrow, SSARethrow, SSAPropagate)):
                        self._verify_exception_exit(function.name, function.may_throw, instruction)
        return self.module

    def _verify_runtime_inventory(self) -> None:
        for name, spec in {
            **RUNTIME_HELPER_INVENTORY,
            **RUNTIME_HELPER_FAMILY_INVENTORY,
        }.items():
            if name != spec.semantic_name:
                self._fail(
                    NativeBoundaryDiagnostic.RUNTIME_HELPER_CLASSIFICATION,
                    f"runtime helper key '{name}' disagrees with semantic identity '{spec.semantic_name}'",
                )
            if spec.visibility is RuntimeVisibility.UNSUPPORTED:
                if spec.exception_behavior is not RuntimeExceptionBehavior.UNSUPPORTED:
                    self._fail(
                        NativeBoundaryDiagnostic.RUNTIME_HELPER_CLASSIFICATION,
                        f"unsupported helper family '{name}' has an executable failure mode",
                    )
                continue
            if (
                spec.visibility is RuntimeVisibility.PUBLIC_ONLY
                and name != "libc/libm/POSIX imports"
            ):
                self._fail(
                    NativeBoundaryDiagnostic.RUNTIME_HELPER_CLASSIFICATION,
                    f"runtime helper '{name}' would expose a non-approved public native ABI",
                )
            if (
                spec.exception_behavior is RuntimeExceptionBehavior.MAY_THROW_AETHER_EXCEPTION
                and not spec.event_transport
            ):
                self._fail(
                    NativeBoundaryDiagnostic.RUNTIME_HELPER_CLASSIFICATION,
                    f"runtime helper '{name}' may throw without private event transport",
                )

    def _verify_boundary_request(self, request: NativeBoundaryRequest) -> None:
        if request.kind not in {"raw-c", "callback", "external-invoke", "ffi"}:
            self._fail(
                NativeBoundaryDiagnostic.UNSUPPORTED_NATIVE_INVOKE,
                f"unsupported native boundary kind '{request.kind}' for '{request.name}'",
            )
        if request.transfers_event_ownership:
            self._fail(
                NativeBoundaryDiagnostic.WRONG_OWNERSHIP_TRANSFER,
                f"'{request.name}' attempts to transfer private event ownership to {request.kind}",
            )
        if request.event_transport:
            self._fail(
                NativeBoundaryDiagnostic.EXCEPTION_CROSSING_FOREIGN_BOUNDARY,
                f"'{request.name}' attempts to expose private event transport through {request.kind}",
            )
        if request.kind == "callback" and request.may_throw:
            self._fail(
                NativeBoundaryDiagnostic.THROWING_CALLBACK,
                f"callback '{request.name}' may throw; no native callback containment ABI exists",
            )
        if request.kind in {"external-invoke", "raw-c", "ffi"} and request.may_throw:
            self._fail(
                NativeBoundaryDiagnostic.UNSUPPORTED_EXTERNAL_MAY_THROW,
                f"external invoke '{request.name}' is marked may_throw; no foreign exception ABI exists",
            )

    def _verify_abi_versions(self) -> None:
        if self.exception_runtime_abi_version != EXCEPTION_RUNTIME_ABI_VERSION:
            self._fail(
                NativeBoundaryDiagnostic.RUNTIME_ABI_MISMATCH,
                "private exception runtime ABI mismatch: "
                f"compiler requires v{EXCEPTION_RUNTIME_ABI_VERSION}, "
                f"boundary requested v{self.exception_runtime_abi_version}",
            )
        if self.interface_abi_version != INTERFACE_ABI_VERSION:
            self._fail(
                NativeBoundaryDiagnostic.INTERFACE_ABI_MISMATCH,
                "private interface ABI mismatch: "
                f"compiler requires v{INTERFACE_ABI_VERSION}, "
                f"boundary requested v{self.interface_abi_version}",
            )
        if not isinstance(self.exception_strategy, ExceptionLoweringStrategy):
            self._fail(
                NativeBoundaryDiagnostic.UNSUPPORTED_NATIVE_INVOKE,
                f"unsupported exception transport {self.exception_strategy!r}",
            )

    def _function_references(self) -> dict[tuple[str, str], str]:
        references: dict[tuple[str, str], str] = {}
        for function in self.module.functions:
            for block in function.blocks:
                for instruction in block.instructions:
                    if isinstance(instruction, SSAFunctionRef):
                        references[
                            (function.name, instruction.result.name)
                        ] = instruction.function
        return references

    def _witnesses(self) -> dict[str, IRWitnessTable]:
        witnesses: dict[str, IRWitnessTable] = {}
        for function in self.module.functions:
            for block in function.blocks:
                for instruction in block.instructions:
                    if not isinstance(instruction, SSAInterfaceConstruct):
                        continue
                    previous = witnesses.get(instruction.witness.symbol)
                    if previous is not None and previous != instruction.witness:
                        self._fail(
                            NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                            f"conflicting canonical witness '{instruction.witness.symbol}'",
                        )
                    witnesses[instruction.witness.symbol] = instruction.witness
        return witnesses

    def _verify_witnesses(self, witnesses: dict[str, IRWitnessTable]) -> None:
        for witness in witnesses.values():
            if witness.abi_version != self.interface_abi_version:
                self._fail(
                    NativeBoundaryDiagnostic.INTERFACE_ABI_MISMATCH,
                    f"witness '{witness.symbol}' uses ABI v{witness.abi_version}",
                )
            for slot in witness.method_slots:
                expected_thunk = dispatch_thunk_symbol(
                    witness.interface_id,
                    witness.concrete_type_id,
                    slot.index,
                    slot.method_id,
                )
                if slot.thunk_symbol != expected_thunk:
                    self._fail(
                        NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                        f"interface slot '{slot.method_id}' has non-canonical thunk identity",
                    )
                target_name = (
                    f"{witness.concrete_type_id}."
                    f"{slot.method_id.rsplit('.', 1)[-1]}"
                )
                if target_name not in self._functions:
                    self._fail(
                        NativeBoundaryDiagnostic.EXCEPTION_CROSSING_FOREIGN_BOUNDARY,
                        f"interface thunk '{slot.thunk_symbol}' targets foreign or missing function '{target_name}'",
                    )

    def _verify_descriptors(self) -> None:
        identities: dict[str, object] = {}

        def register(name: str, type_: object) -> None:
            if not isinstance(type_, (StructType, ClassRefType)) or type_.name != name:
                self._fail(
                    NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                    f"descriptor identity '{name}' does not match concrete payload type '{type_}'",
                )
            previous = identities.get(name)
            if previous is not None and previous != type_:
                self._fail(
                    NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                    f"descriptor identity '{name}' denotes multiple native layouts",
                )
            identities[name] = type_

        pending_catches: set[str] = set()
        for function in self.module.functions:
            for block in function.blocks:
                for instruction in block.instructions:
                    if isinstance(instruction, SSAPackException):
                        if isinstance(instruction.payload.type, InterfaceType):
                            if (
                                instruction.payload.type.name != "Error"
                                or instruction.dynamic_type is not None
                            ):
                                self._fail(
                                    NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                                    "dynamic exception payload must be the Error interface without a static descriptor",
                                )
                        elif instruction.dynamic_type is None:
                            self._fail(
                                NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                                "concrete exception payload is missing its canonical descriptor",
                            )
                        else:
                            register(instruction.dynamic_type, instruction.payload.type)
                    elif isinstance(instruction, SSAExceptionPayload):
                        if instruction.catch_type == "Error":
                            if instruction.result.type != InterfaceType("Error"):
                                self._fail(
                                    NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                                    "Error catch payload does not use the canonical Error interface",
                                )
                        else:
                            register(instruction.catch_type, instruction.result.type)
                    elif isinstance(instruction, SSAExceptionMatch) and not instruction.catch_all:
                        pending_catches.add(instruction.catch_type)

        for name in pending_catches - identities.keys():
            target = self._functions.get(f"{name}.message")
            if target is None or not target.parameters:
                self._fail(
                    NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                    f"catch descriptor '{name}' has no module-owned canonical Error witness",
                )
            register(name, target.parameters[0].type)

        for name, concrete_type in identities.items():
            target = self._functions.get(f"{name}.message")
            expected_return = (
                MethodResultType(concrete_type, StringType())
                if isinstance(concrete_type, StructType)
                else StringType()
            )
            if (
                target is None
                or tuple(parameter.type for parameter in target.parameters)
                != (concrete_type,)
                or target.return_type != expected_return
                or target.may_throw
            ):
                self._fail(
                    NativeBoundaryDiagnostic.DESCRIPTOR_MISMATCH,
                    f"descriptor '{name}' has no ABI-compatible non-throwing "
                    "module-owned Error.message target",
                )
        self._exception_identities = identities

    def _verify_call(self, instruction: SSACall) -> None:
        if instruction.builtin is None:
            return
        spec = RUNTIME_HELPER_INVENTORY.get(instruction.builtin)
        if spec is None:
            self._fail(
                NativeBoundaryDiagnostic.RUNTIME_HELPER_CLASSIFICATION,
                f"runtime helper '{instruction.builtin}' has no native exception classification",
            )
        if spec.event_transport or spec.exception_behavior is RuntimeExceptionBehavior.MAY_THROW_AETHER_EXCEPTION:
            self._fail(
                NativeBoundaryDiagnostic.RUNTIME_HELPER_CLASSIFICATION,
                f"runtime helper '{instruction.builtin}' is incorrectly callable without private event containment",
            )

    def _verify_direct_invoke(self, instruction: SSAInvoke) -> None:
        if instruction.builtin is not None:
            self._fail(
                NativeBoundaryDiagnostic.UNSUPPORTED_EXTERNAL_MAY_THROW,
                f"runtime/external helper '{instruction.builtin}' cannot use Aether event transport",
            )
        target = self._functions.get(instruction.function)
        if target is None:
            self._fail(
                NativeBoundaryDiagnostic.UNSUPPORTED_EXTERNAL_MAY_THROW,
                f"external may_throw invoke '{instruction.function}' is unsupported",
            )
        if instruction.function == "main":
            self._fail(
                NativeBoundaryDiagnostic.MISSING_CONTAINMENT,
                "process entry 'main' cannot be invoked as a throwing callable",
            )

    def _verify_indirect_call(
        self,
        function_name: str,
        instruction: SSACallIndirect,
        function_refs: dict[tuple[str, str], str],
    ) -> None:
        target_name = function_refs.get((function_name, instruction.callee.name))
        if target_name is None:
            # This is an ordinary Aether callback call.  Function types have no
            # public/native provenance and no event slot; it is nonthrowing in
            # the accepted SSA.  A future FFI conversion must add provenance.
            return
        target = self._functions.get(target_name)
        if target is None or target.may_throw:
            self._fail(
                NativeBoundaryDiagnostic.CALLBACK_EXCEPTION,
                f"callback '{target_name}' may propagate an Aether exception through a nonthrowing function pointer",
            )

    def _verify_indirect_invoke(
        self,
        function_name: str,
        instruction: SSAInvokeIndirect,
        function_refs: dict[tuple[str, str], str],
    ) -> None:
        target_name = function_refs.get((function_name, instruction.callee.name))
        target = self._functions.get(target_name) if target_name is not None else None
        if target is None:
            # Function values are Aether-internal today.  There is no source or
            # public API that can construct one from a native pointer, so the
            # private event-out signature is owned by the compiler.  A future
            # conversion to/from C must submit a NativeBoundaryRequest and is
            # rejected above until an FFI containment ABI exists.
            return
        if target_name == "main":
            self._fail(
                NativeBoundaryDiagnostic.MISSING_CONTAINMENT,
                "process entry 'main' cannot cross an indirect throwing-call boundary",
            )
        if not target.may_throw:
            self._fail(
                NativeBoundaryDiagnostic.CALLBACK_EXCEPTION,
                f"indirect invoke target '{target_name}' is not marked may_throw",
            )

    def _verify_interface_invoke(
        self,
        instruction: SSAInvokeInterface,
        witnesses: dict[str, IRWitnessTable],
    ) -> None:
        if not instruction.slot.may_throw:
            self._fail(
                NativeBoundaryDiagnostic.EXCEPTION_CROSSING_FOREIGN_BOUNDARY,
                f"interface invoke '{instruction.slot.method_id}' is not marked may_throw",
            )
        matching_slots = [
            slot
            for witness in witnesses.values()
            if witness.interface_id == instruction.receiver.type.name
            for slot in witness.method_slots
            if slot.method_id == instruction.slot.method_id
        ]
        if not matching_slots:
            self._fail(
                NativeBoundaryDiagnostic.EXCEPTION_CROSSING_FOREIGN_BOUNDARY,
                f"interface invoke '{instruction.slot.method_id}' has no compiler-owned dispatch thunk",
            )
        if any(slot.may_throw != instruction.slot.may_throw for slot in matching_slots):
            self._fail(
                NativeBoundaryDiagnostic.EXCEPTION_CROSSING_FOREIGN_BOUNDARY,
                f"interface invoke '{instruction.slot.method_id}' disagrees with witness may_throw metadata",
            )

    def _verify_exception_exit(self, name: str, may_throw: bool, instruction: object) -> None:
        if getattr(instruction, "target") is not None:
            return
        if name == "main":
            return  # The private root reporter consumes and destroys the event.
        if not may_throw:
            self._fail(
                NativeBoundaryDiagnostic.MISSING_CONTAINMENT,
                f"function '{name}' can release an exception without the private event-out ABI",
            )

    @staticmethod
    def _fail(code: NativeBoundaryDiagnostic, message: str) -> None:
        raise NativeBoundaryVerificationError(code, message)
