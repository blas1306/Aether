from __future__ import annotations

from dataclasses import fields
from typing import Callable

import pytest

from aether.ir import model as ir_model
from aether.ir.dto import (
    IR_INSTRUCTION_DTO_REGISTRY,
    IR_TYPE_TAGS,
    IRDTOError,
    ir_basic_block_from_dto,
    ir_basic_block_to_dto,
    ir_constant_from_dto,
    ir_constant_to_dto,
    ir_enum_constant_from_dto,
    ir_enum_constant_to_dto,
    ir_function_from_dto,
    ir_function_to_dto,
    ir_instruction_from_dto,
    ir_instruction_to_dto,
    ir_module_from_dto,
    ir_module_to_dto,
    ir_parameter_from_dto,
    ir_parameter_to_dto,
    ir_source_location_from_dto,
    ir_source_location_to_dto,
    ir_storage_from_dto,
    ir_storage_to_dto,
    ir_struct_definition_from_dto,
    ir_struct_definition_to_dto,
    ir_type_from_dto,
    ir_type_to_dto,
    ir_value_from_dto,
    ir_value_to_dto,
)
from aether.ir.types import (
    ArrayType,
    BoolType,
    ClassRefType,
    ComplexType,
    DoubleType,
    EnumType,
    ExceptionEventType,
    FloatType,
    FunctionType,
    InterfaceType,
    IntType,
    IRType,
    ListType,
    MatrixType,
    MethodResultType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)


LOCATION = ir_model.IRSourceLocation(17, 5, "src/contracts.ae")
INT = IntType()
FLOAT = FloatType()
PROFILE = StructType("Profile")
ROW = VectorType(FLOAT, "row")
COLUMN = VectorType(FLOAT, "column")
MATRIX = MatrixType(FLOAT)


def _result_type(tag: str) -> IRType:
    if tag == "class_new":
        return ClassRefType("Document")
    if tag == "interface_construct":
        return InterfaceType("Readable")
    if tag == "function_ref":
        return FunctionType((INT,), INT)
    if tag == "method_result_new":
        return MethodResultType(PROFILE, INT)
    if tag.startswith("vector_") and tag not in {"vector_dot", "vector_get", "vector_length"}:
        return ROW
    if tag in {"outer_product", "matrix_add", "matrix_sub", "matrix_scale", "matrix_mat_mul"}:
        return MATRIX
    if tag == "matrix_vector_mul":
        return COLUMN
    if tag == "vector_matrix_mul":
        return ROW
    if tag in {"array_new", "array_copy", "array_slice"}:
        return ArrayType(INT)
    if tag in {"list_new", "list_copy", "list_slice"}:
        return ListType(INT)
    if tag == "struct_new":
        return PROFILE
    if tag in {"compare_op", "list_contains", "list_is_empty"}:
        return BoolType()
    if tag == "exception_pack":
        return ExceptionEventType()
    if tag == "exception_match":
        return BoolType()
    return INT


def _value(name: str, type_: IRType = INT) -> ir_model.IRValue:
    return ir_model.IRValue(name, type_)


def _instruction_sample(entry_index: int) -> ir_model.IRInstruction:
    """Build one structural sample from the authoritative registry entry."""

    entry = IR_INSTRUCTION_DTO_REGISTRY[entry_index]
    tag = entry.tag
    result_type = _result_type(tag)
    values: dict[str, object] = {
        "result": _value(f"{tag}.result", result_type),
        "destination": ir_model.IRStorage(f"{tag}.destination", result_type),
        "source": ir_model.IRStorage(f"{tag}.source", result_type),
        "source_location": LOCATION,
        "slot": ir_model.IRStorage(f"{tag}.slot", INT),
        "operator": "+" if tag == "binary_op" else "neg",
        "operand": _value(f"{tag}.operand"),
        "function": "helper",
        "arguments": (_value(f"{tag}.argument"),),
        "builtin": None,
        "may_throw_effect": False,
        "callee": _value(f"{tag}.callee", FunctionType((INT,), INT)),
        "newline": True,
        "aggregate_shape": (2, 3),
        "struct": _value(f"{tag}.struct", PROFILE),
        "object": _value(f"{tag}.object", ClassRefType("Document")),
        "carrier": _value(f"{tag}.carrier", ClassRefType("Document")),
        "witness": ir_model.IRWitnessTable(
            symbol="__ae_witness_i8_5265616461626c65__c8_446f63756d656e74__contract",
            interface_id="Readable",
            concrete_type_id="Document",
            carrier_kind="class",
            method_slots=(
                ir_model.IRWitnessMethodSlot(
                    index=0,
                    method_id="Readable.read",
                    parameter_types=(),
                    return_type=INT,
                    thunk_symbol="__ae_interface_thunk_s0__contract",
                ),
            ),
        ),
        "field_index": 1,
        "field_name": "name",
        "initialize": True,
        "receiver": _value(f"{tag}.receiver", PROFILE),
        "method_result": _value(
            f"{tag}.method_result",
            MethodResultType(PROFILE, INT),
        ),
        "fields": (_value(f"{tag}.field"),),
        "elements": (_value(f"{tag}.element", FLOAT),),
        "array": _value(f"{tag}.array", ArrayType(INT)),
        "list_value": _value(f"{tag}.list", ListType(INT)),
        "index": _value(f"{tag}.index"),
        "start": _value(f"{tag}.start"),
        "end": _value(f"{tag}.end"),
        "borrowed": True,
        "borrow_scope": "contract-audit",
        "vector": _value(f"{tag}.vector", ROW),
        "matrix": _value(f"{tag}.matrix", MATRIX),
        "left": _value(f"{tag}.left", MATRIX if tag.startswith("matrix_") else ROW),
        "right": _value(f"{tag}.right", MATRIX if tag.startswith("matrix_") else ROW),
        "scalar": _value(f"{tag}.scalar", FLOAT),
        "length": 3,
        "orientation": "row",
        "rows": 2,
        "cols": 3,
        "inner": 4,
        "columns": 3,
        "row": _value(f"{tag}.row"),
        "column": _value(f"{tag}.column"),
        "sequence": _value(f"{tag}.sequence", ListType(INT)),
        "condition": _value(f"{tag}.condition", BoolType()),
        "true_target": "then",
        "false_target": "else",
        "target": "exit",
        "normal_target": "normal",
        "exceptional_target": "handler",
        "exception": _value(f"{tag}.exception", ExceptionEventType()),
        "exceptional_target_event": _value(
            f"{tag}.handler_event", ExceptionEventType()
        ),
        "event": _value(f"{tag}.event", ExceptionEventType()),
        "target_event": _value(f"{tag}.target_event", ExceptionEventType()),
        "handler_id": "handler0",
        "catch_types": ("FileError", "Error"),
        "catch_type": "FileError",
        "catch_all": False,
        "payload": _value(f"{tag}.payload", StructType("Profile")),
        "dynamic_type": "Profile",
        "transferred_storage": ir_model.IRStorage(f"{tag}.transfer", result_type),
        "count": 2,
    }
    if tag == "const":
        values["value"] = ir_model.IREnumConstant("Status", "ready", 1, 7)
    elif tag == "destroy":
        values["value"] = ir_model.IRStorage("destroy.value", INT)
    else:
        values["value"] = _value(f"{tag}.value")
    if tag == "outer_product":
        values["column"] = _value("outer.column", COLUMN)
        values["row"] = _value("outer.row", ROW)
    if tag == "compare_op":
        values["operator"] = "eq"
    if tag in {"interface_call", "invoke_interface"}:
        values["receiver"] = _value(
            "interface_call.receiver",
            InterfaceType("Readable"),
        )
        values["arguments"] = ()
        values["slot"] = ir_model.IRWitnessMethodSlot(
            index=0,
            method_id="Readable.read",
            parameter_types=(),
            return_type=INT,
        )

    constructor_fields = {field.name for field in fields(entry.instruction_type)}
    return entry.instruction_type(
        **{name: values[name] for name in constructor_fields}
    )


def _all_instruction_samples() -> list[ir_model.IRInstruction]:
    return [_instruction_sample(index) for index in range(len(IR_INSTRUCTION_DTO_REGISTRY))]


def _complete_module() -> ir_model.IRModule:
    instructions = _all_instruction_samples()
    groups = [instructions[index::4] for index in range(4)]
    return ir_model.IRModule(
        functions=[
            ir_model.IRFunction(
                f"contract_group_{index}",
                [],
                VoidType(),
                [
                    ir_model.IRBasicBlock(
                        "entry",
                        group[: len(group) // 2],
                    ),
                    ir_model.IRBasicBlock(
                        "finish",
                        group[len(group) // 2 :],
                    ),
                ],
                may_throw=True,
            )
            for index, group in enumerate(groups)
        ],
        structs=[
            ir_model.IRStructDefinition(
                "Address",
                (("street", StringType()), ("coordinates", VectorType(FLOAT, None))),
            ),
            ir_model.IRStructDefinition(
                "Profile",
                (
                    ("address", StructType("Address")),
                    ("history", ListType(ArrayType(StructType("Address")))),
                    ("transform", MatrixType(DoubleType())),
                ),
            ),
        ],
    )


def test_complete_realistic_module_round_trip_covers_authoritative_84_variants() -> None:
    module = _complete_module()

    decoded = ir_module_from_dto(ir_module_to_dto(module))

    assert decoded == module
    assert len(module.structs) == 2
    assert len(module.functions) == 4
    assert all(len(function.blocks) >= 2 for function in module.functions)
    covered = {
        type(instruction)
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    }
    assert covered == {entry.instruction_type for entry in IR_INSTRUCTION_DTO_REGISTRY}
    assert len(IR_INSTRUCTION_DTO_REGISTRY) == 84


def _type_samples() -> list[IRType]:
    samples: dict[type[IRType], IRType] = {
        IntType: IntType(),
        FloatType: FloatType(),
        DoubleType: DoubleType(),
        BoolType: BoolType(),
        StringType: StringType(),
        VoidType: VoidType(),
        FunctionType: FunctionType((IntType(), StringType()), BoolType()),
        ComplexType: ComplexType(),
        NullableType: NullableType(StringType()),
        ListType: ListType(ArrayType(IntType())),
        ArrayType: ArrayType(StructType("Address")),
        VectorType: VectorType(FloatType(), "column"),
        MatrixType: MatrixType(DoubleType()),
        StructType: StructType("Profile"),
        MethodResultType: MethodResultType(StructType("Profile"), IntType()),
        ClassRefType: ClassRefType("Document"),
        InterfaceType: InterfaceType("Printable"),
        EnumType: EnumType("Status", ("ready", "done"), "Status"),
        ExceptionEventType: ExceptionEventType(),
    }
    assert set(samples) == set(IR_TYPE_TAGS)
    return [samples[type_] for type_ in IR_TYPE_TAGS]


def _assert_json_primitive_tree(value: object) -> None:
    if value is None or type(value) in {bool, int, float, str}:
        return
    if isinstance(value, list):
        for item in value:
            _assert_json_primitive_tree(item)
        return
    assert type(value) is dict
    assert all(type(key) is str for key in value)
    for item in value.values():
        _assert_json_primitive_tree(item)


@pytest.mark.parametrize("sample", _type_samples())
def test_every_reachable_type_has_stable_round_trip_and_malformed_coverage(sample: IRType) -> None:
    dto = ir_type_to_dto(sample)

    assert dto["tag"] == IR_TYPE_TAGS[type(sample)]
    _assert_json_primitive_tree(dto)
    assert ir_type_from_dto(dto) == sample

    with pytest.raises(IRDTOError, match="Unknown IR type DTO tag"):
        ir_type_from_dto({**dto, "tag": "future_type"})


@pytest.mark.parametrize(
    "sample",
    [
        True,
        42,
        1.25,
        complex(2.0, -3.0),
        "héllo",
        ir_model.IREnumConstant("Status", "ready", 1, 7),
    ],
)
def test_every_reachable_constant_has_stable_round_trip_and_malformed_coverage(
    sample: object,
) -> None:
    dto = ir_constant_to_dto(sample)  # type: ignore[arg-type]

    _assert_json_primitive_tree(dto)
    assert ir_constant_from_dto(dto) == sample

    with pytest.raises(IRDTOError, match="Unknown IR constant DTO tag"):
        ir_constant_from_dto({**dto, "tag": "future_constant"})


@pytest.mark.parametrize(
    ("sample", "encoder", "decoder"),
    [
        (_value("temporary"), ir_value_to_dto, ir_value_from_dto),
        (ir_model.IRStorage("slot", INT), ir_storage_to_dto, ir_storage_from_dto),
        (ir_model.IRParameter("argument", INT), ir_parameter_to_dto, ir_parameter_from_dto),
    ],
)
def test_every_reachable_value_kind_has_stable_round_trip_and_malformed_coverage(
    sample: ir_model.IRValue,
    encoder: Callable[[object], dict[str, object]],
    decoder: Callable[[dict[str, object]], object],
) -> None:
    dto = encoder(sample)

    _assert_json_primitive_tree(dto)
    assert decoder(dto) == sample

    with pytest.raises(IRDTOError):
        decoder({**dto, "tag": "future_value"})


def test_enum_metadata_and_source_location_leaf_contracts_are_audited() -> None:
    enum_value = ir_model.IREnumConstant("Status", "ready", 1, 7)
    enum_dto = ir_enum_constant_to_dto(enum_value)
    location_dto = ir_source_location_to_dto(LOCATION)

    assert ir_enum_constant_from_dto(enum_dto) == enum_value
    assert ir_source_location_from_dto(location_dto) == LOCATION
    assert ir_source_location_from_dto(None) is None
    _assert_json_primitive_tree(enum_dto)
    _assert_json_primitive_tree(location_dto)

    with pytest.raises(IRDTOError):
        ir_enum_constant_from_dto({**enum_dto, "tag": "future_enum"})
    assert location_dto is not None
    with pytest.raises(IRDTOError):
        ir_source_location_from_dto({**location_dto, "tag": "future_location"})


@pytest.mark.parametrize("index", range(len(IR_INSTRUCTION_DTO_REGISTRY)))
def test_every_registered_instruction_has_root_audit_coverage(index: int) -> None:
    entry = IR_INSTRUCTION_DTO_REGISTRY[index]
    sample = _instruction_sample(index)
    dto = ir_instruction_to_dto(sample)

    assert dto["kind"] == entry.tag
    _assert_json_primitive_tree(dto)
    assert ir_instruction_from_dto(dto) == sample

    with pytest.raises(IRDTOError, match="Unknown IR instruction DTO tag"):
        ir_instruction_from_dto({**dto, "kind": "future_instruction"})


def test_every_root_container_has_encoder_decoder_explicit_shape_and_malformed_coverage() -> None:
    block = ir_model.IRBasicBlock("entry", [_instruction_sample(0)])
    function = ir_model.IRFunction(
        "main",
        [ir_model.IRParameter("argument", INT)],
        INT,
        [block],
    )
    definition = ir_model.IRStructDefinition(
        "Box",
        (("value", NullableType(ListType(INT))),),
    )
    module = ir_model.IRModule([function], [definition])
    contracts = [
        (block, ir_basic_block_to_dto, ir_basic_block_from_dto, {"name", "instructions"}),
        (
            function,
            ir_function_to_dto,
            ir_function_from_dto,
            {"name", "parameters", "return_type", "blocks"},
        ),
        (
            definition,
            ir_struct_definition_to_dto,
            ir_struct_definition_from_dto,
            {"name", "fields"},
        ),
        (module, ir_module_to_dto, ir_module_from_dto, {"schema_version", "functions", "structs"}),
    ]

    for sample, encoder, decoder, explicit_fields in contracts:
        dto = encoder(sample)
        assert set(dto) == explicit_fields
        _assert_json_primitive_tree(dto)
        assert decoder(dto) == sample

        missing_field = next(iter(explicit_fields))
        malformed = {key: value for key, value in dto.items() if key != missing_field}
        with pytest.raises(IRDTOError, match="missing fields"):
            decoder(malformed)
