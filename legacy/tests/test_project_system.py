from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

import project_system
from project_outputs import BUILD_DIRNAME
from project_system import DEFAULT_MAIN_FILE, ProjectManager, ProjectRegistry


TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "tmp_test_projects"


class ProjectManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TMP_ROOT / f"case_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.manager = ProjectManager()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_project_generates_expected_structure(self) -> None:
        project = self.manager.create_project("SampleProject", self.root)
        expected_main = (
            "\\documentclass{article}\n"
            "\\usepackage{graphicx} % Required for inserting images\n"
            "\\usepackage{amsmath}\n"
            "\\usepackage{amsthm}\n"
            "\\usepackage{amssymb}\n"
            "\\usepackage{float}\n\n"
            "\\title{SampleProject}\n"
            "\\date{\\today}\n\n"
            "\\begin{document}\n\n"
            "\\maketitle\n\n"
            "\\section{Introduction}\n\n"
            "\\end{document}\n"
        )

        self.assertEqual(project.name, "SampleProject")
        self.assertTrue((project.path / ".mtexproj").exists())
        self.assertTrue((project.path / BUILD_DIRNAME).is_dir())
        self.assertTrue(project.main_path.exists())
        self.assertEqual(project.main_path.read_text(encoding="utf-8"), expected_main)

        metadata = json.loads((project.path / ".mtexproj").read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "SampleProject")
        self.assertEqual(metadata["main"], DEFAULT_MAIN_FILE)
        self.assertEqual(metadata["version"], 1)

    def test_open_project_without_metadata_imports_folder(self) -> None:
        project_dir = self.root / "ImportedProject"
        project_dir.mkdir()
        (project_dir / "main.mtex").write_text("\\documentclass{article}\n", encoding="utf-8")

        project = self.manager.open_project(project_dir)

        self.assertEqual(project.name, "ImportedProject")
        self.assertEqual(project.main_file, "main.mtex")
        self.assertTrue((project_dir / ".mtexproj").exists())
        self.assertTrue((project_dir / BUILD_DIRNAME).is_dir())

    def test_create_project_entries_resolve_root_folder_and_file_targets(self) -> None:
        project = self.manager.create_project("WorkspaceProject", self.root)
        docs_dir = project.path / "docs"
        docs_dir.mkdir()
        selected_file = docs_dir / "notes.txt"
        selected_file.write_text("seed", encoding="utf-8")

        root_file = self.manager.create_project_file(project.path, None, "readme.md")
        nested_file = self.manager.create_project_file(project.path, docs_dir, "chapter.mtex")
        nested_folder = self.manager.create_project_folder(project.path, selected_file, "assets")

        self.assertEqual(root_file, project.path / "readme.md")
        self.assertTrue(root_file.exists())
        self.assertEqual(nested_file, docs_dir / "chapter.mtex")
        self.assertTrue(nested_file.exists())
        self.assertEqual(nested_folder, docs_dir / "assets")
        self.assertTrue(nested_folder.is_dir())

    def test_project_entry_creation_rejects_invalid_or_existing_names(self) -> None:
        project = self.manager.create_project("SafetyProject", self.root)
        (project.path / "exists.txt").write_text("data", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "empty"):
            self.manager.create_project_file(project.path, None, "   ")
        with self.assertRaisesRegex(ValueError, "path separators"):
            self.manager.create_project_folder(project.path, None, "../escape")
        with self.assertRaises(FileExistsError):
            self.manager.create_project_file(project.path, None, "exists.txt")

    def test_upload_files_copies_new_files_and_skips_existing_names(self) -> None:
        project = self.manager.create_project("UploadProject", self.root)
        images_dir = project.path / "images"
        images_dir.mkdir()
        existing_target = images_dir / "plot.png"
        existing_target.write_text("keep", encoding="utf-8")

        source_dir = self.root / "external"
        source_dir.mkdir()
        duplicate_source = source_dir / "plot.png"
        duplicate_source.write_text("replace", encoding="utf-8")
        new_source = source_dir / "diagram.svg"
        new_source.write_text("<svg />", encoding="utf-8")

        result = self.manager.upload_files(project.path, images_dir, [duplicate_source, new_source])

        self.assertEqual(result.copied_paths, (images_dir / "diagram.svg",))
        self.assertEqual(result.skipped_existing, (images_dir / "plot.png",))
        self.assertEqual(existing_target.read_text(encoding="utf-8"), "keep")
        self.assertEqual((images_dir / "diagram.svg").read_text(encoding="utf-8"), "<svg />")


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TMP_ROOT / f"case_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "recent_projects.json"
        self.manager = ProjectManager()
        self.registry = ProjectRegistry(self.registry_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_registry_persists_and_orders_recent_projects(self) -> None:
        first = self.manager.create_project("First", self.root)
        second = self.manager.create_project("Second", self.root)

        self.registry.add_project(first)
        self.registry.add_project(second)
        self.registry.save()

        loaded = ProjectRegistry(self.registry_path)
        loaded.load()
        projects = loaded.list_projects()

        self.assertEqual([project.name for project in projects], ["Second", "First"])

    def test_remove_missing_projects_filters_deleted_entries(self) -> None:
        existing = self.manager.create_project("KeepMe", self.root)
        missing = self.manager.create_project("DeleteMe", self.root)

        self.registry.add_project(existing)
        self.registry.add_project(missing)
        shutil.rmtree(missing.path, ignore_errors=True)

        self.registry.remove_missing_projects()

        self.assertEqual([project.name for project in self.registry.list_projects()], ["KeepMe"])


def test_default_registry_path_uses_platformdirs(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_user_data_dir(*args, **kwargs) -> str:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return str(tmp_path / "data-home")

    monkeypatch.setattr(project_system, "user_data_dir", fake_user_data_dir)

    path = project_system.default_registry_path()

    assert path == tmp_path / "data-home" / "recent_projects.json"
    assert captured["args"] == ()
    assert captured["kwargs"] == {"appname": "MTeX Studio", "appauthor": False}


if __name__ == "__main__":
    unittest.main()
