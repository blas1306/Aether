from __future__ import annotations

from typing import NoReturn

from aether.analysis.cfg import CFGBuilder
from aether.analysis.dominance_frontier import DominanceFrontierAnalysis
from aether.analysis.dominators import DominatorAnalysis
from aether.ir.model import IRFunction, IRModule

from .model import SSAFunction, SSAModule
from .phi_placement import PhiPlacement
from .renaming import SSARenameError, SSARenamer
from .verifier import SSAVerificationError, SSAVerifier


class GeneralSSABuildError(ValueError):
    """Raised when experimental general SSA construction fails."""


class GeneralSSABuilder:
    """Experimental Cytron-style SSA builder for mutable slot IR.

    This builder is intentionally separate from the effective pattern-based
    ``SSABuilder``. It wires together CFG construction, dominator analysis,
    dominance-frontier phi placement, dominator-tree renaming, and SSA
    verification without changing the existing pipeline or CLI behavior.
    """

    def build(self, module: IRModule) -> SSAModule:
        return self.build_module(module)

    def build_module(self, module: IRModule) -> SSAModule:
        ssa_module = SSAModule(
            [self._build_function_unverified(function) for function in module.functions]
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
