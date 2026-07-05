from __future__ import annotations

from aether.ssa.model import SSAFunction, SSAModule

from .result import SSAOptimizationResult
from .sccp import SCCPAnalyzer, SCCPTransformer


class SCCPPass:
    """Run SCCP analysis and transformation as a normal SSA optimizer pass."""

    _STAT_KEYS = (
        "replaced_constants",
        "simplified_branches",
        "removed_blocks",
        "removed_phi_incomings",
    )

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        changed = False
        stats = {key: 0 for key in self._STAT_KEYS}

        for function in module.functions:
            analysis = SCCPAnalyzer(function).analyze()
            transformation = SCCPTransformer(SSAModule([function]), analysis).run()

            for key, value in transformation.stats.items():
                stats[key] = stats.get(key, 0) + value

            if transformation.changed:
                changed = True
                updated_functions.extend(transformation.module.functions)
            else:
                updated_functions.append(function)

        if not changed:
            return SSAOptimizationResult(module, changed=False, stats=stats)

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats=stats,
        )
