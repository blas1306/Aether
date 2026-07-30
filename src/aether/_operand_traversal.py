from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, is_dataclass, replace
from typing import Any, TypeVar


InstructionT = TypeVar("InstructionT")
ValueT = TypeVar("ValueT")


def instruction_operands(
    instruction: object,
    value_type: type[ValueT],
) -> tuple[ValueT, ...]:
    """Return every value use in a dataclass instruction.

    Instruction models use ``result`` for their sole definition.  Every value
    in every other field is an operand, including values nested in tuples such
    as call arguments and phi incoming pairs.  The traversal deliberately does
    not dispatch on concrete instruction classes, so adding a dataclass
    instruction cannot silently omit it from optimizer use-def analysis.
    """

    _require_dataclass_instruction(instruction)
    operands: list[ValueT] = []
    for field in fields(instruction):
        if field.name == "result" or field.metadata.get("ir_definition", False):
            continue
        _collect_values(getattr(instruction, field.name), value_type, operands)
    return tuple(operands)


def rewrite_instruction_operands(
    instruction: InstructionT,
    value_type: type[ValueT],
    rewrite_value: Callable[[ValueT], ValueT],
) -> tuple[InstructionT, int]:
    """Rewrite every value use while preserving definitions and metadata."""

    _require_dataclass_instruction(instruction)
    updates: dict[str, Any] = {}
    rewritten_uses = 0
    for field in fields(instruction):
        if field.name == "result" or field.metadata.get("ir_definition", False):
            continue
        value = getattr(instruction, field.name)
        rewritten, count = _rewrite_nested(value, value_type, rewrite_value)
        if count:
            updates[field.name] = rewritten
            rewritten_uses += count
    if not updates:
        return instruction, 0
    return replace(instruction, **updates), rewritten_uses


def instruction_result(
    instruction: object,
    value_type: type[ValueT],
) -> ValueT | None:
    """Return the conventional single instruction result, when present."""

    result = getattr(instruction, "result", None)
    return result if isinstance(result, value_type) else None


def assert_complete_instruction_hierarchy(
    instruction_type: type[object],
) -> None:
    """Reject instruction classes that cannot use structural traversal."""

    pending = list(instruction_type.__subclasses__())
    seen: set[type[object]] = set()
    while pending:
        candidate = pending.pop()
        if candidate in seen:
            continue
        seen.add(candidate)
        pending.extend(candidate.__subclasses__())
        if "__dataclass_fields__" not in candidate.__dict__:
            raise TypeError(
                f"{candidate.__name__} must be a dataclass for complete "
                "optimizer operand traversal"
            )


def _require_dataclass_instruction(instruction: object) -> None:
    if not is_dataclass(instruction) or isinstance(instruction, type):
        raise TypeError(
            f"{type(instruction).__name__} must be a dataclass instruction "
            "for complete optimizer operand traversal"
        )


def _collect_values(
    value: object,
    value_type: type[ValueT],
    operands: list[ValueT],
) -> None:
    if isinstance(value, value_type):
        operands.append(value)
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            _collect_values(item, value_type, operands)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_values(key, value_type, operands)
            _collect_values(item, value_type, operands)


def _rewrite_nested(
    value: Any,
    value_type: type[ValueT],
    rewrite_value: Callable[[ValueT], ValueT],
) -> tuple[Any, int]:
    if isinstance(value, value_type):
        rewritten = rewrite_value(value)
        return rewritten, int(rewritten is not value)

    if isinstance(value, tuple):
        rewritten_items: list[Any] = []
        count = 0
        for item in value:
            rewritten, item_count = _rewrite_nested(
                item,
                value_type,
                rewrite_value,
            )
            rewritten_items.append(rewritten)
            count += item_count
        if not count:
            return value, 0
        return tuple(rewritten_items), count

    if isinstance(value, list):
        rewritten_items = []
        count = 0
        for item in value:
            rewritten, item_count = _rewrite_nested(
                item,
                value_type,
                rewrite_value,
            )
            rewritten_items.append(rewritten)
            count += item_count
        if not count:
            return value, 0
        return rewritten_items, count

    if isinstance(value, dict):
        rewritten_items = {}
        count = 0
        for key, item in value.items():
            rewritten_key, key_count = _rewrite_nested(
                key,
                value_type,
                rewrite_value,
            )
            rewritten_item, item_count = _rewrite_nested(
                item,
                value_type,
                rewrite_value,
            )
            rewritten_items[rewritten_key] = rewritten_item
            count += key_count + item_count
        if not count:
            return value, 0
        return rewritten_items, count

    return value, 0
