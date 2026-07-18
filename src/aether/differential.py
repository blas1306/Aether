from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence

from .backend.llvm import LLVMBuilder
from .capabilities import BackendIdentity, validate_backend_capabilities
from .pipeline import prepare_typed_program
from .typechecker import TypeChecker


OPTIMIZATION_LEVELS = ("O0", "O1", "O2")
DEFAULT_CORPUS_ROOT = Path(__file__).resolve().parents[2] / "tests" / "aether" / "parity_corpus"


@dataclass(frozen=True)
class DifferentialCase:
    name: str
    source_path: Path
    arguments: tuple[str, ...] = ()
    fixture_files: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", self.source_path.resolve())


@dataclass(frozen=True)
class Observation:
    stdout: bytes
    stderr: bytes
    exit_code: int
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class DifferentialResult:
    case: DifferentialCase
    ast: Observation
    native: Mapping[str, Observation]


class DifferentialParityError(AssertionError):
    pass


def discover_cases(corpus_root: Path = DEFAULT_CORPUS_ROOT) -> tuple[DifferentialCase, ...]:
    root = corpus_root.resolve()
    cases: list[DifferentialCase] = []
    for source_path in sorted(root.rglob("*.ae")):
        metadata_path = source_path.with_suffix(".json")
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.exists()
            else {}
        )
        if metadata.get("enabled") is False:
            continue
        arguments = tuple(str(value) for value in metadata.get("arguments", ()))
        fixture_files = {
            str(relative): _fixture_bytes(value)
            for relative, value in metadata.get("files", {}).items()
        }
        cases.append(
            DifferentialCase(
                name=source_path.relative_to(root).with_suffix("").as_posix(),
                source_path=source_path,
                arguments=arguments,
                fixture_files=fixture_files,
            )
        )
    if not cases:
        raise ValueError(f"Differential corpus is empty: {root}")
    return tuple(cases)


def run_case(
    case: DifferentialCase,
    *,
    optimization_levels: Sequence[str] = OPTIMIZATION_LEVELS,
    timeout: float = 20.0,
) -> DifferentialResult:
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError("clang is required by the AST/native differential gate")

    source = case.source_path.read_text(encoding="utf-8")
    typed = prepare_typed_program(
        source,
        TypeChecker(source_root=case.source_path.parent, entry_path=case.source_path),
    )
    validate_backend_capabilities(typed, BackendIdentity.NATIVE)
    llvm = LLVMBuilder().emit_llvm(typed)

    with tempfile.TemporaryDirectory(prefix="aether-differential-build-") as build_dir_name:
        build_dir = Path(build_dir_name)
        llvm_path = build_dir / "program.ll"
        llvm_path.write_text(llvm, encoding="utf-8")

        ast = _run_ast(case, timeout=timeout)
        native: dict[str, Observation] = {}
        for level in optimization_levels:
            if level not in OPTIMIZATION_LEVELS:
                raise ValueError(f"Unsupported differential optimization level: {level}")
            executable = build_dir / f"program-{level}"
            command = [clang, f"-{level}", str(llvm_path), "-o", str(executable)]
            if os.name != "nt":
                command.append("-lm")
            compiled = subprocess.run(
                command,
                check=False,
                capture_output=True,
                env=_controlled_environment(),
                timeout=timeout,
            )
            if compiled.returncode != 0:
                detail = (compiled.stderr or compiled.stdout).decode(errors="replace")
                raise RuntimeError(f"clang {level} failed for {case.name}: {detail.strip()}")
            native[level] = _run_native(case, executable, timeout=timeout)

    return DifferentialResult(case=case, ast=ast, native=native)


def assert_result_parity(result: DifferentialResult) -> None:
    for level, observation in result.native.items():
        if observation == result.ast:
            continue
        differences = []
        for field in ("stdout", "stderr", "exit_code", "files"):
            ast_value = getattr(result.ast, field)
            native_value = getattr(observation, field)
            if ast_value != native_value:
                differences.append(
                    f"  {field}: AST={ast_value!r}; native {level}={native_value!r}"
                )
        raise DifferentialParityError(
            f"observable divergence in {result.case.name} at {level}:\n"
            + "\n".join(differences)
        )


def run_corpus(
    cases: Iterable[DifferentialCase] | None = None,
    *,
    optimization_levels: Sequence[str] = OPTIMIZATION_LEVELS,
    timeout: float = 20.0,
) -> tuple[DifferentialResult, ...]:
    results = []
    for case in cases or discover_cases():
        result = run_case(
            case,
            optimization_levels=optimization_levels,
            timeout=timeout,
        )
        assert_result_parity(result)
        results.append(result)
    return tuple(results)


def _run_ast(case: DifferentialCase, *, timeout: float) -> Observation:
    with tempfile.TemporaryDirectory(prefix="aether-differential-ast-") as sandbox_name:
        sandbox = Path(sandbox_name)
        _write_fixtures(sandbox, case.fixture_files)
        arguments = _expand_arguments(case.arguments, sandbox)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "aether",
                "--backend=ast",
                str(case.source_path),
                "--",
                *arguments,
            ],
            cwd=sandbox,
            env=_controlled_environment(),
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        return _observation(completed, sandbox)


def _run_native(
    case: DifferentialCase,
    executable: Path,
    *,
    timeout: float,
) -> Observation:
    with tempfile.TemporaryDirectory(prefix="aether-differential-native-") as sandbox_name:
        sandbox = Path(sandbox_name)
        _write_fixtures(sandbox, case.fixture_files)
        arguments = _expand_arguments(case.arguments, sandbox)
        completed = subprocess.run(
            [str(executable), *arguments],
            cwd=sandbox,
            env=_controlled_environment(),
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        return _observation(completed, sandbox)


def _controlled_environment() -> dict[str, str]:
    environment = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1])
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root
        if not existing_python_path
        else os.pathsep.join((source_root, existing_python_path))
    )
    environment.update(
        {
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
        }
    )
    return environment


def _expand_arguments(arguments: Sequence[str], sandbox: Path) -> list[str]:
    return [argument.replace("{sandbox}", str(sandbox)) for argument in arguments]


def _write_fixtures(sandbox: Path, fixture_files: Mapping[str, bytes]) -> None:
    for relative, content in fixture_files.items():
        target = sandbox / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _observation(
    completed: subprocess.CompletedProcess[bytes],
    sandbox: Path,
) -> Observation:
    files = tuple(
        (path.relative_to(sandbox).as_posix(), path.read_bytes())
        for path in sorted(sandbox.rglob("*"))
        if path.is_file()
    )
    return Observation(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        files=files,
    )


def _fixture_bytes(value: object) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, dict) and set(value) == {"hex"}:
        return bytes.fromhex(str(value["hex"]))
    raise ValueError("fixture values must be UTF-8 strings or {'hex': '...'}")
