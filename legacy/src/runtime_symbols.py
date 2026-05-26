from __future__ import annotations

from typing import Any, Mapping, MutableMapping


def build_runtime_shared_symbols(
    *,
    math_aliases: Mapping[str, Any],
    runtime_helpers: Mapping[str, Any],
    octave_helpers: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "_mt_norm": math_aliases["norm"],
        "_mt_min": runtime_helpers["mt_min"],
        "_mt_max": runtime_helpers["mt_max"],
        "_mt_length": runtime_helpers["mt_length"],
        "_mt_numel": runtime_helpers["mt_numel"],
        "_mt_nchoosek": runtime_helpers["mt_nchoosek"],
        "_mt_solve": runtime_helpers["mt_solve"],
        "_mt_bar": runtime_helpers["mt_bar"],
        "_mt_sin": math_aliases["sin"],
        "_mt_cos": math_aliases["cos"],
        "_mt_tan": math_aliases["tan"],
        "_mt_sinh": math_aliases["sinh"],
        "_mt_cosh": math_aliases["cosh"],
        "_mt_tanh": math_aliases["tanh"],
        "_mt_asin": math_aliases["asin"],
        "_mt_acos": math_aliases["acos"],
        "_mt_atan": math_aliases["atan"],
        "_mt_exp": math_aliases["exp"],
        "_mt_ln": math_aliases["ln"],
        "_mt_log": math_aliases["log"],
        "_mt_sqrt": math_aliases["sqrt"],
        "_mt_nthroot": math_aliases["nthroot"],
        "_mt_abs": math_aliases["abs"],
        "_mt_sign": math_aliases["sign"],
        "_mt_floor": math_aliases["floor"],
        "_mt_ceiling": math_aliases["ceiling"],
        "_mt_linspace": runtime_helpers["mt_linspace"],
        "_rand_matrix": runtime_helpers["rand_matrix"],
        "_randi_matrix": runtime_helpers["randi_matrix"],
        "_orth": runtime_helpers["orth"],
        "_mat_null": runtime_helpers["mat_null"],
        "_mt_mul": runtime_helpers["mt_mul"],
        "_mt_div": runtime_helpers["mt_div"],
        "_mt_pow": runtime_helpers["mt_pow"],
        "_mt_ew_mul": runtime_helpers["mt_ew_mul"],
        "_mt_ew_div": runtime_helpers["mt_ew_div"],
        "_mt_ew_pow": runtime_helpers["mt_ew_pow"],
        "_mt_transpose": runtime_helpers["mt_transpose"],
        "_mt_adj": runtime_helpers["mt_adj"],
        "_mt_call": runtime_helpers["mt_call"],
        "_mt_apply_symbol": runtime_helpers["mt_apply_symbol"],
        "_mt_matrix_literal": runtime_helpers["mt_matrix_literal"],
        "_oct_range": octave_helpers["range"],
        "_oct_get1": octave_helpers["get1"],
        "_oct_get2": octave_helpers["get2"],
        "_oct_get_any": octave_helpers["get_any"],
        "_oct_set1": octave_helpers["set1"],
        "_oct_set2": octave_helpers["set2"],
        "_oct_set_slice": octave_helpers["set_slice"],
        "_oct_slice": octave_helpers["slice"],
        "_oct_span": octave_helpers["span"],
    }


def register_shared_symbols(
    common_symbols: MutableMapping[str, Any],
    parser_local_dict: MutableMapping[str, Any],
    updates: Mapping[str, Any],
) -> None:
    common_symbols.update(updates)
    parser_local_dict.update(updates)
