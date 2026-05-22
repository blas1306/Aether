from __future__ import annotations

from pathlib import Path

import pytest

pytest.skip("MTeX build-status workflow retired from active Aether Studio surface.", allow_module_level=True)

from qt_app import MathTeXQtWindow
from project_system import ProjectManager


@pytest.fixture()
def studio_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    window = MathTeXQtWindow()
    manager = ProjectManager()
    project = manager.create_project("StatusPreferencesProject", tmp_path)
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


def test_auto_compile_preference_is_restored_across_window_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qapp,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    first_window = MathTeXQtWindow()
    try:
        assert first_window.auto_compile_checkbox is not None
        first_window.auto_compile_checkbox.setChecked(True)
        qapp.processEvents()

        assert first_window.preferences_store.storage_path.exists()
        first_window._reset_auto_compile_runtime()
        first_window.close()
        qapp.processEvents()

        second_window = MathTeXQtWindow()
        try:
            assert second_window.auto_compile_checkbox is not None
            assert second_window.auto_compile_checkbox.isChecked() is True
            assert second_window.auto_compile_controller.enabled is True
        finally:
            second_window._reset_auto_compile_runtime()
            second_window.close()
            qapp.processEvents()
    finally:
        first_window._reset_auto_compile_runtime()
        first_window.close()
        qapp.processEvents()


def test_build_status_is_visible_during_manual_build_and_finishes_in_success(
    studio_window: MathTeXQtWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert studio_window.current_mtex_path is not None
    assert studio_window.build_status_label is not None

    source_path = studio_window.current_mtex_path
    artifacts = studio_window._build_artifacts_for_source(source_path)
    observed_statuses: list[str] = []
    monkeypatch.setattr(studio_window.preview, "load_pdf", lambda pdf_path, preserve_state=True: True)

    def _fake_execute(path, contexto, abrir_pdf=False, build_dir=None, output_basename=None):
        del contexto, abrir_pdf
        observed_statuses.append(studio_window.build_status_label.text())
        pdf_path = _write_fake_build_outputs(
            Path(build_dir),
            Path(path),
            compile_log_text="manual success\n",
            pdf_bytes=b"%PDF-1.4\n%manual\n",
            output_basename=output_basename,
        )
        return str(pdf_path)

    monkeypatch.setattr("qt_app.ejecutar_mtex", _fake_execute)

    studio_window._run_mtex_compilation(source_path, trigger="manual")

    assert observed_statuses == ["Build: Manual build in progress..."]
    assert studio_window.build_status_label.text() == "Build: Manual build succeeded"
