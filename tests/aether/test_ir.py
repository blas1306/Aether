from __future__ import annotations

from aether.ir import (
    ArrayType,
    BoolType,
    ClassRefType,
    ComplexType,
    DoubleType,
    EnumType,
    FloatType,
    InterfaceType,
    IntType,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
    ListType,
    MatrixType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
    print_ir,
)


def test_ir_type_text_representation() -> None:
    int_type = IntType()

    assert str(int_type) == "int"
    assert str(FloatType()) == "float"
    assert str(DoubleType()) == "double"
    assert str(BoolType()) == "bool"
    assert str(StringType()) == "string"
    assert str(VoidType()) == "void"
    assert str(ComplexType()) == "complex"
    assert str(NullableType(int_type)) == "nullable<int>"
    assert str(ListType(int_type)) == "list<int>"
    assert str(ArrayType(int_type)) == "array<int>"
    assert str(VectorType(DoubleType())) == "vector<double>"
    assert str(MatrixType(DoubleType())) == "matrix<double>"
    assert str(StructType("Point")) == "struct Point"
    assert str(ClassRefType("Counter")) == "class Counter"
    assert str(InterfaceType("Shape")) == "interface Shape"
    assert str(EnumType("Status")) == "enum Status"


def test_create_simple_add_function() -> None:
    int_type = IntType()
    left = IRParameter("a", int_type)
    right = IRParameter("b", int_type)
    result = IRValue("0", int_type)
    function = IRFunction(
        name="add",
        parameters=[left, right],
        return_type=int_type,
        blocks=[
            IRBasicBlock(
                "entry",
                [
                    IRBinaryOp(result, "add", left, right),
                    IRReturn(result),
                ],
            )
        ],
    )

    assert function.name == "add"
    assert function.parameters == [left, right]
    assert function.blocks[0].instructions[0] == IRBinaryOp(result, "add", left, right)


def test_pretty_print_function_with_return() -> None:
    int_type = IntType()
    result = IRValue("0", int_type)
    module = IRModule(
        [
            IRFunction(
                "answer",
                [],
                int_type,
                [IRBasicBlock("entry", [IRConst(result, 42), IRReturn(result)])],
            )
        ]
    )

    assert print_ir(module) == (
        "func @answer() -> int {\n"
        "entry:\n"
        "    %0: int = const 42\n"
        "    return %0\n"
        "}"
    )


def test_pretty_print_simple_if_branch() -> None:
    bool_type = BoolType()
    condition = IRParameter("condition", bool_type)
    module = IRModule(
        [
            IRFunction(
                "choose",
                [condition],
                bool_type,
                [
                    IRBasicBlock("entry", [IRBranch(condition, "then", "else")]),
                    IRBasicBlock("then", [IRReturn(condition)]),
                    IRBasicBlock("else", [IRReturn(condition)]),
                ],
            )
        ]
    )

    assert print_ir(module) == (
        "func @choose(%condition: bool) -> bool {\n"
        "entry:\n"
        "    branch %condition, then, else\n"
        "\n"
        "then:\n"
        "    return %condition\n"
        "\n"
        "else:\n"
        "    return %condition\n"
        "}"
    )


def test_pretty_print_while_with_mutable_slot_and_jump() -> None:
    int_type = IntType()
    bool_type = BoolType()
    counter = IRValue("counter", int_type)
    zero = IRValue("0", int_type)
    current = IRValue("1", int_type)
    condition = IRValue("2", bool_type)
    module = IRModule(
        [
            IRFunction(
                "loop",
                [],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(zero, 0),
                            IRStore(counter, zero),
                            IRJump("loop.condition"),
                        ],
                    ),
                    IRBasicBlock(
                        "loop.condition",
                        [
                            IRLoad(current, counter),
                            IRBinaryOp(condition, "lt", current, zero),
                            IRBranch(condition, "loop.body", "loop.exit"),
                        ],
                    ),
                    IRBasicBlock("loop.body", [IRJump("loop.condition")]),
                    IRBasicBlock("loop.exit", [IRReturn()]),
                ],
            )
        ]
    )

    assert print_ir(module) == (
        "func @loop() -> void {\n"
        "entry:\n"
        "    %0: int = const 0\n"
        "    store %counter, %0\n"
        "    jump loop.condition\n"
        "\n"
        "loop.condition:\n"
        "    %1: int = load %counter\n"
        "    %2: bool = lt %1, %0\n"
        "    branch %2, loop.body, loop.exit\n"
        "\n"
        "loop.body:\n"
        "    jump loop.condition\n"
        "\n"
        "loop.exit:\n"
        "    return\n"
        "}"
    )


def test_pretty_print_module_with_multiple_functions() -> None:
    void_type = VoidType()
    module = IRModule(
        [
            IRFunction("first", [], void_type, [IRBasicBlock("entry", [IRReturn()])]),
            IRFunction("second", [], void_type, [IRBasicBlock("entry", [IRReturn()])]),
        ]
    )

    assert print_ir(module) == (
        "func @first() -> void {\n"
        "entry:\n"
        "    return\n"
        "}\n"
        "\n"
        "func @second() -> void {\n"
        "entry:\n"
        "    return\n"
        "}"
    )
