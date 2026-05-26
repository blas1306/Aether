from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

from project_outputs import ProjectOutputManager

PROJECT_METADATA_FILENAME = ".mtexproj"
DEFAULT_MAIN_FILE = "main.mtex"
PROJECT_VERSION = 1
APP_STORAGE_NAME = "MTeX Studio"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _path_key(path: str | Path) -> str:
    return str(_normalize_path(path)).casefold()


def default_registry_path() -> Path:
    base_dir = Path(user_data_dir(appname=APP_STORAGE_NAME, appauthor=False))
    return base_dir / "recent_projects.json"


def default_projects_root() -> Path:
    documents_dir = Path.home() / "Documents"
    base_dir = documents_dir if documents_dir.exists() else Path.home()
    return base_dir / "MTeX Studio Projects"


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    path: Path
    main_file: str
    last_opened: str | None = None
    created_at: str | None = None
    version: int = PROJECT_VERSION

    @property
    def main_path(self) -> Path:
        return self.path / self.main_file

    def with_last_opened(self, timestamp: str | None = None) -> "ProjectInfo":
        return replace(self, last_opened=timestamp or _now_iso())

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "path": str(self.path),
            "main": self.main_file,
            "version": self.version,
        }
        if self.created_at:
            data["created_at"] = self.created_at
        if self.last_opened:
            data["last_opened"] = self.last_opened
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ProjectInfo":
        name = str(data.get("name") or "").strip()
        path = data.get("path")
        if not name or not path:
            raise ValueError("Invalid project payload.")
        main_file = str(data.get("main") or DEFAULT_MAIN_FILE)
        return cls(
            name=name,
            path=_normalize_path(str(path)),
            main_file=main_file,
            last_opened=str(data["last_opened"]) if data.get("last_opened") else None,
            created_at=str(data["created_at"]) if data.get("created_at") else None,
            version=int(data.get("version") or PROJECT_VERSION),
        )


@dataclass(frozen=True)
class ProjectUploadResult:
    copied_paths: tuple[Path, ...]
    skipped_existing: tuple[Path, ...]


class ProjectRegistry:
    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = storage_path or default_registry_path()
        self._projects: list[ProjectInfo] = []

    def load(self) -> list[ProjectInfo]:
        if not self.storage_path.exists():
            self._projects = []
            return []
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._projects = []
            return []
        raw_projects = payload.get("projects", payload) if isinstance(payload, dict) else payload
        projects: list[ProjectInfo] = []
        if isinstance(raw_projects, list):
            for item in raw_projects:
                if not isinstance(item, dict):
                    continue
                try:
                    projects.append(ProjectInfo.from_dict(item))
                except ValueError:
                    continue
        self._projects = self._dedupe_projects(projects)
        return list(self._projects)

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PROJECT_VERSION,
            "projects": [project.to_dict() for project in self._projects],
        }
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_projects(self) -> list[ProjectInfo]:
        return list(self._projects)

    def add_project(self, project: ProjectInfo) -> None:
        self.touch_project(project)

    def remove_missing_projects(self) -> None:
        self._projects = [project for project in self._projects if project.path.exists()]

    def touch_project(self, project: ProjectInfo | str | Path) -> ProjectInfo:
        project_info = project if isinstance(project, ProjectInfo) else self._find_project(project)
        if project_info is None:
            raise ValueError("Project is not registered.")
        updated = project_info.with_last_opened()
        kept = [entry for entry in self._projects if _path_key(entry.path) != _path_key(updated.path)]
        self._projects = [updated, *kept]
        return updated

    def _find_project(self, path: str | Path) -> ProjectInfo | None:
        target_key = _path_key(path)
        for project in self._projects:
            if _path_key(project.path) == target_key:
                return project
        return None

    def _dedupe_projects(self, projects: list[ProjectInfo]) -> list[ProjectInfo]:
        deduped: list[ProjectInfo] = []
        seen: set[str] = set()
        for project in projects:
            key = _path_key(project.path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(project)
        return deduped


class ProjectManager:
    metadata_filename = PROJECT_METADATA_FILENAME
    default_main_file = DEFAULT_MAIN_FILE
    project_version = PROJECT_VERSION

    def __init__(self) -> None:
        self.output_manager = ProjectOutputManager()

    def project_file_path(self, project_root: str | Path) -> Path:
        return _normalize_path(project_root) / self.metadata_filename

    def validate_project_entry_name(self, name: str) -> str:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Name cannot be empty.")
        if clean_name in {".", ".."}:
            raise ValueError("Name cannot be '.' or '..'.")
        if Path(clean_name).is_absolute():
            raise ValueError("Name must stay inside the selected project folder.")
        if len(Path(clean_name).parts) != 1:
            raise ValueError("Name must not include path separators.")
        if any(char in '<>:"/\\|?*' for char in clean_name):
            raise ValueError("Name contains invalid characters.")
        if clean_name.rstrip(" .") != clean_name:
            raise ValueError("Name cannot end with a space or period.")
        return clean_name

    def resolve_target_directory(
        self,
        project_root: str | Path,
        selected_path: str | Path | None = None,
    ) -> Path:
        root_dir = self._resolve_project_root(project_root)
        if selected_path is None:
            return root_dir
        candidate = _normalize_path(selected_path)
        self._ensure_path_is_inside_project(root_dir, candidate)
        if candidate.is_dir():
            return candidate
        if candidate.is_file():
            return candidate.parent
        raise FileNotFoundError(f"Selected path not found: {candidate}")

    def create_project_file(
        self,
        project_root: str | Path,
        selected_path: str | Path | None,
        name: str,
    ) -> Path:
        destination = self._build_project_entry_path(project_root, selected_path, name)
        destination.touch(exist_ok=False)
        return destination

    def create_project_folder(
        self,
        project_root: str | Path,
        selected_path: str | Path | None,
        name: str,
    ) -> Path:
        destination = self._build_project_entry_path(project_root, selected_path, name)
        destination.mkdir(parents=False, exist_ok=False)
        return destination

    def upload_files(
        self,
        project_root: str | Path,
        selected_path: str | Path | None,
        sources: list[str | Path],
    ) -> ProjectUploadResult:
        destination_dir = self.resolve_target_directory(project_root, selected_path)
        root_dir = self._resolve_project_root(project_root)
        copied_paths: list[Path] = []
        skipped_existing: list[Path] = []
        for source in sources:
            source_path = _normalize_path(source)
            if not source_path.exists() or not source_path.is_file():
                raise FileNotFoundError(f"Upload source not found: {source_path}")
            destination = destination_dir / self.validate_project_entry_name(source_path.name)
            self._ensure_path_is_inside_project(root_dir, destination)
            if destination.exists():
                skipped_existing.append(destination)
                continue
            shutil.copy2(source_path, destination)
            copied_paths.append(destination)
        return ProjectUploadResult(
            copied_paths=tuple(copied_paths),
            skipped_existing=tuple(skipped_existing),
        )

    def create_project(self, name: str, base_dir: str | Path) -> ProjectInfo:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Project name cannot be empty.")
        root_dir = _normalize_path(base_dir)
        project_dir = root_dir / clean_name
        if project_dir.exists() and any(project_dir.iterdir()):
            raise FileExistsError(f"Project directory already exists: {project_dir}")
        project_dir.mkdir(parents=True, exist_ok=True)
        project = ProjectInfo(
            name=clean_name,
            path=project_dir,
            main_file=self.default_main_file,
            created_at=_now_iso(),
            last_opened=_now_iso(),
            version=self.project_version,
        )
        project.main_path.write_text(self._default_template(clean_name), encoding="utf-8")
        self.output_manager.ensure_build_dir(project_dir)
        self.write_project_metadata(project)
        return project

    def open_project(self, path: str | Path) -> ProjectInfo:
        project_root = self._resolve_project_root(path)
        metadata_path = self.project_file_path(project_root)
        if metadata_path.exists():
            project = self.load_project_metadata(project_root)
        else:
            project = self._import_project(project_root)
        if not project.main_path.exists():
            raise FileNotFoundError(f"Main file not found: {project.main_path}")
        self.output_manager.ensure_build_dir(project.path)
        return project.with_last_opened()

    def load_project_metadata(self, path: str | Path) -> ProjectInfo:
        project_root = self._resolve_project_root(path)
        metadata_path = self.project_file_path(project_root)
        if not metadata_path.exists():
            raise FileNotFoundError(f"Project metadata not found: {metadata_path}")
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid project metadata in {metadata_path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid project metadata in {metadata_path}")
        main_file = str(payload.get("main") or self._infer_main_file(project_root))
        project = ProjectInfo(
            name=str(payload.get("name") or project_root.name),
            path=project_root,
            main_file=main_file,
            created_at=str(payload["created_at"]) if payload.get("created_at") else None,
            last_opened=str(payload["last_opened"]) if payload.get("last_opened") else None,
            version=int(payload.get("version") or self.project_version),
        )
        if not project.main_path.exists():
            fallback_main = self._infer_main_file(project_root)
            project = replace(project, main_file=fallback_main)
        return project

    def write_project_metadata(self, project: ProjectInfo) -> None:
        payload: dict[str, object] = {
            "name": project.name,
            "main": project.main_file,
            "version": project.version,
        }
        if project.created_at:
            payload["created_at"] = project.created_at
        metadata_path = self.project_file_path(project.path)
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def validate_project(self, path: str | Path) -> bool:
        try:
            project_root = self._resolve_project_root(path)
        except (FileNotFoundError, NotADirectoryError):
            return False
        metadata_path = self.project_file_path(project_root)
        if metadata_path.exists():
            return True
        return any(project_root.glob("*.mtex"))

    def _resolve_project_root(self, path: str | Path) -> Path:
        target = _normalize_path(path)
        if target.is_file():
            if target.name != self.metadata_filename:
                raise FileNotFoundError(f"Not a project file: {target}")
            target = target.parent
        if not target.exists():
            raise FileNotFoundError(f"Project path not found: {target}")
        if not target.is_dir():
            raise NotADirectoryError(f"Project path is not a directory: {target}")
        return target

    def _build_project_entry_path(
        self,
        project_root: str | Path,
        selected_path: str | Path | None,
        name: str,
    ) -> Path:
        root_dir = self._resolve_project_root(project_root)
        parent_dir = self.resolve_target_directory(root_dir, selected_path)
        clean_name = self.validate_project_entry_name(name)
        destination = parent_dir / clean_name
        self._ensure_path_is_inside_project(root_dir, destination)
        if destination.exists():
            raise FileExistsError(f"Path already exists: {destination}")
        return destination

    def _ensure_path_is_inside_project(self, project_root: Path, path: Path) -> None:
        try:
            path.resolve().relative_to(project_root.resolve())
        except ValueError as exc:
            raise ValueError("Project files must stay inside the current project folder.") from exc

    def _infer_main_file(self, project_root: Path) -> str:
        preferred = project_root / self.default_main_file
        if preferred.exists():
            return self.default_main_file
        candidates = sorted(project_root.glob("*.mtex"), key=lambda item: item.name.lower())
        if not candidates:
            raise FileNotFoundError(f"No .mtex files found in {project_root}")
        return candidates[0].name

    def _import_project(self, project_root: Path) -> ProjectInfo:
        project = ProjectInfo(
            name=project_root.name,
            path=project_root,
            main_file=self._infer_main_file(project_root),
            created_at=_now_iso(),
            last_opened=_now_iso(),
            version=self.project_version,
        )
        self.write_project_metadata(project)
        return project

    def _default_template(self, project_name: str) -> str:
        return (
            "\\documentclass{article}\n"
            "\\usepackage{graphicx} % Required for inserting images\n"
            "\\usepackage{amsmath}\n"
            "\\usepackage{amsthm}\n"
            "\\usepackage{amssymb}\n"
            "\\usepackage{float}\n\n"
            f"\\title{{{project_name}}}\n"
            "\\date{\\today}\n\n"
            "\\begin{document}\n\n"
            "\\maketitle\n\n"
            "\\section{Introduction}\n\n"
            "\\end{document}\n"
        )
