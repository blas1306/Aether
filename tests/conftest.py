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

from shadow_validation_harness import ShadowValidationHarness
from rust_authority_canary_harness import (
    RustAuthorityCanaryConfiguration,
    RustAuthorityCanaryHarness,
)
from aether.pipeline import SSAPipeline
from aether.ssa.shadow import (
    PersistentRustSSALoweringClient,
    RUST_SSA_QUALIFICATION_EXECUTABLE_ENV,
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
)


_SHADOW_HARNESS_ATTRIBUTE = "_aether_shadow_validation_harness"
_CANARY_HARNESS_ATTRIBUTE = "_aether_rust_authority_canary_harness"
_SSA_QUALIFICATION_ATTRIBUTE = "_aether_rust_ssa_authority_qualification"
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
    parser.getgroup("aether-rust-ssa-authority-qualification").addoption(
        "--rust-ssa-authority-qualification-executable",
        default=None,
        help=(
            "Explicit test-only Rust SSA authority companion for promotion "
            "subset requalification."
        ),
    )
    parser.getgroup("aether-rust-ssa-authority-qualification").addoption(
        "--rust-ssa-shadow-qualification-executable",
        default=None,
        help=(
            "Explicit test-only Rust SSA shadow companion for the Python-"
            "authority rollback lane."
        ),
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
    authority_executable = session.config.getoption(
        "--rust-ssa-authority-qualification-executable"
    )
    shadow_executable = session.config.getoption(
        "--rust-ssa-shadow-qualification-executable"
    )
    if authority_executable is not None and shadow_executable is not None:
        raise pytest.UsageError(
            "Rust SSA authority and Python-authority shadow qualification are "
            "mutually exclusive"
        )
    executable = authority_executable or shadow_executable
    if executable is not None:
        resolved_executable = Path(executable).resolve()
        previous_qualification_executable = os.environ.get(
            RUST_SSA_QUALIFICATION_EXECUTABLE_ENV
        )
        os.environ[RUST_SSA_QUALIFICATION_EXECUTABLE_ENV] = os.fspath(
            resolved_executable
        )
        client = PersistentRustSSALoweringClient(
            resolved_executable, timeout_seconds=60
        )
        original_init = SSAPipeline.__init__

        def qualification_init(
            pipeline: SSAPipeline,
            *,
            builder="general",
            authority_configuration=None,
            rust_shadow_client=None,
        ) -> None:
            if builder == "general" and authority_configuration is None:
                authority_configuration = SSALoweringAuthorityConfiguration(
                    SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
                    if authority_executable is not None
                    else SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
                )
            if builder == "general" and rust_shadow_client is None:
                rust_shadow_client = client
            original_init(
                pipeline,
                builder=builder,
                authority_configuration=authority_configuration,
                rust_shadow_client=rust_shadow_client,
            )

        SSAPipeline.__init__ = qualification_init  # type: ignore[method-assign]
        setattr(
            session.config,
            _SSA_QUALIFICATION_ATTRIBUTE,
            (original_init, client, previous_qualification_executable),
        )


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
    ssa_qualification = getattr(
        session.config, _SSA_QUALIFICATION_ATTRIBUTE, None
    )
    if ssa_qualification is not None:
        original_init, client, previous_qualification_executable = ssa_qualification
        SSAPipeline.__init__ = original_init  # type: ignore[method-assign]
        client.close()
        if previous_qualification_executable is None:
            os.environ.pop(RUST_SSA_QUALIFICATION_EXECUTABLE_ENV, None)
        else:
            os.environ[RUST_SSA_QUALIFICATION_EXECUTABLE_ENV] = (
                previous_qualification_executable
            )
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
