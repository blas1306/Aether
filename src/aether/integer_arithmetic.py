from __future__ import annotations

from math import copysign, nan


INT_MIN = -(2**31)
INT_MAX = 2**31 - 1

DIVISION_BY_ZERO_MESSAGE = "Aether panic: Division by zero"
INTEGER_OVERFLOW_MESSAGE = "Aether panic: Integer overflow"
CHECKED_INT_OPERATORS = frozenset({"add", "sub", "mul", "div", "mod", "rem"})


def is_aether_int(value: object) -> bool:
    """Return whether ``value`` is a valid Aether signed i32 value."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and INT_MIN <= value <= INT_MAX
    )


def integer_literal_range_message(value: int) -> str:
    return (
        f"Integer literal {value} is outside the range of Aether int "
        f"[{INT_MIN}, {INT_MAX}]."
    )


def int_operator_may_trap(operator: str) -> bool:
    return operator in CHECKED_INT_OPERATORS


def checked_int_binary(operator: str, left: int, right: int) -> int | float:
    """Evaluate one Aether int operation without host-language overflow semantics."""
    if operator in {"div", "mod", "rem"} and right == 0:
        raise ZeroDivisionError(DIVISION_BY_ZERO_MESSAGE)
    if operator == "div" and left == INT_MIN and right == -1:
        raise OverflowError(INTEGER_OVERFLOW_MESSAGE)

    if operator == "add":
        result: int | float = left + right
    elif operator == "sub":
        result = left - right
    elif operator == "mul":
        result = left * right
    elif operator == "div":
        return left / right
    elif operator in {"mod", "rem"}:
        quotient = abs(left) // abs(right)
        if (left < 0) != (right < 0):
            quotient = -quotient
        return left - quotient * right
    else:
        raise AssertionError(f"Unsupported checked int operator: {operator}")

    if result < INT_MIN or result > INT_MAX:
        raise OverflowError(INTEGER_OVERFLOW_MESSAGE)
    return result


def checked_int_negate(value: int) -> int:
    result = -value
    if result < INT_MIN or result > INT_MAX:
        raise OverflowError(INTEGER_OVERFLOW_MESSAGE)
    return result


def ieee_divide(left: float, right: float) -> float:
    """Mirror LLVM fdiv for the zero-divisor cases Python rejects."""
    if right != 0.0:
        return left / right
    if left == 0.0:
        return nan
    sign = copysign(1.0, left) * copysign(1.0, right)
    return copysign(float("inf"), sign)
