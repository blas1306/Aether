from __future__ import annotations

from pathlib import Path

import pytest

pytest.skip("MTeX compile pipeline retired from active Aether Studio surface.", allow_module_level=True)

from qt_app import MathTeXQtWindow
from project_system import ProjectManager


@pytest.fixture()
def studio_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("CompilePipelineProject", tmp_path)
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


def test_manual_and_auto_compile_use_consistent_build_pipeline(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert studio_window.current_mtex_path is not None

    source_path = studio_window.current_mtex_path
    artifacts = studio_window._build_artifacts_for_source(source_path)
    preview_loads: list[tuple[Path, bool]] = []
    compiler_calls: list[tuple[Path, Path, bool]] = []

    monkeypatch.setattr(
        studio_window.preview,
        "load_pdf",
        lambda pdf_path, preserve_state=True: preview_loads.append((Path(pdf_path), preserve_state)) or True,
    )

    def _fake_execute(path, contexto, abrir_pdf=False, build_dir=None, output_basename=None):
        del contexto
        build_path = Path(build_dir)
        source = Path(path)
        compiler_calls.append((source, build_path, abrir_pdf))
        pdf_path = _write_fake_build_outputs(
            build_path,
            source,
            compile_log_text="consistent success\n",
            pdf_bytes=b"%PDF-1.4\n%consistent\n",
            output_basename=output_basename,
        )
        return str(pdf_path)

    monkeypatch.setattr("qt_app.ejecutar_mtex", _fake_execute)

    studio_window._run_mtex_compilation(source_path, trigger="manual")
    manual_result = studio_window.latest_mtex_execution_result
    manual_pdf = studio_window.last_generated_pdf

    studio_window._run_mtex_compilation(source_path, trigger="auto")
    auto_result = studio_window.latest_mtex_execution_result
    auto_pdf = studio_window.last_generated_pdf

    assert manual_result is not None
    assert auto_result is not None
    assert compiler_calls == [
        (source_path, artifacts.build_dir, False),
        (source_path, artifacts.build_dir, False),
    ]
    assert manual_result.success is True
    assert auto_result.success is True
    assert manual_result.build_dir == artifacts.build_dir == auto_result.build_dir
    assert manual_result.pdf_path == artifacts.pdf_path == auto_result.pdf_path
    assert manual_pdf == artifacts.pdf_path == auto_pdf
    assert [path.name for path in manual_result.output_files] == [path.name for path in auto_result.output_files]
    assert [path.name for path in auto_result.output_files] == [
        "compile.log",
        f"{artifacts.tex_path.stem}.log",
        f"{artifacts.pdf_path.stem}.pdf",
        f"{artifacts.tex_path.stem}.tex",
    ]
    assert any("Manual compile finished successfully." in entry.message for entry in manual_result.logs)
    assert any("Auto compile finished successfully." in entry.message for entry in auto_result.logs)
    assert studio_window.build_status_label is not None
    assert studio_window.build_status_label.text() == "Build: Auto build succeeded"
    assert preview_loads == [
        (artifacts.pdf_path, True),
        (artifacts.pdf_path, True),
    ]


def test_failed_build_preserves_previous_valid_pdf_across_multiple_attempts(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert studio_window.current_mtex_path is not None

    source_path = studio_window.current_mtex_path
    artifacts = studio_window._build_artifacts_for_source(source_path)
    previous_bytes = b"%PDF-1.4\n%stable\n"
    previous_pdf = _write_fake_build_outputs(
        artifacts.build_dir,
        source_path,
        compile_log_text="seed success\n",
        pdf_bytes=previous_bytes,
        output_basename=artifacts.tex_path.stem,
    )
    studio_window.last_generated_pdf = previous_pdf

    preview_messages: list[str] = []
    attempts: list[int] = []
    monkeypatch.setattr(studio_window.preview, "set_message", lambda text: preview_messages.append(text))

    def _fake_execute(path, contexto, abrir_pdf=False, build_dir=None, output_basename=None):
        del contexto, abrir_pdf
        attempt = len(attempts) + 1
        attempts.append(attempt)
        _write_fake_build_outputs(
            Path(build_dir),
            Path(path),
            compile_log_text=f"failure attempt {attempt}\n",
            output_basename=output_basename,
        )
        return None

    monkeypatch.setattr("qt_app.ejecutar_mtex", _fake_execute)

    studio_window._run_mtex_compilation(source_path, trigger="manual")
    first_result = studio_window.latest_mtex_execution_result
    studio_window._run_mtex_compilation(source_path, trigger="auto")
    second_result = studio_window.latest_mtex_execution_result

    assert attempts == [1, 2]
    assert first_result is not None
    assert second_result is not None
    assert first_result.success is False
    assert second_result.success is False
    assert first_result.pdf_path == previous_pdf
    assert second_result.pdf_path == previous_pdf
    assert studio_window.last_generated_pdf == previous_pdf
    assert previous_pdf.read_bytes() == previous_bytes
    assert any("Keeping last available PDF preview" in entry.message for entry in first_result.logs)
    assert any("Keeping last available PDF preview" in entry.message for entry in second_result.logs)
    assert (artifacts.build_dir / "compile.log").read_text(encoding="utf-8") == "failure attempt 2\n"
    assert preview_messages == []


def test_failed_build_adds_probable_cause_from_compile_log_to_logs_panel(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert studio_window.current_mtex_path is not None

    source_path = studio_window.current_mtex_path
    artifacts = studio_window._build_artifacts_for_source(source_path)

    def _fake_execute(path, contexto, abrir_pdf=False, build_dir=None, output_basename=None):
        del path, contexto, abrir_pdf
        build_path = Path(build_dir)
        build_path.mkdir(parents=True, exist_ok=True)
        stem = output_basename or artifacts.tex_path.stem
        (build_path / f"{stem}.tex").write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\[\n"
            "\\left[\\begin{matrix}1 & 2\\\\3 & 4\\end{matrix}\\right]\n"
            "\\]\n"
            "\\end{document}\n",
            encoding="utf-8",
        )
        log_text = (
            "! Misplaced alignment tab character &.\n"
            "l.19 \\left[\\begin{matrix}1 &\n"
            " 2\\\\3 & 4\\end{matrix}\\right]\n"
        )
        (build_path / f"{stem}.log").write_text(log_text, encoding="utf-8")
        (build_path / "compile.log").write_text(log_text, encoding="utf-8")
        return None

    monkeypatch.setattr("qt_app.ejecutar_mtex", _fake_execute)

    studio_window._run_mtex_compilation(source_path, trigger="manual")
    result = studio_window.latest_mtex_execution_result

    assert result is not None
    assert result.success is False
    assert any(
        entry.source == "latex" and "Misplaced alignment tab character &." in entry.message
        for entry in result.logs
    )
    assert any(
        entry.source == "latex" and "amsmath" in entry.message
        for entry in result.logs
    )


def test_successful_build_after_failure_replaces_previous_valid_pdf_cleanly(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert studio_window.current_mtex_path is not None

    source_path = studio_window.current_mtex_path
    artifacts = studio_window._build_artifacts_for_source(source_path)
    preview_loads: list[Path] = []
    attempts: list[int] = []

    monkeypatch.setattr(
        studio_window.preview,
        "load_pdf",
        lambda pdf_path, preserve_state=True: preview_loads.append(Path(pdf_path)) or True,
    )

    def _fake_execute(path, contexto, abrir_pdf=False, build_dir=None, output_basename=None):
        del contexto, abrir_pdf
        attempt = len(attempts) + 1
        attempts.append(attempt)
        if attempt == 1:
            pdf_path = _write_fake_build_outputs(
                Path(build_dir),
                Path(path),
                compile_log_text="success 1\n",
                pdf_bytes=b"%PDF-1.4\n%v1\n",
                output_basename=output_basename,
            )
            return str(pdf_path)
        if attempt == 2:
            _write_fake_build_outputs(
                Path(build_dir),
                Path(path),
                compile_log_text="failure 2\n",
                output_basename=output_basename,
            )
            return None
        pdf_path = _write_fake_build_outputs(
            Path(build_dir),
            Path(path),
            compile_log_text="success 3\n",
            pdf_bytes=b"%PDF-1.4\n%v2\n",
            output_basename=output_basename,
        )
        return str(pdf_path)

    monkeypatch.setattr("qt_app.ejecutar_mtex", _fake_execute)

    studio_window._run_mtex_compilation(source_path, trigger="manual")
    studio_window._run_mtex_compilation(source_path, trigger="auto")
    studio_window._run_mtex_compilation(source_path, trigger="manual")
    final_result = studio_window.latest_mtex_execution_result

    assert attempts == [1, 2, 3]
    assert final_result is not None
    assert final_result.success is True
    assert final_result.pdf_path == artifacts.pdf_path
    assert studio_window.last_generated_pdf == artifacts.pdf_path
    assert artifacts.pdf_path.read_bytes() == b"%PDF-1.4\n%v2\n"
    assert (artifacts.build_dir / "compile.log").read_text(encoding="utf-8") == "success 3\n"
    assert all("failed or did not produce a new PDF" not in entry.message for entry in final_result.logs)
    assert all("Keeping last available PDF preview" not in entry.message for entry in final_result.logs)
    assert preview_loads == [artifacts.pdf_path, artifacts.pdf_path]


def test_build_outputs_do_not_leak_between_projects(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert studio_window.current_project is not None

    project_a = studio_window.current_project
    project_b = ProjectManager().create_project("SecondBuildProject", tmp_path)
    artifacts_a = studio_window.output_manager.artifacts_for_source(
        project_a.main_path,
        project_root=project_a.path,
        output_basename=project_a.name,
    )
    artifacts_b = studio_window.output_manager.artifacts_for_source(
        project_b.main_path,
        project_root=project_b.path,
        output_basename=project_b.name,
    )

    monkeypatch.setattr(studio_window.preview, "load_pdf", lambda pdf_path, preserve_state=True: True)

    def _fake_execute(path, contexto, abrir_pdf=False, build_dir=None, output_basename=None):
        del contexto, abrir_pdf
        source = Path(path)
        project_marker = source.parent.name.encode("utf-8")
        pdf_path = _write_fake_build_outputs(
            Path(build_dir),
            source,
            compile_log_text=f"log for {source.parent.name}\n",
            pdf_bytes=b"%PDF-1.4\n%" + project_marker + b"\n",
            output_basename=output_basename,
        )
        return str(pdf_path)

    monkeypatch.setattr("qt_app.ejecutar_mtex", _fake_execute)

    studio_window._compile_current_mtex()
    first_result = studio_window.latest_mtex_execution_result

    studio_window._open_project(project_b)
    assert studio_window.latest_mtex_execution_result is None
    assert studio_window.last_generated_pdf is None

    studio_window._compile_current_mtex()
    second_result = studio_window.latest_mtex_execution_result

    assert first_result is not None
    assert second_result is not None
    assert first_result.build_dir == artifacts_a.build_dir
    assert second_result.build_dir == artifacts_b.build_dir
    assert first_result.pdf_path == artifacts_a.pdf_path
    assert second_result.pdf_path == artifacts_b.pdf_path
    assert studio_window.last_generated_pdf == artifacts_b.pdf_path
    assert all(path.is_relative_to(artifacts_b.build_dir) for path in second_result.output_files)
    assert all(str(artifacts_a.build_dir) not in entry.message for entry in second_result.logs)
    assert (artifacts_a.build_dir / "compile.log").read_text(encoding="utf-8") == f"log for {project_a.name}\n"
    assert (artifacts_b.build_dir / "compile.log").read_text(encoding="utf-8") == f"log for {project_b.name}\n"
    assert artifacts_a.pdf_path.read_bytes() != artifacts_b.pdf_path.read_bytes()


def test_auto_compile_pending_build_runs_once_after_current_build_finishes(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkbox = studio_window.auto_compile_checkbox
    triggers: list[str] = []
    state = {"active": 0, "max_active": 0}

    assert checkbox is not None
    checkbox.setChecked(True)

    def _fake_run(path, trigger="manual"):
        del path
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        try:
            triggers.append(trigger)
            if len(triggers) == 1:
                studio_window.schedule_auto_build()
                studio_window.trigger_auto_build()
                studio_window.schedule_auto_build()
                studio_window.trigger_auto_build()
                studio_window.schedule_auto_build()
                studio_window.trigger_auto_build()
        finally:
            state["active"] -= 1

    monkeypatch.setattr(studio_window, "_run_mtex_compilation", _fake_run)

    studio_window._compile_current_mtex()

    assert triggers == ["manual", "auto"]
    assert state["max_active"] == 1
    assert studio_window.auto_compile_controller.build_in_progress is False
    assert studio_window.auto_compile_controller.pending_trigger is None


def test_manual_compile_during_pending_auto_compile_behaves_consistently(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkbox = studio_window.auto_compile_checkbox
    triggers: list[str] = []

    assert checkbox is not None
    checkbox.setChecked(True)

    def _fake_run(path, trigger="manual"):
        del path
        triggers.append(trigger)
        if len(triggers) == 1:
            studio_window.schedule_auto_build()
            studio_window.trigger_auto_build()
            studio_window._compile_current_mtex()

    monkeypatch.setattr(studio_window, "_run_mtex_compilation", _fake_run)

    studio_window._request_current_mtex_compile("auto")

    assert triggers == ["auto", "manual"]
    assert studio_window._auto_compile_timer.isActive() is False
    assert studio_window.auto_compile_controller.build_in_progress is False
    assert studio_window.auto_compile_controller.pending_trigger is None
