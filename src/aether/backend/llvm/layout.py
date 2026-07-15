from __future__ import annotations

from dataclasses import dataclass

from aether.ir.model import IRStructDefinition
from aether.ir.types import (
    ArrayType,
    BoolType,
    ClassRefType,
    ComplexType,
    DoubleType,
    EnumType,
    FloatType,
    FunctionType,
    IntType,
    InterfaceType,
    IRType,
    ListType,
    MatrixType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)

from .types import LLVMBackendError, llvm_type


@dataclass(frozen=True)
class TypeLayout:
    """Backend storage facts for a value type.

    ``size_operand`` is an LLVM i64 constant expression rather than a host
    integer when the target controls the size.  Consequently struct padding,
    nested aggregates, and pointer width are all decided by LLVM's DataLayout.
    Natural load/store alignment and allocator alignment provide the equivalent
    alignment contract; Aether never computes field offsets itself.
    """

    llvm_type: str
    sized: bool
    size_operand: str | None
    trivially_copyable: bool
    trivially_relocatable: bool
    needs_destroy: bool
    contains_references: bool
    needs_retain: bool
    supported_as_collection_element: bool
    reason: str | None = None
    alignment: str = "target-natural"


class LLVMTypeLayouts:
    """Canonical recursive layout registry for one combined LLVM module."""

    def __init__(self, structs: list[IRStructDefinition]) -> None:
        self._structs = {definition.name: definition for definition in structs}
        self._cache: dict[IRType, TypeLayout] = {}
        self._active: list[str] = []

    def layout(self, type_: IRType) -> TypeLayout:
        cached = self._cache.get(type_)
        if cached is not None:
            return cached
        result = self._compute(type_)
        self._cache[type_] = result
        return result

    def collection_element(self, collection: str, type_: IRType) -> TypeLayout:
        layout = self.layout(type_)
        if not layout.supported_as_collection_element:
            reason = layout.reason or "the type has no supported value-copy layout"
            raise LLVMBackendError(
                f"LLVM/native {collection} cannot store element type '{type_}': {reason}"
            )
        if not layout.sized or layout.size_operand is None:
            raise LLVMBackendError(
                f"LLVM/native {collection} cannot store element type '{type_}': "
                "the LLVM type is incomplete or unsized"
            )
        return layout

    def _compute(self, type_: IRType) -> TypeLayout:
        if isinstance(type_, IntType):
            return self._fixed(type_, 4)
        if isinstance(type_, EnumType):
            return self._fixed(type_, 4)
        if isinstance(type_, BoolType):
            return self._fixed(type_, 1)
        if isinstance(type_, DoubleType):
            return self._fixed(type_, 8)
        if isinstance(type_, StringType):
            rendered = llvm_type(type_)
            size = f"ptrtoint (ptr getelementptr ({rendered}, ptr null, i64 1) to i64)"
            return TypeLayout(rendered, True, size, False, True, True, True, True, True)
        if isinstance(type_, (ArrayType, ListType, VectorType, MatrixType)):
            return self._reference(type_)
        if isinstance(type_, StructType):
            return self._struct(type_)
        if isinstance(type_, FunctionType):
            return self._unsupported(
                type_, "callable value-copy semantics inside aggregate collections are not defined"
            )
        if isinstance(type_, (ClassRefType, InterfaceType)):
            return self._unsupported(
                type_, "class/interface references are outside the LLVM/native collection subset"
            )
        if isinstance(type_, FloatType):
            return self._unsupported(type_, "float is not represented by the current LLVM/native backend")
        if isinstance(type_, ComplexType):
            return self._unsupported(type_, "complex is not represented by the current LLVM/native backend")
        if isinstance(type_, NullableType):
            return self._unsupported(type_, "nullable values have no current LLVM/native storage ABI")
        if isinstance(type_, VoidType):
            return self._unsupported(type_, "void is unsized")
        return self._unsupported(type_, "the backend has no storage layout for this type")

    @staticmethod
    def _fixed(type_: IRType, size: int) -> TypeLayout:
        return TypeLayout(llvm_type(type_), True, str(size), True, True, False, False, False, True)

    @staticmethod
    def _reference(type_: IRType) -> TypeLayout:
        rendered = llvm_type(type_)
        size = f"ptrtoint (ptr getelementptr ({rendered}, ptr null, i64 1) to i64)"
        return TypeLayout(rendered, True, size, True, True, False, True, False, True)

    def _struct(self, type_: StructType) -> TypeLayout:
        definition = self._structs.get(type_.name)
        if definition is None:
            return self._unsupported(type_, f"nominal struct '{type_.name}' has no complete LLVM definition")
        if type_.name in self._active:
            cycle = " -> ".join((*self._active, type_.name))
            return self._unsupported(type_, f"recursive by-value layout has infinite size ({cycle})")

        self._active.append(type_.name)
        try:
            field_layouts = [self.layout(field_type) for _name, field_type in definition.fields]
        finally:
            self._active.pop()

        for (field_name, field_type), field_layout in zip(definition.fields, field_layouts):
            if not field_layout.supported_as_collection_element:
                detail = field_layout.reason or "unsupported storage semantics"
                return self._unsupported(
                    type_, f"field '{field_name}' of type '{field_type}' is unsupported: {detail}"
                )
            if not field_layout.sized:
                return self._unsupported(
                    type_, f"field '{field_name}' of type '{field_type}' is incomplete or unsized"
                )
        rendered = llvm_type(type_)
        size = f"ptrtoint (ptr getelementptr ({rendered}, ptr null, i64 1) to i64)"
        return TypeLayout(
            rendered,
            True,
            size,
            all(field.trivially_copyable for field in field_layouts),
            all(field.trivially_relocatable for field in field_layouts),
            any(field.needs_destroy for field in field_layouts),
            any(field.contains_references for field in field_layouts),
            any(field.needs_retain for field in field_layouts),
            True,
        )

    @staticmethod
    def _unsupported(type_: IRType, reason: str) -> TypeLayout:
        try:
            rendered = llvm_type(type_)
        except LLVMBackendError:
            rendered = "<unsupported>"
        return TypeLayout(rendered, False, None, False, False, False, False, False, False, reason)
