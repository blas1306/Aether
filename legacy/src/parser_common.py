from __future__ import annotations

import re


def _is_apostrophe_operator(text: str, idx: int) -> bool:
    """Detecta si una comilla simple actua como operador postfix estilo Octave."""
    if idx < 0 or idx >= len(text) or text[idx] != "'":
        return False
    j = idx - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    if j < 0:
        return False
    prev = text[j]
    return prev.isalnum() or prev in {")", "]", "}", "_"}


def _has_disabled_apostrophe_operator(text: str) -> bool:
    in_str = ""
    escape = False
    for idx, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = ""
            continue
        if ch in {"'", '"'}:
            if ch == "'":
                prev_idx = idx - 1
                while prev_idx >= 0 and text[prev_idx].isspace():
                    prev_idx -= 1
                if prev_idx >= 0 and text[prev_idx] == ".":
                    continue
                if _is_apostrophe_operator(text, idx):
                    return True
            in_str = ch
    return False


def _replace_cmd(text: str, cmd: str, replacement: str) -> str:
    """Reemplaza comandos \\cmd evitando coincidir con prefijos de otras palabras."""
    if not cmd.startswith("\\"):
        return text.replace(cmd, replacement)
    pattern = rf"{re.escape(cmd)}(?![A-Za-z])"
    return re.sub(pattern, replacement, text)


def _replace_cmd_outside_strings(text: str, cmd: str, replacement: str) -> str:
    """Reemplaza comandos solo fuera de strings entre comillas."""
    parts: list[str] = []
    segment: list[str] = []
    in_str = False
    quote = ""
    escape = False

    def flush_segment() -> None:
        nonlocal segment
        if not segment:
            return
        parts.append(_replace_cmd("".join(segment), cmd, replacement))
        segment = []

    for idx, ch in enumerate(text):
        if in_str:
            parts.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
                quote = ""
            continue

        if ch in {"'", '"'}:
            if ch == "'" and _is_apostrophe_operator(text, idx):
                segment.append(ch)
                continue
            flush_segment()
            parts.append(ch)
            in_str = True
            quote = ch
            continue

        segment.append(ch)

    flush_segment()
    return "".join(parts)


def _find_matching_paren(text: str, start_idx: int) -> int | None:
    """Busca el parentesis de cierre para el '(' en start_idx."""
    depth = 0
    in_str = False
    quote = ""
    escape = False
    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if in_str:
            if ch == quote:
                in_str = False
                quote = ""
            continue
        if ch in {"'", '"'}:
            prev = text[idx - 1] if idx > 0 else ""
            if ch == "'" and (prev.isalnum() or prev in {")", "]", "_"}):
                continue
            in_str = True
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _split_top_level(text: str, sep: str) -> list[str]:
    """Divide texto por separador solo a nivel tope (sin entrar a () [] {})."""
    if not sep:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    depth_paren = 0
    depth_brack = 0
    depth_brace = 0
    in_str = False
    quote = ""
    escape = False
    i = 0
    n = len(text)
    sep_len = len(sep)
    while i < n:
        ch = text[i]
        if escape:
            buf.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            i += 1
            continue
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
                quote = ""
            i += 1
            continue
        if ch in {"'", '"'}:
            prev = text[i - 1] if i > 0 else ""
            if ch == "'" and (prev.isalnum() or prev in {")", "]", "_"}):
                buf.append(ch)
                i += 1
                continue
            in_str = True
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            depth_paren += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth_paren = max(depth_paren - 1, 0)
            buf.append(ch)
            i += 1
            continue
        if ch == "[":
            depth_brack += 1
            buf.append(ch)
            i += 1
            continue
        if ch == "]":
            depth_brack = max(depth_brack - 1, 0)
            buf.append(ch)
            i += 1
            continue
        if ch == "{":
            depth_brace += 1
            buf.append(ch)
            i += 1
            continue
        if ch == "}":
            depth_brace = max(depth_brace - 1, 0)
            buf.append(ch)
            i += 1
            continue
        if (
            depth_paren == 0
            and depth_brack == 0
            and depth_brace == 0
            and text.startswith(sep, i)
        ):
            parts.append("".join(buf).strip())
            buf = []
            i += sep_len
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf).strip())
    return parts
