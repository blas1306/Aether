from __future__ import annotations

import shutil

import pytest

from aether.differential import OPTIMIZATION_LEVELS, discover_cases, run_corpus


def test_profile_22_differential_corpus_is_nonempty_and_named() -> None:
    names = {case.name for case in discover_cases()}
    assert names == {
        "aggregates",
        "arguments",
        "files",
        "panic",
        "panic_division_zero",
        "panic_integer_overflow",
        "panic_list_insert",
        "panic_list_pop",
        "panic_list_remove",
        "panic_split",
        "scalars",
        "strings",
    }


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_profile_22_ast_native_observations_match_at_every_optimization_level() -> None:
    results = run_corpus()
    assert len(results) == 12
    assert all(tuple(result.native) == OPTIMIZATION_LEVELS for result in results)
