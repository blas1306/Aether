from __future__ import annotations

from dataclasses import dataclass
import json
import re

from aether.ir.model import IRBranch, IRFunction, IRJump, IRReturn


_DOT_SIMPLE_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class CFGNode:
    name: str


@dataclass(frozen=True)
class CFGEdge:
    source: str
    target: str


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
            if isinstance(terminator, IRJump):
                edges.append(CFGEdge(block.name, terminator.target))
            elif isinstance(terminator, IRBranch):
                edges.append(CFGEdge(block.name, terminator.true_target))
                edges.append(CFGEdge(block.name, terminator.false_target))
            elif isinstance(terminator, IRReturn):
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
            lines.append(f"    {_dot_id(edge.source)} -> {_dot_id(edge.target)};")

        lines.append("}")
        return "\n".join(lines)


def _dot_id(value: str) -> str:
    if _DOT_SIMPLE_ID.fullmatch(value):
        return value
    return json.dumps(value, ensure_ascii=False)
