import re
import shutil
import subprocess
import sympy as sp
import numpy as np
import os
import platform
from dataclasses import dataclass
import logging
from pathlib import Path

from editor_pdf_sync import MtexTraceArtifact, TRACE_ARTIFACT_VERSION, TraceMappingSpan, write_trace_artifact
import latex_lang as runtime_lang
from diagnostics import (
    diagnostic_line_offset,
    make_build_diagnostic,
    render_diagnostic,
    runtime_error_from_exception,
)
from numeric_format import format_value_for_display, matrix_to_latex as render_matrix_to_latex, value_is_fully_numeric

# ImportÃ¡ tu propio motor MathTeX
from latex_lang import (
    ejecutar_linea,
    get_document_output_dir,
    reset_plot_state,
    reset_environment,
    set_document_output_dir,
    set_plot_mode,
    get_plot_mode,
)  # <- ajustAÃ© esto al nombre de tu funciÃ³n real


logger = logging.getLogger(__name__)


# ============================================================
# === CONVERSIÃ“N DE RESULTADOS A LATEX =======================
# ============================================================

def matrix_to_latex(M):
    """Convierte listas, arrays o matrices SymPy a formato LaTeX."""
    try:
        return render_matrix_to_latex(M)
    except Exception as e:
        return f"\\textcolor{{red}}{{Matrix error: {e}}}"


def expr_to_latex(expr):
    """Convierte cualquier tipo de expresiÃ³n a cÃ³digo LaTeX."""
    if value_is_fully_numeric(expr):
        return format_value_for_display(expr)

    if isinstance(expr, sp.Basic):
        return sp.latex(expr)
    if isinstance(expr, (sp.MatrixBase, np.ndarray, list, tuple)):
        return matrix_to_latex(expr)
    if isinstance(expr, (int, float, complex)):
        return format_value_for_display(expr)
    try:
        return sp.latex(sp.sympify(expr))
    except Exception:
        return format_value_for_display(expr)


_VAR_NOT_FOUND = object()
_LATEX_TEXT_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _escape_latex_text(text):
    return "".join(_LATEX_TEXT_ESCAPES.get(ch, ch) for ch in str(text))


def _latex_message(text, *, color="red"):
    return f"\\textcolor{{{color}}}{{{_escape_latex_text(text)}}}"


def _parse_one_based_index(token):
    cleaned = token.strip()
    if not re.fullmatch(r"[+-]?\d+", cleaned):
        raise ValueError("indice no valido")
    idx = int(cleaned)
    if idx < 1:
        raise ValueError("los indices empiezan en 1")
    return idx - 1


def _raise_index_out_of_range(name, index, size):
    raise ValueError(f"indice {index} fuera de rango para {name} (maximo {size})")


def _resolve_sequence_index(value, base_name, index):
    if isinstance(value, sp.MatrixBase):
        if value.cols == 1:
            size = value.rows
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value[index, 0]
        if value.rows == 1:
            size = value.cols
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value[0, index]
        raise ValueError(f"{base_name} es una matriz; usa dos indices")

    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            raise ValueError(f"{base_name} es escalar y no admite indices")
        if value.ndim == 1:
            size = value.shape[0]
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value[index]
        if value.ndim == 2 and 1 in value.shape:
            size = max(value.shape)
            if index >= size:
                _raise_index_out_of_range(base_name, index + 1, size)
            return value.reshape(-1)[index]
        if value.ndim == 2:
            raise ValueError(f"{base_name} es una matriz; usa dos indices")

    if isinstance(value, (list, tuple)):
        size = len(value)
        if index >= size:
            _raise_index_out_of_range(base_name, index + 1, size)
        return value[index]

    raise ValueError(f"{base_name} es escalar y no admite indices")


def _resolve_matrix_index(value, base_name, row_index, col_index):
    if isinstance(value, sp.MatrixBase):
        rows, cols = value.shape
        if row_index >= rows or col_index >= cols:
            raise ValueError(
                f"indices ({row_index + 1}, {col_index + 1}) fuera de rango para {base_name} "
                f"({rows}x{cols})"
            )
        return value[row_index, col_index]

    if isinstance(value, np.ndarray):
        if value.ndim != 2:
            if value.ndim == 1:
                raise ValueError(f"{base_name} es un vector; usa un solo indice")
            raise ValueError(f"{base_name} no admite dos indices")
        rows, cols = value.shape
        if row_index >= rows or col_index >= cols:
            raise ValueError(
                f"indices ({row_index + 1}, {col_index + 1}) fuera de rango para {base_name} "
                f"({rows}x{cols})"
            )
        return value[row_index, col_index]

    if isinstance(value, (list, tuple)):
        rows = len(value)
        if row_index >= rows:
            raise ValueError(f"fila {row_index + 1} fuera de rango para {base_name} (maximo {rows})")
        row_value = value[row_index]
        if not isinstance(row_value, (list, tuple, np.ndarray)):
            raise ValueError(f"{base_name} no es una matriz indexable con dos indices")
        cols = len(row_value)
        if col_index >= cols:
            raise ValueError(
                f"columna {col_index + 1} fuera de rango para {base_name}[{row_index + 1}] (maximo {cols})"
            )
        return row_value[col_index]

    raise ValueError(f"{base_name} no es una matriz indexable con dos indices")


def _resolve_var_reference(ref, contexto):
    expr = ref.strip()
    if expr in contexto:
        return contexto[expr]

    m = re.fullmatch(r"([a-zA-Z_][a-zA-Z0-9_]*)(?:\((.+)\)|\[(.+)\])", expr)
    if not m:
        return _VAR_NOT_FOUND

    base_name = m.group(1)
    raw_indices = m.group(2) if m.group(2) is not None else m.group(3)
    if base_name not in contexto:
        return _VAR_NOT_FOUND

    value = contexto[base_name]
    tokens = [tok.strip() for tok in raw_indices.split(",") if tok.strip()]
    if not tokens:
        raise ValueError("indice vacio")
    if len(tokens) > 2:
        raise ValueError("maximo dos indices")

    if len(tokens) == 1:
        i = _parse_one_based_index(tokens[0])
        return _resolve_sequence_index(value, base_name, i)

    i = _parse_one_based_index(tokens[0])
    j = _parse_one_based_index(tokens[1])
    return _resolve_matrix_index(value, base_name, i, j)

# ============================================================
# === REEMPLAZO AUTOMÃTICO DE VARIABLES ======================
# ============================================================

def _evaluate_expr_reference(expr, contexto):
    expr_text = expr.strip()
    if not expr_text:
        raise ValueError("expresion vacia")

    active_context = runtime_lang.env_ast if contexto is None else contexto
    runtime_env = runtime_lang.env_ast
    restore_snapshot = None

    if active_context is not runtime_env:
        restore_snapshot = dict(runtime_env)
        runtime_env.clear()
        runtime_env.update(active_context)

    try:
        ctx = runtime_lang._build_parser_context()
        ctx.env_ast = active_context
        expr_py = runtime_lang._oct_expr_to_python(expr_text, ctx)
        scope = ctx.eval_context({"env_ast": active_context})
        return eval(expr_py, {"__builtins__": __builtins__}, scope)
    finally:
        if restore_snapshot is not None:
            runtime_env.clear()
            runtime_env.update(restore_snapshot)


def reemplazar_vars(texto, contexto):
    """Reemplaza \var{nombre} con su valor LaTeX en el texto."""
    contexto = contexto or {}

    def repl(m):
        var = m.group(1)
        try:
            resolved = _resolve_var_reference(var, contexto)
        except Exception as e:
            return _latex_message(f"Error var {var}: {e}")
        if resolved is _VAR_NOT_FOUND:
            return _latex_message(f"?{var}?", color="gray")
        try:
            return expr_to_latex(resolved)
        except Exception as e:
            return _latex_message(f"Error var {var}: {e}")

    return re.sub(r"\\var\{([^{}]+)\}", repl, texto)


def reemplazar_exprs(texto, contexto):
    r"""Reemplaza \expr{expresion} evaluando expresiones MathTeX en el contexto actual."""
    contexto = contexto or {}

    def repl(m):
        expr = m.group(1)
        try:
            resolved = _evaluate_expr_reference(expr, contexto)
            return expr_to_latex(resolved)
        except Exception as e:
            return _latex_message(f"Error expr {expr}: {e}")

    return re.sub(r"\\expr\{([^{}]+)\}", repl, texto)


def reemplazar_plots(texto, contexto=None):
    def repl(m):
        raw_options = m.group(1)
        nombre = m.group(2)
        include_opts = raw_options.strip() if raw_options and raw_options.strip() else r"width=0.6\linewidth"
        plot_map = contexto.get("_plot_files", {}) if contexto else {}
        output_dir = contexto.get("_document_output_dir") if contexto else None
        output_dir_path = Path(output_dir) if output_dir else None
        candidatos = []
        if nombre in plot_map:
            candidatos.append(plot_map[nombre])
        candidatos.append(f"{nombre}.png")
        candidatos.append(f"plot_{nombre}.png")
        archivo = None
        include_target = None
        for ruta in candidatos:
            if not ruta:
                continue
            candidate_path = Path(ruta)
            if candidate_path.exists():
                archivo = str(candidate_path)
                include_target = candidate_path.as_posix()
                break
            if output_dir_path is not None and not candidate_path.is_absolute():
                built_candidate = output_dir_path / candidate_path
                if built_candidate.exists():
                    archivo = str(built_candidate)
                    include_target = candidate_path.name
                    break
        if archivo:
            return (
                "\\begin{figure}[H]\n"
                "\\centering\n"
                f"\\includegraphics[{include_opts}]{{{include_target or archivo}}}\n"
                "\\end{figure}\n"
            )
        return _latex_message(f"[No se encontro {nombre}]")

    return re.sub(r"\\plot(?:\[([^\]]*)\])?\{([a-zA-Z_][a-zA-Z0-9_]*)\}", repl, texto)


def reemplazar_tablas(texto, contexto=None):
    table_blocks = contexto.get("_table_blocks", {}) if contexto else {}
    missing_table = False

    def repl(m):
        nonlocal missing_table
        table_id = m.group(1).strip()
        table_tex = table_blocks.get(table_id)
        if table_tex is not None:
            return table_tex
        missing_table = True
        print(f"Warning: table '{table_id}' not found for \\table{{...}}.")
        return _latex_message(f"[Table {table_id} not found]")

    replaced = re.sub(r"\\table\{([^{}]+)\}", repl, texto)
    return replaced, missing_table


BASE_REQUIRED_LATEX_PACKAGES = (
    ("graphicx", r"\usepackage{graphicx}"),
    ("float", r"\usepackage{float}"),
    ("fontenc", r"\usepackage[T1]{fontenc}"),
    ("lmodern", r"\usepackage{lmodern}"),
)
OPTIONAL_LATEX_PACKAGES = {
    "booktabs": r"\usepackage{booktabs}",
    "xcolor": r"\usepackage{xcolor}",
}

CODEBLOCK_SPLIT_RE = re.compile(r"\\codeblock|\\endcodeblock|\\begin\{code\}|\\end\{code\}")
MULTIPASS_HINT_RE = re.compile(
    r"""(?ix)
    \\tableofcontents
    |\\listoffigures
    |\\listoftables
    |\\(?:ref|pageref|autoref|eqref)\{
    |\\(?:cite|nocite)\{
    |\\(?:bibliography|addbibresource)\{
    |\\printbibliography
    """
)
RERUN_LOG_HINTS = (
    "Rerun to get cross-references right.",
    "LaTeX Warning: Label(s) may have changed. Rerun",
    "There were undefined references.",
)


def _build_required_packages(contexto=None, include_xcolor: bool = False):
    package_list = list(BASE_REQUIRED_LATEX_PACKAGES)
    requested = set()

    if contexto:
        raw = contexto.get("_required_packages", set())
        if isinstance(raw, str):
            requested.add(raw)
        elif isinstance(raw, (list, tuple, set)):
            requested.update(str(pkg) for pkg in raw)

    if include_xcolor:
        requested.add("xcolor")

    for pkg_name in ("booktabs", "xcolor"):
        if pkg_name in requested:
            package_list.append((pkg_name, OPTIONAL_LATEX_PACKAGES[pkg_name]))

    return package_list


def ensure_required_packages(tex: str, required_packages=None) -> str:
    """Inserta los paquetes necesarios en el preambulo si faltan."""
    packages = required_packages if required_packages is not None else BASE_REQUIRED_LATEX_PACKAGES
    marker = r"\begin{document}"
    marker_idx = tex.find(marker)
    if marker_idx == -1:
        return tex

    preamble = tex[:marker_idx]
    rest = tex[marker_idx:]
    missing = []

    for pkg_name, directive in packages:
        pattern = rf"\\usepackage(?:\[[^\]]*\])?\{{{re.escape(pkg_name)}\}}"
        if re.search(pattern, preamble):
            continue
        missing.append(directive)

    if not missing:
        return tex

    insertion = ("\n" if preamble and not preamble.endswith("\n") else "") + "\n".join(missing) + "\n"
    return preamble + insertion + rest


def _tex_likely_needs_multipass(tex: str) -> bool:
    return bool(MULTIPASS_HINT_RE.search(tex))


def _log_requests_rerun(log_path: str) -> bool:
    if not os.path.exists(log_path):
        return False
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_text = f.read()
    except Exception:
        return False
    return any(hint in log_text for hint in RERUN_LOG_HINTS)


def _extract_latex_error_summary(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None

    for idx, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("!"):
            follow_up = ""
            if idx + 1 < len(lines):
                follow_up = lines[idx + 1].strip()
            if follow_up and not follow_up.startswith("l."):
                return f"{stripped} {follow_up}".strip()
            return stripped
    return None


def summarize_latex_build_failure(log_path: str | Path) -> str | None:
    return _extract_latex_error_summary(Path(log_path))


def explain_latex_build_failure(log_path: str | Path, tex_path: str | Path | None = None) -> str | None:
    summary = summarize_latex_build_failure(log_path)
    if not summary:
        return None

    lowered = summary.lower()
    tex_text = ""
    if tex_path is not None:
        try:
            tex_text = Path(tex_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            tex_text = ""

    if "misplaced alignment tab character &" in lowered:
        if r"\begin{matrix}" in tex_text:
            return (
                r"LaTeX found a matrix environment in the generated document, but the preamble does not include "
                r"\usepackage{amsmath}. Add that package explicitly to the .mtex document."
            )
        if any(token in tex_text for token in (r"\begin{tabular}", r"\begin{array}", r"\begin{align}", r"\begin{aligned}")):
            return (
                "LaTeX found an alignment marker '&' outside a valid alignment context. "
                "Check the surrounding tabular/array/align markup near the reported line."
            )
        return (
            "LaTeX found an '&' alignment marker where plain text or normal math was expected. "
            "Check the reported line for matrix, table, array, or align syntax."
        )

    if "undefined control sequence" in lowered:
        return (
            "LaTeX tried to use a command that is not defined in the current preamble. "
            "Check for a misspelled command or a missing package."
        )

    if "missing $ inserted" in lowered:
        return (
            "LaTeX detected content that should probably be inside math mode. "
            "Check underscores, carets, and formulas near the reported line."
        )

    return None


def _write_compile_log(log_path: Path, compile_log_path: Path, fallback_text: str | None = None) -> None:
    if log_path.exists():
        try:
            shutil.copyfile(log_path, compile_log_path)
            return
        except Exception:
            pass
    if fallback_text is None:
        return
    try:
        compile_log_path.write_text(fallback_text, encoding="utf-8")
    except Exception:
        pass


def _run_pdflatex(
    tex_filename: str,
    cwd: str,
    draftmode: bool = False,
    output_dir: str | None = None,
    synctex: bool = False,
):
    cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error"]
    if output_dir:
        cmd.append(f"-output-directory={output_dir}")
    if synctex:
        cmd.append("-synctex=1")
    if draftmode:
        cmd.append("-draftmode")
    cmd.append(tex_filename)
    return subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _delimiter_balance_delta(text: str) -> int:
    """Calcula el cambio neto de delimitadores ignorando strings y comentarios."""
    delta = 0
    in_str = False
    quote = ""
    escaped = False

    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if in_str:
            if ch == quote:
                in_str = False
                quote = ""
            continue
        if ch in {"'", '"'}:
            in_str = True
            quote = ch
            continue
        if ch in {"#", "%"}:
            break
        if ch in "([{":
            delta += 1
        elif ch in ")]}":
            delta -= 1
    return delta


def _statement_is_comment_only(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("#") or stripped.startswith("%")


def _statement_requests_plot(text: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9_])(plot|plot3)\s*\(", text))


@dataclass(frozen=True)
class CodeStatement:
    text: str
    start_line: int
    end_line: int


def split_code_statements_with_lines(block: str, *, preserve_newlines: bool = True) -> list[CodeStatement]:
    statements: list[CodeStatement] = []
    current_lines: list[str] = []
    current_flat: list[str] = []
    current_start_line: int | None = None
    current_end_line: int | None = None
    depth = 0

    def flush() -> None:
        nonlocal current_lines, current_flat, current_start_line, current_end_line, depth
        if current_start_line is None or current_end_line is None:
            current_lines = []
            current_flat = []
            depth = 0
            return
        text = "\n".join(current_lines).strip() if preserve_newlines else " ".join(current_flat).strip()
        if text:
            statements.append(CodeStatement(text=text, start_line=current_start_line, end_line=current_end_line))
        current_lines = []
        current_flat = []
        current_start_line = None
        current_end_line = None
        depth = 0

    for line_number, raw_line in enumerate(block.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            if current_start_line is not None and depth > 0:
                current_lines.append("")
                current_end_line = line_number
            elif current_start_line is not None and depth <= 0:
                flush()
            continue

        if current_start_line is None:
            current_start_line = line_number
        current_end_line = line_number
        current_lines.append(raw_line.rstrip())
        current_flat.append(stripped)
        depth += _delimiter_balance_delta(stripped)

        if depth <= 0:
            flush()

    flush()
    return statements


def split_code_statements(block: str) -> list[str]:
    """
    Split a code block into executable statements, allowing
    multiline expressions while delimiters remain open.
    """
    return [statement.text for statement in split_code_statements_with_lines(block, preserve_newlines=False)]


# Backward-compatible alias for internal callers that still import the old name.
_split_code_statements = split_code_statements


@dataclass(frozen=True)
class _TrackedTexSegment:
    text: str
    source_start_line: int | None
    source_end_line: int | None
    kind: str


@dataclass(frozen=True)
class _SourceChunk:
    text: str
    start_line: int
    inside_code: bool


def _iter_source_chunks(text: str):
    position = 0
    current_line = 1
    inside_code = False

    for match in CODEBLOCK_SPLIT_RE.finditer(text):
        chunk = text[position:match.start()]
        yield _SourceChunk(text=chunk, start_line=current_line, inside_code=inside_code)
        current_line += chunk.count("\n")
        current_line += match.group(0).count("\n")
        position = match.end()
        inside_code = not inside_code

    tail = text[position:]
    yield _SourceChunk(text=tail, start_line=current_line, inside_code=inside_code)


def _append_literal_segments(segments: list[_TrackedTexSegment], text: str, start_line: int) -> None:
    if not text:
        return
    current_line = start_line
    for line_text in text.splitlines(keepends=True):
        segments.append(
            _TrackedTexSegment(
                text=line_text,
                source_start_line=current_line,
                source_end_line=current_line,
                kind="source_line",
            )
        )
        current_line += 1


def _transform_segments_with_runtime_placeholders(
    segments: list[_TrackedTexSegment],
    contexto=None,
) -> tuple[list[_TrackedTexSegment], bool]:
    transformed: list[_TrackedTexSegment] = []
    missing_table = False

    for segment in segments:
        text = reemplazar_exprs(segment.text, contexto)
        text = reemplazar_vars(text, contexto)
        text = reemplazar_plots(text, contexto)
        text, segment_missing_table = reemplazar_tablas(text, contexto)
        missing_table = missing_table or segment_missing_table
        transformed.append(
            _TrackedTexSegment(
                text=text,
                source_start_line=segment.source_start_line,
                source_end_line=segment.source_end_line,
                kind=segment.kind,
            )
        )

    return transformed, missing_table


def _insert_required_package_segments(
    segments: list[_TrackedTexSegment],
    required_packages,
) -> list[_TrackedTexSegment]:
    marker = r"\begin{document}"
    marker_index = -1
    preamble_text = ""
    for index, segment in enumerate(segments):
        if marker in segment.text:
            marker_index = index
            break
        preamble_text += segment.text

    if marker_index < 0:
        return segments

    missing_directives: list[str] = []
    for pkg_name, directive in required_packages:
        pattern = rf"\\usepackage(?:\[[^\]]*\])?\{{{re.escape(pkg_name)}\}}"
        if re.search(pattern, preamble_text):
            continue
        missing_directives.append(directive)

    if not missing_directives:
        return segments

    insertion_text = ("\n" if preamble_text and not preamble_text.endswith("\n") else "") + "\n".join(missing_directives) + "\n"
    insertion_segment = _TrackedTexSegment(
        text=insertion_text,
        source_start_line=None,
        source_end_line=None,
        kind="generated_preamble",
    )
    return segments[:marker_index] + [insertion_segment] + segments[marker_index:]


def _build_trace_spans(segments: list[_TrackedTexSegment]) -> list[TraceMappingSpan]:
    spans: list[TraceMappingSpan] = []
    tex_line = 1

    for segment in segments:
        line_count = len(segment.text.splitlines()) if segment.text else 0
        if line_count <= 0:
            continue
        next_span = TraceMappingSpan(
            source_start_line=segment.source_start_line,
            source_end_line=segment.source_end_line,
            tex_start_line=tex_line,
            tex_end_line=tex_line + line_count - 1,
            kind=segment.kind,
        )
        if (
            spans
            and spans[-1].source_start_line == next_span.source_start_line
            and spans[-1].source_end_line == next_span.source_end_line
            and spans[-1].kind == next_span.kind
            and spans[-1].tex_end_line + 1 == next_span.tex_start_line
        ):
            previous = spans[-1]
            spans[-1] = TraceMappingSpan(
                source_start_line=previous.source_start_line,
                source_end_line=previous.source_end_line,
                tex_start_line=previous.tex_start_line,
                tex_end_line=next_span.tex_end_line,
                kind=previous.kind,
            )
        else:
            spans.append(next_span)
        tex_line += line_count

    return spans


def _render_traced_mtex_document(
    contenido: str,
    contexto,
    *,
    source_path: Path,
    tex_path: Path,
    pdf_path: Path,
    synctex_path: Path,
    synctex_enabled: bool,
) -> tuple[str, MtexTraceArtifact]:
    segments: list[_TrackedTexSegment] = []

    for chunk in _iter_source_chunks(contenido):
        if not chunk.inside_code:
            _append_literal_segments(segments, chunk.text, chunk.start_line)
            continue

        statements = split_code_statements_with_lines(chunk.text)
        resultado_final = None
        resultado_final_span: tuple[int, int] | None = None
        plot_generado = False

        for statement in statements:
            linea = statement.text.strip()
            if not linea or _statement_is_comment_only(linea):
                continue
            global_start_line = chunk.start_line + statement.start_line - 1
            global_end_line = chunk.start_line + statement.end_line - 1
            try:
                with diagnostic_line_offset(global_start_line - 1):
                    resultado = ejecutar_linea(statement.text)
                resultado_final = resultado
                resultado_final_span = (global_start_line, global_end_line)
                if _statement_requests_plot(statement.text):
                    plot_generado = True
            except Exception as e:
                diag = runtime_error_from_exception(e, source=statement.text, line=global_start_line)
                segments.append(
                    _TrackedTexSegment(
                        text=_latex_message(render_diagnostic(diag)),
                        source_start_line=global_start_line,
                        source_end_line=global_end_line,
                        kind="runtime_diagnostic",
                    )
                )

        if resultado_final is not None and not plot_generado and resultado_final_span is not None:
            segments.append(
                _TrackedTexSegment(
                    text=expr_to_latex(resultado_final),
                    source_start_line=resultado_final_span[0],
                    source_end_line=resultado_final_span[1],
                    kind="code_result",
                )
            )

    segments, missing_table = _transform_segments_with_runtime_placeholders(segments, contexto)
    needs_xcolor = missing_table or any(r"\textcolor{" in segment.text for segment in segments)
    required_packages = _build_required_packages(contexto, include_xcolor=needs_xcolor)
    segments = _insert_required_package_segments(segments, required_packages)
    salida_tex = "".join(segment.text for segment in segments)
    trace_artifact = MtexTraceArtifact(
        version=TRACE_ARTIFACT_VERSION,
        source_path=source_path,
        tex_path=tex_path,
        pdf_path=pdf_path,
        synctex_path=synctex_path,
        synctex_enabled=synctex_enabled,
        spans=_build_trace_spans(segments),
    )
    return salida_tex, trace_artifact


# ============================================================
# === EJECUTOR PRINCIPAL DE ARCHIVOS .MTEX ===================
# ============================================================

def ejecutar_mtex(
    path,
    contexto,
    abrir_pdf=True,
    build_dir: str | Path | None = None,
    output_basename: str | None = None,
):
    """
    Read an .mtex file, execute MathTeX blocks,
    replace variables, and generate a .tex file and PDF.
    """
    if not str(path).lower().endswith(".mtex"):
        print("Warning: ejecutar_mtex is intended for .mtex documents (LaTeX+MathTeX).")
    reset_environment(contexto)
    previous_plot_mode = get_plot_mode()
    previous_plot_output_dir = get_document_output_dir()
    set_plot_mode("document")

    source_path = Path(path).expanduser().resolve()
    source_dir = source_path.parent
    output_dir_path = Path(build_dir).expanduser().resolve() if build_dir is not None else source_dir
    output_dir_path.mkdir(parents=True, exist_ok=True)
    output_stem = output_basename or source_path.stem
    tex_path = output_dir_path / f"{output_stem}.tex"
    pdf_path = output_dir_path / f"{output_stem}.pdf"
    trace_path = output_dir_path / f"{output_stem}.mtextrace.json"
    synctex_path = output_dir_path / f"{output_stem}.synctex.gz"
    log_path = output_dir_path / f"{output_stem}.log"
    compile_log_path = output_dir_path / "compile.log"
    try:
        tex_target = os.path.relpath(tex_path, start=source_dir)
    except ValueError:
        tex_target = str(tex_path)
    set_document_output_dir(output_dir_path)
    if contexto is not None:
        contexto["_document_output_dir"] = str(output_dir_path)

    with open(source_path, "r", encoding="utf-8") as f:
        contenido = f.read()
    likely_multipass = _tex_likely_needs_multipass(contenido)
    salida_tex, trace_artifact = _render_traced_mtex_document(
        contenido,
        contexto,
        source_path=source_path,
        tex_path=tex_path,
        pdf_path=pdf_path,
        synctex_path=synctex_path,
        synctex_enabled=True,
    )
    compile_log_fallback = None

    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(salida_tex)

    print(f"LaTeX file generated: {tex_path}")

    pdf_generado = None
    previous_pdf_bytes = None
    if pdf_path.exists():
        try:
            previous_pdf_bytes = pdf_path.read_bytes()
        except Exception:
            previous_pdf_bytes = None
    try:
        final_run = None
        if likely_multipass:
            draft_pass = _run_pdflatex(
                tex_target,
                str(source_dir),
                draftmode=True,
                output_dir=str(output_dir_path),
                synctex=True,
            )
            if draft_pass.returncode != 0:
                final_run = draft_pass
            else:
                normal_pass = _run_pdflatex(
                    tex_target,
                    str(source_dir),
                    draftmode=False,
                    output_dir=str(output_dir_path),
                    synctex=True,
                )
                final_run = normal_pass
                if normal_pass.returncode == 0 and _log_requests_rerun(str(log_path)):
                    final_run = _run_pdflatex(
                        tex_target,
                        str(source_dir),
                        draftmode=False,
                        output_dir=str(output_dir_path),
                        synctex=True,
                    )
        else:
            normal_pass = _run_pdflatex(
                tex_target,
                str(source_dir),
                draftmode=False,
                output_dir=str(output_dir_path),
                synctex=True,
            )
            final_run = normal_pass
            if normal_pass.returncode == 0 and _log_requests_rerun(str(log_path)):
                final_run = _run_pdflatex(
                    tex_target,
                    str(source_dir),
                    draftmode=False,
                    output_dir=str(output_dir_path),
                    synctex=True,
                )

        if final_run is not None and final_run.returncode == 0 and pdf_path.exists():
            print("PDF compiled successfully.")
            pdf_generado = str(pdf_path)
            trace_artifact = MtexTraceArtifact(
                version=trace_artifact.version,
                source_path=trace_artifact.source_path,
                tex_path=trace_artifact.tex_path,
                pdf_path=trace_artifact.pdf_path,
                synctex_path=trace_artifact.synctex_path,
                synctex_enabled=synctex_path.exists(),
                spans=trace_artifact.spans,
            )
            write_trace_artifact(trace_path, trace_artifact)
            logger.debug(
                "Forward sync trace written to %s with %s span(s). SyncTeX available: %s",
                trace_path,
                len(trace_artifact.spans),
                trace_artifact.synctex_enabled,
            )

            if abrir_pdf:
                system_name = platform.system()
                if system_name == "Windows":
                    os.startfile(str(pdf_path))
                elif system_name == "Darwin":
                    subprocess.run(["open", str(pdf_path)])
                else:
                    subprocess.run(["xdg-open", str(pdf_path)])
        else:
            compile_log_fallback = "LaTeX compilation failed.\n"
            if final_run is None:
                compile_log_fallback += "The compiler did not produce a result.\n"
            elif not pdf_path.exists():
                compile_log_fallback += "The compiler finished without producing a PDF.\n"
            build_diag = make_build_diagnostic(
                "latex-compilation-failed",
                "LaTeX compilation failed.",
                source=_extract_latex_error_summary(log_path),
                hint=f"Check {compile_log_path.name} for the full compiler output.",
            )
            print(render_diagnostic(build_diag))
            if previous_pdf_bytes is not None:
                try:
                    pdf_path.write_bytes(previous_pdf_bytes)
                except Exception:
                    pass

    except Exception as e:
        compile_log_fallback = f"Error while compiling PDF: {e}\n"
        build_diag = make_build_diagnostic(
            "latex-compilation-exception",
            f"Error while compiling PDF: {e}",
            hint="Check the compiler installation and project paths.",
        )
        print(render_diagnostic(build_diag))
        if previous_pdf_bytes is not None:
            try:
                pdf_path.write_bytes(previous_pdf_bytes)
            except Exception:
                pass

    finally:
        set_plot_mode(previous_plot_mode or "interactive")
        set_document_output_dir(previous_plot_output_dir)
        _write_compile_log(log_path, compile_log_path, fallback_text=compile_log_fallback)

        plot_files = []
        if contexto:
            plot_files.extend(contexto.get("plots", []))
            extra = contexto.get("_plot_files", {})
            plot_files.extend(extra.values())
            contexto["plots"] = []
            if "_plot_files" in contexto:
                contexto["_plot_files"].clear()
            contexto.pop("_document_output_dir", None)

    return pdf_generado

