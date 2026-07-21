//! Focused coverage for schema-v1 wire type import.

use aether_ir::wire::{IRTypeDTO, NullableDTO};
use aether_ir::{
    ArrayType, BoolType, ClassRefType, ComplexType, DoubleType, EnumType, FloatType, FunctionType,
    IRImportError, IRType, IntType, InterfaceType, ListType, MatrixType, MethodResultType,
    NullableType, StringType, StructType, VectorType, VoidType, import_type,
};
use serde_json::json;

fn boxed(type_: IRTypeDTO) -> Box<IRTypeDTO> {
    Box::new(type_)
}

#[test]
#[allow(clippy::too_many_lines)]
fn imports_every_wire_type_variant() {
    let cases = vec![
        (IRTypeDTO::Int {}, IRType::from(IntType)),
        (IRTypeDTO::Float {}, IRType::from(FloatType)),
        (IRTypeDTO::Double {}, IRType::from(DoubleType)),
        (IRTypeDTO::Bool {}, IRType::from(BoolType)),
        (IRTypeDTO::String {}, IRType::from(StringType)),
        (IRTypeDTO::Void {}, IRType::from(VoidType)),
        (
            IRTypeDTO::Function {
                parameter_types: vec![IRTypeDTO::Int {}, IRTypeDTO::Bool {}],
                return_type: boxed(IRTypeDTO::String {}),
            },
            IRType::from(FunctionType {
                parameter_types: vec![IntType.into(), BoolType.into()],
                return_type: Box::new(StringType.into()),
            }),
        ),
        (IRTypeDTO::Complex {}, IRType::from(ComplexType)),
        (
            IRTypeDTO::Nullable {
                inner: boxed(IRTypeDTO::Int {}),
            },
            IRType::from(NullableType {
                inner: Box::new(IntType.into()),
            }),
        ),
        (
            IRTypeDTO::List {
                element: boxed(IRTypeDTO::String {}),
            },
            IRType::from(ListType {
                element: Box::new(StringType.into()),
            }),
        ),
        (
            IRTypeDTO::Array {
                element: boxed(IRTypeDTO::Bool {}),
            },
            IRType::from(ArrayType {
                element: Box::new(BoolType.into()),
            }),
        ),
        (
            IRTypeDTO::Vector {
                element: boxed(IRTypeDTO::Double {}),
                orientation: NullableDTO(Some("column".to_owned())),
            },
            IRType::from(VectorType {
                element: Box::new(DoubleType.into()),
                orientation: Some("column".to_owned()),
            }),
        ),
        (
            IRTypeDTO::Matrix {
                element: boxed(IRTypeDTO::Float {}),
            },
            IRType::from(MatrixType {
                element: Box::new(FloatType.into()),
            }),
        ),
        (
            IRTypeDTO::Struct {
                name: "Point".to_owned(),
            },
            IRType::from(StructType {
                name: "Point".to_owned(),
            }),
        ),
        (
            IRTypeDTO::MethodResult {
                receiver: boxed(IRTypeDTO::Struct {
                    name: "Counter".to_owned(),
                }),
                value: boxed(IRTypeDTO::Int {}),
            },
            IRType::from(MethodResultType {
                receiver: StructType {
                    name: "Counter".to_owned(),
                },
                value: Box::new(IntType.into()),
            }),
        ),
        (
            IRTypeDTO::ClassRef {
                name: "Widget".to_owned(),
            },
            IRType::from(ClassRefType {
                name: "Widget".to_owned(),
            }),
        ),
        (
            IRTypeDTO::Interface {
                name: "Drawable".to_owned(),
            },
            IRType::from(InterfaceType {
                name: "Drawable".to_owned(),
            }),
        ),
        (
            IRTypeDTO::Enum {
                name: "Color".to_owned(),
                variants: vec!["red".to_owned(), "green".to_owned()],
                display_name: NullableDTO(Some("Colour".to_owned())),
            },
            IRType::from(EnumType {
                name: "Color".to_owned(),
                variants: vec!["red".to_owned(), "green".to_owned()],
                display_name: Some("Colour".to_owned()),
            }),
        ),
    ];

    assert_eq!(cases.len(), 18);
    for (wire, expected) in cases {
        assert_eq!(import_type(&wire), Ok(expected.clone()));
        assert_eq!(IRType::try_from(&wire), Ok(expected.clone()));
        assert_eq!(IRType::try_from(wire), Ok(expected));
    }
}

#[test]
fn recursively_allocates_deeply_nested_types() {
    let wire = IRTypeDTO::Function {
        parameter_types: vec![
            IRTypeDTO::Nullable {
                inner: boxed(IRTypeDTO::List {
                    element: boxed(IRTypeDTO::Array {
                        element: boxed(IRTypeDTO::Struct {
                            name: "Node".to_owned(),
                        }),
                    }),
                }),
            },
            IRTypeDTO::MethodResult {
                receiver: boxed(IRTypeDTO::Struct {
                    name: "Accumulator".to_owned(),
                }),
                value: boxed(IRTypeDTO::Matrix {
                    element: boxed(IRTypeDTO::Complex {}),
                }),
            },
        ],
        return_type: boxed(IRTypeDTO::Vector {
            element: boxed(IRTypeDTO::Function {
                parameter_types: vec![IRTypeDTO::Interface {
                    name: "Comparable".to_owned(),
                }],
                return_type: boxed(IRTypeDTO::ClassRef {
                    name: "Result".to_owned(),
                }),
            }),
            orientation: NullableDTO(None),
        }),
    };

    let imported = import_type(&wire).expect("nested type must import");
    let IRType::Function(function) = imported else {
        panic!("expected a function type");
    };
    assert_eq!(function.parameter_types.len(), 2);
    assert_eq!(
        function.parameter_types[0].to_string(),
        "nullable<list<array<struct Node>>>"
    );
    assert_eq!(
        function.parameter_types[1].to_string(),
        "method_result<Accumulator, matrix<complex>>"
    );
    assert_eq!(
        function.return_type.to_string(),
        "vector<class Result(interface Comparable)>"
    );
}

#[test]
fn imports_identically_after_a_wire_serialization_round_trip() {
    let wire = IRTypeDTO::Function {
        parameter_types: vec![IRTypeDTO::Vector {
            element: boxed(IRTypeDTO::Double {}),
            orientation: NullableDTO(Some("row".to_owned())),
        }],
        return_type: boxed(IRTypeDTO::Enum {
            name: "Token".to_owned(),
            variants: vec!["word".to_owned(), "number".to_owned()],
            display_name: NullableDTO(None),
        }),
    };

    let encoded = serde_json::to_string(&wire).expect("wire type must serialize");
    let decoded: IRTypeDTO =
        serde_json::from_str(&encoded).expect("wire type must deserialize after serialization");

    assert_eq!(decoded, wire);
    assert_eq!(import_type(&decoded), import_type(&wire));
    assert_eq!(
        serde_json::to_string(&decoded).expect("decoded wire type must serialize"),
        encoded
    );
}

#[test]
fn rejects_a_non_struct_method_result_receiver_with_a_dedicated_error() {
    let wire: IRTypeDTO = serde_json::from_value(json!({
        "tag": "method_result",
        "receiver": {"tag": "int"},
        "value": {"tag": "void"}
    }))
    .expect("the malformed combination is structurally valid wire data");

    let error = import_type(&wire).expect_err("owned IR cannot represent this receiver");
    assert_eq!(
        error,
        IRImportError::MethodResultReceiverNotStruct { actual: "int" }
    );
    assert_eq!(
        error.to_string(),
        "method-result receiver must be a struct type, found wire type 'int'"
    );
}

#[test]
fn propagates_structural_errors_from_nested_types() {
    let wire = IRTypeDTO::Array {
        element: boxed(IRTypeDTO::Function {
            parameter_types: vec![IRTypeDTO::MethodResult {
                receiver: boxed(IRTypeDTO::List {
                    element: boxed(IRTypeDTO::Int {}),
                }),
                value: boxed(IRTypeDTO::Bool {}),
            }],
            return_type: boxed(IRTypeDTO::Void {}),
        }),
    };

    assert_eq!(
        import_type(&wire),
        Err(IRImportError::MethodResultReceiverNotStruct { actual: "list" })
    );
}

#[test]
fn preserves_order_optional_fields_and_unverified_semantics_deterministically() {
    let wire = IRTypeDTO::Function {
        parameter_types: vec![
            IRTypeDTO::Enum {
                name: String::new(),
                variants: vec!["same".to_owned(), "same".to_owned(), String::new()],
                display_name: NullableDTO(Some(String::new())),
            },
            IRTypeDTO::Vector {
                element: boxed(IRTypeDTO::Void {}),
                orientation: NullableDTO(Some("diagonal".to_owned())),
            },
        ],
        return_type: boxed(IRTypeDTO::Struct {
            name: String::new(),
        }),
    };

    let first = import_type(&wire).expect("semantic checks belong to the verifier");
    let second = import_type(&wire).expect("repeated import must succeed");
    let owned = IRType::try_from(wire).expect("owned conversion must match borrowed conversion");

    assert_eq!(first, second);
    assert_eq!(second, owned);
    let IRType::Function(function) = first else {
        panic!("expected a function type");
    };
    let IRType::Enum(enum_type) = &function.parameter_types[0] else {
        panic!("expected enum parameter");
    };
    assert_eq!(enum_type.variants, ["same", "same", ""]);
    assert_eq!(enum_type.display_name.as_deref(), Some(""));
}
