from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import errno
import os
import tempfile

from .string_value import EMPTY_STRING, MAX_STRING_LENGTH, StringValue


FILE_STATUS_TYPE = "FileStatus"
FILE_READ_RESULT_TYPE = "FileReadResult"
READ_TEXT_BUILTIN = "io.readText"
WRITE_TEXT_BUILTIN = "io.writeText"
WRITE_TEXT_ATOMIC_BUILTIN = "io.writeTextAtomic"
APPEND_TEXT_BUILTIN = "io.appendText"
TEXT_FILE_BUILTINS = frozenset(
    {
        READ_TEXT_BUILTIN,
        WRITE_TEXT_BUILTIN,
        WRITE_TEXT_ATOMIC_BUILTIN,
        APPEND_TEXT_BUILTIN,
    }
)


class FileStatus(IntEnum):
    Success = 0
    NotFound = 1
    PermissionDenied = 2
    InvalidPath = 3
    InvalidUtf8 = 4
    IoError = 5


FILE_STATUS_VARIANTS = tuple(status.name for status in FileStatus)
_READ_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class TextFileRead:
    content: StringValue
    status: FileStatus


def read_text(path: StringValue) -> TextFileRead:
    normalized = _path_text(path)
    if normalized is None:
        return TextFileRead(EMPTY_STRING, FileStatus.InvalidPath)

    descriptor: int | None = None
    data = bytearray()
    status = FileStatus.Success
    try:
        descriptor = os.open(normalized, os.O_RDONLY)
        while True:
            try:
                chunk = os.read(descriptor, _READ_CHUNK_SIZE)
            except InterruptedError:
                continue
            if not chunk:
                break
            if len(data) > MAX_STRING_LENGTH - len(chunk):
                status = FileStatus.IoError
                break
            data.extend(chunk)
    except (MemoryError, OverflowError):
        status = FileStatus.IoError
    except OSError as exc:
        status = _status_from_os_error(exc)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                status = FileStatus.IoError

    if status is not FileStatus.Success:
        return TextFileRead(EMPTY_STRING, status)
    try:
        return TextFileRead(StringValue.from_utf8(data), FileStatus.Success)
    except (ValueError, UnicodeError):
        return TextFileRead(EMPTY_STRING, FileStatus.InvalidUtf8)
    except (MemoryError, OverflowError):
        return TextFileRead(EMPTY_STRING, FileStatus.IoError)


def write_text(path: StringValue, content: StringValue) -> FileStatus:
    return _write_text(path, content, append=False)


def append_text(path: StringValue, content: StringValue) -> FileStatus:
    return _write_text(path, content, append=True)


def write_text_atomic(path: StringValue, content: StringValue) -> FileStatus:
    """Durably replace a POSIX text file without exposing partial contents.

    An error before ``os.replace`` leaves the old destination untouched and
    attempts to remove the private temporary.  An error afterwards means the
    new file is visible but directory-metadata durability was not confirmed.
    The module-level syscall boundaries are intentionally monkeypatchable for
    fault-injection tests; this is not part of the Aether public API.
    """

    normalized = _path_text(path)
    if normalized is None:
        return FileStatus.InvalidPath
    parent, base = os.path.split(normalized)
    if not base:
        return FileStatus.InvalidPath
    if os.name != "posix":
        return FileStatus.IoError
    if not parent:
        parent = "."

    descriptor: int | None = None
    temporary: str | None = None
    published = False
    status = FileStatus.Success
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{base}.aether-atomic-",
            suffix=".tmp",
            dir=parent,
        )
        data = content.utf8_bytes
        offset = 0
        while offset < len(data):
            try:
                written = os.write(descriptor, data[offset:])
            except InterruptedError:
                continue
            if written <= 0:
                status = FileStatus.IoError
                break
            offset += written
        if status is not FileStatus.Success:
            return status

        status = _fsync_status(descriptor)
        if status is not FileStatus.Success:
            return status

        try:
            os.close(descriptor)
        except OSError as exc:
            status = _status_from_os_error(exc)
            return status
        finally:
            # POSIX close failure leaves the descriptor state unspecified; it
            # must not be retried and cleanup continues by pathname.
            descriptor = None

        try:
            os.replace(temporary, normalized)
        except OSError as exc:
            status = _status_from_os_error(exc)
            return status
        published = True

        directory_flags = os.O_RDONLY
        directory_flags |= getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_CLOEXEC", 0)
        directory: int | None = None
        try:
            directory = os.open(parent, directory_flags)
            status = _fsync_status(directory)
        except OSError as exc:
            status = _status_from_os_error(exc)
        finally:
            if directory is not None:
                try:
                    os.close(directory)
                except OSError:
                    status = FileStatus.IoError
        return status
    except (MemoryError, OverflowError):
        return FileStatus.IoError
    except OSError as exc:
        return _status_from_os_error(exc)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None and not published:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _write_text(path: StringValue, content: StringValue, *, append: bool) -> FileStatus:
    normalized = _path_text(path)
    if normalized is None:
        return FileStatus.InvalidPath

    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    descriptor: int | None = None
    status = FileStatus.Success
    try:
        descriptor = os.open(normalized, flags, 0o666)
        data = content.utf8_bytes
        offset = 0
        while offset < len(data):
            try:
                written = os.write(descriptor, data[offset:])
            except InterruptedError:
                continue
            if written <= 0:
                status = FileStatus.IoError
                break
            offset += written
    except OSError as exc:
        status = _status_from_os_error(exc)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                status = FileStatus.IoError
    return status


def _path_text(path: StringValue) -> str | None:
    if not isinstance(path, StringValue):
        raise TypeError("Aether text-file paths require a string value")
    data = path.utf8_bytes
    if not data or b"\x00" in data:
        return None
    # StringValue already established strict UTF-8 validity. Decoding here is
    # only the Python host boundary; it performs no expansion or normalization.
    return data.decode("utf-8", errors="strict")


def _fsync_status(descriptor: int) -> FileStatus:
    while True:
        try:
            os.fsync(descriptor)
            return FileStatus.Success
        except InterruptedError:
            continue
        except OSError as exc:
            return _status_from_os_error(exc)


def _status_from_os_error(error: OSError) -> FileStatus:
    if isinstance(error, FileNotFoundError) or error.errno == errno.ENOENT:
        return FileStatus.NotFound
    if isinstance(error, PermissionError) or error.errno in {errno.EACCES, errno.EPERM}:
        return FileStatus.PermissionDenied
    invalid_errnos = {errno.EINVAL, errno.ENAMETOOLONG}
    if error.errno in invalid_errnos:
        return FileStatus.InvalidPath
    return FileStatus.IoError
