from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets  # type: ignore

from shadow_validation_harness import ShadowValidationHarness


_SHADOW_HARNESS_ATTRIBUTE = "_aether_shadow_validation_harness"
_SHADOW_INFRASTRUCTURE_TESTS = (
    "tests/aether/test_shadow_validation_harness.py",
    "tests/aether/test_shadow_verifier.py",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("aether-shadow-validation")
    group.addoption(
        "--shadow-validation-executable",
        default=None,
        help=(
            "Explicit aether-ir-verifier executable used to inject "
            "Python-authoritative Initial IR shadow verification."
        ),
    )
    group.addoption(
        "--shadow-validation-output",
        default=None,
        help="Optional deterministic JSON summary path.",
    )


def pytest_configure(config: pytest.Config) -> None:
    executable = config.getoption("--shadow-validation-executable")
    if executable is None:
        return
    harness = ShadowValidationHarness(executable=executable)
    setattr(config, _SHADOW_HARNESS_ATTRIBUTE, harness)


def pytest_collection_finish(session: pytest.Session) -> None:
    harness = _shadow_harness(session.config)
    if harness is not None:
        harness.tests_collected = len(session.items)


def pytest_sessionstart(session: pytest.Session) -> None:
    harness = _shadow_harness(session.config)
    if harness is not None:
        harness.install()


def pytest_runtest_setup(item: pytest.Item) -> None:
    harness = _shadow_harness(item.config)
    if harness is not None:
        harness.set_injection_enabled(
            not item.nodeid.startswith(_SHADOW_INFRASTRUCTURE_TESTS)
        )
        harness.set_active_test(item.nodeid)


def pytest_runtest_teardown(item: pytest.Item) -> None:
    harness = _shadow_harness(item.config)
    if harness is not None:
        harness.tests_completed += 1
        harness.set_active_test(None)
        harness.set_injection_enabled(True)


def pytest_sessionfinish(session: pytest.Session) -> None:
    harness = _shadow_harness(session.config)
    if harness is None:
        return
    harness.set_active_test(None)
    harness.uninstall()
    output = session.config.getoption("--shadow-validation-output")
    if output is not None:
        harness.write_summary(output, population="full_python_test_suite")


def _shadow_harness(config: pytest.Config) -> ShadowValidationHarness | None:
    value = getattr(config, _SHADOW_HARNESS_ATTRIBUTE, None)
    return value if isinstance(value, ShadowValidationHarness) else None


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
    for widget in list(app.topLevelWidgets()):
        widget.close()
    app.processEvents()


@pytest.fixture(scope="session")
def rust_verifier_executable() -> Path:
    """Build and return the explicitly selected development verifier."""

    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    subprocess.run(
        [cargo, "build", "-p", "aether-ir-verifier"],
        cwd=ROOT_DIR / "compiler-rs",
        check=True,
    )
    executable_name = (
        "aether-ir-verifier.exe"
        if sys.platform == "win32"
        else "aether-ir-verifier"
    )
    return ROOT_DIR / "compiler-rs" / "target" / "debug" / executable_name


@pytest.fixture(autouse=True)
def _cleanup_qt_top_level_widgets(qapp):
    yield
    for widget in list(qapp.topLevelWidgets()):
        try:
            widget.close()
        except Exception:
            pass
    qapp.processEvents()
