"""Eliminate SSA bounds checks only when O2.1 proves the full obligation."""
from __future__ import annotations

from dataclasses import replace

from aether.ssa.analysis.proof_coverage import CheckProof, ProofCoverageAudit
from aether.ssa.analysis.alias_modref import SummaryAnalysis
from aether.ssa.model import (
    SSAArrayGet,
    SSAArraySet,
    SSABasicBlock,
    SSAFunction,
    SSAMatrixGet,
    SSAMatrixSet,
    SSAListGet,
    SSAListSet,
    SSAModule,
    SSAVectorGet,
    SSAVectorSet,
)

from .result import SSAOptimizationResult


class ProvenBoundsCheckEliminator:
    """Mark supported accesses unchecked after an exact PROVEN_SAFE audit proof.

    Matrix checks use one runtime helper, so both independently audited row and
    column obligations must be safe before that helper is removed. Slicing and
    List checks additionally require O2.4 alias/mod-ref fact preservation.
    """

    _SUPPORTED = (
        SSAArrayGet, SSAArraySet, SSAVectorGet, SSAVectorSet,
        SSAMatrixGet, SSAMatrixSet,
        SSAListGet, SSAListSet,
    )

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        summaries = SummaryAnalysis().compute(module)
        report = ProofCoverageAudit().audit(module, summaries=summaries)
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
            "list_checks_examined": sum(check.domain == "List" for check in report.checks),
            "list_checks_preserved_unknown": sum(
                check.domain == "List" and check.proof == CheckProof.UNKNOWN.value
                for check in report.checks
            ),
            "list_checks_alias_invalidated": sum(
                check.domain == "List" and check.unknown_reason == "ALIAS_UNCERTAINTY"
                for check in report.checks
            ),
            "list_checks_modref_invalidated": sum(
                check.domain == "List" and check.unknown_reason == "MUTATION_INVALIDATION"
                for check in report.checks
            ),
            "list_checks_call_invalidated": sum(
                check.domain == "List" and check.unknown_reason in {"CALL_INVALIDATION", "EXCEPTION_EDGE"}
                for check in report.checks
            ),
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
