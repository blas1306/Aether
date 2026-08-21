from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = ROOT / "scripts/qualify_rust_ssa_authority_full_suite.py"


def _qualifier_module():
    spec = importlib.util.spec_from_file_location(
        "rust_ssa_full_suite_qualifier", QUALIFIER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(returncode: int, summary: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[sys.executable, "-m", "pytest"],
        returncode=returncode,
        stdout=summary,
        stderr="",
    )


def _write_junit(path: Path, failures: list[str]) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for name in failures:
        testcase = ET.SubElement(
            suite,
            "testcase",
            classname="tests.synthetic",
            name=name,
        )
        failure = ET.SubElement(testcase, "failure", message=f"{name} failed")
        failure.text = f"tests/synthetic.py:10: AssertionError: {name} failed"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_synthetic_pytest_failures_report_all_node_ids_and_output(
    tmp_path: Path,
) -> None:
    qualifier = _qualifier_module()
    test_path = tmp_path / "test_synthetic_failures.py"
    test_path.write_text(
        """\
import sys


def test_first_failure():
    print("first captured stdout")
    print("first captured stderr", file=sys.stderr)
    assert False, "first synthetic detail"


def test_second_failure():
    print("second captured stdout")
    print("second captured stderr", file=sys.stderr)
    assert False, "second synthetic detail"
""",
        encoding="utf-8",
    )
    junit_report = tmp_path / "failures.xml"

    result = qualifier._run(
        [str(test_path)], lsan_compatible=True, junit_report=junit_report
    )
    failures, failure_count = qualifier._parse_junit_failures(junit_report)

    assert result.returncode == 1
    assert failure_count == 2
    assert len(failures) == 2
    assert [row["node_id"].rsplit("/", 1)[-1] for row in failures] == [
        "test_synthetic_failures.py::test_first_failure",
        "test_synthetic_failures.py::test_second_failure",
    ]
    assert [row["phase"] for row in failures] == ["call", "call"]
    assert "first synthetic detail" in failures[0]["error_summary"]
    assert "second synthetic detail" in failures[1]["error_summary"]
    assert "first captured stdout" in failures[0]["stdout"]
    assert "first captured stderr" in failures[0]["stderr"]
    assert "second captured stdout" in failures[1]["stdout"]
    assert "second captured stderr" in failures[1]["stderr"]


def test_successful_pytest_has_no_failure_diagnostics(tmp_path: Path) -> None:
    qualifier = _qualifier_module()
    test_path = tmp_path / "test_synthetic_success.py"
    test_path.write_text(
        "def test_success():\n    assert True\n",
        encoding="utf-8",
    )
    junit_report = tmp_path / "success.xml"

    result = qualifier._run(
        [str(test_path)], lsan_compatible=True, junit_report=junit_report
    )

    assert result.returncode == 0
    assert qualifier._count(result, "passed") == 1
    assert qualifier._parse_junit_failures(junit_report) == ([], 0)


def test_qualification_pass_fail_semantics_are_unchanged() -> None:
    qualifier = _qualifier_module()
    safe = _completed(0, "4828 passed, 4 skipped")
    promotion = _completed(0, "8 passed")
    native = _completed(0, "54 passed")

    assert qualifier._qualification_passed(safe, promotion, native)
    assert not qualifier._qualification_passed(
        _completed(1, "4824 passed, 3 failed, 5 skipped"), promotion, native
    )
    assert not qualifier._qualification_passed(
        safe, _completed(1, "7 passed, 1 failed"), native
    )
    assert not qualifier._qualification_passed(
        safe, promotion, _completed(1, "54 passed")
    )
    assert not qualifier._qualification_passed(
        safe, promotion, _completed(0, "53 passed")
    )
    assert qualifier._count(safe, "failed") == 0
    failed_safe = _completed(1, "4824 passed, 3 failed, 5 skipped")
    assert qualifier._count(failed_safe, "failed") == 3


def test_failed_main_writes_diagnostics_and_remains_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    qualifier = _qualifier_module()

    def fake_run(arguments, *, lsan_compatible, junit_report=None):
        if junit_report is not None:
            _write_junit(junit_report, ["test_first", "test_second"])
            return _completed(1, "4824 passed, 2 failed, 5 skipped")
        if "tests/aether/test_native_exceptions.py" in arguments:
            if lsan_compatible:
                return _completed(0, "54 passed")
            result = _completed(1, "1 failed")
            result.stderr = "LeakSanitizer cannot run under ptrace"
            return result
        return _completed(0, "8 passed")

    output = tmp_path / "full_suite.json"
    monkeypatch.setattr(qualifier, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(QUALIFIER),
            "--revision",
            "diagnostic-revision",
            "--output",
            str(output),
            "--executable",
            sys.executable,
        ],
    )

    assert qualifier.main() == 1

    report = json.loads(output.read_text(encoding="utf-8"))
    assert (
        report["decision"]
        == "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_BLOCKED"
    )
    assert report["failed"] == 2
    assert report["semantic_mismatches"] == report["real_semantic_failures"] == 0
    assert report["infrastructure_failures"] == 0
    assert report["environmental_failures"] == 0
    assert report["unclassified_test_failures"] == 2
    assert {row["classification"] for row in report["failures"]} == {
        "unclassified_test_failures"
    }
    assert [row["node_id"] for row in report["failures"]] == [
        "tests/synthetic.py::test_first",
        "tests/synthetic.py::test_second",
    ]
    assert report["reported_failure_count"] == 2
    assert report["failures_truncated"] is False
    assert report["summaries"]["safe_default"] == (
        "4824 passed, 2 failed, 5 skipped"
    )
    assert report["pytest_log"] == "full_suite_pytest.log"
    log = output.with_name(report["pytest_log"])
    assert "4824 passed, 2 failed, 5 skipped" in log.read_text(encoding="utf-8")


def test_successful_main_keeps_pass_result_without_failures(
    tmp_path: Path, monkeypatch
) -> None:
    qualifier = _qualifier_module()

    def fake_run(arguments, *, lsan_compatible, junit_report=None):
        if junit_report is not None:
            _write_junit(junit_report, [])
            return _completed(0, "4828 passed, 4 skipped")
        if "tests/aether/test_native_exceptions.py" in arguments:
            return _completed(0, "54 passed")
        return _completed(0, "8 passed")

    output = tmp_path / "full_suite.json"
    monkeypatch.setattr(qualifier, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(QUALIFIER),
            "--revision",
            "diagnostic-revision",
            "--output",
            str(output),
            "--executable",
            sys.executable,
        ],
    )

    assert qualifier.main() == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert (
        report["decision"]
        == "RUST_SSA_AUTHORITY_REQUALIFICATION_FULL_SUITE_PASS"
    )
    assert report["passed"] == 4828
    assert report["failed"] == report["real_semantic_failures"] == 0
    assert report["semantic_mismatches"] == 0
    assert report["infrastructure_failures"] == 0
    assert report["environmental_failures"] == 0
    assert report["unclassified_test_failures"] == 0
    assert report["failures"] == []
    assert report["reported_failure_count"] == 0
    assert report["failures_truncated"] is False


def test_failure_diagnostics_are_bounded_and_deterministic(tmp_path: Path) -> None:
    qualifier = _qualifier_module()
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    oversized = "diagnostic detail " * qualifier.MAX_DIAGNOSTIC_CHARACTERS
    for index in reversed(range(qualifier.MAX_FAILURES + 2)):
        testcase = ET.SubElement(
            suite,
            "testcase",
            classname="tests.synthetic.TestFailures",
            name=f"test_failure_{index:03d}",
            file="tests/synthetic.py",
        )
        failure = ET.SubElement(testcase, "failure", message="synthetic")
        failure.text = oversized
        stdout = ET.SubElement(testcase, "system-out")
        stdout.text = oversized
        stderr = ET.SubElement(testcase, "system-err")
        stderr.text = oversized
    report = tmp_path / "bounded.xml"
    ET.ElementTree(root).write(report, encoding="utf-8", xml_declaration=True)

    first = qualifier._parse_junit_failures(report)
    second = qualifier._parse_junit_failures(report)

    assert first == second
    failures, failure_count = first
    assert failure_count == qualifier.MAX_FAILURES + 2
    assert len(failures) == qualifier.MAX_FAILURES
    assert failures == sorted(
        failures,
        key=lambda row: (row["node_id"], row["phase"], row["error_summary"]),
    )
    for failure in failures:
        assert len(failure["error_summary"]) <= qualifier.MAX_DIAGNOSTIC_CHARACTERS
        assert len(failure["stdout"]) <= qualifier.MAX_DIAGNOSTIC_CHARACTERS
        assert len(failure["stderr"]) <= qualifier.MAX_DIAGNOSTIC_CHARACTERS
        assert "...[truncated; original_chars=" in failure["error_summary"]


def test_log_and_environment_preserve_complete_diagnostic_evidence(
    tmp_path: Path,
) -> None:
    qualifier = _qualifier_module()
    result = subprocess.CompletedProcess(
        args=[sys.executable, "-m", "pytest", "--tb=short"],
        returncode=1,
        stdout="complete stdout\n",
        stderr="complete stderr\n",
    )
    log_path = tmp_path / "full_suite_pytest.log"

    qualifier._write_pytest_log(log_path, result)
    environment = qualifier._environment(Path(sys.executable))

    log = log_path.read_text(encoding="utf-8")
    assert "complete stdout\n" in log
    assert "complete stderr\n" in log
    assert environment["sys_version"] == sys.version
    assert environment["platform"] == platform.platform()
    assert environment["machine"] == platform.machine()
    assert environment["python_executable"] == str(Path(sys.executable).resolve())
    executable = environment["qualification_executable"]
    assert isinstance(executable, dict)
    assert executable["resolved_path"] == str(Path(sys.executable).resolve())
    assert executable["sha256"]


def test_failure_classification_requires_concrete_evidence() -> None:
    qualifier = _qualifier_module()
    failures = [
        {
            "node_id": "tests/semantic.py::test_mismatch",
            "error_summary": (
                'SSAShadowFailure: {"classification": "semantic_mismatch"}'
            ),
            "phase": "call",
            "stdout": "",
            "stderr": "",
        },
        {
            "node_id": "tests/infrastructure.py::test_companion",
            "error_summary": (
                "packaged Rust SSA companion manifest was not found"
            ),
            "phase": "call",
            "stdout": "",
            "stderr": "",
        },
        {
            "node_id": "tests/environment.py::test_wheel",
            "error_summary": "Cannot import 'setuptools.build_meta'",
            "phase": "call",
            "stdout": "",
            "stderr": "",
        },
        {
            "node_id": "tests/generic.py::test_assertion",
            "error_summary": "AssertionError: unrelated failure",
            "phase": "call",
            "stdout": "",
            "stderr": "",
        },
    ]

    assert qualifier._classify_failures(failures) == {
        "semantic_mismatches": 1,
        "infrastructure_failures": 1,
        "environmental_failures": 1,
        "unclassified_test_failures": 1,
    }
    assert [failure["classification"] for failure in failures] == [
        "semantic_mismatches",
        "infrastructure_failures",
        "environmental_failures",
        "unclassified_test_failures",
    ]
