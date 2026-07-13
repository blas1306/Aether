from __future__ import annotations

from pathlib import Path


def test_run_file_resolves_imports_relative_to_file(tmp_path: Path, monkeypatch, capsys) -> None:
    from aether_lsp.run_file import main

    project_root = tmp_path / "project"
    source_dir = project_root / "src" / "aether"
    source_dir.mkdir(parents=True)
    (source_dir / "Geometry.ae").write_text(
        """
package Geometry;

public struct Point {
    double x;
    double y;
}

public alias P = Point;
""",
        encoding="utf-8",
    )
    main_file = source_dir / "main.ae"
    main_file.write_text("import Geometry;\nP p = P(1.0, 2.0);\nprintln(p.x);\n", encoding="utf-8")

    monkeypatch.chdir(project_root)

    exit_code = main([str(main_file)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "1.0\n"
    assert captured.err == ""


def test_run_file_propagates_explicit_main_exit_code(tmp_path: Path, capsys) -> None:
    from aether_lsp.run_file import main

    main_file = tmp_path / "main.ae"
    main_file.write_text("int main() { return 7; }\n", encoding="utf-8")

    assert main([str(main_file)]) == 7
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
