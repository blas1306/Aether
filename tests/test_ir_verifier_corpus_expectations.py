from __future__ import annotations

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.ir_verifier import (
    CORPUS_MANIFEST,
    CRITICAL_DIFFERENTIAL_CASES,
    CorpusComparison,
    CorpusEntry,
    _load_manifest,
    compare_verifier_observations,
)


KNOWN_PAIRS = {
    "undefined-slot": ("IRV-031", "IRV-032", "representation_import_model"),
    "return-storage-after-move": ("IRV-050", "IRV-026", "first_failure_ordering"),
    "inconsistent-branch-initialization": (
        "IRV-036",
        "IRV-028",
        "lifecycle_dataflow_semantics",
    ),
}


def test_manifest_has_only_the_three_explicit_diagnostic_divergences() -> None:
    schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    documented = {
        entry.id: (
            entry.expected_invariant,
            entry.expected_rust_invariant,
            entry.diagnostic_divergence,
        )
        for entry in entries
        if entry.diagnostic_divergence is not None
    }

    assert schema_version == 2
    assert documented == KNOWN_PAIRS


def test_manifest_keeps_the_intentional_irv_024_outcome_mismatch_explicit() -> None:
    _, entries = _load_manifest(CORPUS_MANIFEST)
    documented = {
        entry.id: (entry.expected_rust_outcome, entry.outcome_divergence)
        for entry in entries
        if entry.outcome_divergence is not None
    }

    assert documented == {
        "non-void-path-without-return": (
            "accepted",
            "intentional_irv_024_graph_analysis",
        )
    }


def test_manifest_has_exactly_one_critical_case_per_phase_4_5a_blocker() -> None:
    _, entries = _load_manifest(CORPUS_MANIFEST)
    critical = {
        entry.id: entry
        for entry in entries
        if entry.id.startswith("critical-")
    }

    assert set(critical) == set(CRITICAL_DIFFERENTIAL_CASES)
    assert {
        entry.expected_invariant for entry in critical.values()
    } == set(CRITICAL_DIFFERENTIAL_CASES.values())
    for case_id, expected_invariant in CRITICAL_DIFFERENTIAL_CASES.items():
        entry = critical[case_id]
        assert entry.accepted is False
        assert entry.expected_invariant == expected_invariant
        assert expected_invariant in entry.covers


def test_known_pairs_are_documented_divergences() -> None:
    _, entries = _load_manifest(CORPUS_MANIFEST)
    by_id = {entry.id: entry for entry in entries}

    for case_id, (python_invariant, rust_invariant, _kind) in KNOWN_PAIRS.items():
        comparison = compare_verifier_observations(
            by_id[case_id],
            python_accepted=False,
            python_invariant=python_invariant,
            rust_accepted=False,
            rust_invariant=rust_invariant,
        )

        assert comparison is CorpusComparison.DOCUMENTED_DIAGNOSTIC_DIVERGENCE


def test_comparison_separates_outcomes_from_diagnostics_and_ignores_messages() -> None:
    entry = CorpusEntry(
        id="example",
        test="tests/example.py::test_example",
        accepted=False,
        expected_invariant="IRV-001",
    )

    assert (
        compare_verifier_observations(
            entry,
            python_accepted=True,
            python_invariant=None,
            rust_accepted=False,
            rust_invariant="IRV-001",
        )
        is CorpusComparison.OUTCOME_MISMATCH
    )
    assert (
        compare_verifier_observations(
            entry,
            python_accepted=False,
            python_invariant="IRV-001",
            rust_accepted=False,
            rust_invariant="IRV-001",
        )
        is CorpusComparison.EXACT_DIAGNOSTIC_MATCH
    )
    assert (
        compare_verifier_observations(
            entry,
            python_accepted=False,
            python_invariant="IRV-001",
            rust_accepted=False,
            rust_invariant="IRV-002",
        )
        is CorpusComparison.UNEXPECTED_DIAGNOSTIC_DIVERGENCE
    )
    assert (
        compare_verifier_observations(
            entry,
            python_accepted=True,
            python_invariant=None,
            rust_accepted=True,
            rust_invariant=None,
        )
        is None
    )


def test_a_documented_case_still_rejects_an_unexpected_pair() -> None:
    _, entries = _load_manifest(CORPUS_MANIFEST)
    entry = next(item for item in entries if item.id == "undefined-slot")

    comparison = compare_verifier_observations(
        entry,
        python_accepted=False,
        python_invariant="IRV-031",
        rust_accepted=False,
        rust_invariant="IRV-050",
    )

    assert comparison is CorpusComparison.UNEXPECTED_DIAGNOSTIC_DIVERGENCE
