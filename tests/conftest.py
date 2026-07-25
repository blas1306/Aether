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
from rust_authority_canary_harness import (
    RustAuthorityCanaryConfiguration,
    RustAuthorityCanaryHarness,
)


_SHADOW_HARNESS_ATTRIBUTE = "_aether_shadow_validation_harness"
_CANARY_HARNESS_ATTRIBUTE = "_aether_rust_authority_canary_harness"
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
    canary = parser.getgroup("aether-rust-authority-canary")
    canary.addoption(
        "--rust-authority-canary-config",
        default=None,
        help="Explicit test-only Rust-authority canary configuration.",
    )
    canary.addoption(
        "--rust-authority-canary-executable",
        default=None,
        help="Explicit aether-ir-verifier executable for the canary.",
    )
    canary.addoption(
        "--rust-authority-canary-output",
        default=None,
        help="Required deterministic JSON summary path for a canary run.",
    )
    canary.addoption(
        "--rust-authority-canary-population",
        default=None,
        help="Required configured suite name recorded in the canary summary.",
    )


def pytest_configure(config: pytest.Config) -> None:
    executable = config.getoption("--shadow-validation-executable")
    canary_values = {
        "configuration": config.getoption("--rust-authority-canary-config"),
        "executable": config.getoption(
            "--rust-authority-canary-executable"
        ),
        "output": config.getoption("--rust-authority-canary-output"),
        "population": config.getoption(
            "--rust-authority-canary-population"
        ),
    }
    selected_canary_values = {
        name for name, value in canary_values.items() if value is not None
    }
    if executable is not None and selected_canary_values:
        raise pytest.UsageError(
            "shadow validation and Rust-authority canary are mutually exclusive"
        )
    if selected_canary_values and selected_canary_values != set(canary_values):
        raise pytest.UsageError(
            "Rust-authority canary requires config, executable, output, "
            "and population options"
        )
    if executable is not None:
        harness = ShadowValidationHarness(executable=executable)
        setattr(config, _SHADOW_HARNESS_ATTRIBUTE, harness)
    if selected_canary_values:
        canary_configuration = RustAuthorityCanaryConfiguration.load(
            canary_values["configuration"]
        )
        population = canary_values["population"]
        if population not in canary_configuration.suites:
            raise pytest.UsageError(
                "Rust-authority canary population is not configured"
            )
        canary_harness = RustAuthorityCanaryHarness(
            configuration=canary_configuration,
            executable=canary_values["executable"],
        )
        setattr(config, _CANARY_HARNESS_ATTRIBUTE, canary_harness)


def pytest_collection_finish(session: pytest.Session) -> None:
    harness = _shadow_harness(session.config)
    if harness is not None:
        harness.tests_collected = len(session.items)
    canary = _canary_harness(session.config)
    if canary is not None:
        canary.tests_collected = len(session.items)


def pytest_sessionstart(session: pytest.Session) -> None:
    harness = _shadow_harness(session.config)
    if harness is not None:
        harness.install()
    canary = _canary_harness(session.config)
    if canary is not None:
        canary.install()


def pytest_runtest_setup(item: pytest.Item) -> None:
    harness = _shadow_harness(item.config)
    if harness is not None:
        harness.set_injection_enabled(
            not item.nodeid.startswith(_SHADOW_INFRASTRUCTURE_TESTS)
        )
        harness.set_active_test(item.nodeid)
    canary = _canary_harness(item.config)
    if canary is not None:
        canary.set_active_test(item.nodeid)


def pytest_runtest_teardown(item: pytest.Item) -> None:
    harness = _shadow_harness(item.config)
    if harness is not None:
        harness.tests_completed += 1
        harness.set_active_test(None)
        harness.set_injection_enabled(True)
    canary = _canary_harness(item.config)
    if canary is not None:
        canary.tests_completed += 1
        canary.set_active_test(None)


def pytest_sessionfinish(session: pytest.Session) -> None:
    harness = _shadow_harness(session.config)
    if harness is not None:
        harness.set_active_test(None)
        harness.uninstall()
        output = session.config.getoption("--shadow-validation-output")
        if output is not None:
            harness.write_summary(
                output,
                population="full_python_test_suite",
            )
    canary = _canary_harness(session.config)
    if canary is not None:
        canary.set_active_test(None)
        canary.uninstall()
        canary.write_summary(
            session.config.getoption("--rust-authority-canary-output"),
            population=session.config.getoption(
                "--rust-authority-canary-population"
            ),
        )


def _shadow_harness(config: pytest.Config) -> ShadowValidationHarness | None:
    value = getattr(config, _SHADOW_HARNESS_ATTRIBUTE, None)
    return value if isinstance(value, ShadowValidationHarness) else None


def _canary_harness(
    config: pytest.Config,
) -> RustAuthorityCanaryHarness | None:
    value = getattr(config, _CANARY_HARNESS_ATTRIBUTE, None)
    return value if isinstance(value, RustAuthorityCanaryHarness) else None


@pytest.fixture
def rust_authority_canary(
    request: pytest.FixtureRequest,
) -> RustAuthorityCanaryHarness:
    harness = _canary_harness(request.config)
    if harness is None:
        pytest.skip("requires explicit Rust-authority canary activation")
    return harness


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
