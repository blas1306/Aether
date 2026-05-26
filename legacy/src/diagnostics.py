from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from parser_common import _is_apostrophe_operator


@dataclass(frozen=True)
class MathTeXDiagnostic:
    category: str
    kind: str
    message: str
    line: int | None = None
    column: int | None = None
    start: int | None = None
    end: int | None = None
    hint: str | None = None
    snippet: str | None = None


_CATEGORY_LABELS = {
    "parser": "Parse error",
    "block": "Block error",
    "runtime": "Runtime error",
    "build": "Build error",
}

_DIAGNOSTIC_LINE_OFFSET: ContextVar[int] = ContextVar("diagnostic_line_offset", default=0)


@contextmanager
def diagnostic_line_offset(offset: int):
    token = _DIAGNOSTIC_LINE_OFFSET.set(max(int(offset), 0))
    try:
        yield
    finally:
        _DIAGNOSTIC_LINE_OFFSET.reset(token)


def _with_line_offset(line: int | None) -> int | None:
    if line is None:
        return None
    return line + _DIAGNOSTIC_LINE_OFFSET.get()


def _with_diagnostic_line_offset(diag: MathTeXDiagnostic) -> MathTeXDiagnostic:
    line = _with_line_offset(diag.line)
    if line == diag.line:
        return diag
    return MathTeXDiagnostic(
        category=diag.category,
        kind=diag.kind,
        message=diag.message,
        line=line,
        column=diag.column,
        start=diag.start,
        end=diag.end,
        hint=diag.hint,
        snippet=diag.snippet,
    )


def _format_location(diag: MathTeXDiagnostic) -> str:
    if diag.line is None:
        return ""
    if diag.column is None:
        return f"line {diag.line}"
    return f"line {diag.line}, column {diag.column}"


def format_diagnostic(diag: MathTeXDiagnostic) -> str:
    parts = [diag.message]
    location = _format_location(diag)
    if location:
        parts.append(f"at {location}")
    text = " ".join(parts)
    if diag.hint:
        text += f" Hint: {diag.hint}"
    return text


def _normalize_snippet(snippet: str | None, *, max_length: int = 140) -> str:
    if not snippet:
        return ""
    compact = " ".join(snippet.strip().split())
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3].rstrip() + "..."


def render_diagnostic(
    diag: MathTeXDiagnostic,
    *,
    include_kind: bool = True,
    include_hint: bool = True,
    include_snippet: bool = True,
) -> str:
    category_label = _CATEGORY_LABELS.get(diag.category, diag.category.replace("-", " ").title())
    header = category_label
    if include_kind and diag.kind:
        header += f" [{diag.kind}]"
    header += f": {diag.message}"

    details: list[str] = []
    location = _format_location(diag)
    if location:
        details.append(location)
    if include_hint and diag.hint:
        details.append(f"Hint: {diag.hint}")
    if include_snippet:
        snippet = _normalize_snippet(diag.snippet)
        if snippet:
            details.append(f"Snippet: {snippet}")

    if not details:
        return header
    return f"{header} ({'; '.join(details)})"


def render_error_for_display(error: MathTeXDiagnostic | BaseException | str) -> str:
    if isinstance(error, MathTeXDiagnostic):
        return render_diagnostic(error)
    diagnostic = getattr(error, "diagnostic", None)
    if isinstance(diagnostic, MathTeXDiagnostic):
        return render_diagnostic(diagnostic)
    text = str(error).strip()
    if text:
        return text
    if isinstance(error, BaseException):
        return error.__class__.__name__
    return ""


class MathTeXParseError(SyntaxError):
    def __init__(self, diagnostic: MathTeXDiagnostic, *, recoverable: bool = False):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
        self.recoverable = recoverable
        self.msg = diagnostic.message
        self.lineno = diagnostic.line
        self.offset = diagnostic.column
        self.end_lineno = diagnostic.line if diagnostic.end is not None else None
        self.end_offset = diagnostic.end
        self.text = diagnostic.snippet

    @property
    def kind(self) -> str:
        return self.diagnostic.kind

    def __str__(self) -> str:
        return format_diagnostic(self.diagnostic)


class MathTeXBlockError(MathTeXParseError):
    pass


class MathTeXRuntimeError(ValueError):
    def __init__(self, diagnostic: MathTeXDiagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic

    @property
    def kind(self) -> str:
        return self.diagnostic.kind

    def __str__(self) -> str:
        return format_diagnostic(self.diagnostic)


def make_parse_error(
    kind: str,
    message: str,
    *,
    source: str | None = None,
    line: int | None = 1,
    column: int | None = None,
    start: int | None = None,
    end: int | None = None,
    hint: str | None = None,
    recoverable: bool = False,
) -> MathTeXParseError:
    return MathTeXParseError(
        MathTeXDiagnostic(
            category="parser",
            kind=kind,
            message=message,
            line=_with_line_offset(line),
            column=column,
            start=start if start is not None else column,
            end=end,
            hint=hint,
            snippet=source.strip() if source else None,
        ),
        recoverable=recoverable,
    )


def make_block_error(
    kind: str,
    message: str,
    *,
    source: str | None = None,
    line: int | None = None,
    column: int | None = None,
    start: int | None = None,
    end: int | None = None,
    hint: str | None = None,
) -> MathTeXBlockError:
    return MathTeXBlockError(
        MathTeXDiagnostic(
            category="block",
            kind=kind,
            message=message,
            line=_with_line_offset(line),
            column=column,
            start=start if start is not None else column,
            end=end,
            hint=hint,
            snippet=source.strip() if source else None,
        )
    )


def make_runtime_error(
    kind: str,
    message: str,
    *,
    source: str | None = None,
    line: int | None = 1,
    column: int | None = None,
    start: int | None = None,
    end: int | None = None,
    hint: str | None = None,
) -> MathTeXRuntimeError:
    return MathTeXRuntimeError(
        MathTeXDiagnostic(
            category="runtime",
            kind=kind,
            message=message,
            line=_with_line_offset(line),
            column=column,
            start=start if start is not None else column,
            end=end,
            hint=hint,
            snippet=source.strip() if source else None,
        )
    )


def make_build_diagnostic(
    kind: str,
    message: str,
    *,
    source: str | None = None,
    line: int | None = None,
    column: int | None = None,
    start: int | None = None,
    end: int | None = None,
    hint: str | None = None,
) -> MathTeXDiagnostic:
    return MathTeXDiagnostic(
        category="build",
        kind=kind,
        message=message,
        line=_with_line_offset(line),
        column=column,
        start=start if start is not None else column,
        end=end,
        hint=hint,
        snippet=source.strip() if source else None,
    )


def parse_error_from_syntax_error(
    exc: SyntaxError,
    *,
    source: str | None = None,
    kind: str = "invalid-expression",
    message: str | None = None,
    hint: str | None = None,
    recoverable: bool = False,
) -> MathTeXParseError:
    raw_message = getattr(exc, "msg", None) or str(exc)
    raw_text = getattr(exc, "text", None)
    text_matches = bool(source and raw_text and raw_text.strip() == source.strip())
    line = getattr(exc, "lineno", None) if text_matches else 1 if source else None
    column = getattr(exc, "offset", None) if text_matches else None
    end = getattr(exc, "end_offset", None) if text_matches else None

    normalized_kind = kind
    normalized_hint = hint
    normalized_message = message

    if "was never closed" in raw_message:
        normalized_kind = "unclosed-delimiter"
        if normalized_message is None:
            normalized_message = raw_message[:1].upper() + raw_message[1:]
        if normalized_hint is None:
            normalized_hint = "Add the missing closing delimiter to complete the expression."
    elif raw_message == "invalid syntax" and normalized_message is None:
        normalized_message = "Invalid expression syntax."
    elif normalized_message is None:
        normalized_message = raw_message[:1].upper() + raw_message[1:]

    return make_parse_error(
        normalized_kind,
        normalized_message,
        source=source or raw_text,
        line=line,
        column=column,
        end=end,
        hint=normalized_hint,
        recoverable=recoverable,
    )


def _find_prev_nonspace(text: str, idx: int) -> int | None:
    pos = idx - 1
    while pos >= 0 and text[pos].isspace():
        pos -= 1
    return pos if pos >= 0 else None


def _find_next_nonspace(text: str, idx: int) -> int | None:
    pos = idx
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos if pos < len(text) else None


def _is_left_operand_boundary(ch: str) -> bool:
    return ch.isalnum() or ch in {")", "]", "}", "_", "'"}


def _is_right_operand_boundary(ch: str) -> bool:
    return ch.isalnum() or ch in {"(", "[", "{", "_", "\\", '"', "'"}


def _line_col_from_index(source: str, idx: int) -> tuple[int, int]:
    safe_idx = max(0, min(idx, len(source)))
    line = source.count("\n", 0, safe_idx) + 1
    last_newline = source.rfind("\n", 0, safe_idx)
    column = safe_idx + 1 if last_newline < 0 else safe_idx - last_newline
    return line, column


def _line_for_token(source: str | None, token: str | None) -> int | None:
    if not source or not token or "\n" not in source:
        return None
    pattern = re.compile(rf"(?<![A-Za-z0-9_\\]){re.escape(token)}(?![A-Za-z0-9_])")
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        return None
    line, _column = _line_col_from_index(source, matches[0].start())
    return line


def find_unbalanced_delimiter(source: str) -> MathTeXDiagnostic | None:
    opens = {"(": ")", "[": "]", "{": "}"}
    closes = {value: key for key, value in opens.items()}
    stack: list[tuple[str, int]] = []
    in_string = ""
    escape = False

    for idx, ch in enumerate(source):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = ""
            continue

        if ch in {"'", '"'}:
            if ch == "'" and _is_apostrophe_operator(source, idx):
                continue
            in_string = ch
            continue

        if ch in opens:
            stack.append((ch, idx))
            continue

        if ch in closes:
            if not stack or stack[-1][0] != closes[ch]:
                opener = closes[ch]
                line, column = _line_col_from_index(source, idx)
                return MathTeXDiagnostic(
                    category="parser",
                    kind="unmatched-delimiter",
                    message=f"Unexpected closing '{ch}'.",
                    line=line,
                    column=column,
                    start=column,
                    end=column,
                    hint=f"Remove '{ch}' or add the matching '{opener}' before it.",
                    snippet=source.strip(),
                )
            stack.pop()

    if not stack:
        return None

    opener, start_idx = stack[-1]
    closer = opens[opener]
    if opener == "[" and re.search(r"(?:^|=)\s*\[", source):
        message = "Matrix literal '[' was never closed."
    elif opener == "(":
        message = "Parenthesis '(' was never closed."
    elif opener == "{":
        message = "Brace '{' was never closed."
    else:
        message = f"Bracket '{opener}' was never closed."
    line, column = _line_col_from_index(source, start_idx)
    return MathTeXDiagnostic(
        category="parser",
        kind="unclosed-delimiter",
        message=message,
        line=line,
        column=column,
        start=column,
        end=column,
        hint=f"Add '{closer}' to close the expression.",
        snippet=source.strip(),
    )


def find_expression_issue(source: str) -> MathTeXDiagnostic | None:
    delimiter_issue = find_unbalanced_delimiter(source)
    if delimiter_issue is not None:
        return delimiter_issue

    stripped = source.rstrip()
    for op in ("**", "//", ".*", "./", ".^", "+", "-", "*", "/", "^"):
        if not stripped.endswith(op):
            continue
        op_start = len(stripped) - len(op)
        line, col = _line_col_from_index(stripped, op_start)
        return MathTeXDiagnostic(
            category="parser",
            kind="malformed-dot-operator" if op.startswith(".") else "missing-operand",
            message=f"Operator '{op}' is missing a right operand.",
            line=line,
            column=col,
            start=col,
            end=col + len(op),
            hint="Add an expression after the operator.",
            snippet=source.strip(),
        )

    left_stripped = source.lstrip()
    left_offset = len(source) - len(left_stripped)
    for op in ("**", "//", ".*", "./", ".^", "*", "/", "^"):
        if not left_stripped.startswith(op):
            continue
        line, col = _line_col_from_index(source, left_offset)
        return MathTeXDiagnostic(
            category="parser",
            kind="malformed-dot-operator" if op.startswith(".") else "missing-operand",
            message=f"Operator '{op}' is missing a left operand.",
            line=line,
            column=col,
            start=col,
            end=col + len(op),
            hint="Add an expression before the operator.",
            snippet=source.strip(),
        )

    idx = 0
    while True:
        idx = source.find(".'", idx)
        if idx < 0:
            break
        prev_idx = _find_prev_nonspace(source, idx)
        if prev_idx is None or not _is_left_operand_boundary(source[prev_idx]):
            line, col = _line_col_from_index(source, idx)
            return MathTeXDiagnostic(
                category="parser",
                kind="invalid-transpose",
                message="Transpose postfix `.'` is missing a left operand.",
                line=line,
                column=col,
                start=col,
                end=col + 2,
                hint="Place `.'` immediately after a matrix expression.",
                snippet=source.strip(),
            )
        next_idx = _find_next_nonspace(source, idx + 2)
        if next_idx is not None and source[next_idx] == "'":
            line, col = _line_col_from_index(source, next_idx)
            return MathTeXDiagnostic(
                category="parser",
                kind="invalid-transpose",
                message="Invalid transpose postfix sequence after `.'`.",
                line=line,
                column=col,
                start=col,
                end=col,
                hint="Use a single transpose postfix or rewrite the expression explicitly.",
                snippet=source.strip(),
            )
        idx += 2

    dot_idx = 0
    while True:
        match = re.search(r"\.(\*|/|\^)", source[dot_idx:])
        if match is None:
            break
        op_start = dot_idx + match.start()
        op = source[op_start : op_start + 2]
        prev_idx = _find_prev_nonspace(source, op_start)
        next_idx = _find_next_nonspace(source, op_start + 2)
        if prev_idx is None or not _is_left_operand_boundary(source[prev_idx]):
            line, col = _line_col_from_index(source, op_start)
            return MathTeXDiagnostic(
                category="parser",
                kind="malformed-dot-operator",
                message=f"Dot operator '{op}' is missing a left operand.",
                line=line,
                column=col,
                start=col,
                end=col + 2,
                hint="Add a value before the dot operator.",
                snippet=source.strip(),
            )
        if next_idx is None or not _is_right_operand_boundary(source[next_idx]):
            line, col = _line_col_from_index(source, op_start)
            return MathTeXDiagnostic(
                category="parser",
                kind="malformed-dot-operator",
                message=f"Dot operator '{op}' is missing a right operand.",
                line=line,
                column=col,
                start=col,
                end=col + 2,
                hint="Add a value after the dot operator.",
                snippet=source.strip(),
            )
        dot_idx = op_start + 2

    return None


_NAME_ERROR_RE = re.compile(r"name '([^']+)' is not defined")
_UNDEFINED_RE = re.compile(r"^(?:Function\s+)?([A-Za-z_]\w*) is not defined\.$")
_CALL_EVAL_RE = re.compile(r"^Could not evaluate ([A-Za-z_]\w*)\(\.\.\.\): (.+)$")
_ARGS_RE = re.compile(r"^(?:Function\s+)?([A-Za-z_]\w*|The expression|The symbolic matrix) expects (\d+) argument\(s\)\.?$")


def _guess_called_name(source: str | None) -> str | None:
    if not source:
        return None
    rhs = source.split("=", 1)[1] if "=" in source else source
    match = re.search(r"([A-Za-z_]\w*)\s*\(", rhs)
    return match.group(1) if match else None


def _guess_index_target(source: str | None) -> str | None:
    if not source:
        return None
    rhs = source.split("=", 1)[1] if "=" in source else source
    match = re.search(r"([A-Za-z_]\w*)\s*(?:\(|\[)", rhs)
    return match.group(1) if match else None


def _message_with_symbol(prefix: str, name: str | None, fallback: str) -> str:
    if name:
        return f"{prefix} {name} {fallback}"
    return f"{prefix} {fallback}".strip()


def _infer_runtime_line_from_traceback(exc: Exception) -> int | None:
    candidate: int | None = None
    tb = exc.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename or ""
        if filename.startswith("<") and filename.endswith(">"):
            candidate = tb.tb_lineno
        tb = tb.tb_next
    return candidate


def runtime_error_from_exception(
    exc: Exception,
    *,
    source: str | None = None,
    line: int | None = 1,
) -> MathTeXRuntimeError:
    if isinstance(exc, MathTeXRuntimeError):
        return exc

    effective_line = line
    inferred_line = _infer_runtime_line_from_traceback(exc)
    if source and "\n" in source and inferred_line is not None:
        effective_line = inferred_line

    message = str(exc).strip() or exc.__class__.__name__
    called_name = _guess_called_name(source)
    index_target = _guess_index_target(source)

    if isinstance(exc, NameError):
        match = _NAME_ERROR_RE.search(message)
        name = match.group(1) if match else called_name
        token_line = _line_for_token(source, name)
        if token_line is not None:
            effective_line = token_line
        if called_name and name == called_name:
            return make_runtime_error(
                "undefined-function",
                f"Function {name} is not defined.",
                source=source,
                line=effective_line,
                hint="Define the function before calling it.",
            )
        return make_runtime_error(
            "undefined-variable",
            f"Variable {name or 'value'} is not defined.",
            source=source,
            line=effective_line,
            hint="Define the variable before using it in this expression.",
        )

    call_eval_match = _CALL_EVAL_RE.match(message)
    if call_eval_match:
        name, inner = call_eval_match.groups()
        if inner in {
            "The value cannot be applied as a function.",
            "The matrix cannot be evaluated with arguments.",
            "The expression expects 0 argument(s).",
            "The symbolic matrix expects 0 argument(s).",
        }:
            return make_runtime_error(
                "not-callable",
                f"{name} is not callable.",
                source=source,
                line=effective_line,
                hint="Only functions or symbolic expressions with parameters can be called.",
            )
        args_match = _ARGS_RE.match(inner)
        if args_match:
            _label, expected = args_match.groups()
            return make_runtime_error(
                "invalid-call-arity",
                f"{name} expects {expected} argument(s).",
                source=source,
                line=effective_line,
                hint="Call it with the required number of arguments.",
            )
        return make_runtime_error(
            "evaluation-failed",
            f"Could not evaluate {name}(...): {inner}",
            source=source,
            line=effective_line,
        )

    undefined_match = _UNDEFINED_RE.match(message)
    if undefined_match:
        name = undefined_match.group(1)
        token_line = _line_for_token(source, name)
        if token_line is not None:
            effective_line = token_line
        if message.startswith("Function "):
            return make_runtime_error(
                "undefined-function",
                f"Function {name} is not defined.",
                source=source,
                line=effective_line,
                hint="Define the function before calling it.",
            )
        if called_name and name == called_name:
            return make_runtime_error(
                "undefined-function",
                f"Function {name} is not defined.",
                source=source,
                line=effective_line,
                hint="Define the function before calling it.",
            )
        return make_runtime_error(
            "undefined-variable",
            f"Variable {name} is not defined.",
            source=source,
            line=effective_line,
            hint="Define the variable before using it in this expression.",
        )

    if isinstance(exc, TypeError) and "object is not callable" in message:
        token_line = _line_for_token(source, called_name)
        if token_line is not None:
            effective_line = token_line
        return make_runtime_error(
            "not-callable",
            f"{called_name or 'Value'} is not callable.",
            source=source,
            line=effective_line,
            hint="Only functions or symbolic expressions with parameters can be called.",
        )

    if isinstance(exc, IndexError) or message == "list index out of range" or message.startswith("Index out of range"):
        if index_target:
            return make_runtime_error(
                "index-out-of-range",
                f"Index is out of range for {index_target}.",
                source=source,
                line=effective_line,
                hint="Check that the index stays within the valid bounds.",
            )
        return make_runtime_error(
            "index-out-of-range",
            "Index is out of range.",
            source=source,
            line=effective_line,
            hint="Check that the index stays within the valid bounds.",
        )

    if "The value cannot be applied as a function." in message or "cannot be evaluated with arguments" in message:
        token_line = _line_for_token(source, called_name)
        if token_line is not None:
            effective_line = token_line
        return make_runtime_error(
            "not-callable",
            f"{called_name or 'Value'} is not callable.",
            source=source,
            line=effective_line,
            hint="Only functions or symbolic expressions with parameters can be called.",
        )

    args_match = _ARGS_RE.match(message)
    if args_match:
        label, expected = args_match.groups()
        token_line = _line_for_token(source, called_name or label)
        if token_line is not None:
            effective_line = token_line
        if expected == "0":
            return make_runtime_error(
                "not-callable",
                f"{called_name or label} is not callable.",
                source=source,
                line=effective_line,
                hint="Only functions or symbolic expressions with parameters can be called.",
            )
        return make_runtime_error(
            "invalid-call-arity",
            f"{called_name or label} expects {expected} argument(s).",
            source=source,
            line=effective_line,
            hint="Call it with the required number of arguments.",
        )

    if "must be an integer" in message or message == "Incomplete range in index.":
        return make_runtime_error(
            "invalid-index",
            message,
            source=source,
            line=effective_line,
            hint="Use integer indices or complete index ranges.",
        )

    if "is not a matrix" in message or "is not a vector/matrix" in message:
        return make_runtime_error(
            "invalid-index-target",
            message,
            source=source,
            line=effective_line,
            hint="Use indexing only on matrices or vectors of the expected shape.",
        )

    if "Matrix size mismatch" in message:
        return make_runtime_error(
            "incompatible-dimensions",
            "Incompatible dimensions for matrix multiplication.",
            source=source,
            line=effective_line,
            hint="Check that the inner dimensions agree.",
        )

    if "Incompatible dimensions" in message:
        return make_runtime_error(
            "incompatible-dimensions",
            message,
            source=source,
            line=effective_line,
            hint="Check that the operand shapes are compatible for this operation.",
        )

    if "Cannot mix SymPy matrices with NumPy arrays" in message:
        return make_runtime_error(
            "mixed-matrix-types",
            message,
            source=source,
            line=effective_line,
            hint="Convert both operands to the same matrix/array type before combining them.",
        )

    return make_runtime_error(
        "runtime-error",
        message,
        source=source,
        line=effective_line,
    )
