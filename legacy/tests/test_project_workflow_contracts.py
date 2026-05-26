from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_system import ProjectManager, ProjectRegistry


def test_open_project_rejects_invalid_metadata_cleanly(tmp_path: Path):
    project_dir = tmp_path / "BrokenProject"
    project_dir.mkdir()
    (project_dir / "main.mtex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (project_dir / ".mtexproj").write_text("{ invalid json", encoding="utf-8")

    manager = ProjectManager()

    with pytest.raises(ValueError, match="Invalid project metadata"):
        manager.open_project(project_dir)


def test_project_registry_deduplicates_recent_entries(tmp_path: Path):
    manager = ProjectManager()
    registry = ProjectRegistry(tmp_path / "recent_projects.json")
    project = manager.create_project("SampleProject", tmp_path)

    registry.add_project(project)
    registry.add_project(project)
    registry.save()

    payload = json.loads((tmp_path / "recent_projects.json").read_text(encoding="utf-8"))
    assert len(payload["projects"]) == 1

    reloaded = ProjectRegistry(tmp_path / "recent_projects.json")
    reloaded.load()
    projects = reloaded.list_projects()

    assert len(projects) == 1
    assert projects[0].path == Path(project.path)
