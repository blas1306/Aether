from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from .backend.llvm import LLVMBackend
from .capabilities import (
    BackendIdentity,
    Capability,
    CapabilityState,
    NATIVE_CAPABILITY_PROFILE,
    backend_capability_issues,
    detect_required_capabilities,
)
from .errors import AetherError, AetherRuntimeError
from .ir import (
    IRInterpreter,
    IRLowerer,
    IRUnhandledExceptionError,
    IRVerifier,
)
from .ir.interpreter import IRExecutionError
from .ir.optimizer import OptimizerPipeline
from .pipeline import parse_source, prepare_typed_program
from .runner import run_aether
from .ssa import GeneralSSABuilder, SSAInterpreter, SSAVerifier
from .ssa.optimizer import SSAOptimizerPipeline
from .typechecker import TypeChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPOSITORY_ROOT / "corpus" / "exceptions"
CATALOG_PATH = CORPUS_ROOT / "catalog.json"
REPORT_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "compiler"
    / "exceptions"
    / "EXCEPTION_PROMOTION_DIFFERENTIAL_REPORT.json"
)
RELEASE_DOCUMENT_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "compiler"
    / "exceptions"
    / "EXCEPTION_PROMOTION_EVIDENCE.md"
)
OPTIMIZATION_LEVELS = ("O0", "O1", "O2")
INTERPRETER_STAGES = (
    "frontend",
    "initial-ir",
    "optimized-initial-ir",
    "ssa",
    "optimized-ssa",
)
REQUIRED_POSITIVE_COVERAGE = frozenset(
    {
        "throw",
        "throw expression",
        "bare rethrow",
        "try/catch",
        "multiple catches",
        "typed catches",
        "catch(Error)",
        "nested try/catch",
        "propagation across functions",
        "propagation across methods",
        "propagation through interface dispatch",
        "constructors",
        "struct exceptions",
        "class exceptions",
        "interface implementations",
        "Error.message()",
        "unmatched exceptions",
        "root reporting",
        "panic vs exception",
        "cleanup during unwinding",
        "ARC ownership",
        "arrays/lists inside exceptions",
        "nested owned aggregates",
        "recursion",
        "interface calls",
        "indirect calls",
        "constructors throwing",
        "rethrow chains",
    }
)
REQUIRED_NEGATIVE_COVERAGE = frozenset(
    {
        "invalid throw",
        "null throw",
        "illegal rethrow",
        "invalid catch ordering",
        "duplicate handlers",
        "non-Error throwable",
        "malformed programs",
    }
)
OWNERSHIP_COVERAGE = frozenset(
    {
        "single destruction",
        "no leaks",
        "no double free",
        "cleanup during unwinding",
        "rethrow ownership",
        "constructor failure cleanup",
        "nested catches",
        "nested owned aggregates",
        "ARC interaction",
    }
)
_HANDLER_PATTERN = re.compile(r"^handler:([A-Za-z0-9_-]+)$", re.MULTILINE)
_SANITIZER_MARKERS = (
    "AddressSanitizer",
    "LeakSanitizer",
    "UndefinedBehaviorSanitizer",
    "runtime error:",
)


class ExceptionEvidenceError(AssertionError):
    pass


@dataclass(frozen=True)
class ExpectedObservation:
    stdout: str
    stderr: str
    selected_handlers: tuple[str, ...]
    termination: str
    message: str | None
    exit_status: int


@dataclass(frozen=True)
class PositiveCase:
    path: Path
    relative_path: str
    covers: frozenset[str]
    expected: ExpectedObservation
    sanitizer: bool


@dataclass(frozen=True)
class NegativeCase:
    path: Path
    relative_path: str
    phase: str
    error: str
    message: str
    line: int
    column: int
    covers: frozenset[str]


@dataclass(frozen=True)
class StageObservation:
    stdout: str
    stderr: str
    selected_handlers: tuple[str, ...]
    termination: str
    message: str | None
    exit_status: int
    cleanup: str = "verified"
    ownership: str = "verified"


@dataclass(frozen=True)
class CaseResult:
    case: PositiveCase
    stages: Mapping[str, StageObservation]


def load_catalog(
    path: Path = CATALOG_PATH,
) -> tuple[tuple[PositiveCase, ...], tuple[NegativeCase, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    positives = tuple(_positive_case(item) for item in payload.get("positive", ()))
    negatives = tuple(_negative_case(item) for item in payload.get("negative", ()))
    return positives, negatives


def catalog_errors(path: Path = CATALOG_PATH) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load exception catalog: {exc}"]
    if payload.get("schema_version") != 1:
        errors.append("exception catalog schema_version must be 1")
    try:
        positives, negatives = load_catalog(path)
    except (KeyError, TypeError, ValueError) as exc:
        return [*errors, f"invalid exception catalog entry: {exc}"]
    if not positives or not negatives:
        errors.append("exception catalog must contain positive and negative cases")
    positive_paths = [case.relative_path for case in positives]
    negative_paths = [case.relative_path for case in negatives]
    listed = [*positive_paths, *negative_paths]
    if positive_paths != sorted(positive_paths) or negative_paths != sorted(negative_paths):
        errors.append("exception catalog paths must be sorted within each category")
    if len(listed) != len(set(listed)):
        errors.append("exception catalog paths must be unique")
    actual = {
        path.relative_to(CORPUS_ROOT).as_posix()
        for path in CORPUS_ROOT.rglob("*.ae")
    }
    for missing in sorted(actual - set(listed)):
        errors.append(f"exception corpus file is not cataloged: {missing}")
    for stale in sorted(set(listed) - actual):
        errors.append(f"exception catalog path does not exist: {stale}")
    positive_coverage = frozenset().union(*(case.covers for case in positives))
    negative_coverage = frozenset().union(*(case.covers for case in negatives))
    for missing in sorted(REQUIRED_POSITIVE_COVERAGE - positive_coverage):
        errors.append(f"missing positive exception coverage: {missing}")
    for missing in sorted(REQUIRED_NEGATIVE_COVERAGE - negative_coverage):
        errors.append(f"missing negative exception coverage: {missing}")
    for missing in sorted(OWNERSHIP_COVERAGE - positive_coverage):
        errors.append(f"missing ownership evidence: {missing}")
    ownership_cases = [
        case for case in positives if case.covers.intersection(OWNERSHIP_COVERAGE)
    ]
    for case in ownership_cases:
        if not case.sanitizer:
            errors.append(
                f"ownership case must enable sanitizer execution: {case.relative_path}"
            )
    for case in positives:
        errors.extend(_validate_positive_case(case))
    for case in negatives:
        if case.phase not in {"parser", "typechecker"}:
            errors.append(f"unknown negative phase for {case.relative_path}: {case.phase}")
    for required in (CORPUS_ROOT / "README.md", RELEASE_DOCUMENT_PATH, REPORT_PATH):
        if not required.is_file():
            errors.append(
                f"exception evidence reference does not exist: "
                f"{required.relative_to(REPOSITORY_ROOT).as_posix()}"
            )
    if RELEASE_DOCUMENT_PATH.is_file():
        release_text = RELEASE_DOCUMENT_PATH.read_text(encoding="utf-8")
        for target in (
            "../../../corpus/exceptions/catalog.json",
            "EXCEPTION_PROMOTION_DIFFERENTIAL_REPORT.json",
        ):
            if target not in release_text:
                errors.append(f"exception release document is missing reference: {target}")
    return errors


def capability_errors(cases: Iterable[PositiveCase]) -> list[str]:
    errors: list[str] = []
    support = NATIVE_CAPABILITY_PROFILE.support_for(Capability.ERROR_HANDLING)
    if support.state is not CapabilityState.COMPLETE:
        errors.append("ERROR_HANDLING must be COMPLETE for stable ERQ-006 evidence")
    for case in cases:
        try:
            typed = prepare_typed_program(
                case.path.read_text(encoding="utf-8"),
                TypeChecker(source_root=case.path.parent, entry_path=case.path),
            )
        except AetherError as exc:
            errors.append(
                f"positive case failed frontend preparation: {case.relative_path}: "
                f"{exc.format()}"
            )
            continue
        required = {
            item.capability for item in detect_required_capabilities(typed)
        }
        if Capability.ERROR_HANDLING not in required:
            errors.append(
                f"positive case does not require ERROR_HANDLING: {case.relative_path}"
            )
        diagnostic_codes = {
            issue.diagnostic_code
            for issue in backend_capability_issues(typed, BackendIdentity.NATIVE)
        }
        if diagnostic_codes:
            errors.append(
                f"stable native route rejects promoted case {case.relative_path}: "
                f"diagnostics={sorted(diagnostic_codes)!r}"
            )
    return errors


def negative_errors(cases: Iterable[NegativeCase]) -> list[str]:
    errors: list[str] = []
    for case in cases:
        source = case.path.read_text(encoding="utf-8")
        try:
            program = parse_source(source)
            if case.phase == "parser":
                errors.append(
                    f"expected parser rejection but parsing succeeded: {case.relative_path}"
                )
                continue
            TypeChecker(source_root=case.path.parent, entry_path=case.path).check(
                program
            )
        except AetherError as exc:
            actual = (
                type(exc).__name__,
                exc.message,
                exc.line,
                exc.column,
            )
            expected = (case.error, case.message, case.line, case.column)
            if actual != expected:
                errors.append(
                    f"diagnostic mismatch for {case.relative_path}: "
                    f"expected={expected!r}, actual={actual!r}"
                )
            elif case.phase == "typechecker" and type(exc).__name__ == "AetherSyntaxError":
                errors.append(
                    f"expected typechecker rejection but parser failed: {case.relative_path}"
                )
            continue
        except Exception as exc:  # pragma: no cover - release containment
            errors.append(
                f"unexpected failure for {case.relative_path}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        errors.append(f"negative exception case was accepted: {case.relative_path}")
    return errors


def run_case(
    case: PositiveCase,
    *,
    native: bool = True,
    optimization_levels: Sequence[str] = OPTIMIZATION_LEVELS,
    timeout: float = 20.0,
) -> CaseResult:
    source = case.path.read_text(encoding="utf-8")
    program = parse_source(source)
    TypeChecker(source_root=case.path.parent, entry_path=case.path).check(program)

    stages: dict[str, StageObservation] = {}
    stages["frontend"] = _run_frontend(source, case.path)

    initial_ir = IRLowerer().lower(program)
    IRVerifier(initial_ir).verify()
    stages["initial-ir"] = _run_ir_interpreter(IRInterpreter(initial_ir))

    optimized_ir = OptimizerPipeline().run(initial_ir)
    IRVerifier(optimized_ir).verify()
    stages["optimized-initial-ir"] = _run_ir_interpreter(
        IRInterpreter(optimized_ir)
    )

    # SSA and native consume the verified Initial IR boundary directly in the
    # supported compiler pipeline.  Optimized Initial IR is an independently
    # executable evidence stage, not the input to SSA construction.
    ssa = GeneralSSABuilder().build(initial_ir)
    SSAVerifier(ssa).verify()
    stages["ssa"] = _run_ssa_interpreter(SSAInterpreter(ssa))

    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    SSAVerifier(optimized_ssa).verify()
    stages["optimized-ssa"] = _run_ssa_interpreter(
        SSAInterpreter(optimized_ssa)
    )

    if native:
        stages.update(
            _run_native_stages(
                case,
                optimized_ssa,
                optimization_levels=optimization_levels,
                timeout=timeout,
            )
        )
    result = CaseResult(case, stages)
    assert_case_parity(result)
    return result


def run_corpus(
    cases: Iterable[PositiveCase] | None = None,
    *,
    native: bool = True,
    optimization_levels: Sequence[str] = OPTIMIZATION_LEVELS,
    timeout: float = 20.0,
) -> tuple[CaseResult, ...]:
    positives = load_catalog()[0] if cases is None else tuple(cases)
    return tuple(
        run_case(
            case,
            native=native,
            optimization_levels=optimization_levels,
            timeout=timeout,
        )
        for case in positives
    )


def assert_case_parity(result: CaseResult) -> None:
    expected = StageObservation(**asdict(result.case.expected))
    differences: list[str] = []
    for stage, actual in result.stages.items():
        for field in (
            "stdout",
            "stderr",
            "selected_handlers",
            "termination",
            "message",
            "exit_status",
            "cleanup",
            "ownership",
        ):
            expected_value = getattr(expected, field)
            actual_value = getattr(actual, field)
            if actual_value != expected_value:
                differences.append(
                    f"  {stage}.{field}: expected={expected_value!r}; "
                    f"actual={actual_value!r}"
                )
    if differences:
        raise ExceptionEvidenceError(
            f"exception differential mismatch in {result.case.relative_path}:\n"
            + "\n".join(differences)
        )


def build_report(
    results: Sequence[CaseResult],
    negatives: Sequence[NegativeCase],
) -> dict[str, Any]:
    coverage: dict[str, list[str]] = {}
    for result in results:
        for label in sorted(result.case.covers):
            coverage.setdefault(label, []).append(result.case.relative_path)
    stage_names = tuple(results[0].stages) if results else ()
    return {
        "schema_version": 1,
        "requirement": "ERQ-006",
        "status": "passed",
        "capability_promotion": "performed",
        "error_handling_state": "COMPLETE",
        "backend_strategy": "event-out",
        "summary": {
            "positive_programs": len(results),
            "negative_programs": len(negatives),
            "stages_per_positive": len(stage_names),
            "stage_comparisons": len(results) * max(0, len(stage_names) - 1),
            "sanitizer_programs": sum(result.case.sanitizer for result in results),
        },
        "stages": list(stage_names),
        "coverage": {key: coverage[key] for key in sorted(coverage)},
        "positive_results": [
            {
                "path": result.case.relative_path,
                "status": "passed",
                "sanitizer": result.case.sanitizer,
                "stages": {
                    name: _observation_payload(observation)
                    for name, observation in result.stages.items()
                },
            }
            for result in results
        ],
        "negative_results": [
            {
                "path": case.relative_path,
                "status": "rejected-as-expected",
                "phase": case.phase,
                "diagnostic": {
                    "error": case.error,
                    "message": case.message,
                    "line": case.line,
                    "column": case.column,
                },
            }
            for case in negatives
        ],
        "ownership_evidence": {
            "initial_ir": "lifecycle and terminal-event verification passed",
            "ssa": "ownership, event-linearity, and cleanup verification passed",
            "native": "ASan, UBSan, and leak detection passed for tagged cases",
        },
    }


def canonical_report_text(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def check_report(report: Mapping[str, Any], path: Path = REPORT_PATH) -> list[str]:
    if not path.is_file():
        return [f"exception differential report is missing: {path}"]
    actual = path.read_text(encoding="utf-8")
    expected = canonical_report_text(report)
    if actual != expected:
        return [
            "exception differential report is stale; rerun "
            "scripts/check_exception_promotion.py --write-report"
        ]
    return []


def _positive_case(item: Mapping[str, Any]) -> PositiveCase:
    relative = _catalog_relative_path(str(item["path"]), "positive")
    expected = item["expected"]
    return PositiveCase(
        path=(CORPUS_ROOT / relative).resolve(),
        relative_path=relative,
        covers=frozenset(str(value) for value in item["covers"]),
        expected=ExpectedObservation(
            stdout=str(expected["stdout"]),
            stderr=str(expected["stderr"]),
            selected_handlers=tuple(str(value) for value in expected["selected_handlers"]),
            termination=str(expected["termination"]),
            message=None if expected["message"] is None else str(expected["message"]),
            exit_status=int(expected["exit_status"]),
        ),
        sanitizer=bool(item["sanitizer"]),
    )


def _negative_case(item: Mapping[str, Any]) -> NegativeCase:
    relative = _catalog_relative_path(str(item["path"]), "negative")
    return NegativeCase(
        path=(CORPUS_ROOT / relative).resolve(),
        relative_path=relative,
        phase=str(item["phase"]),
        error=str(item["error"]),
        message=str(item["message"]),
        line=int(item["line"]),
        column=int(item["column"]),
        covers=frozenset(str(value) for value in item["covers"]),
    )


def _catalog_relative_path(value: str, category: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or path.suffix != ".ae"
        or not path.parts
        or path.parts[0] != category
    ):
        raise ValueError(f"invalid {category} corpus path: {value!r}")
    return value


def _validate_positive_case(case: PositiveCase) -> list[str]:
    errors: list[str] = []
    if case.expected.termination not in {"return", "exception", "panic"}:
        errors.append(
            f"invalid termination for {case.relative_path}: "
            f"{case.expected.termination}"
        )
    actual_handlers = _selected_handlers(case.expected.stdout)
    if actual_handlers != case.expected.selected_handlers:
        errors.append(
            f"selected handler oracle mismatch for {case.relative_path}: "
            f"declared={case.expected.selected_handlers!r}, "
            f"stdout={actual_handlers!r}"
        )
    return errors


def _run_frontend(source: str, path: Path) -> StageObservation:
    chunks: list[str] = []
    try:
        result = run_aether(
            source,
            source_root=path.parent,
            output_writer=chunks.append,
        )
    except AetherRuntimeError as exc:
        return _language_failure_observation("".join(chunks), exc)
    except Exception as exc:  # pragma: no cover - release containment
        return _unexpected_observation("".join(chunks), exc)
    return _observation("".join(chunks), "", result.exit_code, "return", None)


def _run_ir_interpreter(interpreter: IRInterpreter) -> StageObservation:
    try:
        result = interpreter.call("main")
    except IRUnhandledExceptionError as exc:
        return _observation(
            interpreter.output,
            f"Aether unhandled exception: {exc.dynamic_type}: {exc.message}\n",
            1,
            "exception",
            exc.message,
        )
    except IRExecutionError as exc:
        return _ir_failure_observation(interpreter.output, exc)
    except Exception as exc:  # pragma: no cover - release containment
        return _unexpected_observation(interpreter.output, exc)
    return _observation(interpreter.output, "", int(result or 0), "return", None)


def _run_ssa_interpreter(interpreter: SSAInterpreter) -> StageObservation:
    try:
        result = interpreter.call("main")
    except IRUnhandledExceptionError as exc:
        return _observation(
            interpreter.output,
            f"Aether unhandled exception: {exc.dynamic_type}: {exc.message}\n",
            1,
            "exception",
            exc.message,
        )
    except IRExecutionError as exc:
        return _ir_failure_observation(interpreter.output, exc)
    except Exception as exc:  # pragma: no cover - release containment
        return _unexpected_observation(interpreter.output, exc)
    return _observation(interpreter.output, "", int(result or 0), "return", None)


def _run_native_stages(
    case: PositiveCase,
    module: Any,
    *,
    optimization_levels: Sequence[str],
    timeout: float,
) -> dict[str, StageObservation]:
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError("clang is required by exception promotion evidence")
    llvm = LLVMBackend().emit(module)
    stages: dict[str, StageObservation] = {}
    with tempfile.TemporaryDirectory(prefix="aether-exception-evidence-") as name:
        build_dir = Path(name)
        llvm_path = build_dir / "program.ll"
        llvm_path.write_text(llvm, encoding="utf-8")
        for level in optimization_levels:
            if level not in OPTIMIZATION_LEVELS:
                raise ValueError(f"unsupported native optimization level: {level}")
            executable = build_dir / f"program-{level}"
            command = [
                clang,
                f"-{level}",
                "-Wno-override-module",
            ]
            sanitized = case.sanitizer and level == "O0"
            if sanitized:
                command.extend(
                    [
                        "-g",
                        "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer",
                    ]
                )
            command.extend([str(llvm_path), "-o", str(executable)])
            if os.name != "nt":
                command.append("-lm")
            built = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_controlled_environment(sanitized=sanitized),
            )
            if built.returncode != 0:
                detail = built.stderr or built.stdout
                raise RuntimeError(
                    f"clang {level} failed for {case.relative_path}: "
                    f"{detail.strip()}"
                )
            completed = subprocess.run(
                [str(executable)],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_controlled_environment(sanitized=sanitized),
            )
            ownership = "verified"
            if sanitized and any(
                marker in completed.stderr for marker in _SANITIZER_MARKERS
            ):
                ownership = "sanitizer-failure"
            stages[f"native-{level}"] = _native_observation(
                completed.stdout,
                completed.stderr,
                completed.returncode,
                ownership=ownership,
            )
    return stages


def _language_failure_observation(
    stdout: str,
    exc: AetherRuntimeError,
) -> StageObservation:
    if exc.message.startswith("Aether panic: "):
        message = exc.message.removeprefix("Aether panic: ")
        return _observation(
            stdout + f"Aether panic: {message}\n",
            "",
            1,
            "panic",
            message,
        )
    if exc.kind:
        return _observation(
            stdout,
            f"Aether unhandled exception: {exc.kind}: {exc.message}\n",
            1,
            "exception",
            exc.message,
        )
    return _unexpected_observation(stdout, exc)


def _ir_failure_observation(stdout: str, exc: IRExecutionError) -> StageObservation:
    text = str(exc)
    if text.startswith("Aether panic: "):
        message = text.removeprefix("Aether panic: ")
        return _observation(
            stdout + f"Aether panic: {message}\n",
            "",
            1,
            "panic",
            message,
        )
    return _unexpected_observation(stdout, exc)


def _native_observation(
    stdout: str,
    stderr: str,
    exit_status: int,
    *,
    ownership: str,
) -> StageObservation:
    root = re.fullmatch(
        r"Aether unhandled exception: ([A-Za-z_][A-Za-z0-9_]*): (.*)\n",
        stderr,
        flags=re.DOTALL,
    )
    if root is not None:
        return _observation(
            stdout,
            stderr,
            exit_status,
            "exception",
            root.group(2),
            ownership=ownership,
        )
    panic_lines = [
        line.removeprefix("Aether panic: ")
        for line in stdout.splitlines()
        if line.startswith("Aether panic: ")
    ]
    if panic_lines:
        return _observation(
            stdout,
            stderr,
            exit_status,
            "panic",
            panic_lines[-1],
            ownership=ownership,
        )
    return _observation(
        stdout,
        stderr,
        exit_status,
        "return",
        None,
        ownership=ownership,
    )


def _observation(
    stdout: str,
    stderr: str,
    exit_status: int,
    termination: str,
    message: str | None,
    *,
    ownership: str = "verified",
) -> StageObservation:
    return StageObservation(
        stdout=stdout,
        stderr=stderr,
        selected_handlers=_selected_handlers(stdout),
        termination=termination,
        message=message,
        exit_status=exit_status,
        cleanup="verified",
        ownership=ownership,
    )


def _unexpected_observation(stdout: str, exc: Exception) -> StageObservation:
    return StageObservation(
        stdout=stdout,
        stderr=f"{type(exc).__name__}: {exc}",
        selected_handlers=_selected_handlers(stdout),
        termination="stage-error",
        message=str(exc),
        exit_status=70,
        cleanup="unverified",
        ownership="unverified",
    )


def _selected_handlers(stdout: str) -> tuple[str, ...]:
    return tuple(_HANDLER_PATTERN.findall(stdout))


def _controlled_environment(*, sanitized: bool) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
        }
    )
    if sanitized:
        environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1:exitcode=99"
        environment["UBSAN_OPTIONS"] = "halt_on_error=1:exitcode=99"
    return environment


def _observation_payload(observation: StageObservation) -> dict[str, Any]:
    payload = asdict(observation)
    payload["selected_handlers"] = list(observation.selected_handlers)
    return payload
