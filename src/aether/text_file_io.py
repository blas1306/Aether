from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import errno
import os

from .string_value import EMPTY_STRING, MAX_STRING_LENGTH, StringValue


FILE_STATUS_TYPE = "FileStatus"
FILE_READ_RESULT_TYPE = "FileReadResult"
READ_TEXT_BUILTIN = "io.readText"
WRITE_TEXT_BUILTIN = "io.writeText"
APPEND_TEXT_BUILTIN = "io.appendText"
TEXT_FILE_BUILTINS = frozenset(
    {READ_TEXT_BUILTIN, WRITE_TEXT_BUILTIN, APPEND_TEXT_BUILTIN}
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


def _status_from_os_error(error: OSError) -> FileStatus:
    if isinstance(error, FileNotFoundError) or error.errno == errno.ENOENT:
        return FileStatus.NotFound
    if isinstance(error, PermissionError) or error.errno in {errno.EACCES, errno.EPERM}:
        return FileStatus.PermissionDenied
    invalid_errnos = {errno.EINVAL, errno.ENAMETOOLONG}
    if error.errno in invalid_errnos:
        return FileStatus.InvalidPath
    return FileStatus.IoError
