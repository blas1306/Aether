from __future__ import annotations

from dataclasses import dataclass, replace

from aether.analysis.cfg import CFG, CFGEdge, CFGNode

from .model import (
    SSABasicBlock,
    SSABranch,
    SSAFunction,
    SSAInstruction,
    SSAInvoke,
    SSAInvokeIndirect,
    SSAInvokeInterface,
    SSAJump,
    SSAPhi,
    SSAPropagate,
    SSARethrow,
    SSAThrow,
    SSAValue,
)


@dataclass(frozen=True)
class SSACFGEdge:
    source: str
    target: str
    kind: str
    arguments: tuple[SSAValue, ...] = ()


class SSACFGBuilder:
    """Build the complete SSA CFG with deterministic typed edge ordering."""

    def build(self, function: SSAFunction) -> CFG:
        return CFG(
            function.name,
            tuple(CFGNode(block.name) for block in function.blocks),
            tuple(
                CFGEdge(edge.source, edge.target, edge.kind)
                for block in function.blocks
                for edge in successor_edges(block)
            ),
        )


def successor_edges(block: SSABasicBlock) -> tuple[SSACFGEdge, ...]:
    if not block.instructions:
        return ()
    terminator = block.instructions[-1]
    if isinstance(terminator, SSAJump):
        return (SSACFGEdge(block.name, terminator.target, "normal"),)
    if isinstance(terminator, SSABranch):
        return (
            SSACFGEdge(block.name, terminator.true_target, "normal"),
            SSACFGEdge(block.name, terminator.false_target, "normal"),
        )
    if isinstance(
        terminator,
        (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface),
    ):
        return (
            SSACFGEdge(
                block.name,
                terminator.normal_target,
                "normal",
                terminator.normal_arguments,
            ),
            SSACFGEdge(
                block.name,
                terminator.exceptional_target,
                "exceptional",
                terminator.exceptional_arguments,
            ),
        )
    if isinstance(terminator, (SSAThrow, SSARethrow, SSAPropagate)):
        if terminator.target is None:
            return ()
        return (
            SSACFGEdge(
                block.name,
                terminator.target,
                "exceptional",
                terminator.exceptional_arguments,
            ),
        )
    return ()


def predecessors(function: SSAFunction) -> dict[str, tuple[SSACFGEdge, ...]]:
    result: dict[str, list[SSACFGEdge]] = {
        block.name: [] for block in function.blocks
    }
    for block in function.blocks:
        for edge in successor_edges(block):
            result[edge.target].append(edge)
    return {name: tuple(edges) for name, edges in result.items()}


def reachable_blocks(function: SSAFunction) -> tuple[str, ...]:
    blocks = {block.name: block for block in function.blocks}
    if function.entry_block not in blocks:
        return ()
    visited: set[str] = set()
    ordered: list[str] = []
    worklist = [function.entry_block]
    while worklist:
        name = worklist.pop()
        if name in visited:
            continue
        visited.add(name)
        ordered.append(name)
        worklist.extend(
            reversed(
                [
                    edge.target
                    for edge in successor_edges(blocks[name])
                    if edge.target not in visited
                ]
            )
        )
    return tuple(ordered)


def reverse_postorder(function: SSAFunction) -> tuple[str, ...]:
    blocks = {block.name: block for block in function.blocks}
    if function.entry_block not in blocks:
        return ()
    visited: set[str] = set()
    postorder: list[str] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for edge in successor_edges(blocks[name]):
            visit(edge.target)
        postorder.append(name)

    visit(function.entry_block)
    postorder.reverse()
    return tuple(postorder)


def rewrite_edge(
    terminator: SSAInstruction,
    *,
    old_target: str,
    new_target: str,
) -> SSAInstruction:
    """Return a terminator with one target rewritten and edge kind retained."""

    if isinstance(terminator, SSAJump):
        return (
            replace(terminator, target=new_target)
            if terminator.target == old_target
            else terminator
        )
    if isinstance(terminator, SSABranch):
        return replace(
            terminator,
            true_target=(
                new_target
                if terminator.true_target == old_target
                else terminator.true_target
            ),
            false_target=(
                new_target
                if terminator.false_target == old_target
                else terminator.false_target
            ),
        )
    if isinstance(
        terminator,
        (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface),
    ):
        return replace(
            terminator,
            normal_target=(
                new_target
                if terminator.normal_target == old_target
                else terminator.normal_target
            ),
            exceptional_target=(
                new_target
                if terminator.exceptional_target == old_target
                else terminator.exceptional_target
            ),
        )
    if isinstance(terminator, (SSAThrow, SSARethrow, SSAPropagate)):
        return (
            replace(terminator, target=new_target)
            if terminator.target == old_target
            else terminator
        )
    raise TypeError(f"{type(terminator).__name__} is not an SSA CFG terminator")


def remove_unreachable_blocks(function: SSAFunction) -> SSAFunction:
    """Drop only blocks unreachable through the complete normal+exception CFG."""

    reachable = set(reachable_blocks(function))
    if len(reachable) == len(function.blocks):
        return function
    blocks = []
    for block in function.blocks:
        if block.name not in reachable:
            continue
        instructions = [
            (
                SSAPhi(
                    instruction.result,
                    tuple(
                        (source, value)
                        for source, value in instruction.incoming
                        if source in reachable
                    ),
                )
                if isinstance(instruction, SSAPhi)
                else instruction
            )
            for instruction in block.instructions
        ]
        blocks.append(SSABasicBlock(block.name, instructions))
    return SSAFunction(
        function.name,
        list(function.parameters),
        function.return_type,
        blocks,
        function.entry_block,
        function.may_throw,
    )
