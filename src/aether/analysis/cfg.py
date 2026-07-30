from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aether.ir.model import IRFunction


_DOT_SIMPLE_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class CFGNode:
    name: str


@dataclass(frozen=True)
class CFGEdge:
    source: str
    target: str
    kind: str = "normal"


@dataclass(frozen=True)
class CFG:
    function_name: str
    nodes: tuple[CFGNode, ...]
    edges: tuple[CFGEdge, ...]


class CFGBuilder:
    """Build a block-level control-flow graph from lowered IR."""

    def build(self, function: IRFunction) -> CFG:
        nodes = tuple(CFGNode(block.name) for block in function.blocks)
        edges: list[CFGEdge] = []

        for block in function.blocks:
            if not block.instructions:
                continue

            terminator = block.instructions[-1]
            terminator_name = type(terminator).__name__
            if terminator_name == "IRJump":
                edges.append(CFGEdge(block.name, terminator.target))
            elif terminator_name == "IRBranch":
                edges.append(CFGEdge(block.name, terminator.true_target))
                edges.append(CFGEdge(block.name, terminator.false_target))
            elif terminator_name in {
                "IRInvoke",
                "IRInvokeIndirect",
                "IRInvokeInterface",
            }:
                edges.append(
                    CFGEdge(block.name, terminator.normal_target, "normal")
                )
                edges.append(
                    CFGEdge(
                        block.name,
                        terminator.exceptional_target,
                        "exceptional",
                    )
                )
            elif terminator_name in {"IRThrow", "IRRethrow", "IRPropagate"}:
                if terminator.target is not None:
                    edges.append(
                        CFGEdge(block.name, terminator.target, "exceptional")
                    )
            elif terminator_name == "IRReturn":
                continue

        return CFG(function.name, nodes, tuple(edges))


class DOTPrinter:
    """Print a CFG as a minimal Graphviz DOT digraph."""

    def to_dot(self, cfg: CFG) -> str:
        lines = [f"digraph {_dot_id(cfg.function_name)} {{"]

        for node in cfg.nodes:
            lines.append(f"    {_dot_id(node.name)};")

        if cfg.nodes and cfg.edges:
            lines.append("")

        for edge in cfg.edges:
            suffix = (
                ' [label="exceptional"]'
                if edge.kind == "exceptional"
                else ""
            )
            lines.append(
                f"    {_dot_id(edge.source)} -> {_dot_id(edge.target)}{suffix};"
            )

        lines.append("}")
        return "\n".join(lines)


def _dot_id(value: str) -> str:
    if _DOT_SIMPLE_ID.fullmatch(value):
        return value
    return json.dumps(value, ensure_ascii=False)
