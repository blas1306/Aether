from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScalarMathStatus(str, Enum):
    CONSOLIDATED = "consolidated"
    EXPERIMENTAL = "experimental"
    FUTURE = "future"


class ScalarMathLowering(str, Enum):
    LLVM_INTRINSIC = "llvm-intrinsic"
    LIBM = "libm"
    AETHER_RUNTIME = "aether-runtime"
    UNSUPPORTED_NATIVE = "unsupported-native"


@dataclass(frozen=True)
class ScalarMathOperation:
    name: str
    arities: tuple[int, ...]
    status: ScalarMathStatus
    native_lowering: ScalarMathLowering


# This is the canonical inventory of the scalar mathematics surface that exists
# in Aether today.  In particular, it deliberately does not grow by mirroring
# Python's math module or libm.
SCALAR_MATH_OPERATIONS = {
    operation.name: operation
    for operation in (
        ScalarMathOperation("sin", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LIBM),
        ScalarMathOperation("cos", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LIBM),
        ScalarMathOperation("tan", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LIBM),
        ScalarMathOperation("exp", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LIBM),
        ScalarMathOperation("ln", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LIBM),
        ScalarMathOperation("log", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LIBM),
        ScalarMathOperation("sqrt", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LLVM_INTRINSIC),
        ScalarMathOperation("abs", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LLVM_INTRINSIC),
        ScalarMathOperation("Math.mod", (2,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.AETHER_RUNTIME),
        ScalarMathOperation("Math.factorial", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.AETHER_RUNTIME),
        ScalarMathOperation("Math.floor", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LLVM_INTRINSIC),
        ScalarMathOperation("Math.ceil", (1,), ScalarMathStatus.CONSOLIDATED, ScalarMathLowering.LLVM_INTRINSIC),
        # These names are retained for AST compatibility, but the primitive
        # complex type remains experimental and has no native ABI yet.
        ScalarMathOperation("complex", (1, 2), ScalarMathStatus.EXPERIMENTAL, ScalarMathLowering.UNSUPPORTED_NATIVE),
        ScalarMathOperation("real", (1,), ScalarMathStatus.EXPERIMENTAL, ScalarMathLowering.UNSUPPORTED_NATIVE),
        ScalarMathOperation("imag", (1,), ScalarMathStatus.EXPERIMENTAL, ScalarMathLowering.UNSUPPORTED_NATIVE),
        ScalarMathOperation("conj", (1,), ScalarMathStatus.EXPERIMENTAL, ScalarMathLowering.UNSUPPORTED_NATIVE),
        ScalarMathOperation("angle", (1,), ScalarMathStatus.EXPERIMENTAL, ScalarMathLowering.UNSUPPORTED_NATIVE),
    )
}

NATIVE_SCALAR_MATH_FUNCTIONS = frozenset(
    name
    for name, operation in SCALAR_MATH_OPERATIONS.items()
    if operation.status is ScalarMathStatus.CONSOLIDATED
)
EXPERIMENTAL_SCALAR_MATH_FUNCTIONS = frozenset(
    name
    for name, operation in SCALAR_MATH_OPERATIONS.items()
    if operation.status is ScalarMathStatus.EXPERIMENTAL
)
SCALAR_MATH_CONSTANTS = {"Math.pi": ("double", 3.141592653589793)}


def scalar_math_may_trap(name: str, argument_types: tuple[object, ...]) -> bool:
    """Return whether a checked scalar operation has an observable panic path."""

    if name in {"Math.mod", "Math.factorial"}:
        return True
    if name in {"Math.floor", "Math.ceil"}:
        return bool(argument_types) and str(argument_types[0]) != "int"
    return name == "abs" and bool(argument_types) and str(argument_types[0]) == "int"
