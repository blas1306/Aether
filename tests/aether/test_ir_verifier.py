from __future__ import annotations

import re

import pytest

from aether.ir import (
    ArrayType,
    BoolType,
    ClassRefType,
    DoubleType,
    EnumType,
    FunctionType,
    IRArrayCopy,
    IRArraySlice,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInitDefault,
    IRJump,
    IRLoad,
    IRListNew,
    IRListCopy,
    IRListClear,
    IRListPop,
    IRListPush,
    IRListInsert,
    IRListRemoveAt,
    IRListSet,
    IRListSlice,
    IRLowerer,
    IRMatrixNew,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRStorage,
    IRStructDefinition,
    IRType,
    IRValue,
    IRVectorNew,
    IRVerificationError,
    IRVerifier,
    IntType,
    ListType,
    MatrixType,
    MethodResultType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)
from aether.ir.dto import ir_module_from_json, ir_module_to_json
from aether.pipeline import parse_source
from aether.typechecker import TypeChecker


def _lower(source: str) -> IRModule:
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def _assert_verification_error(module: IRModule, message: str) -> None:
    with pytest.raises(IRVerificationError, match=re.escape(message)):
        IRVerifier(module).verify()


def _collection_lifecycle_module(
    operation: str,
    element_type: IRType,
    structs: tuple[IRStructDefinition, ...] = (),
) -> IRModule:
    collection_type = (
        ArrayType(element_type)
        if operation in {"array_copy", "array_slice"}
        else ListType(element_type)
    )
    collection = IRParameter("collection", collection_type)
    result = IRValue("result", collection_type)
    start = IRParameter("start", IntType())
    end = IRParameter("end", IntType())
    if operation == "array_copy":
        instruction = IRArrayCopy(result, collection)
        parameters = [collection]
    elif operation == "list_copy":
        instruction = IRListCopy(result, collection)
        parameters = [collection]
    elif operation == "array_slice":
        instruction = IRArraySlice(result, collection, start, end)
        parameters = [collection, start, end]
    elif operation == "list_slice":
        instruction = IRListSlice(result, collection, start, end)
        parameters = [collection, start, end]
    else:
        raise AssertionError(f"unsupported test operation {operation}")
    return IRModule(
        [
            IRFunction(
                "main",
                parameters,
                VoidType(),
                [IRBasicBlock("entry", [instruction, IRReturn(None)])],
            )
        ],
        list(structs),
    )


@pytest.mark.parametrize(
    ("operation", "prefix"),
    [
        ("array_copy", "Array copy"),
        ("list_copy", "List copy"),
        ("list_slice", "List slice"),
    ],
)
def test_collection_copy_like_operations_require_direct_element_lifecycle(
    operation: str,
    prefix: str,
) -> None:
    module = _collection_lifecycle_module(operation, ClassRefType("Box"))

    _assert_verification_error(
        module,
        f"{prefix} element type 'class Box' has no lifecycle: "
        "lifecycle layout for 'class Box' is not defined",
    )


@pytest.mark.parametrize("operation", ["array_copy", "list_copy", "list_slice"])
def test_collection_lifecycle_check_is_shallow_and_accepts_reasonless_traits(
    operation: str,
) -> None:
    holder = IRStructDefinition(
        "Holder",
        (("member", ClassRefType("Box")),),
    )
    supported = (
        ListType(ClassRefType("Box")),
        StructType("Holder"),
        FunctionType((IntType(),), IntType()),
    )

    for element_type in supported:
        module = _collection_lifecycle_module(operation, element_type, (holder,))
        assert IRVerifier(module).verify() is module


def test_array_slice_does_not_check_element_lifecycle() -> None:
    module = _collection_lifecycle_module("array_slice", ClassRefType("Box"))

    assert IRVerifier(module).verify() is module


def test_verifies_lowered_add_function() -> None:
    module = _lower(
        """
int add(int a, int b) {
    return a + b;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_verifies_function_with_local_store_and_load() -> None:
    module = _lower(
        """
int identity(int value) {
    int result = value;
    return result;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_rejects_list_set_with_incompatible_value_type() -> None:
    int_type = IntType()
    double_type = DoubleType()
    element = IRValue("0", int_type)
    list_value = IRValue("1", ListType(int_type))
    index = IRValue("2", int_type)
    value = IRValue("3", double_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(element, 1),
                            IRListNew(list_value, (element,)),
                            IRConst(index, 0),
                            IRConst(value, 2.0),
                            IRListSet(list_value, index, value),
                            IRReturn(element),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "List set value type mismatch: expected int, got double")


def test_rejects_list_clear_with_non_list_operand() -> None:
    int_type = IntType()
    value = IRValue("0", int_type)
    module = IRModule(
        [IRFunction("main", [], int_type, [IRBasicBlock("entry", [IRConst(value, 1), IRListClear(value), IRReturn(value)])])]
    )

    _assert_verification_error(module, "List clear expects list value, got int")


def test_rejects_list_push_with_incompatible_value_type() -> None:
    int_type = IntType()
    double_type = DoubleType()
    element = IRValue("0", int_type)
    list_value = IRValue("1", ListType(int_type))
    value = IRValue("2", double_type)
    module = IRModule([IRFunction("main", [], int_type, [IRBasicBlock("entry", [IRConst(element, 1), IRListNew(list_value, (element,)), IRConst(value, 2.0), IRListPush(list_value, value), IRReturn(element)])])])

    _assert_verification_error(module, "List push value type mismatch: expected int, got double")


def test_rejects_list_insert_with_non_int_index() -> None:
    int_type = IntType()
    element = IRValue("0", int_type)
    list_value = IRValue("1", ListType(int_type))
    index = IRValue("2", DoubleType())
    module = IRModule([IRFunction("main", [], int_type, [IRBasicBlock("entry", [IRConst(element, 1), IRListNew(list_value, (element,)), IRConst(index, 0.0), IRListInsert(list_value, index, element), IRReturn(element)])])])

    _assert_verification_error(module, "List insert index must be int, got double")


def test_rejects_list_pop_with_incompatible_result_type() -> None:
    int_type = IntType()
    element = IRValue("0", int_type)
    list_value = IRValue("1", ListType(int_type))
    result = IRValue("2", DoubleType())
    module = IRModule([IRFunction("main", [], int_type, [IRBasicBlock("entry", [IRConst(element, 1), IRListNew(list_value, (element,)), IRListPop(result, list_value), IRReturn(element)])])])

    _assert_verification_error(module, "List pop result type mismatch: expected int, got double")


def test_rejects_list_remove_at_with_non_int_index() -> None:
    int_type = IntType()
    element = IRValue("0", int_type)
    list_value = IRValue("1", ListType(int_type))
    index = IRValue("2", DoubleType())
    result = IRValue("3", int_type)
    module = IRModule([IRFunction("main", [], int_type, [IRBasicBlock("entry", [IRConst(element, 1), IRListNew(list_value, (element,)), IRConst(index, 0.0), IRListRemoveAt(result, list_value, index), IRReturn(result)])])])

    _assert_verification_error(module, "List remove_at index must be int, got double")


def test_verifies_function_calling_another_function() -> None:
    module = _lower(
        """
int increment(int value) {
    return value + 1;
}

int twiceIncrement(int value) {
    return increment(increment(value));
}
"""
    )

    assert IRVerifier(module).verify() is module


@pytest.mark.parametrize(
    "source",
    [
        "boolean compare(int a, int b) { return a < b; }",
        "boolean compare(int a, int b) { return a <= b; }",
        "boolean compare(int a, int b) { return a > b; }",
        "boolean compare(int a, int b) { return a >= b; }",
        "boolean compare(int a, int b) { return a == b; }",
        "boolean compare(int a, int b) { return a != b; }",
        "boolean compare(boolean a, boolean b) { return a == b; }",
        "boolean compare(boolean a, boolean b) { return a != b; }",
        "boolean compare(string a, string b) { return a == b; }",
        "boolean compare(string a, string b) { return a != b; }",
    ],
)
def test_verifies_lowered_comparison_function(source: str) -> None:
    module = _lower(source)

    assert IRVerifier(module).verify() is module


def test_verifies_lowered_if_else_function() -> None:
    module = _lower(
        """
int f(int x) {
    int y = 0;
    if (x > 0) {
        y = 1;
    } else {
        y = 2;
    }
    return y;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_verifies_lowered_while_function() -> None:
    module = _lower(
        """
int sumTo(int n) {
    int i = 0;
    int sum = 0;

    while (i < n) {
        sum = sum + i;
        i = i + 1;
    }

    return sum;
}
"""
    )

    assert IRVerifier(module).verify() is module


def test_verifies_row_vector_new() -> None:
    int_type = IntType()
    vector_type = VectorType(int_type, "row")
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    vector = IRValue("2", vector_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(first, 1),
                            IRConst(second, 2),
                            IRVectorNew(vector, (first, second)),
                            IRConst(IRValue("3", int_type), 0),
                            IRReturn(IRValue("3", int_type)),
                        ],
                    )
                ],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_verifies_column_vector_new() -> None:
    int_type = IntType()
    vector_type = VectorType(int_type, "column")
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    vector = IRValue("2", vector_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(first, 1),
                            IRConst(second, 2),
                            IRVectorNew(vector, (first, second)),
                            IRConst(IRValue("3", int_type), 0),
                            IRReturn(IRValue("3", int_type)),
                        ],
                    )
                ],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_verifies_matrix_new() -> None:
    int_type = IntType()
    first = IRValue("0", int_type)
    second = IRValue("1", int_type)
    third = IRValue("2", int_type)
    fourth = IRValue("3", int_type)
    matrix = IRValue("4", MatrixType(int_type))
    return_value = IRValue("5", int_type)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(first, 1),
                            IRConst(second, 2),
                            IRConst(third, 3),
                            IRConst(fourth, 4),
                            IRMatrixNew(matrix, (first, second, third, fourth), 2, 2),
                            IRConst(return_value, 0),
                            IRReturn(return_value),
                        ],
                    )
                ],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_rejects_vector_new_orientation_mismatch() -> None:
    int_type = IntType()
    first = IRValue("0", int_type)
    vector = IRValue("1", VectorType(int_type, "column"))
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(first, 1),
                            IRVectorNew(vector, (first,), "row"),
                            IRReturn(first),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "Vector new orientation mismatch")


def test_verifies_void_function_with_bare_return() -> None:
    module = IRModule(
        [
            IRFunction(
                "nothing",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_verifies_return_ssa_value() -> None:
    parameter = IRParameter("value", IntType())
    module = IRModule(
        [
            IRFunction(
                "identity",
                [parameter],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(parameter)])],
            )
        ]
    )

    decoded = ir_module_from_json(ir_module_to_json(module))
    assert IRVerifier(decoded).verify() is decoded


def test_verifies_return_constant_result() -> None:
    result = IRValue("result", IntType())
    module = IRModule(
        [
            IRFunction(
                "constant",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(result, 1), IRReturn(result)])],
            )
        ]
    )

    decoded = ir_module_from_json(ir_module_to_json(module))
    assert IRVerifier(decoded).verify() is decoded


def test_verifies_return_expression_result() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("result", IntType())
    module = IRModule(
        [
            IRFunction(
                "add",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "add", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    decoded = ir_module_from_json(ir_module_to_json(module))
    assert IRVerifier(decoded).verify() is decoded


def test_return_storage_is_irv026_even_with_colliding_ssa_name() -> None:
    parameter = IRParameter("x", IntType())
    storage = IRStorage("x", IntType())
    module = IRModule(
        [
            IRFunction(
                "collision",
                [parameter],
                IntType(),
                [IRBasicBlock("entry", [IRInitDefault(storage), IRReturn(storage)])],
            )
        ]
    )

    decoded = ir_module_from_json(ir_module_to_json(module))
    with pytest.raises(IRVerificationError, match="is storage") as raised:
        IRVerifier(decoded).verify()

    assert raised.value.normalized_failure is not None
    assert raised.value.normalized_failure.invariant_id == "IRV-026"


def test_return_storage_is_irv026() -> None:
    storage = IRStorage("slot", IntType())
    module = IRModule(
        [
            IRFunction(
                "storage_return",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRInitDefault(storage), IRReturn(storage)])],
            )
        ]
    )

    decoded = ir_module_from_json(ir_module_to_json(module))
    with pytest.raises(IRVerificationError, match="is storage") as raised:
        IRVerifier(decoded).verify()

    assert raised.value.normalized_failure is not None
    assert raised.value.normalized_failure.invariant_id == "IRV-026"


def test_verifies_module_with_multiple_functions() -> None:
    int_type = IntType()
    left = IRParameter("left", int_type)
    right = IRParameter("right", int_type)
    result = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "add",
                [left, right],
                int_type,
                [IRBasicBlock("entry", [IRBinaryOp(result, "add", left, right), IRReturn(result)])],
            ),
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn()])],
            ),
        ]
    )

    assert IRVerifier(module).verify() is module


def test_verifies_int_to_double_cast() -> None:
    parameter = IRParameter("value", IntType())
    result = IRValue("0", DoubleType())
    module = IRModule(
        [
            IRFunction(
                "widen",
                [parameter],
                DoubleType(),
                [IRBasicBlock("entry", [IRCast(result, parameter), IRReturn(result)])],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_verifies_identity_cast_and_integer_power() -> None:
    int_type = IntType()
    base = IRParameter("base", int_type)
    exponent = IRParameter("exponent", int_type)
    identity = IRValue("identity", int_type)
    result = IRValue("result", int_type)
    module = IRModule(
        [
            IRFunction(
                "power",
                [base, exponent],
                int_type,
                [
                    IRBasicBlock(
                        "entry",
                        [IRCast(identity, base), IRBinaryOp(result, "pow", identity, exponent), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_unsupported_cast_error() -> None:
    parameter = IRParameter("value", BoolType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "bad",
                [parameter],
                IntType(),
                [IRBasicBlock("entry", [IRCast(result, parameter), IRReturn(result)])],
            )
        ]
    )

    _assert_verification_error(module, "Cast requires int/double operands, got bool to int")


def test_duplicate_function_error() -> None:
    module = IRModule(
        [
            IRFunction("add", [], VoidType(), [IRBasicBlock("entry", [IRReturn()])]),
            IRFunction("add", [], VoidType(), [IRBasicBlock("entry", [IRReturn()])]),
        ]
    )

    _assert_verification_error(module, "Duplicate function 'add'")


def test_missing_entry_block_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [IRBasicBlock("body", [IRReturn()])],
            )
        ]
    )

    _assert_verification_error(module, "Function 'main' has no entry block")


def test_duplicate_parameter_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "identity",
                [IRParameter("value", IntType()), IRParameter("value", IntType())],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(IRValue("value", IntType()))])],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Duplicate parameter 'value' in function 'identity'",
    )


def test_duplicate_block_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRReturn()]),
                    IRBasicBlock("entry", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Duplicate block 'entry' in function 'main'")


def test_instruction_after_return_error() -> None:
    value = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRReturn(), IRConst(value, 1)])],
            )
        ]
    )

    _assert_verification_error(module, "Instruction after terminator in block 'entry'")


def test_undefined_value_error() -> None:
    missing = IRValue("3", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(missing)])],
            )
        ]
    )

    _assert_verification_error(module, "Undefined value '%3'")


def test_undefined_slot_error() -> None:
    slot = IRValue("x", IntType())
    loaded = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "read",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRLoad(loaded, slot), IRReturn(loaded)])],
            )
        ]
    )

    _assert_verification_error(module, "Undefined slot '%x'")


def test_load_before_store_error() -> None:
    slot = IRValue("x", IntType())
    loaded = IRValue("0", IntType())
    value = IRValue("1", IntType())
    module = IRModule(
        [
            IRFunction(
                "read",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(value, 1),
                            IRLoad(loaded, slot),
                            IRStore(slot, value),
                            IRReturn(loaded),
                        ],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "Slot '%x' loaded before store")


def test_call_to_missing_function_error() -> None:
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRCall("missing", (), result), IRReturn(result)])],
            )
        ]
    )

    _assert_verification_error(module, "Call to undefined function 'missing'")


def test_call_wrong_arity_error() -> None:
    parameter = IRParameter("value", IntType())
    call_result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "add",
                [IRParameter("left", IntType()), IRParameter("right", IntType())],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRBinaryOp(
                                IRValue("0", IntType()),
                                "add",
                                IRValue("left", IntType()),
                                IRValue("right", IntType()),
                            ),
                            IRReturn(IRValue("0", IntType())),
                        ],
                    )
                ],
            ),
            IRFunction(
                "main",
                [parameter],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCall("add", (parameter,), call_result), IRReturn(call_result)],
                    )
                ],
            ),
        ]
    )

    _assert_verification_error(module, "Function 'add' expects 2 arguments, got 1")


def test_call_wrong_argument_type_error() -> None:
    argument = IRParameter("value", StringType())
    call_result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "id",
                [IRParameter("value", IntType())],
                IntType(),
                [IRBasicBlock("entry", [IRReturn(IRValue("value", IntType()))])],
            ),
            IRFunction(
                "main",
                [argument],
                IntType(),
                [IRBasicBlock("entry", [IRCall("id", (argument,), call_result), IRReturn(call_result)])],
            ),
        ]
    )

    _assert_verification_error(
        module,
        "Argument 1 to function 'id' type mismatch: expected int, got string",
    )


def _builtin_call_module(
    function: str,
    builtin: str,
    argument_types: tuple[IRType, ...],
    result_type: IRType | None,
    *,
    structs: tuple[IRStructDefinition, ...] = (),
) -> IRModule:
    parameters = [IRParameter(f"argument{index}", type_) for index, type_ in enumerate(argument_types)]
    result = IRValue("result", result_type) if result_type is not None else None
    return IRModule(
        [
            IRFunction(
                "main",
                parameters,
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCall(function, tuple(parameters), result, builtin), IRReturn()],
                    )
                ],
            )
        ],
        list(structs),
    )


def test_builtin_identity_accepts_the_canonical_semantic_name() -> None:
    module = _builtin_call_module("sin", "sin", (DoubleType(),), DoubleType())

    assert IRVerifier(module).verify() is module


@pytest.mark.parametrize("function", ["cos", "user_sin", "sin_alias", "renamed_sin"])
def test_builtin_identity_rejects_compatible_wrong_alias_and_renamed_functions(function: str) -> None:
    module = _builtin_call_module(function, "sin", (DoubleType(),), DoubleType())

    _assert_verification_error(module, "Scalar builtin call must retain its canonical semantic name")


def test_builtin_identity_rejects_a_user_function_with_the_same_signature() -> None:
    module = _builtin_call_module("user_sin", "sin", (DoubleType(),), DoubleType())
    parameter = IRParameter("number", DoubleType())
    module.functions.insert(
        0,
        IRFunction(
            "user_sin",
            [parameter],
            DoubleType(),
            [IRBasicBlock("entry", [IRReturn(parameter)])],
        ),
    )

    _assert_verification_error(module, "Scalar builtin call must retain its canonical semantic name")


def test_builtin_identity_is_name_based_even_with_a_same_named_user_declaration() -> None:
    module = _builtin_call_module("sin", "sin", (DoubleType(),), DoubleType())
    parameter = IRParameter("number", DoubleType())
    module.functions.insert(
        0,
        IRFunction(
            "sin",
            [parameter],
            DoubleType(),
            [IRBasicBlock("entry", [IRReturn(parameter)])],
        ),
    )

    assert IRVerifier(module).verify() is module


def test_renamed_builtin_tag_is_not_treated_as_an_alias() -> None:
    module = _builtin_call_module("renamed_sin", "renamed_sin", (DoubleType(),), DoubleType())

    _assert_verification_error(module, "unknown scalar math builtin 'renamed_sin'")


@pytest.mark.parametrize("builtin", ["__aether_retain", "__aether_release"])
def test_lifecycle_builtins_accept_the_exact_managed_type_allowlist(builtin: str) -> None:
    definition = IRStructDefinition("Managed", (("number", IntType()),))
    managed_types = (
        StringType(),
        StructType("Managed"),
        MethodResultType(StructType("Managed"), IntType()),
        ArrayType(IntType()),
        ListType(BoolType()),
        NullableType(StringType()),
    )

    for managed_type in managed_types:
        module = _builtin_call_module(
            builtin,
            builtin,
            (managed_type,),
            None,
            structs=(definition,),
        )
        assert IRVerifier(module).verify() is module


@pytest.mark.parametrize(
    "builtin, argument_type",
    [
        ("__aether_retain", IntType()),
        ("__aether_retain", EnumType("State", ("ready",))),
        ("__aether_release", BoolType()),
        ("__aether_release", VectorType(IntType(), "row")),
        ("__aether_release", MatrixType(DoubleType())),
    ],
)
def test_lifecycle_builtins_reject_types_outside_the_managed_allowlist(
    builtin: str,
    argument_type: IRType,
) -> None:
    module = _builtin_call_module(builtin, builtin, (argument_type,), None)

    _assert_verification_error(module, f"Lifecycle builtin does not support argument type {argument_type}")


@pytest.mark.parametrize("builtin", ["__aether_retain", "__aether_release"])
def test_lifecycle_builtins_require_one_argument_and_no_result(builtin: str) -> None:
    wrong_count = _builtin_call_module(builtin, builtin, (), None)
    unexpected_result = _builtin_call_module(builtin, builtin, (StringType(),), StringType())

    _assert_verification_error(wrong_count, "Lifecycle builtin requires one argument and no result")
    _assert_verification_error(unexpected_result, "Lifecycle builtin requires one argument and no result")


@pytest.mark.parametrize("builtin", ["__aether_retain", "__aether_release"])
def test_lifecycle_builtins_require_their_canonical_function_name(builtin: str) -> None:
    module = _builtin_call_module("lifecycle_alias", builtin, (StringType(),), None)

    _assert_verification_error(module, "Lifecycle builtin call must retain its canonical semantic name")


def test_return_type_mismatch_error() -> None:
    value = IRValue("0", StringType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(value, "oops"), IRReturn(value)])],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Return type mismatch: expected int, got string",
    )


def test_binary_op_incompatible_operand_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", StringType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "add", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Binary op 'add' requires compatible operands, got int and string",
    )


def test_compare_op_int_less_than_string_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", StringType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' requires int or double operands, got int and string",
    )


def test_compare_op_bool_less_than_bool_error() -> None:
    left = IRParameter("left", BoolType())
    right = IRParameter("right", BoolType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' requires int or double operands, got bool and bool",
    )


def test_compare_op_string_less_than_string_error() -> None:
    left = IRParameter("left", StringType())
    right = IRParameter("right", StringType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' requires int or double operands, got string and string",
    )


def test_compare_op_result_type_must_be_bool_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "lt", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Compare op 'lt' result type mismatch: expected bool, got int",
    )


def test_compare_op_unknown_operator_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRCompareOp(result, "unknown", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(module, "Unsupported compare operator 'unknown'")


def test_branch_condition_must_be_bool_error() -> None:
    condition = IRParameter("condition", IntType())
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "else")]),
                    IRBasicBlock("then", [IRReturn()]),
                    IRBasicBlock("else", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Branch condition must be bool")


def test_loop_branch_condition_must_be_bool_error() -> None:
    condition = IRParameter("condition", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", [IRJump("cond0")]),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Branch condition must be bool")


def test_jump_target_must_exist_error() -> None:
    module = IRModule(
        [
            IRFunction(
                "loop",
                [],
                VoidType(),
                [IRBasicBlock("entry", [IRJump("missing")])],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Unknown jump target 'missing' in function 'loop'",
    )


def test_branch_target_must_exist_error() -> None:
    condition = IRParameter("condition", BoolType())
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "missing")]),
                    IRBasicBlock("then", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Unknown branch target 'missing' in function 'choose'",
    )


def test_loop_branch_target_must_exist_error() -> None:
    condition = IRParameter("condition", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "missing")]),
                    IRBasicBlock("body0", [IRJump("cond0")]),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Unknown branch target 'missing' in function 'broken'",
    )


def test_load_after_merge_requires_store_on_all_incoming_paths() -> None:
    condition = IRParameter("condition", BoolType())
    slot = IRValue("y", IntType())
    one = IRValue("0", IntType())
    loaded = IRValue("1", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "merge")]),
                    IRBasicBlock(
                        "then",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("merge")],
                    ),
                    IRBasicBlock("merge", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Slot '%y' loaded before store")


def test_load_after_loop_requires_store_before_loop() -> None:
    condition = IRParameter("condition", BoolType())
    slot = IRValue("x", IntType())
    one = IRValue("0", IntType())
    loaded = IRValue("1", IntType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock(
                        "body0",
                        [IRConst(one, 1), IRStore(slot, one), IRJump("cond0")],
                    ),
                    IRBasicBlock("exit0", [IRLoad(loaded, slot), IRReturn(loaded)]),
                ],
            )
        ]
    )

    _assert_verification_error(module, "Slot '%x' loaded before store")


def test_loop_body_must_have_terminator_error() -> None:
    condition = IRParameter("condition", BoolType())
    module = IRModule(
        [
            IRFunction(
                "broken",
                [condition],
                VoidType(),
                [
                    IRBasicBlock("entry", [IRJump("cond0")]),
                    IRBasicBlock("cond0", [IRBranch(condition, "body0", "exit0")]),
                    IRBasicBlock("body0", []),
                    IRBasicBlock("exit0", [IRReturn()]),
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Block 'body0' in function 'broken' has no terminator",
    )


def test_non_void_function_accepts_infinite_cycle_with_valued_exit() -> None:
    condition = IRParameter("condition", BoolType())
    value = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                IntType(),
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "else")]),
                    IRBasicBlock("then", [IRConst(value, 1), IRReturn(value)]),
                    IRBasicBlock("else", [IRJump("entry")]),
                ],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_division_result_type_must_match_error() -> None:
    left = IRParameter("left", IntType())
    right = IRParameter("right", IntType())
    result = IRValue("0", IntType())
    module = IRModule(
        [
            IRFunction(
                "divide",
                [left, right],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRBinaryOp(result, "div", left, right), IRReturn(result)],
                    )
                ],
            )
        ]
    )

    _assert_verification_error(
        module,
        "Binary op 'div' result type mismatch: expected double, got int",
    )


def test_call_result_type_must_match_error() -> None:
    result = IRValue("0", DoubleType())
    module = IRModule(
        [
            IRFunction(
                "answer",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(IRValue("0", IntType()), 1), IRReturn(IRValue("0", IntType()))])],
            ),
            IRFunction(
                "main",
                [],
                DoubleType(),
                [IRBasicBlock("entry", [IRCall("answer", (), result), IRReturn(result)])],
            ),
        ]
    )

    _assert_verification_error(
        module,
        "Call result type mismatch: expected int, got double",
    )
