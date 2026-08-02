from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBackendError
from aether.backend.llvm.printer import LLVMPrinter
from aether.capabilities import BackendCapabilityError, BackendIdentity, validate_backend_capabilities
from aether.ir import IRLowerer
from aether.pipeline import parse_source, prepare_typed_program
from aether.ssa import GeneralSSABuilder, SSAPackException
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
) -> subprocess.CompletedProcess[str]:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("clang is not available")
    _program, module = _lower(source)
    llvm = LLVMBackend().emit(module)
    if mutate_llvm is not None:
        llvm = mutate_llvm(llvm)
    llvm_path = tmp_path / "exceptions.ll"
    executable = tmp_path / "exceptions"
    llvm_path.write_text(llvm, encoding="utf-8")
    command = [clang, f"-O{optimization}", "-Wno-override-module"]
    if sanitize:
        command.extend(
            ["-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        )
    command.extend([str(llvm_path), "-o", str(executable)])
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


def test_exception_lowering_uses_versioned_event_out_for_every_invoke_form() -> None:
    source = ERROR_TYPES + """
void directFailure() { throw NetworkError("direct"); }
void indirectFailure() { throw FileError("indirect"); }
void apply(void() operation) { operation(); }

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
    assert "invoke.interface.event.out" in llvm
    assert "landingpad" not in llvm
    assert "personality" not in llvm


@pytest.mark.parametrize("optimization", ["0", "1", "2"])
def test_native_nested_rethrow_and_replacement_are_stable_at_all_optimizations(
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
    completed = _compile_and_run(source, tmp_path, optimization=optimization)

    assert completed.returncode == 1
    assert completed.stdout == "original\n"
    assert completed.stderr == (
        "Aether unhandled exception: NetworkError: replacement\n"
    )


def test_native_class_identity_interface_pack_and_exact_matching(tmp_path: Path) -> None:
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
    completed = _compile_and_run(source, tmp_path, optimization="2")

    assert completed.returncode == 0
    assert completed.stdout == "offline\n"
    assert completed.stderr == ""


def test_native_throwing_message_replaces_old_caught_event(tmp_path: Path) -> None:
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
    completed = _compile_and_run(source, tmp_path, optimization="2", sanitize=True)

    assert completed.returncode == 0
    assert completed.stdout == "inner\n"
    assert completed.stderr == ""


def test_native_panic_bypasses_catch_and_never_forms_an_event(tmp_path: Path) -> None:
    source = """
struct ArithmeticError implements Error {
    string text;
    string message() { return text; }
}
int main() {
    try {
        int value = 2147483647 + 1;
        throw ArithmeticError("catchable");
    } catch (Error error) {
        println("caught");
    }
    return 0;
}
"""
    completed = _compile_and_run(source, tmp_path, optimization="2")

    assert completed.returncode == 1
    assert completed.stdout == "Aether panic: Integer overflow\n"
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
