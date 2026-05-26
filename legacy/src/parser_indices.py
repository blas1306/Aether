from __future__ import annotations

import re
from typing import Callable

from diagnostics import make_parse_error
from mathtex_ast import ASTNode, RangeNode, SliceNode, SymbolNode
from parser_common import _find_matching_paren, _split_top_level
from parsers import ParserContext


ParseMathtexExpr = Callable[[str, ParserContext], ASTNode]
NormalizeName = Callable[[str], str]


def parse_index_component(
    component: str,
    ctx: ParserContext,
    parse_mathtex_expr: ParseMathtexExpr,
) -> SliceNode:
    cleaned = component.strip()
    if not cleaned:
        raise make_parse_error(
            "empty-index",
            "Index expression is empty.",
            source=component,
            hint="Add an index value or ':' for a full slice.",
        )
    if cleaned == ":":
        return SliceNode(RangeNode(None, None, None))

    range_parts = [part.strip() for part in _split_top_level(cleaned, ":")]
    if len(range_parts) in {2, 3} and any(not part for part in range_parts):
        raise make_parse_error(
            "incomplete-range",
            "Index range is incomplete.",
            source=component,
            hint="Use start:end or start:step:end.",
        )
    if len(range_parts) in {2, 3} and all(range_parts):
        start_ast = parse_mathtex_expr(range_parts[0], ctx)
        if len(range_parts) == 2:
            end_ast = parse_mathtex_expr(range_parts[1], ctx)
            return SliceNode(RangeNode(start_ast, None, end_ast))
        step_ast = parse_mathtex_expr(range_parts[1], ctx)
        end_ast = parse_mathtex_expr(range_parts[2], ctx)
        return SliceNode(RangeNode(start_ast, step_ast, end_ast))

    return SliceNode(parse_mathtex_expr(cleaned, ctx))


def parse_indexed_assignment_lhs(
    lhs: str,
    ctx: ParserContext,
    parse_mathtex_expr: ParseMathtexExpr,
    normalize_name: NormalizeName,
) -> tuple[SymbolNode, list[SliceNode]] | None:
    match = re.match(r"^(\\?[A-Za-z_]\w*)\s*\(", lhs)
    if not match:
        return None

    name_raw = match.group(1)
    open_idx = lhs.find("(", match.start(0))
    if open_idx < 0:
        return None
    close_idx = _find_matching_paren(lhs, open_idx)
    if close_idx is None:
        raise make_parse_error(
            "unclosed-delimiter",
            "Indexed assignment parenthesis '(' was never closed.",
            source=lhs,
            column=open_idx + 1,
            hint="Add ')' to close the indexed assignment target.",
        )
    if lhs[close_idx + 1 :].strip():
        return None

    inside = lhs[open_idx + 1 : close_idx].strip()
    if not inside:
        raise make_parse_error(
            "empty-index",
            "Indexed assignment has an empty index list.",
            source=lhs,
            column=open_idx + 1,
            hint="Add at least one index inside the parentheses.",
        )
    parts = [part.strip() for part in _split_top_level(inside, ",")]
    if len(parts) not in {1, 2}:
        return None
    if any(not part for part in parts):
        raise make_parse_error(
            "empty-index",
            "Indexed assignment contains an empty index.",
            source=lhs,
            column=open_idx + 1,
            hint="Fill in each index position or remove the extra comma.",
        )

    indices = [parse_index_component(part, ctx, parse_mathtex_expr) for part in parts]
    return SymbolNode(normalize_name(name_raw)), indices
