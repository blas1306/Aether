"""Eliminate SSA bounds checks only when O2.1 proves the full obligation."""
from __future__ import annotations

from dataclasses import replace

from aether.ssa.analysis.proof_coverage import CheckProof, ProofCoverageAudit
from aether.ssa.model import (
    SSAArrayGet,
    SSAArraySet,
    SSABasicBlock,
    SSAFunction,
    SSAMatrixGet,
    SSAMatrixSet,
    SSAModule,
    SSAVectorGet,
    SSAVectorSet,
)

from .result import SSAOptimizationResult


class ProvenBoundsCheckEliminator:
    """Mark supported accesses unchecked after an exact PROVEN_SAFE audit proof.

    Matrix checks use one runtime helper, so both independently audited row and
    column obligations must be safe before that helper is removed. Slicing and
    List checks deliberately remain outside the O2.2 transformation scope.
    """

    _SUPPORTED = (
        SSAArrayGet, SSAArraySet, SSAVectorGet, SSAVectorSet,
        SSAMatrixGet, SSAMatrixSet,
    )

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        report = ProofCoverageAudit().audit(module)
        by_site: dict[tuple[str, str, int], list] = {}
        for check in report.checks:
            by_site.setdefault(
                (check.function, check.block, check.instruction_index), []
            ).append(check)

        stats = {
            "checks_examined": len(report.checks),
            "checks_removed": 0,
            "bounds_checks_removed": 0,
            "shape_checks_removed": 0,
            "checks_preserved_unknown": sum(
                check.proof == CheckProof.UNKNOWN.value for check in report.checks
            ),
            "checks_preserved_proven_unsafe": sum(
                check.proof == CheckProof.PROVEN_UNSAFE.value for check in report.checks
            ),
            "array_checks_removed": 0,
            "list_checks_removed": 0,
            "vector_checks_removed": 0,
            "matrix_checks_removed": 0,
            "slicing_checks_removed": 0,
        }
        functions: list[SSAFunction] = []
        for function in module.functions:
            blocks: list[SSABasicBlock] = []
            for block in function.blocks:
                instructions = []
                for index, instruction in enumerate(block.instructions):
                    checks = by_site.get((function.name, block.name, index), ())
                    if (
                        isinstance(instruction, self._SUPPORTED)
                        and checks
                        and all(check.proof == CheckProof.PROVEN_SAFE.value for check in checks)
                    ):
                        instruction = replace(instruction, bounds_checked=False)
                        removed = len(checks)
                        stats["checks_removed"] += removed
                        stats["bounds_checks_removed"] += removed
                        domain = checks[0].domain.lower()
                        stats[f"{domain}_checks_removed"] += removed
                    instructions.append(instruction)
                blocks.append(SSABasicBlock(block.name, instructions))
            functions.append(SSAFunction(
                function.name, list(function.parameters), function.return_type,
                blocks, function.entry_block, function.may_throw,
            ))
        optimized = SSAModule(functions, list(module.structs))
        if optimized == module:
            optimized = module
        return SSAOptimizationResult(
            optimized, changed=optimized is not module, stats=stats
        )
