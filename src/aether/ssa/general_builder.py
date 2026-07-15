from __future__ import annotations

from typing import NoReturn

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
    """

    def build(self, module: IRModule) -> SSAModule:
        return self.build_module(module)

    def build_module(self, module: IRModule) -> SSAModule:
        module = expand_lifecycle(module)
        ssa_module = SSAModule(
            [self._build_function_unverified(function) for function in module.functions],
            list(module.structs),
        )
        return self._verify_module(ssa_module)

    def build_function(self, function: IRFunction) -> SSAFunction:
        ssa_function = self._build_function_unverified(function)
        module = self._verify_module(SSAModule([ssa_function]))
        return module.functions[0]

    def _build_function_unverified(self, function: IRFunction) -> SSAFunction:
        try:
            cfg = CFGBuilder().build(function)
        except Exception as error:
            self._fail(function.name, "CFG construction", error)

        try:
            dominators = DominatorAnalysis(cfg).compute()
        except Exception as error:
            self._fail(function.name, "dominator analysis", error)

        try:
            dominance_frontier = DominanceFrontierAnalysis(cfg, dominators).compute()
        except Exception as error:
            self._fail(function.name, "dominance-frontier analysis", error)

        try:
            phi_placement = PhiPlacement(
                function,
                cfg,
                dominators,
                dominance_frontier,
            ).place()
        except Exception as error:
            self._fail(function.name, "phi placement", error)

        try:
            return SSARenamer(function, cfg, dominators, phi_placement).rename().function
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
