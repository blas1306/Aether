from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtGui

pytest.skip("MTeX PDF sync workflow retired from active Aether Studio surface.", allow_module_level=True)

from editor_pdf_sync import MtexTraceArtifact, TRACE_ARTIFACT_VERSION, TraceMappingSpan, write_trace_artifact
from project_system import ProjectManager
from qt_app import MathTeXQtWindow


@pytest.fixture()
def studio_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("EditorSyncProject", tmp_path)
    window._open_project(project)
    qapp.processEvents()
    yield window
    if window.mtex_editor is not None:
        window.mtex_editor.document().setModified(False)
    window._reset_auto_compile_runtime()
    window.current_project = None
    window.current_mtex_path = None
    window.close()
    qapp.processEvents()


def _move_cursor_to_line(window: MathTeXQtWindow, line_number: int, qapp) -> None:
    assert window.mtex_editor is not None
    cursor = window.mtex_editor.textCursor()
    cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
    cursor.movePosition(
        QtGui.QTextCursor.MoveOperation.Down,
        QtGui.QTextCursor.MoveMode.MoveAnchor,
        max(0, line_number - 1),
    )
    window.mtex_editor.setTextCursor(cursor)
    qapp.processEvents()


def test_editor_cursor_movement_does_not_trigger_automatic_pdf_sync(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    assert studio_window.current_mtex_path is not None
    assert studio_window.preview is not None

    source_path = studio_window.current_mtex_path
    source_path.write_text(
        "\\section{Intro}\n"
        "Intro line one.\n"
        "Intro line two.\n"
        "\\subsection{Details}\n"
        "Details line.\n"
        "\\section{Conclusion}\n"
        "Done.\n",
        encoding="utf-8",
    )

    artifacts = studio_window._build_artifacts_for_source(source_path)
    artifacts.build_dir.mkdir(parents=True, exist_ok=True)
    artifacts.pdf_path.write_bytes(b"%PDF-1.4\n%editor-sync\n")
    artifacts.toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {subsection}{\numberline {1.1}Details}{3}{subsection.1.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )

    jumps: list[int] = []
    monkeypatch.setattr(studio_window.preview, "current_pdf_path", lambda: artifacts.pdf_path)
    monkeypatch.setattr(studio_window.preview, "jump_to_page_index", lambda page_index: jumps.append(page_index) or True)

    studio_window._open_mtex_file(source_path)
    qapp.processEvents()

    for line_number in (2, 3, 5, 7):
        _move_cursor_to_line(studio_window, line_number, qapp)

    assert jumps == []


def test_go_to_code_location_in_pdf_uses_current_cursor_and_landmark_mapping(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    assert studio_window.current_mtex_path is not None
    assert studio_window.preview is not None

    source_path = studio_window.current_mtex_path
    source_path.write_text(
        "\\section{Intro}\n"
        "Intro line one.\n"
        "Intro line two.\n"
        "\\subsection{Details}\n"
        "Details line.\n"
        "\\section{Conclusion}\n"
        "Done.\n",
        encoding="utf-8",
    )

    artifacts = studio_window._build_artifacts_for_source(source_path)
    artifacts.build_dir.mkdir(parents=True, exist_ok=True)
    artifacts.pdf_path.write_bytes(b"%PDF-1.4\n%editor-sync\n")
    artifacts.toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {subsection}{\numberline {1.1}Details}{3}{subsection.1.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )

    jumps: list[int] = []
    monkeypatch.setattr(studio_window.preview, "current_pdf_path", lambda: artifacts.pdf_path)
    monkeypatch.setattr(studio_window.preview, "jump_to_page_index", lambda page_index: jumps.append(page_index) or True)

    studio_window._open_mtex_file(source_path)
    qapp.processEvents()

    _move_cursor_to_line(studio_window, 2, qapp)
    studio_window._go_to_code_location_in_pdf()

    _move_cursor_to_line(studio_window, 5, qapp)
    studio_window._go_to_code_location_in_pdf()

    _move_cursor_to_line(studio_window, 7, qapp)
    studio_window._go_to_code_location_in_pdf()

    assert jumps == [1, 2, 4]


def test_go_to_code_location_in_pdf_prefers_trace_and_synctex_when_available(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    assert studio_window.current_mtex_path is not None
    assert studio_window.preview is not None

    source_path = studio_window.current_mtex_path
    source_path.write_text(
        "\\section{Intro}\n"
        "First body line.\n"
        "Second body line.\n"
        "\\section{Conclusion}\n"
        "Done.\n",
        encoding="utf-8",
    )

    artifacts = studio_window._build_artifacts_for_source(source_path)
    artifacts.build_dir.mkdir(parents=True, exist_ok=True)
    artifacts.pdf_path.write_bytes(b"%PDF-1.4\n%editor-sync\n")
    artifacts.toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )
    artifacts.trace_path.parent.mkdir(parents=True, exist_ok=True)
    write_trace_artifact(
        artifacts.trace_path,
        MtexTraceArtifact(
            version=TRACE_ARTIFACT_VERSION,
            source_path=source_path,
            tex_path=artifacts.tex_path,
            pdf_path=artifacts.pdf_path,
            synctex_path=artifacts.synctex_path,
            synctex_enabled=True,
            spans=[
                TraceMappingSpan(source_start_line=2, source_end_line=2, tex_start_line=20, tex_end_line=20, kind="source_line"),
                TraceMappingSpan(source_start_line=3, source_end_line=3, tex_start_line=21, tex_end_line=21, kind="source_line"),
            ],
        ),
    )

    jumps: list[int] = []
    monkeypatch.setattr(studio_window.preview, "current_pdf_path", lambda: artifacts.pdf_path)
    monkeypatch.setattr(
        "editor_pdf_sync.query_synctex_forward",
        lambda **kwargs: [
            type(
                "Record",
                (),
                {
                    "page_index": 7 if kwargs["line_number"] == 20 else 8,
                    "x": 0.0,
                    "y": 0.0,
                    "h": 0.0,
                    "v": 0.0,
                    "width": 0.0,
                    "height": 0.0,
                    "output_path": artifacts.pdf_path,
                },
            )()
        ],
    )
    monkeypatch.setattr(studio_window.preview, "jump_to_page_index", lambda page_index: jumps.append(page_index) or True)

    studio_window._open_mtex_file(source_path)
    qapp.processEvents()

    _move_cursor_to_line(studio_window, 2, qapp)
    studio_window._go_to_code_location_in_pdf()

    _move_cursor_to_line(studio_window, 3, qapp)
    studio_window._go_to_code_location_in_pdf()

    assert jumps == [7, 8]


def test_go_to_pdf_location_in_code_moves_editor_to_nearest_mapped_heading(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    assert studio_window.current_mtex_path is not None
    assert studio_window.preview is not None
    assert studio_window.mtex_editor is not None

    source_path = studio_window.current_mtex_path
    source_path.write_text(
        "\\section{Intro}\n"
        "Intro line one.\n"
        "\\subsection{Details}\n"
        "Details line.\n"
        "\\section{Conclusion}\n"
        "Done.\n",
        encoding="utf-8",
    )

    artifacts = studio_window._build_artifacts_for_source(source_path)
    artifacts.build_dir.mkdir(parents=True, exist_ok=True)
    artifacts.pdf_path.write_bytes(b"%PDF-1.4\n%editor-sync\n")
    artifacts.toc_path.write_text(
        r"\contentsline {section}{\numberline {1}Intro}{2}{section.1}%" "\n"
        r"\contentsline {subsection}{\numberline {1.1}Details}{3}{subsection.1.1}%" "\n"
        r"\contentsline {section}{\numberline {2}Conclusion}{5}{section.2}%" "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(studio_window.preview, "current_pdf_path", lambda: artifacts.pdf_path)
    monkeypatch.setattr(studio_window.preview, "current_page_index", lambda: 3)

    studio_window._open_mtex_file(source_path)
    qapp.processEvents()

    _move_cursor_to_line(studio_window, 1, qapp)
    studio_window._go_to_pdf_location_in_code()

    assert studio_window.mtex_editor.textCursor().blockNumber() + 1 == 3
