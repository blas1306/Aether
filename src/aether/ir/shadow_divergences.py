"""Hash-scoped reviewed divergences for Initial IR shadow verification."""

from __future__ import annotations

from dataclasses import dataclass

from .rust_verifier_client import RustVerifierPhase
from .shadow_verifier import (
    ShadowClassification,
    ShadowDiagnosticKey,
    ShadowOutcomeKey,
)
from .verification_result import VerifierCategory


@dataclass(frozen=True)
class ShadowDivergenceRule:
    """One exact canonical-request exception to ordinary parity."""

    rule_id: str
    request_sha256: str
    expected_python_key: ShadowOutcomeKey
    expected_rust_key: ShadowOutcomeKey
    protocol_version: int
    ir_schema_version: int
    classification: ShadowClassification

    def __post_init__(self) -> None:
        if len(self.request_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.request_sha256
        ):
            raise ValueError("request_sha256 must be lowercase hexadecimal SHA-256")
        allowed = {
            ShadowClassification.DOCUMENTED_DIAGNOSTIC_DIVERGENCE,
            ShadowClassification.DOCUMENTED_OUTCOME_DIVERGENCE,
        }
        if self.classification not in allowed:
            raise ValueError("divergence rules require a documented classification")


@dataclass(frozen=True)
class ExactShadowDivergenceRegistry:
    """Immutable registry whose rules match every declared field."""

    rules: tuple[ShadowDivergenceRule, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(self.rules))
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("divergence rule IDs must be unique")

    def match(
        self,
        *,
        request_hash: str,
        python_key: ShadowOutcomeKey,
        rust_key: ShadowOutcomeKey,
        protocol_version: int,
        ir_schema_version: int,
    ) -> ShadowDivergenceRule | None:
        for rule in self.rules:
            if (
                rule.request_sha256 == request_hash
                and rule.expected_python_key == python_key
                and rule.expected_rust_key == rust_key
                and rule.protocol_version == protocol_version
                and rule.ir_schema_version == ir_schema_version
            ):
                return rule
        return None


def _python_rejection(
    invariant_id: str,
    category: VerifierCategory,
) -> ShadowOutcomeKey:
    return (
        "rejected",
        ShadowDiagnosticKey(invariant_id=invariant_id, category=category),
    )


def _rust_rejection(
    invariant_id: str,
    category: VerifierCategory,
    phase: RustVerifierPhase,
    *,
    function_index: int,
    function_name: str,
    block_index: int,
    block_name: str,
    instruction_index: int,
    instruction_kind: str,
) -> ShadowOutcomeKey:
    return (
        "rejected",
        ShadowDiagnosticKey(
            invariant_id=invariant_id,
            category=category,
            phase=phase,
            function_index=function_index,
            function_name=function_name,
            block_index=block_index,
            block_name=block_name,
            instruction_index=instruction_index,
            instruction_kind=instruction_kind,
        ),
    )


DEFAULT_SHADOW_DIVERGENCE_REGISTRY = ExactShadowDivergenceRegistry(
    (
        ShadowDivergenceRule(
            rule_id="undefined-slot-representation-import-model",
            request_sha256=(
                "65b64a4021d20766e845fb23e48fd90c"
                "4992cf0f23936298e147f8b4eb6c095e"
            ),
            expected_python_key=_python_rejection(
                "IRV-031", VerifierCategory.DATA_FLOW
            ),
            expected_rust_key=_rust_rejection(
                "IRV-032",
                VerifierCategory.DATA_FLOW,
                RustVerifierPhase.LIFECYCLE,
                function_index=0,
                function_name="read",
                block_index=0,
                block_name="entry",
                instruction_index=0,
                instruction_kind="load",
            ),
            protocol_version=1,
            ir_schema_version=1,
            classification=(
                ShadowClassification.DOCUMENTED_DIAGNOSTIC_DIVERGENCE
            ),
        ),
        ShadowDivergenceRule(
            rule_id="return-storage-after-move-first-failure-ordering",
            request_sha256=(
                "90c0a3fccf6b737179d1feef9c32d11b"
                "3874edfccc3914facbd0df1d904803d9"
            ),
            expected_python_key=_python_rejection(
                "IRV-050", VerifierCategory.LIFECYCLE
            ),
            expected_rust_key=_rust_rejection(
                "IRV-026",
                VerifierCategory.RETURNS,
                RustVerifierPhase.TYPES,
                function_index=0,
                function_name="main",
                block_index=0,
                block_name="entry",
                instruction_index=3,
                instruction_kind="return",
            ),
            protocol_version=1,
            ir_schema_version=1,
            classification=(
                ShadowClassification.DOCUMENTED_DIAGNOSTIC_DIVERGENCE
            ),
        ),
        ShadowDivergenceRule(
            rule_id="inconsistent-branch-initialization-dataflow-semantics",
            request_sha256=(
                "2b1463ad529acf1b86dccd04c89408431"
                "826d51d0a0bba8739830c4e46d30d1f"
            ),
            expected_python_key=_python_rejection(
                "IRV-036", VerifierCategory.LIFECYCLE
            ),
            expected_rust_key=_rust_rejection(
                "IRV-028",
                VerifierCategory.LIFECYCLE,
                RustVerifierPhase.LIFECYCLE,
                function_index=0,
                function_name="main",
                block_index=3,
                block_name="merge",
                instruction_index=0,
                instruction_kind="return",
            ),
            protocol_version=1,
            ir_schema_version=1,
            classification=(
                ShadowClassification.DOCUMENTED_DIAGNOSTIC_DIVERGENCE
            ),
        ),
        ShadowDivergenceRule(
            rule_id="non-void-path-without-return-graph-analysis",
            request_sha256=(
                "d635f6fc4c9e933e20442539c12409fc"
                "dc3de3da0938927f6b784c3002550baa"
            ),
            expected_python_key=_python_rejection(
                "IRV-024", VerifierCategory.RETURNS
            ),
            expected_rust_key=("accepted",),
            protocol_version=1,
            ir_schema_version=1,
            classification=ShadowClassification.DOCUMENTED_OUTCOME_DIVERGENCE,
        ),
    )
)


__all__ = [
    "DEFAULT_SHADOW_DIVERGENCE_REGISTRY",
    "ExactShadowDivergenceRegistry",
    "ShadowDivergenceRule",
]
