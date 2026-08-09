"""Collection length and linear-algebra shape facts with provenance."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aether.ir.types import ArrayType, ListType, MatrixType, VectorType
from aether.ssa.cfg import predecessors, reverse_postorder
from aether.ssa.model import (
    SSAArrayCopy, SSAArrayLength, SSAArrayNew, SSAArraySlice, SSACall,
    SSACallIndirect, SSAFunction, SSAInterfaceCall, SSAInvoke, SSAInvokeIndirect,
    SSAInvokeInterface, SSAListClear, SSAListCopy, SSAListInsert, SSAListLength,
    SSAListNew, SSAListPop, SSAListPush, SSAListRemoveAt, SSAListSlice,
    SSAMatrixColumns, SSAMatrixNew, SSAMatrixRows, SSAValue, SSAVectorLength,
    SSAVectorNew,
)

if TYPE_CHECKING:
    from .alias_modref import ModRefAnalysis


@dataclass(frozen=True)
class LengthFact:
    collection: SSAValue
    value: SSAValue | None = None
    constant: int | None = None
    provenance: str = "runtime"
    stable: bool = False


@dataclass(frozen=True)
class VectorShapeFact:
    vector: SSAValue
    length: int | None
    orientation: str | None
    provenance: str
    stable: bool = True


@dataclass(frozen=True)
class MatrixShapeFact:
    matrix: SSAValue
    rows: int | None
    columns: int | None
    provenance: str
    stable: bool = True


@dataclass(frozen=True)
class ShapeAnalysisResult:
    _lengths: dict[str, dict[SSAValue, LengthFact]]
    _vectors: dict[str, dict[SSAValue, VectorShapeFact]]
    _matrices: dict[str, dict[SSAValue, MatrixShapeFact]]

    def length_of(self, value: SSAValue, block: str) -> LengthFact | None:
        return self._lengths.get(block, {}).get(value)
    def vector_shape_of(self, value: SSAValue, block: str) -> VectorShapeFact | None:
        return self._vectors.get(block, {}).get(value)
    def matrix_shape_of(self, value: SSAValue, block: str) -> MatrixShapeFact | None:
        return self._matrices.get(block, {}).get(value)
    def verify(self) -> None:
        for facts in self._vectors.values():
            if any(fact.length is not None and fact.length < 0 for fact in facts.values()):
                raise ValueError("negative vector dimension in shape facts")
        for facts in self._matrices.values():
            if any((fact.rows is not None and fact.rows < 0) or (fact.columns is not None and fact.columns < 0) for fact in facts.values()):
                raise ValueError("negative matrix dimension in shape facts")
    def debug_string(self) -> str:
        lines = []
        for block in self._lengths:
            lengths = ", ".join(f"{v.name}={f.constant if f.constant is not None else f.value.name if f.value else '?'}:{f.provenance}" for v, f in sorted(self._lengths[block].items(), key=lambda item:item[0].name))
            vectors = ", ".join(f"{v.name}=({f.length},{f.orientation})" for v, f in sorted(self._vectors[block].items(), key=lambda item:item[0].name))
            matrices = ", ".join(f"{v.name}=({f.rows}x{f.columns})" for v, f in sorted(self._matrices[block].items(), key=lambda item:item[0].name))
            lines.append(f"{block}: lengths[{lengths}] vectors[{vectors}] matrices[{matrices}]")
        return "\n".join(lines)


class ShapeAnalysis:
    """Forward must-fact analysis; unknown calls invalidate mutable List facts."""
    def compute(
        self,
        function: SSAFunction,
        modref: "ModRefAnalysis | None" = None,
    ) -> ShapeAnalysisResult:
        blocks = {block.name: block for block in function.blocks}; pred = predecessors(function); order = reverse_postorder(function)
        lengths = {name: {} for name in blocks}; vectors = {name: {} for name in blocks}; matrices = {name: {} for name in blocks}
        changed = True; iterations = 0; limit = max(1, len(blocks) * 4)
        while changed and iterations < limit:
            changed = False; iterations += 1
            for name in order:
                sources = [edge.source for edge in pred[name]]
                ls = _must_join([lengths[source] for source in sources]) if sources else {}
                vs = _must_join([vectors[source] for source in sources]) if sources else {}
                ms = _must_join([matrices[source] for source in sources]) if sources else {}
                for instruction in blocks[name].instructions:
                    result = getattr(instruction, "result", None)
                    if isinstance(instruction, SSAArrayNew): ls[result] = LengthFact(result, constant=len(instruction.elements), provenance="constructor", stable=True)
                    elif isinstance(instruction, SSAListNew): ls[result] = LengthFact(result, constant=len(instruction.elements), provenance="constructor")
                    elif isinstance(instruction, SSAArrayCopy):
                        fact = ls.get(instruction.array); ls[result] = LengthFact(result, fact.value if fact else None, fact.constant if fact else None, "array-copy", True)
                    elif isinstance(instruction, SSAListCopy):
                        fact = ls.get(instruction.list_value); ls[result] = LengthFact(result, fact.value if fact else None, fact.constant if fact else None, "list-copy")
                    elif isinstance(instruction, SSAArrayLength):
                        existing = ls.get(instruction.array); ls[instruction.array] = LengthFact(instruction.array, result, existing.constant if existing else None, "array-length", True)
                    elif isinstance(instruction, SSAListLength):
                        existing = ls.get(instruction.list_value); ls[instruction.list_value] = LengthFact(instruction.list_value, result, existing.constant if existing else None, "list-length")
                    elif isinstance(instruction, (SSAArraySlice, SSAListSlice)):
                        collection = result; ls[collection] = LengthFact(collection, provenance="slice-result", stable=isinstance(instruction, SSAArraySlice))
                    elif isinstance(instruction, SSAVectorNew):
                        fact = VectorShapeFact(result, len(instruction.elements), instruction.orientation, "constructor"); vs[result] = fact; ls[result] = LengthFact(result, constant=fact.length, provenance="vector-shape", stable=True)
                    elif isinstance(instruction, SSAVectorLength):
                        existing = vs.get(instruction.vector); ls[instruction.vector] = LengthFact(instruction.vector, result, existing.length if existing else None, "vector-length", True)
                    elif isinstance(instruction, SSAMatrixNew): ms[result] = MatrixShapeFact(result, instruction.rows, instruction.cols, "constructor")
                    elif isinstance(instruction, SSAMatrixRows):
                        existing = ms.get(instruction.matrix); ms[instruction.matrix] = MatrixShapeFact(instruction.matrix, instruction.rows, existing.columns if existing else None, "matrix-rows")
                    elif isinstance(instruction, SSAMatrixColumns):
                        existing = ms.get(instruction.matrix); ms[instruction.matrix] = MatrixShapeFact(instruction.matrix, existing.rows if existing else None, instruction.columns, "matrix-columns")
                    # Arithmetic shape instructions already carry the checked
                    # static dimensions selected by type checking/lowering.
                    elif isinstance(result, SSAValue) and isinstance(result.type, VectorType) and hasattr(instruction, "length"):
                        length = getattr(instruction, "length")
                        orientation = getattr(instruction, "orientation", result.type.orientation)
                        vs[result] = VectorShapeFact(result, length, orientation, "instruction-metadata")
                        ls[result] = LengthFact(result, constant=length, provenance="vector-shape", stable=True)
                    elif isinstance(result, SSAValue) and isinstance(result.type, MatrixType) and hasattr(instruction, "rows"):
                        rows = getattr(instruction, "rows"); columns = getattr(instruction, "cols", None)
                        ms[result] = MatrixShapeFact(result, rows, columns, "instruction-metadata")
                    if isinstance(instruction, (SSAListClear, SSAListPush, SSAListInsert, SSAListRemoveAt, SSAListPop)):
                        if modref is None:
                            ls.pop(instruction.list_value, None)
                        else:
                            ls = {
                                value: fact for value, fact in ls.items()
                                if modref.preserves_length_fact(instruction, value)
                            }
                    if isinstance(instruction, (SSACall, SSACallIndirect, SSAInterfaceCall, SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface)) and instruction.writes_memory:
                        ls = {
                            value: fact for value, fact in ls.items()
                            if not isinstance(value.type, ListType)
                            or (modref is not None and modref.preserves_length_fact(instruction, value))
                        }
                if ls != lengths[name] or vs != vectors[name] or ms != matrices[name]:
                    lengths[name], vectors[name], matrices[name] = ls, vs, ms; changed = True
        result = ShapeAnalysisResult(lengths, vectors, matrices)
        result.verify()
        return result


def _must_join(maps):
    if not maps: return {}
    keys = set(maps[0]).intersection(*(set(item) for item in maps[1:]))
    return {key: maps[0][key] for key in keys if all(item[key] == maps[0][key] for item in maps[1:])}
