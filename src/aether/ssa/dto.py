from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
import json
import re
from typing import Any

from aether.ir.dto import (
    ir_instruction_from_dto,
    ir_instruction_to_dto,
    ir_struct_definition_from_dto,
    ir_struct_definition_to_dto,
    ir_type_from_dto,
    ir_type_to_dto,
    ir_value_from_dto,
    ir_value_to_dto,
)
from aether.ir import model as ir_model
from aether.ir.model import (
    IREnumConstant,
    IRErasedBoxLayout,
    IRSourceLocation,
    IRWitnessMethodSlot,
    IRWitnessTable,
)

from .model import (
    SSABasicBlock,
    SSAFunction,
    SSAInstruction,
    SSAInvoke,
    SSAInvokeIndirect,
    SSAInvokeInterface,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAPropagate,
    SSARethrow,
    SSAThrow,
    SSAValue,
)


SSA_SCHEMA_VERSION = 1


class SSADTOError(ValueError):
    """Raised when an SSA interchange document is malformed."""


_METADATA_TYPES = {
    type_.__name__: type_
    for type_ in (
        IREnumConstant,
        IRErasedBoxLayout,
        IRSourceLocation,
        IRWitnessMethodSlot,
        IRWitnessTable,
    )
}


def _kind(name: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _instruction_types() -> dict[str, type[SSAInstruction]]:
    pending = list(SSAInstruction.__subclasses__())
    result: dict[str, type[SSAInstruction]] = {}
    while pending:
        type_ = pending.pop()
        pending.extend(type_.__subclasses__())
        if not is_dataclass(type_):
            continue
        result[_kind(type_.__name__[3:])] = type_
    return result


_INSTRUCTION_TYPES = _instruction_types()


def ssa_module_to_dto(module: SSAModule) -> dict[str, object]:
    if type(module) is not SSAModule:
        raise TypeError(f"Expected SSAModule, got {type(module).__name__}")
    return {
        "schema_version": SSA_SCHEMA_VERSION,
        "representation": "aether_ssa",
        "functions": [_function_to_dto(function) for function in module.functions],
        "structs": [
            ir_struct_definition_to_dto(definition)
            for definition in module.structs
        ],
    }


def ssa_module_from_dto(dto: Mapping[str, object]) -> SSAModule:
    mapping = _mapping(dto, "SSA module")
    _fields(
        mapping,
        {"schema_version", "representation", "functions", "structs"},
        "SSA module",
    )
    if mapping["schema_version"] != SSA_SCHEMA_VERSION:
        raise SSADTOError(
            f"Unsupported SSA schema version {mapping['schema_version']!r}"
        )
    if mapping["representation"] != "aether_ssa":
        raise SSADTOError("SSA module representation must be 'aether_ssa'")
    return SSAModule(
        [
            _function_from_dto(item)
            for item in _sequence(mapping["functions"], "SSA functions")
        ],
        [
            ir_struct_definition_from_dto(_mapping(item, "SSA struct"))
            for item in _sequence(mapping["structs"], "SSA structs")
        ],
    )


def ssa_module_to_json(
    module: SSAModule,
    *,
    indent: int | None = 2,
) -> str:
    return json.dumps(
        ssa_module_to_dto(module),
        ensure_ascii=False,
        allow_nan=False,
        indent=indent,
        separators=None if indent is not None else (",", ":"),
    )


def ssa_module_from_json(data: str | bytes | bytearray) -> SSAModule:
    try:
        decoded = json.loads(data, object_pairs_hook=_without_duplicates)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SSADTOError(f"Malformed SSA JSON: {error}") from error
    return ssa_module_from_dto(_mapping(decoded, "SSA module"))


def _function_to_dto(function: SSAFunction) -> dict[str, object]:
    dto: dict[str, object] = {
        "name": function.name,
        "parameters": [_parameter_to_dto(value) for value in function.parameters],
        "return_type": ir_type_to_dto(function.return_type),
        "blocks": [_block_to_dto(block) for block in function.blocks],
        "entry_block": function.entry_block,
    }
    if function.may_throw:
        dto["may_throw"] = True
    return dto


def _function_from_dto(dto: object) -> SSAFunction:
    mapping = _mapping(dto, "SSA function")
    expected = {"name", "parameters", "return_type", "blocks", "entry_block"}
    if "may_throw" in mapping:
        expected.add("may_throw")
    _fields(mapping, expected, "SSA function")
    may_throw = mapping.get("may_throw", False)
    if type(may_throw) is not bool:
        raise SSADTOError("SSA function.may_throw must be boolean")
    return SSAFunction(
        _string(mapping["name"], "SSA function.name"),
        [
            _parameter_from_dto(item)
            for item in _sequence(
                mapping["parameters"], "SSA function.parameters"
            )
        ],
        ir_type_from_dto(mapping["return_type"]),
        [
            _block_from_dto(item)
            for item in _sequence(mapping["blocks"], "SSA function.blocks")
        ],
        _string(mapping["entry_block"], "SSA function.entry_block"),
        may_throw,
    )


def _block_to_dto(block: SSABasicBlock) -> dict[str, object]:
    return {
        "name": block.name,
        "instructions": [
            _instruction_to_dto(instruction)
            for instruction in block.instructions
        ],
    }


def _block_from_dto(dto: object) -> SSABasicBlock:
    mapping = _mapping(dto, "SSA block")
    _fields(mapping, {"name", "instructions"}, "SSA block")
    return SSABasicBlock(
        _string(mapping["name"], "SSA block.name"),
        [
            _instruction_from_dto(item)
            for item in _sequence(mapping["instructions"], "SSA instructions")
        ],
    )


def _instruction_to_dto(instruction: SSAInstruction) -> dict[str, object]:
    if type(instruction) not in _INSTRUCTION_TYPES.values():
        raise TypeError(
            f"Unsupported SSA instruction {type(instruction).__name__}"
        )
    if isinstance(instruction, SSAPhi):
        return {
            "kind": "phi",
            "result": ir_value_to_dto(_ir_value(instruction.result)),
            "incoming": [
                {
                    "block": block_name,
                    "value": ir_value_to_dto(_ir_value(value)),
                }
                for block_name, value in instruction.incoming
            ],
        }

    ir_instruction = _ssa_instruction_to_ir(instruction)
    dto = ir_instruction_to_dto(ir_instruction)
    if isinstance(
        instruction,
        (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface),
    ):
        dto.pop("exceptional_target_event")
        dto["normal_arguments"] = [
            ir_value_to_dto(_ir_value(value))
            for value in instruction.normal_arguments
        ]
        dto["exceptional_arguments"] = [
            ir_value_to_dto(_ir_value(value))
            for value in instruction.exceptional_arguments
        ]
    elif isinstance(instruction, (SSAThrow, SSARethrow, SSAPropagate)):
        dto.pop("target_event")
        dto["exceptional_arguments"] = [
            ir_value_to_dto(_ir_value(value))
            for value in instruction.exceptional_arguments
        ]
    return dto


def _instruction_from_dto(dto: object) -> SSAInstruction:
    mapping = _mapping(dto, "SSA instruction")
    kind = _string(mapping.get("kind"), "SSA instruction.kind")
    if kind == "phi":
        _fields(mapping, {"kind", "result", "incoming"}, "SSA phi")
        incoming = []
        for item in _sequence(mapping["incoming"], "SSA phi.incoming"):
            edge = _mapping(item, "SSA phi incoming")
            _fields(edge, {"block", "value"}, "SSA phi incoming")
            incoming.append(
                (
                    _string(edge["block"], "SSA phi incoming.block"),
                    _ssa_value(ir_value_from_dto(edge["value"])),
                )
            )
        return SSAPhi(
            _ssa_value(ir_value_from_dto(mapping["result"])),
            tuple(incoming),
        )

    type_ = _INSTRUCTION_TYPES.get(kind)
    if type_ is None and kind == "exception_pack":
        type_ = _INSTRUCTION_TYPES.get("pack_exception")
    if type_ is None:
        raise SSADTOError(f"Unknown SSA instruction kind '{kind}'")

    try:
        if issubclass(
            type_,
            (SSAInvoke, SSAInvokeIndirect, SSAInvokeInterface),
        ):
            expected = {
                "kind",
                *(
                    field.name
                    for field in fields(type_)
                    if field.name
                    not in {"normal_arguments", "exceptional_arguments"}
                ),
                "normal_arguments",
                "exceptional_arguments",
            }
            _fields(mapping, expected, f"SSA instruction '{kind}'")
            ir_dto = dict(mapping)
            normal = tuple(
                _ssa_value(ir_value_from_dto(value))
                for value in _sequence(
                    ir_dto.pop("normal_arguments"),
                    "SSA invoke.normal_arguments",
                )
            )
            exceptional = tuple(
                _ssa_value(ir_value_from_dto(value))
                for value in _sequence(
                    ir_dto.pop("exceptional_arguments"),
                    "SSA invoke.exceptional_arguments",
                )
            )
            ir_dto["exceptional_target_event"] = ir_dto["exception"]
            result = _ir_instruction_to_ssa(
                ir_instruction_from_dto(ir_dto)
            )
            return type_(
                **{
                    **{
                        field.name: getattr(result, field.name)
                        for field in fields(type_)
                        if field.name
                        not in {
                            "normal_arguments",
                            "exceptional_arguments",
                        }
                    },
                    "normal_arguments": normal,
                    "exceptional_arguments": exceptional,
                }
            )
        if issubclass(type_, (SSAThrow, SSARethrow, SSAPropagate)):
            expected = {
                "kind",
                "event",
                "target",
                "exceptional_arguments",
            }
            _fields(mapping, expected, f"SSA instruction '{kind}'")
            ir_dto = dict(mapping)
            exceptional = tuple(
                _ssa_value(ir_value_from_dto(value))
                for value in _sequence(
                    ir_dto.pop("exceptional_arguments"),
                    "SSA transfer.exceptional_arguments",
                )
            )
            ir_dto["target_event"] = (
                None if ir_dto["target"] is None else ir_dto["event"]
            )
            result = _ir_instruction_to_ssa(
                ir_instruction_from_dto(ir_dto)
            )
            return type_(
                result.event,
                result.target,
                exceptional,
            )
        return _ir_instruction_to_ssa(
            ir_instruction_from_dto(mapping)
        )
    except (TypeError, ValueError) as error:
        raise SSADTOError(
            f"Invalid SSA instruction '{kind}': {error}"
        ) from error


def _ssa_instruction_to_ir(instruction: SSAInstruction):
    if isinstance(instruction, SSAInvoke):
        return ir_model.IRInvoke(
            instruction.function,
            tuple(_ir_value(value) for value in instruction.arguments),
            None if instruction.result is None else _ir_value(instruction.result),
            _ir_value(instruction.exception),
            instruction.normal_target,
            instruction.exceptional_target,
            _ir_value(instruction.exception),
            instruction.builtin,
            instruction.source_location,
        )
    if isinstance(instruction, SSAInvokeIndirect):
        return ir_model.IRInvokeIndirect(
            _ir_value(instruction.callee),
            tuple(_ir_value(value) for value in instruction.arguments),
            None if instruction.result is None else _ir_value(instruction.result),
            _ir_value(instruction.exception),
            instruction.normal_target,
            instruction.exceptional_target,
            _ir_value(instruction.exception),
        )
    if isinstance(instruction, SSAInvokeInterface):
        return ir_model.IRInvokeInterface(
            _ir_value(instruction.receiver),
            tuple(_ir_value(value) for value in instruction.arguments),
            instruction.slot,
            None if instruction.result is None else _ir_value(instruction.result),
            _ir_value(instruction.exception),
            instruction.normal_target,
            instruction.exceptional_target,
            _ir_value(instruction.exception),
        )
    if isinstance(instruction, (SSAThrow, SSARethrow, SSAPropagate)):
        ir_type = {
            SSAThrow: ir_model.IRThrow,
            SSARethrow: ir_model.IRRethrow,
            SSAPropagate: ir_model.IRPropagate,
        }[type(instruction)]
        return ir_type(
            _ir_value(instruction.event),
            instruction.target,
            (
                None
                if instruction.target is None
                else _ir_value(instruction.event)
            ),
        )
    ir_type = getattr(ir_model, f"IR{type(instruction).__name__[3:]}")
    return ir_type(
        **{
            field.name: _to_ir(getattr(instruction, field.name))
            for field in fields(instruction)
        }
    )


def _ir_instruction_to_ssa(instruction) -> SSAInstruction:
    ssa_name = f"SSA{type(instruction).__name__[2:]}"
    type_ = next(
        (
            candidate
            for candidate in _INSTRUCTION_TYPES.values()
            if candidate.__name__ == ssa_name
        ),
        None,
    )
    if type_ is None:
        raise SSADTOError(
            f"Initial IR instruction '{type(instruction).__name__}' is not "
            "legal in SSA"
        )
    return type_(
        **{
            field.name: _to_ssa(getattr(instruction, field.name))
            for field in fields(type_)
            if hasattr(instruction, field.name)
        }
    )


def _to_ir(value: object) -> object:
    if isinstance(value, SSAValue):
        return _ir_value(value)
    if isinstance(value, tuple):
        return tuple(_to_ir(item) for item in value)
    if isinstance(value, list):
        return [_to_ir(item) for item in value]
    return value


def _to_ssa(value: object) -> object:
    if isinstance(value, ir_model.IRValue):
        return _ssa_value(value)
    if isinstance(value, tuple):
        return tuple(_to_ssa(item) for item in value)
    if isinstance(value, list):
        return [_to_ssa(item) for item in value]
    return value


def _ir_value(value: SSAValue):
    if isinstance(value, SSAParameter):
        return ir_model.IRParameter(value.name, value.type)
    return ir_model.IRValue(value.name, value.type)


def _ssa_value(value) -> SSAValue:
    if isinstance(value, ir_model.IRStorage):
        raise SSADTOError("Owning Initial IR storage is not legal in SSA")
    if isinstance(value, ir_model.IRParameter):
        return SSAParameter(value.name, value.type)
    if not isinstance(value, ir_model.IRValue):
        raise SSADTOError(
            f"Expected SSA value, got {type(value).__name__}"
        )
    return SSAValue(value.name, value.type)


def _parameter_to_dto(value: SSAParameter) -> dict[str, object]:
    return {
        "tag": "parameter",
        "name": value.name,
        "type": ir_type_to_dto(value.type),
    }


def _parameter_from_dto(dto: object) -> SSAParameter:
    mapping = _mapping(dto, "SSA parameter")
    _fields(mapping, {"tag", "name", "type"}, "SSA parameter")
    if mapping["tag"] != "parameter":
        raise SSADTOError("SSA parameter.tag must be 'parameter'")
    return SSAParameter(
        _string(mapping["name"], "SSA parameter.name"),
        ir_type_from_dto(mapping["type"]),
    )


def _encode(value: object) -> object:
    if isinstance(value, SSAValue):
        return {
            "tag": (
                "parameter" if isinstance(value, SSAParameter) else "value"
            ),
            "name": value.name,
            "type": ir_type_to_dto(value.type),
        }
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, complex):
        return {"tag": "complex", "real": value.real, "imaginary": value.imag}
    if is_dataclass(value) and type(value).__name__ in _METADATA_TYPES:
        return {
            "tag": "metadata",
            "type": type(value).__name__,
            "fields": {
                field.name: _encode(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise TypeError(f"Unsupported SSA DTO value {type(value).__name__}")


def _decode(value: object) -> Any:
    if isinstance(value, list):
        return tuple(_decode(item) for item in value)
    if not isinstance(value, Mapping):
        return value
    mapping = _mapping(value, "SSA encoded value")
    tag = mapping.get("tag")
    if tag in {"value", "parameter"}:
        _fields(mapping, {"tag", "name", "type"}, "SSA value")
        value_type = SSAParameter if tag == "parameter" else SSAValue
        return value_type(
            _string(mapping["name"], "SSA value.name"),
            ir_type_from_dto(mapping["type"]),
        )
    if tag == "complex":
        _fields(mapping, {"tag", "real", "imaginary"}, "SSA complex")
        return complex(mapping["real"], mapping["imaginary"])
    if tag == "metadata":
        _fields(mapping, {"tag", "type", "fields"}, "SSA metadata")
        type_name = _string(mapping["type"], "SSA metadata.type")
        type_ = _METADATA_TYPES.get(type_name)
        if type_ is None:
            raise SSADTOError(f"Unknown SSA metadata type '{type_name}'")
        encoded_fields = _mapping(mapping["fields"], "SSA metadata.fields")
        expected = {field.name for field in fields(type_)}
        _fields(encoded_fields, expected, f"SSA metadata '{type_name}'")
        return type_(
            **{
                field.name: _decode(encoded_fields[field.name])
                for field in fields(type_)
            }
        )
    raise SSADTOError(f"Unknown encoded SSA value tag {tag!r}")


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SSADTOError(f"{context} must be an object")
    if any(type(key) is not str for key in value):
        raise SSADTOError(f"{context} keys must be strings")
    return value


def _sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise SSADTOError(f"{context} must be an array")
    return value


def _string(value: object, context: str) -> str:
    if type(value) is not str:
        raise SSADTOError(f"{context} must be a string")
    return value


def _fields(
    mapping: Mapping[str, object],
    expected: set[str],
    context: str,
) -> None:
    actual = set(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise SSADTOError(f"{context} has invalid fields: {'; '.join(details)}")


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SSADTOError(f"Duplicate JSON object key '{key}'")
        result[key] = value
    return result
