import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from editor_pdf_sync import load_trace_artifact
from latex_lang import env_ast
from mtex_executor import ejecutar_mtex
from project_outputs import BUILD_DIRNAME, COMPILE_LOG_FILENAME, ProjectOutputManager

TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "tmp_test_projects"


class ProjectOutputManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TMP_ROOT / f"outputs_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_artifacts_live_under_project_build_directory(self) -> None:
        project_root = self.root / "DemoProject"
        source_path = project_root / "chapters" / "main.mtex"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n", encoding="utf-8")

        manager = ProjectOutputManager()
        artifacts = manager.artifacts_for_source(
            source_path,
            project_root=project_root,
            output_basename=project_root.name,
        )

        self.assertEqual(artifacts.build_dir, project_root / BUILD_DIRNAME)
        self.assertEqual(artifacts.tex_path, project_root / BUILD_DIRNAME / "DemoProject.tex")
        self.assertEqual(artifacts.pdf_path, project_root / BUILD_DIRNAME / "DemoProject.pdf")
        self.assertEqual(artifacts.trace_path, project_root / BUILD_DIRNAME / "DemoProject.mtextrace.json")
        self.assertEqual(artifacts.compile_log_path, project_root / BUILD_DIRNAME / COMPILE_LOG_FILENAME)


class EjecutarMtexBuildOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TMP_ROOT / f"build_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.project_root = self.root / "BuildProject"
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.source_path = self.project_root / "main.mtex"
        self.source_path.write_text(
            "\\documentclass{article}\n\\begin{document}\nHello build output\n\\end{document}\n",
            encoding="utf-8",
        )
        self.build_dir = self.project_root / BUILD_DIRNAME

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_ejecutar_mtex_writes_outputs_to_build_dir(self) -> None:
        calls: list[tuple[str, str, bool, str | None, bool]] = []

        def _fake_pdflatex(
            tex_filename: str,
            cwd: str,
            draftmode: bool = False,
            output_dir: str | None = None,
            synctex: bool = False,
        ):
            calls.append((tex_filename, cwd, draftmode, output_dir, synctex))
            target_dir = Path(output_dir or cwd)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / f"{self.project_root.name}.log").write_text("Compilation finished.\n", encoding="utf-8")
            if not draftmode:
                (target_dir / f"{self.project_root.name}.pdf").write_bytes(b"%PDF-1.4\n%mock\n")
                if synctex:
                    (target_dir / f"{self.project_root.name}.synctex.gz").write_bytes(b"synctex")

            class _Result:
                returncode = 0

            return _Result()

        with patch("mtex_executor._run_pdflatex", side_effect=_fake_pdflatex):
            generated_pdf = ejecutar_mtex(
                str(self.source_path),
                env_ast,
                abrir_pdf=False,
                build_dir=self.build_dir,
                output_basename=self.project_root.name,
            )

        self.assertEqual(Path(generated_pdf), self.build_dir / f"{self.project_root.name}.pdf")
        self.assertTrue((self.build_dir / f"{self.project_root.name}.tex").exists())
        self.assertTrue((self.build_dir / f"{self.project_root.name}.pdf").exists())
        self.assertTrue((self.build_dir / f"{self.project_root.name}.synctex.gz").exists())
        self.assertTrue((self.build_dir / f"{self.project_root.name}.mtextrace.json").exists())
        self.assertTrue((self.build_dir / COMPILE_LOG_FILENAME).exists())
        self.assertFalse((self.project_root / "main.tex").exists())
        self.assertFalse((self.project_root / "main.pdf").exists())
        self.assertTrue(calls)
        self.assertEqual(Path(calls[0][1]), self.project_root)
        self.assertEqual(Path(calls[0][3]), self.build_dir.resolve())
        self.assertTrue(all(call[4] is True for call in calls))
        trace_artifact = load_trace_artifact(self.build_dir / f"{self.project_root.name}.mtextrace.json")
        self.assertIsNotNone(trace_artifact)
        assert trace_artifact is not None
        self.assertTrue(trace_artifact.synctex_enabled)
        self.assertGreaterEqual(len(trace_artifact.spans), 1)


if __name__ == "__main__":
    unittest.main()
