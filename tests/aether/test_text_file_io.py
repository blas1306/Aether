from __future__ import annotations

from io import StringIO
from pathlib import Path
import errno
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.errors import AetherTypeError
from aether.capabilities import (
    AST_CAPABILITY_PROFILE,
    BackendCapabilityError,
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
from aether.text_file_io import (
    FileStatus,
    append_text,
    read_text,
    write_text,
    write_text_atomic,
)
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


def test_python_atomic_write_exact_bytes_paths_permissions_and_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "ledger.alpt"
    values = ["", "ascii", "hé\x00🙂", "line\n" * 40_000]
    for value in values:
        assert write_text_atomic(
            StringValue.dynamic(str(destination)), StringValue.dynamic(value)
        ) is FileStatus.Success
        assert destination.read_bytes() == value.encode()
        assert list(tmp_path.glob(".*.aether-atomic-*.tmp")) == []
    assert destination.stat().st_mode & 0o777 == 0o600

    relative = tmp_path / "relative.txt"
    monkeypatch.chdir(tmp_path)
    assert write_text_atomic(
        StringValue.dynamic("relative.txt"), StringValue.dynamic("relative")
    ) is FileStatus.Success
    assert relative.read_bytes() == b"relative"

    referent = tmp_path / "referent.txt"
    referent.write_bytes(b"referent")
    link = tmp_path / "link.txt"
    link.symlink_to(referent)
    assert write_text_atomic(
        StringValue.dynamic(str(link)), StringValue.dynamic("replacement")
    ) is FileStatus.Success
    assert not link.is_symlink()
    assert link.read_bytes() == b"replacement"
    assert referent.read_bytes() == b"referent"


def test_python_atomic_write_path_and_creation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = StringValue.dynamic("x")
    for invalid in ("", "bad\x00tail", "/", str(tmp_path) + "/"):
        assert write_text_atomic(StringValue.dynamic(invalid), content) is FileStatus.InvalidPath
    assert write_text_atomic(
        StringValue.dynamic(str(tmp_path / "missing" / "file")), content
    ) is FileStatus.NotFound

    monkeypatch.setattr(
        tempfile,
        "mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(PermissionError(errno.EACCES, "denied")),
    )
    assert write_text_atomic(
        StringValue.dynamic(str(tmp_path / "denied")), content
    ) is FileStatus.PermissionDenied


def test_python_atomic_write_rejects_unvalidated_non_posix_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "ledger.alpt"
    destination.write_bytes(b"old")
    monkeypatch.setattr("aether.text_file_io.os.name", "nt")
    assert write_text_atomic(
        StringValue.dynamic(str(destination)), StringValue.dynamic("new")
    ) is FileStatus.IoError
    assert destination.read_bytes() == b"old"


@pytest.mark.parametrize("fault", ["write", "zero-write", "fsync", "close", "rename"])
def test_python_atomic_faults_before_publish_preserve_old_bytes_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    destination = tmp_path / "ledger.alpt"
    destination.write_bytes(b"old-ledger")
    real_write = os.write
    real_fsync = os.fsync
    real_close = os.close
    real_replace = os.replace

    if fault == "write":
        monkeypatch.setattr(os, "write", lambda *_args: (_ for _ in ()).throw(OSError(errno.ENOSPC, "full")))
    elif fault == "zero-write":
        monkeypatch.setattr(os, "write", lambda *_args: 0)
    elif fault == "fsync":
        monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError(errno.EIO, "sync")))
    elif fault == "close":
        def fail_close(fd: int) -> None:
            real_close(fd)
            raise OSError(errno.EIO, "close")
        monkeypatch.setattr(os, "close", fail_close)
    elif fault == "rename":
        monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError(errno.EIO, "rename")))

    status = write_text_atomic(
        StringValue.dynamic(str(destination)), StringValue.dynamic("new-ledger")
    )
    assert status is FileStatus.IoError
    assert destination.read_bytes() == b"old-ledger"
    assert list(tmp_path.glob(".*.aether-atomic-*.tmp")) == []

    # Keep references live so monkeypatch wrappers cannot be mistaken for the
    # production boundaries by static analysis.
    assert all(callable(item) for item in (real_write, real_fsync, real_close, real_replace))


def test_python_atomic_directory_sync_failure_reports_error_after_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "ledger.alpt"
    destination.write_bytes(b"old")
    real_fsync = os.fsync
    calls = 0

    def fail_second_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EIO, "directory sync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_second_fsync)
    status = write_text_atomic(
        StringValue.dynamic(str(destination)), StringValue.dynamic("new")
    )
    assert status is FileStatus.IoError
    assert destination.read_bytes() == b"new"
    assert list(tmp_path.glob(".*.aether-atomic-*.tmp")) == []


def test_python_atomic_directory_open_failure_reports_published_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "ledger.alpt"
    destination.write_bytes(b"old")
    real_open = os.open

    def fail_directory_open(path: str, flags: int, mode: int = 0o777) -> int:
        if path == str(tmp_path) and flags & getattr(os, "O_DIRECTORY", 0):
            raise PermissionError(errno.EACCES, "directory open")
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", fail_directory_open)
    status = write_text_atomic(
        StringValue.dynamic(str(destination)), StringValue.dynamic("new")
    )
    assert status is FileStatus.PermissionDenied
    assert destination.read_bytes() == b"new"


def test_python_atomic_unlink_cleanup_is_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "ledger.alpt"
    destination.write_bytes(b"old")
    real_unlink = os.unlink
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError(errno.EIO, "rename")))
    monkeypatch.setattr(os, "unlink", lambda *_args: (_ for _ in ()).throw(OSError(errno.EIO, "unlink")))
    assert write_text_atomic(
        StringValue.dynamic(str(destination)), StringValue.dynamic("new")
    ) is FileStatus.IoError
    assert destination.read_bytes() == b"old"
    orphan = list(tmp_path.glob(".*.aether-atomic-*.tmp"))
    assert len(orphan) == 1
    real_unlink(orphan[0])


def test_python_atomic_concurrent_writers_publish_whole_values(tmp_path: Path) -> None:
    destination = tmp_path / "concurrent.txt"
    contents = ("a" * 100_000, "β" * 70_000)
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(
                lambda value: write_text_atomic(
                    StringValue.dynamic(str(destination)), StringValue.dynamic(value)
                ),
                contents,
            )
        )
    assert statuses == [FileStatus.Success, FileStatus.Success]
    assert destination.read_bytes() in {value.encode() for value in contents}
    assert list(tmp_path.glob(".*.aether-atomic-*.tmp")) == []


def test_python_atomic_retries_interrupted_write_and_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "interrupted.txt"
    real_write = os.write
    real_fsync = os.fsync
    write_interrupted = False
    fsync_interrupted = False

    def interrupted_write(fd: int, data: bytes) -> int:
        nonlocal write_interrupted
        if not write_interrupted:
            write_interrupted = True
            raise InterruptedError(errno.EINTR, "write")
        return real_write(fd, data)

    def interrupted_fsync(fd: int) -> None:
        nonlocal fsync_interrupted
        if not fsync_interrupted:
            fsync_interrupted = True
            raise InterruptedError(errno.EINTR, "fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "write", interrupted_write)
    monkeypatch.setattr(os, "fsync", interrupted_fsync)
    assert write_text_atomic(
        StringValue.dynamic(str(destination)), StringValue.dynamic("complete")
    ) is FileStatus.Success
    assert destination.read_bytes() == b"complete"


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
from io import writeTextAtomic as atomic;
int main() {{
    FileStatus created = atomic("{path}", "{content}");
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
        io.writeTextAtomic("{path}", "atomic");
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
    assert [call.builtin for call in calls] == [
        "io.writeText", "io.writeTextAtomic", "io.appendText", "io.readText"
    ]
    assert all(call.must_preserve for call in calls)
    assert calls[-1].allocates and calls[-1].reads_memory
    assert calls[0].writes_memory and calls[1].writes_memory and calls[2].writes_memory

    ssa = SSAOptimizerPipeline(verify_after_each=True).run(
        GeneralSSABuilder().build(ir)
    )
    ssa_calls = [
        instruction
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSACall)
        and instruction.builtin in {
            "io.writeText", "io.writeTextAtomic", "io.appendText", "io.readText"
        }
    ]
    assert [call.builtin for call in ssa_calls] == [
        "io.writeText", "io.writeTextAtomic", "io.appendText", "io.readText"
    ]


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
    FileStatus written = io.writeTextAtomic("{_quoted_path(path)}", "{content}");
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
    println(io.writeTextAtomic("", "x") == FileStatus.InvalidPath);
    println(io.writeTextAtomic("/", "x") == FileStatus.InvalidPath);
    println(io.appendText("bad{chr(0)}tail", "x") == FileStatus.InvalidPath);
    return 0;
}}
'''
    output = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=output, stderr=output) == 0
    assert output.getvalue() == "true\n" * 11
    assert path.read_bytes() == content.encode() + b"+tail"
    assert path.stat().st_mode & 0o777 == 0o600


_NATIVE_FAULT_SHIM = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int selected(const char *name) {
    const char *value = getenv("AETHER_ATOMIC_TEST_FAULT");
    return value != NULL && strcmp(value, name) == 0;
}

ssize_t write(int fd, const void *buffer, size_t count) {
    static ssize_t (*next_write)(int, const void *, size_t);
    if (next_write == NULL) next_write = dlsym(RTLD_NEXT, "write");
    if (selected("write")) { errno = EIO; return -1; }
    if (selected("short-write") && count > 2) count = 2;
    return next_write(fd, buffer, count);
}

int fsync(int fd) {
    static int (*next_fsync)(int);
    static int calls;
    if (next_fsync == NULL) next_fsync = dlsym(RTLD_NEXT, "fsync");
    calls += 1;
    if ((selected("file-fsync") && calls == 1) ||
        (selected("directory-fsync") && calls == 2)) {
        errno = EIO;
        return -1;
    }
    return next_fsync(fd);
}

int close(int fd) {
    static int (*next_close)(int);
    static int calls;
    if (next_close == NULL) next_close = dlsym(RTLD_NEXT, "close");
    calls += 1;
    int result = next_close(fd);
    if (selected("close") && calls == 1) { errno = EIO; return -1; }
    return result;
}

int rename(const char *old_path, const char *new_path) {
    static int (*next_rename)(const char *, const char *);
    if (next_rename == NULL) next_rename = dlsym(RTLD_NEXT, "rename");
    if (selected("rename") || selected("rename-unlink")) { errno = EIO; return -1; }
    return next_rename(old_path, new_path);
}

int unlink(const char *path) {
    static int (*next_unlink)(const char *);
    if (next_unlink == NULL) next_unlink = dlsym(RTLD_NEXT, "unlink");
    if (selected("rename-unlink")) { errno = EIO; return -1; }
    return next_unlink(path);
}

int mkstemp(char *template) {
    static int (*next_mkstemp)(char *);
    if (next_mkstemp == NULL) next_mkstemp = dlsym(RTLD_NEXT, "mkstemp");
    if (selected("create")) { errno = EACCES; return -1; }
    return next_mkstemp(template);
}
"""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize(
    "fault",
    ["create", "write", "file-fsync", "close", "rename", "short-write", "directory-fsync", "rename-unlink"],
)
def test_native_atomic_fault_injection_preserves_publication_contract(
    tmp_path: Path, fault: str
) -> None:
    destination = tmp_path / f"native-{fault}.alpt"
    destination.write_bytes(b"old-ledger")
    source = f'''import io; int main() {{
        FileStatus status = io.writeTextAtomic("{_quoted_path(destination)}", "new-ledger");
        if (status == FileStatus.{"Success" if fault == "short-write" else "IoError"}) {{ return 0; }}
        if (status == FileStatus.PermissionDenied && "{fault}" == "create") {{ return 0; }}
        return 9;
    }}'''
    llvm_path = tmp_path / f"native-{fault}.ll"
    executable = tmp_path / f"native-{fault}"
    shim = tmp_path / "atomic_fault_shim.c"
    llvm_path.write_text(LLVMBuilder().emit_llvm(_typed(source)), encoding="utf-8")
    shim.write_text(_NATIVE_FAULT_SHIM, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", "-O1", str(llvm_path), str(shim), "-ldl", "-o", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    environment = dict(os.environ, AETHER_ATOMIC_TEST_FAULT=fault)
    completed = subprocess.run([str(executable)], env=environment, check=False)
    assert completed.returncode == 0

    if fault in {"short-write", "directory-fsync"}:
        assert destination.read_bytes() == b"new-ledger"
    else:
        assert destination.read_bytes() == b"old-ledger"
    temporaries = list(tmp_path.glob(f"{destination.name}.aether-atomic-*"))
    if fault == "rename-unlink":
        assert len(temporaries) == 1
        temporaries[0].unlink()
    else:
        assert temporaries == []


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("optimization", ["-O0", "-O1", "-O2"])
def test_generated_text_file_runtime_compiles_at_clang_profiles(
    tmp_path: Path, optimization: str
) -> None:
    data_path = tmp_path / f"profile-{optimization[-1]}.txt"
    typed = _typed(
        f'''import io; int main() {{
        io.writeTextAtomic("{_quoted_path(data_path)}", "a");
        io.writeTextAtomic("{_quoted_path(data_path)}", "a");
        io.appendText("{_quoted_path(data_path)}", "b");
        FileReadResult result = io.readText("{_quoted_path(data_path)}");
        if (result.status != FileStatus.Success) {{ return 1; }}
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
    for capability in (
        Capability.ATOMIC_TEXT_FILE_WRITE,
        Capability.DURABLE_TEXT_FILE_WRITE,
    ):
        assert AST_CAPABILITY_PROFILE.support_for(capability).state is CapabilityState.PARTIAL
        assert NATIVE_CAPABILITY_PROFILE.support_for(capability).state is CapabilityState.PARTIAL

    module_items = completion_items("import io as Files;\nFiles.", 2, len("Files.") + 1)
    assert {item.label for item in module_items} == {
        "readText", "writeText", "writeTextAtomic", "appendText"
    }
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
    typed = _typed('import io; int main() { io.writeTextAtomic("x", "y"); return 0; }')
    monkeypatch.setattr("aether.backend.llvm.build.sys.platform", "win32")
    with pytest.raises(BackendCapabilityError, match="capability 'files'"):
        LLVMBuilder().emit_llvm(typed)


@pytest.mark.parametrize(
    "call",
    ['io.writeTextAtomic("x")', 'io.writeTextAtomic("x", "y", "z")', 'io.writeTextAtomic(1, "y")'],
)
def test_atomic_write_typechecker_rejects_wrong_arity_and_types(call: str) -> None:
    with pytest.raises(AetherTypeError):
        _typed(f"import io; int main() {{ {call}; return 0; }}")
