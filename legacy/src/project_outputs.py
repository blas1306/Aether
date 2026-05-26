from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


BUILD_DIRNAME = "build"
COMPILE_LOG_FILENAME = "compile.log"


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


@dataclass(frozen=True)
class BuildArtifacts:
    project_root: Path
    source_path: Path
    build_dir: Path
    tex_path: Path
    pdf_path: Path
    toc_path: Path
    aux_path: Path
    trace_path: Path
    latex_log_path: Path
    compile_log_path: Path
    synctex_path: Path


class ProjectOutputManager:
    build_dir_name = BUILD_DIRNAME
    compile_log_filename = COMPILE_LOG_FILENAME

    def build_dir_for_project(self, project_root: str | Path) -> Path:
        return _normalize_path(project_root) / self.build_dir_name

    def ensure_build_dir(self, project_root: str | Path) -> Path:
        build_dir = self.build_dir_for_project(project_root)
        build_dir.mkdir(parents=True, exist_ok=True)
        return build_dir

    def artifacts_for_source(
        self,
        source_path: str | Path,
        project_root: str | Path | None = None,
        output_basename: str | None = None,
    ) -> BuildArtifacts:
        resolved_source = _normalize_path(source_path)
        resolved_project_root = _normalize_path(project_root) if project_root is not None else resolved_source.parent
        build_dir = self.build_dir_for_project(resolved_project_root)
        stem = output_basename or resolved_source.stem
        return BuildArtifacts(
            project_root=resolved_project_root,
            source_path=resolved_source,
            build_dir=build_dir,
            tex_path=build_dir / f"{stem}.tex",
            pdf_path=build_dir / f"{stem}.pdf",
            toc_path=build_dir / f"{stem}.toc",
            aux_path=build_dir / f"{stem}.aux",
            trace_path=build_dir / f"{stem}.mtextrace.json",
            latex_log_path=build_dir / f"{stem}.log",
            compile_log_path=build_dir / self.compile_log_filename,
            synctex_path=build_dir / f"{stem}.synctex.gz",
        )

    def list_output_files(self, build_dir: str | Path) -> list[Path]:
        root = _normalize_path(build_dir)
        if not root.exists():
            return []
        return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: str(path).lower())
