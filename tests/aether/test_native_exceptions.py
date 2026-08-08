from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBackendError
from aether.backend.llvm.exception_abi import ExceptionLoweringStrategy
from aether.backend.llvm.printer import LLVMPrinter
from aether.capabilities import BackendCapabilityError, BackendIdentity, validate_backend_capabilities
from aether.errors import AetherTypeError
from aether.ir import IRLowerer
from aether.pipeline import parse_source, prepare_typed_program
from aether.ssa import GeneralSSABuilder, SSAInvoke, SSAPackException
from aether.typechecker import TypeChecker


ERROR_TYPES = """
struct FileError implements Error {
    string text;
    string message() { return text; }
}

class NetworkError implements Error {
    string text;
    public string message() { return text; }
}
"""


def _lower(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return program, GeneralSSABuilder().build(IRLowerer().lower(program))


def _compile_and_run(
    source: str,
    tmp_path: Path,
    *,
    optimization: str = "0",
    mutate_llvm=None,
    sanitize: bool = False,
    exception_strategy: ExceptionLoweringStrategy = ExceptionLoweringStrategy.EVENT_OUT,
) -> subprocess.CompletedProcess[str]:
    compiler_name = "clang"
    clang = shutil.which(compiler_name)
    if clang is None:
        pytest.skip(f"{compiler_name} is not available")
    _program, module = _lower(source)
    llvm = LLVMBackend(
        LLVMPrinter(
            exception_strategy=exception_strategy,
            allow_test_exception_strategy=(
                exception_strategy is ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE
            ),
        )
    ).emit(module)
    if mutate_llvm is not None:
        llvm = mutate_llvm(llvm)
    tmp_path.mkdir(parents=True, exist_ok=True)
    llvm_path = tmp_path / "exceptions.ll"
    executable = tmp_path / "exceptions"
    llvm_path.write_text(llvm, encoding="utf-8")
    command = [clang, f"-O{optimization}", "-Wno-override-module"]
    if sanitize:
        command.extend(
            ["-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        )
    command.extend([str(llvm_path), "-o", str(executable)])
    if exception_strategy is ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE:
        # The prototype deliberately records its Itanium C++ ABI dependency;
        # use the runtime SONAME so minimal CI images need no development
        # linker symlink.
        command.append("-l:libstdc++.so.6")
    built = subprocess.run(command, check=False, capture_output=True, text=True)
    if built.returncode != 0:
        pytest.fail(f"clang rejected exception LLVM:\n{built.stderr}")
    environment = None
    if sanitize:
        import os

        environment = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1"}
    return subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )


def test_llvm_eh_prototype_is_real_and_kept_opt_in(tmp_path: Path) -> None:
    source = ERROR_TYPES + """
void fail() { throw FileError("eh"); }
int main() {
    try { fail(); }
    catch (FileError error) { println(error.message()); }
    return 0;
}
"""
    _program, module = _lower(source)
    llvm = LLVMBackend(
        LLVMPrinter(
            exception_strategy=ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
            allow_test_exception_strategy=True,
        )
    ).emit(module)

    assert "invoke void @fail" in llvm
    assert "landingpad { ptr, i32 } catch ptr @_ZTIPv" in llvm
    assert "personality ptr @__gxx_personality_v0" in llvm
    assert "resume { ptr, i32 }" in llvm
    assert "@__ae_exception_eh_raise_v1" in llvm
    assert "event.out" not in llvm

    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        exception_strategy=ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    )
    assert completed.returncode == 0
    assert completed.stdout == "eh\n"
    assert completed.stderr == ""


@pytest.mark.parametrize("optimization", ["0", "1", "2"])
def test_event_out_and_llvm_eh_execute_the_same_verified_ssa_corpus(
    optimization: str,
    tmp_path: Path,
) -> None:
    source = ERROR_TYPES + """
struct DetailError implements Error {
    string text;
    string message() { return text; }
}
interface MessageProducer {
    string produce();
}
struct ThrowingMessage implements MessageProducer {
    string text;
    string produce() { throw DetailError(text); }
}
void directFailure() { throw FileError("direct"); }
void indirectFailure() { throw NetworkError("indirect"); }
void apply(Function<(), void> operation) { operation(); }
void relay() {
    try { directFailure(); }
    catch (FileError error) { throw; }
}
int main() {
    try { directFailure(); }
    catch (FileError error) { println(error.message()); }

    try { apply(indirectFailure); }
    catch (Error error) { println(error.message()); }

    MessageProducer dynamic = ThrowingMessage("interface");
    try { println(dynamic.produce()); }
    catch (DetailError error) { println(error.message()); }

    try { relay(); }
    catch (FileError error) { println(error.message()); }
    return 0;
}
"""
    outputs = []
    for strategy in (
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ):
        completed = _compile_and_run(
            source,
            tmp_path / strategy.value,
            optimization=optimization,
            sanitize=optimization == "0",
            exception_strategy=strategy,
        )
        outputs.append((completed.returncode, completed.stdout, completed.stderr))

    assert outputs[0] == outputs[1] == (
        0,
        "direct\nindirect\ninterface\ndirect\n",
        "",
    )


def test_exception_lowering_uses_event_out_except_nonthrowing_error_message() -> None:
    source = ERROR_TYPES + """
void directFailure() { throw NetworkError("direct"); }
void indirectFailure() { throw FileError("indirect"); }
void apply(Function<(), void> operation) { operation(); }

int main() {
    try {
        directFailure();
        apply(indirectFailure);
    } catch (Error error) {
        println(error.message());
    }
    return 0;
}
"""
    _program, module = _lower(source)
    llvm = LLVMBackend().emit(module)

    assert "%AetherExceptionEventV1 = type" in llvm
    assert "@__ae_exception_create_v1" in llvm
    assert "@__ae_exception_destroy_v1" in llvm
    assert "invoke.direct.event.out" in llvm
    assert "invoke.indirect.event.out" in llvm
    assert "invoke.interface.event.out" not in llvm
    assert "invoke.error.message.failed" not in llvm
    assert "call ptr %interface.call.thunk" in llvm
    assert "landingpad" not in llvm
    assert "personality" not in llvm


@pytest.mark.parametrize("optimization", ["0", "1", "2"])
@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_native_nested_rethrow_and_replacement_are_stable_at_all_optimizations(
    strategy: ExceptionLoweringStrategy,
    optimization: str,
    tmp_path: Path,
) -> None:
    source = ERROR_TYPES + """
void failFile() { throw FileError("original"); }
void failNetwork() { throw NetworkError("replacement"); }

void relay() {
    try {
        failFile();
    } catch (FileError old) {
        throw;
    }
}

int main() {
    try {
        relay();
    } catch (FileError original) {
        println(original.message());
    }
    try {
        throw FileError("old");
    } catch (FileError old) {
        failNetwork();
    } catch (NetworkError wrong) {
        println("wrong same handler");
    }
    return 0;
}
"""
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization=optimization,
        exception_strategy=strategy,
    )

    assert completed.returncode == 1
    assert completed.stdout == "original\n"
    assert completed.stderr == (
        "Aether unhandled exception: NetworkError: replacement\n"
    )


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_native_class_identity_interface_pack_and_exact_matching(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    source = ERROR_TYPES + """
int main() {
    Error error = NetworkError("offline");
    try {
        throw error;
    } catch (FileError wrong) {
        println("wrong");
    } catch (NetworkError exact) {
        println(exact.message());
    }
    return 0;
}
"""
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        exception_strategy=strategy,
    )

    assert completed.returncode == 0
    assert completed.stdout == "offline\n"
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_native_managed_struct_snapshot_and_class_identity(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    source = """
struct ManagedError implements Error {
    string text;
    Array<int> data;
    List<string> names;
    int? code;
    string message() { return text; }
}
class IdentityError implements Error {
    string text;
    public string message() { return text; }
}
int main() {
    ManagedError original = ManagedError("snapshot", {1, 2}, {"a"}, null);
    try { throw original; }
    catch (ManagedError caught) {
        original.text = "mutated";
        println(caught.message());
    }

    IdentityError shared = IdentityError("before");
    try { throw shared; }
    catch (IdentityError caught) {
        println(caught.message());
        println(shared.message());
    }
    return 0;
}
"""
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        sanitize=True,
        exception_strategy=strategy,
    )

    assert completed.returncode == 0
    assert completed.stdout == "snapshot\nbefore\nbefore\n"
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_shared_native_recursion_aggregate_and_owned_field_corpus(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    """Exercise both transports with one broader verified-SSA program."""

    source = """
struct FileError implements Error {
    string text;
    string message() { return text; }
}
class NetworkError implements Error {
    string text;
    public string message() { return text; }
}
struct Pair {
    int left;
    int right;
}
struct Counter {
    int value;
    int advance(boolean fail) {
        value = value + 1;
        if (fail) { throw FileError("method result"); }
        return value;
    }
}
struct OwnedFields {
    Array<int> numbers;
    List<string> names;
    Error cause;
    string? note;
}
Pair pairOrFail(int value, boolean fail) {
    if (fail) { throw FileError("aggregate"); }
    return Pair(value, value + 1);
}
int recurse(int depth) {
    if (depth == 0) { throw FileError("recursive"); }
    return recurse(depth - 1);
}
int mutualA(int depth) {
    if (depth == 0) { throw NetworkError("mutual"); }
    return mutualB(depth - 1);
}
int mutualB(int depth) {
    if (depth == 0) { throw NetworkError("mutual"); }
    return mutualA(depth - 1);
}
int main() {
    Pair pair = pairOrFail(4, false);
    println(pair.left);
    try { Pair absent = pairOrFail(0, true); }
    catch (NetworkError wrong) { println("wrong aggregate"); }
    catch (FileError exact) { println(exact.message()); }

    try { recurse(6); }
    catch (FileError exact) { println(exact.message()); }
    try { mutualA(7); }
    catch (Error any) { println(any.message()); }

    Counter counter = Counter(10);
    println(counter.advance(false));
    try { counter.advance(true); }
    catch (FileError exact) { println(exact.message()); }

    Error cause = NetworkError("owned interface");
    OwnedFields fields = OwnedFields({1, 2}, {"a", "b"}, cause, null);
    println(fields.cause.message());
    return 0;
}
"""
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        sanitize=True,
        exception_strategy=strategy,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "4\naggregate\nrecursive\nmutual\n11\nmethod result\nowned interface\n"
    )
    assert completed.stderr == ""


@pytest.mark.parametrize("optimization", ["0", "1", "2"])
def test_native_constructor_failure_rolls_back_caller_and_callee_receivers(
    optimization: str,
    tmp_path: Path,
) -> None:
    source = """
struct ConstructionError implements Error {
    string text;
    string message() { return text; }
}
struct Wrapper {
    string initialized;
    Array<string> nested;
    constructor() {
        initialized = "owned";
        nested = {"partial"};
        throw ConstructionError("constructor");
    }
}
int main() {
    try { Wrapper value = Wrapper(); }
    catch (ConstructionError error) { println(error.message()); }
    return 0;
}
"""
    outputs = []
    for strategy in (
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ):
        completed = _compile_and_run(
            source,
            tmp_path / strategy.value,
            optimization=optimization,
            sanitize=True,
            exception_strategy=strategy,
        )
        outputs.append((completed.returncode, completed.stdout, completed.stderr))

    assert outputs[0] == outputs[1] == (0, "constructor\n", "")


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_native_nested_class_constructor_failure_releases_each_partial_owner(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    source = """
struct ConstructionError implements Error {
    string text;
    string message() { return text; }
}
class Broken {
    string initialized;
    Array<string> nested;
    constructor() {
        this.initialized = "child";
        this.nested = {"partial"};
        throw ConstructionError("nested class");
    }
}
class Outer {
    string initialized;
    Broken child;
    constructor() {
        this.initialized = "outer";
        this.child = Broken();
    }
}
class FailsBeforeFirstField {
    string uninitialized;
    Broken child;
    constructor() {
        failBeforeFirstField();
        this.uninitialized = "unreachable";
        this.child = Broken();
    }
}
void failBeforeFirstField() { throw ConstructionError("before first field"); }
int main() {
    try { Outer value = Outer(); }
    catch (ConstructionError error) { println(error.message()); }
    try { FailsBeforeFirstField value = FailsBeforeFirstField(); }
    catch (ConstructionError error) { println(error.message()); }
    return 0;
}
"""
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        sanitize=True,
        exception_strategy=strategy,
    )

    assert completed.returncode == 0
    assert completed.stdout == "nested class\nbefore first field\n"
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_constructor_failure_inside_catch_preserves_old_event_ownership(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    source = """
struct OuterError implements Error {
    string text;
    string message() { return text; }
}
struct ConstructionError implements Error {
    string text;
    string message() { return text; }
}
struct Wrapper {
    string initialized;
    List<string> nested;
    constructor() {
        initialized = "owned";
        nested = {"partial"};
        throw ConstructionError("new event");
    }
}
void failOuter() { throw OuterError("old event"); }
int main() {
    try { failOuter(); }
    catch (OuterError old) {
        try { Wrapper value = Wrapper(); }
        catch (ConstructionError current) {
            println(old.message());
            println(current.message());
        }
    }
    return 0;
}
"""
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        sanitize=True,
        exception_strategy=strategy,
    )

    assert completed.returncode == 0
    assert completed.stdout == "old event\nnew event\n"
    assert completed.stderr == ""


def test_throwing_error_message_is_rejected_semantically(tmp_path: Path) -> None:
    source = """
struct OuterError implements Error {
    string text;
    string message() { throw InnerError("inner"); }
}
struct InnerError implements Error {
    string text;
    string message() { return text; }
}
int main() {
    try {
        try {
            throw OuterError("outer");
        } catch (Error old) {
            println(old.message());
        }
    } catch (InnerError error) {
        println(error.message());
    }
    return 0;
}
"""
    with pytest.raises(
        AetherTypeError,
        match=r"Error\.message\(\) is non-throwing.*OuterError\.message",
    ):
        _compile_and_run(source, tmp_path, optimization="2", sanitize=True)


@pytest.mark.parametrize(
    ("panic_statement", "expected"),
    [
        ("int value = 2147483647 + 1;", "Aether panic: Integer overflow\n"),
        ("int value = 1 % 0;", "Aether panic: Division by zero\n"),
        (
            "Array<int> values = {1}; int value = values[1];",
            "Aether panic: Array index out of bounds\n",
        ),
    ],
)
@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_native_panic_bypasses_catch_and_never_forms_an_event(
    strategy: ExceptionLoweringStrategy,
    panic_statement: str,
    expected: str,
    tmp_path: Path,
) -> None:
    source = """
struct ArithmeticError implements Error {
    string text;
    string message() { return text; }
}
int main() {
    try {
        PANIC_STATEMENT
        throw ArithmeticError("catchable");
    } catch (Error error) {
        println("caught");
    }
    return 0;
}
""".replace("PANIC_STATEMENT", panic_statement)
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        exception_strategy=strategy,
    )

    assert completed.returncode == 1
    assert completed.stdout == expected
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_native_deep_propagation_and_high_volume_events(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    source = """
struct StressError implements Error {
    string text;
    string message() { return text; }
}
void descend(int depth) {
    if (depth == 0) { throw StressError("deep"); }
    descend(depth - 1);
}
void fail() { throw StressError("repeat"); }
void relay() {
    try { fail(); }
    catch (StressError error) { throw; }
}
int main() {
    try { descend(64); }
    catch (StressError error) { println(error.message()); }
    int count = 0;
    while (count < 2000) {
        try { relay(); }
        catch (StressError error) { count = count + 1; }
    }
    println(count);
    return 0;
}
"""
    completed = _compile_and_run(
        source,
        tmp_path,
        optimization="2",
        sanitize=True,
        exception_strategy=strategy,
    )

    assert completed.returncode == 0
    assert completed.stdout == "deep\n2000\n"
    assert completed.stderr == ""


def test_root_reporting_failure_is_fail_fast_and_destroys_original_event(
    tmp_path: Path,
) -> None:
    source = """
struct RootError implements Error {
    string text;
    string message() { return text; }
}
int main() { throw RootError("root"); }
"""

    def inject_message_failure(llvm: str) -> str:
        marker = "@__ae_exception_fault_mask_v1 = private global i32 0"
        assert marker in llvm
        return llvm.replace(marker, marker[:-1] + "4", 1)

    completed = _compile_and_run(
        source,
        tmp_path,
        mutate_llvm=inject_message_failure,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == "Aether panic: exception reporting failed"


@pytest.mark.parametrize(
    ("fault_mask", "expected"),
    [
        (1, "Aether panic: invalid private exception event"),
        (2, "Aether panic: invalid private exception event"),
        (4, "Aether panic: exception reporting failed"),
        (8, "Aether panic: exception reporting failed"),
    ],
)
@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_private_runtime_fault_injection_is_fail_fast_and_leak_free(
    strategy: ExceptionLoweringStrategy,
    fault_mask: int,
    expected: str,
    tmp_path: Path,
) -> None:
    source = """
struct RootError implements Error {
    string text;
    string message() { return text; }
}
int main() { throw RootError("fault"); }
"""

    def inject_fault(llvm: str) -> str:
        marker = "@__ae_exception_fault_mask_v1 = private global i32 0"
        assert marker in llvm
        return llvm.replace(marker, marker[:-1] + str(fault_mask), 1)

    completed = _compile_and_run(
        source,
        tmp_path,
        mutate_llvm=inject_fault,
        sanitize=True,
        exception_strategy=strategy,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == expected


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_struct_error_payload_allocation_failure_is_fail_fast(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    source = """
struct RootError implements Error {
    string text;
    string message() { return text; }
}
int main() { throw RootError("payload allocation"); }
"""

    def fail_payload_allocation(llvm: str) -> str:
        lines = llvm.splitlines()
        candidates = [
            index
            for index, line in enumerate(lines)
            if "%exception.box." in line and "call ptr @aether_alloc" in line
        ]
        assert len(candidates) == 1
        index = candidates[0]
        lines[index] = lines[index].replace(
            "@aether_alloc",
            "@__ae_exception_test_payload_alloc_fail_v1",
            1,
        )
        mutated = "\n".join(lines)
        return mutated + """

define private ptr @__ae_exception_test_payload_alloc_fail_v1(i64 %size) {
entry:
  call void @__ae_exception_panic_v1()
  unreachable
}
"""

    completed = _compile_and_run(
        source,
        tmp_path,
        mutate_llvm=fail_payload_allocation,
        sanitize=True,
        exception_strategy=strategy,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == "Aether panic: invalid private exception event"


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_throw_during_root_message_is_rejected_before_lowering(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    source = """
struct RootError implements Error {
    string text;
    string message() { throw ReportingError("recursive"); }
}
struct ReportingError implements Error {
    string text;
    string message() { return text; }
}
int main() { throw RootError("root"); }
"""
    with pytest.raises(
        AetherTypeError,
        match=r"Error\.message\(\) is non-throwing.*RootError\.message",
    ):
        _compile_and_run(
            source,
            tmp_path,
            sanitize=True,
            exception_strategy=strategy,
        )


def test_backend_rejects_malformed_descriptor_and_runtime_abi() -> None:
    _program, module = _lower(
        """
struct FileError implements Error {
    string text;
    string message() { return text; }
}
int main() { throw FileError("bad"); }
"""
    )
    pack_block = next(
        block
        for function in module.functions
        for block in function.blocks
        if any(isinstance(item, SSAPackException) for item in block.instructions)
    )
    index = next(
        index
        for index, item in enumerate(pack_block.instructions)
        if isinstance(item, SSAPackException)
    )
    pack = pack_block.instructions[index]
    assert isinstance(pack, SSAPackException)
    pack_block.instructions[index] = replace(pack, dynamic_type="OtherError")

    with pytest.raises(LLVMBackendError, match="descriptor identity"):
        LLVMBackend().emit(module)
    with pytest.raises(LLVMBackendError, match="runtime ABI mismatch"):
        LLVMPrinter(exception_runtime_abi_version=999)
    with pytest.raises(LLVMBackendError, match="unsupported exception lowering"):
        LLVMPrinter(exception_strategy="stack-scanning")
    with pytest.raises(LLVMBackendError, match="test-only prototype"):
        LLVMPrinter(
            exception_strategy=ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE
        )


def test_backend_rejects_malformed_invoke_before_llvm_emission() -> None:
    _program, module = _lower(
        """
struct FileError implements Error {
    string text;
    string message() { return text; }
}
void fail() { throw FileError("bad invoke"); }
int main() {
    try { fail(); }
    catch (FileError error) { println(error.message()); }
    return 0;
}
"""
    )
    block = next(
        block
        for function in module.functions
        for block in function.blocks
        if isinstance(block.instructions[-1], SSAInvoke)
    )
    invoke = block.instructions[-1]
    assert isinstance(invoke, SSAInvoke)
    block.instructions[-1] = replace(invoke, exceptional_arguments=())

    with pytest.raises(
        LLVMBackendError,
        match="malformed or unverified SSA",
    ):
        LLVMBackend().emit(module)


def test_stable_native_capability_gate_still_rejects_exceptions() -> None:
    program = prepare_typed_program(
        """
struct FileError implements Error {
    string text;
    string message() { return text; }
}
int main() { throw FileError("still gated"); }
""",
        TypeChecker(),
    )

    with pytest.raises(BackendCapabilityError, match="AE-BACKEND-ERROR_HANDLING"):
        validate_backend_capabilities(program, BackendIdentity.NATIVE)


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_root_reporter_calls_error_message_as_nonthrowing(
    strategy: ExceptionLoweringStrategy,
) -> None:
    _program, module = _lower(
        """
struct RootError implements Error {
    string text;
    string message() { return text; }
}
int main() {
    try { throw RootError("caught"); }
    catch (Error caught) { println(caught.message()); }
    throw RootError("root");
}
"""
    )
    llvm = LLVMBackend(
        LLVMPrinter(
            exception_strategy=strategy,
            allow_test_exception_strategy=(
                strategy is ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE
            ),
        )
    ).emit(module)

    root = llvm.split(
        "define private void @__ae_exception_root_terminate_v1", 1
    )[1]
    root = root.split("\n}", 1)[0]
    assert "%text = call ptr %thunk(ptr %carrier) nounwind" in root
    assert "%text = invoke ptr %thunk" not in root
    assert "message_event" not in root
    assert "message_threw" not in root
    assert "willreturn" not in root
    assert (
        "define { %struct.RootError, ptr } "
        "@RootError.message(%struct.RootError %this) nounwind {"
    ) in llvm
    assert any(
        line.startswith("define private ptr @__ae_interface_thunk_")
        and line.endswith(" nounwind {")
        for line in llvm.splitlines()
    )
    assert "invoke.interface.event.out" not in llvm
    assert "invoke.error.message.failed" not in llvm
    assert "call ptr %interface.call.thunk" in llvm


def test_backend_rejects_may_throw_error_message_target() -> None:
    _program, module = _lower(
        """
struct BrokenInternalError implements Error {
    string message() { return "not actually throwing"; }
}
int main() { throw BrokenInternalError(); }
"""
    )
    target = next(
        function
        for function in module.functions
        if function.name == "BrokenInternalError.message"
    )
    target.may_throw = True

    with pytest.raises(
        LLVMBackendError,
        match=r"non-throwing.*Error\.message",
    ):
        LLVMBackend().emit(module)


@pytest.mark.parametrize(
    "strategy",
    [
        ExceptionLoweringStrategy.EVENT_OUT,
        ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE,
    ],
)
def test_root_error_message_internal_failure_uses_panic_contract(
    strategy: ExceptionLoweringStrategy,
    tmp_path: Path,
) -> None:
    completed = _compile_and_run(
        """
struct RootError implements Error {
    Array<int> values;
    string message() {
        int impossible = values[1];
        return "unreachable";
    }
}
int main() { throw RootError({1}); }
""",
        tmp_path,
        exception_strategy=strategy,
    )

    assert completed.returncode == 1
    assert completed.stdout == "Aether panic: Array index out of bounds\n"
    assert completed.stderr == ""
