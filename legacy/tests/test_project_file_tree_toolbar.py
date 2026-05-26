from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets  # type: ignore

from notebook_file import load_notebook_file
from project_system import ProjectManager
from project_widgets import ProjectWorkspaceWidget


def _build_workspace_widget(project_manager: ProjectManager) -> ProjectWorkspaceWidget:
    return ProjectWorkspaceWidget(
        editor_factory=QtWidgets.QPlainTextEdit,
        preview_factory=QtWidgets.QLabel,
        preview_message="Preview",
        project_manager=project_manager,
    )


def test_new_file_in_selected_folder_emits_open_for_mtex(tmp_path: Path, monkeypatch, qapp) -> None:
    manager = ProjectManager()
    project = manager.create_project("ToolbarProject", tmp_path)
    figures_dir = project.path / "figures"
    figures_dir.mkdir()
    widget = _build_workspace_widget(manager)
    opened_paths: list[str] = []
    widget.file_open_requested.connect(opened_paths.append)

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("plot_notes.mtex", True)),
    )

    try:
        widget.set_project(project)
        widget._select_tree_path(figures_dir)

        widget.new_file_btn.click()
        qapp.processEvents()

        created_path = figures_dir / "plot_notes.mtex"
        assert created_path.exists()
        assert opened_paths == [str(created_path)]
        assert widget.file_tree.currentItem() is not None
        assert widget.file_tree.currentItem().text(0) == "plot_notes.mtex"
    finally:
        widget.close()
        qapp.processEvents()


def test_new_file_in_root_emits_open_for_mtx(tmp_path: Path, monkeypatch, qapp) -> None:
    manager = ProjectManager()
    project = manager.create_project("ToolbarScriptProject", tmp_path)
    widget = _build_workspace_widget(manager)
    opened_paths: list[str] = []
    widget.file_open_requested.connect(opened_paths.append)

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("solver.mtx", True)),
    )

    try:
        widget.set_project(project)

        widget.new_file_btn.click()
        qapp.processEvents()

        created_path = project.path / "solver.mtx"
        assert created_path.exists()
        assert opened_paths == [str(created_path)]
    finally:
        widget.close()
        qapp.processEvents()


def test_new_file_in_root_emits_open_for_aether(tmp_path: Path, monkeypatch, qapp) -> None:
    manager = ProjectManager()
    project = manager.create_project("ToolbarAetherProject", tmp_path)
    widget = _build_workspace_widget(manager)
    opened_paths: list[str] = []
    widget.file_open_requested.connect(opened_paths.append)

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("experiment.ae", True)),
    )

    try:
        widget.set_project(project)

        widget.new_file_btn.click()
        qapp.processEvents()

        created_path = project.path / "experiment.ae"
        assert created_path.exists()
        assert opened_paths == [str(created_path)]
    finally:
        widget.close()
        qapp.processEvents()


def test_new_notebook_file_initializes_mtn_and_emits_open(tmp_path: Path, monkeypatch, qapp) -> None:
    manager = ProjectManager()
    project = manager.create_project("NotebookFileProject", tmp_path)
    widget = _build_workspace_widget(manager)
    opened_paths: list[str] = []
    widget.file_open_requested.connect(opened_paths.append)

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        staticmethod(lambda *args, **kwargs: ("analysis.mtn", True)),
    )

    try:
        widget.set_project(project)

        widget.new_file_btn.click()
        qapp.processEvents()

        created_path = project.path / "analysis.mtn"
        assert load_notebook_file(created_path).path == created_path
        assert opened_paths == [str(created_path)]
    finally:
        widget.close()
        qapp.processEvents()


def test_upload_skips_existing_files_and_copies_new_ones(tmp_path: Path, monkeypatch, qapp) -> None:
    manager = ProjectManager()
    project = manager.create_project("UploadWidgetProject", tmp_path)
    assets_dir = project.path / "assets"
    assets_dir.mkdir()
    existing_target = assets_dir / "logo.png"
    existing_target.write_text("old-logo", encoding="utf-8")

    external_dir = tmp_path / "external_assets"
    external_dir.mkdir()
    duplicate_source = external_dir / "logo.png"
    duplicate_source.write_text("new-logo", encoding="utf-8")
    new_source = external_dir / "diagram.png"
    new_source.write_text("diagram", encoding="utf-8")

    warnings: list[str] = []

    def fake_warning(*args, **kwargs):
        if len(args) >= 3:
            warnings.append(str(args[2]))
        elif "text" in kwargs:
            warnings.append(str(kwargs["text"]))
        return QtWidgets.QMessageBox.StandardButton.Ok

    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *args, **kwargs: ([str(duplicate_source), str(new_source)], "All Files (*)")),
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", fake_warning)

    widget = _build_workspace_widget(manager)
    try:
        widget.set_project(project)
        widget._select_tree_path(assets_dir)

        widget.upload_btn.click()
        qapp.processEvents()

        assert existing_target.read_text(encoding="utf-8") == "old-logo"
        assert (assets_dir / "diagram.png").read_text(encoding="utf-8") == "diagram"
        assert warnings
        assert "logo.png" in warnings[-1]
    finally:
        widget.close()
        qapp.processEvents()
