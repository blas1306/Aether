from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests import qualification_runner as qr


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).with_name("qualification.toml")


def command_suite(command: list[str], timeout: int = 5) -> dict:
    return {
        "id": "fixture:command",
        "command": command,
        "timeout_seconds": timeout,
        "platform": ["any"],
    }


class QualificationRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = qr.load_manifest(MANIFEST)
        cls.suites = qr.validate_manifest(cls.data, ROOT)

    def test_manifest_parses_and_validates(self) -> None:
        self.assertEqual(self.data["version"], 1)
        self.assertGreater(len(self.suites), 100)

    def test_profile_selection_and_multiple_membership(self) -> None:
        core = {suite["id"] for suite in qr.selected_suites(self.suites, "core")}
        conformance = {suite["id"] for suite in qr.selected_suites(self.suites, "conformance")}
        self.assertIn("cargo:aether-driver:core_v1", core)
        self.assertTrue(core <= conformance)
        self.assertNotIn("cargo:aether-driver:linear_algebra_qr_v1", conformance)

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(qr.ManifestError, "unknown profile"):
            qr.selected_suites(self.suites, "mystery")

    def test_new_integration_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "crates" / "new-crate" / "tests" / "unclassified.rs"
            target.parent.mkdir(parents=True)
            target.write_text("#[test] fn new_test() {}\n", encoding="utf-8")
            with self.assertRaisesRegex(qr.ManifestError, "unclassified integration test: new-crate/unclassified"):
                qr.validate_manifest(copy.deepcopy(self.data), root)

    def test_unknown_suite_reference_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        integration = next(s for s in data["suite"] if s.get("target_kind") == "integration")
        integration["target"] = "suite_that_does_not_exist"
        integration["command"][-1] = "suite_that_does_not_exist"
        with self.assertRaisesRegex(qr.ManifestError, "manifest references missing integration test"):
            qr.validate_manifest(data, ROOT)

    def test_previously_mandatory_conformance_suite_cannot_be_dropped(self) -> None:
        data = copy.deepcopy(self.data)
        suite = next(
            s for s in data["suite"]
            if s.get("primary_responsibility") == "observable language and native-program conformance"
        )
        suite["profiles"] = ["full"]
        with self.assertRaisesRegex(qr.ManifestError, "previously mandatory language suite"):
            qr.validate_manifest(data, ROOT)

    def test_nonzero_command_is_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            result = qr.run_suite(command_suite([sys.executable, "-c", "raise SystemExit(7)"]), path, path)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["returncode"], 7)

    def test_missing_command_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            result = qr.run_suite(command_suite(["qualification-command-does-not-exist"]), path, path)
            self.assertEqual(result["status"], "BLOCKED")

    def test_timeout_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            result = qr.run_suite(command_suite([sys.executable, "-c", "import time; time.sleep(10)"], 1), path, path)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("timeout", result["reason"])

    def test_timeout_kills_persistent_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            pid_file = path / "child.pid"
            code = (
                "import pathlib,subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(30)"
            )
            result = qr.run_suite(command_suite([sys.executable, "-c", code], 1), path, path)
            self.assertEqual(result["status"], "BLOCKED")
            child_pid = int(pid_file.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and Path(f"/proc/{child_pid}").exists():
                time.sleep(0.05)
            if Path(f"/proc/{child_pid}/stat").exists():
                state = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
                self.assertEqual(state, "Z", "persistent child remained alive after timeout")

    def test_json_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "result.json"
            qr.write_json(destination, {"status": "PASS", "duration_seconds": 0.1})
            self.assertEqual(json.loads(destination.read_text())["status"], "PASS")

    def test_full_uses_literal_workspace_without_inventory_filters(self) -> None:
        full = qr.selected_suites(self.suites, "full")
        workspace = [suite for suite in full if suite["kind"] == "cargo-workspace"]
        self.assertEqual([suite["command"] for suite in workspace], [qr.FULL_EXACT_COMMAND])
        self.assertFalse(any(suite.get("target_kind") == "integration" for suite in full))
        self.assertEqual(qr.integration_inventory(ROOT), {
            (suite["crate"], suite["target"])
            for suite in self.suites if suite.get("target_kind") == "integration"
        })

    def test_main_returns_nonzero_for_fail_or_blocked(self) -> None:
        fake = [{"id": "fixture", "profiles": ["core"]}]
        result = {"id": "fixture", "status": "FAIL", "duration_seconds": 0.0, "log": "x"}
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(qr, "load_manifest", return_value={"version": 1, "suite": fake}), \
             mock.patch.object(qr, "validate_manifest", return_value=fake), \
             mock.patch.object(qr, "run_suite", return_value=result), \
             mock.patch.dict(os.environ, {"QUALIFY_OUTPUT_DIR": temp}):
            self.assertEqual(qr.main(["core"]), 1)


if __name__ == "__main__":
    unittest.main()
