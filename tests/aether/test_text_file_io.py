from __future__ import annotations

from io import StringIO
from pathlib import Path
import os
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBuildError, LLVMBuilder, LLVMRunner
from aether.capabilities import (
    AST_CAPABILITY_PROFILE,
    NATIVE_CAPABILITY_PROFILE,
    Capability,
    CapabilityState,
)
from aether.ir import IRCall
from aether.language_service import completion_items
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import SSACall
from aether.ssa import GeneralSSABuilder
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.string_value import StringValue
from aether.text_file_io import FileStatus, append_text, read_text, write_text
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _quoted_path(path: Path) -> str:
    return path.as_posix().replace('"', '\\"')


def test_python_runtime_reads_empty_utf8_nul_large_and_invalid(tmp_path: Path) -> None:
    cases = {
        "empty.txt": b"",
        "ascii.txt": b"hello\nworld",
        "utf8.txt": "hé🙂".encode(),
        "nul.txt": b"left\x00right",
        "large.txt": ("á🙂line\n" * 20_000).encode(),
    }
    for name, expected in cases.items():
        path = tmp_path / name
        path.write_bytes(expected)
        result = read_text(StringValue.dynamic(str(path)))
        assert result.status is FileStatus.Success
        assert result.content.utf8_bytes == expected

    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"valid-prefix\xff")
    result = read_text(StringValue.dynamic(str(invalid)))
    assert result.status is FileStatus.InvalidUtf8
    assert result.content.utf8_bytes == b""


def test_python_runtime_path_and_error_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert read_text(StringValue.dynamic(str(tmp_path / "missing"))).status is FileStatus.NotFound
    assert read_text(StringValue.dynamic("")).status is FileStatus.InvalidPath
    assert read_text(StringValue.dynamic("bad\x00tail")).status is FileStatus.InvalidPath
    assert write_text(StringValue.dynamic(""), StringValue.dynamic("x")) is FileStatus.InvalidPath
    assert append_text(StringValue.dynamic("bad\x00tail"), StringValue.dynamic("x")) is FileStatus.InvalidPath

    def denied(*_args: object, **_kwargs: object) -> int:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(os, "open", denied)
    assert read_text(StringValue.dynamic("denied")).status is FileStatus.PermissionDenied
    assert write_text(StringValue.dynamic("denied"), StringValue.dynamic("x")) is FileStatus.PermissionDenied


def test_python_runtime_write_truncate_and_append_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    assert write_text(StringValue.dynamic(str(path)), StringValue.dynamic("old data")) is FileStatus.Success
    content = StringValue.dynamic("hé\x00🙂")
    assert write_text(StringValue.dynamic(str(path)), content) is FileStatus.Success
    assert path.read_bytes() == content.utf8_bytes
    assert append_text(StringValue.dynamic(str(path)), StringValue.dynamic("+tail")) is FileStatus.Success
    assert append_text(StringValue.dynamic(str(path)), StringValue.dynamic("")) is FileStatus.Success
    assert path.read_bytes() == content.utf8_bytes + b"+tail"

    created = tmp_path / "created.txt"
    assert append_text(StringValue.dynamic(str(created)), StringValue.dynamic("first")) is FileStatus.Success
    assert created.read_bytes() == b"first"
    assert write_text(StringValue.dynamic(str(created)), StringValue.dynamic("")) is FileStatus.Success
    assert created.read_bytes() == b""


def test_python_runtime_retries_short_writes_and_normalizes_zero_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[bytes] = []
    counts = iter((2, 1, 2))
    monkeypatch.setattr(os, "open", lambda *_args: 7)
    monkeypatch.setattr(os, "close", lambda _fd: None)

    def short_write(_fd: int, data: bytes) -> int:
        observed.append(bytes(data))
        return next(counts)

    monkeypatch.setattr(os, "write", short_write)
    assert write_text(StringValue.dynamic("path"), StringValue.dynamic("abcde")) is FileStatus.Success
    assert observed == [b"abcde", b"cde", b"de"]

    monkeypatch.setattr(os, "write", lambda _fd, _data: 0)
    assert write_text(StringValue.dynamic("path"), StringValue.dynamic("x")) is FileStatus.IoError


def test_ast_api_structured_results_aliases_and_bytes(tmp_path: Path) -> None:
    path = _quoted_path(tmp_path / "ast.txt")
    content = "hé\x00🙂"
    source = f'''\
import io as Files;
int main() {{
    FileStatus created = Files.writeText("{path}", "{content}");
    FileStatus appended = Files.appendText("{path}", "+tail");
    FileReadResult result = Files.readText("{path}");
    FileReadResult missing = Files.readText("{path}.missing");
    println(created == FileStatus.Success);
    println(appended == FileStatus.Success);
    println(result.status == FileStatus.Success);
    println(result.content.byteLength);
    println(missing.status == FileStatus.NotFound && missing.content.byteLength == 0);
    println(Files.readText("").status == FileStatus.InvalidPath);
    println(Files.readText("bad{chr(0)}tail").status == FileStatus.InvalidPath);
    return 0;
}}
'''
    result = run_aether(source)
    assert result.output == "true\ntrue\ntrue\n13\ntrue\ntrue\ntrue\n"
    assert (tmp_path / "ast.txt").read_bytes() == content.encode() + b"+tail"


def test_ir_ssa_identity_effects_and_dce_preservation(tmp_path: Path) -> None:
    path = _quoted_path(tmp_path / "effects.txt")
    typed = _typed(
        f'''import io; int main() {{
        io.writeText("{path}", "x");
        io.appendText("{path}", "y");
        io.readText("{path}");
        return 0;
        }}'''
    )
    ir = IRBackend().lower_verified(typed)
    calls = [
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall) and instruction.builtin is not None
    ]
    assert [call.builtin for call in calls] == ["io.writeText", "io.appendText", "io.readText"]
    assert all(call.must_preserve for call in calls)
    assert calls[-1].allocates and calls[-1].reads_memory
    assert calls[0].writes_memory and calls[1].writes_memory

    ssa = SSAOptimizerPipeline(verify_after_each=True).run(
        GeneralSSABuilder().build(ir)
    )
    ssa_calls = [
        instruction
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSACall)
        and instruction.builtin in {"io.writeText", "io.appendText", "io.readText"}
    ]
    assert [call.builtin for call in ssa_calls] == ["io.writeText", "io.appendText", "io.readText"]


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_exact_bytes_statuses_and_utf8_validation(tmp_path: Path) -> None:
    path = tmp_path / "native.txt"
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"bad\xff")
    large_path = tmp_path / "large.txt"
    large_bytes = ("á🙂line\n" * 20_000).encode()
    large_path.write_bytes(large_bytes)
    empty_path = tmp_path / "empty.txt"
    empty_path.write_bytes(b"")
    content = "hé\x00🙂"
    source = f'''\
import io;
int main() {{
    FileStatus written = io.writeText("{_quoted_path(path)}", "{content}");
    FileStatus appended = io.appendText("{_quoted_path(path)}", "+tail");
    FileReadResult result = io.readText("{_quoted_path(path)}");
    FileReadResult invalid = io.readText("{_quoted_path(invalid)}");
    FileReadResult missing = io.readText("{_quoted_path(tmp_path / 'missing')}");
    FileReadResult large = io.readText("{_quoted_path(large_path)}");
    FileReadResult empty = io.readText("{_quoted_path(empty_path)}");
    println(written == FileStatus.Success);
    println(appended == FileStatus.Success);
    println(result.status == FileStatus.Success && result.content.byteLength == 13);
    println(invalid.status == FileStatus.InvalidUtf8 && invalid.content.byteLength == 0);
    println(missing.status == FileStatus.NotFound && missing.content.byteLength == 0);
    println(large.status == FileStatus.Success && large.content.byteLength == {len(large_bytes)});
    println(empty.status == FileStatus.Success && empty.content.byteLength == 0);
    println(io.writeText("", "x") == FileStatus.InvalidPath);
    println(io.appendText("bad{chr(0)}tail", "x") == FileStatus.InvalidPath);
    return 0;
}}
'''
    output = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=output, stderr=output) == 0
    assert output.getvalue() == "true\ntrue\ntrue\ntrue\ntrue\ntrue\ntrue\ntrue\ntrue\n"
    assert path.read_bytes() == content.encode() + b"+tail"


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("optimization", ["-O0", "-O1", "-O2"])
def test_generated_text_file_runtime_compiles_at_clang_profiles(
    tmp_path: Path, optimization: str
) -> None:
    data_path = tmp_path / f"profile-{optimization[-1]}.txt"
    typed = _typed(
        f'''import io; int main() {{
        io.writeText("{_quoted_path(data_path)}", "a");
        io.appendText("{_quoted_path(data_path)}", "b");
        FileReadResult result = io.readText("{_quoted_path(data_path)}");
        if result.status != FileStatus.Success {{ return 1; }}
        return 0;
        }}'''
    )
    llvm = LLVMBuilder().emit_llvm(typed)
    llvm_path = tmp_path / f"profile-{optimization[-1]}.ll"
    executable = tmp_path / f"profile-{optimization[-1]}"
    llvm_path.write_text(llvm, encoding="utf-8")
    completed = subprocess.run(
        [shutil.which("clang") or "clang", optimization, str(llvm_path), "-o", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    subprocess.run([str(executable)], check=True)
    assert data_path.read_bytes() == b"ab"


def test_capabilities_and_completions_cover_text_file_api() -> None:
    for capability in (
        Capability.FILES,
        Capability.TEXT_FILE_READ,
        Capability.TEXT_FILE_WRITE,
        Capability.TEXT_FILE_APPEND,
    ):
        assert AST_CAPABILITY_PROFILE.support_for(capability).state is CapabilityState.COMPLETE
        assert NATIVE_CAPABILITY_PROFILE.support_for(capability).state is CapabilityState.PARTIAL

    module_items = completion_items("import io as Files;\nFiles.", 2, len("Files.") + 1)
    assert {item.label for item in module_items} == {"readText", "writeText", "appendText"}
    status_items = completion_items("FileStatus.", 1, len("FileStatus.") + 1)
    assert {item.label for item in status_items} == {
        "Success",
        "NotFound",
        "PermissionDenied",
        "InvalidPath",
        "InvalidUtf8",
        "IoError",
    }
    result_items = completion_items(
        "FileReadResult result = io.readText(\"x\");\nresult.",
        2,
        len("result.") + 1,
    )
    assert {item.label for item in result_items} == {"content", "status"}


def test_native_windows_reports_pending_utf16_path_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = _typed('import io; int main() { io.readText("x"); return 0; }')
    monkeypatch.setattr("aether.backend.llvm.build.sys.platform", "win32")
    with pytest.raises(LLVMBuildError, match="UTF-16 path conversion is pending"):
        LLVMBuilder().emit_llvm(typed)
