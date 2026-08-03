from __future__ import annotations

import json

from aether.exception_evidence import (
    INTERPRETER_STAGES,
    REPORT_PATH,
    capability_errors,
    catalog_errors,
    load_catalog,
    negative_errors,
    run_corpus,
)


def test_exception_promotion_release_contract_is_complete_and_fail_closed() -> None:
    positives, negatives = load_catalog()

    assert catalog_errors() == []
    assert capability_errors(positives) == []
    assert negative_errors(negatives) == []

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["requirement"] == "ERQ-006"
    assert report["status"] == "passed"
    assert report["capability_promotion"] == "not-performed"
    assert report["error_handling_state"] == "UNSUPPORTED"
    assert report["summary"]["positive_programs"] == len(positives)
    assert report["summary"]["negative_programs"] == len(negatives)
    assert report["summary"]["stage_comparisons"] == 77


def test_exception_corpus_matches_every_executable_interpreter_stage() -> None:
    results = run_corpus(native=False)

    assert results
    for result in results:
        assert tuple(result.stages) == INTERPRETER_STAGES
        expected = result.case.expected
        for observation in result.stages.values():
            assert observation.stdout == expected.stdout
            assert observation.stderr == expected.stderr
            assert observation.selected_handlers == expected.selected_handlers
            assert observation.termination == expected.termination
            assert observation.message == expected.message
            assert observation.exit_status == expected.exit_status
            assert observation.cleanup == "verified"
            assert observation.ownership == "verified"
