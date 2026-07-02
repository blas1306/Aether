from __future__ import annotations

# Compatibility shim: the canonical CFG module is now aether.analysis.cfg.
from aether.analysis.cfg import CFG, CFGBuilder, CFGEdge, CFGNode, DOTPrinter

__all__ = [
    "CFG",
    "CFGBuilder",
    "CFGEdge",
    "CFGNode",
    "DOTPrinter",
]
