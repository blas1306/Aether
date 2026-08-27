"""Opt-in performance characterization for SSA authority diagnostics."""

from __future__ import annotations

from time import perf_counter

from aether.ir.model import IRModule

from .general_builder import GeneralSSABuilder
from .model import SSAModule
from .shadow import SSAPerformanceProfile
from .verifier import SSAVerifier


def characterize_python_ssa_only(
    module: IRModule,
) -> tuple[SSAModule, SSAPerformanceProfile]:
    """Measure the current Python-only authority path from verified Initial IR.

    This is a diagnostic wrapper, not a new authority configuration.  It uses
    the same builder and final verifier as ``SSAPipeline.run``.
    """
    total_started = perf_counter()
    phases: dict[str, float] = {}
    lowering_phases: dict[str, float] = {}
    lifecycle_phases: dict[str, float] = {}
    value = GeneralSSABuilder(
        performance_timings=phases,
        phase_timings=lowering_phases,
        lifecycle_timings=lifecycle_phases,
    ).build(module)
    started = perf_counter()
    SSAVerifier(value).verify()
    phases["python_authority_pipeline_verification"] = perf_counter() - started
    total = perf_counter() - total_started
    measured = sum(phases.values())
    residual = max(0.0, total - measured)
    if measured > total:
        total = measured
        residual = 0.0
    return value, SSAPerformanceProfile(
        mode="python_ssa_only",
        clock="time.perf_counter",
        phases_seconds=phases,
        measured_component_sum_seconds=measured,
        residual_unattributed_seconds=residual,
        total_wall_seconds=total,
        rust_phase_detail="not_applicable",
        rust_ssa_lowering_phases_seconds={},
        python_ssa_lowering_phases_seconds=lowering_phases,
        python_lifecycle_phases_seconds=lifecycle_phases,
    )
