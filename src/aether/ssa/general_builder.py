from __future__ import annotations

from time import perf_counter
from typing import MutableMapping, NoReturn

from aether.analysis.cfg import CFGBuilder
from aether.analysis.dominance_frontier import DominanceFrontierAnalysis
from aether.analysis.dominators import DominatorAnalysis
from aether.ir.model import IRFunction, IRModule
from aether.ir.lifecycle import expand_lifecycle

from .model import SSAFunction, SSAModule
from .phi_placement import PhiPlacement
from .renaming import SSARenameError, SSARenamer
from .verifier import SSAVerificationError, SSAVerifier


class GeneralSSABuildError(ValueError):
    """Raised when general SSA construction fails."""


class GeneralSSABuilder:
    """Cytron-style SSA builder for mutable slot IR.

    This builder is the default SSA construction path. The older pattern-based
    ``SSABuilder`` remains available as an explicit compatibility fallback for
    comparison and migration diagnostics.

    A verified ``IRModule`` is read-only input. Lifecycle expansion either
    returns a freshly allocated module or an already-expanded module that every
    subsequent analysis only reads; CFG construction, dominance, phi placement
    and renaming allocate their own result state. Consequently ``build`` never
    mutates the supplied Initial IR graph.
    """

    def __init__(
        self,
        *,
        performance_timings: MutableMapping[str, float] | None = None,
        phase_timings: MutableMapping[str, float] | None = None,
        lifecycle_timings: MutableMapping[str, float] | None = None,
    ) -> None:
        """Create a builder with optional observational phase timings.

        Both mappings are caller-owned and opt-in. ``performance_timings``
        preserves the stable coarse production characterization fields;
        ``phase_timings`` exposes the RUST-3.11 lowering decomposition. When
        neither is supplied, the production builder does not read the clock.
        """
        self._performance_timings = performance_timings
        self._phase_timings = phase_timings
        if lifecycle_timings is not None:
            self._lifecycle_timings = lifecycle_timings

    def build(self, module: IRModule) -> SSAModule:
        return self.build_module(module)

    def build_module(self, module: IRModule) -> SSAModule:
        timings = self._performance_timings
        observe_lifecycle = timings is not None or self._phase_timings is not None
        lifecycle_started = perf_counter() if observe_lifecycle else 0.0
        if timings is None:
            module = expand_lifecycle(
                module,
                performance_timings=getattr(self, "_lifecycle_timings", None),
            )
        else:
            module = expand_lifecycle(
                module,
                performance_timings=getattr(self, "_lifecycle_timings", None),
            )
            timings["python_lifecycle_normalization"] = (
                perf_counter() - lifecycle_started
            )
        if self._phase_timings is not None:
            self._record_phase(
                "python_lifecycle_normalization",
                perf_counter() - lifecycle_started,
            )

        observe_lowering = timings is not None or self._phase_timings is not None
        started = perf_counter() if observe_lowering else 0.0
        ssa_module = SSAModule(
            [self._build_function_unverified(function) for function in module.functions],
            list(module.structs),
        )
        if timings is not None:
            timings["python_ssa_lowering"] = perf_counter() - started

        observe_verification = timings is not None or self._phase_timings is not None
        started = perf_counter() if observe_verification else 0.0
        verified = self._verify_module(ssa_module)
        if timings is not None:
            timings["python_builder_verification"] = perf_counter() - started
        if self._phase_timings is not None:
            self._record_phase("python_builder_verification", perf_counter() - started)
        return verified

    def build_function(self, function: IRFunction) -> SSAFunction:
        ssa_function = self._build_function_unverified(function)
        started = perf_counter() if self._phase_timings is not None else 0.0
        module = self._verify_module(SSAModule([ssa_function]))
        self._record_phase_since("python_builder_verification", started)
        return module.functions[0]

    def _build_function_unverified(self, function: IRFunction) -> SSAFunction:
        started = perf_counter() if self._phase_timings is not None else 0.0
        try:
            cfg = CFGBuilder().build(function)
        except Exception as error:
            self._fail(function.name, "CFG construction", error)
        self._record_phase_since("python_cfg_construction", started)

        try:
            dominators = DominatorAnalysis(
                cfg,
                performance_timings=self._phase_timings,
            ).compute()
        except Exception as error:
            self._fail(function.name, "dominator analysis", error)

        started = perf_counter() if self._phase_timings is not None else 0.0
        try:
            dominance_frontier = DominanceFrontierAnalysis(cfg, dominators).compute()
        except Exception as error:
            self._fail(function.name, "dominance-frontier analysis", error)
        self._record_phase_since("python_dominance_frontiers", started)

        try:
            phi_placement = PhiPlacement(
                function,
                cfg,
                dominators,
                dominance_frontier,
                self._phase_timings,
            ).place()
        except Exception as error:
            self._fail(function.name, "phi placement", error)

        try:
            return SSARenamer(
                function,
                cfg,
                dominators,
                phi_placement,
                performance_timings=self._phase_timings,
            ).rename().function
        except SSARenameError as error:
            self._fail(function.name, "SSA renaming", error)

    def _verify_module(self, module: SSAModule) -> SSAModule:
        try:
            return SSAVerifier(module).verify()
        except SSAVerificationError as error:
            raise GeneralSSABuildError(f"SSA verification failed: {error}") from error

    @staticmethod
    def _fail(function_name: str, stage: str, error: Exception) -> NoReturn:
        raise GeneralSSABuildError(
            f"General SSA build failed for function '{function_name}' "
            f"during {stage}: {error}"
        ) from error

    def _record_phase(self, phase: str, elapsed: float) -> None:
        if self._phase_timings is not None:
            self._phase_timings[phase] = (
                self._phase_timings.get(phase, 0.0) + elapsed
            )

    def _record_phase_since(self, phase: str, started: float) -> None:
        if self._phase_timings is not None:
            self._record_phase(phase, perf_counter() - started)
