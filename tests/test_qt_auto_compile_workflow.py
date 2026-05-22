from __future__ import annotations

from pathlib import Path

import pytest

pytest.skip("MTeX auto-compile workflow retired from active Aether Studio surface.", allow_module_level=True)

from qt_app import MathTeXQtWindow
from project_system import ProjectManager


@pytest.fixture()
def studio_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("AutoCompileProject", tmp_path)
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


def _write_fake_build_outputs(
    build_dir: Path,
    source_path: Path,
    *,
    compile_log_text: str,
    pdf_bytes: bytes | None = None,
    output_basename: str | None = None,
) -> Path:
    build_dir.mkdir(parents=True, exist_ok=True)
    stem = output_basename or source_path.stem
    (build_dir / f"{stem}.tex").write_text(f"% generated from {source_path.name}\n", encoding="utf-8")
    (build_dir / f"{stem}.log").write_text(compile_log_text, encoding="utf-8")
    (build_dir / "compile.log").write_text(compile_log_text, encoding="utf-8")
    pdf_path = build_dir / f"{stem}.pdf"
    if pdf_bytes is not None:
        pdf_path.write_bytes(pdf_bytes)
    return pdf_path


def test_auto_compile_checkbox_is_visible_and_off_by_default(studio_window: MathTeXQtWindow) -> None:
    checkbox = studio_window.auto_compile_checkbox

    assert checkbox is not None
    assert checkbox.text() == "Auto compile"
    assert checkbox.isChecked() is False
    assert studio_window.build_status_label is not None
    assert studio_window.build_status_label.text() == "Build: Ready"


def test_auto_compile_on_schedules_qt_debounce_for_active_document(
    studio_window: MathTeXQtWindow,
    qapp,
) -> None:
    checkbox = studio_window.auto_compile_checkbox
    editor = studio_window.mtex_editor

    assert checkbox is not None
    assert editor is not None

    checkbox.setChecked(True)
    editor.insertPlainText("\n% auto compile test")
    qapp.processEvents()

    assert studio_window._auto_compile_timer.isActive() is True


def test_manual_compile_flow_still_runs_when_auto_compile_is_off(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    triggers: list[str] = []
    checkbox = studio_window.auto_compile_checkbox

    assert checkbox is not None
    checkbox.setChecked(False)

    monkeypatch.setattr(
        studio_window,
        "_run_mtex_compilation",
        lambda path, trigger="manual": triggers.append(trigger),
    )

    studio_window._compile_current_mtex()

    assert triggers == ["manual"]
    assert studio_window._auto_compile_timer.isActive() is False


def test_pending_auto_build_runs_after_current_build_finishes(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    triggers: list[str] = []
    checkbox = studio_window.auto_compile_checkbox

    assert checkbox is not None
    checkbox.setChecked(True)

    def _fake_run(path, trigger="manual"):
        triggers.append(trigger)
        if len(triggers) == 1:
            studio_window.schedule_auto_build()
            studio_window.trigger_auto_build()

    monkeypatch.setattr(studio_window, "_run_mtex_compilation", _fake_run)

    studio_window._compile_current_mtex()

    assert triggers == ["manual", "auto"]


def test_failed_build_keeps_last_valid_pdf_in_preview_result(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert studio_window.current_mtex_path is not None

    artifacts = studio_window._build_artifacts_for_source(studio_window.current_mtex_path)
    artifacts.build_dir.mkdir(parents=True, exist_ok=True)
    previous_pdf = artifacts.pdf_path
    previous_pdf.write_bytes(b"%PDF-1.4\n%previous\n")
    studio_window.last_generated_pdf = previous_pdf

    messages: list[str] = []
    monkeypatch.setattr(studio_window.preview, "set_message", lambda text: messages.append(text))
    monkeypatch.setattr("qt_app.ejecutar_mtex", lambda *args, **kwargs: None)

    studio_window._run_mtex_compilation(studio_window.current_mtex_path, trigger="auto")

    assert studio_window.last_generated_pdf == previous_pdf
    assert studio_window.latest_mtex_execution_result is not None
    assert studio_window.latest_mtex_execution_result.success is False
    assert studio_window.latest_mtex_execution_result.pdf_path == previous_pdf
    assert studio_window.build_status_label is not None
    assert studio_window.build_status_label.text() == "Build: Auto build failed, showing last valid PDF"
    assert messages == []
